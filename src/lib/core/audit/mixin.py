#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit log mixin for WebAdmin.

Audit entries are stored in the ``audit`` table in ``data.db`` (shared with
the history store).
"""

import os
from datetime import datetime, timezone

from flask import has_request_context, request, session


class _AuditMixin:
    """Audit log persistence and helpers."""

    # Core secret field names redacted from audit detail.  Module-declared
    # secret fields are added dynamically at init via _module_secret_fields
    # (see _sensitive_fields()), keeping the core free of module specifics.
    _SENSITIVE_FIELDS = frozenset({
        'password', 'password_hash', 'token', 'secret', 'key_file',
        'bind_password', 'client_secret', 'graph_secret', 'sp_key', 'idp_cert',
        'smtp_password', 'ms365_client_secret',
        'gmail_client_secret', 'gmail_refresh_token',
    })

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_audit_store(self) -> None:
        """Create the AuditStore on the shared connector."""
        from .store import AuditStore  # noqa: PLC0415
        from lib.db import get_connector        # noqa: PLC0415
        connector = getattr(self, '_db_connector', None)
        if connector is None:
            db_path = os.path.join(self._var_dir or self._config_dir, 'data.db')
            connector = get_connector(None, default_sqlite_path=db_path)
            self._db_connector = connector
        self._audit_store = AuditStore(connector)

    # ── Legacy in-memory list (kept for test and backward compat) ─────────────
    # Code that reads/writes ``wa._audit_log`` still works via the property.

    @property
    def _audit_log(self) -> list:
        """Return audit entries as a list (oldest first) — for backward compat."""
        if not hasattr(self, '_audit_store'):
            return []
        return self._audit_store.get_all(newest_first=False)

    @_audit_log.setter
    def _audit_log(self, value: list) -> None:
        """Setting _audit_log replaces the entire DB table (used in tests)."""
        if not hasattr(self, '_audit_store'):
            return
        self._audit_store.delete_all()
        if value:
            self._audit_store.migrate_from_list(value)

    # ── Persistence (no longer file-based) ────────────────────────────────────

    def _load_audit(self) -> None:
        """No-op: audit is loaded lazily from DB via _audit_log property."""

    def _persist_audit(self) -> bool:
        """No-op: audit is written to DB on each _audit()/_audit_system() call."""
        return True

    # ── Write ─────────────────────────────────────────────────────────────────

    def _audit_write(self, event: str, user: str, ip: str,
                     detail: str | list | dict) -> None:
        """Insert one audit entry, resiliently.

        A write failure (DB locked, disk full, a broken transaction left by some
        other operation…) must NEVER break the caller's request nor — worse —
        silently stop ALL future auditing.  On error we roll the shared
        connection back (so it isn't left in an aborted state that would fail
        every subsequent write) and log the reason to stderr so the operator can
        see exactly why auditing stopped, instead of it failing invisibly.
        """
        store = getattr(self, '_audit_store', None)
        if store is None:
            return
        try:
            store.insert(
                ts=datetime.now(timezone.utc).isoformat(),
                event=event, user=user, ip=ip, detail=detail,
                max_entries=self._AUDIT_MAX_ENTRIES,
            )
            # Event-rule evaluation is decoupled: the background event worker reads
            # new audit rows by cursor and notifies on matching rules, so writing an
            # audit entry never blocks on a (possibly slow) notification channel.
        except Exception as exc:  # pylint: disable=broad-except
            conn = getattr(self, '_db_connector', None)
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:  # pylint: disable=broad-except
                    pass
            import sys, traceback  # noqa: PLC0415
            print(f'> WebAdmin >> audit write failed for {event!r}: '
                  f'{type(exc).__name__}: {exc}', file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    def _audit(self, event: str, username: str = '', ip: str = '',
               detail: str | list | dict = '') -> None:
        """Append an audit entry (requires Flask request context)."""
        self._audit_write(
            event,
            username or session.get('username', ''),
            ip or request.remote_addr,
            detail,
        )

    def _audit_system(self, event: str, detail: str | list | dict = '') -> None:
        """Append a system-generated audit entry (no Flask context needed)."""
        self._audit_write(event, 'system', 'internal', detail)

    def _audit_auto(self, event: str, detail: str | list | dict = '') -> None:
        """Append an audit entry attributed to the request actor when a Flask context
        is active (a user-initiated action), else as a system entry (autostart /
        background thread).  One call site, no duplicate 'admin' + 'system' rows."""
        if has_request_context() and session.get('username'):
            self._audit(event, detail=detail)
        else:
            self._audit_system(event, detail)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _diff_dicts(
        old: dict, new: dict, prefix: str = '', *,
        sensitive: frozenset[str] = frozenset(),
    ) -> list[dict]:
        """Return ``[{field, old, new}]`` for every value that differs."""
        changes: list[dict] = []
        all_keys = sorted(set(list(old.keys()) + list(new.keys())))
        for key in all_keys:
            path = f'{prefix}.{key}' if prefix else key
            ov = old.get(key)
            nv = new.get(key)
            if ov == nv:
                continue
            if isinstance(ov, dict) and isinstance(nv, dict):
                changes.extend(
                    _AuditMixin._diff_dicts(ov, nv, path, sensitive=sensitive)
                )
            else:
                hide = key in sensitive
                # Mask secrets even when a whole dict/list is added or removed
                # (only one side is a dict here, so the recursion above is
                # skipped) — otherwise nested secrets such as
                # profiles.ssh.ssh_password would be logged in plaintext.
                changes.append({
                    'field': path,
                    'old': '***' if hide else _AuditMixin._mask_secrets(ov, sensitive),
                    'new': '***' if hide else _AuditMixin._mask_secrets(nv, sensitive),
                })
        return changes

    @staticmethod
    def _mask_secrets(value, sensitive: frozenset[str]):
        """Recursively replace the values of *sensitive*-named keys with ``'***'``."""
        if isinstance(value, dict):
            return {k: ('***' if k in sensitive else _AuditMixin._mask_secrets(v, sensitive))
                    for k, v in value.items()}
        if isinstance(value, list):
            return [_AuditMixin._mask_secrets(v, sensitive) for v in value]
        return value
