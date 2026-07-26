#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What every relational store does the same way.

Each domain owns its own store: its columns, its joins, its JSON payloads, how a row
becomes a dict.  None of that belongs here and none of it is shared — forcing seventeen
different tables through one hierarchy would cost more than the duplication it removed.

What IS shared is the small stuff around the edges, and it had been written out once per
store: nine identical ``close()``, seven identical ``count()``, three identical audit-column
backfills, seven copies of "what time is it in the format this project stores".  The line
count is not the point.  The point is that each of those is a **decision** — "closing is a
no-op because the connector owns the connection lifecycle" — and a decision copied nine
times is a decision nobody can change.

A store subclasses :class:`BaseStore`, names its table, and gets those for free:

    class RolesStore(BaseStore):
        _TABLE = 'roles'

Two names, not one, because they are not always the same string: ``groups`` and ``user``
are reserved words, so the SQL identifier may need quoting while the *logical* name — the
key in ``entity_versions``, and what a human calls the table — stays plain.  Keeping them
apart is not tidiness: the freshness probe shipped with the raw name for a quoted table,
which fails on MySQL 8 by returning "no answer", and a probe that cannot answer never
reloads anything.  Silent.
"""

from __future__ import annotations

from lib.db.freshness import ensure_version_row, table_stamp
from lib.util.entity_audit import utc_now_iso


class BaseStore:
    """Connector plumbing, the probe, and the two or three queries every store repeats."""

    #: Logical table name — the key in ``entity_versions`` and what the docs call it.
    _TABLE: str = ''

    def __init__(self, db) -> None:
        self._db = db

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def _sql_table(self) -> str:
        """The identifier to put in SQL.  Overridden where the name is a reserved word."""
        return self._TABLE

    # ── Time ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        """The one timestamp format this project stores (UTC, second resolution).

        Shared with :func:`lib.util.entity_audit.touch_entity` on purpose: two formats used
        to coexist (``…Z`` here, ``…+00:00`` there), and for the same second the second one
        sorts *below* the first — so ordering by the stored string stopped being ordering
        by time exactly when two writers met.
        """
        return utc_now_iso()

    # ── The queries every store has ───────────────────────────────────────────

    def count(self) -> int:
        """Number of rows in this store's main table."""
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {self._sql_table}')
        return row[0] if row else 0

    def stamp(self):
        """Cheap "did anything change?" probe — see :mod:`lib.db.freshness`.

        Only meaningful for a table whose writers bump the version counter; for the rest it
        still reports row count and newest ``updated_at``.
        """
        return table_stamp(self._db, self._TABLE, sql_name=self._sql_table)

    def _ensure_version_row(self) -> None:
        """Seed this table's counter row.  Call from ``_bootstrap`` if the store's writers
        bump the version (i.e. if anything reloads it from another process)."""
        ensure_version_row(self._db, self._TABLE)

    def _backfill_audit_columns(self) -> None:
        """Give rows written before the audit columns existed a value.

        Runs once per start and matches nothing afterwards: the WHERE clause selects the
        empty ``created_at`` that only a pre-migration row has.
        """
        now = self._now()
        self._db.execute(
            f"UPDATE {self._sql_table} SET created_at=?, updated_at=?, updated_by=? "
            "WHERE created_at=''",
            (now, now, 'system'),
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle, not the store.

        Kept as a method because callers close stores generically; making it a no-op in one
        place is the whole reason this class exists.
        """


class EncryptedPayloadMixin:
    """A store whose payload column holds secrets (credentials, host profiles).

    The two implementations were byte-identical apart from the parameter name.  Which keys
    count as secret comes from :mod:`lib.security.secret_manager`, so the rule lives with
    the secrets and not with either table.
    """

    _fernet = None
    _secret_keys = None

    def _encrypt(self, payload):
        from lib.security import secret_manager                 # noqa: PLC0415
        if self._fernet and isinstance(payload, dict):
            return secret_manager.encrypt_sensitive(
                payload, self._fernet, keys=self._secret_keys or secret_manager.ENCRYPT_KEYS)
        return payload

    def _decrypt(self, payload):
        from lib.security import secret_manager                 # noqa: PLC0415
        if self._fernet:
            return secret_manager.decrypt_all(payload, self._fernet)
        return payload
