#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""On-demand module check execution mixin for WebAdmin.

The "run check now" button: build a transient Monitor and run the requested
modules through the shared check executor (:mod:`lib.services.monitoring.executor`,
the same one the scheduler cycle uses), returning serialisable results for the UI.
"""

import os

# Hard per-module timeout (seconds) for a run somebody is WAITING ON — the Status screen's
# button holds the HTTP request open, so this is how long a browser is asked to sit there.
# Blocking threads continue in the background afterwards (they cannot be killed) and write
# their own state and history when they land; they just no longer delay the answer.
#
# A run that is not holding a request open should not use this number: see the `timeout`
# argument, which is how the infrastructure section's background collection asks for the
# configured `monitoring|module_timeout` instead of a browser's patience.
_MODULE_CHECK_TIMEOUT = 45


class _ChecksMixin:
    """Run module checks via Monitor and return serialisable results."""

    def _run_checks(self, requested, *, timeout: int | None = None,
                    progress_cb=None, lang: str = '') -> tuple[dict, list[str]]:
        """Execute the requested module checks in parallel and return their
        serialisable results.

        All modules start simultaneously; returns after *timeout* seconds (default
        ``_MODULE_CHECK_TIMEOUT``) regardless of whether any module is still running
        (modules past the deadline are reported as a timeout error).

        ``timeout`` is a parameter and not the constant because the two callers are asking
        different questions. A button that holds the request open is asking "how long may a
        browser be made to wait"; a background collection is asking "how long is this
        installation willing to wait for one module", which is a setting the operator owns
        (``monitoring|module_timeout``) — a fleet whose NAS answers in five minutes needs a
        different answer from one whose devices answer in two seconds.

        ``progress_cb(state, module, detail, extra)`` is handed straight to the executor: it
        is called as each module starts and lands, so a background run can be watched.

        ``lang`` is the language of whoever is WATCHING, carried through so a module's progress
        lines come out in it. Without it they are resolved in the installation's notification
        language — right for a message sent to a channel, wrong for a line on the screen of the
        person who just pressed the button.
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

        return run_checks(monitor, module_names, lang=lang,
                          timeout=int(timeout or _MODULE_CHECK_TIMEOUT),
                          history=getattr(self, '_history', None),
                          progress_cb=progress_cb)
