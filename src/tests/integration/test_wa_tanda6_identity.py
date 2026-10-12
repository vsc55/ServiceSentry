#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Identity holes of the 2026-10-12 audit's sixth batch, through the app — each pinned.

The built-in *editor* and *viewer* roles were grantable by anyone with ``users_edit`` (or
``groups_add``), whatever the granter held; ``config_edit`` could set the SCIM token and default
role, one PATCH away from admin; SCIM deleted or disabled the last administrator; a password
change said nothing about the API tokens it leaves working; the bootstrap administrator kept
the built-in default password with nothing forcing it out; a WebAuthn sign-in challenge lived
only in the cookie, so a copy of it was a second session; and the per-account second-factor
limit looked before it counted.
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest.mock

import pytest

from tests.conftest import _login, _login_as                        # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _roles():
    from lib.core.constants import BUILTIN_ROLE_UIDS                 # noqa: PLC0415
    return BUILTIN_ROLE_UIDS


# ── IDN-1 ─────────────────────────────────────────────────────────────────────
class TestBuiltinRolesAreJudgedByWhatTheyCarry:

    def test_users_edit_cannot_self_promote_to_editor(self, admin):
        c = _login_as(admin, 'helpdesk', perms=['users_view', 'users_edit'])
        r = c.put('/api/v1/users/helpdesk', json={'role': _roles()['editor']})
        assert r.status_code == 403
        assert 'config_edit' not in admin._get_effective_permissions(
            'helpdesk', admin._users['helpdesk']['role'])

    def test_scoped_delegate_cannot_widen_to_all_companies_via_viewer(self, admin):
        c = _login_as(admin, 'scoped', perms=['users_edit', 'org.o-1.view'])
        r = c.put('/api/v1/users/scoped', json={'role': _roles()['viewer']})
        assert r.status_code == 403

    def test_groups_add_cannot_create_a_group_carrying_editor(self, admin):
        c = _login_as(admin, 'gm', perms=['groups_view', 'groups_add', 'groups_edit'])
        r = c.post('/api/v1/groups', json={'name': 'g', 'roles': [_roles()['editor']]})
        assert r.status_code == 403

    def test_a_delegate_holding_everything_viewer_carries_may_still_grant_it(self, admin):
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS   # noqa: PLC0415
        perms = sorted(set(BUILTIN_ROLE_PERMISSIONS['viewer']) | {'users_view', 'users_edit'})
        c = _login_as(admin, 'deleg', perms=perms)
        admin._users['other'] = {'uid': 'u-other', 'role': '', 'enabled': True,
                                 'password_hash': ''}
        r = c.put('/api/v1/users/other', json={'role': _roles()['viewer']})
        assert r.status_code == 200, r.get_json()
        assert admin._users['other']['role'] == _roles()['viewer']


# ── IDN-2 ─────────────────────────────────────────────────────────────────────
class TestScimIsAdminOnly:

    def test_config_edit_cannot_set_the_scim_token(self, admin):
        c = _login_as(admin, 'ed', role=_roles()['editor'])
        r = c.put('/api/v1/config', json={'scim': {'enabled': True, 'token': 'A' * 40}})
        assert r.status_code == 403
        assert admin._config_section('scim').get('token', '') != 'A' * 40

    def test_config_edit_cannot_set_scim_default_role(self, admin):
        c = _login_as(admin, 'ed', role=_roles()['editor'])
        r = c.put('/api/v1/config', json={'scim': {'default_role': _roles()['editor']}})
        assert r.status_code == 403

    def test_the_registry_marks_every_scim_field_admin_only(self):
        from lib.config.spec import CONFIG_FIELDS                    # noqa: PLC0415
        scim = [f for f in CONFIG_FIELDS if f.path.startswith('scim|')]
        assert scim and all(f.admin_only for f in scim)


