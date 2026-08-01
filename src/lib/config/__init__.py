#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""" Configuracion de ServiSesentry. """

import os

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


def secret_key_path(config_dir: str) -> str:
    """Absolute path to the key file inside *config_dir* (single definition)."""
    return os.path.join(config_dir, SECRET_KEY_FILENAME)


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
