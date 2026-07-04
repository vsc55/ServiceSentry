#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the SCIM 2.0 provisioning endpoints (/scim/v2/*)."""

import json
import os

_TOK = 'testtoken'
_AUTH = {'Authorization': f'Bearer {_TOK}'}


def _scim_cfg(wa, config_dir, token=_TOK, enabled=True, extra=None):
    p = os.path.join(config_dir, 'config.json')
    try:
        with open(p, encoding='utf-8') as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    cfg['scim'] = {'enabled': enabled, 'token': token, 'default_role': '',
                   'auto_disable': True, **(extra or {})}
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)
    wa._config_mgr.invalidate()
    wa._read_config_file(wa._CONFIG_FILE)


class TestScimAuth:
    def test_disabled_rejected(self, admin, config_dir):
        _scim_cfg(admin, config_dir, enabled=False)
        client = admin.app.test_client()
        r = client.get('/scim/v2/ServiceProviderConfig', headers=_AUTH)
        assert r.status_code == 401

    def test_no_token_rejected(self, admin, config_dir):
        _scim_cfg(admin, config_dir)
        client = admin.app.test_client()
        assert client.get('/scim/v2/Users').status_code == 401

    def test_wrong_token_rejected(self, admin, config_dir):
        _scim_cfg(admin, config_dir)
        client = admin.app.test_client()
        r = client.get('/scim/v2/Users', headers={'Authorization': 'Bearer nope'})
        assert r.status_code == 401

    def test_spconfig_ok(self, admin, config_dir):
        _scim_cfg(admin, config_dir)
        client = admin.app.test_client()
        r = client.get('/scim/v2/ServiceProviderConfig', headers=_AUTH)
        assert r.status_code == 200
        assert r.get_json()['patch']['supported'] is True


