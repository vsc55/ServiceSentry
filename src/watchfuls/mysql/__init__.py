#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Javier Pastor (aka VSC55)
# <jpastor at cerebelum dot net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import concurrent.futures
import json
import os
import os.path
import socket
import threading
from enum import IntEnum

import pymysql
import pymysql.cursors

try:
    import paramiko
    _PARAMIKO_AVAILABLE = True
except ImportError:
    _PARAMIKO_AVAILABLE = False

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


class _SSHTunnel:
    """Minimal SSH TCP port-forwarding tunnel for a single pymysql connection.

    Binds a local random TCP port, accepts one connection, and relays it
    through an SSH direct-tcpip channel to the remote MySQL host/port.
    """

    def __init__(self, ssh_host, ssh_port, ssh_user, ssh_password, ssh_key,
                 remote_host, remote_port, timeout=10):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = {
            'hostname': str(ssh_host),
            'port': int(ssh_port),
            'username': str(ssh_user),
            'timeout': timeout,
            'banner_timeout': timeout,
            'auth_timeout': timeout,
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
            try:
                conn.close()
            except Exception:
                pass
            try:
                chan.close()
            except Exception:
                pass

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
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def close(self):
        try:
            self._server.close()
        except Exception:
            pass
        try:
            self._client.close()
        except Exception:
            pass


class ConfigOptions(IntEnum):
    enabled      = 1
    host         = 100
    port         = 101
    user         = 102
    password     = 103
    db           = 104
    socket       = 105
    conn_type    = 106
    ssh_host     = 200
    ssh_port     = 201
    ssh_user     = 202
    ssh_password = 203
    ssh_key      = 204


class Watchful(ModuleBase):

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        list_db = self._check_get_list_db()
        self._check_run(list_db)
        super().check()
        return self.dict_return

    def _check_get_list_db(self):
        return_list = []
        for (key, value) in self.get_conf('list', {}).items():
            if isinstance(value, bool):
                is_enabled = value
            elif isinstance(value, dict):
                is_enabled = self._get_conf(ConfigOptions.enabled, key)
            else:
                is_enabled = self._DEFAULTS['enabled']
            self._debug(f"{key} - Enabled: {is_enabled}", DebugLevel.info)
            if is_enabled:
                return_list.append(key)
        return return_list

    def _check_run(self, list_db):
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_db = {executor.submit(self._db_check, db): db for db in list_db}
            for future in concurrent.futures.as_completed(future_to_db):
                db = future_to_db[future]
                try:
                    future.result()
                except Exception as exc:
                    message = f'MySQL: {db} - *Error: {exc}* 💥'
                    self.dict_return.set(db, False, message)

    def _db_check(self, db):
        conn_type = self._get_conf(ConfigOptions.conn_type, db)
        user      = self._get_conf(ConfigOptions.user, db)
        password  = self._get_conf(ConfigOptions.password, db)
        db_name   = self._get_conf(ConfigOptions.db, db)

        # Backwards compat: legacy configs with socket path but no conn_type default to "tcp";
        # promote them automatically so existing setups keep working.
        if conn_type == 'tcp':
            tmp_socket = self._get_conf(ConfigOptions.socket, db)
            if tmp_socket:
                conn_type = 'socket'

        if conn_type == 'socket':
            socket_path = self._get_conf(ConfigOptions.socket, db)
            status, message = self._db_connect_socket(socket_path, user, password, db_name)
        elif conn_type == 'ssh':
            host         = self._get_conf(ConfigOptions.host, db)
            port         = self._get_conf(ConfigOptions.port, db)
            ssh_host     = self._get_conf(ConfigOptions.ssh_host, db)
            ssh_port     = self._get_conf(ConfigOptions.ssh_port, db)
            ssh_user     = self._get_conf(ConfigOptions.ssh_user, db)
            ssh_password = self._get_conf(ConfigOptions.ssh_password, db)
            ssh_key      = self._get_conf(ConfigOptions.ssh_key, db)
            status, message = self._db_connect_ssh(
                ssh_host, ssh_port, ssh_user, ssh_password, ssh_key,
                host, port, user, password, db_name)
        else:  # tcp
            host = self._get_conf(ConfigOptions.host, db)
            port = self._get_conf(ConfigOptions.port, db)
            status, message = self._db_connect_tcp(host, port, user, password, db_name)

        s_message = 'MySQL: '
        if status == 'OK':
            s_message += f'*{db}* ✅'
            status = True
        else:
            s_message += f'{db} - *Error:* '
            match status:
                case '1045':
                    s_message += '*Access denied* 🔐'
                case '2003':
                    s_message += "*Can't connect to MySQL server*"
                    if '(timed out)' in message:
                        s_message += ' *(timed out)*'
                    elif '[Errno 111]' in message:
                        s_message += ' *(connection refused)*'
                    elif '[Errno 113]' in message:
                        s_message += ' *(no route to host)*'
                    else:
                        s_message += ' *(?????)*'
                    s_message += '⚠️'
                case 'SSH_ERROR' | 'SSH_UNAVAILABLE':
                    s_message += f'*SSH error: {message}* ⚠️'
                case _:
                    s_message += f'*{message}* ⚠️'
            status = False

        other_data = {'message': message}
        self.dict_return.set(db, status, s_message, False, other_data)
        if self.check_status_custom(status, db, message):
            self.send_message(s_message, status)

    # ── Connection helpers ────────────────────────────────────────────

    @staticmethod
    def _db_connect_tcp(host, port, user, password, db):
        return Watchful._pymysql_connect(
            host=str(host), port=int(port),
            user=user, password=password, db=db)

    @staticmethod
    def _db_connect_socket(socket_path, user, password, db):
        if not socket_path:
            return 'SOCKET_NOT_EXIST', 'No socket path configured'
        if not os.path.exists(socket_path):
            return 'SOCKET_NOT_EXIST', 'Socket file does not exist'
        return Watchful._pymysql_connect(
            unix_socket=str(socket_path), user=user, password=password, db=db)

    @classmethod
    def _db_connect_ssh(cls, ssh_host, ssh_port, ssh_user, ssh_password, ssh_key,
                        mysql_host, mysql_port, user, password, db):
        if not _PARAMIKO_AVAILABLE:
            return 'SSH_UNAVAILABLE', 'paramiko is not installed'
        try:
            tunnel = _SSHTunnel(
                ssh_host, ssh_port, ssh_user, ssh_password, ssh_key,
                mysql_host, mysql_port)
        except Exception as exc:
            return 'SSH_ERROR', str(exc)
        try:
            return cls._pymysql_connect(
                host='127.0.0.1', port=tunnel.local_port,
                user=user, password=password, db=db)
        finally:
            tunnel.close()

    @staticmethod
    def _pymysql_connect(host='', port=3306, user='', password='', db='', unix_socket=''):
        """Connect to MySQL, run SELECT 1, return (status_code, message)."""
        try:
            kw = {
                'user': user, 'password': password, 'db': db,
                'charset': 'utf8mb4', 'connect_timeout': 10,
                'cursorclass': pymysql.cursors.DictCursor,
            }
            if unix_socket:
                kw['unix_socket'] = unix_socket
            else:
                kw['host'] = host
                kw['port'] = int(port)
            connection = pymysql.connect(**kw)
        except Exception as exc:
            return_msg = repr(exc)
            err_code = str(exc).split(',')[0][1:]
            if err_code == '2003' and unix_socket:
                return 'SOCKET_ERROR', 'Socket file is not working'
            if err_code in ('1045', '2003'):
                return err_code, return_msg
            return '-9999', return_msg

        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                return 'OK', ''
        except Exception as exc:
            return '-9999', repr(exc)
        finally:
            connection.close()

    # ── Web UI test endpoint ──────────────────────────────────────────

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """Test a connection config dict. Called from the web UI test button."""
        if config.get('_test_mode') == 'ssh':
            return cls._test_ssh_only(config)

        conn_type = str(config.get('conn_type', 'tcp'))
        user      = str(config.get('user', ''))
        password  = str(config.get('password', ''))
        db        = str(config.get('db', ''))

        if conn_type == 'socket':
            socket_path = str(config.get('socket', ''))
            status, message = cls._db_connect_socket(socket_path, user, password, db)
        elif conn_type == 'ssh':
            host         = str(config.get('host', ''))
            port         = int(config.get('port', 3306))
            ssh_host     = str(config.get('ssh_host', ''))
            ssh_port     = int(config.get('ssh_port', 22))
            ssh_user     = str(config.get('ssh_user', ''))
            ssh_password = str(config.get('ssh_password', ''))
            ssh_key      = str(config.get('ssh_key', ''))
            status, message = cls._db_connect_ssh(
                ssh_host, ssh_port, ssh_user, ssh_password, ssh_key,
                host, port, user, password, db)
        else:  # tcp
            host = str(config.get('host', ''))
            port = int(config.get('port', 3306))
            status, message = cls._db_connect_tcp(host, port, user, password, db)

        return {'ok': status == 'OK', 'message': cls._format_test_message(status, message)}

    @classmethod
    def _test_ssh_only(cls, config: dict) -> dict:
        if not _PARAMIKO_AVAILABLE:
            return {'ok': False, 'message': 'paramiko is not installed (pip install paramiko)'}
        ssh_host     = str(config.get('ssh_host', ''))
        ssh_port     = int(config.get('ssh_port', 22))
        ssh_user     = str(config.get('ssh_user', ''))
        ssh_password = str(config.get('ssh_password', ''))
        ssh_key      = str(config.get('ssh_key', ''))
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kw = {
                'hostname': ssh_host, 'port': ssh_port, 'username': ssh_user,
                'timeout': 10, 'banner_timeout': 10, 'auth_timeout': 10,
            }
            if ssh_key:
                kw['key_filename'] = ssh_key
            elif ssh_password:
                kw['password'] = ssh_password
            client.connect(**kw)
            client.close()
            return {'ok': True, 'message': 'SSH connection successful'}
        except Exception as exc:
            return {'ok': False, 'message': f'SSH error: {exc}'}

    @classmethod
    def list_databases(cls, config: dict) -> dict:
        """Return the list of databases visible to the configured user."""
        conn_type = str(config.get('conn_type', 'tcp'))
        user      = str(config.get('user', ''))
        password  = str(config.get('password', ''))

        if conn_type == 'socket':
            socket_path = str(config.get('socket', ''))
            if not socket_path or not os.path.exists(socket_path):
                return {'ok': False, 'message': 'Socket file does not exist', 'databases': []}
            return cls._pymysql_list_databases(unix_socket=socket_path, user=user, password=password)
        elif conn_type == 'ssh':
            host         = str(config.get('host', ''))
            port         = int(config.get('port', 3306))
            ssh_host     = str(config.get('ssh_host', ''))
            ssh_port     = int(config.get('ssh_port', 22))
            ssh_user     = str(config.get('ssh_user', ''))
            ssh_password = str(config.get('ssh_password', ''))
            ssh_key      = str(config.get('ssh_key', ''))
            if not _PARAMIKO_AVAILABLE:
                return {'ok': False, 'message': 'paramiko is not installed', 'databases': []}
            try:
                tunnel = _SSHTunnel(ssh_host, ssh_port, ssh_user, ssh_password, ssh_key,
                                    host, port)
            except Exception as exc:
                return {'ok': False, 'message': f'SSH error: {exc}', 'databases': []}
            try:
                return cls._pymysql_list_databases(
                    host='127.0.0.1', port=tunnel.local_port, user=user, password=password)
            finally:
                tunnel.close()
        else:  # tcp
            host = str(config.get('host', ''))
            port = int(config.get('port', 3306))
            return cls._pymysql_list_databases(host=host, port=port, user=user, password=password)

    @staticmethod
    def _pymysql_list_databases(host='', port=3306, user='', password='', unix_socket=''):
        """Connect to MySQL and return the SHOW DATABASES list."""
        try:
            kw = {
                'user': user, 'password': password,
                'charset': 'utf8mb4', 'connect_timeout': 10,
                'cursorclass': pymysql.cursors.DictCursor,
            }
            if unix_socket:
                kw['unix_socket'] = unix_socket
            else:
                kw['host'] = host
                kw['port'] = int(port)
            connection = pymysql.connect(**kw)
        except Exception as exc:
            return {'ok': False, 'message': repr(exc), 'databases': []}
        try:
            with connection.cursor() as cursor:
                cursor.execute('SHOW DATABASES')
                rows = cursor.fetchall()
                return {'ok': True, 'message': '', 'databases': [r['Database'] for r in rows]}
        except Exception as exc:
            return {'ok': False, 'message': repr(exc), 'databases': []}
        finally:
            connection.close()

    @staticmethod
    def _format_test_message(status, message):
        match status:
            case 'OK':
                return 'Connection successful'
            case '1045':
                return 'Access denied'
            case '2003':
                if '(timed out)' in message:
                    return "Can't connect: timed out"
                if '[Errno 111]' in message:
                    return "Can't connect: connection refused"
                if '[Errno 113]' in message:
                    return "Can't connect: no route to host"
                return "Can't connect to MySQL server"
            case 'SOCKET_NOT_EXIST':
                return 'Socket file does not exist'
            case 'SOCKET_ERROR':
                return 'Socket file is not working'
            case 'SSH_UNAVAILABLE':
                return 'paramiko is not installed (pip install paramiko)'
            case 'SSH_ERROR':
                return f'SSH error: {message}'
            case _:
                return message or 'Unknown error'

    # ── Config helpers ────────────────────────────────────────────────

    def _get_conf(self, opt_find: IntEnum, dev_name: str, default_val=None):
        if default_val is None:
            match opt_find:
                case ConfigOptions.port:
                    val_def = self.get_conf(opt_find.name, self._DEFAULTS['port'])
                case ConfigOptions.ssh_port:
                    val_def = self.get_conf(opt_find.name, self._DEFAULTS.get('ssh_port', 22))
                case (ConfigOptions.socket | ConfigOptions.host
                      | ConfigOptions.user | ConfigOptions.password
                      | ConfigOptions.db | ConfigOptions.conn_type
                      | ConfigOptions.ssh_host | ConfigOptions.ssh_user
                      | ConfigOptions.ssh_password | ConfigOptions.ssh_key):
                    val_def = self.get_conf(opt_find.name, self._DEFAULTS.get(opt_find.name, ''))
                case ConfigOptions.enabled:
                    val_def = self.get_conf(opt_find.name, self._DEFAULTS['enabled'])
                case None:
                    raise ValueError("opt_find it can not be None!")
                case _:
                    raise TypeError(f"{opt_find.name} is not valid option!")
        else:
            val_def = default_val

        value = self.get_conf_in_list(opt_find, dev_name, val_def)

        match opt_find:
            case ConfigOptions.port | ConfigOptions.ssh_port:
                return self._parse_conf_int(value, val_def)
            case ConfigOptions.enabled:
                return bool(value)
            case _:
                return self._parse_conf_str(value, val_def)
