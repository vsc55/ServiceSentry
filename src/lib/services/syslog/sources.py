#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""External syslog sources, opened on demand: other programs' databases, only read.

The panel has its own message table (the "internal" source) and, beside it, any number of
external ones — databases rsyslog or LogAnalyzer fill, configured in
:mod:`lib.services.syslog.store.sources`. The Syslog page shows ONE source at a time, chosen
in a selector; the event rules may watch several (each with its own cursor).

What this module guarantees about an external source:

- **It is only read.** Each is a :class:`~lib.services.syslog.store.SyslogStore` with
  ``read_only=True``: no schema change, no write, no pruning, no clearing; a column of ours
  that the table lacks reads as empty.
- **It is opened when first asked for**, with short timeouts, and kept open while its row is
  unchanged. Nothing is opened for a source nobody looks at and no rule watches.
- **An unreachable one costs its own view and nothing else.** The failure is remembered for
  ``_RETRY_SECS`` so a page refreshing every few seconds does not wait on a dead server each
  time, and it is reported (``errors``) instead of raised into a loop.
- **A change made by another process is noticed.** The list is re-read when the table's
  stamp moves, checked at most every ``_RELOAD_SECS`` — the events and syslog services are
  separate processes and learn about a new source that way.

Who may see which source is decided by permissions (``syslog_sources_all_view`` or
``syslogsrc.<uid>.view``) — see :func:`visible`.
"""

from __future__ import annotations

import os
import threading
import time

from lib.db import get_connector
from lib.services.syslog.store import SyslogStore

#: The flag that grants every external source; ``syslogsrc.<uid>.view`` grants one.
ALL_SOURCES_PERM = 'syslog_sources_all_view'
SOURCE_PERM = 'syslogsrc.%s.view'
#: What the API and the UI call the panel's own table.
INTERNAL = 'internal'

_CONNECT_TIMEOUT = 5      # seconds to reach an external server
_READ_TIMEOUT = 30        # seconds a single query may take there
_RETRY_SECS = 30.0        # after a failed connect, do not try again before this
_RELOAD_SECS = 10.0       # how often the source list may be re-read


class SourceUnavailable(RuntimeError):
    """An external source that exists but cannot be read right now (the reason is the text)."""


def visible(perms) -> set | None:
    """The external sources *perms* may read: ``None`` for all of them, else a set of uids
    (possibly empty). ``syslog_view`` — the internal one — is a separate, plain flag."""
    perms = set(perms or ())
    if ALL_SOURCES_PERM in perms:
        return None
    out = set()
    for p in perms:
        if p.startswith('syslogsrc.') and p.endswith('.view'):
            out.add(p[len('syslogsrc.'):-len('.view')])
    return out


def may_see(uid: str, perms) -> bool:
    allowed = visible(perms)
    return allowed is None or uid in allowed


def connector_config(conn: dict) -> dict:
    """A source's stored connection as a :func:`lib.db.get_connector` config, bounded."""
    cfg = {k: v for k, v in (conn or {}).items() if v not in (None, '') and k != 'cred_uid'}
    cfg['driver'] = str(cfg.get('driver') or 'mysql')
    cfg['connect_timeout'] = _CONNECT_TIMEOUT
    cfg['read_timeout'] = _READ_TIMEOUT
    # Each read its own statement: an idle transaction left open on somebody else's server
    # holds a metadata lock their own ALTER or DROP would queue behind.
    cfg['autocommit'] = True
    return cfg


def with_credential(conn: dict, credentials=None) -> dict:
    """*conn* with the user and password of the credential it names (``cred_uid``), if any.

    The credential wins over what the source holds itself — choosing one means "log in as
    this". One that is gone or switched off is an error rather than a fall back to the inline
    fields: those were left blank on purpose, and connecting with nothing would fail anyway,
    with a less useful message."""
    conn = dict(conn or {})
    uid = str(conn.get('cred_uid') or '').strip()
    if not uid:
        return conn
    cred = credentials.get(uid) if credentials is not None else None
    if not cred:
        raise SourceUnavailable(f'credential not found: {uid}')
    if cred.get('enabled') is False:
        raise SourceUnavailable(f"credential switched off: {cred.get('name') or uid}")
    data = cred.get('data') or {}
    conn['user'] = data.get('db_user') or data.get('user') or ''
    conn['password'] = data.get('db_password') or data.get('password') or ''
    return conn


def open_source(src: dict, credentials=None) -> SyslogStore:
    """A read-only store over *src*'s `SystemEvents`. Raises :class:`SourceUnavailable`.

    *credentials* is the credentials store a ``cred_uid`` is resolved against."""
    conn = with_credential((src or {}).get('data') or {}, credentials)
    if str(conn.get('driver') or '') == 'sqlite':
        # Opening a missing file would CREATE it: an empty database where the operator
        # expected rsyslog's.
        if not conn.get('path'):
            raise SourceUnavailable('no database file configured')
        if not os.path.isfile(conn['path']):
            raise SourceUnavailable(f"database file not found: {conn['path']}")
    try:
        db = get_connector(connector_config(conn), default_sqlite_path='')
    except Exception as exc:  # pylint: disable=broad-except
        raise SourceUnavailable(str(exc)[:300] or exc.__class__.__name__) from exc
    tz = (src or {}).get('time_zone') or 'UTC'
    return SyslogStore(db, time_zone=tz, read_only=True)


