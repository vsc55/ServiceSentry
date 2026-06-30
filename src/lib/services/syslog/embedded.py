#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The syslog receiver running embedded in the web admin.

Composes the shared listener lifecycle (:class:`_SyslogMixin`) with the host
context (:class:`_EmbeddedBase`).  Owns its store/server/lock; binds the ports
only when this process hosts the listener (``SS_SYSLOG_EMBEDDED``).
"""

from __future__ import annotations

import os
import threading

from lib.debug import DebugLevel
from lib.services.embedded import _EmbeddedBase
from lib.services.syslog.manager import _SyslogMixin


def _embedded_listener_enabled() -> bool:
    """Whether the web admin should bind the syslog ports itself.

    Set ``SS_SYSLOG_EMBEDDED=0`` when the receiver runs as its own process /
    container (``main.py --syslog``): the web admin still shows the Syslog tab and
    serves the data from the shared DB, but does not bind the ports."""
    v = os.environ.get('SS_SYSLOG_EMBEDDED')
    if v is None:
        return True
    return v.strip().lower() not in ('0', 'false', 'no', 'off')


class EmbeddedSyslog(_EmbeddedBase, _SyslogMixin):

    def __init__(self, host):
        _EmbeddedBase.__init__(self, host)
        # The syslog stores are shared host infrastructure (the listener writes
        # them, the events worker + Syslog tab read them) — delegated below.  This
        # object owns only the listener server + its lock + the retention timer.
        self._syslog_server = None
        self._syslog_lock = threading.Lock()
        self._syslog_retention_stop = threading.Event()
        if self._syslog_store is not None:
            threading.Thread(target=self._retention_loop,
                             name='syslog-retention', daemon=True).start()

    # ── shared stores delegated to the host ───────────────────────────────────
    @property
    def _syslog_store(self):
        return getattr(self._host, '_syslog_store', None)

    @property
    def _syslog_drops_store(self):
        return getattr(self._host, '_syslog_drops_store', None)

    @property
    def _syslog_db_connector(self):
        return getattr(self._host, '_syslog_db_connector', None)

    # The web admin binds the ports only when this process hosts the listener.
    def _syslog_can_bind(self) -> bool:
        return _embedded_listener_enabled()

    def _syslog_autostart(self) -> bool:
        from lib.config.spec import cfg_get  # noqa: PLC0415
        return bool(cfg_get(self._config_section('syslog'), 'syslog|autostart'))

    def _retention_loop(self) -> None:
        while not self._syslog_retention_stop.wait(self.RETENTION_EVERY):
            self._syslog_prune_once()

    # ── boot ──────────────────────────────────────────────────────────────────
    def start_at_boot(self) -> None:
        """Bind the listener at boot only when enabled + autostart (a standalone
        --syslog process ignores autostart)."""
        if self._syslog_store is None:
            return
        if self._syslog_autostart():
            self._syslog_apply_config()
        else:
            self._dbg('> Syslog >> autostart off: listener not started at boot '
                      '(start it from the Services tab)', DebugLevel.info)

    # ── ServiceDescriptor surface (Services tab) ──────────────────────────────
    def status(self) -> dict:
        cfg = self._syslog_cfg()
        srv = self._syslog_server
        embedded = _embedded_listener_enabled()
        enabled = bool(cfg.get('enabled'))
        running = bool(srv and srv.running)
        if not embedded:
            state = 'external'
        elif not enabled:
            state = 'disabled'
        else:
            state = 'running' if running else 'stopped'
        udp = int(cfg.get('udp_port') or 0)
        tcp = int(cfg.get('tcp_port') or 0)
        tls = int(cfg.get('tls_port') or 0)
        count = self._syslog_store.count() if self._syslog_store else 0
        return {
            'state': state, 'running': running, 'enabled': enabled,
            'embedded': embedded, 'controllable': embedded and enabled,
            'udp_port': udp, 'tcp_port': tcp, 'tls_port': tls, 'count': count,
            'detail': [
                {'label_key': 'svc_mode',
                 'value_key': 'svc_mode_embedded' if embedded else 'svc_mode_container'},
                {'label_key': 'svc_ports',
                 'value': f"UDP {udp or '—'} · TCP {tcp or '—'} · TLS {tls or '—'}"},
                {'label_key': 'svc_messages', 'value': count},
            ],
        }

    def control(self, action: str) -> tuple:
        if not _embedded_listener_enabled():
            return False, 'not_controllable'
        if action == 'stop':
            self.listener_stop()
            self._audit_system('syslog_stopped', {})
            return True, ''
        if not bool(self._syslog_cfg().get('enabled')):
            return False, 'disabled'
        self._syslog_apply_config()
        ok = bool(self._syslog_server and self._syslog_server.running)
        if ok:
            self._audit_system('syslog_started', {})
        return ok, '' if ok else 'already'

    # ── used by routes/config + app shutdown ──────────────────────────────────
    def apply_config(self) -> list:
        return self._syslog_apply_config()

    @property
    def server(self):
        return self._syslog_server

    def listener_stop(self) -> None:
        """Stop just the listener (leave retention running)."""
        with self._syslog_lock:
            if self._syslog_server is not None:
                try:
                    self._syslog_server.stop()
                except Exception:  # pylint: disable=broad-except
                    pass
                self._syslog_server = None
                self._dbg("> Syslog >> embedded listener stopped", DebugLevel.info)

    def stop(self) -> None:
        """Full shutdown: stop the retention loop *and* the listener (app exit)."""
        self._syslog_retention_stop.set()
        self.listener_stop()

    def on_config_changed(self, changed) -> None:
        # Re-apply a *running* listener when any syslog setting changed (new ports/
        # allowlist, or stop it on disable).  A config edit never starts a stopped
        # listener — that is a Services-tab action.
        if any(p.startswith('syslog|') for p in changed) and self._syslog_server is not None:
            self._syslog_apply_config()


def make_embedded(host) -> EmbeddedSyslog:
    return EmbeddedSyslog(host)
