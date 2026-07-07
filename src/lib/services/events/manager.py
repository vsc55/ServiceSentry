#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-rules manager: match events and fire notifications.

A rule (lib.services.events.store.EventRulesStore) matches events from a source and,
when it fires, dispatches a ``kind='event'`` notification to the channels the rule
chose (via lib.core.notify.notification_dispatcher, channels override).

This module is intentionally Flask-free (the dispatcher is imported lazily only
when a rule actually fires) so it can be mixed into both the WebAdmin and the
standalone :class:`lib.services.syslog.service.SyslogService`.

Sources:
* ``audit``  — every audit-log entry (login_failed, daemon/syslog started/stopped,
  config_changed, host/user created/deleted, …); evaluated from `_audit_write`.
  This also covers "service status" for the embedded services (their start/stop
  are audit events).
* ``syslog`` — each received syslog message (severity/host/app/match), evaluated
  from the syslog listener's per-message hook (embedded mixin and standalone
  service alike).

Matching is best-effort and never raises into the caller's path.
"""

from __future__ import annotations

import json
import re
import threading
import time

from lib.debug import DebugLevel


class _EventsMixin:

    def _init_events(self) -> None:
        self._event_last: dict[str, float] = {}   # rule uid -> last fire ts (cooldown cache)
        self._event_rules_cache: list | None = None
        self._event_state = None                  # EventStateStore (persisted cooldown + cursor)
        self._event_worker_stop = None            # threading.Event while the worker runs

    # ── persistent state (cooldown + cursor) ──────────────────────────────────────
    def _attach_event_state(self, store) -> None:
        """Wire the persistent cooldown/cursor store and warm the cooldown cache so a
        rule does not re-fire after a restart."""
        self._event_state = store
        try:
            self._event_last = store.cooldowns()
        except Exception:  # pylint: disable=broad-except
            pass

    # ── rule cache ──────────────────────────────────────────────────────────────
    def _events_reload(self) -> None:
        """Refresh the cached rule list (call after any rule CRUD)."""
        store = getattr(self, '_event_rules_store', None)
        self._event_rules_cache = store.list() if store is not None else []

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
            try:
                n = self._event_worker_tick()
                return True, f'{n} record(s) processed'
            except Exception as exc:  # pylint: disable=broad-except
                return False, str(exc)
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
        """[(source, store)] the worker consumes — only stores that are present and
        expose the cursor API (query_since/max_id)."""
        out = []
        for source, attr in (('syslog', '_syslog_store'), ('audit', '_audit_store')):
            store = getattr(self, attr, None)
            if store is not None and hasattr(store, 'query_since') and hasattr(store, 'max_id'):
                out.append((source, store))
        return out

    def _event_worker_tick(self) -> int:
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
            return 0
        # Desired-state stop: events|enabled=false idles the worker everywhere
        # (embedded and external) without killing it, so a Services-tab stop takes
        # effect on a dedicated container too.
        if not self._events_enabled():
            return 0
        processed = 0
        for source, store in self._event_sources():
            try:
                last = st.cursor(source)
                if last is None:                 # first run → start at the tail (no replay)
                    last = store.max_id()
                    st.set_cursor(source, last)
                id_key = '_id' if source == 'audit' else 'id'
                while True:
                    rows = store.query_since(last, limit=500)
                    if not rows:
                        break
                    for rec in rows:
                        self._eval_event(source, rec)
                        processed += 1
                    last = rows[-1].get(id_key, last)
                    st.set_cursor(source, last)
                    if len(rows) < 500:
                        break
            except Exception as exc:  # pylint: disable=broad-except
                self._dbg(f"> Events >> worker tick ({source}) failed: {exc}", DebugLevel.error)
        return processed

    def _event_worker_loop(self, stop_event, poll_secs: float = 2.0) -> None:
        """Run ticks every *poll_secs* seconds until *stop_event* is set."""
        self._dbg("> Events >> worker started", DebugLevel.info)
        poll = max(0.2, float(poll_secs or 2.0))
        while not stop_event.is_set():
            self._event_worker_tick()
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
    def _eval_event(self, source: str, ctx: dict) -> None:
        """Evaluate every enabled rule of *source* against *ctx* and notify on a
        match (honouring each rule's per-rule cooldown).  Never raises."""
        try:
            rules = self._events_rules()
            if not rules:
                return
            now = time.time()
            default_cd = self._event_default_cooldown()
            for r in rules:
                if not r.get('enabled') or (r.get('source') or 'audit') != source:
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
            try:
                return re.search(needle, text) is not None
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
        if detail in (None, ''):
            return ''
        if isinstance(detail, str):
            return detail
        try:
            return json.dumps(detail, ensure_ascii=False, default=str)[:500]
        except Exception:  # pylint: disable=broad-except
            return str(detail)[:500]

    def _dispatch_event(self, source: str, rule: dict, ctx: dict) -> None:
        channels = [c for c in (rule.get('channels') or [])
                    if c in ('telegram', 'email', 'webhook')]
        if not channels:
            return
        from lib.core.notify.notification_dispatcher import dispatch  # noqa: PLC0415
        name = rule.get('name') or ''
        if source == 'syslog':
            status = ctx.get('severity_name') or str(ctx.get('severity', ''))
            message = ctx.get('message', '')
            item = ctx.get('hostname') or ctx.get('source') or name
            ts = ctx.get('received_at', '')
        else:  # audit
            status = ctx.get('event', '')
            message = self._event_detail_str(ctx.get('detail'))
            item = name or ctx.get('event', '')
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
