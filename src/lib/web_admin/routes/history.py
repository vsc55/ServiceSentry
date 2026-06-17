#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""History API routes: /api/v1/history/*"""

import json
import os
import time

from flask import jsonify, request, session

from lib.web_admin.constants import DEFAULT_LANG


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
        modules_cfg = wa._read_config_file(wa._MODULES_FILE) or {}

        def _check_label(mod: str, key: str, item_uid: str) -> str:
            """The item's display 'label' from modules.json — the series key may
            be an opaque UID, so show the friendly name instead."""
            for mk in (mod, f'watchfuls.{mod}', mod.split('.')[-1]):
                mc = modules_cfg.get(mk)
                if not isinstance(mc, dict):
                    continue
                for coll, items in mc.items():
                    if coll.startswith('__') or not isinstance(items, dict):
                        continue
                    for cand in (key, item_uid):
                        it = items.get(cand) if cand else None
                        if isinstance(it, dict) and str(it.get('label') or '').strip():
                            return str(it['label'])
            return ''

        # Cache per-module data to avoid repeated file reads
        _name_cache:    dict[str, str]  = {}
        _history_cache: dict[str, dict] = {}
        for entry in index:
            mod = entry['module']
            if mod not in _name_cache:
                _name_cache[mod]    = _pretty_name(wa._modules_dir, mod, lang)
                _history_cache[mod] = _history_config(wa._modules_dir, mod)
            entry['pretty_name']  = _name_cache[mod]
            entry['history_cfg']  = _history_cache[mod]  # {field, unit, label}
            # Friendly label priority:
            #  1. the item's editable 'label' in modules.json (matched by key/uid)
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
            hours  = min(8760, max(1, int(request.args.get('hours', 24))))
            points = min(2000, max(10, int(request.args.get('points', 500))))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid hours or points'}), 400

        to_ts   = time.time()
        from_ts = to_ts - hours * 3600

        data     = wa._history.query(
            module, key, from_ts, to_ts, points, item_uid=item_uid
        )
        hist_cfg = _history_config(wa._modules_dir, module)

        # field priority: explicit query param > module schema > auto-detect
        field = request.args.get('field') or None
        if field is None:
            schema_field = hist_cfg.get('field')
            if schema_field is not None:
                field = schema_field
            else:
                from lib.stores.history import HistoryStore  # noqa: PLC0415
                field = HistoryStore.suggest_field(data)

        stats = wa._history.get_stats(
            module, key, from_ts, to_ts, field, item_uid=item_uid
        )

        return jsonify({
            'points':          data,
            'suggested_field': field,
            'unit':            hist_cfg.get('unit') or '',
            'metric_label':    hist_cfg.get('label') or '',
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
