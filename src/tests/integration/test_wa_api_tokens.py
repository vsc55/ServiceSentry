#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API tokens: scripting an account without handing over its password.

Everything but SCIM authenticated by session cookie plus CSRF, so automation had to store a
real password — and once an account carries a second factor a password no longer completes a
sign-in at all. Turning on `mfa_required` therefore broke every script in the building, and
the only workaround was an account deliberately left unprotected.

Two properties carry the whole design, and most of this file is about them:

* a token is **intersected** with its owner's current permissions on every request, so it can
  never outgrow the account, and demoting the account demotes the token at the same instant;
* the routes that manage CREDENTIALS — minting, revoking, passwords, second factors — refuse
  a token. A narrow token that can mint a wide one is not narrow, and one that can change its
  owner's password is a foothold that takes over the account it was scoped inside.
"""

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


def _mint(client, **body):
    body.setdefault('name', 'ci')
    body.setdefault('permissions', ['users_view'])
    return client.post('/api/v1/account/tokens', json=body)


def _bearer(admin, raw):
    c = admin.app.test_client()
    c.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {raw}'
    return c


class TestMinting:

    def test_the_token_is_answered_once_and_never_again(self, client):
        _login(client)
        raw = _mint(client).get_json()['token']
        assert raw.startswith('sst_')
        listed = client.get('/api/v1/account/tokens').get_json()['tokens']
        assert len(listed) == 1
        assert raw not in str(listed), 'the token can be read back out of the list'

    def test_the_listing_carries_no_hash(self, client):
        _login(client)
        _mint(client)
        assert 'token_hash' not in str(client.get('/api/v1/account/tokens').get_json())

    def test_a_name_is_required(self, client):
        """A token nobody named is the one nobody dares revoke six months later, because the
        list cannot say what would break."""
        _login(client)
        assert _mint(client, name='   ').status_code == 400

    def test_permissions_are_required(self, client):
        """No default of "everything": the value of a scoped credential is the scope."""
        _login(client)
        assert _mint(client, permissions=[]).status_code == 400

    def test_an_unknown_permission_is_refused(self, client):
        _login(client)
        assert _mint(client, permissions=['not_a_flag']).status_code == 400

    def test_a_permission_you_do_not_have_is_refused(self, admin):
        """The intersection would drop it anyway. Refusing here is so the list says what it
        means, instead of showing a permission that silently does nothing."""
        admin._users['ed'] = {'uid': 'u-ed', 'role': 'viewer', 'enabled': True,
                              'password_hash': generate_password_hash('edsecret')}
        admin.app.config['TESTING'] = True
        c = admin.app.test_client()
        c.post('/login', data={'username': 'ed', 'password': 'edsecret'},
               follow_redirects=True)
        r = _mint(c, permissions=['config_edit'])
        assert r.status_code == 403

    @pytest.mark.parametrize('days', [-1, 0.5, 'soon', 99999])
    def test_a_nonsense_expiry_is_refused(self, client, days):
        _login(client)
        assert _mint(client, expires_days=days).status_code == 400

    def test_the_audit_entry_does_not_carry_the_token(self, client, admin):
        """A log that holds a live credential is a second place to steal it from."""
        _login(client)
        raw = _mint(client).get_json()['token']
        entry = next(e for e in admin._audit_log if e.get('event') == 'api_token_created')
        assert raw not in str(entry)
        assert entry['detail']['permissions'] == ['users_view']


class TestUsingOne:

    def test_it_authenticates_an_api_call(self, client, admin):
        _login(client)
        raw = _mint(client).get_json()['token']
        assert _bearer(admin, raw).get('/api/v1/users').status_code == 200

    def test_without_it_the_same_call_is_401(self, admin):
        assert admin.app.test_client().get('/api/v1/users').status_code == 401

    def test_a_garbage_token_authenticates_nobody(self, admin):
        assert _bearer(admin, 'sst_deadbeefcafe_' + 'f' * 48).get(
            '/api/v1/users').status_code == 401

    def test_it_is_confined_to_what_it_was_given(self, client, admin):
        """`users_view` and nothing else — the account has far more."""
        _login(client)
        raw = _mint(client, permissions=['users_view']).get_json()['token']
        c = _bearer(admin, raw)
        assert c.get('/api/v1/users').status_code == 200
        assert c.get('/api/v1/config').status_code == 403

    def test_star_follows_the_owner(self, client, admin):
        _login(client)
        raw = _mint(client, permissions='*').get_json()['token']
        assert _bearer(admin, raw).get('/api/v1/config').status_code == 200

    def test_demoting_the_owner_narrows_the_token(self, client, admin):
        """The reason the permissions are intersected per request instead of frozen at
        creation: taking a role away has to take it away everywhere at once."""
        _login(client)
        raw = _mint(client, permissions='*').get_json()['token']
        admin._users['admin']['role'] = 'viewer'
        assert _bearer(admin, raw).get('/api/v1/config').status_code == 403

    def test_a_revoked_token_stops_working(self, client, admin):
        _login(client)
        created = _mint(client).get_json()
        raw, uid = created['token'], created['record']['uid']
        assert client.delete(f'/api/v1/account/tokens/{uid}').status_code == 200
        assert _bearer(admin, raw).get('/api/v1/users').status_code == 401

    def test_an_expired_token_stops_working(self, client, admin):
        _login(client)
        raw = _mint(client, expires_days=1).get_json()['token']
        row = admin._api_token_store.list_for(admin._users['admin']['uid'])[0]
        admin._api_token_store._db.execute(
            'UPDATE api_tokens SET expires_at = ? WHERE uid = ?',
            ('2000-01-01T00:00:00+00:00', row['uid']))
        admin._api_token_store._db.commit()
        assert _bearer(admin, raw).get('/api/v1/users').status_code == 401

    def test_a_disabled_account_takes_its_tokens_with_it(self, client, admin):
        """Offboarding: the account's own state governs, or disabling somebody would leave a
        door open that nobody thinks to close."""
        _login(client)
        raw = _mint(client).get_json()['token']
        admin._users['admin']['enabled'] = False
        assert _bearer(admin, raw).get('/api/v1/users').status_code == 401

    def test_a_service_account_marked_no_login_cannot_be_scripted_either(self, client, admin):
        _login(client)
        raw = _mint(client).get_json()['token']
        admin._users['admin']['login_enabled'] = False
        assert _bearer(admin, raw).get('/api/v1/users').status_code == 401

    def test_it_is_not_handed_a_session_cookie(self, client, admin):
        """The client did not ask for a session. Ignoring the cookie is the best case;
        storing it turns a stateless call into a second credential on somebody's disk."""
        _login(client)
        raw = _mint(client).get_json()['token']
        resp = _bearer(admin, raw).get('/api/v1/users')
        assert not resp.headers.getlist('Set-Cookie')

    def test_it_does_not_appear_in_the_sessions_list(self, client, admin):
        """A token is not a session: it is not in that screen, and "revoke all sessions"
        does not mean something different depending on what you meant."""
        _login(client)
        raw = _mint(client).get_json()['token']
        before = len(admin._sessions)
        _bearer(admin, raw).get('/api/v1/users')
        assert len(admin._sessions) == before

    def test_a_signed_in_browser_stays_a_browser(self, client, admin):
        """A cookie session wins over a header. Mixing the two is what makes the CSRF
        judgement below ambiguous."""
        _login(client)
        raw = _mint(client, permissions=['users_view']).get_json()['token']
        client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {raw}'
        assert client.get('/api/v1/config').status_code == 200   # the session's rights, not the token's


