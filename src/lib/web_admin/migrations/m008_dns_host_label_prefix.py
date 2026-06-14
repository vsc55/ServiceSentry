#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 008: prefix the host name to host-bound DNS check labels.

DNS became host-aware after m005, but checks already bound to a host kept a
label like "MX cerebelum.lan" with no indication of WHICH host runs the query.
Prefix the bound host's name ("NS1 - MX cerebelum.lan") so the notification says
which server reported it.  Inline checks (no host) and already-prefixed labels
are left untouched.
"""

ID = '008_dns_host_label_prefix'

_TARGETS = ('dns', 'watchfuls.dns')


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
        for item in lst.values():
            if not isinstance(item, dict):
                continue
            name = _host_name(wa, item.get('host_uid'))
            if not name:
                continue   # inline check (no host) or host gone — nothing to prefix
            label = str(item.get('label') or '').strip()
            if not label or label.lower().startswith(name.lower()):
                continue   # empty or already prefixed
            item['label'] = f'{name} - {label}'
            changed = True
    if changed:
        wa._save_config_file(wa._MODULES_FILE, modules)
