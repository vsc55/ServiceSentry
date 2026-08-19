#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MFA routes: managing your own second factor, and taking somebody else's off.

Routes registered by this file:

    GET    /api/v1/account/mfa            what the signed-in account has (never the secret)
    POST   /api/v1/account/mfa/begin      start an enrolment — secret, link, QR
    POST   /api/v1/account/mfa/confirm    prove it with a code; answers the recovery codes ONCE
    POST   /api/v1/account/mfa/recovery   a fresh set of recovery codes
    POST   /api/v1/account/mfa/disable    turn it off (needs a current code)
    POST   /api/v1/account/mfa/webauthn/begin    options for registering a security key
    POST   /api/v1/account/mfa/webauthn/confirm  the registration response; stores the key
    DELETE /api/v1/users/<uid>/mfa        take somebody else's off (mfa_reset_others)

**No permission guards the first five.** Managing your own second factor is like changing your
own password: every account does it on its own page, and a flag there would be a way to stop
somebody protecting themselves. What is guarded is the last one, because removing another
account's factor is the operation that *lowers* protection.

Everything that changes state re-checks the caller. Turning MFA off asks for a current code —
otherwise a borrowed session is enough to strip the factor and the account is back to a
password somebody already has.
"""

import time

from flask import jsonify, request, session

from lib import APP_NAME
from lib.core.mfa import cose, webauthn
from lib.core.mfa import service as mfa_service

# How long a registration challenge is good for. Short on purpose: it is one round trip with a
# person touching a key in the middle, and a challenge that outlives the page it was issued for
# is a challenge somebody else can still answer.
WEBAUTHN_CHALLENGE_SECONDS = 300


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
        """What this account has, and whether a security key can be offered at all.

        No secret, ever — not even the encrypted one. `webauthn_ok` travels with the state
        rather than as a page-load constant because it is a fact about the INSTALLATION that
        the card has to act on: offering "add a security key" where a credential cannot be
        scoped produces a key that silently never works again, and `webauthn_reason` is what
        lets the screen say which of the three things is missing instead of just going quiet.
        """
        username, _uid = _me()
        scope = wa._webauthn_scope()
        return jsonify({'ok': True, **wa._mfa_status(username),
                        'webauthn_ok': bool(scope.get('ok')),
                        'webauthn_reason': scope.get('reason', '')})

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

    # ── Security keys ────────────────────────────────────────────────────────

    @app.route('/api/v1/account/mfa/webauthn/begin', methods=['POST'])
    @login_required
    def api_account_mfa_webauthn_begin():
        """What the browser needs to call `navigator.credentials.create()`.

        Refused rather than attempted when this install cannot scope a credential — no public
        URL, not https, or an RP ID the origin does not sit under. A key registered against a
        guess is one that silently never works again, and the browser's own error for it names
        nothing useful.

        The challenge is kept in the session, never sent back to be echoed: a challenge the
        client is trusted to return is not a challenge.
        """
        username, uid = _me()
        if not uid:
            return jsonify({'ok': False, 'error': 'unknown_user'}), 400
        scope = wa._webauthn_scope()
        if not scope.get('ok'):
            return jsonify({'ok': False, 'error': scope.get('reason') or 'unavailable'}), 400
        challenge = webauthn.new_challenge()
        session['webauthn_reg'] = {'challenge': challenge,
                                   'expires': time.time() + WEBAUTHN_CHALLENGE_SECONDS}
        user = wa._users.get(username) or {}
        return jsonify({
            'ok': True,
            'rp_id': scope['rp_id'],
            'rp_name': APP_NAME,
            'challenge': challenge,
            # base64url of the uid, because a WebAuthn user handle is BYTES. The uid and not
            # the name: a rename must not detach the key, exactly as for the TOTP row.
            'user_id': webauthn.b64u_encode(uid.encode()),
            'user_name': username,
            'user_display': user.get('display_name') or username,
            'algorithms': list(cose.SUPPORTED),
            'timeout_ms': WEBAUTHN_CHALLENGE_SECONDS * 1000,
        })

    @app.route('/api/v1/account/mfa/webauthn/confirm', methods=['POST'])
    @login_required
    def api_account_mfa_webauthn_confirm():
        """The registration response. Verified here and stored only if it holds.

        No second step after this one: the response was signed by the authenticator over a
        challenge this server issued, so the ceremony IS the proof. Asking for one more touch
        would be theatre.
        """
        username, uid = _me()
        data = request.get_json(silent=True) or {}
        held = session.pop('webauthn_reg', None) or {}   # one use, whatever the outcome
        if not held or float(held.get('expires') or 0) < time.time():
            return jsonify({'ok': False, 'error': 'no_challenge'}), 400
        scope = wa._webauthn_scope()
        if not scope.get('ok'):
            return jsonify({'ok': False, 'error': scope.get('reason') or 'unavailable'}), 400
        out = mfa_service.webauthn_register(
            wa._mfa_store, uid,
            attestation_object=webauthn.b64u_decode(str(data.get('attestation_object') or '')),
            client_data_json=webauthn.b64u_decode(str(data.get('client_data_json') or '')),
            challenge=held.get('challenge', ''),
            rp_id=scope['rp_id'], origin=scope['origin'],
            label=str(data.get('label') or '')[:64])
        if not out.get('ok'):
            # The `detail` says which check failed and goes to the LOG, never to the sender:
            # "wrong origin" and "wrong challenge" are two different pieces of help to give
            # somebody probing.
            wa._audit('mfa_failed', username, request.remote_addr,
                      detail={'stage': 'webauthn_register', 'error': out.get('error', ''),
                              'detail': out.get('detail', '')})
            wa._ipban_offense('login_failed')
            return jsonify({'ok': False, 'error': out.get('error', 'ceremony')}), 400
        wa._audit('mfa_enrolled', username, request.remote_addr, detail={'method': 'webauthn'})
        return jsonify({'ok': True, 'method': 'webauthn'})

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
