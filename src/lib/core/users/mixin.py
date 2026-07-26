#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User accounts mixin for WebAdmin."""

import uuid

from werkzeug.security import generate_password_hash

from lib.core.constants import BUILTIN_ROLE_UIDS
from lib.core.entity_sync import diff_entities, snapshot


class _UsersMixin:
    """Persistence and lookup for user accounts (DB table ``users``)."""

    #: The rows as last read from — or written to — the database (see _persist_users).
    _users_snapshot: dict = None

    def _load_or_create_users(self, default_user: str, default_pass: str):
        """Load users from the DB or create the default admin on first run."""
        data = self._users_store.load()
        if data:
            self._users = data
            self._users_snapshot = snapshot(data)
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

    def _load_users(self) -> None:
        """Re-read the users table into memory.

        Separate from :meth:`_load_or_create_users`, which is the first-run path: that one
        may CREATE the default administrator, and a reload must never do that — a
        momentarily unreadable table would mint a second admin account.

        An empty answer is refused rather than applied. "No users" is not a state this
        product can be in: it means the table is mid-migration or the process was pointed
        at the wrong database, and applying it would lock everyone out of a running
        instance.
        """
        data = self._users_store.load()
        if data:
            self._users = data

    def _reload_users_if_stale(self) -> bool:
        """Re-read the users table when another writer has touched it (see
        :class:`lib.web_admin.mixins.freshness._FreshnessMixin`).  The CLI writes this one
        — ``ssentry user role bob viewer`` was invisible to a running web process until it
        was restarted."""
        return self._reload_if_stale('users', getattr(self, '_users_store', None),
                                     self._load_users)

    def _persist_users(self) -> bool:
        """Write the users this process changed — not the whole table.

        Replacing every row would delete an account the CLI created while the panel held
        an older copy, silently. :mod:`lib.core.entity_sync` has the rule.
        """
        writes, deletes = diff_entities(self._users_snapshot, self._users)
        if not writes and not deletes:
            return True
        ok = self._users_store.apply(writes, deletes)
        if ok:
            self._users_snapshot = snapshot(self._users)
            self._mark_fresh('users', self._users_store)
        return ok
