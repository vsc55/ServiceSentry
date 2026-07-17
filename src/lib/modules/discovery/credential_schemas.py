#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Credential-type schemas: the field sets the credentials manager renders.

A *credential type* describes the fields one reusable credential holds.  The
built-in ``ssh`` type lives here (core-owned); additional types are discovered
from each watchful module's ``schema.json`` ``__credential__`` declaration, so a
module that needs its own kind of secret (e.g. the ``web`` module's HTTP
authentication) registers a credential type the manager can create/edit and the
module then consumes by reference (``cred_uid``) — exactly like host profiles.

A module declaration lists only the *field names* (and the type key); it carries
**no translations**.  Field labels/types come from the module's own collection
metadata (schema.json + lang/), and the type's display label from the module's
``pretty_name`` — both merged by :meth:`ModuleBase.discover_schemas`::

    "__credential__": {"type": "web_auth", "fields": ["auth_user", "auth_password"]}

(``__credentials__`` — a list — is accepted for modules declaring several.)

Each resolved field carries ``{name, kind, label_i18n, secret}`` (``kind`` ∈
{text, password, textarea, select, bool}, derived from the field's type +
secret flag).  ``secret`` fields are encrypted at rest and masked in the API.
"""

from __future__ import annotations

import json
import os

# Built-in SSH credential type — the identity (user + password or key) reused
# by hosts and OS checks.  Core-owned: the declaration carries no translations,
# only i18n KEYS (``label``/``hint``) resolved by the frontend against the core
# lang files (lib/web_admin/lang/en_EN.py / es_ES.py).  Module types instead
# carry resolved ``label_i18n``/``hint_i18n`` from their own lang/ files.
_BUILTIN_SSH = {
    'type': 'ssh',
    'builtin': True,
    'module': '__core__',
    'label': 'cred_type_ssh',
    'fields': [
        {'name': 'ssh_user', 'kind': 'text', 'autocomplete': 'off',
         'label': 'cred_user', 'hint': 'cred_user_hint'},
        {'name': 'ssh_auth_method', 'kind': 'select', 'default': 'password',
         'label': 'cred_auth_method', 'hint': 'cred_auth_method_hint',
         'options': [
             {'value': 'password', 'label': 'cred_auth_password'},
             {'value': 'file', 'label': 'cred_auth_file'},
             {'value': 'text', 'label': 'cred_auth_text'},
         ]},
        {'name': 'ssh_password', 'kind': 'password', 'secret': True,
         'label': 'cred_password', 'hint': 'cred_password_hint',
         'show_when': {'ssh_auth_method': ['password']}},
        {'name': 'ssh_key', 'kind': 'text', 'placeholder': '/path/to/id_rsa',
         'label': 'cred_key', 'hint': 'cred_key_hint',
         'show_when': {'ssh_auth_method': ['file']}},
        {'name': 'ssh_key_string', 'kind': 'textarea', 'secret': True, 'rows': 8,
         'label': 'cred_key_string', 'hint': 'cred_key_string_hint',
         'show_when': {'ssh_auth_method': ['text']}},
    ],
}


def _watchfuls_dir(watchfuls_dir: str | None) -> str:
    if watchfuls_dir:
        return watchfuls_dir
    # this file is lib/modules/discovery/credential_schemas.py → climb three levels to src.
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, 'watchfuls'))


def _module_i18n(module_dir: str) -> dict:
    """Load a module's ``lang/*.json`` → ``{lang: {labels, hints, pretty_name…}}``."""
    out: dict = {}
    ldir = os.path.join(module_dir, 'lang')
    if not os.path.isdir(ldir):
        return out
    for fn in sorted(os.listdir(ldir)):
        if not fn.endswith('.json'):
            continue
        try:
            with open(os.path.join(ldir, fn), encoding='utf-8') as fh:
                out[fn[:-5]] = json.load(fh)
        except (OSError, ValueError):
            pass
    return out


def _i18n_for(lang_data: dict, section: str, key: str) -> dict:
    """Build ``{lang: text}`` for *key* under *section* across a module's langs."""
    out = {}
    for lang, data in lang_data.items():
        sec = data.get(section) if isinstance(data, dict) else None
        if isinstance(sec, dict) and isinstance(sec.get(key), str) and sec[key]:
            out[lang] = sec[key]
    return out


def _general_i18n(key: str) -> dict:
    """Build ``{lang: text}`` for *key* from the GENERAL i18n catalog — the fallback
    for GENERIC credential action/link labels (e.g. the shared Entra ID provisioning
    actions ``provision_app``/``test_permissions``/``fix_permissions``/``open_app``),
    so their text lives once in the core i18n instead of being duplicated in every
    module's ``action_labels``.  Mirrors the frontend's ``t(action.id)`` fallback."""
    from lib.i18n import TRANSLATIONS  # noqa: PLC0415
    out = {lang: cat[key] for lang, cat in TRANSLATIONS.items()
           if isinstance(cat, dict) and isinstance(cat.get(key), str) and cat[key]}
    return out


