#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""History fields a module works out at run time.

A module declares what it charts in its ``schema.json``: ``__history__.fields`` names each
value it records, with a label and a unit, and that is what turns a number in a JSON blob into
a named series with an axis. It is a **static** declaration, which is right for a module that
records the same three things on every install.

It is not enough for a module whose fields depend on data the installation supplies. The SNMP
watchful is the case that forced this: what it records is decided by the device profiles
present — the ones shipped plus whatever somebody wrote for the box in their rack — so the set
cannot be written into a schema at build time without being wrong for every install that added
one.

So a module may also declare them at run time, with a module-level function mirroring
``discover_db_tables()`` (see :mod:`lib.db.module_tables`)::

    # watchfuls/<name>/__init__.py
    def discover_history_fields(lang='en_EN', var_dir=''):
        return {'cpu_user': {'label': 'CPU user', 'unit': '%'}}

Both halves are merged by :func:`lib.core.history.service.history_meta`, and **the static
declaration wins**: it is the one somebody wrote down on purpose, and a run-time discovery
that silently renamed it would make the schema a lie.

Failure is always an empty map, never an exception. These fields decide what a chart's legend
says; a module that cannot answer costs its own labels — the values are still recorded, still
charted, and read as their raw field names — and that is not a reason for a history page to
return a 500.
"""

from __future__ import annotations

import importlib
import logging
import re

_log = logging.getLogger(__name__)


#: Optional per-field metadata a module may hand over beside the label and the unit.
#:
#: The projection below is a whitelist and not a pass-through, which is the right shape — a
#: module cannot put arbitrary keys into a core structure — but it had to grow when a module
#: started knowing more than "what is this called". Both of these are things only the module
#: can answer, and the union it returns is where the answer was being dropped:
#:
#: * ``source``/``source_label`` — which part of the device this measures. A device with a
#:   dozen SNMP profiles answers sixty-four kinds of measurement, and "disks" is a heading a
#:   person can read where an alphabetical list of field names is not;
#: * ``chart`` — whether a value is a line or a state, which is the difference between drawing
#:   a graph and drawing a badge, and cannot be guessed from a number that has no unit;
#: * ``states`` — what the numbers a field answers with MEAN. Only the module knows: the agent
#:   says "1" and the MIB it came from says that 1 is Normal.
#: * ``row_split`` — how this table's row names separate the row from the thing it belongs
#:   to, for the tables whose names carry a qualifier the MIB has no column for.
_OPTIONAL_META = ('source', 'source_label', 'source_short', 'source_rank', 'chart',
                  'row_split', 'headline', 'icon', 'identity', 'tally', 'tally_role',
                  'chart_label')

#: The same, for metadata that is a map rather than a word.
_OPTIONAL_MAPS = ('states', 'headline_rows', 'present_when', 'quiet_when')

#: …and for the metadata that is a LIST. Kept apart because the two above coerce — a list run
#: through `str()` becomes the string "['if_total_out']", which is a field name nothing
#: matches and no error anywhere.
_OPTIONAL_LISTS = ('chart_with',)


def _ask_module(module: str, hook: str, lang: str, var_dir: str) -> dict:
    """Call one of a watchful's discovery hooks, and survive anything it does.

    One implementation because there are two of them now — the fields a module records and the
    names of the things that produce them — and "how do you ask a module something at run time"
    is not a question either of them should answer twice.
    """
    name = str(module or '').strip()
    if not name or name.startswith('_') or '.' in name:
        return {}
    try:
        mod = importlib.import_module(f'watchfuls.{name}')
    except Exception:  # pylint: disable=broad-except
        return {}       # not a watchful, or one whose optional dependencies are absent
    fn = getattr(mod, hook, None)
    if not callable(fn):
        return {}
    try:
        declared = fn(lang, var_dir) or {}
    except TypeError:
        # A module that only cares about the language may take just that.
        try:
            declared = fn(lang) or {}
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning('%s() failed for module %s: %s', hook, name, exc)
            return {}
    except Exception as exc:  # pylint: disable=broad-except
        _log.warning('%s() failed for module %s: %s', hook, name, exc)
        return {}
    if not isinstance(declared, dict):
        _log.warning('%s() for module %s did not return a map', hook, name)
        return {}
    return declared


#: What a brand may be, checked where a module's word crosses into the core. The shapes are
#: the ones :mod:`lib.core.snmp.profiles` validates on the way in; this is the second door,
#: because a module's hook is code and the first door only guards the files.
_LOGO_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')
_ICON_RE = re.compile(r'^bi-[a-z0-9-]{1,40}$')
_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _brand(raw: dict) -> dict:
    """One brand declaration, checked into shape — ``{}`` when it is not usable."""
    name = str((raw or {}).get('name') or '').strip()
    if not name or len(name) > 48:
        return {}
    out = {'name': name}
    for key, rule in (('logo', _LOGO_RE), ('icon', _ICON_RE), ('color', _COLOR_RE)):
        val = str((raw or {}).get(key) or '').strip().lower()
        if rule.match(val):
            out[key] = val
    return out


def module_history_sources(module: str, lang: str = 'en_EN', var_dir: str = '') -> dict:
    """``{source: {label, short, rank}}`` the module computes now, or ``{}``.

    The other half of :func:`module_history_fields`. A module that fronts several answerers
    says what to call each of them; one that does not have several says nothing, and a screen
    that groups by source is unchanged.
    """
    out: dict = {}
    for src, meta in _ask_module(module, 'discover_history_sources', lang, var_dir).items():
        key = str(src or '').strip()
        if not key or not isinstance(meta, dict):
            continue
        # A module names the facts it files that nothing else can name (see the SNMP
        # profiles' `attrs`). Capped and stringified like everything else a module hands over:
        # this reaches a label on a screen, and a module is a file somebody edited.
        attrs = meta.get('attrs')
        attrs = {str(k): str(v)[:120] for k, v in list((attrs or {}).items())[:256]
                 if str(k or '').strip() and str(v or '').strip()}
        brand = meta.get('brand')
        out[key] = {'label': str(meta.get('label') or key),
                    'short': str(meta.get('short') or ''),
                    'rank':  int(meta.get('rank') or 0),
                    'attrs': attrs,
                    # …and who made it. Checked into shape here like everything else a module
                    # hands over: this reaches an `img` URL and a `style`, and the module is a
                    # file somebody edited.
                    'brand': _brand(brand if isinstance(brand, dict) else {}),
                    'brands': [{**_brand(e), 'any': [str(w).strip().lower()
                                                     for w in (e.get('any') or [])][:12]}
                               for e in (meta.get('brands') or [])
                               if isinstance(e, dict) and _brand(e) and e.get('any')][:64]}
    return out


def module_history_fields(module: str, lang: str = 'en_EN', var_dir: str = '') -> dict:
    """``{field: {label, unit, …}}`` the module computes now, or ``{}``.

    *module* is the bare watchful name (``snmp``), as the history records it.
    """
    declared = _ask_module(module, 'discover_history_fields', lang, var_dir)
    out: dict = {}
    for field, meta in declared.items():
        key = str(field or '').strip()
        if not key:
            continue
        meta = meta if isinstance(meta, dict) else {}
        out[key] = {'label': str(meta.get('label') or key),
                    'unit':  str(meta.get('unit') or ''),
                    **{k: str(meta.get(k) or '') for k in _OPTIONAL_META if meta.get(k)},
                    **{k: dict(meta[k]) for k in _OPTIONAL_MAPS
                       if isinstance(meta.get(k), dict) and meta[k]},
                    **{k: [str(x) for x in meta[k]] for k in _OPTIONAL_LISTS
                       if isinstance(meta.get(k), (list, tuple)) and meta[k]}}
    return out
