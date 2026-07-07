#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""History API routes: /api/v1/history/*"""

import json
import os
import time

from flask import jsonify, request, session

from lib.i18n import DEFAULT_LANG


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


def _history_meta(modules_dir: str | None, module: str, lang: str) -> dict:
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


def register(app, wa):
    history_view_req   = wa._perm_required('history_view')
    history_delete_req = wa._perm_required('history_delete')

    @app.route('/api/v1/history/index', methods=['GET'])
    @history_view_req
    def api_history_index():
        """Return metadata for all recorded series, including module pretty names."""
        if not wa._history:
            return jsonify([])
        lang  = session.get('lang') or wa._default_lang or DEFAULT_LANG
        index = wa._history.get_index()
        modules_cfg = wa._load_modules()

        def _check_label(mod: str, key: str, item_uid: str) -> str:
            """The item's display 'label' from the module configuration — the series key may
            be an opaque UID, so show the friendly name instead.  Composite keys
            ``<item>/<metric>`` (e.g. proxmox ``<uid>/node/pve04``) resolve the leading
            item segment to its label and keep the metric → ``<label> / node/pve04``."""
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

        # Cache per-module data to avoid repeated file reads
        _name_cache:    dict[str, str]  = {}
        _history_cache: dict[str, dict] = {}
        for entry in index:
            mod = entry['module']
            if mod not in _name_cache:
                _name_cache[mod]    = _pretty_name(wa._modules_dir, mod, lang)
                _history_cache[mod] = _history_meta(wa._modules_dir, mod, lang)
            entry['pretty_name']  = _name_cache[mod]
            entry['history_cfg']  = _history_cache[mod]  # {field, unit, label, fields}
            # Friendly label priority:
            #  1. the item's editable 'label' in the module configuration (matched by key/uid)
            #  2. the display 'name' the module stored in the record's other_data
            #     (covers derived result keys like "<uid>_ram"/"_swap" that are not
            #     a real item key, so step 1 can't find them)
            label = _check_label(mod, entry.get('key', ''), entry.get('item_uid', ''))
            if not label:
                last_data = entry.get('last_data')
                if isinstance(last_data, dict):
                    label = str(last_data.get('name') or '').strip()
            entry['label'] = label
        return jsonify(index)

    @app.route('/api/v1/history', methods=['GET'])
    @history_view_req
    def api_history_query():
        """Return time-series data for one (module, key) pair.

        Query params:
          module  — required
          key     — required
          hours   — time window in hours (default 24, max 8760)
          points  — max samples to return (default 500, max 2000)
          field   — override the suggested numeric field
        """
        if not wa._history:
            return jsonify({'points': [], 'stats': {}, 'suggested_field': None})

        module   = request.args.get('module', '').strip()
        key      = request.args.get('key', '').strip()
        item_uid = request.args.get('uid', '').strip() or None
        if not module or not key:
            return jsonify({'error': 'module and key are required'}), 400

        try:
            # Fractional hours allowed (sub-hour ranges like "10m" → 1/6 h);
            # up to ~10 years for "Ny" ranges.
            hours  = min(87600.0, max(1 / 60, float(request.args.get('hours', 24))))
            points = min(2000, max(10, int(request.args.get('points', 500))))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid hours or points'}), 400

        to_ts   = time.time()
        from_ts = to_ts - hours * 3600

        data     = wa._history.query(
            module, key, from_ts, to_ts, points, item_uid=item_uid
        )
        lang     = session.get('lang') or wa._default_lang or DEFAULT_LANG
        hist_cfg = _history_meta(wa._modules_dir, module, lang)

        # field priority: explicit query param > module schema > auto-detect
        field = request.args.get('field') or None
        if field is None:
            schema_field = hist_cfg.get('field')
            if schema_field is not None:
                field = schema_field
            else:
                from .store import HistoryStore  # noqa: PLC0415
                field = HistoryStore.suggest_field(data)

        stats = wa._history.get_stats(
            module, key, from_ts, to_ts, field, item_uid=item_uid
        )

        # Unit / label follow the SELECTED field (modules can record several).
        fmeta = (hist_cfg.get('fields') or {}).get(field or '', {})
        return jsonify({
            'points':          data,
            'suggested_field': field,
            'unit':            fmeta.get('unit', hist_cfg.get('unit') or ''),
            'metric_label':    fmeta.get('label') or hist_cfg.get('label') or '',
            'fields':          hist_cfg.get('fields') or {},
            'stats':           stats,
        })

    @app.route('/api/v1/history', methods=['DELETE'])
    @history_delete_req
    def api_history_delete():
        """Delete all history for a (module, key) pair.

        Accepts module and key as query parameters so that the request body
        is not needed (DELETE + body is unreliable across proxies).
        """
        if not wa._history:
            return jsonify({'ok': True, 'deleted': 0})

        module   = request.args.get('module', '').strip()
        key      = request.args.get('key', '').strip()
        item_uid = request.args.get('uid', '').strip() or None
        if not module or not key:
            return jsonify({'error': 'module and key are required'}), 400

        deleted = wa._history.delete_series(module, key, item_uid=item_uid)
        wa._audit('history_deleted', detail={
            'module': module, 'key': key, 'item_uid': item_uid or '', 'deleted': deleted,
        })
        return jsonify({'ok': True, 'deleted': deleted})

    @app.route('/api/v1/history/all', methods=['DELETE'])
    @history_delete_req
    def api_history_delete_all():
        """Delete the entire history database."""
        if not wa._history:
            return jsonify({'ok': True, 'deleted': 0})
        deleted = wa._history.delete_all()
        wa._audit('history_all_deleted', detail={'deleted': deleted})
        return jsonify({'ok': True, 'deleted': deleted})

    @app.route('/api/v1/history/test-write', methods=['POST'])
    @history_view_req
    def api_history_test_write():
        """Write a test record and immediately read it back.
        Verifies the full read/write path without the daemon."""
        import sys  # noqa: PLC0415
        h = wa._history
        if h is None:
            return jsonify({'ok': False, 'error': 'wa._history is None'})
        try:
            before = h.get_index()
            h.record('__test__', '__test__', True, {'value': 42.0})
            after  = h.get_index()
            entry  = next((e for e in after if e['module'] == '__test__'), None)
            # Clean up
            h.delete_series('__test__', '__test__')
            return jsonify({
                'ok':           bool(entry),
                'before_count': len(before),
                'after_count':  len(after),
                'test_entry':   entry,
                'db_path':      getattr(h, '_path', '?'),
            })
        except Exception as exc:  # pylint: disable=broad-except
            import traceback  # noqa: PLC0415
            traceback.print_exc(file=sys.stderr)
            return jsonify({'ok': False, 'error': str(exc)})

    @app.route('/api/v1/history/diag', methods=['GET'])
    @history_view_req
    def api_history_diag():
        """Diagnostic endpoint — returns internal state of the history store."""
        import sys  # noqa: PLC0415
        h = wa._history
        if h is None:
            return jsonify({
                'store': None,
                'var_dir': wa._var_dir,
                'error': '_history is None — _init_history() failed or var_dir not set',
            })
        try:
            count_row = h._conn().execute('SELECT COUNT(*) FROM history').fetchone()
            count     = count_row[0] if count_row else -1
            cols      = [r[1] for r in h._conn().execute('PRAGMA table_info(history)').fetchall()]
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'store': 'error', 'error': str(exc)})
        return jsonify({
            'store':      'SQLiteConnector',
            'db_path':    getattr(h, '_path', '?'),
            'var_dir':    wa._var_dir,
            'rows':       count,
            'columns':    cols,
            'py_version': sys.version,
        })
