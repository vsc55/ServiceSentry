#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Abstract database connector interface.

All SQL passed to these methods must use ``?`` as the positional parameter
placeholder.  Concrete connectors translate to their native style internally
(``%s`` for PostgreSQL/MySQL, ``?`` for SQLite).

DDL should use the symbolic type tokens defined on each connector so that
``CREATE TABLE`` statements remain portable:

    connector.DDL_AUTOINCREMENT  — primary key with auto-increment
    connector.DDL_REAL           — floating-point column type
    connector.DDL_TEXT           — variable-length text column
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseConnector(ABC):
    """Abstract database connector.

    All implementations must be thread-safe.  The recommended approach is
    to maintain a per-thread connection via ``threading.local``.
    """

    # DDL type tokens — override in subclasses
    DDL_AUTOINCREMENT: str = 'INTEGER PRIMARY KEY AUTOINCREMENT'
    DDL_REAL:          str = 'REAL'
    DDL_TEXT:          str = 'TEXT'
    DDL_INTEGER:       str = 'INTEGER'

    # ── Schema management ────────────────────────────────────────────────────

    @abstractmethod
    def execute_ddl(self, ddl: str) -> None:
        """Execute one or more DDL statements (CREATE TABLE, CREATE INDEX…).

        DDL is split on ``;`` and each statement is run individually.
        Implementations must handle ``IF NOT EXISTS`` / ``IF EXISTS``
        gracefully.  DDL does NOT use ``?`` placeholders.
        """

    @abstractmethod
    def add_column_if_missing(
        self, table: str, column: str, col_type: str
    ) -> None:
        """Add a column to *table* if it does not already exist.

        Used for non-destructive schema migrations.
        """

    # ── Read ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Execute a SELECT and return all matching rows."""

    @abstractmethod
    def fetchone(self, sql: str, params: tuple = ()) -> tuple | None:
        """Execute a SELECT and return the first matching row, or ``None``."""

    # ── Write ────────────────────────────────────────────────────────────────

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> int:
        """Execute a DML statement (INSERT/UPDATE/DELETE).

        Returns the number of rows affected.
        """

    @abstractmethod
    def executemany(self, sql: str, params_list: list[tuple]) -> int:
        """Execute a DML statement once per item in *params_list*.

        Returns the total number of rows affected.
        """

    @abstractmethod
    def commit(self) -> None:
        """Commit the current transaction."""

    @abstractmethod
    def rollback(self) -> None:
        """Roll back the current transaction."""

    # ── Maintenance ──────────────────────────────────────────────────────────

    def vacuum(self) -> None:
        """Reclaim unused disk space.  Default: no-op (e.g. MySQL handles
        this automatically; override in connectors that support it)."""

    def checkpoint(self) -> None:
        """Flush the write-ahead log (SQLite WAL only).
        Default: no-op for backends that don't use WAL."""

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @abstractmethod
    def close(self) -> None:
        """Close the current thread's connection."""

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _adapt_sql(self, sql: str) -> str:
        """Translate canonical ``?`` placeholders to the backend's style.

        Override in subclasses that use a different placeholder token.
        """
        return sql  # default: keep as-is (SQLite uses ?)
