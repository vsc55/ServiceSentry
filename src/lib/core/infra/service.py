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
                'tags', 'description', 'status', 'modules_total', 'modules_active',
                # …and which of its rows somebody said are worth an alert, so the screen can
                # show the mark it set. A list of names it already displays: no secret in it,
                # and the projection stays a whitelist.
                'watch')


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
    out['watch'] = [w for w in (host.get('watch') or ())
                    if isinstance(w, dict) and w.get('module') and w.get('row')]
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


def _tally_fact(tallies: dict, mod: str, field: str, meta: dict, row: dict,
                data: dict) -> None:
    """Add one row's FACT to the count its column is keeping."""
    if not row.get('row'):
        return
    if meta.get('tally') != 'all' and not _headline_rows_admits(meta, row, data):
        return
    facts = _facts_for(meta, data)
    seen = str(facts.get(meta.get('tally_role') or '') or '').strip()
    if not seen:
        return
    _counted(tallies, mod, field, meta, row, seen)


def _counted(tallies: dict, mod: str, field: str, meta: dict, row: dict,
             seen: str) -> None:
    """Add one row to a counted column — the number, and the row itself.

    The rows are kept and not only tallied, because a count is a question somebody then wants
    to open: "21 VLANs" is the summary and "which 21" is the next sentence. Answered HERE
    rather than re-derived in the browser, for the reason every other half of this file is:
    the rule that decides what a count is about (`headline_rows`, `tally: "all"`, the state a
    reading maps to) is applied on this side, and a screen re-applying it from the payload
    would be a second implementation of it — free to disagree, and the day it did the count
    and the list behind it would say different things about the same switch.
    """
    bucket = tallies.setdefault((mod, field), {'meta': meta, 'counts': {}, 'rows': {},
                                               'key': row.get('key'), 'item': row.get('name'),
                                               'ts': row.get('ts', '')})
    bucket['counts'][seen] = bucket['counts'].get(seen, 0) + 1
    # The name the row is filed under everywhere else — before the profile's split, which is
    # what the measurements carry as `row_key`.
    bucket['rows'].setdefault(seen, []).append(str(row.get('row') or ''))


def _facts_for(meta: dict, data: dict) -> dict:
    """The facts this row recorded under the profile that produced *meta*.

    The older flat shape is `{role: value}` with no source. Read either, because a sample
    written before the nesting is still on disk until the next cycle.
    """
    attrs = (data or {}).get('_attrs')
    if not isinstance(attrs, dict):
        return {}
    got = attrs.get(str((meta or {}).get('source') or ''))
    return got if isinstance(got, dict) else {k: v for k, v in attrs.items()
                                              if not isinstance(v, dict)}


def _headline_rows_admits(meta: dict, row: dict, data: dict) -> bool:
    """Whether this row is one the table's `headline_rows` rule is about.

    The predicate behind `_headline_of`, on its own so the tally can ask the same question.
    Two callers of one rule, because a summary that counted rows the cards do not show would
    be two answers to "which of these matter".
    """
    return bool(_headline_of({**(meta or {}), 'headline': True}, row, data))


def _is_fitted(meta: dict, data: dict) -> bool:
    """Whether the piece of equipment this reading is of is there — see `present_when`."""
    gate = (meta or {}).get('present_when') or {}
    field = str(gate.get('field') or '')
    if not field:
        return True         # a profile that says nothing describes something that is there
    seen = (data or {}).get(field)
    if isinstance(seen, bool) or not isinstance(seen, (int, float)):
        # The evidence column did not answer THIS cycle. Present, because the alternative is a
        # summary that empties itself on one lost datagram — and a reading that is missing is
        # not a reading of zero.
        return True
    try:
        return float(seen) > float(gate.get('above') or 0)
    except (TypeError, ValueError):
        return True


def _state_key(value) -> str:
    """A reading as the string a `states` map is keyed by (`"1"`, not `1` or `1.0`)."""
    if value is None or isinstance(value, bool):
        return ''
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    return str(int(number)) if number.is_integer() else str(number)


