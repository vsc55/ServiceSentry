#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The second factor through the app: enrolling it, and the gate it puts in front of a login.

:mod:`tests.unit.test_mfa_totp` proves the arithmetic against the RFC's own vectors and
:mod:`tests.unit.test_mfa_qr` proves the square against the standard's. What is tested HERE is
the thing neither of them can see — that a password on its own stops being enough.

The property the whole feature rests on, and the first class below: a sign-in that owes a
second factor is **not a session**. No row in the sessions table, no ``logged_in``, nothing
``_login_required`` lets through. The obvious alternative — create the session and flag it —
hands a real, API-usable session to whoever has the password, and makes every gate in the panel
responsible for remembering one more field. Here there is nothing to remember: until the code
verifies, the request is anonymous by having no session.
"""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:                             # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')

from lib.core.mfa import service as mfa_service   # noqa: E402
from lib.core.mfa import totp                     # noqa: E402
from tests.conftest import _login                 # noqa: E402


def _enrol(admin, username='admin'):
    """Give *username* a confirmed factor, the way the endpoints would. Returns the secret."""
    uid = (admin._users.get(username) or {}).get('uid', '')
    out = mfa_service.enroll_begin(admin._mfa_store, uid, username)
    # Confirmed with the PREVIOUS step (still inside the tolerance window) so the current one
    # is left unspent for the test to sign in with. Enrolling with the current code would burn
    # it — which is the anti-replay rule doing exactly what it is there for.
    code = totp.code_at(out['secret'], totp.current_step() - 1)
    done = mfa_service.enroll_confirm(admin._mfa_store, uid, code)
    assert done['ok'], done
    return out['secret'], done['recovery']


def _code(secret, offset=0):
    return totp.code_at(secret, totp.current_step() + offset)


def _post_mfa(client, code):
    client.get('/login/mfa')
    with client.session_transaction() as s:
        tok = s.get('_csrf')
    data = {'code': code}
    if tok:
        data['csrf_token'] = tok
    return client.post('/login/mfa', data=data, follow_redirects=False)


class TestAPasswordAloneStopsBeingEnough:

    def test_without_a_factor_nothing_changes(self, admin, client):
        """An account that has not enrolled signs in exactly as it did before — which is what
        makes this safe to deploy on an installation that has never heard of it."""
        _login(client)
        assert client.get('/api/v1/me').status_code == 200

    def test_with_one_the_password_lands_on_the_second_step(self, admin, client):
        _enrol(admin)
        res = _login(client)
        assert b'mfa' in res.request.path.encode() or res.status_code == 200
        with client.session_transaction() as s:
            assert not s.get('logged_in'), 'the password must not have created a session'
            assert s.get('mfa_pending'), 'and the sign-in must be parked'

    def test_the_parked_sign_in_is_not_a_session(self, admin, client):
        """The whole security of the step. A flagged session would be a real one."""
        _enrol(admin)
        _login(client)
        assert client.get('/api/v1/me').status_code in (401, 403)
        assert client.get('/api/v1/users').status_code in (401, 403)
        assert not admin._sessions, 'nothing may have been written to the sessions table'

    def test_the_right_code_finishes_it(self, admin, client):
        secret, _codes = _enrol(admin)
        _login(client)
        assert _post_mfa(client, _code(secret)).status_code == 302
        with client.session_transaction() as s:
            assert s.get('logged_in') and not s.get('mfa_pending')
        assert client.get('/api/v1/me').status_code == 200

    def test_a_wrong_code_does_not(self, admin, client):
        _enrol(admin)
        _login(client)
        _post_mfa(client, '000000')
        with client.session_transaction() as s:
            assert not s.get('logged_in')
        assert client.get('/api/v1/me').status_code in (401, 403)


class TestTheSecondStepCannotBeWalkedAround:

    def test_the_page_needs_a_parked_sign_in(self, admin, client):
        """Arriving at the URL directly is the login page, not a hint about what is missing."""
        res = client.get('/login/mfa', follow_redirects=False)
        assert res.status_code == 302 and '/login' in res.headers['Location']

    def test_posting_a_code_with_nothing_parked_grants_nothing(self, admin, client):
        secret, _codes = _enrol(admin)
        assert _post_mfa(client, _code(secret)).status_code == 302
        with client.session_transaction() as s:
            assert not s.get('logged_in')

    def test_a_code_for_somebody_else_is_not_a_way_in(self, admin, client):
        """The parked note names WHO is halfway in; the code is checked against that account
        and not against whoever has one that verifies."""
        secret, _codes = _enrol(admin, 'admin')
        admin._users['other'] = {'uid': 'u-other', 'password_hash': '', 'role': 'viewer',
                                 'enabled': True}
        _login(client)
        with client.session_transaction() as s:
            held = dict(s['mfa_pending'])
            held['username'] = 'other'
            s['mfa_pending'] = held
        _post_mfa(client, _code(secret))
        with client.session_transaction() as s:
            assert not s.get('logged_in')

    def test_an_account_disabled_between_the_two_halves_does_not_get_in(self, admin, client):
        """This is the second half of an authentication, so it re-reads rather than trusting
        what the first half saw."""
        secret, _codes = _enrol(admin)
        _login(client)
        admin._users['admin']['enabled'] = False
        _post_mfa(client, _code(secret))
        with client.session_transaction() as s:
            assert not s.get('logged_in')


class TestACodeIsSpentWhenItIsUsed:

    def test_the_same_code_does_not_open_a_second_session(self, admin, client):
        """Thirty seconds is a long time to hold somebody else's code."""
        secret, _codes = _enrol(admin)
        code = _code(secret)
        _login(client)
        assert _post_mfa(client, code).status_code == 302
        client.post('/logout', follow_redirects=True)
        _login(client)
        _post_mfa(client, code)
        with client.session_transaction() as s:
            assert not s.get('logged_in'), 'the code was already used'

    def test_a_recovery_code_works_once(self, admin, client):
        _secret, codes = _enrol(admin)
        _login(client)
        assert _post_mfa(client, codes[0]).status_code == 302
        client.post('/logout', follow_redirects=True)
        _login(client)
        _post_mfa(client, codes[0])
        with client.session_transaction() as s:
            assert not s.get('logged_in')

    def test_using_one_leaves_the_others(self, admin, client):
        _secret, codes = _enrol(admin)
        _login(client)
        _post_mfa(client, codes[0])
        assert admin._mfa_status('admin')['recovery_left'] == len(codes) - 1


