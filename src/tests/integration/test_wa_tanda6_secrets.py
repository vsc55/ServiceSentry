#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stored secrets that a test or an action could aim at an address of the caller's choosing,
and data the panel handed to whoever could reach the screen.

Audit 2026-10-12 (second pass), the IDOR / NET / IDN findings about secrets:

* ``/api/v1/snmp/<action>`` filled a stored item's, a device's or a credential's community
  into a request whose ``host`` the client chose — and ``snmp_view`` (viewer) opens it;
* an external syslog source's test and edit sent the stored password, or any credential
  named by ``cred_uid``, to the host in the body;
* ``/api/v1/credentials/test`` was open to ``credentials_view``;
* the Teams tab sign-in matched an account by UPN/mail with no regard to what it is bound to;
* the LDAP test routes opened LDAPS without validating the certificate, and turning TLS off
  in the form (LDAP or SMTP) did not count as a new destination for the stored password;
* the Servers / Coverage overview widgets counted the whole fleet for a user confined to one
  device, the module widgets ignored their declared ``perm``, and ``/status`` showed every
  check's detail to any signed-in account.

No network: every connector is replaced by a recorder.
"""

from __future__ import annotations

import os
import ssl
import sys
import unittest.mock

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

try:
    import flask  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')

from tests.conftest import _login, _login_as                        # noqa: E402

ATTACKER = '203.0.113.66'


# ─────────────────────────────── IDOR-1: SNMP actions ───────────────────────────────
class TestSnmpActionsAreConfined:
    """A viewer may walk an OID, but not with somebody else's community at their own host."""

    @pytest.fixture()
    def seen(self, admin, monkeypatch):
        import lib.core.snmp.actions as sa                           # noqa: PLC0415
        import lib.core.snmp.routes as sr                            # noqa: PLC0415
        monkeypatch.setattr(sa, '_HAS_PYSNMP', True)
        calls = []

        def _walk(cls, **kw):                                        # noqa: ARG001
            calls.append({k: kw.get(k) for k in ('host', 'community', 'v3_auth_key')})
            return [], None
        monkeypatch.setattr(sr._Ops, '_snmp_walk_oid', classmethod(_walk))
        mods = admin._load_modules() or {}
        mods['snmp'] = {'enabled': True, 'servers': {'it1': {
            'enabled': True, 'host': '10.8.8.8', 'community': 'ITEM-COMMUNITY',
            'version': '2c'}}}
        admin._save_modules(mods)
        return calls

    @staticmethod
    def _leaked(calls):
        return [c for c in calls if c.get('host') == ATTACKER
                and any('COMMUNITY' in str(v) or 'KEY' in str(v) for v in c.values())]

    def test_a_viewer_cannot_send_a_stored_items_community_to_their_host(self, admin, seen):
        c = _login_as(admin, 'snmpro', perms=['snmp_view'])
        r = c.post('/api/v1/snmp/walk_oid',
                   json={'_item_key': 'it1', 'host': ATTACKER, 'oid': '1.3.6.1.2.1.1'})
        assert r.status_code == 200, r.get_json()
        assert not self._leaked(seen), seen

    def test_a_viewer_cannot_send_a_devices_community_to_their_host(self, admin, seen):
        dev = admin._devices_store.create({
            'name': 'core-sw', 'address': '10.9.9.9', 'kind': 'remote',
            'profiles': {'snmp': {'community': 'DEV-COMMUNITY', 'version': '2c'}}}, actor='t')
        c = _login_as(admin, 'snmpro', perms=['snmp_view'])
        c.post('/api/v1/snmp/walk_oid',
               json={'device_uid': dev, 'host': ATTACKER, 'oid': '1.3.6.1.2.1.1'})
        assert not self._leaked(seen), seen

    def test_a_viewer_cannot_send_a_credential_to_their_host(self, admin, seen):
        cred = admin._credentials_store.create({
            'name': 'snmpcred', 'ctype': 'snmp',
            'data': {'community': 'CRED-COMMUNITY', 'snmpv3_username': 'u',
                     'snmpv3_auth_key': 'CRED-AUTHKEY'}}, actor='t')
        c = _login_as(admin, 'snmpro', perms=['snmp_view'])
        c.post('/api/v1/snmp/walk_oid',
               json={'cred_uid': cred, 'host': ATTACKER, 'oid': '1.3.6.1.2.1.1'})
        assert not self._leaked(seen), seen

    def test_the_stored_item_still_runs_with_its_own_community(self, admin, seen):
        """The confinement runs the item as saved — it does not stop it working."""
        c = _login_as(admin, 'snmpro', perms=['snmp_view'])
        c.post('/api/v1/snmp/walk_oid', json={'_item_key': 'it1', 'oid': '1.3.6.1.2.1.1'})
        assert seen and seen[-1]['host'] == '10.8.8.8'
        assert seen[-1]['community'] == 'ITEM-COMMUNITY'


