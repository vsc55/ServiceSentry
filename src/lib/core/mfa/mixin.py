#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The second factor as the web admin sees it: the half-finished login, and who owns a factor.

WHO MUST carry one is next door, in :mod:`.policy` — that half reads config and answers yes or
no without touching a request, so it is testable without an app. This half is the one that
needs Flask: it keeps the sign-in that is halfway in.

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

# How long somebody has to reach for their phone, when the installation has not said. The
# setting is `web_admin|mfa_hold_secs`; this is the fallback for a caller with no config — the
# CLI, a test — and the default the registry declares is the same number, read from there.
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
            'expires': time.time() + self._mfa_hold_secs(),
        }

    def _mfa_hold_secs(self) -> int:
        """How long the parked sign-in lives, from `web_admin|mfa_hold_secs`.

        Clamped to the range the registry declares rather than trusted: a zero here would
        expire the hold before the page rendered, and the failure would look like a wrong code
        rather than like a setting. A value that cannot be read as a number falls back to the
        default, for the same reason.
        """
        from lib.config.spec import cfg_default          # noqa: PLC0415
        section = self._config_section('web_admin') if hasattr(self, '_config_section') else {}
        try:
            want = int((section or {}).get('mfa_hold_secs',
                                           cfg_default('web_admin|mfa_hold_secs')))
        except (TypeError, ValueError):
            return HOLD_SECONDS
        return max(30, min(3600, want))

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
