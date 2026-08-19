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

import os
from unittest.mock import patch

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
from tests.helpers import _fn, _read, _strip_comments   # noqa: E402

SRC_ROOT = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


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


def _set_policy(admin, value):
    """Set `web_admin|mfa_required` the way a config save would."""
    cfg = admin._read_config_file(admin._CONFIG_FILE) or {}
    cfg.setdefault('web_admin', {})['mfa_required'] = value
    admin._write_config(cfg)


class TestRequiringIt:
    """Phase two: the installation can make accounts carry one. The property that matters is
    that switching it ON never locks anybody out — the enrolment happens on the way in, which
    is the only reason a policy like this is safe to turn on with nobody signed up."""

    def test_off_by_default_and_nothing_is_asked(self, admin, client):
        assert admin._mfa_policy() == 'off'
        _login(client)
        with client.session_transaction() as s:
            assert s.get('logged_in')

    def test_all_sends_an_unenrolled_account_to_enrol(self, admin, client):
        _set_policy(admin, 'all')
        assert admin._mfa_must_enrol('admin') is True
        res = _login(client)
        assert b'csrf' in res.data or res.status_code == 200
        with client.session_transaction() as s:
            assert not s.get('logged_in'), 'no session until a factor exists'
            assert s.get('mfa_pending')

    def test_the_enrolment_page_finishes_the_sign_in(self, admin, client):
        """Refusing instead of enrolling would lock out everybody who has not — which the
        moment the policy is switched on is everybody, the last administrator included."""
        _set_policy(admin, 'all')
        _login(client)
        page = client.get('/login/mfa/enrol')
        assert page.status_code == 200
        # The secret it just stored is the one the code has to match: the page draws from it.
        uid = admin._users['admin']['uid']
        secret = admin._mfa_store.factor(uid, decrypt=True)['secret']
        with client.session_transaction() as s:
            tok = s.get('_csrf')
        res = client.post('/login/mfa/enrol',
                          data={'code': totp.code_at(secret, totp.current_step()),
                                'csrf_token': tok or ''})
        assert res.status_code == 200
        with client.session_transaction() as s:
            assert s.get('logged_in'), 'enrolling finished the sign-in'
        assert admin._mfa_status('admin')['enrolled'] is True
        assert admin._mfa_status('admin')['recovery_left'] == 10

    def test_admins_covers_an_administrator_by_GROUP(self, admin, client):
        """`admins` means an administrator however they became one. Asking only the account's
        own role is the bug the August audit found in four other guards."""
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _set_policy(admin, 'admins')
        admin._users['byrole'] = {'uid': 'u-role', 'role': BUILTIN_ROLE_UIDS['admin'],
                                  'enabled': True, 'groups': []}
        admin._groups['g-adm'] = {'uid': 'g-adm', 'name': 'Admins', 'enabled': True,
                                  'roles': [BUILTIN_ROLE_UIDS['admin']]}
        admin._users['bygroup'] = {'uid': 'u-grp', 'role': BUILTIN_ROLE_UIDS['viewer'],
                                   'enabled': True, 'groups': ['g-adm']}
        admin._users['plain'] = {'uid': 'u-plain', 'role': BUILTIN_ROLE_UIDS['viewer'],
                                 'enabled': True, 'groups': []}
        assert admin._mfa_policy_applies('byrole') is True
        assert admin._mfa_policy_applies('bygroup') is True, 'admin by group is an admin'
        assert admin._mfa_policy_applies('plain') is False

    def test_a_factor_is_honoured_even_with_the_policy_off(self, admin, client):
        """Turning the policy off must not silently stop honouring what people set up."""
        secret, _codes = _enrol(admin)
        _set_policy(admin, 'off')
        _login(client)
        with client.session_transaction() as s:
            assert not s.get('logged_in')
        assert _post_mfa(client, _code(secret)).status_code == 302

    def test_the_enrol_page_will_not_mint_a_secret_for_somebody_who_has_one(self, admin, client):
        """Otherwise a password alone would replace a working factor."""
        _enrol(admin)
        _set_policy(admin, 'all')
        _login(client)
        res = client.get('/login/mfa/enrol', follow_redirects=False)
        assert res.status_code == 302 and '/login/mfa' in res.headers['Location']

    def test_it_needs_a_parked_sign_in_like_the_other_half(self, admin, client):
        _set_policy(admin, 'all')
        res = client.get('/login/mfa/enrol', follow_redirects=False)
        assert res.status_code == 302 and '/login' in res.headers['Location']

    def test_a_policy_that_cannot_be_honoured_is_ignored_rather_than_locking_everybody_out(
            self, admin, client, monkeypatch):
        """`MfaStore` refuses to write a seed it cannot encrypt, so a policy demanding one on
        an install without a key would demand what nobody can enrol — every account that had
        not already enrolled, shut out, the last administrator included."""
        _set_policy(admin, 'all')
        monkeypatch.setattr(admin._mfa_store, '_fernet', None)
        assert admin._mfa_policy() == 'off'
        _login(client)
        with client.session_transaction() as s:
            assert s.get('logged_in'), 'the policy gave way rather than the installation'

    def test_a_value_that_is_not_one_of_the_three_is_refused_on_save(self, admin, client):
        """Stored, it would be read as "not one of the values I check for", which fails OPEN —
        the one direction a policy field must never fail in."""
        _login(client)
        res = client.put('/api/v1/config', json={'web_admin': {'mfa_required': 'sometimes'}})
        assert res.status_code >= 400
        assert admin._mfa_policy() == 'off'


