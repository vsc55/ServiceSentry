#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Syslog-receiver lifecycle for the web admin.

Owns the :class:`lib.stores.syslog.SyslogStore` and the
:class:`lib.syslog.server.SyslogServer`, starting/stopping the listener from the
``syslog`` config section, evaluating the alert rule per message (routed through
the notification dispatcher with ``kind='syslog'``), and pruning old/excess rows
on a background timer.
"""

from __future__ import annotations

import os
import threading

from lib.debug import DebugLevel
from lib.syslog.alert import dispatch_syslog_alert
from lib.syslog.server import build_server, should_alert

_RETENTION_EVERY = 300          # prune sweep interval (s)
_ALERT_COOLDOWN = 60            # min seconds between alerts per source (anti-storm)


def _embedded_listener_enabled() -> bool:
    """Whether the web admin should bind the syslog ports itself.

    Set ``SS_SYSLOG_EMBEDDED=0`` when the receiver runs as its own process /
    container (``main.py --syslog``): the web admin still shows the Syslog tab
    and serves the data from the shared DB, but does not bind the ports."""
    v = os.environ.get('SS_SYSLOG_EMBEDDED')
    if v is None:
        return True
    return v.strip().lower() not in ('0', 'false', 'no', 'off')


class _SyslogMixin:

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def _init_syslog(self) -> None:
        """Create the store and start the listener (when enabled) + retention."""
        self._syslog_store = None
        self._syslog_server = None
        self._syslog_lock = threading.Lock()
        self._syslog_retention_stop = threading.Event()
        self._syslog_alert_last: dict[str, float] = {}
        connector = getattr(self, '_db_connector', None)
        if connector is None:
            return
        try:
            from lib.stores.syslog import SyslogStore  # noqa: PLC0415
            self._syslog_store = SyslogStore(connector)
        except Exception:  # pylint: disable=broad-except
            return
        self._syslog_apply_config()
        threading.Thread(target=self._syslog_retention_loop,
                         name='syslog-retention', daemon=True).start()

    def _syslog_cfg(self) -> dict:
        # Merge registry defaults underneath the saved values: defaults are lazy
        # (not stored), so a config where only ``enabled`` was toggled would
        # otherwise lack the ports and the listener would bind nothing.
        from lib.config.spec import section_defaults  # noqa: PLC0415
        return {**section_defaults('syslog'), **(self._config_section('syslog') or {})}

    def _syslog_apply_config(self) -> list[str]:
        """(Re)build and (re)start the listener from the current config.

        Returns the list of bind problems (empty on success / when disabled)."""
        with self._syslog_lock:
            if self._syslog_server is not None:
                try:
                    self._syslog_server.stop()
                except Exception:  # pylint: disable=broad-except
                    pass
                self._syslog_server = None
            cfg = self._syslog_cfg()
            if not cfg.get('enabled') or self._syslog_store is None:
                return []
            if not _embedded_listener_enabled():
                self._dbg('> Syslog >> SS_SYSLOG_EMBEDDED=0: listener runs as a '
                          'separate process; web admin serves stored data only',
                          DebugLevel.info)
                return []
            srv = build_server(
                cfg,
                sink=self._syslog_store.add_many,
                on_message=self._syslog_alert,
                dbg=lambda m: self._dbg(m, DebugLevel.info),
            )
            problems = srv.start()
            for p in problems:
                self._dbg(f"> Syslog >> bind problem: {p}", DebugLevel.error)
            if srv.running:
                self._dbg("> Syslog >> embedded listener started", DebugLevel.info)
            else:
                self._dbg("> Syslog >> embedded listener did NOT start "
                          "(no transport bound)", DebugLevel.error)
            self._syslog_server = srv
            return problems

    def _syslog_stop(self) -> None:
        """Full shutdown: stop the retention loop *and* the listener (app exit)."""
        self._syslog_retention_stop.set()
        self._syslog_listener_stop()

    def _syslog_listener_stop(self) -> None:
        """Stop just the listener, leaving retention running so it can be started
        again from the Services dashboard without a restart."""
        with self._syslog_lock:
            if self._syslog_server is not None:
                try:
                    self._syslog_server.stop()
                except Exception:  # pylint: disable=broad-except
                    pass
                self._syslog_server = None
                self._dbg("> Syslog >> embedded listener stopped", DebugLevel.info)

    # ── alert rule ──────────────────────────────────────────────────────────────
    def _syslog_alert(self, rec: dict) -> None:
        """Notify (via the dispatcher, kind='syslog') when a message matches the
        rule: severity at/above the threshold and, if set, the regex."""
        if should_alert(self._syslog_cfg(), rec, self._syslog_alert_last,
                        cooldown=_ALERT_COOLDOWN):
            src = rec.get('hostname') or rec.get('source') or '?'
            self._dbg(f"> Syslog >> alert match from {src} "
                      f"(sev={rec.get('severity_name') or rec.get('severity')}); "
                      f"dispatching", DebugLevel.warning)
            dispatch_syslog_alert(self, rec)

    # ── retention ────────────────────────────────────────────────────────────────
    def _syslog_retention_loop(self) -> None:
        while not self._syslog_retention_stop.wait(_RETENTION_EVERY):
            store = self._syslog_store
            if store is None:
                continue
            cfg = self._syslog_cfg()
            try:
                store.prune(retention_days=int(cfg.get('retention_days', 0) or 0),
                            max_rows=int(cfg.get('max_rows', 0) or 0))
            except Exception:  # pylint: disable=broad-except
                pass
