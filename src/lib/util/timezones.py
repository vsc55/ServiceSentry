#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The time zones this installation can interpret — which may be none.

Its own module, and not a helper of whichever screen asked first: a site has a time zone, and so
will a scheduled report, a maintenance window and an account. The first caller is the worst
possible reason to decide where something lives.

**Empty is a real answer.** :func:`zoneinfo.available_timezones` reads the system's tz database,
and there are two ordinary ways to have none: Windows without the ``tzdata`` package, and a
container slimmed to the bone. Neither is a failure and neither should raise — the caller is
told there are none and decides what to do, which for the web UI is to fall back to the list the
browser ships.

Names and not offsets, always. ``+01:00`` stops being true twice a year; ``Europe/Madrid`` does
not.
"""

from __future__ import annotations

import functools


@functools.lru_cache(maxsize=1)
def available() -> tuple:
    """Every zone name this installation knows, sorted — possibly empty.

    Cached: the set does not change while the process is running (it is the tz database on
    disk), it is six hundred strings, and the screens that ask are the ones drawing a form.
    """
    try:
        import zoneinfo                         # noqa: PLC0415  (stdlib, 3.9+)
        return tuple(sorted(zoneinfo.available_timezones()))
    except Exception:                           # pylint: disable=broad-except
        return ()


def known(name: str) -> bool:
    """Whether *name* is one this installation can resolve.

    With no tz database nothing is known, and that is deliberately NOT "everything is invalid":
    callers that validate must decide for themselves whether an installation that cannot check
    should reject what it cannot check. Storing a name a slimmed container cannot resolve is
    usually better than losing it — the container gets `tzdata` later, the typed value does not
    come back.
    """
    return str(name or '') in available()
