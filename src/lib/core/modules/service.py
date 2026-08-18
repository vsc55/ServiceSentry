#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The module-config document: what may be seen of it, whether it is well formed, and what
the UI is built from.

What was one 787-line module is now the domain it described: `items.py` (an item's identity),
`authz.py` (may this save touch this item), `provisioning.py` (credentials out, declared hosts
in), `actions.py` (the config a watchful action runs with). What stayed is the document
itself — the whole config as it is read, checked, normalised and rendered.

Everything here is Flask-free (no request/session/jsonify); the route owns request parsing,
secret restore, persistence and audit. Most of it is pure over plain dicts and raises
:class:`~lib.core.users.service.AdminOpError` on a violation.
"""

from __future__ import annotations

import importlib
import os
import sys

from lib.core.users.service import AdminOpError


# ── view / validation ────────────────────────────────────────────────────────────
def visible_modules(all_data: dict, perms) -> dict:
    """The subset of *all_data* the user may view via per-module ``module.{name}.view``
    permissions (used when the user lacks the global ``modules_view``)."""
    return {n: c for n, c in all_data.items() if f'module.{n}.view' in perms}


def validate_modules_shape(data: dict) -> None:
    """Every top-level value must be a module-config dict.  Raises on a malformed body."""
    if not all(isinstance(v, dict) for v in data.values()):
        raise AdminOpError('invalid_modules_data')


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


def build_module_widgets(modules_dir: str, status_raw: dict, modules_raw: dict, lang: str) -> dict:
    """Generic Overview-widget data: for every module declaring ``__overview_widget__``,
    call its ``Watchful.overview_widget(items, status, lang)`` hook and collect the result.
    The core stays module-agnostic — all domain logic/strings come from the module."""
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
        try:
            status = next((status_raw[k] for k in (f'watchfuls.{mod_name}', mod_name)
                           if isinstance(status_raw.get(k), dict)), {})
            cfg = next((modules_raw[k] for k in (f'watchfuls.{mod_name}', mod_name)
                        if isinstance(modules_raw.get(k), dict)), {})
            items = cfg.get('list') if isinstance(cfg.get('list'), dict) else {}
            cls = getattr(importlib.import_module(f'watchfuls.{mod_name}'), 'Watchful', None)
            fn = getattr(cls, 'overview_widget', None)
            if callable(fn):
                out[mod_name] = fn(items, status, lang) or {}
        except Exception:  # pylint: disable=broad-except
            continue
    return out