class TestCsrfDoesNotApplyToIt:

    def test_a_bearer_write_needs_no_csrf_token(self, client, admin):
        """No cross-site page can attach an `Authorization` header, so the double-submit
        token protects nothing here — and requiring it would reject every write an API client
        makes."""
        _login(client)
        raw = _mint(client, permissions=['checks_run']).get_json()['token']
        admin._csrf_enabled = True
        try:
            r = _bearer(admin, raw).post('/api/v1/checks/run', json={})
            assert r.status_code != 403
        finally:
            admin._csrf_enabled = False


class TestATokenCannotWidenItself:
    """The routes that manage credentials refuse a token. This is what the scope is worth."""

    @staticmethod
    def _tok(client, admin, perms='*'):
        _login(client)
        return _bearer(admin, _mint(client, permissions=perms).get_json()['token'])

    def test_it_cannot_mint_another_token(self, client, admin):
        c = self._tok(client, admin)
        assert c.post('/api/v1/account/tokens',
                      json={'name': 'wider', 'permissions': '*'}).status_code == 403

    def test_it_cannot_list_or_revoke_its_siblings(self, client, admin):
        c = self._tok(client, admin)
        assert c.get('/api/v1/account/tokens').status_code == 403

    def test_it_cannot_change_the_owners_password(self, client, admin):
        c = self._tok(client, admin)
        r = c.put('/api/v1/users/me/password',
                  json={'current_password': 'secret', 'new_password': 'Newpass123'})
        assert r.status_code == 403

    def test_it_cannot_turn_off_the_second_factor(self, client, admin):
        c = self._tok(client, admin)
        assert c.post('/api/v1/account/mfa/disable', json={'code': '000000'}).status_code == 403

    def test_it_cannot_reset_somebody_elses_second_factor(self, client, admin):
        c = self._tok(client, admin)
        assert c.delete('/api/v1/users/u-x/mfa').status_code == 403


class TestRevoking:

    def test_i_cannot_revoke_a_token_that_is_not_mine(self, client, admin):
        """Pinned to the owner in the UPDATE itself, so guessing a uid matches no row."""
        _login(client)
        uid = _mint(client).get_json()['record']['uid']
        admin._users['ed'] = {'uid': 'u-ed', 'role': 'viewer', 'enabled': True,
                              'password_hash': generate_password_hash('edsecret')}
        c = admin.app.test_client()
        c.post('/login', data={'username': 'ed', 'password': 'edsecret'},
               follow_redirects=True)
        assert c.delete(f'/api/v1/account/tokens/{uid}').status_code == 404
        assert admin._api_token_store.count_for(admin._users['admin']['uid']) == 1

    def test_an_admin_can_cut_off_all_of_somebody_elses(self, client, admin):
        admin._users['ed'] = {'uid': 'u-ed', 'role': 'viewer', 'enabled': True,
                              'password_hash': generate_password_hash('edsecret')}
        c = admin.app.test_client()
        c.post('/login', data={'username': 'ed', 'password': 'edsecret'},
               follow_redirects=True)
        _mint(c, name='one')
        _mint(c, name='two')
        _login(client)
        r = client.delete('/api/v1/users/ed/tokens')
        assert r.status_code == 200 and r.get_json()['revoked'] == 2
        assert admin._api_token_store.count_for('u-ed') == 0

    def test_deleting_the_account_deletes_its_tokens(self, client, admin):
        admin._users['ed'] = {'uid': 'u-ed', 'role': 'viewer', 'enabled': True,
                              'password_hash': generate_password_hash('edsecret')}
        c = admin.app.test_client()
        c.post('/login', data={'username': 'ed', 'password': 'edsecret'},
               follow_redirects=True)
        _mint(c)
        _login(client)
        client.delete('/api/v1/users/ed')
        assert admin._api_token_store.list_for('u-ed') == []


class TestNamesAreUnique:
    """The name is the only thing in the list that says what a token is for."""

    def test_two_live_tokens_cannot_share_a_name(self, client):
        _login(client)
        assert _mint(client, name='ci').status_code == 200
        assert _mint(client, name='ci').status_code == 409

    def test_case_and_padding_do_not_make_it_a_different_name(self, client):
        """CI and "ci " are the same name to the person reading the list, and two tokens
        wearing it make revoking the right one a coin flip."""
        _login(client)
        _mint(client, name='ci')
        assert _mint(client, name='  CI ').status_code == 409

    def test_a_revoked_name_can_be_reused(self, client):
        """Kept for the record, but refusing to reuse the name of something that stopped
        working months ago would be a rule with no purpose."""
        _login(client)
        uid = _mint(client, name='ci').get_json()['record']['uid']
        client.delete(f'/api/v1/account/tokens/{uid}')
        assert _mint(client, name='ci').status_code == 200


