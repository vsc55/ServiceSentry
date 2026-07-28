#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Datastore watchful: what the panel invokes.
#
"""Test a connection and list the databases behind it.

Both are the same shape: build a config from what the form currently holds - saved or not -
stand up a tunnel if the item asks for one, and hand off to the engine driver. Neither emits
a result nor notifies anyone, which is what separates them from the check.
"""

from . import deps
from .tunnel import _pkey_from_string
from .tables import _DEFAULT_PORTS, _PRETTY
from .tunnel import _SSHTunnel

if deps._PARAMIKO:
    import paramiko


class DatastoreActions:
    """Operations the UI calls by name (see ``WATCHFUL_ACTIONS``)."""

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
               'db_index': int(config.get('db_index', 0) or 0),
               'timeout': int(config.get('timeout') or 0) or 10}

        ok, msg, metrics = cls._check_databases(db_type, conn_type, cfg)
        label = _PRETTY.get(db_type, db_type)
        return {'ok': ok, 'message': f'{label}: {cls._summary_text(ok, msg, metrics)}'}

    @classmethod
    def _test_ssh_only(cls, config: dict) -> dict:
        if not deps._PARAMIKO:
            return {'ok': False, 'message': 'paramiko is not installed (pip install paramiko)'}
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kw = {
                'hostname': str(config.get('ssh_host', '')),
                'port': int(config.get('ssh_port') or 22),
                'username': str(config.get('ssh_user', '')),
                'timeout': cls._to(config), 'banner_timeout': cls._to(config), 'auth_timeout': cls._to(config),
            }
            if config.get('ssh_key_string'):
                kw['pkey'] = _pkey_from_string(str(config['ssh_key_string']),
                                               str(config.get('ssh_password', '') or ''))
            elif config.get('ssh_key'):
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
        cfg = {**config, 'port': port, 'ssh_port': ssh_port, 'conn_type': conn_type,
               'timeout': int(config.get('timeout') or 0) or 10}

        if conn_type == 'ssh':
            if not deps._PARAMIKO:
                return {'ok': False, 'message': 'paramiko is not installed', 'items': []}
            try:
                tunnel = _SSHTunnel(
                    cfg['ssh_host'], cfg['ssh_port'], cfg['ssh_user'],
                    cfg['ssh_password'], cfg['ssh_key'],
                    cfg['host'], port,
                    verify_host=bool(cfg.get('ssh_verify_host', False)), timeout=cls._to(cfg))
            except Exception as exc:
                return {'ok': False, 'message': f'SSH error: {exc}', 'items': []}
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
        return {'ok': False, 'message': f'{_PRETTY.get(db_type, db_type)} does not support database listing', 'items': []}