class TestScimKeepsTheLastAdministrator:

    def _scim_admin(self, admin, *, local_admin_enabled):
        from lib.providers.scim.service import ScimService          # noqa: PLC0415
        admin._users['admin']['enabled'] = local_admin_enabled
        admin._users['idp-admin'] = {
            'uid': 'u-idp', 'role': _roles()['admin'], 'enabled': True, 'groups': [],
            'auth_source': 'scim', 'auth_source_id': 'ext-1', 'provisioned_by': 'scim',
            'scim_external_id': 'ext-1', 'password_hash': ''}
        return ScimService(admin, 'https://p.example/scim/v2')

    def test_delete_of_the_last_active_admin_is_refused(self, admin, client):
        with admin.app.test_request_context('/scim/v2/Users/u-idp'):
            svc = self._scim_admin(admin, local_admin_enabled=False)
            _body, status = svc.delete_user('u-idp')
        assert status == 403
        assert 'idp-admin' in admin._users

    def test_patch_active_false_of_the_last_active_admin_is_refused_whole(self, admin):
        with admin.app.test_request_context('/scim/v2/Users/u-idp'):
            svc = self._scim_admin(admin, local_admin_enabled=False)
            _body, status = svc.patch_user('u-idp', {'Operations': [
                {'op': 'replace', 'path': 'displayName', 'value': 'Renamed'},
                {'op': 'replace', 'value': {'active': False}}]})
        assert status == 403
        assert admin._users['idp-admin']['enabled'] is True
        assert admin._users['idp-admin'].get('display_name', '') != 'Renamed'

    def test_put_active_false_of_the_last_active_admin_is_refused(self, admin):
        with admin.app.test_request_context('/scim/v2/Users/u-idp'):
            svc = self._scim_admin(admin, local_admin_enabled=False)
            _body, status = svc.replace_user('u-idp', {'active': False, 'displayName': 'x'})
        assert status == 403
        assert admin._users['idp-admin']['enabled'] is True

    def test_with_another_active_admin_the_delete_goes_through(self, admin):
        with admin.app.test_request_context('/scim/v2/Users/u-idp'):
            svc = self._scim_admin(admin, local_admin_enabled=True)
            _body, status = svc.delete_user('u-idp')
        assert status == 204
        assert 'idp-admin' not in admin._users


# ── IDN-5 ─────────────────────────────────────────────────────────────────────
def _mint(client, name='t'):
    r = client.post('/api/v1/account/tokens', json={'name': name, 'permissions': '*'})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['token']


class TestPasswordChangeReportsTheTokens:

    def test_own_change_keeps_the_tokens_and_says_how_many(self, admin, client):
        _login(client)
        tok = _mint(client, 'a')
        _mint(client, 'b')
        r = client.put('/api/v1/users/me/password',
                       json={'current_password': 'secret', 'new_password': 'N3w-secret-pw!'})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['api_tokens'] == 2
        bare = admin.app.test_client()
        assert bare.get('/api/v1/me', headers={'Authorization': 'Bearer ' + tok}).status_code == 200

    def test_revoke_all_of_mine_cuts_them_and_is_audited(self, admin, client):
        _login(client)
        tok = _mint(client, 'a')
        r = client.delete('/api/v1/account/tokens')
        assert r.status_code == 200 and r.get_json()['revoked'] == 1
        bare = admin.app.test_client()
        assert bare.get('/api/v1/me', headers={'Authorization': 'Bearer ' + tok}).status_code == 401
        assert any(e.get('event') == 'api_tokens_revoked' for e in admin._audit_log)

    def test_a_token_cannot_revoke_all_of_its_owners_tokens(self, admin, client):
        _login(client)
        tok = _mint(client, 'a')
        bare = admin.app.test_client()
        r = bare.delete('/api/v1/account/tokens', headers={'Authorization': 'Bearer ' + tok})
        assert r.status_code == 403
        assert admin._live_api_token_count('admin') == 1

    def test_admin_reset_says_how_many_tokens_the_account_has(self, admin, client):
        c = _login_as(admin, 'bob', perms=['dashboard_view'])
        _mint(c, 'x')
        _login(client)
        r = client.put('/api/v1/users/bob', json={'password': 'An0ther-pw!'})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['api_tokens'] == 1
        r = client.delete('/api/v1/users/bob/tokens')
        assert r.status_code == 200 and r.get_json()['revoked'] == 1


# ── DIST-6 ────────────────────────────────────────────────────────────────────
def _bootstrap_wa(password):
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', password, var, pw_require_upper=False, pw_require_digit=False,
                  pw_require_symbol=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    return wa


def _sign_in(wa, password='admin'):
    c = wa.app.test_client()
    r = c.post('/login', data={'username': 'admin', 'password': password})
    return c, r


