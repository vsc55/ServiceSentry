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
from functools import lru_cache

from lib.core.hosts.resolve import host_profile_specs
from lib.discovery import scan
from lib.i18n import TRANSLATIONS
from lib.modules import ModuleBase


def _section_label(section: str, key: str, block: str = 'labels') -> dict:
    """Build ``{lang: text}`` for a core profile field from the lang files
    (``<section>.labels``, or another block of it) — a core-owned profile takes its
    words from core i18n like every other translation, not inline here."""
    out = {}
    for lang, data in TRANSLATIONS.items():
        txt = ((data.get(section) or {}).get(block) or {}).get(key)
        if isinstance(txt, str) and txt:
            out[lang] = txt
    return out


def _profile_label(key: str) -> dict:
    """The SSH profile's own labels (``ssh_profile.labels``)."""
    return _section_label('ssh_profile', key)


def _profile_options(keys: tuple[str, ...]) -> dict:
    """Build ``{option: {lang: text}}`` for the SSH auth-method options from the
    lang files (``ssh_profile.auth_options``)."""
    out: dict = {}
    for opt in keys:
        m = {}
        for lang, data in TRANSLATIONS.items():
            txt = ((data.get('ssh_profile') or {}).get('auth_options') or {}).get(opt)
            if isinstance(txt, str) and txt:
                m[lang] = txt
        if m:
            out[opt] = m
    return out

_META_KEYS = ('type', 'options', 'options_int', 'options_deps', 'options_disabled',
              'options_i18n', 'secret', 'sensitive', 'placeholder', 'placeholder_map',
              'placeholder_map_field', 'show_when', 'rows',
              # A multi-value field is a LIST with a picker, not a text box. Dropping the
              # flag here does not fail: it renders a comma-separated string that happens
              # to look editable, which is the worst of the three possible outcomes.
              'multi',
              'min', 'max', 'label_i18n', 'default')

# ── Built-in SSH connection profile (core, not a module) ──────────────────────
# SSH reachability is a property of the *server* itself, so the core owns it:
# a host declared "remote" carries this connection and any module that needs to
# run commands on the box (RAID) or tunnel through it (datastore) reuses it.
# Always present in the catalog regardless of which modules are installed.
CORE_SSH_SECRET_FIELDS = frozenset({'ssh_password', 'ssh_key_string'})

_BUILTIN_SSH = {
    'module':        '__host__',
    'builtin':       True,
    'address_field': 'ssh_host',   # fed from the host address; never shown
    'fields': [
        {'name': 'ssh_port', 'type': 'int', 'min': 1, 'max': 65535, 'placeholder': 22,
         'default': 0,
         'label_i18n': _profile_label('ssh_port')},
        {'name': 'ssh_user', 'type': 'str',
         'label_i18n': _profile_label('ssh_user')},
        # Authentication method: password, a key file (path), or inline key
        # text.  Drives which credential field shows.  Defaults to password.
        {'name': 'ssh_auth_method', 'type': 'str', 'default': 'password',
         'options': ['password', 'file', 'text'],
         'options_i18n': _profile_options(('password', 'file', 'text')),
         'label_i18n': _profile_label('ssh_auth_method')},
        {'name': 'ssh_password', 'type': 'str', 'secret': True,
         'show_when': {'ssh_auth_method': ['password']},
         'label_i18n': _profile_label('ssh_password')},
        {'name': 'ssh_key', 'type': 'str', 'placeholder': '/path/to/id_rsa',
         'show_when': {'ssh_auth_method': ['file']},
         'label_i18n': _profile_label('ssh_key')},
        {'name': 'ssh_key_string', 'type': 'textarea', 'secret': True, 'rows': 10,
         'placeholder': '-----BEGIN OPENSSH PRIVATE KEY-----…',
         'show_when': {'ssh_auth_method': ['text']},
         'label_i18n': _profile_label('ssh_key_string')},
        {'name': 'ssh_verify_host', 'type': 'bool', 'default': False,
         'label_i18n': _profile_label('ssh_verify_host')},
    ],
}


def _watchfuls_dir(watchfuls_dir: str | None) -> str:
    if watchfuls_dir:
        return watchfuls_dir
    # this file is lib/core/hosts/profiles.py → climb three levels to the src root.
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, 'watchfuls'))


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
        specs = host_profile_specs(schema.get('__host_profile__'))
        if not specs:
            continue

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
    # A protocol the CORE declares overrides any module-declared profile of the same key.
    # A profile that only exists while some module happens to be installed is a property of
    # that module; these are properties of the DEVICE.
    catalog.update(core_profiles())
    return catalog