class TestManagingYourOwn:

    def test_the_status_never_carries_a_secret(self, admin, client):
        secret, _codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        body = client.get('/api/v1/account/mfa').get_json()
        assert body['enrolled'] is True
        blob = str(body)
        assert 'secret' not in blob and secret not in blob

    def test_enrolling_twice_is_refused(self, admin, client):
        """Silently overwriting a working factor from a borrowed session is the whole attack
        this endpoint would otherwise be."""
        secret, _codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        assert client.post('/api/v1/account/mfa/begin', json={}).status_code == 409

    def test_turning_it_off_needs_a_current_code(self, admin, client):
        """A session is exactly what an attacker has when they have borrowed one."""
        secret, _codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        assert client.post('/api/v1/account/mfa/disable',
                           json={'code': '000000'}).status_code == 403
        assert admin._mfa_status('admin')['enrolled'] is True
        # Two steps on, so the code that signed in is not the one that turns it off.
        assert client.post('/api/v1/account/mfa/disable',
                           json={'code': _code(secret, 1)}).status_code == 200
        assert admin._mfa_status('admin')['enrolled'] is False

    def test_regenerating_the_codes_needs_one_too(self, admin, client):
        """Regenerating from a borrowed session would hand the attacker ten permanent ways
        back in."""
        secret, codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        assert client.post('/api/v1/account/mfa/recovery',
                           json={'code': '000000'}).status_code == 403
        res = client.post('/api/v1/account/mfa/recovery', json={'code': _code(secret, 1)})
        assert res.status_code == 200
        fresh = res.get_json()['recovery']
        assert set(fresh).isdisjoint(codes), 'the old list must stop working'

    def test_an_unenrolled_account_reports_so(self, admin, client):
        _login(client)
        assert client.get('/api/v1/account/mfa').get_json()['enrolled'] is False


class TestResettingSomebodyElses:

    def test_it_is_behind_its_own_permission(self, admin, client):
        """Granted to nobody by default: it is also what an attacker with `users_edit` would
        do to strip the protection before going after the password."""
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        for role in ('editor', 'viewer'):
            assert 'mfa_reset_others' not in BUILTIN_ROLE_PERMISSIONS[role]
        assert 'mfa_reset_others' in BUILTIN_ROLE_PERMISSIONS['admin']

    def test_an_admin_can_reset_it_and_the_account_signs_in_again(self, admin, client):
        secret, _codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        uid = admin._users['admin']['uid']
        assert client.delete(f'/api/v1/users/{uid}/mfa').status_code == 200
        assert admin._mfa_status('admin')['enrolled'] is False
        client.post('/logout', follow_redirects=True)
        _login(client)
        with client.session_transaction() as s:
            assert s.get('logged_in'), 'the password alone is enough again'

    def test_it_takes_the_recovery_codes_with_it(self, admin, client):
        """A factor without its codes is an account somebody can still get into with a code
        that no longer opens anything."""
        secret, _codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        uid = admin._users['admin']['uid']
        client.delete(f'/api/v1/users/{uid}/mfa')
        assert admin._mfa_store.recovery_left(uid) == 0

    def test_resetting_an_account_that_has_none_says_so(self, admin, client):
        _login(client)
        uid = admin._users['admin']['uid']
        assert client.delete(f'/api/v1/users/{uid}/mfa').status_code == 400
