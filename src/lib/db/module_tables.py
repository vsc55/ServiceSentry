#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-declared tables in the general database.

Watchful *modules* may need their own persistent tables (caches, derived
indexes, per-module state) in the application database — the same SQLite /
MySQL / PostgreSQL backend the core stores use — instead of inventing their own
storage.  This module is the general mechanism the DB manager exposes for that:

* A module declares its tables with a module-level ``discover_db_tables()``
  function (mirror of ``discover_schemas``) returning a list of
  :class:`~lib.db.schema.TableSpec`.  Build each spec with :func:`module_table`,
  which namespaces it as ``mod_<module>_<name>`` so module tables can never
  collide with core tables or with each other.

* At bootstrap (web admin and monitor), the DB manager calls
  :func:`reconcile_module_tables` on the shared connector, which discovers every
  module's tables and reconciles them — creating or migrating them exactly like
  the core stores' ``reconcile_table`` calls.

A module obtains the connector at runtime via ``self.db`` (monitor context,
exposed by :class:`~lib.modules.module_base.ModuleBase`) or via the
``__connector__`` key injected into the action config by the watchfuls web
route.  Both resolve to the one shared connector, so module tables live in the
same database and transaction model as everything else.

Example (in ``watchfuls/<name>/__init__.py``)::

    from lib.db.module_tables import module_table
    from lib.db.schema import Column, Index

    def discover_db_tables():
        return [module_table('mymod', 'cache', (
            Column('key',   'TEXT', nullable=False, unique=True),
            Column('value', 'TEXT'),
        ), indexes=(Index('by_key', ('key',)),))]
"""

from __future__ import annotations

import importlib
import logging
import os
import sys

from .schema import Index, TableSpec

_log = logging.getLogger(__name__)


def _module_prefix(module: str) -> str:
    return f'mod_{module}_'


def module_table(module: str, name: str, columns, *, indexes=(),
                 composite_pk=(), unique_constraints=(), renames=None) -> TableSpec:
    """Build a :class:`TableSpec` namespaced to *module*.

    The table name and every index name are forced to start with
    ``mod_<module>_`` (idempotent: an already-prefixed name is left as-is), so a
    module's tables can never collide with core tables or with another module.
    """
    prefix = _module_prefix(module)
    tname = name if name.startswith(prefix) else prefix + name
    pidx = tuple(
        Index(
            ix.name if ix.name.startswith(prefix) else prefix + ix.name,
            tuple(ix.columns),
            ix.unique,
        )
        for ix in indexes
    )
    return TableSpec(
        name=tname,
        columns=tuple(columns),
        indexes=pidx,
        composite_pk=tuple(composite_pk),
        unique_constraints=tuple(unique_constraints),
        renames=dict(renames or {}),
    )


def _tables_from_module(module_name: str, mod) -> list[TableSpec]:
    """Validate and return the TableSpecs declared by one imported module."""
    fn = getattr(mod, 'discover_db_tables', None)
    if not callable(fn):
        return []
    try:
        declared = fn() or []
    except Exception as exc:  # pylint: disable=broad-except
        _log.warning('discover_db_tables() failed for module %s: %s', module_name, exc)
        return []

    prefix = _module_prefix(module_name)
    out: list[TableSpec] = []
    for spec in declared:
        if not isinstance(spec, TableSpec):
            _log.warning('module %s declared a non-TableSpec table; skipping', module_name)
            continue
        if not spec.name.startswith(prefix):
            _log.warning(
                'module %s table %r is not namespaced as %r — use module_table(); skipping',
                module_name, spec.name, prefix + '…')
            continue
        out.append(spec)
    return out


def _watchfuls_dir(watchfuls_dir: str | None) -> str:
    if watchfuls_dir:
        return watchfuls_dir
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'watchfuls')
    )


def collect_module_tables(watchfuls_dir: str | None = None) -> list[TableSpec]:
    """Discover every module's declared tables across the watchfuls package.

    Walks the folder-based modules (same convention as ``discover_schemas``),
    imports each, and aggregates the validated, namespaced TableSpecs.  A module
    that fails to import or declares nothing is silently skipped.
    """
    base = _watchfuls_dir(watchfuls_dir)
    specs: list[TableSpec] = []
    if not os.path.isdir(base):
        return specs

    parent = os.path.dirname(base)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    for entry in sorted(os.listdir(base)):
        if entry.startswith('_'):
            continue
        path = os.path.join(base, entry)
        if not (os.path.isdir(path) and os.path.isfile(os.path.join(path, '__init__.py'))):
            continue
        try:
            mod = importlib.import_module(f'watchfuls.{entry}')
        except Exception as exc:  # pylint: disable=broad-except  # pragma: no cover
            _log.warning('Could not import module %s for DB tables: %s', entry, exc)
            continue
        specs.extend(_tables_from_module(entry, mod))
    return specs


def reconcile_module_tables(connector, watchfuls_dir: str | None = None) -> list[str]:
    """Discover and reconcile every module-declared table on *connector*.

    Called once at bootstrap (web admin and monitor).  Each table is reconciled
    independently; a failure on one is logged and never aborts the others or the
    application startup.  Returns the names of the tables successfully reconciled.
    """
    done: list[str] = []
    for spec in collect_module_tables(watchfuls_dir):
        try:
            connector.reconcile_table(spec)
            done.append(spec.name)
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning('Failed to reconcile module table %s: %s', spec.name, exc)
    return done
