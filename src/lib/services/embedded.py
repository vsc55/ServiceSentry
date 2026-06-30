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

    def __init__(self, host):
        self._host = host
        self._CONFIG_FILE = host._CONFIG_FILE

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
