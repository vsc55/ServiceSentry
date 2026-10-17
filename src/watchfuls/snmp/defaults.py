#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: the parsed schema and the defaults derived from it.
#
"""What ``schema.json`` says, read once.

Its own file because more than one half of the module needs it: the check loop resolves an
item's settings against these, and so does discovery when it reports what a server would be
checked with. Keeping them in ``__init__`` would have made the mixins import the package that
imports them.
"""

import json
import os

from lib.core.snmp.defaults import CONN_DEFAULTS


# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA: dict = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)

# Default values per schema section.
#
# The connection half comes from the CORE, because the schema no longer spells those fields
# out: the collection names the protocol (``__profile_fields__``) and the panel expands it.
# Read straight from disk here, without that expansion — so port 161 and "public" would
# simply have gone missing, and a server with no explicit port would have been asked on
# whatever ``int('')`` turned into. The module's own answers (its ``enabled``, how long it
# waits, how many times it retries) still come from the schema and still win.
_SERVER_DEFAULTS: dict = {
    **CONN_DEFAULTS,
    **{k: v['default'] for k, v in _SCHEMA['servers'].items()
       if isinstance(v, dict) and 'default' in v},
}
# The module's own settings (`__module__`).
_MODULE_DEFAULTS: dict = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                          if isinstance(v, dict) and 'default' in v}
# checks schema is nested inside servers as a sub_collection
_CHECK_DEFAULTS: dict  = {k: v['default'] for k, v in _SCHEMA['servers']['checks'].items()
                          if isinstance(v, dict) and 'default' in v}


def _cfg_int(value, default: int) -> int:
    """An int setting read from a saved item: blank/None/garbage → *default*, an explicit 0
    stays 0. ``int(cfg.get('alert', 3))`` turned a cleared field (``None``/``''``) into a
    TypeError that failed the check on every cycle, and ``int(v or default)`` the other way
    round made ``retries: 0`` impossible to ask for."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)
