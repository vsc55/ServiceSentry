#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What each audit event MEANS, declared by the package that writes it.

The audit screen paints one badge per row, and it is the only thing a glance down two hundred
entries gives you. That badge used to be worked out from the event NAME — a rule matching
``deleted``/``revoked`` plus a handful of names written out by hand — which had two problems,
one visible and one not:

* seven events that erase data and fifteen that are failures rendered neutral grey, because
  nobody had remembered to add them; deleting ONE audit entry showed red while emptying the
  WHOLE audit log showed grey;
* and even once the word lists were widened, the colour still depended on the noun somebody
  chose when they named the event. ``purge_done`` would have passed unnoticed; ``rule_failed``
  would have gone red for a rule that merely reported "no match".

So the severity is DECLARED, beside the code that emits the event:

.. code-block:: python

    # lib/services/ipban/manifest.py
    AUDIT_EVENTS = [
        {'key': 'ip_banned',             'severity': 'warning'},
        {'key': 'ipban_history_cleared', 'severity': 'danger'},
    ]

Same shape and same discovery as ``NOTIFY_EVENTS`` and ``MODULE_PERMISSIONS``: a package that
adds an event declares it in its own ``manifest.py``, and nothing central has to be edited.
:func:`audit_severity` folds them into ``{key: severity}`` for the frontend.

The LABELS stay in ``lib.i18n`` (``audit_events``) — those are translations, and a severity is
not: duplicating it per language would let two languages disagree about how alarming something
is.

Severities are the four Bootstrap tones the screen already uses:

``danger``   something was destroyed, or something failed
``warning``  worth noticing — a session ended, a service stopped, an IP was banned
``success``  something was created or came up
``info``     a value changed
``muted``    routine, no colour
"""

from __future__ import annotations

_MODULE_ROOTS = ('lib.core', 'lib.services', 'lib.providers')

VALID_SEVERITIES = frozenset({'danger', 'warning', 'success', 'info', 'muted'})


def discover_audit_events() -> list[dict]:
    """Every declared audit event, from each package's ``manifest.py``."""
    from lib.discovery import scan_flat  # noqa: PLC0415
    out: list[dict] = []
    for raw in scan_flat('AUDIT_EVENTS', roots=_MODULE_ROOTS):
        ev = _normalize(raw)
        if ev:
            out.append(ev)
    return out


def _normalize(raw) -> dict | None:
    """Keep a declaration only if it names an event and a severity we know how to paint.

    An unknown severity is dropped rather than passed through: it would reach the browser as
    a CSS class that does not exist, and the row would render with no badge at all — the one
    outcome worse than the wrong colour, because it looks like the event carries no weight.
    """
    if not isinstance(raw, dict):
        return None
    key = str(raw.get('key') or '').strip()
    severity = str(raw.get('severity') or '').strip()
    if not key or severity not in VALID_SEVERITIES:
        return None
    return {'key': key, 'severity': severity}


def audit_severity() -> dict:
    """``{event_key: severity}`` — what the frontend needs, and nothing else."""
    return {ev['key']: ev['severity'] for ev in discover_audit_events()}
