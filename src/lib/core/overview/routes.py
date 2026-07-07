#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview domain routes — dashboard *layout* management.

The org-wide default layout (``config.overview.default_layout``) and the per-user
factory reset.  Two things deliberately stay elsewhere because they are not overview
*layout* concerns:

* the overview *data* snapshot (``GET /api/v1/modules/overview``) lives in the modules
  domain — it aggregates module/check/server state;
* the widget catalog (``overview_widgets_catalog``) lives in the module-discovery layer
  (:mod:`lib.modules.discovery.overview_widgets`) — it is discovered from the watchful
  modules.
"""

from flask import jsonify, request, session


def register(app, wa):
    overview_view_req = wa._perm_required('overview_view')

    # --- API: data-driven widget data (AJAX, one request per widget) --------------
    @app.route('/api/v1/overview/widget/<wid>', methods=['GET'])
    def api_widget_data(wid):
        """Self-contained data for one Overview widget so every card/table fetches its own
        (no monolithic aggregate).  Returns ``{content}`` for a **stat** card (its
        ``stat(wa)`` provider) or ``{rows}`` for a **table** (its ``rows(wa, f)`` provider,
        filtered server-side via ``?f=``).  The provider + permission gate (``perms`` =
        any/prefix) come from the widget's own descriptor."""
        from lib.core.overview.discovery import (  # noqa: PLC0415
            discover_widget_rows, discover_widget_stats, discover_overview_widgets)
        stat_fn = discover_widget_stats().get(wid)
        rows_fn = discover_widget_rows().get(wid)
        if stat_fn is None and rows_fn is None:
            return jsonify({'error': 'not_found'}), 404
        desc = next((w for w in discover_overview_widgets() if w.get('id') == wid), None)
        perms = wa._get_session_permissions()
        p = (desc or {}).get('perms') or {}
        any_p, prefixes = p.get('any') or [], tuple(p.get('prefix') or [])
        if (any_p or prefixes) and not (
                any(x in perms for x in any_p)
                or (prefixes and any(str(x).startswith(prefixes) for x in perms))):
            return jsonify({'error': 'forbidden'}), 403
        if stat_fn is not None:
            try:
                content = stat_fn(wa)
            except Exception:  # pylint: disable=broad-except
                content = {}
            return jsonify({'content': content})
        # Read the filter value under the name the widget declares (view.filter.param),
        # defaulting to 'f' — otherwise a widget with a custom param (e.g. syslog's
        # 'severity_max') never receives its filter and shows unfiltered rows.
        fparam = (((desc or {}).get('view') or {}).get('filter') or {}).get('param') or 'f'
        try:
            rows = rows_fn(wa, request.args.get(fparam, ''))
        except Exception:  # pylint: disable=broad-except
            rows = []
        return jsonify({'rows': rows})

    # --- API: org-wide default dashboard layout ------------------
    @app.route('/api/v1/overview/default-layout', methods=['GET'])
    @overview_view_req
    def api_get_default_layout():
        """Org-wide default dashboard layout, applied to users who have not
        customised theirs. Empty ⇒ the frontend falls back to its built-in layout."""
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        return jsonify((cfg.get('overview') or {}).get('default_layout') or [])

    overview_setdef_req = wa._perm_required('overview_set_default')

    @app.route('/api/v1/overview/default-layout', methods=['PUT'])
    @overview_setdef_req
    def api_set_default_layout():
        """Save the posted layout as the org-wide default (config.overview).

        Gated by the dedicated ``overview_set_default`` permission — it changes
        the default for *every* user, beyond editing one's own dashboard."""
        data, err = wa._require_json()
        if err:
            return err
        widgets = data.get('layout')
        if not isinstance(widgets, list):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        layout = [
            {
                'id':     str(w.get('id', '')),
                'cols':   int(w.get('cols') or 2),
                'h':      w.get('h', 'auto'),
                'hidden': bool(w.get('hidden')),
            }
            for w in widgets if isinstance(w, dict) and w.get('id')
        ]
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        cfg.setdefault('overview', {})['default_layout'] = layout
        ok = wa._write_config(cfg)
        wa._audit('overview_default_layout_set', detail={
            'widgets': len(layout),
            'visible': [w['id'] for w in layout if not w.get('hidden')],
        })
        return jsonify({'ok': bool(ok)})

    overview_resetfac_req = wa._perm_required('overview_reset_factory')

    @app.route('/api/v1/overview/reset-factory', methods=['POST'])
    @overview_resetfac_req
    def api_reset_factory_layout():
        """Reset the caller's own dashboard to the factory built-in layout,
        persisted to their account — audited as a permission-gated action."""
        data, err = wa._require_json()
        if err:
            return err
        widgets = data.get('layout')
        layout = [
            {
                'id':     str(w.get('id', '')),
                'cols':   int(w.get('cols') or 2),
                'h':      w.get('h', 'auto'),
                'hidden': bool(w.get('hidden')),
            }
            for w in (widgets if isinstance(widgets, list) else [])
            if isinstance(w, dict) and w.get('id')
        ]
        user = wa._users.get(session.get('username', ''))
        if user is not None:
            user['dashboard_layout'] = layout
            wa._persist_users()
        wa._audit('overview_reset_factory', detail={
            'widgets': len(layout),
            'visible': [w['id'] for w in layout if not w.get('hidden')],
        })
        return jsonify({'ok': True})
