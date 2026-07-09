#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone event-processing service — run the decoupled event worker as its own
process/container.

The web admin hosts the worker in-process by default, see
:class:`lib.services.events.manager._EventsMixin`, but the same evaluation loop can run
on its own host/container, sharing the database with the rest of ServiceSentry.
Set ``SS_EVENTS_EMBEDDED=0`` on the web admin so a single dedicated ``--events``
worker owns rule evaluation (``events|enabled`` is the on/off switch, uniform with
the monitor/syslog).

It wires the collaborators the worker needs and nothing else (no Flask, no
listener): read new syslog/audit rows by cursor → evaluate rules → dispatch →
record. Rule evaluation reuses the Event-rules manager (the same rules edited in
the web UI, stored in the shared DB), so embedded and standalone behave alike.
"""

from __future__ import annotations

import os
import signal
import threading

from lib.config import CONFIG_FILENAME, config_path
from lib.config.manager import (
    ConfigManager, bootstrap_database_cfg, overlay_section_env, read_config_raw)
from lib.db import build_syslog_connector, get_connector
from lib.debug import Debug, DebugLevel
from .manager import _EventsMixin
from lib.services.heartbeat import _HeartbeatMixin, db_summary
from lib.services.control_server import start_control_server
from lib.core.audit.store import AuditStore
from lib.core.config.store import ConfigStore
from lib.services.events.store import EventRulesStore, EventStateStore, NotificationLogStore
from lib.services.manager.instances import ServiceInstancesStore
from lib.services.manager.commands import ServiceCommandsStore
from lib.services.manager.leader import ServiceLeaderStore
from lib.services.syslog.store import SyslogStore
from lib.core.notify.webhook.store import WebhooksStore
from lib.security import secret_manager

_CONFIG_WATCH_EVERY = 15        # poll the shared DB for rule/config changes (s)


class EventService(_HeartbeatMixin, _EventsMixin):
    """Own the decoupled event worker as a self-contained, DB-sharing daemon."""

    _CONFIG_FILE = CONFIG_FILENAME
    _HB_KEY = 'events'
    _LEADER_GATED = True       # single-owner: only the lease holder advances the cursor

    # ── heartbeat hooks (observed state for the Services tab) ──────────────────
    def _hb_running(self) -> bool:
        # Report "running" only while actually processing: events|enabled=false idles
        # the worker (a Services-tab stop), so the web card shows it stopped.
        return not self._stop.is_set() and self._events_enabled()

    def _hb_detail(self) -> dict:
        return {'poll_secs': self._poll_secs()}

    def _hb_db_info(self) -> dict:
        info = {'main': self._hb_db_main}
        if self._hb_db_syslog:
            info['syslog'] = self._hb_db_syslog
        return info

    def __init__(self, config_dir: str, var_dir: str | None = None,
                 log_level: str | None = None):
        self._config_dir = config_dir
        self._var_dir = var_dir or config_dir
        self._log_level_override = log_level or None
        self._secret_key_path = os.path.join(config_dir, '.flask_secret')
        self._fernet = secret_manager.fernet_from_secret_file(self._secret_key_path)
        self._secret_keys = secret_manager.ENCRYPT_KEYS

        # Main connector (audit/event-rules/notification-log/event-state), same
        # logic the web admin uses (incl. SS_DB_* env), defaulting to shared SQLite.
        db_cfg = bootstrap_database_cfg(read_config_raw(config_path(config_dir), self._fernet))
        db_path = os.path.join(self._var_dir, 'data.db')
        self._db_connector = get_connector(db_cfg or None, default_sqlite_path=db_path)

        self._config_store = ConfigStore(self._db_connector)
        self._config_mgr = ConfigManager(
            self._config_store, config_path(config_dir),
            fernet=self._fernet, secret_keys=self._secret_keys)

        # Syslog rows may live in their own DB (high-volume isolation); falls back
        # to the system connector when ``syslog_db`` is not enabled.
        _sdb = overlay_section_env('syslog_db', self._config_section('syslog_db'))
        self._syslog_db_connector = build_syslog_connector(
            _sdb, main_connector=self._db_connector,
            default_sqlite_path=os.path.join(self._var_dir, 'syslog.db'))
        self._hb_db_main = db_summary(db_cfg, os.path.basename(db_path))
        self._hb_db_syslog = (db_summary(_sdb, 'syslog.db')
                              if (_sdb or {}).get('enabled') else None)

        # Sources the worker consumes (audit on the main DB, syslog on its own).
        self._audit_store = AuditStore(self._db_connector)
        self._syslog_store = SyslogStore(self._syslog_db_connector)
        # Dispatch + bookkeeping (shared DB).
        self._webhooks_store = WebhooksStore(
            self._db_connector, fernet=self._fernet, secret_keys=self._secret_keys)
        self._event_rules_store = EventRulesStore(self._db_connector)
        self._notification_log_store = NotificationLogStore(self._db_connector)
        self._event_state_store = EventStateStore(self._db_connector)
        # Liveness registry (shared DB) so the web admin sees this worker.
        self._service_instances_store = ServiceInstancesStore(self._db_connector)
        # Imperative command queue (run-now/reload) the heartbeat loop drains.
        self._service_commands_store = ServiceCommandsStore(self._db_connector)
        # Leader lease: with >1 events replica only the holder advances the cursor.
        self._service_leader_store = ServiceLeaderStore(self._db_connector)

        self._init_events()
        self._attach_event_state(self._event_state_store)

        self._debug = Debug()
        self._debug.set_from_config(
            self._log_level_override
            or self._config_section('global').get('log_level') or 'info')
        self._stop = threading.Event()

        backend = ((db_cfg or {}).get('driver') or (db_cfg or {}).get('engine')
                   or (db_cfg or {}).get('type') or 'sqlite')
        self._dbg(f'> Events >> service init: config={config_dir} var={self._var_dir} '
                  f'db={backend}', DebugLevel.info)

    # ── context surface used by the notification dispatcher ───────────────────
    def _read_config_file(self, _filename: str | None = None) -> dict:
        """Effective configuration (DB ← config.json), via the ConfigManager."""
        return self._config_mgr.read() or {}

    def _config_section(self, name: str) -> dict:
        return (self._read_config_file(self._CONFIG_FILE) or {}).get(name) or {}

    def _load_webhooks(self, *, decrypt: bool = True) -> list:
        try:
            return self._webhooks_store.list(decrypt=decrypt)
        except Exception:  # pylint: disable=broad-except
            return []

    def _dbg(self, message, level: DebugLevel = DebugLevel.info) -> None:
        self._debug.print(message, level)

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def _poll_secs(self) -> int:
        v = self._config_section('events').get('poll_secs')
        try:
            return max(1, int(v)) if v not in (None, '') else 2
        except (TypeError, ValueError):
            return 2

    def _reconcile_once(self) -> None:
        """Re-read config + refresh the rule cache.  Called by the periodic watch
        loop and on demand by the control-server poke."""
        self._config_mgr.invalidate()
        self._events_reload()

    def _watch_loop(self) -> None:
        """Pick up rule edits made from the web UI (a different process)."""
        while not self._stop.wait(_CONFIG_WATCH_EVERY):
            self._reconcile_once()

    def run(self) -> int:
        """Block running the worker loop until interrupted (SIGINT/SIGTERM)."""
        def _shutdown(*_a):
            self._dbg('> Events >> shutdown requested', DebugLevel.info)
            self._stop.set()
        for _sig in (signal.SIGINT, getattr(signal, 'SIGTERM', signal.SIGINT)):
            try:
                signal.signal(_sig, _shutdown)
            except (ValueError, OSError):
                pass                                  # not in the main thread / unsupported
        self._events_reload()
        threading.Thread(target=self._watch_loop, name='events-config-watch',
                         daemon=True).start()
        self._control_server = start_control_server(self)
        self.start_heartbeat()
        self._dbg('> Events >> standalone worker starting '
                  f'(poll={self._poll_secs()}s)', DebugLevel.info)
        # _event_worker_loop blocks until self._stop is set.
        self._event_worker_loop(self._stop, self._poll_secs())
        self.stop_heartbeat()
        return 0


def run_standalone(args, config_dir: str, var_dir: str, modules_dir=None) -> int:
    """Build + run the event worker as a standalone process (``main.py --events``)."""
    return EventService(config_dir, var_dir,
                        log_level=getattr(args, 'log_level', None)).run()