class TestScimUsers:
    def _c(self, admin, config_dir):
        _scim_cfg(admin, config_dir)
        return admin.app.test_client()

    def test_create_user(self, admin, config_dir):
        client = self._c(admin, config_dir)
        r = client.post('/scim/v2/Users', headers=_AUTH, json={
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User'],
            'userName': 'jane@corp.com', 'externalId': 'ext-1',
            'displayName': 'Jane Doe',
            'emails': [{'value': 'jane@corp.com', 'primary': True}], 'active': True})
        assert r.status_code == 201
        body = r.get_json()
        assert body['userName'] == 'jane@corp.com' and body['id']
        u = admin._users['jane@corp.com']
        assert u['auth_source'] == 'scim' and u['email'] == 'jane@corp.com'
        assert u['auth_source_id'] == 'ext-1' and u['enabled'] is True

    def test_duplicate_conflicts(self, admin, config_dir):
        client = self._c(admin, config_dir)
        payload = {'userName': 'dup', 'active': True}
        assert client.post('/scim/v2/Users', headers=_AUTH, json=payload).status_code == 201
        assert client.post('/scim/v2/Users', headers=_AUTH, json=payload).status_code == 409

    def test_filter_by_username(self, admin, config_dir):
        client = self._c(admin, config_dir)
        client.post('/scim/v2/Users', headers=_AUTH, json={'userName': 'bob', 'active': True})
        r = client.get('/scim/v2/Users?filter=userName eq "bob"', headers=_AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data['totalResults'] == 1 and data['Resources'][0]['userName'] == 'bob'
        # Unknown user → empty list, not 404 (Entra existence probe).
        r2 = client.get('/scim/v2/Users?filter=userName eq "ghost"', headers=_AUTH)
        assert r2.get_json()['totalResults'] == 0

    def test_get_and_patch_deactivate(self, admin, config_dir):
        client = self._c(admin, config_dir)
        uid = client.post('/scim/v2/Users', headers=_AUTH,
                          json={'userName': 'carl', 'active': True}).get_json()['id']
        assert client.get(f'/scim/v2/Users/{uid}', headers=_AUTH).status_code == 200
        r = client.patch(f'/scim/v2/Users/{uid}', headers=_AUTH, json={
            'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
            'Operations': [{'op': 'replace', 'value': {'active': False}}]})
        assert r.status_code == 200 and r.get_json()['active'] is False
        assert admin._users['carl']['enabled'] is False

    def test_delete_user(self, admin, config_dir):
        client = self._c(admin, config_dir)
        uid = client.post('/scim/v2/Users', headers=_AUTH,
                          json={'userName': 'tmp', 'active': True}).get_json()['id']
        assert client.delete(f'/scim/v2/Users/{uid}', headers=_AUTH).status_code == 204
        assert 'tmp' not in admin._users

    def test_missing_username_400(self, admin, config_dir):
        client = self._c(admin, config_dir)
        assert client.post('/scim/v2/Users', headers=_AUTH, json={'active': True}).status_code == 400

    def test_update_audits_before_after(self, admin, config_dir):
        client = self._c(admin, config_dir)
        uid = client.post('/scim/v2/Users', headers=_AUTH,
                          json={'userName': 'aud', 'active': True}).get_json()['id']
        client.patch(f'/scim/v2/Users/{uid}', headers=_AUTH, json={
            'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
            'Operations': [{'op': 'replace', 'value': {'active': False}}]})
        # The update is audited with before/after of ONLY the changed field (enabled),
        # not the whole snapshot (email/display_name/… are unchanged → absent).
        entry = next(e for e in reversed(admin._audit_log) if e['event'] == 'scim_user_updated')
        assert entry['detail']['before'] == {'enabled': True}
        assert entry['detail']['after'] == {'enabled': False}
        # A no-op update (same values) records no further scim_user_updated entry.
        n_before = sum(1 for e in admin._audit_log if e['event'] == 'scim_user_updated')
        client.patch(f'/scim/v2/Users/{uid}', headers=_AUTH, json={
            'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
            'Operations': [{'op': 'replace', 'value': {'active': False}}]})
        n_after = sum(1 for e in admin._audit_log if e['event'] == 'scim_user_updated')
        assert n_after == n_before


class TestScimGroups:
    def _c(self, admin, config_dir):
        _scim_cfg(admin, config_dir)
        return admin.app.test_client()

    def test_create_group_with_members(self, admin, config_dir):
        client = self._c(admin, config_dir)
        uid = client.post('/scim/v2/Users', headers=_AUTH,
                          json={'userName': 'gm', 'active': True}).get_json()['id']
        r = client.post('/scim/v2/Groups', headers=_AUTH, json={
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:Group'],
            'displayName': 'Ops', 'members': [{'value': uid}]})
        assert r.status_code == 201
        gid = r.get_json()['id']
        assert admin._groups[gid]['name'] == 'Ops'
        assert admin._groups[gid]['source'] == 'scim'          # tagged as IdP-managed
        assert gid in admin._users['gm']['groups']
        # source survives a persist + reload round-trip.
        assert admin._groups_store.load()[gid]['source'] == 'scim'
        # Membership reflected on read.
        members = client.get(f'/scim/v2/Groups/{gid}', headers=_AUTH).get_json()['members']
        assert members and members[0]['value'] == uid

    def test_patch_remove_member(self, admin, config_dir):
        client = self._c(admin, config_dir)
        uid = client.post('/scim/v2/Users', headers=_AUTH,
                          json={'userName': 'gm2', 'active': True}).get_json()['id']
        gid = client.post('/scim/v2/Groups', headers=_AUTH,
                          json={'displayName': 'Team', 'members': [{'value': uid}]}).get_json()['id']
        r = client.patch(f'/scim/v2/Groups/{gid}', headers=_AUTH, json={
            'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
            'Operations': [{'op': 'remove', 'path': 'members', 'value': [{'value': uid}]}]})
        assert r.status_code == 200
        assert gid not in admin._users['gm2']['groups']

    def test_delete_group_unlinks_members(self, admin, config_dir):
        client = self._c(admin, config_dir)
        uid = client.post('/scim/v2/Users', headers=_AUTH,
                          json={'userName': 'gm3', 'active': True}).get_json()['id']
        gid = client.post('/scim/v2/Groups', headers=_AUTH,
                          json={'displayName': 'Gone', 'members': [{'value': uid}]}).get_json()['id']
        assert client.delete(f'/scim/v2/Groups/{gid}', headers=_AUTH).status_code == 204
        assert gid not in admin._groups
        assert gid not in admin._users['gm3']['groups']
