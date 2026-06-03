#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit log mixin for WebAdmin.

Audit entries are stored in the ``audit`` table in ``data.db`` (shared with
the history store).  The old ``audit.json`` file is migrated automatically on
first startup and then kept as a backup (renamed to ``audit.json.bak``).
"""

import json
import os
from datetime import datetime, timezone

from flask import request, session


class _AuditMixin:
    """Audit log persistence and helpers."""

    _SENSITIVE_FIELDS = frozenset({
        'password', 'password_hash', 'token', 'secret', 'key_file',
        'bind_password', 'client_secret', 'sp_key',
        'smtp_password', 'ms365_client_secret',
        'gmail_client_secret', 'gmail_refresh_token',
    })

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_audit_store(self) -> None:
        """Create the AuditStore and migrate audit.json if it exists."""
        from lib.audit_store import AuditStore  # noqa: PLC0415
        db_path = os.path.join(self._var_dir or self._config_dir, 'data.db')
        self._audit_store = AuditStore(db_path)
        self._migrate_audit_json()

    def _migrate_audit_json(self) -> None:
        """If audit.json exists and the DB table is empty, import its entries."""
        json_path = os.path.join(self._config_dir, self._AUDIT_FILE)
        if not os.path.isfile(json_path):
            return
        try:
            with open(json_path, encoding='utf-8') as fh:
                entries = json.load(fh)
            if not isinstance(entries, list):
                return
            migrated = self._audit_store.migrate_from_list(entries)
            if migrated:
                bak = json_path + '.bak'
                os.replace(json_path, bak)
        except (OSError, ValueError):
            pass

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

    def _audit(self, event: str, username: str = '', ip: str = '',
               detail: str | list | dict = '') -> None:
        """Append an audit entry (requires Flask request context)."""
        if not hasattr(self, '_audit_store'):
            return
        self._audit_store.insert(
            ts=datetime.now(timezone.utc).isoformat(),
            event=event,
            user=username or session.get('username', ''),
            ip=ip or request.remote_addr,
            detail=detail,
            max_entries=self._AUDIT_MAX_ENTRIES,
        )

    def _audit_system(self, event: str, detail: str | list | dict = '') -> None:
        """Append a system-generated audit entry (no Flask context needed)."""
        if not hasattr(self, '_audit_store'):
            return
        self._audit_store.insert(
            ts=datetime.now(timezone.utc).isoformat(),
            event=event,
            user='system',
            ip='internal',
            detail=detail,
            max_entries=self._AUDIT_MAX_ENTRIES,
        )

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
                changes.append({
                    'field': path,
                    'old': '***' if hide else ov,
                    'new': '***' if hide else nv,
                })
        return changes
