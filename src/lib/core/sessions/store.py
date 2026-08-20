#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for WebAdmin sessions.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default;
PostgreSQL/MySQL supported through the same interface).

The relationship to the owning user is stored as ``user_uid`` (the user's
stable UID), not by username, so renames never break the association.

The session's own public identifier is ``uid`` (a short hex id, safe to
expose); the secret ``token`` is the primary key and is never sent to clients.

Schema::

    sessions(uid, token PK, user_uid, created, last_seen, ip, user_agent, remember)
    session_access(uid PK, session_uid, ts, ip, method, path, status)
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

_SCHEMA = TableSpec(
    name='sessions',
    columns=(
        Column('uid',        'TEXT', primary_key=True),   # stable session id
        Column('token',      'TEXT', nullable=False, default="''", unique=True),
        Column('user_uid',   'TEXT', nullable=False, default="''"),
        Column('created',    'TEXT', nullable=False, default="''"),
        Column('last_seen',  'TEXT', nullable=False, default="''"),
        Column('ip',         'TEXT', nullable=False, default="''"),
        Column('user_agent', 'TEXT', nullable=False, default="''"),
        # Whether the sign-in asked to be remembered. It was a property of the COOKIE only —
        # `session.permanent` — so the server had no idea, and the idle timeout expired a
        # remembered session exactly as fast as any other. Which made "remember me" mean "the
        # cookie survives closing the browser" and nothing else: come back the next morning,
        # more than `session_idle_minutes` had passed, and you signed in again. Stored here so
        # the check that enforces the timeout can see what the person asked for.
        Column('remember',   'INTEGER', nullable=False, default='0'),
    ),
    indexes=(Index('idx_sessions_user_uid', ('user_uid',)),),
    renames={'sid': 'uid'},  # legacy column rename, data preserved
)

# ── What a session has done ──────────────────────────────────────────────────────────────
# `last_seen` says a session is alive and nothing else. Who is signed in, from where and since
# when are all answerable from the row above; what that sign-in has DONE was not answerable at
# all. The audit log records the actions that have a NAME ('config_saved'), attributed to the
# ACCOUNT — so two sessions of the same person read as one, and a request that was REFUSED
# leaves no trace anywhere.
#
# A ring per session, exactly like `api_token_access` and for the same reason: the questions
# ("what has this session been doing", "what was it denied") are about the recent past, and a
# table that grows with web traffic is not bookkeeping.
#
# **What gets written is a rule, not a list of routes** (see `_SessionsMixin._hook_session_
# access`): every act (POST/PUT/PATCH/DELETE) and every refusal (status >= 400). A successful
# read is not recorded, because the panel polls itself — health every 6 s, the keepalive every
# 20 s, the access tab every 30 s — and a ring that records those is two hundred rows of
# heartbeat with the one interesting line already evicted.
_ACCESS = TableSpec(
    name='session_access',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        # The session's PUBLIC id, which is what the panel knows it by. Never the token: this
        # table is read by whoever may see the sessions list, and the token is the credential.
        Column('session_uid', 'TEXT', nullable=False, default="''"),
        Column('ts',          'TEXT', nullable=False, default="''"),
        Column('ip',          'TEXT', nullable=False, default="''"),
        Column('method',      'TEXT', nullable=False, default="''"),
        # The route PATTERN and not the URL, for the same two reasons as the token ring: a wall
        # of near-identical strings answers nothing, and the raw path is where a username or an
        # id ends up in a table shown to everybody who may read the sessions list.
        Column('path',        'TEXT', nullable=False, default="''"),
        Column('status',      'INTEGER', nullable=False, default='0'),
    ),
    indexes=(
        Index('idx_session_access_ses', ('session_uid',)),
    ),
)

_T = _SCHEMA.name  # table name — single source of truth
_A = _ACCESS.name


