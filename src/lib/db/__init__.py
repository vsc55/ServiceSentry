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

    if driver == 'sqlite':
        from .sqlite import SQLiteConnector  # noqa: PLC0415
        path = cfg.get('path') or default_sqlite_path
        return SQLiteConnector(path)

    if driver == 'postgresql':
        from .postgresql import PostgreSQLConnector  # noqa: PLC0415
        return PostgreSQLConnector(cfg)

    if driver in ('mysql', 'mariadb'):
        from .mysql import MySQLConnector  # noqa: PLC0415
        return MySQLConnector(cfg)

    raise ValueError(
        f'Unknown database driver: {driver!r}. '
        "Supported: 'sqlite', 'postgresql', 'mysql', 'mariadb'."
    )


__all__ = [
    'get_connector', 'BaseConnector',
    'module_table', 'collect_module_tables', 'reconcile_module_tables',
]
