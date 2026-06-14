#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background scheduler mixin for WebAdmin.

Adds an in-process monitoring loop so the web admin can run checks
automatically at a configurable interval without needing a separate
systemd service.

Configuration (config.json → daemon):
  timer_check    int  — interval in seconds (min 60, default 300).
                        Also used as the default for ``-t`` in daemon mode.
  web_autostart  bool — start the scheduler automatically when the web
                        admin process starts (default false).
"""

import os
import sys
import threading
import time


class _DaemonMixin:
    """Background check scheduler embedded in the WebAdmin process."""

    # ── State ─────────────────────────────────────────────────────────────────

    def _daemon_init(self) -> None:
        """Initialise scheduler state.  Called from WebAdmin.__init__."""
        self._daemon_thread: threading.Thread | None = None
        self._daemon_stop_event: threading.Event = threading.Event()
        self._daemon_next_run_ts: float = 0.0   # time.monotonic() target
        self._daemon_last_run_ts: float | None = None  # epoch (wall-clock) of last run
        self._daemon_monitor = None             # persistent Monitor instance
        self._daemon_last_prune_ts: float = 0.0  # epoch of last history prune
        self._daemon_lifecycle_lock = threading.Lock()  # guards start/stop races

        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        if cfg.get('daemon', {}).get('web_autostart', False):
            self._daemon_start(run_now=True)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def _daemon_running(self) -> bool:
        return self._daemon_thread is not None and self._daemon_thread.is_alive()

    @property
    def _daemon_interval(self) -> int:
        """Interval in seconds (re-read from config so live changes take effect)."""
        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        raw = cfg.get('daemon', {}).get('timer_check', 300)
        return max(10, int(raw or 300))

    @property
    def _daemon_seconds_until_next(self) -> int | None:
        """Seconds until the next scheduled check, or None if not running."""
        if not self._daemon_running or not self._daemon_next_run_ts:
            return None
        return max(0, int(self._daemon_next_run_ts - time.monotonic()))

    def _daemon_status_dict(self) -> dict:
        """Return a serialisable snapshot of the scheduler state."""
        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        daemon_cfg = cfg.get('daemon', {})
        return {
            'running':     self._daemon_running,
            'interval':    self._daemon_interval,
            'next_in':     self._daemon_seconds_until_next,
            'last_run':    self._daemon_last_run_ts,
            'web_autostart': bool(daemon_cfg.get('web_autostart', False)),
        }

    # ── Control ───────────────────────────────────────────────────────────────

    def _daemon_start(self, run_now: bool = False) -> bool:
        """Start the scheduler.  Returns False if it is already running.

        Guarded by a lifecycle lock so two concurrent start requests can't
        both pass the running-check and spawn duplicate scheduler threads.
        """
        with self._daemon_lifecycle_lock:
            if self._daemon_running:
                return False
            self._daemon_stop_event.clear()
            self._daemon_monitor = None   # reset so loop creates a fresh monitor
            self._daemon_thread = threading.Thread(
                target=self._daemon_loop,
                args=(run_now,),
                daemon=True,
                name='ss-scheduler',
            )
            self._daemon_thread.start()
        self._audit_system('daemon_started', {
            'interval': self._daemon_interval,
            'run_now':  run_now,
        })
        return True

    def _daemon_stop(self) -> bool:
        """Signal the scheduler to stop.  Returns False if not running."""
        with self._daemon_lifecycle_lock:
            if not self._daemon_running:
                return False
            self._daemon_stop_event.set()
            self._daemon_next_run_ts = 0.0
            self._daemon_monitor = None
        self._audit_system('daemon_stopped', {})
        return True

    # ── Internal: persistent monitor ──────────────────────────────────────────

    def _daemon_get_monitor(self):
        """Return the persistent Monitor instance, creating it if needed.

        Using a single Monitor across all scheduler cycles is critical for
        correct change detection.  The Monitor's in-memory ``status`` dict
        accumulates the last-known state of each check item.  Re-creating the
        monitor each cycle would reload from disk, which can lose states that
        were updated in-memory but not yet flushed — causing check_status() to
        see every item as "new" and firing Telegram notifications on every cycle.
        """
        if self._daemon_monitor is not None:
            return self._daemon_monitor

        from lib import Monitor  # pylint: disable=import-outside-toplevel

        if self._modules_dir and self._modules_dir not in sys.path:
            sys.path.insert(0, self._modules_dir)
        parent = os.path.dirname(self._modules_dir or '')
        if parent and parent not in sys.path:
            sys.path.insert(0, parent)

        dir_base = os.path.dirname(self._modules_dir or '')
        self._daemon_monitor = Monitor(
            dir_base, self._config_dir, self._modules_dir, self._var_dir,
        )
        return self._daemon_monitor

    def _daemon_run_one_cycle(self) -> tuple[dict, list]:
        """Run all checks using the persistent Monitor.

        Delegates to _run_checks but ensures the same Monitor instance is
        reused so state-change detection works correctly across cycles.
        """
        monitor = self._daemon_get_monitor()
        # _run_checks normally creates its own Monitor; bypass that by calling
        # the lower-level helpers directly on our persistent instance.
        import threading as _threading  # pylint: disable=import-outside-toplevel
        _save_lock    = _threading.Lock()
        _hist_lock    = _threading.Lock()
        _hist_records: list = []
        results: dict = {}
        errors: list[str] = []

        module_names = monitor._get_enabled_modules()
        if not module_names:
            return results, errors

        import concurrent.futures  # pylint: disable=import-outside-toplevel
        _enabled_set = set(module_names)

        def _has_items(mod_name: str) -> bool:
            cfg = monitor.config_modules.get_conf([mod_name]) or {}
            if not isinstance(cfg, dict):
                return False
            for val in cfg.values():
                if isinstance(val, dict) and val:
                    return True
            return False

        def _run_one(mod_name: str):
            try:
                success, result_name, result_data = monitor.check_module(mod_name)
                if success and result_data is not None:
                    with _save_lock:
                        monitor._process_module_result(result_name, result_data)
                        monitor.status.save()
                    with _hist_lock:
                        for _key in result_data.list:
                            _hist_records.append((
                                result_name,
                                _key,
                                result_data.get_status(_key),
                                result_data.get_other_data(_key),
                            ))
                    items = {
                        key: {
                            'status':  result_data.get_status(key),
                            'message': result_data.get_message(key),
                        }
                        for key in result_data.list
                    }
                    return mod_name, items, None
                if mod_name in _enabled_set and not _has_items(mod_name):
                    return mod_name, {}, None
                return mod_name, None, f'{mod_name}: check failed'
            except Exception as exc:  # pylint: disable=broad-except
                if mod_name in _enabled_set and not _has_items(mod_name):
                    return mod_name, {}, None
                return mod_name, None, f'{mod_name}: {type(exc).__name__}: {exc}'

        # Warm imports sequentially first so the dns module's dnspython load (which
        # transiently removes watchfuls/ from sys.path) can't race with concurrent
        # bare-name imports of the other modules.
        for _m in module_names:
            try:
                monitor._import_watchful(_m)
            except Exception:  # pylint: disable=broad-except
                pass

        workers = min(len(module_names), 16)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        try:
            future_to_mod = {executor.submit(_run_one, m): m for m in module_names}
            done, not_done = concurrent.futures.wait(
                future_to_mod.keys(), timeout=120,
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        for future in done:
            mod = future_to_mod[future]
            try:
                name, items, err = future.result()
                if items is not None:
                    results[name] = items
                else:
                    errors.append(err or name)
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(f'{mod}: {exc}')

        for future in not_done:
            errors.append(f'{future_to_mod[future]}: timeout')

        # Write history sequentially from the daemon thread — no concurrent
        # lock contention on the SQLite file.
        if self._history and _hist_records:
            for _mod, _key, _status, _data in _hist_records:
                self._history.record(_mod, _key, _status, _data)

        return results, errors

    # ── Loop ──────────────────────────────────────────────────────────────────

    def _daemon_loop(self, run_now: bool) -> None:
        """Background loop — runs in a daemon thread."""

        if not run_now:
            interval = self._daemon_interval
            self._daemon_next_run_ts = time.monotonic() + interval
            if self._daemon_stop_event.wait(timeout=interval):
                self._daemon_next_run_ts = 0.0
                return

        while not self._daemon_stop_event.is_set():
            self._daemon_next_run_ts = 0.0
            self._daemon_last_run_ts = time.time()  # wall-clock epoch for the UI
            try:
                # Skip cycle if an on-demand check is already running
                if self._check_lock.acquire(blocking=False):
                    try:
                        results, errors = self._daemon_run_one_cycle()
                        # Only audit when there are errors — successful runs are
                        # too frequent and would flood the audit log.
                        if errors:
                            self._audit_system('daemon_checks_run', {
                                'ok':     list(results.keys()),
                                'errors': errors,
                            })
                    finally:
                        self._check_lock.release()
            except Exception as exc:  # pylint: disable=broad-except
                self._audit_system('daemon_error', {'error': str(exc)})
                self._daemon_monitor = None   # reset on error so next cycle starts fresh

            # Prune old history once per day.
            if time.time() - self._daemon_last_prune_ts > 86400:
                try:
                    if getattr(self, '_history', None):
                        cfg = self._read_config_file(self._CONFIG_FILE) or {}
                        days = max(0, int(cfg.get('history', {}).get('retention_days', 30)))
                        self._history.prune(days)
                except Exception:  # pylint: disable=broad-except
                    pass
                self._daemon_last_prune_ts = time.time()

            interval = self._daemon_interval
            self._daemon_next_run_ts = time.monotonic() + interval
            if self._daemon_stop_event.wait(timeout=interval):
                self._daemon_next_run_ts = 0.0
                return
