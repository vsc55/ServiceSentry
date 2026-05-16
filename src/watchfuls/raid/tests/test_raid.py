#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/raid.py."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from lib.linux.raid_mdstat import RaidMdstat
from conftest import create_mock_monitor


class TestRaidInit:

    def test_init(self):
        from watchfuls.raid import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.raid': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.raid'
        assert w.paths.find('mdstat') == '/proc/mdstat'


class TestRaidConfigOptions:

    def test_config_options_enum(self):
        from watchfuls.raid import ConfigOptions
        assert hasattr(ConfigOptions, 'enabled')
        assert hasattr(ConfigOptions, 'host')
        assert hasattr(ConfigOptions, 'port')
        assert hasattr(ConfigOptions, 'user')
        assert hasattr(ConfigOptions, 'password')
        assert hasattr(ConfigOptions, 'key_file')


class TestRaidDefaults:

    def test_defaults_from_list_schema(self):
        from watchfuls.raid import Watchful
        d = Watchful._DEFAULTS
        assert d['enabled'] is True
        assert d['port'] == 0  # 0 = use default SSH port (22); see placeholder in schema
        assert d['host'] == ''

    def test_module_defaults(self):
        from watchfuls.raid import Watchful
        md = Watchful._MODULE_DEFAULTS
        assert md['threads'] == 5
        assert md['timeout'] == 30
        assert md['local'] is True

    def test_schema_key_is_list(self):
        from watchfuls.raid import Watchful
        assert 'list' in Watchful.ITEM_SCHEMA
        assert 'remote' not in Watchful.ITEM_SCHEMA


