#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/proxmox.

The check connects once per item (``_connect``) and queries the cluster through
the stateless API helper ``_pve_get(conn, path)``, which is patched here with a
``{path: data}`` map so the tests stay hermetic (no network). The SSRF guard is
neutralised so ``_connect`` does not hit DNS.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from conftest import create_mock_monitor


@pytest.fixture(autouse=True)
def _no_ssrf_guard():
    with patch('lib.net_guard.validate_external_url', return_value=None):
        yield


def _item(**over):
    base = {
        'enabled': True, 'label': 'PVE', 'host': '10.0.0.1', 'port': 8006,
        'verify_ssl': False, 'auth_method': 'token',
        'token_id': 'mon@pve!ss', 'token_secret': 'uuid-secret',
        'check_cluster': False, 'check_nodes': False, 'check_ceph': False,
        'check_network': False, 'check_updates': False, 'updates_threshold': 1,
    }
    base.update(over)
    return base


def _run(item, api_map):
    """Build a Watchful with one item and run check() with _pve_get patched.

    *api_map* maps an API path → data (or a callable raising for errors).
    """
    from watchfuls.proxmox import Watchful
    config = {'watchfuls.proxmox': {'threads': 1, 'alert': 3, 'list': {'pve': item}}}
    w = Watchful(create_mock_monitor(config))

    def fake_get(conn, path):
        if path == '/version' and path not in api_map:
            return {'version': '8.0'}        # connection probe
        val = api_map[path]
        if callable(val):
            return val()
        return val

    with patch.object(w, '_pve_get', side_effect=fake_get):
        return w.check().list


class TestProxmoxInit:

    def test_init(self):
        from watchfuls.proxmox import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.proxmox': {}}))
        assert w.name_module == 'watchfuls.proxmox'

    def test_schema(self):
        from watchfuls.proxmox import Watchful
        lst = Watchful.ITEM_SCHEMA['list']
        assert lst['host']['default'] == ''
        assert lst['auth_method']['options'] == ['token', 'password']
        assert lst['port']['default'] == 8006
        assert lst['verify_ssl']['default'] is False


