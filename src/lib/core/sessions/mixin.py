#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session registry mixin for WebAdmin."""

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, request, session

# What a session does that is worth keeping. NOT "every request": the panel polls itself —
# `/api/v1/health` every 6 s, the keepalive every 20 s, the access tab every 30 s — so a ring
# that records successful reads is a ring of heartbeats, and the one line somebody opened it
# for was evicted by the browser that was left open over lunch. Recording them would also put
# a write on the response path of every poll of every tab.
#
# So: the ACTS and the REFUSALS. A method that changes something is an act whatever it
# returned, and a status of 400 or more is the answer worth having whatever was asked — "this
# session tried something it may not do" is the line an access review is looking for, and it
# is a GET as often as not.
_LOGGED_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

# Stdlib logging, as in lib/db/base.py and lib/security/secret_manager.py.
_log = logging.getLogger(__name__)


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
        """The Flask secret key: from the environment, else from disk, else newly minted.

        ``SS_SECRET_KEY`` wins and is NOT written to disk — it is supplied per process (a
        Kubernetes Secret, a compose ``.env``), and persisting a copy would leave a second
        source of truth to drift from it. A malformed value raises rather than falling
        back: starting on a different key than the operator pinned is how stored secrets
        become unreadable without anything having reported an error.
        """
        from lib.config import secret_key_from_env       # noqa: PLC0415
        env_key = secret_key_from_env()
        if env_key:
            return env_key
        path = self._secret_key_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    key = fh.read().strip()
                if key:
                    return key
            except OSError:
                # Unreadable key file → fall through and mint a new one below. Failing here
                # would leave the panel unable to start over a permissions problem.
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
                # Best effort: a filesystem that cannot chmod (Windows, some mounts) is not
                # a reason to refuse to run. The key itself was written successfully.
                pass
        except OSError as exc:
            # NOT best-effort like the chmod above. This file signs Flask sessions AND
            # derives the Fernet key for every stored secret (see the docstring), so a
            # failure to persist it means the process runs on an in-memory key: on the next
            # restart a DIFFERENT key is generated, every session is invalidated and — far
            # worse — everything encrypted in the meantime becomes undecryptable.
            #
            # Not raised, because refusing to start would be a worse outcome than running
            # with a key that survives only this process. But it must never be silent: this
            # is one of the ways an installation ends up with the "wrong key" that
            # secret_manager.decrypt_all then reports on every read.
            _log.error('Could not persist the secret key at %s (%s) — running on an '
                       'in-memory key. Sessions and every secret encrypted from now on '
                       'will be unreadable after a restart. Fix the permissions on that '
                       'directory and restart.', self._secret_key_path, exc)

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
        token    = secrets.token_hex(32)          # the secret auth credential (256-bit)
        uid      = str(uuid.uuid4())               # public session id (matches user/host/… uids)
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
        """Validate the current request against the session registry — or accept the API
        token that already authenticated it.

        A token request has no row here and must not have one: a token is not a session, it
        does not belong in the screen that lists who is signed in, and "revoke all sessions"
        must not quietly mean something different depending on how somebody connected. It was
        already checked whole by the before_request hook — token valid, not revoked, not
        expired, account enabled and allowed to sign in — so there is nothing left to verify
        and no registry to verify it against.
        """
        if getattr(g, 'api_token', None):
            return True
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

    def _hook_session_access(self, response):
        """Record what this session just did — after the fact, so the STATUS is part of it.

        The mirror of `_hook_api_token_access`, and deliberately the same shape: the two
        screens that answer "what has been reaching this panel" should not disagree about what
        a row means. What differs is WHICH requests get a row (see `_LOGGED_METHODS`): a token
        is a client whose every call is deliberate, a browser is a client that polls.

        A token request is skipped here — it has no session row, and its calls belong to the
        ring beside the token. Static files are skipped too: they authorise nothing, they
        arrive by the dozen per page, and a 404 for a missing icon is not access history.
        """
        store = getattr(self, '_sessions_store', None)
        if store is None or getattr(g, 'api_token', None) or request.endpoint == 'static':
            return response
        sid = session.get('session_id') or ''
        if not sid or not session.get('logged_in'):
            return response
        status = int(getattr(response, 'status_code', 0) or 0)
        if request.method not in _LOGGED_METHODS and status < 400:
            return response
        try:
            # The route PATTERN, not the URL — `/api/v1/users/<username>` rather than the forty
            # paths it resolves to. An unmatched request (a 404) has no rule, so the path is
            # taken as it came: a 404 is exactly when the URL is the point.
            rule = getattr(request.url_rule, 'rule', '') or request.path
            store.log_access(
                sid,
                ts=datetime.now(timezone.utc).isoformat(),
                ip=request.remote_addr or '',
                method=request.method, path=rule, status=status,
                keep=int(getattr(self, '_SESSION_LOG_MAX', 200) or 0))
        except Exception:                       # pylint: disable=broad-except
            pass                                # bookkeeping must never fail a response
        return response

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
