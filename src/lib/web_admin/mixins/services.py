#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Services dashboard: aggregate status + start/stop for the background services.

One place to see how the moving parts are doing and (for the ones this process
hosts) operate them:

* **scheduler** — the embedded monitoring loop (``_MonitoringMixin``); start/stop here.
* **syslog** — the embedded syslog listener (``_SyslogMixin``); start/stop here
  when it runs in-process.  When a dedicated container owns it
  (``SS_SYSLOG_EMBEDDED=0``) it is shown read-only.
* **worker** — a *separate* monitoring process/container; detected from recent
  check activity in the shared DB (read-only — it lives elsewhere).
* **database** — the shared datastore; driver + a live connectivity probe.

Only the embedded services are controllable; everything that lives in another
process is reported but never operated from here.
"""

from __future__ import annotations

import time

from lib.debug import DebugLevel

# A worker is "active" if a check landed within this many scheduler intervals.
_WORKER_FRESH_INTERVALS = 3
_WORKER_FRESH_FLOOR = 120          # …but at least this many seconds


class _ServicesMixin:

    # ── central registry ───────────────────────────────────────────────────────
    def _service_registry(self):
        """The central :class:`ServiceRegistry` (built once per instance).

        Every background service registers a descriptor here, so the status
        aggregation, the control endpoint, the start-up log and the
        ``_CONTROLLABLE`` set all iterate one list instead of hard-coding a branch
        per service.  Adding a service is a single ``register()`` call."""
        reg = getattr(self, '_svc_registry', None)
        if reg is not None:
            return reg
        from lib.services.registry import ServiceRegistry  # noqa: PLC0415
        from lib.services.base import ServiceDescriptor  # noqa: PLC0415
        from lib.services import discover_embedded_services  # noqa: PLC0415
        reg = ServiceRegistry()
        # Discovered services: each lib/services package self-describes via
        # EMBEDDED_SERVICE and provides its embedded object (composition) in
        # ``self._embedded_services``; status/control come from that object.  Drop a
        # package with EMBEDDED_SERVICE + an ``embedded`` module → it appears here,
        # no edit to this host.
        for meta in discover_embedded_services():
            obj = self._embedded_services.get(meta['key'])
            if obj is None:
                continue                       # no embedded object built for it
            control = obj.control if meta.get('controllable') else None
            reg.register(ServiceDescriptor(
                meta['key'], meta['label_key'], meta['icon'],
                status=obj.status, control=control))
        # Read-only host views (NOT lib/services packages): a separate worker
        # process detected from the DB + the datastore connectivity probe.
        reg.register(ServiceDescriptor(
            'worker', 'svc_worker', 'bi-cpu', status=self._service_worker_status))
        reg.register(ServiceDescriptor(
            'database', 'svc_database', 'bi-database', status=self._service_database_status))
        self._svc_registry = reg
        return reg

    # ── aggregate status ──────────────────────────────────────────────────────
    def _services_status_dict(self) -> dict:
        """Serialisable snapshot of every registered service for the dashboard.

        Each entry carries its own identity (``label_key`` / ``icon``) from the
        registry, so the Services tab renders it generically."""
        out = {}
        for d in self._service_registry():
            out[d.key] = {**d.status(), 'label_key': d.label_key, 'icon': d.icon}
        # Only present when syslog uses its OWN database (else it shares 'database').
        # Not a registered service (it is a conditional facet of the syslog one).
        syslog_db = self._service_syslog_database_status()
        if syslog_db is not None:
            out['database_syslog'] = {**syslog_db,
                                      'label_key': 'svc_database_syslog',
                                      'icon': 'bi-database-fill-gear'}
        return out

    # ── startup log ───────────────────────────────────────────────────────────
    def _log_services_startup(self) -> None:
        """Log a one-line startup state for each controllable service this process
        hosts — so the boot log shows what came up *and* what came up
        stopped/disabled/external, not only the services that started running.
        Iterates the registry, so a new service is logged without touching this."""
        _texts = {
            'running':  'running',
            'stopped':  'stopped',
            'disabled': 'disabled (off in config)',
            'external': 'external (a dedicated process/container owns it)',
        }
        for d in self._service_registry():
            if d.control is None:       # read-only views are not "started" here
                continue
            st = d.status()
            state = st.get('state')
            extra = ''
            if state == 'running':
                if st.get('interval') is not None:
                    extra = f" (interval={st['interval']}s)"
                elif st.get('poll_secs') is not None:
                    extra = f" (poll={st['poll_secs']}s)"
                elif st.get('udp_port') or st.get('tcp_port') or st.get('tls_port'):
                    _p = [f'{l}:{st.get(k)}' for l, k in
                          (('udp', 'udp_port'), ('tcp', 'tcp_port'), ('tls', 'tls_port')) if st.get(k)]
                    extra = f" ({', '.join(_p)})"
            self._dbg(f"> Services >> {d.key}: {_texts.get(state, str(state))}{extra}",
                      DebugLevel.info)

    def _service_worker_status(self) -> dict:
        """A *separate* monitoring process (``--monitor``/worker container) detected
        from recent check activity in the shared DB — read-only (it lives elsewhere).
        ``embedded`` here means *this* process is the one checking."""
        hist = getattr(self, '_history', None)
        latest = hist.latest_ts() if hist is not None else None
        mon = self._embedded_services.get('monitoring')
        interval = (getattr(mon, 'interval', None) or 300)
        embedded_running = bool(mon is not None and mon.running)
        fresh_window = max(interval * _WORKER_FRESH_INTERVALS, _WORKER_FRESH_FLOOR)
        fresh = latest is not None and (time.time() - latest) <= fresh_window
        if embedded_running:
            state = 'embedded'               # this process is the one checking
        elif fresh:
            state = 'active'                 # a separate worker is producing checks
        elif latest is not None:
            state = 'stale'                  # checks exist but none recently
        else:
            state = 'unknown'                # never seen any check
        return {
            'state':         state,
            'controllable':  False,          # lives in another process
            'embedded':      False,
            'last_activity': latest,
            'fresh':         fresh,
            'detail': [
                {'label_key': 'svc_last_activity', 'value': latest, 'fmt': 'ago'},
                {'label_key': 'svc_recent_checks',
                 'value_key': 'svc_yes' if fresh else 'svc_no'},
            ],
        }

    def _service_database_status(self) -> dict:
        from lib.config.manager import bootstrap_database_cfg  # noqa: PLC0415
        db_cfg = bootstrap_database_cfg(self._read_config_file(self._CONFIG_FILE)) or {}
        driver = (db_cfg.get('driver') or 'sqlite').lower()
        conn = getattr(self, '_db_connector', None)
        ok = False
        try:
            if conn is not None:
                conn.fetchone('SELECT 1')
                ok = True
        except Exception:  # pylint: disable=broad-except
            ok = False
        name = (db_cfg.get('name') if driver != 'sqlite'
                else (db_cfg.get('path') or 'data.db'))
        host = db_cfg.get('host') if driver != 'sqlite' else None
        return {
            'state':        'running' if ok else 'error',
            'controllable': False,
            'embedded':     False,
            'driver':       driver,
            'host':         host,
            'name':         name,
            'detail': [
                {'label_key': 'svc_driver', 'value': driver or '—'},
                {'label_key': 'svc_host', 'value': host or '—'},
                {'label_key': 'svc_db_name', 'value': name or '—'},
            ],
        }

    def _service_syslog_database_status(self) -> dict | None:
        """Status of the DEDICATED syslog database, or None when syslog shares the
        system DB.  ``build_syslog_connector`` only builds a separate connector when
        ``syslog_db.enabled`` — otherwise it returns the main one, so there is no
        second connection to report."""
        from lib.config.manager import overlay_section_env  # noqa: PLC0415
        sdb = overlay_section_env('syslog_db', self._config_section('syslog_db')) or {}
        if not sdb.get('enabled'):
            return None
        driver = (sdb.get('driver') or 'sqlite').lower()
        conn = getattr(self, '_syslog_db_connector', None)
        main = getattr(self, '_db_connector', None)
        # A dedicated config that fell back to the main connector (build error) is
        # NOT actually using its own database — surface that as an error.
        fell_back = conn is not None and conn is main
        ok = False
        if not fell_back:
            try:
                if conn is not None:
                    conn.fetchone('SELECT 1')
                    ok = True
            except Exception:  # pylint: disable=broad-except
                ok = False
        host = sdb.get('host') if driver != 'sqlite' else None
        name = (sdb.get('name') if driver != 'sqlite'
                else (sdb.get('path') or 'syslog.db'))
        detail = [
            {'label_key': 'svc_driver', 'value': driver or '—'},
            {'label_key': 'svc_host', 'value': host or '—'},
            {'label_key': 'svc_db_name', 'value': name or '—'},
        ]
        if fell_back:
            detail.append({'label_key': 'svc_status', 'value_key': 'svc_db_fell_back'})
        return {
            'state':        'running' if ok else 'error',
            'controllable': False,
            'embedded':     False,
            'driver':       driver,
            'host':         host,
            'name':         name,
            'fell_back':    fell_back,
            'detail':       detail,
        }

    # ── control ─────────────────────────────────────────────────────────────────
    def _service_control(self, name: str, action: str) -> tuple[bool, str]:
        """Start/stop a service — dispatched through the central registry.

        ``reason`` is ``''`` on success or a short machine code on refusal
        (``unknown_service`` / ``bad_action`` / ``not_controllable`` /
        ``already`` / ``disabled``).  Per-service guards/audit live in the
        ``_control_*`` methods the descriptors point at."""
        if action not in ('start', 'stop'):
            return False, 'bad_action'
        d = self._service_registry().get(name)
        if d is None:
            return False, 'unknown_service'
        if d.control is None:
            return False, 'not_controllable'   # a read-only service (worker/database)
        return d.control(action)
