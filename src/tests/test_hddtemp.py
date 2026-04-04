#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/hddtemp.py."""

import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import create_mock_monitor


# Datos simulados del daemon hddtemp
HDDTEMP_RESPONSE_OK = b"|/dev/sda|ST2000VN004-2E4164|29|C||/dev/sdb|ST3000VN007-2E4166|31|C|"
HDDTEMP_RESPONSE_ERR = b"|/dev/sda|ST2000VN004-2E4164|ERR|*|"
HDDTEMP_RESPONSE_HOT = b"|/dev/sda|ST2000VN004-2E4164|55|C|"


class TestHddtempInfo:

    def setup_method(self):
        from watchfuls.hddtemp import Watchful
        self.Watchful = Watchful

    def test_info_default(self):
        info = self.Watchful.Hddtemp_Info("test_label")
        assert info.label == "test_label"
        assert info.host == ""
        assert info.port == 0
        assert info.alert == 0
        assert info.exclude == []
        assert info.list_hdd == {}
        assert info.error == ""

    def test_info_set_attributes(self):
        info = self.Watchful.Hddtemp_Info("server1")
        info.host = "192.168.1.1"
        info.port = 7634
        info.alert = 50
        info.exclude = ["/dev/sdc"]
        assert info.host == "192.168.1.1"
        assert info.port == 7634
        assert info.alert == 50
        assert info.exclude == ["/dev/sdc"]


class TestHddtempWatchfulInit:

    def test_init(self):
        from watchfuls.hddtemp import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.hddtemp': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.hddtemp'
        assert w.dict_return is not None

    def test_default_values(self):
        from watchfuls.hddtemp import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.hddtemp': {}})
        w = Watchful(mock_monitor)
        # Verificar que get_conf retorna defaults cuando no hay configuración
        assert w.get_conf('alert', 50) == 50
        assert w.get_conf('threads', 5) == 5


class TestHddtempCheck:

    def setup_method(self):
        from watchfuls.hddtemp import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.hddtemp.socket.create_connection')
    def test_check_ok_disks(self, mock_conn):
        """Verifica que discos con temp < alert se marcan OK."""
        config = {
            'watchfuls.hddtemp': {
                'alert': 50,
                'list': {
                    'server1': {
                        'enabled': True,
                        'host': '192.168.1.1',
                        'port': 7634,
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        # Mock socket
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [HDDTEMP_RESPONSE_OK, b'']
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        result = w.check()
        # Dos discos, ambos OK (29ºC y 31ºC < 50)
        items = result.list
        assert len(items) > 0
        for key, val in items.items():
            assert val['status'] is True

    @patch('watchfuls.hddtemp.socket.create_connection')
    def test_check_hot_disk(self, mock_conn):
        """Disco con temp > alert se marca como fallo."""
        config = {
            'watchfuls.hddtemp': {
                'alert': 50,
                'list': {
                    'server1': {
                        'enabled': True,
                        'host': '192.168.1.1',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [HDDTEMP_RESPONSE_HOT, b'']
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        result = w.check()
        items = result.list
        found_fail = False
        for key, val in items.items():
            if not val['status']:
                found_fail = True
        assert found_fail

    @patch('watchfuls.hddtemp.socket.create_connection')
    def test_check_err_disk(self, mock_conn):
        """Disco con ERR en temp se marca como fallo."""
        config = {
            'watchfuls.hddtemp': {
                'alert': 50,
                'list': {
                    'server1': {
                        'enabled': True,
                        'host': '192.168.1.1',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [HDDTEMP_RESPONSE_ERR, b'']
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        result = w.check()
        items = result.list
        found_fail = False
        for key, val in items.items():
            if not val['status']:
                found_fail = True
        assert found_fail

    def test_check_empty_list(self):
        """Sin hosts configurados, no hay resultados."""
        config = {'watchfuls.hddtemp': {'list': {}}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_host(self):
        """Host deshabilitado no se procesa."""
        config = {
            'watchfuls.hddtemp': {
                'list': {
                    'server1': False
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_host_without_host_key(self):
        """Host habilitado pero sin 'host' key no se procesa."""
        config = {
            'watchfuls.hddtemp': {
                'list': {
                    'server1': {
                        'enabled': True,
                        # Sin 'host'
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.hddtemp.socket.create_connection')
    def test_check_excludes_disk(self, mock_conn):
        """Discos en la lista de exclusión no se reportan."""
        config = {
            'watchfuls.hddtemp': {
                'alert': 50,
                'list': {
                    'server1': {
                        'enabled': True,
                        'host': '192.168.1.1',
                        'exclude': ['/dev/sda'],
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [HDDTEMP_RESPONSE_OK, b'']
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        result = w.check()
        items = result.list
        # /dev/sda excluido, solo /dev/sdb
        for key, val in items.items():
            assert '/dev/sda' not in key

    @patch('watchfuls.hddtemp.socket.create_connection')
    def test_check_connection_error(self, mock_conn):
        """Error de conexión marca fallo."""
        config = {
            'watchfuls.hddtemp': {
                'list': {
                    'server1': {
                        'enabled': True,
                        'host': '192.168.1.1',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        mock_conn.side_effect = ConnectionRefusedError("Connection refused")
        result = w.check()
        items = result.list
        # Debería haber un resultado con error
        found_fail = False
        for key, val in items.items():
            if not val['status']:
                found_fail = True
        assert found_fail
