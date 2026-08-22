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

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'profiles')
# Where an installation's own profiles live, under the application data directory.
CUSTOM_SUBDIR = 'snmp_profiles'


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
    for num, cast in (('scale', float), ('max_rate', float), ('width', int)):
        if raw.get(num) not in (None, ''):
            try:
                out[num] = cast(raw[num])
            except (TypeError, ValueError):
                pass
    # What this value IS about the machine, for the ones that are not measurements: a name, a
    # model, a serial. The section shows those as identity instead of as data.
    role = str(raw.get('role') or '').strip().lower()
    if role and _ID_RE.match(role):
        out['role'] = role
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
        'metrics': metrics,
    }
    if includes:
        out['includes'] = includes
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
    """A profile's or metric's name in the reader's language, however it names itself."""
    labels = (obj or {}).get('label') or {}
    return (labels.get(lang) or labels.get(default_lang) or labels.get('*')
            or str((obj or {}).get('id') or (obj or {}).get('key') or ''))


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
    """``{field: {label, unit}}`` for the metrics of this profile that are measurements.

    The shape :mod:`lib.core.history.service` produces from a module's static ``__history__``
    declaration — because that is what makes a value chartable in History and nameable in the
    Infrastructure section, and a profile is exactly that declaration for values that arrive
    without one. Text metrics are absent on purpose: they are what the machine IS, not what it
    is doing.
    """
    out = {}
    for m in (profile or {}).get('metrics') or ():
        if m.get('kind') == 'text':
            continue
        out[m['key']] = {'label': label_of(m, lang), 'unit': m.get('unit', '')}
    return out
