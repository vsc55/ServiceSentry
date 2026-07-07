#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IP ban (internal fail2ban) management routes: /api/v1/ipbans.

Lists the jailed IPs and lets an operator ban or lift a ban manually.  The jail
itself is enforced everywhere by :class:`lib.services.ipban.jail.IpBanManager`; these
endpoints are only its management surface.  Gated by the config permissions
(fail2ban is a security-admin function).
"""

import ipaddress
import time

from flask import jsonify, request, session

_MAX_REASON = 200        # cap free-text reason / description to keep rows bounded


def register(app, wa):
    # Granular per-resource fail2ban permissions (bans / watchlist / whitelist /
    # history / exposed services). Each endpoint gates on exactly its operation.
    ban_view_req  = wa._perm_required('ipban_ban_view')
    ban_add_req   = wa._perm_required('ipban_ban_add')
    ban_edit_req  = wa._perm_required('ipban_ban_edit')
    ban_del_req   = wa._perm_required('ipban_ban_delete')
    watch_clear_req = wa._perm_required('ipban_watchlist_clear')
    wl_view_req   = wa._perm_required('ipban_whitelist_view')
    wl_add_req    = wa._perm_required('ipban_whitelist_add')
    wl_del_req    = wa._perm_required('ipban_whitelist_delete')
    hist_view_req = wa._perm_required('ipban_history_view')
    # An IP's attempt-history modal is opened from the bans/history views.
    any_view_req  = wa._perm_required('ipban_ban_view', 'ipban_history_view', 'ipban_whitelist_view')
    # Exposed services live in Config → fail2ban: setting the per-service action needs
    # ipban_service_edit (or general config_edit); viewing the card is open to config
    # admins and any fail2ban viewer.
    svc_edit_req  = wa._perm_required('ipban_service_edit', 'config_edit')
    svc_view_req  = wa._perm_required('ipban_service_edit', 'config_view', 'config_edit',
                                      'ipban_ban_view', 'ipban_whitelist_view', 'ipban_history_view')

    @app.route('/api/v1/ipbans', methods=['GET'])
    @ban_view_req
    def api_ipbans():
        """Currently-jailed IPs (active only) plus the *watchlist*: IPs accumulating
        unauthorized-access offenses but not yet banned. Expired bans drop off here —
        the full history lives in /api/v1/ipbans/banlog."""
        mgr = getattr(wa, '_ipban', None)
        if mgr is None:
            return jsonify({'bans': [], 'offenders': [], 'enabled': False})
        bans = mgr.list_bans(active_only=True)
        return jsonify({'bans': bans,
                        'offenders': mgr.list_offenders(),
                        'enabled': bool(wa._IPBAN_ENABLED),
                        'count': sum(1 for b in bans if b.get('active'))})

    @app.route('/api/v1/ipbans', methods=['POST'])
    @ban_add_req
    def api_ipban_add():
        """Manually ban an IP.  Body: ``{ip, duration_secs?, reason?}`` — a positive
        ``duration_secs`` forces that term, ``0`` = permanent, omitted = escalation
        ladder.  A whitelisted IP is refused."""
        data = request.get_json(silent=True) or {}
        ip = str(data.get('ip', '')).strip()
        if not ip:
            return jsonify({'error': wa._t('ipban_ip_required')}), 400
        try:
            ip = str(ipaddress.ip_address(ip))   # validate + normalize a single IP
        except ValueError:
            return jsonify({'error': wa._t('ipban_ip_invalid')}), 400
        mgr = getattr(wa, '_ipban', None)
        if mgr is None:
            return jsonify({'error': 'unavailable'}), 503
        if mgr.is_whitelisted(ip):
            return jsonify({'error': wa._t('ipban_whitelisted')}), 400
        dur = data.get('duration_secs')
        try:
            dur = None if dur in (None, '') else int(dur)
        except (TypeError, ValueError):
            dur = None
        reason = str(data.get('reason') or 'manual').strip()[:_MAX_REASON] or 'manual'
        rec = mgr.ban(ip, duration_secs=dur, reason=reason,
                      by=session.get('username', 'admin'))
        if rec is None:
            return jsonify({'error': wa._t('ipban_whitelisted')}), 400
        return jsonify({'ok': True, 'ban': rec})

    # ── service registry (exposed services + their block-action capabilities) ───
    @app.route('/api/v1/ipbans/services', methods=['GET'])
    @svc_view_req
    def api_ipban_services():
        """The registered port-exposing services: their endpoints, the block actions
        each supports, and the currently configured action."""
        reg = getattr(wa, '_ipban_services', None)
        return jsonify({'services': reg.services() if reg is not None else []})

    @app.route('/api/v1/ipbans/services/action', methods=['POST'])
    @svc_edit_req
    def api_ipban_service_action():
        """Set a service's block action. Body: ``{service, action}`` — '' clears the
        override (back to the service default); an unsupported action is refused."""
        reg = getattr(wa, '_ipban_services', None)
        data = request.get_json(silent=True) or {}
        service = str(data.get('service', '')).strip()
        action = str(data.get('action', '')).strip()
        if reg is None or not service:
            return jsonify({'error': wa._t('ipban_not_found')}), 400
        if not reg.set_action(service, action):
            return jsonify({'error': wa._t('ipban_not_found')}), 404
        wa._audit('ipban_service_action', detail={'service': service, 'action': action or 'default'})
        return jsonify({'ok': True})

    @app.route('/api/v1/ipbans/banlog', methods=['GET'])
    @hist_view_req
    def api_ipban_banlog():
        """Ban history: every ban / escalation / unban event (audit trail), most recent
        first. ``?ip=…`` filters to one address."""
        mgr = getattr(wa, '_ipban', None)
        if mgr is None:
            return jsonify({'history': []})
        ip = (request.args.get('ip') or '').strip() or None
        return jsonify({'history': mgr.ban_history(limit=500, ip=ip)})

    @app.route('/api/v1/ipbans/history', methods=['GET'])
    @any_view_req
    def api_ipban_history():
        """Recent recorded attempts for an IP (``?ip=…``) — for the detail modal."""
        mgr = getattr(wa, '_ipban', None)
        ip = (request.args.get('ip') or '').strip()
        if mgr is None or not ip:
            return jsonify({'ip': ip, 'history': []})
        return jsonify({'ip': ip, 'history': mgr.history(ip)})

    @app.route('/api/v1/ipbans/action', methods=['POST'])
    @ban_edit_req
    def api_ipban_set_action():
        """Set a per-ban response override. Body: ``{ip, action}`` where action is
        '' (use the global default), 'page', 'minimal' or 'reject'."""
        mgr = getattr(wa, '_ipban', None)
        data = request.get_json(silent=True) or {}
        ip = str(data.get('ip', '')).strip()
        action = str(data.get('action', '')).strip()
        if mgr is None or not ip:
            return jsonify({'error': wa._t('ipban_ip_required')}), 400
        if not mgr.set_block_action(ip, action):
            return jsonify({'error': wa._t('ipban_not_found')}), 404
        return jsonify({'ok': True})

    @app.route('/api/v1/ipbans/clear', methods=['POST'])
    @watch_clear_req
    def api_ipban_clear():
        """Drop an IP from the watchlist (forget its offenses/history). Body: ``{ip}``.
        Does not affect an active ban."""
        mgr = getattr(wa, '_ipban', None)
        ip = str((request.get_json(silent=True) or {}).get('ip', '')).strip()
        if mgr is None or not ip:
            return jsonify({'error': wa._t('ipban_ip_required')}), 400
        cleared = mgr.clear_offenses(ip)
        return jsonify({'ok': True, 'cleared': cleared})

    # ── never-ban whitelist (IP/CIDR + description) ─────────────────────────────
    @app.route('/api/v1/ipbans/whitelist', methods=['GET'])
    @wl_view_req
    def api_ipban_whitelist():
        """The UI-managed never-ban entries (IP/CIDR + description)."""
        store = getattr(wa, '_ip_whitelist_store', None)
        return jsonify({'whitelist': store.list() if store is not None else []})

    @app.route('/api/v1/ipbans/whitelist', methods=['POST'])
    @wl_add_req
    def api_ipban_whitelist_add():
        """Add a never-ban entry.  Body: ``{value, description?}``.  The value is
        validated/normalized as an IP or CIDR."""
        store = getattr(wa, '_ip_whitelist_store', None)
        if store is None:
            return jsonify({'error': 'unavailable'}), 503
        data = request.get_json(silent=True) or {}
        rec = store.add(str(data.get('value', '')),
                        str(data.get('description', ''))[:_MAX_REASON],
                        time.time(), created_by=session.get('username', ''))
        if rec is None:
            return jsonify({'error': wa._t('ipban_wl_invalid')}), 400
        wa._configure_ipban()          # push the new whitelist into the live jail
        wa._audit('ip_whitelist_added', detail={'value': rec['value'],
                                                'description': rec['description']})
        return jsonify({'ok': True, 'entry': rec})

    @app.route('/api/v1/ipbans/whitelist/<uid>', methods=['DELETE'])
    @wl_del_req
    def api_ipban_whitelist_remove(uid):
        """Remove a never-ban entry by its uid."""
        store = getattr(wa, '_ip_whitelist_store', None)
        if store is None or not store.delete(uid):
            return jsonify({'error': wa._t('ipban_not_found')}), 404
        wa._configure_ipban()
        wa._audit('ip_whitelist_removed', detail={'uid': uid})
        return jsonify({'ok': True})

    @app.route('/api/v1/ipbans/<path:ip>', methods=['DELETE'])
    @ban_del_req
    def api_ipban_remove(ip):
        """Lift a ban (and clear the IP's offense history).  A ``reason`` (why it is
        being lifted) may be passed as a query param or JSON body; it is recorded on
        the ban history's ``unbanned`` event."""
        mgr = getattr(wa, '_ipban', None)
        if mgr is None:
            return jsonify({'error': 'unavailable'}), 503
        data = request.get_json(silent=True) or {}
        reason = str(request.args.get('reason') or data.get('reason') or '').strip()[:_MAX_REASON]
        removed = mgr.unban(ip, by=session.get('username', 'admin'), reason=reason or None)
        if not removed:
            return jsonify({'error': wa._t('ipban_not_found')}), 404
        return jsonify({'ok': True})
