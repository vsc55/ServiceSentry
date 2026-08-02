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
        client.post("/logout")
        events = [e['event'] for e in admin._audit_log]
        assert 'logout' in events

    def test_modules_save_audited(self, admin, client):
        """Saving modules logs the specific field changes."""
        _login(client)
        client.put("/api/v1/modules", json={"ping": {"enabled": False, "threads": 5}})
        entry = [e for e in admin._audit_log if e['event'] == 'modules_saved'][-1]
        assert isinstance(entry['detail'], list)
        assert any(c['field'] == 'ping.enabled' for c in entry['detail'])

    def test_a_save_that_changed_nothing_is_not_audited(self, admin, client):
        """Reported while chasing a phantom "Modules saved" entry: a PUT that stores what was
        already there is a no-op, and an entry with nothing under it is worse than none. The
        audit answers "what changed and when"; a row that answers "nothing" still costs a
        click to discover that, and invites the reading that a change was made and lost."""
        _login(client)
        payload = {"ping": {"enabled": False, "threads": 5}}
        client.put("/api/v1/modules", json=payload)
        before = len([e for e in admin._audit_log if e['event'] == 'modules_saved'])
        client.put("/api/v1/modules", json=payload)          # byte-for-byte the same
        after = len([e for e in admin._audit_log if e['event'] == 'modules_saved'])
        assert after == before, 'a no-op save wrote an audit entry with no changes in it'

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
        assert 'session_all_revoked' in events

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
        html = client.get("/admin").data
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



class TestEveryAuditedEventHasAName:
    """An event with no label renders in the audit screen as its raw identifier.

    Found while adding a prefix to the maintenance events: `ipban_history_cleared` had no
    label at all, and it was not alone — six events were shipping as bare snake_case. Nothing
    was checking, and they read fine in code; it is only on the screen an operator opens
    after an incident that they are unreadable.

    Scanned from the CALLS rather than from a list, because a list is the thing that goes
    stale: the events are written by ~30 modules and the next one added will not think to
    register itself anywhere.
    """

    @staticmethod
    def _events_used():
        import glob
        import io
        import os
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        used = set()
        for path in glob.glob(os.path.join(root, 'lib', '**', '*.py'), recursive=True):
            body = io.open(path, encoding='utf-8', errors='replace').read()
            used |= set(re.findall(r"_audit(?:_system|_auto)?\(\s*'([a-z0-9_]+)'", body))
        return used

    def test_the_scan_finds_the_events(self):
        """A guard over a parser that matches nothing passes for ever."""
        assert len(self._events_used()) >= 100

    def test_every_event_is_labelled_in_both_languages(self):
        from lib.i18n.lang import en_EN, es_ES
        for name, table in (('es_ES', es_ES.LANG), ('en_EN', en_EN.LANG)):
            catalog = table['audit_events']
            missing = sorted(e for e in self._events_used() if not catalog.get(e))
            assert not missing, f'{name} shows these as raw identifiers: {missing}'

    def test_the_labels_say_which_area_they_came_from(self):
        """Two hundred entries in one list: without a prefix naming the subsystem, filtering
        by eye is reading every row. One read simply "Estado borrado" — neither the area nor
        what it was the state OF."""
        from lib.i18n.lang import es_ES
        catalog = es_ES.LANG['audit_events']
        bare = sorted(k for k, v in catalog.items() if ':' not in v)
        assert not bare, f'audit labels with no area prefix: {bare}'


