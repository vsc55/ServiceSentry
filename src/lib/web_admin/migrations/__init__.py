#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration runner for web_admin data schema upgrades."""

import importlib
import json
import os

# Ordered list of migration module names. Add new entries at the end.
_MIGRATIONS = [
    'm001_uid_relationships',
    'm002_add_auth_source',
]

_STATE_FILE = '_migrations.json'


def _state_path(wa):
    return os.path.join(wa._config_dir, _STATE_FILE)


def _load_state(path):
    try:
        with open(path, encoding='utf-8') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_state(path, applied):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sorted(applied), f, indent=2)


def run_all(wa):
    """Run all pending migrations against the given WebAdmin instance."""
    path = _state_path(wa)
    applied = _load_state(path)
    dirty = False
    for mod_name in _MIGRATIONS:
        mod = importlib.import_module(f'.{mod_name}', package=__package__)
        if mod.ID not in applied:
            mod.run(wa)
            applied.add(mod.ID)
            dirty = True
    if dirty:
        _save_state(path, applied)
