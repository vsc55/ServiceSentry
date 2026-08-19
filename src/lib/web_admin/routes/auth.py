#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authentication routes: /login, /logout.

Routes registered by this file:

    GET,POST /login      login form (GET) / authenticate (POST) — local + LDAP/OIDC/SAML
    GET,POST /login/mfa  the second factor, when the account has one. NOT a session yet:
                         the password was accepted and nothing was created until this passes
    GET,POST /login/mfa/enrol  enrolment on the way in, when the policy covers this account
                         and it has none — refusing instead would lock out everybody who has
                         not enrolled, which the moment a policy is switched on is everybody
    POST     /logout     end the current session
"""

from flask import flash, redirect, render_template, request, session, url_for

from lib.core.mfa import service as mfa_service
from lib.debug import DebugLevel
from lib.security.ratelimit import RateLimiter

# Per-IP login throttle thresholds come from config (web_admin|login_ratelimit_*,
# attrs _LOGIN_RATELIMIT_MAX / _LOGIN_RATELIMIT_WINDOW_SECS; 0 = disabled) — a brute-force speed bump
# on top of the per-account lockout (stops single-IP password spraying).


def register(app, wa):

    if not hasattr(wa, '_login_ratelimit'):
        wa._login_ratelimit = RateLimiter()

    # Auth lives in web_admin (outside the notify-events discovery roots), so it declares
    # its notification events with the manual registry — the same escape hatch any code has.
    from lib.core.notify.events import register_event  # noqa: PLC0415
    for _key, _label, _order in (('auth_login', 'notif_event_auth_login', 50),
                                 ('auth_login_failed', 'notif_event_auth_login_failed', 51),
                                 ('auth_account_locked', 'notif_event_auth_locked', 52)):
        register_event({'key': _key, 'source': 'auth', 'label_key': _label,
                        'matrix': True, 'order': _order})

    def _login_ok(username, source, remember=False):
        """Audit a successful login (with source/role/remember) + info debug line."""
        role = session.get('role', '')
        wa._dbg(f"> Auth >> login OK user={username!r} source={source} role={role!r} "
                f"from {request.remote_addr}", DebugLevel.info)
        wa._audit('login_ok', username, request.remote_addr,
                  detail={'auth_source': source, 'role': role, 'remember': bool(remember)})

    def _login_failed(username, reason):
        """Audit a failed login + **warning** debug line (visible at the default level)."""
        wa._dbg(f"> Auth >> login FAILED user={username!r} reason={reason} "
                f"from {request.remote_addr}", DebugLevel.warning)
        wa._audit('login_failed', username, request.remote_addr, detail={'reason': reason})
        # Forward to the notification router (opt-in matrix): a lock is its own kind.
        try:
            import time as _t  # noqa: PLC0415
            from lib.core.notify.notification_dispatcher import dispatch as _dispatch  # noqa: PLC0415,E501
            from lib.core.notify.formatting import notify_lang, notify_text  # noqa: PLC0415
            _kind = 'auth_account_locked' if reason == 'account_locked' else 'auth_login_failed'
            _cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
            _lang = notify_lang(_cfg)
            _st = 'notif_status_locked' if _kind == 'auth_account_locked' else 'notif_status_failed'
            _dispatch(wa, kind=_kind, module='auth', item=username or (request.remote_addr or '?'),
                      status=notify_text(_cfg, _lang, _st),
                      message=notify_text(_cfg, _lang, 'notif_msg_auth_failed', username or '?',
                                          reason, request.remote_addr),
                      timestamp=_t.strftime('%Y-%m-%d %H:%M:%S'))
        except Exception:  # pylint: disable=broad-except
            pass
        # Feed the internal fail2ban (progressive per-IP jail) — every failed login,
        # whatever the reason, is one 'auth'-track offense.
        wa._ipban_offense('login_failed')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Login page."""
        if session.get('logged_in'):
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            # Per-IP brute-force throttle (before any credential work). Config-driven
            # thresholds (0 = disabled).
            _ip = request.remote_addr or '?'
            _ok, _retry = wa._login_ratelimit.hit(_ip, wa._LOGIN_RATELIMIT_MAX, wa._LOGIN_RATELIMIT_WINDOW_SECS)
            if not _ok:
                wa._audit('login_throttled', '', _ip, detail={'retry_after': _retry})
                wa._ipban_offense('login_throttled')
                flash(wa._t('login_throttled'), 'danger')
                return redirect(url_for('login'))
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            remember = request.form.get('remember_me') == 'on'
            wa._dbg(f"> Auth >> login attempt user={username!r} from {request.remote_addr}",
                    DebugLevel.info)

            # Resolve the attempt (LDAP when enabled → local) with no web concern; the
            # decision + the previously-duplicated LDAP branches live in
            # _AuthMixin.resolve_login.  Here we only map the result to session/audit/flash.
            result = wa.resolve_login(username, password)
            if result.user:
                # False means the password was right and the account owes a second factor.
                # Nothing has been created — no session row, no `logged_in` — so the browser
                # is still anonymous while it is on the next page.
                if not wa._establish_session(result.username, result.user, remember,
                                             source=result.source):
                    # Two ways to owe a second factor: having one to prove, or having to set
                    # one up because the installation's policy covers this account.
                    return redirect(url_for('login_mfa_enrol')
                                    if wa._mfa_must_enrol(result.username, result.source)
                                    else url_for('login_mfa'))
                _login_ok(result.username, result.source, remember)
                return redirect(wa._landing_url(result.user))
            _login_failed(result.username, result.reason)
            flash(wa._t(result.flash_key), 'danger')
            return redirect(url_for('login'))

        return render_template('login.html')

    @app.route('/login/mfa', methods=['GET', 'POST'])
    def login_mfa():
        """The second half of a sign-in: the code, and nothing else.

        Reached only with a parked sign-in in the cookie — the password was accepted and no
        session was created. Anything else here is somebody who arrived at the URL directly,
        and the answer is the login page, not a hint about what is missing.

        A failed code is fed to the same two places a failed password is: the audit log and
        the fail2ban jail. Six digits guessed one at a time is otherwise a *cheaper* attack
        than a password, and it happens against an account whose password is already known.
        """
        held = wa._mfa_pending()
        if session.get('logged_in'):
            return redirect(url_for('dashboard'))
        if not held:
            return redirect(url_for('login'))
        if request.method == 'POST':
            _ip = request.remote_addr or '?'
            _ok, _retry = wa._login_ratelimit.hit(_ip, wa._LOGIN_RATELIMIT_MAX,
                                                  wa._LOGIN_RATELIMIT_WINDOW_SECS)
            if not _ok:
                wa._audit('login_throttled', held.get('username', ''), _ip,
                          detail={'retry_after': _retry, 'stage': 'mfa'})
                wa._ipban_offense('login_throttled')
                flash(wa._t('login_throttled'), 'danger')
                return redirect(url_for('login_mfa'))
            username = held.get('username', '')
            kind = wa._mfa_verify_pending(request.form.get('code', ''))
            if not kind:
                wa._dbg(f"> Auth/MFA >> second factor FAILED user={username!r} "
                        f"from {request.remote_addr}", DebugLevel.warning)
                wa._audit('mfa_failed', username, request.remote_addr,
                          detail={'source': held.get('source', '')})
                wa._ipban_offense('login_failed')
                flash(wa._t('mfa_step_bad_code'), 'danger')
                return redirect(url_for('login_mfa'))
            user = wa._users.get(username) or {}
            # The account can have gone away — or been disabled — between the password and
            # the code. This is the second half of an authentication, so it re-reads rather
            # than trusting what the first half saw.
            if not user or not user.get('enabled', True):
                wa._mfa_clear()
                _login_failed(username, 'account_disabled')
                flash(wa._t('invalid_credentials'), 'danger')
                return redirect(url_for('login'))
            # A recovery code is either the owner in trouble or somebody who should not be
            # there, and it is the one sign-in worth telling the account about.
            if kind == 'recovery':
                left = wa._mfa_status(username).get('recovery_left', 0)
                wa._audit('mfa_recovery_used', username, request.remote_addr,
                          detail={'remaining': left})
            wa._mfa_clear()
            wa._establish_session(username, user, bool(held.get('remember')),
                                  source=held.get('source', 'local'), second_factor_done=True)
            _login_ok(username, held.get('source', 'local'), held.get('remember'))
            return redirect(wa._landing_url(user))
        return render_template('login_mfa.html')

    @app.route('/login/mfa/enrol', methods=['GET', 'POST'])
    def login_mfa_enrol():
        """Enrolment on the way in, for an account the policy covers and that has none.

        This is what makes `mfa_required` safe to switch on. Refusing the sign-in instead
        would lock out everybody who has not enrolled yet — which, the moment the policy is
        turned on, is everybody, the last administrator included.

        The account is one password away from here, and that is worth saying plainly: whoever
        has the password can enrol THEIR authenticator. It is the same exposure a password
        reset flow carries, it is audited and it notifies, and the alternative — an
        out-of-band enrolment step — is a feature nobody would switch on.
        """
        held = wa._mfa_pending()
        if session.get('logged_in'):
            return redirect(url_for('dashboard'))
        if not held:
            return redirect(url_for('login'))
        username = held.get('username', '')
        # Somebody who already has a factor belongs on the other page — and must not be able
        # to reach a screen that mints a new secret with only a password.
        if wa._mfa_enrolled(username):
            return redirect(url_for('login_mfa'))
        user = wa._users.get(username) or {}
        if not user or not user.get('enabled', True):
            wa._mfa_clear()
            return redirect(url_for('login'))
        uid = wa._mfa_uid(username)
        if request.method == 'POST':
            _ip = request.remote_addr or '?'
            _ok, _retry = wa._login_ratelimit.hit(_ip, wa._LOGIN_RATELIMIT_MAX,
                                                  wa._LOGIN_RATELIMIT_WINDOW_SECS)
            if not _ok:
                wa._audit('login_throttled', username, _ip,
                          detail={'retry_after': _retry, 'stage': 'mfa_enrol'})
                wa._ipban_offense('login_throttled')
                flash(wa._t('login_throttled'), 'danger')
                return redirect(url_for('login_mfa_enrol'))
            done = mfa_service.enroll_confirm(wa._mfa_store, uid,
                                              request.form.get('code', ''))
            if not done.get('ok'):
                wa._audit('mfa_failed', username, request.remote_addr,
                          detail={'stage': 'forced_enrol', 'error': done.get('error', '')})
                wa._ipban_offense('login_failed')
                flash(wa._t('mfa_step_bad_code'), 'danger')
                return redirect(url_for('login_mfa_enrol'))
            wa._audit('mfa_enrolled', username, request.remote_addr,
                      detail={'method': 'totp', 'forced': True})
            wa._mfa_clear()
            wa._establish_session(username, user, bool(held.get('remember')),
                                  source=held.get('source', 'local'), second_factor_done=True)
            _login_ok(username, held.get('source', 'local'), held.get('remember'))
            # The codes are shown ONCE and there is no way back from the stored form, so the
            # page does not move on by itself — the reader presses Continue.
            return render_template('login_mfa_enrol.html', recovery=done['recovery'],
                                   landing=wa._landing_url(user))
        # A fresh secret on every GET: somebody who closed the page halfway must not be handed
        # the one that may be sitting in a screenshot.
        out = mfa_service.enroll_begin(wa._mfa_store, uid, username)
        if not out.get('ok'):
            # Unreachable while `_mfa_policy` fails safe, and left here because the two would
            # have to be wrong together for it to matter: a policy that demands what cannot be
            # stored must say so rather than loop.
            wa._mfa_clear()
            flash(wa._t('mfa_required_no_key'), 'danger')
            return redirect(url_for('login'))
        return render_template('login_mfa_enrol.html', recovery=None, **out)

    @app.route('/logout', methods=['POST'])
    def logout():
        """Log out and redirect to login page (POST-only + CSRF → no logout-CSRF)."""
        token = session.get('session_token')
        uname = session.get('username', '')
        if token:
            wa._revoke_session(token)
        wa._dbg(f"> Auth >> logout user={uname!r} from {request.remote_addr}", DebugLevel.info)
        wa._audit('logout', uname, request.remote_addr,
                  detail={'uid': session.get('session_id', ''),
                          'role': session.get('role', '')})
        session.clear()
        return redirect(url_for('login'))
