#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background services subsystem.

Every long-running ServiceSentry service lives here as a self-contained package
that can run **embedded** in the web admin or **standalone** as its own process /
container:

* :mod:`lib.services.monitoring` — the service monitor: the check engine
  (:class:`Monitor`), the scheduler mixin and the standalone ``--monitor`` service.
* :mod:`lib.services.syslog` — the syslog receiver: RFC 3164/5424 parser, the
  UDP/TCP(+TLS) listener and the standalone ``--syslog`` service.
* :mod:`lib.services.events` — the decoupled event processor: the rule-evaluation
  manager and the standalone ``--events`` service.

``base`` defines the :class:`Service` contract and ``registry`` the
:class:`ServiceRegistry` that the web admin's Services tab iterates to render and
control every service generically (no per-service branches).

Each service package self-describes for the web admin by exposing an
``EMBEDDED_SERVICE`` dict; :func:`discover_embedded_services` finds them, so a new
service appears in the Services tab just by dropping a package here (no edit to the
web admin) — the host only has to provide the embedded ``_service_<key>_status`` /
``_control_<key>`` methods by convention.
"""

from __future__ import annotations


def discover_embedded_services() -> list[dict]:
    """Discover every service package's ``EMBEDDED_SERVICE`` self-description.

    Scans the sub-packages of :mod:`lib.services` (each long-running service is a
    package) and collects the ``EMBEDDED_SERVICE`` dict any of them exposes,
    returning them ordered by the optional ``order`` key.  A package without one is
    simply skipped, and an import error in one package never breaks the rest.
    """
    import importlib  # noqa: PLC0415
    import pkgutil    # noqa: PLC0415

    found: list[dict] = []
    for mod in pkgutil.iter_modules(__path__):
        if not mod.ispkg:                       # base.py / registry.py are modules
            continue
        try:
            sub = importlib.import_module(f'{__name__}.{mod.name}')
        except Exception:  # pylint: disable=broad-except
            continue
        meta = getattr(sub, 'EMBEDDED_SERVICE', None)
        if isinstance(meta, dict) and meta.get('key'):
            found.append(meta)
    found.sort(key=lambda m: m.get('order', 999))
    return found


def build_embedded_services(host) -> dict:
    """Instantiate every discovered service's ``Embedded<X>`` object, bound to the
    *host* WebAdmin (composition).  Returns ``{key: object}`` in discovery order.

    Each service package exposes ``embedded.make_embedded(host)``; the object owns
    its runtime (threads/server/scheduler) and provides ``status`` / ``control`` /
    ``start_at_boot``.  A package without an ``embedded`` module is skipped."""
    import importlib  # noqa: PLC0415

    out: dict = {}
    for meta in discover_embedded_services():
        key = meta['key']
        try:
            mod = importlib.import_module(f'{__name__}.{key}.embedded')
            out[key] = mod.make_embedded(host)
        except Exception:  # pylint: disable=broad-except
            continue
    return out