class TestDefaultPasswordMustBeChanged:

    def test_the_default_password_marks_the_bootstrap_admin(self):
        wa = _bootstrap_wa('admin')
        assert wa._users['admin'].get('must_change_password') is True
        row = wa._users_store._db.fetchone(
            "SELECT must_change_password FROM users WHERE username = 'admin'")
        assert row[0] == 1

    def test_a_chosen_password_does_not(self, admin):
        assert not admin._users['admin'].get('must_change_password')
        row = admin._users_store._db.fetchone(
            "SELECT must_change_password FROM users WHERE username = 'admin'")
        assert row[0] == 0

    def test_everything_but_the_change_answers_403_or_goes_to_the_screen(self):
        wa = _bootstrap_wa('admin')
        c, r = _sign_in(wa)
        page = c.get('/')
        assert page.status_code == 302 and '/login/change-password' in page.location
        api = c.get('/api/v1/me')
        assert api.status_code == 403
        assert api.get_json()['code'] == 'password_change_required'
        assert c.get('/login/change-password').status_code == 200

    def test_the_screen_refuses_the_same_password_and_a_weak_one(self):
        wa = _bootstrap_wa('admin')
        c, _ = _sign_in(wa)
        c.post('/login/change-password', data={'current_password': 'admin',
                                               'new_password': 'admin',
                                               'confirm_password': 'admin'})
        assert wa._users['admin'].get('must_change_password') is True
        c.post('/login/change-password', data={'current_password': 'admin',
                                               'new_password': 'x',
                                               'confirm_password': 'x'})
        assert wa._users['admin'].get('must_change_password') is True
        assert c.get('/api/v1/me').status_code == 403

    def test_a_good_new_password_clears_the_mark_for_good(self):
        wa = _bootstrap_wa('admin')
        c, _ = _sign_in(wa)
        r = c.post('/login/change-password', data={'current_password': 'admin',
                                                   'new_password': 'brand-new-pass',
                                                   'confirm_password': 'brand-new-pass'})
        assert r.status_code == 302 and '/login/change-password' not in r.location
        assert not wa._users['admin'].get('must_change_password')
        assert c.get('/api/v1/me').status_code == 200
        # Persisted, not only in memory: the next load from the table has no mark either.
        assert not wa._users_store.load()['admin'].get('must_change_password')

    def test_the_account_page_route_also_clears_it_and_refuses_the_old_one(self):
        wa = _bootstrap_wa('admin')
        c, _ = _sign_in(wa)
        r = c.put('/api/v1/users/me/password',
                  json={'current_password': 'admin', 'new_password': 'admin'})
        assert r.status_code == 400
        r = c.put('/api/v1/users/me/password',
                  json={'current_password': 'admin', 'new_password': 'brand-new-pass'})
        assert r.status_code == 200, r.get_json()
        assert c.get('/api/v1/me').status_code == 200

    def test_a_users_table_from_before_the_column_reads_as_zero(self, tmp_path):
        from lib.core.users.store import UsersStore                  # noqa: PLC0415
        from lib.db.sqlite import SQLiteConnector                    # noqa: PLC0415
        con = SQLiteConnector(str(tmp_path / 'old.db'))
        con.execute("CREATE TABLE users (uid TEXT PRIMARY KEY, username TEXT NOT NULL DEFAULT '',"
                    " password_hash TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '',"
                    " display_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',"
                    " lang TEXT NOT NULL DEFAULT '', dark_mode INTEGER,"
                    " enabled INTEGER NOT NULL DEFAULT 1,"
                    " auth_source TEXT NOT NULL DEFAULT 'local',"
                    " extra TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT '',"
                    " updated_at TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT '')")
        con.execute("INSERT INTO users (uid, username) VALUES ('u1', 'old')")
        con.commit()
        store = UsersStore(con)
        assert con.fetchone("SELECT must_change_password FROM users WHERE uid = 'u1'")[0] == 0
        assert 'must_change_password' not in store.load()['old']