class TestTrustingADirectoryThatAlreadyAsks:
    """Phase three. "Does this IdP enforce MFA" is a fact about somebody else's system that
    only its operator can state, so it is a switch per provider rather than a rule here.

    Trusting one is a statement about that DOOR, not about the account: the same person using
    their password still meets the panel's own policy."""

    def _trust(self, admin, section, value=True):
        cfg = admin._read_config_file(admin._CONFIG_FILE) or {}
        cfg.setdefault(section, {})['mfa_trusted'] = value
        admin._write_config(cfg)

    def test_untrusted_by_default(self, admin):
        """The conservative direction: the panel keeps asking for what it can verify itself
        until an operator says the directory is doing it."""
        for source in ('ldap', 'oidc', 'saml2'):
            assert admin._mfa_provider_trusted(source) is False

    @pytest.mark.parametrize('source', ['ldap', 'oidc', 'saml2'])
    def test_a_trusted_provider_skips_both_halves(self, admin, source):
        """The code step AND the forced enrolment: both exist to establish the same fact, and
        the directory established it."""
        _enrol(admin)
        _set_policy(admin, 'all')
        self._trust(admin, source)
        assert admin._mfa_required('admin', source) is False
        assert admin._mfa_must_enrol('admin', source) is False

    def test_it_says_nothing_about_a_local_sign_in(self, admin, client):
        """Somebody who also has a password here still meets the panel's own policy when they
        use it — otherwise trusting one directory would quietly disarm every other door."""
        secret, _codes = _enrol(admin)
        self._trust(admin, 'oidc')
        assert admin._mfa_required('admin', 'local') is True
        _login(client)
        with client.session_transaction() as s:
            assert not s.get('logged_in')
        assert _post_mfa(client, _code(secret)).status_code == 302

    def test_trusting_one_does_not_trust_the_others(self, admin):
        _enrol(admin)
        self._trust(admin, 'ldap')
        assert admin._mfa_required('admin', 'ldap') is False
        for other in ('oidc', 'saml2'):
            assert admin._mfa_required('admin', other) is True

    def test_a_source_with_no_section_is_never_trusted(self, admin):
        """A Teams tab sign-in has no config section of its own, so there is nowhere to say
        it enforces MFA — and the answer to "no setting" is the safe one."""
        _enrol(admin)
        for source in ('entraid', 'local', '', 'made-up'):
            assert admin._mfa_provider_trusted(source) is False
            assert admin._mfa_required('admin', source) is True

    def test_turning_the_trust_back_off_asks_again(self, admin):
        _enrol(admin)
        self._trust(admin, 'oidc')
        assert admin._mfa_required('admin', 'oidc') is False
        self._trust(admin, 'oidc', False)
        assert admin._mfa_required('admin', 'oidc') is True


