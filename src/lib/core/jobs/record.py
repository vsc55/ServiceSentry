#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The one call a package makes when its work ends.

A job finishes deep inside a worker thread that has no web admin, no request and no database
handle — it has the dict it has been updating and nothing else. Rather than thread a connector
through four unrelated pieces of machinery, the process hands one over ONCE at start-up and
this module keeps it.

``bind`` is called by whoever built the connector; until it is, :func:`record` does nothing
and says so by returning ``''``. That is the right failure: a worker process with no panel
runs no jobs anybody started from a screen, and a note about them would have nowhere to go.
"""

from __future__ import annotations

import os
import time
import uuid

_DB = None
_LIMITS = {'keep': 500, 'days': 30, 'lines': 200}

#: WHO is running this. Not a fresh uuid: `host:pid:role` is the identity this panel already
#: gives itself — the heartbeat writes it, the service registry lists it, and the health screen
#: shows it — so a job's owner is a name somebody can look up rather than twelve hex digits
#: that mean nothing anywhere else. The pid makes it new on every start, which is the property
#: the sweep below needs.
_OWNER = ''

#: How stale a heartbeat may be and still mean "that process is there". Generous, because
#: the cost of being wrong is asymmetric: calling a live job interrupted is a lie on the
#: screen, and waiting a few minutes longer to call a dead one interrupted is a delay.
_ALIVE_WITHIN = 300

#: How often the prune runs — every Nth write rather than on a timer. A thread of its own to
#: delete a handful of rows would be a thread to explain in every crash dump; a delete on
#: every write is a delete for a table that grows by one.
_PRUNE_EVERY = 25
_WRITES = [0]


def _identity(given: str = '') -> str:
    """Who this process is, in the words the rest of the panel already uses.

    ``host:pid:role`` — what :mod:`lib.services.heartbeat` writes into the service registry.
    Falling back to host and pid where no role was handed over, and to a random id where even
    the hostname cannot be read: an owner nobody can look up is still better than two runs
    sharing one.
    """
    if str(given or '').strip():
        return str(given).strip()[:120]
    try:
        from lib.services.heartbeat import hostname    # noqa: PLC0415
        return f'{hostname()}:{os.getpid()}:web'[:120]
    except Exception:  # pylint: disable=broad-except
        return uuid.uuid4().hex[:12]


def bind(db, limits: dict | None = None, owner: str = '') -> None:
    """Hand the package the connector its history lives in, and the installation's limits.

    Also closes whatever the LAST run left open. Nothing can be running that this process did
    not start — a job is threads in one process and dies with it — so a row still marked
    running belongs to a process that is gone. Reported from the screen: restart the panel
    with a collection in flight and it was visible nowhere, having neither ended nor appeared
    to begin.
    """
    global _DB, _OWNER                            # pylint: disable=global-statement
    _DB = db
    _OWNER = _identity(owner)
    for key in _LIMITS:
        if limits and limits.get(key) is not None:
            try:
                _LIMITS[key] = max(0, int(limits[key]))
            except (TypeError, ValueError):
                pass
    st = store()
    if st is not None:
        st.reap(alive=_alive(db))


def _alive(db) -> set:
    """The instances the service registry says are up right now.

    Without it the sweep is a broom: every open row is closed, which is right for the one
    panel that is the normal case and wrong the moment two of them share a database — one
    starting would declare the other's running job dead. With it, a row is only closed when
    its owner is not there any more.

    An empty answer means "the registry cannot say", and the sweep falls back to the broom:
    a job whose fate is unknown showing as interrupted is the thing this whole mechanism
    exists to say, and leaving rows open for ever is how they became invisible in the first
    place.
    """
    try:
        from lib.services.manager.instances import ServiceInstancesStore  # noqa: PLC0415
        rows = ServiceInstancesStore(db).list_instances() or []
    except Exception:  # pylint: disable=broad-except
        return set()
    now = time.time()
    out = set()
    for row in rows:
        iid = str((row or {}).get('instance_id') or '')
        try:
            seen = float((row or {}).get('last_seen') or 0)
        except (TypeError, ValueError):
            seen = 0
        # A registry row is not a pulse: a process that died leaves its last one behind. Only
        # a recent one says anybody is there.
        if iid and seen and (now - seen) < _ALIVE_WITHIN:
            out.add(iid)
    return out


def bound() -> bool:
    """Whether anything will be written. For the screen, so it can say so."""
    return _DB is not None


def limits() -> dict:
    return dict(_LIMITS)


def store():
    """The history store, or ``None`` when nothing was bound."""
    if _DB is None:
        return None
    from .history import JobHistoryStore          # noqa: PLC0415
    return JobHistoryStore(_DB)


def start(job: dict) -> str:
    """Open the row, at the moment the work starts. Hand the uid back to :func:`finish`.

    At the START and not at the end, because a job that never gets one is exactly the job
    somebody is looking for: a collection interrupted by a restart used to be visible nowhere.
    """
    st = store()
    return st.begin(job, owner=_OWNER) if st is not None else ''


def finish(uid: str, job: dict, log: list | None = None) -> bool:
    """Close the row :func:`start` opened. Never raises, and never blocks the work.

    *job* is the shape :mod:`lib.core.jobs.service` documents, plus ``ended``. *log* is
    whatever the job wants remembered about what it did — capped by the installation's
    setting, keeping the END of it, which is where whatever went wrong is.
    """
    st = store()
    if st is None or not uid:
        return False
    ok = st.complete(uid, job, log, cap=_LIMITS['lines'])
    _WRITES[0] += 1
    if ok and _WRITES[0] % _PRUNE_EVERY == 0:
        st.prune(keep=_LIMITS['keep'], days=_LIMITS['days'])
    return ok


def record(job: dict, log: list | None = None) -> str:
    """Open and close in one go — for work that was already over when it got here."""
    uid = start(job)
    return uid if finish(uid, job, log) else ''
