#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MFA routes: managing your own second factor, and taking somebody else's off.

Routes registered by this file:

    GET    /api/v1/account/mfa            what the signed-in account has (never the secret)
    POST   /api/v1/account/mfa/begin      start an enrolment — secret, link, QR
    POST   /api/v1/account/mfa/confirm    prove it with a code; answers the recovery codes ONCE
    POST   /api/v1/account/mfa/recovery   a fresh set of recovery codes
    POST   /api/v1/account/mfa/disable    turn it off (needs a current code)
    DELETE /api/v1/users/<uid>/mfa        take somebody else's off (mfa_reset_others)

**No permission guards the first five.** Managing your own second factor is like changing your
own password: every account does it on its own page, and a flag there would be a way to stop
somebody protecting themselves. What is guarded is the last one, because removing another
account's factor is the operation that *lowers* protection.

Everything that changes state re-checks the caller. Turning MFA off asks for a current code —
otherwise a borrowed session is enough to strip the factor and the account is back to a
password somebody already has.
"""

from flask import jsonify, request, session

from lib import APP_NAME
from lib.core.mfa import service as mfa_service


def register(app, wa):
    login_required = wa._login_required
    reset_req = wa._perm_required('mfa_reset_others')

    def _me() -> tuple:
        """`(username, user_uid)` for the signed-in account."""
        username = session.get('username', '')
        return username, wa._mfa_uid(username)

    @app.route('/api/v1/account/mfa', methods=['GET'])
    @login_required
    def api_account_mfa():
        """What this account has. Three facts and no secret — not even the encrypted one."""
        username, _uid = _me()
        return jsonify({'ok': True, **wa._mfa_status(username)})

    @app.route('/api/v1/account/mfa/begin', methods=['POST'])
    @login_required
    def api_account_mfa_begin():
        """Start an enrolment: a fresh secret, the `otpauth:` link, the QR and the string.

        Both ways in, always. The square is what anybody actually uses; the base32 beside it
        is the half somebody can read back — and the only one left when the camera will not
        focus or the phone has none.

        Restarting replaces whatever was pending, so somebody who closed the page halfway gets
        a new secret rather than one that may be sitting in a screenshot.
        """
        username, uid = _me()
        if not uid:
            return jsonify({'ok': False, 'error': 'unknown_user'}), 400
        if wa._mfa_enrolled(username):
            # Already on. Replacing it is "turn it off and start again", which asks for a
            # current code — silently overwriting a working factor from a borrowed session is
            # the whole attack this endpoint would otherwise be.
            return jsonify({'ok': False, 'error': 'already_enrolled'}), 409
        out = mfa_service.enroll_begin(wa._mfa_store, uid, username, APP_NAME)
        if not out.get('ok'):
            return jsonify(out), 503 if out.get('error') == 'no_key' else 400
        return jsonify(out)

    @app.route('/api/v1/account/mfa/confirm', methods=['POST'])
    @login_required
    def api_account_mfa_confirm():
        """Prove the pending enrolment and switch it on.

        The recovery codes come back HERE and only here. Not at `begin`: an enrolment somebody
        abandoned would have left a working set behind it — a way into an account whose owner
        believes they never finished.
        """
        username, uid = _me()
        data = request.get_json(silent=True) or {}
        out = mfa_service.enroll_confirm(wa._mfa_store, uid, str(data.get('code') or ''))
        if not out.get('ok'):
            wa._audit('mfa_failed', username, request.remote_addr,
                      detail={'stage': 'enrol', 'error': out.get('error', '')})
            wa._ipban_offense('login_failed')
            return jsonify(out), 400
        wa._audit('mfa_enrolled', username, request.remote_addr, detail={'method': 'totp'})
        return jsonify(out)

    @app.route('/api/v1/account/mfa/recovery', methods=['POST'])
    @login_required
    def api_account_mfa_recovery():
        """A fresh set of recovery codes, replacing the old one whole.

        A current code is required: this is what somebody does when they think the old list
        leaked, and it must not be something a borrowed session can do — regenerating from one
        would hand the attacker ten permanent ways back in.
        """
        username, uid = _me()
        data = request.get_json(silent=True) or {}
        code = str(data.get('code') or '')
        if not mfa_service.verify(wa._mfa_store, uid, code):
            # `empty` and `bad_code` are one audit line apart and are two different stories: a
            # form submitted with nothing in it is somebody in a hurry, and a run of wrong
            # codes is somebody guessing. On the wire both stay `bad_code` — which of the two
            # it was is not something to tell whoever is sending them.
            wa._audit('mfa_failed', username, request.remote_addr,
                      detail={'stage': 'recovery', 'error': 'empty' if not code else 'bad_code'})
            wa._ipban_offense('login_failed')
            return jsonify({'ok': False, 'error': 'bad_code'}), 403
        out = mfa_service.recovery_regenerate(wa._mfa_store, uid)
        if not out.get('ok'):
            # This branch used to answer 400 and record NOTHING, which is the worst place to
            # be silent: the code was right, so it is not the person — it is the factor gone
            # between two requests, or a database that would not take the write. Both are
            # invisible from the browser, and the second is invisible everywhere else too.
            wa._audit('mfa_failed', username, request.remote_addr,
                      detail={'stage': 'recovery', 'error': out.get('error', '')})
            return jsonify(out), 400
        wa._audit('mfa_recovery_regenerated', username, request.remote_addr)
        return jsonify(out)

    @app.route('/api/v1/account/mfa/disable', methods=['POST'])
    @login_required
    def api_account_mfa_disable():
        """Turn it off — with a current code, never on the session alone.

        A POST and not a DELETE because it carries one: the code. This project's `apiDelete`
        sends no body, and a one-time code in a query string is a one-time code in an access
        log.

        A session is exactly what an attacker has when they have borrowed one, and without
        this check the first thing they would do is take the second factor off and leave the
        account on a password they already know.
        """
        username, uid = _me()
        data = request.get_json(silent=True) or {}
        code = str(data.get('code') or '')
        if not wa._mfa_enrolled(username):
            wa._audit('mfa_failed', username, request.remote_addr,
                      detail={'stage': 'disable', 'error': 'not_enrolled'})
            return jsonify({'ok': False, 'error': 'not_enrolled'}), 400
        if not mfa_service.verify(wa._mfa_store, uid, code):
            wa._audit('mfa_failed', username, request.remote_addr,
                      detail={'stage': 'disable', 'error': 'empty' if not code else 'bad_code'})
            wa._ipban_offense('login_failed')
            return jsonify({'ok': False, 'error': 'bad_code'}), 403
        wa._mfa_store.delete(uid)
        wa._audit('mfa_disabled', username, request.remote_addr)
        return jsonify({'ok': True})

    @app.route('/api/v1/users/<uid>/mfa', methods=['DELETE'])
    @reset_req
    def api_user_mfa_reset(uid):
        """Take another account's second factor off — the supported way back in.

        Behind its own permission, granted to nobody by default: it is what an administrator
        does for somebody who lost their phone AND their codes, and it is also what an
        attacker with `users_edit` would do to strip the protection before going after the
        password. Deliberate, or not at all.
        """
        username, _rec = wa._uid_to_username(str(uid or ''))
        if not username:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if not wa._mfa_reset(username, actor=session.get('username', ''),
                             reason=str((request.get_json(silent=True) or {}).get('reason') or '')):
            return jsonify({'ok': False, 'error': 'not_enrolled'}), 400
        return jsonify({'ok': True})