class TestProxmoxCheck:

    def test_empty_list(self):
        from watchfuls.proxmox import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.proxmox': {'list': {}}}))
        assert len(w.check().items()) == 0

    def test_disabled_item(self):
        res = _run(_item(enabled=False, check_cluster=True), {})
        assert len(res) == 0

    # ── cluster ──────────────────────────────────────────────────────────

    def test_cluster_quorate_ok(self):
        api = {'/cluster/status': [
            {'type': 'cluster', 'name': 'lab', 'quorate': 1},
            {'type': 'node', 'name': 'n1', 'online': 1},
            {'type': 'node', 'name': 'n2', 'online': 1},
        ]}
        res = _run(_item(check_cluster=True), api)
        assert res['pve/cluster']['status'] is True
        assert res['pve/cluster']['other_data']['nodes_online'] == 2

    def test_cluster_quorum_lost(self):
        api = {'/cluster/status': [
            {'type': 'cluster', 'name': 'lab', 'quorate': 0},
            {'type': 'node', 'name': 'n1', 'online': 1},
        ]}
        res = _run(_item(check_cluster=True), api)
        assert res['pve/cluster']['status'] is False

    def test_cluster_standalone(self):
        api = {'/cluster/status': [{'type': 'node', 'name': 'n1', 'online': 1}]}
        res = _run(_item(check_cluster=True), api)
        assert res['pve/cluster']['status'] is True
        assert res['pve/cluster']['other_data'].get('standalone') is True

    def test_cluster_caches_node_ips(self):
        api = {'/cluster/status': [
            {'type': 'cluster', 'name': 'lab', 'quorate': 1},
            {'type': 'node', 'name': 'n1', 'online': 1, 'ip': '10.0.0.5'},
            {'type': 'node', 'name': 'n2', 'online': 1, 'ip': '10.0.0.6'},
        ]}
        res = _run(_item(check_cluster=True), api)
        assert res['pve/cluster']['other_data']['node_ips'] == ['10.0.0.5', '10.0.0.6']

    def test_connection_failover_between_nodes(self):
        """A cluster has several nodes: if the first configured address is down,
        the check fails over to the next and still succeeds."""
        from watchfuls.proxmox import Watchful, PveError
        config = {'watchfuls.proxmox': {'threads': 1, 'alert': 3, 'list': {
            'pve': _item(host='10.0.0.1, 10.0.0.2', check_cluster=True)}}}
        w = Watchful(create_mock_monitor(config))
        api = {'/cluster/status': [
            {'type': 'cluster', 'name': 'lab', 'quorate': 1},
            {'type': 'node', 'name': 'n1', 'online': 1, 'ip': '10.0.0.2'},
        ]}

        def fake_get(conn, path):
            if '10.0.0.1' in conn['base']:
                raise PveError(0, 'node down')        # first node unreachable
            if path == '/version':
                return {'version': '8.0'}
            return api[path]

        with patch.object(w, '_pve_get', side_effect=fake_get):
            res = w.check().list
        assert res['pve/cluster']['status'] is True   # failed over to the 2nd node

    # ── nodes / maintenance ──────────────────────────────────────────────

    def test_nodes_online_offline_maintenance(self):
        api = {
            '/nodes': [
                {'node': 'n1', 'status': 'online'},
                {'node': 'n2', 'status': 'offline'},
                {'node': 'n3', 'status': 'online'},
            ],
            '/cluster/ha/status/current': [
                {'type': 'node', 'node': 'n3', 'status': 'maintenance'},
            ],
        }
        res = _run(_item(check_nodes=True), api)
        assert res['pve/node/n1']['status'] is True
        assert res['pve/node/n2']['status'] is False          # offline
        assert res['pve/node/n3']['status'] is True           # maintenance = ok
        assert res['pve/node/n3']['other_data'].get('maintenance') is True

    def test_nodes_without_ha(self):
        from watchfuls.proxmox import PveError
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/cluster/ha/status/current': lambda: (_ for _ in ()).throw(PveError(400, 'no ha')),
        }
        res = _run(_item(check_nodes=True), api)
        assert res['pve/node/n1']['status'] is True            # HA error → not maintenance

    # ── ceph ─────────────────────────────────────────────────────────────

    def test_ceph_ok(self):
        api = {'/cluster/ceph/status': {'health': {'status': 'HEALTH_OK'}}}
        res = _run(_item(check_ceph=True), api)
        assert res['pve/ceph']['status'] is True

    def test_ceph_warn(self):
        api = {'/cluster/ceph/status': {'health': {'status': 'HEALTH_WARN'}}}
        res = _run(_item(check_ceph=True), api)
        assert res['pve/ceph']['status'] is False

    def test_ceph_not_configured(self):
        from watchfuls.proxmox import PveError
        api = {'/cluster/ceph/status':
               lambda: (_ for _ in ()).throw(PveError(500, "rados_connect failed - No such file"))}
        res = _run(_item(check_ceph=True), api)
        assert res['pve/ceph']['status'] is True               # not installed → ok/info

    # ── network ──────────────────────────────────────────────────────────

    def test_network_iface_down(self):
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/nodes/n1/network': [
                {'iface': 'lo', 'type': 'loopback', 'autostart': 1, 'active': 1},
                {'iface': 'vmbr0', 'type': 'bridge', 'autostart': 1, 'active': 1},
                {'iface': 'eth1', 'type': 'eth', 'autostart': 1},          # no 'active' → down
            ],
        }
        res = _run(_item(check_network=True), api)
        assert res['pve/net/n1']['status'] is False
        assert 'eth1' in res['pve/net/n1']['other_data']['down']

    def test_network_all_up(self):
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/nodes/n1/network': [
                {'iface': 'vmbr0', 'type': 'bridge', 'autostart': 1, 'active': 1},
            ],
        }
        res = _run(_item(check_network=True), api)
        assert res['pve/net/n1']['status'] is True

    # ── updates ──────────────────────────────────────────────────────────

    def test_updates_security_alerts(self):
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/nodes/n1/apt/update': [
                {'Package': 'libc', 'Origin': 'Debian:bookworm-security'},
                {'Package': 'foo', 'Origin': 'Debian'},
            ],
        }
        res = _run(_item(check_updates=True, updates_threshold=1), api)
        assert res['pve/updates/n1']['status'] is False        # security → alert
        assert res['pve/updates/n1']['other_data']['security'] == 1

    def test_updates_count_informational(self):
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/nodes/n1/apt/update': [{'Package': 'foo', 'Origin': 'Debian'},
                                     {'Package': 'bar', 'Origin': 'Proxmox'}],
        }
        res = _run(_item(check_updates=True, updates_threshold=1), api)
        assert res['pve/updates/n1']['status'] is True         # no security → ok
        assert res['pve/updates/n1']['other_data']['total'] == 2

    def test_updates_up_to_date(self):
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/nodes/n1/apt/update': [],
        }
        res = _run(_item(check_updates=True), api)
        assert res['pve/updates/n1']['status'] is True
        assert res['pve/updates/n1']['other_data']['total'] == 0

    # ── storage ──────────────────────────────────────────────────────────

    def test_storage_inactive_alerts(self):
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/nodes/n1/storage': [
                {'storage': 'local', 'enabled': 1, 'active': 1, 'used_fraction': 0.10},
                {'storage': 'nfs1', 'enabled': 1, 'active': 0},                # down
                {'storage': 'old', 'enabled': 0, 'active': 0},                 # disabled → ignored
            ],
        }
        res = _run(_item(check_storage=True, storage_threshold=90), api)
        assert res['pve/storage/n1']['status'] is False
        assert res['pve/storage/n1']['other_data']['down'] == ['nfs1']

    def test_storage_usage_over_threshold(self):
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/nodes/n1/storage': [
                {'storage': 'local', 'enabled': 1, 'active': 1, 'used': 95, 'total': 100},
            ],
        }
        res = _run(_item(check_storage=True, storage_threshold=90), api)
        assert res['pve/storage/n1']['status'] is False
        assert res['pve/storage/n1']['other_data']['full'] == ['local 95%']

    def test_storage_all_ok(self):
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/nodes/n1/storage': [
                {'storage': 'local', 'enabled': 1, 'active': 1, 'used_fraction': 0.42},
            ],
        }
        res = _run(_item(check_storage=True, storage_threshold=90), api)
        assert res['pve/storage/n1']['status'] is True

    def test_storage_threshold_zero_ignores_usage(self):
        """storage_threshold=0 → only alert on inactive, never on usage."""
        api = {
            '/nodes': [{'node': 'n1', 'status': 'online'}],
            '/nodes/n1/storage': [
                {'storage': 'local', 'enabled': 1, 'active': 1, 'used_fraction': 0.99},
            ],
        }
        res = _run(_item(check_storage=True, storage_threshold=0), api)
        assert res['pve/storage/n1']['status'] is True

    # ── maintenance (derived from member-host maintenance) ───────────────

    def test_maintenance_skips_per_node_checks(self):
        """An online node whose mapped host is in maintenance has its per-node
        checks (network here) skipped — its problems must not alert."""
        item = _item(check_network=True)
        item['__cluster_members__'] = [
            {'node': 'pve02', 'name': 'srv-2', 'host_uid': 'h2', 'maintenance': True}]
        api = {
            '/nodes': [{'node': 'pve01', 'status': 'online'},
                       {'node': 'pve02', 'status': 'online'}],
            '/nodes/pve01/network': [{'iface': 'eth0', 'type': 'eth', 'autostart': 1, 'active': 1}],
            '/nodes/pve02/network': [{'iface': 'eth0', 'type': 'eth', 'autostart': 1}],  # down
        }
        res = _run(item, api)
        assert 'pve/net/pve02' not in res            # maintenance → skipped, no alert
        assert res['pve/net/pve01']['status'] is True

    # ── cluster member ↔ host mapping ────────────────────────────────────

    def test_member_host_maintenance_skips_node(self):
        """A node whose mapped host is in maintenance is reported as maintenance
        (OK), not offline-error — and carries the host name."""
        item = _item(check_nodes=True)
        item['__cluster_members__'] = [
            {'node': 'pve02', 'name': 'srv-2', 'host_uid': 'h2', 'maintenance': True}]
        api = {'/nodes': [{'node': 'pve01', 'status': 'online'},
                          {'node': 'pve02', 'status': 'offline'}],
               '/cluster/ha/status/current': []}
        res = _run(item, api)
        assert res['pve/node/pve02']['status'] is True
        assert res['pve/node/pve02']['other_data'].get('maintenance') is True
        assert res['pve/node/pve02']['other_data'].get('host_name') == 'srv-2'

    def test_member_host_name_annotates_node(self):
        """An online node mapped to a host shows the host name in status."""
        item = _item(check_nodes=True)
        item['__cluster_members__'] = [
            {'node': 'pve01', 'name': 'srv-1', 'host_uid': 'h1', 'maintenance': False}]
        api = {'/nodes': [{'node': 'pve01', 'status': 'online'}],
               '/cluster/ha/status/current': []}
        res = _run(item, api)
        assert res['pve/node/pve01']['status'] is True
        assert res['pve/node/pve01']['other_data'].get('host_name') == 'srv-1'
        assert 'srv-1' in res['pve/node/pve01']['message']

    # ── VIP / cluster address ────────────────────────────────────────────

    def test_vip_used_when_no_host(self):
        """Only a VIP configured (no member host) still connects and runs."""
        api = {'/cluster/status': [{'type': 'cluster', 'name': 'lab', 'quorate': 1},
                                   {'type': 'node', 'name': 'n1', 'online': 1}]}
        res = _run(_item(host='', vip='cluster.lan', check_cluster=True), api)
        assert res['pve/cluster']['status'] is True

    def test_list_nodes_returns_member_names(self):
        from watchfuls.proxmox import Watchful

        def fake(conn, path):
            if path == '/version':
                return {'version': '8.0'}
            if path == '/cluster/status':
                return [{'type': 'cluster', 'name': 'lab'},
                        {'type': 'node', 'name': 'pve02'},
                        {'type': 'node', 'name': 'pve01'}]
            return []
        with patch.object(Watchful, '_connect', return_value={'conn': 1}), \
             patch.object(Watchful, '_pve_get', side_effect=fake):
            out = Watchful.list_nodes({'host': '10.0.0.1', 'auth_method': 'token',
                                       'token_id': 't', 'token_secret': 's'})
        assert out['ok'] is True
        assert out['items'] == ['pve01', 'pve02']        # sorted, deduped

    # ── connection failure ───────────────────────────────────────────────

    def test_connection_error_threshold(self):
        from watchfuls.proxmox import Watchful, PveError
        config = {'watchfuls.proxmox': {'threads': 1, 'alert': 2,
                                        'list': {'pve': _item(check_cluster=True)}}}
        w = Watchful(create_mock_monitor(config))
        with patch.object(w, '_connect', side_effect=PveError(0, 'timeout')):
            res = w.check().list
        # alert=2 → first failure is still "effective" (ok) until the streak hits 2
        assert 'pve' in res
        assert res['pve']['other_data'].get('error') == 'timeout'


