#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Has this table changed since I last read it?

The web admin loads roles, users and groups into memory once, at startup, and every
permission check reads those dicts.  That is a single-writer assumption: another process
writing the same database — the CLI, or a second web replica behind a load balancer — is
invisible until a restart.  Serving a role that was revoked ten minutes ago is the kind of
staleness that matters.

Reloading on every request would answer it, at the cost of re-reading and re-parsing every
row to discover that nothing changed, which is the normal case.  So ask a question that is
cheap to ask instead.

**The answer is a counter, not a timestamp.**  Every writer bumps ``entity_versions`` for
its table inside the same transaction as the write, so the version and the rows it
describes become visible together — a reader can never see one without the other.  A
counter says "something changed" without anyone's clock being involved, which matters
precisely because the writers this exists for are *different machines*: with a timestamp,
a replica whose clock runs a few seconds behind writes a row stamped below the current
maximum, and the change is invisible to everybody else until an unrelated write moves the
maximum again.  That failure is silent, and it is the exact scenario the mechanism is for.

The stamp still carries the row count and the newest ``updated_at`` beside the version,
fetched in the same round trip.  Not as the primary signal but as a backstop for a writer
that bypasses this module — a hand-edited row, a migration script, an older build — which
moves the rows without touching the counter.
"""

from __future__ import annotations

from lib.db.schema import Column, TableSpec

#: One row per tracked table: the number of times it has been written.
VERSIONS_SCHEMA = TableSpec(
    name='entity_versions',
    columns=(
        Column('name',    'TEXT', primary_key=True),   # the table being tracked
        Column('version', 'INTEGER', nullable=False, default='0'),
    ),
)
_T = VERSIONS_SCHEMA.name


def ensure_version_row(db, table: str) -> None:
    """Create the counters table if needed and seed *table*'s row at 0.

    Called from each store's bootstrap so the write path below is a plain UPDATE with no
    insert-on-missing branch.  That is deliberate: PostgreSQL aborts the whole transaction
    on a failed statement, so "try INSERT, catch the duplicate, carry on" would take the
    caller's write down with it when two processes start at the same moment.
    """
    try:
        db.reconcile_table(VERSIONS_SCHEMA)
        if db.fetchone(f'SELECT 1 FROM {_T} WHERE name = ?', (table,)) is None:
            db.execute(f'INSERT INTO {_T}(name, version) VALUES(?, 0)', (table,))
            db.commit()
    except Exception:  # pylint: disable=broad-except
        # Two processes bootstrapping at once: one of them loses the insert race, and the
        # row it wanted exists anyway. Nothing here is worth failing a startup over.
        pass


def bump_version(db, table: str) -> None:
    """Record that *table* changed.  MUST be called inside the caller's transaction.

    Inside, so the counter and the rows commit together — either both or neither. Two
    separate transactions fail in two different ways, and both are worse:

    * bump AFTER the write commits, and a crash in between leaves rows nobody will ever
      notice: the version never moves, so every other process keeps its stale copy for good;
    * bump BEFORE, and a reader can see the new version while the rows are still the old
      ones — it reloads, gets what it already had, and records the new version as seen. It
      is then permanently stale AND convinced it is current.

    A plain UPDATE, with no fallback: if the row is missing the version simply does not
    move, and the count/timestamp in :func:`table_stamp` still notice the change. Failing
    the caller's write to fix our own bookkeeping would be the wrong trade.
    """
    db.execute(f'UPDATE {_T} SET version = version + 1 WHERE name = ?', (table,))


def table_stamp(db, table: str, *, sql_name: str | None = None):
    """``(version, row_count, newest updated_at)`` for *table*, or ``None`` if unreadable.

    *table* is the logical name — the key in the counters table.  *sql_name* is what goes
    into the SQL when the two differ, which happens whenever the name is a reserved word:
    ``groups`` is one on MySQL 8, and an unquoted ``FROM groups`` there does not raise
    anywhere visible — it makes this function return ``None``, which the caller reads as
    "no answer" and never reloads. Silent, and only on one backend.

    One round trip: the version comes from a scalar subquery beside the aggregates, which
    every supported backend accepts.

    ``None`` means "no answer", NOT "nothing changed" and NOT "everything changed": a
    caller must keep what it already has rather than reload from — or wipe against — a
    database it just failed to talk to.
    """
    try:
        row = db.fetchone(
            f'SELECT (SELECT version FROM {_T} WHERE name = ?), COUNT(*), MAX(updated_at) '
            f'FROM {sql_name or table}',
            (table,),
        )
    except Exception:  # pylint: disable=broad-except
        return None      # a blip must not cost the caller its cache
    if row is None:
        return None
    return (row[0] or 0, row[1], row[2] or '')
