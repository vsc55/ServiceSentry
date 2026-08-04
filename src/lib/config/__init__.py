#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""" Configuracion de ServiSesentry. """

import os
import re

from lib.config.config_control import ConfigControl
from lib.config.config_store import ConfigStore
from lib.config.config_type_return import ConfigTypeReturn
from lib.config.spec import (
    Cfg,
    CONFIG_FIELDS,
    CFG_BY_PATH,
    cfg_default,
    cfg_get,
    cfg_validate,
    normalize_url,
)


# The system config file name lives here ONLY — callers pass the config
# directory, never the file name, so the source of truth is centralised.
CONFIG_FILENAME = 'config.json'

# The key file, same rule. It signs Flask's session cookies AND derives the Fernet key that
# every stored secret is encrypted with — losing it is not "sign in again", it is every secret
# in the database becoming unreadable. Written 0o600 from the first open (lib.core.sessions).
# It was spelled out twice: here and as a literal in the CLI context, which is one spelling
# away from a CLI that silently derives a different key and decrypts nothing.
SECRET_KEY_FILENAME = '.flask_secret'

# The same key, supplied by the environment instead of a file. It is the one setting that
# MUST be identical across every process sharing a database — the Fernet key each of them
# derives from it is what decrypts the stored secrets — and the only one that had no `SS_*`
# to pin it with. On a single host the compose files get away with sharing a volume; a pod
# per role does not, so each generated its own key and could not read the others' secrets.
SECRET_KEY_ENV = 'SS_SECRET_KEY'

# 32 bytes as hex, the shape the file has always held. Enforced rather than accepted loosely
# because the failure it prevents is silent: a key that "works" but differs from the one the
# data was encrypted with reads as data loss, months later, with no error at the time.
_SECRET_KEY_RE = re.compile(r'^[0-9a-fA-F]{64}$')


def secret_key_path(config_dir: str) -> str:
    """Absolute path to the key file inside *config_dir* (single definition)."""
    return os.path.join(config_dir, SECRET_KEY_FILENAME)


def secret_key_from_env() -> str:
    """The key pinned through ``SS_SECRET_KEY``, or ``''`` when it is not set.

    Raises ``ValueError`` when it IS set but malformed. Refusing to start is deliberate:
    the alternative is falling back to a generated key, encrypting everything with it, and
    leaving the operator believing their pinned key is in use — the discovery comes when
    another replica cannot read a secret, or a restart makes the data unreadable.
    """
    raw = (os.environ.get(SECRET_KEY_ENV) or '').strip()
    if not raw:
        return ''
    if not _SECRET_KEY_RE.match(raw):
        raise ValueError(
            f'{SECRET_KEY_ENV} must be 64 hex characters (32 bytes) — got {len(raw)} '
            f'character(s). Generate one with: python -c '
            f'"import secrets; print(secrets.token_hex(32))"')
    return raw


def config_path(config_dir: str) -> str:
    """Absolute path to config.json inside *config_dir* (single definition)."""
    return os.path.join(config_dir, CONFIG_FILENAME)


def load_config(config_dir: str) -> ConfigControl:
    """Open the system ``config.json`` (the bootstrap/read-only file layer).

    Takes the **config directory** (not a file path) — the file name is defined
    once, here.  This only *reads* the file; it never writes to it.

    Editable configuration is **not** stored here: it lives in the DB (single
    source), read and written through :class:`lib.config.manager.ConfigManager`.
    Missing values fall back to the registry default (``spec.py``) at read time,
    so nothing is ever materialised into ``config.json`` on startup.
    """
    cc = ConfigControl(config_path(config_dir))
    cc.read()
    return cc


__all__ = [
    'ConfigStore',
    'ConfigControl',
    'ConfigTypeReturn',
    'Cfg',
    'CONFIG_FIELDS',
    'CFG_BY_PATH',
    'cfg_default',
    'cfg_get',
    'cfg_validate',
    'load_config',
    'config_path',
    'CONFIG_FILENAME',
    'SECRET_KEY_FILENAME',
    'secret_key_path',
    'normalize_url',
]
