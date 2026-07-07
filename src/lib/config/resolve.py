#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration resolution: merge the editable DB layer with the read-only
``config.json`` and environment overrides into the effective config.

Every config field is a 2-level ``section|field`` path.  Precedence per field:

    env var  >  config.json  >  DB  >  spec default

A field set by an env var or present in ``config.json`` is **read-only**
(returned in the ``locked`` set so the UI can disable it and the PUT can reject
it).  The ``database`` section is bootstrap-only — read from ``config.json`` /
env, never from the DB (the DB connector is built from it).
"""

from __future__ import annotations

import copy

from lib.config.spec import CONFIG_FIELDS, CFG_BY_PATH, cfg_default

# The editable config DB is the single source for everything with a
# ``section|field`` shape — all real configuration *and* feature data that fits
# (the ``overview`` layout, the ``notif_templates`` / ``notif_html_templates``
# overrides).  Only ``database`` is excluded: it is bootstrap (the DB connector is
# built from it before the config layer exists), so it stays in ``config.json``.
# (Webhooks are not here — they have their own table, ``lib/core/notify/webhook/store.py``.)
FILE_ONLY_SECTIONS = frozenset({'database'})

# First-run-only credentials: created once, kept in the file, never in the DB.
CRED_PATHS = frozenset({'web_admin|username', 'web_admin|password'})

# Sections never sourced from the editable DB layer (read from file/env only).
_DB_EXCLUDED_SECTIONS = FILE_ONLY_SECTIONS


def file_leaves(file_cfg: dict) -> dict:
    """Flatten a nested config dict to ``{'section|field': value}`` (2-level)."""
    out: dict = {}
    if not isinstance(file_cfg, dict):
        return out
    for section, fields in file_cfg.items():
        if isinstance(fields, dict):
            for field, val in fields.items():
                out[f'{section}|{field}'] = val
    return out


def resolve_config(db_values: dict | None, file_cfg: dict | None,
                   env_values: dict | None = None,
                   *, include_defaults: bool = True) -> tuple[dict, set]:
    """Return ``(effective_config, locked_paths)``.

    *db_values* / *env_values* are flat ``{'section|field': value}`` maps;
    *file_cfg* is the nested ``config.json`` dict (already decrypted).  All
    values are treated verbatim (secrets must be decrypted by the caller).
    """
    db_values = db_values or {}
    env_values = env_values or {}
    file_cfg = file_cfg if isinstance(file_cfg, dict) else {}
    leaves = file_leaves(file_cfg)

    # Faithful base: start from the whole file so feature data carried alongside
    # the config (the ``webhooks`` list, the ``overview`` dashboard layout, the
    # bootstrap ``database`` section, first-run credentials) passes through
    # untouched — there is a single read for *all* of config.json.  The editable
    # registry fields are then overlaid from the DB below.  ``config.json`` keeps
    # overriding the DB (read-only); only *registry* file overrides are locked.
    effective: dict = copy.deepcopy(file_cfg)

    paths: set = set(db_values) | set(env_values)
    paths |= {p for p in leaves if p in CFG_BY_PATH}        # only registry overrides lock
    if include_defaults:
        paths |= {f.path for f in CONFIG_FIELDS
                  if f.default is not None and not getattr(f, 'no_seed', False)}

    locked: set = set()
    for path in paths:
        section, sep, field = path.partition('|')
        if not sep:
            continue
        if path in env_values:                              # 1. env var (locked)
            val = env_values[path]
            locked.add(path)
        elif path in leaves:                                # 2. config.json (locked)
            val = leaves[path]
            locked.add(path)
        elif section not in _DB_EXCLUDED_SECTIONS and path in db_values:  # 3. DB (editable)
            val = db_values[path]
        elif include_defaults and path in CFG_BY_PATH:      # 4. spec default
            val = cfg_default(path)
            if val is None:
                continue                                    # no value anywhere → omit
        else:
            continue
        effective.setdefault(section, {})[field] = val
    return effective, locked