class TestProxmoxAction:

    def test_test_connection_token(self):
        from watchfuls.proxmox import Watchful
        api = {
            '/version': {'version': '8.0'},
            '/cluster/status': [
                {'type': 'cluster', 'name': 'lab', 'quorate': 1},
                {'type': 'node', 'name': 'n1', 'online': 1},
            ],
            '/cluster/ceph/status': {'health': {'status': 'HEALTH_OK'}},
        }
        with patch.object(Watchful, '_pve_get', new=MagicMock(side_effect=lambda c, p: api[p])):
            out = Watchful.test_connection(
                {'host': '10.0.0.1', 'auth_method': 'token',
                 'token_id': 'a@pve!b', 'token_secret': 'x'})
        assert out['ok'] is True
        assert 'quórum OK' in out['message']

    def test_test_connection_password_ticket(self):
        """Password auth performs a login POST then the GET; both go through
        the low-level _request, patched here."""
        from watchfuls.proxmox import Watchful
        import json as _json

        def fake_request(url, *, method='GET', data=None, headers=None,
                         verify_ssl=True, timeout=10):
            if url.endswith('/access/ticket'):
                assert method == 'POST' and data['username'] == 'root@pam'
                return 200, _json.dumps({'data': {'ticket': 'T', 'CSRFPreventionToken': 'C'}})
            if url.endswith('/version'):
                assert headers.get('Cookie') == 'PVEAuthCookie=T'
                return 200, _json.dumps({'data': {'version': '8.0'}})
            if url.endswith('/cluster/status'):
                assert headers.get('Cookie') == 'PVEAuthCookie=T'
                return 200, _json.dumps({'data': [{'type': 'node', 'name': 'n1', 'online': 1}]})
            return 200, _json.dumps({'data': {}})

        with patch.object(Watchful, '_request', side_effect=fake_request):
            out = Watchful.test_connection(
                {'host': '10.0.0.1', 'auth_method': 'password',
                 'username': 'root@pam', 'password': 'pw'})
        assert out['ok'] is True
        assert 'standalone' in out['message'].lower()


