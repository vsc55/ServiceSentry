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

Routes registered by this file:

    POST   /api/v1/auth/entraid/groups                    fetch all directory groups via Graph
    POST   /api/v1/auth/entraid/group_lookup              look up a single group by ID via Graph
    POST   /api/v1/auth/entraid/saml2/device-code         device-code: provision SAML2 app
    POST   /api/v1/auth/entraid/saml2/secret/device-code  device-code: add Graph secret to app
    POST   /api/v1/auth/entraid/saml2/device-poll         poll SAML2 app provisioning result
    POST   /api/v1/auth/entraid/scim/device-code          device-code: provision SCIM app
    POST   /api/v1/auth/entraid/scim/device-poll          poll SCIM app provisioning result
    POST   /api/v1/auth/entraid/provision/device-code   device-code: generic module app
    POST   /api/v1/auth/entraid/provision/device-poll   poll generic module app provisioning
"""

import secrets
import time

from flask import jsonify

from lib.providers.entraid import auth, directory, provisioning
from lib.providers.entraid.client import GRAPH_CLI_CLIENT_ID, SCIM_PROVISION_SCOPE


def _public_base(wa) -> str:
    """The server's public base URL (scheme + host, no trailing slash) — used to
    expand a ``{public_url}`` token in a profile's redirect URIs.  Single source:
    :meth:`WebAdmin.public_base_url` (config override → proxy-aware auto-detect)."""
    return wa.public_base_url()


def _saml_acs_uri(wa) -> str:
    acs = wa._config_section('saml2').get('sp_acs_url', '').strip()
    return acs or f'{_public_base(wa)}/auth/saml2/acs'


def _saml_entity_id(wa) -> str:
    eid = wa._config_section('saml2').get('sp_entity_id', '').strip()
    return eid or _public_base(wa)


def register(app, wa):
    """Register the ``/api/v1/auth/entra*`` app-registration + directory routes on *app*.

    Wires the Graph group-read helpers (used by the OIDC/SAML2 config UI) and the
    device-code provisioning wizards for the SAML2, SCIM and generic module apps
    (start + poll pairs). Uses ``wa._entra_flows`` to hold in-flight device-code
    flows keyed by a short-lived token; group/SSO routes require ``config_edit`` and
    the generic module wizard requires the credential add/edit permissions.
    """
    if not hasattr(wa, '_entra_flows'):
        wa._entra_flows = {}

    config_edit_req = wa._perm_required('config_edit')

    def _wiz_err(kind: str, message: str):
        """Audit an Entra wizard failure uniformly across every wizard (module/OIDC/
        SAML2/SCIM/email/Teams), so a device-code error, decline or expiry is registered
        — not just shown transiently in the wizard modal."""
        wa._audit('entra_wizard_error', detail={'kind': kind, 'error': str(message or '')[:500]})

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

    @app.route('/api/v1/auth/entraid/groups', methods=['POST'])
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

    @app.route('/api/v1/auth/entraid/group_lookup', methods=['POST'])
    @config_edit_req
    def api_entra_group_lookup():
        """Look up a single group by ID via Graph."""
        data = wa._optional_json()
        group_id = (data.get('group_id') or '').strip()
        client_id, client_secret, provider_url = _entra_section_creds(data)

        if not group_id:
            return jsonify({'ok': False, 'message': wa._t('entra_group_id_required')}), 200
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

    @app.route('/api/v1/auth/entraid/saml2/device-code', methods=['POST'])
    @config_edit_req
    def api_entra_saml2_device_code():
        """Start a device-code flow to register the SAML2 enterprise app. Stashes the
        flow and returns the user code / verification URI plus the SP ACS URL and
        entity id the admin will need."""
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

    @app.route('/api/v1/auth/entraid/saml2/secret/device-code', methods=['POST'])
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

    @app.route('/api/v1/auth/entraid/saml2/device-poll', methods=['POST'])
    @config_edit_req
    def api_entra_saml2_device_poll():
        """Poll a pending SAML2 device-code flow. Returns ``pending``/``expired``/
        ``error`` while sign-in is incomplete; once a token arrives, either back-fills
        the Graph secret (``saml2_secret`` flow) or provisions the SAML2 app and
        returns its config (audited). Cleans up the flow on any terminal state."""
        data, err = wa._require_json()
        if err:
            return err
        flow_token = data.get('flow_token')
        flow = wa._entra_flows.get(flow_token)
        if not flow:
            return jsonify({'status': 'expired'})
        if time.time() > flow['expires_at']:
            wa._entra_flows.pop(flow_token, None)
            _wiz_err('saml2', 'sign-in expired')
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
            _wiz_err('saml2', body.get('error_description', error))
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
                            'message': wa._t('entra_no_tenant')})

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

    # ── SCIM provisioning app (device-code) ────────────────────────────────
    # "Register SCIM in Azure": create an enterprise app wired to ServiceSentry's
    # own /scim/v2 endpoint (SCIM sync job + BaseAddress/SecretToken), so Entra can
    # push users/groups.  The bearer token comes from the request (the value in the
    # config form, possibly just generated and unsaved) and falls back to the stored
    # scim|token.  The base URL is derived from the server's public URL.
    def _scim_base_url(wa_):
        base = _public_base(wa_)
        return f'{base.rstrip("/")}/scim/v2'

    @app.route('/api/v1/auth/entraid/scim/device-code', methods=['POST'])
    @config_edit_req
    def api_entra_scim_device_code():
        """Start a device-code flow to register (or re-sync) the SCIM enterprise app
        wired to this server's ``/scim/v2`` endpoint. Requires a stored SCIM bearer
        token; uses the Graph CLI client (needs ``Synchronization.ReadWrite.All``).
        Returns the user code / verification URI and the SCIM base URL."""
        body = wa._optional_json() or {}
        app_name = (body.get('app_name') or provisioning.SCIM_APP_NAME).strip() or provisioning.SCIM_APP_NAME
        # The bearer token is read from config only — it never travels in the request
        # (the UI persists it first). The frontend just tells us "is it set".
        token = (wa._config_section('scim').get('token') or '').strip()
        if not token:
            return jsonify({'error': wa._t('scim_token_empty')}), 400
        base = (body.get('scim_base') or '').strip() or _scim_base_url(wa)
        # When an app is already registered, re-sync mode: re-push the (new) token to
        # the EXISTING app instead of creating another one (keeps both sides in sync).
        sp_object_id = (body.get('sp_object_id') or '').strip()
        try:
            # SCIM needs Synchronization.ReadWrite.All → use the Graph CLI client
            # (Azure PowerShell isn't preauthorized for it: AADSTS65002).
            d = auth.device_code_start(scope=SCIM_PROVISION_SCOPE, client_id=GRAPH_CLI_CLIENT_ID)
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'error': str(exc) or wa._t('entra_device_code_error')}), 502
        flow_token = secrets.token_urlsafe(16)
        wa._entra_flows[flow_token] = {
            'device_code':  d['device_code'],
            'expires_at':   time.time() + int(d.get('expires_in', 900)),
            'interval':     int(d.get('interval', 5)),
            'kind':         'scim',
            'app_name':     app_name,
            'scim_base':    base,
            'scim_token':   token,
            'sp_object_id': sp_object_id or None,   # set → re-sync existing app
            'client_id':    GRAPH_CLI_CLIENT_ID,     # poll must use the same client
        }
        return jsonify({
            'flow_token':       flow_token,
            'user_code':        d['user_code'],
            'verification_uri': d['verification_uri'],
            'verification_uri_complete': d.get('verification_uri_complete', ''),
            'expires_in':       d.get('expires_in', 900),
            'interval':         d.get('interval', 5),
            'scim_base':        base,
        })

    @app.route('/api/v1/auth/entraid/scim/device-poll', methods=['POST'])
    @config_edit_req
    def api_entra_scim_device_poll():
        """Poll a pending SCIM device-code flow. Returns ``pending``/``expired``/
        ``error`` until sign-in completes; then either re-pushes the secrets to the
        existing app (re-sync mode) or provisions a new SCIM app + sync job. The
        bearer token is never echoed back to the client. Audited; flow cleaned up."""
        data, err = wa._require_json()
        if err:
            return err
        flow_token = data.get('flow_token')
        flow = wa._entra_flows.get(flow_token)
        if not flow or flow.get('kind') != 'scim':
            return jsonify({'status': 'expired'})
        if time.time() > flow['expires_at']:
            wa._entra_flows.pop(flow_token, None)
            _wiz_err('scim', 'sign-in expired')
            return jsonify({'status': 'expired'})

        body = auth.device_code_poll(flow['device_code'],
                                     client_id=flow.get('client_id') or GRAPH_CLI_CLIENT_ID)
        error = body.get('error', '')
        if error == 'authorization_pending':
            return jsonify({'status': 'pending'})
        if error == 'slow_down':
            flow['interval'] = min(flow['interval'] + 5, 30)
            return jsonify({'status': 'pending', 'interval': flow['interval']})
        if error:
            wa._entra_flows.pop(flow_token, None)
            _wiz_err('scim', body.get('error_description', error))
            return jsonify({'status': 'error', 'message': body.get('error_description', error)})

        tenant_id = auth.extract_tenant_id(body)
        if not tenant_id:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'error',
                            'message': wa._t('entra_no_tenant')})

        # Re-sync mode: an app already exists → just re-push the token to it.
        if flow.get('sp_object_id'):
            try:
                result = provisioning.update_scim_secrets(
                    body['access_token'], flow['sp_object_id'],
                    flow['scim_base'], flow['scim_token'])
            except Exception as exc:  # pylint: disable=broad-except
                wa._entra_flows.pop(flow_token, None)
                wa._audit('entra_scim_resync_failed', detail={
                    'sp_object_id': flow['sp_object_id'], 'error': str(exc)})
                return jsonify({'status': 'error', 'message': str(exc)})
            wa._entra_flows.pop(flow_token, None)
            wa._audit('entra_scim_resync', detail={'sp_object_id': flow['sp_object_id']})
            result.pop('secret_token', None)   # the token never travels back to the client
            return jsonify({'status': 'complete', 'resync': True, **result})

        try:
            result = provisioning.provision_scim_app(
                body['access_token'], tenant_id, flow['scim_base'], flow['scim_token'],
                app_name=flow.get('app_name', provisioning.SCIM_APP_NAME))
        except Exception as exc:  # pylint: disable=broad-except
            wa._entra_flows.pop(flow_token, None)
            wa._audit('entra_scim_app_provision_failed', detail={
                'app_name': flow.get('app_name', ''), 'tenant_id': tenant_id, 'error': str(exc)})
            return jsonify({'status': 'error', 'message': str(exc)})

        wa._entra_flows.pop(flow_token, None)
        wa._audit('entra_scim_app_provisioned', detail={
            'app_name':  flow.get('app_name', ''),
            'tenant_id': tenant_id,
            'client_id': result.get('client_id', ''),
            'job_id':    result.get('job_id', '')})
        result.pop('secret_token', None)   # the token never travels back to the client
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

    def _required_roles(body):
        """The application permissions a check/fix needs: the module profile's roles
        (by ``profile``), else an inline ``__entraid_provision__`` spec in the body."""
        prof = _provision_profile(body.get('profile'))
        if not prof or not prof.get('resources'):
            from lib.providers.entraid import normalize_entraid_provision  # noqa: PLC0415
            _inline = normalize_entraid_provision(body)
            if _inline['resources']:
                prof = _inline
        roles = [r for res in ((prof or {}).get('resources') or []) for r in (res.get('roles') or [])]
        return list(dict.fromkeys(roles))

    @app.route('/api/v1/auth/entraid/check-permissions', methods=['POST'])
    @cred_edit_req
    def api_entraid_check_permissions():
        """Verify an Entra app-only credential holds the application permissions a
        module needs (resolved from its ``__entraid_provision__`` by ``profile``).

        Read-only and generic — the core knows no module's permissions, it discovers
        them by profile.  Acquires an app-only token and inspects its ``roles`` claim
        (no admin, no writes).  Identity: inline ``tenant_id``/``client_id``/
        ``client_secret`` from the body, with a stored credential (``cred_uid``)
        filling the rest — notably the secret the editor sends masked.  Returns a
        modal-ready report ``{ok, all_ok, message, variant, info, missing, results}``."""
        from lib.providers.entraid import permissions  # noqa: PLC0415
        body = wa._optional_json() or {}
        required = _required_roles(body)
        if not required:
            return jsonify({'ok': False, 'message': wa._t('cred_prov_error')}), 400
        vals = {}
        cred_uid = str(body.get('cred_uid') or '').strip()
        cstore = getattr(wa, '_credentials_store', None)
        if cred_uid and cstore is not None:
            stored = (cstore.get(cred_uid, decrypt=True) or {}).get('data') or {}
            vals.update({k: stored.get(k) for k in ('tenant_id', 'client_id', 'client_secret')})
        for k in ('tenant_id', 'client_id', 'client_secret'):
            if body.get(k) not in (None, ''):
                vals[k] = body[k]
        tenant = str(vals.get('tenant_id') or '').strip()
        client_id = str(vals.get('client_id') or '').strip()
        secret = str(vals.get('client_secret') or '').strip()
        if not (tenant and client_id and secret):
            return jsonify({'ok': False, 'message': wa._t('prov_entraid_perms_need_creds')}), 400
        try:
            token = auth.app_token(tenant, client_id, secret)
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'ok': False, 'message': f'Auth: {exc}'})
        rep = permissions.permission_report(permissions.token_roles(token), required)
        msg = (wa._t('prov_entraid_perms_all_ok') if rep['all_ok']
               else wa._t('prov_entraid_perms_missing') + ': ' + ', '.join(rep['missing']))
        return jsonify({'ok': True, 'message': msg,
                        'variant': 'success' if rep['all_ok'] else 'warning', **rep})

    @app.route('/api/v1/auth/entraid/provision/device-code', methods=['POST'])
    @cred_edit_req
    def api_entraid_provision_device_code():
        """Start a device-code flow to provision a generic Entra app for a module
        credential (or an inline declaration, e.g. the OIDC 'Register in Azure'
        button). Resolves the permission profile from the module schema or the
        request body, expands ``{public_url}`` in redirect URIs, stashes the flow and
        returns the user code / verification URI."""
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
        # "Ensure" mode: instead of creating a new app, GRANT the declared
        # permissions to an EXISTING app (by client_id) and admin-consent them —
        # the "Fix permissions" flow. The poll branches on this.
        ensure_client_id = str(body.get('client_id') or '').strip()
        wa._entra_flows[flow_token] = {
            'device_code': d['device_code'],
            'expires_at': time.time() + int(d.get('expires_in', 900)),
            'interval': int(d.get('interval', 5)),
            'app_name': app_name, 'resources': prof['resources'],
            'redirect_uris': redirect_uris,
            'group_claims': bool(prof.get('group_claims')),
            'require_assignment': bool(prof.get('require_assignment')),
            # Expose an SSO API surface (App ID URI + access_as_user + Teams preauth) so
            # the app can be admin-installed as a Teams app (used by the Teams wizard).
            'expose_api': bool(body.get('expose_api')),
            'ensure_client_id': ensure_client_id,
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
        """Poll a pending generic-provisioning device-code flow. Returns ``pending``/
        ``expired``/``error`` until sign-in completes; then registers the app with the
        declared per-resource permissions (and optional SSO surface) and returns the
        tenant/client/secret fields for the credential. Audited; flow cleaned up."""
        data, err = wa._require_json()
        if err:
            return err
        ftok = data.get('flow_token')
        flow = wa._entra_flows.get(ftok)
        if not flow or flow.get('kind') != 'module':
            return jsonify({'status': 'expired'})
        if time.time() > flow['expires_at']:
            wa._entra_flows.pop(ftok, None)
            _wiz_err('provision', 'sign-in expired')
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
            _wiz_err('provision', b.get('error_description', error))
            return jsonify({'status': 'error', 'message': b.get('error_description', error)})
        tenant_id = auth.extract_tenant_id(b)
        if not tenant_id:
            wa._entra_flows.pop(ftok, None)
            _wiz_err('provision', 'could not determine tenant')
            return jsonify({'status': 'error', 'message': wa._t('entra_no_tenant')})
        # "Fix permissions": grant the declared permissions to the EXISTING app
        # (by client_id) and admin-consent them, without creating a new app.
        ensure_cid = flow.get('ensure_client_id')
        if ensure_cid:
            try:
                report = provisioning.ensure_app_permissions(
                    b['access_token'], tenant_id, ensure_cid, flow['resources'])
            except Exception as exc:  # pylint: disable=broad-except
                wa._entra_flows.pop(ftok, None)
                wa._audit('entra_app_permissions_failed',
                          detail={'tenant_id': tenant_id, 'client_id': ensure_cid, 'error': str(exc)})
                return jsonify({'status': 'error', 'message': str(exc)})
            wa._entra_flows.pop(ftok, None)
            wa._audit('entra_app_permissions_ensured', detail={
                'tenant_id': tenant_id, 'client_id': ensure_cid,
                'granted': report.get('granted'), 'missing': report.get('missing')})
            return jsonify({'status': 'complete', 'ensure': True, 'report': report})
        try:
            result = provisioning.provision_entra_app(
                b['access_token'], tenant_id, flow['resources'],
                app_name=flow.get('app_name', provisioning.DEFAULT_APP_NAME),
                redirect_uris=flow.get('redirect_uris'),
                group_claims=flow.get('group_claims', False),
                require_assignment=flow.get('require_assignment', False),
                expose_api=flow.get('expose_api', False))
        except Exception as exc:  # pylint: disable=broad-except
            wa._entra_flows.pop(ftok, None)
            wa._audit('entra_app_provision_failed', detail={'tenant_id': tenant_id, 'error': str(exc)})
            return jsonify({'status': 'error', 'message': str(exc)})
        wa._entra_flows.pop(ftok, None)
        _det = {'app_name': flow.get('app_name', ''), 'tenant_id': tenant_id,
                'client_id': result.get('client_id', '')}
        if 'sso_exposed' in result:
            _det['sso_exposed'] = result['sso_exposed']
        wa._audit('entra_app_provisioned', detail=_det)
        # Record the SSO-surface configuration outcome separately so a failure is
        # auditable (the wizard toast is transient): needed for Teams app install.
        if result.get('sso_exposed') is False:
            wa._audit('entra_expose_api_failed', detail={
                'client_id': result.get('client_id', ''),
                'error': result.get('sso_error', '')})
        return jsonify({'status': 'complete', 'fields': result})
