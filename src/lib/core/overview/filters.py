#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared parsing for the Overview table widgets' severity filter.

The compound filter (level + operator + maintenance) is persisted/transported as a single
opaque string so it fits the generic one-value filter plumbing (``item[store]`` /
``data-<store>`` / ``?<param>=``):

    ''                all
    on                (modules) enabled only
    virtual|physical  (servers) host type
    <op>_<level>      op in {ge, eq}, level in {warning, error}
    ...+m             also include hosts in maintenance (union)
    m                 maintenance only

``ge`` = "that level or higher" (severity ranks: error > warning), ``eq`` = exactly.  Legacy
single-value filters (error/warn/maint/errmaint) map onto this scheme for saved dashboards.
"""

_LEGACY = {
    'error': 'ge_error', 'warn': 'ge_warning',
    'maint': 'm', 'errmaint': 'ge_error+m',
}


def parse_severity_filter(f: str):
    """Return ``(level, op, maint)`` from an encoded filter value.

    * ``level`` in ``'' | 'on' | 'virtual' | 'physical' | 'warning' | 'error'``
    * ``op``    in ``'' | 'ge' | 'eq'`` (set only for a severity level)
    * ``maint`` bool — also include hosts in maintenance.
    """
    f = _LEGACY.get(f or '', f or '')
    maint = f == 'm' or f.endswith('+m')
    base = '' if f == 'm' else (f[:-2] if f.endswith('+m') else f)
    op, level = '', base
    if base.startswith(('ge_', 'eq_')):
        op, level = base[:2], base[3:]
    return level, op, maint


def severity_rank(has_error: bool, has_warning: bool) -> int:
    """Worst severity as a rank: 2 = error, 1 = warning, 0 = neither."""
    return 2 if has_error else (1 if has_warning else 0)


def severity_matches(rank: int, level: str, op: str) -> bool:
    """Whether a ``rank`` satisfies the requested severity ``level`` under ``op``
    (``ge`` = at least, else exactly).  ``error`` is the top rank, so ge==eq there."""
    need = 1 if level == 'warning' else 2
    return rank >= need if op == 'ge' else rank == need