# ─────────────────────────── IDOR-2 / NET-2: syslog sources ─────────────────────────
class TestSyslogSourceSecretsStayWithTheirServer:

    @pytest.fixture()
    def env(self, admin, client, monkeypatch):
        from lib.services.syslog import sources as S                 # noqa: PLC0415
        seen = []

        def _connector(cfg, **kw):                                   # noqa: ARG001
            seen.append({'host': cfg.get('host'), 'user': cfg.get('user'),
                         'password': cfg.get('password')})
            raise RuntimeError('t6a2-stub')
        monkeypatch.setattr(S, 'get_connector', _connector)
        _login(client)
        r = client.post('/api/v1/syslog/sources', json={'name': 'rsys', 'data': {
            'driver': 'mysql', 'host': '10.1.1.1', 'name': 'Syslog', 'user': 'rs',
            'password': 'STORED-DBPW'}})
        assert r.status_code == 201, r.get_json()
        cred = admin._credentials_store.create({
            'name': 'dbc', 'ctype': 'database',
            'data': {'db_user': 'dbu', 'db_password': 'CRED-DBPW'}}, actor='t')
        return {'uid': r.get_json()['uid'], 'cred': cred, 'seen': seen}

    def test_the_stored_password_does_not_follow_a_new_host(self, admin, env):
        c = _login_as(admin, 'cfged', perms=['config_view', 'config_edit'])
        c.post('/api/v1/syslog/sources/test', json={'uid': env['uid'], 'name': 'rsys', 'data': {
            'driver': 'mysql', 'host': ATTACKER, 'name': 'Syslog', 'user': 'rs',
            'password': None}})
        assert env['seen'] and env['seen'][-1]['host'] == ATTACKER
        assert env['seen'][-1]['password'] != 'STORED-DBPW'

    def test_the_stored_password_is_still_used_on_its_own_server(self, admin, env):
        c = _login_as(admin, 'cfged', perms=['config_view', 'config_edit'])
        c.post('/api/v1/syslog/sources/test', json={'uid': env['uid'], 'name': 'rsys', 'data': {
            'driver': 'mysql', 'host': '10.1.1.1', 'name': 'Syslog', 'user': 'rs',
            'password': None}})
        assert env['seen'] and env['seen'][-1]['password'] == 'STORED-DBPW'

    def test_an_edit_that_moves_the_source_does_not_keep_the_password(self, admin, env):
        c = _login_as(admin, 'cfged', perms=['config_view', 'config_edit'])
        r = c.put(f"/api/v1/syslog/sources/{env['uid']}", json={'name': 'rsys', 'data': {
            'driver': 'mysql', 'host': ATTACKER, 'name': 'Syslog', 'user': 'rs',
            'password': None}})
        assert r.status_code == 200, r.get_json()
        stored = admin._syslog_sources._store.get(env['uid'])
        assert (stored['data'].get('password') or '') == ''

    def test_a_credential_cannot_be_aimed_without_credentials_edit(self, admin, env):
        c = _login_as(admin, 'cfged', perms=['config_view', 'config_edit'])
        r = c.post('/api/v1/syslog/sources/test', json={'name': 'x', 'data': {
            'driver': 'postgresql', 'host': ATTACKER, 'name': 'x', 'cred_uid': env['cred']}})
        assert r.status_code == 403
        assert not env['seen']
        r = c.put(f"/api/v1/syslog/sources/{env['uid']}", json={'name': 'rsys', 'data': {
            'driver': 'mysql', 'host': ATTACKER, 'name': 'Syslog', 'cred_uid': env['cred']}})
        assert r.status_code == 403
        r = c.post('/api/v1/syslog/sources', json={'name': 'new', 'data': {
            'driver': 'mysql', 'host': ATTACKER, 'name': 'S', 'cred_uid': env['cred']}})
        assert r.status_code == 403

    def test_credentials_edit_may_choose_a_credential(self, admin, env):
        c = _login_as(admin, 'cfgcred',
                      perms=['config_view', 'config_edit', 'credentials_edit'])
        r = c.post('/api/v1/syslog/sources/test', json={'name': 'x', 'data': {
            'driver': 'postgresql', 'host': '10.2.2.2', 'name': 'x', 'cred_uid': env['cred']}})
        assert r.status_code == 200
        assert env['seen'] and env['seen'][-1]['password'] == 'CRED-DBPW'


