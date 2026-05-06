#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User accounts mixin for WebAdmin."""

import json
import os
import tempfile

from werkzeug.security import generate_password_hash


class _UsersMixin:
    """Persistence and lookup for user accounts (``users.json``)."""

    @property
    def _users_path(self) -> str:
        return os.path.join(self._config_dir, self._USERS_FILE)

    def _load_or_create_users(self, default_user: str, default_pass: str):
        """Load ``users.json`` or create it with one admin account.

        Only creates default credentials on first run (file absent).
        A corrupt file is left untouched to avoid silently resetting credentials.
        """
        path = self._users_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and data:
                    self._users = data
            except (json.JSONDecodeError, OSError):
                pass  # File corrupt — do NOT overwrite, keep existing in-memory state
            return  # File existed (valid or corrupt) — never reset credentials
        # First run: file does not exist yet
        if not self._users:
            self._users = {
                default_user: {
                    'password_hash': generate_password_hash(default_pass),
                    'role': 'admin',
                    'display_name': 'Administrator',
                },
            }
            self._persist_users()

    def _persist_users(self) -> bool:
        """Write current user dict to ``users.json`` atomically."""
        tmp_path = None
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', dir=self._config_dir,
                suffix='.tmp', delete=False,
            ) as tmp:
                json.dump(self._users, tmp, indent=4, ensure_ascii=False)
                tmp_path = tmp.name
            os.replace(tmp_path, self._users_path)
            return True
        except OSError:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return False
