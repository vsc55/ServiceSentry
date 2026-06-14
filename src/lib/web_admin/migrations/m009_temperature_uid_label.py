#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 009: temperature checks keyed by UID + editable label.

Mirrors m004 for the Temperature (CPU/sensor) module.  Previously each check
was keyed by the sensor name; now the key is the stable ``uid`` and the sensor
identifier lives in its own ``sensor`` field.  Re-keys every check to its UID
(generating one when absent), copies the old sensor-name key into ``sensor``
when that field is empty, and fills an empty ``label`` with
``"<host name> - <sensor>"`` so the display name identifies the server.
"""

import uuid

ID = '009_temperature_uid_label'

_TARGETS = ('temperature', 'watchfuls.temperature')


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
            # The old key WAS the sensor name — preserve it in the sensor field.
            sensor = str(item.get('sensor') or '').strip() or old_key
            if item.get('sensor') != sensor:
                item['sensor'] = sensor
                mod_changed = True
            if not str(item.get('label') or '').strip():
                host = _host_name(wa, item.get('host_uid'))
                item['label'] = f'{host} - {sensor}' if host else sensor
                mod_changed = True
            if old_key != uid:
                mod_changed = True
            new_list[uid] = item
        if mod_changed:
            mod_cfg['list'] = new_list
            changed = True
    if changed:
        wa._save_config_file(wa._MODULES_FILE, modules)
