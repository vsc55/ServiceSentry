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

import re

#: How long a row name may be before the split is not attempted. Row names are what a device
#: calls a disk or an interface — "Drive 1 (DX517-1)", "eth0" — and a bound on the input is
#: the one protection a regular expression that arrived as DATA can be given: Python's `re`
#: has no timeout, so a pattern somebody wrote badly is a worker that stops answering. An
#: unsplit name is a heading that does not appear, which is what happened before any of this.
_ROW_SPLIT_MAX = 200


def split_row(name: str, pattern: str) -> tuple:
    """``(row, group)`` for one row name — ``(name, '')`` when it does not split.

    The PATTERN is the module's (a profile declares it, validated where profiles are), and
    applying it is not: this is a string with a bracket in it, and nothing here knows what
    SNMP is. Not matching is the normal case rather than an error — an internal disk is
    called "Drive 1" with nothing in brackets, and it belongs to the group with no name.
    """
    text = str(name or '')
    if not pattern or len(text) > _ROW_SPLIT_MAX:
        return text, ''
    try:
        m = re.match(pattern, text)
    except re.error:
        return text, ''
    if not m or 'row' not in (m.groupdict() or {}):
        return text, ''
    return (m.group('row') or text).strip(), (m.groupdict().get('group') or '').strip()

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


def sources_of(fields_by_module: dict) -> dict:
    """``{source_id: {'label', 'rank'}}`` — how to NAME and ORDER the things that answered.

    A module records an attribute under the id of whatever produced it (``synology_ups``), and
    an id is not a name: the identity column was printing them raw beside values that were
    translated. The module already declares the name, per language, beside every measurement
    that came from the same source — so this reads that declaration instead of asking modules
    for a second one, and a source that only ever answers TEXT (a profile of pure identity
    facts) keeps its id, which is a word somebody can act on rather than a blank heading.
    """
    out: dict = {}
    for meta in (fields_by_module or {}).values():
        for spec in (meta or {}).values():
            src = str((spec or {}).get('source') or '').strip()
            if not src or src in out:
                continue
            out[src] = {'label': str((spec or {}).get('source_label') or '').strip() or src,
                        # What the THING is called, when the profile says. Empty is the normal
                        # case and the caller decides what to do with it — the identity card
                        # falls back to the title, trimmed.
                        'short': str((spec or {}).get('source_short') or '').strip(),
                        'rank': int((spec or {}).get('source_rank') or 0)}
    return out


def attributes(results: list, sources: dict | None = None) -> list:
    """What the device IS, as opposed to what it is doing.

    A result carries measurements and, beside them, ``_attrs``: the facts that identify the
    thing being measured — a disk's model and serial, an interface's MAC, the chassis'
    firmware and where it is racked. The underscore is the recorders' existing convention for
    "about this result rather than a measurement of it", the same one ``_row`` uses, so this
    reads what every module already records instead of asking modules for something new.

    They were being written and never shown. A serial number nobody can read from the panel
    is a serial number somebody reads off the machine with a torch, and the firmware version
    is half of every "is this the box with the problem" question.

    ``_attrs`` is ``{source: {key: value}}`` — the *source* being whatever the module calls
    the thing that answered. That nesting is not bookkeeping: one registry entry can front
    several pieces of equipment (a NAS and the UPS plugged into it both answer "vendor",
    "model", "version"), and flattened they would read as one machine with contradictory
    facts. Grouped, they read as what they are.

    Sorted with the device's own facts first (no row) and then row by row, because that is
    the order somebody reads them in: what is this, then what is inside it.
    """
    out = []
    for row in results or ():
        data = row.get('data') if isinstance(row.get('data'), dict) else {}
        attrs = data.get('_attrs')
        if not isinstance(attrs, dict):
            continue
        for source, facts in attrs.items():
            # A flat `{key: value}` is the older shape and still readable — one unnamed
            # source. Tolerated rather than migrated: it is live status, rewritten every
            # cycle, so it corrects itself within one round.
            if not isinstance(facts, dict):
                facts, source = {source: facts}, ''
            spec = (sources or {}).get(str(source or '')) or {}
            for key, value in facts.items():
                text = str(value if value is not None else '').strip()
                if not text:
                    continue      # an empty attribute is one the device did not answer
                out.append({'module': row.get('module') or '', 'row': row.get('row') or '',
                            'item': row.get('name') or '', 'source': str(source or ''),
                            # The name the source gives itself, in the reader's language. Falls
                            # back to the id: a word somebody can act on beats a blank heading.
                            'source_label': str(spec.get('label') or '') or str(source or ''),
                            # …and the name of the thing itself, when it has one.
                            'source_short': str(spec.get('short') or ''),
                            'key': str(key), 'value': text})
    # Standards before a vendor's own MIB, and that is the order a person reads these in:
    # what EVERY device is (RFC 1213), then what this one is (the vendor's MIB), then what is
    # plugged into it. Alphabetically the standard came last, which is the wrong end.
    def _rank(a):
        return int(((sources or {}).get(a['source']) or {}).get('rank') or 0)
    out.sort(key=lambda a: (a['row'] != '', a['row'], a['module'], _rank(a), a['source'],
                            a['key']))
    return out


