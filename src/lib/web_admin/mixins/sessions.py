#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session registry mixin for WebAdmin."""

import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import request, session


class _SessionsMixin:
    """Flask session registry (persistent, server-side) + secret key helpers."""

    # Idle timeout comes from config `web_admin|session_idle_minutes`
    # (attr _SESSION_IDLE_MINUTES; 0 = disabled). The absolute cap is
    # _REMEMBER_ME_DAYS (from `created`). Both are enforced on every request in
    # _check_session, so a stolen token is not valid indefinitely.

    # ------------------------------------------------------------------ #
    # Secret key                                                           #
    # ------------------------------------------------------------------ #

    @property
    def _secret_key_path(self) -> str:
        return os.path.join(self._config_dir, self._SECRET_KEY_FILE)

    def _load_or_create_secret_key(self) -> str:
        """Load the Flask secret key from disk, or generate a new one."""
        path = self._secret_key_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    key = fh.read().strip()
                if key:
                    return key
            except OSError:
                pass
        key = secrets.token_hex(32)
        self._save_secret_key(key)
        return key

    def _save_secret_key(self, key: str) -> None:
        """Write the secret key to disk with owner-only permissions.

        This file signs Flask sessions AND derives the Fernet key for every stored
        secret, so it must never be world-readable."""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            path = self._secret_key_path
            # Create with 0o600 from the start (avoids a brief world-readable window).
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(path, flags, 0o600)
            try:
                os.write(fd, key.encode('utf-8'))
            finally:
                os.close(fd)
            try:
                os.chmod(path, 0o600)      # tighten an existing file too (no-op on Windows)
            except OSError:
                pass
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Session registry                                                     #
    # ------------------------------------------------------------------ #

    def _load_sessions(self) -> None:
        """Load active sessions from the DB and discard expired ones."""
        data = self._sessions_store.load()
        if data:
            self._sessions = data
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self._REMEMBER_ME_DAYS)
        ).isoformat()
        stale = [
            t for t, s in self._sessions.items()
            if s.get('last_seen', '') < cutoff
        ]
        for t in stale:
            del self._sessions[t]
        if stale:
            self._persist_sessions()

    def _persist_sessions(self) -> bool:
        """Write sessions registry to the database (columnar sessions table)."""
        return self._sessions_store.save_all(self._sessions)

    def _create_session(
        self, username: str, ip: str, user_agent: str,
    ) -> tuple[str, str]:
        """Register a new session and return (token, uid)."""
        token    = secrets.token_hex(32)
        uid      = secrets.token_hex(8)
        now      = datetime.now(timezone.utc).isoformat()
        user_uid = (self._users.get(username) or {}).get('uid', username)
        entry = {
            'uid':        uid,
            'user_uid':   user_uid,
            'created':    now,
            'last_seen':  now,
            'ip':         ip,
            'user_agent': user_agent,
        }
        self._sessions[token] = entry
        # Single-row insert instead of rewriting the whole sessions table.
        self._sessions_store.upsert(token, entry)
        return token, uid

    def _check_session(self) -> bool:
        """Validate the current request's session against the registry."""
        if not session.get('logged_in'):
            return False
        token = session.get('session_token')
        if not token or token not in self._sessions:
            session.clear()
            return False
        entry     = self._sessions[token]
        user_uid  = entry.get('user_uid', '')
        # Resolve uid → (username, user_record)
        uname, user_rec = self._uid_to_username(user_uid)
        if uname is None:
            uname = session.get('username', '')
            user_rec = self._users.get(uname)
        if user_rec is None or not user_rec.get('enabled', True):
            del self._sessions[token]
            self._sessions_store.delete(token)
            session.clear()
            return False
        # Idle + absolute lifetime enforcement — a stolen/forgotten session must not
        # stay valid forever.
        now = datetime.now(timezone.utc)
        idle = int(self._SESSION_IDLE_MINUTES or 0) * 60

        def _age(field):
            ts = entry.get(field)
            if not ts:
                return None
            try:
                return (now - datetime.fromisoformat(ts)).total_seconds()
            except (ValueError, TypeError):
                return None

        idle_age = _age('last_seen')
        abs_age  = _age('created')
        max_abs  = self._REMEMBER_ME_DAYS * 86400
        if (idle and idle_age is not None and idle_age > idle) or \
           (abs_age is not None and abs_age > max_abs):
            del self._sessions[token]
            self._sessions_store.delete(token)
            self._audit('session_expired', username=uname, ip=request.remote_addr,
                        detail={'uid': entry.get('uid', token[:8]),
                                'reason': 'idle' if (idle and idle_age and idle_age > idle) else 'absolute'})
            session.clear()
            return False
        if 'session_id' not in session:
            session['session_id'] = entry.get('uid', token[:16])
        current_ip = request.remote_addr
        if entry.get('ip') and entry['ip'] != current_ip:
            self._audit(
                'session_ip_changed',
                username=uname,
                ip=current_ip,
                detail={
                    'uid': entry.get('uid', token[:8]),
                    'previous_ip': entry['ip'],
                    'current_ip': current_ip,
                },
            )
            entry['ip'] = current_ip
        entry['last_seen'] = datetime.now(timezone.utc).isoformat()
        return True

    def _revoke_session(self, token: str) -> bool:
        """Remove a single session from the registry (by its secret token)."""
        if token in self._sessions:
            del self._sessions[token]
            self._sessions_store.delete(token)
            return True
        return False

    def _revoke_session_by_uid(self, uid: str) -> bool:
        """Revoke a session by its public ``uid`` (the PK the UI knows — the token is
        server-only). Drops the in-memory entry and deletes the row by uid."""
        if not uid:
            return False
        token = next((t for t, e in self._sessions.items() if e.get('uid') == uid), None)
        if token is not None:
            del self._sessions[token]
        # Delete by uid too, so a stale in-memory cache (or another process's write)
        # is still cleaned up.
        deleted_db = self._sessions_store.delete_by_uid(uid)
        return token is not None or deleted_db

    def _uid_to_username(self, uid: str) -> tuple[str | None, dict | None]:
        """Return (username, user_dict) for a user UID, or (None, None)."""
        for uname, d in self._users.items():
            if d.get('uid') == uid:
                return uname, d
        return None, None

    def _revoke_user_sessions(self, username: str, except_token: str | None = None) -> int:
        """Remove all sessions belonging to *username*. Returns count.

        ``except_token`` keeps one session alive (used on self password-change so the
        user isn't logged out of the very session performing the change)."""
        user_uid = (self._users.get(username) or {}).get('uid', '')
        if not user_uid:
            return 0
        tokens = [
            t for t, s in self._sessions.items()
            if s.get('user_uid') == user_uid and t != except_token
        ]
        for t in tokens:
            del self._sessions[t]
        if tokens:
            if except_token is None:
                self._sessions_store.delete_by_user_uid(user_uid)   # single query
            else:
                for t in tokens:
                    self._sessions_store.delete(t)
        return len(tokens)

    def _revoke_all_sessions(self) -> int:
        """Remove every session from the registry. Returns count."""
        count = len(self._sessions)
        self._sessions.clear()
        self._persist_sessions()
        return count
