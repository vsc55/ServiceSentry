#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls.datastore."""

from unittest.mock import MagicMock, patch
import pytest
from conftest import create_mock_monitor


# ── Schema / defaults ─────────────────────────────────────────────────────────

class TestDatastoreSchema:

    def test_item_schema_loaded(self):
        from watchfuls.datastore import Watchful
        assert Watchful.ITEM_SCHEMA is not None
        assert 'list' in Watchful.ITEM_SCHEMA

    def test_defaults_from_schema(self):
        from watchfuls.datastore import Watchful
        assert 'enabled' in Watchful._DEFAULTS
        assert 'db_type' in Watchful._DEFAULTS
        assert Watchful._DEFAULTS['db_type'] == 'mysql'

    def test_all_schema_fields_have_type_and_default(self):
        from watchfuls.datastore import Watchful
        for k, v in Watchful.ITEM_SCHEMA['list'].items():
            if k.startswith('__'):
                continue
            assert 'type' in v, f"Field '{k}' missing 'type'"
            assert 'default' in v, f"Field '{k}' missing 'default'"


# ── Initialisation ─────────────────────────────────────────────────────────────

class TestDatastoreInit:

    def test_init(self):
        from watchfuls.datastore import Watchful
        mock = create_mock_monitor({'watchfuls.datastore': {}})
        w = Watchful(mock)
        assert w.name_module == 'watchfuls.datastore'


# ── Runtime check ──────────────────────────────────────────────────────────────

class TestDatastoreCheck:

    def _make(self, cfg):
        from watchfuls.datastore import Watchful
        mock = create_mock_monitor({'watchfuls.datastore': cfg})
        return Watchful(mock)

    def test_empty_list(self):
        w = self._make({'list': {}})
        result = w.check()
        assert len(result.items()) == 0

    def test_disabled_item_skipped(self):
        w = self._make({'list': {'db1': {'enabled': False, 'db_type': 'mysql'}}})
        result = w.check()
        assert len(result.items()) == 0

    def test_check_ok(self):
        w = self._make({'list': {'db1': {'enabled': True, 'db_type': 'mysql'}}})
        with patch.object(w, '_ds_check') as mock_check:
            w.check()
            mock_check.assert_called_once_with('db1')

    def test_check_exception_sets_error(self):
        w = self._make({'list': {'db1': {'enabled': True, 'db_type': 'mysql'}}})
        with patch.object(w, '_ds_check', side_effect=RuntimeError('boom')):
            result = w.check()
            assert 'db1' in result.list
            assert result.list['db1']['status'] is False


# ── Backend dispatcher ─────────────────────────────────────────────────────────

class TestBackendDispatch:

    def test_unknown_db_type(self):
        from watchfuls.datastore import Watchful
        ok, msg = Watchful._backend_check_direct('fakedb', {})
        assert ok is False
        assert 'fakedb' in msg

    def test_ssh_unavailable_returns_error(self):
        from watchfuls.datastore import Watchful
        import watchfuls.datastore as mod
        orig = mod._PARAMIKO
        mod._PARAMIKO = False
        try:
            ok, msg = Watchful._backend_check('mysql', 'ssh', {
                'ssh_host': 'h', 'ssh_port': 22, 'ssh_user': 'u',
                'ssh_password': '', 'ssh_key': '', 'host': 'db', 'port': 3306,
            })
            assert ok is False
            assert 'paramiko' in msg
        finally:
            mod._PARAMIKO = orig


# ── MySQL backend ──────────────────────────────────────────────────────────────

class TestMysqlBackend:

    def test_success(self):
        from watchfuls.datastore import Watchful
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        with patch('pymysql.connect', return_value=mock_conn):
            ok, msg = Watchful._test_mysql(
                {'conn_type': 'tcp', 'host': '127.0.0.1', 'port': 3306,
                 'user': 'root', 'password': '', 'db': ''})
            assert ok is True

    def test_access_denied(self):
        from watchfuls.datastore import Watchful
        import pymysql.err
        with patch('pymysql.connect',
                   side_effect=pymysql.err.OperationalError(1045, 'Access denied')):
            ok, msg = Watchful._test_mysql(
                {'conn_type': 'tcp', 'host': '127.0.0.1', 'port': 3306,
                 'user': 'bad', 'password': 'bad', 'db': ''})
            assert ok is False
            assert 'Access denied' in msg

    def test_socket_missing_path(self):
        from watchfuls.datastore import Watchful
        ok, msg = Watchful._test_mysql(
            {'conn_type': 'socket', 'socket': '/nonexistent.sock',
             'user': 'root', 'password': '', 'db': ''})
        assert ok is False
        assert 'Socket' in msg


