#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-describing Overview widgets — discovery for the built-in (core/service) widgets.

Each core domain (``lib.core.*``) and service (``lib.services.*``) declares the Overview
dashboard widgets it owns in its ``overview_widget`` submodule, as an ``OVERVIEW_WIDGETS``
list.  :func:`discover_overview_widgets` collects them — the same self-describing pattern
as ``permissions.py`` (``MODULE_PERMISSIONS``) — so a domain/service contributes a widget
by declaring it, without editing the Overview frontend's hardcoded ``_DW_DEFS``.

Descriptor shape (data-only; i18n labels stay in the lang files, keyed by ``label_key``)::

    OVERVIEW_WIDGETS = [
        {
            'id':        'users',              # unique widget id (matches its render fn)
            'icon':      'bi-person',          # Bootstrap-icon class
            'label_key': 'overview_users',     # i18n key for the title
            'cols':      2,                    # default column span (of 12)
            'h':         'auto',               # default height ('auto' or px int)
            'has_h':     False,                # allow the user to resize height
            'multi':     False,                # allow several instances (scoped)
            'order':     30,                   # position in the default layout
            'perms':     {'any': ['users_view']},  # ANY-of + optional 'prefix': ['server.']
            'nav':       {'tab': 'tab-users'},     # click-through target (tab + optional 'sub')
        },
    ]

``perms`` is a small declarative permission expression evaluated in the frontend:
``any`` = show if the user holds ANY of these flags; ``prefix`` = OR any flag starting
with one of these prefixes (e.g. per-server ``server.<uid>.view``).
"""

from __future__ import annotations

# Package roots scanned for a self-describing ``overview_widget`` module.
_MODULE_ROOTS = ('lib.core', 'lib.services')


def discover_overview_widgets() -> list[dict]:
    """Every built-in widget descriptor (core domains + services), ordered by ``order``.

    Descriptors live in each package's ``manifest.py`` (``OVERVIEW_WIDGETS``, importing its
    own data providers); the shared scanner (:mod:`lib.discovery`) collects them."""
    from lib.discovery import scan_flat  # noqa: PLC0415
    found = [w for w in scan_flat('OVERVIEW_WIDGETS', roots=_MODULE_ROOTS)
             if isinstance(w, dict) and w.get('id')]
    found.sort(key=lambda w: w.get('order', 999))
    return found


def discover_widget_rows() -> dict:
    """``{widget_id: fn(wa, f)}`` — the server-side row providers for data-driven AJAX
    **table** widgets, taken from each descriptor's ``rows`` callable (a widget owns
    everything about itself in its one descriptor).  Each provider returns its rows already
    filtered by *f*; served by the generic ``/api/v1/overview/widget/<id>`` endpoint."""
    out: dict = {}
    for w in discover_overview_widgets():
        fn = w.get('rows')
        if callable(fn) and w.get('id'):
            out[w['id']] = fn
    return out


def discover_widget_content() -> dict:
    """``{widget_id: fn(wa)}`` — the server-side provider for every data-driven AJAX widget
    that is not a table: a **stat** card declares it as ``stat``, anything else as
    ``content``.  Whatever it returns is handed to the frontend under ``{content}`` by the
    generic ``/api/v1/overview/widget/<id>`` endpoint (tables get ``{rows}`` instead), so
    every widget fetches its own data independently.

    Two names for one thing on purpose, and the shape is the reason: a stat card's provider
    returns the ONE shape a stat card knows (``{value, accent?, icon?, badges}``) and ten
    descriptors already say ``stat``, while a map's returns whatever a map needs.  Calling
    the second one ``stat`` would be a function named after a card it does not draw."""
    out: dict = {}
    for w in discover_overview_widgets():
        fn = w.get('content') or w.get('stat')
        if callable(fn) and w.get('id'):
            out[w['id']] = fn
    return out


def discover_overview_widgets_public() -> list[dict]:
    """Descriptors with non-JSON-safe values (e.g. the ``rows`` callable) stripped, for
    serialising to the frontend.  The frontend never needs the server-side row provider —
    it fetches rows over AJAX — so callables are dropped here, not authored separately."""
    return [
        {k: v for k, v in w.items() if not callable(v)}
        for w in discover_overview_widgets()
    ]
