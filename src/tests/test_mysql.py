#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/mysql.py."""

from unittest.mock import MagicMock, patch

import pytest

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

    @patch('watchfuls.mysql.pymysql.connect')
    def test_check_db_2003_connection_refused(self, mock_connect):
        """Error 2003 con [Errno 111] muestra 'connection refused'."""
        config = {
            'watchfuls.mysql': {
                'host': 'localhost',
                'socket': '',
                'list': {'db1': {'enabled': True, 'host': 'localhost'}},
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        import pymysql
        mock_connect.side_effect = pymysql.OperationalError(
            2003, "Can't connect to MySQL server on 'localhost' ([Errno 111] Connection refused)")

        result = w.check()
        items = result.list
        assert items['db1']['status'] is False
        assert 'connection refused' in items['db1']['message']

    @patch('watchfuls.mysql.pymysql.connect')
    def test_check_db_2003_no_route(self, mock_connect):
        """Error 2003 con [Errno 113] muestra 'no route to host'."""
        config = {
            'watchfuls.mysql': {
                'host': 'localhost',
                'socket': '',
                'list': {'db1': {'enabled': True, 'host': 'remote'}},
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        import pymysql
        mock_connect.side_effect = pymysql.OperationalError(
            2003, "Can't connect to MySQL server on 'remote' ([Errno 113] No route to host)")

        result = w.check()
        items = result.list
        assert items['db1']['status'] is False
        assert 'no route to host' in items['db1']['message']

    @patch('watchfuls.mysql.pymysql.connect')
    def test_check_db_2003_unknown_sub_error(self, mock_connect):
        """Error 2003 con sub-error desconocido muestra '?????'."""
        config = {
            'watchfuls.mysql': {
                'host': 'localhost',
                'socket': '',
                'list': {'db1': {'enabled': True, 'host': 'localhost'}},
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        import pymysql
        mock_connect.side_effect = pymysql.OperationalError(
            2003, "Can't connect to MySQL server on 'localhost' (Unknown error)")

        result = w.check()
        items = result.list
        assert items['db1']['status'] is False
        assert '?????' in items['db1']['message']

    @patch('watchfuls.mysql.pymysql.connect')
    def test_check_db_unknown_error_code(self, mock_connect):
        """Error con código desconocido usa rama default."""
        config = {
            'watchfuls.mysql': {
                'host': 'localhost',
                'socket': '',
                'list': {'db1': {'enabled': True, 'host': 'localhost'}},
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        import pymysql
        mock_connect.side_effect = pymysql.OperationalError(
            9999, "Some completely unknown error")

        result = w.check()
        items = result.list
        assert items['db1']['status'] is False


class TestMysqlGetConf:

    def setup_method(self):
        from watchfuls.mysql import ConfigOptions, Watchful
        self.Watchful = Watchful
        self.ConfigOptions = ConfigOptions

    def test_get_conf_none_raises_value_error(self):
        """opt_find=None lanza ValueError."""
        config = {'watchfuls.mysql': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        with pytest.raises(ValueError, match="can not be None"):
            w._get_conf(None, 'db1')

    def test_get_conf_invalid_option_raises_type_error(self):
        """opt_find inválido lanza TypeError."""
        from enum import IntEnum

        class FakeOption(IntEnum):
            invalid = 999

        config = {'watchfuls.mysql': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        with pytest.raises(TypeError, match="is not valid option"):
            w._get_conf(FakeOption.invalid, 'db1')