@lru_cache(maxsize=None)
def _core_profiles() -> dict:
    """``{protocol: entry}`` for every connection profile the CORE declares.

    The one place that answers "what is an SSH / an SNMP connection". Four other things
    needed that answer and each read it from somewhere else: the catalogue built it here,
    while ``resolve_host``, the hide-when-bound list and the assisted migration read a COPY
    of the field names out of every module's ``__host_profile__``. Eleven modules carried
    such a copy — ten of them the same seven SSH names — for a list they do not own and
    that this function overrides anyway.

    Cached because it is asked per item per cycle by the monitor and the declarations cannot
    change while the process lives.
    """
    out: dict = {
        # SSH is core-owned without a manifest: it predates the mechanism and its fields
        # carry their translations inline.
        'ssh': {
            'module':        _BUILTIN_SSH['module'],
            'builtin':       True,
            'address_field': _BUILTIN_SSH['address_field'],
            # A way IN, not a collection: nothing about having credentials says the panel
            # charts this machine.
            'samples_when':  '',
            'fields':        list(_BUILTIN_SSH['fields']),
        },
    }
    for pkg, decl in scan('HOST_PROFILE'):
        if not isinstance(decl, dict) or not decl.get('key'):
            continue
        section = decl.get('i18n') or ''
        fields = []
        for f in (decl.get('fields') or []):
            if not isinstance(f, dict) or not f.get('name'):
                continue
            f = dict(f)
            if section:
                label = _section_label(section, f['name'])
                if label:
                    f['label_i18n'] = label
                hint = _section_label(section, f['name'], 'hints')
                if hint:
                    f['hint_i18n'] = hint
            fields.append(f)
        out[decl['key']] = {
            'module':        decl.get('module') or pkg,
            'builtin':       True,
            'address_field': decl.get('address_field'),
            'samples_when':  decl.get('samples_when') or '',
            'fields':        fields,
        }
    return out


def core_profiles() -> dict:
    """A caller-owned copy of :func:`_core_profiles` — the cache is shared and long-lived,
    and the catalogue it feeds is handed to code that edits its entries."""
    return {k: {**v, 'fields': [dict(f) for f in v['fields']]}
            for k, v in _core_profiles().items()}


def profile_sampled_modules(host: dict) -> set:
    """The modules that sample *host* because of its OWN record, with no item anywhere.

    A protocol may declare (``samples_when``) the field that turns a connection into a
    collection: for SNMP it is ``device_profiles``, and a host that carries one IS a device —
    a switch, a router, a UPS — read every cycle without a check existing. That is not an
    SNMP fact the core has to know, it is a sentence the protocol writes down.

    Read from the DECLARATION and not from what has been recorded, which is the whole point:
    the recorded answer is empty for a device that has never been sampled, so "what would run
    against this machine" said "nothing" about exactly the machine somebody was trying to take
    a first sample of.
    """
    out: set = set()
    profiles = (host or {}).get('profiles')
    if not isinstance(profiles, dict):
        return out
    for key, entry in _core_profiles().items():
        field = entry.get('samples_when')
        prof = profiles.get(key)
        if not field or not isinstance(prof, dict):
            continue
        raw = prof.get(field)
        # A list or a separated string: the field is edited as chips and stored as text, and
        # both shapes reach here (lib/core/snmp/profiles.assigned parses the same two).
        filled = (any(str(x).strip() for x in raw) if isinstance(raw, (list, tuple))
                  else str(raw or '').strip() != '')
        if filled:
            out.add(str(entry.get('module') or '').strip().rsplit('.', 1)[-1])
    out.discard('')
    return out


def core_profile_fields(key: str) -> list[dict]:
    """The fields the core declares for one protocol, or ``[]`` if it declares none."""
    entry = _core_profiles().get(str(key or ''))
    return [dict(f) for f in entry['fields']] if entry else []


def core_profile_field_names(key: str) -> tuple:
    """Just their names — what a module's ``__host_profile__`` used to restate."""
    entry = _core_profiles().get(str(key or ''))
    return tuple(f['name'] for f in entry['fields']) if entry else ()


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


def module_host_multi_bind(watchfuls_dir: str | None = None) -> dict:
    """Return ``{module: bool}`` — whether ONE check binds to SEVERAL hosts
    (``host_uids`` list) instead of a single ``host_uid``.  Declared by
    ``"__host_multiple_bind__": true`` (e.g. proxmox: a cluster check whose
    failover address list spans all member nodes); default False.

    Distinct from :func:`module_host_multiple` (several *checks* per one host).
    A multi-bind module is configured as a single multi-host check (Modules),
    not per-host — so it is excluded from the per-host "Servers" enable flow."""
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
            out[entry] = bool(schema.get('__host_multiple_bind__'))
    return out


