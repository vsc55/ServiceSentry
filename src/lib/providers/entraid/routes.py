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

**This file is meant to be routing and little else.** What each button *does* lives
next to the subject it belongs to, so a rule is written once and read where it applies:

* :mod:`~lib.providers.entraid.device_flow` — the device-code conversation itself
  (park a flow, poll it, expire it); every start/poll pair below is one call into it.
* :mod:`~lib.providers.entraid.sections` — which app an auth section uses, and the
  SP/SCIM URLs this server publishes.
* :mod:`~lib.providers.entraid.cred_link` — reading and writing the credential that
  holds an Entra app.
* :mod:`~lib.providers.entraid.declarations` — resolving what an app must be granted.

What is left here is a route's own business: which permission guards it, what it
stashes for the poll, what it audits, and the shape of the answer.

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
    POST   /api/v1/auth/entraid/provision/assign-role   assign the Azure role on a picked subscription
    POST   /api/v1/auth/entraid/oidc/secret/device-code   device-code: rotate the OIDC app secret
    POST   /api/v1/auth/entraid/oidc/secret/device-poll   poll the OIDC secret rotation
    POST   /api/v1/auth/entraid/cred/secret/device-code   device-code: rotate a credential app's secret
    POST   /api/v1/auth/entraid/cred/secret/device-poll   poll the credential secret rotation
    POST   /api/v1/auth/entraid/check-permissions         verify the app's granted Graph permissions
    POST   /api/v1/auth/entraid/sso/check-permissions     verify an SSO section's granted Graph permissions
