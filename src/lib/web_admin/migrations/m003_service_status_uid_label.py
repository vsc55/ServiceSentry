#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 003: service_status checks keyed by UID + editable label.

Re-keys each service_status check to its stable ``uid`` (generating one when
absent) and fills an empty ``label`` with ``"<host name> - <service>"``, so the
name shown in Modules and in notifications is friendly and editable while the
item key stays opaque and stable (status tracking keys off it).
"""

import uuid

ID = '003_service_status_uid_label'

_TARGETS = ('service_status', 'watchfuls.service_status')


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
                svc = str(item.get('service') or '').strip() or old_key
                host = _host_name(wa, item.get('host_uid'))
                item['label'] = f'{host} - {svc}' if host else svc
                mod_changed = True
            if old_key != uid:
                mod_changed = True
            new_list[uid] = item
        if mod_changed:
            mod_cfg['list'] = new_list
            changed = True
    if changed:
        wa._save_config_file(wa._MODULES_FILE, modules)