class TestWhereASecurityKeyWouldBeRegistered:
    """A credential is scoped by the BROWSER to the RP ID and cannot be moved, so registering
    one against a guess produces a key that silently never works again. When the install
    cannot say where it lives, the answer is not to offer WebAuthn at all."""

    def _url(self, admin, public_url='', rp_id=''):
        cfg = admin._read_config_file(admin._CONFIG_FILE) or {}
        cfg.setdefault('web_admin', {})['public_url'] = public_url
        cfg['web_admin']['webauthn_rp_id'] = rp_id
        admin._write_config(cfg)

    def test_no_public_url_means_it_is_not_offered(self, admin):
        self._url(admin, '')
        out = admin._webauthn_scope()
        assert out['ok'] is False and out['reason'] == 'no_public_url'

    def test_an_ip_address_is_not_a_registrable_domain(self, admin):
        self._url(admin, 'https://10.0.0.5')
        assert admin._webauthn_scope()['reason'] == 'no_public_url'

    def test_plain_http_is_refused_here_rather_than_by_the_browser(self, admin):
        """Refusing here means an explanation instead of an opaque browser error."""
        self._url(admin, 'http://panel.example.com')
        out = admin._webauthn_scope()
        assert out['ok'] is False and out['reason'] == 'not_https'

    def test_a_public_url_over_https_gives_the_domain_and_the_origin(self, admin):
        self._url(admin, 'https://panel.example.com')
        out = admin._webauthn_scope()
        assert out['ok'] is True
        assert out['rp_id'] == 'panel.example.com'
        assert out['origin'] == 'https://panel.example.com'

    def test_the_escape_can_scope_keys_to_a_parent_domain(self, admin):
        """Several names in front of one panel, or a public URL on a subdomain of the domain
        the keys should belong to."""
        self._url(admin, 'https://panel.example.com', rp_id='example.com')
        out = admin._webauthn_scope()
        assert out['ok'] is True and out['rp_id'] == 'example.com'

    def test_an_escape_the_origin_does_not_sit_under_is_refused(self, admin):
        """The browser would reject it, which is a worse place to find out."""
        self._url(admin, 'https://panel.example.com', rp_id='somewhere-else.net')
        assert admin._webauthn_scope()['reason'] == 'rp_id_mismatch'

    def test_a_child_of_the_origin_is_not_a_valid_scope_either(self, admin):
        self._url(admin, 'https://example.com', rp_id='panel.example.com')
        assert admin._webauthn_scope()['reason'] == 'rp_id_mismatch'

    def test_a_proxy_the_panel_is_not_reading_is_a_warning_and_not_a_refusal(self, admin):
        """The ceremony would work — what breaks first is the session cookie, and naming
        WebAuthn as the problem would send somebody to the wrong setting."""
        self._url(admin, 'https://panel.example.com')
        admin._PROXY_COUNT = 0
        out = admin._webauthn_scope()
        assert out['ok'] is True and out['proxy_warning'] is True
        admin._PROXY_COUNT = 1
        assert admin._webauthn_scope()['proxy_warning'] is False


class TestTheUsersTableSaysWhoHasOne:
    """A column read at a glance down forty rows, so "which of these is unprotected" is a
    question the screen answers instead of one an admin has to open forty modals for."""

    def test_the_listing_reports_it_per_account(self, admin, client):
        _login(client)
        body = client.get('/api/v1/users').get_json()
        assert body['admin']['mfa'] is False
        _enrol(admin)
        body = client.get('/api/v1/users').get_json()
        assert body['admin']['mfa'] is True

    def test_it_is_a_boolean_and_carries_nothing_else(self, admin, client):
        """The users list has no business knowing WHICH kind of factor, let alone anything
        about it."""
        _login(client)                       # sign in FIRST: enrolling parks the next one
        secret, _codes = _enrol(admin)
        blob = str(client.get('/api/v1/users').get_json()['admin'])
        assert secret not in blob and 'credential' not in blob and 'recovery' not in blob

    def test_a_store_that_cannot_answer_leaves_the_column_empty_rather_than_failing(
            self, admin, client, monkeypatch):
        """The users table is not the place an MFA problem takes the page down."""
        _login(client)
        _enrol(admin)
        def _boom():
            raise RuntimeError('database gone')
        monkeypatch.setattr(admin._mfa_store, 'enrolled_user_uids', _boom)
        res = client.get('/api/v1/users')
        assert res.status_code == 200 and res.get_json()['admin']['mfa'] is False

    def test_resetting_from_the_admin_screen_clears_the_column(self, admin, client):
        secret, _codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        uid = admin._users['admin']['uid']
        assert client.delete(f'/api/v1/users/{uid}/mfa').status_code == 200
        assert client.get('/api/v1/users').get_json()['admin']['mfa'] is False