class TestEverySeverityIsDeclaredNotGuessed:
    """What an audit event MEANS is declared by the package that writes it.

    The badge — the only thing a glance down two hundred rows gives you — used to be worked
    out from the event NAME: a rule matching `deleted`/`revoked` plus a handful of names
    written out by hand. Two things were wrong with that, and only the first was visible:
    seven destructive events and fifteen failures rendered neutral grey (three of them
    security signals, plus `internal_error`, the entry written when the panel crashed); and
    even with the word lists widened, the colour still depended on the noun somebody chose.
    `purge_done` would have slipped through; `rule_failed` would have gone red for a rule
    that merely reported "no match".

    Same shape and same discovery as NOTIFY_EVENTS and MODULE_PERMISSIONS, so a package that
    adds an event declares it where the code that emits it lives.
    """

    @staticmethod
    def _emitted():
        import glob
        import io as _io
        import os as _os
        import re as _re
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        used = set()
        for path in glob.glob(_os.path.join(root, 'lib', '**', '*.py'), recursive=True):
            body = _io.open(path, encoding='utf-8', errors='replace').read()
            used |= set(_re.findall(r"_audit(?:_system|_auto)?\(\s*'([a-z0-9_]+)'", body))
        return used

    def test_every_emitted_event_declares_its_severity(self):
        """The check that makes the next event impossible to forget: emit one without
        declaring it and the build fails here, not in a grey badge nobody notices."""
        from lib.core.audit.events import audit_severity
        missing = sorted(self._emitted() - set(audit_severity()))
        assert not missing, f'emitted with no declared severity: {missing}'

    def test_every_LABELLED_event_declares_one_too(self):
        """The scan above reads literals, so it cannot see an event emitted through a
        variable — `wa._audit(event, …)` in the maintenance endpoint is exactly that, and
        `db_optimized`/`db_compacted` slipped past it.

        The i18n catalog is the second list, and a complete one: every event needs a label to
        render, and a guard already enforces that. Crossing the two closes the blind spot
        without asking anyone to remember it."""
        from lib.core.audit.events import audit_severity
        from lib.i18n.lang import es_ES
        declared = set(audit_severity())
        missing = sorted(e for e in es_ES.LANG['audit_events'] if e not in declared)
        assert not missing, f'labelled but no declared severity: {missing}'

    def test_nothing_is_declared_that_nobody_emits(self):
        """The rot that lasts longest: a declaration for an event that no longer exists,
        because nobody greps for a name that is gone.

        Checked against the literals AND the label catalog, since an event emitted through a
        variable is invisible to the scan but always has a label — without that union this
        would report the maintenance events as dead the moment they were declared."""
        from lib.core.audit.events import audit_severity
        from lib.i18n.lang import es_ES
        known = self._emitted() | set(es_ES.LANG['audit_events'])
        stale = sorted(set(audit_severity()) - known)
        assert not stale, f'declared but never emitted: {stale}'

    def test_each_event_is_declared_exactly_once(self):
        """Two packages declaring the same event is not harmless: the dict keeps whichever
        was scanned last, so the two can disagree and the winner is decided by import order —
        a difference nobody would think to look for.

        It happened while regrouping: `entra_oidc_secret_rotated` sat in both the audit domain
        and the Entra provider, `msteams_sso_*` in both notify and Entra. They agreed on the
        severity, which is exactly why it would have gone unnoticed until they did not.
        """
        import collections
        from lib.discovery import scan
        where = collections.defaultdict(list)
        for pkg, values in scan('AUDIT_EVENTS'):
            for value in values:
                where[value['key']].append(pkg)
        dupes = {k: v for k, v in where.items() if len(v) > 1}
        assert not dupes, f'declared in more than one package: {dupes}'

    def test_events_are_declared_by_the_package_that_writes_them(self):
        """The point of declaring them at all. They were first written into whichever
        manifest existed, which put SCIM, Teams, webhooks and the login events in the audit
        domain's file — a central list wearing a per-package shape, and the thing that goes
        stale the moment a module changes.

        The audit domain keeps only its own two plus the ones no package owns: the request
        lifecycle's (login, csrf, the crash handler), which `lib.web_admin` cannot declare
        because it is not a discovery root, and a couple raised from `lib/util`.
        """
        from lib.discovery import scan
        by_pkg = {pkg: {v['key'] for v in vals} for pkg, vals in scan('AUDIT_EVENTS')}
        for pkg, prefix in (('scim', 'scim_'), ('syslog', 'syslog_'),
                            ('entraid', 'entra_'), ('ipban', 'ip')):
            owned = {k for k in by_pkg.get(pkg, ()) if k.startswith(prefix)}
            assert owned, f'{pkg} declares none of its own {prefix}* events'
            elsewhere = {k for other, keys in by_pkg.items() if other != pkg
                         for k in keys if k.startswith(prefix)}
            assert not elsewhere, f'{prefix}* events declared outside {pkg}: {elsewhere}'
        assert len(by_pkg) >= 18, f'only {len(by_pkg)} packages declare events'

    def test_the_discovery_found_them(self):
        """A scan that silently matches nothing passes for ever."""
        from lib.core.audit.events import audit_severity
        assert len(audit_severity()) >= 100

    def test_only_known_severities_survive(self):
        """An unknown severity reaches the browser as a CSS class that does not exist, and the
        row renders with NO badge — worse than the wrong colour, because it reads as an event
        that carries no weight at all. Dropped at the door instead."""
        from lib.core.audit.events import VALID_SEVERITIES, _normalize, audit_severity
        assert set(audit_severity().values()) <= VALID_SEVERITIES
        assert _normalize({'key': 'x', 'severity': 'chartreuse'}) is None
        assert _normalize({'key': '', 'severity': 'danger'}) is None
        assert _normalize({'key': 'x', 'severity': 'danger'}) == {'key': 'x',
                                                                  'severity': 'danger'}

    def test_the_badge_reads_the_declaration_and_nothing_else(self):
        """No substring rules left in the renderer — that is the whole point."""
        import io as _io
        import os as _os
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        body = _io.open(_os.path.join(root, 'lib', 'web_admin', 'templates', 'partials',
                                      'audit', '_filters.html'), encoding='utf-8').read()
        fn = body[body.index('function _auditEventBadge'):]
        fn = fn[:fn.index('\n}')]
        assert 'AUDIT_SEVERITY[event]' in fn
        for guessy in ('includes(', "=== 'login", '_AUDIT_DESTRUCTIVE', '_AUDIT_FAILURE'):
            assert guessy not in fn, f'the badge is guessing again: {guessy}'

    def test_the_ones_that_started_this_are_right(self):
        """The reports, in order: "Estado De Checks Borrado" grey, then "Error Interno" grey."""
        from lib.core.audit.events import audit_severity
        sev = audit_severity()
        for event in ('status_cleared', 'internal_error', 'csrf_failed', 'scim_auth_failed',
                      'audit_cleared', 'syslog_cleared', 'ipban_history_cleared'):
            assert sev[event] == 'danger', f'{event} is {sev[event]}'
        # …and the two that must NOT be alarming: they reclaim space and change no row.
        for event in ('db_optimized', 'db_compacted'):
            assert sev[event] == 'muted', f'{event} is {sev[event]}'


