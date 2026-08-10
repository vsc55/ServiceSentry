#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The thread that takes the automatic copies.

Everything about WHEN lives in :mod:`lib.core.backup.schedule` and is a pure function; what is
here is the part that cannot be one — a thread, a lease, and the calls that touch disk.

**One process takes it, not all of them.** The panel runs as several processes against the same
database (web, worker, syslog, events), and every one of them would otherwise wake up, find a
copy due and take it: four archives a tick, four full reads of every table. The lease the
services already use decides which one, and the loser does nothing rather than doing it badly.

**A tick every ten minutes, not every minute.** The interval rule stays true until a copy is
taken, so a coarse tick costs a few minutes of drift and saves 1430 wakeups a day. It also
means a copy started by hand and one started by the schedule cannot collide within a tick.
"""

from __future__ import annotations

import datetime as _dt
import threading
import time

from lib import __version__
from lib.core.backup import schedule as _sched
from lib.core.backup import service as _svc

# How often to ask "is one due?". See the module docstring: the answer does not go stale.
TICK_SECONDS = 600

# The lease key. Its own rather than borrowing the monitoring one: an install that runs no
# checks still takes backups, and tying the two would make "monitoring off" mean "no copies"
# without anybody saying so.
LEASE_KEY = 'backup'
LEASE_TTL = 900   # longer than a tick, so a slow copy does not lose the lease mid-write


class BackupRunner:
    """Owns the thread. Started by the web admin; stops with it."""

    def __init__(self, wa):
        self._wa = wa
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name='ss-backup')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ── The loop ─────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        # A first tick right away would run during start-up, while stores are still being
        # built; one tick of grace costs nothing an interval-based schedule notices.
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception as exc:      # pylint: disable=broad-except
                # A failing tick must never kill the thread: the next one may well work (a
                # full disk gets emptied, a network mount comes back), and a dead thread
                # takes automatic copies away silently until somebody restarts the panel.
                self._audit_failure(str(exc))

    def tick(self, now_ts: float | None = None) -> dict:
        """One round: take a copy if one is due, then prune. Returns what it did.

        Separate from the loop and returning its outcome so a test can drive it without a
        thread and a clock.
        """
        wa = self._wa
        every = getattr(wa, '_BACKUP_EVERY_HOURS', 0)
        now = now_ts or time.time()
        out = {'due': False, 'created': '', 'pruned': [], 'leader': True}

        var_dir = wa._var_dir or ''
        backup_dir = str(getattr(wa, '_BACKUP_DIR', '') or '')
        existing = _svc.list_backups(var_dir, backup_dir)
        last = _sched.last_auto_ts(existing)
        if not _sched.is_due(every, now, last):
            return out
        out['due'] = True

        # Only now is the lease worth asking for. Claiming it every tick would have every
        # process fighting over a lock for the 143 ticks a day on which there is nothing to do.
        if not self._claim():
            out['leader'] = False
            return out

        name = _sched.auto_name(_dt.datetime.fromtimestamp(now))
        res = _svc.create_backup(
            wa._db_connector, name,
            var_dir=var_dir, config_dir=getattr(wa, '_config_dir', '') or '',
            backup_dir=backup_dir,
            # The scheduled copy takes what a copy is FOR: the install itself. Not the
            # syslog, not the history — those are the parts an operator opts into for a
            # hand-made copy, and an unattended job that quietly writes 160k rows every day
            # is how the disk fills.
            parts=['core', 'config_file'],
            include_secrets=bool(getattr(wa, '_BACKUP_AUTO_SECRETS', True)),
            actor='(schedule)', app_version=__version__,
            engine=str(getattr(wa._db_connector, 'driver', '') or ''),
        )
        if not res.get('ok'):
            self._audit_failure(res.get('message', ''))
            return out
        out['created'] = name
        # `_audit_auto`, not `_audit`: this runs on a thread with no request, and
        # `_audit` reads the session and the remote address off one. It attributes the
        # entry to the request actor when there IS one and to the system when not,
        # which is exactly the difference between a copy somebody asked for and this.
        wa._audit_auto('backup_created', detail={
            'name': name, 'auto': True,
            'parts': res['manifest'].get('parts', []),
            'secrets': res['manifest'].get('secrets'),
            'size': res['manifest'].get('size', 0),
        })

        # Pruned AFTER the new one is on disk, and only then: pruning first would, on a full
        # disk, delete the old copy and fail to write the new one — leaving fewer copies than
        # before the run that was supposed to add one.
        for old in _sched.prune(_svc.list_backups(var_dir, backup_dir),
                               getattr(wa, '_BACKUP_KEEP', 7)):
            if _svc.delete_backup(var_dir, old, backup_dir):
                out['pruned'].append(old)
        if out['pruned']:
            wa._audit_auto('backup_deleted', detail={'names': out['pruned'], 'auto': True})
        return out

    # ── The lease ────────────────────────────────────────────────────────────
    def _claim(self) -> bool:
        """Try to become the process that takes this copy.

        An install with no lease store — a single process, which is most of them — takes it:
        the lease exists to stop FOUR processes writing four archives a tick, and refusing to
        work without one would turn the common deployment into the broken one.
        """
        store = getattr(self._wa, '_service_leader_store', None)
        instance = str(getattr(self._wa, '_instance_id', '') or '')
        if store is None or not instance:
            return True
        try:
            return bool(store.acquire(LEASE_KEY, instance, LEASE_TTL))
        except Exception:      # pylint: disable=broad-except
            # A lease that cannot be asked for must not stop the copy: the worst case is a
            # duplicate archive, and the worst case of the other choice is no backups at all.
            return True

    # ── Bookkeeping ──────────────────────────────────────────────────────────
    def _audit_failure(self, message: str) -> None:
        """A scheduled copy that failed is the line that matters most in the log.

        An unattended job failing in silence is worse than having no job: the copies are
        counted on precisely because nobody is watching them being made.
        """
        try:
            self._wa._audit_auto('backup_created',
                                 detail={'auto': True, 'ok': False,
                                         'message': message[:500]})
        except Exception:      # pylint: disable=broad-except
            pass
