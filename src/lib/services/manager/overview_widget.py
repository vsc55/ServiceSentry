#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widget the services control-plane owns (see :mod:`lib.core.overview.discovery`).

Self-describing: discovered by :func:`lib.core.overview.discovery.discover_overview_widgets`
and merged into the dashboard's widget definitions.  Summarises how many registered
services are running (ON) versus stopped/disabled/external (OFF), mirroring the count the
Services tab shows.  Data comes from ``services_stat`` below; the render resolves by ``id``
in the generic stat dispatcher (``_dwRenderStat``).
"""

from lib.services import discover_embedded_services


# A service counts as ON when it is running (its ``running`` flag is set, or its state is
# an "up" state); anything else (stopped/disabled/external-down) is OFF. Only the real
# embedded services are tallied — the read-only host views (worker/database/database_syslog)
# aren't services you start/stop, so they're excluded.
_ON_STATES = ('running', 'active', 'embedded')


def _is_on(entry: dict) -> bool:
    return bool(entry.get('running')) or entry.get('state') in _ON_STATES


def _services_stat(on: int, off: int) -> dict:
    """Standard stat content: value (total) + accent + declarative badges (style names +
    i18n keys/args — never HTML), painted by the generic ``_dwRenderStat``."""
    badges = [{'style': 'ok', 'icon': 'bi-play-circle-fill',
               'key': 'overview_services_on', 'args': [on]}]
    badges.append(
        {'style': 'muted', 'icon': 'bi-stop-circle', 'key': 'overview_services_off', 'args': [off]}
        if off else
        {'style': 'ok', 'icon': 'bi-check-circle', 'key': 'overview_services_all_on'})
    return {'value': on + off, 'accent': 'green' if not off else 'amber', 'badges': badges}


def services_stat(wa) -> dict:
    """Standard stat content for the ``services`` card: how many registered services are
    running versus stopped.  Fetched over AJAX by the generic stat renderer."""
    try:
        status = wa._services_status_dict() or {}
        keys = {m.get('key') for m in discover_embedded_services()}
        services = [e for k, e in status.items() if k in keys]
        on = sum(1 for e in services if _is_on(e))
        return _services_stat(on, len(services) - on)
    except Exception:  # pylint: disable=broad-except
        return _services_stat(0, 0)
