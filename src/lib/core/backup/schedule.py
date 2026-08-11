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

import re

# Automatic copies carry this prefix so retention can tell them from the ones a person made.
# Recognised by NAME rather than recorded in a table: the files are the truth (somebody can
# copy one in, or delete one with the panel stopped), and a name that says what made it
# survives being moved to another machine.
AUTO_PREFIX = 'auto-'


# A slug is what a task's name becomes inside a file name. Anything outside this cannot be one,
# which is what keeps a task called "../etc" from steering where its copies are written — the
# same rule the backup name itself follows, for the same reason.
_SLUG_RE = re.compile(r'[^A-Za-z0-9_-]+')


def task_slug(name: str) -> str:
    """A task's name, reduced to what may appear in a file name.

    Empty in, empty out — and an empty slug produces the old unscoped `auto-<date>` name, which
    is exactly what the copies taken before tasks existed are called. Retention has to keep
    recognising those or the upgrade would orphan every copy already on disk.
    """
    return _SLUG_RE.sub('-', str(name or '').strip()).strip('-')[:32].lower()


def auto_name(now, task: str = '') -> str:
    """The name for the copy *task* takes at *now* (a ``datetime``).

    The task is IN the name because retention counts per task: a daily task and a monthly one
    keep different numbers of copies, and a counter that could not tell them apart would have
    the daily one pruning the monthly one's — deleting exactly the copies that took a month to
    become worth having.
    """
    slug = task_slug(task)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    return f'{AUTO_PREFIX}{slug}-{stamp}' if slug else f'{AUTO_PREFIX}{stamp}'


def is_auto(name: str, task: str | None = None) -> bool:
    """Was *name* produced by the scheduler — and, when *task* is given, by that task?

    ``task=None`` means "by any of them", which is what the UI asks to badge a row.
    """
    n = str(name or '')
    if not n.startswith(AUTO_PREFIX):
        return False
    if task is None:
        return True
    slug = task_slug(task)
    if not slug:
        # The unscoped name from before tasks existed: `auto-<date>`, where the character after
        # the prefix is a digit. A task WITH a slug must not claim those.
        rest = n[len(AUTO_PREFIX):]
        return bool(rest) and rest[0].isdigit()
    return n.startswith(f'{AUTO_PREFIX}{slug}-')


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


def last_auto_ts(backups: list, task: str | None = None) -> float | None:
    """When the newest AUTOMATIC copy was taken, from what :func:`service.list_backups` returns.

    Hand-made copies are ignored deliberately: taking one before an upgrade must not push the
    scheduled one back a whole interval — they answer different questions and only one of them
    is a promise.
    """
    stamps = [b.get('mtime') for b in (backups or [])
              if is_auto(b.get('name'), task) and b.get('mtime')]
    return max(stamps) if stamps else None


def prune(backups: list, keep, task: str | None = None) -> list:
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
    autos = sorted((b for b in (backups or []) if is_auto(b.get('name'), task)),
                   key=lambda b: b.get('mtime') or 0, reverse=True)
    # Oldest first, as the docstring says and the code did not: the order does not change WHAT
    # is deleted, but a run interrupted half way should have freed the least useful copies
    # rather than the ones nearest to being the last good one.
    return [b['name'] for b in reversed(autos[k:])]


# ── A calendar, with the catch-up an interval gave for free ──────────────────
#
# "Every N hours" answers "how long since the last one", which survives the panel being down
# but drifts and cannot say "Mondays at 03:00". A wall-clock rule says exactly that and, asked
# naively ("is it 03:00 now?"), is false 1439 minutes out of 1440 and misses its window
# entirely if the process was not up for it.
#
# So it is asked the other way round: what was the most recent moment this task was DUE, and
# has a copy been taken since? That is true from the moment the window passes until a copy is
# taken — so a panel that comes back at 09:00 still takes the 03:00 copy, and a tick every ten
# minutes catches it just as well as a tick every minute would.

MODE_INTERVAL = 'interval'
MODE_CALENDAR = 'calendar'
MODES = (MODE_INTERVAL, MODE_CALENDAR)


def parse_at(value: str) -> tuple:
    """``"HH:MM"`` → ``(hour, minute)``, falling back to 03:00.

    Never raises: an operator types this, and a typo must not stop the scheduler thread. The
    copy lands at the default hour and the field still shows what was entered.
    """
    try:
        hh, mm = str(value or '').strip().split(':', 1)
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError, TypeError):
        pass
    return 3, 0


def normalise_days(days) -> list:
    """The weekdays a task runs on, Monday=0 — empty meaning EVERY day.

    Empty is "every day" rather than "never" on purpose: a task with no day ticked is one
    somebody has not narrowed, and a schedule that silently never runs is the failure this
    whole feature exists against.
    """
    if not isinstance(days, (list, tuple, set)):
        return []
    out = sorted({int(d) for d in days if str(d).lstrip('-').isdigit() and 0 <= int(d) <= 6})
    return [] if len(out) == 7 else out


def last_due_at(now, days, at: str):
    """The most recent moment this calendar task was due, at or before *now*.

    Walks back at most seven days: with `days` empty every day matches, and with days chosen
    the furthest gap between two of them is a week.
    """
    import datetime as _dt      # noqa: PLC0415 — only the calendar path needs it
    hour, minute = parse_at(at)
    wanted = normalise_days(days)
    for back in range(0, 8):
        cand = (now - _dt.timedelta(days=back)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        if cand > now:
            continue
        if not wanted or cand.weekday() in wanted:
            return cand
    return None


def is_due_calendar(now, days, at: str, last_ts: float | None) -> bool:
    """Has this task's window passed with no copy taken since?

    With no copy yet the answer is YES, as with an interval: an install that has never taken
    one is the install that most needs it, and waiting for the next Monday to find out the path
    was wrong is a week of believing in a backup that does not exist.
    """
    due = last_due_at(now, days, at)
    if due is None:
        return False
    if last_ts is None:
        return True
    return float(last_ts) < due.timestamp()


def task_is_due(task: dict, now_ts: float, last_ts: float | None) -> bool:
    """Is *task* due — whichever way it says when.

    One entry point so the runner never asks which kind it is holding: a scheduler that
    branched on mode at every call is a scheduler with two places to get the catch-up wrong.
    """
    import datetime as _dt      # noqa: PLC0415
    if str((task or {}).get('mode') or MODE_INTERVAL) == MODE_CALENDAR:
        return is_due_calendar(_dt.datetime.fromtimestamp(now_ts),
                               (task or {}).get('days'), (task or {}).get('at'), last_ts)
    return is_due((task or {}).get('every_hours'), now_ts, last_ts)
