#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collecting what every package says it is running, into one shape.

Flask-free: it is handed the web admin and asks packages, and everything it returns is
plain data. The route around it does the permissions and the JSON.
"""

from __future__ import annotations

import time

from lib.discovery import scan

#: The manifest key a package declares to appear here. The value is a callable taking the
#: web admin and returning ``[{...}]`` in the shape :func:`live` documents.
DESCRIPTOR = 'BACKGROUND_JOBS'

#: The states a job can be in. `running` is the only one that is news; the rest are what the
#: list keeps around briefly so somebody who looked away still gets an answer.
#:
#: `interrupted` is never reported by a package — it is what the history writes over a row
#: that was still open when the process came back up. Nothing can be running that this process
#: did not start, so a row in that state belongs to a run that is gone.
STATES = ('running', 'done', 'failed', 'interrupted')

#: What every job carries, whatever produced it — and the DEFAULT for each, so a package
#: that leaves one out produces a row with a blank rather than a KeyError on the screen.
_SHAPE = {
    'id': '', 'source': '', 'kind': '', 'label': '', 'detail': '',
    'state': 'running', 'started': 0.0, 'done': 0, 'total': 0, 'error': '',
    # …and what it is doing, step by step. `detail` is the one line a list row has room for;
    # this is the checklist behind it, for somebody who opened the row to find out WHY it has
    # been going for four minutes.
    #
    # A step is `{state, text, scope, note, n, total}` and only the first two are required:
    #
    #   state   one of STEP_STATES. The package's own words do not travel — a screen cannot
    #           colour a word it has never seen — so anything else arrives blank.
    #   text    what is being done      ("Reading the metrics")
    #   scope   what it is being done TO ("erebor"), when one step covers several things
    #   n/total how far through that scope        (2 of 24)
    #   note    what the count is OF               ("Disks")
    #
    # Flattened to one sentence it read "erebor · Reading the metrics · 2/24 Disks", which is
    # the same words with the columns taken away — and the columns are what makes forty of
    # them scannable.
    'steps': [],
}

#: What a step can be. Anything else is drawn as "no verdict yet", which is what a package
#: saying something this file has not heard of actually means.
STEP_STATES = ('pending', 'running', 'ok', 'failed')


def normalise(source: str, raw: dict) -> dict:
    """One package's job as the shape every screen reads.

    Defensive about the numbers because they come from four different modules that grew
    separately: a `total` of zero is "no idea how many", not a bar at 0 %, and a `done`
    past the total is what a scope narrowed halfway through looks like.
    """
    out = dict(_SHAPE)
    for key in _SHAPE:
        if key in (raw or {}):
            out[key] = raw[key]
    out['source'] = str(source or '')
    out['id'] = str(out['id'] or '')
    out['state'] = out['state'] if out['state'] in STATES else 'running'
    try:
        out['total'] = max(0, int(out['total'] or 0))
        out['done'] = max(0, min(int(out['done'] or 0), out['total'] or 10 ** 9))
    except (TypeError, ValueError):
        out['total'], out['done'] = 0, 0
    try:
        out['started'] = float(out['started'] or 0)
    except (TypeError, ValueError):
        out['started'] = 0.0
    for key in ('kind', 'label', 'detail', 'error'):
        out[key] = str(out[key] or '')
    out['steps'] = _steps(out['steps'])
    return out


def _steps(raw) -> list:
    """A package's checklist, cleaned. A bare string is a step with only a `text`."""
    out = []
    for item in raw if isinstance(raw, (list, tuple)) else ():
        if not isinstance(item, dict):
            item = {'text': str(item or '')}
        text = str(item.get('text') or '')
        if not text.strip():
            continue
        state = str(item.get('state') or '')
        step = {'state': state if state in STEP_STATES else '', 'text': text,
                'scope': str(item.get('scope') or ''), 'note': str(item.get('note') or ''),
                # Whether this line hangs off the one above it. A package with two levels —
                # a module, and the machines it is working through — says so here; the
                # alternative was leading spaces in the text, which is an indent a screen has
                # to parse back out of a sentence.
                'sub': bool(item.get('sub'))}
        try:
            n, total = int(item.get('n') or 0), int(item.get('total') or 0)
        except (TypeError, ValueError):
            n = total = 0
        # A count with no total is a number with nothing to compare it to, and a total of
        # zero is a package saying it does not know how many — both are no counter at all.
        if total > 0:
            step['n'], step['total'] = max(0, min(n, total)), total
        out.append(step)
    return out


def live(wa) -> list:
    """Every background job this process is running, newest first.

    Each package declaring ``BACKGROUND_JOBS`` hands back its own, already answering:

    ``id``       what its own screen polls it by, so a row can lead back there
    ``kind``     what sort of work it is, in the package's own words
    ``label``    what it is working ON — a device's name, a MIB, a backup's task
    ``detail``   the step it is on right now
    ``state``    ``running`` / ``done`` / ``failed``
    ``started``  epoch seconds
    ``done`` / ``total``  how far, when the work has a countable size

    A package that raises is skipped rather than taking the list down: a screen that
    answers "here are three of the four" is worth more than one that answers nothing
    because a fourth thing is broken.
    """
    out: list = []
    for name, descriptor in scan(DESCRIPTOR):
        if not callable(descriptor):
            continue
        try:
            got = descriptor(wa) or []
        except Exception:  # pylint: disable=broad-except
            continue
        for raw in got:
            if isinstance(raw, dict):
                out.append(normalise(name, raw))
    return ordered(out)


#: Running first, then failed, then done. A finished job is kept by whoever owns it, briefly,
#: so somebody who looked away still gets an answer — it must not sit above work that is still
#: going on.
_ORDER = {'running': 0, 'failed': 1, 'interrupted': 2, 'done': 3}


def ordered(jobs: list) -> list:
    """The list in the order somebody opens the screen for: what is happening, then what just
    happened, newest first within each."""
    return sorted(jobs or (),
                  key=lambda j: (_ORDER.get(j.get('state'), 3), -float(j.get('started') or 0)))


def summary(jobs: list) -> dict:
    """The counts a badge is drawn from, so the sidebar and the list cannot disagree."""
    out = {s: 0 for s in STATES}
    for job in jobs or ():
        out[job.get('state', 'running')] = out.get(job.get('state', 'running'), 0) + 1
    out['total'] = len(jobs or ())
    return out


def age(job: dict, now: float | None = None) -> float:
    """How long it has been going, in seconds. Zero when it never said when it started."""
    started = float((job or {}).get('started') or 0)
    return max(0.0, (now if now is not None else time.time()) - started) if started else 0.0
