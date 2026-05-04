#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session management routes: /api/sessions, /api/sessions/invalidate,
/api/sessions/revoke/<sid>, /api/sessions/revoke-user/<username>."""

from flask import jsonify, session


def register(app, wa):
    sessions_view_req   = wa._perm_required('sessions_view')
    sessions_revoke_req = wa._perm_required('sessions_revoke')

    # --- API: sessions (admin only) --------------------------------

    @app.route('/api/sessions', methods=['GET'])
    @sessions_view_req
    def api_get_sessions():
        """Return all active sessions (keyed by sid, token never exposed)."""
        current_token = session.get('session_token')
        result = {}
        for token, entry in wa._sessions.items():
            sid = entry.get('sid') or token[:16]
            result[sid] = {
                'username': entry.get('username', ''),
                'ip': entry.get('ip', ''),
                'user_agent': entry.get('user_agent', ''),
                'created': entry.get('created', ''),
                'last_seen': entry.get('last_seen', ''),
                'is_current': token == current_token,
            }
        return jsonify(result)

    @app.route('/api/sessions/invalidate', methods=['POST'])
    @sessions_revoke_req
    def api_invalidate_sessions():
        """Revoke ALL active sessions."""
        count = wa._revoke_all_sessions()
        wa._audit('all_sessions_revoked', detail=str(count))
        session.clear()
        return jsonify({'ok': True, 'count': count})

    @app.route('/api/sessions/revoke/<sid>', methods=['POST'])
    @sessions_revoke_req
    def api_revoke_session_route(sid):
        """Revoke a specific session by its sid."""
        token = next(
            (t for t, e in wa._sessions.items() if e.get('sid') == sid),
            None,
        )
        if token and wa._revoke_session(token):
            wa._audit('session_revoked', detail=sid)
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('session_not_found')}), 404

    @app.route('/api/sessions/revoke-user/<username>', methods=['POST'])
    @sessions_revoke_req
    def api_revoke_user_sessions_route(username):
        """Revoke all sessions for a specific user."""
        count = wa._revoke_user_sessions(username)
        wa._audit('user_sessions_revoked',
                  detail=f'{username} ({count})')
        if username == session.get('username'):
            session.clear()
        return jsonify({'ok': True, 'count': count})
