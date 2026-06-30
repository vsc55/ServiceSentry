#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared, Flask-free syslog listener lifecycle.

The config merge, the (re)build/(re)start of the listener, the allowlist-drop
recording and the retention pruning are identical whether the receiver runs
embedded in the web admin or as the standalone ``--syslog`` service — so they live
here and are mixed into both (mirroring :mod:`lib.services.monitoring.manager` and
:mod:`lib.services.events.manager`).

Each host adds only its own bits: the web admin adds the ``SS_SYSLOG_EMBEDDED``
gate (``_syslog_can_bind``), ``autostart`` and the boot wiring; the standalone
service adds the cross-process config watch and the blocking run loop.

Required from the host: ``_config_section`` (effective config), ``_dbg``,
``_syslog_store`` / ``_syslog_drops_store`` (DB stores) and ``_syslog_server`` /
``_syslog_lock`` (listener state).  Optional: ``_host_override`` / ``_port_override``
(the ``--syslog-host`` / ``--syslog-port`` CLI overrides).
"""

from __future__ import annotations

import time

from lib.debug import DebugLevel
from lib.services.syslog.server import build_server


class _SyslogMixin:
    """Shared syslog receiver lifecycle (no Flask, no process-management)."""

    RETENTION_EVERY = 300       # prune sweep interval (s)

    # ── overridable gate ──────────────────────────────────────────────────────
    def _syslog_can_bind(self) -> bool:
        """Whether THIS process should bind the ports.  Standalone: always.  The
        web admin overrides this to honour ``SS_SYSLOG_EMBEDDED`` (0 = a dedicated
        container owns the ports; the panel only serves stored data)."""
        return True

    # ── config ────────────────────────────────────────────────────────────────
    def _syslog_cfg(self) -> dict:
        """Effective ``syslog`` config with registry defaults merged underneath the
        saved values (defaults are lazy, so a config with only ``enabled`` saved
        would otherwise lack the ports).  CLI overrides win when present."""
        from lib.config.spec import section_defaults  # noqa: PLC0415
        saved = self._config_section('syslog') or {}
        # A null (blank) value means "use the registry default" → skip nulls so the
        # merged default underneath wins.
        cfg = {**section_defaults('syslog'),
               **{k: v for k, v in saved.items() if v is not None}}
        host_override = getattr(self, '_host_override', None)
        port_override = getattr(self, '_port_override', None)
        if host_override:
            cfg['bind_host'] = host_override
        if port_override is not None:
            cfg['udp_port'] = port_override
            cfg['tcp_port'] = port_override
        return cfg

    @staticmethod
    def _config_summary(cfg: dict) -> str:
        """One-line, secret-free description of the active listener config."""
        ports = []
        for label, key in (('udp', 'udp_port'), ('tcp', 'tcp_port'), ('tls', 'tls_port')):
            try:
                p = int(cfg.get(key) or 0)
            except (TypeError, ValueError):
                p = 0
            if p:
                ports.append(f'{label}:{p}')
        allow = str(cfg.get('allowed_sources') or '').strip()
        return (f"bind={cfg.get('bind_host') or '0.0.0.0'} "
                f"transports=[{', '.join(ports) or 'none'}] "
                f"allow={allow or 'any'} "
                f"retention_days={cfg.get('retention_days', 0) or 0} "
                f"max_rows={cfg.get('max_rows', 0) or 0}")

    # ── (re)build / (re)start ───────────────────────────────────────────────────
    def _syslog_apply_config(self) -> list[str]:
        """(Re)build and (re)start the listener from the current config.

        Returns the list of bind problems (empty on success, when disabled, or when
        this process does not bind the ports)."""
        with self._syslog_lock:
            if self._syslog_server is not None:
                try:
                    self._syslog_server.stop()
                except Exception:  # pylint: disable=broad-except
                    pass
                self._syslog_server = None
            cfg = self._syslog_cfg()
            if not cfg.get('enabled'):
                self._dbg('> Syslog >> disabled in config; listener not started',
                          DebugLevel.warning)
                return []
            if getattr(self, '_syslog_store', None) is None:
                return []
            if not self._syslog_can_bind():
                self._dbg('> Syslog >> listener not bound here (a dedicated process '
                          'owns the ports); serving stored data only', DebugLevel.info)
                return []
            self._dbg(f'> Syslog >> starting listener: {self._config_summary(cfg)}',
                      DebugLevel.info)
            srv = build_server(
                cfg, sink=self._syslog_store.add_many,
                # No per-message hook: rule evaluation is decoupled — the event
                # worker drains stored rows by cursor, so a flood of messages never
                # blocks the listener on a slow notification channel.
                dbg=lambda m: self._dbg(m, DebugLevel.info),
                dbg_warn=lambda m: self._dbg(m, DebugLevel.warning),
                on_drop=self._syslog_record_drop)
            problems = srv.start()
            for p in problems:
                self._dbg(f'> Syslog >> bind problem: {p}', DebugLevel.error)
            if srv.running:
                self._dbg('> Syslog >> listener started', DebugLevel.info)
            else:
                self._dbg('> Syslog >> listener did NOT start (no transport bound)',
                          DebugLevel.error)
            self._syslog_server = srv
            return problems

    # ── allowlist-drop tally + retention ────────────────────────────────────────
    def _syslog_record_drop(self, source: str, transport: str, delta: int) -> None:
        """Persist allowlist drops (shared DB → visible in the web Syslog tab)."""
        store = getattr(self, '_syslog_drops_store', None)
        if store is not None:
            try:
                store.record(source, transport, delta, time.time())
            except Exception:  # pylint: disable=broad-except
                pass

    # ── Imperative commands (reload / prune) ───────────────────────────────────
    def _apply_command(self, action: str, args: dict | None = None) -> tuple[bool, str]:
        """Execute a one-shot command from the service-command queue on the
        instance hosting the listener (embedded here or a remote receiver)."""
        if action == 'reload':
            mgr = getattr(self, '_config_mgr', None)
            if mgr is not None:
                try:
                    mgr.invalidate()
                except Exception:  # pylint: disable=broad-except
                    pass
            problems = self._syslog_apply_config()
            return (not problems), ('listener reloaded' if not problems
                                    else '; '.join(problems))
        if action in ('prune', 'clear_status'):
            self._syslog_prune_once()
            return True, 'retention sweep run'
        return False, 'unknown_action'

    def _syslog_prune_once(self) -> None:
        """One retention sweep (time + row caps).  Each host drives it from its own
        loop/timer."""
        store = getattr(self, '_syslog_store', None)
        if store is None:
            return
        cfg = self._syslog_cfg()
        try:
            deleted = store.prune(retention_days=int(cfg.get('retention_days', 0) or 0),
                                  max_rows=int(cfg.get('max_rows', 0) or 0))
            if deleted:
                self._dbg(f'> Syslog >> retention pruned {deleted} message(s)',
                          DebugLevel.info)
        except Exception as exc:  # pylint: disable=broad-except
            self._dbg(f'> Syslog >> retention sweep failed: {exc}', DebugLevel.error)
