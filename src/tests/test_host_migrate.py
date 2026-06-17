#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the assisted host-migration planner (lib/hosts/migrate.py)."""

from lib.hosts.migrate import build_migration_plan, apply_to_modules


def _by_addr(plan):
    return {c['address']: c for c in plan['candidates']}


class TestPlan:

    def test_merges_duplicates_and_cross_module(self):
        mods = {
            'watchfuls.snmp': {'servers': {
                'r1':  {'host': '10.0.0.1', 'community': 'public', 'version': '2c',
                        'checks': {'c': {'oid': 'x'}}, 'uid': 's1'},
                'r1b': {'host': '10.0.0.1', 'community': 'public', 'version': '2c', 'uid': 's2'},
            }},
            'watchfuls.ping': {'list': {
                'p1': {'host': '10.0.0.1', 'timeout': 5, 'uid': 'p1'},
            }},
        }
        plan = build_migration_plan(mods)
        assert plan['total_items'] == 3
        c = _by_addr(plan)['10.0.0.1']
        assert c['is_duplicate'] is True
        assert {m['key'] for m in c['members']} == {'r1', 'r1b', 'p1'}
        # Host profiles are address-only now (snmp community/version are
        # per-check), so the candidate carries no protocol creds.
        assert c['profiles'] == {}
        assert set(c['modules']) == {'snmp', 'ping'}

    def test_same_address_merges_regardless_of_settings(self):
        # community is per-check now, so two SNMP servers at the same address
        # merge into one host (each check keeps its own community).
        mods = {'watchfuls.snmp': {'servers': {
            'a': {'host': '1.1.1.1', 'community': 'public', 'uid': 'a'},
            'b': {'host': '1.1.1.1', 'community': 'private', 'uid': 'b'},
        }}}
        plan = build_migration_plan(mods)
        cands = [c for c in plan['candidates'] if c['address'] == '1.1.1.1']
        assert len(cands) == 1 and len(cands[0]['members']) == 2

    def test_different_address_separate(self):
        mods = {'watchfuls.ping': {'list': {
            'p1': {'host': '10.0.0.1', 'uid': 'p1'},
            'p2': {'host': '10.0.0.2', 'uid': 'p2'},
        }}}
        plan = build_migration_plan(mods)
        assert len(plan['candidates']) == 2
        assert all(not c['is_duplicate'] for c in plan['candidates'])

    def test_skips_already_bound_and_empty_address(self):
        mods = {'watchfuls.ping': {'list': {
            'bound':  {'host': '10.0.0.1', 'host_uid': 'H', 'uid': 'b'},
            'empty':  {'host': '', 'uid': 'e'},
            'ok':     {'host': '10.0.0.9', 'uid': 'o'},
        }}}
        plan = build_migration_plan(mods)
        assert plan['total_items'] == 1
        assert plan['candidates'][0]['address'] == '10.0.0.9'

    def test_datastore_ssh_profile_db_creds_stay_on_check(self):
        mods = {'watchfuls.datastore': {'list': {
            'db1': {'host': 'db.local', 'db_type': 'postgres', 'user': 'u',
                    'password': 'p', 'ssh_host': 'jump', 'ssh_user': 'j',
                    'conn_type': 'ssh', 'uid': 'd1'},
        }}}
        plan = build_migration_plan(mods)
        # The host is the SSH server ('jump'): datastore's DB endpoint ('host')
        # is now an editable per-check field (like web's 'url'), not a host
        # profile — so only the ssh tunnel is shared.  The per-DB connection
        # (host/user/password) stays on the check, letting one host run several
        # DBs, possibly tunnelled to different boxes (docker/internal).
        c = _by_addr(plan)['jump']
        assert c['protocols'] == ['ssh']
        assert c['profiles']['ssh'] == {'ssh_user': 'j'}
        assert 'db' not in c['profiles']


class TestApply:

    def test_strips_connection_and_sets_host_uid(self):
        mods = {
            'watchfuls.snmp': {'servers': {
                'r1': {'host': '10.0.0.1', 'community': 'public', 'version': '2c',
                       'enabled': True, 'checks': {'c': {'oid': 'x'}}, 'uid': 's1'}}},
            'watchfuls.ping': {'list': {
                'p1': {'host': '10.0.0.1', 'timeout': 5, 'uid': 'p1'}}},
        }
        plan = build_migration_plan(mods)
        cand = _by_addr(plan)['10.0.0.1']
        apply_to_modules(mods, [{'uid': 'HOST-A', 'members': cand['members']}])

        r1 = mods['watchfuls.snmp']['servers']['r1']
        assert r1['host_uid'] == 'HOST-A'
        # Only the host-owned address is stripped; per-check settings stay.
        assert 'host' not in r1
        assert r1['community'] == 'public' and r1['version'] == '2c'
        assert r1['checks'] == {'c': {'oid': 'x'}}
        assert r1['enabled'] is True and r1['uid'] == 's1'

        p1 = mods['watchfuls.ping']['list']['p1']
        assert p1['host_uid'] == 'HOST-A' and 'host' not in p1
        assert p1['timeout'] == 5

    def test_apply_ignores_unknown_members(self):
        mods = {'watchfuls.ping': {'list': {'p1': {'host': '1.2.3.4', 'uid': 'p1'}}}}
        apply_to_modules(mods, [{'uid': 'H', 'members': [
            {'module': 'watchfuls.ping', 'collection': 'list', 'key': 'nope'},
            {'module': 'watchfuls.ping', 'collection': 'list', 'key': 'p1'},
        ]}])
        assert mods['watchfuls.ping']['list']['p1']['host_uid'] == 'H'
