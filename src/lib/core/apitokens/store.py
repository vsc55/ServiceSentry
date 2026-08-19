#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where an API token lives — its own table, and never the token itself.

Schema::

    api_tokens(uid PK, user_uid, name, token_id, token_hash, permissions,
               expires_at, last_used, revoked, created, created_by)

**Only the hash is stored**, like a recovery code and unlike every encrypted secret in this
project. The difference is what a reader of the database could do with it: an encrypted value
exists because something has to USE it later (an SMTP password, a bot token), so it must be
recoverable. Nothing ever needs to read a token back — a caller presents one and we check it —
so keeping it recoverable would be storing a credential for no reason at all.

``token_id`` is the half kept in clear, and it is what makes verification one indexed lookup
instead of hashing the candidate against every row in the table. It carries no secret: it names
the token the way a username names an account.

The hash is **SHA-256 and deliberately not scrypt**. A password KDF is slow on purpose, to make
guessing a human-chosen secret expensive; the secret here is 192 random bits, where guessing is
not a threat model but a joke. What IS real is that this runs on every single API request, and
a deliberately-slow hash there is a denial of service anybody can trigger by sending garbage.
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

_TOKENS = TableSpec(
    name='api_tokens',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('user_uid',    'TEXT', nullable=False, default="''"),
        # What the owner called it. The only thing that makes a list of tokens usable:
        # "deploy pipeline" is revocable knowledge, `sst_9f2a…` is not.
        Column('name',        'TEXT', nullable=False, default="''"),
        # The public half — indexed, and how a presented token finds its row.
        Column('token_id',    'TEXT', nullable=False, default="''"),
        Column('token_hash',  'TEXT', nullable=False, default="''"),
        # JSON list of permission flags, or the string '*' for "whatever the owner has".
        # Either way it is INTERSECTED with the owner's current permissions at request time,
        # so a token can never outgrow the account it belongs to (see service.effective).
        Column('permissions', 'TEXT', nullable=False, default="'[]'"),
        # '' = never expires. Stored as the caller wrote it so a list can show it.
        Column('expires_at',  'TEXT', nullable=False, default="''"),
        # Written at most once a minute (see mixin): the point is "is this still in use",
        # and a write per request would put the busiest table in the database on the hot path.
        Column('last_used',   'TEXT', nullable=False, default="''"),
        Column('revoked',     'INTEGER', nullable=False, default='0'),
        Column('created',     'TEXT', nullable=False, default="''"),
        Column('created_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(
        Index('idx_api_tokens_user', ('user_uid',)),
        Index('idx_api_tokens_tid', ('token_id',)),
    ),
)

# ── What a token has done ────────────────────────────────────────────────────────────────
# `last_used` answers "is this still in use" and nothing else, which leaves the two questions
# anybody actually asks about a credential unanswered: what has it been doing, and from where.
# The audit log answers neither — it records the ACCOUNT, so a token's writes are indistinguish-
# able from the person's own, and reads are not audited for anybody.
#
# Kept as a RING PER TOKEN rather than a log: a bounded number of the most recent calls, oldest
# discarded. An unbounded table here would grow with traffic, which is the one thing an API's
# own bookkeeping must not do, and the questions this answers ("what did it do today", "where is
# it calling from") are about the recent past. Whoever needs forever has a reverse proxy.
_ACCESS = TableSpec(
    name='api_token_access',
    columns=(
        Column('uid',       'TEXT', primary_key=True),
        Column('token_uid', 'TEXT', nullable=False, default="''"),
        Column('ts',        'TEXT', nullable=False, default="''"),
        Column('ip',        'TEXT', nullable=False, default="''"),
        Column('method',    'TEXT', nullable=False, default="''"),
        # The route PATTERN, not the URL: `/api/v1/users/<username>` and not the forty distinct
        # paths it resolves to. A ring of two hundred entries filled with one username per row
        # answers "which endpoints does this token use" with a wall of near-identical strings,
        # and the raw path is also where an id or an email ends up in a table that is shown to
        # anybody who may read the token list.
        Column('path',      'TEXT', nullable=False, default="''"),
        Column('status',    'INTEGER', nullable=False, default='0'),
    ),
    indexes=(
        Index('idx_api_token_access_tok', ('token_uid',)),
    ),
)

_T = _TOKENS.name
_A = _ACCESS.name


