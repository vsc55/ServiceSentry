#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom roles mixin for WebAdmin."""

import json
import os
import tempfile


class _RolesMixin:
    """Persistence and lookup for custom roles (``roles.json``)."""

    @property
    def _roles_path(self) -> str:
        return os.path.join(self._config_dir, self._ROLES_FILE)

    def _load_roles(self) -> None:
        """Load custom roles from ``roles.json``."""
        path = self._roles_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    data = json.load(fh)
                self._builtin_role_labels = data.pop('__builtin_labels__', {})
                self._custom_roles = data
            except (json.JSONDecodeError, OSError):
                self._custom_roles = {}
                self._builtin_role_labels = {}
        else:
            self._custom_roles = {}
            self._builtin_role_labels = {}

    def _persist_roles(self) -> bool:
        """Write custom roles to ``roles.json`` atomically."""
        tmp_path = None
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            data = dict(self._custom_roles)
            if self._builtin_role_labels:
                data['__builtin_labels__'] = self._builtin_role_labels
            with tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', dir=self._config_dir,
                suffix='.tmp', delete=False,
            ) as tmp:
                json.dump(data, tmp, indent=4, ensure_ascii=False)
                tmp_path = tmp.name
            os.replace(tmp_path, self._roles_path)
            return True
        except OSError:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return False
