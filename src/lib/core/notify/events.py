#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification-event registry — the core discovers *what* can be notified.

Symmetric to the channel registry (:mod:`lib.core.notify.registry`, the *endpoints*):
this is the registry of notification **sources/kinds** — the events services publish and
the notifications monitoring sensors forward.  Each ``kind`` (``down``/``recovery``/
``warn``/``syslog``/``event``/…) is the value carried in ``dispatch(kind=…)`` and the key
of the routing matrix ``notifications|{channel}_on_{kind}``.

Two ways an event enters the registry, mirroring the self-describing pattern already used
by ``permissions.py`` (``MODULE_PERMISSIONS``) and ``overview_widget.py`` (``OVERVIEW_WIDGETS``):

* **Discovered** — a domain that publishes notifications declares a ``notify_events``
  submodule with a ``NOTIFY_EVENTS`` list; :func:`discover_events` scans ``lib.core.*`` /
  ``lib.services.*`` / ``lib.providers.*`` and collects them.
* **Manual** — :func:`register_event` adds one programmatically (a source not tied to a
  discoverable package, or a future admin-defined event).

Descriptor shape (data-only; i18n labels live in the lang files, keyed by ``label_key``)::

    NOTIFY_EVENTS = [
        {
            'key':       'down',              # dispatch kind / matrix key
            'source':    'monitoring',        # owning domain (grouping in the UI)
            'label_key': 'notif_kind_down',   # i18n key for the human label
            'matrix':    True,                # participates in the {channel}_on_{key} matrix
            'order':     10,                  # position in the UI / matrix
        },
    ]

``matrix=False`` marks a source that does *not* auto-route through the matrix — e.g.
``event`` (event rules pick their channels explicitly), so it is a known source but has no
matrix columns.  This module only *knows* the events; wiring the config matrix and the
routing UI to it is a later phase.
"""

from __future__ import annotations

# Package roots scanned for a self-describing ``notify_events`` module.
_MODULE_ROOTS = ('lib.core', 'lib.services', 'lib.providers')

# Manually-registered events (key -> descriptor); merged on top of discovered ones.
_MANUAL: dict[str, dict] = {}


def _normalize(d) -> dict | None:
    """Coerce a raw descriptor into the canonical shape, or None if it has no key."""
    if not isinstance(d, dict) or not d.get('key'):
        return None
    return {
        'key':       str(d['key']),
        'source':    str(d.get('source', '')),
        'label_key': str(d.get('label_key', '')),
        'matrix':    bool(d.get('matrix', True)),   # generates {channel}_on_{key} config keys
        'ui':        bool(d.get('ui', True)),        # shown as a row in the routing-matrix UI
        'order':     d.get('order', 999),
    }


def register_event(descriptor: dict) -> None:
    """Manually register (or override) a notification event.  Merged over discovery."""
    ev = _normalize(descriptor)
    if ev:
        _MANUAL[ev['key']] = ev


def _scan(pkg_name: str) -> list[dict]:
    import importlib  # noqa: PLC0415
    import pkgutil    # noqa: PLC0415

    try:
        pkg = importlib.import_module(pkg_name)
    except Exception:  # pylint: disable=broad-except
        return []
    found: list[dict] = []
    for mod in pkgutil.iter_modules(pkg.__path__):
        if not mod.ispkg:
            continue
        try:
            sub = importlib.import_module(f'{pkg_name}.{mod.name}.notify_events')
        except Exception:  # pylint: disable=broad-except
            continue   # that domain publishes no notification events
        declared = getattr(sub, 'NOTIFY_EVENTS', None)
        if isinstance(declared, (list, tuple)):
            for raw in declared:
                ev = _normalize(raw)
                if ev:
                    found.append(ev)
    return found


def discover_events() -> list[dict]:
    """Every event a domain declares (core + services + providers), unordered/undeduped."""
    found: list[dict] = []
    for root in _MODULE_ROOTS:
        found.extend(_scan(root))
    return found


def events() -> list[dict]:
    """All notification events — discovered + manual (manual wins) — deduped by key,
    ordered by ``order`` then ``key``."""
    merged: dict[str, dict] = {}
    for ev in discover_events():
        merged.setdefault(ev['key'], ev)
    merged.update(_MANUAL)   # manual registrations win over discovery
    return sorted(merged.values(), key=lambda e: (e['order'], e['key']))


def matrix_events() -> list[dict]:
    """Events that auto-route through the ``{channel}_on_{key}`` matrix (``matrix=True``)."""
    return [e for e in events() if e['matrix']]


def ui_matrix_events() -> list[dict]:
    """Matrix events to show as rows in the routing-matrix UI (``matrix`` and ``ui``).
    Excludes matrix kinds kept only for config compatibility (``ui=False``), e.g. a legacy
    kind with no active dispatcher."""
    return [e for e in matrix_events() if e['ui']]


def event_keys() -> list[str]:
    return [e['key'] for e in events()]


def matrix_event_keys() -> list[str]:
    return [e['key'] for e in matrix_events()]
