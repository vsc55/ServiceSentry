#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Database connector factory.

Usage::

    from lib.db import get_connector

    # From config.json:
    # { "database": { "driver": "sqlite", "path": "data.db" } }
    connector = get_connector(config['database'], default_sqlite_path='/var/data.db')

Supported drivers:
    sqlite      — built-in, no extra dependencies (default)
    postgresql  — requires psycopg2-binary
    mysql       — requires PyMySQL
    mariadb     — alias for mysql
"""

from __future__ import annotations

from lib.config.spec import cfg_get
from .base import BaseConnector
from .module_tables import (
    collect_module_tables,
    module_table,
    reconcile_module_tables,
)


def get_connector(
    config: dict | None = None,
    *,
    default_sqlite_path: str = ':memory:',
) -> BaseConnector:
    """Create and return a connector from *config*.

    ``config`` is the ``database`` section of ``config.json``.  When ``None``
    or when ``driver`` is omitted, a SQLite connector is returned using
    *default_sqlite_path*.

    Args:
        config:              dict with ``driver`` and backend-specific keys.
        default_sqlite_path: path used when driver is ``sqlite`` and no
                             ``path`` key is present in *config*.
    """
    cfg    = config or {}
    driver = cfg_get(cfg, 'database|driver').lower()

    from lib.object_base import ObjectBase  # noqa: PLC0415
    from lib.debug import DebugLevel  # noqa: PLC0415

    if driver == 'sqlite':
        from .sqlite import SQLiteConnector  # noqa: PLC0415
        path = cfg.get('path') or default_sqlite_path
        ObjectBase.debug.print(f"> DB >> driver=sqlite path={path}", DebugLevel.info)
        return SQLiteConnector(path)

    if driver == 'postgresql':
        from .postgresql import PostgreSQLConnector  # noqa: PLC0415
        ObjectBase.debug.print(
            f"> DB >> driver=postgresql host={cfg.get('host', 'localhost')} "
            f"db={cfg.get('name', 'servicesentry')}", DebugLevel.info)
        return PostgreSQLConnector(cfg)

    if driver in ('mysql', 'mariadb'):
        from .mysql import MySQLConnector  # noqa: PLC0415
        ObjectBase.debug.print(
            f"> DB >> driver={driver} host={cfg.get('host', 'localhost')} "
            f"db={cfg.get('name', 'servicesentry')}", DebugLevel.info)
        return MySQLConnector(cfg)

    raise ValueError(
        f'Unknown database driver: {driver!r}. '
        "Supported: 'sqlite', 'postgresql', 'mysql', 'mariadb'."
    )


def build_syslog_connector(syslog_db_cfg: dict | None, *, main_connector,
                           default_sqlite_path: str):
    """Return the connector syslog storage should use.

    When ``syslog_db_cfg['enabled']`` is set, a *dedicated* connector is built
    from that config (so a high-volume syslog feed can live in its own database,
    isolated from the system DB).  Otherwise — or on any error — the shared
    *main_connector* is returned.  The config mirrors the ``database`` section
    (driver/path/host/port/name/user/password).
    """
    sdb = syslog_db_cfg or {}
    if not sdb.get('enabled'):
        return main_connector
    from lib.object_base import ObjectBase  # noqa: PLC0415
    from lib.debug import DebugLevel  # noqa: PLC0415
    try:
        cfg = {
            'driver':   (sdb.get('driver') or 'sqlite'),
            'path':     sdb.get('path') or '',
            'host':     sdb.get('host') or 'localhost',
            'port':     sdb.get('port'),
            'name':     sdb.get('name') or 'servicesentry_syslog',
            'user':     sdb.get('user') or '',
            'password': sdb.get('password') or '',
        }
        conn = get_connector(cfg, default_sqlite_path=default_sqlite_path)
        ObjectBase.debug.print("> Syslog DB >> using dedicated database "
                               f"(driver={cfg['driver']})", DebugLevel.info)
        return conn
    except Exception as exc:  # pylint: disable=broad-except
        ObjectBase.debug.print("> Syslog DB >> dedicated connector failed "
                               f"({exc}); falling back to the system database",
                               DebugLevel.error)
        return main_connector


__all__ = [
    'get_connector', 'build_syslog_connector', 'BaseConnector',
    'module_table', 'collect_module_tables', 'reconcile_module_tables',
]