# ── PostgreSQL backend ─────────────────────────────────────────────────────────

class TestPostgresBackend:

    def test_driver_missing(self):
        from watchfuls.datastore import Watchful
        import watchfuls.datastore as mod
        orig = mod._PSYCOPG2
        mod._PSYCOPG2 = False
        try:
            ok, msg = Watchful._test_postgres(
                {'conn_type': 'tcp', 'host': 'h', 'port': 5432,
                 'user': 'u', 'password': 'p', 'db': 'db', 'tls': False})
            assert ok is False
            assert 'psycopg2' in msg
        finally:
            mod._PSYCOPG2 = orig


# ── MSSQL backend ──────────────────────────────────────────────────────────────

class TestMssqlBackend:

    def test_mssql_msg_tuple_arg(self):
        """pymssql raises Error((code, bytes)) — single tuple arg."""
        from watchfuls.datastore import Watchful
        exc = Exception((18456, b'DB-Lib error message 20018, severity 14:\nGeneral SQL Server error\nDB-Lib error message 20002, severity 9:\nAdaptive Server connection failed\n'))
        assert Watchful._mssql_msg(exc) == 'Login failed: check username and password'

    def test_mssql_msg_two_args(self):
        """Also handles Error(code, bytes) with two separate args."""
        from watchfuls.datastore import Watchful
        exc = Exception(18456, b'General SQL Server error\n')
        assert Watchful._mssql_msg(exc) == 'Login failed: check username and password'

    def test_mssql_msg_conn_refused(self):
        from watchfuls.datastore import Watchful
        exc = Exception((20002, b'DB-Lib error message 20002:\nAdaptive Server connection failed\n'))
        assert Watchful._mssql_msg(exc) == 'Connection failed: server not reachable'

    def test_driver_missing(self):
        from watchfuls.datastore import Watchful
        import watchfuls.datastore as mod
        orig = mod._PYMSSQL
        mod._PYMSSQL = False
        try:
            ok, msg = Watchful._test_mssql(
                {'host': 'h', 'port': 1433, 'user': 'u',
                 'password': 'p', 'db': 'db', 'tls': False})
            assert ok is False
            assert 'pymssql' in msg
        finally:
            mod._PYMSSQL = orig


# ── MongoDB backend ────────────────────────────────────────────────────────────

class TestMongoBackend:

    def test_driver_missing(self):
        from watchfuls.datastore import Watchful
        import watchfuls.datastore as mod
        orig = mod._PYMONGO
        mod._PYMONGO = False
        try:
            ok, msg = Watchful._test_mongodb(
                {'host': 'h', 'port': 27017, 'user': 'u',
                 'password': 'p', 'auth_db': 'admin', 'tls': False})
            assert ok is False
            assert 'pymongo' in msg
        finally:
            mod._PYMONGO = orig


# ── Redis backend ──────────────────────────────────────────────────────────────

class TestRedisBackend:

    def test_driver_missing(self):
        from watchfuls.datastore import Watchful
        import watchfuls.datastore as mod
        orig = mod._REDIS
        mod._REDIS = False
        try:
            ok, msg = Watchful._test_redis(
                {'conn_type': 'tcp', 'host': 'h', 'port': 6379,
                 'password': '', 'db_index': 0, 'tls': False})
            assert ok is False
            assert 'redis' in msg
        finally:
            mod._REDIS = orig


# ── Memcached backend ──────────────────────────────────────────────────────────

class TestMemcachedBackend:

    def test_driver_missing(self):
        from watchfuls.datastore import Watchful
        import watchfuls.datastore as mod
        orig = mod._PYMEMCACHE
        mod._PYMEMCACHE = False
        try:
            ok, msg = Watchful._test_memcached(
                {'conn_type': 'tcp', 'host': 'h', 'port': 11211, 'socket': ''})
            assert ok is False
            assert 'pymemcache' in msg
        finally:
            mod._PYMEMCACHE = orig


# ── Elasticsearch backend ──────────────────────────────────────────────────────

