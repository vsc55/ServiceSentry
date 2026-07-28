#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run one module's ``check()`` once, right now, with no monitor behind it.

Two features need exactly this and nothing more: the Servers "test" button (does this host
answer?) and a module page's live refresh (what does this check say *now*, rather than what
it said when the monitor last ran).  Both want the module's REAL ``check()`` — a probe that
went through different code would prove nothing about the check that actually runs at 3am —
so instead of a per-module probe, the module is given a **minimal Monitor stand-in**: the
config, an in-memory status, and whatever registry it needs to resolve a connection.  No
Telegram, no history, no file writes.

This lives in ``lib/modules`` because it is about the module result contract and nothing
else.  It spent its first life in ``lib/core/hosts/probe.py``, where it was written for the
Servers button, and the module pages imported it from there — a generic layer reaching into
one domain.  The bill arrived as a bug: the projection below is the one place that decides
which fields of a result survive an on-demand run, it silently stopped carrying ``severity``,
and nobody looked for that decision in a hosts file.  See
``docs/caso-diagnostico.md`` → "La misma comprobación salía ámbar o roja según quién la
ejecutara".
"""

from __future__ import annotations

import importlib
import os
import sys

from lib.config import ConfigControl
from lib.services.monitoring.monitor import Monitor

# What a result carries out of a one-off run: every field ``DictReturnCheck.set()`` writes,
# minus the ones that are about NOTIFYING rather than about the result.  Named here, and
# checked against ``set()`` by a guard test, because the alternative — a hand-copied list
# that nobody revisits — is what dropped ``severity``.  A field added to the contract must
# be added here or excluded on purpose; it can no longer fall out by omission.
RESULT_FIELDS = ('status', 'severity', 'message', 'name', 'other_data')

# ``send`` is the monitor's notify gate, not part of the answer: a one-off run notifies
# nobody, so carrying it would only invite a caller to act on it.
RESULT_FIELDS_EXCLUDED = ('send',)

# What each field reads as when the module never set it — the same empty value the contract
# uses, so a caller cannot tell a one-off run from a stored result by the shape it gets.
_FIELD_ABSENT = {'status': False, 'severity': '', 'message': '', 'name': '',
                 'other_data': None}


class ProbeMonitor(Monitor):
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

    Returns one dict per result: ``key`` plus every field in :data:`RESULT_FIELDS`, taken
    from the module's ``dict_return``.  *modules_config* must be keyed by the fully-qualified
    module name (``watchfuls.<module_name>``).  *modules_dir* (the watchfuls directory) lets
    the module resolve its own check-message i18n; *notify_cfg* (the global config) sets the
    notification language for those messages.
    """
    if modules_dir:
        parent = os.path.dirname(modules_dir)
        if parent and parent not in sys.path:
            sys.path.insert(0, parent)
    mod = importlib.import_module(f'watchfuls.{module_name}')
    cls = getattr(mod, 'Watchful', None)
    if cls is None:
        raise ImportError(f'watchfuls.{module_name} has no Watchful')
    watchful = cls(ProbeMonitor(modules_config, hosts_store, db,
                                modules_dir=modules_dir, notify_cfg=notify_cfg))
    watchful.check()
    out = []
    for key, val in (watchful.dict_return.list or {}).items():
        if not isinstance(val, dict):
            continue
        # ``status`` is coerced because callers branch on it; the rest travel as emitted.
        # A field the module never set stays absent rather than becoming a value: an empty
        # ``severity`` is exactly what "this is a plain error" looks like downstream, so the
        # absence has to survive as an absence.
        row = {'key': key}
        for field in RESULT_FIELDS:
            row[field] = (bool(val.get('status')) if field == 'status'
                          else val.get(field, _FIELD_ABSENT[field]))
        out.append(row)
    return out
