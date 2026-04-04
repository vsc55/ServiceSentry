#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/mysql.py."""

import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import create_mock_monitor


class TestMysqlInit:

    def test_init(self):
        from watchfuls.mysql import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.mysql': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.mysql'


class TestMysqlConfigOptions:

    def test_config_options_enum(self):
        from watchfuls.mysql import ConfigOptions
        assert hasattr(ConfigOptions, 'enabled')
        assert hasattr(ConfigOptions, 'host')
        assert hasattr(ConfigOptions, 'port')
        assert hasattr(ConfigOptions, 'user')
        assert hasattr(ConfigOptions, 'password')
        assert hasattr(ConfigOptions, 'db')
        assert hasattr(ConfigOptions, 'socket')


class TestMysqlCheck:

    def setup_method(self):
        from watchfuls.mysql import Watchful
        self.Watchful = Watchful

    def test_check_empty_list(self):
        """Sin DBs configuradas, no hay resultados."""
        config = {'watchfuls.mysql': {'list': {}}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_db(self):
        """DB deshabilitada no se procesa."""
        config = {
            'watchfuls.mysql': {
                'list': {
                    'db1': False
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.mysql.pymysql.connect')
    def test_check_db_ok(self, mock_connect):
        """Conexión exitosa se marca OK."""
        config = {
            'watchfuls.mysql': {
                'host': 'localhost',
                'port': 3306,
                'user': 'root',
                'password': '',
                'db': '',
                'socket': '',
                'list': {
                    'db1': {
                        'enabled': True,
                        'host': 'localhost',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        # Mock conexión exitosa
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value = mock_conn

        result = w.check()
        items = result.list
        assert 'db1' in items
        assert items['db1']['status'] is True

    @patch('watchfuls.mysql.pymysql.connect')
    def test_check_db_access_denied(self, mock_connect):
        """Error 1045 (access denied) se detecta."""
        config = {
            'watchfuls.mysql': {
                'host': 'localhost',
                'socket': '',
                'list': {
                    'db1': {
                        'enabled': True,
                        'host': 'localhost',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        # Simular OperationalError 1045
        import pymysql
        mock_connect.side_effect = pymysql.OperationalError(
            1045, "Access denied for user 'root'@'localhost' (using password: NO)")

        result = w.check()
        items = result.list
        assert 'db1' in items
        assert items['db1']['status'] is False
        assert 'Access denied' in items['db1']['message'] or 'Error' in items['db1']['message']

    @patch('watchfuls.mysql.pymysql.connect')
    def test_check_db_cant_connect(self, mock_connect):
        """Error 2003 (can't connect) se detecta."""
        config = {
            'watchfuls.mysql': {
                'host': 'localhost',
                'socket': '',
                'list': {
                    'db1': {
                        'enabled': True,
                        'host': 'server_unreachable',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        import pymysql
        mock_connect.side_effect = pymysql.OperationalError(
            2003, "Can't connect to MySQL server on 'server_unreachable' (timed out)")

        result = w.check()
        items = result.list
        assert 'db1' in items
        assert items['db1']['status'] is False

    @patch('watchfuls.mysql.os.path.exists', return_value=False)
    def test_check_db_socket_not_exist(self, mock_exists):
        """Socket que no existe retorna error."""
        config = {
            'watchfuls.mysql': {
                'socket': '/var/run/mysqld/mysqld.sock',
                'list': {
                    'db1': {
                        'enabled': True,
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        result = w.check()
        items = result.list
        assert 'db1' in items
        assert items['db1']['status'] is False

    def test_check_multiple_dbs(self):
        """Múltiples DBs, una habilitada y otra no."""
        config = {
            'watchfuls.mysql': {
                'host': 'localhost',
                'socket': '',
                'list': {
                    'db1': True,
                    'db2': False,
                    'db3': {'enabled': True},
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch('watchfuls.mysql.pymysql.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = w.check()
            items = result.list
            assert 'db1' in items
            assert 'db2' not in items
            assert 'db3' in items
