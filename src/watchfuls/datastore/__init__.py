#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Datastore connectivity watchful — MySQL/MariaDB, PostgreSQL, MSSQL,
MongoDB, Redis, Valkey, Elasticsearch, OpenSearch, InfluxDB, Memcached."""

import concurrent.futures
import json
import os
import os.path
import socket
import threading
import urllib.request
import urllib.error
import base64
from enum import IntEnum

import pymysql
import pymysql.cursors

try:
    import paramiko
    _PARAMIKO = True
except ImportError:
    _PARAMIKO = False

try:
    import psycopg2
    _PSYCOPG2 = True
except ImportError:
    _PSYCOPG2 = False

try:
    import pymssql
    _PYMSSQL = True
except ImportError:
    _PYMSSQL = False

try:
    import pymongo
    _PYMONGO = True
except ImportError:
    _PYMONGO = False

try:
    import redis as redis_lib
    _REDIS = True
except ImportError:
    _REDIS = False

try:
    import pymemcache.client.base as _pmc
    _PYMEMCACHE = True
except ImportError:
    _PYMEMCACHE = False

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

# Default TCP port per engine (used when port == 0)
_DEFAULT_PORTS = {
    'mysql': 3306, 'mariadb': 3306,
    'postgres': 5432,
    'mssql': 1433,
    'mongodb': 27017,
    'redis': 6379, 'valkey': 6379,
    'elasticsearch': 9200, 'opensearch': 9200,
    'influxdb': 8086,
    'memcached': 11211,
}

_PRETTY = {
    'mysql': 'MySQL / MariaDB', 'mariadb': 'MySQL / MariaDB',
    'postgres': 'PostgreSQL', 'mssql': 'MSSQL',
    'mongodb': 'MongoDB',
    'redis': 'Redis / Valkey', 'valkey': 'Redis / Valkey',
    'elasticsearch': 'Elasticsearch / OpenSearch', 'opensearch': 'Elasticsearch / OpenSearch',
    'influxdb': 'InfluxDB',
    'memcached': 'Memcached',
}


# ── SSH tunnel ────────────────────────────────────────────────────────────────

class _SSHTunnel:
    """One-shot SSH TCP port-forward tunnel."""

    def __init__(self, ssh_host, ssh_port, ssh_user, ssh_password, ssh_key,
                 remote_host, remote_port, timeout=10):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = {
            'hostname': str(ssh_host), 'port': int(ssh_port),
            'username': str(ssh_user),
            'timeout': timeout, 'banner_timeout': timeout, 'auth_timeout': timeout,
        }
        if ssh_key:
            kw['key_filename'] = str(ssh_key)
        elif ssh_password:
            kw['password'] = str(ssh_password)
        client.connect(**kw)
        transport = client.get_transport()
        transport.set_keepalive(10)
        self._client = client
        self._transport = transport
        self._remote_host = str(remote_host)
        self._remote_port = int(remote_port)
        self._accept_timeout = timeout + 5

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', 0))
        srv.listen(1)
        self.local_port = srv.getsockname()[1]
        self._server = srv
        self._thread = threading.Thread(target=self._accept_and_relay, daemon=True)
        self._thread.start()

    def _accept_and_relay(self):
        try:
            self._server.settimeout(self._accept_timeout)
            conn, addr = self._server.accept()
            self._server.close()
        except Exception:
            return
        chan = None
        try:
            chan = self._transport.open_channel(
                'direct-tcpip', (self._remote_host, self._remote_port), addr)
            if chan is None:
                raise RuntimeError('SSH channel returned None')
            chan.settimeout(None)
        except Exception:
            conn.close()
            return
        try:
            self._relay(conn, chan)
        finally:
            try: conn.close()
            except Exception: pass
            try: chan.close()
            except Exception: pass

    @staticmethod
    def _relay(conn, chan):
        def fwd(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
        t1 = threading.Thread(target=fwd, args=(conn, chan), daemon=True)
        t2 = threading.Thread(target=fwd, args=(chan, conn), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()

    def close(self):
        try: self._server.close()
        except Exception: pass
        try: self._client.close()
        except Exception: pass


# ── ConfigOptions ─────────────────────────────────────────────────────────────

class ConfigOptions(IntEnum):
    enabled      = 1
    db_type      = 2
    conn_type    = 3
    host         = 100
    port         = 101
    user         = 102
    password     = 103
    db           = 104
    socket       = 105
    scheme       = 106
    auth_db      = 107
    db_index     = 108
    tls          = 109
    token        = 110
    ssh_host     = 200
    ssh_port     = 201
    ssh_user     = 202
    ssh_password = 203
    ssh_key      = 204


# ── Watchful ──────────────────────────────────────────────────────────────────

class Watchful(ModuleBase):

    ITEM_SCHEMA = _SCHEMA
    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    # ── Runtime monitoring ────────────────────────────────────────────

    def check(self):
        items = [k for k, v in self.get_conf('list', {}).items()
                 if (v if isinstance(v, bool) else
                     (v.get('enabled', self._DEFAULTS['enabled']) if isinstance(v, dict)
                      else self._DEFAULTS['enabled']))]
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as ex:
            futures = {ex.submit(self._ds_check, key): key for key in items}
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    self.dict_return.set(key, False, f'Datastore: {key} - *Error: {exc}* 💥')
        super().check()
        return self.dict_return

    def _ds_check(self, key):
        db_type   = self._get_conf(ConfigOptions.db_type, key)
        conn_type = self._get_conf(ConfigOptions.conn_type, key)
        label     = _PRETTY.get(db_type, db_type)

        cfg = self._build_cfg(key, db_type)
        ok, msg = self._backend_check(db_type, conn_type, cfg)

        if ok:
            s_msg = f'{label}: *{key}* ✅'
        else:
            s_msg = f'{label}: {key} - *Error: {msg}* ⚠️'

        self.dict_return.set(key, ok, s_msg, False, {'message': msg})
        if self.check_status_custom(ok, key, msg):
            self.send_message(s_msg, ok)

    def _build_cfg(self, key, db_type):
        """Collect all config fields for one item into a plain dict."""
        port = self._get_conf(ConfigOptions.port, key)
        if not port:
            port = _DEFAULT_PORTS.get(db_type, 0)
        ssh_port = self._get_conf(ConfigOptions.ssh_port, key) or 22
        return {
            'db_type':      db_type,
            'host':         self._get_conf(ConfigOptions.host,         key),
            'port':         port,
            'socket':       self._get_conf(ConfigOptions.socket,       key),
            'user':         self._get_conf(ConfigOptions.user,         key),
            'password':     self._get_conf(ConfigOptions.password,     key),
            'db':           self._get_conf(ConfigOptions.db,           key),
            'scheme':       self._get_conf(ConfigOptions.scheme,       key),
            'auth_db':      self._get_conf(ConfigOptions.auth_db,      key),
            'db_index':     self._get_conf(ConfigOptions.db_index,     key),
            'tls':          self._get_conf(ConfigOptions.tls,          key),
            'token':        self._get_conf(ConfigOptions.token,        key),
            'ssh_host':     self._get_conf(ConfigOptions.ssh_host,     key),
            'ssh_port':     ssh_port,
            'ssh_user':     self._get_conf(ConfigOptions.ssh_user,     key),
            'ssh_password': self._get_conf(ConfigOptions.ssh_password, key),
            'ssh_key':      self._get_conf(ConfigOptions.ssh_key,      key),
        }

    # ── Backend dispatcher ────────────────────────────────────────────

    @classmethod
    def _backend_check(cls, db_type, conn_type, cfg) -> tuple[bool, str]:
        """Return (ok, message) for the given db_type + conn_type."""
        if conn_type == 'ssh':
            if not _PARAMIKO:
                return False, 'paramiko is not installed (pip install paramiko)'
            try:
                tunnel = _SSHTunnel(
                    cfg['ssh_host'], cfg['ssh_port'], cfg['ssh_user'],
                    cfg['ssh_password'], cfg['ssh_key'],
                    cfg['host'], cfg['port'])
            except Exception as exc:
                return False, f'SSH error: {exc}'
            try:
                return cls._backend_check_direct(db_type, {**cfg, 'host': '127.0.0.1', 'port': tunnel.local_port})
            finally:
                tunnel.close()
        return cls._backend_check_direct(db_type, cfg)

    @classmethod
    def _backend_check_direct(cls, db_type, cfg) -> tuple[bool, str]:
        if db_type in ('mysql', 'mariadb'):
            return cls._test_mysql(cfg)
        if db_type == 'postgres':
            return cls._test_postgres(cfg)
        if db_type == 'mssql':
            return cls._test_mssql(cfg)
        if db_type == 'mongodb':
            return cls._test_mongodb(cfg)
        if db_type in ('redis', 'valkey'):
            return cls._test_redis(cfg)
        if db_type in ('elasticsearch', 'opensearch'):
            return cls._test_elasticsearch(cfg)
        if db_type == 'influxdb':
            return cls._test_influxdb(cfg)
        if db_type == 'memcached':
            return cls._test_memcached(cfg)
        return False, f'Unknown db_type: {db_type}'

    # ── MySQL / MariaDB ───────────────────────────────────────────────

    @classmethod
    def _test_mysql(cls, cfg) -> tuple[bool, str]:
        conn_type = cfg.get('conn_type', 'tcp')
        if conn_type == 'socket':
            path = cfg.get('socket', '')
            if not path or not os.path.exists(path):
                return False, 'Socket file does not exist'
            return cls._pymysql_ping(unix_socket=path,
                user=cfg['user'], password=cfg['password'], db=cfg['db'])
        return cls._pymysql_ping(
            host=cfg['host'], port=int(cfg['port']),
            user=cfg['user'], password=cfg['password'], db=cfg['db'])

    @staticmethod
    def _pymysql_ping(host='', port=3306, user='', password='', db='', unix_socket='') -> tuple[bool, str]:
        try:
            kw = {'user': user, 'password': password, 'db': db,
                  'charset': 'utf8mb4', 'connect_timeout': 10,
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
                return False, 'Access denied'
            if code == '2003':
                if '(timed out)' in msg:   return False, "Can't connect: timed out"
                if '[Errno 111]' in msg:   return False, "Can't connect: connection refused"
                if '[Errno 113]' in msg:   return False, "Can't connect: no route to host"
                return False, "Can't connect to MySQL server"
            return False, msg
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT 1')
            return True, ''
        except Exception as exc:
            return False, repr(exc)
        finally:
            conn.close()

    # ── PostgreSQL ────────────────────────────────────────────────────

    @classmethod
    def _test_postgres(cls, cfg) -> tuple[bool, str]:
        if not _PSYCOPG2:
            return False, 'psycopg2 is not installed (pip install psycopg2-binary)'
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            kw = {'user': cfg['user'], 'password': cfg['password'],
                  'dbname': cfg['db'] or 'postgres', 'connect_timeout': 10}
            if cfg.get('tls'):
                kw['sslmode'] = 'require'
            if conn_type == 'socket':
                path = cfg.get('socket', '')
                if not path:
                    return False, 'Socket path not configured'
                kw['host'] = path
            else:
                kw['host'] = cfg['host']
                kw['port'] = int(cfg['port'])
            conn = psycopg2.connect(**kw)
            conn.close()
            return True, ''
        except Exception as exc:
            return False, str(exc)

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
    def _test_mssql(cls, cfg) -> tuple[bool, str]:
        if not _PYMSSQL:
            return False, 'pymssql is not installed (pip install pymssql)'
        try:
            conn = pymssql.connect(
                server=cfg['host'], port=str(int(cfg['port'])),
                user=cfg['user'], password=cfg['password'],
                database=cfg['db'] or 'master',
                login_timeout=10, tds_version='7.4')
            conn.close()
            return True, ''
        except Exception as exc:
            return False, cls._mssql_msg(exc)

    # ── MongoDB ───────────────────────────────────────────────────────

    @classmethod
    def _test_mongodb(cls, cfg) -> tuple[bool, str]:
        if not _PYMONGO:
            return False, 'pymongo is not installed (pip install pymongo)'
        try:
            kw = {
                'host': cfg['host'], 'port': int(cfg['port']),
                'serverSelectionTimeoutMS': 10000,
                'connectTimeoutMS': 10000,
            }
            if cfg['user']:
                kw['username'] = cfg['user']
                kw['password'] = cfg['password']
                kw['authSource'] = cfg.get('auth_db') or 'admin'
            if cfg.get('tls'):
                kw['tls'] = True
            client = pymongo.MongoClient(**kw)
            client.admin.command('ping')
            client.close()
            return True, ''
        except Exception as exc:
            return False, str(exc)

    # ── Redis / Valkey ────────────────────────────────────────────────

    @classmethod
    def _test_redis(cls, cfg) -> tuple[bool, str]:
        if not _REDIS:
            return False, 'redis is not installed (pip install redis)'
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            kw = {
                'password': cfg['password'] or None,
                'db': int(cfg.get('db_index', 0)),
                'socket_timeout': 10,
                'socket_connect_timeout': 10,
            }
            if cfg.get('tls'):
                kw['ssl'] = True
            if conn_type == 'socket':
                path = cfg.get('socket', '')
                if not path:
                    return False, 'Socket path not configured'
                kw['unix_socket_path'] = path
                r = redis_lib.Redis(**kw)
            else:
                kw['host'] = cfg['host']
                kw['port'] = int(cfg['port'])
                r = redis_lib.Redis(**kw)
            r.ping()
            r.close()
            return True, ''
        except Exception as exc:
            return False, str(exc)

    # ── Elasticsearch / OpenSearch ────────────────────────────────────

    @classmethod
    def _test_elasticsearch(cls, cfg) -> tuple[bool, str]:
        scheme = cfg.get('scheme', 'http')
        host   = cfg['host']
        port   = int(cfg['port'])
        url    = f'{scheme}://{host}:{port}/_cluster/health'
        try:
            req = urllib.request.Request(url)
            if cfg['user']:
                creds = base64.b64encode(f"{cfg['user']}:{cfg['password']}".encode()).decode()
                req.add_header('Authorization', f'Basic {creds}')
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
            status = body.get('status', '')
            if status == 'red':
                return False, f'Cluster status is RED'
            return True, ''
        except urllib.error.HTTPError as exc:
            return False, f'HTTP {exc.code}: {exc.reason}'
        except Exception as exc:
            return False, str(exc)

    # ── InfluxDB ──────────────────────────────────────────────────────

    @classmethod
    def _test_influxdb(cls, cfg) -> tuple[bool, str]:
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
            with urllib.request.urlopen(_req('/health'), timeout=10) as resp:
                body = json.loads(resp.read())
            status = body.get('status', '')
            return (True, '') if status == 'pass' else (False, f'Health status: {status}')
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                return False, f'HTTP {exc.code}: {exc.reason}'
        except Exception as exc:
            return False, str(exc)

        # InfluxDB 1.x — /ping endpoint (returns 204 No Content)
        try:
            with urllib.request.urlopen(_req('/ping'), timeout=10):
                pass
            return True, ''
        except urllib.error.HTTPError as exc:
            return False, f'HTTP {exc.code}: {exc.reason}'
        except Exception as exc:
            return False, str(exc)

    # ── Memcached ─────────────────────────────────────────────────────

    @classmethod
    def _test_memcached(cls, cfg) -> tuple[bool, str]:
        if not _PYMEMCACHE:
            return False, 'pymemcache is not installed (pip install pymemcache)'
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            if conn_type == 'socket':
                path = cfg.get('socket', '')
                if not path:
                    return False, 'Socket path not configured'
                server = path
            else:
                server = (cfg['host'], int(cfg['port']))
            client = _pmc.Client(server, connect_timeout=10, timeout=10)
            client.get('__ping__')
            client.close()
            return True, ''
        except Exception as exc:
            return False, str(exc)

    # ── Web UI — test_connection ──────────────────────────────────────

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        if config.get('_test_mode') == 'ssh':
            return cls._test_ssh_only(config)

        db_type   = str(config.get('db_type', 'mysql'))
        conn_type = str(config.get('conn_type', 'tcp'))
        port      = int(config.get('port') or 0) or _DEFAULT_PORTS.get(db_type, 0)
        ssh_port  = int(config.get('ssh_port') or 22)
        cfg = {**config, 'port': port, 'ssh_port': ssh_port, 'conn_type': conn_type,
               'db_index': int(config.get('db_index', 0) or 0)}

        ok, msg = cls._backend_check(db_type, conn_type, cfg)
        label = _PRETTY.get(db_type, db_type)
        return {'ok': ok, 'message': f'{label}: {msg}' if not ok else f'{label}: connection successful'}

    @classmethod
    def _test_ssh_only(cls, config: dict) -> dict:
        if not _PARAMIKO:
            return {'ok': False, 'message': 'paramiko is not installed (pip install paramiko)'}
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kw = {
                'hostname': str(config.get('ssh_host', '')),
                'port': int(config.get('ssh_port') or 22),
                'username': str(config.get('ssh_user', '')),
                'timeout': 10, 'banner_timeout': 10, 'auth_timeout': 10,
            }
            if config.get('ssh_key'):
                kw['key_filename'] = config['ssh_key']
            elif config.get('ssh_password'):
                kw['password'] = config['ssh_password']
            client.connect(**kw)
            client.close()
            return {'ok': True, 'message': 'SSH connection successful'}
        except Exception as exc:
            return {'ok': False, 'message': f'SSH error: {exc}'}

    # ── Web UI — list_databases ───────────────────────────────────────

    @classmethod
    def list_databases(cls, config: dict) -> dict:
        db_type   = str(config.get('db_type', 'mysql'))
        conn_type = str(config.get('conn_type', 'tcp'))
        port      = int(config.get('port') or 0) or _DEFAULT_PORTS.get(db_type, 0)
        ssh_port  = int(config.get('ssh_port') or 22)
        cfg = {**config, 'port': port, 'ssh_port': ssh_port, 'conn_type': conn_type}

        if conn_type == 'ssh':
            if not _PARAMIKO:
                return {'ok': False, 'message': 'paramiko is not installed', 'databases': []}
            try:
                tunnel = _SSHTunnel(
                    cfg['ssh_host'], cfg['ssh_port'], cfg['ssh_user'],
                    cfg['ssh_password'], cfg['ssh_key'],
                    cfg['host'], port)
            except Exception as exc:
                return {'ok': False, 'message': f'SSH error: {exc}', 'databases': []}
            try:
                return cls._list_databases_direct(db_type, {**cfg, 'host': '127.0.0.1', 'port': tunnel.local_port})
            finally:
                tunnel.close()
        return cls._list_databases_direct(db_type, cfg)

    @classmethod
    def _list_databases_direct(cls, db_type, cfg) -> dict:
        if db_type in ('mysql', 'mariadb'):
            return cls._list_mysql(cfg)
        if db_type == 'postgres':
            return cls._list_postgres(cfg)
        if db_type == 'mssql':
            return cls._list_mssql(cfg)
        if db_type == 'mongodb':
            return cls._list_mongodb(cfg)
        if db_type in ('elasticsearch', 'opensearch'):
            return cls._list_es_indices(cfg)
        if db_type == 'influxdb':
            return cls._list_influxdb(cfg)
        return {'ok': False, 'message': f'{_PRETTY.get(db_type, db_type)} does not support database listing', 'databases': []}

    @classmethod
    def _list_mysql(cls, cfg) -> dict:
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            kw = {'user': cfg['user'], 'password': cfg['password'],
                  'charset': 'utf8mb4', 'connect_timeout': 10,
                  'cursorclass': pymysql.cursors.DictCursor}
            if conn_type == 'socket':
                kw['unix_socket'] = cfg.get('socket', '')
            else:
                kw['host'] = cfg['host']; kw['port'] = int(cfg['port'])
            conn = pymysql.connect(**kw)
        except Exception as exc:
            return {'ok': False, 'message': repr(exc), 'databases': []}
        try:
            with conn.cursor() as cur:
                cur.execute('SHOW DATABASES')
                return {'ok': True, 'message': '', 'databases': [r['Database'] for r in cur.fetchall()]}
        except Exception as exc:
            return {'ok': False, 'message': repr(exc), 'databases': []}
        finally:
            conn.close()

    @classmethod
    def _list_postgres(cls, cfg) -> dict:
        if not _PSYCOPG2:
            return {'ok': False, 'message': 'psycopg2 is not installed', 'databases': []}
        conn_type = cfg.get('conn_type', 'tcp')
        try:
            kw = {'user': cfg['user'], 'password': cfg['password'],
                  'dbname': 'postgres', 'connect_timeout': 10}
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
            return {'ok': True, 'message': '', 'databases': dbs}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'databases': []}

    @classmethod
    def _list_mssql(cls, cfg) -> dict:
        if not _PYMSSQL:
            return {'ok': False, 'message': 'pymssql is not installed', 'databases': []}
        try:
            conn = pymssql.connect(
                server=cfg['host'], port=str(int(cfg['port'])),
                user=cfg['user'], password=cfg['password'],
                database='master', login_timeout=10)
            with conn.cursor() as cur:
                cur.execute('SELECT name FROM sys.databases ORDER BY name')
                dbs = [r[0] for r in cur.fetchall()]
            conn.close()
            return {'ok': True, 'message': '', 'databases': dbs}
        except Exception as exc:
            return {'ok': False, 'message': cls._mssql_msg(exc), 'databases': []}

    @classmethod
    def _list_mongodb(cls, cfg) -> dict:
        if not _PYMONGO:
            return {'ok': False, 'message': 'pymongo is not installed', 'databases': []}
        try:
            kw = {'host': cfg['host'], 'port': int(cfg['port']),
                  'serverSelectionTimeoutMS': 10000}
            if cfg['user']:
                kw['username'] = cfg['user']
                kw['password'] = cfg['password']
                kw['authSource'] = cfg.get('auth_db') or 'admin'
            if cfg.get('tls'):
                kw['tls'] = True
            client = pymongo.MongoClient(**kw)
            dbs = client.list_database_names()
            client.close()
            return {'ok': True, 'message': '', 'databases': sorted(dbs)}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'databases': []}

    @classmethod
    def _list_es_indices(cls, cfg) -> dict:
        scheme = cfg.get('scheme', 'http')
        url    = f'{scheme}://{cfg["host"]}:{int(cfg["port"])}/_cat/indices?format=json&h=index&s=index'
        try:
            req = urllib.request.Request(url)
            if cfg['user']:
                creds = base64.b64encode(f"{cfg['user']}:{cfg['password']}".encode()).decode()
                req.add_header('Authorization', f'Basic {creds}')
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
            indices = sorted(e['index'] for e in body if not e['index'].startswith('.'))
            return {'ok': True, 'message': '', 'databases': indices}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'databases': []}

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
            with urllib.request.urlopen(_req('/api/v2/buckets'), timeout=10) as resp:
                body = json.loads(resp.read())
            buckets = sorted(b['name'] for b in body.get('buckets', []) if not b['name'].startswith('_'))
            return {'ok': True, 'message': '', 'databases': buckets}
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                return {'ok': False, 'message': f'HTTP {exc.code}: {exc.reason}', 'databases': []}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'databases': []}

        # InfluxDB 1.x — SHOW DATABASES
        try:
            with urllib.request.urlopen(_req('/query?q=SHOW+DATABASES'), timeout=10) as resp:
                body = json.loads(resp.read())
            values = body.get('results', [{}])[0].get('series', [{}])[0].get('values', [])
            dbs = sorted(r[0] for r in values if r[0] != '_internal')
            return {'ok': True, 'message': '', 'databases': dbs}
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'databases': []}

    # ── Config helpers ─────────────────────────────────────────────────

    def _get_conf(self, opt: ConfigOptions, key: str, default=None):
        if default is None:
            match opt:
                case ConfigOptions.port:
                    default = self.get_conf('port', self._DEFAULTS['port'])
                case ConfigOptions.ssh_port:
                    default = self.get_conf('ssh_port', self._DEFAULTS.get('ssh_port', 22))
                case ConfigOptions.db_index:
                    default = self.get_conf('db_index', self._DEFAULTS.get('db_index', 0))
                case ConfigOptions.tls:
                    default = self.get_conf('tls', self._DEFAULTS.get('tls', False))
                case ConfigOptions.enabled:
                    default = self.get_conf('enabled', self._DEFAULTS['enabled'])
                case _:
                    default = self.get_conf(opt.name, self._DEFAULTS.get(opt.name, ''))
        val = self.get_conf_in_list(opt, key, default)
        match opt:
            case ConfigOptions.port | ConfigOptions.ssh_port | ConfigOptions.db_index:
                return self._parse_conf_int(val, default)
            case ConfigOptions.enabled | ConfigOptions.tls:
                return bool(val)
            case _:
                return self._parse_conf_str(val, default)