# ─────────────────────────── credentials/test needs edit ────────────────────────────
class TestCredentialTestNeedsEdit:

    @pytest.fixture()
    def cred(self, admin):
        return admin._credentials_store.create({
            'name': 'ssh-prod', 'ctype': 'ssh',
            'data': {'ssh_user': 'root', 'ssh_password': 'CRED-SSHPW'}}, actor='t')

    def test_credentials_view_cannot_run_a_test(self, admin, cred):
        c = _login_as(admin, 'cview', perms=['credentials_view'])
        with unittest.mock.patch('lib.core.devices.ssh_client.test_connection',
                                 return_value=(True, 'ok')) as tc:
            r = c.post('/api/v1/credentials/test', json={'cred_uid': cred, 'address': ATTACKER})
        assert r.status_code == 403
        assert not tc.called

    def test_credentials_add_tests_a_draft_but_not_a_stored_one(self, admin, cred):
        c = _login_as(admin, 'cadd', perms=['credentials_view', 'credentials_add'])
        with unittest.mock.patch('lib.core.devices.ssh_client.test_connection',
                                 return_value=(True, 'ok')) as tc:
            r = c.post('/api/v1/credentials/test', json={'cred_uid': cred, 'address': ATTACKER})
            assert r.status_code == 403 and not tc.called
            r = c.post('/api/v1/credentials/test', json={
                'data': {'ssh_user': 'me', 'ssh_password': 'typed'}, 'address': '10.3.3.3'})
        assert r.status_code == 200 and tc.called

    def test_credentials_edit_runs_it(self, admin, cred):
        c = _login_as(admin, 'cedit', perms=['credentials_view', 'credentials_edit'])
        with unittest.mock.patch('lib.core.devices.ssh_client.test_connection',
                                 return_value=(True, 'ok')) as tc:
            r = c.post('/api/v1/credentials/test', json={'cred_uid': cred, 'address': '10.3.3.3'})
        assert r.status_code == 200
        assert tc.call_args.kwargs['password'] == 'CRED-SSHPW'


# ─────────────────────────── IDN-3: Teams SSO binding ───────────────────────────────
class TestTeamsSsoHonoursTheBinding:

    def _post(self, client, claims):
        from lib.providers.entraid import sso_routes                 # noqa: PLC0415
        with unittest.mock.patch.object(sso_routes.tab_sso, 'available', return_value=True), \
             unittest.mock.patch.object(sso_routes.tab_sso, 'validate_tab_token',
                                        return_value=claims):
            return client.post('/auth/msteams/sso', json={'token': 'x'})

    def test_an_account_bound_to_another_oid_is_refused(self, admin, client):
        admin._users['alice@corp.example'] = {
            'uid': 'u-a', 'auth_source': 'entraid', 'auth_source_id': 'oid-person-a',
            'email': 'alice@corp.example', 'role': 'admin', 'enabled': True, 'groups': []}
        r = self._post(client, {'preferred_username': 'alice@corp.example',
                                'oid': 'oid-person-b'})
        assert r.status_code == 403
        with client.session_transaction() as s:
            assert not s.get('logged_in')

    def test_an_account_bound_to_another_provider_is_refused_and_audited(self, admin, client):
        admin._users['bob'] = {'uid': 'u-b', 'auth_source': 'saml2',
                               'auth_source_id': 'nameid-bob', 'email': 'bob@corp.example',
                               'role': 'admin', 'enabled': True, 'groups': []}
        with unittest.mock.patch.object(admin, '_audit') as audit:
            r = self._post(client, {'preferred_username': 'bob@corp.example', 'oid': 'oid-z'})
        assert r.status_code == 403
        reasons = [k.kwargs.get('detail', {}).get('error') for k in audit.call_args_list
                   if k.args and k.args[0] == 'msteams_sso_failed']
        assert 'entraid_bound_to_other_provider' in reasons

    def test_an_unbound_sso_account_is_still_matched(self, admin, client):
        admin._users['carol@corp.example'] = {
            'uid': 'u-c', 'auth_source': 'oidc', 'email': 'carol@corp.example',
            'role': 'viewer', 'enabled': True, 'groups': []}
        r = self._post(client, {'preferred_username': 'carol@corp.example', 'oid': 'oid-c'})
        assert r.status_code == 200 and r.get_json()['ok'] is True