def _headline_of(meta: dict, row: dict, data: dict):
    """The field's headline flag, once this ROW has been allowed to keep it.

    A summary is not a dump, and a table is where the difference shows. HOST-RESOURCES-MIB
    reports every store a host has: on a NAS running containers that is physical memory, swap,
    the buffers — and then forty bind mounts of the same volume, so the Details tab came out as
    five useful rings followed by thirty-nine that all said 67 % of the same 31 TiB.

    Which rows belong there is the TABLE's answer (``headline_rows``), tested against a fact
    the device itself reported — ``hrStorageType`` says "this row is RAM" or "this row is a
    fixed disk". Not against the row's NAME: a volume is ``/volume1`` on one machine and ``C:``
    on the next, and a panel matching on paths is a panel that knows what Linux is.

    A row-level rule never touches the device's OWN figures (no row): CPU idle and a chassis
    temperature are not rows of anything and have nothing to be filtered by.
    """
    flag = (meta or {}).get('headline') or False
    rule = (meta or {}).get('headline_rows') or {}
    if not flag or not rule or not (row or {}).get('row'):
        return flag
    attrs = (data or {}).get('_attrs')
    facts = {}
    if isinstance(attrs, dict):
        got = attrs.get(str((meta or {}).get('source') or ''))
        # The older flat shape is `{role: value}` with no source. Read either, because a
        # sample written before the nesting is still on disk until the next cycle.
        facts = got if isinstance(got, dict) else {k: v for k, v in attrs.items()
                                                  if not isinstance(v, dict)}
    if rule.get('role'):
        value = str(facts.get(rule['role']) or '').strip()
        if value not in set(rule.get('any') or ()):
            return False
    # A pattern on the row's NAME, for a table whose rows differ by nothing else. Bounded the
    # same way `split_row` is: `re` has no timeout, so a pattern somebody wrote badly would be
    # a worker that stops answering, and a row name is short.
    pattern = rule.get('row_matches') or ''
    if pattern:
        name = str((row or {}).get('row') or '')
        if len(name) > _ROW_SPLIT_MAX:
            return False
        try:
            if not re.search(pattern, name):
                return False
        except re.error:
            return False
    return flag


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
            # Some tables answer with a name that carries a qualifier — a Synology calls a
            # disk in an expansion bay "Drive 1 (DX517-1)" — and the MIB has no column for
            # it, so the only place that fact exists is the name the device composed. The
            # PROFILE says how to separate the two, because assuming anything about
            # parentheses is a statement about one vendor and belongs in that vendor's file.
            #
            # Split here and not in the browser: it runs once per measurement instead of on
            # every repaint, and what reaches the screen is data rather than a rule.
            row_name, row_group = split_row(row.get('row') or '',
                                            (meta or {}).get('row_split') or '')
            out.append({
                'module': mod,
                'key':    row.get('key'),
                'item':   row.get('name'),
                # Which row of the device it is ('' when the device itself is the answer).
                # The screen that draws this is already about one device, so its name is the
                # one word on the card that carries no information.
                'row':       row_name,
                # …and which part of the device that row lives in, when its name said so.
                'row_group': row_group,
                # The name BEFORE the split, which is the one the row is filed under
                # everywhere else — the attributes recorded beside it (a disk's model and
                # serial, a SMART attribute's status) carry it unsplit. Sent so the screen can
                # put a row's facts next to that row without re-deriving a split it did not do.
                'row_key':   row.get('row') or '',
                'field':  field,
                'label':  (meta or {}).get('label') or field,
                'unit':   (meta or {}).get('unit') or '',
                # Which part of the device this measures, as the module groups it — the
                # heading a person reads instead of an alphabet of sixty-four field names.
                'source':       (meta or {}).get('source') or '',
                'source_label': (meta or {}).get('source_label') or '',
                # …and what the thing itself is called, when the profile says. The identity
                # cards and the summary tiles both want this one; the family rail, where you
                # are choosing among profiles, wants the title.
                'source_short': (meta or {}).get('source_short') or '',
                # …and whether it is a standard or a vendor's MIB, which is the order the
                # summary's sections read in for the same reason the identity cards do.
                'source_rank':  int((meta or {}).get('source_rank') or 0),
                # `line` or `state`: whether the value is a graph or a badge. Declared, not
                # guessed from its unit — a number without one may be either.
                'chart':        (meta or {}).get('chart') or '',
                # What this field's numbers MEAN, when the module knows. An agent answers "1"
                # and only the MIB it came from says that 1 is Normal.
                'states':       (meta or {}).get('states') or {},
                # Whether this is one of the handful somebody wants before the other thousand.
                # Declared by the profile, because which values answer "how is this machine"
                # is a fact about the equipment: a switch's headline is its throughput and a
                # UPS's is its battery.
                'headline':     _headline_of(meta, row, data),
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
