#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The shared check executor — runs a set of watchful modules on a Monitor.

One place owns "run these modules concurrently, process + persist each result,
collect the per-item status/message, record history, and report errors/timeouts".
Both callers reuse it:

* the **on-demand** check (web UI "run now", :class:`_ChecksMixin`) — a transient
  Monitor, the modules the user asked for, a short deadline;
* the **scheduler** cycle (:class:`_MonitoringMixin`) — the persistent Monitor,
  every enabled module, a longer deadline + change-detection/history.

What differs (which Monitor, which modules, the timeout, the cycle-level logging)
stays in the callers; the per-module run loop lives here, so it exists once.
"""

from __future__ import annotations

import concurrent.futures
import threading

from lib.debug import DebugLevel


def run_checks(monitor, module_names, *, timeout: int, history=None,
               progress_cb=None, lang: str = '', only_host: str = '') -> tuple[dict, list]:
    """Run *module_names* on *monitor* concurrently and return ``(results, errors)``.

    ``results`` = ``{module: {item: {'status', 'message'}}}`` for modules that ran;
    ``errors`` = a list of ``"module: reason"`` strings.  Returns after *timeout*
    seconds regardless of still-running modules — their daemon threads finish on
    their own internal (socket/subprocess) timeouts and cannot be killed.  When a
    *history* store is given, each item's status is recorded under ``_hist_lock``
    (one writer at a time — no concurrent SQLite contention).

    **A module that finishes after the deadline still gets its history written**, by its
    own thread. It has to: the thread is not killed, it comes back, and it already stores
    its live status this way — but its history rows went into a buffer whose writer had
    run minutes earlier, so they were dropped in silence. The symptom is a module with a
    current status on screen and no series behind it, and nothing anywhere says why.

    Found on an SNMP fleet: sampling a NAS with a full device profile took ~5 minutes
    against a 120 s deadline, so live status appeared (late) on every cycle and the history
    table had not one row of that module since the day it was installed.

    ``only_host`` narrows every module to the items bound to ONE machine — "collect this
    device now", as opposed to a cycle, which is about the installation. It also turns OFF the
    orphan prune: that deletes every stored key the run did not report, which is right when
    the run covered everything and would wipe thirty-nine other machines' live state when it
    did not.

    ``progress_cb(state, module, detail)`` is called as each module STARTS and as it lands
    (``'running'`` / ``'ok'`` / ``'error'``), from the worker's own thread. It exists for the
    person standing in front of the screen: a collection asked for by hand runs for minutes
    and a bar that only moves at the end is indistinguishable from one that has hung. It is
    optional and never allowed to fail the run — a progress display that raises would take
    down the work it is describing, which is the wrong way round."""
    if not module_names:
        return {}, []

    results: dict = {}
    errors: list[str] = []
    _save_lock = threading.Lock()
    _hist_lock = threading.Lock()
    _hist_records: list = []
    # Set once the buffered flush below has happened. After that a module that comes back
    # writes its own rows instead of adding them to a list nobody reads again.
    _flushed = threading.Event()
    _enabled_set = set(monitor._get_enabled_modules())
    # Start from what is actually stored, the way the scheduler's own cycle does.
    #
    # Saving is `persist_status(status.data)`, which REPLACES the table — so a run launched
    # from the panel writes back this process's whole snapshot, and a web process that read
    # the state once at startup would put an hour-old copy of every other check on top of
    # what the worker has written since. It also decides whether a counter has a baseline:
    # a rate is the difference against the previous reading, and the previous reading is in
    # the table, not in this process's memory.
    try:
        monitor.status.read()
    except Exception:  # pylint: disable=broad-except
        pass          # a state that cannot be read is not a reason not to run the checks

    def _has_items(mod_name: str) -> bool:
        """True if the module has at least one item configured in any collection."""
        cfg = monitor.config_modules.get_conf([mod_name]) or {}
        if not isinstance(cfg, dict):
            return False
        for val in cfg.values():
            if isinstance(val, dict) and val:
                return True
        return False

    def _tell(state: str, mod_name: str, detail: str = '', extra: dict | None = None) -> None:
        """Say where a module is, if anyone is listening. Never at the cost of the run.

        *extra* is whatever the module said about its own phase (`report_progress`), passed
        through untouched: the core names no steps.
        """
        if progress_cb is None:
            return
        try:
            progress_cb(state, mod_name, detail, extra)
        except Exception:  # pylint: disable=broad-except
            pass

    def _run_one(mod_name: str):
        _tell('running', mod_name)
        try:
            success, result_name, result_data = monitor.check_module(
                mod_name, only_host=only_host)
            if success and result_data is not None:
                with _save_lock:
                    monitor._process_module_result(result_name, result_data,
                                                   prune=not only_host)
                    # This module's rows and not the whole table: a run saves once per
                    # module, and rewriting every other module's to record this one is
                    # three quarters of a second per run of `DELETE FROM check_state`,
                    # with every page load waiting three times longer behind it.
                    #
                    # Asked for rather than assumed: with no database the monitor's status is
                    # a plain ConfigControl, which has no such method — and an AttributeError
                    # here is swallowed by the `except` below, so the module would be recorded
                    # as having FAILED for the sole reason that it was saved.
                    _save = getattr(monitor.status, 'save_module', None)
                    if callable(_save):
                        _save(result_name)
                    else:
                        monitor.status.save()
                _recs = [(result_name, _key,
                          result_data.get_status(_key),
                          result_data.get_other_data(_key))
                         for _key in result_data.list]
                with _hist_lock:
                    # Both branches under the same lock, so a module finishing exactly at the
                    # boundary is written once — by the flush or by itself, never by neither.
                    if _flushed.is_set():
                        if history:
                            for _r in _recs:
                                history.record(*_r)
                    else:
                        _hist_records.extend(_recs)
                items = {
                    key: {
                        'status':  result_data.get_status(key),
                        'message': result_data.get_message(key),
                    }
                    for key in result_data.list
                }
                _failed = sum(1 for k in items if items[k]['status'] is not True)
                monitor.debug.print(
                    f"> Check > {mod_name} >> {len(items)} item(s), {_failed} not OK",
                    DebugLevel.debug)
                _tell('ok', mod_name, f'{len(items)}')
                return mod_name, items, None
            # check_module returned success=False.  Suppress the error only for a
            # known/enabled module with no items configured yet (user hasn't set it
            # up); unknown/non-existent modules always produce an error.
            if mod_name in _enabled_set and not _has_items(mod_name):
                _tell('ok', mod_name, '0')
                return mod_name, {}, None
            monitor.debug.print(f"> Check > {mod_name} >> check failed", DebugLevel.warning)
            _tell('error', mod_name, 'check failed')
            return mod_name, None, f'{mod_name}: check failed'
        except Exception as exc:  # pylint: disable=broad-except
            if mod_name in _enabled_set and not _has_items(mod_name):
                _tell('ok', mod_name, '0')
                return mod_name, {}, None
            monitor.debug.print(
                f"> Check > {mod_name} >> {type(exc).__name__}: {exc}", DebugLevel.error)
            _tell('error', mod_name, f'{type(exc).__name__}: {exc}')
            return mod_name, None, f'{mod_name}: {type(exc).__name__}: {exc}'
        finally:
            # This runs in a short-lived pool worker thread; close its per-thread DB
            # connection cleanly (server engines only) so it isn't logged as an
            # 'aborted connection' when the thread ends.
            _db = getattr(monitor, '_db', None)
            if _db is not None:
                _db.close_thread_if_needed()

    # Warm module imports sequentially before the concurrent phase: a module that
    # mutates sys.path during its check (dns loads dnspython, whose package shadows
    # our 'dns' watchful) must not race with bare-name imports of the others.
    for _m in module_names:
        try:
            monitor._import_watchful(_m)
        except Exception:  # pylint: disable=broad-except
            pass            # _run_one reports the real per-module error

    # The channel a module uses to say where it is (monitor.report_progress). Installed for
    # as long as the RUN is watched, which is not the same as the length of this call: a module
    # that overran the deadline is still working and still reporting, and the job is still open
    # on the screen waiting for it. Taken off when the last straggler lands — sooner froze the
    # checklist mid-read (reported exactly that way), and never would leave the scheduler's own
    # cycles reporting into a job that ended hours ago.
    _prev_sink = getattr(monitor, '_progress_sink', None)
    _prev_lang = getattr(monitor, '_progress_lang', '')
    monitor._progress_sink = _tell if progress_cb is not None else None
    # …and the language the WATCHER reads in. A module's sentences are otherwise resolved in
    # the installation's notification language, which is the right answer for a message sent
    # to a channel and the wrong one for a line on the screen of the person who just pressed
    # the button: reported as a Spanish dialog with "Reading the metrics" inside it.
    monitor._progress_lang = str(lang or '') if progress_cb is not None else ''

    workers = min(len(module_names), 16)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        future_to_mod = {executor.submit(_run_one, m): m for m in module_names}
        done, not_done = concurrent.futures.wait(future_to_mod.keys(), timeout=timeout)
    finally:
        # wait=False: return immediately without joining still-blocking threads
        # (they cannot be forcibly killed in Python).
        executor.shutdown(wait=False, cancel_futures=True)

    def _unhook() -> None:
        """Put back whatever was listening before this batch."""
        monitor._progress_sink = _prev_sink
        monitor._progress_lang = _prev_lang

    for future in done:
        mod = future_to_mod[future]
        try:
            name, items, err = future.result()
            if items is not None:
                results[name] = items
            else:
                errors.append(err or name)
        except Exception as exc:  # pylint: disable=broad-except
            errors.append(f'{mod}: {exc}')

    #: How many modules are still out. The sink comes off when it reaches zero, and it is
    #: a lock and not a bare integer because the stragglers land on their own threads: `-= 1`
    #: is three bytecodes, and two of them at once is a count that never reaches zero and a
    #: sink that never comes off.
    _left = {'n': len(not_done)}
    _left_lock = threading.Lock()

    def _late(future) -> None:
        """A module that overran, landing after the batch had already returned.

        It writes its own state and history — that part always worked. What nobody told was
        the SCREEN, which had been shown "still working" and then never heard another word,
        so a collection somebody was watching ended at 90 % and stayed there. The run is over
        when the run is over, and this is the only moment that knows.
        """
        mod_name = future_to_mod.get(future, '')
        try:
            name, items, err = future.result()
        except Exception as exc:  # pylint: disable=broad-except
            _tell('error', mod_name, f'{type(exc).__name__}: {exc}')
            with _left_lock:
                _left['n'] -= 1
                last = _left['n'] <= 0
            if last:
                _unhook()
            return
        if items is None:
            _tell('error', mod_name, err or name)
        else:
            _tell('ok', mod_name, f'{len(items)}')
        with _left_lock:
            _left['n'] -= 1
            last = _left['n'] <= 0
        if last:
            _unhook()

    if not not_done:
        _unhook()          # nothing overran: the run is over and so is the listening
    for future in not_done:
        errors.append(f'{future_to_mod[future]}: timeout after {timeout}s')
        # Not 'error': the module has NOT failed, it is still working and will write its own
        # state and history when it lands (see the docstring). A screen told "error" would be
        # a screen that has to un-say it.
        _tell('timeout', future_to_mod[future], str(timeout))
        # …and it is told when it does land. The callback fires on the worker thread that
        # finishes it, which outlives this function: the pool is shut down without waiting,
        # and a future already running is not cancelled by that.
        future.add_done_callback(_late)

    # Write history sequentially (one writer at a time — no concurrent SQLite contention),
    # and from here on a straggler writes its own; see the note in the docstring.
    with _hist_lock:
        _flushed.set()
        if history:
            for _mod, _key, _status, _data in _hist_records:
                history.record(_mod, _key, _status, _data)
        _hist_records.clear()

    # Flush the cycle's buffered alerts once, grouped per channel (+ summary). All
    # _process_module_result() calls above have finished, so the batch is complete.
    # (The daemon path historically sent per-item alerts but never a summary.)
    _notifier = getattr(monitor, '_notifier', None)
    if _notifier is not None:
        try:
            _notifier.flush(public_url=getattr(monitor, '_PUBLIC_URL', ''))
        except Exception:  # pylint: disable=broad-except
            pass

    return results, errors
