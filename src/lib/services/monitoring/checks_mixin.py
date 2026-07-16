#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""On-demand module check execution mixin for WebAdmin.

The "run check now" button: build a transient Monitor and run the requested
modules through the shared check executor (:mod:`lib.services.monitoring.executor`,
the same one the scheduler cycle uses), returning serialisable results for the UI.
"""

import os

# Hard per-module timeout (seconds).  After this _run_checks returns; blocking
# threads continue in the background (they cannot be killed) but do NOT delay the
# response to the frontend.
_MODULE_CHECK_TIMEOUT = 45


class _ChecksMixin:
    """Run module checks via Monitor and return serialisable results."""

    def _run_checks(self, requested) -> tuple[dict, list[str]]:
        """Execute the requested module checks in parallel and return their
        serialisable results.

        All modules start simultaneously; returns after ``_MODULE_CHECK_TIMEOUT``
        seconds regardless of whether any module is still running (modules past the
        deadline are reported as a timeout error).
        """
        import sys
        from lib import Monitor
        from lib.services.monitoring.executor import run_checks

        if self._modules_dir and self._modules_dir not in sys.path:
            sys.path.insert(0, self._modules_dir)
        parent = os.path.dirname(self._modules_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        dir_base = os.path.dirname(self._modules_dir)
        monitor = Monitor(dir_base, self._config_dir,
                          self._modules_dir, self._var_dir)
        # An on-demand "Run all" notifies exactly like the daemon cycle: give the transient
        # monitor a cycle notifier routed through this host's core notification router (same as
        # the persistent monitor in manager._monitoring_build_monitor). It is state-change based
        # (the shared check_state is the baseline), so an unchanged service sends nothing; the
        # executor flushes it at the end of the batch.
        try:
            from lib.core.notify.monitor_notifier import MonitorNotifier  # noqa: PLC0415
            # A manual run routes as a single ``manual_run`` event (one routing row),
            # separate from the daemon's per-kind down/recovery/warn — the digest still
            # shows each check's real state.
            monitor._notifier = MonitorNotifier(self, route_kind='manual_run')
        except Exception:  # pylint: disable=broad-except
            pass

        if requested == 'all':
            module_names = monitor._get_enabled_modules()
        else:
            module_names = [m for m in requested if isinstance(m, str)]

        return run_checks(monitor, module_names, timeout=_MODULE_CHECK_TIMEOUT,
                          history=getattr(self, '_history', None))
