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
import time

from lib.security import secret_manager
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


def _strip_obsolete(effective: dict) -> None:
    """Drop config leaves removed from the registry (so the UI never shows a
    field that no longer exists). Mutates *effective* in place; empties sections
    left blank."""
    from lib.config.spec import OBSOLETE_CONFIG_PATHS  # noqa: PLC0415 (avoid import cycle)
    for path in OBSOLETE_CONFIG_PATHS:
        section, sep, field = path.partition('|')
        sec = effective.get(section) if sep else None
        if isinstance(sec, dict) and field in sec:
            sec.pop(field, None)
            if not sec:
                effective.pop(section, None)


def overlay_section_env(section_name: str, section_cfg: dict | None) -> dict:
    """Overlay the registry's ``env=`` vars for *section_name* onto its config.

    The ConfigManager read does not apply env overrides, so consumers that need
    an env-overridable section *outside* the web layer (e.g. the syslog DB
    connector, in both the web admin and the standalone receiver — for Docker)
    call this to layer ``SS_*`` env on top of the stored values.
    """
    from lib.config.spec import env_field_specs  # noqa: PLC0415 (avoid import cycle)
    out = dict(section_cfg or {})
    for env_key, (path, cast) in env_field_specs().items():
        sec, _, field = path.partition('|')
        if sec != section_name:
            continue
        raw = os.environ.get(env_key)
        if raw in (None, ''):
            continue
        if cast is bool:
            out[field] = raw.strip().lower() in ('1', 'true', 'yes', 'on')
        elif cast is int:
            try:
                out[field] = int(raw)
            except (TypeError, ValueError):
                continue
        else:
            out[field] = raw
    return out


def overlay_all_env(cfg: dict | None) -> dict:
    """Overlay every registry ``env=`` var onto a FULL config dict, section by section.

    The section-scoped :func:`overlay_section_env` is fine when a consumer already knows
    which section it wants, but the notification router and the standalone service workers
    consume the whole config (any section) — and ``ConfigManager.read`` deliberately does
    not apply env (the web UI needs the saved-vs-env-locked distinction). This applies the
    env on the CONSUMPTION side so ``SS_TELEGRAM_*``, ``SS_EVENTS_AUTOSTART``, etc. take
    effect in web-embedded dispatch and in the Docker standalone workers alike.

    ``database|*`` is skipped on purpose — the connector is built from
    :func:`bootstrap_database_cfg` before this layer exists, and re-casting it here would
    be redundant. A section absent from *cfg* is created when an env var targets it (e.g.
    a blank saved telegram config + ``SS_TELEGRAM_TOKEN``)."""
    from lib.config.spec import env_field_specs  # noqa: PLC0415 (avoid import cycle)
    out = {sec: dict(vals) if isinstance(vals, dict) else vals
           for sec, vals in (cfg or {}).items()}
    for env_key, (path, cast) in env_field_specs().items():
        sec, _, field = path.partition('|')
        if sec == 'database':                    # owned by bootstrap_database_cfg
            continue
        raw = os.environ.get(env_key)
        if raw in (None, ''):
            continue
        if cast is bool:
            value = raw.strip().lower() in ('1', 'true', 'yes', 'on')
        elif cast is int:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
        else:
            value = raw
        if not isinstance(out.get(sec), dict):
            out[sec] = {}
        out[sec][field] = value
    return out