# Structural attributes copied verbatim from a field declaration to its catalog
# entry (everything except the derived ``kind`` and the translations).
_FIELD_PASS_THROUGH = ('options', 'show_when', 'default', 'placeholder', 'rows',
                       'autocomplete', 'credential_type')


def _resolve_option_labels(entry: dict, name: str, lang_data: dict) -> None:
    """Attach per-option ``label_i18n`` from the module's ``option_labels`` section.

    ``option_labels`` maps ``{field_name: {value: text}}`` per language.  A plain
    string option ``"create"`` becomes ``{value, label_i18n}`` so the credential
    editor / action modal can show the translated label."""
    opts = entry.get('options')
    if not isinstance(opts, list):
        return
    new = []
    for o in opts:
        val = o.get('value') if isinstance(o, dict) else o
        li = {}
        for lang, data in lang_data.items():
            sec = data.get('option_labels') if isinstance(data, dict) else None
            fmap = sec.get(name) if isinstance(sec, dict) else None
            if isinstance(fmap, dict) and isinstance(fmap.get(val), str) and fmap[val]:
                li[lang] = fmap[val]
        if li:
            merged = dict(o) if isinstance(o, dict) else {'value': val}
            merged['label_i18n'] = li
            new.append(merged)
        else:
            new.append(o)
    entry['options'] = new


def _field_out(decl: dict, label_i18n: dict | None = None, hint_i18n: dict | None = None) -> dict:
    """Normalise a field declaration into a uniform catalog entry.

    Both the built-in ssh fields and module ``__credential__`` fields share the
    same declaration vocabulary (``name`` + ``type`` + ``secret`` + optional
    ``options``/``show_when``/``default``…).  ``kind`` is derived here.  The
    label/hint arrive either as a resolved ``{lang: text}`` map (*label_i18n* —
    module types, from their lang/ files) or, when absent, as the declaration's
    own i18n KEY (``label``/``hint`` — core types, resolved by the frontend)."""
    out = {'name': decl.get('name'), 'kind': decl.get('kind') or 'text',
           'secret': bool(decl.get('secret'))}
    if label_i18n:
        out['label_i18n'] = label_i18n
    elif decl.get('label'):
        out['label'] = decl['label']
    if hint_i18n:
        out['hint_i18n'] = hint_i18n
    elif decl.get('hint'):
        out['hint'] = decl['hint']
    for k in _FIELD_PASS_THROUGH:
        if decl.get(k) is not None:
            out[k] = decl[k]
    return out


