#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session management routes: /api/v1/sessions, /api/v1/sessions/invalidate,
/api/v1/sessions/revoke/<uid>, /api/v1/sessions/revoke-user/<username>.

Routes registered by this file:

    GET    /api/v1/sessions                         Return all active sessions
    POST   /api/v1/sessions/invalidate              Revoke ALL active sessions (admin only)
    POST   /api/v1/sessions/revoke/<uid>            Revoke a specific session by uid
    POST   /api/v1/sessions/revoke-user/<username>  Revoke all sessions for a user
"""

from flask import jsonify, session

from lib.core.sessions import service as sessions_svc


def register(app, wa):
    sessions_view_req   = wa._perm_required('sessions_view')
    sessions_revoke_req = wa._perm_required('sessions_revoke')

    # --- API: sessions (admin only) --------------------------------

    @app.route('/api/v1/sessions', methods=['GET'])
    @sessions_view_req
    def api_get_sessions():
        """Return all active sessions (keyed by uid, token never exposed)."""
        current_token = session.get('session_token')
        return jsonify(sessions_svc.build_sessions_view(
            wa._sessions, wa._users, current_token))

    @app.route('/api/v1/sessions/invalidate', methods=['POST'])
    @sessions_revoke_req
    def api_invalidate_sessions():
        """Revoke ALL active sessions (admin only)."""
        if not wa._is_admin_requester():
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        count = wa._revoke_all_sessions()
        wa._audit('all_sessions_revoked', detail=str(count))
        session.clear()
        return jsonify({'ok': True, 'count': count})

    @app.route('/api/v1/sessions/revoke/<uid>', methods=['POST'])
    @sessions_revoke_req
    def api_revoke_session_route(uid):
        """Revoke a specific session by its uid.

        Non-admins may only revoke their own sessions.
        """
        token = sessions_svc.find_token_by_uid(wa._sessions, uid)
        entry = wa._sessions.get(token) if token else None
        if not entry:
            return jsonify({'error': wa._t('session_not_found')}), 404
        # Non-admins can only revoke their own sessions.
        current_uid = (wa._users.get(session.get('username', '')) or {}).get('uid', '')
        if not wa._is_admin_requester() and entry.get('user_uid') != current_uid:
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        if wa._revoke_session_by_uid(uid):   # delete by uid (the PK), not the token
            # Resolve the session owner's username for the audit trail.
            _owner = sessions_svc.owner_username(wa._users, entry.get('user_uid'))
            wa._audit('session_revoked', detail={
                'session_uid': uid, 'username': _owner,
                'ip': entry.get('ip', ''),
            })
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('session_not_found')}), 404

    @app.route('/api/v1/sessions/revoke-user/<username>', methods=['POST'])
    @sessions_revoke_req
    def api_revoke_user_sessions_route(username):
        """Revoke all sessions for a specific user.

        Non-admins may only revoke their own sessions.
        """
        if not wa._is_admin_requester() and username != session.get('username'):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        count = wa._revoke_user_sessions(username)
        wa._audit('user_sessions_revoked',
                  detail={'username': username, 'count': count})
        if username == session.get('username'):
            session.clear()
        return jsonify({'ok': True, 'count': count})
