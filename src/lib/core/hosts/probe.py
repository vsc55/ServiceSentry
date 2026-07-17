#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run a single module check once — backing the Servers "test" feature.

Instead of a per-module probe, this reuses each watchful's real ``check()`` by
giving it a **minimal Monitor stand-in**: just the config, an in-memory status,
and the host registry needed to resolve ``host_uid`` → connection.  No Telegram,
no history, no file writes (we call the module's ``check()`` directly, never the
Monitor's).  The module's ``dict_return`` holds the per-result status/message.
"""

from __future__ import annotations

import importlib
import os
import sys

from lib.config import ConfigControl
from lib.services.monitoring.monitor import Monitor


class ProbeHostsStore:
    """Return a (possibly unsaved draft) host for its uid, else delegate.

    Lets the Servers modal test an edited/new host without first persisting it.
    """

    def __init__(self, draft: dict | None, real):
        self._draft = draft or None
        self._real = real

    def get(self, uid, **kw):
        if self._draft and uid == self._draft.get('uid'):
            return self._draft
        return self._real.get(uid, **kw) if self._real is not None else None


class _ProbeMonitor(Monitor):
    """Monitor subclass that skips the heavy __init__ and stubs side effects."""

    def __init__(self, modules_config, hosts_store, db,
                 modules_dir='', notify_cfg=None):  # pylint: disable=super-init-not-called
        self.dir_base = self.dir_config = self.dir_var = ''
        # dir_modules must point at the watchfuls dir so ModuleBase._msg can load
        # each module's lang/<lang>.json — otherwise check messages fall back to
        # their raw i18n key (e.g. "cpu_ok") in the Servers "test" results.
        self.dir_modules = modules_dir or ''
        self.tg = None
        self._db = db
        self._history = None
        self._hosts_store = hosts_store
        self._audit_store = None
        self._status_counts_dirty = False
        # Global config so _notify_lang() resolves the configured notification
        # language (and admin text overrides) instead of falling back to en_EN.
        self.config = ConfigControl(None, notify_cfg or {})
        self.config_modules = ConfigControl(None, modules_config or {})
        self.status = ConfigControl(None, {})

    def send_message(self, message, status=None, module: str = '', item: str = '',
                     severity: str = ''):   # noqa: D401 - no-op in a probe
        # Signature must mirror Monitor.send_message (message, status, module, item, severity):
        # ModuleBase.send_message forwards module=/item=/severity=, so a probe of any module
        # that emits an alert (e.g. process via check_status) would otherwise TypeError.
        return None

    def send_message_end(self):
        return None

    def _audit_system(self, event, detail=''):
        return None


def run_module_check(module_name: str, modules_config: dict, *,
                     hosts_store=None, db=None, modules_dir=None,
                     notify_cfg=None) -> list:
    """Run ``watchfuls.<module_name>.check()`` once and return its results.

    Returns ``[{'key', 'status', 'message', 'other_data'}]`` from the module's
    ``dict_return``.  *modules_config* must be keyed by the fully-qualified
    module name (``watchfuls.<module_name>``).  *modules_dir* (the watchfuls
    directory) lets the module resolve its own check-message i18n; *notify_cfg*
    (the global config) sets the notification language for those messages.
    """
    if modules_dir:
        parent = os.path.dirname(modules_dir)
        if parent and parent not in sys.path:
            sys.path.insert(0, parent)
    mod = importlib.import_module(f'watchfuls.{module_name}')
    cls = getattr(mod, 'Watchful', None)
    if cls is None:
        raise ImportError(f'watchfuls.{module_name} has no Watchful')
    watchful = cls(_ProbeMonitor(modules_config, hosts_store, db,
                                 modules_dir=modules_dir, notify_cfg=notify_cfg))
    watchful.check()
    out = []
    for key, val in (watchful.dict_return.list or {}).items():
        if not isinstance(val, dict):
            continue
        out.append({
            'key': key,
            'status': bool(val.get('status')),
            'message': val.get('message', ''),
            'other_data': val.get('other_data'),
        })
    return out
