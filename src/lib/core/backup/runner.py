#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The thread that takes the automatic copies.

Everything about WHEN lives in :mod:`lib.core.backup.schedule` and is a pure function; what is
here is the part that cannot be one — a thread, a lease, and the calls that touch disk. What a
person starts by hand — a copy, a restore, "run this task now" — is
:mod:`lib.core.backup.jobs`, inherited by the class below: none of it is scheduled, and it was
half of a file whose docstring is this one.

**Who runs this.** The thread is started by the WEB admin and nowhere else
(`WebAdmin._start_backup_runner`), so in a multi-container deployment the scheduled copies are
taken by the `web` container — not by the worker, the syslog receiver or the events service. A
copy reads every table of the system database and writes an archive to `<var_dir>/backups`,
which is the volume the web role already has; nothing about it belongs to a monitoring worker.

**One process takes it, not all of them.** That is still not "one process" — a deployment may
run several web replicas behind a load balancer, and each of them would wake up, find the same
copy due and take it: three archives a tick, three full reads of every table. The lease the
services already use decides which one, and the losers do nothing rather than doing it badly.

**The consequence worth knowing:** an install whose web role is stopped takes no scheduled
copies at all. Nothing is queued and nothing catches up on its own beyond the interval rule —
though that rule is exactly what makes a panel brought back up at 09:00 still take the 03:00
copy, so a web container that restarts loses nothing.

