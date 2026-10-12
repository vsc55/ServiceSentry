#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Identity holes of the 2026-10-12 audit's fourth batch, through the app — each pinned.

The current-code checks after sign-in (turning MFA off, new recovery codes, adding a key) had
no per-account limit, only the per-address jail; a non-ASCII CSRF token was a 500; bodies of
the wrong JSON type were 500s across users, roles, groups, companies, MFA and Teams SSO; a
caller granted ONE company could rename, delete or re-file every other one; the second factor
did not re-read `login_enabled`; SCIM could add or drop LOCAL accounts in its groups; the
account screen named the wrong default landing page; and the job-history limits never
reached the code that applies them.
"""

from __future__ import annotations

import os

import pytest

from tests.conftest import _login, _login_as                        # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _enrol(admin, username='admin'):
    """A confirmed TOTP factor for *username*; returns the secret."""
    from lib.core.mfa import service as mfa_service, totp          # noqa: PLC0415
    uid = admin._users[username]['uid']
    out = mfa_service.enroll_begin(admin._mfa_store, uid, username)
    done = mfa_service.enroll_confirm(admin._mfa_store, uid,
                                      totp.code_at(out['secret'], totp.current_step() - 1))
    assert done['ok'], done
    return out['secret']


def _uid(r):
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()['uid']


class TestSecondFactor:

    def test_current_code_checks_after_sign_in_are_limited_per_account(self, admin, client):
        from lib.core.mfa import totp                                 # noqa: PLC0415
        _login(client)                                 # signed in before the factor existed
        secret = _enrol(admin)
        admin._LOCKOUT_MAX_ATTEMPTS = 3
        admin._ipban_offense = lambda *a, **k: None    # the per-ADDRESS jail is not the point
        for _ in range(3):
            assert client.post('/api/v1/account/mfa/disable',
                               json={'code': '000000'}).status_code == 403
        r = client.post('/api/v1/account/mfa/disable',
                        json={'code': totp.code_at(secret, totp.current_step())})
        assert r.status_code == 429, 'the right code after a run of guesses is still refused'
        assert admin._mfa_enrolled('admin')

    def test_login_disabled_between_the_two_halves_does_not_get_in(self, admin, client):
        from lib.core.mfa import totp                                 # noqa: PLC0415
        secret = _enrol(admin)
        _login(client)                                 # password accepted, code owed
        admin._users['admin']['login_enabled'] = False
        client.get('/login/mfa')
        client.post('/login/mfa', data={'code': totp.code_at(secret, totp.current_step())})
        assert client.get('/api/v1/me').status_code != 200

    def test_a_list_body_on_the_key_step_is_refused_not_a_500(self, admin, client):
        _enrol(admin)
        _login(client)
        assert client.post('/login/mfa/webauthn/verify', json=[1]).status_code == 403


class TestBodiesOfTheWrongType:

    def test_a_non_ascii_csrf_token_is_a_403(self, admin, client):
        _login(client)
        admin._csrf_enabled = True
        r = client.post('/api/v1/roles', json={'name': 'X'}, headers={'X-CSRF-Token': 'café'})
        assert r.status_code in (400, 403)

    @pytest.mark.parametrize('url,body', [
        ('/api/v1/roles', {'name': 7}),
        ('/api/v1/roles', {'name': 'R', 'permissions': 'users_view'}),
        ('/api/v1/groups', {'name': {'a': 1}}),
        ('/api/v1/groups', {'name': 'G', 'roles': [1]}),
        ('/api/v1/users', {'username': 7, 'password': 'Passw0rd!xyzLONG'}),
        ('/api/v1/users', {'username': 'u1', 'password': 1.5}),
        ('/api/v1/users', {'username': 'u1', 'password': 'Passw0rd!xyzLONG', 'email': ['x']}),
    ])
    def test_create_answers_400(self, admin, client, url, body):
        _login(client)
        assert client.post(url, json=body).status_code == 400

    def test_update_answers_400(self, admin, client):
        _login(client)
        rol = _uid(client.post('/api/v1/roles', json={'name': 'R', 'permissions': ['users_view']}))
        grp = _uid(client.post('/api/v1/groups', json={'name': 'G'}))
        assert client.put(f'/api/v1/roles/{rol}', json={'description': 3}).status_code == 400
        assert client.put(f'/api/v1/groups/{grp}', json={'members': [1]}).status_code == 400
        assert client.put('/api/v1/users/me/password',
                          json={'current_password': None, 'new_password': 7}).status_code == 400

    def test_list_bodies_and_a_numeric_sso_token(self, admin, client):
        _login(client)
        assert client.post('/api/v1/orgs', json=[1]).status_code == 400
        assert client.post('/api/v1/orgs/owner', json=[1]).status_code == 400
        assert client.post('/api/v1/account/mfa/disable', json=[1]).status_code == 400
        assert admin.app.test_client().post('/auth/msteams/sso', json={'token': 7}).status_code == 400

    def test_a_list_body_on_the_infra_watch(self, admin, client):
        _login(client)
        dev = admin._devices_store.create({'name': 'srv-a', 'address': '10.0.0.5',
                                           'kind': 'remote'}, actor='admin')
        assert client.post(f'/api/v1/infra/devices/{dev}/watch', json=[1]).status_code == 400


class TestCompanies:

    @pytest.fixture()
    def two(self, admin, client):
        _login(client)
        a = _uid(client.post('/api/v1/orgs', json={'name': 'Alfa', 'short': 'A'}))
        b = _uid(client.post('/api/v1/orgs', json={'name': 'Beta', 'short': 'B'}))
        sb = _uid(client.post('/api/v1/dcim/sites', json={'name': 'SB'}))
        sx = _uid(client.post('/api/v1/dcim/sites', json={'name': 'SX'}))
        assert client.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': sb,
                                                       'org_uid': b}).status_code == 200
        ua = _login_as(admin, 'ua', perms=['orgs_view', 'orgs_edit', f'org.{a}.view'])
        return dict(a=a, b=b, sb=sb, sx=sx, ua=ua)

    def test_another_companys_record_is_not_found(self, admin, two):
        ua = two['ua']
        assert ua.put(f'/api/v1/orgs/{two["b"]}', json={'name': 'Mine'}).status_code == 404
        assert ua.delete(f'/api/v1/orgs/{two["b"]}/source').status_code == 404
        assert ua.delete(f'/api/v1/orgs/{two["b"]}').status_code == 404
        assert admin._orgs_store.orgs.get(two['b'])['name'] == 'Beta'
        assert ua.put(f'/api/v1/orgs/{two["a"]}', json={'name': 'Alfa 2'}).status_code == 200

    def test_ownership_is_not_taken_from_or_given_to_an_unseen_company(self, admin, two):
        ua = two['ua']
        r = ua.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': two['sb'], 'org_uid': two['a']})
        assert r.status_code == 403
        r = ua.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': two['sb'], 'org_uid': ''})
        assert r.status_code == 403
        assert admin._orgs_store.said_of('site', two['sb']) == two['b']
        r = ua.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': two['sx'], 'org_uid': two['b']})
        assert r.status_code == 404
        r = ua.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': two['sx'], 'org_uid': two['a']})
        assert r.status_code == 200, 'an unclaimed thing may be filed under your own company'


class TestScimGroups:

    def test_scim_does_not_touch_local_members(self, admin, config_dir):
        from tests.integration.test_wa_scim import _AUTH, _scim_cfg    # noqa: PLC0415
        _scim_cfg(admin, config_dir)
        c = admin.app.test_client()
        local = admin._users['admin']['uid']
        gid = c.post('/scim/v2/Groups', headers=_AUTH,
                     json={'displayName': 'Ops', 'members': [{'value': local}]}).get_json()['id']
        assert gid not in (admin._users['admin'].get('groups') or [])
        admin._users['admin']['groups'] = [gid]           # an admin put it there by hand
        c.put(f'/scim/v2/Groups/{gid}', headers=_AUTH, json={'displayName': 'Ops', 'members': []})
        assert gid in admin._users['admin']['groups']


class TestLandingDefault:

    def test_me_names_the_page_the_redirect_uses(self, admin, client):
        from lib.web_admin.constants import HOME_PAGES, home_page_ids  # noqa: PLC0415
        core = {p['id'] for p in HOME_PAGES}
        module_page = next(i for i in home_page_ids() if i not in core)
        _login(client)
        admin._LANDING_PAGE = module_page
        assert client.get('/api/v1/me').get_json()['landing_default'] == module_page
        grp = _uid(client.post('/api/v1/groups', json={'name': 'G'}))
        admin._groups[grp]['landing_page'] = 'no-such-page'
        admin._users['admin']['groups'] = [grp]
        admin._LANDING_PAGE = 'overview'
        assert client.get('/api/v1/me').get_json()['landing_default'] == 'overview'


class TestJobHistoryLimits:

    def test_saved_config_and_environment_reach_the_recorder(self, admin, monkeypatch):
        from lib.core.jobs import record as jobs_record                # noqa: PLC0415
        before = jobs_record.limits()
        try:
            admin._apply_config_attrs({'web_admin': {'jobs_history_keep': 9}})
            assert jobs_record.limits()['keep'] == 9
            monkeypatch.setenv('SS_JOBS_HISTORY_LINES', '17')
            admin._apply_env_overrides()
            assert jobs_record.limits()['lines'] == 17
        finally:
            jobs_record.set_limits(before)
            os.environ.pop('SS_JOBS_HISTORY_LINES', None)
