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
import time

from lib.debug import DebugLevel
from lib.syslog.server import build_server

_RETENTION_EVERY = 300          # prune sweep interval (s)


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
        connector = getattr(self, '_db_connector', None)
        if connector is None:
            return
        try:
            from lib.db import build_syslog_connector  # noqa: PLC0415
            from lib.stores.syslog import SyslogStore, SyslogDropsStore  # noqa: PLC0415
            from lib.config.manager import overlay_section_env  # noqa: PLC0415
            var = getattr(self, '_var_dir', None) or getattr(self, '_config_dir', '')
            sdb = overlay_section_env('syslog_db', self._config_section('syslog_db'))
            self._syslog_db_connector = build_syslog_connector(
                sdb, main_connector=connector,
                default_sqlite_path=os.path.join(var, 'syslog.db'))
            self._syslog_store = SyslogStore(self._syslog_db_connector)
            self._syslog_drops_store = SyslogDropsStore(self._syslog_db_connector)
        except Exception:  # pylint: disable=broad-except
            return
        # autostart gates only the boot start: enabled + autostart ⇒ bind now;
        # enabled + autostart=off ⇒ boot stopped but startable from the Services
        # tab.  A standalone --syslog process ignores autostart (handled there).
        if self._syslog_autostart():
            self._syslog_apply_config()
        else:
            self._dbg('> Syslog >> autostart off: listener not started at boot '
                      '(start it from the Services tab)', DebugLevel.info)
        threading.Thread(target=self._syslog_retention_loop,
                         name='syslog-retention', daemon=True).start()

    def _syslog_autostart(self) -> bool:
        """Whether the embedded listener starts at web-admin boot (master ``enabled``
        gates usability; this gates the automatic launch)."""
        from lib.config.spec import cfg_get  # noqa: PLC0415
        return bool(cfg_get(self._config_section('syslog'), 'syslog|autostart'))

    def _syslog_cfg(self) -> dict:
        # Merge registry defaults underneath the saved values: defaults are lazy
        # (not stored), so a config where only ``enabled`` was toggled would
        # otherwise lack the ports and the listener would bind nothing.
        from lib.config.spec import section_defaults  # noqa: PLC0415
        saved = self._config_section('syslog') or {}
        # A null (blank) value means "use the registry default", so it must not
        # override the default merged underneath — skip nulls.
        return {**section_defaults('syslog'),
                **{k: v for k, v in saved.items() if v is not None}}

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
                # No per-message hook: event-rule evaluation is decoupled — the
                # background event worker drains stored rows by cursor, so a flood of
                # messages never blocks the listener on a slow notification channel.
                dbg=lambda m: self._dbg(m, DebugLevel.info),
                dbg_warn=lambda m: self._dbg(m, DebugLevel.warning),
                on_drop=self._syslog_record_drop,
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

    # ── dropped-sender tally (allowlist) ─────────────────────────────────────────
    def _syslog_record_drop(self, source: str, transport: str, delta: int) -> None:
        """Persist allowlist drops so the Syslog tab can show what's being dropped."""
        store = getattr(self, '_syslog_drops_store', None)
        if store is not None:
            try:
                store.record(source, transport, delta, time.time())
            except Exception:  # pylint: disable=broad-except
                pass

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
