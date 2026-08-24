#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Device profiles — the OID matrix.

An SNMP agent answers ``1.3.6.1.4.1.2021.11.9.0`` with ``7``. It does not say that this is the
CPU, that seven is a percentage, or that the number beside it is a byte counter which means
nothing until it is differentiated. Every SNMP tool in existence carries that knowledge
somewhere; here it is a **profile**: a named list of metrics, each mapping an OID to a key, a
label, a unit, a kind and how it should be drawn.

A profile is data, and deliberately not code::

    {
      "id": "if_generic",
      "label": {"en_EN": "Network interfaces", "es_ES": "Interfaces de red"},
      "metrics": [
        {"key": "if_in", "walk": "1.3.6.1.2.1.2.2.1.10", "kind": "counter",
         "unit": "B/s", "width": 32, "index_label": "1.3.6.1.2.1.2.2.1.2"}
      ]
    }

**Two sources, one catalogue.** The product ships profiles as files (they are reviewed in
commits and travel with the release), and an installation may add or override its own — the
device in the rack is always going to be the one nobody wrote a profile for. Both arrive
through :func:`catalog`, custom last, so an override is exactly that and not a second list to
search.

**Everything unusable is dropped, never raised.** A malformed metric costs its own line; a
malformed profile costs that profile. A file somebody edited by hand at 3am must not be able to
stop the monitor — a device whose profile is wrong is one device that goes unmeasured, which is
visible on its own screen, and that is a far better failure than a check cycle that does not
run.
"""

from __future__ import annotations

import json
import os
import re

# Profile and metric ids land in a JSON key, a history field name and a chart label, so they
# keep the same shape the rest of the product demands of an identifier.
_ID_RE = re.compile(r'^[a-z][a-z0-9_]*$')
# A dotted OID, with no leading dot and no trailing junk. The catalogue does not resolve names
# (that is the MIB browser's job): a profile carries numbers, so it works on an installation
# with no MIBs compiled at all.
_OID_RE = re.compile(r'^\d+(\.\d+)+$')

# How deep a group may name another group. Nesting is useful exactly once or twice — "every
# Linux profile" inside "every server we run" — and past that a person cannot say what a group
# holds by looking at it, which is the whole point of one.
MAX_GROUP_DEPTH = 8

KINDS = ('gauge', 'counter', 'text')
# How a metric wants to be drawn. The section decides what to do with it — this is the profile
# saying what the value IS, not how many pixels it gets.
CHARTS = ('line', 'area', 'value', 'none')

# The shipped catalogue, inside the package that reads it. It used to be a `profiles/`
# directory sitting BESIDE a `profiles.py`, which is a trap rather than a mess: a
# module and a same-named directory in one package resolve by a rule nobody should
# have to know, and the day somebody drops an __init__.py in there the imports change
# meaning in silence.
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sources')
# Where an installation's own profiles live, under the application data directory.
CUSTOM_SUBDIR = 'snmp_profiles'


#: The two halves of a proportion a summary can draw as one figure. Deliberately not open-
#: ended: a vocabulary the core has to understand is one the core has to be able to draw, and
#: two words it knows what to do with beat twenty it passes through and ignores.
HEADLINE_ROLES = ('used', 'total', 'free')

#: A Bootstrap icon name, and nothing that is not one. The value reaches a `class` attribute.
_ICON_RE = re.compile(r'^bi-[a-z0-9-]{1,40}$')


def _label(raw, fallback: str) -> dict:
    """A metric's or profile's name per language.

    A plain string is accepted and becomes the name in every language: a profile for one rack
    in one company should not have to be bilingual to be usable.
    """
    if isinstance(raw, dict):
        out = {str(k): str(v) for k, v in raw.items() if isinstance(v, str) and v.strip()}
        if out:
            return out
    if isinstance(raw, str) and raw.strip():
        return {'*': raw.strip()}
    return {'*': fallback}


def normalise_metric(raw) -> dict | None:
    """One metric declaration, checked into shape (``None`` when it is not usable)."""
    if not isinstance(raw, dict):
        return None
    key = str(raw.get('key') or '').strip().lower()
    if not _ID_RE.match(key):
        return None
    oid = str(raw.get('oid') or '').strip()
    walk = str(raw.get('walk') or '').strip()
    # One or the other, never both: a metric is either a single value or a column of them, and
    # a declaration that says both is one whose author did not decide.
    if bool(oid) == bool(walk):
        return None
    if oid and not _OID_RE.match(oid):
        return None
    if walk and not _OID_RE.match(walk):
        return None
    kind = str(raw.get('kind') or 'gauge').strip().lower()
    if kind not in KINDS:
        return None
    chart = str(raw.get('chart') or ('none' if kind == 'text' else 'line')).strip().lower()
    if chart not in CHARTS:
        chart = 'none' if kind == 'text' else 'line'
    out = {
        'key':   key,
        'kind':  kind,
        'chart': chart,
        'unit':  str(raw.get('unit') or '').strip(),
        'label': _label(raw.get('label'), key.replace('_', ' ').capitalize()),
    }
    if oid:
        out['oid'] = oid
    else:
        out['walk'] = walk
        # The column that NAMES each row. Without it a table of eight interfaces is eight
        # numbered lines, and the number is the SNMP index — which is not the port on the
        # front of the switch, and is the first thing somebody assumes it is.
        # One column, or SEVERAL joined: a SMART table has one row per (disk, attribute), and
        # either column alone names several rows — "Reallocated_Sector_Ct" is a row on every
        # disk in the box, and merging them would chart one disk's sectors as all of them.
        idx = raw.get('index_label')
        if isinstance(idx, (list, tuple)):
            cols = [str(c).strip() for c in idx]
            cols = [c for c in cols if _OID_RE.match(c)]
            if len(cols) == 1:
                out['index_label'] = cols[0]
            elif cols:
                out['index_label'] = cols
        else:
            idx = str(idx or '').strip()
            if idx and _OID_RE.match(idx):
                out['index_label'] = idx
        # The factor this reading has to be multiplied by, when the DEVICE decides it and not
        # the profile. Storage is the case that forces it: a filesystem table reports its size
        # in allocation units and puts the size of a unit in a column beside it, per row —
        # 4096 on most agents, 512 or 65536 on plenty, and a profile that guessed would report
        # a NAS as sixteen times smaller than it is with nothing on screen saying so.
        sby = str(raw.get('scale_by') or '').strip()
        if sby and _OID_RE.match(sby):
            out['scale_by'] = sby
        # Which TABLE this column belongs to, for the tables whose rows have no names. Row
        # identity is the row's name, and two nameless tables of one device fall back to their
        # SNMP indices — where storage row 3 and processor row 3 are not the same row and
        # would silently merge into one. Named tables do not need it: the name is the identity.
        grp = str(raw.get('group') or '').strip().lower()
        if grp and _ID_RE.match(grp):
            out['group'] = grp
        # WHICH ROWS of the table this metric is about, by what another column says about
        # them. A routing table is the case that forces it: the default gateway is the next
        # hop OF THE ROW whose destination is 0.0.0.0, and every other row's next hop is a
        # different answer to a different question. Without it a profile can read a column or
        # nothing, and "the column, filtered" is not something the reader can express.
        #
        # An exact match on a value and not a pattern: the values this selects on are
        # protocol constants — a destination of 0.0.0.0, a type, a status — and a regular
        # expression here would be a way to write a filter that half-matches by accident.
        # The column that belongs WITH this one, on the same row. An address and its
        # netmask are two columns of one table and one fact — "192.168.1.10" and
        # "255.255.255.0" as separate lines is arithmetic left to the reader, and as separate
        # LISTS ("a, b, c" and "m, m, m") the pairing is gone altogether. The same shape is
        # what an ARP table needs, and a route table, so it is declared rather than special-
        # cased: which column, what joins them, and how the second one is written.
        #
        # `as: "prefix"` is the one rendering the core knows, and it is IP arithmetic rather
        # than knowledge about any device: a dotted netmask written as the number of bits.
        # A value that is not a contiguous mask keeps its own text — a wrong number would be
        # worse than an ugly one.
        pair = raw.get('with')
        if isinstance(pair, dict):
            p_oid = str(pair.get('oid') or '').strip()
            if p_oid and _OID_RE.match(p_oid):
                mode = str(pair.get('as') or '').strip().lower()
                out['with'] = {'oid': p_oid,
                               'sep': str(pair.get('sep') if pair.get('sep') is not None
                                          else ' '),
                               'as': mode if mode in ('prefix',) else ''}
        # A table of things this device SAW, rather than of things it is. A switch's
        # forwarding table and a machine's ARP cache are hundreds of volatile rows that
        # nobody wants alerts about and that are only worth anything joined across the fleet
        # — as ordinary rows they would be a `check_state` row and a history series per MAC.
        # So they go to their own store (`lib.core.infra.evidence`) and never become results.
        #
        # The KIND is the profile's word. The core does not know what a forwarding table is,
        # and a vocabulary written there would be the one device in front of whoever wrote it.
        # A table whose summary is a TALLY: how many of its rows are in each state.
        #
        # Twenty-four ports, each with its own row, is the right answer to "what is each port
        # doing" and the wrong one to "how is this switch" — nobody reads twenty-four badges,
        # and the number they want is "six up, eighteen down". The core cannot derive that on
        # its own: it would have to know that ifOperStatus is worth counting and that a serial
        # number is not, which is knowledge about a MIB and not about a panel.
        #
        # `true` counts the rows the TABLE says its summary is about — the ports of a switch,
        # not its VLANs and its loopback. `"all"` counts every row, which is what a column
        # that answers "what KIND of thing is this row" needs: it is the one summary whose
        # subject is the rows the other one leaves out.
        if raw.get('tally') and isinstance(raw.get('states'), dict):
            out['tally'] = 'all' if str(raw.get('tally')).strip().lower() == 'all' else True
        # A column recorded as ONE number for the whole device: what all its rows add up
        # to. The tally counts rows and is worked out when the screen is drawn; this is a
        # MEASUREMENT, so it is summed where the reading happens and lands in the series like
        # any other — which is the difference between a number on a card and a graph.
        #
        # A switch's overall traffic is the case: every other monitoring tool draws it and no
        # agent serves it, because it is the sum of the ports and only something holding all
        # the ports at once can add them up.
        if str(raw.get('aggregate') or '').strip().lower() == 'sum':
            out['aggregate'] = 'sum'
        ev = str(raw.get('evidence') or '').strip().lower()
        if ev and _ID_RE.match(ev):
            out['evidence'] = ev
        where = raw.get('where')
        if isinstance(where, dict):
            w_oid = str(where.get('oid') or '').strip()
            w_val = str(where.get('equals') if where.get('equals') is not None else '').strip()
            if w_oid and _OID_RE.match(w_oid) and w_val:
                out['where'] = {'oid': w_oid, 'equals': w_val}
    # A column whose states COLOUR but do not JUDGE.
    #
    # `level` was doing two jobs: it paints the badge and it decides whether the device is
    # in trouble. For a fan or a power supply those are the same answer. For a switch port
    # they are not — an access port with nothing plugged into it is `down`, which is worth
    # a red mark on a list of thirty ports and is NOT a fault of the switch. A rack full
    # of half-populated switches came out permanently red, which is the state that stops
    # meaning anything the first time it is wrong.
    #
    # Which ports matter is a decision about the installation, and the panel has not been
    # given one; the switch's own condition is its CPU, its temperature, its fans and its
    # power supplies, and those still judge. Declared and defaulting to ON, so a profile
    # that says nothing keeps reporting.
    if raw.get('verdict') is False:
        out['verdict'] = False
    # Two columns that are ONE picture. Traffic in and traffic out are not two questions —
    # nobody looks at what a link received without looking at what it sent — and two
    # charts side by side on two different y-scales is that comparison made impossible.
    # Which columns belong together is the profile's word, because the core would have to
    # know that in and out are a pair and that CPU and temperature are not.
    with_keys = [str(k).strip() for k in (raw.get('chart_with') or ())
                 if str(k).strip() and _ID_RE.match(str(k).strip())]
    if with_keys:
        out['chart_with'] = with_keys
        # …and what the combined picture is CALLED. The tile's own label names one half of
        # it, and a chart of both headed "Traffic in" is a chart that lies about itself.
        out['chart_label'] = _label(raw.get('chart_label'), out['label'])
    for num, cast in (('scale', float), ('max_rate', float), ('width', int)):
        if raw.get(num) not in (None, ''):
            try:
                out[num] = cast(raw[num])
            except (TypeError, ValueError):
                pass
    # What this value IS about the machine, for the ones that are not measurements: a name, a
    # model, a serial. The section shows those as identity instead of as data.
    # What to draw beside it. A number has no picture — only whatever produced it knows that
    # this one is a temperature and that one a count of bad sectors — so the profile says, and
    # a metric that says nothing simply gets none.
    #
    # Validated to a Bootstrap icon NAME and not passed through: this ends up in a `class`
    # attribute, and a profile is data an administrator can write.
    icon = str(raw.get('icon') or '').strip().lower()
    if _ICON_RE.match(icon):
        out['icon'] = icon
    role = str(raw.get('role') or '').strip().lower()
    if role and _ID_RE.match(role):
        out['role'] = role
    # A table that describes the BOX rather than the things inside it.
    #
    # Almost every walk is a list of parts: disks, interfaces, volumes, each row a thing with
    # a life of its own, and its model and serial belong beside it. `ipAddrTable` is not that
    # shape. Its rows are the addresses of ONE machine, and filing them per row puts the
    # answer to "what is this box on the network" into five rows nothing opens — collected
    # every cycle and visible nowhere, which is the same as not asking.
    #
    # So the rows of such a table are folded into ONE fact about the device, joined in the
    # order the agent walked them. Only for `text`, and only for a walk: a number folded into
    # a list is a string that used to be a measurement.
    if walk and kind == 'text' and raw.get('of_device'):
        out['of_device'] = True
    # Readings that are not answers. A column answers for every row it has, including the ones
    # that mean nothing to a reader: `ipAddrTable` lists the loopback beside the address the
    # machine is actually reachable on, and "127.0.0.1, 192.168.1.10" leads with the one nobody
    # asked about. The pattern is the PROFILE's — the core has no opinion about what 127 means,
    # and the next profile will want to drop "N/A" or "unknown" instead.
    #
    # A pattern that does not compile is no filter rather than a filter that drops everything:
    # a fact that silently disappears is worse than one with noise in it.
    skip = str(raw.get('skip') or '').strip()
    if skip:
        try:
            re.compile(skip)
            out['skip'] = skip
        except re.error:
            pass
    # Whether this is one of the handful somebody wants BEFORE the other thousand.
    #
    # A device with a full set of profiles answers a thousand values, and "how is this machine"
    # is four or five of them — the CPU, the memory, the temperature, whether the box says it
    # is well. Which ones those are is a fact about the equipment and not about the panel, so
    # the profile says it: a switch's headline is its throughput and a UPS's is its battery,
    # and a core that picked them by name would be a core that knows what a NAS is.
    #
    # `true` is a figure on its own. A ROLE says this figure is one HALF of a proportion —
    # HOST-RESOURCES-MIB gives every store, memory and filesystem alike, as a size and an
    # amount used, and two numbers side by side is arithmetic left to the reader when the
    # answer is "83 %". Which of the two is which cannot be guessed from a label that says
    # "Usado" in one profile and "In use" in the next, so the profile says that too.
    # Beside what the thing IS rather than among what it is doing. "Is there an update" is
    # not a measurement anybody charts — it is a property of the box. Separate from `headline`
    # because they are different questions: one asks which figures answer "how is this
    # machine", this one asks which answer "what is this machine".
    #
    # `true` is a line of its own in the identity card. A ROLE NAME says the value is about
    # that fact and belongs beside it: "is there an update" is a statement about the firmware
    # version, so it reads as a badge next to it rather than as a second entry saying almost
    # the same words. Which fact it annotates is the profile's to know — the core names roles,
    # it does not know that DSM has updates.
    ident = raw.get('identity')
    if isinstance(ident, str) and _ID_RE.match(ident.strip().lower()):
        out['identity'] = ident.strip().lower()
    elif ident:
        out['identity'] = True
    head = raw.get('headline')
    if isinstance(head, str) and head.strip().lower() in HEADLINE_ROLES:
        out['headline'] = head.strip().lower()
    elif head:
        out['headline'] = True
    # What the numbers MEAN, for a value that answers with an enumeration. The agent says
    # "1" and only the MIB it came from says that 1 is Normal, so a panel without this
    # prints the integer — "System status 1, Power supply status 1" — which is a column of
    # numbers nobody can act on.
    states = _states(raw.get('states'))
    if states:
        out['states'] = states
        quiet = _quiet_when(raw.get('quiet_when'), states)
        if quiet:
            out['quiet_when'] = quiet
    return out


def _quiet_when(raw, states: dict) -> dict:
    """When a reading is not news because ANOTHER column says it was never meant to be.

    ``ifOperStatus`` is the case, and nothing about it is special to interfaces: one column
    reports what something IS DOING and a second reports what somebody ASKED it to do. Down
    while it was asked to be up is a fault. Down while it was asked to be DOWN is a switch in
    the off position, and reporting that as a fault is reporting the administrator's own
    decision back at them.

    Reported from the panel: two NAS counting `ovs-system`, `sit0` and three VLAN interfaces
    as down. Every one of those answers ``ifAdminStatus = 2`` — Open vSwitch's datapath device
    and the IPv6-in-IPv4 tunnel device are down by design and always will be. The same reading
    on the same box also covered `docker0`, which is admin-UP and genuinely down, and that one
    has to go on saying so: the rule is about what was ASKED, not about which names look
    virtual.

    ``{"field": "if_admin", "equals": 2, "state": "off"}`` — on a row where that field reads
    that value, this reading counts as the named state instead of the one its own value maps
    to. A FIELD and not an OID, so the rule is written in the same words as the rest of the
    profile and everything downstream can apply it without walking anything: the column is
    already sampled and already sits beside this one on the same row.

    The named state has to exist in this metric's own map or the rule is dropped. A
    substitution that lands nowhere would leave the reading judged exactly as it was, wearing
    a declaration that says otherwise — which is worse than not declaring it.
    """
    if not isinstance(raw, dict):
        return {}
    field = str(raw.get('field') or '').strip()
    state = str(raw.get('state') or '').strip()
    if not field or not _ID_RE.match(field) or not state or 'equals' not in raw:
        return {}
    if state not in (states or {}):
        return {}
    return {'field': field, 'equals': str(raw.get('equals')).strip(), 'state': state}


#: What a state MEANS for somebody looking at it, which decides its colour. Declared and not
#: derived from the word: "Degraded" is bad and "Repairing" is not, and no rule about the
#: text can tell those apart.
LEVELS = ('ok', 'warn', 'bad', 'info')


def _present_when(raw) -> dict:
    """How to tell whether the thing this profile describes is actually THERE.

    An agent answers a table whether or not the hardware behind it exists. SYNOLOGY-GPUINFO-MIB
    is the case reported from the panel: a NAS with no GPU answers it anyway — utilisation 0 %,
    memory 0 B — and the summary of every one of those machines grew a GPU card saying nothing.
    A reading of zero is a reading; "there is no GPU here" is not something zero can say on its
    own, and it is not something the panel may decide either.

    So the PROFILE says which column is the evidence: a GPU with no memory at all is not a
    GPU that is idle. ``{"field": "syno_gpu_mem_total", "above": 0}`` — the piece is present
    when that field is a number greater than the threshold, and while it is not, none of this
    profile's readings are news. They stay in Measures, where the question is what the device
    answered rather than how it is; the same place `absent` leaves a component a switch says
    it does not have.

    A rule naming no field is dropped rather than applied: a gate nobody can pass would empty
    a summary for a reason nothing on the screen could explain.
    """
    if not isinstance(raw, dict):
        return {}
    field = str(raw.get('field') or '').strip()
    if not field or not _ID_RE.match(field):
        return {}
    try:
        above = float(raw.get('above') if raw.get('above') is not None else 0)
    except (TypeError, ValueError):
        return {}
    return {'field': field, 'above': above}


def _headline_rows(raw) -> dict:
    """Which ROWS of this table belong on a summary — or ``{}`` for all of them.

    Reported from the screen, and it is the difference between a summary and a dump.
    HOST-RESOURCES-MIB reports every store a host has, and on a NAS running containers that is
    physical memory, swap, the buffers, and then forty bind mounts of the same volume: the
    Details tab came out as five rings of memory followed by thirty-nine rings that all said
    67 % of the same 31 TiB. Nobody can read that, and the summary was the one screen that
    existed so nobody had to.

    The table already says what each row IS — ``hrStorageType`` is a column — so the rule is
    "these types", named by the ROLE the profile files that column under. Not by row name: a
    volume is called ``/volume1`` on one machine and ``C:`` on the next, and a panel matching
    on paths would be a panel that knows what Linux is.

    ``{"role": "kind", "any": ["…25.2.1.2", …]}``. A rule that names no role or no values is
    dropped rather than applied, because a filter nobody can satisfy is a summary that is
    always empty — and an empty summary looks like a device that answered nothing.
    """
    if not isinstance(raw, dict):
        return {}
    out = {}
    role = str(raw.get('role') or '').strip()
    any_of = [str(v).strip() for v in (raw.get('any') or ()) if str(v).strip()]
    if role and any_of:
        out.update({'role': role, 'any': any_of})
    # …or, for a table that has no column saying what its rows are, a pattern for their NAMES.
    # SYNOLOGY-RAID-MIB lists a storage pool and the volumes carved out of it in one table and
    # answers nothing that tells them apart — "Storage Pool 1" and "volume1" differ by name and
    # by nothing else. Matching on names is an assumption about how ONE vendor names things,
    # which is why it lives in that vendor's file, next to the OIDs it is about: the core
    # applies a pattern it was handed and knows nothing about pools.
    pattern = str(raw.get('row_matches') or '').strip()
    if pattern:
        try:
            re.compile(pattern)
        except re.error:
            pattern = ''    # an unusable pattern is no filter, not an empty summary
        if pattern:
            out['row_matches'] = pattern
    return out


def _row_split(raw) -> str:
    """A pattern that separates a row's NAME from the thing it belongs to — or ``''``.

    Some tables answer with a name that already carries a qualifier. A Synology names a disk
    in an expansion bay "Drive 1 (DX517-1)", so eight disks in two enclosures sort into each
    other and read as one shelf of eight. SYNOLOGY-DISK-MIB has no column for the enclosure —
    fifteen objects and not one of them says which shelf a disk is in — so the only place that
    fact exists is inside the name the device itself composed.

    Splitting it is therefore an assumption about how ONE vendor names things, and this is
    where a vendor-specific assumption belongs: in that vendor's profile, written down, next
    to the OIDs it is about. The core stays ignorant of parentheses.

    Two named groups are required, ``row`` and ``group``, because a pattern that matched
    positionally would silently swap them the day somebody reordered it.
    """
    pat = str(raw or '').strip()
    if not pat:
        return ''
    try:
        rx = re.compile(pat)
    except re.error:
        return ''
    if 'row' not in rx.groupindex or 'group' not in rx.groupindex:
        return ''
    return pat


def _states(raw) -> dict:
    """``{value: {label, level}}``, checked into shape — ``{}`` when there is nothing usable.

    The key is the raw value as a STRING: it is what JSON can hold as an object key and what
    the browser compares against. A value the map does not cover is not an error and is not
    guessed at — it falls back to its own number, which is what the whole column did before
    any of this and is honest about not knowing.

    Each state is REBUILT rather than copied, because a profile is data an administrator
    writes and this ends up on a screen. Which means this is a whitelist: a key added to the
    format and not added here is dropped here, quietly, and the guard is the round-trip test
    in `test_snmp_profiles.py` rather than anything raising.
    """
    if not isinstance(raw, dict):
        return {}
    out = {}
    for value, spec in raw.items():
        key = str(value).strip()
        if not key:
            continue
        spec = spec if isinstance(spec, dict) else {'label': spec}
        label = _label(spec.get('label'), '')
        if not label or not any(label.values()):
            continue
        level = str(spec.get('level') or 'info').strip().lower()
        out[key] = {'label': label, 'level': level if level in LEVELS else 'info'}
        # …and whether this value means the thing IS NOT THERE, which the summary needs: a
        # passive switch answers "fan: not present", and a component the box says it does not
        # have has no condition to report. Rebuilt state by state on purpose — a profile is
        # data an administrator writes — so anything not named here is dropped, silently, in
        # the one place that would not raise about it.
        if spec.get('absent'):
            out[key]['absent'] = True
        # …and a MARK of its own, for a state that is worth seeing at a glance without being
        # good or bad. The screen draws one per level, and `info` deliberately draws none:
        # every interface TYPE is `info` — a VLAN is not better or worse than a port — and a
        # grey dot in front of all six of them is six pixels of nothing repeated. "Switched
        # off" is `info` too and is the exact opposite case: neither good nor bad, and the
        # one thing somebody scanning a rail of interfaces wants to pick out. So the profile
        # says which of its `info` states earned a mark, because only the profile knows.
        icon = str(spec.get('icon') or '').strip().lower()
        if _ICON_RE.match(icon):
            out[key]['icon'] = icon
    return out


def normalise(raw) -> dict | None:
    """One profile, checked into shape (``None`` when it is not usable).

    A profile carries **metrics**, or **members** (``includes``), or both. One with neither is
    not a profile: it would sit in the catalogue, be assignable to a machine, and measure
    nothing — which reads as a device that answers nothing rather than as a declaration
    somebody got wrong.

    A profile that names members is what the panel calls a **group**. It is not a second kind
    of thing with a table and a screen of its own: thirteen Synology profiles assigned one by
    one to every NAS in the rack is thirteen chips saying what one word says, and the shape
    that fixes it already existed — an entry in the catalogue with an id, a name and something
    to sample. What a group holds is other entries' ids instead of OIDs, and everything
    downstream (assigning, detecting, charting) goes on speaking about ids.
    """
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get('id') or '').strip().lower()
    if not _ID_RE.match(pid):
        return None
    metrics, seen = [], set()
    for m in (raw.get('metrics') or []):
        norm = normalise_metric(m)
        if norm is None or norm['key'] in seen:
            continue                    # a duplicate key would overwrite its twin's series
        seen.add(norm['key'])
        metrics.append(norm)
    # Members: ids, checked for shape only. Whether they EXIST is not knowable here — a
    # profile is normalised on its own, before the catalogue it belongs to is assembled, and
    # a group written against a custom profile that has not loaded yet is not malformed. The
    # resolution drops what it cannot find (:func:`expand`), which is also what happens when
    # somebody deletes a profile a group named a year ago.
    includes, seen_i = [], set()
    for m in (raw.get('includes') or []):
        mid = str(m or '').strip().lower()
        if not _ID_RE.match(mid) or mid in seen_i or mid == pid:
            continue                    # naming itself is a loop with one link in it
        seen_i.add(mid)
        includes.append(mid)
    if not metrics and not includes:
        return None
    out = {
        'id':      pid,
        'label':   _label(raw.get('label'), pid.replace('_', ' ').capitalize()),
        # What the thing this profile describes is CALLED, as opposed to what the profile is
        # called. They are not the same question and neither can be derived from the other:
        # the catalogue entry has to say "Synology — system (SYNOLOGY-SYSTEM-MIB)" so somebody
        # choosing among forty profiles knows which MIB they are picking, while the card on a
        # device page is naming a box in a rack — "Synology", and the UPS beside it is "UPS".
        # Trimming the long one gets the first right and the second wrong, which is how it was
        # reported. Optional: a profile that says nothing keeps the trimmed title.
        'short_label': _label(raw.get('short_label'), ''),
        'metrics': metrics,
    }
    if includes:
        out['includes'] = includes
    split = _row_split(raw.get('row_split'))
    if split:
        out['row_split'] = split
    rows = _headline_rows(raw.get('headline_rows'))
    if rows:
        out['headline_rows'] = rows
    gate = _present_when(raw.get('present_when'))
    if gate:
        out['present_when'] = gate
    # What this profile is FOR, and how a device is recognised as one of them. Two ways,
    # because devices answer two different questions about themselves:
    #
    #   sysobjectid_prefix — WHO MADE IT. A prefix, so a vendor's tree identifies the family
    #     and the exact node identifies a model nobody wants to enumerate.
    #   probe — WHAT IT SERVES. One OID: if the device answers it, the profile applies. This is
    #     the one that matters for the generic profiles, because "does it implement
    #     HOST-RESOURCES-MIB" is not a question sysObjectID can answer — a Synology, a Linux
    #     box and a Windows server all do, and their sysObjectIDs have nothing in common.
    #
    # Both live in the PROFILE and not in the code that detects: an action carrying a list of
    # "the generic ones" is a list that goes stale the moment somebody adds a profile, which is
    # exactly how the storage profile shipped invisible to detection.
    match = raw.get('match')
    if isinstance(match, dict):
        found = {}
        prefix = str(match.get('sysobjectid_prefix') or '').strip()
        if _OID_RE.match(prefix):
            found['sysobjectid_prefix'] = prefix
        probe = str(match.get('probe') or '').strip()
        if _OID_RE.match(probe):
            found['probe'] = probe
        # Which generic profiles this one replaces on the devices it claims. A Synology runs
        # net-snmp underneath, so it answers the UCD disk-I/O probe AND its own — and both
        # measure the same disks. Detection would propose the pair, and an admin who accepted
        # both would chart every disk twice under two sets of names.
        sup = match.get('supersedes')
        if isinstance(sup, (list, tuple)):
            ids = [str(x).strip().lower() for x in sup]
            ids = [x for x in ids if _ID_RE.match(x)]
            if ids:
                found['supersedes'] = ids
        if found:
            out['match'] = found
    if isinstance(raw.get('description'), (str, dict)):
        out['description'] = _label(raw.get('description'), '')
    return out


def load_dir(directory: str) -> list:
    """Every usable profile in one directory, in file order.

    A directory that does not exist is an empty list and not an error: the folder for the
    installation's own profiles is created the first time somebody puts one there, and until
    then the shipped catalogue is the whole catalogue.
    """
    out: list = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return out
    for name in names:
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(directory, name), encoding='utf-8') as fh:
                prof = normalise(json.load(fh))
        except (OSError, ValueError):
            continue                    # one broken file costs its own profile, nothing else
        if prof:
            out.append(prof)
    return out


def custom_dir(var_dir: str) -> str:
    """Where an installation keeps its own profiles — beside its own MIBs.

    Under ``var_dir`` and not beside the shipped ones: a package upgrade replaces the
    application directory, and a profile somebody wrote for the device in their rack must
    survive that.
    """
    var_dir = str(var_dir or '').strip()
    return os.path.join(var_dir, CUSTOM_SUBDIR) if var_dir else ''


def shipped(directory: str | None = None) -> dict:
    """The profiles that travel with the product, by id."""
    out: dict = {}
    for prof in load_dir(directory or _DIR):
        prof['source'] = 'shipped'
        out[prof['id']] = prof
    return out


def catalog(custom=None, directory: str | None = None, written=None) -> dict:
    """Every profile available, by id — shipped first, the installation’s own last.

    Custom last so an installation can **override** a shipped profile by reusing its id, which
    is what somebody does when the vendor changed an OID in a firmware release and the fix
    cannot wait for the next version of this product.