def probe(src: dict, credentials=None) -> dict:
    """Try *src* once: ``{ok, error, count, has_table}`` — for the "test connection" button."""
    try:
        store = open_source(src, credentials)
    except SourceUnavailable as exc:
        return {'ok': False, 'error': str(exc), 'count': 0, 'has_table': False}
    try:
        has_table = bool(store._x()['table'])          # pylint: disable=protected-access
        count = store.count() if has_table else 0
        return {'ok': True, 'error': '' if has_table else 'no SystemEvents table',
                'count': count, 'has_table': has_table}
    except Exception as exc:  # pylint: disable=broad-except
        return {'ok': False, 'error': str(exc)[:300], 'count': 0, 'has_table': False}
    finally:
        try:
            store._db.close()                           # pylint: disable=protected-access
        except Exception:  # pylint: disable=broad-except
            pass


class SyslogSources:
    """The configured external sources, each opened on demand (thread-safe)."""

    def __init__(self, store, credentials=None) -> None:
        self._store = store                     # SyslogSourcesStore
        self.credentials = credentials          # CredentialsStore, for a source's cred_uid
        self._lock = threading.Lock()
        self._rows: dict = {}                   # uid → decrypted row
        self._stamp = object()
        self._checked = 0.0
        self._open: dict = {}                   # uid → (updated_at, SyslogStore)
        self._failed: dict = {}                 # uid → (monotonic, error)
        self.errors: dict = {}                  # uid → last error ('' when fine)

    # ── the list ─────────────────────────────────────────────────────────────
    def _refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._checked < _RELOAD_SECS:
            return
        self._checked = now
        try:
            stamp = self._store.stamp()
        except Exception:  # pylint: disable=broad-except
            stamp = object()
        if not force and stamp == self._stamp:
            return
        try:
            rows = {r['uid']: r for r in self._store.list()}
        except Exception:  # pylint: disable=broad-except
            return
        self._stamp = stamp
        self._rows = rows
        # A source edited or deleted is reopened (or dropped) on its next use.
        for uid in list(self._open):
            row = rows.get(uid)
            if row is None or row['updated_at'] != self._open[uid][0]:
                self._close(uid)
        for uid in list(self._failed):
            if uid not in rows:
                self._failed.pop(uid, None)

    def invalidate(self) -> None:
        """Forget what was read: the next call re-reads the list (after a change here)."""
        with self._lock:
            self._failed.clear()
            self._refresh(force=True)

    def list(self) -> list[dict]:
        """Every configured source (decrypted — the caller masks before sending it out)."""
        with self._lock:
            self._refresh()
            return sorted(self._rows.values(), key=lambda r: r['name'].lower())

    # ── opening ──────────────────────────────────────────────────────────────
    def _close(self, uid: str) -> None:
        entry = self._open.pop(uid, None)
        if entry is not None:
            try:
                entry[1]._db.close()                    # pylint: disable=protected-access
            except Exception:  # pylint: disable=broad-except
                pass

    def get(self, uid: str) -> SyslogStore:
        """The read-only store of source *uid*.

        Raises ``KeyError`` for a source that does not exist or is switched off, and
        :class:`SourceUnavailable` for one that cannot be reached (recently failed included)."""
        with self._lock:
            self._refresh()
            row = self._rows.get(uid)
            if row is None or not row.get('enabled'):
                raise KeyError(uid)
            entry = self._open.get(uid)
            if entry is not None and entry[0] == row['updated_at']:
                return entry[1]
            failed = self._failed.get(uid)
            if failed and time.monotonic() - failed[0] < _RETRY_SECS:
                raise SourceUnavailable(failed[1])
        # Connect outside the lock: a slow server must not hold up the other sources.
        try:
            store = open_source(row, self.credentials)
        except SourceUnavailable as exc:
            with self._lock:
                self._failed[uid] = (time.monotonic(), str(exc))
                self.errors[uid] = str(exc)
            raise
        with self._lock:
            self._failed.pop(uid, None)
            self.errors[uid] = ''
            self._close(uid)
            self._open[uid] = (row['updated_at'], store)
        return store

    def watched(self) -> list[tuple]:
        """``[(uid, name, store)]`` for every enabled source the event rules watch and that
        can be opened now. One that cannot is skipped this time and left in ``errors``."""
        out = []
        for row in self.list():
            if not (row.get('enabled') and row.get('watch')):
                continue
            try:
                out.append((row['uid'], row['name'], self.get(row['uid'])))
            except (KeyError, SourceUnavailable):
                continue
        return out

    def close(self) -> None:
        with self._lock:
            for uid in list(self._open):
                self._close(uid)
