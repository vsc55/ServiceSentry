#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for web_admin data migrations."""

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    from lib.web_admin.migrations import m003_service_status_uid_label as m003
    from lib.web_admin.migrations import m004_filesystemusage_uid_label as m004
    from lib.web_admin.migrations import m005_dns_uid_label as m005
    from lib.web_admin.migrations import m006_more_uid_labels as m006
    from lib.web_admin.migrations import m007_restore_inline_identity as m007
    from lib.web_admin.migrations import m008_dns_host_label_prefix as m008
    from lib.web_admin.migrations import m009_temperature_uid_label as m009
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


class TestM003ServiceStatusUidLabel:

    def test_rekeys_to_uid_and_fills_label(self, admin):
        huid = admin._hosts_store.create({'name': 'NS1', 'address': '10.0.0.9'}, actor='t')
        modules = {'service_status': {'enabled': True, 'list': {
            # has a uid already → key becomes that uid; label built from host+service
            'NS1-3': {'enabled': True, 'service': 'named', 'host_uid': huid,
                      'uid': 'abc-123', 'expected': 'running'},
            # no uid → one is generated and used as the key
            'NS1-4': {'enabled': True, 'service': 'ntpsec', 'host_uid': huid,
                      'expected': 'running'},
        }}}
        assert admin._save_config_file(admin._MODULES_FILE, modules)

        m003.run(admin)

        out = admin._read_config_file(admin._MODULES_FILE)['service_status']['list']
        assert 'NS1-3' not in out and 'NS1-4' not in out      # old keys gone
        assert out['abc-123']['service'] == 'named'
        assert out['abc-123']['label'] == 'NS1 - named'        # host - service
        gen = next(k for k in out if k != 'abc-123')
        assert out[gen]['uid'] == gen                          # key == its uid
        assert out[gen]['label'] == 'NS1 - ntpsec'

    def test_keeps_existing_label_and_no_host(self, admin):
        modules = {'service_status': {'enabled': True, 'list': {
            'k1': {'enabled': True, 'service': 'named', 'uid': 'u1',
                   'label': 'My custom label', 'expected': 'running'},
            # no host_uid → label falls back to the service name only
            'k2': {'enabled': True, 'service': 'cron', 'uid': 'u2', 'expected': 'running'},
        }}}
        assert admin._save_config_file(admin._MODULES_FILE, modules)

        m003.run(admin)

        out = admin._read_config_file(admin._MODULES_FILE)['service_status']['list']
        assert out['u1']['label'] == 'My custom label'   # user label preserved
        assert out['u2']['label'] == 'cron'              # no host → service only


class TestM004FilesystemUsageUidLabel:

    def test_rekeys_to_uid_and_fills_label(self, admin):
        huid = admin._hosts_store.create({'name': 'NS1', 'address': '10.0.0.9'}, actor='t')
        modules = {'filesystemusage': {'enabled': True, 'list': {
            '/':   {'enabled': True, 'partition': '/', 'host_uid': huid, 'uid': 'fsu-1'},
            'NS1': {'enabled': True, 'partition': '/', 'host_uid': huid},  # no uid → generated
        }}}
        assert admin._save_config_file(admin._MODULES_FILE, modules)

        m004.run(admin)

        out = admin._read_config_file(admin._MODULES_FILE)['filesystemusage']['list']
        assert '/' not in out and 'NS1' not in out         # old keys gone
        assert out['fsu-1']['label'] == 'NS1 - /'          # host - partition
        gen = next(k for k in out if k != 'fsu-1')
        assert out[gen]['uid'] == gen and out[gen]['label'] == 'NS1 - /'


class TestM009TemperatureUidLabel:

    def test_rekeys_sensor_to_uid_and_fills_fields(self, admin):
        huid = admin._hosts_store.create({'name': 'PVE20', 'address': '10.0.0.9'}, actor='t')
        # Old style: keyed by sensor name, no sensor field, no uid.
        modules = {'temperature': {'enabled': True, 'list': {
            'INT3400 Thermal': {'enabled': True, 'host_uid': huid, 'alert': 80},
        }}}
        assert admin._save_config_file(admin._MODULES_FILE, modules)

        m009.run(admin)

        out = admin._read_config_file(admin._MODULES_FILE)['temperature']['list']
        assert 'INT3400 Thermal' not in out                 # old key gone
        uid = next(iter(out))
        assert out[uid]['uid'] == uid                       # keyed by UID
        assert out[uid]['sensor'] == 'INT3400 Thermal'      # old key preserved as sensor
        assert out[uid]['label'] == 'PVE20 - INT3400 Thermal'