def _tally_rows(tallies: dict) -> list:
    """One entry per counted column: how many rows were in each state.

    Emitted as a measurement of the DEVICE (no row) because that is what it is about, and with
    the state map beside it so the screen can turn "1: 6" into "6 up" without learning what
    ifOperStatus is. `headline` is `tally` rather than `True`: the summary draws it as a row of
    counts and not as one big number, and a screen that had to guess which from the shape of
    the payload would guess wrong the day a device answers one state.
    """
    out = []
    for (mod, field), bucket in tallies.items():
        meta = bucket['meta'] or {}
        counts = bucket['counts']
        if not counts:
            continue
        out.append({
            'module': mod, 'key': bucket['key'], 'item': bucket['item'],
            'row': '', 'row_group': '', 'row_key': '',
            'field': field, 'label': meta.get('label') or field, 'unit': '',
            'source': meta.get('source') or '', 'source_label': meta.get('source_label') or '',
            'source_short': meta.get('source_short') or '',
            'source_rank': int(meta.get('source_rank') or 0),
            'chart': 'value', 'states': meta.get('states') or {},
            'headline': 'tally', 'icon': meta.get('icon') or '', 'identity': False,
            # The tally itself, and the total beside it: "6 up" reads differently under
            # "of 24" than under "of 6", and the reader should not have to add up the badges.
            'counts': counts, 'value': sum(counts.values()),
            # WHICH rows are behind each count, so "21 Virtual (VLAN)" can be opened onto the
            # twenty-one. Filed under the name the measurements carry (`row_key`), which is
            # how the screen joins a row to everything else the device said about it.
            'rows': {k: v for k, v in (bucket.get('rows') or {}).items() if v},
            # …and, for a count over a FACT, which fact it counted. The value never reaches
            # `data` — a text column is filed as an attribute — so this is what the screen
            # needs to show the column at all.
            'tally_role': str(meta.get('tally_role') or ''),
            'ts': bucket['ts'], 'series': {},
        })
    return out


def _quiet_key(meta: dict, data: dict, key: str) -> str:
    """The state a reading counts as, once the row has been asked whether it was ever meant
    to be up (`quiet_when` in the profile format).

    A column says what something IS DOING; another says what somebody ASKED it to do. Down
    while it was asked to be up is a fault; down while it was asked to be down is a switch in
    the off position. Reported from the panel as two NAS counting `ovs-system`, `sit0` and
    three VLANs among their down interfaces — all five administratively down, none of them a
    fault, and `docker0` on the same box admin-UP and genuinely down.

    A rule whose column did not answer changes nothing: a row missing the evidence is not a
    row excused by it, and treating silence as permission would quietly stop reporting the
    faults this exists to keep reporting.
    """
    rule = (meta or {}).get('quiet_when') or {}
    field = str(rule.get('field') or '')
    if not field or not isinstance(data, dict) or field not in data:
        return key
    if _state_key(data.get(field)) != str(rule.get('equals') or ''):
        return key
    return str(rule.get('state') or '') or key


