#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 005: DNS checks keyed by UID + editable label.

Mirrors m003/m004 for the DNS module: re-keys each check to its stable ``uid``
(generating one when absent) and fills an empty ``label`` with
``"<record_type> <host>"`` (e.g. "MX cerebelum.lan"), so the name shown in
Modules, the status page and notifications is descriptive while the key stays an
opaque UID (no more "cerebelum.lan_3" collision suffixes).
"""

import uuid

ID = '005_dns_uid_label'

_TARGETS = ('dns', 'watchfuls.dns')


def run(wa):
    modules = wa._read_config_file(wa._MODULES_FILE)
    if not isinstance(modules, dict):
        return
    changed = False
    for mod_key in _TARGETS:
        mod_cfg = modules.get(mod_key)
        if not isinstance(mod_cfg, dict):
            continue
        lst = mod_cfg.get('list')
        if not isinstance(lst, dict):
            continue
        new_list = {}
        mod_changed = False
        for old_key, item in lst.items():
            if not isinstance(item, dict):
                new_list[old_key] = item
                continue
            uid = str(item.get('uid') or '').strip() or str(uuid.uuid4())
            if item.get('uid') != uid:
                item['uid'] = uid
                mod_changed = True
            if not str(item.get('label') or '').strip():
                host = str(item.get('host') or '').strip() or old_key
                rtype = str(item.get('record_type') or 'A').strip().upper() or 'A'
                item['label'] = f'{rtype} {host}'
                mod_changed = True
            if old_key != uid:
                mod_changed = True
            new_list[uid] = item
        if mod_changed:
            mod_cfg['list'] = new_list
            changed = True
    if changed:
        wa._save_config_file(wa._MODULES_FILE, modules)
