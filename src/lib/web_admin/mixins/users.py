#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User accounts mixin for WebAdmin."""

import uuid

from werkzeug.security import generate_password_hash

from ..constants import BUILTIN_ROLE_UIDS


class _UsersMixin:
    """Persistence and lookup for user accounts (DB table ``users``)."""

    def _load_or_create_users(self, default_user: str, default_pass: str):
        """Load users from the DB or create the default admin on first run."""
        data = self._users_store.load()
        if data:
            self._users = data
        # Ensure every user has a stable uid
        dirty = False
        for udata in self._users.values():
            if not udata.get('uid'):
                udata['uid'] = str(uuid.uuid4())
                dirty = True
        if dirty:
            self._persist_users()
        # First run: no users in DB yet
        if not self._users:
            self._users = {
                default_user: {
                    'uid': str(uuid.uuid4()),
                    'password_hash': generate_password_hash(default_pass),
                    'role': BUILTIN_ROLE_UIDS['admin'],
                    'display_name': 'Administrator',
                },
            }
            self._persist_users()

    def _persist_users(self) -> bool:
        """Write current user dict to the columnar users table."""
        return self._users_store.save_all(self._users)
