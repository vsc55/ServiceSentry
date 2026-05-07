#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session registry mixin for WebAdmin."""

import json
import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone

from flask import request, session


class _SessionsMixin:
    """Flask session registry (persistent, server-side) + secret key helpers."""

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
        """Write the secret key to disk."""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._secret_key_path, 'w', encoding='utf-8') as fh:
                fh.write(key)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Session registry                                                     #
    # ------------------------------------------------------------------ #

    @property
    def _sessions_path(self) -> str:
        return os.path.join(self._config_dir, self._SESSIONS_FILE)

    def _load_sessions(self) -> None:
        """Load active sessions from disk and discard expired ones."""
        path = self._sessions_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    self._sessions = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._sessions = {}
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
        # Migrate sessions created before sid was introduced
        migrated = False
        for entry in self._sessions.values():
            if 'sid' not in entry:
                entry['sid'] = secrets.token_hex(8)
                migrated = True
        if migrated:
            self._persist_sessions()

    def _persist_sessions(self) -> bool:
        """Write sessions registry to disk atomically."""
        tmp_path = None
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', dir=self._config_dir,
                suffix='.tmp', delete=False,
            ) as tmp:
                json.dump(self._sessions, tmp, indent=4, ensure_ascii=False)
                tmp_path = tmp.name
            os.replace(tmp_path, self._sessions_path)
            return True
        except OSError:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return False

    def _create_session(
        self, username: str, ip: str, user_agent: str,
    ) -> tuple[str, str]:
        """Register a new session and return (token, sid)."""
        token = secrets.token_hex(32)
        sid = secrets.token_hex(8)
        now = datetime.now(timezone.utc).isoformat()
        self._sessions[token] = {
            'sid': sid,
            'username': username,
            'created': now,
            'last_seen': now,
            'ip': ip,
            'user_agent': user_agent,
        }
        self._persist_sessions()
        return token, sid

    def _check_session(self) -> bool:
        """Validate the current request's session against the registry."""
        if not session.get('logged_in'):
            return False
        token = session.get('session_token')
        if not token or token not in self._sessions:
            session.clear()
            return False
        entry = self._sessions[token]
        # Kick disabled users immediately
        uname = entry.get('username', session.get('username', ''))
        if not self._users.get(uname, {}).get('enabled', True):
            del self._sessions[token]
            self._persist_sessions()
            session.clear()
            return False
        if 'session_id' not in session:
            session['session_id'] = entry.get('sid', token[:16])
        current_ip = request.remote_addr
        if entry.get('ip') and entry['ip'] != current_ip:
            self._audit(
                'session_ip_changed',
                username=entry.get('username', ''),
                ip=current_ip,
                detail={
                    'sid': entry.get('sid', token[:8]),
                    'previous_ip': entry['ip'],
                    'current_ip': current_ip,
                },
            )
            entry['ip'] = current_ip
        entry['last_seen'] = datetime.now(timezone.utc).isoformat()
        return True

    def _revoke_session(self, token: str) -> bool:
        """Remove a single session from the registry."""
        if token in self._sessions:
            del self._sessions[token]
            self._persist_sessions()
            return True
        return False

    def _revoke_user_sessions(self, username: str) -> int:
        """Remove all sessions belonging to *username*. Returns count."""
        tokens = [
            t for t, s in self._sessions.items()
            if s.get('username') == username
        ]
        for t in tokens:
            del self._sessions[t]
        if tokens:
            self._persist_sessions()
        return len(tokens)

    def _revoke_all_sessions(self) -> int:
        """Remove every session from the registry. Returns count."""
        count = len(self._sessions)
        self._sessions.clear()
        self._persist_sessions()
        return count