class TestRotating:
    """A new secret without the old one stopping first.

    Rotating by revoke-then-create is what this replaces, and it costs two things that only
    hurt in production: the permission set has to be rebuilt from memory, and everything using
    the token is broken from the revoke until the new one is deployed.
    """

    @staticmethod
    def _rotate(client, uid):
        return client.post(f'/api/v1/account/tokens/{uid}/rotate')

    def test_the_new_token_works(self, client, admin):
        _login(client)
        uid = _mint(client, name='ci').get_json()['record']['uid']
        raw = self._rotate(client, uid).get_json()['token']
        assert _bearer(admin, raw).get('/api/v1/users').status_code == 200

    def test_the_old_one_keeps_working(self, client, admin):
        """The whole point: a window instead of an outage."""
        _login(client)
        created = _mint(client, name='ci').get_json()
        self._rotate(client, created['record']['uid'])
        assert _bearer(admin, created['token']).get('/api/v1/users').status_code == 200

    def test_it_keeps_the_permissions(self, client, admin):
        _login(client)
        uid = _mint(client, name='ci', permissions=['users_view']).get_json()['record']['uid']
        raw = self._rotate(client, uid).get_json()['token']
        c = _bearer(admin, raw)
        assert c.get('/api/v1/users').status_code == 200
        assert c.get('/api/v1/config').status_code == 403

    def test_the_name_moves_to_the_new_one(self, client):
        """Whatever reads the list still finds the name it knows on the CURRENT token, and
        the one to retire is the one that says so."""
        _login(client)
        uid = _mint(client, name='ci').get_json()['record']['uid']
        r = self._rotate(client, uid).get_json()
        assert r['record']['name'] == 'ci'
        assert 'ci' in r['previous']['name'] and r['previous']['name'] != 'ci'

    def test_the_two_never_share_a_name(self, client):
        _login(client)
        uid = _mint(client, name='ci').get_json()['record']['uid']
        self._rotate(client, uid)
        names = [tk['name'] for tk in
                 client.get('/api/v1/account/tokens').get_json()['tokens'] if not tk['revoked']]
        assert len(names) == len(set(names))

    def test_the_lifetime_is_the_original_span_not_the_original_date(self, client, admin):
        """Copying the date would hand back something expiring tomorrow and call it a
        rotation."""
        from datetime import datetime, timedelta, timezone
        _login(client)
        created = _mint(client, name='ci', expires_days=30).get_json()
        uid = created['record']['uid']
        now = datetime.now(timezone.utc)
        admin._api_token_store._db.execute(
            'UPDATE api_tokens SET created = ?, expires_at = ? WHERE uid = ?',
            ((now - timedelta(days=29)).isoformat(), (now + timedelta(days=1)).isoformat(), uid))
        admin._api_token_store._db.commit()
        rec = self._rotate(client, uid).get_json()['record']
        left = (datetime.fromisoformat(rec['expires_at']) - now).days
        assert left >= 25, f'the rotated token only lasts {left} days'

    def test_a_token_that_never_expires_rotates_into_one_that_never_expires(self, client):
        _login(client)
        uid = _mint(client, name='ci', expires_days=0).get_json()['record']['uid']
        assert self._rotate(client, uid).get_json()['record']['expires_at'] == ''

    def test_a_revoked_token_is_not_rotated(self, client):
        _login(client)
        uid = _mint(client, name='ci').get_json()['record']['uid']
        client.delete(f'/api/v1/account/tokens/{uid}')
        assert self._rotate(client, uid).status_code == 404

    def test_i_cannot_rotate_somebody_elses(self, client, admin):
        _login(client)
        uid = _mint(client, name='ci').get_json()['record']['uid']
        admin._users['ed'] = {'uid': 'u-ed', 'role': 'viewer', 'enabled': True,
                              'password_hash': generate_password_hash('edsecret')}
        c = admin.app.test_client()
        c.post('/login', data={'username': 'ed', 'password': 'edsecret'}, follow_redirects=True)
        assert c.post(f'/api/v1/account/tokens/{uid}/rotate').status_code == 404

    def test_a_token_cannot_rotate_one(self, client, admin):
        """It is minting a credential, so it needs a real sign-in like the rest."""
        _login(client)
        created = _mint(client, name='ci', permissions='*').get_json()
        c = _bearer(admin, created['token'])
        r = c.post(f"/api/v1/account/tokens/{created['record']['uid']}/rotate")
        assert r.status_code == 403

    def test_it_is_audited_and_names_what_it_replaces(self, client, admin):
        _login(client)
        created = _mint(client, name='ci').get_json()
        raw = self._rotate(client, created['record']['uid']).get_json()['token']
        entry = next(e for e in admin._audit_log if e.get('event') == 'api_token_rotated')
        assert entry['detail']['replaces'] == created['record']['token_id']
        assert raw not in str(entry)


