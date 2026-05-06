#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Groups mixin for WebAdmin."""

import json
import os
import tempfile


class _GroupsMixin:
    """Persistence and lookup for user groups (``groups.json``)."""

    @property
    def _groups_path(self) -> str:
        return os.path.join(self._config_dir, self._GROUPS_FILE)

    def _load_groups(self) -> None:
        """Load groups from ``groups.json``. Creates a default group on first run."""
        path = self._groups_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    self._groups = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._groups = {}
        else:
            self._groups = {
                'administrators': {
                    'label': 'Administrators',
                    'description': 'Default administrators group',
                    'roles': ['admin'],
                },
            }
            self._persist_groups()

    def _persist_groups(self) -> bool:
        """Write groups to ``groups.json`` atomically."""
        tmp_path = None
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', dir=self._config_dir,
                suffix='.tmp', delete=False,
            ) as tmp:
                json.dump(self._groups, tmp, indent=4, ensure_ascii=False)
                tmp_path = tmp.name
            os.replace(tmp_path, self._groups_path)
            return True
        except OSError:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return False
