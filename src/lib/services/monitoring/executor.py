#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The shared check executor — runs a set of watchful modules on a Monitor.

One place owns "run these modules concurrently, process + persist each result,
collect the per-item status/message, record history, and report errors/timeouts".
Both callers reuse it:

* the **on-demand** check (web UI "run now", :class:`_ChecksMixin`) — a transient
  Monitor, the modules the user asked for, a short deadline;
* the **scheduler** cycle (:class:`_MonitoringMixin`) — the persistent Monitor,
  every enabled module, a longer deadline + change-detection/history.

What differs (which Monitor, which modules, the timeout, the cycle-level logging)
stays in the callers; the per-module run loop lives here, so it exists once.
"""

from __future__ import annotations

import concurrent.futures
import threading

from lib.debug import DebugLevel


def run_checks(monitor, module_names, *, timeout: int, history=None) -> tuple[dict, list]:
    """Run *module_names* on *monitor* concurrently and return ``(results, errors)``.

    ``results`` = ``{module: {item: {'status', 'message'}}}`` for modules that ran;
    ``errors`` = a list of ``"module: reason"`` strings.  Returns after *timeout*
    seconds regardless of still-running modules — their daemon threads finish on
    their own internal (socket/subprocess) timeouts and cannot be killed.  When a
    *history* store is given, each item's status is recorded sequentially from the
    calling thread (no concurrent SQLite contention)."""
    if not module_names:
        return {}, []

    results: dict = {}
    errors: list[str] = []
    _save_lock = threading.Lock()
    _hist_lock = threading.Lock()
    _hist_records: list = []
    _enabled_set = set(monitor._get_enabled_modules())

    def _has_items(mod_name: str) -> bool:
        """True if the module has at least one item configured in any collection."""
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
                            result_name, _key,
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
                _failed = sum(1 for k in items if items[k]['status'] is not True)
                monitor.debug.print(
                    f"> Check > {mod_name} >> {len(items)} item(s), {_failed} not OK",
                    DebugLevel.debug)
                return mod_name, items, None
            # check_module returned success=False.  Suppress the error only for a
            # known/enabled module with no items configured yet (user hasn't set it
            # up); unknown/non-existent modules always produce an error.
            if mod_name in _enabled_set and not _has_items(mod_name):
                return mod_name, {}, None
            monitor.debug.print(f"> Check > {mod_name} >> check failed", DebugLevel.warning)
            return mod_name, None, f'{mod_name}: check failed'
        except Exception as exc:  # pylint: disable=broad-except
            if mod_name in _enabled_set and not _has_items(mod_name):
                return mod_name, {}, None
            monitor.debug.print(
                f"> Check > {mod_name} >> {type(exc).__name__}: {exc}", DebugLevel.error)
            return mod_name, None, f'{mod_name}: {type(exc).__name__}: {exc}'

    # Warm module imports sequentially before the concurrent phase: a module that
    # mutates sys.path during its check (dns loads dnspython, whose package shadows
    # our 'dns' watchful) must not race with bare-name imports of the others.
    for _m in module_names:
        try:
            monitor._import_watchful(_m)
        except Exception:  # pylint: disable=broad-except
            pass            # _run_one reports the real per-module error

    workers = min(len(module_names), 16)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        future_to_mod = {executor.submit(_run_one, m): m for m in module_names}
        done, not_done = concurrent.futures.wait(future_to_mod.keys(), timeout=timeout)
    finally:
        # wait=False: return immediately without joining still-blocking threads
        # (they cannot be forcibly killed in Python).
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
        errors.append(f'{future_to_mod[future]}: timeout after {timeout}s')

    # Write history sequentially from this thread (no concurrent SQLite contention).
    if history and _hist_records:
        for _mod, _key, _status, _data in _hist_records:
            history.record(_mod, _key, _status, _data)

    return results, errors
