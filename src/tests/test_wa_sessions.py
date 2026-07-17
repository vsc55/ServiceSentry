#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for server-side session registry and management."""

import uuid

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── Session registry ─────────────────────

class TestSessionRegistry:
    """Server-side session tracking and management."""

    def test_session_created_on_login(self, admin, client):
        """Login creates an entry in the server-side sessions dict."""
        assert len(admin._sessions) == 0
        _login(client)
        assert len(admin._sessions) == 1

    def test_session_token_in_flask_session(self, client):
        """Login stores a session_token and session_id in Flask's session."""
        _login(client)
        with client.session_transaction() as s:
            assert 'session_token' in s
            assert len(s['session_token']) == 64  # hex(32) — the secret credential
            assert 'session_id' in s
            # Public session id is a uuid4 (matches user/host/role/… uids)
            assert uuid.UUID(s['session_id']).version == 4

    def test_session_records_user_uid(self, admin, client):
        """Session entry contains the logged-in user's UID (not username)."""
        _login(client)
        entry    = list(admin._sessions.values())[0]
        expected = admin._users['admin'].get('uid', '')
        assert entry['user_uid'] == expected
        assert 'username' not in entry

    def test_session_removed_on_logout(self, admin, client):
        """Logout removes the session from the registry."""
        _login(client)
        assert len(admin._sessions) == 1
        client.post("/logout")
        assert len(admin._sessions) == 0

    def test_session_invalid_after_revocation(self, admin, client):
        """Revoking all sessions invalidates the cookie."""
        _login(client)
        assert client.get("/api/v1/me").status_code == 200
        admin._revoke_all_sessions()
        resp = client.get("/api/v1/me", follow_redirects=False)
        assert resp.status_code == 401

    def test_revoke_user_sessions(self, admin, client):
        """_revoke_user_sessions removes only the target user's sessions."""
        import uuid as _uuid
        _login(client)
        # Add a real user + fake session for them
        other_uid = str(_uuid.uuid4())
        admin._users['other'] = {'uid': other_uid, 'role': '', 'display_name': 'Other',
                                  'password_hash': '', 'enabled': True}
        admin._sessions['fake'] = {
            'uid': 'fakeuid', 'user_uid': other_uid,
            'created': '', 'last_seen': '', 'ip': '', 'user_agent': '',
        }
        assert len(admin._sessions) == 2
        removed = admin._revoke_user_sessions('other')
        assert removed == 1
        assert len(admin._sessions) == 1

    def test_sessions_persisted_to_db(self, admin, client):
        """Sessions are stored in the columnar sessions table after login."""
        _login(client)
        assert admin._sessions_store.count() == 1
        rows     = admin._sessions_store.load()
        token    = next(iter(rows))
        expected = admin._users['admin'].get('uid', '')
        assert rows[token]['user_uid'] == expected

    def test_api_get_sessions(self, client):
        """GET /api/sessions returns sessions keyed by uid with is_current flag."""
        _login(client)
        resp = client.get("/api/v1/sessions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        entry = list(data.values())[0]
        assert entry['is_current'] is True
        assert 'username' in entry
        # Full token must not appear in any value
        with client.session_transaction() as s:
            token = s['session_token']
        assert token not in data  # token is not a key
        for v in data.values():
            assert token not in str(v)

    def test_api_revoke_session(self, admin, client):
        """POST /api/sessions/revoke/<uid> removes that session."""
        _login(client)
        # uid comes from the entry's 'uid' field, not the token key
        token = list(admin._sessions.keys())[0]
        uid = admin._sessions[token]['uid']
        resp = client.post(f"/api/v1/sessions/revoke/{uid}",
                           content_type="application/json", data="{}")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert token not in admin._sessions

    def test_api_revoke_session_404(self, client):
        """Revoking a non-existent session returns 404."""
        _login(client)
        resp = client.post("/api/v1/sessions/revoke/nonexistent",
                           content_type="application/json", data="{}")
        assert resp.status_code == 404

    def test_api_revoke_user_sessions(self, admin, client):
        """POST /api/sessions/revoke-user/<user> removes user sessions."""
        import uuid as _uuid
        _login(client)
        victim_uid = str(_uuid.uuid4())
        admin._users['victim'] = {'uid': victim_uid, 'role': '', 'display_name': 'Victim',
                                   'password_hash': '', 'enabled': True}
        admin._sessions['fake'] = {
            'uid': 'fakeuid2', 'user_uid': victim_uid,
            'created': '', 'last_seen': '', 'ip': '', 'user_agent': '',
        }
        resp = client.post("/api/v1/sessions/revoke-user/victim",
                           content_type="application/json", data="{}")
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 1
        assert 'fake' not in admin._sessions
        # Admin session still present
        assert len(admin._sessions) == 1

    def test_sessions_api_admin_only(self, admin, client):
        """Non-admin users without sessions_revoke cannot invalidate sessions, but viewer can view."""
        admin._users["viewer1"] = {
            "password_hash": generate_password_hash("v"),
            "role": "viewer", "display_name": "V",
        }
        _login(client, "viewer1", "v")
        assert client.get("/api/v1/sessions").status_code == 200  # viewer has sessions_view
        assert client.post("/api/v1/sessions/invalidate",
                           content_type="application/json",
                           data="{}").status_code == 403

    def test_invalidate_all_sessions(self, admin, client):
        """POST /api/sessions/invalidate clears all sessions."""
        _login(client)
        assert len(admin._sessions) == 1
        resp = client.post("/api/v1/sessions/invalidate",
                           content_type="application/json", data="{}")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert len(admin._sessions) == 0

    def test_close_all_sessions_button_in_ui(self, client):
        """Users tab has the close-all-sessions button."""
        _login(client)
        html = client.get("/admin").data
        assert b'invalidateAllSessions()' in html
        assert b'session_close_all' in html

    def test_sessions_panel_in_ui(self, client):
        """Users tab contains the sessions panel."""
        _login(client)
        html = client.get("/admin").data
        assert b'sessions-container' in html
        assert b'renderSessions' in html

    def test_per_user_revoke_button_in_ui(self, client):
        """Users tab has the per-user revoke button."""
        _login(client)
        html = client.get("/admin").data
        assert b'revokeUserSessions' in html

    def test_session_ip_change_audited(self, admin, client):
        """A request from a different IP than the session was created with emits session_ip_changed."""
        _login(client)
        # Overwrite recorded IP to simulate a different origin
        token = list(admin._sessions.keys())[0]
        admin._sessions[token]['ip'] = '10.0.0.1'
        # Make any authenticated request — triggers _check_session
        resp = client.get("/api/v1/me")
        assert resp.status_code == 200
        events = [e['event'] for e in admin._audit_log]
        assert 'session_ip_changed' in events
        entry = next(e for e in admin._audit_log if e['event'] == 'session_ip_changed')
        assert entry['detail']['previous_ip'] == '10.0.0.1'

    def test_session_same_ip_not_audited(self, admin, client):
        """No audit event when the IP stays the same between requests."""
        _login(client)
        resp = client.get("/api/v1/me")
        assert resp.status_code == 200
        events = [e['event'] for e in admin._audit_log]
        assert 'session_ip_changed' not in events
