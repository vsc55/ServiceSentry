#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP: reading one metric off a device.
#
"""Reading — a metric declaration, a device, and what came back.

The half of sampling that is about the DEVICE, and therefore the half that is core. Three
things ask for it and they are not the same caller: the scheduler, once per cycle; the test
screen, when somebody wants to know whether an assignment is right before trusting it; and,
soon, the host walk. They must all get identical answers or the screen becomes a second
opinion, which is worse than no screen at all.

What is NOT here is what to do with the answer — the previous reading it is a difference
from, the name a row keeps between cycles, whether a silent device counts as down yet. That
is turning a reading into a SERIES, it needs state that outlives the process, and it stays
with the watchful that emits the verdict (``watchfuls.snmp.sampler``).
"""

from __future__ import annotations

import re

# A key segment lands in a result key, a history row and a chart legend. Anything that would
# split the key (`/`) or read as a path has to go, or a port called "eth0/1" becomes two.
_KEY_SAFE = re.compile(r'[^0-9A-Za-z._:-]+')


def _safe_key(text: str, fallback: str) -> str:
    out = _KEY_SAFE.sub('_', str(text or '').strip()).strip('_')
    return out or fallback


def _row_factor(column, index):
    """The multiplier this row's ``scale_by`` column gave, or 1 when it gave nothing usable.

    One, and never zero or a dropped reading: the factor is a detail ABOUT the value, and a
    device that answers the value but not the unit has still answered the value. Reporting a
    volume as empty because its block size was missing would be a wrong number where an
    imprecise one was available.
    """
    try:
        got = float(str((column or {}).get(index, '')).strip())
    except (TypeError, ValueError):
        return 1
    return got if got > 0 else 1


def read_metric(metric: dict, conn: dict, get, walk, columns: dict) -> tuple:
    """One metric declaration, read off one device. Returns ``(rows, error)``.

    A row is ``{'index', 'key', 'name', 'raw', 'factor'}``; a scalar metric produces exactly
    one whose index, key and name are empty, because it IS the device's own value and has
    nothing to be one row of.

    Free of the monitor on purpose. What "read this metric" means — one GET, or a walk plus
    the columns that name and scale its rows — is the same question whether the answer is
    going into a series or onto the screen of somebody testing a profile against the box in
    front of them. Two implementations of it would agree until the day they did not, and the
    day they did not is the day the test says the profile works and the sampler records
    nothing. *get* and *walk* are the two primitives, passed in because the caller decides
    what it is talking to.

    *columns* is a cache the caller owns, and the reason an interface table with five metrics
    against one name column is one walk and not five: whatever fills it stays filled for the
    rest of the device.
    """
    if metric.get('oid'):
        raw, err = get(oid=metric['oid'], **conn)
        if err:
            return [], err
        return [{'index': '', 'key': '', 'name': '', 'raw': raw, 'factor': 1}], None

    walked, err = walk(oid=metric['walk'], **conn)
    if err and not walked:
        return [], err
    idx = metric.get('index_label') or ''
    idx_oids = list(idx) if isinstance(idx, (list, tuple)) else ([idx] if idx else [])
    by_oid = metric.get('scale_by') or ''
    for extra in idx_oids + ([by_oid] if by_oid else []):
        if extra not in columns:
            found, _e = walk(oid=extra, **conn)
            columns[extra] = found or {}
    grp = metric.get('group') or ''
    out = []
    for index, raw in walked.items():
        # The device's own name for the row, and the index only when it has none: an SNMP
        # index is not the port on the front of the switch, and a chart legend that says
        # "3" is one nobody can act on. Where there is no name, the table's own id goes in
        # front of the index — storage row 3 and processor row 3 are not the same row.
        parts = [str((columns.get(o) or {}).get(index, '') or '').strip()
                 for o in idx_oids]
        name = ' / '.join(p for p in parts if p)
        if name:
            row_key, row_name = _safe_key(name, index), name
        else:
            row_key = f'{grp}.{index}' if grp else index
            row_name = row_key
        out.append({'index': index, 'key': row_key, 'name': row_name, 'raw': raw,
                    'factor': _row_factor(columns.get(by_oid), index) if by_oid else 1})
    return out, (err or None)
