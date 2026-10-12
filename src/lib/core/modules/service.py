#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The module-config document: what may be seen of it, whether it is well formed, and what
the UI is built from.

What was one 787-line module is now the domain it described: `items.py` (an item's identity),
`authz.py` (may this save touch this item), `provisioning.py` (credentials out, declared devices
in), `actions.py` (the config a watchful action runs with). What stayed is the document
itself — the whole config as it is read, checked, normalised and rendered.

Everything here is Flask-free (no request/session/jsonify); the route owns request parsing,
secret restore, persistence and audit. Most of it is pure over plain dicts and raises
:class:`~lib.core.users.service.AdminOpError` on a violation.
"""

from __future__ import annotations

import copy
import importlib
import os
import sys

from lib.core.users.service import AdminOpError


# ── view / validation ────────────────────────────────────────────────────────────
def visible_modules(all_data: dict, perms) -> dict:
    """The subset of *all_data* the user may view via per-module ``module.{name}.view``
    permissions (used when the user lacks the global ``modules_view``)."""
    return {n: c for n, c in all_data.items() if f'module.{n}.view' in perms}


def keep_unseen_modules(old_data: dict, data: dict, perms) -> list:
    """Put back, in place, every stored module the user may not view and *data* left out.

    The GET serves a scoped user only :func:`visible_modules`, and the save REPLACES the whole
    configuration with what comes back — so the modules they were never shown arrived as
    deleted, and authorising that removal failed every save. Absent-and-unseen means
    untouched; a module the body DOES name is left to the authorisation like any other.
    Returns the names restored."""
    kept = []
    for name, cfg in (old_data or {}).items():
        if name in data or f'module.{name}.view' in perms:
            continue
        data[name] = copy.deepcopy(cfg)
        kept.append(name)
    return kept


def validate_modules_shape(data: dict) -> None:
    """Every top-level value must be a module-config dict.  Raises on a malformed body."""
    if not all(isinstance(v, dict) for v in data.values()):
        raise AdminOpError('invalid_modules_data')


# ── closed-choice fields ─────────────────────────────────────────────────────────
def _closed_options(meta) -> set | None:
    """The accepted values of a field with a CLOSED list of options, or ``None``.

    ``None`` — nothing to enforce — for a field without a static ``options`` list, or one
    that declares it also takes free text (``allow_custom`` / ``free_text``), or whose list
    holds something that is not a plain value (a dict without ``value``)."""
    if not isinstance(meta, dict):
        return None
    opts = meta.get('options')
    if not isinstance(opts, list) or not opts:
        return None
    if meta.get('allow_custom') or meta.get('free_text'):
        return None
    out = set()
    for o in opts:
        if isinstance(o, dict):
            if 'value' not in o:
                return None
            out.add(str(o['value']))
        elif isinstance(o, (str, int, float, bool)):
            out.add(str(o))
        else:
            return None
    return out


def _check_fields(module: str, schema: dict, item: dict, old_item: dict) -> None:
    for field, meta in (schema or {}).items():
        if str(field).startswith('__') or field not in item:
            continue
        allowed = _closed_options(meta)
        if allowed is None:
            continue
        value = item.get(field)
        if value in (None, ''):
            continue                    # blank = the default, as everywhere else
        if isinstance(old_item, dict) and old_item.get(field) == value:
            continue                    # stored before: a legacy value must not block saves
        values = value if isinstance(value, list) else [value]
        for v in values:
            if isinstance(v, (dict, list)) or str(v) not in allowed:
                raise AdminOpError('invalid_config_value', f'{module}.{field}', str(v)[:60])


def validate_option_values(data: dict, old_data: dict, schemas: dict) -> None:
    """Refuse a value outside a field's declared ``options`` — for every module.

    A dropdown in the browser is a suggestion; the save took whatever the body carried, and
    the value then reached code that trusted the schema to have bounded it (the DNS record
    type went into a PowerShell command line unquoted). Checked per field from the schemas,
    so no module is named here. A value that is ALREADY stored at the same place passes
    unchanged — refusing it would make an old config unsaveable for a field nobody touched.
    """
    schemas = schemas or {}
    old_data = old_data if isinstance(old_data, dict) else {}
    for mod_key, cfg in (data or {}).items():
        if not isinstance(cfg, dict):
            continue
        module = str(mod_key).split('.')[-1]
        old_cfg = old_data.get(mod_key) if isinstance(old_data.get(mod_key), dict) else {}
        _check_fields(module, schemas.get(f'{module}|__module__'), cfg, old_cfg)
        for coll, items in cfg.items():
            sch = schemas.get(f'{module}|{coll}')
            if not isinstance(sch, dict) or not isinstance(items, dict):
                continue
            old_items = old_cfg.get(coll) if isinstance(old_cfg.get(coll), dict) else {}
            subs = [k for k, m in sch.items()
                    if isinstance(m, dict) and m.get('type') == 'sub_collection']
            for ik, item in items.items():
                if not isinstance(item, dict):
                    continue
                old_item = old_items.get(ik) if isinstance(old_items.get(ik), dict) else {}
                _check_fields(module, sch, item, old_item)
                for sub in subs:
                    sub_sch = schemas.get(f'{module}|{coll}|{sub}')
                    sub_items = item.get(sub)
                    if not isinstance(sub_sch, dict) or not isinstance(sub_items, dict):
                        continue
                    old_subs = old_item.get(sub) if isinstance(old_item.get(sub), dict) else {}
                    for sk, sub_item in sub_items.items():
                        if isinstance(sub_item, dict):
                            _check_fields(module, sub_sch, sub_item,
                                          old_subs.get(sk) if isinstance(old_subs.get(sk), dict)
                                          else {})


# ── unit spellings ───────────────────────────────────────────────────────────────
def normalize_unit_fields(data: dict) -> None:
    """Rewrite every ``*_unit`` value in place to the spelling the schemas offer now.

    The size ladder was always binary; only its labels were wrong, so ``GB`` became ``GiB``
    and the numbers did not move. Stored config still says ``GB`` though, and that is not a
    cosmetic difference by the time it reaches the browser: the dropdown now offers
    ``MiB/GiB/TiB``, a select whose value is not among its options shows the FIRST one, and
    saving without touching anything would silently rewrite a 100 GB threshold as 100 MiB —
    a thousandfold change to a limit the admin set, made by opening a page.

    So the value is migrated on the way out and persists the next time the item is saved.
    Driven by the field-name suffix rather than a list of module fields, because the modules
    that will add a threshold later are not knowable from here.
    """
    from lib.util.tools import normalize_unit  # noqa: PLC0415

    def _walk(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if isinstance(val, str) and str(key).endswith('_unit'):
                    node[key] = normalize_unit(val)
                else:
                    _walk(val)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data or {})


def build_module_page(modules_dir: str, module: str, status_raw: dict,
                      modules_raw: dict, lang: str) -> dict:
    """Data for a module-contributed SECTION (``__page__``), from its
    ``Watchful.page_data(items, status, lang)`` hook.

    This is the CACHED half of the page: it reads the monitor's last check results, so it
    answers instantly and costs no upstream API call.  A live refresh is a normal watchful
    action the module declares and serves itself (``/api/v1/modules/watchfuls/<m>/<a>``).
    The core stays module-agnostic — every string and number here comes from the module.
    """
    try:
        status = next((status_raw[k] for k in (f'watchfuls.{module}', module)
                       if isinstance(status_raw.get(k), dict)), {})
        cfg = next((modules_raw[k] for k in (f'watchfuls.{module}', module)
                    if isinstance(modules_raw.get(k), dict)), {})
        items = cfg.get('list') if isinstance(cfg.get('list'), dict) else {}
        parent = os.path.dirname(modules_dir or '')
        if parent and parent not in sys.path:
            sys.path.insert(0, parent)
        cls = getattr(importlib.import_module(f'watchfuls.{module}'), 'Watchful', None)
        fn = getattr(cls, 'page_data', None)
        return (fn(items, status, lang) or {}) if callable(fn) else {}
    except Exception:  # pylint: disable=broad-except
        return {}


def _widget_items(cfg: dict) -> dict:
    """A module's own items, for its widget hook — whatever it calls its collection.

    `list` is a convention and not a rule: three of the four modules with a widget use it and
    the SNMP watchful calls its collection `servers`, so a hook that took the items was handed
    an empty dict. Nothing broke loudly — the widget simply had no names in it, which is the
    quiet kind of wrong this codebase keeps finding.

    `list` still wins where it exists, so nothing that works today changes; the rest are merged
    in the order the module declares them, which for every module that has one is a single
    collection.
    """
    if isinstance((cfg or {}).get('list'), dict):
        return cfg['list']
    out: dict = {}
    for name, coll in (cfg or {}).items():
        if not str(name).startswith('__') and isinstance(coll, dict):
            out.update({k: v for k, v in coll.items() if isinstance(v, dict)})
    return out


def build_module_widgets(modules_dir: str, status_raw: dict, modules_raw: dict, lang: str,
                         may_see=None) -> dict:
    """Generic Overview-widget data: for every module declaring ``__overview_widget__``,
    call its ``Watchful.overview_widget(items, status, lang)`` hook and collect the result.
    The core stays module-agnostic — all domain logic/strings come from the module.

    *may_see* — ``(module, catalog_entry) -> bool`` — leaves out a module the caller may
    not see. Every widget declares the permission it needs (``perm``), and the endpoint
    asked nothing of it: anyone with ``overview_view`` read every module's widget data."""
    out: dict = {}
    try:
        from lib.modules.discovery.overview_widgets import overview_widgets_catalog  # noqa: PLC0415
        catalog = overview_widgets_catalog(modules_dir)
    except Exception:  # pylint: disable=broad-except
        return out
    if not catalog:
        return out
    parent = os.path.dirname(modules_dir or '')
    if parent and parent not in sys.path:
        sys.path.insert(0, parent)
    for mod_name in catalog:
        if may_see is not None and not may_see(mod_name, catalog[mod_name]):
            continue
        try:
            status = next((status_raw[k] for k in (f'watchfuls.{mod_name}', mod_name)
                           if isinstance(status_raw.get(k), dict)), {})
            cfg = next((modules_raw[k] for k in (f'watchfuls.{mod_name}', mod_name)
                        if isinstance(modules_raw.get(k), dict)), {})
            items = _widget_items(cfg)
            cls = getattr(importlib.import_module(f'watchfuls.{mod_name}'), 'Watchful', None)
            fn = getattr(cls, 'overview_widget', None)
            if callable(fn):
                out[mod_name] = fn(items, status, lang) or {}
        except Exception:  # pylint: disable=broad-except
            continue
    return out


