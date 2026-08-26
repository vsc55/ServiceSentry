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
_HOST_FIELDS = ('uid', 'name', 'address', 'kind', 'device_type', 'os', 'virtual',
                'maintenance',
                # What the machine SAID it runs, where nobody has chosen. Not the setting —
                # the answer the setting stands for; see `enrich_hosts`.
                'os_auto',
                # …and who made it, which one it is, and the mark to draw for the maker. The
                # registry holds none of these: they are the device's own word, and until now
                # the only screen that showed them was the identity column of one device page.
                'vendor', 'model', 'brand',
                'tags', 'description', 'status', 'modules_total', 'modules_active',
                # …and which of its rows somebody said are worth an alert, so the screen can
                # show the mark it set. A list of names it already displays: no secret in it,
                # and the projection stays a whitelist.
                'watch')


def fleet_row(host: dict) -> dict:
    """One host, projected to what the live section shows."""
    out = {k: host.get(k) for k in _HOST_FIELDS}
    out['tags'] = list(host.get('tags') or [])
    # A dict either way: the row is JSON, and a screen that has to test for null before it can
    # ask for a name is a screen with two shapes to draw.
    out['brand'] = dict(host.get('brand') or {})
    out['virtual'] = bool(host.get('virtual'))
    out['maintenance'] = bool(host.get('maintenance'))
    # A host with no enabled checks has no status at all (see hosts.service._host_statuses),
    # and that is not the same as "fine". The empty string travels as it is so the screen can
    # say "not watched" instead of painting a machine nobody is looking at as OK.
    out['status'] = str(host.get('status') or '')
    out['watch'] = [{'module': w['module'], 'row': w['row'],
                     # …and what the row was marked AS. Without it the screen can say a port
                     # is watched and not that it is the line out, which is the whole point of
                     # having said so.
                     'role': str(w.get('role') or '')}
                    for w in (host.get('watch') or ())
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


def sources_of(fields_by_module: dict, declared: dict | None = None) -> dict:
    """``{source_id: {'label', 'short', 'rank'}}`` — how to NAME and ORDER what answered.

    A module records an attribute under the id of whatever produced it (``synology_ups``), and
    an id is not a name: the identity column was printing them raw beside values that were
    translated. The module declares the name per language beside every measurement that came
    from the same source, so this reads that declaration rather than asking for a second one.

    *declared* is the module's own ``sources`` map, and it is read FIRST. A source that only
    ever answers TEXT contributes no measurement at all, so nothing in the field map carries
    its name — the VLAN table's card was headed `bridge_vlans` under a list of translated VLAN
    names. Reported from the screen. Falling back to the id stays: a word somebody can act on
    beats a blank heading, and a module that declares neither is unchanged.
    """
    out: dict = {}
    for mod in (declared or {}).values():
        for src, spec in (mod or {}).items():
            if str(src or '').strip():
                brand = (spec or {}).get('brand')
                out[str(src)] = {'label': str((spec or {}).get('label') or '') or str(src),
                                 'short': str((spec or {}).get('short') or ''),
                                 'rank':  int((spec or {}).get('rank') or 0),
                                 # What this source calls the facts it files under its own
                                 # keys — the ones the core has no word for. See `attributes`.
                                 'attrs': dict((spec or {}).get('attrs') or {}),
                                 # Who MADE the thing that answered — see `identity_of`. Only
                                 # the module's own declaration carries it: a field map is
                                 # built from measurements, and a manufacturer is not one.
                                 'brand': dict(brand) if isinstance(brand, dict) else {},
                                 # …and how it recognises a maker in what it REPORTS, for the
                                 # profiles that speak for nobody in particular.
                                 'brands': list((spec or {}).get('brands') or [])}
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


def fleet_identity(status_raw: dict, hosts: list, sources: dict | None = None) -> dict:
    """``{uid: {os, vendor, model, brand}}`` for a whole fleet, one pass per machine.

    What the screens want out of the recorded state, worked out where the recorded state is
    already open. Every machine, not only the ones still on ``auto``: the OS is the one fact
    with a setting to lose to, and skipping the rest of the fleet would mean a switch whose OS
    somebody pinned also lost its manufacturer.
    """
    from lib.core.hosts.resolve import os_from_facts, reported_facts        # noqa: PLC0415
    out: dict = {}
    for host in hosts or ():
        uid = str((host or {}).get('uid') or '')
        if not uid:
            continue
        facts = reported_facts(status_raw, uid)
        if not facts:
            continue
        said = identity_of(facts, sources)
        said['os'] = os_from_facts(facts)
        if any(said.values()):
            out[uid] = said
    return out


def brand_said(vendor: str, sources: dict | None = None) -> dict:
    """The maker a reported vendor string stands for — ``{}`` when nobody recognises it.

    A server with no vendor MIB still knows what it is: `dmidecode` answers "HP", "Dell Inc.",
    "QEMU", and the profile that reads DMI is the thing that knows what DMI answers, so the
    table lives THERE (``brands``, see `lib.core.snmp.profiles`) and this only matches against
    it. A name nobody recognises is not an error and not a blank — it stays the brand's name,
    with no mark to draw.

    Matched as a substring on purpose: one machine says "HP", the next "Hewlett-Packard", and
    the third "HPE ProLiant". They are the same rack.
    """
    said = str(vendor or '').strip().lower()
    if not said:
        return {}
    for spec in (sources or {}).values():
        for entry in (spec or {}).get('brands') or ():
            if any(w and w in said for w in (entry.get('any') or ())):
                return {k: v for k, v in entry.items() if k != 'any'}
    return {}


def identity_of(facts: dict, sources: dict | None = None) -> dict:
    """``{'brand', 'vendor', 'model'}`` — who made this box and which one it is.

    *facts* is :func:`lib.core.hosts.resolve.reported_facts`; *sources* is :func:`sources_of`.

    **The brand comes from whatever RECOGNISED the device, not from a list here.** A profile
    that matches on `1.3.6.1.4.1.14988` is the only thing in the product that knows a device
    under that tree was made by MikroTik, and it says so beside the match. The core carries the
    answer and never learns a manufacturer's name — the same rule that keeps module names out
    of it.

    **The model comes from the same answerer as the brand.** One registry entry fronts several
    pieces of equipment: a NAS and the UPS plugged into it both answer "model", and picking the
    two facts independently is how a Synology came to be listed as a Smart-UPS. Where the brand
    is not declared by anybody, the lowest-ranked source wins — standards before a vendor's own
    MIB before what is plugged in, which is the order the identity column already reads in.

    A device whose profile declares no brand but which SAYS who made it (a server with the
    `extend` directives set up) keeps its word: the vendor it reported is the brand's name, with
    no mark to draw beside it.
    """
    sources = sources or {}
    rank = lambda src: int((sources.get(src) or {}).get('rank') or 0)          # noqa: E731
    said = lambda role: sorted((facts or {}).get(role) or (),                  # noqa: E731
                               key=lambda s: rank(s.get('source')))
    brand, of_source = {}, ''
    for cand in sorted({s['source'] for vals in (facts or {}).values() for s in vals},
                       key=rank):
        found = (sources.get(cand) or {}).get('brand')
        if isinstance(found, dict) and found.get('name'):
            brand, of_source = dict(found), cand
            break
    # Whoever declared the brand IS the box, so nothing else gets to answer for it. A NAS with
    # a UPS plugged into it answers "model" twice and "vendor" once — and the once is the UPS's
    # — so a fact taken from wherever it happened to appear made a DS1821+ manufactured by APC.
    # Where nobody declared a brand there is no box to be wrong about: the lowest-ranked source
    # leads, which is the order the identity column already reads in.
    def pick(vals):
        if of_source:
            return next((v['value'] for v in vals if v['source'] == of_source), '')
        return vals[0]['value'] if vals else ''

    vendor = pick(said('vendor'))
    if not brand and vendor:
        # Nobody's MIB recognised it, but it told us who made it — and one of the profiles may
        # know that word: the one that READ it does. Failing that the name alone, which is
        # still an answer and is the only one some machines will ever give.
        brand = brand_said(vendor, sources) or {'name': vendor}
    return {'brand': brand, 'vendor': vendor or str(brand.get('name') or ''),
            'model': pick(said('model'))}


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
            # Who this card is about. Declared by the source where the source IS a maker's
            # (`mikrotik_routeros`), and otherwise whatever it reported — the `extend` card of
            # an HP is a card about an HP, and heading it "Machine" is the one word on it that
            # carries no information.
            card = spec.get('brand') if isinstance(spec.get('brand'), dict) else {}
            if not card:
                card = brand_said(facts.get('vendor') or '', sources)
            for key, value in facts.items():
                text = str(value if value is not None else '').strip()
                if not text:
                    continue      # an empty attribute is one the device did not answer
                # …and what to CALL it, when only the source knows. A fact filed under a
                # ROLE is named by the core in every language; one filed under the profile's
                # own metric key has no such word, and the screen was printing the key with
                # the lookup prefix still on it: `attr_mt_active_fan`. Empty for a role, which
                # is what leaves the core's word in charge.
                named = str((spec.get('attrs') or {}).get(str(key)) or '')
                out.append({'module': row.get('module') or '', 'row': row.get('row') or '',
                            'label': named,
                            'item': row.get('name') or '', 'source': str(source or ''),
                            # The name the source gives itself, in the reader's language. Falls
                            # back to the id: a word somebody can act on beats a blank heading.
                            'source_label': str(spec.get('label') or '') or str(source or ''),
                            # …and the name of the thing itself, when it has one.
                            'source_short': str(spec.get('short') or ''),
                            # …and the mark of whoever made it. `said` when the maker was read
                            # off the device rather than declared by the profile: a profile
                            # that speaks for one maker has a better word for its card
                            # ("RouterOS") than the maker's name, and one that speaks for
                            # nobody has none — so the screen knows which to head it with.
                            'source_brand': dict(card),
                            'source_brand_said': bool(card) and not spec.get('brand'),
                            'key': str(key), 'value': text})
    _aggregate_members(out)
    # WHAT THE BOX IS first, then what every device is, then what is plugged into it.
    #
    # It used to be the middle one leading — the standard MIB, on the grounds that "VLANs above
    # System is the wrong first sentence about a switch". Which was right about the VLANs and
    # wrong about the order: the first sentence about a switch is that it is a MikroTik
    # CRS310. Reported from the screen, as three device pages where the card naming the
    # equipment sat under the one naming its contact address.
    #
    # A card with a MAKER is the one about the box, and that is a fact the card carries rather
    # than a list here of which sources are identities.
    def _rank(a):
        rank = int(((sources or {}).get(a['source']) or {}).get('rank') or 0)
        return (0, rank) if a.get('source_brand') else (1, rank)
    out.sort(key=lambda a: (a['row'] != '', a['row'], a['module'], _rank(a), a['source'],
                            a['key']))
    return out


#: Beyond this many boxes it stops being an arrangement of a map and starts being somebody
#: using their account as a key-value store. A fleet that big is not read as a picture anyway.
LINK_LAYOUT_MAX = 500

#: Far outside any drawing anyone will make, and small enough that no arithmetic on it
#: overflows into a viewBox nobody can zoom back out of.
_LINK_LAYOUT_FAR = 1_000_000


#: How many drawings one account may hold an arrangement for. Two exist; the cap is here so
#: the field cannot become somewhere to put anything else.
LINK_LAYOUT_CANVASES = 8


#: Where a drawing's arrangement USED to be kept, for the one that had somewhere of its own
#: before there were two. A rename that loses an arrangement is a rename that broke something,
#: and this is read once and written forward under the new field.
LINK_LAYOUT_WAS = {'infraLinkSvg': 'infra_link_layout'}


def map_layouts_of(user) -> dict:
    """The arrangements an account holds, including one written before the field was keyed.

    Read through here and not off the record, so the day the old field goes there is one place
    that stops mentioning it.
    """
    out = normalise_map_layouts((user or {}).get('infra_map_layouts'))
    for name, was in LINK_LAYOUT_WAS.items():
        if not out.get(name):
            got = normalise_link_layout((user or {}).get(was))
            if got:
                out[name] = got
    return out


def normalise_map_layouts(raw) -> dict:
    """``{drawing: {uid: {'x', 'y'}}}`` — the arrangements one account holds.

    Two drawings take one: the map of addresses and the map of cables. Keyed by the drawing,
    because where a machine sits on one says nothing about where it should sit on the other.
    """
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for name, layout in list(raw.items())[:LINK_LAYOUT_CANVASES]:
        key = str(name or '').strip()
        if not key or len(key) > 64 or not key.isidentifier():
            continue
        got = normalise_link_layout(layout)
        if got:
            out[key] = got
    return out


def normalise_link_layout(raw) -> dict:
    """``{uid: {'x': float, 'y': float}}`` — with everything that is not that dropped.

    Where somebody has PUT each box on one drawing. Checked here and not at either end,
    because both ends are the same browser: it is written by one and drawn by another, and a
    coordinate that is not a number puts a box at NaN — which draws nothing at all and reads as
    a device that has vanished. The same reason the browser validates its own copy on the way
    out of local storage.

    Not config. It is a preference about a PICTURE, which is the same thing a dashboard layout
    is, and it is filed the same way: on the account. Two people looking at one rack are
    entitled to two arrangements of it.
    """
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for uid, at in list(raw.items())[:LINK_LAYOUT_MAX]:
        key = str(uid or '').strip()
        if not key or len(key) > 64 or not isinstance(at, dict):
            continue
        try:
            x, y = float(at.get('x')), float(at.get('y'))
        except (TypeError, ValueError):
            continue
        if not (-_LINK_LAYOUT_FAR < x < _LINK_LAYOUT_FAR):
            continue                      # NaN and the infinities fail this too, on purpose
        if not (-_LINK_LAYOUT_FAR < y < _LINK_LAYOUT_FAR):
            continue
        out[key] = {'x': x, 'y': y}
    return out


#: What separates one port from the next where an aggregate lists its members.
_MEMBER_JOIN = ', '


def _member_sort(name: str) -> list:
    """Numeric-aware, so a list reads the way the front of a switch does: 12 after 3, which an
    alphabetical sort does not do."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', str(name or ''))]


def _aggregate_members(attrs: list) -> None:
    """Give every aggregate the list of ports that are IN it.

    The MIB answers this one way round only: a PORT says which aggregator it is attached to,
    and the aggregator says nothing at all. So the panel showed eight rows called Po1…Po8 and
    the only way to learn what was in one was to read twenty-eight port rows looking for it.

    Turned round HERE and not in the browser, for the reason every other join on this path is:
    a second implementation of "which ports are in that bond" is free to disagree with this
    one, and the day it did the map and the device page would say different things about the
    same switch.
    """
    members: dict = {}
    spec: dict = {}
    for a in attrs:
        if a.get('key') != 'aggregate' or not a.get('row') or not a.get('value'):
            continue
        members.setdefault(str(a['value']), []).append(str(a['row']))
        spec.setdefault(str(a['value']), a)
    if not members:
        return
    # Only where the aggregate is a row this device actually reported. A name that matches no
    # row is an interface the panel is not reading, and inventing a row for it would put a
    # heading on the screen with nothing under it.
    rows = {str(a.get('row') or '') for a in attrs}
    for name, ports in members.items():
        if name not in rows:
            continue
        src = spec[name]
        listed = sorted(set(ports), key=_member_sort)
        attrs.append({'module': src.get('module') or '', 'row': name,
                      'item': src.get('item') or '', 'source': src.get('source') or '',
                      'source_label': src.get('source_label') or '',
                      'source_short': src.get('source_short') or '',
                      'key': 'aggregate_members',
                      'value': _MEMBER_JOIN.join(listed),
                      # The rows this list IS, beside the words it reads as. A fact whose
                      # value happens to be several row names is a fact somebody wants to
                      # open one of — and the screen must not learn to split a string on a
                      # comma to find out which, because a row name may contain one.
                      'rows': listed})


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


def metrics(results: list, fields_by_module: dict, names: dict | None = None) -> list:
    """The numbers behind a host's results.

    *results* is what :func:`lib.core.hosts.service.build_host_status` returns; each row
    carries its module and its ``data`` bag. *fields_by_module* is
    ``{module: {field: {label, unit}}}`` — the module's own ``__history__`` declaration,
    already translated.

    *names* is ``{module: its name}`` — what to call a measurement's family when the module
    did not group it. Most do not: grouping by SOURCE is a device-profile idea, so a ping, a
    certificate and a disk check all arrived with no source at all and landed in one pile with
    an EMPTY heading. Reported from the screen as a button with a count and no word on it.

    The module is the answer, and it is the same rule the sourced ones follow — grouped by
    whatever produced them. Its own name, from its own lang file, so the core still ships no
    string naming a module.

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
                # …and where it did not group them, the module itself. An empty heading
                # is the one word on a rail that carries no information — see `names`.
                'source':       (meta or {}).get('source') or mod,
                'source_label': ((meta or {}).get('source_label')
                                 or (names or {}).get(mod) or mod),
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
