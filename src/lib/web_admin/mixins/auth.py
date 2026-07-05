#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local password authentication + account lockout for WebAdmin.

Verifies credentials against the DB-backed user store, enforces the per-account
lockout, and keeps every failure path timing-equal so a username cannot be
enumerated by response time (see :meth:`_timing_decoy_hash`)."""

from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from lib.debug import DebugLevel


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