"""

from flask import jsonify

from lib.providers.entraid import auth, cred_link, declarations, device_flow, directory, provisioning, sections
from lib.providers.entraid.client import GRAPH_CLI_CLIENT_ID, PROVISION_SCOPE, SCIM_PROVISION_SCOPE

# Azure Resource Manager audience — the RBAC step signs in for Graph and redeems the
# same consent here (see auth.token_from_refresh).
ARM_SCOPE = 'https://management.azure.com/.default'


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

    flows = wa._entra_flows
    config_edit_req = wa._perm_required('config_edit')

    def _auth_error(exc) -> str:
        """A sign-in failure, said so the reader knows where to look.

        ``AADSTS7000215`` means "invalid client secret" — and Entra also returns it for a
        secret that is perfectly correct but was created seconds ago and has not
        propagated yet. The retry above has already waited; if it is still failing, the
        reader deserves to know which of the two it might be instead of a raw trace id.
        """
        text = str(exc)
        if auth.FRESH_SECRET_ERROR in text:
            return f"{wa._t('prov_entraid_secret_not_ready')} — {text}"
        return f'Auth: {text}'

    def _wiz_err(kind: str, message: str):
        """Audit an Entra wizard failure uniformly across every wizard (module/OIDC/
        SAML2/SCIM/email/Teams), so a device-code error, decline or expiry is registered
        — not just shown transiently in the wizard modal."""
        wa._audit('entra_wizard_error', detail={'kind': kind, 'error': str(message or '')[:500]})

    def _section_creds(data):
        """Graph client-credentials for the auth section named in *data* — see
        :func:`sections.section_credentials` for which app each section uses and when a
        request body is allowed to override it."""
        return sections.section_credentials(wa._config_section, data)

    def _start_error(exc, key: str):
        """A wizard that could not even start. The reason from Entra when there is one,
        the section's own wording when the failure carries no text."""
        return jsonify({'error': str(exc) or wa._t(key)}), 502

    @app.route('/api/v1/auth/entraid/groups', methods=['POST'])
    @config_edit_req
    def api_entra_groups():
        """Fetch all directory groups via Graph, using the OIDC/SAML2 app credentials."""
        from flask import request, session
        data = wa._optional_json()
        client_id, client_secret, provider_url = _section_creds(data)

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

    @app.route('/api/v1/auth/entraid/sso/check-permissions', methods=['POST'])
    @config_edit_req
    def api_entra_sso_check_permissions():
        """Are the SSO app's Graph permissions granted AND admin-consented?

        The same question the credentials editor answers for a module's app, asked of the
        app behind an auth section (``oidc`` / ``saml2``).  It is worth asking separately
        because consent is the half that fails silently: registering the app succeeds, the
        admin never presses "Grant admin consent", and everything keeps working until
        something actually calls Graph — the group picker comes back empty, or a login maps
        no groups, with no hint that a consent is missing.

        Read-only: it acquires an app-only token and reads its ``roles`` claim. A
        permission that is requested but not consented never reaches that claim, which is
        exactly the distinction being tested.

        Credentials come from :func:`sections.section_credentials`, the same resolution the
        group fetch uses — so this checks the identity that is really used, not one
        configured somewhere else. The permission list comes from the section's own UI
        declaration, the one its "Register in Azure" button provisions.
        """
        from lib.providers.entraid import permissions  # noqa: PLC0415
        data = wa._optional_json() or {}
        # Declared server-side (client.SSO_APP_ROLES), next to the id the registration
        # grants: the check must ask for exactly what "Register in Azure" provisioned, and
        # a list kept in the panel would drift from the one in the wizard.
        from lib.providers.entraid.client import SSO_APP_ROLES  # noqa: PLC0415
        required = [str(r).strip() for r in (data.get('app_roles') or SSO_APP_ROLES)
                    if str(r).strip()]
        if not required:
            return jsonify({'ok': False, 'message': wa._t('cred_prov_error')}), 400
        client_id, client_secret, provider_url = _section_creds(data)
        tenant = auth.tenant_from_provider_url(provider_url)
        if not tenant:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_not_entra')})
        if not client_id or not client_secret:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_missing_creds')})
        try:
            token = auth.app_token_retrying(tenant, client_id, client_secret)
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'ok': False, 'message': _auth_error(exc)})
        rep = permissions.permission_report(permissions.token_roles(token), required)
        msg = (wa._t('prov_entraid_perms_all_ok') if rep['all_ok']
               else wa._t('prov_entraid_perms_missing') + ': ' + ', '.join(rep['missing']))
        return jsonify({'ok': True, 'message': msg,
                        'variant': 'success' if rep['all_ok'] else 'warning', **rep})

    @app.route('/api/v1/auth/entraid/group_lookup', methods=['POST'])
    @config_edit_req
    def api_entra_group_lookup():
        """Look up a single group by ID via Graph."""
        data = wa._optional_json()
        group_id = (data.get('group_id') or '').strip()
        client_id, client_secret, provider_url = _section_creds(data)

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
            _tok, payload = device_flow.start(flows, 'saml2', app_name=app_name)
        except Exception as exc:  # pylint: disable=broad-except
            return _start_error(exc, 'entra_device_code_error')
        return jsonify({**payload,
                        'acs_url':   sections.saml_acs_uri(wa),
                        'entity_id': sections.saml_entity_id(wa)})

    @app.route('/api/v1/auth/entraid/saml2/secret/device-code', methods=['POST'])
    @config_edit_req
    def api_entra_saml2_secret_device_code():
        """Start a device-code flow to add a Graph client secret to the EXISTING SAML2
        app (for the group→role mapping), without recreating it."""
        app_id = wa._config_section('saml2').get('sp_app_id', '').strip()
        if not app_id:
            return jsonify({'error': wa._t('entra_saml2_groups_no_app')}), 400
        try:
            _tok, payload = device_flow.start(flows, 'saml2_secret', app_id=app_id)
        except Exception as exc:  # pylint: disable=broad-except
            return _start_error(exc, 'entra_device_code_error')
        return jsonify(payload)

    @app.route('/api/v1/auth/entraid/oidc/secret/device-code', methods=['POST'])
    @config_edit_req
    def api_entra_oidc_secret_device_code():
        """Start a device-code flow to mint a FRESH client secret on the EXISTING OIDC app
        (rotation), without recreating the app registration."""
        app_id = wa._config_section('oidc').get('client_id', '').strip()
        if not app_id:
            return jsonify({'error': wa._t('entra_oidc_no_app')}), 400
        try:
            _tok, payload = device_flow.start(flows, 'oidc_secret', app_id=app_id)
        except Exception as exc:  # pylint: disable=broad-except
            return _start_error(exc, 'entra_device_code_error')
        return jsonify(payload)

    @app.route('/api/v1/auth/entraid/oidc/secret/device-poll', methods=['POST'])
    @config_edit_req
    def api_entra_oidc_secret_device_poll():
        """Poll the OIDC secret-rotation flow. On success mints a new secret on the existing
        app and persists it (with the expiry Entra granted) into ``oidc|client_secret`` /
        ``oidc|secret_expires_at``. The previous secret stays valid until it expires, so the
        rotation is non-disruptive."""
        data, err = wa._require_json()
        if err:
            return err
        flow, body, resp = device_flow.poll(flows, data.get('flow_token'), 'oidc_secret',
                                            on_error=_wiz_err)
        if resp:
            return jsonify(resp)
        try:
            res = provisioning.add_app_secret(body['access_token'], flow['app_id'],
                                              display_name='ServiceSentry OIDC')
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'status': 'error', 'message': str(exc)})
        wa._save_oidc_secret(res.get('secret', ''), res.get('expires_at', ''))
        wa._audit('entra_oidc_secret_rotated',
                  detail={'app_id': flow['app_id'], 'expires_at': res.get('expires_at', '')})
        return jsonify({'status': 'complete', 'expires_at': res.get('expires_at', '')})

    @app.route('/api/v1/auth/entraid/saml2/device-poll', methods=['POST'])
    @config_edit_req
    def api_entra_saml2_device_poll():
        """Poll a pending SAML2 device-code flow. Returns ``pending``/``expired``/
        ``error`` while sign-in is incomplete; once a token arrives, either back-fills
        the Graph secret (``saml2_secret`` flow) or provisions the SAML2 app and
        returns its config (audited)."""
        data, err = wa._require_json()
        if err:
            return err
        flow_token = data.get('flow_token')
        # Two flows share this poll (register the app / back-fill its Graph secret), so
        # the kind is whichever one is parked under this token — still never a third.
        kind = (flows.get(flow_token) or {}).get('kind')
        if kind not in ('saml2', 'saml2_secret'):
            return jsonify({'status': 'expired'})
        flow, body, resp = device_flow.poll(flows, flow_token, kind, on_error=_wiz_err)
        if resp:
            return jsonify(resp)
        access_token = body['access_token']

        # Back-fill a Graph client secret on the EXISTING app (group→role mapping),
        # without recreating it.
        if kind == 'saml2_secret':
            try:
                secret = provisioning.add_graph_secret(access_token, flow['app_id'])
            except Exception as exc:  # pylint: disable=broad-except
                return jsonify({'status': 'error', 'message': str(exc)})
            wa._audit('entra_saml2_graph_secret', detail={'app_id': flow['app_id']})
            return jsonify({'status': 'complete', 'graph_secret': secret})

        tenant_id = auth.extract_tenant_id(body)
        if not tenant_id:
            return jsonify({'status': 'error', 'message': wa._t('entra_no_tenant')})

        try:
            result = provisioning.provision_saml2_app(
                access_token, sections.saml_acs_uri(wa), sections.saml_entity_id(wa), tenant_id,
                app_name=flow.get('app_name', provisioning.SAML2_APP_NAME))
        except Exception as exc:
            wa._audit('entra_saml2_app_provision_failed', detail={
                'app_name': flow.get('app_name', ''), 'tenant_id': tenant_id,
                'error': str(exc),
            })
            return jsonify({'status': 'error', 'message': str(exc)})

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
        base = (body.get('scim_base') or '').strip() or sections.scim_base_url(wa)
        # When an app is already registered, re-sync mode: re-push the (new) token to
        # the EXISTING app instead of creating another one (keeps both sides in sync).
        sp_object_id = (body.get('sp_object_id') or '').strip()
        try:
            # SCIM needs Synchronization.ReadWrite.All → use the Graph CLI client
            # (Azure PowerShell isn't preauthorized for it: AADSTS65002). The poll
            # redeems with the same client, which device_flow keeps on the flow.
            _tok, payload = device_flow.start(
                flows, 'scim', scope=SCIM_PROVISION_SCOPE, client_id=GRAPH_CLI_CLIENT_ID,
                app_name=app_name, scim_base=base, scim_token=token,
                sp_object_id=sp_object_id or None)   # set → re-sync existing app
        except Exception as exc:  # pylint: disable=broad-except
            return _start_error(exc, 'entra_device_code_error')
        return jsonify({**payload, 'scim_base': base})

    @app.route('/api/v1/auth/entraid/scim/device-poll', methods=['POST'])
    @config_edit_req
    def api_entra_scim_device_poll():
        """Poll a pending SCIM device-code flow. Returns ``pending``/``expired``/
        ``error`` until sign-in completes; then either re-pushes the secrets to the
        existing app (re-sync mode) or provisions a new SCIM app + sync job. The
        bearer token is never echoed back to the client. Audited."""
        data, err = wa._require_json()
        if err:
            return err
        flow, body, resp = device_flow.poll(flows, data.get('flow_token'), 'scim',
                                            on_error=_wiz_err)
        if resp:
            return jsonify(resp)

        tenant_id = auth.extract_tenant_id(body)
        if not tenant_id:
            return jsonify({'status': 'error', 'message': wa._t('entra_no_tenant')})

        # Re-sync mode: an app already exists → just re-push the token to it.
        if flow.get('sp_object_id'):
            try:
                result = provisioning.update_scim_secrets(
                    body['access_token'], flow['sp_object_id'],
                    flow['scim_base'], flow['scim_token'])
            except Exception as exc:  # pylint: disable=broad-except
                wa._audit('entra_scim_resync_failed', detail={
                    'sp_object_id': flow['sp_object_id'], 'error': str(exc)})
                return jsonify({'status': 'error', 'message': str(exc)})
            wa._audit('entra_scim_resync', detail={'sp_object_id': flow['sp_object_id']})
            result.pop('secret_token', None)   # the token never travels back to the client
            return jsonify({'status': 'complete', 'resync': True, **result})

        try:
            result = provisioning.provision_scim_app(
                body['access_token'], tenant_id, flow['scim_base'], flow['scim_token'],
                app_name=flow.get('app_name', provisioning.SCIM_APP_NAME))
        except Exception as exc:  # pylint: disable=broad-except
            wa._audit('entra_scim_app_provision_failed', detail={
                'app_name': flow.get('app_name', ''), 'tenant_id': tenant_id, 'error': str(exc)})
            return jsonify({'status': 'error', 'message': str(exc)})

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

    # ── Rotate the client secret of a CREDENTIAL's app ────────────────────────────
    # The same operation the OIDC section offers, for the Entra app behind a module
    # credential (m365, azure, …). Entra secrets expire; without this the only way to
    # replace one was to re-register the app, which changes its id and its grants and
    # therefore breaks whatever else already trusts it.

    @app.route('/api/v1/auth/entraid/cred/secret/device-code', methods=['POST'])
    @cred_edit_req
    def api_entra_cred_secret_device_code():
        """Start a device-code flow to mint a FRESH secret on the credential's EXISTING
        app — no new registration, so the app id, its permissions and its consent stay."""
        body = wa._optional_json() or {}
        app_id, cred_uid = cred_link.credential_app_id(
            getattr(wa, '_credentials_store', None), body)
        if not app_id:
            return jsonify({'error': wa._t('prov_entraid_fix_need_client')}), 400
        try:
            _tok, payload = device_flow.start(flows, 'cred_secret',
                                              app_id=app_id, cred_uid=cred_uid)
        except Exception as exc:  # pylint: disable=broad-except
            return _start_error(exc, 'entra_device_code_error')
        return jsonify(payload)

    @app.route('/api/v1/auth/entraid/cred/secret/device-poll', methods=['POST'])
    @cred_edit_req
    def api_entra_cred_secret_device_poll():
        """Poll the credential secret rotation.

        On success the new secret is BOTH stored on the credential and returned as a
        field. Stored, because a rotation that only filled the form would leave the app
        with a secret nobody kept if the editor were closed without saving; returned, so
        the field on screen stops showing the value that is about to expire.

        The previous secret stays valid until its own expiry, so nothing breaks while the
        new one propagates.
        """
        data, err = wa._require_json()
        if err:
            return err
        flow, body, resp = device_flow.poll(flows, data.get('flow_token'), 'cred_secret',
                                            on_error=_wiz_err)
        if resp:
            return jsonify(resp)
        try:
            res = provisioning.add_app_secret(body['access_token'], flow['app_id'],
                                              display_name='ServiceSentry')
        except Exception as exc:  # pylint: disable=broad-except
            _wiz_err('cred_secret', str(exc))
            return jsonify({'status': 'error', 'message': str(exc)})
        from flask import session                       # noqa: PLC0415
        from lib.core.constants import SYSTEM_USER      # noqa: PLC0415
        secret = res.get('secret', '')
        stored = cred_link.store_rotated_secret(
            getattr(wa, '_credentials_store', None), flow.get('cred_uid', ''), secret,
            actor=session.get('username', SYSTEM_USER))
        wa._audit('entra_cred_secret_rotated',
                  detail={'app_id': flow['app_id'], 'cred_uid': flow.get('cred_uid', ''),
                          'expires_at': res.get('expires_at', ''), 'stored': stored})
        # `fields` is what the wizard writes back into the open editor.
        # `rotated` is what tells the wizard this was not an app creation, so it can say
        # so instead of "app created and credential filled" — which would be a lie about
        # the one operation whose whole point is that the app did NOT change.
        return jsonify({'status': 'complete', 'rotated': True,
                        'expires_at': res.get('expires_at', ''),
                        'stored': stored, 'fields': {'client_secret': secret}})

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
        modules_dir = getattr(wa, '_modules_dir', None)
        required = declarations.declared_roles(modules_dir, body)
        if not required:
            return jsonify({'ok': False, 'message': wa._t('cred_prov_error')}), 400
        vals, stored = cred_link.credential_auth_values(
            getattr(wa, '_credentials_store', None), body)
        tenant = str(vals.get('tenant_id') or '').strip()
        client_id = str(vals.get('client_id') or '').strip()
        secret = str(vals.get('client_secret') or '').strip()
        if not (tenant and client_id and secret):
            return jsonify({'ok': False, 'message': wa._t('prov_entraid_perms_need_creds')}), 400
        try:
            token = auth.app_token_retrying(tenant, client_id, secret)
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'ok': False, 'message': _auth_error(exc)})
        rep = permissions.permission_report(permissions.token_roles(token), required)
        # A declaration may be gated by more than application permissions: an Azure one
        # also needs an ARM role assignment, which no token claim can answer — reporting
        # only the claim would say "all granted" while every ARM call 403s. The owner of
        # the declaration produces that row; this route only folds it in, and stays
        # unaware of what the extra check was.
        rbac = (declarations.provision_profile(modules_dir, body.get('profile'))
                or {}).get('azure_rbac') or {}
        if rbac:
            from lib.providers.azure import rbac as azure_rbac  # noqa: PLC0415
            # The whole credential, not just the three auth fields: the declaration names
            # which OTHER field is its target, and only it knows which one that is.
            values = dict(stored)
            values.update({k: v for k, v in body.items() if v not in (None, '')})
            values.update({'tenant_id': tenant, 'client_id': client_id,
                           'client_secret': secret})
            permissions.merge_row(rep, azure_rbac.permission_row(
                rbac, values, wa._t('prov_entraid_perm_azure_rbac')))
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
        prof = declarations.declared_profile(getattr(wa, '_modules_dir', None), body)
        if not prof or not prof.get('resources'):
            return jsonify({'error': wa._t('cred_prov_error')}), 400
        app_name = (body.get('app_name') or prof['app_name']).strip() or prof['app_name']
        # An Azure RBAC step needs a SECOND token (audience management.azure.com), which
        # means a refresh token — so this flow, and only this flow, adds offline_access.
        # Asked for whenever the step is DECLARED, not only when a target was supplied:
        # without a target the poll uses that same token to list the admin's
        # subscriptions so they can pick one instead of pasting a GUID.
        rbac = dict(prof.get('azure_rbac') or {})
        rbac_target = str(body.get(rbac.get('field') or '') or '').strip() if rbac else ''
        _base = sections.public_base(wa)
        redirect_uris = [str(u).replace('{public_url}', _base)
                         for u in (prof.get('redirect_uris') or [])]
        try:
            _tok, payload = device_flow.start(
                flows, 'module',
                scope=(PROVISION_SCOPE + ' offline_access') if rbac else None,
                app_name=app_name, resources=prof['resources'],
                redirect_uris=redirect_uris,
                group_claims=bool(prof.get('group_claims')),
                require_assignment=bool(prof.get('require_assignment')),
                # Expose an SSO API surface (App ID URI + access_as_user + Teams preauth)
                # so the app can be admin-installed as a Teams app (Teams wizard).
                expose_api=bool(body.get('expose_api')),
                # "Ensure" mode: instead of creating a new app, GRANT the declared
                # permissions to an EXISTING app (by client_id) and admin-consent them —
                # the "Fix permissions" flow. The poll branches on this.
                ensure_client_id=str(body.get('client_id') or '').strip(),
                azure_rbac=rbac, rbac_target=rbac_target)
        except Exception as exc:  # pylint: disable=broad-except
            return _start_error(exc, 'cred_prov_error')
        return jsonify(payload)

    @app.route('/api/v1/auth/entraid/provision/device-poll', methods=['POST'])
    @cred_edit_req
    def api_entraid_provision_device_poll():
        """Poll a pending generic-provisioning device-code flow. Returns ``pending``/
        ``expired``/``error`` until sign-in completes; then registers the app with the
        declared per-resource permissions (and optional SSO surface) and returns the
        tenant/client/secret fields for the credential. Audited."""
        data, err = wa._require_json()
        if err:
            return err
        flow, b, resp = device_flow.poll(flows, data.get('flow_token'), 'module',
                                         on_error=_wiz_err)
        if resp:
            return jsonify(resp)
        tenant_id = auth.extract_tenant_id(b)
        if not tenant_id:
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
                wa._audit('entra_app_permissions_failed',
                          detail={'tenant_id': tenant_id, 'client_id': ensure_cid, 'error': str(exc)})
                return jsonify({'status': 'error', 'message': str(exc)})
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
            wa._audit('entra_app_provision_failed', detail={'tenant_id': tenant_id, 'error': str(exc)})
            return jsonify({'status': 'error', 'message': str(exc)})
        # Azure RBAC step (declared by the module): the app now exists, so grant its
        # service principal a role ON the subscription. Separate audience → exchange the
        # refresh token for an ARM one. Reported, never fatal: the app + secret are
        # already usable, and the admin can assign the role by hand.
        rbac = flow.get('azure_rbac') or {}
        target = flow.get('rbac_target') or ''
        pending = None
        if rbac:
            sp_oid = result.get('sp_object_id')
            role = rbac.get('role', 'reader')
            try:
                if not sp_oid:
                    raise RuntimeError('the service principal was not created')
                arm_tok = auth.token_from_refresh(b.get('refresh_token', ''), ARM_SCOPE)
            except Exception as exc:  # pylint: disable=broad-except
                arm_tok = ''
                result['azure_rbac'] = {'ok': False, 'already': False,
                                        'role': role, 'message': str(exc)}
                wa._audit('entra_azure_rbac_failed',
                          detail={'subscription_id': target, 'role': role,
                                  'principal_id': sp_oid or '', 'error': str(exc)})
            if arm_tok and target:
                rep = provisioning.assign_subscription_role(arm_tok, target, sp_oid, role=role)
                result['azure_rbac'] = rep
                wa._audit('entra_azure_rbac_assigned' if rep.get('ok') else 'entra_azure_rbac_failed',
                          detail={'subscription_id': target, 'role': rep.get('role'),
                                  'principal_id': sp_oid or '', 'already': rep.get('already'),
                                  'error': rep.get('message', '')})
            elif arm_tok:
                # No target was supplied: offer the subscriptions this admin can see
                # instead of making them find and paste a GUID. The ARM token is held in
                # a SEPARATE short-lived flow so the choice can be completed without a
                # second sign-in — see …/provision/assign-role.
                subs = provisioning.list_subscriptions(arm_tok)
                rtok = device_flow.park(flows, kind='azure_rbac', arm_token=arm_tok,
                                        principal_id=sp_oid, role=role,
                                        field=rbac.get('field', ''),
                                        client_id=result.get('client_id', ''))
                pending = {'flow_token': rtok, 'role': role,
                           'field': rbac.get('field', ''), 'subscriptions': subs}
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
        out = {'status': 'complete', 'fields': result}
        if pending:
            out['azure_rbac_pending'] = pending
        return jsonify(out)

    @app.route('/api/v1/auth/entraid/provision/assign-role', methods=['POST'])
    @cred_edit_req
    def api_entraid_provision_assign_role():
        """Finish the Azure RBAC step on the subscription the admin PICKED, reusing the
        ARM token the provisioning poll already holds — so choosing a target costs no
        second sign-in. Audited; the flow is consumed either way."""
        data, err = wa._require_json()
        if err:
            return err
        ftok = data.get('flow_token')
        flow = device_flow.take(flows, ftok, 'azure_rbac')
        if flow is None:
            return jsonify({'status': 'expired'})
        sub = str(data.get('subscription_id') or '').strip()
        if not sub:
            return jsonify({'error': wa._t('cred_prov_rbac_no_sub')}), 400
        device_flow.drop(flows, ftok)
        rep = provisioning.assign_subscription_role(
            flow['arm_token'], sub, flow['principal_id'], role=flow.get('role', 'reader'))
        wa._audit('entra_azure_rbac_assigned' if rep.get('ok') else 'entra_azure_rbac_failed',
                  detail={'subscription_id': sub, 'role': rep.get('role'),
                          'principal_id': flow.get('principal_id', ''),
                          'client_id': flow.get('client_id', ''),
                          'already': rep.get('already'), 'error': rep.get('message', '')})
        return jsonify({'status': 'complete', 'azure_rbac': rep,
                        'field': flow.get('field', ''), 'subscription_id': sub})
