#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID app-registration API routes: /api/v1/auth/entra*/.

App creation (device-code sign-in → register app + secret + consent) is served by
the shared generic provisioner:

POST /api/v1/auth/entraid/provision/device-code — start; POST …/device-poll — poll.

The SSO OIDC "Register in Azure" button and every module credential reuse it (the
OIDC app is just a provisioning profile: redirect URI + groups claim +
require-assignment + its permissions). SAML2 keeps its own routes below, and this
module also exposes the Graph "fetch groups" helpers used by the OIDC config.
"""

import secrets
import time

from flask import jsonify

from lib.config.spec import normalize_url
from lib.providers.entraid import auth, directory, provisioning


def _public_base(wa) -> str:
    """The server's public base URL (scheme + host, no trailing slash) — used to
    expand a ``{public_url}`` token in a profile's redirect URIs."""
    base = normalize_url(getattr(wa, '_public_url', '') or '')
    if not base:
        return f'http://localhost:{getattr(wa, "_WEB_PORT", 80)}'
    if '://' not in base:
        base = f'https://{base}'
    return base.rstrip('/')


def _saml_acs_uri(wa) -> str:
    cfg = wa._config_section('saml2')
    acs = cfg.get('sp_acs_url', '').strip()
    if acs:
        return acs
    base = normalize_url(getattr(wa, '_public_url', ''))
    if not base:
        return f'http://localhost:{wa._WEB_PORT}/auth/saml2/acs'
    if '://' not in base:
        base = f'https://{base}'
    return f'{base}/auth/saml2/acs'


def _saml_entity_id(wa) -> str:
    cfg = wa._config_section('saml2')
    eid = cfg.get('sp_entity_id', '').strip()
    if eid:
        return eid
    base = normalize_url(getattr(wa, '_public_url', ''))
    if not base:
        return f'http://localhost:{wa._WEB_PORT}'
    if '://' not in base:
        base = f'https://{base}'
    return base


