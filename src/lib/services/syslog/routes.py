#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Syslog receiver API routes: /api/v1/syslog/* — received messages, aggregate stats,
facets, listener status, and the dropped-sender tally (senders rejected by the allowlist).

Query-arg parsing helpers live here (they read ``flask.request`` — a routes concern); the
store consumes the plain filter dict they produce (Flask-free).

Routes registered by this file:

    GET    /api/v1/syslog              received messages (newest first)
    GET    /api/v1/syslog/stats        aggregate counts for dashboard charts
    GET    /api/v1/syslog/facets       distinct devices/sources/apps for filters
    GET    /api/v1/syslog/status       listener status + stored count
    DELETE /api/v1/syslog              delete all stored messages (internal source only)

The four reads take ``src=<uid>``: an external source (another program's database, see
:mod:`lib.services.syslog.sources`) instead of the panel's own table. Not ``source`` — that
one was already the sender-IP filter. The external sources themselves are managed in
:mod:`lib.services.syslog.routes_sources`.
    GET    /api/v1/syslog/drops        senders rejected by the allowlist
    DELETE /api/v1/syslog/drops        reset the dropped-sender tally
    DELETE /api/v1/syslog/drops/<uid>  remove a single dropped source
"""

from flask import jsonify, request

from lib.services.syslog import sources as _sources


# ── query-arg parsing (shared by the message + drops handlers) ───────────────────
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
            # Query strings are user input: a non-numeric value is not a filter, not a 500.
            pass
    return out


def _syslog_filters():
    """Filter dict shared by the list and stats endpoints. hostname/app/facility/
    severity accept multiple values (Ctrl+click multi-select in the UI)."""
    return {
        'source':   request.args.get('source', '').strip(),
        'host':     request.args.get('device', '').strip(),   # a device's address, matched against the sender
        'hostname': _multi_arg('hostname'),
        'app':      _multi_arg('app'),
        'facility': _multi_int_arg('facility'),
        'severity': _multi_int_arg('severity'),
        'severity_max': _int_arg('severity_max'),
        'since':    _int_arg('since'),
        'until':    _int_arg('until'),
        'q':        request.args.get('q', '').strip(),
    }


def pick_store(wa):
    """The store ``?src=`` names: ``(store, None)``, or ``(None, (response, status))``.

    No ``src`` (or ``internal``) is the panel's own table, which ``syslog_view`` — already
    checked by the route — grants. An external one also needs ``syslog_sources_all_view`` or
    its own ``syslogsrc.<uid>.view``; one that is unknown or switched off is a 404, and one
    that cannot be reached a 503 that says why — the page shows it, nothing else breaks."""
    src = request.args.get('src', '').strip()
    if not src or src == _sources.INTERNAL:
        return getattr(wa, '_syslog_store', None), None
    if not _sources.may_see(src, wa._get_session_permissions()):
        return None, (jsonify({'error': wa._t('access_denied')}), 403)
    registry = getattr(wa, '_syslog_sources', None)
    if registry is None:
        return None, (jsonify({'error': 'syslog_source_unknown'}), 404)
    try:
        return registry.get(src), None
    except KeyError:
        return None, (jsonify({'error': 'syslog_source_unknown'}), 404)
    except _sources.SourceUnavailable as exc:
        return None, (jsonify({'error': 'syslog_source_unreachable', 'detail': str(exc)}), 503)


def register(app, wa):
    syslog_view_req   = wa._perm_required('syslog_view')
    syslog_delete_req = wa._perm_required('syslog_delete')

    # The external sources' own routes (list, add, edit, delete, test).
    from lib.services.syslog.routes_sources import register as _register_sources  # noqa: PLC0415
    _register_sources(app, wa)

    # ── received messages ────────────────────────────────────────────────────────

    @app.route('/api/v1/syslog', methods=['GET'])
    @syslog_view_req
    def api_syslog_list():
        """Return received messages (newest first) for the given filters."""
        store, fail = pick_store(wa)
        if fail:
            return fail
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
        store, fail = pick_store(wa)
        if fail:
            return fail
        _empty = {'total': 0, 'by_device': [], 'by_app': [],
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
        """Distinct devices/sources/apps for the filter dropdowns."""
        store, fail = pick_store(wa)
        if fail:
            return fail
        if store is None:
            return jsonify({'hostname': [], 'source': [], 'app': []})
        try:
            return jsonify({c: store.distinct(c) for c in ('hostname', 'source', 'app')})
        except Exception:  # pylint: disable=broad-except
            return jsonify({'hostname': [], 'source': [], 'app': []})

    @app.route('/api/v1/syslog/status', methods=['GET'])
    @syslog_view_req
    def api_syslog_status():
        """Listener status: enabled flag, running, configured ports, stored count.

        For an external source: its name and count instead — there is no listener of ours
        behind it, and nothing on it can be cleared."""
        store, fail = pick_store(wa)
        if fail:
            return fail
        if getattr(store, 'read_only', False):
            try:
                count = store.count()
            except Exception:  # pylint: disable=broad-except
                count = 0
            return jsonify({'read_only': True, 'running': False, 'enabled': True,
                            'count': count})
        srv = getattr(wa, '_syslog_server', None)
        # Effective config (registry defaults merged), not the raw stored section —
        # so an unset field reports its default (e.g. enabled/ports) exactly as the
        # listener would use it, instead of a misleading None/0.
        sy = wa._embedded_services.get('syslog')
        cfg = sy._syslog_cfg() if sy else (wa._config_section('syslog') or {})
        return jsonify({
            'enabled': bool(cfg.get('enabled')),
            'running': bool(srv and srv.running),
            'udp_port': int(cfg.get('udp_port') or 0),
            'tcp_port': int(cfg.get('tcp_port') or 0),
            'tls_port': int(cfg.get('tls_port') or 0),
            'count': store.count() if store else 0,
            'read_only': False,
        })

    @app.route('/api/v1/syslog', methods=['DELETE'])
    @syslog_delete_req
    def api_syslog_clear():
        """Delete all stored syslog messages — of the internal source only."""
        store = getattr(wa, '_syslog_store', None)
        if (request.args.get('src', '').strip() not in ('', _sources.INTERNAL)
                or getattr(store, 'read_only', False)):
            # Somebody else's database (an external source, or syslog_db in external mode):
            # what it keeps is not this panel's to empty.
            return jsonify({'ok': False, 'error': 'syslog_read_only'}), 409
        deleted = store.delete_all() if store else 0
        wa._audit('syslog_cleared', detail={'deleted': deleted})
        return jsonify({'ok': True, 'deleted': deleted})

    # ── dropped senders (rejected by the allowlist) ──────────────────────────────

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
            return jsonify({'error': wa._t('not_found')}), 404
        wa._audit('syslog_drops_cleared', detail={'uid': uid})
        return jsonify({'ok': True})
