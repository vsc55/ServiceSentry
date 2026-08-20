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
        idx = str(raw.get('index_label') or '').strip()
        if idx and _OID_RE.match(idx):
            out['index_label'] = idx
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

    A profile with no usable metric is not a profile: it would sit in the catalogue, be
    assignable to a machine, and measure nothing — which reads as a device that answers
    nothing rather than as a declaration somebody got wrong.
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
    if not metrics:
        return None
    out = {
        'id':      pid,
        'label':   _label(raw.get('label'), pid.replace('_', ' ').capitalize()),
        'metrics': metrics,
    }
    # What this profile is FOR, matched against the device's own answer to sysObjectID. Only a
    # prefix: a vendor's tree identifies the family, and the exact node identifies a model
    # nobody wants to enumerate.
    match = raw.get('match')
    if isinstance(match, dict):
        prefix = str(match.get('sysobjectid_prefix') or '').strip()
        if _OID_RE.match(prefix):
            out['match'] = {'sysobjectid_prefix': prefix}
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


def catalog(custom=None, directory: str | None = None) -> dict:
    """Every profile available, by id — shipped first, the installation's own last.

    Custom last so an installation can **override** a shipped profile by reusing its id, which
    is what somebody does when the vendor changed an OID in a firmware release and the fix
    cannot wait for the next version of this product.
    """
    out = shipped(directory)
    for raw in (custom or []):
        prof = normalise(raw)
        if prof:
            prof['source'] = 'custom'
            out[prof['id']] = prof
    return out


def label_of(obj: dict, lang: str, default_lang: str = 'en_EN') -> str:
    """A profile's or metric's name in the reader's language, however it names itself."""
    labels = (obj or {}).get('label') or {}
    return (labels.get(lang) or labels.get(default_lang) or labels.get('*')
            or str((obj or {}).get('id') or (obj or {}).get('key') or ''))


def match_sysobjectid(profiles: dict, sysobjectid: str) -> dict | None:
    """The profile that claims this device, if one does.

    Longest prefix wins: a vendor's tree and a model's node under it are both legitimate
    claims, and the more specific one is the one that knows more about the machine.
    """
    oid = str(sysobjectid or '').strip().lstrip('.')
    if not oid:
        return None
    best = None
    for prof in (profiles or {}).values():
        prefix = ((prof.get('match') or {}).get('sysobjectid_prefix') or '')
        if not prefix or not (oid == prefix or oid.startswith(prefix + '.')):
            continue
        if best is None or len(prefix) > len((best.get('match') or {}).get('sysobjectid_prefix') or ''):
            best = prof
    return best


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
