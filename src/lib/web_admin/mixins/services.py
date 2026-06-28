#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Services dashboard: aggregate status + start/stop for the background services.

One place to see how the moving parts are doing and (for the ones this process
hosts) operate them:

* **scheduler** — the embedded monitoring loop (``_DaemonMixin``); start/stop here.
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

import os
import time

from lib.web_admin.mixins.syslog import _embedded_listener_enabled


def _embedded_event_worker_enabled() -> bool:
    """Whether this process may host the event worker (mirrors the syslog flag).

    ``SS_EVENTS_EMBEDDED=0`` keeps it out of this process so it can run as its own
    container (``events|mode=external``)."""
    v = os.environ.get('SS_EVENTS_EMBEDDED')
    if v is None:
        return True
    return v.strip().lower() not in ('0', 'false', 'no', 'off')

# A worker is "active" if a check landed within this many scheduler intervals.
_WORKER_FRESH_INTERVALS = 3
_WORKER_FRESH_FLOOR = 120          # …but at least this many seconds


class _ServicesMixin:

    # ── aggregate status ──────────────────────────────────────────────────────
    def _services_status_dict(self) -> dict:
        """Serialisable snapshot of every service for the Services dashboard."""
        out = {
            'scheduler': self._service_scheduler_status(),
            'syslog':    self._service_syslog_status(),
            'events':    self._service_events_status(),
            'worker':    self._service_worker_status(),
            'database':  self._service_database_status(),
        }
        # Only present when syslog uses its OWN database (else it shares 'database').
        syslog_db = self._service_syslog_database_status()
        if syslog_db is not None:
            out['database_syslog'] = syslog_db
        return out

    def _service_scheduler_status(self) -> dict:
        d = self._daemon_status_dict()
        return {
            'state':        'running' if d.get('running') else 'stopped',
            'running':      bool(d.get('running')),
            'controllable': True,            # always start/stop-able in-process
            'embedded':     True,
            'interval':     d.get('interval'),
            'next_in':      d.get('next_in'),
            'last_run':     d.get('last_run'),
            'autostart':    d.get('web_autostart'),
        }

    def _service_syslog_status(self) -> dict:
        cfg = self._syslog_cfg()
        srv = getattr(self, '_syslog_server', None)
        store = getattr(self, '_syslog_store', None)
        embedded = _embedded_listener_enabled()
        enabled = bool(cfg.get('enabled'))
        running = bool(srv and srv.running)
        if not embedded:
            state = 'external'               # a dedicated container owns the ports
        elif not enabled:
            state = 'disabled'               # off in config
        else:
            state = 'running' if running else 'stopped'
        return {
            'state':        state,
            'running':      running,
            'enabled':      enabled,
            'embedded':     embedded,
            # controllable only when hosted here AND enabled in config
            'controllable': embedded and enabled,
            'udp_port':     int(cfg.get('udp_port') or 0),
            'tcp_port':     int(cfg.get('tcp_port') or 0),
            'tls_port':     int(cfg.get('tls_port') or 0),
            'count':        store.count() if store else 0,
        }

    def _service_events_status(self) -> dict:
        """Decoupled event worker: drains syslog/audit by cursor and notifies on
        matching rules.  mode = embedded (this process) | external (another) | off."""
        mode = str((self._config_section('events') or {}).get('mode') or 'embedded').lower()
        env_on = _embedded_event_worker_enabled()
        running = bool(self._event_worker_running())
        embedded = mode == 'embedded' and env_on
        if mode == 'external':
            state = 'external'               # a dedicated process/container owns it
        elif mode == 'off':
            state = 'disabled'               # no evaluation
        else:
            state = 'running' if running else 'stopped'
        rules = self._events_rules() or []
        return {
            'state':         state,
            'running':       running,
            'embedded':      embedded,
            'controllable':  embedded,       # start/stop only when hosted here
            'mode':          mode,
            'poll_secs':     int((self._config_section('events') or {}).get('poll_secs') or 2),
            'rules':         len(rules),
            'rules_enabled': sum(1 for r in rules if r.get('enabled')),
        }

    def _service_worker_status(self) -> dict:
        hist = getattr(self, '_history', None)
        latest = hist.latest_ts() if hist is not None else None
        interval = self._daemon_interval or 300
        fresh_window = max(interval * _WORKER_FRESH_INTERVALS, _WORKER_FRESH_FLOOR)
        fresh = latest is not None and (time.time() - latest) <= fresh_window
        if self._daemon_running:
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
        return {
            'state':        'running' if ok else 'error',
            'controllable': False,
            'embedded':     False,
            'driver':       driver,
            'host':         db_cfg.get('host') if driver != 'sqlite' else None,
            'name':         db_cfg.get('name') if driver != 'sqlite'
                            else (db_cfg.get('path') or 'data.db'),
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
        return {
            'state':        'running' if ok else 'error',
            'controllable': False,
            'embedded':     False,
            'driver':       driver,
            'host':         sdb.get('host') if driver != 'sqlite' else None,
            'name':         sdb.get('name') if driver != 'sqlite'
                            else (sdb.get('path') or 'syslog.db'),
            'fell_back':    fell_back,
        }

    # ── control (embedded services only) ──────────────────────────────────────
    def _service_control(self, name: str, action: str) -> tuple[bool, str]:
        """Start/stop an embedded service.  Returns (ok, reason).

        ``reason`` is ``''`` on success or a short machine code on refusal
        (``unknown_service`` / ``bad_action`` / ``not_controllable`` /
        ``already`` / ``disabled``)."""
        if action not in ('start', 'stop'):
            return False, 'bad_action'

        if name == 'scheduler':
            ok = self._daemon_start() if action == 'start' else self._daemon_stop()
            return (ok, '' if ok else 'already')

        if name == 'syslog':
            if not _embedded_listener_enabled():
                return False, 'not_controllable'
            if action == 'stop':
                self._syslog_listener_stop()
                self._audit_system('syslog_stopped', {})
                return True, ''
            # start: only meaningful when enabled in config
            if not bool(self._syslog_cfg().get('enabled')):
                return False, 'disabled'
            self._syslog_apply_config()
            srv = getattr(self, '_syslog_server', None)
            ok = bool(srv and srv.running)
            if ok:
                self._audit_system('syslog_started', {})
            return ok, '' if ok else 'already'

        if name == 'events':
            mode = str((self._config_section('events') or {}).get('mode') or 'embedded').lower()
            if not (mode == 'embedded' and _embedded_event_worker_enabled()):
                return False, 'not_controllable'
            if action == 'stop':
                self._stop_event_worker()
                self._audit_system('events_worker_stopped', {})
                return True, ''
            poll = (self._config_section('events') or {}).get('poll_secs')
            self._start_event_worker(int(poll) if poll not in (None, '') else 2)
            ok = bool(self._event_worker_running())
            if ok:
                self._audit_system('events_worker_started', {})
            return ok, '' if ok else 'already'

        return False, 'unknown_service'