class TestElasticsearchBackend:

    def test_cluster_status_red(self):
        from watchfuls.datastore import Watchful
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"status": "red"}'
        with patch('urllib.request.urlopen', return_value=mock_resp):
            ok, msg = Watchful._test_elasticsearch(
                {'scheme': 'http', 'host': 'h', 'port': 9200, 'user': '', 'password': ''})
            assert ok is False
            assert 'RED' in msg

    def test_cluster_status_green(self):
        from watchfuls.datastore import Watchful
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"status": "green"}'
        with patch('urllib.request.urlopen', return_value=mock_resp):
            ok, _ = Watchful._test_elasticsearch(
                {'scheme': 'http', 'host': 'h', 'port': 9200, 'user': '', 'password': ''})
            assert ok is True


# ── InfluxDB backend ──────────────────────────────────────────────────────────

class TestInfluxdbBackend:

    def test_health_pass(self):
        from watchfuls.datastore import Watchful
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"status": "pass"}'
        with patch('urllib.request.urlopen', return_value=mock_resp):
            ok, _ = Watchful._test_influxdb(
                {'scheme': 'http', 'host': 'h', 'port': 8086,
                 'token': '', 'user': '', 'password': ''})
            assert ok is True

    def test_health_fail(self):
        from watchfuls.datastore import Watchful
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"status": "fail"}'
        with patch('urllib.request.urlopen', return_value=mock_resp):
            ok, msg = Watchful._test_influxdb(
                {'scheme': 'http', 'host': 'h', 'port': 8086,
                 'token': '', 'user': '', 'password': ''})
            assert ok is False
            assert 'fail' in msg


# ── test_connection classmethod ────────────────────────────────────────────────

class TestTestConnection:

    def test_routes_to_mysql(self):
        from watchfuls.datastore import Watchful
        with patch.object(Watchful, '_test_mysql', return_value=(True, '')) as m:
            result = Watchful.test_connection({
                'db_type': 'mysql', 'conn_type': 'tcp',
                'host': 'h', 'port': 3306, 'user': 'u', 'password': 'p', 'db': ''})
            m.assert_called_once()
            assert result['ok'] is True

    def test_routes_to_postgres(self):
        from watchfuls.datastore import Watchful
        with patch.object(Watchful, '_test_postgres', return_value=(True, '')) as m:
            Watchful.test_connection({
                'db_type': 'postgres', 'conn_type': 'tcp',
                'host': 'h', 'port': 5432, 'user': 'u', 'password': 'p',
                'db': '', 'tls': False})
            m.assert_called_once()

    def test_default_port_applied(self):
        from watchfuls.datastore import Watchful, _DEFAULT_PORTS
        captured = {}
        def fake_test_redis(cfg):
            captured['port'] = cfg['port']
            return True, ''
        with patch.object(Watchful, '_test_redis', side_effect=fake_test_redis):
            Watchful.test_connection({'db_type': 'redis', 'conn_type': 'tcp',
                                      'host': 'h', 'port': 0, 'password': '',
                                      'db_index': 0, 'tls': False})
        assert captured['port'] == _DEFAULT_PORTS['redis']

    def test_ssh_only_mode(self):
        from watchfuls.datastore import Watchful
        with patch.object(Watchful, '_test_ssh_only', return_value={'ok': True, 'message': 'ok'}) as m:
            Watchful.test_connection({'_test_mode': 'ssh', 'db_type': 'mysql'})
            m.assert_called_once()


# ── list_databases classmethod ────────────────────────────────────────────────

class TestListDatabases:

    def test_mysql_returns_databases(self):
        from watchfuls.datastore import Watchful
        with patch.object(Watchful, '_list_mysql',
                          return_value={'ok': True, 'message': '', 'databases': ['a', 'b']}):
            result = Watchful.list_databases({'db_type': 'mysql', 'conn_type': 'tcp',
                                              'host': 'h', 'port': 3306,
                                              'user': 'u', 'password': 'p'})
            assert result['ok'] is True
            assert result['databases'] == ['a', 'b']

    def test_unsupported_type_returns_error(self):
        from watchfuls.datastore import Watchful
        result = Watchful.list_databases({'db_type': 'redis', 'conn_type': 'tcp',
                                          'host': 'h', 'port': 6379})
        assert result['ok'] is False
        assert result['databases'] == []

    def test_memcached_not_supported(self):
        from watchfuls.datastore import Watchful
        result = Watchful.list_databases({'db_type': 'memcached', 'conn_type': 'tcp',
                                          'host': 'h', 'port': 11211})
        assert result['ok'] is False
