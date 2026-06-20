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
    ensure_config_defaults,
    normalize_url,
)


# The system config file name lives here ONLY — callers pass the config
# directory, never the file name, so the source of truth is centralised.
CONFIG_FILENAME = 'config.json'


def config_path(config_dir: str) -> str:
    """Absolute path to config.json inside *config_dir* (single definition)."""
    return os.path.join(config_dir, CONFIG_FILENAME)


def load_config(config_dir: str, *, seed: bool = True, log=print) -> ConfigControl:
    """Single, centralised entry point to open the system ``config.json``.

    Takes the **config directory** (not a file path) — the file name is defined
    once, here — reads it and, by default, ensures every registry default is
    present (persisting and reporting any newly-added option).  Every place that
    loads config.json (the daemon, the web admin, the monitor) goes through here,
    so both the file location and the read+seed behaviour live in **one** spot."""
    cc = ConfigControl(config_path(config_dir))
    cc.read()
    if seed:
        ensure_config_defaults(cc, log=log)
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
    'ensure_config_defaults',
    'load_config',
    'config_path',
    'CONFIG_FILENAME',
    'normalize_url',
]
