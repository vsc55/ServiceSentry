#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""History API routes: /api/v1/history/*

Module-name / label / field-metadata resolution lives in the Flask-free
:mod:`lib.core.history.service`; these routes own request parsing, permission gating, the
store query and audit.

Routes registered by this file:

    GET    /api/v1/history/index       Metadata for all recorded series
    GET    /api/v1/history             Time-series data for one (module, key)
    DELETE /api/v1/history             Delete all history for a (module, key)
    DELETE /api/v1/history/all         Delete the entire history database
    POST   /api/v1/history/test-write  Write a test record and read it back
    GET    /api/v1/history/diag        Diagnostic: internal history store state
"""

import time

from flask import jsonify, request, session

from lib.i18n import DEFAULT_LANG
from lib.core.history import service as history_svc


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
        return jsonify(history_svc.enrich_index(index, wa._modules_dir, modules_cfg, lang))

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
        hist_cfg = history_svc.history_meta(wa._modules_dir, module, lang)

        # field priority: explicit query param > module schema > auto-detect
        field = history_svc.resolve_field(hist_cfg, request.args.get('field'), data)

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
