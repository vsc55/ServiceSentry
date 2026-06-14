#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module check execution mixin for WebAdmin."""

import concurrent.futures
import os
import threading

# Hard per-module timeout (seconds).
# After this time _run_checks returns; blocking threads continue in background
# (they cannot be killed) but do NOT delay the response to the frontend.
_MODULE_CHECK_TIMEOUT = 45


class _ChecksMixin:
    """Run module checks via Monitor and return serialisable results."""

    def _run_checks(self, requested) -> tuple[dict, list[str]]:
        """Execute module checks in parallel and return serialisable results.

        All modules start simultaneously.  The function returns after
        _MODULE_CHECK_TIMEOUT seconds regardless of whether any module is
        still running — it does NOT wait for blocking threads.

        Modules that have not finished by the deadline are reported as errors.
        Their background threads will eventually finish on their own internal
        timeouts (socket / subprocess timeouts in each module).
        """
        import sys
        from lib import Monitor

        if self._modules_dir and self._modules_dir not in sys.path:
            sys.path.insert(0, self._modules_dir)
        parent = os.path.dirname(self._modules_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        dir_base = os.path.dirname(self._modules_dir)
        monitor = Monitor(dir_base, self._config_dir,
                          self._modules_dir, self._var_dir)

        if requested == 'all':
            module_names = monitor._get_enabled_modules()
        else:
            module_names = [m for m in requested if isinstance(m, str)]

        results: dict = {}
        errors:  list[str] = []

        if not module_names:
            return results, errors

        _save_lock    = threading.Lock()
        _hist_lock    = threading.Lock()
        _hist_records: list = []   # (module, key, status, other_data) collected from workers

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
                    # Collect history data under a separate lock so the
                    # main thread can write sequentially after wait().
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
                # check_module returned success=False (exception silently caught inside).
                # Suppress the error only when:
                #   - the module IS a known/enabled module (exists on disk), AND
                #   - it has no items configured yet (user hasn't set it up)
                # Unknown/non-existent modules always produce an error.
                if mod_name in _enabled_set and not _has_items(mod_name):
                    return mod_name, {}, None   # known module, no items → empty card
                return mod_name, None, f'{mod_name}: check failed'
            except Exception as exc:  # pylint: disable=broad-except
                if mod_name in _enabled_set and not _has_items(mod_name):
                    return mod_name, {}, None
                return mod_name, None, f'{mod_name}: {type(exc).__name__}: {exc}'

        # Warm module imports sequentially before the concurrent phase: a module
        # that mutates the global sys.path during its check (dns loads dnspython,
        # whose package shadows our 'dns' watchful) must not race with bare-name
        # imports of the others.  After warming, every import is a cache hit.
        for _m in module_names:
            try:
                monitor._import_watchful(_m)
            except Exception:  # pylint: disable=broad-except
                pass  # _run_one reports the real per-module error

        # Use shutdown(wait=False) so blocking threads do NOT delay the response.
        # concurrent.futures.wait() returns after the deadline; then we shut down
        # the executor without waiting for still-running threads.
        workers  = min(len(module_names), 16)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        try:
            future_to_mod = {executor.submit(_run_one, m): m for m in module_names}
            done, not_done = concurrent.futures.wait(
                future_to_mod.keys(),
                timeout=_MODULE_CHECK_TIMEOUT,
            )
        finally:
            # IMPORTANT: wait=False — return immediately without joining threads.
            # Threads that are still blocking on network I/O will finish on their
            # own; they cannot be forcibly killed in Python.
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
            errors.append(f'{future_to_mod[future]}: timeout after {_MODULE_CHECK_TIMEOUT}s')

        # Write history sequentially from this thread to avoid concurrent
        # lock contention on the SQLite file.
        if self._history and _hist_records:
            for _mod, _key, _status, _data in _hist_records:
                self._history.record(_mod, _key, _status, _data)

        return results, errors