# ── IDN-6 ─────────────────────────────────────────────────────────────────────
class TestWebAuthnLoginChallengeIsOneUse:

    def test_a_parked_cookie_cannot_be_replayed(self, admin, client):
        from lib.core.mfa import service as mfa_service              # noqa: PLC0415
        uid = admin._users['admin']['uid']
        assert admin._mfa_store.save_credential(uid, credential_id='c', public_key='pk',
                                                alg=-7, sign_count=0)
        admin._mfa_required = lambda *a, **k: True
        admin._mfa_enrolled = lambda *a, **k: True
        admin._webauthn_scope = lambda: {'ok': True, 'rp_id': 'p.example',
                                         'origin': 'https://p.example'}
        issued = {}
        with unittest.mock.patch.object(mfa_service, 'webauthn_verify',
                                        side_effect=lambda s, u, *, challenge, **k:
                                        {'ok': challenge == issued['c']}):
            client.post('/login', data={'username': 'admin', 'password': 'secret'})
            issued['c'] = client.post('/login/mfa/webauthn/begin').get_json()['challenge']
            parked = client.get_cookie('session').value
            assert client.post('/login/mfa/webauthn/verify',
                               json={'credential_id': 'c'}).status_code == 200
            c2 = admin.app.test_client()
            c2.set_cookie('session', parked)
            assert c2.post('/login/mfa/webauthn/verify',
                           json={'credential_id': 'c'}).status_code == 403
            with c2.session_transaction() as s:
                assert not s.get('logged_in')

    def test_the_store_spends_a_challenge_once(self, admin):
        uid = admin._users['admin']['uid']
        st = admin._mfa_store
        assert st.save_credential(uid, credential_id='c', public_key='pk', alg=-7, sign_count=0)
        assert st.set_challenge(uid, 'ch-1')
        assert not st.consume_challenge(uid, 'other')
        assert st.consume_challenge(uid, 'ch-1')
        assert not st.consume_challenge(uid, 'ch-1')
        assert not st.consume_challenge(uid, '')


# ── MFA per-account limit: counted before judged ─────────────────────────────
class TestMfaLimitCountsBeforeItJudges:

    def test_login_code_attempt_is_counted_before_it_is_checked(self, admin, client):
        admin._mfa_required = lambda *a, **k: True
        admin._mfa_enrolled = lambda *a, **k: True
        admin._LOCKOUT_MAX_ATTEMPTS = 5
        admin._ipban_offense = lambda *a, **k: None
        key = admin._users['admin']['uid']
        seen = []

        def _verify(code):
            dq = admin._mfa_ratelimit._buckets.get(key) or ()
            seen.append(len(dq))
            return ''

        admin._mfa_verify_pending = _verify
        client.post('/login', data={'username': 'admin', 'password': 'secret'})
        client.post('/login/mfa', data={'code': '000000'})
        assert seen == [1]

    def test_account_code_check_is_counted_before_it_is_checked(self, admin, client):
        from lib.core.mfa import service as mfa_service              # noqa: PLC0415
        _login(client)
        admin._LOCKOUT_MAX_ATTEMPTS = 5
        admin._ipban_offense = lambda *a, **k: None
        key = admin._users['admin']['uid']
        seen = []

        def _verify(store, uid, code):
            seen.append(len(admin._mfa_ratelimit._buckets.get(key) or ()))
            return ''

        with unittest.mock.patch.object(mfa_service, 'verify', side_effect=_verify), \
             unittest.mock.patch.object(admin, '_mfa_enrolled', return_value=True):
            client.post('/api/v1/account/mfa/disable', json={'code': '000000'})
        assert seen == [1]


class TestEntraScimRegistrationIsAdminOnly:
    """The Entra SCIM wizard pushes the stored SCIM token to the base URL it registers, and
    `scim_base` comes from the body: with `config_edit` alone it aimed the token anywhere."""

    def test_config_edit_cannot_start_it(self, admin):
        with unittest.mock.patch('lib.providers.entraid.device_flow.start') as start:
            c = _login_as(admin, 'cfgonly', perms=['config_view', 'config_edit'])
            r = c.post('/api/v1/auth/entraid/scim/device-code',
                       json={'scim_base': 'https://203.0.113.9/scim/v2'})
            assert r.status_code == 403
            r = c.post('/api/v1/auth/entraid/scim/device-poll', json={'flow_token': 'x'})
            assert r.status_code == 403
        assert not start.called, 'the stored SCIM token was handed to the flow'