class TestEditingTheScope:
    """Changing what a token may do, without minting a new one.

    Before this, a scope that turned out to be one permission short cost a rotation: a new
    secret redeployed everywhere it is configured, to fix a decision that has nothing to do
    with the secret. That is the cost that gets paid once and then avoided by minting the wide
    token instead — the outcome the whole feature exists to make unnecessary.
    """

    @staticmethod
    def _edit(client, uid, permissions):
        return client.put(f'/api/v1/account/tokens/{uid}', json={'permissions': permissions})

    def test_the_existing_secret_gets_the_new_scope(self, client, admin):
        """The point of editing rather than rotating: the token already deployed is the one
        that changes. Nothing is cached — the row is read and intersected on every request."""
        _login(client)
        created = _mint(client, permissions=['users_view']).get_json()
        c = _bearer(admin, created['token'])
        assert c.get('/api/v1/config').status_code == 403
        assert self._edit(client, created['record']['uid'], ['config_view']).status_code == 200
        assert c.get('/api/v1/config').status_code == 200

    def test_what_it_no_longer_has_stops_working(self, client, admin):
        """Narrowing has to bite as hard as widening, or "edit" is a one-way grant."""
        _login(client)
        created = _mint(client, permissions=['users_view']).get_json()
        c = _bearer(admin, created['token'])
        assert c.get('/api/v1/users').status_code == 200
        self._edit(client, created['record']['uid'], ['config_view'])
        assert c.get('/api/v1/users').status_code == 403

    def test_the_secret_does_not_change(self, client, admin):
        """Editing a scope is not a rotation: nothing has to be redeployed."""
        _login(client)
        created = _mint(client).get_json()
        before = client.get('/api/v1/account/tokens').get_json()['tokens'][0]['token_id']
        r = self._edit(client, created['record']['uid'], ['config_view'])
        assert r.get_json()['record']['token_id'] == before
        assert _bearer(admin, created['token']).get('/api/v1/config').status_code == 200

    def test_it_can_be_widened_to_all_of_mine(self, client):
        _login(client)
        uid = _mint(client).get_json()['record']['uid']
        assert self._edit(client, uid, '*').status_code == 200
        tk = next(t for t in client.get('/api/v1/account/tokens').get_json()['tokens']
                  if t['uid'] == uid)
        assert tk['permissions'] == '*'

    def test_i_cannot_give_it_a_permission_i_do_not_have(self, client, admin):
        """The same rule as minting, because they are the same decision at different times:
        a scope you may not create is not one you may edit your way into."""
        admin._users['ed'] = {'uid': 'u-ed', 'role': 'viewer', 'enabled': True,
                              'password_hash': generate_password_hash('edsecret')}
        c = admin.app.test_client()
        c.post('/login', data={'username': 'ed', 'password': 'edsecret'}, follow_redirects=True)
        uid = c.post('/api/v1/account/tokens',
                     json={'name': 'ci', 'permissions': ['users_view']}
                     ).get_json()['record']['uid']
        assert self._edit(c, uid, ['users_edit']).status_code == 403

    def test_an_unknown_flag_is_refused(self, client):
        _login(client)
        uid = _mint(client).get_json()['record']['uid']
        assert self._edit(client, uid, ['not_a_permission']).status_code == 400

    def test_an_empty_scope_is_refused(self, client):
        """A token with nothing is not a narrower token, it is a token that 403s everywhere —
        which reads as broken rather than as scoped."""
        _login(client)
        uid = _mint(client).get_json()['record']['uid']
        assert self._edit(client, uid, []).status_code == 400

    def test_a_revoked_token_is_not_edited(self, client):
        """It is not a token any more, and a scope on it would be a promise nothing keeps."""
        _login(client)
        uid = _mint(client).get_json()['record']['uid']
        client.delete(f'/api/v1/account/tokens/{uid}')
        assert self._edit(client, uid, ['config_view']).status_code == 404

    def test_i_cannot_edit_somebody_elses(self, client, admin):
        _login(client)
        uid = _mint(client).get_json()['record']['uid']
        admin._users['ed'] = {'uid': 'u-ed', 'role': 'admin', 'enabled': True,
                              'password_hash': generate_password_hash('edsecret')}
        c = admin.app.test_client()
        c.post('/login', data={'username': 'ed', 'password': 'edsecret'}, follow_redirects=True)
        assert self._edit(c, uid, ['config_view']).status_code == 404

    def test_a_token_cannot_edit_one(self, client, admin):
        """A narrow token that can widen itself is not narrow — the same reason it cannot mint
        one, and the reason this route sits behind a real sign-in."""
        _login(client)
        created = _mint(client, permissions='*').get_json()
        c = _bearer(admin, created['token'])
        r = c.put(f"/api/v1/account/tokens/{created['record']['uid']}",
                  json={'permissions': ['config_view']})
        assert r.status_code == 403

    def test_it_is_audited_with_both_sides(self, client, admin):
        """"What may it do now" without "what could it do before" cannot answer the only
        question asked of an entry like this."""
        _login(client)
        uid = _mint(client, permissions=['users_view']).get_json()['record']['uid']
        self._edit(client, uid, ['config_view'])
        entry = next(e for e in admin._audit_log if e.get('event') == 'api_token_edited')
        assert entry['detail']['permissions_before'] == ['users_view']
        assert entry['detail']['permissions'] == ['config_view']


def _as(admin, username, role='admin', password='pw-secret'):
    """A second signed-in client, for the hierarchy and escalation checks."""
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash(password)}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    return c