def credential_schemas(watchfuls_dir: str | None = None) -> dict:
    """Return ``{type: {module, builtin?, label_i18n, fields:[…]}}``.

    Always includes the core ``ssh`` type; each module's ``__credential__`` /
    ``__credentials__`` adds a type.  The declaration carries only the data
    shape (field name + type + secret); the field **labels and help texts**,
    and the type's display name, are read from the module's ``lang/`` files
    (``labels`` / ``hints`` / ``pretty_name``) — no translations in the schema."""
    catalog: dict = {'ssh': {
        'type': 'ssh', 'builtin': True, 'module': '__core__',
        'label': _BUILTIN_SSH['label'],
        'fields': [_field_out(f) for f in _BUILTIN_SSH['fields']],
    }}
    base = _watchfuls_dir(watchfuls_dir)
    if not os.path.isdir(base):
        return catalog

    for entry in sorted(os.listdir(base)):
        if entry.startswith('_'):
            continue
        mdir = os.path.join(base, entry)
        sp = os.path.join(mdir, 'schema.json')
        if not os.path.isfile(sp):
            continue
        try:
            with open(sp, encoding='utf-8') as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            continue
        decl = schema.get('__credential__') or schema.get('__credentials__')
        if not decl:
            continue
        lang_data = _module_i18n(mdir)
        # Type display label = the module's translated pretty_name.
        type_label = {lang: data.get('pretty_name') for lang, data in lang_data.items()
                      if isinstance(data, dict) and isinstance(data.get('pretty_name'), str)}

        for spec in ([decl] if isinstance(decl, dict) else decl):
            if not isinstance(spec, dict):
                continue
            ctype = str(spec.get('type') or '').strip()
            names = spec.get('fields') or []
            if not ctype or ctype == 'ssh' or not isinstance(names, list):
                continue
            field_entries = []
            for f in names:
                # Same declaration vocabulary as the built-in ssh fields
                # (name + kind + secret + options/show_when…).  Only the LABEL
                # differs in source: the field's ``label`` (an i18n key, default
                # = its name) is looked up in the module's own lang/ files.
                name = f.get('name') if isinstance(f, dict) else f
                if not isinstance(name, str) or not name:
                    continue
                d = f if isinstance(f, dict) else {'name': name}
                if 'name' not in d:
                    d = {**d, 'name': name}
                lkey = d.get('label') or name
                fe = _field_out(
                    d,
                    label_i18n=_i18n_for(lang_data, 'labels', lkey) or {'en_EN': name},
                    hint_i18n=_i18n_for(lang_data, 'hints', lkey) or None,
                )
                _resolve_option_labels(fe, name, lang_data)
                field_entries.append(fe)
            if not field_entries:
                continue
            # Optional module-contributed actions for the credential editor (a
            # button + a small inputs sub-form, e.g. proxmox "provision token via
            # SSH").  Inputs share the field vocabulary; a kind:"credential" input
            # carries a ``credential_type`` so the editor renders a credential
            # picker of that type.
            action_entries = []
            for a in (spec.get('actions') or []):
                if not isinstance(a, dict) or not a.get('id') or not a.get('url'):
                    continue
                aid = str(a['id'])
                # An action may reference an explicit i18n label key (e.g. the shared
                # Entra ID actions use `prov_entraid_action_*`); else its id is the key.
                albl = str(a.get('label') or aid)
                inputs = []
                for f in (a.get('inputs') or []):
                    if not isinstance(f, dict) or not f.get('name'):
                        continue
                    lkey = f.get('label') or f['name']
                    ie = _field_out(
                        f,
                        label_i18n=_i18n_for(lang_data, 'labels', lkey) or {'en_EN': f['name']},
                        hint_i18n=_i18n_for(lang_data, 'hints', lkey) or None,
                    )
                    _resolve_option_labels(ie, f['name'], lang_data)
                    inputs.append(ie)
                entry_action = {
                    'id':         aid,
                    'url':        str(a['url']),
                    'icon':       str(a.get('icon') or 'bi-lightning'),
                    'result':     str(a.get('result') or 'toast'),
                    'label_i18n': (_i18n_for(lang_data, 'action_labels', albl)
                                   or _general_i18n(albl) or {'en_EN': aid}),
                    'inputs':     inputs,
                    # False → the action is invokable (e.g. from another modal) but not
                    # shown as a button in the credential-editor actions toolbar.
                    'toolbar':    bool(a.get('toolbar', True)),
                }
                # A device-code provisioning action carries a `provision` object
                # (opaque pass-through). Whatever extras the module's provisioning
                # declaration contributes (app name, permissions, …) are merged in
                # by the provisioning layer — the catalog stays permission-agnostic.
                if isinstance(a.get('provision'), dict):
                    _prov = dict(a['provision'])
                    from lib.providers.entraid import entraid_provision_extras  # noqa: PLC0415
                    for _k, _v in entraid_provision_extras(schema).items():
                        _prov.setdefault(_k, _v)
                    entry_action['provision'] = _prov
                action_entries.append(entry_action)
            # Optional deep-links (schema __credential__.links): a button that opens
            # an external URL built from the credential's own field values — shown
            # only once its ``require`` fields are filled (e.g. "open this app in
            # Entra ID" once client_id exists). Generic: opaque url template + label.
            link_entries = []
            for lnk in (spec.get('links') or []):
                if not isinstance(lnk, dict) or not lnk.get('id') or not lnk.get('url'):
                    continue
                lid = str(lnk['id'])
                llbl = str(lnk.get('label') or lid)
                link_entries.append({
                    'id':         lid,
                    'url':        str(lnk['url']),
                    'icon':       str(lnk.get('icon') or 'bi-box-arrow-up-right'),
                    'require':    [str(x) for x in (lnk.get('require') or []) if isinstance(x, str)],
                    'label_i18n': (_i18n_for(lang_data, 'action_labels', llbl)
                                   or _general_i18n(llbl) or {'en_EN': lid}),
                })
            catalog[ctype] = {
                'module':     entry,
                'label_i18n': type_label or {'en_EN': ctype},
                'fields':     field_entries,
                'actions':    action_entries,
                'links':      link_entries,
            }
    return catalog


def credential_secret_fields(watchfuls_dir: str | None = None) -> set[str]:
    """Set of all ``secret`` field names across every credential type — so the
    store can encrypt them at rest and the API can mask them."""
    out: set[str] = set()
    for spec in credential_schemas(watchfuls_dir).values():
        for f in spec.get('fields') or []:
            if f.get('secret'):
                out.add(f['name'])
    return out