class TestTheSignInPagesSayTheyAreWorking:
    """A form that NAVIGATES has nothing to say while it waits. The browser's own progress
    lives up in the tab, where nobody typing a code is looking, and the button that was pressed
    stays exactly as it was — so a slow answer and a dead button are the same picture. Reported
    from the enrolment page at first sign-in: "Verify does not show a spinner".

    These three pages do NOT load the panel's JS bundle, so `ssBtnBusy` is not available to
    them; the shell carries a markup-driven version instead, and the guard is that each form
    opts in. Opt-in and not automatic, because the same pages carry a form that must be left
    alone: the logout that abandons a half-finished sign-in.
    """

    def _form(self, html: str, action: str) -> str:
        i = html.index(f'action="{action}"')
        return html[html.rindex('<form', 0, i):html.index('>', i) + 1]

    def test_the_shell_ships_the_mechanism(self, client):
        html = client.get('/login').data.decode('utf-8', 'replace')
        assert "form[data-busy]" in html, 'the shell no longer wires the waiting state'
        assert 'spinner-border' in html

    def test_the_code_form_opts_in(self, admin, client):
        _enrol(admin)
        _login(client)                       # parks the sign-in at the second step
        html = client.get('/login/mfa').data.decode('utf-8', 'replace')
        assert 'data-busy' in self._form(html, '/login/mfa')

    def test_the_enrolment_form_opts_in(self, admin, client):
        _set_policy(admin, 'all')
        _login(client)
        html = client.get('/login/mfa/enrol').data.decode('utf-8', 'replace')
        assert 'data-busy' in self._form(html, '/login/mfa/enrol')

    def test_the_way_out_is_left_alone(self, admin, client):
        """The logout beside the code field abandons the sign-in. Disabling it because the
        page is busy would take away the only exit at the moment it is wanted."""
        _set_policy(admin, 'all')
        _login(client)
        html = client.get('/login/mfa/enrol').data.decode('utf-8', 'replace')
        assert 'data-busy' not in self._form(html, '/logout')


class TestAFailedRegenerationLeavesARecord:
    """Regenerating recovery codes is what somebody does when they think the old list leaked,
    so a refusal here is worth a line — and one branch of it was leaving none at all.

    Two different failures share one screen and must not share one story:

    * the CODE was wrong (or empty) — that is the person, and it is what a run of them looks
      like when somebody is guessing;
    * the code was RIGHT and the regeneration still failed — the factor went away between two
      requests, or the database would not take the write. Nothing about that is the sender's
      doing, it answered 400 and recorded nothing, and it is invisible from the browser.

    What the browser is told stays coarser than what is written down: `empty` and `bad_code`
    are one audit line apart and both answer `bad_code` on the wire. Which of the two it was is
    not something to hand back to whoever is sending them.
    """

    def _lines(self, admin, event='mfa_failed'):
        return [e for e in admin._audit_store.get_all() if e['event'] == event]

    def _post(self, client, code):
        return client.post('/api/v1/account/mfa/recovery', json={'code': code})

    def test_a_wrong_code_is_recorded_with_its_stage(self, admin, client):
        secret, _codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        admin._audit_store.delete_all()
        assert self._post(client, '000000').status_code == 403
        rows = self._lines(admin)
        assert rows, 'a refused regeneration wrote nothing at all'
        detail = rows[-1].get('detail') or {}
        assert detail.get('stage') == 'recovery'
        assert detail.get('error') == 'bad_code'

    def test_an_empty_code_is_told_apart_in_the_log_and_not_on_the_wire(self, admin, client):
        secret, _codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        admin._audit_store.delete_all()
        res = self._post(client, '')
        assert res.status_code == 403
        assert (res.get_json() or {}).get('error') == 'bad_code', \
            'the wire tells the sender which of the two it was'
        assert ((self._lines(admin)[-1].get('detail')) or {}).get('error') == 'empty'

    def test_a_right_code_that_still_fails_is_recorded(self, admin, client):
        """**The branch that used to be silent.** The code was correct, so this is not the
        person — and a 400 with nothing written down is a failure nobody can find afterwards."""
        secret, _codes = _enrol(admin)
        _login(client)
        _post_mfa(client, _code(secret))
        admin._audit_store.delete_all()
        with patch.object(admin._mfa_store, 'set_recovery', return_value=False):
            res = self._post(client, _code(secret, 1))
        assert res.status_code == 400
        assert (res.get_json() or {}).get('error') == 'write_failed'
        rows = self._lines(admin)
        assert rows, 'a write that failed with a CORRECT code left no trace'
        detail = rows[-1].get('detail') or {}
        assert detail.get('stage') == 'recovery' and detail.get('error') == 'write_failed'

    def test_turning_it_off_without_one_is_recorded_too(self, admin, client):
        """Same shape, same reason: a request to remove a factor that is not there says
        something about the sender, and it was answering 400 in silence."""
        _login(client)
        admin._audit_store.delete_all()
        res = client.post('/api/v1/account/mfa/disable', json={'code': '000000'})
        assert res.status_code == 400
        detail = (self._lines(admin)[-1].get('detail')) or {}
        assert detail.get('stage') == 'disable' and detail.get('error') == 'not_enrolled'