@pytest.mark.skipif(sys.platform != 'linux', reason="local RAID checks only run on Linux")
class TestRaidCheckLocal:

    def setup_method(self):
        from watchfuls.raid import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_local_no_raids(self, mock_mdstat_cls):
        """Sin RAIDs locales, reporta 'No RAID's'."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': True,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {}
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert len(items) > 0
        for val in items.values():
            assert val['status'] is True
            assert "No RAID" in val['message']

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_local_raid_ok(self, mock_mdstat_cls):
        """RAID local en buen estado."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': True,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {
            'md0': {
                'status': 'active',
                'type': 'raid1',
                'disk': ['sda1[0]', 'sdb1[1]'],
                'update': RaidMdstat.UpdateStatus.ok,
            }
        }
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert 'L_md0' in items
        assert items['L_md0']['status'] is True
        assert 'good status' in items['L_md0']['message']

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_local_raid_degraded(self, mock_mdstat_cls):
        """RAID local degradado."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': True,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {
            'md0': {
                'status': 'active',
                'type': 'raid1',
                'disk': ['sda1[0]'],
                'update': RaidMdstat.UpdateStatus.error,
            }
        }
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert 'L_md0' in items
        assert items['L_md0']['status'] is False
        assert 'degraded' in items['L_md0']['message']

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_local_raid_recovery(self, mock_mdstat_cls):
        """RAID local en recuperación."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': True,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {
            'md0': {
                'status': 'active',
                'type': 'raid1',
                'disk': ['sda1[0]', 'sdb1[2]'],
                'update': RaidMdstat.UpdateStatus.recovery,
                'recovery': {
                    'percent': 5.2,
                    'finish': '200.5min',
                    'speed': '150000K/sec',
                }
            }
        }
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert 'L_md0' in items
        assert items['L_md0']['status'] is False
        assert 'recovery' in items['L_md0']['message']

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_local_disabled(self, mock_mdstat_cls):
        """Chequeo local deshabilitado no ejecuta RaidMdstat."""
        config = {
            'watchfuls.raid': {
                'local': False,
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        w.check()
        mock_mdstat_cls.assert_not_called()

    @patch('watchfuls.raid.RaidMdstat')
    def test_md_analyze_unknown_status(self, mock_mdstat_cls):
        """UpdateStatus desconocido produce 'Unknown Error'."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': True,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {
            'md0': {
                'status': 'active',
                'type': 'raid1',
                'disk': ['sda1[0]'],
                'update': 'unexpected_value',
            }
        }
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert 'L_md0' in items
        assert items['L_md0']['status'] is False
        assert 'Unknown Error' in items['L_md0']['message']


class TestRaidCheckRemote:

    def setup_method(self):
        from watchfuls.raid import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_remote_ok(self, mock_mdstat_cls):
        """RAID remoto en buen estado."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': False,
                'list': {
                    '1': {
                        'enabled': True,
                        'label': 'Server1',
                        'host': '192.168.1.10',
                        'port': 22,
                        'user': 'root',
                        'password': 'pass',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {
            'md0': {
                'status': 'active',
                'type': 'raid1',
                'disk': ['sda1[0]', 'sdb1[1]'],
                'update': RaidMdstat.UpdateStatus.ok,
            }
        }
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert 'R_1_md0' in items
        assert items['R_1_md0']['status'] is True

    def test_check_remote_disabled(self):
        """Remote deshabilitado no se procesa."""
        config = {
            'watchfuls.raid': {
                'local': False,
                'list': {
                    '1': {
                        'enabled': False,
                        'host': '192.168.1.10',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_remote_no_raids(self, mock_mdstat_cls):
        """Remoto sin RAIDs."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': False,
                'list': {
                    '1': {
                        'enabled': True,
                        'label': 'NAS',
                        'host': '192.168.1.10',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {}
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert len(items) > 0
        for val in items.values():
            assert val['status'] is True

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_remote_bool_enabled(self, mock_mdstat_cls):
        """Remote habilitado con booleano True."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': False,
                'list': {
                    '192.168.1.10': True,
                }
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {}
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) > 0

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_remote_bool_disabled(self, mock_mdstat_cls):
        """Remote deshabilitado con booleano False."""
        config = {
            'watchfuls.raid': {
                'local': False,
                'list': {
                    '192.168.1.10': False,
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        mock_mdstat_cls.assert_not_called()
        assert len(result.items()) == 0

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_remote_key_used_as_host_when_host_empty(self, mock_mdstat_cls):
        """Si host no está definido, el key se usa como host."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': False,
                'list': {
                    '192.168.1.10': {
                        'enabled': True,
                        'user': 'root',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {}
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        w.check()

        call_kwargs = mock_mdstat_cls.call_args
        assert call_kwargs.kwargs.get('host') == '192.168.1.10'


class TestRaidGetLabelById:

    def setup_method(self):
        from watchfuls.raid import Watchful
        self.Watchful = Watchful

    def test_label_local(self):
        config = {'watchfuls.raid': {}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        assert w.get_label_by_id(None) == "Local"

    def test_label_remote_with_label(self):
        config = {
            'watchfuls.raid': {
                'list': {
                    '1': {
                        'label': 'MyServer',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        assert w.get_label_by_id('1') == 'MyServer'

    def test_label_remote_without_label_uses_key(self):
        """Sin label definido, get_label_by_id retorna el key."""
        config = {
            'watchfuls.raid': {
                'list': {
                    'nas-server': {
                        'host': '192.168.1.10',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        assert w.get_label_by_id('nas-server') == 'nas-server'

    def test_label_remote_arbitrary_key(self):
        """Keys arbitrarios (no numéricos) funcionan correctamente."""
        config = {
            'watchfuls.raid': {
                'list': {
                    'my-nas': {
                        'label': 'Home NAS',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        assert w.get_label_by_id('my-nas') == 'Home NAS'


class TestRaidCheckRemoteKeyFile:

    def setup_method(self):
        from watchfuls.raid import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_remote_with_key_file(self, mock_mdstat_cls):
        """Remote with key_file passes it to RaidMdstat."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': False,
                'list': {
                    '1': {
                        'enabled': True,
                        'label': 'NAS',
                        'host': '192.168.1.10',
                        'port': 22,
                        'user': 'root',
                        'key_file': '/home/user/.ssh/id_rsa',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {
            'md0': {
                'status': 'active',
                'type': 'raid1',
                'disk': ['sda1[0]', 'sdb1[1]'],
                'update': RaidMdstat.UpdateStatus.ok,
            }
        }
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert 'R_1_md0' in items
        assert items['R_1_md0']['status'] is True

        call_kwargs = mock_mdstat_cls.call_args
        assert call_kwargs.kwargs.get('key_file') == '/home/user/.ssh/id_rsa'

    @patch('watchfuls.raid.RaidMdstat')
    def test_check_remote_without_key_file(self, mock_mdstat_cls):
        """Remote without key_file passes empty string."""
        mock_mdstat_cls.UpdateStatus = RaidMdstat.UpdateStatus
        config = {
            'watchfuls.raid': {
                'local': False,
                'list': {
                    '1': {
                        'enabled': True,
                        'host': '192.168.1.10',
                        'user': 'root',
                        'password': 'pass',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mdstat = MagicMock()
        mock_mdstat.read_status.return_value = {}
        mock_mdstat_cls.return_value = mock_mdstat

        w = self.Watchful(mock_monitor)
        w.check()

        call_kwargs = mock_mdstat_cls.call_args
        assert call_kwargs.kwargs.get('key_file') == ''
