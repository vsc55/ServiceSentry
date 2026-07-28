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


# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA: dict = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)

# Default values per schema section
_SERVER_DEFAULTS: dict = {k: v['default'] for k, v in _SCHEMA['servers'].items()
                          if isinstance(v, dict) and 'default' in v}
# checks schema is nested inside servers as a sub_collection
_CHECK_DEFAULTS: dict  = {k: v['default'] for k, v in _SCHEMA['servers']['checks'].items()
                          if isinstance(v, dict) and 'default' in v}
