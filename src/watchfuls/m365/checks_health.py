#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Microsoft 365 watchful: service health
#
"""Is Microsoft having a bad day, and does it affect the services you use?

``check_health`` reads the tenant's service-health overviews and emits **one result per
service**, so Exchange being degraded is its own check with its own state, its own alert
and its own silence — not a line buried in an aggregate.
"""

import re

from lib.providers.entraid.graph_api import parse_dt


class HealthChecks:
    """Microsoft 365 service health, one result per service."""

    # M365 service-health statuses that mean "fine" (operational or a resolved
    # incident). Anything else is a live problem — a serviceInterruption is a hard
    # outage (down), everything else (degradation/investigating/…) is a warning.
    _HEALTH_OK = frozenset({
        'serviceOperational', 'serviceRestored', 'resolvedExternal', 'falsePositive',
        'postIncidentReviewPublished', 'resolved', 'investigationSuspended'})

    def _health_state_label(self, state: str) -> str:
        """Human-readable label (with a ✅/⚠️/🔴 icon) for a Microsoft service-health
        status code, from the module's ``health_states`` i18n. Falls back to the raw
        code so an unknown/future status still shows something."""
        return self._module_lang_section('health_states').get(state) or state

    def _check_health(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """M365 service health, ONE result per service so each is its own check with
        its own state. ``health_services`` filters to named services (substring
        match); blank = all. Emits under ``<item>/health/<service-slug>``."""
        try:
            data = self._graph_json(token, '/admin/serviceAnnouncement/healthOverviews', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/health', False, self._msg('m3_health_fail', label, exc),
                       {'name': f'{label} · Service health'})
            return
        want = [s.strip().lower() for s in re.split(r'[;,]', it.get('health_services') or '') if s.strip()]
        rows = [s for s in (data.get('value') or [])
                if isinstance(s, dict) and (not want
                    or any(w in str(s.get('service') or '').lower() for w in want))]
        if not rows:
            self._emit(f'{key}/health', False, self._msg('m3_health_none', label),
                       {'name': f'{label} · Service health'}, severity='warning')
            return
        # No filter → auto-surface only the AFFECTED services (Microsoft flags them),
        # so "watch all" doesn't spam a row per healthy service. An explicit filter →
        # always show each chosen service (OK or not), so you see the ones you track.
        target = rows if want else [s for s in rows
                                    if str(s.get('status') or '') not in self._HEALTH_OK]
        if not target:                       # blank filter and everything operational
            self._emit(f'{key}/health', True, self._msg('m3_health_ok_all', label, len(rows)),
                       {'name': f'{label} · Service health'})
            return
        for s in target:
            svc = str(s.get('service') or '').strip() or '?'
            state = str(s.get('status') or '')
            slug = re.sub(r'[^a-z0-9]+', '-', svc.lower()).strip('-') or 'svc'
            state_txt = self._health_state_label(state or 'serviceOperational')
            extra = {'name': f'{label} · {svc}', 'service': svc, 'state': state}
            if state in self._HEALTH_OK:
                self._emit(f'{key}/health/{slug}', True,
                           self._msg('m3_svc_ok', label, svc, state_txt), extra)
            else:
                # serviceInterruption = hard down; any other non-OK state = warning.
                self._emit(f'{key}/health/{slug}', False, self._msg('m3_svc_bad', label, svc, state_txt),
                           extra, severity='' if state == 'serviceInterruption' else 'warning')

    def _check_announcements(self, it: dict, key: str, label: str, token: str,
                             timeout: int) -> None:
        """Service messages that require action, within ``announce_days`` days.

        Different question from service health: health says what is broken NOW, this says
        what Microsoft has told you to do before a date — a retirement, a breaking change.
        Those arrive months ahead and are read by nobody, which is exactly why the deadline
        is worth watching.
        """
        try:
            msgs = self._paged(token, '/admin/serviceAnnouncement/messages', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/announcements', False, self._msg('m3_ann_fail', label, exc),
                       {'name': f'{label} · Service messages'})
            return
        from datetime import datetime, timezone                      # noqa: PLC0415
        days = int(it.get('announce_days') or 0) or 14
        now = datetime.now(timezone.utc)
        due = []
        for m in msgs:
            when = str(m.get('actionRequiredByDateTime') or '')
            if not when:
                continue                       # nothing to be late for
            dt = parse_dt(when)
            if not dt:
                continue
            left = (dt - now).days
            # Already past is not "due soon" — it is done or missed, and either way it is
            # not the deadline this check exists to warn about.
            if 0 <= left <= days:
                due.append((left, str(m.get('title') or m.get('id') or '?')))
        due.sort()
        extra = {'name': f'{label} · Service messages', 'messages': len(msgs),
                 'due': len(due), 'days': days,
                 'soonest': due[0][1] if due else '', 'in_days': due[0][0] if due else ''}
        if due:
            self._emit(f'{key}/announcements', False,
                       self._msg('m3_ann_due', label, len(due), days, due[0][1], due[0][0]),
                       extra, severity='warning')
        else:
            self._emit(f'{key}/announcements', True,
                       self._msg('m3_ann_ok', label, len(msgs)), extra)
