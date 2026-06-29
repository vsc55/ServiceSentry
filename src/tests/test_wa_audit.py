#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the audit log — recording, persistence and API access."""

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── Audit log ────────────────────────────

class TestAuditLog:
    """Audit log records all relevant events."""

    def test_login_audited(self, admin, client):
        """Successful login creates an audit entry."""
        _login(client)
        events = [e['event'] for e in admin._audit_log]
        assert 'login_ok' in events

    def test_audit_write_failure_is_resilient(self, admin):
        """A failed audit insert must not raise nor permanently stop auditing —
        the next write still records (regression: audits silently stopping)."""
        from unittest.mock import patch
        with patch.object(admin._audit_store, 'insert',
                          side_effect=RuntimeError('database is locked')):
            admin._audit_system('host_tested', detail={'ok': False})  # must NOT raise
        # Auditing recovers on the next write.
        admin._audit_system('host_tested', detail={'ok': True})
        assert any(e['event'] == 'host_tested' for e in admin._audit_log)

    def test_failed_login_audited(self, admin, client):
        """Failed login creates an audit entry."""
        client.post("/login", data={"username": "admin", "password": "wrong"},
                    follow_redirects=True)
        events = [e['event'] for e in admin._audit_log]
        assert 'login_failed' in events

    def test_failed_login_reason_invalid_credentials(self, admin, client):
        """Wrong password records reason=invalid_credentials in audit detail."""
        client.post("/login", data={"username": "admin", "password": "wrong"})
        entry = next(e for e in reversed(admin._audit_log) if e['event'] == 'login_failed')
        assert entry['detail']['reason'] == 'invalid_credentials'

    def test_failed_login_reason_user_not_found(self, admin, client):
        """Non-existent username records reason=user_not_found in audit detail."""
        client.post("/login", data={"username": "nobody", "password": "x"})
        entry = next(e for e in reversed(admin._audit_log) if e['event'] == 'login_failed')
        assert entry['detail']['reason'] == 'user_not_found'

    def test_failed_login_reason_account_disabled(self, admin, client):
        """Disabled account records reason=account_disabled in audit detail."""
        from werkzeug.security import generate_password_hash
        admin._users["locked"] = {
            "password_hash": generate_password_hash("secret", method="pbkdf2:sha256"),
            "role": "viewer",
            "enabled": False,
        }
        client.post("/login", data={"username": "locked", "password": "secret"})
        entry = next(e for e in reversed(admin._audit_log) if e['event'] == 'login_failed')
        assert entry['detail']['reason'] == 'account_disabled'

    def test_logout_audited(self, admin, client):
        """Logout creates an audit entry."""
        _login(client)
        client.get("/logout")
        events = [e['event'] for e in admin._audit_log]
        assert 'logout' in events

    def test_modules_save_audited(self, admin, client):
        """Saving modules logs the specific field changes."""
        _login(client)
        client.put("/api/v1/modules", json={"ping": {"enabled": False, "threads": 5}})
        entry = [e for e in admin._audit_log if e['event'] == 'modules_saved'][-1]
        assert isinstance(entry['detail'], list)
        assert any(c['field'] == 'ping.enabled' for c in entry['detail'])

    def test_config_save_audited(self, admin, client):
        """Saving config logs the specific field changes."""
        _login(client)
        client.put("/api/v1/config", json={"monitoring": {"timer_check": 60}})
        entry = [e for e in admin._audit_log if e['event'] == 'config_saved'][-1]
        assert isinstance(entry['detail'], list)
        assert any(c['field'] == 'monitoring.timer_check' for c in entry['detail'])

    def test_user_create_audited(self, admin, client):
        """Creating a user logs username, role and display_name."""
        _login(client)
        client.post("/api/v1/users", json={
            "username": "auduser", "password": "testpass", "role": "viewer",
        })
        entry = [e for e in admin._audit_log if e['event'] == 'user_created'][-1]
        assert entry['detail']['username'] == 'auduser'
        assert entry['detail']['role'] == 'viewer'

    def test_user_update_audited(self, admin, client):
        """Updating a user logs old and new values per changed field."""
        _login(client)
        client.put("/api/v1/users/admin", json={"display_name": "Boss"})
        entry = [e for e in admin._audit_log if e['event'] == 'user_updated'][-1]
        assert entry['detail']['username'] == 'admin'
        changes = entry['detail']['changes']
        dn_change = [c for c in changes if c['field'] == 'display_name'][0]
        assert dn_change['new'] == 'Boss'

    def test_user_delete_audited(self, admin, client):
        """Deleting a user logs the username."""
        admin._users["delme"] = {
            "password_hash": generate_password_hash("x"),
            "role": "viewer", "display_name": "Del",
        }
        _login(client)
        client.delete("/api/v1/users/delme")
        entry = [e for e in admin._audit_log if e['event'] == 'user_deleted'][-1]
        assert entry['detail']['username'] == 'delme'

    def test_password_change_audited(self, admin, client):
        """Changing own password creates an audit entry."""
        _login(client)
        client.put("/api/v1/users/me/password", json={
            "current_password": "secret", "new_password": "newsecret",
        })
        events = [e['event'] for e in admin._audit_log]
        assert 'password_changed' in events

    def test_all_sessions_revoked_audited(self, admin, client):
        """Invalidating all sessions creates an audit entry."""
        _login(client)
        client.post("/api/v1/sessions/invalidate",
                    content_type="application/json", data="{}")
        events = [e['event'] for e in admin._audit_log]
        assert 'all_sessions_revoked' in events

    def test_audit_api_returns_entries(self, admin, client):
        """GET /api/audit returns the audit log."""
        _login(client)
        resp = client.get("/api/v1/audit")
        assert resp.status_code == 200
        entries = resp.get_json()
        assert isinstance(entries, list)
        assert len(entries) >= 1
        assert entries[0]['event'] == 'login_ok'  # most recent first

    def test_audit_api_viewer_can_read_but_not_delete(self, admin, client):
        """Viewer can GET /api/audit (has audit_view) but cannot DELETE."""
        admin._users["viewer1"] = {
            "password_hash": generate_password_hash("v"),
            "role": "viewer", "display_name": "V",
        }
        _login(client, "viewer1", "v")
        assert client.get("/api/v1/audit").status_code == 200
        assert client.delete("/api/v1/audit").status_code == 403

    def test_audit_persisted_to_db(self, admin, client):
        """Audit log is written to the SQLite database, not a JSON file."""
        _login(client)
        # Audit store should have at least the login_ok entry
        assert admin._audit_store.count() >= 1
        entries = admin._audit_store.get_all()
        assert any(e['event'] == 'login_ok' for e in entries)

    def test_audit_max_entries(self, admin):
        """Audit log is capped to _AUDIT_MAX_ENTRIES when inserting via _audit_system."""
        admin._AUDIT_MAX_ENTRIES = 5
        admin._audit_store.delete_all()
        for i in range(10):
            admin._audit_system(f'test_{i}')
        assert admin._audit_store.count() == 5

    def test_audit_unlimited_when_zero(self, admin):
        """Audit log keeps all entries when _AUDIT_MAX_ENTRIES is 0."""
        admin._AUDIT_MAX_ENTRIES = 0
        admin._audit_store.delete_all()
        for i in range(20):
            admin._audit_system(f'test_{i}')
        assert admin._audit_store.count() == 20

    def test_audit_tab_in_ui(self, client):
        """Dashboard has the audit tab for admins."""
        _login(client)
        html = client.get("/").data
        assert b'tab-audit' in html
        assert b'renderAudit' in html

    def test_audit_entry_has_required_fields(self, admin, client):
        """Each audit entry has ts, event, user, ip, detail."""
        _login(client)
        entry = admin._audit_log[-1]
        for field in ('ts', 'event', 'user', 'ip', 'detail'):
            assert field in entry

    def test_admin_password_reset_audited(self, admin, client):
        """Admin resetting a user password logs a 'password_reset' event."""
        admin._users["pwuser"] = {
            "password_hash": generate_password_hash("old"),
            "role": "viewer", "display_name": "PW",
        }
        _login(client)
        client.put("/api/v1/users/pwuser", json={"password": "newpass1"})
        events = [e['event'] for e in admin._audit_log]
        assert 'password_reset' in events
        entry = [e for e in admin._audit_log if e['event'] == 'password_reset'][-1]
        assert entry['detail'] == {'username': 'pwuser'}

    def test_password_reset_separate_from_update(self, admin, client):
        """Changing role + password creates both user_updated and password_reset."""
        admin._users["both"] = {
            "password_hash": generate_password_hash("x"),
            "role": "viewer", "display_name": "B",
        }
        _login(client)
        client.put("/api/v1/users/both", json={
            "role": "editor", "password": "newpass1",
        })
        events = [e['event'] for e in admin._audit_log]
        assert 'user_updated' in events
        assert 'password_reset' in events
        upd = [e for e in admin._audit_log if e['event'] == 'user_updated'][-1]
        assert any(c['field'] == 'role' and c['old'] == 'viewer'
                   and c['new'] == 'editor' for c in upd['detail']['changes'])

    def test_config_save_records_old_and_new(self, admin, client):
        """Config change detail includes old and new values."""
        _login(client)
        client.put("/api/v1/config", json={"monitoring": {"timer_check": 99}})
        entry = [e for e in admin._audit_log if e['event'] == 'config_saved'][-1]
        change = [c for c in entry['detail']
                  if c['field'] == 'monitoring.timer_check'][0]
        assert change['old'] == 300  # original fixture value
        assert change['new'] == 99

    def test_sensitive_fields_masked_in_audit(self, admin, client):
        """Sensitive fields (token, password) are masked in config audit."""
        _login(client)
        client.put("/api/v1/config", json={
            "monitoring": {"timer_check": 300},
            "global": {"log_level": "off"},
            "telegram": {
                "token": "CHANGED-TOKEN",
                "chat_id": "12345",
                "group_messages": False,
            },
        })
        entry = [e for e in admin._audit_log if e['event'] == 'config_saved'][-1]
        if entry['detail']:  # there should be a token change
            token_changes = [c for c in entry['detail']
                             if 'token' in c['field']]
            for c in token_changes:
                assert c['old'] == '***'
                assert c['new'] == '***'

    def test_no_update_audit_when_no_changes(self, admin, client):
        """Updating a user with same values does not emit user_updated."""
        _login(client)
        before = len(admin._audit_log)
        client.put("/api/v1/users/admin", json={
            "role": "admin",
            "display_name": admin._users["admin"].get("display_name", "admin"),
        })
        update_entries = [e for e in admin._audit_log[before:]
                         if e['event'] == 'user_updated']
        assert len(update_entries) == 0

    def test_diff_dicts_helper(self, admin):
        """_diff_dicts correctly identifies changed fields."""
        old = {'a': 1, 'b': {'c': 2, 'd': 3}}
        new = {'a': 1, 'b': {'c': 9, 'd': 3}, 'e': 5}
        changes = WebAdmin._diff_dicts(old, new)
        fields = {c['field'] for c in changes}
        assert 'b.c' in fields
        assert 'e' in fields
        assert 'a' not in fields
        bc = [c for c in changes if c['field'] == 'b.c'][0]
        assert bc['old'] == 2
        assert bc['new'] == 9

    # ── DELETE /api/audit (clear all) ─────────────────────────────

    def test_clear_all_entries(self, admin, client):
        """DELETE /api/audit removes previous entries; only the audit_cleared event remains."""
        _login(client)
        assert len(admin._audit_log) >= 1
        resp = client.delete("/api/v1/audit")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        # The log is not empty: the clear operation itself is recorded as the first entry
        assert len(admin._audit_log) == 1
        assert admin._audit_log[0]['event'] == 'audit_cleared'

    def test_clear_all_persisted_to_db(self, admin, client):
        """After DELETE /api/audit the DB contains only the audit_cleared entry."""
        _login(client)
        client.delete("/api/v1/audit")
        entries = admin._audit_store.get_all()
        assert len(entries) == 1
        assert entries[0]['event'] == 'audit_cleared'

    # ── DELETE /api/audit/<idx> (single entry) ────────────────────

    def test_delete_single_entry(self, admin, client):
        """DELETE /api/audit/<id> removes the entry with that DB id."""
        admin._audit_store.delete_all()
        admin._audit_store.insert('a', 'evt_0', '', '', '')
        admin._audit_store.insert('b', 'evt_1', '', '', '')
        admin._audit_store.insert('c', 'evt_2', '', '', '')
        _login(client)
        # Get the DB id of evt_0 (oldest entry)
        entries = admin._audit_store.get_all(newest_first=False)
        target_id = next(e['_id'] for e in entries if e['event'] == 'evt_0')
        resp = client.delete(f"/api/v1/audit/{target_id}")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        remaining = [e['event'] for e in admin._audit_log
                     if e['event'].startswith('evt_')]
        assert 'evt_0' not in remaining
        assert 'evt_1' in remaining
        assert 'evt_2' in remaining

    def test_delete_single_entry_oob(self, admin, client):
        """DELETE /api/audit/<idx> returns 404 for an out-of-range index."""
        _login(client)
        resp = client.delete("/api/v1/audit/9999")
        assert resp.status_code == 404

    def test_delete_single_entry_negative(self, admin, client):
        """Negative index is out-of-range → 404."""
        _login(client)
        # Flask converts /<int:idx> so -1 does not match the route; expect 404
        resp = client.delete("/api/v1/audit/-1")
        assert resp.status_code == 404

    def test_delete_single_entry_viewer_forbidden(self, admin, client):
        """Viewer cannot delete a single audit entry."""
        admin._users["viewer2"] = {
            "password_hash": generate_password_hash("v"),
            "role": "viewer", "display_name": "V2",
        }
        admin._audit_store.insert('x', 'sentinel', '', '', '')
        entries = admin._audit_store.get_all()
        sentinel_id = next(e['_id'] for e in entries if e['event'] == 'sentinel')
        _login(client, "viewer2", "v")
        resp = client.delete(f"/api/v1/audit/{sentinel_id}")
        assert resp.status_code == 403

    def test_delete_single_entry_persisted(self, admin, client):
        """After DELETE /api/audit/<id> the DB reflects the change."""
        admin._audit_store.delete_all()
        admin._audit_store.insert('t1', 'keep', '', '', '')
        admin._audit_store.insert('t2', 'remove', '', '', '')
        entries = admin._audit_store.get_all(newest_first=False)
        remove_id = next(e['_id'] for e in entries if e['event'] == 'remove')
        _login(client)
        resp = client.delete(f"/api/v1/audit/{remove_id}")
        assert resp.status_code == 200
        remaining_events = [e['event'] for e in admin._audit_store.get_all()]
        assert 'remove' not in remaining_events
        assert 'keep' in remaining_events

