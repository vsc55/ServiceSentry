#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit log mixin for WebAdmin."""

import json
import os
import tempfile
from datetime import datetime, timezone

from flask import request, session


class _AuditMixin:
    """Audit log persistence and helpers."""

    _SENSITIVE_FIELDS = frozenset({
        'password', 'password_hash', 'token', 'secret', 'key_file',
    })

    @property
    def _audit_path(self) -> str:
        return os.path.join(self._config_dir, self._AUDIT_FILE)

    def _load_audit(self) -> None:
        """Load the audit log from disk."""
        path = self._audit_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    self._audit_log = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._audit_log = []

    def _persist_audit(self) -> bool:
        """Write the audit log to disk atomically (capped to last N entries)."""
        to_write = self._audit_log[-self._AUDIT_MAX_ENTRIES:]
        tmp_path = None
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', dir=self._config_dir,
                suffix='.tmp', delete=False,
            ) as tmp:
                json.dump(to_write, tmp, indent=2, ensure_ascii=False)
                tmp_path = tmp.name
            os.replace(tmp_path, self._audit_path)
            self._audit_log = to_write
            return True
        except OSError:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return False

    def _audit(self, event: str, username: str = '', ip: str = '',
               detail: str | list | dict = '') -> None:
        """Append an entry to the audit log and persist."""
        self._audit_log.append({
            'ts': datetime.now(timezone.utc).isoformat(),
            'event': event,
            'user': username or session.get('username', ''),
            'ip': ip or request.remote_addr,
            'detail': detail,
        })
        self._persist_audit()

    @staticmethod
    def _diff_dicts(
        old: dict, new: dict, prefix: str = '', *,
        sensitive: frozenset[str] = frozenset(),
    ) -> list[dict]:
        """Return ``[{field, old, new}]`` for every value that differs.

        Nested dicts are compared recursively. Values of keys in
        *sensitive* are replaced with ``'***'``.
        """
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
