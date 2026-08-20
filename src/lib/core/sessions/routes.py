#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session management routes: /api/v1/sessions, /api/v1/sessions/invalidate,
/api/v1/sessions/revoke/<uid>, /api/v1/sessions/revoke-user/<username>.

Routes registered by this file:

    GET    /api/v1/sessions                         Return all active sessions
    GET    /api/v1/sessions/access                  Every recorded request, across sessions
    GET    /api/v1/sessions/<uid>/access            What ONE session has been doing
    POST   /api/v1/sessions/invalidate              Revoke ALL active sessions (admin only)
    POST   /api/v1/sessions/revoke/<uid>            Revoke a specific session by uid
    POST   /api/v1/sessions/revoke-user/<username>  Revoke all sessions for a user

The two activity reads ride ``sessions_view``, the same flag as the list they belong to.
That is deliberate rather than lax: this screen already shows every session in the
installation with its account, its address and its browser, so a separate permission would
be a second answer to a question the panel has already answered once.
"""

from flask import jsonify, session

from lib.core.sessions import service as sessions_svc

# How many rows the cross-session feed answers with. The per-session rings already bound the
# total; this bounds what ONE request carries, because "every request of every session" is a
# table nobody reads past the first screen of and every row past that still crosses the wire.
ACCESS_FEED_MAX = 500


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

    @app.route('/api/v1/sessions/access', methods=['GET'])
    @sessions_view_req
    def api_sessions_access_all():
        """Every recorded request, newest first, across every live session.

        The list says who is signed in. This says what they have been DOING — and it is the
        only place a REFUSED request appears at all: the audit log records the actions that
        have a name, attributed to the account, so a 403 against a page somebody should not
        have reached leaves no trace anywhere else.

        What is recorded is a rule, not everything (see ``_SessionsMixin._hook_session_
        access``): the acts and the refusals. Successful reads are not — the panel polls
        itself several times a minute per open tab, and a feed of heartbeats answers nothing.

        Each row carries the account, resolved here rather than in the browser: it is a lookup
        the server already does for the listing beside it, and two answers to "whose is this"
        is one more than a screen survives. A row whose session is gone is dropped — those
        rows are pruned with the session, so this only ever catches the race.
        """
        view = sessions_svc.build_sessions_view(
            wa._sessions, wa._users, session.get('session_token'))
        out = []
        for row in wa._sessions_store.access_all(ACCESS_FEED_MAX):
            owner = view.get(row.get('session_uid', ''))
            if owner is None:
                continue
            row['username']   = owner.get('username', '')
            row['is_current'] = bool(owner.get('is_current'))
            out.append(row)
        return jsonify({'access': out, 'max': ACCESS_FEED_MAX})

    @app.route('/api/v1/sessions/<uid>/access', methods=['GET'])
    @sessions_view_req
    def api_session_access(uid):
        """One session's recent requests, newest first.

        ``enabled`` travels with them so the dialog can tell "this session has done nothing
        worth recording" from "the recording is switched off" — an empty list reads as the
        first, and an installation that turned it off would look like a session that has never
        acted. It is a field of its own because ``max`` cannot answer it any more: 0 there
        means *no ceiling*, which is the opposite of off.
        """
        if not sessions_svc.find_token_by_uid(wa._sessions, uid):
            return jsonify({'error': wa._t('session_not_found')}), 404
        return jsonify({'access': wa._sessions_store.access_for(uid),
                        'max': int(getattr(wa, '_SESSION_LOG_MAX', 200) or 0),
                        'enabled': bool(getattr(wa, '_SESSION_LOG_ENABLED', True))})

    @app.route('/api/v1/sessions/invalidate', methods=['POST'])
    @sessions_revoke_req
    def api_invalidate_sessions():
        """Revoke ALL active sessions (admin only)."""
        if not wa._is_admin_requester():
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        count = wa._revoke_all_sessions()
        wa._audit('session_all_revoked', detail=str(count))
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
        wa._audit('session_user_revoked',
                  detail={'username': username, 'count': count})
        if username == session.get('username'):
            session.clear()
        return jsonify({'ok': True, 'count': count})