def module_member_fields(watchfuls_dir: str | None = None) -> dict:
    """Return ``{module: field_key}`` — the per-node member field a multi-bind
    module declares (``__member_field__.key`` in a collection schema, e.g.
    keepalived's ``priority``).  This per-machine datum is stored on the host
    profile (``profiles[module][field_key]``); the web admin uses it to render the
    per-node control and to blank it when cloning a host (a clone is a different
    node).  Module-agnostic — no field name is assumed."""
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
        for coll in schema.values():
            if isinstance(coll, dict) and isinstance(coll.get('__member_field__'), dict):
                key = coll['__member_field__'].get('key')
                if key:
                    out[entry] = key
                break
    return out


def module_status_render(watchfuls_dir: str | None = None) -> dict:
    """Return ``{module: [directive, …]}`` — how the Status card should decorate a
    check's ``other_data`` for that module (``__status_render__`` in the schema).

    Each directive is opaque to the core and rendered generically, e.g.
    ``{"type": "bar", "value": "used", "threshold": "alert", "default_threshold": 80}``
    (a usage bar) or ``{"type": "badge", "field": "code", "prefix": "HTTP "}``.
    Keeps the Status enrichment module-agnostic — no ``other_data`` key names are
    hardcoded in the core."""
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
        directives = schema.get('__status_render__')
        if isinstance(directives, list) and directives:
            out[entry] = directives
    return out


def module_host_specs(watchfuls_dir: str | None = None) -> dict:
    """Return ``{bare_module: [(protocol, address_field, [field names])]}`` read
    straight from each module's ``__host_profile__`` declaration.

    Unlike :func:`host_profiles_catalog` (which is UI-oriented and lets the core
    built-in ``ssh`` profile win), this preserves the *module's own* protocol
    declarations — so the assisted migration still knows datastore items carry
    ``ssh`` tunnel fields even though the catalog presents ssh as core-owned.
    """
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
        specs = host_profile_specs(schema.get('__host_profile__'))
        if not specs:
            continue
        entries = []
        for spec in specs:
            if isinstance(spec, dict) and spec.get('key') and spec.get('fields'):
                entries.append((spec['key'], spec.get('address_field'),
                                list(spec.get('fields') or [])))
        if entries:
            out[entry] = entries
    return out


def module_host_collections(watchfuls_dir: str | None = None) -> dict:
    """Return ``{module: [host-capable collection suffixes]}`` — which item
    collection(s) of a host-centric module may bind to a host (and thus show the
    host picker in the UI).

    A collection is host-capable when it holds one of the profile's connection
    fields (e.g. snmp ``servers`` has ``host``, but its nested ``checks`` does
    not).  For SSH-only / address-only modules (cpu, dns, ram_swap, web…) whose
    profile fields are never inline item fields, *every* top-level item
    collection is host-capable — binding a host is the only way to target a
    remote box, so the picker must still appear.

    Suffixes match :func:`_schemaKeyOf` (e.g. ``"list"`` or ``"servers"``);
    nested sub-collections (``"servers|checks"``) are never host-capable.
    """
    base = _watchfuls_dir(watchfuls_dir)
    out: dict = {}
    if not os.path.isdir(base):
        return out
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
        specs = host_profile_specs(schema.get('__host_profile__'))
        if not specs:
            continue
        all_fields: list = []
        for spec in specs:
            if isinstance(spec, dict):
                all_fields.extend(spec.get('fields') or [])
        # Top-level real item collections (suffix has no '|', not a dunder section).
        top_colls = {
            key.split('|', 1)[1]: meta
            for key, meta in schemas.items()
            if key.startswith(entry + '|')
            and '|' not in key.split('|', 1)[1]
            and not key.split('|', 1)[1].startswith('__')
            and isinstance(meta, dict)
        }
        host_colls = [c for c, meta in top_colls.items()
                      if any(f in meta for f in all_fields)]
        if not host_colls:
            # SSH-only / address-only module: every top-level collection binds.
            host_colls = list(top_colls.keys())
        if host_colls:
            out[entry] = host_colls
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
        specs = host_profile_specs(schema.get('__host_profile__'))
        if not specs:
            continue
        fields: list = []
        for spec in specs:
            if isinstance(spec, dict):
                fields.extend(spec.get('fields') or [])
        if fields:
            out[entry] = fields
    return out
