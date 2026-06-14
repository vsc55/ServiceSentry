#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 007: restore the identity field of INLINE checks after UID re-keying.

m006 re-keyed every item to a UID.  For modules whose key used to *be* the
identity (web's url, ping's host — historically ``placeholder: "__key__"``), an
inline check (one not bound to a host) kept that value only in the key.  After
re-keying, the key is an opaque UID and the identity field is empty, so the
check would target the UID.  The value was preserved in ``label`` by m006, so
restore it here.  Host-bound checks are untouched (the field is filled from the
host at runtime).
"""

ID = '007_restore_inline_identity'

# module -> identity field (the field the key used to back via placeholder __key__)
_FIELDS = {'web': 'url', 'ping': 'host'}


def run(wa):
    modules = wa._read_config_file(wa._MODULES_FILE)
    if not isinstance(modules, dict):
        return
    changed = False
    for bare, field in _FIELDS.items():
        for mod_key in (bare, f'watchfuls.{bare}'):
            mod_cfg = modules.get(mod_key)
            if not isinstance(mod_cfg, dict):
                continue
            lst = mod_cfg.get('list')
            if not isinstance(lst, dict):
                continue
            for item in lst.values():
                if not isinstance(item, dict):
                    continue
                if item.get('host_uid'):
                    continue   # host-bound: identity comes from the host at runtime
                if str(item.get(field) or '').strip():
                    continue   # already set
                lbl = str(item.get('label') or '').strip()
                if lbl:
                    item[field] = lbl
                    changed = True
    if changed:
        wa._save_config_file(wa._MODULES_FILE, modules)
