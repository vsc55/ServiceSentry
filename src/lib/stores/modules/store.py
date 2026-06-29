#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DB-backed store for the watchful module/item configuration.

Two tables, mirroring the existing nested JSON shape:

* ``module_config`` — one row per module (cpu, dns, …): the module-level fields
  (enabled, alert, interval, ``__*__`` meta) as a JSON ``data`` blob.
* ``module_config_items``  — one row per item: ``host_uid`` / ``label`` / ``enabled``
  promoted to columns (joins / lookups), the rest of the item in JSON ``data``.

The store maps the nested config dict <-> rows and is value-agnostic: it stores
and returns exactly what it is given (secrets stay ciphertext).  Encryption lives
one layer up, in the ``DbBackedModules`` facade — the same boundary the file
helpers (``_read_config_file`` / ``_save_config_file``) use today.

A "collection" inside a module is any non-``__`` key whose value is a dict — the
same rule the rest of the code uses (e.g. history's label lookup); today that is
``list``.
"""

from __future__ import annotations

import json
import time
import uuid

from lib.security import secret_manager
from lib.config import ConfigControl
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec


def _now() -> str:
    """ISO-8601 UTC timestamp (same format the hosts store uses)."""
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _loads(text, default):
    """Parse JSON text, returning *default* on any error or type mismatch."""
    try:
        val = json.loads(text) if text else default
    except (ValueError, TypeError):
        return default
    return val if isinstance(val, type(default)) else default


def _loads_any(text):
    """Parse JSON text to whatever it holds (dict OR scalar), or None on error.

    An item is usually a dict, but the legacy format also allows a bare scalar
    (e.g. ``name -> True/False`` enabled flag); both round-trip through here."""
    try:
        return json.loads(text) if text else None
    except (ValueError, TypeError):
        return None


# Item fields stored as their own columns (never duplicated inside ``data``).
# 'uid' is the primary key / the item's dict key, so it is not in ``data`` either.
_ITEM_PROMOTED = ('host_uid', 'label', 'enabled', 'created_at', 'updated_at', 'updated_by')


# ── Tabla 1: config a nivel de módulo ────────────────────────────────────────
_MODULE_CONFIG_SCHEMA = TableSpec(
    name='module_config',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('module',     'TEXT', nullable=False, default="''", unique=True),
        Column('data',       'TEXT', nullable=False, default="'{}'"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_module_config_module', ('module',)),),
)

# ── Tabla 2: ítems de cada módulo ────────────────────────────────────────────
_MODULE_CONFIG_ITEMS_SCHEMA = TableSpec(
    name='module_config_items',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('module_uid', 'TEXT', nullable=False, default="''"),   # → module_config.uid
        Column('collection', 'TEXT', nullable=False, default="'list'"),
        Column('host_uid',   'TEXT', nullable=False, default="''"),   # → hosts.uid
        Column('label',      'TEXT', nullable=False, default="''"),
        Column('enabled',    'INTEGER', nullable=False, default="1"),
        Column('data',       'TEXT', nullable=False, default="'{}'"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(
        Index('idx_module_config_items_moduid', ('module_uid',)),
        Index('idx_module_config_items_host',   ('host_uid',)),
    ),
)


# Table names — single source of truth (the TableSpecs above), reused by every
# query so the names live in exactly one place.
_T_CONFIG = _MODULE_CONFIG_SCHEMA.name
_T_ITEMS = _MODULE_CONFIG_ITEMS_SCHEMA.name


def _is_collection(key, value) -> bool:
    """True when a module sub-key holds items: a non-``__`` key whose value is a
    dict (the same convention used across the codebase)."""
    return isinstance(value, dict) and not str(key).startswith('__')


class ModulesStore:
    """Backend-agnostic store for the modules configuration."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._version = 0
        self._bootstrap()

    # ── Schema ────────────────────────────────────────────────────────────────
    def _bootstrap(self) -> None:
        self._db.reconcile_table(_MODULE_CONFIG_SCHEMA)
        self._db.reconcile_table(_MODULE_CONFIG_ITEMS_SCHEMA)

    # ── Meta ──────────────────────────────────────────────────────────────────
    def version(self) -> int:
        """Monotonic counter bumped on every write — lets the facade invalidate
        its cached dict cheaply."""
        return self._version

    def is_empty(self) -> bool:
        """True when no module configuration has been stored yet."""
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T_CONFIG}')
        return not (row and row[0])

    # ── Read ──────────────────────────────────────────────────────────────────
    def load_all(self) -> dict:
        """Reconstruct the nested ``{module: {fields…, <collection>: {uid: item}}}``
        dict (value-agnostic — secrets stay as stored)."""
        modules: dict = {}
        uid2name: dict = {}
        for uid, module, data in self._db.fetchall(
                f'SELECT uid, module, data FROM {_T_CONFIG}'):
            uid2name[uid] = module
            modules[module] = _loads(data, {})
        for (uid, module_uid, collection, host_uid, label, enabled, data,
             created_at, updated_at, updated_by) in self._db.fetchall(
                f'SELECT uid, module_uid, collection, host_uid, label, enabled, data, '
                f'created_at, updated_at, updated_by FROM {_T_ITEMS}'):
            module = uid2name.get(module_uid)
            if module is None:
                continue  # orphan item (module deleted) — skip
            parsed = _loads_any(data)
            if isinstance(parsed, dict):
                item = parsed
                item['uid'] = uid
                item['label'] = label or ''
                item['enabled'] = bool(enabled)
                if host_uid:                   # omit when empty to keep the original shape
                    item['host_uid'] = host_uid
                # Per-item audit metadata (column-backed; stripped from the data
                # blob on save via _ITEM_PROMOTED). Exposed read-only for the UI.
                if created_at:
                    item['created_at'] = created_at
                if updated_at:
                    item['updated_at'] = updated_at
                if updated_by:
                    item['updated_by'] = updated_by
            else:
                item = parsed                  # legacy scalar item (e.g. name -> bool)
            modules.setdefault(module, {}).setdefault(collection or 'list', {})[uid] = item
        return modules

    # ── Write (full transactional sync) ───────────────────────────────────────
    def save_all(self, modules: dict, *, actor: str = '') -> None:
        """Replace the whole configuration with *modules*: upsert what is present
        and delete what is absent, in one transaction.  Module UIDs are stable
        (reused by name) so ``module_config_items.module_uid`` references stay valid."""
        modules = modules if isinstance(modules, dict) else {}
        now = _now()
        with self._db.transaction():
            existing = {m: u for (u, m) in
                        self._db.fetchall(f'SELECT uid, module FROM {_T_CONFIG}')}
            seen_modules: set = set()
            seen_items: set = set()
            for module, mdict in modules.items():
                if not isinstance(mdict, dict):
                    continue
                seen_modules.add(module)
                mod_fields = {k: v for k, v in mdict.items() if not _is_collection(k, v)}
                collections = {k: v for k, v in mdict.items() if _is_collection(k, v)}
                muid = existing.get(module) or str(uuid.uuid4())
                m_json = json.dumps(mod_fields, ensure_ascii=False)
                if module in existing:
                    self._db.execute(
                        f'UPDATE {_T_CONFIG} SET data=?, updated_at=?, updated_by=? WHERE uid=?',
                        (m_json, now, actor, muid))
                else:
                    self._db.execute(
                        f'INSERT INTO {_T_CONFIG} (uid, module, data, created_at, updated_at, '
                        'updated_by) VALUES (?,?,?,?,?,?)', (muid, module, m_json, now, now, actor))
                for coll, items in collections.items():
                    for iuid, item in items.items():
                        iuid = str(iuid)
                        seen_items.add(iuid)
                        if isinstance(item, dict):
                            host_uid = str(item.get('host_uid') or '')
                            label = str(item.get('label') or '')
                            enabled = 0 if item.get('enabled') is False else 1
                            idata = {k: v for k, v in item.items()
                                     if k != 'uid' and k not in _ITEM_PROMOTED}
                        else:
                            # legacy scalar item (e.g. name -> True/False enabled flag)
                            host_uid, label = '', ''
                            enabled = 0 if item is False else 1
                            idata = item
                        i_json = json.dumps(idata, ensure_ascii=False)
                        if self._db.fetchone(f'SELECT 1 FROM {_T_ITEMS} WHERE uid=?', (iuid,)):
                            self._db.execute(
                                f'UPDATE {_T_ITEMS} SET module_uid=?, collection=?, host_uid=?, '
                                'label=?, enabled=?, data=?, updated_at=?, updated_by=? WHERE uid=?',
                                (muid, coll, host_uid, label, enabled, i_json, now, actor, iuid))
                        else:
                            self._db.execute(
                                f'INSERT INTO {_T_ITEMS} (uid, module_uid, collection, host_uid, '
                                'label, enabled, data, created_at, updated_at, updated_by) '
                                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                                (iuid, muid, coll, host_uid, label, enabled, i_json, now, now, actor))
            # Prune removed modules (and their items) …
            for module, uid in existing.items():
                if module not in seen_modules:
                    self._db.execute(f'DELETE FROM {_T_ITEMS} WHERE module_uid=?', (uid,))
                    self._db.execute(f'DELETE FROM {_T_CONFIG} WHERE uid=?', (uid,))
            # … and items removed from modules that stayed.
            for (iuid,) in self._db.fetchall(f'SELECT uid FROM {_T_ITEMS}'):
                if iuid not in seen_items:
                    self._db.execute(f'DELETE FROM {_T_ITEMS} WHERE uid=?', (iuid,))
        self._version += 1


def create(db: BaseConnector) -> ModulesStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return ModulesStore(db)