# ─────────────────────── IDN-4: LDAP / SMTP transport of the secret ─────────────────
class TestLdapTestRoutesValidateTheCertificate:

    @staticmethod
    def _seed(admin, **ldap):
        cfg = admin._read_config_file(admin._CONFIG_FILE) or {}
        admin._write_config({**cfg, 'ldap': {
            'enabled': True, 'server': 'ldap.corp.invalid', 'port': 636, 'use_ssl': True,
            'ssl_verify': True, 'bind_dn': 'cn=svc', 'bind_password': 'LDAP-PW', **ldap}})

    def test_every_route_passes_a_validating_tls(self, admin, client):
        self._seed(admin)
        _login(client)
        seen = []

        def _rec(*a, **kw):                                          # noqa: ARG001
            seen.append(kw.get('tls'))
            raise RuntimeError('no network')
        for path, body in (('/api/v1/auth/ldap/test', {}), ('/api/v1/auth/ldap/groups', {}),
                           ('/api/v1/auth/ldap/group_lookup', {'dn': 'cn=g,dc=x'})):
            with unittest.mock.patch('ldap3.Server', _rec):
                client.post(path, json=body)
        assert len(seen) == 3
        assert all(t is not None and t.validate == ssl.CERT_REQUIRED for t in seen)

    def test_turning_tls_off_drops_the_stored_bind_password(self, admin, client):
        self._seed(admin)
        _login(client)
        seen = []

        def _conn(*a, **kw):                                         # noqa: ARG001
            seen.append(kw.get('password'))
            raise RuntimeError('no network')
        for body in ({'use_ssl': False}, {'ssl_verify': False}, {}):
            with unittest.mock.patch('ldap3.Connection', _conn):
                client.post('/api/v1/auth/ldap/test', json=body)
        assert seen[0] is None and seen[1] is None      # downgraded: no stored password
        assert seen[2] == 'LDAP-PW'                     # as stored: it is used


class TestSmtpTestKeepsThePasswordOnTls:

    def test_switching_tls_off_drops_the_stored_password(self, admin, client):
        cfg = admin._read_config_file(admin._CONFIG_FILE) or {}
        admin._write_config({**cfg, 'email': {
            **(cfg.get('email') or {}), 'smtp_host': 'smtp.corp.invalid', 'smtp_port': 587,
            'smtp_username': 'mailer', 'smtp_password': 'SMTP-PW', 'smtp_use_tls': True,
            'smtp_use_ssl': False}})
        _login(client)
        seen = []

        def _dispatch(cfg, **kw):                                    # noqa: ARG001
            seen.append(cfg.get('smtp_password'))
            return False, 'stub'
        with unittest.mock.patch('lib.core.notify.email.notify._dispatch', _dispatch):
            client.post('/api/v1/notify/email/test',
                        json={'smtp_use_tls': False, 'test_to': 'a@b.example'})
            client.post('/api/v1/notify/email/test', json={'test_to': 'a@b.example'})
        assert seen == ['', 'SMTP-PW']


