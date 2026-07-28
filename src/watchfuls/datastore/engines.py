#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Datastore watchful: one way to talk to each engine.
#
"""Ten engines, ten conversations, one shape.

MySQL/MariaDB, PostgreSQL, MSSQL, MongoDB, Redis/Valkey, Elasticsearch/OpenSearch, InfluxDB
and Memcached each answer "are you alive" differently, and each names its databases
differently too. Both halves live here because both are the same kind of knowledge - how THIS
engine is spoken to - and separating "ping it" from "list it" would put two halves of one
driver in two files.

Everything above this file works in terms of a backend name; nothing above it imports a
client library.
"""

import base64
import json
import os
import urllib.error
import urllib.request

from . import deps

if deps._PYMYSQL:
    import pymysql
    import pymysql.cursors
if deps._PSYCOPG2:
    import psycopg2
if deps._PYMSSQL:
    import pymssql
if deps._PYMONGO:
    import pymongo
if deps._REDIS:
    import redis as redis_lib
if deps._PYMEMCACHE:
    import pymemcache.client.base as _pmc


class EngineDrivers:
    """Per-engine connectivity tests and database listings. Mixed into ``Watchful``."""

    # ── MySQL / MariaDB ───────────────────────────────────────────────

    @classmethod
    def _test_mysql(cls, cfg) -> tuple:
        conn_type = cfg.get('conn_type', 'tcp')
        if conn_type == 'socket':
            path = cfg.get('socket', '')
            if not path or not os.path.exists(path):
                return False, 'Socket file does not exist', {}
            return cls._pymysql_ping(unix_socket=path,
                user=cfg['user'], password=cfg['password'], db=cfg['db'], timeout=cls._to(cfg))
        return cls._pymysql_ping(
            host=cfg['host'], port=int(cfg['port']),
            user=cfg['user'], password=cfg['password'], db=cfg['db'], timeout=cls._to(cfg))

    @staticmethod
    def _pymysql_ping(host='', port=3306, user='', password='', db='', unix_socket='', timeout=10) -> tuple:
        if not deps._PYMYSQL:
            return False, 'PyMySQL is not installed (pip install PyMySQL)', {}
        try:
            kw = {'user': user, 'password': password, 'db': db,
                  'charset': 'utf8mb4', 'connect_timeout': timeout,
                  'cursorclass': pymysql.cursors.DictCursor}
            if unix_socket:
                kw['unix_socket'] = unix_socket
            else:
                kw['host'] = host; kw['port'] = int(port)
            conn = pymysql.connect(**kw)
        except Exception as exc:
            msg = repr(exc)
            code = str(exc).split(',')[0][1:]
            if code == '1045':
                return False, 'Access denied', {}
            if code == '2003':
                if '(timed out)' in msg:   return False, "Can't connect: timed out", {}
                if '[Errno 111]' in msg:   return False, "Can't connect: connection refused", {}
                if '[Errno 113]' in msg:   return False, "Can't connect: no route to host", {}
                return False, "Can't connect to MySQL server", {}
            return False, msg, {}
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT 1')
            metrics = {}
            try:
                with conn.cursor() as cur:
                    cur.execute("SHOW GLOBAL STATUS WHERE Variable_name IN "
                                "('Threads_connected','Uptime','Queries')")
                    st = {r['Variable_name']: r['Value'] for r in cur.fetchall()}
                if 'Threads_connected' in st: metrics['connections'] = int(st['Threads_connected'])
                if 'Uptime' in st:            metrics['uptime']      = int(st['Uptime'])
                if 'Queries' in st:           metrics['queries']     = int(st['Queries'])
            except Exception:  # pylint: disable=broad-except
                pass
            return True, '', metrics
        except Exception as exc:
            return False, repr(exc), {}
        finally:
            conn.close()

    # ── PostgreSQL ────────────────────────────────────────────────────

    @classmethod
    def _test_postgres(cls, cfg) -> tuple:
        if not deps._PSYCOPG2:
            return False, 'psycopg2 is not installed (pip install psycopg2-binary)', {}
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            kw = {'user': cfg['user'], 'password': cfg['password'],
                  'dbname': cfg['db'] or 'postgres', 'connect_timeout': cls._to(cfg)}
            if cfg.get('tls'):
                kw['sslmode'] = 'require'
            if conn_type == 'socket':
                path = cfg.get('socket', '')
                if not path:
                    return False, 'Socket path not configured', {}
                kw['host'] = path
            else:
                kw['host'] = cfg['host']
                kw['port'] = int(cfg['port'])
            conn = psycopg2.connect(**kw)
            metrics = {}
            try:
                cur = conn.cursor()
                cur.execute('SELECT (SELECT count(*) FROM pg_stat_activity), '
                            'EXTRACT(EPOCH FROM now() - pg_postmaster_start_time())::bigint')
                row = cur.fetchone()
                cur.close()
                metrics = {'connections': int(row[0]), 'uptime': int(row[1])}
            except Exception:  # pylint: disable=broad-except
                pass
            conn.close()
            return True, '', metrics
        except Exception as exc:
            return False, str(exc), {}

    # ── Microsoft SQL Server ──────────────────────────────────────────

    @staticmethod
    def _mssql_msg(exc) -> str:
        """Return a clean error message from a pymssql exception.

        pymssql raises as Error((code, bytes_msg)) — a single-tuple arg —
        so args[0] is the inner (code, msg) pair, not the code directly.
        """
        args = exc.args
        if not args:
            return str(exc)
        inner = args[0]
        # Unwrap (code, msg) tuple whether passed as one arg or two.
        if isinstance(inner, tuple) and len(inner) >= 2:
            code = inner[0] if isinstance(inner[0], int) else None
            raw = inner[1]
        else:
            code = inner if isinstance(inner, int) else None
            raw = args[1] if len(args) > 1 else inner
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode('utf-8', errors='replace')
        if code == 18456:
            return 'Login failed: check username and password'
        if code == 20002:
            return 'Connection failed: server not reachable'
        for line in str(raw).splitlines():
            line = line.strip()
            if line and not line.startswith('DB-Lib error'):
                return line
        return str(raw).strip()

    @classmethod
    def _test_mssql(cls, cfg) -> tuple:
        if not deps._PYMSSQL:
            return False, 'pymssql is not installed (pip install pymssql)', {}
        try:
            conn = pymssql.connect(
                server=cfg['host'], port=str(int(cfg['port'])),
                user=cfg['user'], password=cfg['password'],
                database=cfg['db'] or 'master',
                login_timeout=cls._to(cfg), tds_version='7.4')
            metrics = {}
            try:
                cur = conn.cursor()
                cur.execute('SELECT (SELECT count(*) FROM sys.dm_exec_connections), '
                            'DATEDIFF(second, (SELECT sqlserver_start_time FROM sys.dm_os_sys_info), GETDATE())')
                row = cur.fetchone()
                cur.close()
                metrics = {'connections': int(row[0]), 'uptime': int(row[1])}
            except Exception:  # pylint: disable=broad-except
                pass
            conn.close()
            return True, '', metrics
        except Exception as exc:
            return False, cls._mssql_msg(exc), {}

    # ── MongoDB ───────────────────────────────────────────────────────

    @classmethod
    def _test_mongodb(cls, cfg) -> tuple:
        if not deps._PYMONGO:
            return False, 'pymongo is not installed (pip install pymongo)', {}
        try:
            kw = {
                'host': cfg['host'], 'port': int(cfg['port']),
                'serverSelectionTimeoutMS': cls._to(cfg) * 1000,
                'connectTimeoutMS': cls._to(cfg) * 1000,
            }
            if cfg['user']:
                kw['username'] = cfg['user']
                kw['password'] = cfg['password']
                kw['authSource'] = cfg.get('auth_db') or 'admin'
            if cfg.get('tls'):
                kw['tls'] = True
            client = pymongo.MongoClient(**kw)
            client.admin.command('ping')
            metrics = {}
            try:
                ss = client.admin.command('serverStatus')
                metrics['connections'] = int(ss.get('connections', {}).get('current', 0))
                metrics['uptime']      = int(ss.get('uptime', 0))
                res = ss.get('mem', {}).get('resident')   # already in MB
                if res is not None:
                    metrics['memory'] = int(res)
            except Exception:  # pylint: disable=broad-except
                pass
            client.close()
            return True, '', metrics
        except Exception as exc:
            return False, str(exc), {}

    # ── Redis / Valkey ────────────────────────────────────────────────

    @classmethod
    def _test_redis(cls, cfg) -> tuple:
        if not deps._REDIS:
            return False, 'redis is not installed (pip install redis)', {}
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            kw = {
                'password': cfg['password'] or None,
                'db': int(cfg.get('db_index', 0)),
                'socket_timeout': cls._to(cfg),
                'socket_connect_timeout': cls._to(cfg),
            }
            if cfg.get('tls'):
                kw['ssl'] = True
            if conn_type == 'socket':
                path = cfg.get('socket', '')
                if not path:
                    return False, 'Socket path not configured', {}
                kw['unix_socket_path'] = path
                r = redis_lib.Redis(**kw)
            else:
                kw['host'] = cfg['host']
                kw['port'] = int(cfg['port'])
                r = redis_lib.Redis(**kw)
            r.ping()
            metrics = {}
            try:
                info = r.info()
                metrics['connections'] = int(info.get('connected_clients', 0))
                metrics['uptime']      = int(info.get('uptime_in_seconds', 0))
                metrics['memory']      = round(int(info.get('used_memory', 0)) / 1048576, 1)
                metrics['queries']     = int(info.get('total_commands_processed', 0))
            except Exception:  # pylint: disable=broad-except
                pass
            r.close()
            return True, '', metrics
        except Exception as exc:
            return False, str(exc), {}

    # ── Elasticsearch / OpenSearch ────────────────────────────────────

    @classmethod
    def _test_elasticsearch(cls, cfg) -> tuple:
        scheme = cfg.get('scheme', 'http')
        host   = cfg['host']
        port   = int(cfg['port'])
        url    = f'{scheme}://{host}:{port}/_cluster/health'
        try:
            req = urllib.request.Request(url)
            if cfg['user']:
                creds = base64.b64encode(f"{cfg['user']}:{cfg['password']}".encode()).decode()
                req.add_header('Authorization', f'Basic {creds}')
            with urllib.request.urlopen(req, timeout=cls._to(cfg)) as resp:
                body = json.loads(resp.read())
            status = body.get('status', '')
            if status == 'red':
                return False, 'Cluster status is RED', {}
            return True, '', {}
        except urllib.error.HTTPError as exc:
            return False, f'HTTP {exc.code}: {exc.reason}', {}
        except Exception as exc:
            return False, str(exc), {}

    # ── InfluxDB ──────────────────────────────────────────────────────

    @classmethod
    def _test_influxdb(cls, cfg) -> tuple:
        scheme   = cfg.get('scheme', 'http')
        host     = cfg['host']
        port     = int(cfg['port'])
        token    = cfg.get('token', '')
        user     = cfg.get('user', '')
        password = cfg.get('password', '')

        def _req(path):
            r = urllib.request.Request(f'{scheme}://{host}:{port}{path}')
            if token:
                r.add_header('Authorization', f'Token {token}')
            elif user:
                creds = base64.b64encode(f'{user}:{password}'.encode()).decode()
                r.add_header('Authorization', f'Basic {creds}')
            return r

        # InfluxDB 2.x — /health endpoint
        try:
            with urllib.request.urlopen(_req('/health'), timeout=cls._to(cfg)) as resp:
                body = json.loads(resp.read())
            status = body.get('status', '')
            return (True, '', {}) if status == 'pass' else (False, f'Health status: {status}', {})
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                return False, f'HTTP {exc.code}: {exc.reason}', {}
        except Exception as exc:
            return False, str(exc), {}

        # InfluxDB 1.x — /ping endpoint (returns 204 No Content)
        try:
            with urllib.request.urlopen(_req('/ping'), timeout=cls._to(cfg)):
                pass
            return True, '', {}
        except urllib.error.HTTPError as exc:
            return False, f'HTTP {exc.code}: {exc.reason}', {}
        except Exception as exc:
            return False, str(exc), {}

    # ── Memcached ─────────────────────────────────────────────────────

    @classmethod
    def _test_memcached(cls, cfg) -> tuple:
        if not deps._PYMEMCACHE:
            return False, 'pymemcache is not installed (pip install pymemcache)', {}
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            if conn_type == 'socket':
                path = cfg.get('socket', '')
                if not path:
                    return False, 'Socket path not configured', {}
                server = path
            else:
                server = (cfg['host'], int(cfg['port']))
            client = _pmc.Client(server, connect_timeout=cls._to(cfg), timeout=cls._to(cfg))
            client.get('__ping__')
            metrics = {}
            try:
                raw = client.stats() or {}
                st = {(k.decode() if isinstance(k, bytes) else k):
                      (v.decode() if isinstance(v, bytes) else v) for k, v in raw.items()}
                metrics['connections'] = int(st.get('curr_connections', 0))
                metrics['uptime']      = int(st.get('uptime', 0))
                metrics['memory']      = round(int(st.get('bytes', 0)) / 1048576, 1)
                metrics['queries']     = int(st.get('cmd_get', 0)) + int(st.get('cmd_set', 0))
            except Exception:  # pylint: disable=broad-except
                pass
            client.close()
            return True, '', metrics
        except Exception as exc:
            return False, str(exc), {}

    @classmethod
    def _list_mysql(cls, cfg) -> dict:
        if not deps._PYMYSQL:
            return {'ok': False, 'message': 'PyMySQL is not installed (pip install PyMySQL)', 'items': []}
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            kw = {'user': cfg['user'], 'password': cfg['password'],
                  'charset': 'utf8mb4', 'connect_timeout': cls._to(cfg),
                  'cursorclass': pymysql.cursors.DictCursor}
            if conn_type == 'socket':
                kw['unix_socket'] = cfg.get('socket', '')
            else:
                kw['host'] = cfg['host']; kw['port'] = int(cfg['port'])
            conn = pymysql.connect(**kw)
        except Exception as exc:
            return {'ok': False, 'message': repr(exc), 'items': []}
        try:
            with conn.cursor() as cur:
                cur.execute('SHOW DATABASES')
                return {'ok': True, 'message': '', 'items': [r['Database'] for r in cur.fetchall()]}
        except Exception as exc:
            return {'ok': False, 'message': repr(exc), 'items': []}
        finally:
            conn.close()

    @classmethod
    def _list_postgres(cls, cfg) -> dict:
        if not deps._PSYCOPG2:
            return {'ok': False, 'message': 'psycopg2 is not installed', 'databases': []}
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            kw = {'user': cfg['user'], 'password': cfg['password'],
                  'dbname': 'postgres', 'connect_timeout': cls._to(cfg)}
            if cfg.get('tls'):
                kw['sslmode'] = 'require'
            if conn_type == 'socket':
                kw['host'] = cfg.get('socket', '')
            else:
                kw['host'] = cfg['host']; kw['port'] = int(cfg['port'])
            conn = psycopg2.connect(**kw)
            with conn.cursor() as cur:
                cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname")
                dbs = [r[0] for r in cur.fetchall()]
            conn.close()
            return {'ok': True, 'message': '', 'items': dbs}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'items': []}

    @classmethod
    def _list_mssql(cls, cfg) -> dict:
        if not deps._PYMSSQL:
            return {'ok': False, 'message': 'pymssql is not installed', 'databases': []}
        try:
            conn = pymssql.connect(
                server=cfg['host'], port=str(int(cfg['port'])),
                user=cfg['user'], password=cfg['password'],
                database='master', login_timeout=cls._to(cfg))
            with conn.cursor() as cur:
                cur.execute('SELECT name FROM sys.databases ORDER BY name')
                dbs = [r[0] for r in cur.fetchall()]
            conn.close()
            return {'ok': True, 'message': '', 'items': dbs}
        except Exception as exc:
            return {'ok': False, 'message': cls._mssql_msg(exc), 'items': []}

    @classmethod
    def _list_mongodb(cls, cfg) -> dict:
        if not deps._PYMONGO:
            return {'ok': False, 'message': 'pymongo is not installed', 'databases': []}
        try:
            kw = {'host': cfg['host'], 'port': int(cfg['port']),
                  'serverSelectionTimeoutMS': cls._to(cfg) * 1000}
            if cfg['user']:
                kw['username'] = cfg['user']
                kw['password'] = cfg['password']
                kw['authSource'] = cfg.get('auth_db') or 'admin'
            if cfg.get('tls'):
                kw['tls'] = True
            client = pymongo.MongoClient(**kw)
            dbs = client.list_database_names()
            client.close()
            return {'ok': True, 'message': '', 'items': sorted(dbs)}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'items': []}

    @classmethod
    def _list_es_indices(cls, cfg) -> dict:
        scheme = cfg.get('scheme', 'http')
        url    = f'{scheme}://{cfg["host"]}:{int(cfg["port"])}/_cat/indices?format=json&h=index&s=index'
        try:
            req = urllib.request.Request(url)
            if cfg['user']:
                creds = base64.b64encode(f"{cfg['user']}:{cfg['password']}".encode()).decode()
                req.add_header('Authorization', f'Basic {creds}')
            with urllib.request.urlopen(req, timeout=cls._to(cfg)) as resp:
                body = json.loads(resp.read())
            indices = sorted(e['index'] for e in body if not e['index'].startswith('.'))
            return {'ok': True, 'message': '', 'items': indices}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'items': []}

    @classmethod
    def _list_influxdb(cls, cfg) -> dict:
        scheme   = cfg.get('scheme', 'http')
        host     = cfg['host']
        port     = int(cfg['port'])
        token    = cfg.get('token', '')
        user     = cfg.get('user', '')
        password = cfg.get('password', '')

        def _req(path):
            r = urllib.request.Request(f'{scheme}://{host}:{port}{path}')
            if token:
                r.add_header('Authorization', f'Token {token}')
            elif user:
                creds = base64.b64encode(f'{user}:{password}'.encode()).decode()
                r.add_header('Authorization', f'Basic {creds}')
            return r

        # InfluxDB 2.x — list buckets
        try:
            with urllib.request.urlopen(_req('/api/v2/buckets'), timeout=cls._to(cfg)) as resp:
                body = json.loads(resp.read())
            buckets = sorted(b['name'] for b in body.get('buckets', []) if not b['name'].startswith('_'))
            return {'ok': True, 'message': '', 'items': buckets}
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                return {'ok': False, 'message': f'HTTP {exc.code}: {exc.reason}', 'items': []}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'items': []}

        # InfluxDB 1.x — SHOW DATABASES
        try:
            with urllib.request.urlopen(_req('/query?q=SHOW+DATABASES'), timeout=cls._to(cfg)) as resp:
                body = json.loads(resp.read())
            values = body.get('results', [{}])[0].get('series', [{}])[0].get('values', [])
            dbs = sorted(r[0] for r in values if r[0] != '_internal')
            return {'ok': True, 'message': '', 'items': dbs}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'items': []}
