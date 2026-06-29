#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ConfigControl facade over the module_config tables (drop-in for the file-based
module config): decrypts on read, re-encrypts on save (the store keeps ciphertext)."""

from __future__ import annotations

from lib.security import secret_manager
from lib.config import ConfigControl

from .store import ModulesStore


class DbBackedModules(ConfigControl):
    """A :class:`ConfigControl` whose ``read``/``save`` sync with the
    ``module_config`` / ``module_config_items`` tables — a drop-in for the monitor's
    ``config_modules`` and for the web's module-config access, so every
    ``get_conf`` / ``set_conf`` / ``convert_find_key_to_list`` caller (all
    inherited from ConfigControl) is unchanged.

    Secrets are handled at this boundary, exactly like the file helpers do today:
    decrypted on ``read``, re-encrypted on ``save`` (the store keeps ciphertext).
    """

    def __init__(self, store: ModulesStore, *, fernet=None, secret_keys=None) -> None:
        super().__init__(None, {})
        self._store = store
        self._fernet = fernet
        self._secret_keys = secret_keys or secret_manager.ENCRYPT_KEYS
        self._loaded_version = None

    def read(self, *_a, **_kw) -> dict:
        data = self._store.load_all() if self._store else {}
        if self._fernet:
            data = secret_manager.decrypt_all(data, self._fernet)
        self.data = data
        self._loaded_version = self._store.version() if self._store else None
        return self.data

    def save(self, data=None) -> bool:
        if data is not None:
            self.data = data
        if self._store is None:
            return True
        payload = self.data
        if self._fernet:
            # encrypt_sensitive returns a NEW structure → self.data stays plaintext
            payload = secret_manager.encrypt_sensitive(
                payload, self._fernet, keys=self._secret_keys)
        self._store.save_all(payload)
        self._loaded_version = self._store.version()
        return True

    def reload_if_changed(self) -> dict:
        """Re-read from the DB only when the store version changed (cheap
        freshness for the web's frequent reads within this process).  Cross-process
        readers — e.g. the monitor seeing web edits — should call ``read()`` each
        cycle, since the version counter is per-process."""
        if self._store is not None and self._store.version() != self._loaded_version:
            self.read()
        return self.data
