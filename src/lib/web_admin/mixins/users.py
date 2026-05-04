#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User accounts mixin for WebAdmin."""

import json
import os

from werkzeug.security import generate_password_hash


class _UsersMixin:
    """Persistence and lookup for user accounts (``users.json``)."""

    @property
    def _users_path(self) -> str:
        return os.path.join(self._config_dir, self._USERS_FILE)

    def _load_or_create_users(self, default_user: str, default_pass: str):
        """Load ``users.json`` or create it with one admin account."""
        path = self._users_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    self._users = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._users = {}
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
        """Write current user dict to ``users.json``."""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._users_path, 'w', encoding='utf-8') as fh:
                json.dump(self._users, fh, indent=4, ensure_ascii=False)
            return True
        except OSError:
            return False