def _headline_of(meta: dict, row: dict, data: dict, value=None):
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
    if not flag:
        return flag
    # …and whether the thing this profile describes is FITTED at all. An agent answers a table
    # whether or not the hardware behind it exists: a NAS with no GPU answers SYNOLOGY-GPUINFO
    # anyway — 0 % used of 0 B — and every one of those machines grew a GPU card saying
    # nothing. Zero is a reading and cannot say "there is nothing here"; the profile names the
    # column that can (`present_when`), because which reading is the evidence is knowledge
    # about the equipment.
    if not _is_fitted(meta, data):
        return False
    # A value whose meaning is "there is nothing here". A passive switch answers "fan: not
    # present", which is true and is not news — the summary answers "how is this box", and a
    # component the box says it does not have has no condition to report. It stays in
    # Measures, where the question is "what did it say" rather than "how is it".
    state = ((meta or {}).get('states') or {}).get(_state_key(value))
    if isinstance(state, dict) and state.get('absent'):
        return False
    rule = (meta or {}).get('headline_rows') or {}
    if not rule or not (row or {}).get('row'):
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
    tallies: dict = {}          # (module, field) → what a counted column adds up to
    for row in results or ():
        mod = row.get('module') or ''
        declared = fields_by_module.get(mod) or {}
        data = row.get('data') if isinstance(row.get('data'), dict) else {}
        for field, meta in declared.items():
            # A tally over a FACT rather than over a measurement. What a row IS is recorded as
            # an attribute — a switch says its interface 110 is type 53 — and it is never in
            # `data`, so counting it needs the other half of the result. Worth doing rather
            # than reading the same column a second time as a number: that was a series per
            # interface of a value that never changes.
            if (meta or {}).get('tally_role'):
                _tally_fact(tallies, mod, field, meta, row, data)
                continue
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
            # A column the profile says is worth COUNTING: twenty-four ports each with a
            # badge is the right answer to "what is each port doing" and the wrong one to
            # "how is this switch", where the number wanted is "six up, eighteen down". The
            # per-row values stay exactly as they were — this is a summary beside them, not
            # instead of them.
            # …and only over the rows the table says its summary is about. IF-MIB counts
            # everything a switch has an ifIndex for — the VLANs, the link aggregations, the
            # loopback, the CPU port — so a 24-port switch reported "60 in total", which is
            # true of the MIB and wrong about the box. Same rule the row summaries use, and
            # tested against a fact the device itself reported (`ifType`) rather than against
            # a name: what counts as a port is the MIB's answer, not the panel's.
            if ((meta or {}).get('tally') and row.get('row')
                    and ((meta or {}).get('tally') == 'all'
                         or _headline_rows_admits(meta, row, data))):
                _counted(tallies, mod, field, meta, row,
                         _quiet_key(meta, data, _state_key(value)))
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
                # …and which other field belongs in the SAME picture, when the profile says
                # two columns are one question. Traffic in and traffic out are the case.
                'chart_with':   list((meta or {}).get('chart_with') or ()),
                'chart_label':  (meta or {}).get('chart_label') or '',
                # What this field's numbers MEAN, when the module knows. An agent answers "1"
                # and only the MIB it came from says that 1 is Normal.
                'states':       (meta or {}).get('states') or {},
                # …and WHICH of them this row is in, when its own value is not the whole
                # answer: an interface that is down because somebody switched it off is not
                # an interface that is down. Sent rather than left for the browser to work
                # out, so the badge, the count and the history all read the same row the
                # same way.
                'state_key':    _quiet_key(meta, data, _state_key(value)),
                # Whether this is one of the handful somebody wants before the other thousand.
                # Declared by the profile, because which values answer "how is this machine"
                # is a fact about the equipment: a switch's headline is its throughput and a
                # UPS's is its battery.
                'headline':     _headline_of(meta, row, data, value),
                # What to draw beside it, when whatever produced it said. A number has no
                # picture of its own and the core has no way to know this one is a temperature.
                'icon':         (meta or {}).get('icon') or '',
                # …and whether it belongs beside what the thing IS rather than among what it
                # is doing: "is there an update" is a property of the box, not a measurement.
                'identity':     (meta or {}).get('identity') or False,
                'value':  value,
                'ts':     row.get('ts', ''),
                # What the screen needs to ask History for the series behind this number.
                # Handed over rather than rebuilt in the browser: the pair (module, key) is
                # how the store indexes a series, and a second place that composes it is a
                # second place to get it wrong the day a module changes its keys.
                'series': {'module': mod, 'key': row.get('key'), 'field': field},
            })
    out.extend(_tally_rows(tallies))
    out.sort(key=lambda m: (m['module'], str(m['item'] or ''), m['label']))
    return out
