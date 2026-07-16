#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless store context for the CLI management commands.

Builds just what user/group/service admin needs — the shared DB connector + the
users/groups/roles stores + the service-command queue — mirroring
:class:`lib.services.monitoring.service.MonitorService.__init__` but WITHOUT starting any
Flask app, heartbeat thread, or listener.  Loads the users/groups/roles into memory so the
:mod:`lib.core.users.service` / :mod:`lib.core.groups.service` operations can mutate them;
persistence is an explicit ``persist_*`` call.
"""

from __future__ import annotations

import os

from lib.config import config_path
from lib.config.manager import ConfigManager, bootstrap_database_cfg, read_config_raw
from lib.core.config.store import ConfigStore
from lib.core.groups.store import GroupsStore
from lib.core.roles.store import RolesStore
from lib.core.users.service import PasswordPolicy
from lib.core.users.store import UsersStore
from lib.db import get_connector
from lib.i18n import DEFAULT_LANG
from lib.security import secret_manager
from lib.services.manager.commands import ServiceCommandsStore
from lib.services.manager.instances import ServiceInstancesStore


class CliContext:
    """Loaded users/groups/roles + config over the shared DB, for one-shot commands."""

    def __init__(self, config_dir: str, var_dir: str | None = None):
        self.config_dir = config_dir
        self.var_dir = var_dir or config_dir
        fernet = secret_manager.fernet_from_secret_file(os.path.join(config_dir, '.flask_secret'))
        db_cfg = bootstrap_database_cfg(read_config_raw(config_path(config_dir), fernet))
        db_path = os.path.join(self.var_dir, 'data.db')
        self.db = get_connector(db_cfg or None, default_sqlite_path=db_path)

        self._config_store = ConfigStore(self.db)
        self._config_mgr = ConfigManager(
            self._config_store, config_path(config_dir),
            fernet=fernet, secret_keys=secret_manager.ENCRYPT_KEYS)
        self.cfg = self._config_mgr.read() or {}
        self.lang = (self.cfg.get('web_admin') or {}).get('lang') or DEFAULT_LANG

        self.users_store = UsersStore(self.db)
        self.groups_store = GroupsStore(self.db)
        self.roles_store = RolesStore(self.db)
        self.commands_store = ServiceCommandsStore(self.db)
        self.instances_store = ServiceInstancesStore(self.db)

        # In-memory working copies (the service ops mutate these; persist_* writes back).
        self.users = self.users_store.load()
        self.groups = self.groups_store.load()
        self.roles = self.roles_store.load_roles()   # {uid: {name, ...}} — customs + overrides

    def password_policy(self) -> PasswordPolicy:
        """Build the :class:`PasswordPolicy` from the ``web_admin`` config section.

        Reads the ``pw_*`` settings (length bounds + upper/digit/symbol requirements),
        applying the same defaults the web UI uses.
        """
        wa = self.cfg.get('web_admin') or {}
        return PasswordPolicy(
            min_len=int(wa.get('pw_min_len') or 8),
            max_len=int(wa.get('pw_max_len') or 128),
            require_upper=bool(wa.get('pw_require_upper', False)),
            require_digit=bool(wa.get('pw_require_digit', False)),
            require_symbol=bool(wa.get('pw_require_symbol', False)),
        )

    def group_uid(self, group: str) -> str | None:
        """Resolve a group given by uid or (case-insensitive) name → uid, or None."""
        if group in self.groups:
            return group
        low = group.lower()
        for uid, gd in self.groups.items():
            if (gd.get('name') or '').lower() == low:
                return uid
        return None

    def persist_users(self) -> None:
        """Write the in-memory users working copy back to the DB store."""
        self.users_store.save_all(self.users)

    def persist_groups(self) -> None:
        """Write the in-memory groups working copy back to the DB store."""
        self.groups_store.save_all(self.groups)