def _decrypt_db_values(db_vals: dict, fernet) -> dict:
    """DB values store ciphertext for secrets; decrypt them by field name (reusing
    the nested key-matching of :mod:`lib.security.secret_manager`)."""
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

    #: How long a probe of the ``config`` table's change stamp is trusted before asking
    #: the database again.  Bounds how stale a cache can be when ANOTHER process (a second
    #: web replica, the CLI, a standalone worker) wrote the config, while keeping the hot
    #: read path at most one cheap query per this many seconds.  Our own writes are seen
    #: at once (``invalidate`` drops the probe too).
    STAMP_TTL = 1.5

    def __init__(self, store, config_path: str, *, fernet=None, secret_keys=None) -> None:
        self._store = store
        self._path = config_path
        self._fernet = fernet
        self._secret_keys = secret_keys
        self.env_locked: frozenset[str] = frozenset()   # set by the web env layer
        self.file_locked: frozenset[str] = frozenset()  # computed by read()
        self._lock = threading.Lock()
        self._eff_cache = None                            # (key, mtime, effective, locked, db_vals)
        self._raw_cache = None                            # (mtime, data)
        self._stamp_state = None                          # (db stamp, monotonic probe time)

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
    def _db_stamp(self):
        """The ``config`` table's cross-process change stamp, probed at most once per
        :attr:`STAMP_TTL`.  A failed probe (``None``) keeps the last answer: no answer is
        not "it changed", and reloading against a database we cannot read helps nobody."""
        now = time.monotonic()
        state = self._stamp_state
        if state is not None and (now - state[1]) < self.STAMP_TTL:
            return state[0]
        probe = getattr(self._store, 'stamp', None)
        stamp = probe() if callable(probe) else None
        if stamp is None and state is not None:
            stamp = state[0]
        self._stamp_state = (stamp, now)
        return stamp

    def _load(self):
        """Resolve the effective config, cached.  Returns ``(effective, db_vals)`` —
        the cached objects themselves, so callers copy before handing them out."""
        file_cfg = self.read_raw()
        # Our own writes move the in-process version; another process's writes move the
        # table stamp (throttled). Either one invalidates the cache.
        key = (self._store.version(), self._db_stamp())
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            mtime = None
        cache = self._eff_cache
        if cache and cache[0] == key and cache[1] == mtime:
            self.file_locked = cache[3]
            return cache[2], cache[4]
        db_vals = _decrypt_db_values(self._store.load_all(), self._fernet)
        effective, locked = resolve_config(db_vals, file_cfg, None, include_defaults=False)
        _strip_obsolete(effective)
        self.file_locked = frozenset(locked)
        with self._lock:
            self._eff_cache = (key, mtime, effective, self.file_locked, db_vals)
        return effective, db_vals

    def read(self) -> dict:
        """Effective config: editable DB values overlaid by the read-only file.

        Env overrides are layered on top by the web layer (not here).  Cached by
        ``(store version, config table stamp, file mtime)`` — the stamp is what
        lets one replica see another's writes; updates :attr:`file_locked`.
        """
        effective, _db_vals = self._load()
        return copy.deepcopy(effective)

    # ── the single write ─────────────────────────────────────────────────────
    def write(self, data: dict, actor: str = '') -> bool:
        """Persist a full (effective-shaped) config dict to its homes.

        Editable ``section|field`` leaves → DB (secrets encrypted, single source);
        the bootstrap ``database`` section, first-run credentials and env/file-locked
        overrides stay in ``config.json``.

        The DB side is applied as a **patch** against the config this manager last
        read (the caller's read → modify → write baseline), not as a replacement:

        * only leaves whose value differs from that baseline are written;
        * only rows present in that baseline and absent from *data* are deleted.

        With several processes on one database (web replicas, the CLI) the baseline can
        be older than the table.  Replacing the whole table from it — what this did
        before — re-wrote every stale value and deleted every row another process had
        added since, so one replica's save silently undid another's. As a patch, a key
        the caller did not touch is left exactly as the database has it now.
        """
        _effective, base = self._load_baseline()
        locked = set(self.env_locked) | set(self.file_locked)

        def _editable(p):
            return (p.partition('|')[0] not in FILE_ONLY_SECTIONS
                    and p not in CRED_PATHS and p not in locked)

        plain = file_leaves(data)
        editable = {p for p in plain if _editable(p)}
        changed = {p for p in editable if p not in base or base[p] != plain[p]}
        if changed:
            enc = data
            if self._fernet:
                enc = secret_manager.encrypt_sensitive(data, self._fernet,
                                                       keys=self._secret_keys)
            enc_leaves = file_leaves(enc)
            self._store.set_many({p: enc_leaves[p] for p in changed}, actor=actor)
        removed = [p for p in base if p not in plain and _editable(p)]
        if removed:
            self._store.delete_many(removed)
        file_data = copy.deepcopy(data)
        for path in editable:
            section, _, field = path.partition('|')
            sec = file_data.get(section)
            if isinstance(sec, dict):
                sec.pop(field, None)
                if not sec:
                    file_data.pop(section, None)
        return self.save_raw(file_data)

    def _load_baseline(self):
        """The cached ``(effective, db_vals)`` the caller's data was derived from —
        resolved now only when nothing was ever read (then it is simply the current DB)."""
        cache = self._eff_cache
        if cache is not None:
            self.file_locked = cache[3]
            return cache[2], cache[4]
        return self._load()

    def invalidate(self) -> None:
        """Drop the cached effective config so the next read re-resolves it."""
        self._eff_cache = None
        self._stamp_state = None
