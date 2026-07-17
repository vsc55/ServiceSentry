#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Teams personal-tab sign-in (Teams SSO) — an Entra ID auth flow.

A Teams tab can't sign in with a normal OAuth redirect (Microsoft's login page can't
be framed), so it uses the Teams JS SDK: ``getAuthToken()`` yields a signed token that
:mod:`lib.providers.entraid.tab_sso` validates and this module turns into a session —
the same provider pattern as OIDC/SAML (which also live under ``lib/providers`` and
reuse ``wa._establish_session`` on the WebAdmin).

External-facing (a host renders the page / a token authenticates it), so both live under
the ``/auth/<provider>/*`` convention — CSRF-exempt, NOT session-gated.

Routes registered by this file:

    GET  /auth/msteams/tab       the tab entry page (loads the Teams SDK, does silent SSO)
    POST /auth/msteams/sso       validate a Teams SSO token → establish a session
"""

from flask import jsonify, render_template

from lib.debug import DebugLevel
from lib.providers.entraid import tab_sso
from lib.security.headers import _CSP_HEAD, _CSP_TAIL

# Microsoft-hosted Teams JS SDK (self-hosting would need the bundled file; the office
# CDN is a trusted Microsoft origin, allowed only in this page's scoped CSP).
_TEAMS_SDK = 'https://res.cdn.office.net/teams-js/2.34.0/js/MicrosoftTeams.min.js'


def _tab_csp() -> str:
    """CSP for the tab page: allow the Teams SDK from the office CDN and let the
    Microsoft Teams/Outlook hosts frame this page."""
    fa = "frame-ancestors 'self' " + ' '.join(tab_sso.TEAMS_FRAME_ANCESTORS)
    head = _CSP_HEAD.replace("script-src 'self' 'unsafe-inline'",
                             "script-src 'self' 'unsafe-inline' https://res.cdn.office.net")
    return f"{head}{fa}; {_CSP_TAIL}"


def _resolve_user(wa, claims: dict):
    """Map validated Teams SSO claims to a ServiceSentry user (username, user) or (None, None).

    Matches by username == UPN, else by email (case-insensitive)."""
    upn = (claims.get('preferred_username') or claims.get('upn')
           or claims.get('email') or claims.get('unique_name') or '').strip()
    if not upn:
        return None, None
    users = wa._users or {}
    if upn in users:
        return upn, users[upn]
    low = upn.lower()
    for uname, ud in users.items():
        if isinstance(ud, dict) and (ud.get('email') or '').strip().lower() == low:
            return uname, ud
    return None, None


def register(app, wa):
    """Register the Teams personal-tab sign-in routes (``/auth/msteams/{tab,sso}``).

    Adds the tab entry page and the token-validation endpoint, marks both
    CSRF-exempt (SDK-token auth, not session) and declares the Teams/Outlook
    frame-ancestor origins for the embed CSP. On success the SSO endpoint reuses the
    shared web session layer, exactly like the OIDC/SAML providers.
    """
    # Reuse the shared session layer on the WebAdmin (``wa._establish_session`` /
    # ``wa._landing_url``) — the one place a provider turns an external identity into a
    # ServiceSentry session, exactly like the OIDC/SAML providers do.
    # External/token-authenticated (SDK token), so exempt from the session CSRF check.
    wa._register_csrf_exempt('/auth/msteams/tab', '/auth/msteams/sso')
    # Declare the Teams/Outlook origins that may iframe the panel when embed_in_teams is on
    # (discovered by the security layer — keeps core headers.py provider-agnostic).
    wa._register_embed_origins('_embed_in_teams', *tab_sso.TEAMS_FRAME_ANCESTORS)

    @app.route('/auth/msteams/tab', methods=['GET'])
    def msteams_tab():
        """Render the Teams personal-tab page (loads the Teams JS SDK for silent SSO),
        with a scoped CSP allowing the office CDN and Teams/Outlook framing."""
        # Public entry point rendered inside the Teams tab; it authenticates via the SDK.
        resp = app.make_response(render_template('msteams_tab.html', teams_sdk=_TEAMS_SDK))
        resp.headers['Content-Security-Policy'] = _tab_csp()   # scoped (SDK CDN + Teams framing)
        return resp

    @app.route('/auth/msteams/sso', methods=['POST'])
    def api_msteams_sso():
        """Validate a Teams SSO token and establish a session.

        Verifies the token (signature/audience/issuer) against the ``msteams`` config,
        maps its claims to a ServiceSentry user, and logs in. Refuses cleanly when
        PyJWT is missing (501), the token is invalid (401), no user matches (403), the
        match is a local account (403, takeover guard) or the account is disabled.
        Returns JSON with the landing redirect on success."""
        data = wa._optional_json() or {}
        token = (data.get('token') or '').strip()
        if not token:
            return jsonify({'ok': False, 'error': wa._t('msteams_sso_no_token')}), 400
        if not tab_sso.available():
            return jsonify({'ok': False, 'error': wa._t('msteams_sso_unavailable')}), 501
        cfg = wa._config_section('msteams')
        try:
            claims = tab_sso.validate_tab_token(token, cfg.get('tenant_id', ''), cfg.get('client_id', ''))
        except tab_sso.TabSsoUnavailable:
            return jsonify({'ok': False, 'error': wa._t('msteams_sso_unavailable')}), 501
        except Exception as exc:  # pylint: disable=broad-except
            wa._audit('msteams_sso_failed', detail={'error': str(exc)[:300]})
            return jsonify({'ok': False, 'error': wa._t('msteams_sso_invalid')}), 401

        username, user = _resolve_user(wa, claims)
        if user is None:
            wa._audit('msteams_sso_failed', detail={
                'error': 'no matching user', 'upn': claims.get('preferred_username', '')})
            return jsonify({'ok': False, 'error': wa._t('msteams_sso_no_user')}), 403
        # Never let a Teams token silently take over a LOCAL account (same guard as OIDC).
        if str(user.get('auth_source', 'local')) in ('', 'local'):
            wa._audit('msteams_sso_failed', detail={'error': 'local account', 'user': username})
            return jsonify({'ok': False, 'error': wa._t('msteams_sso_local_account')}), 403
        if user.get('enabled') is False:
            return jsonify({'ok': False, 'error': wa._t('msteams_sso_no_user')}), 403

        wa._establish_session(username, user)
        wa._audit('msteams_sso_login', detail={'user': username})
        wa._dbg(f"> Auth/Teams >> SSO session established user={username!r}", DebugLevel.info)
        return jsonify({'ok': True, 'redirect': wa._landing_url(user)})
