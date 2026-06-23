#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The single owner of configuration I/O.

Everything that reads or writes configuration goes through ``ConfigManager`` so
that *where* config lives is decided in **one** place.  The model:

* the editable configuration is the single source in the DB (one row per
  ``section|field``), overlaid by the read-only ``config.json`` (the bootstrap
  ``database`` section, first-run credentials and any pinned read-only override);
* ``read()`` returns the effective config (DB ← config.json) and ``write()`` splits
  a full config dict back to its homes (editable → DB, file-only → config.json).

Both the web admin and the monitor hold a ``ConfigManager`` and delegate every
config read/write to it — so changing the storage means editing only this file.
"""

from __future__ import annotations

import copy
import os
import threading

from lib import secret_manager
from lib.config.config_control import ConfigControl
from lib.config.resolve import (
    resolve_config, file_leaves, FILE_ONLY_SECTIONS, CRED_PATHS,
)


def read_config_raw(path: str, fernet=None) -> dict:
    """Read ``config.json`` straight from disk and decrypt secrets (no caching).

    Used for the bootstrap ``database`` read that happens before a
    :class:`ConfigManager` (and its DB connector) exists.
    """
    data = ConfigControl(path).read() or {}
    if data and fernet:
        secret_manager.decrypt_all(data, fernet)
    return data


def bootstrap_database_cfg(file_cfg: dict | None) -> dict | None:
    """The ``database`` section for connector bootstrap, with ``SS_DB_*`` env overlaid.

    The database section is consumed *before* the ConfigManager (and its DB
    connector) exists, so the normal web-layer env-override path hasn't run yet.
    Overlaying the env here lets a containerised deployment point ServiceSentry
    at MySQL/MariaDB/PostgreSQL purely through env vars (no config.json edit),
    while a config.json ``database`` block still works when no env is set.
    """
    from lib.config.spec import env_field_specs  # noqa: PLC0415 (avoid import cycle)
    db = dict((file_cfg or {}).get('database') or {})
    for env_key, (path, cast) in env_field_specs().items():
        if not path.startswith('database|'):
            continue
        raw = os.environ.get(env_key)
        if raw in (None, ''):
            continue
        field = path.split('|', 1)[1]
        if cast is int:
            try:
                db[field] = int(raw)
            except (TypeError, ValueError):
                continue
        else:
            db[field] = raw
    return db or None


def _decrypt_db_values(db_vals: dict, fernet) -> dict:
    """DB values store ciphertext for secrets; decrypt them by field name (reusing
    the nested key-matching of :mod:`lib.secret_manager`)."""
    if not (fernet and db_vals):
        return db_vals
    nested: dict = {}
    for path, val in db_vals.items():
        section, sep, field = path.partition('|')
        if sep:
            nested.setdefault(section, {})[field] = val
    secret_manager.decrypt_all(nested, fernet)
    return file_leaves(nested)


class ConfigManager:
    """Single read/write/migrate facade for the application configuration."""

    def __init__(self, store, config_path: str, *, fernet=None, secret_keys=None) -> None:
        self._store = store
        self._path = config_path
        self._fernet = fernet
        self._secret_keys = secret_keys
        self.env_locked: frozenset[str] = frozenset()   # set by the web env layer
        self.file_locked: frozenset[str] = frozenset()  # computed by read()
        self._lock = threading.Lock()
        self._eff_cache = None                            # (ver, mtime, effective, locked)
        self._raw_cache = None                            # (mtime, data)

    # ── raw file (bootstrap + internal) ──────────────────────────────────────
    def read_raw(self) -> dict:
        """The decrypted ``config.json`` as it is on disk (mtime-cached)."""
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            mtime = None
        cache = self._raw_cache
        if cache and cache[0] == mtime:
            return copy.deepcopy(cache[1])
        data = read_config_raw(self._path, self._fernet)
        if mtime is not None:
            with self._lock:
                self._raw_cache = (mtime, copy.deepcopy(data))
        return data

    def save_raw(self, data: dict) -> bool:
        """Write *data* to ``config.json`` verbatim (encrypting secrets), without
        touching the DB.  For file-only edits (e.g. dropping a migrated key)."""
        out = data
        if self._fernet:
            out = secret_manager.encrypt_sensitive(data, self._fernet, keys=self._secret_keys)
        ok = ConfigControl(self._path).save(out)
        self._raw_cache = None
        self.invalidate()
        return ok

    # ── the single read ──────────────────────────────────────────────────────
    def read(self) -> dict:
        """Effective config: editable DB values overlaid by the read-only file.

        Env overrides are layered on top by the web layer (not here).  Cached by
        ``(store version, file mtime)``; updates :attr:`file_locked`.
        """
        file_cfg = self.read_raw()
        ver = self._store.version()
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            mtime = None
        cache = self._eff_cache
        if cache and cache[0] == ver and cache[1] == mtime:
            self.file_locked = cache[3]
            return copy.deepcopy(cache[2])
        db_vals = _decrypt_db_values(self._store.load_all(), self._fernet)
        effective, locked = resolve_config(db_vals, file_cfg, None, include_defaults=False)
        self.file_locked = frozenset(locked)
        with self._lock:
            self._eff_cache = (ver, mtime, effective, self.file_locked)
        return copy.deepcopy(effective)

    # ── the single write ─────────────────────────────────────────────────────
    def write(self, data: dict, actor: str = '') -> bool:
        """Persist a full (effective-shaped) config dict to its homes.

        Editable ``section|field`` leaves → DB (secrets encrypted, single source);
        the bootstrap ``database`` section, first-run credentials and env/file-locked
        overrides stay in ``config.json``.  Callers pass the full effective config,
        so DB rows whose path is absent are reconciled away (deletions propagate).
        """
        enc = data
        if self._fernet:
            enc = secret_manager.encrypt_sensitive(data, self._fernet, keys=self._secret_keys)
        locked = set(self.env_locked) | set(self.file_locked)
        leaves = file_leaves(enc)
        to_db = {p: v for p, v in leaves.items()
                 if p.partition('|')[0] not in FILE_ONLY_SECTIONS
                 and p not in CRED_PATHS and p not in locked}
        if to_db:
            self._store.set_many(to_db, actor=actor)
        present = set(leaves)
        stale = [p for p in self._store.load_all()
                 if p not in present
                 and p.partition('|')[0] not in FILE_ONLY_SECTIONS
                 and p not in CRED_PATHS and p not in locked]
        if stale:
            self._store.delete_many(stale)
        file_data = copy.deepcopy(data)
        for path in to_db:
            section, _, field = path.partition('|')
            sec = file_data.get(section)
            if isinstance(sec, dict):
                sec.pop(field, None)
                if not sec:
                    file_data.pop(section, None)
        return self.save_raw(file_data)

    def invalidate(self) -> None:
        """Drop the cached effective config so the next read re-resolves it."""
        self._eff_cache = None
