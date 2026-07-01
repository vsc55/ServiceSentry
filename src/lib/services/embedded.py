#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Embedded-service composition base.

A service runs **embedded** in the web admin by *composing* its shared lifecycle
mixin (``lib.services.<svc>.manager``) with a thin context that delegates config /
debug / stores to the host WebAdmin — so the very same mixin code runs unchanged
whether the service is standalone (its own process) or embedded (here).

The web admin holds one ``Embedded<X>`` object per discovered service
(composition, not inheritance); each exposes the :class:`ServiceDescriptor`
callables ``status`` / ``control`` and a ``start_at_boot`` that encapsulates its
own gating — so the WebAdmin neither *is* the services nor knows their per-service
rules.  Adding a service = a package with its ``Embedded<X>`` + ``EMBEDDED_SERVICE``
metadata; the host provides nothing service-specific.
"""

from __future__ import annotations

from lib.debug import DebugLevel
from lib.services.heartbeat import _HeartbeatMixin


class _EmbeddedBase(_HeartbeatMixin):
    """Delegate the context surface the service mixins expect to the host."""

    _HB_MODE = 'embedded'

    # Desired-state knob a dedicated container reconciles, declared by services that
    # can be operated while a separate process owns them: ``(section|field, on, off)``.
    # ``None`` → not externally controllable (only when hosted here).
    _EXTERNAL_KNOB: tuple | None = None

    def __init__(self, host):
        self._host = host
        self._CONFIG_FILE = host._CONFIG_FILE

    # ── external control (a dedicated container owns the running service) ─────
    def _control_external(self, action: str) -> tuple:
        """Start/stop this service while a dedicated container owns it, by editing
        the shared desired-state it reconciles — the same knob the Config tab writes,
        pushed with a poke so the remote converges now instead of at its next watch
        tick.  ``action`` is ``start``/``stop``.

        Returns ``(True, '')``: writing desired-state is authoritative even when no
        remote instance is currently reachable (the periodic reconcile catches up).
        ``(False, 'not_controllable')`` for a service that declares no knob."""
        knob = self._EXTERNAL_KNOB
        if knob is None:
            return False, 'not_controllable'
        path, on_val, off_val = knob
        section, field = path.split('|', 1)
        value = on_val if action == 'start' else off_val
        host = self._host
        # Round-trip the FULL effective config with only this one field changed.
        # ConfigManager.write treats its argument as the complete config and prunes
        # every DB row absent from it — so a partial dict here would wipe all other
        # settings (monitoring/events enabled, syslog ports, …).
        cfg = host._read_config_file(self._CONFIG_FILE) or {}
        section_cfg = dict(cfg.get(section) or {})
        section_cfg[field] = value
        cfg = {**cfg, section: section_cfg}
        host._write_config(cfg)
        host._invalidate_config_cache()
        # Let every embedded twin react (a no-op for a service a container owns) and
        # push the change to the remote instances so it applies immediately.
        for svc in getattr(host, '_embedded_services', {}).values():
            try:
                svc.on_config_changed({path})
            except Exception:  # pylint: disable=broad-except
                pass
        poke = getattr(host, '_poke_service_instances', None)
        if poke is not None and self._HB_KEY:
            poke(self._HB_KEY)
        self._audit_system('service_started' if action == 'start' else 'service_stopped',
                           {'service': self._HB_KEY, path: value})
        return True, ''

    # ── config / debug / dispatch context ─────────────────────────────────────
    def _read_config_file(self, filename=None):
        return self._host._read_config_file(filename)

    def _config_section(self, name):
        return self._host._config_section(name)

    def _load_webhooks(self, *, decrypt: bool = True):
        return self._host._load_webhooks(decrypt=decrypt)

    def _dbg(self, msg, level: DebugLevel = DebugLevel.debug):
        return self._host._dbg(msg, level)

    def _audit_system(self, event, detail=None):
        fn = getattr(self._host, '_audit_system', None)
        if fn is not None:
            return fn(event, detail or {})
        return None

    # ── paths / shared collaborators (read live from the host) ────────────────
    @property
    def _config_dir(self):
        return getattr(self._host, '_config_dir', None)

    @property
    def _var_dir(self):
        return getattr(self._host, '_var_dir', None)

    @property
    def _modules_dir(self):
        return getattr(self._host, '_modules_dir', None)

    @property
    def _db_connector(self):
        return getattr(self._host, '_db_connector', None)

    @property
    def _history(self):
        return getattr(self._host, '_history', None)

    @property
    def _service_instances_store(self):
        # Observed-state registry the heartbeat mixin writes to (lives on the host).
        return getattr(self._host, '_service_instances_store', None)

    @property
    def _service_commands_store(self):
        # Imperative command queue the heartbeat loop drains (lives on the host).
        return getattr(self._host, '_service_commands_store', None)

    @property
    def _service_leader_store(self):
        # Leader lease for single-owner services (lives on the host).
        return getattr(self._host, '_service_leader_store', None)

    @property
    def _check_lock(self):
        return self._host._check_lock

    @property
    def _env_override_values(self):
        return getattr(self._host, '_env_override_values', {})

    @property
    def _env_locked(self):
        return getattr(self._host, '_env_locked', frozenset())

    # ── react to a config save (overridden per service; default: nothing) ─────
    def on_config_changed(self, changed) -> None:
        """Called after a config save with *changed* = the set of edited
        ``section|field`` paths, so a service can reload/stop itself live.  The
        WebAdmin just iterates every service; each owns its own rule.  Default: no
        reaction.  (Starting a stopped service is never automatic — that is a
        Services-tab / boot-autostart action.)"""
        return None
