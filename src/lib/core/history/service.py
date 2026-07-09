#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free history metadata/label resolution — the module-name, per-field label/unit and
series-label logic extracted from :mod:`lib.core.history.routes`.

Pure functions over the modules directory + module config; no Flask, no store writes.  The
route owns request parsing, permission gating, the store query and audit.  (This is a read
path, so there are no :class:`AdminOpError` validation failures here.)
"""

from __future__ import annotations

import json
import os


def _pretty_name(modules_dir: str | None, module: str, lang: str) -> str:
    """Return the human-readable module name from its lang JSON, or the raw name."""
    if not modules_dir:
        return module
    for try_lang in (lang, 'en_EN'):
        path = os.path.join(modules_dir, module, 'lang', f'{try_lang}.json')
        try:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
            name = data.get('pretty_name')
            if name:
                return str(name)
        except (OSError, ValueError):
            pass
    return module


def _history_config(modules_dir: str | None, module: str) -> dict:
    """Return the __history__ block from the module's schema.json, or {}."""
    if not modules_dir:
        return {}
    path = os.path.join(modules_dir, module, 'schema.json')
    try:
        with open(path, encoding='utf-8') as fh:
            schema = json.load(fh)
        cfg = schema.get('__history__', {})
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def _prettify_field(field: str) -> str:
    """Fallback label for a history field name: 'battery_charge' → 'Battery charge'."""
    s = str(field or '').replace('_', ' ').strip()
    return s[:1].upper() + s[1:] if s else field


def _history_labels(modules_dir: str | None, module: str, lang: str) -> dict:
    """Per-field display labels from the module lang JSON ``history`` map."""
    if not modules_dir:
        return {}
    for try_lang in (lang, 'en_EN'):
        path = os.path.join(modules_dir, module, 'lang', f'{try_lang}.json')
        try:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
            hist = data.get('history')
            if isinstance(hist, dict) and hist:
                return {k: str(v) for k, v in hist.items()}
        except (OSError, ValueError):
            pass
    return {}


def history_meta(modules_dir: str | None, module: str, lang: str) -> dict:
    """``__history__`` enriched with a resolved per-field ``fields`` map.

    ``fields`` is ``{name: {unit, label}}`` for every numeric field the module
    records (declared in ``__history__.fields`` and/or the single ``field``).
    Labels come from the module lang ``history`` map, falling back to the
    schema label (primary field) or a prettified field name.  Status-only
    modules (``field: null`` with no ``fields``) get an empty map.
    """
    cfg = dict(_history_config(modules_dir, module))
    labels = _history_labels(modules_dir, module, lang)
    declared = cfg.get('fields') if isinstance(cfg.get('fields'), dict) else {}
    primary  = cfg.get('field') if isinstance(cfg.get('field'), str) else None
    fields: dict = {}
    for name, meta in declared.items():
        meta = meta if isinstance(meta, dict) else {}
        fields[name] = {
            'unit':  meta.get('unit', cfg.get('unit') or ''),
            'label': labels.get(name) or meta.get('label')
                     or (cfg.get('label') if name == primary else None)
                     or _prettify_field(name),
        }
    if primary and primary not in fields:
        fields[primary] = {
            'unit':  cfg.get('unit') or '',
            'label': labels.get(primary) or cfg.get('label') or _prettify_field(primary),
        }
    cfg['fields'] = fields
    # Translate the top-level label too (single-series Y-axis / metric label).
    if primary:
        cfg['label'] = labels.get(primary) or cfg.get('label') or _prettify_field(primary)
    return cfg


def check_label(modules_cfg: dict, mod: str, key: str, item_uid: str) -> str:
    """The item's display 'label' from the module configuration — the series key may be an
    opaque UID, so show the friendly name instead.  Composite keys ``<item>/<metric>`` (e.g.
    proxmox ``<uid>/node/pve04``) resolve the leading item segment to its label and keep the
    metric → ``<label> / node/pve04``."""
    def _lookup(cand: str) -> str:
        if not cand:
            return ''
        for mk in (mod, f'watchfuls.{mod}', mod.split('.')[-1]):
            mc = modules_cfg.get(mk)
            if not isinstance(mc, dict):
                continue
            for coll, items in mc.items():
                if coll.startswith('__') or not isinstance(items, dict):
                    continue
                it = items.get(cand)
                if isinstance(it, dict) and str(it.get('label') or '').strip():
                    return str(it['label'])
        return ''

    # Whole-key match first (inline checks whose key IS the item).
    whole = _lookup(key)
    if whole:
        return whole
    # Composite '<item>/<metric>': resolve the leading segment, keep the rest.
    if key and '/' in key:
        head, rest = key.split('/', 1)
        head_label = _lookup(head)
        if head_label:
            return f'{head_label} / {rest}'
    # Fall back to the bare item UID (non-composite derived keys).
    return _lookup(item_uid)


def enrich_index(index: list, modules_dir: str | None, modules_cfg: dict, lang: str) -> list:
    """Enrich a history index (in place) with ``pretty_name``, ``history_cfg`` and a friendly
    ``label`` per entry.  Caches per-module lookups to avoid repeated file reads.  Returns
    *index* for convenience."""
    name_cache:    dict[str, str]  = {}
    history_cache: dict[str, dict] = {}
    for entry in index:
        mod = entry['module']
        if mod not in name_cache:
            name_cache[mod]    = _pretty_name(modules_dir, mod, lang)
            history_cache[mod] = history_meta(modules_dir, mod, lang)
        entry['pretty_name']  = name_cache[mod]
        entry['history_cfg']  = history_cache[mod]  # {field, unit, label, fields}
        # Friendly label priority:
        #  1. the item's editable 'label' in the module configuration (matched by key/uid)
        #  2. the display 'name' the module stored in the record's other_data
        #     (covers derived result keys like "<uid>_ram"/"_swap" that are not
        #     a real item key, so step 1 can't find them)
        label = check_label(modules_cfg, mod, entry.get('key', ''), entry.get('item_uid', ''))
        if not label:
            last_data = entry.get('last_data')
            if isinstance(last_data, dict):
                label = str(last_data.get('name') or '').strip()
        entry['label'] = label
    return index


def resolve_field(hist_cfg: dict, explicit_field, data: list):
    """Pick the numeric field to chart: explicit query param > module schema ``field`` >
    auto-detected from the data (``HistoryStore.suggest_field``)."""
    field = explicit_field or None
    if field is None:
        schema_field = hist_cfg.get('field')
        if schema_field is not None:
            field = schema_field
        else:
            from .store import HistoryStore  # noqa: PLC0415
            field = HistoryStore.suggest_field(data)
    return field
