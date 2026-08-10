#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""When an automatic copy is due, and which old ones go.

Split from the thread that runs it because "is it time?" and "how do I run a thread" are two
different problems and only one of them is worth testing. Everything here is a pure function of
(settings, clock, what exists on disk) — no database, no disk, no Flask.

**An interval, not a cron expression.** "Every N hours" instead of "at 03:00 daily", and the
difference matters more than it looks: a panel that is off at 03:00 must still take its daily
copy when it comes back at 09:00. A wall-clock rule is false 1439 minutes out of 1440, so it
needs a tick every minute to catch its moment and misses the window entirely if the process was
down for it. An interval asks "how long since the last one", which stays true until a copy is
taken and is answered just as well by a tick every ten minutes. A missed window is the case a
backup exists for.

The cost is drift: copies land a tick later each time rather than on the hour. That is the side
to be wrong on — a copy at 03:07 is a copy.

**"Since the last one" is read from the files, not remembered.** Nothing is written down to be
lost on restart, and no state can disagree with what is actually on disk: an operator who
deletes the newest copy gets another one at the next tick, which is what deleting it meant.
"""

from __future__ import annotations

# Automatic copies carry this prefix so retention can tell them from the ones a person made.
# Recognised by NAME rather than recorded in a table: the files are the truth (somebody can
# copy one in, or delete one with the panel stopped), and a name that says what made it
# survives being moved to another machine.
AUTO_PREFIX = 'auto-'


def auto_name(now) -> str:
    """The name for the copy taken at *now* (a ``datetime``)."""
    return f'{AUTO_PREFIX}{now.strftime("%Y%m%d-%H%M%S")}'


def is_auto(name: str) -> bool:
    return str(name or '').startswith(AUTO_PREFIX)


def is_due(every_hours, now_ts: float, last_ts: float | None) -> bool:
    """Is an automatic copy due?

    *every_hours* ``0`` (or anything unreadable) is OFF — this reads a config field an operator
    types into, and a typo must not turn the scheduler into a loop that copies every tick.

    With no copy yet the answer is YES: an install that has never taken one is the install that
    most needs it, and waiting a full interval to start would hide a misconfigured path for a
    day.
    """
    try:
        hours = float(every_hours)
    except (TypeError, ValueError):
        return False
    if hours <= 0:
        return False
    if last_ts is None:
        return True
    return (now_ts - float(last_ts)) >= hours * 3600.0


def last_auto_ts(backups: list) -> float | None:
    """When the newest AUTOMATIC copy was taken, from what :func:`service.list_backups` returns.

    Hand-made copies are ignored deliberately: taking one before an upgrade must not push the
    scheduled one back a whole interval — they answer different questions and only one of them
    is a promise.
    """
    stamps = [b.get('mtime') for b in (backups or [])
              if is_auto(b.get('name')) and b.get('mtime')]
    return max(stamps) if stamps else None


def prune(backups: list, keep) -> list:
    """The names of the automatic copies to delete, oldest first.

    Retention is not decoration. Without it the folder grows until the disk is full, and a full
    disk stops the panel — a backup feature that takes the install down is worse than none.

    ``keep <= 0`` deletes NOTHING: an operator who prunes elsewhere must be able to say so, and
    reading zero as "delete them all" is the reading that loses data. Hand-made copies are never
    touched: a copy somebody took before an upgrade is not something a counter gets to throw
    away.
    """
    try:
        k = int(keep)
    except (TypeError, ValueError):
        return []
    if k <= 0:
        return []
    autos = sorted((b for b in (backups or []) if is_auto(b.get('name'))),
                   key=lambda b: b.get('mtime') or 0, reverse=True)
    return [b['name'] for b in autos[k:]]