class TestTheAdministratorsList:
    """"What can run against this panel without anybody signing in" had no answer.

    The account list says who exists and the sessions screen says who is signed in; a token is
    standing access that appears in neither. Asking account by account is how the answer ends
    up depending on which accounts somebody remembered to open.
    """

    def test_it_lists_everybodys(self, client, admin):
        _login(client)
        _mint(client, name='mine')
        ed = _as(admin, 'ed', role='viewer')
        admin._api_token_store.create(
            user_uid='u-ed', name='eds', token_id='tid-ed', token_hash='x',
            permissions='[]', expires_at='', created='2026-01-01', created_by='ed')
        names = {t['name']: t for t in client.get('/api/v1/tokens').get_json()['tokens']}
        assert 'mine' in names and 'eds' in names
        assert names['eds']['username'] == 'ed'
        assert ed  # the account exists for the row to name

    def test_a_token_whose_account_is_gone_is_still_shown(self, client, admin):
        """It cannot authenticate — the hook refuses an owner it cannot resolve — but a row
        nobody can name is exactly the leftover an audit is looking for."""
        _login(client)
        admin._api_token_store.create(
            user_uid='u-vanished', name='orphan', token_id='tid-o', token_hash='x',
            permissions='[]', expires_at='', created='2026-01-01', created_by='who')
        row = next(t for t in client.get('/api/v1/tokens').get_json()['tokens']
                   if t['name'] == 'orphan')
        assert row['username'] == ''

    def test_it_never_carries_a_hash(self, client):
        _login(client)
        _mint(client)
        assert 'token_hash' not in str(client.get('/api/v1/tokens').get_json())

    def test_it_needs_the_permission(self, client, admin):
        c = _as(admin, 'nobody', role='none', password='nopw-secret')
        assert c.get('/api/v1/tokens').status_code == 403

    def test_an_admin_can_revoke_a_single_one(self, client, admin):
        _login(client)
        _as(admin, 'ed', role='viewer')
        uid = admin._api_token_store.create(
            user_uid='u-ed', name='eds', token_id='tid-ed2', token_hash='x',
            permissions='[]', expires_at='', created='2026-01-01', created_by='ed')
        assert client.delete(f'/api/v1/tokens/{uid}').status_code == 200
        assert admin._api_token_store.by_token_id('tid-ed2')['revoked']

    def test_a_non_admin_cannot_cut_an_administrators(self, client, admin):
        """The same hierarchy guard the rest of user management applies: an account you may
        not act on is not one whose credentials you may cut."""
        _login(client)
        uid = _mint(client).get_json()['record']['uid']
        c = _as(admin, 'helper', role='editor', password='helper-secret')
        assert c.delete(f'/api/v1/tokens/{uid}').status_code in (403, 404)


class TestMintingForSomebodyElse:
    """An escalation surface, and the two rules that keep it from being one."""

    @staticmethod
    def _mint_for(client, username, **body):
        body.setdefault('name', 'deploy')
        body.setdefault('permissions', ['users_view'])
        return client.post(f'/api/v1/users/{username}/tokens', json=body)

    def test_the_token_acts_as_that_account(self, client, admin):
        _login(client)
        _as(admin, 'ed', role='viewer')
        raw = self._mint_for(client, 'ed').get_json()['token']
        c = _bearer(admin, raw)
        assert c.get('/api/v1/users').status_code == 200
        assert [t for t in admin._api_token_store.list_for('u-ed')]

    def test_it_still_cannot_outgrow_that_account(self, client, admin):
        """The intersection is unchanged and is still the security model.

        Granting beyond the owner is now refused outright — a permission the token could never
        use makes the list say something it does not mean — and a token that WAS legitimate
        narrows the instant its owner is demoted, which is the property no amount of validation
        at creation can provide.
        """
        _login(client)
        ed = _as(admin, 'ed', role='editor')
        raw = self._mint_for(client, 'ed', permissions=['users_edit']).get_json()['token']
        c = _bearer(admin, raw)
        # Unlock and not the token routes themselves: those refuse a bearer caller by design,
        # so they cannot show whether a permission is in force.
        assert c.post('/api/v1/users/ed/unlock').status_code == 200
        from lib.core.constants import BUILTIN_ROLE_UIDS
        admin._users['ed']['role'] = BUILTIN_ROLE_UIDS['viewer']
        assert c.post('/api/v1/users/ed/unlock').status_code == 403
        assert ed  # the account was signed in for the fixture to be real

    def test_i_cannot_grant_what_i_do_not_have(self, client, admin):
        """Without this rule, anybody who may edit users mints a token for an administrator
        and then holds it."""
        c = _as(admin, 'helper', role='editor', password='helper-secret')
        _as(admin, 'ed', role='viewer')
        r = c.post('/api/v1/users/ed/tokens',
                   json={'name': 'x', 'permissions': ['audit_delete']})
        assert r.status_code == 403

    def test_star_follows_that_account(self, client, admin):
        """`'*'` resolves against the OWNER on every request, so for somebody else's token it
        means "everything that account has, and everything it is ever given" — which is how a
        token for an account keeps matching the account instead of going stale."""
        _login(client)
        _as(admin, 'ed', role='viewer')
        raw = self._mint_for(client, 'ed', permissions='*').get_json()['token']
        c = _bearer(admin, raw)
        assert c.get('/api/v1/users').status_code == 200
        assert c.get('/api/v1/config').status_code == 403     # the viewer cannot, so nor can it
        from lib.core.constants import BUILTIN_ROLE_UIDS
        admin._users['ed']['role'] = BUILTIN_ROLE_UIDS['editor']
        assert c.get('/api/v1/config').status_code == 200     # …and it grows with the account

    def test_only_an_administrator_may_give_it(self, client, admin):
        """It is the one value here that grows without anybody deciding: whoever minted it saw
        the secret, so a permission granted to that account next year widens a credential they
        may still hold. An administrator already holds everything, so it cannot carry them past
        their own ceiling; a delegated user-manager it could."""
        c = _as(admin, 'helper', role='editor', password='helper-secret')
        _as(admin, 'ed', role='viewer')
        assert c.post('/api/v1/users/ed/tokens',
                      json={'name': 'x', 'permissions': '*'}).status_code == 403

    def test_a_non_admin_cannot_mint_for_an_administrator(self, client, admin):
        c = _as(admin, 'helper', role='editor', password='helper-secret')
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _as(admin, 'boss', role=BUILTIN_ROLE_UIDS['admin'], password='boss-secret')
        assert c.post('/api/v1/users/boss/tokens',
                      json={'name': 'x', 'permissions': ['users_view']}).status_code == 403

    def test_it_needs_the_user_permission(self, client, admin):
        c = _as(admin, 'watcher', role='viewer', password='watch-secret')
        _as(admin, 'ed', role='viewer')
        assert c.post('/api/v1/users/ed/tokens',
                      json={'name': 'x', 'permissions': ['users_view']}).status_code == 403

    def test_it_is_audited_as_its_own_event(self, client, admin):
        """Handing out a credential that is not yours is a different act from minting your
        own, and has to be findable as such."""
        _login(client)
        _as(admin, 'ed', role='viewer')
        self._mint_for(client, 'ed')
        entry = next(e for e in admin._audit_log if e.get('event') == 'api_token_created_for')
        assert entry['detail']['username'] == 'ed'


