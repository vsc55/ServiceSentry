#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone service monitor — run the check scheduler as its own process/container.

The web admin hosts the scheduler in-process by default (``monitoring|enabled``,
subject to ``SS_MONITORING_EMBEDDED``, see
:class:`lib.services.monitoring.manager._MonitoringMixin`), but the same loop can run on its
own host/container, sharing the database with the rest of ServiceSentry.  Set
``SS_MONITORING_EMBEDDED=0`` on the web admin so a single ``--monitor`` worker
owns the checks.

It wires the collaborators the scheduler needs and nothing else (no Flask, no
listener): a DB connector + :class:`ConfigManager` (the very same effective config
edited in the web UI) and a :class:`HistoryStore` for the check history.  Rule
evaluation is **not** here — that is the decoupled event worker's job
(:class:`lib.services.events.service.EventService`); this process only runs the checks.
"""

from __future__ import annotations

import os
import signal
import threading

from lib.config import CONFIG_FILENAME, config_path
from lib.config.manager import (
    ConfigManager, bootstrap_database_cfg, overlay_section_env, read_config_raw)
from lib.db import get_connector
from lib.debug import Debug, DebugLevel
from lib.stores.config import ConfigStore
from lib.stores.service_instances import ServiceInstancesStore
from lib.stores.service_commands import ServiceCommandsStore
from lib.stores.service_leader import ServiceLeaderStore
from lib.security import secret_manager
from lib.services.heartbeat import _HeartbeatMixin, db_summary
from lib.services.control_server import start_control_server
from .manager import _MonitoringMixin

_CONFIG_WATCH_EVERY = 15        # poll the shared DB for monitoring config changes (s)


class MonitorService(_HeartbeatMixin, _MonitoringMixin):
    """Own the service-monitor scheduler as a self-contained, DB-sharing daemon."""

    _CONFIG_FILE = CONFIG_FILENAME
    _HB_KEY = 'monitoring'
    _LEADER_GATED = True       # single-owner: only the lease holder runs cycles

    # ── heartbeat hooks (observed state for the Services tab) ──────────────────
    def _hb_running(self) -> bool:
        return self._monitoring_running

    def _hb_detail(self) -> dict:
        return {'interval': self._monitoring_interval,
                'next_in': self._monitoring_seconds_until_next}

    def _hb_last_cycle(self):
        return self._monitoring_last_run_ts

    def _hb_db_info(self) -> dict:
        return {'main': getattr(self, '_hb_db_main', None)}

    def __init__(self, config_dir: str, var_dir: str | None = None,
                 modules_dir: str | None = None, *,
                 interval_override: int | None = None, log_level: str | None = None):
        self._config_dir = config_dir
        self._var_dir = var_dir or config_dir
        # Default to the watchfuls/ sibling of this checkout when not told otherwise.
        self._modules_dir = modules_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'watchfuls')
        self._log_level_override = log_level or None
        self._secret_key_path = os.path.join(config_dir, '.flask_secret')
        self._fernet = secret_manager.fernet_from_secret_file(self._secret_key_path)
        self._secret_keys = secret_manager.ENCRYPT_KEYS

        # The standalone process has no web env layer, so overlay the ``monitoring``
        # section env (SS_CHECK_INTERVAL, SS_MONITORING_ENABLED) into the same
        # env-override map the mixin reads — keeping the documented Docker envs
        # working.  A positive --timer / SS_TIMER then wins over SS_CHECK_INTERVAL.
        self._env_override_values: dict[str, object] = {}
        self._env_locked: frozenset[str] = frozenset()
        for field, val in overlay_section_env('monitoring', {}).items():
            self._env_override_values[f'monitoring|{field}'] = val
        if interval_override and interval_override > 0:
            self._env_override_values['monitoring|timer_check'] = int(interval_override)

        # Connector from the bootstrap ``database`` section (same logic the web
        # admin uses, incl. SS_DB_* env), defaulting to the shared SQLite file.
        db_cfg = bootstrap_database_cfg(read_config_raw(config_path(config_dir), self._fernet))
        db_path = os.path.join(self._var_dir, 'data.db')
        self._db_connector = get_connector(db_cfg or None, default_sqlite_path=db_path)
        self._hb_db_main = db_summary(db_cfg, os.path.basename(db_path))

        self._config_store = ConfigStore(self._db_connector)
        self._config_mgr = ConfigManager(
            self._config_store, config_path(config_dir),
            fernet=self._fernet, secret_keys=self._secret_keys)

        # Liveness registry (shared DB) so the web admin sees this worker even
        # though it runs in a different process/container.
        self._service_instances_store = ServiceInstancesStore(self._db_connector)
        # Imperative command queue (run-now/clear/reload) the heartbeat loop drains.
        self._service_commands_store = ServiceCommandsStore(self._db_connector)
        # Leader lease: with >1 monitor replica only the holder runs cycles.
        self._service_leader_store = ServiceLeaderStore(self._db_connector)

        # Check history on the shared connector (same table the web admin reads).
        try:
            from lib.stores.history import HistoryStore  # noqa: PLC0415
            self._history = HistoryStore(self._db_connector)
        except Exception:  # pylint: disable=broad-except
            self._history = None

        # An on-demand check and a scheduled cycle must not overlap (the mixin
        # acquires this before each cycle); standalone has no web checks but the
        # contract is the same.
        self._check_lock = threading.Lock()

        self._debug = Debug()
        self._debug.set_from_config(
            self._log_level_override
            or self._config_section('global').get('log_level') or 'info')
        self._stop = threading.Event()
        self._monitoring_init_state()

        backend = ((db_cfg or {}).get('driver') or (db_cfg or {}).get('engine')
                   or (db_cfg or {}).get('type') or 'sqlite')
        self._dbg(f'> Monitor >> service init: config={config_dir} var={self._var_dir} '
                  f'db={backend}', DebugLevel.info)

    # ── context surface used by the scheduler mixin ───────────────────────────
    def _read_config_file(self, _filename: str | None = None) -> dict:
        """Effective configuration (DB ← config.json), via the ConfigManager."""
        return self._config_mgr.read() or {}

    def _config_section(self, name: str) -> dict:
        return (self._read_config_file(self._CONFIG_FILE) or {}).get(name) or {}

    def _dbg(self, message, level: DebugLevel = DebugLevel.info) -> None:
        self._debug.print(message, level)

    # ── one-shot ──────────────────────────────────────────────────────────────
    def clear_status(self) -> None:
        """Clear the saved check state before a run (the ``--clear`` flag)."""
        try:
            self._monitoring_get_monitor().clear_status()
            self._dbg('> Monitor >> saved check status cleared', DebugLevel.info)
        except Exception as exc:  # pylint: disable=broad-except
            self._dbg(f'> Monitor >> clear status failed: {exc}', DebugLevel.error)

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def _reconcile_once(self) -> None:
        """Converge to the desired state: re-read config and start/stop the
        scheduler when the ``enabled`` flag is toggled.  Called both by the periodic
        watch loop and on demand by the control-server poke."""
        self._config_mgr.invalidate()                    # drop the cache, read fresh DB
        enabled = self._monitoring_enabled()
        running = self._monitoring_running
        if enabled and not running:
            self._dbg('> Monitor >> enabled in config; starting scheduler',
                      DebugLevel.info)
            self._monitoring_start(run_now=True)
        elif not enabled and running:
            self._dbg('> Monitor >> disabled in config; stopping scheduler',
                      DebugLevel.info)
            self._monitoring_stop()

    def _watch_loop(self) -> None:
        """Pick up monitoring config edits made from the web UI (a different
        process): start/stop the scheduler when ``enabled`` is toggled — so the
        standalone worker reacts to the web Services tab without a restart."""
        while not self._stop.wait(_CONFIG_WATCH_EVERY):
            self._reconcile_once()

    def run(self, once: bool = False) -> int:
        """Run the scheduler and block until stopped (SIGINT/SIGTERM).

        *once* runs a single check pass and returns (the ``--monitor -t 0`` mode).
        Otherwise the scheduler runs continuously at the configured interval and,
        like the syslog receiver, stays alive even when monitoring is currently
        disabled: a background watcher starts it when it is enabled from the web UI.
        """
        if once:
            self._dbg('> Monitor >> single pass', DebugLevel.info)
            self._monitoring_run_one_cycle()
            self._dbg('> Monitor >> single pass complete; exiting', DebugLevel.info)
            return 0

        def _shutdown(*_a):
            self._dbg('> Monitor >> shutdown requested', DebugLevel.info)
            self._stop.set()
        for _sig in (signal.SIGINT, getattr(signal, 'SIGTERM', signal.SIGINT)):
            try:
                signal.signal(_sig, _shutdown)
            except (ValueError, OSError):
                pass                                     # not in main thread / unsupported

        if self._monitoring_enabled():
            self._monitoring_start(run_now=True)
            self._dbg(f'> Monitor >> standalone scheduler running '
                      f'(interval={self._monitoring_interval}s, Ctrl+C to stop)',
                      DebugLevel.info)
        else:
            self._dbg('> Monitor >> monitoring is disabled in config; waiting for it '
                      'to be enabled from the web UI (Ctrl+C to stop)', DebugLevel.warning)
        threading.Thread(target=self._watch_loop, name='monitor-config-watch',
                         daemon=True).start()
        self._control_server = start_control_server(self)
        self.start_heartbeat()
        self._dbg(f'> Monitor >> config watch every {_CONFIG_WATCH_EVERY}s', DebugLevel.info)
        self._stop.wait()
        self._monitoring_stop()
        self.stop_heartbeat()
        self._dbg('> Monitor >> scheduler stopped; exiting', DebugLevel.info)
        return 0


def run_standalone(args, config_dir: str, var_dir: str, modules_dir: str) -> int:
    """Build + run the monitor as a standalone process (``main.py --monitor``).

    ``-t 0`` runs a single pass and exits; otherwise it runs continuously at the
    configured interval (``--timer`` / ``SS_TIMER`` win)."""
    timer = getattr(args, 'timer_check', None)
    svc = MonitorService(config_dir, var_dir, modules_dir,
                         interval_override=(timer if timer else None),
                         log_level=getattr(args, 'log_level', None))
    if getattr(args, 'clear_status', False):
        svc.clear_status()
    return svc.run(once=(timer == 0))
