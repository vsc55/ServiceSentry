#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Store of Bot Framework *conversation references* for Teams proactive messaging.

To message a user 1:1, a bot must first have a conversation with them; the inbound
messaging endpoint captures a *conversation reference* (service URL + conversation id
+ the user's aad id / UPN) the first time the user interacts with the bot, and we
persist it here so alerts can be pushed later.

Schema::

    msteams_bot_refs(user_key PK, data(json {service_url, conversation_id,
                     user_id, upn, name}), updated_at)

One record is written per *identifier* (aad object id AND UPN/email, both lower-cased)
pointing at the same reference, so :meth:`all_refs` can be looked up by either.
"""

from __future__ import annotations

import json
import time

from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

_SCHEMA = TableSpec(
    name='msteams_bot_refs',
    columns=(
        Column('user_key',   'TEXT', primary_key=True),
        Column('data',       'TEXT', nullable=False, default="'{}'"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
    ),
)
_T = _SCHEMA.name


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class MsTeamsBotStore:
    """Conversation references for Bot Framework proactive messaging."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_SCHEMA)

    def save_reference(self, ref: dict) -> None:
        """Persist a conversation *ref* under every identifier it carries.

        ``ref`` = {service_url, conversation_id, user_id, upn, name}.  Keys are the
        lower-cased aad object id and UPN/email, so a later lookup by either hits it."""
        keys = {str(ref.get(k) or '').strip().lower()
                for k in ('user_id', 'upn') if ref.get(k)}
        if not keys:
            return
        vj = json.dumps(ref, ensure_ascii=False)
        now = _now()
        with self._db.transaction():
            for key in keys:
                if self._db.fetchone(f'SELECT 1 FROM {_T} WHERE user_key = ?', (key,)):
                    self._db.execute(f'UPDATE {_T} SET data=?, updated_at=? WHERE user_key=?',
                                     (vj, now, key))
                else:
                    self._db.execute(
                        f'INSERT INTO {_T} (user_key, data, updated_at) VALUES (?,?,?)',
                        (key, vj, now))

    def all_refs(self) -> dict:
        """Return ``{user_key: reference}`` for every stored identifier."""
        out: dict = {}
        for key, data, _u in self._db.fetchall(f'SELECT user_key, data, updated_at FROM {_T}'):
            try:
                out[key] = json.loads(data) if data else {}
            except (ValueError, TypeError):
                continue
        return out

    def count(self) -> int:
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
        return row[0] if row else 0


def create(db: BaseConnector, **_kw) -> MsTeamsBotStore:
    return MsTeamsBotStore(db)
