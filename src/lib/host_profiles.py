#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host connection-profile catalog.

Builds, from every watchful module's ``__host_profile__`` declaration, the map
of connection protocols a Host can carry and the fields each one holds — with
the field metadata (type, options, secret flag, i18n labels…) taken from the
module's own schema.  The web admin uses this to:

  * render the per-protocol credential forms in the "Servers" section, and
  * know which fields to hide on a module check once it is bound to a host.

Shape::

    {
      "snmp": {"module": "snmp", "address_field": "host",
               "fields": [{"name": "community", "type": "str", ...}, ...]},
      "ssh":  {"module": "datastore", "address_field": null, "fields": [...]},
      ...
    }

``__host_profile__`` itself may be a single spec dict or a list of them (a
module like datastore needs several — an ``ssh`` tunnel plus a ``db`` profile).
"""

from __future__ import annotations

import json
import os

from lib.modules import ModuleBase

_META_KEYS = ('type', 'options', 'options_int', 'options_deps', 'options_disabled',
              'secret', 'sensitive', 'placeholder', 'placeholder_map', 'show_when',
              'min', 'max', 'label_i18n', 'default')


def _watchfuls_dir(watchfuls_dir: str | None) -> str:
    if watchfuls_dir:
        return watchfuls_dir
    return os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, 'watchfuls'))


def host_profiles_catalog(watchfuls_dir: str | None = None) -> dict:
    """Return ``{protocol: {module, address_field, fields:[{name, …meta}]}}``."""
    base = _watchfuls_dir(watchfuls_dir)
    catalog: dict = {}
    if not os.path.isdir(base):
        return catalog

    # Field metadata (with merged i18n) per module collection: keys "mod|collection".
    schemas = ModuleBase.discover_schemas(base)

    for entry in sorted(os.listdir(base)):
        if entry.startswith('_'):
            continue
        sp = os.path.join(base, entry, 'schema.json')
        if not os.path.isfile(sp):
            continue
        try:
            with open(sp, encoding='utf-8') as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            continue
        hp = schema.get('__host_profile__')
        if not hp:
            continue
        specs = [hp] if isinstance(hp, dict) else hp

        # This module's top-level collections (exclude sub-collections "mod|c|sub").
        mod_colls = {
            key.split('|', 1)[1]: meta
            for key, meta in schemas.items()
            if key.startswith(entry + '|') and '|' not in key.split('|', 1)[1]
        }

        for spec in specs:
            if not isinstance(spec, dict):
                continue
            proto = spec.get('key')
            fields = spec.get('fields') or []
            if not proto or not fields:
                continue
            # Locate the collection that actually holds these connection fields.
            coll_meta: dict = {}
            for cmeta in mod_colls.values():
                if isinstance(cmeta, dict) and any(f in cmeta for f in fields):
                    coll_meta = cmeta
                    break
            field_entries = []
            for f in fields:
                m = coll_meta.get(f)
                if isinstance(m, dict):
                    entry_meta = {'name': f}
                    for k in _META_KEYS:
                        if k in m:
                            entry_meta[k] = m[k]
                    entry_meta.setdefault('type', 'str')
                    field_entries.append(entry_meta)
                else:
                    field_entries.append({'name': f, 'type': 'str'})
            catalog[proto] = {
                'module':        entry,
                'address_field': spec.get('address_field'),
                'fields':        field_entries,
            }
    return catalog


def module_host_multiple(watchfuls_dir: str | None = None) -> dict:
    """Return ``{module: bool}`` — whether a host-capable module allows SEVERAL
    checks bound to one host (e.g. datastore: mysql + postgres; web: many URLs).
    Declared by ``"__host_multiple__": true`` in the module schema; default False
    (single check per host, e.g. ping/ntp)."""
    base = _watchfuls_dir(watchfuls_dir)
    out: dict = {}
    if not os.path.isdir(base):
        return out
    for entry in sorted(os.listdir(base)):
        if entry.startswith('_'):
            continue
        sp = os.path.join(base, entry, 'schema.json')
        if not os.path.isfile(sp):
            continue
        try:
            with open(sp, encoding='utf-8') as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            continue
        if schema.get('__host_profile__'):
            out[entry] = bool(schema.get('__host_multiple__'))
    return out


def module_host_fields(watchfuls_dir: str | None = None) -> dict:
    """Return ``{module: [connection field names]}`` — the fields to hide on a
    check once it is bound to a host (from each module's ``__host_profile__``)."""
    base = _watchfuls_dir(watchfuls_dir)
    out: dict = {}
    if not os.path.isdir(base):
        return out
    for entry in sorted(os.listdir(base)):
        if entry.startswith('_'):
            continue
        sp = os.path.join(base, entry, 'schema.json')
        if not os.path.isfile(sp):
            continue
        try:
            with open(sp, encoding='utf-8') as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            continue
        hp = schema.get('__host_profile__')
        if not hp:
            continue
        specs = [hp] if isinstance(hp, dict) else hp
        fields: list = []
        for spec in specs:
            if isinstance(spec, dict):
                fields.extend(spec.get('fields') or [])
        if fields:
            out[entry] = fields
    return out
