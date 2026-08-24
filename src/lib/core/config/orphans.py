#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - readings stored under a key nothing owns any more.
#
"""What is left behind when the thing a reading belonged to stops existing.

A reading is filed under the KEY of whatever produced it — a module item's key while an item
exists, and ``host.<uid>`` for a device the panel reads from its own record instead. Neither
of those is deleted when its owner is: removing a module item leaves its rows in
``check_state`` and in ``history`` under a key nothing can resolve any more, and the panel
cannot even tell they belonged to that machine. Reported from the screen exactly that way — a
NAS whose module was removed showed zero on every tab while eighteen thousand of its samples
were still in the table.

They are not deleted automatically, and that is deliberate: "the item is gone" and "the data
is worthless" are different statements, and the second is the operator's to make. What this
does is FIND them and say how much there is, so Maintenance can offer the sweep.

Pure on purpose — it is handed what each side holds rather than reaching for a store. The
question is arithmetic on two lists, and the hard part is being sure a key really has no
owner; that is much easier to be sure of when it can be run on a table of made-up rows.
"""

from __future__ import annotations


def _bare(module: str) -> str:
    """A module as its results record it — ``snmp``, not ``watchfuls.snmp``."""
    return str(module or '').strip().rsplit('.', 1)[-1]


#: The prefix a device read from its own record files its results under.
HOST_PREFIX = 'host.'


def owner_of(key: str) -> tuple[str, str]:
    """``(kind, id)`` for the thing a stored key belongs to.

    ``('host', <uid>)`` for a device the panel reads because its own record says what it is,
    and ``('item', <key>)`` for everything else — a module item, whatever it keys itself by.

    The three shapes a result key takes are the ones `build_host_status` already speaks: the
    item's key on its own, ``<item>/<row>`` for a table sampled per row, and ``<item>_<suffix>``
    for the older derived-key shape. Only the FIRST separator matters here: a row name may
    contain either character, and cutting at the last one would attribute a reading to an
    owner that never existed.
    """
    k = str(key or '').strip()
    if k.startswith(HOST_PREFIX):
        return 'host', k[len(HOST_PREFIX):].split('/', 1)[0]
    return 'item', k


def _candidates(key: str) -> list[str]:
    """The item keys a stored key could belong to, most specific first."""
    k = str(key or '').strip()
    out = [k]
    for sep in ('/', '_'):
        base = k.split(sep, 1)[0] if sep == '/' else k.rsplit(sep, 1)[0]
        if base and base != k:
            out.append(base)
    return out


def scan(rows, items, hosts, *, modules=None) -> list[dict]:
    """The stored series nothing owns any more.

    *rows* is ``[{'module', 'key', 'count'}]`` — one entry per stored series, from whichever
    table is being swept. *items* is ``{bare module: {item keys}}`` as the configuration
    holds them, *hosts* the set of host uids in the registry.

    *modules* is the set of bare modules the configuration still has an entry for. A module
    ABSENT from it is not swept: absent means "not added", which is also what a module
    temporarily uninstalled looks like, and deleting its history because its folder was moved
    would be the sweep doing the very thing it exists to prevent. What is swept is a module
    that is still there and no longer claims the key. Pass ``None`` to sweep regardless.
    """
    out = []
    for row in rows or ():
        mod = _bare((row or {}).get('module'))
        key = str((row or {}).get('key') or '').strip()
        if not mod or not key:
            continue
        if modules is not None and mod not in modules:
            continue
        kind, ident = owner_of(key)
        if kind == 'host':
            if ident in (hosts or set()):
                continue
            reason = 'host'
        else:
            known = (items or {}).get(mod) or set()
            if any(c in known for c in _candidates(key)):
                continue
            reason = 'item'
        out.append({'module': mod, 'key': key,
                    'count': int((row or {}).get('count') or 0),
                    'reason': reason})
    out.sort(key=lambda r: (r['module'], r['key']))
    return out


def summary(found: list) -> dict:
    """Totals for the screen: how many series, how many samples, and per module."""
    per: dict = {}
    for r in found or ():
        e = per.setdefault(r['module'], {'series': 0, 'count': 0})
        e['series'] += 1
        e['count'] += int(r.get('count') or 0)
    return {'series': len(found or ()),
            'count': sum(int(r.get('count') or 0) for r in (found or ())),
            'modules': [{'module': m, **v} for m, v in sorted(per.items())]}
