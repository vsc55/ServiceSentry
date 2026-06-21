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
    'normalize_url',
]
