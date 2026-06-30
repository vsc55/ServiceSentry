#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitoring scheduler mixin — the embedded/standalone service monitor.

A background loop that runs all enabled checks at a configurable interval using a
single persistent :class:`lib.Monitor` (so change-detection state survives across
cycles and notifications don't re-fire every cycle), prunes history once a day and
audits failures.

This module is intentionally Flask-free so it can be mixed into both the WebAdmin
(embedded, ``SS_MONITORING_EMBEDDED`` decides whether this process hosts it) and
the standalone :class:`lib.services.monitoring.service.MonitorService` (a separate
``--monitor`` process / Docker worker) — exactly like :class:`_EventsMixin` is
shared by the WebAdmin and the events/syslog services.

The host must provide a small context surface: ``_read_config_file`` /
``_config_section`` (effective config), ``_modules_dir`` / ``_config_dir`` /
``_var_dir`` (paths for the :class:`lib.Monitor`), ``_check_lock`` (so an
on-demand check and a scheduled cycle don't overlap) and, optionally, ``_history``
(a HistoryStore), ``_audit_system`` (audit sink), ``_env_override_values`` /
``_env_locked`` (the web env-override layer).

Configuration (``monitoring`` section, mirroring ``syslog``):
  enabled      bool — whether the monitor runs (default True). Embedded vs external
                      is the ``SS_MONITORING_EMBEDDED`` env, not a config field.
  timer_check  int  — interval in seconds (default 300); also the ``-t`` default.
"""

import os
import sys
import threading
import time

from lib.config.spec import cfg_get
from lib.debug import DebugLevel


class _MonitoringMixin:
    """Background check scheduler — embedded in the WebAdmin or run standalone."""

    # ── State ─────────────────────────────────────────────────────────────────

    def _monitoring_init_state(self) -> None:
        """Initialise scheduler state (no auto-start — the host decides when to
        start: the WebAdmin gates on enabled+embedded, the standalone service on
        its ``run()``)."""
        self._monitoring_thread: threading.Thread | None = None
        self._monitoring_stop_event: threading.Event = threading.Event()
        self._monitoring_next_run_ts: float = 0.0   # time.monotonic() target
        self._monitoring_last_run_ts: float | None = None  # epoch (wall-clock) of last run
        self._monitoring_monitor = None             # persistent Monitor instance
        self._monitoring_last_prune_ts: float = 0.0  # epoch of last history prune
        self._monitoring_lifecycle_lock = threading.Lock()  # guards start/stop races

    @staticmethod
    def _embedded_monitor_enabled() -> bool:
        """Whether this process hosts the embedded monitor (SS_MONITORING_EMBEDDED).

        Defaults to True; set it to 0 (e.g. on the web container) when a separate
        ``--monitor`` process / Docker worker owns the monitoring loop."""
        v = os.environ.get('SS_MONITORING_EMBEDDED')
        return True if v is None else v.strip().lower() not in ('0', 'false', 'no', 'off')

    def _monitoring_enabled(self) -> bool:
        """Whether monitoring is enabled (the master switch; env override honoured)."""
        ov = getattr(self, '_env_override_values', {}).get('monitoring|enabled')
        if ov is not None:
            return bool(ov)
        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        return bool(cfg_get(cfg.get('monitoring', {}), 'monitoring|enabled'))

    def _monitoring_autostart(self) -> bool:
        """Whether the embedded monitor starts at web-admin boot (env override
        honoured).  Standalone ``--monitor`` ignores this — it always runs when
        enabled."""
        ov = getattr(self, '_env_override_values', {}).get('monitoring|autostart')
        if ov is not None:
            return bool(ov)
        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        return bool(cfg_get(cfg.get('monitoring', {}), 'monitoring|autostart'))

    def _monitoring_audit(self, event: str, detail: dict | None = None) -> None:
        """Emit an audit event when the host provides a sink (the WebAdmin does;
        the standalone service has none — it logs instead)."""
        fn = getattr(self, '_audit_system', None)
        if fn is None:
            return
        try:
            fn(event, detail or {})
        except Exception:  # pylint: disable=broad-except
            pass

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def _monitoring_running(self) -> bool:
        return self._monitoring_thread is not None and self._monitoring_thread.is_alive()

    @property
    def _monitoring_interval(self) -> int:
        """Interval in seconds (re-read from config so live changes take effect).

        An env var (SS_CHECK_INTERVAL) overrides the saved value and wins — so the
        embedded scheduler honours it in the monolithic Docker mode."""
        ov = getattr(self, '_env_override_values', {}).get('monitoring|timer_check')
        if ov is not None:
            return max(10, int(ov))
        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        return max(10, cfg_get(cfg.get('monitoring', {}), 'monitoring|timer_check', falsy=True))

    @property
    def _monitoring_seconds_until_next(self) -> int | None:
        """Seconds until the next scheduled check, or None if not running."""
        if not self._monitoring_running or not self._monitoring_next_run_ts:
            return None
        return max(0, int(self._monitoring_next_run_ts - time.monotonic()))

    def _monitoring_status_dict(self) -> dict:
        """Serialisable snapshot of the monitor state (mirrors the syslog model:
        an ``enabled`` flag; embedded vs external is the SS_MONITORING_EMBEDDED
        env, surfaced by :meth:`_service_monitoring_status`)."""
        locked = getattr(self, '_env_locked', frozenset())
        return {
            'running':     self._monitoring_running,
            'interval':    self._monitoring_interval,
            'next_in':     self._monitoring_seconds_until_next,
            'last_run':    self._monitoring_last_run_ts,
            'enabled':     self._monitoring_enabled(),
            'enabled_locked':  'monitoring|enabled' in locked,
            'interval_locked': 'monitoring|timer_check' in locked,
        }

    # ── Control ───────────────────────────────────────────────────────────────

    def _monitoring_start(self, run_now: bool = False) -> bool:
        """Start the scheduler.  Returns False if it is already running.

        Guarded by a lifecycle lock so two concurrent start requests can't
        both pass the running-check and spawn duplicate scheduler threads.
        """
        with self._monitoring_lifecycle_lock:
            if self._monitoring_running:
                return False
            self._monitoring_stop_event.clear()
            self._monitoring_monitor = None   # reset so loop creates a fresh monitor
            self._monitoring_thread = threading.Thread(
                target=self._monitoring_loop,
                args=(run_now,),
                daemon=True,
                name='ss-scheduler',
            )
            self._monitoring_thread.start()
        self._monitoring_audit('daemon_started', {
            'interval': self._monitoring_interval,
            'run_now':  run_now,
        })
        return True

    def _monitoring_stop(self) -> bool:
        """Signal the scheduler to stop.  Returns False if not running."""
        with self._monitoring_lifecycle_lock:
            if not self._monitoring_running:
                return False
            self._monitoring_stop_event.set()
            self._monitoring_next_run_ts = 0.0
            self._monitoring_monitor = None
        self._monitoring_audit('daemon_stopped', {})
        return True

    # ── Imperative commands (run-now / clear / reload) ─────────────────────────
    def _apply_command(self, action: str, args: dict | None = None) -> tuple[bool, str]:
        """Execute a one-shot command from the service-command queue.  Runs on the
        instance that hosts the monitor (embedded here or a remote worker), so the
        UI can trigger it regardless of where monitoring lives."""
        if action == 'run_now':
            # Don't overlap with the scheduler / an on-demand check.
            if not self._check_lock.acquire(blocking=False):
                return False, 'busy'
            try:
                results, errors = self._monitoring_run_one_cycle()
                return True, f'{len(results)} ok, {len(errors)} error(s)'
            finally:
                self._check_lock.release()
        if action == 'clear_status':
            try:
                self._monitoring_get_monitor().clear_status()
                return True, 'status cleared'
            except Exception as exc:  # pylint: disable=broad-except
                return False, str(exc)
        if action == 'reload':
            mgr = getattr(self, '_config_mgr', None)
            if mgr is not None:
                try:
                    mgr.invalidate()
                except Exception:  # pylint: disable=broad-except
                    pass
            return True, 'config reloaded'
        return False, 'unknown_action'

    # ── Internal: persistent monitor ──────────────────────────────────────────

    def _monitoring_get_monitor(self):
        """Return the persistent Monitor instance, creating it if needed.

        Using a single Monitor across all scheduler cycles is critical for
        correct change detection.  The Monitor's in-memory ``status`` dict
        accumulates the last-known state of each check item.  Re-creating the
        monitor each cycle would reload from disk, which can lose states that
        were updated in-memory but not yet flushed — causing check_status() to
        see every item as "new" and firing Telegram notifications on every cycle.
        """
        if self._monitoring_monitor is not None:
            return self._monitoring_monitor

        from lib import Monitor  # pylint: disable=import-outside-toplevel

        if self._modules_dir and self._modules_dir not in sys.path:
            sys.path.insert(0, self._modules_dir)
        parent = os.path.dirname(self._modules_dir or '')
        if parent and parent not in sys.path:
            sys.path.insert(0, parent)

        dir_base = os.path.dirname(self._modules_dir or '')
        self._monitoring_monitor = Monitor(
            dir_base, self._config_dir, self._modules_dir, self._var_dir,
        )
        return self._monitoring_monitor

    def _monitoring_run_one_cycle(self) -> tuple[dict, list]:
        """Run all enabled checks for one scheduler cycle on the *persistent*
        Monitor (so change-detection state carries across cycles).  The per-module
        run is delegated to the shared
        :func:`lib.services.monitoring.executor.run_checks` (the same executor the
        on-demand UI checks use); only the cycle setup + logging live here.
        """
        from lib.services.monitoring.executor import run_checks  # noqa: PLC0415

        monitor = self._monitoring_get_monitor()
        # Apply global|log_level + re-read the effective (DB) config each cycle so
        # live edits to verbosity / Telegram / public URL take effect without a
        # restart; then drop stale live status for hosts now in maintenance.
        monitor.debug.set_from_config(cfg_get(self._config_section('global'), 'global|log_level'))
        monitor.refresh_runtime_config()
        monitor.purge_maintenance_states()

        module_names = monitor._get_enabled_modules()
        if not module_names:
            monitor.debug.print("> Daemon >> Cycle skipped: no enabled modules",
                                 DebugLevel.info)
            return {}, []
        monitor.debug.print(
            f"> Daemon >> Cycle start: {len(module_names)} module(s)", DebugLevel.info)

        results, errors = run_checks(monitor, module_names, timeout=120,
                                     history=getattr(self, '_history', None))

        if errors:
            monitor.debug.print(
                f"> Daemon >> Cycle end: {len(results)} ok, {len(errors)} error(s) — "
                + '; '.join(errors), DebugLevel.warning)
        else:
            monitor.debug.print(
                f"> Daemon >> Cycle end: {len(results)} ok", DebugLevel.info)
        return results, errors

    # ── Loop ──────────────────────────────────────────────────────────────────

    def _monitoring_loop(self, run_now: bool) -> None:
        """Background loop — runs in a daemon thread."""

        if not run_now:
            interval = self._monitoring_interval
            self._monitoring_next_run_ts = time.monotonic() + interval
            if self._monitoring_stop_event.wait(timeout=interval):
                self._monitoring_next_run_ts = 0.0
                return

        while not self._monitoring_stop_event.is_set():
            self._monitoring_next_run_ts = 0.0
            # Hot standby: with leader gating, only the lease holder runs cycles —
            # other replicas keep the scheduler alive but idle (no double checks /
            # alerts). _work_allowed() is always true for non-gated / single owner.
            _allowed = self._work_allowed() if hasattr(self, '_work_allowed') else True
            if _allowed:
                self._monitoring_last_run_ts = time.time()  # wall-clock epoch for the UI
            try:
                # Skip cycle if not the leader, or if an on-demand check is running.
                if _allowed and self._check_lock.acquire(blocking=False):
                    try:
                        results, errors = self._monitoring_run_one_cycle()
                        # Only audit when there are errors — successful runs are
                        # too frequent and would flood the audit log.
                        if errors:
                            self._monitoring_audit('daemon_checks_run', {
                                'ok':     list(results.keys()),
                                'errors': errors,
                            })
                    finally:
                        self._check_lock.release()
            except Exception as exc:  # pylint: disable=broad-except
                _mon = self._monitoring_monitor
                if _mon is not None and _mon.debug.enabled:
                    _mon.debug.exception(exc)
                self._monitoring_audit('daemon_error', {'error': str(exc)})
                self._monitoring_monitor = None   # reset on error so next cycle starts fresh

            # Prune old history once per day.
            if time.time() - self._monitoring_last_prune_ts > 86400:
                try:
                    if getattr(self, '_history', None):
                        cfg = self._read_config_file(self._CONFIG_FILE) or {}
                        days = max(0, int(cfg.get('history', {}).get('retention_days', 30)))
                        self._history.prune(days)
                except Exception:  # pylint: disable=broad-except
                    pass
                self._monitoring_last_prune_ts = time.time()

            interval = self._monitoring_interval
            self._monitoring_next_run_ts = time.monotonic() + interval
            if self._monitoring_stop_event.wait(timeout=interval):
                self._monitoring_next_run_ts = 0.0
                return