class TestProxmoxProvision:
    """Provisioning connects over the shared ssh_client (the same SSH path the
    host-aware checks use), so the tests patch ssh_client.connect/run_command."""

    @contextmanager
    def _ssh(self, out='', err='', code=0, raise_exc=None):
        """Patch ssh_client so connect() yields a fake client and run_command()
        returns (out, err, code).  Yields (connect_mock, run_mock)."""
        with patch('lib.ssh_client.HAS_PARAMIKO', True), \
             patch('lib.ssh_client.connect') as conn, \
             patch('lib.ssh_client.run_command', return_value=(out, err, code)) as run:
            if raise_exc is not None:
                conn.side_effect = raise_exc
            else:
                conn.return_value = MagicMock()
            yield conn, run

    def test_provision_creates_token(self):
        from watchfuls.proxmox import Watchful
        token_json = ('{"full-tokenid":"servicesentry@pve!monitoring",'
                      '"value":"sec-uuid-1234","info":{"privsep":0}}')
        with self._ssh(out=token_json) as (_conn, run):
            out = Watchful.provision_token({
                'host': '10.0.0.1', 'ssh_user': 'root', 'ssh_password': 'pw',
                'prov_user': 'servicesentry@pve', 'prov_token': 'monitoring',
            })
        assert out['ok'] is True
        assert out['fields'] == {
            'auth_method': 'token',
            'token_id': 'servicesentry@pve!monitoring',
            'token_secret': 'sec-uuid-1234',
        }
        # least-privilege provisioning: create a custom role with exactly the
        # needed privileges, create the user, grant that role, create the token
        cmd = run.call_args.args[1]
        assert 'pveum role add' in cmd
        assert 'pveum role modify' in cmd
        assert 'Sys.Audit' in cmd and 'Datastore.Audit' in cmd
        assert 'PVEAuditor' not in cmd          # not the built-in role
        assert 'ServiceSentryMonitor' in cmd
        assert 'pveum user add' in cmd
        assert 'pveum acl modify / --users' in cmd and '--roles' in cmd
        assert 'pveum user token add' in cmd

    def test_provision_renew_rotates_secret_only(self):
        """mode=renew only rotates the token secret: no user/ACL setup."""
        from watchfuls.proxmox import Watchful
        token_json = ('{"full-tokenid":"servicesentry@pve!monitoring",'
                      '"value":"sec-uuid-5678","info":{"privsep":0}}')
        with self._ssh(out=token_json) as (_conn, run):
            out = Watchful.provision_token({
                'host': '10.0.0.1', 'ssh_user': 'root', 'ssh_password': 'pw',
                'prov_user': 'servicesentry@pve', 'prov_token': 'monitoring',
                'mode': 'renew',
            })
        assert out['ok'] is True
        assert out['fields']['token_secret'] == 'sec-uuid-5678'
        cmd = run.call_args.args[1]
        assert 'pveum role add' not in cmd
        assert 'pveum user add' not in cmd
        assert 'pveum acl modify' not in cmd
        assert 'pveum user token remove' in cmd
        assert 'pveum user token add' in cmd

    def test_provision_uses_bound_host_ssh_profile(self):
        """When the check is host-bound, provisioning reuses the host's SSH
        profile (address + port + secret) injected as __host__ — the same SSH
        path the host-aware checks use — instead of guessing the default port."""
        from watchfuls.proxmox import Watchful
        token_json = ('{"full-tokenid":"servicesentry@pve!monitoring",'
                      '"value":"sec-uuid-9","info":{"privsep":0}}')
        with self._ssh(out=token_json) as (conn, _run):
            out = Watchful.provision_token({
                # no inline host / ssh_* fields — all from the bound host context
                '__host__': {'address': '10.9.9.9',
                             'ssh': {'ssh_user': 'admin', 'ssh_port': 2222,
                                     'ssh_password': 'hpw'}},
                'prov_user': 'servicesentry@pve', 'prov_token': 'monitoring',
            })
        assert out['ok'] is True
        kw = conn.call_args.kwargs
        assert kw['address'] == '10.9.9.9'
        assert kw['port'] == 2222
        assert kw['user'] == 'admin'
        assert kw['password'] == 'hpw'

    def test_provision_explicit_overrides_host_profile(self):
        """An explicit modal value wins over the bound host's SSH profile."""
        from watchfuls.proxmox import Watchful
        token_json = '{"full-tokenid":"u@pve!t","value":"s","info":{}}'
        with self._ssh(out=token_json) as (conn, _run):
            out = Watchful.provision_token({
                'host': '10.0.0.5', 'ssh_port': 22, 'ssh_user': 'root', 'ssh_password': 'pw',
                '__host__': {'address': '10.9.9.9',
                             'ssh': {'ssh_user': 'admin', 'ssh_port': 2222}},
            })
        assert out['ok'] is True
        kw = conn.call_args.kwargs
        assert kw['address'] == '10.0.0.5'
        assert kw['port'] == 22
        assert kw['user'] == 'root'

    def test_provision_verify_host_default_autoadd(self):
        """By default the host key is auto-added (verify_host=False), unless the
        host SSH profile enables ssh_verify_host."""
        from watchfuls.proxmox import Watchful
        token_json = '{"full-tokenid":"u@pve!t","value":"s","info":{}}'
        with self._ssh(out=token_json) as (conn, _run):
            Watchful.provision_token({'host': '10.0.0.1', 'ssh_password': 'pw'})
        assert conn.call_args.kwargs['verify_host'] is False
        with self._ssh(out=token_json) as (conn, _run):
            Watchful.provision_token({
                '__host__': {'address': '10.0.0.1',
                             'ssh': {'ssh_user': 'root', 'ssh_password': 'pw',
                                     'ssh_verify_host': True}}})
        assert conn.call_args.kwargs['verify_host'] is True

    def test_provision_requires_ssh_credentials(self):
        from watchfuls.proxmox import Watchful
        out = Watchful.provision_token({'host': '10.0.0.1', 'ssh_user': 'root'})
        assert out['ok'] is False
        assert 'ssh' in out['message'].lower()

    def test_provision_ssh_error(self):
        from watchfuls.proxmox import Watchful
        with self._ssh(raise_exc=OSError('auth failed')):
            out = Watchful.provision_token(
                {'host': '10.0.0.1', 'ssh_password': 'pw'})
        assert out['ok'] is False
        assert 'auth failed' in out['message']

    def test_provision_no_token_in_output(self):
        from watchfuls.proxmox import Watchful
        with self._ssh(out='', err='permission denied', code=1):
            out = Watchful.provision_token(
                {'host': '10.0.0.1', 'ssh_password': 'pw'})
        assert out['ok'] is False
        assert 'permission denied' in out['message']


