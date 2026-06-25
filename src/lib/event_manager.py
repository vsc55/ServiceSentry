#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-rules manager: match events and fire notifications.

A rule (lib.stores.event_rules.EventRulesStore) matches events from a source and,
when it fires, dispatches a ``kind='event'`` notification to the channels the rule
chose (via lib.web_admin.notification_dispatcher, channels override).

This module is intentionally Flask-free (the dispatcher is imported lazily only
when a rule actually fires) so it can be mixed into both the WebAdmin and the
standalone :class:`lib.syslog.service.SyslogService`.

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
import time

from lib.debug import DebugLevel


class _EventsMixin:

    def _init_events(self) -> None:
        self._event_last: dict[str, float] = {}   # rule uid -> last fire ts (cooldown)
        self._event_rules_cache: list | None = None

    # ── rule cache ──────────────────────────────────────────────────────────────
    def _events_reload(self) -> None:
        """Refresh the cached rule list (call after any rule CRUD)."""
        store = getattr(self, '_event_rules_store', None)
        self._event_rules_cache = store.list() if store is not None else []

    def _events_rules(self) -> list:
        if self._event_rules_cache is None:
            self._events_reload()
        return self._event_rules_cache or []

    def _event_default_cooldown(self) -> int:
        """Global default cooldown (s) from config (``events|cooldown``), used by
        rules that leave their own Cooldown blank.  0 on any problem."""
        try:
            cfg = self._read_config_file(getattr(self, '_CONFIG_FILE', None)) or {}
            v = (cfg.get('events') or {}).get('cooldown')
            return max(0, int(v)) if v not in (None, '') else 0
        except Exception:  # pylint: disable=broad-except
            return 0

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
            return _EventsMixin._text_matches(
                rule.get('match_type') or 'any',
                str(rule.get('match_text') or ''),
                ctx.get('message') or '')
        return False

    @staticmethod
    def _text_matches(match_type: str, needle: str, text: str) -> bool:
        """Apply a message match (contains/not_contains/starts/ends/regex). An
        empty needle or 'any' matches everything."""
        if match_type in ('', 'any') or (needle == '' and match_type != 'not_contains'):
            return True
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
        from lib.web_admin.notification_dispatcher import dispatch  # noqa: PLC0415
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
