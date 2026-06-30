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
