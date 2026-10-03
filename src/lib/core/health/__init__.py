#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Platform self-monitoring (core).

Health of the platform *itself* — is my background stack alive, are my certificates
valid — as opposed to :mod:`lib.services.monitoring`, which monitors external targets.
It sits below the monitoring service: two lightweight, leader-gated background evaluators
that turn observed state into notification events routed by :mod:`lib.core.notify`.

* :class:`lib.core.health.health.ServiceHealthMonitor` — ``service_down`` / ``service_up``
  from the heartbeat registry.
* :class:`lib.core.health.cert_scan.CertExpiryScanner` — ``cert_expiring`` from the
  configured ``ssl_cert`` checks.

Kept import-light (no Flask, no eager service imports); the events it publishes are
declared in :mod:`lib.core.health.manifest` and discovered by the notify registry.
"""

import threading


class ScannerThread:
    """``start`` / ``stop`` for the background evaluators in this package.

    Each scanner used to keep its own copy, and each copy had one of two faults: ``stop()``
    left ``_thread`` set, so ``start()`` afterwards was a no-op and the scanner could never
    run again; or it reused one ``Event`` that ``start()`` cleared, so a ``start()`` right
    after a ``stop()`` revived the OLD loop next to the new one. Here every start gets a fresh
    Event its loop captures, and ``stop()`` sets it, waits (bounded) for the loop and forgets
    the thread.
    """

    _thread = None
    _stop = None
    #: How long :meth:`stop` waits for the loop to end (an evaluation may be mid-flight).
    STOP_JOIN_SECS = 2.0

    def _spawn(self, name: str, loop) -> bool:
        """Run ``loop(stop_event)`` on a daemon thread, unless one is already running."""
        cur = self._thread
        if cur is not None and cur.is_alive():
            return False
        # A fresh Event once a stop has been asked for: clearing the old one would wake the
        # loop it belongs to, if that loop has not finished yet. One never set (a scanner not
        # started yet) is kept.
        stop_ev = self._stop
        if stop_ev is None or stop_ev.is_set():
            stop_ev = threading.Event()
            self._stop = stop_ev
        self._thread = threading.Thread(target=loop, args=(stop_ev,), name=name, daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float | None = None) -> None:
        """Signal the loop, wait for it (bounded) and forget it, so ``start`` works again."""
        ev = self._stop
        if ev is not None:
            ev.set()
        cur, self._thread = self._thread, None
        if cur is not None and cur.is_alive() and cur is not threading.current_thread():
            cur.join(self.STOP_JOIN_SECS if timeout is None else timeout)


def default_text(key, *args) -> str:
    """Fallback text resolver: the default-language i18n string.

    The evaluators in this package run **without a host wired** (leader-gated background
    threads, no request, no session), so there is no per-user language to resolve against.
    Each of them used to carry its own identical copy of this; one is enough, and the
    import stays local so the package remains import-light.
    """
    from lib.i18n import translate  # noqa: PLC0415
    return translate('', key, *args)