class TestAnEntryAlwaysNamesWhoCausedIt:
    """Reported from the audit screen: a SCIM auth failure showed an empty USER column, with
    a suggestion that it should say `system`.

    It should not. `system` means the panel acted on its own — a service starting, a scheduled
    prune — and an intrusion attempt filed under it reads as the panel doing this to itself,
    in the one filter these entries are most often looked up by. Blank is no better: an empty
    cell reads as a missing value rather than as "there was no identity to record".
    """

    def test_the_scim_failure_names_an_anonymous_caller(self):
        from lib.core.constants import ANONYMOUS_USER, SYSTEM_USER
        import io as _io
        import os as _os
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        body = _io.open(_os.path.join(root, 'lib', 'providers', 'scim', 'routes.py'),
                        encoding='utf-8').read()
        assert "username=ANONYMOUS_USER" in body
        assert "username=''" not in body, 'an audit entry with no actor at all'
        assert ANONYMOUS_USER != SYSTEM_USER

    def test_no_audit_entry_is_written_with_a_blank_actor(self):
        """The one that existed was the only one; the guard is what keeps it that way."""
        import glob
        import io as _io
        import os as _os
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        offenders = []
        for path in glob.glob(_os.path.join(root, 'lib', '**', '*.py'), recursive=True):
            body = _io.open(path, encoding='utf-8', errors='replace').read()
            if "username=''" in body and '_audit' in body:
                offenders.append(_os.path.basename(path))
        assert not offenders, f'audit calls with an empty username: {offenders}'

    def test_both_audit_identities_are_reserved_usernames(self):
        """An account able to take either name would have its actions read as the panel's own
        or as an unauthenticated caller's, and "who did this" stops being answerable."""
        import pytest as _pytest
        from lib.core.constants import ANONYMOUS_USER, SYSTEM_USER
        from lib.core.users.service import AdminOpError, PasswordPolicy, create_user
        policy = PasswordPolicy()
        for reserved in (SYSTEM_USER, ANONYMOUS_USER, 'SYSTEM', 'Anonymous'):
            with _pytest.raises(AdminOpError) as exc:
                create_user({}, username=reserved, password='irrelevant-password',
                            policy=policy, custom_roles={}, groups={})
            assert exc.value.key == 'username_reserved', reserved
