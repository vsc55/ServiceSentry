#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 010: re-key every check item by its UID across all modules.

Earlier migrations (003-009) re-keyed a few modules' ``list`` items to their
``uid``; this finishes the job generically for every module and the nested
snmp ``servers``/``checks`` so each watchful's result key (the dict key it
iterates) is the stable UID — the canonical relation used everywhere
(status.json, check_state, history).

Because result keys change, the persistent runtime state that keyed off the
old keys is reset so monitoring starts clean: the ``history`` table (agreed:
start from zero, its series identity changes) and the ``check_state`` table
(the change-detection baseline regenerates on the next cycle).  ``status.json``
is left untouched — it is a regenerated cache; stale entries are ignored and a
``--clear_status`` run wipes them if desired.
"""

ID = '010_rekey_items_by_uid'


def run(wa):
    # 1) Re-key items by uid in modules.json.
    modules = wa._read_config_file(wa._MODULES_FILE)
    if isinstance(modules, dict):
        from lib.web_admin.routes.modules import _rekey_items_by_uid  # noqa: PLC0415
        _rekey_items_by_uid(modules)
        wa._save_config_file(wa._MODULES_FILE, modules)

    # 2) Reset persistent state that keyed off the old result keys.
    try:
        if getattr(wa, '_history', None):
            wa._history.delete_all()
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from lib.stores.check_state import CheckStateStore  # noqa: PLC0415
        conn = getattr(wa, '_db_connector', None)
        if conn is not None:
            CheckStateStore(conn).clear()
    except Exception:  # pylint: disable=broad-except
        pass