# ─────────────────────── IDOR-3: device overview widgets ────────────────────────────
class TestDeviceWidgetsCountOnlyWhatTheCallerSees:

    def test_a_scoped_user_sees_only_their_device(self, admin):
        st = admin._devices_store
        mine = st.create({'name': 'mine-01', 'address': '10.0.0.1'}, actor='t')
        st.create({'name': 'secret-box', 'address': '10.0.0.2'}, actor='t')
        c = _login_as(admin, 'scoped', perms=[f'server.{mine}.view', 'overview_view'])
        body = c.get('/api/v1/overview/widget/servers_list').get_data(as_text=True)
        assert 'mine-01' in body and 'secret-box' not in body
        cov = c.get('/api/v1/overview/widget/coverage').get_json()['content']
        assert cov['badges'][0]['args'][1] == 1, cov          # monitored / TOTAL

    def test_devices_view_still_sees_the_fleet(self, admin):
        st = admin._devices_store
        st.create({'name': 'mine-01', 'address': '10.0.0.1'}, actor='t')
        st.create({'name': 'other-02', 'address': '10.0.0.2'}, actor='t')
        c = _login_as(admin, 'dv', perms=['devices_view', 'overview_view'])
        body = c.get('/api/v1/overview/widget/servers_list').get_data(as_text=True)
        assert 'mine-01' in body and 'other-02' in body


# ─────────────────────── IDOR-4: module overview widgets ────────────────────────────
class TestModuleWidgetsHonourTheirPerm:

    @staticmethod
    def _seed(admin):
        admin._save_modules({'proxmox': {'enabled': True, 'list': {
            'pc1': {'enabled': True, 'label': 'Cluster-Finance'}}}})
        admin._check_state_store.persist_status({'proxmox': {
            'pc1/cluster': {'status': True, 'other_data': {'quorate': True}}}})

    def test_overview_view_alone_gets_no_module_widget(self, admin):
        self._seed(admin)
        c = _login_as(admin, 'ovonly', perms=['overview_view'])
        r = c.get('/api/v1/modules/overview')
        assert r.status_code == 200
        assert 'proxmox' not in (r.get_json().get('module_widgets') or {})

    def test_the_declared_perm_or_the_module_view_opens_it(self, admin):
        self._seed(admin)
        for perms in (['overview_view', 'modules_view'],
                      ['overview_view', 'module.proxmox.view']):
            c = _login_as(admin, 'ov' + str(len(perms[1])), perms=perms)
            j = c.get('/api/v1/modules/overview').get_json()
            assert 'proxmox' in (j.get('module_widgets') or {}), perms


# ─────────────────────────────── IDOR-5: /status ────────────────────────────────────
class TestStatusPageDetailNeedsChecksView:

    @staticmethod
    def _seed(admin, public):
        admin._save_modules({'ping': {'enabled': True, 'list': {
            'k1': {'enabled': True, 'label': 'Payroll-DB-Primary'}}}})
        admin._check_state_store.persist_status({'ping': {'k1': {
            'status': False, 'other_data': {'message': 'host 10.20.30.40 unreachable'}}}})
        admin._PUBLIC_STATUS = public
        admin._PUBLIC_STATUS_DETAIL = False

    def test_signed_in_without_checks_view_and_not_public_is_404(self, admin):
        self._seed(admin, public=False)
        c = _login_as(admin, 'dcimonly', perms=['dcim_view'])
        assert c.get('/status').status_code == 404

    def test_signed_in_without_checks_view_gets_the_public_summary(self, admin):
        self._seed(admin, public=True)
        c = _login_as(admin, 'dcimonly', perms=['dcim_view'])
        r = c.get('/status')
        assert r.status_code == 200
        assert 'Payroll-DB-Primary' not in r.get_data(as_text=True)
        r = c.get('/status?fragment=1')
        assert 'Payroll-DB-Primary' not in r.get_data(as_text=True)

    def test_a_guest_gets_the_summary_only(self, admin, client):
        self._seed(admin, public=True)
        r = client.get('/status')
        assert r.status_code == 200
        assert 'Payroll-DB-Primary' not in r.get_data(as_text=True)

    def test_checks_view_sees_the_detail(self, admin):
        self._seed(admin, public=False)
        c = _login_as(admin, 'viewer1', perms=['checks_view'])
        r = c.get('/status')
        assert r.status_code == 200
        assert 'Payroll-DB-Primary' in r.get_data(as_text=True)
