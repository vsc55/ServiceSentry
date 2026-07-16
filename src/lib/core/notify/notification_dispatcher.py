#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backward-compatible entry point into the notification router.

Historically this module *was* the dispatcher; routing now lives in the core-owned,
web_admin-independent :class:`lib.core.notify.router.NotificationRouter`.  This shim
keeps the ``dispatch(wa, kind, ...)`` call sites working: it routes through the host's
own router (``wa._notify``) when present, or — for a legacy host that only exposes the
channel surface — runs the same logic against that surface directly.
"""

from __future__ import annotations

from lib.core.notify.router import run_dispatch


def dispatch(wa, kind: str, module: str = '', item: str = '',
             status: str = '', message: str = '',
             timestamp: str = '', channels=None,
             webhook_ids=None) -> dict[str, tuple[bool, str]]:
    """Send a notification to every enabled channel for the given event kind.

    By default the channels are chosen by the ``notifications`` routing matrix
    (``{channel}_on_{kind}``).  Pass *channels* (an iterable of channel names) to
    target an explicit set instead — used by the event-rules manager, where each
    rule picks its own channels.  *webhook_ids* optionally restricts the webhook
    channel to specific destinations (empty/None → every enabled webhook).

    Returns a dict mapping channel name → (ok, message) for each channel
    attempted. Channels not triggered are omitted.
    """
    surface = getattr(wa, '_notify', None) or wa
    return run_dispatch(surface, kind, module=module, item=item, status=status,
                        message=message, timestamp=timestamp,
                        channels=channels, webhook_ids=webhook_ids)
