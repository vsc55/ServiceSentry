#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 012: replace ``global.debug`` (bool) with ``global.log_level`` (str).

Debug verbosity is now a level selector ('off' / 'debug' / 'info' / 'warning' /
'error') instead of an on/off boolean.  Convert any existing ``global.debug``
flag in ``config.json``: a truthy value maps to ``'debug'`` (most verbose),
falsy to ``'off'``.  The stale ``debug`` key is removed so the config UI shows
the new dropdown instead of the old checkbox.
"""

ID = '012_global_debug_to_log_level'


def run(wa):
    data = wa._read_config_file(wa._CONFIG_FILE)
    if not isinstance(data, dict):
        return
    g = data.get('global')
    if not isinstance(g, dict) or 'debug' not in g:
        return
    if 'log_level' not in g:
        g['log_level'] = 'debug' if g.get('debug') else 'off'
    del g['debug']
    wa._save_config_file(wa._CONFIG_FILE, data)