**A tick every ten minutes, not every minute.** The interval rule stays true until a copy is
taken, so a coarse tick costs a few minutes of drift and saves 1430 wakeups a day. It also
means a copy started by hand and one started by the schedule cannot collide within a tick.
"""

from __future__ import annotations

import datetime as _dt
import os
import threading
import time

from lib import __version__
from lib.core.backup import create as _create
from lib.core.backup import schedule as _sched
from lib.core.backup import service as _svc
from lib.core.backup.archive import _log
from lib.core.backup.jobs import _connectors, _JobsMixin
from lib.debug.debug_level import DebugLevel

# How often to ask "is one due?". See the module docstring: the answer does not go stale.
TICK_SECONDS = 600

# The lease key. Its own rather than borrowing the monitoring one: an install that runs no
# checks still takes backups, and tying the two would make "monitoring off" mean "no copies"
# without anybody saying so.
LEASE_KEY = 'backup'
LEASE_TTL = 900   # longer than a tick, so a slow copy does not lose the lease mid-write

# What the pre-task settings become the first time the scheduler runs without tasks.
_LEGACY_TASK_NAME = 'default'


class BackupRunner(_JobsMixin):
    """Owns the thread. Started by the web admin; stops with it.

    The jobs a person starts by hand — a copy, a restore, "run this task now" — come from
    :class:`~lib.core.backup.jobs._JobsMixin`. They share this class because "run now" has to
    go through the schedule's own path (`run_now`) or it would produce a copy the task does
    not own, and nothing else about them is scheduled at all.
    """

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
        """One round: every task that is due takes its copy, then prunes its own.

        Separate from the loop and returning its outcome so a test can drive it without a
        thread and a clock.
        """
        wa = self._wa
        now = now_ts or time.time()
        out = {'created': [], 'pruned': [], 'leader': True}

        # Called first because it also performs the one-off migration of the pre-task settings.
        tasks = self._tasks()
        all_tasks = self._all_tasks()
        # Not `if not tasks`: a task switched OFF still has copies, and its retention still has
        # to be applied to them — that is the difference between "stop making new ones" and
        # "let the old ones grow for ever, counted by nobody".
        if not all_tasks:
            return out

        var_dir = wa._var_dir or ''
        backup_dir = str(getattr(wa, '_BACKUP_DIR', '') or '')
        existing = _svc.list_backups(var_dir, backup_dir)
        # `task_is_due` and not a branch here: a scheduler that asked which kind it was
        # holding at each call is a scheduler with two places to get the catch-up wrong.
        due = [t for t in tasks
               if _sched.task_is_due(t, now, _sched.last_auto_ts(existing, t.get('name')))]
        # Read once for the whole round rather than per task: a tick that asked the profiles
        # table again for every task would also be a tick where two tasks could be pruned by two
        # different versions of the same policy, if somebody saved it in between.
        profiles = self._profiles()
        # Retention is evaluated for EVERY task on every tick, disabled ones included, and not
        # only for the ones that just copied. Computed before the lease is asked for because it
        # is a pure function of what is on disk: knowing there is nothing to do is what lets an
        # idle tick stay free of contention.
        overdue = [t for t in all_tasks
                   if _sched.prune(existing, _sched.with_profile(t, profiles), t.get('name'))]
        if not due and not overdue:
            return out

        # ONE lease for the whole round, not one per task. Two tasks falling due together on
        # two processes would otherwise each take a copy of the same install — and asked for
        # only when there is something to do, so the idle ticks cost no contention at all.
        if not self._claim():
            out['leader'] = False
            return out

        if due:
            _log(f'> Backup > schedule >> {len(due)} task(s) due: '
                 + ', '.join(repr(t.get('name', '')) for t in due))
        ran = set()
        for task in due:
            # Serialised, deliberately. Two copies at once read every table twice and write two
            # archives against the same disk; one after another is slower on paper and the only
            # shape that does not double the load of the moment they collide.
            self._run_task(task, now, var_dir, backup_dir, out, profiles=profiles)
            ran.add(task.get('name'))
        for task in overdue:
            # The ones that just ran already pruned, with the new copy on disk and counted.
            if task.get('name') not in ran:
                self._prune_task(task, var_dir, backup_dir, out, profiles=profiles)
        return out

    def run_now(self, task: dict, now_ts: float | None = None, progress_cb=None) -> dict:
        """Run one task immediately, exactly as the schedule would.

        The point is that it is the SAME path: same parts, same secrets flag, the same
        `auto-<task>-<date>` name and the same per-task retention afterwards. A "run now" that
        went through the generic create would produce a copy the task does not own — outside its
        counter, never pruned by it, and not the thing the operator asked to try.

        No lease: somebody is standing there having pressed the button, and refusing because
        another process holds the schedule's lease would be refusing to do what they asked.
        """
        out = {'created': [], 'pruned': []}
        self._run_task(task, now_ts or time.time(), self._wa._var_dir or '',
                       str(getattr(self._wa, '_BACKUP_DIR', '') or ''), out,
                       progress_cb=progress_cb)
        return out

    def _run_task(self, task: dict, now: float, var_dir: str, backup_dir: str,
                  out: dict, progress_cb=None, profiles=None) -> None:
        wa = self._wa
        name = _sched.auto_name(_dt.datetime.fromtimestamp(now), task.get('name'))
        res = _create.create_backup(
            wa._db_connector, name,
            var_dir=var_dir, config_dir=getattr(wa, '_config_dir', '') or '',
            backup_dir=backup_dir,
            parts=list(task.get('parts') or []),
            include_secrets=bool(task.get('secrets', True)),
            actor=f'(schedule: {task.get("name") or "?"})', app_version=__version__,
            progress_cb=progress_cb, connectors=_connectors(wa),
            engine=str(getattr(wa._db_connector, 'driver', '') or ''),
        )
        if not res.get('ok'):
            self._audit_failure(res.get('message', ''), task.get('name'))
            return
        out['created'].append(name)
        out['status'] = res['manifest'].get('status', 'ok')
        # `_audit_auto`, not `_audit`: this runs on a thread with no request, and `_audit`
        # reads the session and the remote address off one.
        wa._audit_auto('backup_created', detail={
            'name': name, 'auto': True, 'task': task.get('name', ''),
            'parts': res['manifest'].get('parts', []),
            'secrets': res['manifest'].get('secrets'),
            'size': res['manifest'].get('size', 0),
            # The verdict goes in the log too: a copy that lost a table is the line somebody
            # needs to find later, and "it ran" is not the same as "it worked".
            'status': res['manifest'].get('status', 'ok'),
        })

        # Pruned AFTER the new one is on disk: pruning first would, on a full disk, delete the
        # old copy and fail to write the new one.
        self._prune_task(task, var_dir, backup_dir, out, profiles=profiles)

    def _prune_task(self, task: dict, var_dir: str, backup_dir: str, out: dict,
                    profiles=None) -> None:
        """Apply one task's retention to the copies IT took.

        Only within this task: a daily task counting every automatic copy would prune the
        monthly one's — deleting exactly the copies that took a month to become worth having.

        Run on every tick and not only after a copy, which is where this used to sit. A monthly
        task went a month without its rules being applied, and a DISABLED one went for ever:
        somebody who switches a task off to stop new copies has not asked to freeze the old ones
        outside every counter.

        The rules are resolved HERE, once, through :func:`schedule.with_profile`: a task may
        carry its own numbers or follow a shared profile, and everything below this line is
        written against a task that already knows which.
        """
        wa = self._wa
        task = _sched.with_profile(
            task, profiles if profiles is not None else self._profiles())
        existing = _svc.list_backups(var_dir, backup_dir)
        doomed = _sched.prune(existing, task, task.get('name'))
        if not doomed:
            return
        # Did the ceiling do this, or the calendar? Worth separating: a budget that is doing the
        # pruning means the policy asks for more history than there is room for, which is a
        # decision somebody should get to revisit rather than discover as a gap.
        by_rules = set(_sched.prune(existing, {**task, 'max_size': 0}, task.get('name')))
        gone, by_budget = [], []
        for old in doomed:
            if _svc.delete_backup(var_dir, old, backup_dir):
                gone.append(old)
                if old not in by_rules:
                    by_budget.append(old)
        if not gone:
            return
        out['pruned'] += gone
        _log(f'> Backup > schedule >> {task.get("name")!r} retention removed '
             + ', '.join(repr(g) for g in gone))
        wa._audit_auto('backup_deleted', detail={'names': gone, 'auto': True,
                                                 'task': task.get('name', '')})
        if by_budget:
            _log(f'> Backup > schedule >> {task.get("name")!r} is over its size budget; '
                 f'{len(by_budget)} copy(ies) the rules wanted to keep were removed',
                 DebugLevel.warning)
            wa._audit_auto('backup_budget_exceeded',
                           detail={'task': task.get('name', ''), 'names': by_budget,
                                   'max_size': task.get('max_size', 0)})
            self._notify_budget(task, by_budget)

    # ── The tasks ────────────────────────────────────────────────────────────
    def _all_tasks(self) -> list:
        """Every task, enabled or not — what RETENTION is evaluated against.

        Disabled included on purpose: switching a task off says "stop making new copies", not
        "freeze the old ones outside every counter and let them grow for ever". The rules a
        task carries are still that task's answer to how much history is worth keeping.
        """
        store = getattr(self._wa, '_backup_tasks_store', None)
        return store.list_tasks() if store is not None else []

    def _profiles(self) -> list:
        """The shared retention profiles, for the tasks that follow one.

        An install with no profiles store — or none created — answers an empty list, and
        `with_profile` leaves every task exactly as it was written. Profiles are an offer to
        stop repeating a policy, never a thing retention needs in order to work.
        """
        store = getattr(self._wa, '_backup_profiles_store', None)
        return store.list_profiles() if store is not None else []

    def _notify_budget(self, task: dict, names: list) -> None:
        """Say that a size ceiling, not the calendar, is deciding what survives.

        Worth a notification and not just a log line: it means the policy asks for more history
        than there is room for, and the copies being lost are ones the rules wanted to keep.
        Best-effort — a channel that is down must never cost the pruning that already happened.
        """
        try:
            from lib.core.notify.notification_dispatcher import dispatch  # noqa: PLC0415
            wa = self._wa
            dispatch(wa, kind='backup_budget_exceeded',
                     timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
                     module='backup', item=str(task.get('name') or ''),
                     status=wa._notify_text('notif_status_warning'),
                     message=wa._notify_text('notif_msg_backup_budget',
                                             task.get('name', ''), len(names)))
        except Exception:      # pylint: disable=broad-except
            pass

    def _tasks(self) -> list:
        """The enabled tasks, migrating the pre-task settings the first time there are none.

        The three settings this replaced (`backup_every_hours`, `backup_keep`,
        `backup_auto_secrets`) are still read ONCE, to become a task called after them. Retiring
        them outright would have turned a configured schedule into no schedule at all, and a
        copy that quietly stops being taken is discovered when it is needed — which is the one
        moment this feature exists for.
        """
        store = getattr(self._wa, '_backup_tasks_store', None)
        if store is None:
            return []
        tasks = store.enabled_tasks()
        if tasks:
            return tasks
        if store.count():
            return []      # tasks exist and are all disabled — that is an answer, not a gap
        every = getattr(self._wa, '_BACKUP_EVERY_HOURS', 0)
        try:
            if float(every) <= 0:
                return []  # nothing was scheduled before either; nothing to carry over
        except (TypeError, ValueError):
            return []
        store.upsert({
            'name': _LEGACY_TASK_NAME,
            'enabled': True,
            'every_hours': every,
            'parts': ['core', 'config_file'],
            'secrets': bool(getattr(self._wa, '_BACKUP_AUTO_SECRETS', True)),
            # As `keep_last` and with the buckets off: the setting it carries over was a plain
            # counter, and turning it into a retention policy nobody chose would be inventing
            # an answer on their behalf.
            'keep_last': getattr(self._wa, '_BACKUP_KEEP', 7),
            'keep_daily': 0, 'keep_weekly': 0, 'keep_monthly': 0, 'keep_yearly': 0,
        }, actor='(migration)')
        self._wa._audit_auto('backup_task_migrated',
                             detail={'name': _LEGACY_TASK_NAME, 'every_hours': every})
        return store.enabled_tasks()

    # ── The lease ────────────────────────────────────────────────────────────
    def _instance(self) -> str:
        """Who this process is, to the lease.

        The same shape the health and certificate scanners use for theirs
        (`lib/web_admin/mixins/scanners.py`) — job, host, pid — because the lease's whole
        purpose is telling two processes apart, and two of them on one host differ only by the
        pid. Computed once: a lease renewed under a NEW id every tick is not a renewal, it is
        one process fighting itself for its own lease.
        """
        cached = getattr(self, '_inst_id', '')
        if not cached:
            from lib.services.heartbeat import hostname      # noqa: PLC0415
            cached = f'backup-{hostname()}-{os.getpid()}'
            self._inst_id = cached
        return cached

    def _claim(self) -> bool:
        """Try to become the process that takes this copy.

        An install with no lease store — a single process, which is most of them — takes it:
        the lease exists to stop FOUR processes writing four archives a tick, and refusing to
        work without one would turn the common deployment into the broken one.

        It had never once stopped anything. It asked for `_instance_id`, an attribute no
        WebAdmin has, so `instance` was always `''` and the guard above returned True before
        reaching the store — and had it got there, `acquire()` is not a method of
        `ServiceLeaderStore` either (it is `try_acquire`), so the AttributeError would have been
        swallowed by the catch-all below and returned True as well. Two ways of saying yes to
        every process, on the one code path whose entire job is to say no to all but one.
        """
        store = getattr(self._wa, '_service_leader_store', None)
        if store is None:
            return True
        from lib.services.heartbeat import hostname          # noqa: PLC0415
        try:
            return bool(store.try_acquire(LEASE_KEY, self._instance(),
                                          host=hostname(), ttl=LEASE_TTL))
        except Exception:      # pylint: disable=broad-except
            # A lease that cannot be asked for must not stop the copy: the worst case is a
            # duplicate archive, and the worst case of the other choice is no backups at all.
            return True

    # ── Bookkeeping ──────────────────────────────────────────────────────────
    def _audit_failure(self, message: str, task: str = '') -> None:
        """A scheduled copy that failed is the line that matters most in the log.

        An unattended job failing in silence is worse than having no job: the copies are
        counted on precisely because nobody is watching them being made.
        """
        try:
            self._wa._audit_auto('backup_created',
                                 detail={'auto': True, 'ok': False, 'task': task,
                                         'message': message[:500]})
        except Exception:      # pylint: disable=broad-except
            pass