class TestTheSystemIdentity:
    """A token that belongs to nobody, because automation that belongs to a person dies with
    that person's account.

    `system` is a built-in identity: a name, a stable UID and a row in the users listing, but
    no password, no session and NO PERMISSIONS — it acts with the panel's own authority
    precisely because it never passes a permission check. So the invariant that governs every
    other token ("intersected with the owner's, on every request") has nothing to intersect
    with here, and the ceiling moves to the administrator who minted it.
    """

    @staticmethod
    def _mint_system(client, **body):
        body.setdefault('name', 'housekeeping')
        body.setdefault('permissions', ['users_view'])
        return client.post('/api/v1/users/system/tokens', json=body)

    def test_it_can_be_minted_and_it_works(self, client, admin):
        _login(client)
        raw = self._mint_system(client).get_json()['token']
        assert _bearer(admin, raw).get('/api/v1/users').status_code == 200

    def test_its_scope_is_exactly_what_it_was_given(self, client, admin):
        """No owner to intersect with, so the stored set applies as written — and nothing but
        revoking narrows it afterwards."""
        _login(client)
        raw = self._mint_system(client, permissions=['users_view']).get_json()['token']
        c = _bearer(admin, raw)
        assert c.get('/api/v1/users').status_code == 200
        assert c.get('/api/v1/config').status_code == 403

    def test_star_is_refused(self, client):
        """Not policy: there is no owner set to resolve it against, so `service.effective`
        returns the empty set for it. It would be a token that can do nothing while claiming
        to do everything."""
        _login(client)
        assert self._mint_system(client, permissions='*').status_code == 400

    def test_only_an_administrator_may_mint_one(self, client, admin):
        """The panel's own identity is not something a delegated user-manager hands out."""
        c = _as(admin, 'helper', role='editor', password='helper-secret')
        assert c.post('/api/v1/users/system/tokens',
                      json={'name': 'x', 'permissions': ['users_view']}).status_code == 403

    def test_anonymous_may_not_own_one(self, client):
        """A token is an identification; the identity for "we do not know who" cannot hold
        one, or the log grows a credential behind that name."""
        _login(client)
        assert client.post('/api/v1/users/anonymous/tokens',
                           json={'name': 'x', 'permissions': ['users_view']}).status_code == 400

    def test_a_reserved_identity_in_a_session_holds_nothing(self, admin):
        """`system` is not a row in the users store, so the lookup falls back to the VIEWER
        default — which would hand the panel's own actor a viewer's permissions."""
        with admin.app.test_request_context('/'):
            from flask import session as fsession
            fsession['logged_in'] = True
            fsession['username'] = 'system'
            assert admin._get_session_permissions() == frozenset()

    def test_it_is_revocable_like_any_other(self, client, admin):
        _login(client)
        created = self._mint_system(client).get_json()
        assert client.delete(f"/api/v1/tokens/{created['record']['uid']}").status_code == 200
        assert _bearer(admin, created['token']).get('/api/v1/users').status_code == 401


class TestWhatAnAccountMayBeGiven:
    """The dialog offered the CALLER's permissions whoever the token was for.

    So minting one for a viewer showed all seventy-five and let you tick sixty the viewer does
    not have. Nothing broke — the request-time intersection drops them — which is exactly the
    problem: the list claimed the token could do things it could never do, and the first
    evidence otherwise was a 403 in something scripted at 3am.
    """

    def test_it_answers_with_that_accounts_own_set(self, client, admin):
        _login(client)
        _as(admin, 'ed', role='viewer')
        data = client.get('/api/v1/users/ed/permissions').get_json()
        assert 'users_view' in data['permissions']
        assert 'config_edit' not in data['permissions']
        assert data['unbounded'] is False

    def test_the_system_identity_is_unbounded_and_holds_nothing(self, client):
        """Nothing narrows its tokens, so the caller's own set is the only ceiling — and the
        screen has to know that rather than drawing an empty list of checkboxes."""
        _login(client)
        data = client.get('/api/v1/users/system/permissions').get_json()
        assert data['permissions'] == [] and data['unbounded'] is True

    def test_a_permission_the_owner_lacks_is_refused(self, client, admin):
        """Not a security rule — the intersection drops it anyway — but the same one the
        account's own screen applies: a permission that silently does nothing makes the list
        say something it does not mean."""
        _login(client)
        _as(admin, 'ed', role='viewer')
        r = client.post('/api/v1/users/ed/tokens',
                        json={'name': 'x', 'permissions': ['config_edit']})
        assert r.status_code == 400

    def test_it_needs_the_user_permission(self, client, admin):
        c = _as(admin, 'watcher', role='viewer', password='watch-secret')
        assert c.get('/api/v1/users/watcher/permissions').status_code == 403


