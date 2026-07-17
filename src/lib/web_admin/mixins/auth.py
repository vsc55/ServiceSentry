#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local password authentication + account lockout for WebAdmin.

Verifies credentials against the DB-backed user store, enforces the per-account
lockout, and keeps every failure path timing-equal so a username cannot be
enumerated by response time (see :meth:`_timing_decoy_hash`)."""

from collections import namedtuple
from datetime import datetime, timedelta, timezone

from flask import request, session
from werkzeug.security import check_password_hash, generate_password_hash

from lib.debug import DebugLevel
from lib.i18n import SUPPORTED_LANGS
from ..constants import HOME_PAGES

# i18n key per ``auth_source`` for the login-notification method label (translated in the
# system notification language, like every other notification string).
_AUTH_METHOD_KEYS = {
    'local': 'notif_auth_local', 'ldap': 'notif_auth_ldap',
    'oidc': 'notif_auth_oidc', 'saml2': 'notif_auth_saml', 'saml': 'notif_auth_saml',
    'entraid': 'notif_auth_entraid', 'msteams': 'notif_auth_msteams', 'scim': 'notif_auth_scim',
}

# Result of resolving a login attempt (LDAP vs local), free of any web concern.
#   user       the authenticated user dict, or None on failure
#   source     how they authenticated ('ldap' / 'local' / the user's auth_source)
#   username   canonical username to use for the session + audit (LDAP may rewrite it)
#   flash_key  i18n key of the message to show on failure ('' on success)
#   reason     audit reason code ('' on success)
LoginResult = namedtuple('LoginResult', 'user source username flash_key reason')


class _AuthMixin:
    """Local credential verification and brute-force lockout.

    Relies on the host WebAdmin for the user store (``self._users`` /
    ``self._persist_users``), the lockout thresholds (``self._LOCKOUT_*``) and the
    debug printer (``self._dbg``)."""

    def _timing_decoy_hash(self) -> str:
        """A stable password hash to verify against on the paths that have no real hash
        to check (unknown / disabled / locked users), so their response time matches a
        wrong-password attempt and the account can't be enumerated by timing. Prefers a
        REAL account's hash (identical scrypt cost); caches a generated one otherwise."""
        real = next((u.get('password_hash') for u in self._users.values()
                     if u.get('password_hash')), None)
        if real:
            return real
        decoy = getattr(self, '_decoy_pw_hash', None)
        if decoy is None:
            decoy = self._decoy_pw_hash = generate_password_hash('decoy-not-a-real-password')
        return decoy

    def _authenticate(self, username: str, password: str) -> tuple[dict | None, str | None]:
        """Return ``(user, None)`` on success or ``(None, reason)`` on failure.

        Reasons: ``'user_not_found'``, ``'account_disabled'``,
        ``'account_locked'``, ``'invalid_credentials'``.

        Every failure path runs exactly one ``check_password_hash`` (against the real
        hash or :meth:`_timing_decoy_hash`) so unknown / wrong-password / disabled /
        locked are indistinguishable by response time (anti-enumeration).
        """
        user = self._users.get(username)
        if not user:
            check_password_hash(self._timing_decoy_hash(), password)
            return None, 'user_not_found'
        if not user.get('enabled', True):
            check_password_hash(user.get('password_hash') or self._timing_decoy_hash(), password)
            return None, 'account_disabled'

        # Check active lockout
        locked_until_str = user.get('_locked_until')
        if locked_until_str:
            locked_until = datetime.fromisoformat(locked_until_str)
            now = datetime.now(timezone.utc)
            if now < locked_until:
                # Hash anyway so a locked account isn't faster to detect (enumeration).
                check_password_hash(user.get('password_hash') or self._timing_decoy_hash(), password)
                return None, 'account_locked'
            # Lockout expired — clear it
            user.pop('_locked_until', None)
            user.pop('_failed_attempts', None)
            self._persist_users()

        # A passwordless account (SSO/OIDC/SAML/SCIM-provisioned, enabled, no local
        # hash) must never authenticate locally — and must still run one hash so it
        # is timing-indistinguishable from a wrong password (and never KeyErrors).
        if not check_password_hash(user.get('password_hash') or self._timing_decoy_hash(), password):
            max_attempts = self._LOCKOUT_MAX_ATTEMPTS
            if max_attempts > 0:
                attempts = user.get('_failed_attempts', 0) + 1
                user['_failed_attempts'] = attempts     # in-memory only (no per-attempt DB
                                                        # write → no timing enumeration channel)
                if attempts >= max_attempts:
                    locked_until = datetime.now(timezone.utc) + timedelta(seconds=self._LOCKOUT_DURATION_SECS)
                    user['_locked_until'] = locked_until.isoformat()
                    self._persist_users()               # persist only when actually locking
                    self._dbg(f"> Auth/Local >> account {username!r} locked after "
                              f"{attempts} failed attempts", DebugLevel.warning)
                    return None, 'account_locked'
            return None, 'invalid_credentials'

        # Success — clear any lockout state
        if user.pop('_failed_attempts', None) is not None or user.pop('_locked_until', None) is not None:
            self._persist_users()
        return user, None

    def resolve_login(self, username: str, password: str) -> 'LoginResult':
        """Resolve a login attempt against LDAP (when enabled) then local, with no web
        concern (no session/flash/redirect) — the ``login`` route maps the result to those.

        Mirrors the previous inline route flow exactly, with the two duplicated LDAP branches
        (known-SSO user vs unknown user) collapsed into one:

        * LDAP is tried when it is enabled+available AND the user is not a known *local*
          account (a known SSO/LDAP user, or an unknown user).
        * A known SSO/LDAP user never falls through to local; an unknown user falls through to
          local only on an LDAP *connection* error when ``fallback_to_local`` is set.
        * Local users (and the fallback) go through :meth:`_authenticate`.

        Anti-enumeration is preserved: generic ``invalid_credentials`` for local
        locked/disabled/wrong-password; the exact reason is only in the audit log.
        """
        from lib.providers.ldap import auth as ldap_auth  # noqa: PLC0415
        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        ldap_cfg = cfg.get('ldap') or {}
        ldap_conn_error = False

        if ldap_cfg.get('enabled') and ldap_auth.is_available():
            existing = self._users.get(username, {})
            # LDAP for a known non-local (SSO/LDAP) user OR an unknown user; a known local
            # account skips LDAP and authenticates locally below.
            if existing.get('auth_source', 'local') != 'local' or not existing:
                attrs, reason = ldap_auth.authenticate(self, username, password)
                if attrs:
                    canonical = attrs.get('username') or username
                    user = ldap_auth.sync_user(self, canonical, attrs)
                    if user is None:
                        # sync refused (username collides with a local account) — generic reject.
                        return LoginResult(None, '', canonical, 'invalid_credentials',
                                           'ldap_account_conflict')
                    if not user.get('enabled', True):
                        return LoginResult(None, '', canonical, 'account_disabled',
                                           'account_disabled')
                    return LoginResult(user, 'ldap', canonical, '', '')
                # No LDAP match.
                if not existing:
                    # Unknown user: bad creds → reject; connection error → maybe fall back to local.
                    if reason in ('ldap_invalid_credentials', 'ldap_user_not_found'):
                        return LoginResult(None, '', username, 'invalid_credentials', reason)
                    if not ldap_cfg.get('fallback_to_local', True):
                        return LoginResult(None, '', username, 'ldap_connection_error', reason)
                    ldap_conn_error = True   # ldap_connection_error → fall through to local
                else:
                    # Known SSO/LDAP user: never fall through to local.
                    flash_key = ('ldap_connection_error' if reason == 'ldap_connection_error'
                                 else 'invalid_credentials')
                    return LoginResult(None, '', username, flash_key, reason)

        # Local authentication (also the LDAP-connection-error fallback for unknown users).
        user, reason = self._authenticate(username, password)
        if user:
            return LoginResult(user, user.get('auth_source') or 'local', username, '', '')
        if reason in ('account_locked', 'account_disabled'):
            flash_key = 'invalid_credentials'          # generic message (anti-enumeration)
        elif ldap_conn_error:
            flash_key = 'ldap_connection_error'        # local also failed → surface the LDAP error
        else:
            flash_key = 'invalid_credentials'
        return LoginResult(None, '', username, flash_key, reason)

    # ── post-auth outcome (shared by the login route AND the SSO provider routes) ──
    def _landing_url(self, user: dict) -> str:
        """Effective post-login URL by precedence: per-user → first group (alphabetical)
        with a landing set → global default. Maps a landing id (admin/status/…) to its URL
        via HOME_PAGES; unknown/empty ⇒ the admin panel ('/')."""
        by_id = {p['id']: p for p in HOME_PAGES}
        cand = str(user.get('landing_page') or '').strip()
        if cand not in by_id:
            glp = sorted(
                ((self._uid_to_group_label(g) or g, self._groups[g].get('landing_page', ''))
                 for g in user.get('groups', [])
                 if g in self._groups and self._groups[g].get('landing_page')),
                key=lambda x: str(x[0]).lower())
            cand = glp[0][1] if glp else ''
        if cand not in by_id:
            cand = str(getattr(self, '_landing_page', '') or '').strip()
        entry = by_id.get(cand) or by_id.get('admin')
        return (entry.get('url') if entry else '/') or '/'

    def _auth_method_label(self, auth_source, lang: str = '', cfg: dict = None) -> str:
        """Friendly name for how a user authenticated ('local'/'ldap'/'oidc'/…), localised
        (admin override honoured)."""
        src = str(auth_source or 'local').strip() or 'local'
        key = _AUTH_METHOD_KEYS.get(src)
        if key:
            from lib.core.notify.formatting import notify_text  # noqa: PLC0415
            return notify_text(cfg, lang, key)
        return src.upper()

    def _establish_session(self, username: str, user: dict, remember: bool = False) -> None:
        """Populate the Flask session after a successful authentication (local or any SSO
        provider), reset the per-IP login throttle and forward an ``auth_login`` notification."""
        # A successful auth clears the per-IP login throttle (legit users on a shared
        # NAT are never penalised by earlier failures).
        rl = getattr(self, '_login_ratelimit', None)
        if rl is not None:
            rl.reset(request.remote_addr or '?')
        session.permanent = remember
        token, uid = self._create_session(
            username, request.remote_addr, request.user_agent.string,
        )
        session['session_token'] = token
        session['session_id']    = uid
        session['logged_in']     = True
        session['username']      = username
        # Forward a successful login (any source: local/LDAP/OIDC/SAML/Teams) to the
        # notification router — opt-in per channel via the routing matrix (default off).
        # The auth method (Local / LDAP / SSO provider) is carried in both the status and
        # the message so the alert says *how* the user signed in.
        try:
            import time as _t  # noqa: PLC0415
            from lib.core.notify.notification_dispatcher import dispatch as _dispatch  # noqa: PLC0415,E501
            from lib.core.notify.formatting import notify_lang, notify_text  # noqa: PLC0415
            cfg = self._read_config_file(self._CONFIG_FILE) or {}
            lang = notify_lang(cfg)
            method = self._auth_method_label(user.get('auth_source'), lang, cfg)
            _dispatch(self, kind='auth_login', module='auth', item=username,
                      status=f"{notify_text(cfg, lang, 'notif_status_login')} · {method}",
                      message=notify_text(cfg, lang, 'notif_msg_auth_login', username, method,
                                          request.remote_addr),
                      timestamp=_t.strftime('%Y-%m-%d %H:%M:%S'))
        except Exception:  # pylint: disable=broad-except
            pass
        role_ref  = user.get('role', 'viewer')
        role_name = self._uid_to_role_name(role_ref) if self._is_uid(role_ref) else role_ref
        session['role']         = role_name or 'viewer'
        session['display_name'] = user.get('display_name', username)
        self._dbg(f"> Auth >> session established user={username!r} role={session['role']}",
                  DebugLevel.info)
        user_lang = user.get('lang')
        if user_lang and user_lang in SUPPORTED_LANGS:
            session['lang'] = user_lang
        user_dm = user.get('dark_mode')
        if user_dm is not None:
            session['dark_mode'] = user_dm
