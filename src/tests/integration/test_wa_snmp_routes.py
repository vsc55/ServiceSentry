#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SNMP answers for itself: ``/api/v1/snmp/<action>``.

The library, the catalogue and asking a device used to be reachable only at
``/api/v1/modules/watchfuls/snmp/<action>`` — a path that described where the code lived
rather than what the endpoint is about, and a gate (``modules_view``) that could not tell
"let this person compile MIBs" from "let this person see every module in the panel".

What these pin is the gate, because that is the part with a cost when it is wrong: an
operation reachable by somebody who should not reach it, or a read that quietly demands
write rights and audits a row for every look.
"""

import os
import pathlib

import pytest

from lib.web_admin import WebAdmin
from tests.conftest import _login

_WATCHFULS_DIR = os.path.join(
    os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0], 'watchfuls')


@pytest.fixture()
def wa(tmp_path):
    config_dir = str(tmp_path / 'config')
    var_dir = str(tmp_path / 'var')
    os.makedirs(config_dir, exist_ok=True)
    os.makedirs(var_dir, exist_ok=True)
    (pathlib.Path(config_dir) / 'config.json').write_text('{}', encoding='utf-8')
    admin = WebAdmin(config_dir, 'admin', 'secret', var_dir,
                     modules_dir=_WATCHFULS_DIR,
                     pw_require_upper=False, pw_require_digit=False)
    admin.app.config['TESTING'] = True
    return admin


@pytest.fixture()
def client(wa):
    return wa.app.test_client()


def _as(wa, client, role):
    """Log in as a user of *role* (admin is already there)."""
    if role != 'admin':
        wa._users[role] = {'password_hash': wa._users['admin']['password_hash'],
                           'role': role, 'display_name': role.title()}
    _login(client, role)


class TestTheSurfaceExists:

    def test_a_read_only_action_answers(self, wa, client):
        _as(wa, client, 'admin')
        res = client.post('/api/v1/snmp/list_mibs', json={})
        assert res.status_code == 200
        assert isinstance(res.get_json(), dict)

    def test_it_also_answers_a_get(self, wa, client):
        """The module route did, and the capability was not worth narrowing on the way past:
        listing a library is a read, and a read is a GET."""
        _as(wa, client, 'admin')
        assert client.get('/api/v1/snmp/list_mibs').status_code == 200

    def test_an_unknown_action_is_a_404_and_not_a_500(self, wa, client):
        _as(wa, client, 'admin')
        assert client.post('/api/v1/snmp/rm_rf', json={}).status_code == 404

    def test_an_action_of_the_module_is_not_reachable_here(self, wa, client):
        """`discover` finds OIDs for the field of a check, so it stays a check's action. The
        split is by what an operation is ABOUT, and a surface that quietly accepted both
        would make that line meaningless."""
        _as(wa, client, 'admin')
        assert client.post('/api/v1/snmp/discover', json={}).status_code == 404


class TestTheGate:

    def test_anonymous_is_refused(self, client):
        res = client.post('/api/v1/snmp/list_mibs', json={})
        assert res.status_code in (401, 403)

    def test_a_viewer_may_read_the_library(self, wa, client):
        """`snmp_view` goes to viewer: reading a MIB library tells you what the panel can
        measure, which is the same kind of fact as the rest of what a viewer sees."""
        _as(wa, client, 'viewer')
        assert client.post('/api/v1/snmp/list_mibs', json={}).status_code == 200

    def test_a_viewer_may_not_change_it(self, wa, client):
        """The one that matters. Compiling, importing and deleting are `snmp_manage`, and a
        read-only flag that let any of them through would be a write anybody who can look
        can do."""
        _as(wa, client, 'viewer')
        for action in ('build_oid_index', 'clean_library', 'delete_mib', 'save_profile'):
            res = client.post(f'/api/v1/snmp/{action}', json={})
            assert res.status_code == 403, f'{action} was allowed'

    def test_an_editor_may_change_it(self, wa, client):
        _as(wa, client, 'editor')
        res = client.post('/api/v1/snmp/list_profiles', json={})
        assert res.status_code == 200
        # A write reaches the operation rather than the gate: whatever it answers, it is not
        # a refusal.
        assert client.post('/api/v1/snmp/save_profile', json={}).status_code != 403

    def test_the_modules_permission_no_longer_opens_it(self, wa, client):
        """The clean cut. A role with `modules_view` and nothing else used to reach the whole
        SNMP surface, because a watchful owned no flags of its own — which is exactly what
        made "grant the MIB library" impossible to say."""
        wa._custom_roles['_snmp_none'] = {'label': '_snmp_none',
                                          'permissions': ['modules_view']}
        wa._users['modonly'] = {'password_hash': wa._users['admin']['password_hash'],
                                'role': '_snmp_none', 'display_name': 'Mod'}
        _login(client, 'modonly')
        assert client.post('/api/v1/snmp/list_mibs', json={}).status_code == 403
