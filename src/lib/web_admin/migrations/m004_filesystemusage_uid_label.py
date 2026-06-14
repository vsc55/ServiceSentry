#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 004: filesystemusage checks keyed by UID + editable label.

Mirrors m003 for the Disk Usage module: re-keys each check to its stable
``uid`` (generating one when absent) and fills an empty ``label`` with
``"<host name> - <partition>"`` so the name shown in Modules, the status page
and notifications identifies the server, while the key stays an opaque UID.
"""

import uuid

ID = '004_filesystemusage_uid_label'

_TARGETS = ('filesystemusage', 'watchfuls.filesystemusage')


def _host_name(wa, host_uid):
    store = getattr(wa, '_hosts_store', None)
    if not store or not host_uid:
        return ''
    try:
        h = store.get(host_uid)
    except Exception:  # pylint: disable=broad-except
        h = None
    return (h or {}).get('name', '') if isinstance(h, dict) else ''


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
                part = str(item.get('partition') or '').strip() or old_key
                host = _host_name(wa, item.get('host_uid'))
                item['label'] = f'{host} - {part}' if host else part
                mod_changed = True
            if old_key != uid:
                mod_changed = True
            new_list[uid] = item
        if mod_changed:
            mod_cfg['list'] = new_list
            changed = True
    if changed:
        wa._save_config_file(wa._MODULES_FILE, modules)