class ApiTokenStore(BaseStore):
    """API tokens: mint, look up by public id, list, revoke."""

    _TABLE = _T

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        self._db.reconcile_table(_TOKENS)
        self._db.reconcile_table(_ACCESS)
        # Inserts since the last trim. Trimming on every call would put a COUNT and a DELETE on
        # the hot path of every API request to keep a ring that only has to be roughly the
        # right size; every Nth is the same ceiling with a fraction of the writes.
        self._access_since_trim = 0

    # ── Read ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _row(r) -> dict:
        return {'uid': r[0], 'user_uid': r[1], 'name': r[2] or '', 'token_id': r[3] or '',
                'token_hash': r[4] or '', 'permissions': r[5] or '[]',
                'expires_at': r[6] or '', 'last_used': r[7] or '',
                'revoked': bool(r[8]), 'created': r[9] or '', 'created_by': r[10] or ''}

    _COLS = ('uid, user_uid, name, token_id, token_hash, permissions, expires_at, '
             'last_used, revoked, created, created_by')

    def by_token_id(self, token_id: str) -> dict | None:
        """The row a presented token names, revoked ones included.

        Revoked rows come back on purpose: the caller has to be able to tell "this token was
        revoked" from "this token never existed", because those are different answers to the
        person holding it — and the same answer over the wire.
        """
        row = self._db.fetchone(f'SELECT {self._COLS} FROM {_T} WHERE token_id = ?',
                                (str(token_id or ''),))
        return self._row(row) if row else None

    def name_taken(self, user_uid: str, name: str, *, except_uid: str = '') -> bool:
        """Whether this account already has a LIVE token by that name.

        Case-insensitive and trimmed, because "CI" and "ci " are the same name to the person
        reading the list — and the list is the only thing that says what a token is for.
        Two tokens called the same thing make revoking one a coin flip.

        Revoked ones do not count: they are kept for the record, and refusing to reuse the
        name of something that stopped working months ago would be a rule with no purpose.
        """
        want = str(name or '').strip().lower()
        if not want:
            return False
        for row in self.list_for(user_uid):
            if row.get('revoked') or row.get('uid') == except_uid:
                continue
            if str(row.get('name') or '').strip().lower() == want:
                return True
        return False

    def rename(self, uid: str, name: str, *, user_uid: str = '') -> bool:
        """Rename a token. Pinned to the owner for the same reason revoke is."""
        sql = f'UPDATE {_T} SET name = ? WHERE uid = ?'
        params = [str(name or ''), str(uid or '')]
        if user_uid:
            sql += ' AND user_uid = ?'
            params.append(str(user_uid))
        n = self._db.execute(sql, tuple(params))
        self._db.commit()
        return bool(n)

    def set_permissions(self, uid: str, permissions: str, *, user_uid: str = '') -> bool:
        """Change what a token may do, without touching the secret.

        The secret and the scope are two different things, and only one of them is compromised
        when a scope turns out to be wrong. Pinned to the owner like every other self-service
        write here.

        Not applied to a revoked token — the caller checks that too, but the row is the last
        place that can enforce it, and "edited a token that stopped working" is a state nobody
        should be able to reach through a race.
        """
        sql = f'UPDATE {_T} SET permissions = ? WHERE uid = ? AND revoked = 0'
        params = [str(permissions or '[]'), str(uid or '')]
        if user_uid:
            sql += ' AND user_uid = ?'
            params.append(str(user_uid))
        n = self._db.execute(sql, tuple(params))
        self._db.commit()
        return bool(n)

    def list_for(self, user_uid: str) -> list:
        """One account's tokens, newest first. Never the hash — see :meth:`public`."""
        rows = self._db.fetchall(
            f'SELECT {self._COLS} FROM {_T} WHERE user_uid = ? ORDER BY created DESC',
            (str(user_uid or ''),))
        return [self._row(r) for r in rows]

    def list_all(self) -> list:
        """Every token in the installation, newest first — the administrator's view.

        One query rather than one per account: the screen it feeds asks a question about the
        installation ("what standing access exists"), and asking it account by account is how
        the answer ends up depending on which accounts you remembered to look at.
        """
        rows = self._db.fetchall(f'SELECT {self._COLS} FROM {_T} ORDER BY created DESC')
        return [self._row(r) for r in rows]

    def count_for(self, user_uid: str, *, active_only: bool = True) -> int:
        sql = f'SELECT COUNT(*) FROM {_T} WHERE user_uid = ?'
        if active_only:
            sql += ' AND revoked = 0'
        row = self._db.fetchone(sql, (str(user_uid or ''),))
        return int(row[0]) if row else 0

    def tokens_by_user(self) -> dict:
        """`{user_uid: live token count}` — one query for a whole listing."""
        out: dict = {}
        for uid, in self._db.fetchall(
                f'SELECT user_uid FROM {_T} WHERE revoked = 0') or ():
            if uid:
                out[uid] = out.get(uid, 0) + 1
        return out

    # ── Write ────────────────────────────────────────────────────────────────

    def create(self, *, user_uid: str, name: str, token_id: str, token_hash: str,
               permissions: str, expires_at: str, created: str, created_by: str) -> str:
        uid = str(uuid.uuid4())
        self._db.execute(
            f'INSERT INTO {_T} (uid, user_uid, name, token_id, token_hash, permissions,'
            ' expires_at, last_used, revoked, created, created_by)'
            " VALUES (?, ?, ?, ?, ?, ?, ?, '', 0, ?, ?)",
            (uid, str(user_uid or ''), str(name or ''), str(token_id or ''),
             str(token_hash or ''), str(permissions or '[]'), str(expires_at or ''),
             str(created or ''), str(created_by or '')))
        self._db.commit()
        return uid

    def revoke(self, uid: str, *, user_uid: str = '') -> bool:
        """Revoke by uid, optionally pinned to an owner.

        `user_uid` is how the self-service route stays an IDOR away from nothing: it revokes
        `uid AND user_uid`, so a token id belonging to somebody else matches no row rather
        than being revoked by whoever guessed it.
        """
        sql = f'UPDATE {_T} SET revoked = 1 WHERE uid = ? AND revoked = 0'
        params = [str(uid or '')]
        if user_uid:
            sql += ' AND user_uid = ?'
            params.append(str(user_uid))
        n = self._db.execute(sql, tuple(params))
        self._db.commit()
        return bool(n)

    def revoke_all_for(self, user_uid: str) -> int:
        """Revoke every live token of one account — what deleting or disabling it must do."""
        n = self._db.execute(
            f'UPDATE {_T} SET revoked = 1 WHERE user_uid = ? AND revoked = 0',
            (str(user_uid or ''),))
        self._db.commit()
        return int(n or 0)

    # ── Access log ───────────────────────────────────────────────────────────

    def log_access(self, token_uid: str, *, ts: str, ip: str, method: str,
                   path: str, status: int, keep: int = 200) -> None:
        """Record one call. Never raises: bookkeeping must not fail a request.

        `keep` <= 0 turns it off — an installation that does not want the rows, or that reads
        its access log off a proxy, should not be made to store them here.
        """
        if keep <= 0:
            return
        try:
            self._db.execute(
                f'INSERT INTO {_A} (uid, token_uid, ts, ip, method, path, status)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?)',
                (str(uuid.uuid4()), str(token_uid or ''), str(ts or ''), str(ip or ''),
                 str(method or '')[:8], str(path or '')[:255], int(status or 0)))
            self._access_since_trim += 1
            if self._access_since_trim >= max(10, keep // 4):
                self._access_since_trim = 0
                self._trim_access(token_uid, keep)
            self._db.commit()
        except Exception:                       # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:                   # pylint: disable=broad-except
                pass

    def _trim_access(self, token_uid: str, keep: int) -> None:
        """Drop everything past the newest `keep` rows of ONE token.

        Per token and not globally: a chatty token would otherwise evict the history of every
        quiet one, and the quiet ones are where a single unexpected call is the whole signal.
        """
        rows = self._db.fetchall(
            f'SELECT ts FROM {_A} WHERE token_uid = ? ORDER BY ts DESC LIMIT 1 OFFSET ?',
            (str(token_uid or ''), int(keep)))
        if not rows:
            return
        self._db.execute(f'DELETE FROM {_A} WHERE token_uid = ? AND ts <= ?',
                         (str(token_uid or ''), rows[0][0]))

    def access_for(self, token_uid: str, limit: int = 200) -> list:
        """One token's recent calls, newest first."""
        rows = self._db.fetchall(
            f'SELECT ts, ip, method, path, status FROM {_A}'
            f' WHERE token_uid = ? ORDER BY ts DESC LIMIT ?',
            (str(token_uid or ''), int(limit)))
        return [{'ts': r[0] or '', 'ip': r[1] or '', 'method': r[2] or '',
                 'path': r[3] or '', 'status': int(r[4] or 0)} for r in rows]

    def access_all(self, limit: int = 500) -> list:
        """The newest calls across EVERY token, newest first.

        One query and a ceiling. Per-token rings mean the total is already bounded, but "every
        call of every token" is still a table nobody reads past the first screen of — and the
        rows it would take to reach the bottom are rows that have to cross the wire.
        """
        rows = self._db.fetchall(
            f'SELECT token_uid, ts, ip, method, path, status FROM {_A}'
            f' ORDER BY ts DESC LIMIT ?', (int(limit),))
        return [{'token_uid': r[0] or '', 'ts': r[1] or '', 'ip': r[2] or '',
                 'method': r[3] or '', 'path': r[4] or '', 'status': int(r[5] or 0)}
                for r in rows]

    def delete_access_for(self, token_uid: str) -> int:
        """Forget a token's history — for a token that is being deleted with its account."""
        n = self._db.execute(f'DELETE FROM {_A} WHERE token_uid = ?', (str(token_uid or ''),))
        self._db.commit()
        return int(n or 0)

    def touch(self, uid: str, when: str) -> None:
        """Record that the token was used. Throttled by the caller, never here."""
        self._db.execute(f'UPDATE {_T} SET last_used = ? WHERE uid = ?',
                         (str(when or ''), str(uid or '')))
        self._db.commit()

    def delete_for_user(self, user_uid: str) -> int:
        """Remove the rows outright — for an account that no longer exists.

        The access history goes with them: it is keyed by token, so leaving it behind would be
        rows about a credential that no longer exists, belonging to an account that no longer
        exists, which nothing can ever ask a question about again.
        """
        for row in self._db.fetchall(f'SELECT uid FROM {_T} WHERE user_uid = ?',
                                     (str(user_uid or ''),)) or ():
            self.delete_access_for(row[0])
        n = self._db.execute(f'DELETE FROM {_T} WHERE user_uid = ?', (str(user_uid or ''),))
        self._db.commit()
        return int(n or 0)