class TestActingOnSomebodyElsesToken:
    """The row was revoke-only: the buttons the account screen has were missing here."""

    def _mint_for(self, client, username='ed', **body):
        body.setdefault('name', 'deploy')
        body.setdefault('permissions', ['users_view'])
        return client.post(f'/api/v1/users/{username}/tokens', json=body).get_json()

    def test_an_admin_can_re_scope_it(self, client, admin):
        _login(client)
        _as(admin, 'ed', role='editor')
        created = self._mint_for(client)
        c = _bearer(admin, created['token'])
        assert c.get('/api/v1/config').status_code == 403
        r = client.put(f"/api/v1/tokens/{created['record']['uid']}",
                       json={'permissions': ['config_view']})
        assert r.status_code == 200
        assert c.get('/api/v1/config').status_code == 200

    def test_re_scoping_stays_inside_the_owners_set(self, client, admin):
        _login(client)
        _as(admin, 'ed', role='viewer')
        created = self._mint_for(client)
        assert client.put(f"/api/v1/tokens/{created['record']['uid']}",
                          json={'permissions': ['config_edit']}).status_code == 400

    def test_it_can_be_widened_to_all_of_that_accounts(self, client, admin):
        """The same statement the mint route takes, and the same rule behind it."""
        _login(client)
        _as(admin, 'ed', role='viewer')
        created = self._mint_for(client)
        assert client.put(f"/api/v1/tokens/{created['record']['uid']}",
                          json={'permissions': '*'}).status_code == 200
        assert next(t for t in client.get('/api/v1/tokens').get_json()['tokens']
                    if t['uid'] == created['record']['uid'])['permissions'] == '*'

    def test_a_non_admin_cannot_widen_it_that_way(self, client, admin):
        _login(client)
        _as(admin, 'ed', role='viewer')
        created = self._mint_for(client)
        c = _as(admin, 'helper', role='editor', password='helper-secret')
        assert c.put(f"/api/v1/tokens/{created['record']['uid']}",
                     json={'permissions': '*'}).status_code == 403

    def test_an_admin_can_rotate_it_and_the_old_one_keeps_working(self, client, admin):
        """The same window instead of an outage the owner gets."""
        _login(client)
        _as(admin, 'ed', role='viewer')
        created = self._mint_for(client)
        r = client.post(f"/api/v1/tokens/{created['record']['uid']}/rotate")
        assert r.status_code == 200
        assert _bearer(admin, r.get_json()['token']).get('/api/v1/users').status_code == 200
        assert _bearer(admin, created['token']).get('/api/v1/users').status_code == 200

    def test_the_rotated_one_keeps_the_name_and_the_old_one_is_marked(self, client, admin):
        _login(client)
        _as(admin, 'ed', role='viewer')
        created = self._mint_for(client)
        r = client.post(f"/api/v1/tokens/{created['record']['uid']}/rotate").get_json()
        assert r['record']['name'] == 'deploy'
        assert r['previous']['name'] != 'deploy' and 'deploy' in r['previous']['name']

    def test_an_orphan_is_revocable_but_not_re_scoped(self, client, admin):
        """There is nobody to bound a new scope by, and an orphan with a fresh permission set
        is a credential being kept alive rather than cleaned up."""
        _login(client)
        uid = admin._api_token_store.create(
            user_uid='u-vanished', name='orphan', token_id='tid-orph', token_hash='x',
            permissions='[]', expires_at='', created='2026-01-01', created_by='who')
        assert client.put(f'/api/v1/tokens/{uid}', json={'permissions': ['users_view']}
                          ).status_code == 404
        assert client.post(f'/api/v1/tokens/{uid}/rotate').status_code == 404
        assert client.delete(f'/api/v1/tokens/{uid}').status_code == 200

    def test_a_non_admin_cannot_touch_an_administrators(self, client, admin):
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _login(client)
        uid = _mint(client).get_json()['record']['uid']
        _as(admin, 'boss', role=BUILTIN_ROLE_UIDS['admin'], password='boss-secret')
        c = _as(admin, 'helper', role='editor', password='helper-secret')
        assert c.put(f'/api/v1/tokens/{uid}', json={'permissions': ['users_view']}
                     ).status_code in (403, 404)

    def test_both_acts_are_audited_as_their_own_events(self, client, admin):
        _login(client)
        _as(admin, 'ed', role='editor')
        created = self._mint_for(client)
        client.put(f"/api/v1/tokens/{created['record']['uid']}",
                   json={'permissions': ['config_view']})
        client.post(f"/api/v1/tokens/{created['record']['uid']}/rotate")
        events = {e.get('event') for e in admin._audit_log}
        assert 'api_token_edited_by_admin' in events
        assert 'api_token_rotated_by_admin' in events


