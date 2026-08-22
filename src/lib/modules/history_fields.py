#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""History fields a module works out at run time.

A module declares what it charts in its ``schema.json``: ``__history__.fields`` names each
value it records, with a label and a unit, and that is what turns a number in a JSON blob into
a named series with an axis. It is a **static** declaration, which is right for a module that
records the same three things on every install.

It is not enough for a module whose fields depend on data the installation supplies. The SNMP
watchful is the case that forced this: what it records is decided by the device profiles
present — the ones shipped plus whatever somebody wrote for the box in their rack — so the set
cannot be written into a schema at build time without being wrong for every install that added
one.

So a module may also declare them at run time, with a module-level function mirroring
``discover_db_tables()`` (see :mod:`lib.db.module_tables`)::

    # watchfuls/<name>/__init__.py
    def discover_history_fields(lang='en_EN', var_dir=''):
        return {'cpu_user': {'label': 'CPU user', 'unit': '%'}}

Both halves are merged by :func:`lib.core.history.service.history_meta`, and **the static
declaration wins**: it is the one somebody wrote down on purpose, and a run-time discovery
that silently renamed it would make the schema a lie.

Failure is always an empty map, never an exception. These fields decide what a chart's legend
says; a module that cannot answer costs its own labels — the values are still recorded, still
charted, and read as their raw field names — and that is not a reason for a history page to
return a 500.
"""

from __future__ import annotations

import importlib
import logging

_log = logging.getLogger(__name__)


def module_history_fields(module: str, lang: str = 'en_EN', var_dir: str = '') -> dict:
    """``{field: {label, unit}}`` the module computes now, or ``{}``.

    *module* is the bare watchful name (``snmp``), as the history records it.
    """
    name = str(module or '').strip()
    if not name or name.startswith('_') or '.' in name:
        return {}
    try:
        mod = importlib.import_module(f'watchfuls.{name}')
    except Exception:  # pylint: disable=broad-except
        return {}       # not a watchful, or one whose optional dependencies are absent
    fn = getattr(mod, 'discover_history_fields', None)
    if not callable(fn):
        return {}
    try:
        declared = fn(lang, var_dir) or {}
    except TypeError:
        # A module that only cares about the language may take just that.
        try:
            declared = fn(lang) or {}
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning('discover_history_fields() failed for module %s: %s', name, exc)
            return {}
    except Exception as exc:  # pylint: disable=broad-except
        _log.warning('discover_history_fields() failed for module %s: %s', name, exc)
        return {}

    if not isinstance(declared, dict):
        _log.warning('discover_history_fields() for module %s did not return a map', name)
        return {}
    out: dict = {}
    for field, meta in declared.items():
        key = str(field or '').strip()
        if not key:
            continue
        meta = meta if isinstance(meta, dict) else {}
        out[key] = {'label': str(meta.get('label') or key),
                    'unit':  str(meta.get('unit') or '')}
    return out
