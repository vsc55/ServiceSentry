#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Datastore watchful: what it reports about an item.
#
"""Reach the datastore, optionally through a tunnel, and say what came back.

The engine-specific part is not here: this decides WHICH backend to ask, whether to stand a
tunnel up first, how to name the result and what a list of databases means against what was
expected. Swapping MySQL for MongoDB changes nothing in this file, which is the point.
"""

from . import deps
from .tables import _DEFAULT_PORTS, _PRETTY, ConfigOptions
from .tunnel import _SSHTunnel


class DatastoreChecks:
    """The per-item check, mixed into ``Watchful``."""

    def _ds_check(self, key):
        db_type   = self._get_conf(ConfigOptions.db_type, key)
        conn_type = self._get_conf(ConfigOptions.conn_type, key)
        # Display name: the editable item label (e.g. "NS1 - mysql") if set, else
        # the DB type's pretty name.  The key itself is an opaque UID.
        disp = (self.get_conf(['list', key, 'label'], '') or '').strip() or _PRETTY.get(db_type, db_type)

        cfg = self._build_cfg(key, db_type)
        ok, msg, metrics = self._check_databases(db_type, conn_type, cfg)

        # Numeric engine metrics (connections/uptime/memory/queries) recorded for
        # the history charts; non-numeric values are dropped.
        other = {'message': msg}
        for mk, mv in (metrics or {}).items():
            if isinstance(mv, (int, float)) and not isinstance(mv, bool):
                other[mk] = mv

        conns = other.get('connections')
        # Per-item limit overrides; blank/0 inherits the module-level default
        # (Configuration > Modules).  0 everywhere = disabled.
        limit = int(self.get_conf(['list', key, 'alert_connections'], 0)
                    or self.module_default('alert_connections', 0) or 0)
        # A connection-count threshold breach is a warning (the datastore is reachable);
        # a real connect/query error (the else branch, ok already False) stays a down.
        threshold_breach = False
        if ok and limit > 0 and isinstance(conns, (int, float)) and conns > limit:
            ok  = False
            threshold_breach = True
            msg = f'{int(conns)} connections > {limit}'   # internal reason (change detection)
            s_msg = self._msg('ds_conn_high', disp, int(conns), limit)
        elif ok:
            # Shared formatter → identical detail to the web "Test connection".
            s_msg = self._msg('ds_ok', disp, self._summary_text(True, msg, metrics))
        else:
            s_msg = self._msg('ds_conn_error', disp, msg)

        severity = 'warning' if threshold_breach else ''
        # change_msg=msg: the INTERNAL reason, so a failure that mutates (refused →
        # timeout) alerts again instead of hiding under an unchanged "still down".
        self._emit(key, ok, s_msg, other, severity=severity, name=disp, change_msg=msg)

    def _build_cfg(self, key, db_type):
        """Collect all config fields for one item into a plain dict."""
        port = self._get_conf(ConfigOptions.port, key)
        if not port:
            port = _DEFAULT_PORTS.get(db_type, 0)
        ssh_port = self._get_conf(ConfigOptions.ssh_port, key) or 22
        return {
            'db_type':      db_type,
            'conn_type':    self._get_conf(ConfigOptions.conn_type,    key),
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
            'ssh_key_string': self._get_conf(ConfigOptions.ssh_key_string, key),
            'ssh_verify_host': self._get_conf(ConfigOptions.ssh_verify_host, key),
            'timeout':      (self._get_conf(ConfigOptions.timeout, key)
                             or int(self.module_default('timeout', 10) or 10)),
        }

    # ── Backend dispatcher ────────────────────────────────────────────

    @classmethod
    def _check_databases(cls, db_type, conn_type, cfg) -> tuple:
        """Connectivity + multi-database existence check.

        The ``db`` field may hold several comma-separated databases. With one
        (or none) it connects normally to that database; with several it
        connects at server level (for connectivity + metrics) and verifies that
        every listed database exists, reusing the per-engine listing. Returns
        ``(ok, message, metrics)``."""
        dbs = [d.strip() for d in str(cfg.get('db') or '').split(',') if d.strip()]
        if len(dbs) <= 1:
            return cls._backend_check(db_type, conn_type, {**cfg, 'db': dbs[0] if dbs else ''})

        ok, msg, metrics = cls._backend_check(db_type, conn_type, {**cfg, 'db': ''})
        if ok:
            listing = cls.list_databases({**cfg, 'db_type': db_type, 'conn_type': conn_type, 'db': ''})
            if listing.get('ok'):
                avail = {str(x).lower() for x in (listing.get('items') or [])}
                missing = [d for d in dbs if d.lower() not in avail]
                if missing:
                    ok, msg = False, f"missing: {', '.join(missing)}"
                else:
                    msg = f'{len(dbs)} databases OK'
            else:
                ok, msg = False, (listing.get('message') or 'cannot list databases')
        return ok, msg, metrics

    @staticmethod
    def _summary_text(ok, msg, metrics) -> str:
        """Human detail line shared by the monitoring check (``_ds_check``) and the
        web "Test connection" action, so both always report the same thing:
        the database-existence result (e.g. "32 databases OK") plus the live
        connection count when the engine exposes it."""
        if not ok:
            return msg or 'connection failed'
        conns = (metrics or {}).get('connections')
        bits = []
        if msg:
            bits.append(msg)
        if isinstance(conns, (int, float)) and not isinstance(conns, bool):
            bits.append(f'{int(conns)} conn.')
        return ', '.join(bits) if bits else 'connection successful'

    @staticmethod
    def _to(cfg) -> int:
        """Connection timeout (seconds) from cfg; blank/invalid -> 10."""
        try:
            return int(cfg.get('timeout') or 0) or 10
        except (TypeError, ValueError):
            return 10

    @classmethod
    def _backend_check(cls, db_type, conn_type, cfg) -> tuple:
        """Return (ok, message, metrics) for the given db_type + conn_type.

        ``metrics`` is a dict of engine stats (connections/uptime/memory/queries)
        the backend could read — empty when the engine doesn't expose them."""
        if conn_type == 'ssh':
            if not deps._PARAMIKO:
                return False, 'paramiko is not installed (pip install paramiko)', {}
            try:
                tunnel = _SSHTunnel(
                    cfg['ssh_host'], cfg['ssh_port'], cfg['ssh_user'],
                    cfg['ssh_password'], cfg['ssh_key'],
                    cfg['host'], cfg['port'],
                    verify_host=bool(cfg.get('ssh_verify_host', False)),
                    ssh_key_string=cfg.get('ssh_key_string', ''), timeout=cls._to(cfg))
            except Exception as exc:
                return False, f'SSH error: {exc}', {}
            try:
                return cls._backend_check_direct(db_type, {**cfg, 'host': '127.0.0.1', 'port': tunnel.local_port})
            finally:
                tunnel.close()
        return cls._backend_check_direct(db_type, cfg)

    @classmethod
    def _backend_check_direct(cls, db_type, cfg) -> tuple:
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
        return False, f'Unknown db_type: {db_type}', {}
