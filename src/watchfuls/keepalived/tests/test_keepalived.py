#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/keepalived.

The check binds one item to several member hosts and probes each over
``host_exec`` (SVC state + ``ip addr`` dump). Both ``resolve_host`` (host
registry) and ``host_exec`` (SSH/local) are patched so the tests stay hermetic
and exercise only the per-node + VIP roll-up aggregation.
"""

from unittest.mock import patch

from conftest import create_mock_monitor

VIP = '192.168.1.50'


def _members(*uids):
    return [{'host_uid': u, 'name': u, 'address': f'10.0.0.{i + 1}', 'maintenance': False}
            for i, u in enumerate(uids)]


def _out(state, addrs):
    lines = [f'SVC={state}'] + [f'2: eth0    inet {a}/24 scope global eth0' for a in addrs]
    return '\n'.join(lines) + '\n'


def _run(item, members, exec_map, priorities=None):
    """Run check() for a single keepalived item with patched host access.

    *exec_map*: ``{uid: (stdout, stderr, code)}`` returned by host_exec for that
    member (missing uid → unreachable). *priorities*: ``{uid: priority}``.
    """
    from watchfuls.keepalived import Watchful
    config = {'watchfuls.keepalived': {'threads': 1, 'alert': 3, 'list': {'k1': item}}}
    w = Watchful(create_mock_monitor(config))
    prio = priorities or {}

    def fake_resolve(arg):
        # Per-member connection lookup: {'host_uid': uid} (no cluster fields).
        if isinstance(arg, dict) and 'host_uid' in arg and '__cluster_members__' not in arg \
                and 'label' not in arg:
            uid = arg['host_uid']
            return {'host_uid': uid, 'ssh_host': uid, 'host_kind': 'remote',
                    'enabled': True, 'priority': prio.get(uid)}
        return {**arg, '__cluster_members__': members}

    def fake_exec(mi, cmd, timeout=15):
        return exec_map.get(mi.get('ssh_host'), ('', 'unreachable', -1))

    with patch.object(w, 'resolve_host', side_effect=fake_resolve), \
         patch.object(w, 'host_exec', side_effect=fake_exec):
        return w.check().list


def _item(**over):
    base = {'enabled': True, 'label': 'web', 'vip': VIP,
            'check_service': True, 'check_vip': True, 'check_priority': False}
    base.update(over)
    return base


class TestKeepalivedBasics:

    def test_init(self):
        from watchfuls.keepalived import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.keepalived': {}}))
        assert w.name_module == 'watchfuls.keepalived'

    def test_schema_is_cluster(self):
        from watchfuls.keepalived import Watchful
        sch = Watchful.ITEM_SCHEMA
        assert sch['__host_multiple_bind__'] is True
        assert sch['list']['__cluster_columns__'] == ['vip']
        assert sch['list']['__member_field__']['key'] == 'priority'

    def test_declares_vip_provision_host(self):
        """The VIP is auto-provisioned as a host via the generic core hook: the
        module declares __provision_host__ (address_field vip → vip_host_uid)."""
        from watchfuls.keepalived import Watchful
        decl = Watchful.ITEM_SCHEMA['list']['__provision_host__']
        assert decl['address_field'] == 'vip'
        assert decl['link_field'] == 'vip_host_uid'
        assert '{label}' in decl['name_template']


class TestVipRollup:

    def test_healthy_single_master(self):
        res = _run(_item(), _members('a', 'b', 'c'), {
            'a': (_out('active', ['10.0.0.1', VIP]), '', 0),   # MASTER (holds VIP)
            'b': (_out('active', ['10.0.0.2']), '', 0),
            'c': (_out('active', ['10.0.0.3']), '', 0),
        })
        assert res['k1/vip']['status'] is True
        assert res['k1/node/a']['status'] is True
        assert res['k1/node/a']['other_data']['holds_vip'] is True
        assert res['k1/node/b']['other_data']['holds_vip'] is False

    def test_vip_down_no_holder(self):
        res = _run(_item(), _members('a', 'b'), {
            'a': (_out('active', ['10.0.0.1']), '', 0),
            'b': (_out('active', ['10.0.0.2']), '', 0),
        })
        assert res['k1/vip']['status'] is False
        assert res['k1/vip']['severity'] != 'warning'      # hard error: VIP down

    def test_split_brain_is_warning(self):
        res = _run(_item(), _members('a', 'b'), {
            'a': (_out('active', ['10.0.0.1', VIP]), '', 0),
            'b': (_out('active', ['10.0.0.2', VIP]), '', 0),
        })
        assert res['k1/vip']['status'] is False
        assert res['k1/vip']['severity'] == 'warning'
        assert res['k1/vip']['other_data']['holders'] == 2

    def test_service_down_node_fails(self):
        res = _run(_item(), _members('a', 'b'), {
            'a': (_out('active', ['10.0.0.1', VIP]), '', 0),
            'b': (_out('inactive', ['10.0.0.2']), '', 0),
        })
        assert res['k1/node/b']['status'] is False
        assert res['k1/vip']['status'] is True             # a still holds it fine

    def test_unreachable_node(self):
        res = _run(_item(), _members('a', 'b'), {
            'a': (_out('active', ['10.0.0.1', VIP]), '', 0),
            # 'b' missing → host_exec returns unreachable
        })
        assert res['k1/node/b']['status'] is False

    def test_maintenance_member_skipped(self):
        members = _members('a', 'b')
        members[1]['maintenance'] = True
        res = _run(_item(), members, {
            'a': (_out('active', ['10.0.0.1', VIP]), '', 0),
        })
        assert 'k1/node/b' not in res                      # skipped, not failed
        assert res['k1/vip']['status'] is True


class TestPriority:

    def test_priority_ok_on_highest(self):
        res = _run(_item(check_priority=True), _members('a', 'b'), {
            'a': (_out('active', ['10.0.0.1', VIP]), '', 0),
            'b': (_out('active', ['10.0.0.2']), '', 0),
        }, priorities={'a': 150, 'b': 100})
        assert res['k1/priority']['status'] is True

    def test_priority_warns_when_lower_holds_vip(self):
        res = _run(_item(check_priority=True), _members('a', 'b'), {
            'a': (_out('active', ['10.0.0.1', VIP]), '', 0),   # holds VIP, prio 100
            'b': (_out('active', ['10.0.0.2']), '', 0),        # active, prio 150
        }, priorities={'a': 100, 'b': 150})
        assert res['k1/priority']['status'] is False
        assert res['k1/priority']['severity'] == 'warning'
        assert res['k1/priority']['other_data']['top_priority'] == 150


class TestVipConfig:

    def test_missing_vip_warns(self):
        res = _run(_item(vip=''), _members('a'), {
            'a': (_out('active', ['10.0.0.1']), '', 0),
        })
        assert res['k1/vip']['status'] is False
        assert res['k1/vip']['severity'] == 'warning'

    def test_no_members_warns(self):
        res = _run(_item(), [], {})
        assert res['k1']['status'] is False
        assert res['k1']['severity'] == 'warning'
