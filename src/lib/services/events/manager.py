#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-rules manager: match events and fire notifications.

A rule (lib.services.events.store.EventRulesStore) matches events from a source and,
when it fires, dispatches a ``kind='event'`` notification to the channels the rule
chose (via lib.core.notify.notification_dispatcher, channels override).

This module is intentionally Flask-free (the dispatcher is imported lazily only
when a rule actually fires) so it can be mixed into both the WebAdmin and the
standalone :class:`lib.services.syslog.service.SyslogService`.

Evaluation is **decoupled from ingestion**: a background worker
(:meth:`_event_worker_tick`) drains newly-stored rows from each source **by cursor**
(``EventStateStore``), on a poll interval — the syslog listener has no per-message hook.
It runs in the WebAdmin (embedded) and in the standalone syslog/event services alike.

Sources:
* ``audit``  — every audit-log entry (login_failed, daemon/syslog started/stopped,
  config_changed, device/user created/deleted, …), read from the ``audit`` table.
  This also covers "service status" for the embedded services (their start/stop
  are audit events).
* ``syslog`` — each received syslog message (severity/host/app/match), read from the
  ``syslog`` table.

Matching is best-effort and never raises into the caller's path.
"""

from __future__ import annotations

import collections
import functools
import json
import re
import threading
import time

from lib.debug import DebugLevel
from lib.services.events.rules_logic import regex_is_unsafe

def _is_simulated_line(ctx) -> bool:
    from lib.modules.simulated import SYSLOG_MSGID          # noqa: PLC0415
    return isinstance(ctx, dict) and str(ctx.get('msgid') or '') == SYSLOG_MSGID


#: How much of a field a rule's regex is run against (chars). Syslog text is the sender's.
REGEX_MAX_TEXT = 4096


@functools.lru_cache(maxsize=256)
def _regex_unsafe(pattern: str) -> bool:
    return regex_is_unsafe(pattern)



#: How far behind its cursor the event worker looks again for rows committed late.
_LATE_WINDOW = 200


class _Seen:
    """A bounded set of recent ids: membership, and the oldest forgotten first."""

    def __init__(self, size: int = 4 * _LATE_WINDOW):
        self._order = collections.deque(maxlen=size)
        self._set: set = set()

    def __contains__(self, rid) -> bool:
        return rid in self._set

    def add(self, rid) -> None:
        if rid is None or rid in self._set:
            return
        if len(self._order) == self._order.maxlen:
            self._set.discard(self._order[0])
        self._order.append(rid)
        self._set.add(rid)

class _EventsMixin:

    def _init_events(self) -> None:
        self._event_last: dict[str, float] = {}   # rule uid -> last fire ts (cooldown cache)
        self._event_rules_cache: list | None = None
        self._event_state = None                  # EventStateStore (persisted cooldown + cursor)
        self._event_worker_stop = None            # threading.Event while the worker runs
        self._event_tick_lock = threading.Lock()  # serialize tick: worker loop vs run_now command

    # ── persistent state (cooldown + cursor) ──────────────────────────────────────
    def _attach_event_state(self, store) -> None:
        """Wire the persistent cooldown/cursor store and warm the cooldown cache so a
        rule does not re-fire after a restart."""
        self._event_state = store
        try:
            self._event_last = store.cooldowns()
        except Exception:  # pylint: disable=broad-except
            pass

    def _event_refresh_cooldowns(self) -> None:
        """Merge the persisted cooldowns into the cache (the later fire wins). Best-effort:
        a failed read keeps what is in memory."""
        st = self._event_state
        if st is None:
            return
        try:
            persisted = st.cooldowns() or {}
        except Exception:  # pylint: disable=broad-except
            return
        for uid, ts in persisted.items():
            try:
                if float(ts) > float(self._event_last.get(uid, 0) or 0):
                    self._event_last[uid] = float(ts)
            except (TypeError, ValueError):
                continue

    # ── rule cache ──────────────────────────────────────────────────────────────
    def _events_reload(self) -> None:
        """Refresh the cached rule list (call after any rule CRUD)."""
        store = getattr(self, '_event_rules_store', None)
        self._event_rules_cache = store.list() if store is not None else []
        from lib.services.events.rules_logic import unsafe_patterns  # noqa: PLC0415
        for rule in self._event_rules_cache:
            malos = unsafe_patterns(rule)
            if malos and rule.get('enabled', True):
                self._dbg(f"> Events >> rule {rule.get('name')!r} is NOT evaluated: unsafe regex "
                          f"{malos!r} (nested repetition); edit the rule", DebugLevel.warning)

    def _events_rules(self) -> list:
        if self._event_rules_cache is None:
            self._events_reload()
        return self._event_rules_cache or []

    def _events_enabled(self) -> bool:
        """Whether rule evaluation is enabled — the on/off master switch, uniform
        with monitoring/syslog (embedded-vs-external is the SS_EVENTS_EMBEDDED env,
        not a config field).  Disabling it idles the worker everywhere (it keeps
        running to react to a later reconcile) — so a Services-tab stop of an
        external worker takes effect without killing the container.

        Backward compat: an explicit ``events|enabled`` wins; else the legacy
        ``events|mode`` is honoured (``off`` ⇒ disabled, any other value ⇒ enabled)."""
        try:
            ev = (self._read_config_file(getattr(self, '_CONFIG_FILE', None))
                  or {}).get('events') or {}
        except Exception:  # pylint: disable=broad-except
            return True
        val = ev.get('enabled')
        if val is not None:
            return bool(val)
        legacy = ev.get('mode')
        if legacy is not None:
            return str(legacy).lower() != 'off'
        return True

    def _event_default_cooldown(self) -> int:
        """Global default cooldown (s) from config (``events|cooldown``), used by
        rules that leave their own Cooldown blank.  0 on any problem."""
        try:
            cfg = self._read_config_file(getattr(self, '_CONFIG_FILE', None)) or {}
            v = (cfg.get('events') or {}).get('cooldown')
            return max(0, int(v)) if v not in (None, '') else 0
        except Exception:  # pylint: disable=broad-except
            return 0

    # ── Imperative commands (run-now / reload) ─────────────────────────────────
    def _apply_command(self, action: str, args: dict | None = None) -> tuple[bool, str]:
        """Execute a one-shot command from the service-command queue on the
        instance hosting the event worker (embedded here or a remote worker)."""
        if action == 'run_now':
            # On a thread of its own, holding the tick lock until it ends — like the
            # monitor's run-now. This runs on the heartbeat's loop, which also renews the
            # lease: a long backlog drained here let the lease lapse, a standby took it and
            # dispatched beside this one, and peers saw no heartbeat.
            lock = getattr(self, '_event_tick_lock', None)
            if lock is not None and not lock.acquire(blocking=False):
                return False, 'busy'

            def _tick():
                try:
                    self._event_worker_tick_impl()
                except Exception as exc:  # pylint: disable=broad-except
                    try:
                        self._dbg(f"> Events >> run-now failed: {exc}", DebugLevel.error)
                    except Exception:  # pylint: disable=broad-except
                        pass
                finally:
                    if lock is not None:
                        lock.release()
            try:
                threading.Thread(target=_tick, name='events-run-now', daemon=True).start()
            except Exception as exc:  # pylint: disable=broad-except
                if lock is not None:
                    lock.release()
                return False, str(exc)
            return True, 'started'
        if action == 'reload':
            try:
                mgr = getattr(self, '_config_mgr', None)
                if mgr is not None:
                    mgr.invalidate()
                self._events_reload()
                return True, 'rules reloaded'
            except Exception as exc:  # pylint: disable=broad-except
                return False, str(exc)
        return False, 'unknown_action'

    # ── worker (cursor over the source tables) ────────────────────────────────────
    def _event_sources(self) -> list:
        """``[(cursor_key, source, store, log_source)]`` the worker consumes — only stores
        that are present and expose the cursor API (query_since/max_id).

        *source* is the kind a rule names (``syslog``/``audit``). The external syslog sources
        a rule may watch come after the internal one, each under its own cursor
        (``syslog:<uid>``) and with *log_source* = its uid; the internal one's is ``''``."""
        out = []
        for source, attr in (('syslog', '_syslog_store'), ('audit', '_audit_store')):
            store = getattr(self, attr, None)
            if store is not None and hasattr(store, 'query_since') and hasattr(store, 'max_id'):
                out.append((source, source, store, ''))
        sources = getattr(self, '_syslog_sources', None)
        if sources is not None:
            try:
                for uid, name, store in sources.watched():
                    out.append((f'syslog:{uid}', 'syslog', store, (uid, name)))
            except Exception as exc:  # pylint: disable=broad-except
                self._dbg(f"> Events >> external syslog sources unavailable: {exc}",
                          DebugLevel.warning)
        return out

    def _event_worker_tick(self) -> int:
        """Guarded entry: serialize the tick so the periodic worker loop and a queued
        ``run_now`` command (drained by the heartbeat / control poke) never drain the
        cursor concurrently — which would re-read the same rows and double-dispatch
        alerts.  A tick already in progress makes the second caller a no-op."""
        lock = getattr(self, '_event_tick_lock', None)
        if lock is not None and not lock.acquire(blocking=False):
            return 0
        try:
            return self._event_worker_tick_impl()
        finally:
            if lock is not None:
                lock.release()

    def _event_worker_tick_impl(self) -> int:
        """Consume every new syslog/audit row since the cursor and evaluate the rules.

        Returns the number of records processed.  Never raises.  This is the path
        that replaces the former inline evaluation, so a flood of incoming messages
        no longer blocks ingestion — the worker drains the backlog at its own pace."""
        st = self._event_state
        if st is None:
            return 0
        # Hot standby: with leader gating, only the lease holder advances the cursor
        # and dispatches — other replicas idle, so notifications never double-fire.
        if hasattr(self, '_work_allowed') and not self._work_allowed():
            self._event_leading = False
            return 0
        if not self.__dict__.get('_event_leading'):
            # Just took the work over (a start, or a standby that won the lease): the
            # cooldowns in memory are the ones read at start-up, and the old leader has
            # fired since. Without this the new leader fired every rule still in cooldown.
            self._event_leading = True
            self._event_refresh_cooldowns()
        # Desired-state stop: events|enabled=false idles the worker everywhere
        # (embedded and external) without killing it, so a Services-tab stop takes
        # effect on a dedicated container too.
        if not self._events_enabled():
            return 0
        processed = 0
        for key, source, store, log_source in self._event_sources():
            try:
                last = st.cursor(key)
                tail = store.max_id()
                if tail is None:
                    # The table could not be confirmed this tick (an external source whose
                    # database is down). Not empty: reseeding here put the cursor at 0 and
                    # the next tick replayed the whole table. Keep the cursor, try later.
                    continue
                # First run → start at the tail (no replay). And a cursor PAST the tail is a
                # cursor of another table: a dedicated syslog database switched on, a source
                # re-pointed, a restore that lowered the ids. Kept, every new row sat below it
                # and no rule fired again, silently.
                if last is None or (tail is not None and last > tail):
                    last = tail
                    st.set_cursor(key, last)
                    # The late window belonged to the old table: rebuild it from the new
                    # cursor, as at start-up, or every row just behind it fires again.
                    self.__dict__.get('_event_seen', {}).pop(key, None)
                id_key = '_id' if source == 'audit' else 'id'
                uid, name = log_source if log_source else ('', '')
                seen = self._event_late_window(key, store, last, id_key)
                desde = max(0, int(last or 0) - _LATE_WINDOW)
                while True:
                    rows = store.query_since(desde, limit=500)
                    if not rows:
                        break
                    for rec in rows:
                        rid = rec.get(id_key)
                        if rid in seen:
                            continue
                        seen.add(rid)
                        if uid:
                            rec['log_source'], rec['log_source_name'] = uid, name
                        self._eval_event(source, rec, log_source=uid)
                        processed += 1
                    top = rows[-1].get(id_key, last)
                    if top is not None and (last is None or top > last):
                        last = top
                        st.set_cursor(key, last)
                    desde = rows[-1].get(id_key, desde)
                    if len(rows) < 500:
                        break
            except Exception as exc:  # pylint: disable=broad-except
                self._dbg(f"> Events >> worker tick ({key}) failed: {exc}", DebugLevel.error)
        return processed

    def _event_late_window(self, key, store, last, id_key) -> '_Seen':
        """The ids already evaluated just behind the cursor of *key*.

        On PostgreSQL and MySQL ids are handed out when a row is INSERTED, not when it is
        committed: with several writers (web threads auditing, two syslog receivers, rsyslog's
        workers) id 100 can become visible after 101 was read and the cursor moved past it — a
        row no rule would ever see. So every tick re-reads a short window behind the cursor and
        evaluates only what it has not evaluated yet. The first time, after a start, the window
        is taken as done: it was, by the process before.
        """
        cache = self.__dict__.setdefault('_event_seen', {})
        seen = cache.get(key)
        if seen is None:
            seen = cache[key] = _Seen()
            try:
                for rec in store.query_since(max(0, int(last or 0) - _LATE_WINDOW),
                                             limit=_LATE_WINDOW + 1):
                    rid = rec.get(id_key)
                    if rid is not None and rid <= int(last or 0):    # only what it had passed
                        seen.add(rid)
            except Exception:  # pylint: disable=broad-except
                pass
        return seen

    def _event_worker_loop(self, stop_event, poll_secs: float = 2.0) -> None:
        """Run ticks every *poll_secs* seconds until *stop_event* is set."""
        self._dbg("> Events >> worker started", DebugLevel.info)
        poll = max(0.2, float(poll_secs or 2.0))
        while not stop_event.is_set():
            try:
                self._event_worker_tick()
            except Exception as exc:  # pylint: disable=broad-except
                # The tick guards each source, but its gates (_events_enabled reads
                # config) do not: a DB outage there must cost one tick, not the worker.
                try:
                    self._dbg(f"> Events >> worker tick failed: {exc}", DebugLevel.error)
                except Exception:  # pylint: disable=broad-except
                    pass
            if stop_event.wait(poll):
                break
        self._dbg("> Events >> worker stopped", DebugLevel.info)

    def _start_event_worker(self, poll_secs: float = 2.0) -> None:
        """Start the background event worker thread (idempotent; no-op without state)."""
        if self._event_state is None or self._event_worker_stop is not None:
            return
        stop = threading.Event()
        self._event_worker_stop = stop
        threading.Thread(target=self._event_worker_loop, args=(stop, poll_secs),
                         name='event-worker', daemon=True).start()

    def _stop_event_worker(self) -> None:
        """Signal the worker loop to exit."""
        stop = self._event_worker_stop
        if stop is not None:
            stop.set()
            self._event_worker_stop = None

    def _event_worker_running(self) -> bool:
        return self._event_worker_stop is not None

    # ── evaluation ──────────────────────────────────────────────────────────────
    @staticmethod
    def _rule_watches(rule: dict, log_source: str) -> bool:
        """Whether a syslog rule looks at the source a row came from: its ``log_source`` is
        ``''`` (the internal one — every rule written before there were others), ``'*'``
        (all of them) or one external source's uid."""
        want = str(rule.get('log_source') or '')
        return want == '*' or want == (log_source or '')

    def _eval_event(self, source: str, ctx: dict, log_source: str = '') -> None:
        """Evaluate every enabled rule of *source* against *ctx* and notify on a
        match (honouring each rule's per-rule cooldown).  Never raises.

        *log_source* is the external syslog source the row came from (``''`` = internal)."""
        if source == 'syslog' and _is_simulated_line(ctx):
            # A simulated device's log line (a demonstration's): on screen like any other,
            # never a rule's match — a rule notifies channels, and nobody is paged for a site
            # that does not exist.
            return
        try:
            rules = self._events_rules()
            if not rules:
                return
            now = time.time()
            default_cd = self._event_default_cooldown()
            for r in rules:
                if not r.get('enabled') or (r.get('source') or 'audit') != source:
                    continue
                if source == 'syslog' and not self._rule_watches(r, log_source):
                    continue
                if not self._event_matches(source, r, ctx):
                    continue
                # Blank/None cooldown inherits the global default; an explicit
                # value (including 0 = notify every match) overrides it.
                cd_raw = r.get('cooldown')
                if cd_raw in (None, ''):
                    cd = default_cd
                else:
                    try:
                        cd = max(0, int(cd_raw))
                    except (TypeError, ValueError):
                        cd = default_cd
                uid = r.get('id') or r.get('name') or ''
                if cd and (now - self._event_last.get(uid, 0)) < cd:
                    continue
                self._event_last[uid] = now
                st = self._event_state
                if st is not None:
                    try:
                        st.set_cooldown(uid, now)        # persist so it survives restarts
                    except Exception:  # pylint: disable=broad-except
                        pass
                self._dispatch_event(source, r, ctx)
        except Exception as exc:  # pylint: disable=broad-except
            self._dbg(f"> Events >> eval failed: {exc}", DebugLevel.error)

    @staticmethod
    def _event_matches(source: str, rule: dict, ctx: dict) -> bool:
        if source == 'audit':
            evs = rule.get('events') or []
            return (not evs) or (ctx.get('event') in evs)
        if source == 'syslog':
            sev_max = rule.get('severity_max')
            if sev_max not in (None, ''):
                try:
                    if int(ctx.get('severity', 5)) > int(sev_max):
                        return False
                except (TypeError, ValueError):
                    # A non-numeric severity_max cannot filter anything, so it does not:
                    # the rule goes on to be judged by its other conditions rather than
                    # silently matching nothing.
                    pass
            host = str(rule.get('host') or '').strip()
            if host and host not in (ctx.get('hostname'), ctx.get('source')):
                return False
            app = str(rule.get('app') or '').strip()
            if app and app != (ctx.get('app') or ''):
                return False
            return _EventsMixin._conditions_match(rule, ctx)
        return False

    @staticmethod
    def _ctx_field(ctx: dict, field: str) -> str:
        """Resolve a matcher's target field from the syslog context: a matcher can
        check the message (default), the host or the app — not only the message."""
        if field == 'host':
            return str(ctx.get('hostname') or ctx.get('source') or '')
        if field == 'app':
            return str(ctx.get('app') or '')
        if field == 'severity':
            sev = ctx.get('severity')
            return '' if sev in (None, '') else str(sev)   # numeric 0..7, for </<=/> etc.
        return str(ctx.get('message') or '')

    @staticmethod
    def _conditions_match(rule: dict, ctx: dict) -> bool:
        """Match the rule's conditions against the event context.

        New model: ``match_groups`` is OR-of-ANDs (DNF) — a list of groups, each a
        list of ``{field, type, text}`` matchers (field = message/host/app). Matches
        when ANY group fully matches (all its matchers AND).  No/empty groups → match
        all.  Falls back to the legacy single ``match_type``/``match_text``."""
        groups = rule.get('match_groups')
        if isinstance(groups, list) and groups:
            for g in groups:
                if isinstance(g, list) and g and all(
                    _EventsMixin._text_matches(
                        str(m.get('type') or 'any'), str(m.get('text') or ''),
                        _EventsMixin._ctx_field(ctx, str(m.get('field') or 'message')))
                    for m in g if isinstance(m, dict)):
                    return True
            return False
        return _EventsMixin._text_matches(
            rule.get('match_type') or 'any', str(rule.get('match_text') or ''),
            str(ctx.get('message') or ''))

    @staticmethod
    def _text_matches(match_type: str, needle: str, text: str) -> bool:
        """Apply a match (equals/contains/not_contains/starts/ends/regex). An empty
        needle or 'any' matches everything."""
        if match_type in ('', 'any') or (needle == '' and match_type != 'not_contains'):
            return True
        if match_type == 'equals':
            return text == needle
        if match_type == 'contains':
            return needle in text
        if match_type == 'not_contains':
            return needle not in text
        if match_type == 'starts':
            return text.startswith(needle)
        if match_type == 'ends':
            return text.endswith(needle)
        if match_type == 'regex':
            # Rule regexes run on text a syslog sender writes, holding the GIL: a pattern
            # that nests repetitions (saved before the editor refused them) is not run at
            # all, and every other one sees a bounded slice of the text.
            if _regex_unsafe(needle):
                return False
            try:
                return re.search(needle, text[:REGEX_MAX_TEXT]) is not None
            except re.error:
                return False
        if match_type in ('gt', 'gte', 'lt', 'lte'):
            try:
                a, b = float(text), float(needle)
            except (TypeError, ValueError):
                return False        # non-numeric value/needle → no numeric match
            if match_type == 'gt':
                return a > b
            if match_type == 'gte':
                return a >= b
            if match_type == 'lt':
                return a < b
            return a <= b           # lte
        return True

    @staticmethod
    def _event_detail_str(detail) -> str:
        if not detail:            # None / '' / {} / [] → no detail to show (not "{}")
            return ''
        if isinstance(detail, str):
            return detail
        try:
            return json.dumps(detail, ensure_ascii=False, default=str)[:500]
        except Exception:  # pylint: disable=broad-except
            return str(detail)[:500]

    def _audit_event_label(self, event: str) -> str:
        """Human-readable label for an audit event name in the configured language
        (e.g. 'syslog_started' → 'Syslog: Started'), falling back to the raw name."""
        if not event:
            return ''
        try:
            from lib.i18n import TRANSLATIONS, DEFAULT_LANG  # noqa: PLC0415
            cfg = self._read_config_file(getattr(self, '_CONFIG_FILE', None)) or {}
            lang = (cfg.get('web_admin') or {}).get('lang') or DEFAULT_LANG
            table = TRANSLATIONS.get(lang) or TRANSLATIONS.get(DEFAULT_LANG) or {}
            return (table.get('audit_events') or {}).get(event, event)
        except Exception:  # pylint: disable=broad-except
            return event

    def _dispatch_event(self, source: str, rule: dict, ctx: dict) -> None:
        from lib.core.notify.registry import channels as _registered  # noqa: PLC0415
        valid = set(_registered())
        channels = [c for c in (rule.get('channels') or []) if c in valid]
        if not channels:
            return
        from lib.core.notify.notification_dispatcher import dispatch  # noqa: PLC0415
        name = rule.get('name') or ''
        if source == 'syslog':
            status = ctx.get('severity_name') or str(ctx.get('severity', ''))
            message = ctx.get('message', '')
            item = ctx.get('hostname') or ctx.get('source') or name
            if ctx.get('log_source_name'):
                item = f"{item} ({ctx['log_source_name']})"   # which external source
            ts = ctx.get('received_at', '')
        else:  # audit
            event = ctx.get('event', '')
            status = self._audit_event_label(event)   # human-readable, translated
            message = self._event_detail_str(ctx.get('detail'))
            item = name or status
            ts = ctx.get('ts', '')
        self._dbg(f"> Events >> rule {name!r} matched {source} → {channels}",
                  DebugLevel.info)
        results = dispatch(self, kind='event', module=source, item=item,
                           status=status, message=message, timestamp=ts, channels=channels,
                           webhook_ids=rule.get('webhook_ids') or [])
        self._record_notification(rule, source, status, results or {})

    def _record_notification(self, rule: dict, source: str, status: str,
                             results: dict) -> None:
        """Persist the send result to the notification log + the rule's last-fired."""
        ok = bool(results) and all(v[0] for v in results.values())
        # Per-channel ok/err summary for the log message.
        parts = [f"{c}:{'ok' if r[0] else 'err'}" + ('' if r[0] else f'({r[1]})')
                 for c, r in results.items()]
        msg = f"{status} — " + (', '.join(parts) if parts else 'no channels')
        log = getattr(self, '_notification_log_store', None)
        if log is not None:
            try:
                log.add(rule_id=rule.get('id', ''), rule_name=rule.get('name', ''),
                        source=source, channels=list(results.keys()), ok=ok, message=msg)
            except Exception:  # pylint: disable=broad-except
                pass
        store = getattr(self, '_event_rules_store', None)
        uid = rule.get('id')
        if store is not None and uid:
            try:
                store.touch(uid, ts=time.time(), ok=ok)
            except Exception:  # pylint: disable=broad-except
                pass
