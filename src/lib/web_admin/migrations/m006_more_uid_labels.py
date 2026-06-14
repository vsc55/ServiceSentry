#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 006: more modules keyed by UID + editable label.

Same shape as m003/m004/m005, applied to the remaining host-centric modules the
user asked for.  Re-keys each check to its stable ``uid`` (generating one when
absent) and fills an empty ``label`` from a per-module template resolving
``{host}`` (the bound host's name) and any ``{field}`` of the item.
"""

import re
import uuid

ID = '006_more_uid_labels'

# bare module name -> label template
_TEMPLATES = {
    'cpu':       '{host}',
    'ram_swap':  '{host}',
    'ntp':       '{host}',
    'ping':      '{host}',
    'datastore': '{host} - {db_type}',
    'ssl_cert':  '{host} - {server_name}',
    'web':       '{host} - {url}',
}

_TOKEN = re.compile(r'\{(\w+)\}')

# Modules whose key used to BE the identity (placeholder __key__): for an inline
# check (no host_uid) the value lives only in the key, so preserve it into the
# field before the key becomes a UID.  Host-bound checks fill it from the host.
_KEY_FIELD = {'web': 'url', 'ping': 'host'}


def _host_name(wa, host_uid):
    store = getattr(wa, '_hosts_store', None)
    if not store or not host_uid:
        return ''
    try:
        h = store.get(host_uid)
    except Exception:  # pylint: disable=broad-except
        h = None
    return (h or {}).get('name', '') if isinstance(h, dict) else ''


def _render(template, host, item):
    def repl(m):
        k = m.group(1)
        if k == 'host':
            return host or ''
        v = item.get(k)
        return str(v) if v not in (None, '') else ''
    s = _TOKEN.sub(repl, template)
    s = re.sub(r'^\s*-\s*', '', re.sub(r'\s*-\s*$', '', s))
    return s.strip()


def run(wa):
    modules = wa._read_config_file(wa._MODULES_FILE)
    if not isinstance(modules, dict):
        return
    changed = False
    for bare, tpl in _TEMPLATES.items():
        for mod_key in (bare, f'watchfuls.{bare}'):
            mod_cfg = modules.get(mod_key)
            if not isinstance(mod_cfg, dict):
                continue
            lst = mod_cfg.get('list')
            if not isinstance(lst, dict):
                continue
            new_list = {}
            mod_changed = False
            key_field = _KEY_FIELD.get(bare)
            for old_key, item in lst.items():
                if not isinstance(item, dict):
                    new_list[old_key] = item
                    continue
                # Inline (no host) check whose identity lived in the key: keep it
                # in the field before the key becomes a UID.
                if (key_field and not item.get('host_uid')
                        and not str(item.get(key_field) or '').strip()):
                    item[key_field] = old_key
                    mod_changed = True
                uid = str(item.get('uid') or '').strip() or str(uuid.uuid4())
                if item.get('uid') != uid:
                    item['uid'] = uid
                    mod_changed = True
                if not str(item.get('label') or '').strip():
                    host = _host_name(wa, item.get('host_uid'))
                    item['label'] = _render(tpl, host, item) or old_key
                    mod_changed = True
                if old_key != uid:
                    mod_changed = True
                new_list[uid] = item
            if mod_changed:
                mod_cfg['list'] = new_list
                changed = True
    if changed:
        wa._save_config_file(wa._MODULES_FILE, modules)