def register(app, wa):
    if not hasattr(wa, '_entra_flows'):
        wa._entra_flows = {}

    config_edit_req = wa._perm_required('config_edit')

    def _entra_section_creds(data):
        """Graph client-credentials for the group→role mapping, from the named auth
        section (``oidc`` or ``saml2``).  SAML2's app (registered by the wizard) has
        its own client secret in ``graph_secret``; OIDC uses its normal client creds.
        Request-body values override the stored ones (used right after the wizard,
        before the masked secret is reloaded)."""
        sec = (data.get('sec') or 'oidc').strip()
        cfg = wa._config_section(sec if sec in ('oidc', 'saml2') else 'oidc')
        if sec == 'saml2':
            # SAML2 uses ITS OWN app credentials (the wizard registers a graph_secret
            # on the SAML2 app, which has Group.Read.All).  Never borrow OIDC's.
            cid, csec, purl = (cfg.get('sp_app_id', ''), cfg.get('graph_secret', ''),
                               cfg.get('idp_sso_url', ''))
        else:
            cid, csec, purl = (cfg.get('client_id', ''), cfg.get('client_secret', ''),
                               cfg.get('provider_url', ''))
        # Body override only when it carries a FULL id+secret pair (used right after
        # the wizard, before the masked secret reloads).  A lone client_id must never
        # override — it would mismatch a fallback secret.
        if data.get('client_id') and data.get('client_secret'):
            cid  = str(data.get('client_id')).strip()
            csec = str(data.get('client_secret')).strip()
        if data.get('provider_url'):
            purl = str(data.get('provider_url')).strip()
        return (cid or '').strip(), (csec or '').strip(), (purl or '').strip()

    @app.route('/api/v1/auth/entra/groups', methods=['POST'])
    @config_edit_req
    def api_entra_groups():
        """Fetch all directory groups via Graph, using the OIDC/SAML2 app credentials."""
        from flask import request, session
        data = wa._optional_json()
        client_id, client_secret, provider_url = _entra_section_creds(data)

        tenant = auth.tenant_from_provider_url(provider_url)
        if not tenant:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_not_entra')}), 200
        if not client_id or not client_secret:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_missing_creds')}), 200
        try:
            token = auth.app_token(tenant, client_id, client_secret)
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'ok': False, 'message': str(exc)}), 200
        try:
            groups = directory.fetch_groups(token)
        except Exception as exc:  # pylint: disable=broad-except
            wa._audit('entra_groups', session.get('username', ''), request.remote_addr,
                      detail={'ok': False, 'error': str(exc)})
            return jsonify({'ok': False, 'message': str(exc)}), 200
        wa._audit('entra_groups', session.get('username', ''), request.remote_addr,
                  detail={'count': len(groups)})
        return jsonify({'ok': True, 'groups': groups})

    @app.route('/api/v1/auth/entra/group_lookup', methods=['POST'])
    @config_edit_req
    def api_entra_group_lookup():
        """Look up a single group by ID via Graph."""
        data = wa._optional_json()
        group_id = (data.get('group_id') or '').strip()
        client_id, client_secret, provider_url = _entra_section_creds(data)

        if not group_id:
            return jsonify({'ok': False, 'message': 'group_id required'}), 200
        tenant = auth.tenant_from_provider_url(provider_url)
        if not tenant:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_not_entra')}), 200
        if not client_id or not client_secret:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_missing_creds')}), 200
        try:
            token = auth.app_token(tenant, client_id, client_secret)
            name = directory.lookup_group(token, group_id)
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'ok': False, 'message': str(exc)}), 200
        if name is None:
            return jsonify({'ok': True, 'found': False, 'name': None})
        return jsonify({'ok': True, 'found': True, 'name': name})

    @app.route('/api/v1/auth/entra/saml2/device-code', methods=['POST'])
    @config_edit_req
    def api_entra_saml2_device_code():
        req_body = wa._optional_json() or {}
        app_name = (req_body.get('app_name') or provisioning.SAML2_APP_NAME).strip() or provisioning.SAML2_APP_NAME
        try:
            d = auth.device_code_start()
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'error': str(exc) or wa._t('entra_device_code_error')}), 502

        flow_token = secrets.token_urlsafe(16)
        wa._entra_flows[flow_token] = {
            'device_code': d['device_code'],
            'expires_at':  time.time() + int(d.get('expires_in', 900)),
            'interval':    int(d.get('interval', 5)),
            'kind':        'saml2',
            'app_name':    app_name,
        }
        return jsonify({
            'flow_token':       flow_token,
            'user_code':        d['user_code'],
            'verification_uri': d['verification_uri'],
            'expires_in':       d.get('expires_in', 900),
            'interval':         d.get('interval', 5),
            'acs_url':          _saml_acs_uri(wa),
            'entity_id':        _saml_entity_id(wa),
        })

    @app.route('/api/v1/auth/entra/saml2/secret/device-code', methods=['POST'])
    @config_edit_req
    def api_entra_saml2_secret_device_code():
        """Start a device-code flow to add a Graph client secret to the EXISTING SAML2
        app (for the group→role mapping), without recreating it."""
        app_id = wa._config_section('saml2').get('sp_app_id', '').strip()
        if not app_id:
            return jsonify({'error': wa._t('entra_saml2_groups_no_app')}), 400
        try:
            d = auth.device_code_start()
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'error': str(exc) or wa._t('entra_device_code_error')}), 502
        flow_token = secrets.token_urlsafe(16)
        wa._entra_flows[flow_token] = {
            'device_code': d['device_code'],
            'expires_at':  time.time() + int(d.get('expires_in', 900)),
            'interval':    int(d.get('interval', 5)),
            'kind':        'saml2_secret',
            'app_id':      app_id,
        }
        return jsonify({
            'flow_token':       flow_token,
            'user_code':        d['user_code'],
            'verification_uri': d['verification_uri'],
            'verification_uri_complete': d.get('verification_uri_complete'),
            'expires_in':       d.get('expires_in', 900),
            'interval':         d.get('interval', 5),
        })

    @app.route('/api/v1/auth/entra/saml2/device-poll', methods=['POST'])
    @config_edit_req
    def api_entra_saml2_device_poll():
        data, err = wa._require_json()
        if err:
            return err
        flow_token = data.get('flow_token')
        flow = wa._entra_flows.get(flow_token)
        if not flow:
            return jsonify({'status': 'expired'})
        if time.time() > flow['expires_at']:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'expired'})

        body = auth.device_code_poll(flow['device_code'])
        error = body.get('error', '')

        if error == 'authorization_pending':
            return jsonify({'status': 'pending'})
        if error == 'slow_down':
            flow['interval'] = min(flow['interval'] + 5, 30)
            return jsonify({'status': 'pending', 'interval': flow['interval']})
        if error:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'error', 'message': body.get('error_description', error)})

        access_token = body['access_token']

        # Back-fill a Graph client secret on the EXISTING app (group→role mapping),
        # without recreating it.
        if flow.get('kind') == 'saml2_secret':
            wa._entra_flows.pop(flow_token, None)
            try:
                secret = provisioning.add_graph_secret(access_token, flow['app_id'])
            except Exception as exc:  # pylint: disable=broad-except
                return jsonify({'status': 'error', 'message': str(exc)})
            wa._audit('entra_saml2_graph_secret', detail={'app_id': flow['app_id']})
            return jsonify({'status': 'complete', 'graph_secret': secret})

        tenant_id = auth.extract_tenant_id(body)
        if not tenant_id:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'error',
                            'message': 'Could not determine tenant ID from token.'})

        try:
            result = provisioning.provision_saml2_app(
                access_token, _saml_acs_uri(wa), _saml_entity_id(wa), tenant_id,
                app_name=flow.get('app_name', provisioning.SAML2_APP_NAME))
        except Exception as exc:
            wa._entra_flows.pop(flow_token, None)
            wa._audit('entra_saml2_app_provision_failed', detail={
                'app_name': flow.get('app_name', ''), 'tenant_id': tenant_id,
                'error': str(exc),
            })
            return jsonify({'status': 'error', 'message': str(exc)})

        wa._entra_flows.pop(flow_token, None)
        wa._audit('entra_saml2_app_provisioned', detail={
            'app_name':  flow.get('app_name', ''),
            'tenant_id': tenant_id,
            'client_id': result.get('client_id', ''),
        })
        return jsonify({'status': 'complete', **result})

    # ── Generic module-credential app provisioning (device-code) ───────────
    # A module declares in its schema which Microsoft Graph *application*
    # permissions its monitoring app needs (__entraid_provision__); this reuses the
    # SAME device-code flow as the SSO wizard to create that app and return the
    # tenant/client/secret that fill the module's credential. Module-agnostic —
    # the core knows no module's permissions, it discovers them by profile.
    cred_edit_req = wa._perm_required('credentials_add', 'credentials_edit')

    def _provision_profile(profile):
        try:
            from lib.providers.entraid import module_entraid_provision  # noqa: PLC0415
            return module_entraid_provision(getattr(wa, '_modules_dir', None)).get(str(profile or ''))
        except Exception:  # pylint: disable=broad-except
            return None

    @app.route('/api/v1/auth/entraid/provision/device-code', methods=['POST'])
    @cred_edit_req
    def api_entraid_provision_device_code():
        body = wa._optional_json() or {}
        prof = _provision_profile(body.get('profile'))
        if not prof or not prof.get('resources'):
            # No module profile → build from an inline spec in the request, so
            # non-module callers (e.g. the SSO OIDC "Register in Azure" button)
            # reuse this generic flow. Same declaration vocabulary as a schema's
            # __entraid_provision__.
            from lib.providers.entraid import normalize_entraid_provision  # noqa: PLC0415
            _inline = normalize_entraid_provision(body)
            if _inline['resources']:
                prof = _inline
        if not prof or not prof.get('resources'):
            return jsonify({'error': wa._t('cred_prov_error')}), 400
        app_name = (body.get('app_name') or prof['app_name']).strip() or prof['app_name']
        try:
            d = auth.device_code_start()
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'error': str(exc) or wa._t('cred_prov_error')}), 502
        flow_token = secrets.token_urlsafe(16)
        _base = _public_base(wa)
        redirect_uris = [str(u).replace('{public_url}', _base)
                         for u in (prof.get('redirect_uris') or [])]
        wa._entra_flows[flow_token] = {
            'device_code': d['device_code'],
            'expires_at': time.time() + int(d.get('expires_in', 900)),
            'interval': int(d.get('interval', 5)),
            'app_name': app_name, 'resources': prof['resources'],
            'redirect_uris': redirect_uris,
            'group_claims': bool(prof.get('group_claims')),
            'require_assignment': bool(prof.get('require_assignment')),
            'kind': 'module',
        }
        return jsonify({'flow_token': flow_token, 'user_code': d['user_code'],
                        'verification_uri': d['verification_uri'],
                        # URL with the code already embedded (…/devicelogin?otc=CODE):
                        # opening it drops the admin straight into sign-in (their
                        # existing browser session) with nothing to type.
                        'verification_uri_complete': d.get('verification_uri_complete', ''),
                        'expires_in': d.get('expires_in', 900), 'interval': d.get('interval', 5)})

    @app.route('/api/v1/auth/entraid/provision/device-poll', methods=['POST'])
    @cred_edit_req
    def api_entraid_provision_device_poll():
        data, err = wa._require_json()
        if err:
            return err
        ftok = data.get('flow_token')
        flow = wa._entra_flows.get(ftok)
        if not flow or flow.get('kind') != 'module':
            return jsonify({'status': 'expired'})
        if time.time() > flow['expires_at']:
            wa._entra_flows.pop(ftok, None)
            return jsonify({'status': 'expired'})
        b = auth.device_code_poll(flow['device_code'])
        error = b.get('error', '')
        if error == 'authorization_pending':
            return jsonify({'status': 'pending'})
        if error == 'slow_down':
            flow['interval'] = min(flow['interval'] + 5, 30)
            return jsonify({'status': 'pending', 'interval': flow['interval']})
        if error:
            wa._entra_flows.pop(ftok, None)
            return jsonify({'status': 'error', 'message': b.get('error_description', error)})
        tenant_id = auth.extract_tenant_id(b)
        if not tenant_id:
            wa._entra_flows.pop(ftok, None)
            return jsonify({'status': 'error', 'message': 'No se pudo determinar el tenant.'})
        try:
            result = provisioning.provision_entra_app(
                b['access_token'], tenant_id, flow['resources'],
                app_name=flow.get('app_name', provisioning.DEFAULT_APP_NAME),
                redirect_uris=flow.get('redirect_uris'),
                group_claims=flow.get('group_claims', False),
                require_assignment=flow.get('require_assignment', False))
        except Exception as exc:  # pylint: disable=broad-except
            wa._entra_flows.pop(ftok, None)
            wa._audit('entra_app_provision_failed', detail={'tenant_id': tenant_id, 'error': str(exc)})
            return jsonify({'status': 'error', 'message': str(exc)})
        wa._entra_flows.pop(ftok, None)
        wa._audit('entra_app_provisioned', detail={
            'app_name': flow.get('app_name', ''), 'tenant_id': tenant_id,
            'client_id': result.get('client_id', '')})
        return jsonify({'status': 'complete', 'fields': result})