class TestM005DnsUidLabel:

    def test_rekeys_to_uid_and_fills_label(self, admin):
        modules = {'dns': {'enabled': True, 'list': {
            'cerebelum.lan':   {'enabled': True, 'host': 'cerebelum.lan',
                                'record_type': 'NS', 'uid': 'dns-1'},
            'cerebelum.lan_3': {'enabled': True, 'host': 'cerebelum.lan',
                                'record_type': 'MX'},  # no uid → generated
        }}}
        assert admin._save_config_file(admin._MODULES_FILE, modules)

        m005.run(admin)

        out = admin._read_config_file(admin._MODULES_FILE)['dns']['list']
        assert 'cerebelum.lan' not in out and 'cerebelum.lan_3' not in out
        assert out['dns-1']['label'] == 'NS cerebelum.lan'
        gen = next(k for k in out if k != 'dns-1')
        assert out[gen]['uid'] == gen and out[gen]['label'] == 'MX cerebelum.lan'


class TestM006MoreUidLabels:

    def test_single_and_multi_check_labels(self, admin):
        huid = admin._hosts_store.create({'name': 'NS1', 'address': '10.0.0.9'}, actor='t')
        modules = {
            # single-check module → label = host name
            'cpu': {'enabled': True, 'list': {
                'NS1': {'enabled': True, 'host_uid': huid, 'uid': 'cpu-1'}}},
            # multi-check module → label = "host - <id>"
            'datastore': {'enabled': True, 'list': {
                'db1': {'enabled': True, 'host_uid': huid, 'db_type': 'mysql'}}},
        }
        assert admin._save_config_file(admin._MODULES_FILE, modules)

        m006.run(admin)

        out = admin._read_config_file(admin._MODULES_FILE)
        cpu = out['cpu']['list']
        assert cpu['cpu-1']['label'] == 'NS1'
        ds = out['datastore']['list']
        assert 'db1' not in ds
        gen = next(iter(ds))
        assert ds[gen]['uid'] == gen and ds[gen]['label'] == 'NS1 - mysql'


class TestM007RestoreInlineIdentity:

    def test_restores_inline_url_from_label(self, admin):
        # An inline web check (no host_uid) whose url was lost to UID re-keying;
        # the value survives in 'label' and must be restored to 'url'.
        modules = {'web': {'enabled': True, 'list': {
            'uid-1': {'enabled': True, 'url': '', 'label': 'www.cerebelum.net'},
            # host-bound check is left untouched (url comes from the host)
            'uid-2': {'enabled': True, 'url': '', 'label': 'NS1 - x',
                      'host_uid': 'h1'},
        }}}
        assert admin._save_config_file(admin._MODULES_FILE, modules)

        m007.run(admin)

        out = admin._read_config_file(admin._MODULES_FILE)['web']['list']
        assert out['uid-1']['url'] == 'www.cerebelum.net'   # restored
        assert out['uid-2']['url'] == ''                    # host-bound untouched


class TestM008DnsHostLabelPrefix:

    def test_prefixes_host_name_to_bound_dns_labels(self, admin):
        huid = admin._hosts_store.create({'name': 'NS1', 'address': '10.0.0.9'}, actor='t')
        modules = {'dns': {'enabled': True, 'list': {
            # host-bound, no prefix yet → gets "NS1 - ..."
            'd1': {'enabled': True, 'host_uid': huid, 'label': 'MX cerebelum.lan'},
            # already prefixed → untouched
            'd2': {'enabled': True, 'host_uid': huid, 'label': 'NS1 - A cerebelum.lan'},
            # inline (no host) → untouched
            'd3': {'enabled': True, 'label': 'NS x.lan'},
        }}}
        assert admin._save_config_file(admin._MODULES_FILE, modules)

        m008.run(admin)

        out = admin._read_config_file(admin._MODULES_FILE)['dns']['list']
        assert out['d1']['label'] == 'NS1 - MX cerebelum.lan'
        assert out['d2']['label'] == 'NS1 - A cerebelum.lan'   # unchanged
        assert out['d3']['label'] == 'NS x.lan'                # inline, unchanged
