#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The second factor as the web admin sees it: the half-finished login, and who owns a factor.

The one thing worth reading here is :meth:`_MfaMixin._mfa_hold`. A password that has been
accepted but not yet seconded is **not a session**: no row in the sessions table, no
``logged_in``, nothing ``_login_required`` will let through. It is a short-lived note in the
Flask cookie saying who is halfway in, and it expires on its own.

That shape is the whole security of the step. The obvious alternative — create the session and
set a ``needs_mfa`` flag on it — puts a real, revocable, API-usable session in an attacker's
hands the moment they have the password, and makes every gate in the panel responsible for
checking one more field. Here there is nothing to check: until the code verifies, the request
is anonymous, and it is anonymous by having no session rather than by everybody remembering.
"""

from __future__ import annotations

import time

from flask import session

from lib.core.mfa import service as mfa_service
from lib.debug import DebugLevel

# How long somebody has to reach for their phone. Long enough to unlock it and find the app,
# short enough that a password typed on a shared machine does not stay half-usable for the
# afternoon.
HOLD_SECONDS = 300


class _MfaMixin:
    """Second-factor state on the WebAdmin. The store is created in :mod:`.mixins.stores`."""

    # ── Who has one ──────────────────────────────────────────────────────────

    def _mfa_uid(self, username: str) -> str:
        """A username as the uid the factor is keyed by — never the name.

        The same reason sessions key on uid: a rename must not detach somebody's second factor,
        and it must not attach it to whoever takes the name next.
        """
        return str((self._users.get(str(username or '')) or {}).get('uid') or '')

    def _mfa_status(self, username: str) -> dict:
        """`{'enrolled', 'pending', 'recovery_left', …}` — no secret, ever."""
        store = getattr(self, '_mfa_store', None)
        uid = self._mfa_uid(username)
        if store is None or not uid:
            return {'enrolled': False, 'pending': False, 'method': '', 'since': '',
                    'recovery_left': 0}
        return mfa_service.status(store, uid)

    def _mfa_enrolled(self, username: str) -> bool:
        return bool(self._mfa_status(username).get('enrolled'))

    def _mfa_policy(self) -> str:
        """`'off'`, `'admins'` or `'all'` — who this installation makes carry a second factor.

        **Fails safe, and that is the whole reason this is a method.** A policy that demanded a
        factor on an install where secrets cannot be encrypted would demand something nobody
        can enrol: `MfaStore` refuses to write a seed it cannot protect, so every account that
        had not already enrolled would be shut out, including the last administrator. Read as
        `off` in that case whatever the config says, and said out loud — the alternative is an
        installation nobody can open and a setting that looks correct.

        Read from the config each time rather than mirrored on an attribute: it is consulted
        once per sign-in, and an attribute would be a second copy every save has to refresh.
        """
        from lib.config.spec import cfg_default        # noqa: PLC0415
        section = self._config_section('web_admin') if hasattr(self, '_config_section') else {}
        want = str((section or {}).get('mfa_required')
                   or cfg_default('web_admin|mfa_required') or 'off')
        if want not in ('off', 'admins', 'all'):
            return 'off'
        if want != 'off' and getattr(self, '_mfa_store', None) is not None \
                and self._mfa_store._fernet is None:
            self._dbg('> MFA >> `mfa_required` is set but secrets cannot be encrypted on this '
                      'install — the policy is being ignored, because enforcing it would lock '
                      'out every account that has not already enrolled', DebugLevel.warning)
            return 'off'
        return want

    def _mfa_policy_applies(self, username: str) -> bool:
        """Does the installation's policy cover THIS account?

        `admins` means an administrator however they became one — by their own role or through
        a group carrying it. Asking only the account's own role is the bug the August audit
        found in four other guards, and repeating it here would leave the accounts the policy
        exists to protect as the ones it skipped.
        """
        policy = self._mfa_policy()
        if policy == 'all':
            return True
        if policy != 'admins':
            return False
        from lib.core.users import service as users_svc   # noqa: PLC0415
        user = self._users.get(str(username or '')) or {}
        return bool(user) and users_svc.user_is_admin(user, self._groups)

    def _mfa_must_enrol(self, username: str, source: str = 'local') -> bool:
        """The policy covers this account and it has no factor — enrol on the way in.

        Not "refuse the sign-in": that would mean switching the policy on locks out everybody
        who has not enrolled yet, which on a fresh policy is everybody. The forced enrolment IS
        the way in, and it is what makes this safe to turn on.
        """
        _ = source
        return self._mfa_policy_applies(username) and not self._mfa_enrolled(username)

    def _mfa_required(self, username: str, source: str = 'local') -> bool:
        """Does this sign-in owe a second factor — either verifying one or setting one up?

        An account with a factor always verifies it, whatever the policy says: turning the
        policy off must not silently stop honouring the ones people already set up.

        *source* is already threaded through so that per-provider policy has one place to land:
        an account that arrived through an IdP which enforces MFA itself should not be asked
        twice, and that is a switch per provider rather than a rule written here.
        """
        return self._mfa_enrolled(username) or self._mfa_must_enrol(username, source)

    # ── The half-finished login ──────────────────────────────────────────────

    def _mfa_hold(self, username: str, source: str, remember: bool) -> None:
        """Park a sign-in that still owes a second factor.

        Deliberately NOT a session: no row, no ``logged_in``, nothing any gate will accept.
        The Flask cookie is signed, so the browser cannot promote itself — and the only thing
        it names is the username, which whoever typed the password already knows.
        """
        session['mfa_pending'] = {
            'username': str(username or ''),
            'source': str(source or 'local'),
            'remember': bool(remember),
            'expires': time.time() + HOLD_SECONDS,
        }

    def _mfa_pending(self) -> dict:
        """The parked sign-in, or `{}` — expired ones clear themselves on the way out."""
        held = session.get('mfa_pending') or {}
        if not isinstance(held, dict) or not held.get('username'):
            return {}
        if float(held.get('expires') or 0) < time.time():
            session.pop('mfa_pending', None)
            return {}
        return held

    def _mfa_clear(self) -> None:
        session.pop('mfa_pending', None)

    def _mfa_verify_pending(self, code: str) -> str:
        """`'totp'`, `'recovery'` or `''` for the parked sign-in.

        Does not establish anything: the caller decides what a success means, because the same
        check serves the login step and (later) a re-authentication in front of something
        dangerous.
        """
        held = self._mfa_pending()
        store = getattr(self, '_mfa_store', None)
        uid = self._mfa_uid(held.get('username', '')) if held else ''
        if store is None or not uid:
            return ''
        return mfa_service.verify(store, uid, code)

    # ── Taking one off ───────────────────────────────────────────────────────

    def _mfa_reset(self, username: str, *, actor: str = '', reason: str = '') -> bool:
        """Remove an account's second factor, codes and all, and say so in the audit log.

        The one operation that lowers an account's protection without its owner proving
        anything, so it is never silent: the line names who did it and to whom. It is also the
        supported way back in for somebody who lost their phone AND their codes — which is why
        the CLI can reach it from the machine, where the alternative is an installation nobody
        can open again.
        """
        store = getattr(self, '_mfa_store', None)
        uid = self._mfa_uid(username)
        if store is None or not uid:
            return False
        gone = store.delete(uid)
        if gone:
            self._audit('mfa_reset_by_admin', actor or username,
                        detail={'user': str(username or ''), 'reason': reason or ''})
        return gone
