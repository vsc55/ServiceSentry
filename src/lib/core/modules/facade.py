#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ConfigControl facade over the module_config tables (drop-in for the file-based
module config): decrypts on read, re-encrypts on save (the store keeps ciphertext)."""

from __future__ import annotations

import copy
import threading

from lib.security import secret_manager
from lib.config import ConfigControl

from .store import ModulesStore, StaleModulesConfig

__all__ = ('DbBackedModules', 'StaleModulesConfig', 'snapshot', 'save_versioned',
           'mutate_modules')


class DbBackedModules(ConfigControl):
    """A :class:`ConfigControl` whose ``read``/``save`` sync with the
    ``module_config`` / ``module_config_items`` tables — a drop-in for the monitor's
    ``config_modules`` and for the web's module-config access, so every
    ``get_conf`` / ``set_conf`` / ``convert_find_key_to_list`` caller (all
    inherited from ConfigControl) is unchanged.

    Secrets are handled at this boundary, exactly like the file helpers do today:
    decrypted on ``read``, re-encrypted on ``save`` (the store keeps ciphertext).

    ``lock`` serialises this process's read-modify-write cycles (see :func:`mutate_modules`);
    the store's version check covers the writers in OTHER processes.
    """

    def __init__(self, store: ModulesStore, *, fernet=None, secret_keys=None) -> None:
        super().__init__(None, {})
        self._store = store
        self._fernet = fernet
        self._secret_keys = secret_keys or secret_manager.ENCRYPT_KEYS
        self._loaded_version = None
        self.lock = threading.RLock()

    @property
    def loaded_version(self):
        """The store version the cached ``data`` was read at (or written as)."""
        return self._loaded_version

    def read(self, *_a, **_kw) -> dict:
        with self.lock:
            # The version BEFORE the rows: read after, a write landing in between would be
            # recorded as seen while its rows are not — stale, and convinced it is current.
            version = self._store.version() if self._store else None
            data = self._store.load_all() if self._store else {}
            if self._fernet:
                data = secret_manager.decrypt_all(data, self._fernet)
            self.data = data
            self._loaded_version = version
            return self.data

    def save(self, data=None, *, expected_version=None) -> bool:
        """Persist *data*. With *expected_version*, raise :class:`StaleModulesConfig` (and
        write nothing) when the stored configuration has moved past it."""
        with self.lock:
            if self._store is None:
                if data is not None:
                    self.data = data
                return True
            payload = data if data is not None else self.data
            if self._fernet:
                # encrypt_sensitive returns a NEW structure → the plaintext stays as given
                payload = secret_manager.encrypt_sensitive(
                    payload, self._fernet, keys=self._secret_keys)
            new_version = self._store.save_all(payload, expected_version=expected_version)
            if data is not None:
                self.data = data
            self._loaded_version = new_version
            return True

    def reload_if_changed(self) -> dict:
        """Re-read from the DB only when the configuration's version moved.

        The version is the database's (``entity_versions``), so a write made by another
        process — a second web replica, the CLI — is seen here too, not only this
        process's own."""
        with self.lock:
            if self._store is not None and self._store.version() != self._loaded_version:
                self.read()
            return self.data


# ── read-modify-write helpers (Flask-free; *wa* is the web admin) ─────────────────────
def _facade(wa):
    f = getattr(wa, '_modules_facade', None)
    return f if isinstance(f, DbBackedModules) else None


def snapshot(wa) -> tuple:
    """``(modules, version)``: a private copy of the configuration and the version it is at.

    ``version`` is ``None`` when *wa* has no DB-backed facade (a test double), in which case
    nothing can be checked and nothing is."""
    f = _facade(wa)
    if f is None:
        return wa._load_modules(), None          # pylint: disable=protected-access
    with f.lock:
        return wa._load_modules(), f.loaded_version   # pylint: disable=protected-access


def save_versioned(wa, data: dict, version) -> bool:
    """Save *data* only if the configuration is still at *version* (else
    :class:`StaleModulesConfig`). Without a facade, the plain ``wa._save_modules``."""
    f = _facade(wa)
    if f is None or version is None:
        return wa._save_modules(data)           # pylint: disable=protected-access
    return f.save(copy.deepcopy(data), expected_version=version)


def mutate_modules(wa, fn, *, attempts: int = 3):
    """Load → ``fn(modules)`` → save, without losing a concurrent write.

    *fn* edits the dict in place and returns a result; a falsy result means "nothing
    changed" and nothing is saved. In this process the facade lock keeps two cycles from
    interleaving; a write from another process makes the save stale, and the cycle is run
    again on the fresh configuration. Returns *fn*'s result (raises
    :class:`StaleModulesConfig` if every attempt lost the race)."""
    f = _facade(wa)
    lock = f.lock if f is not None else threading.RLock()
    for attempt in range(max(1, attempts)):
        with lock:
            modules, version = snapshot(wa)
            result = fn(modules)
            if not result:
                return result
            try:
                save_versioned(wa, modules, version)
                return result
            except StaleModulesConfig:
                if attempt + 1 >= max(1, attempts):
                    raise
    return None