class SessionsStore(BaseStore):
    """Relational store for WebAdmin sessions (backend-agnostic)."""

    _TABLE = _T

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        # Inserts since the last trim. Trimming on every write would put a query and a DELETE
        # on the path of every action to keep a ring that only has to be roughly the right
        # size; every Nth is the same ceiling for a fraction of the writes.
        self._access_since_trim = 0
        self._bootstrap()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)
        self._db.reconcile_table(_ACCESS)

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Return all sessions as ``{token: {uid, user_uid, …}}``."""
        rows = self._db.fetchall(
            'SELECT token, uid, user_uid, created, last_seen, ip, user_agent, remember '
            f'FROM {_T}'
        )
        return {
            r[0]: {
                'uid':        r[1],
                'user_uid':   r[2],
                'created':    r[3],
                'last_seen':  r[4],
                'ip':         r[5],
                'user_agent': r[6],
                'remember':   bool(r[7]),
            }
            for r in rows
        }

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, sessions: dict) -> bool:
        """Replace all sessions atomically.

        The activity of the sessions that did NOT survive goes with them. This is the path
        that drops expired sessions at startup and the one behind "sign everybody out", so
        without the prune the history of every session ever opened would pile up here keyed to
        a uid nothing can name: invisible in the panel, which only shows the activity of
        sessions that exist, and unbounded on disk, which is the one thing a ring is for.
        """
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T}')
                for token, s in sessions.items():
                    self._db.execute(
                        f'INSERT INTO {_T}'
                        '(token, uid, user_uid, created, last_seen, ip, user_agent,'
                        ' remember) VALUES(?,?,?,?,?,?,?,?)',
                        (token,
                         s.get('uid', ''),        s.get('user_uid', ''),
                         s.get('created', ''),    s.get('last_seen', ''),
                         s.get('ip', ''),         s.get('user_agent', ''),
                         1 if s.get('remember') else 0),
                    )
                self._prune_access([s.get('uid', '') for s in sessions.values()])
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def upsert(self, token: str, session: dict) -> bool:
        """Insert or replace a single session row (portable delete-then-insert)."""
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE token = ?', (token,))
                self._db.execute(
                    f'INSERT INTO {_T}'
                    '(token, uid, user_uid, created, last_seen, ip, user_agent,'
                    ' remember) VALUES(?,?,?,?,?,?,?,?)',
                    (token,
                     session.get('uid', ''),        session.get('user_uid', ''),
                     session.get('created', ''),    session.get('last_seen', ''),
                     session.get('ip', ''),         session.get('user_agent', ''),
                     1 if session.get('remember') else 0),
                )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def touch(self, uid: str, when: str) -> bool:
        """Persist `last_seen` for one session. **Throttled by the caller, never here.**

        It was written to the in-memory registry and nowhere else, so the column kept the
        creation time for the life of the row. Nothing looked wrong — the sessions screen
        reads the same process's memory — until a restart, when the idle timeout started
        counting from the LOGIN instead of from the last request. In development, where the
        watcher restarts on every edit, that is every few minutes; across two web replicas,
        neither ever saw the other's traffic.
        """
        if not uid:
            return False
        try:
            with self._db.transaction():
                self._db.execute(f'UPDATE {_T} SET last_seen = ? WHERE uid = ?',
                                 (str(when or ''), str(uid)))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, token: str) -> bool:
        """Delete a single session by token.  Returns True if found."""
        try:
            with self._db.transaction():
                # The uid first: it is what the activity rows are keyed by, and after the
                # DELETE below there is nothing left to resolve the token into one.
                rows = self._db.fetchall(f'SELECT uid FROM {_T} WHERE token = ?', (token,))
                deleted = self._db.execute(f'DELETE FROM {_T} WHERE token = ?', (token,))
                for r in rows or ():
                    self._db.execute(f'DELETE FROM {_A} WHERE session_uid = ?', (r[0],))
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            return False

    def delete_by_uid(self, uid: str) -> bool:
        """Delete a session by its uid (the PK / the public id the UI knows — the token
        is never exposed to clients, so management operations key on uid)."""
        if not uid:
            return False
        try:
            with self._db.transaction():
                deleted = self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
                self._db.execute(f'DELETE FROM {_A} WHERE session_uid = ?', (uid,))
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            return False

    def delete_by_user_uid(self, user_uid: str) -> int:
        """Delete all sessions for a given user UID.  Returns count deleted."""
        try:
            with self._db.transaction():
                uids = self._db.fetchall(f'SELECT uid FROM {_T} WHERE user_uid = ?',
                                         (user_uid,)) or ()
                deleted = self._db.execute(f'DELETE FROM {_T} WHERE user_uid = ?', (user_uid,))
                for r in uids:
                    self._db.execute(f'DELETE FROM {_A} WHERE session_uid = ?', (r[0],))
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    # ── Activity ──────────────────────────────────────────────────────────────

    def log_access(self, session_uid: str, *, ts: str, ip: str, method: str,
                   path: str, status: int, keep: int = 200) -> None:
        """Record one request. Never raises: bookkeeping must not fail a response.

        `keep` <= 0 means **no ceiling** — every request that matches the rule is kept and the
        ring becomes a log. Whether to record at all is a switch of its own
        (`web_admin|session_log_enabled`) and belongs to the caller: "no limit" and "no rows"
        are opposite answers, and a single number that carried both is how somebody zeroing
        every cap in the panel to keep everything switched two of them off.
        """
        if not session_uid:
            return
        try:
            self._db.execute(
                f'INSERT INTO {_A} (uid, session_uid, ts, ip, method, path, status)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?)',
                (str(uuid.uuid4()), str(session_uid), str(ts or ''), str(ip or ''),
                 str(method or '')[:8], str(path or '')[:255], int(status or 0)))
            self._access_since_trim += 1
            if keep > 0 and self._access_since_trim >= max(10, keep // 4):
                self._access_since_trim = 0
                self._trim_access(session_uid, keep)
            self._db.commit()
        except Exception:                       # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:                   # pylint: disable=broad-except
                pass

    def _trim_access(self, session_uid: str, keep: int) -> None:
        """Drop everything past the newest `keep` rows of ONE session.

        Per session and not globally: one busy administrator would otherwise evict the history
        of every quiet session, and a quiet session is where a single unexpected request is
        the whole signal.
        """
        rows = self._db.fetchall(
            f'SELECT ts FROM {_A} WHERE session_uid = ? ORDER BY ts DESC LIMIT 1 OFFSET ?',
            (str(session_uid or ''), int(keep)))
        if not rows:
            return
        self._db.execute(f'DELETE FROM {_A} WHERE session_uid = ? AND ts <= ?',
                         (str(session_uid or ''), rows[0][0]))

    def _prune_access(self, keep_uids) -> None:
        """Forget the activity of every session that is not in *keep_uids*."""
        keep = [str(u) for u in (keep_uids or ()) if u]
        if not keep:
            self._db.execute(f'DELETE FROM {_A}')
            return
        marks = ','.join(['?'] * len(keep))
        self._db.execute(f'DELETE FROM {_A} WHERE session_uid NOT IN ({marks})', tuple(keep))

    def access_for(self, session_uid: str, limit: int = 200) -> list:
        """One session's recent requests, newest first."""
        rows = self._db.fetchall(
            f'SELECT ts, ip, method, path, status FROM {_A}'
            f' WHERE session_uid = ? ORDER BY ts DESC LIMIT ?',
            (str(session_uid or ''), int(limit)))
        return [{'ts': r[0] or '', 'ip': r[1] or '', 'method': r[2] or '',
                 'path': r[3] or '', 'status': int(r[4] or 0)} for r in rows]

    def access_all(self, limit: int = 500) -> list:
        """The newest requests across EVERY session, newest first.

        One query and a ceiling. The per-session rings already bound the total, but "every
        request of every session" is still a table nobody reads past the first screen of — and
        the rows it would take to reach the bottom are rows that have to cross the wire.
        """
        rows = self._db.fetchall(
            f'SELECT session_uid, ts, ip, method, path, status FROM {_A}'
            f' ORDER BY ts DESC LIMIT ?', (int(limit),))
        return [{'session_uid': r[0] or '', 'ts': r[1] or '', 'ip': r[2] or '',
                 'method': r[3] or '', 'path': r[4] or '', 'status': int(r[5] or 0)}
                for r in rows]

    def delete_access_for(self, session_uid: str) -> int:
        """Forget one session's activity, keeping the session."""
        n = self._db.execute(f'DELETE FROM {_A} WHERE session_uid = ?',
                             (str(session_uid or ''),))
        self._db.commit()
        return int(n or 0)