class TestWhatATokenHasBeenDoing:
    """`last_used` says a token is alive. It cannot say what it is for, whether what it is
    doing is what you set it up to do, or where it is calling from — and the audit log answers
    none of those either: it records the ACCOUNT, so a token's writes read as the person's own,
    and reads are not audited for anybody.
    """

    def test_a_call_is_recorded_with_what_it_was(self, client, admin):
        _login(client)
        created = _mint(client).get_json()
        _bearer(admin, created['token']).get('/api/v1/users')
        rows = client.get(f"/api/v1/account/tokens/{created['record']['uid']}/access"
                          ).get_json()['access']
        assert rows and rows[0]['method'] == 'GET'
        assert rows[0]['path'] == '/api/v1/users' and rows[0]['status'] == 200

    def test_a_refused_call_is_recorded_too(self, client, admin):
        """The line an access review is looking for. A history of the calls that worked is a
        history of the half that went as expected."""
        _login(client)
        created = _mint(client, permissions=['users_view']).get_json()
        _bearer(admin, created['token']).get('/api/v1/config')
        rows = client.get(f"/api/v1/account/tokens/{created['record']['uid']}/access"
                          ).get_json()['access']
        assert any(r['status'] == 403 for r in rows)

    def test_it_stores_the_route_and_not_the_url(self, client, admin):
        """A ring filled with one username per row answers "which endpoints does this use"
        with a wall of near-identical strings — and a raw path is where an id or an email ends
        up in a table shown to whoever may read the token list."""
        _login(client)
        created = _mint(client, permissions=['users_edit']).get_json()
        _bearer(admin, created['token']).post('/api/v1/users/admin/unlock')
        rows = client.get(f"/api/v1/account/tokens/{created['record']['uid']}/access"
                          ).get_json()['access']
        assert any(r['path'] == '/api/v1/users/<username>/unlock' for r in rows)
        assert not any('admin' in r['path'] for r in rows)

    def test_a_session_request_is_not_logged(self, client):
        """This is a token's history, not the panel's traffic. Every click of a signed-in
        browser in here would bury the handful of calls it exists to show."""
        _login(client)
        created = _mint(client).get_json()
        client.get('/api/v1/users')            # the cookie session, not the token
        assert client.get(f"/api/v1/account/tokens/{created['record']['uid']}/access"
                          ).get_json()['access'] == []

    def test_the_ring_is_capped_per_token(self, admin, client):
        """Per token and not globally: a chatty token would otherwise evict the history of a
        quiet one, and the quiet one is where a single unexpected call is the whole signal."""
        _login(client)
        store = admin._api_token_store
        for i in range(40):
            store.log_access('t-1', ts=f'2026-01-01T00:{i:02d}:00', ip='1.2.3.4',
                             method='GET', path='/x', status=200, keep=10)
        store.log_access('t-2', ts='2026-01-01T00:00:00', ip='1.2.3.4',
                         method='GET', path='/y', status=200, keep=10)
        assert len(store.access_for('t-1')) <= 12     # trimmed every keep//4 inserts
        assert len(store.access_for('t-2')) == 1

    def test_zero_is_no_ceiling_and_not_no_rows(self, admin):
        """It used to mean "record nothing", which is the opposite of what the same `0` means
        in `audit_max_entries` and `syslog|max_rows`. Somebody zeroing every cap in the panel
        to keep everything switched two of them off instead — reported from this install, with
        four zeroed fields and two silently empty logs."""
        for i in range(30):
            admin._api_token_store.log_access('t-all', ts=f'2026-01-01T00:{i:02d}:00', ip='',
                                              method='GET', path='/x', status=200, keep=0)
        assert len(admin._api_token_store.access_for('t-all', limit=999)) == 30

    def test_the_switch_is_what_stops_it(self, admin, client):
        """"No limit" and "no rows" are opposite answers, so they are two settings."""
        _login(client)
        raw = _mint(client).get_json()['token']
        admin._API_TOKEN_LOG_ENABLED = False
        _bearer(admin, raw).get('/api/v1/users')
        uid = client.get('/api/v1/account/tokens').get_json()['tokens'][0]['uid']
        assert admin._api_token_store.access_for(uid) == []

    def test_the_history_outlives_the_revocation(self, client, admin):
        """"What did this do before we cut it off" is asked precisely about the tokens that
        were cut off."""
        _login(client)
        created = _mint(client).get_json()
        _bearer(admin, created['token']).get('/api/v1/users')
        client.delete(f"/api/v1/account/tokens/{created['record']['uid']}")
        assert client.get(f"/api/v1/account/tokens/{created['record']['uid']}/access"
                          ).get_json()['access']

    def test_it_goes_when_the_account_goes(self, client, admin):
        """Rows about a credential that no longer exists, belonging to an account that no
        longer exists, are rows nothing can ever ask a question about again."""
        _login(client)
        created = _mint(client).get_json()
        _bearer(admin, created['token']).get('/api/v1/users')
        admin._api_token_store.delete_for_user(admin._users['admin']['uid'])
        assert admin._api_token_store.access_for(created['record']['uid']) == []

    def test_i_cannot_read_somebody_elses(self, client, admin):
        _login(client)
        uid = _mint(client).get_json()['record']['uid']
        c = _as(admin, 'ed', role='viewer')
        assert c.get(f'/api/v1/account/tokens/{uid}/access').status_code == 404

    def test_an_administrator_can_read_any(self, client, admin):
        _login(client)
        created = _mint(client).get_json()
        _bearer(admin, created['token']).get('/api/v1/users')
        assert client.get(f"/api/v1/tokens/{created['record']['uid']}/access"
                          ).get_json()['access']

    def test_the_admin_route_needs_the_permission(self, client, admin):
        c = _as(admin, 'nobody2', role='none', password='nopw2-secret')
        assert c.get('/api/v1/tokens/whatever/access').status_code == 403


class TestTheCrossTokenFeed:
    """The per-token history answers "is this credential doing what I set it up to do". This
    answers the one nothing could ask: what has been reaching this panel without anybody
    signing in, in order, across every token there is."""

    def test_it_carries_calls_of_every_token_with_whose_they_are(self, client, admin):
        _login(client)
        mine = _mint(client, name='mine').get_json()
        _bearer(admin, mine['token']).get('/api/v1/users')
        rows = client.get('/api/v1/tokens/access').get_json()['access']
        assert rows and rows[0]['name'] == 'mine'
        assert rows[0]['username'] == 'admin'
        assert rows[0]['token_uid'] == mine['record']['uid']

    def test_a_token_whose_account_is_gone_still_appears(self, client, admin):
        """A credential nobody owns any more is what the feed is read for."""
        _login(client)
        admin._api_token_store.create(
            user_uid='u-vanished', name='orphan', token_id='tid-feed', token_hash='x',
            permissions='[]', expires_at='', created='2026-01-01', created_by='who')
        row = admin._api_token_store.by_token_id('tid-feed')
        admin._api_token_store.log_access(row['uid'], ts='2026-01-01T00:00:00', ip='9.9.9.9',
                                          method='GET', path='/x', status=200)
        got = next(r for r in client.get('/api/v1/tokens/access').get_json()['access']
                   if r['name'] == 'orphan')
        assert got['username'] == ''

    def test_it_is_newest_first_and_capped(self, client, admin):
        _login(client)
        created = _mint(client).get_json()
        uid = created['record']['uid']
        for i in range(5):
            admin._api_token_store.log_access(uid, ts=f'2026-01-0{i + 1}T00:00:00', ip='',
                                              method='GET', path=f'/p{i}', status=200)
        data = client.get('/api/v1/tokens/access').get_json()
        ts = [r['ts'] for r in data['access']]
        assert ts == sorted(ts, reverse=True)
        assert data['max'] >= len(data['access'])

    def test_it_needs_the_permission(self, client, admin):
        c = _as(admin, 'nobody3', role='none', password='nopw3-secret')
        assert c.get('/api/v1/tokens/access').status_code == 403
