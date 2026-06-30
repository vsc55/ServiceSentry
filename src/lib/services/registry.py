#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The :class:`ServiceRegistry` — the central controller for background services.

The web admin builds one registry at start-up and registers a descriptor for every
service it knows about (monitoring / syslog / events) plus the read-only views
(worker / database).  The Services tab, the control endpoint and the start-up log
then iterate the registry instead of hard-coding one branch per service — so adding
a service (or a module-contributed one) is a single ``register()`` call.
"""

from __future__ import annotations

from typing import Iterator, Optional

from lib.services.base import ServiceDescriptor


class ServiceRegistry:
    """An ordered collection of :class:`ServiceDescriptor`, keyed by ``key``."""

    def __init__(self) -> None:
        self._services: list[ServiceDescriptor] = []

    def register(self, descriptor: ServiceDescriptor) -> ServiceDescriptor:
        """Add a service. A later registration with the same key replaces the
        earlier one (so an override is possible)."""
        self._services = [s for s in self._services if s.key != descriptor.key]
        self._services.append(descriptor)
        return descriptor

    def get(self, key: str) -> Optional[ServiceDescriptor]:
        return next((s for s in self._services if s.key == key), None)

    def __iter__(self) -> Iterator[ServiceDescriptor]:
        return iter(self._services)

    def __len__(self) -> int:
        return len(self._services)

    def keys(self) -> list[str]:
        return [s.key for s in self._services]

    def controllable_keys(self) -> set[str]:
        """Keys whose service this process can operate (have a control fn)."""
        return {s.key for s in self._services if s.controllable}