class TestTheThreeViewsAnswerTheSameQuestion:
    """"Which of these accounts is unprotected" is a question the Users section is asked in
    three places — the table, the cards and the access review — and it was answered in one.

    The column landed first because a table has a cell per row. The cards and the review kept
    quiet, which is worse than not having the feature: an access review that lists roles and
    groups and says nothing about second factors reads as one where nobody is missing one.

    So the mark is ONE function used by all three. A tick that means "protected" in the table
    and something slightly different in the review is worse than not having it in two of them.
    """

    def _views(self) -> str:
        base = os.path.join(SRC_ROOT, 'lib', 'web_admin', 'templates', 'partials', 'users')
        return (_read(os.path.join(base, '_list.html'))
                + _read(os.path.join(base, '_view_access.html')))

    def test_the_mark_is_written_once(self):
        src = _strip_comments(self._views())
        assert 'function _usrMfaMark' in src
        # Three callers: the table cell, the card chip and the review's column.
        assert src.count('_usrMfaMark(') >= 4, 'a view answers this its own way again'

    def test_it_says_it_in_words_and_not_only_in_colour(self):
        body = _fn(_strip_comments(self._views()), '_usrMfaMark')
        assert 'mfa_state_on' in body and 'mfa_state_off' in body
        assert 'bi-shield-check' in body and 'bi-shield-slash' in body, \
            'the two states differ by colour alone — unreadable for a colour-vision deficiency'

    def test_the_cards_answer_either_way(self):
        """A chip only on the protected accounts cannot be scanned for the others, which is
        the direction the question is actually asked in."""
        src = _strip_comments(_read(os.path.join(
            SRC_ROOT, 'lib', 'web_admin', 'templates', 'partials', 'users', '_list.html')))
        body = _fn(src, '_usersCardsBody')
        assert '_usrMfaMark(u)' in body
        assert 'u.mfa ?' not in body, 'the card chip is conditional on having one again'

    def test_the_access_review_counts_the_unprotected(self):
        """It is the view whose whole job is the question, so it says the number out loud —
        and counts only accounts that CAN sign in, or the number stops being believable."""
        body = _fn(_strip_comments(_read(os.path.join(
            SRC_ROOT, 'lib', 'web_admin', 'templates', 'partials', 'users',
            '_view_access.html'))), '_usrViewAccess')
        assert 'usr_count_no_mfa' in body
        assert 'login_enabled' in body, 'a service account with no login pads the count'

    def test_all_three_are_served_by_the_flag_the_api_sends(self, admin, client):
        _enrol(admin)
        _login(client)
        _post_mfa(client, _code(admin._mfa_store.factor(
            admin._users['admin']['uid'], decrypt=True)['secret']))
        rows = client.get('/api/v1/users').get_json() or {}
        assert rows.get('admin', {}).get('mfa') is True
