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


def _text(raw) -> str:
    """A reading as the string it will be recorded as. SNMP answers bytes as readily as text,
    and joining a column onto a bytes object is a `TypeError` in the middle of a cycle."""
    if isinstance(raw, bytes):
        return raw.decode('utf-8', 'replace').strip()
    return str(raw if raw is not None else '').strip()


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


def prefix_of(mask: str) -> str:
    """A dotted netmask as the number of bits, or ``''`` when it is not one.

    IP arithmetic and not knowledge about any device, which is why it can live in the core:
    255.255.255.0 is /24 on every machine ever made. Empty for anything that is not a
    contiguous mask — a made-up number would be worse than the text somebody can read.
    """
    parts = str(mask or '').strip().split('.')
    if len(parts) != 4:
        return ''
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return ''
    if any(o < 0 or o > 255 for o in octets):
        return ''
    bits = ''.join(f'{o:08b}' for o in octets)
    if '01' in bits:
        return ''                       # 255.0.255.0 is not a prefix, whatever it is
    return str(bits.count('1'))


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
    # The column that says which rows this metric is about, when the profile named one.
    where = metric.get('where') or {}
    w_oid = str(where.get('oid') or '')
    # …and the column that travels WITH this one on the same row (an address and its mask).
    pair = metric.get('with') or {}
    p_oid = str(pair.get('oid') or '')
    for extra in (idx_oids + ([by_oid] if by_oid else []) + ([w_oid] if w_oid else [])
                  + ([p_oid] if p_oid else [])):
        if extra not in columns:
            found, _e = walk(oid=extra, **conn)
            columns[extra] = found or {}
    grp = metric.get('group') or ''
    out = []
    for index, raw in walked.items():
        # Filtered on the OTHER column's value, per row. A row the filter column says nothing
        # about is dropped rather than kept: "the rows where the destination is 0.0.0.0" does
        # not include the ones with no destination, and keeping them would put every route's
        # next hop under the word "gateway".
        if w_oid and str((columns.get(w_oid) or {}).get(index, '')).strip() != where['equals']:
            continue
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
        # Composed only for TEXT: a number with something appended to it is a string that
        # used to be a measurement, and the arithmetic downstream would fail on it.
        if p_oid and str(metric.get('kind') or '') == 'text':
            mate = str((columns.get(p_oid) or {}).get(index, '') or '').strip()
            if pair.get('as') == 'prefix':
                mate = prefix_of(mate) or mate
            if mate:
                raw = f'{_text(raw)}{pair.get("sep", " ")}{mate}'
        out.append({'index': index, 'key': row_key, 'name': row_name, 'raw': raw,
                    'factor': _row_factor(columns.get(by_oid), index) if by_oid else 1})
    return out, (err or None)