``written`` is everything written in the panel, which lives in the database rather than
    in a file: a deployment with a web container and a worker container shares the database and
    not the disk, and what somebody writes in the panel has to be what the worker samples. It
    arrives last for the same reason the custom files do — but it may **not** take an id that
    already names something. Overriding a profile is a deliberate act performed by putting a
    file on the machine; doing it by accident from a form, and silently unmeasuring whatever
    that id used to measure, is not the same act at all.
    """
    out = shipped(directory)
    for raw in (custom or []):
        prof = normalise(raw)
        if prof:
            prof['source'] = 'custom'
            out[prof['id']] = prof
    for raw in (written or []):
        prof = normalise(raw)
        if not prof or prof['id'] in out:
            continue
        prof['source'] = 'db'
        out[prof['id']] = prof
    return out


def is_group(profile) -> bool:
    """Does this entry stand for others? A group is what it holds, not a flag it carries."""
    return bool((profile or {}).get('includes'))


def expand(profiles: dict, ids) -> list:
    """The ids to actually sample for *ids*, with every group resolved to its members.

    The one place a group stops being one. Everything upstream — the field on a server, the
    chips, the detection, the backup — deals in whatever ids somebody chose; everything
    downstream deals in profiles that have metrics. Which means a group can be renamed, have a
    profile added to it, or be deleted, and nothing but this function has to know.

    Members come out before the group itself (which contributes only when it also declares
    metrics of its own), in declaration order, deduplicated: two groups that share a profile
    must not sample it twice, which would chart every one of its series against itself.

    Cycle-safe and depth-capped. A group that names another group is a reasonable thing to
    write — "every Linux profile" inside "every server we run" — and a pair that name each
    other is a reasonable thing to write **by mistake**, once, in a form. One of them costs a
    recursion error in the middle of a monitoring cycle; both cost nothing here.
    """
    out: list = []
    seen: set = set()
    path: set = set()

    def walk(pid: str, depth: int) -> None:
        if depth > MAX_GROUP_DEPTH or pid in path:
            return
        prof = profiles.get(pid)
        if prof is None:
            return                      # a member somebody deleted is not a member
        path.add(pid)
        for member in prof.get('includes') or ():
            walk(member, depth + 1)
        path.discard(pid)
        if prof.get('metrics') and pid not in seen:
            seen.add(pid)
            out.append(pid)

    for raw in (ids or ()):
        walk(str(raw or '').strip().lower(), 0)
    return out


def reaches(profiles: dict, ids, target: str) -> bool:
    """Is *target* anywhere below *ids*? The question a save has to answer before it saves.

    Not the same question :func:`expand` answers: expansion returns what can be SAMPLED, and
    a group has no metrics, so a group is never in its output. What a loop is made of is
    groups.
    """
    target = str(target or '').strip().lower()
    path: set = set()

    def walk(pid: str, depth: int) -> bool:
        if depth > MAX_GROUP_DEPTH or pid in path:
            return False
        if pid == target:
            return True
        prof = profiles.get(pid)
        if prof is None:
            return False
        path.add(pid)
        found = any(walk(m, depth + 1) for m in prof.get('includes') or ())
        path.discard(pid)
        return found

    return any(walk(str(p or '').strip().lower(), 0) for p in (ids or ()))


def collapse(profiles: dict, ids) -> list:
    """*ids*, with every run of them that a group already covers replaced by that group.

    A detection against a Synology proposes the thirteen profiles written for it, and putting
    thirteen chips in the field is a correct answer to a question nobody asked. If a group
    holds exactly those thirteen, the group IS the answer — same profiles sampled, one thing
    to read, and one thing to change when the family grows a fourteenth.

    Only a group whose members are **all** present may stand for them. A partial cover would
    quietly assign profiles the device did not answer, which is the failure this whole flow
    exists to avoid: a wrong profile does not fail, it measures numbers that look fine.

    Biggest cover first, ties by id, and a member spent on one group is not available to
    another — so a device that answers both a vendor family and the generic set gets the two
    groups rather than the larger one plus the pieces of the smaller.
    """
    have: list = []
    for raw in (ids or ()):
        pid = str(raw or '').strip().lower()
        if pid and pid not in have:
            have.append(pid)
    present = set(have)

    covers = []
    for gid, prof in profiles.items():
        if not is_group(prof) or gid in present:
            continue
        cover = set(expand(profiles, [gid]))
        if cover and cover <= present:
            covers.append((gid, cover))
    covers.sort(key=lambda c: (-len(c[1]), c[0]))

    chosen: list = []
    spent: set = set()
    for gid, cover in covers:
        if cover & spent:
            continue
        chosen.append((gid, cover))
        spent |= cover
    if not chosen:
        return have

    # Each group lands where its first member was, so what comes out reads in the order the
    # detection found things rather than in the order the catalogue happens to be in.
    out: list = []
    for pid in have:
        if pid not in spent:
            out.append(pid)
            continue
        for gid, cover in chosen:
            if pid in cover and gid not in out:
                out.append(gid)
                break
    return out


def assigned(server: dict) -> list:
    """The profile ids one server carries, in the order they were chosen.

    Here and not in either of its callers, because there are two and they have to agree: the
    scheduler reads this field to decide what to collect, and the panel reads it to show what
    the collection is going to be. Two parsers of one field is a screen that reports a
    profile the sampler never runs — separated by a newline instead of a comma, or by a
    capital letter, both of which somebody types.

    A list or a separated string, because the field is edited as chips and stored as text.
    """
    raw = (server or {}).get('device_profiles')
    parts = ([str(x) for x in raw] if isinstance(raw, (list, tuple))
             else re.split(r'[,\s]+', str(raw or '')))
    seen, out = set(), []
    for p in parts:
        pid = p.strip().lower()
        if pid and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def label_of(obj: dict, lang: str, default_lang: str = 'en_EN') -> str:
    """A profile's or metric's name in the reader's language, however it names itself.

    A plain string is a valid label — ``_label`` says so, and a profile for one rack in one
    company should not have to be bilingual to be usable. This function is called on profiles
    that have been through ``normalise`` (where a string has already become a dict) AND on
    ones that have not: a probe builds its catalogue from raw files. It crashed on the second
    kind, and the failure was not a traceback anybody saw — the sampler caught it, recorded
    that the device had answered nothing, and the screen said the machine was not responding.
    """
    labels = (obj or {}).get('label') or {}
    if isinstance(labels, str):
        return labels.strip() or str((obj or {}).get('id') or (obj or {}).get('key') or '')
    if not isinstance(labels, dict):
        labels = {}
    return (labels.get(lang) or labels.get(default_lang) or labels.get('*')
            or str((obj or {}).get('id') or (obj or {}).get('key') or ''))


def short_label_of(obj: dict, lang: str, default_lang: str = 'en_EN') -> str:
    """What the thing a profile describes is CALLED — or ``''`` when it does not say.

    Empty rather than falling back to the long title, because the two are answers to different
    questions and the caller is the one that knows which it wants. The identity card wants this
    one; the catalogue wants the title.
    """
    labels = (obj or {}).get('short_label') or {}
    if isinstance(labels, str):
        return labels.strip()
    if not isinstance(labels, dict):
        return ''
    return str(labels.get(lang) or labels.get(default_lang) or labels.get('*') or '').strip()


def claims_sysobjectid(profiles: dict, sysobjectid: str) -> list:
    """Every profile that claims this device, most specific first, then by id.

    Longest prefix wins on specificity — a vendor's tree and a model's node under it are both
    legitimate claims, and the more specific one knows more about the machine — but a vendor
    can legitimately have SEVERAL profiles at the same depth: a Synology's system, its disks
    and its volumes are three different subjects and three different profiles, and they all
    claim the same tree. Returning one of them would leave the other two undetected for the
    device they were written for.

    Ties are broken by id so two runs against one unchanged device agree.
    """
    oid = str(sysobjectid or '').strip().lstrip('.')
    if not oid:
        return []
    hits = []
    for pid in sorted(profiles or {}):
        prof = profiles[pid]
        prefix = ((prof.get('match') or {}).get('sysobjectid_prefix') or '')
        if prefix and (oid == prefix or oid.startswith(prefix + '.')):
            hits.append((-len(prefix), pid, prof))
    return [prof for _n, _pid, prof in sorted(hits, key=lambda h: (h[0], h[1]))]


def match_sysobjectid(profiles: dict, sysobjectid: str) -> dict | None:
    """The most specific profile that claims this device, if one does."""
    hits = claims_sysobjectid(profiles, sysobjectid)
    return hits[0] if hits else None


def history_fields(profile: dict, lang: str = 'en_EN') -> dict:
    """``{field: {label, unit, source, source_label}}`` for this profile's measurements.

    The shape :mod:`lib.core.history.service` produces from a module's static ``__history__``
    declaration — because that is what makes a value chartable in History and nameable in the
    Infrastructure section, and a profile is exactly that declaration for values that arrive
    without one. Text metrics are absent on purpose: they are what the machine IS, not what it
    is doing.

    ``source`` is this profile, and it travels with every field because the union that comes
    out the other end has no way to work it back. A device carries a dozen profiles — the
    system, the disks, the RAID, the shares, the UPS plugged into it — and they are what a
    person groups by when a device answers sixty-four different measurements: "disks" is a
    heading somebody can read, and the alphabet is not. Flattened, that grouping was thrown
    away at the only point it existed.

    ``chart`` comes along for the same reason: a profile says whether a value is a line or a
    state, and that is the difference between drawing a graph and drawing a badge.

    ``states`` is what turns the badge into a word. An agent answers "1" and the MIB it came
    from is what says that 1 means Normal — the panel has no way to know and was printing the
    integer, so a column read "System status 1, Power supply status 1, Update available 2",
    which is not information. A profile that declares none is unchanged: its values are still
    numbers, and a value the map does not cover falls back to its number rather than to a
    guess.
    """
    out = {}
    for m in (profile or {}).get('metrics') or ():
        # Text metrics are absent on purpose: they are what the machine IS, not what it is
        # doing, and nothing charts them. One exception, and it is not an exception to that
        # rule: a text column the profile says is worth COUNTING. The count is a measurement
        # about the device even though the thing being counted is a fact — "twenty-nine of
        # these are VLANs" — and the field entry is what carries the words for it. It never
        # reaches the value path, because a text metric's answer is filed as an attribute and
        # is never in `data`.
        if m.get('kind') == 'text' and not m.get('tally'):
            continue
        out[m['key']] = {
            'label':        label_of(m, lang),
            'unit':         m.get('unit', ''),
            'source':       str((profile or {}).get('id') or ''),
            'source_label': label_of(profile or {}, lang),
            'source_short': short_label_of(profile or {}, lang),
            # Whether this is a STANDARD or a vendor's own MIB, and it is not decoration: it
            # is the reading order of a device's identity. RFC 1213 is what every SNMP agent
            # answers, the vendor's MIB is what THIS box answers, and the UPS profile is about
            # something plugged into it — "from what every device is, to what this one is, to
            # what is attached" is how a person reads those three cards, and alphabetical order
            # put the standard last. Declared by the profile (it claims a vendor tree or it
            # does not) rather than decided by a list of ids in the panel.
            'source_rank':  1 if ((profile or {}).get('match') or {}).get('sysobjectid_prefix')
                              else 0,
            # The flag AS DECLARED — `True`, or which half of a proportion it is. Flattened
            # to a boolean here once, and the summary drew two byte counts side by side
            # instead of one percentage: the role survived normalise and died on the way out.
            'headline':     m.get('headline') or False,
            'icon':          m.get('icon') or '',
            'identity':      m.get('identity') or False,
            # Whether the summary of this column is a count of its rows by state.
            'tally':         m.get('tally') or False,
            # Two columns that are one picture. Traffic in and traffic out are not two
            # questions — nobody looks at what a link received without looking at what it
            # sent, and two charts side by side on two different y-scales is the comparison
            # made impossible. Which columns belong together is the PROFILE's word: the core
            # would have to know that in and out are a pair and that CPU and temperature are
            # not, which is knowledge about the MIB.
            'chart_with':    list(m.get('chart_with') or ()),
            # …and what the combined picture is CALLED. The tile's own label names one half of
            # it, and a chart of both headed "Traffic in" is a chart that lies about itself.
            'chart_label':   (label_of({'label': m['chart_label']}, lang)
                              if m.get('chart_with') else ''),
            # For a tally over a FACT: which of the row's facts holds the value to count.
            'tally_role':    m.get('role') if m.get('kind') == 'text' else '',
            # …and the column that can excuse this one, when the profile named one.
            'quiet_when':    dict(m.get('quiet_when') or {}),
            # …and, for a table, which of its rows the summary is about. Carried on every
            # field like `row_split`, because it is a fact about the TABLE and every column of
            # a table is filtered the same way.
            'headline_rows': (profile or {}).get('headline_rows') or {},
            # …and how to tell whether the thing this profile describes is there at all.
            # Carried on every field for the same reason: it is a fact about the PROFILE, and
            # a GPU that is not fitted is not fitted for all of its columns at once.
            'present_when': (profile or {}).get('present_when') or {},
            'chart':        m.get('chart', ''),
        }
        states = states_of(m, lang)
        if states:
            out[m['key']]['states'] = states
        # The profile's, not the metric's: it is a fact about how this TABLE names its rows,
        # and every column of the table is named the same way.
        if (profile or {}).get('row_split'):
            out[m['key']]['row_split'] = profile['row_split']
    return out


def states_of(metric: dict, lang: str = 'en_EN') -> dict:
    """``{value: {label, level}}`` for a metric that answers with an enumeration.

    Declared as ``"states": {"1": {"label": {...}, "level": "ok"}}``. The key is the raw value
    as a STRING, because that is what a JSON object can hold and what the browser will compare
    against; the level is one of ``ok`` / ``warn`` / ``bad`` / ``info``, which is what decides
    the colour — and it is declared rather than derived from the word, because "Degraded" is
    bad, "Repairing" is not, and no rule about the text can tell them apart.
    """
    declared = (metric or {}).get('states')
    if not isinstance(declared, dict):
        return {}
    out = {}
    for value, spec in declared.items():
        spec = spec if isinstance(spec, dict) else {'label': spec}
        label = label_of(spec, lang)
        if not label:
            continue
        out[str(value)] = {'label': label, 'level': str(spec.get('level') or 'info')}
        # …and whether this value means the thing IS NOT THERE. A passive switch answers
        # "fan: not present", which is true and is not news: the summary is "how is this
        # box", and a component the box says it does not have has no condition to report.
        # Declared rather than guessed from the word, for the same reason the level is.
        if spec.get('absent'):
            out[str(value)]['absent'] = True
        # …and the mark it earned. This function REBUILDS each state rather than copying it,
        # which is the right shape for something that reaches a screen and is also how a
        # declaration goes missing: the profile said `icon`, the normaliser kept it, and the
        # projection to the panel quietly dropped it — so the state arrived with nothing to
        # draw and nothing anywhere said why.
        if spec.get('icon'):
            out[str(value)]['icon'] = str(spec['icon'])
    return out
