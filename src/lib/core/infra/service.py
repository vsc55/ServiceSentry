#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The fleet's view-model — pure functions over plain dicts, no Flask.

Two shapes, and the split is the section itself:

* :func:`fleet_row` — one machine as a LINE: what it is, how it is doing, how much of it is
  actually being watched. Everything a list needs and nothing a list cannot show.
* :func:`metrics` — one machine's NUMBERS: the values its checks last returned, each with
  the label and unit the module that produced it declares.

The second is the one worth explaining. A check result carries ``other_data`` — a bag of
whatever the module felt like recording — and the section must not guess which of those keys
is a measurement, nor invent a name for it. It does not have to: a module already declares
its numeric fields in ``__history__`` (that is what makes them chartable in History), with a
unit and a translated label. So the rule here is "a field the module CALLED a measurement",
resolved through the same metadata the charts use, and a module that declares none
contributes state and no numbers — correctly, because that is all it has.

That declaration is also where the SNMP device profiles will plug in later: an OID matrix is
exactly this — a name, a unit and a kind for a value that arrives without any.
"""

from __future__ import annotations

# What a machine IS, for a screen that may not touch it. Deliberately a whitelist and not
# "the record minus a few keys": the host record carries `profiles`, which holds the bound
# credential of every protocol that reaches it, and a projection written as a subtraction is
# one field away from shipping those the day somebody adds a key.
_HOST_FIELDS = ('uid', 'name', 'address', 'kind', 'os', 'virtual', 'maintenance',
                'tags', 'description', 'status', 'modules_total', 'modules_active')


def fleet_row(host: dict) -> dict:
    """One host, projected to what the live section shows."""
    out = {k: host.get(k) for k in _HOST_FIELDS}
    out['tags'] = list(host.get('tags') or [])
    out['virtual'] = bool(host.get('virtual'))
    out['maintenance'] = bool(host.get('maintenance'))
    # A host with no enabled checks has no status at all (see hosts.service._host_statuses),
    # and that is not the same as "fine". The empty string travels as it is so the screen can
    # say "not watched" instead of painting a machine nobody is looking at as OK.
    out['status'] = str(host.get('status') or '')
    return out


def fleet(hosts: list) -> list:
    """The fleet, newest problem first.

    Ordered by STATE and not alphabetically: this list is opened when something is wrong, and
    a screen that answers "which machine is in trouble" by making you read forty rows is a
    screen that only works when nothing is happening. Ties keep the name order, so it still
    reads as a list of machines rather than a shuffling one.
    """
    rank = {'error': 0, 'warning': 1, '': 2, 'ok': 3}
    return sorted((fleet_row(h) for h in hosts or ()),
                  key=lambda h: (rank.get(h['status'], 2), str(h.get('name') or '').lower()))


def summary(rows: list) -> dict:
    """Counts by state, for the header. ``unwatched`` is its own number on purpose: a
    registry of forty machines where nine are watched by nothing is the fact the section
    exists to surface, and it hides perfectly inside "31 OK"."""
    out = {'total': len(rows or ()), 'ok': 0, 'warning': 0, 'error': 0,
           'unwatched': 0, 'maintenance': 0}
    for h in rows or ():
        st = h.get('status') or ''
        if h.get('maintenance'):
            out['maintenance'] += 1
        if st in ('ok', 'warning', 'error'):
            out[st] += 1
        else:
            out['unwatched'] += 1
    return out


def metrics(results: list, fields_by_module: dict) -> list:
    """The numbers behind a host's results.

    *results* is what :func:`lib.core.hosts.service.build_host_status` returns; each row
    carries its module and its ``data`` bag. *fields_by_module* is
    ``{module: {field: {label, unit}}}`` — the module's own ``__history__`` declaration,
    already translated.

    A value is emitted only when the module declared that field AND the value is a number.
    Both halves matter: the first keeps the section from naming things the module did not
    name, and the second keeps a string that happens to sit under a declared key from
    reaching a chart axis.
    """
    out = []
    for row in results or ():
        mod = row.get('module') or ''
        declared = fields_by_module.get(mod) or {}
        data = row.get('data') if isinstance(row.get('data'), dict) else {}
        for field, meta in declared.items():
            if field not in data:
                continue
            value = data.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            out.append({
                'module': mod,
                'key':    row.get('key'),
                'item':   row.get('name'),
                'field':  field,
                'label':  (meta or {}).get('label') or field,
                'unit':   (meta or {}).get('unit') or '',
                'value':  value,
                'ts':     row.get('ts', ''),
                # What the screen needs to ask History for the series behind this number.
                # Handed over rather than rebuilt in the browser: the pair (module, key) is
                # how the store indexes a series, and a second place that composes it is a
                # second place to get it wrong the day a module changes its keys.
                'series': {'module': mod, 'key': row.get('key'), 'field': field},
            })
    out.sort(key=lambda m: (m['module'], str(m['item'] or ''), m['label']))
    return out