class TestProxmoxCredentialManager:
    """The reusable credential (type proxmox_auth) is overlaid onto the item at
    check time via resolve_host()/_apply_cred → the check uses its token."""

    def test_credential_overlays_token(self):
        from watchfuls.proxmox import Watchful
        cred = {'enabled': True, 'data': {
            'auth_method': 'token', 'token_id': 'c@pve!t', 'token_secret': 'csec'}}
        # Item references a stored credential (cred_uid) with NO inline token.
        item = {'enabled': True, 'host': '10.0.0.1', 'auth_method': 'token',
                'cred_uid': 'CRED-1'}
        mon = create_mock_monitor({'watchfuls.proxmox': {'list': {'pve': item}}})
        mon._credentials_store = MagicMock()
        mon._credentials_store.get.return_value = cred
        w = Watchful(mon)
        resolved = w._resolved_item('pve')
        assert resolved['token_id'] == 'c@pve!t'
        assert resolved['token_secret'] == 'csec'

    def test_schema_declares_credential(self):
        from watchfuls.proxmox import Watchful
        cred = Watchful.ITEM_SCHEMA['__credential__']
        assert cred['type'] == 'proxmox_auth'
        names = {f['name'] for f in cred['fields']}
        assert {'token_id', 'token_secret', 'username', 'password'} <= names

    def test_catalog_exposes_provision_action(self):
        """credential_schemas() exposes the proxmox_auth credential-editor action
        with an embedded ssh credential picker input."""
        from lib.credential_schemas import credential_schemas
        cat = credential_schemas('watchfuls')
        actions = cat['proxmox_auth'].get('actions') or []
        prov = next((a for a in actions if a['id'] == 'provision_token'), None)
        assert prov and prov['result'] == 'fields'
        inputs = {i['name']: i for i in prov['inputs']}
        assert inputs['ssh_cred_uid']['kind'] == 'credential'
        assert inputs['ssh_cred_uid']['credential_type'] == 'ssh'
        assert 'host' in inputs and 'ssh_password' in inputs
        # the create/renew mode selector, with translated option labels
        assert inputs['mode']['kind'] == 'select'
        opt_vals = {(o.get('value') if isinstance(o, dict) else o) for o in inputs['mode']['options']}
        assert opt_vals == {'create', 'renew'}
        create_opt = next(o for o in inputs['mode']['options']
                          if isinstance(o, dict) and o.get('value') == 'create')
        assert create_opt['label_i18n'].get('en_EN')

    def test_secondary_ssh_cred_overlay(self):
        """The action route overlays a referenced ssh_cred_uid (a saved ssh
        credential) onto the action config, so provisioning uses its SSH login."""
        from lib.web_admin.routes.watchfuls import _apply_cred_to_config
        wa = MagicMock()
        wa._credentials_store.get.return_value = {
            'enabled': True, 'data': {'ssh_user': 'svc', 'ssh_password': 'p@ss'}}
        cfg = {'host': '10.0.0.1', 'ssh_cred_uid': 'SSH-1'}
        _apply_cred_to_config(wa, cfg)
        assert cfg['ssh_user'] == 'svc'
        assert cfg['ssh_password'] == 'p@ss'
