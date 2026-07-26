#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The :class:`Service` descriptor — the contract every background service
registers under so the web admin can list and control it generically.

A descriptor is intentionally thin: it carries the *identity* a UI needs
(``key`` / ``label_key`` / ``icon``) plus two callables — ``status`` (a
serialisable snapshot) and, for the ones this process can operate, ``control``
(start/stop).  The per-service guards/audit live inside those callables, so the
registry never needs to know anything service-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class ServiceDescriptor:
    """One registered background service.

    * ``key`` — stable id used by the API and the control endpoint
      (``monitoring`` / ``syslog`` / ``events`` / ``worker`` / ``database`` …).
    * ``label_key`` / ``icon`` — i18n key + Bootstrap icon for the Services card.
    * ``status`` — ``() -> dict``: a serialisable snapshot. Should include
      ``state`` (running/stopped/disabled/external/…), ``controllable`` and a
      ``detail`` list of ``{'label_key': str, 'value': Any}`` rows the card shows.
    * ``control`` — ``(action: str) -> (ok: bool, reason: str)`` for ``start`` /
      ``stop``; ``None`` for read-only services (worker, database) that are
      reported but never operated from here.
    """
    key: str
    label_key: str
    icon: str
    status: Callable[[], dict]
    control: Optional[Callable[[str], tuple]] = None

    @property
    def controllable(self) -> bool:
        """Whether this process can start/stop the service (has a control fn).

        Note this is the *capability*; whether a control action is allowed right
        now (embedded gate, enabled flag) is decided inside ``control``."""
        return self.control is not None


class _StandaloneConfigMixin:
    """Config as a standalone worker consumes it.

    A worker process has no web layer to apply ``SS_*`` overrides and no config UI whose
    "saved vs env-locked" distinction could break, so env is layered over the WHOLE config
    here — this is the process's single consumption surface (autostart gates, notify
    channels, database targets…).

    One copy, not three: the monitoring, syslog and events services had this byte for byte,
    and a rule about *which configuration a process actually obeys* is a bad thing to state
    three times — the day one of them stops overlaying env, that worker silently ignores
    every SS_* the deployment sets.
    """

    def _read_config_file(self, _filename: str | None = None) -> dict:
        """Effective configuration (DB ← config.json) with ``SS_*`` env overlaid."""
        from lib.config.manager import overlay_all_env  # noqa: PLC0415
        return overlay_all_env(self._config_mgr.read() or {})
