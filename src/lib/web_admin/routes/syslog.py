#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Syslog receiver API routes: /api/v1/syslog/*"""

from flask import jsonify, request


def _int_arg(name, default=None):
    v = request.args.get(name, '')
    if v == '' or v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _multi_arg(name):
    """All non-empty string values for a repeated query arg (multi-select)."""
    return [v.strip() for v in request.args.getlist(name) if v.strip()]


def _multi_int_arg(name):
    """All integer values for a repeated query arg (multi-select)."""
    out = []
    for v in request.args.getlist(name):
        s = (v or '').strip()
        if not s:
            continue
        try:
            out.append(int(s))
        except (TypeError, ValueError):
            pass
    return out


def _syslog_filters():
    """Filter dict shared by the list and stats endpoints. hostname/app/facility/
    severity accept multiple values (Ctrl+click multi-select in the UI)."""
    return {
        'source':   request.args.get('source', '').strip(),
        'host':     request.args.get('host', '').strip(),
        'hostname': _multi_arg('hostname'),
        'app':      _multi_arg('app'),
        'facility': _multi_int_arg('facility'),
        'severity': _multi_int_arg('severity'),
        'severity_max': _int_arg('severity_max'),
        'since':    _int_arg('since'),
        'until':    _int_arg('until'),
        'q':        request.args.get('q', '').strip(),
    }


def register(app, wa):
    syslog_view_req   = wa._perm_required('syslog_view')
    syslog_delete_req = wa._perm_required('syslog_delete')

    @app.route('/api/v1/syslog', methods=['GET'])
    @syslog_view_req
    def api_syslog_list():
        """Return received messages (newest first) for the given filters."""
        store = getattr(wa, '_syslog_store', None)
        if store is None:
            return jsonify({'messages': [], 'total': 0})
        filters = _syslog_filters()
        limit  = _int_arg('limit', 200) or 200
        offset = _int_arg('offset', 0) or 0
        sort   = request.args.get('sort', 'ts').strip() or 'ts'
        order  = request.args.get('order', 'desc').strip() or 'desc'
        try:
            messages = store.query(filters, limit=limit, offset=offset, sort=sort, order=order)
            total = store.count(filters)
        except Exception:  # pylint: disable=broad-except
            return jsonify({'messages': [], 'total': 0})
        return jsonify({'messages': messages, 'total': total})

    @app.route('/api/v1/syslog/stats', methods=['GET'])
    @syslog_view_req
    def api_syslog_stats():
        """Aggregate counts for the dashboard charts (total + by host/severity/
        facility/app), honouring the same filters as the message list."""
        store = getattr(wa, '_syslog_store', None)
        _empty = {'total': 0, 'by_host': [], 'by_app': [],
                  'by_severity': [], 'by_facility': []}
        if store is None:
            return jsonify(_empty)
        filters = _syslog_filters()
        try:
            return jsonify(store.stats(filters, top=_int_arg('top', 10) or 10))
        except Exception:  # pylint: disable=broad-except
            return jsonify(_empty)

    @app.route('/api/v1/syslog/facets', methods=['GET'])
    @syslog_view_req
    def api_syslog_facets():
        """Distinct hosts/sources/apps for the filter dropdowns."""
        store = getattr(wa, '_syslog_store', None)
        if store is None:
            return jsonify({'hostname': [], 'source': [], 'app': []})
        return jsonify({c: store.distinct(c) for c in ('hostname', 'source', 'app')})

    @app.route('/api/v1/syslog/status', methods=['GET'])
    @syslog_view_req
    def api_syslog_status():
        """Listener status: enabled flag, running, configured ports, stored count."""
        store = getattr(wa, '_syslog_store', None)
        srv = getattr(wa, '_syslog_server', None)
        cfg = wa._config_section('syslog')
        return jsonify({
            'enabled': bool(cfg.get('enabled')),
            'running': bool(srv and srv.running),
            'udp_port': int(cfg.get('udp_port') or 0),
            'tcp_port': int(cfg.get('tcp_port') or 0),
            'tls_port': int(cfg.get('tls_port') or 0),
            'count': store.count() if store else 0,
        })

    @app.route('/api/v1/syslog', methods=['DELETE'])
    @syslog_delete_req
    def api_syslog_clear():
        """Delete all stored syslog messages."""
        store = getattr(wa, '_syslog_store', None)
        deleted = store.delete_all() if store else 0
        wa._audit('syslog_cleared', detail={'deleted': deleted})
        return jsonify({'ok': True, 'deleted': deleted})

    @app.route('/api/v1/syslog/drops', methods=['GET'])
    @syslog_view_req
    def api_syslog_drops():
        """Senders rejected by the allowlist — what is being dropped (per source)."""
        store = getattr(wa, '_syslog_drops_store', None)
        if store is None:
            return jsonify({'drops': [], 'sources': 0, 'dropped': 0})
        try:
            return jsonify({'drops': store.query(limit=_int_arg('limit', 200) or 200),
                            **store.totals()})
        except Exception:  # pylint: disable=broad-except
            return jsonify({'drops': [], 'sources': 0, 'dropped': 0})

    @app.route('/api/v1/syslog/drops', methods=['DELETE'])
    @syslog_delete_req
    def api_syslog_drops_clear():
        """Reset the dropped-sender tally."""
        store = getattr(wa, '_syslog_drops_store', None)
        deleted = store.delete_all() if store else 0
        wa._audit('syslog_drops_cleared', detail={'deleted': deleted})
        return jsonify({'ok': True, 'deleted': deleted})

    @app.route('/api/v1/syslog/drops/<uid>', methods=['DELETE'])
    @syslog_delete_req
    def api_syslog_drop_delete(uid):
        """Remove a single dropped source from the tally."""
        store = getattr(wa, '_syslog_drops_store', None)
        if store is None or not store.delete(uid):
            return jsonify({'error': 'Not found'}), 404
        wa._audit('syslog_drops_cleared', detail={'uid': uid})
        return jsonify({'ok': True})
