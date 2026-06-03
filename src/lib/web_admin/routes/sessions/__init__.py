#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session management routes: /api/v1/sessions, /api/v1/sessions/invalidate,
/api/v1/sessions/revoke/<sid>, /api/v1/sessions/revoke-user/<username>."""

from flask import jsonify, session


def register(app, wa):
    sessions_view_req   = wa._perm_required('sessions_view')
    sessions_revoke_req = wa._perm_required('sessions_revoke')

    def _is_admin_requester() -> bool:
        admin_uid = wa._role_name_to_uid('admin')
        user = wa._users.get(session.get('username', '')) or {}
        return user.get('role', '') == admin_uid

    # --- API: sessions (admin only) --------------------------------

    @app.route('/api/v1/sessions', methods=['GET'])
    @sessions_view_req
    def api_get_sessions():
        """Return all active sessions (keyed by sid, token never exposed)."""
        current_token = session.get('session_token')
        # Build uid→username reverse map once
        uid_to_name = {d.get('uid', ''): u for u, d in wa._users.items()}
        result = {}
        for token, entry in wa._sessions.items():
            sid      = entry.get('sid') or token[:16]
            user_uid = entry.get('user_uid', '')
            uname    = uid_to_name.get(user_uid, user_uid)
            result[sid] = {
                'username':   uname,
                'user_uid':   user_uid,
                'ip':         entry.get('ip', ''),
                'user_agent': entry.get('user_agent', ''),
                'created':    entry.get('created', ''),
                'last_seen':  entry.get('last_seen', ''),
                'is_current': token == current_token,
            }
        return jsonify(result)

    @app.route('/api/v1/sessions/invalidate', methods=['POST'])
    @sessions_revoke_req
    def api_invalidate_sessions():
        """Revoke ALL active sessions (admin only)."""
        if not _is_admin_requester():
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        count = wa._revoke_all_sessions()
        wa._audit('all_sessions_revoked', detail=str(count))
        session.clear()
        return jsonify({'ok': True, 'count': count})

    @app.route('/api/v1/sessions/revoke/<sid>', methods=['POST'])
    @sessions_revoke_req
    def api_revoke_session_route(sid):
        """Revoke a specific session by its sid.

        Non-admins may only revoke their own sessions.
        """
        entry = next(
            (e for e in wa._sessions.values() if e.get('sid') == sid),
            None,
        )
        if not entry:
            return jsonify({'error': wa._t('session_not_found')}), 404
        # Non-admins can only revoke their own sessions.
        current_uid = (wa._users.get(session.get('username', '')) or {}).get('uid', '')
        if not _is_admin_requester() and entry.get('user_uid') != current_uid:
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        token = next(
            (t for t, e in wa._sessions.items() if e.get('sid') == sid),
            None,
        )
        if token and wa._revoke_session(token):
            wa._audit('session_revoked', detail=sid)
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('session_not_found')}), 404

    @app.route('/api/v1/sessions/revoke-user/<username>', methods=['POST'])
    @sessions_revoke_req
    def api_revoke_user_sessions_route(username):
        """Revoke all sessions for a specific user.

        Non-admins may only revoke their own sessions.
        """
        if not _is_admin_requester() and username != session.get('username'):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        count = wa._revoke_user_sessions(username)
        wa._audit('user_sessions_revoked',
                  detail=f'{username} ({count})')
        if username == session.get('username'):
            session.clear()
        return jsonify({'ok': True, 'count': count})
