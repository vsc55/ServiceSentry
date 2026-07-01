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

import threading
import time

from lib.debug import DebugLevel

# A worker is "active" if a check landed within this many scheduler intervals.
_WORKER_FRESH_INTERVALS = 3
_WORKER_FRESH_FLOOR = 120          # …but at least this many seconds

# A heartbeat instance is "alive" if seen within this window (a few beats of the
# ~10 s heartbeat); running-but-older = stale, stopped-but-older = down.
_HB_ALIVE_WINDOW = 35


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

    # ── live instances (heartbeat) ──────────────────────────────────────────────
    def _derive_instance_state(self, row: dict, now: float) -> str:
        """alive / stale / stopped / down / unknown from a heartbeat row."""
        last = row.get('last_seen')
        if not last:
            return 'unknown'
        recent = (now - last) <= _HB_ALIVE_WINDOW
        if row.get('running'):
            return 'alive' if recent else 'stale'
        return 'stopped' if recent else 'down'

    def _service_instances_list(self, service_key: str | None = None) -> list[dict]:
        """Heartbeat rows (optionally for one service), each enriched with a derived
        ``state``, ``age`` (seconds since last seen) and ``is_self`` (this process).
        Empty when the registry table is absent — so it degrades gracefully."""
        store = getattr(self, '_service_instances_store', None)
        if store is None:
            return []
        try:
            rows = (store.list_for(service_key) if service_key
                    else store.list_instances())
        except Exception:  # pylint: disable=broad-except
            return []
        from lib.services.heartbeat import hostname  # noqa: PLC0415
        import os  # noqa: PLC0415
        me_host, me_pid = hostname(), os.getpid()
        # Authoritative leader per service (the live lease), so the badge reflects
        # who holds it NOW — not the frozen `leader` flag a since-dead row carries.
        leaders: dict = {}
        lstore = getattr(self, '_service_leader_store', None)
        if lstore is not None:
            try:
                leaders = {l['service_key']: l.get('instance_id')
                           for l in lstore.list_leaders()}
            except Exception:  # pylint: disable=broad-except
                leaders = {}
        now = time.time()
        out = []
        for r in rows:
            last = r.get('last_seen')
            det = r.get('detail')
            if isinstance(det, dict) and 'leader' in det:   # leader-gated service
                det = {**det,
                       'leader': leaders.get(r.get('service_key')) == r.get('instance_id')}
            out.append({
                **r, 'detail': det,
                'derived_state': self._derive_instance_state(r, now),
                'age': (now - last) if last else None,
                'is_self': r.get('host') == me_host and r.get('pid') == me_pid,
            })
        return out

    # ── aggregate status ──────────────────────────────────────────────────────
    def _services_status_dict(self) -> dict:
        """Serialisable snapshot of every registered service for the dashboard.

        Each entry carries its own identity (``label_key`` / ``icon``) from the
        registry, so the Services tab renders it generically.  Each controllable
        service also carries ``instances`` — its live heartbeat rows, so the UI can
        show the real state of remote (non-embedded) instances in another pod."""
        out = {}
        instances_by_key: dict = {}
        for inst in self._service_instances_list():
            instances_by_key.setdefault(inst.get('service_key'), []).append(inst)
        for d in self._service_registry():
            entry = {**d.status(), 'label_key': d.label_key, 'icon': d.icon}
            if d.key in instances_by_key:
                entry['instances'] = instances_by_key[d.key]
                # For a service owned by a dedicated container, the web's own status()
                # is an idle stub (Next/Last run always '—'), so overlay the live
                # runtime from its leader instance's heartbeat.
                if entry.get('state') == 'external':
                    self._overlay_external_runtime(entry, instances_by_key[d.key])
            out[d.key] = entry
        # Only present when syslog uses its OWN database (else it shares 'database').
        # Not a registered service (it is a conditional facet of the syslog one).
        syslog_db = self._service_syslog_database_status()
        if syslog_db is not None:
            out['database_syslog'] = {**syslog_db,
                                      'label_key': 'svc_database_syslog',
                                      'icon': 'bi-database-fill-gear'}
        return out

    def _overlay_external_runtime(self, entry: dict, insts: list) -> None:
        """Fill an external service's summary from its running instance's heartbeat.

        The web hosts none of it, so its own next-run/last-run are empty; take them
        from the representative instance — the lease holder for a leader-gated service
        (monitor/events), or any live instance for an active-active one (syslog, which
        has no leader).  Its heartbeat detail carries ``next_in``/``interval`` and the
        row carries ``last_cycle_at``.  Also reflect that the remote is running."""
        # Prefer the leader (leader-gated); else any alive instance (active-active);
        # else the sole/first one — so the card's running flag and Start/Stop button
        # reflect a syslog receiver with no leader, not just leader-gated services.
        rep = next((i for i in insts if (i.get('detail') or {}).get('leader')), None)
        if rep is None:
            rep = next((i for i in insts if i.get('derived_state') == 'alive'), None)
        if rep is None:
            rep = insts[0] if insts else None
        if rep is None:
            return
        det = rep.get('detail') or {}
        patch = {'svc_next_run': det.get('next_in'),
                 'svc_last_run': rep.get('last_cycle_at')}
        for row in entry.get('detail', []):
            lk = row.get('label_key')
            if lk in patch and patch[lk] is not None:
                row['value'] = patch[lk]
        # The representative instance is alive+running → surface that as running.
        if rep.get('derived_state') == 'alive':
            entry['running'] = True

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

        # Prefer the real heartbeat: a separate monitoring instance (another
        # process/pod) that is alive is an authoritative "active worker" signal,
        # more reliable than inferring from check freshness.  Fall back to the
        # history heuristic when no heartbeat row exists (e.g. a pre-upgrade worker).
        remote = [i for i in self._service_instances_list('monitoring')
                  if not i.get('is_self')]
        remote_alive = [i for i in remote if i.get('derived_state') == 'alive']
        if embedded_running:
            state = 'embedded'               # this process is the one checking
        elif remote_alive:
            state = 'active'                 # a separate worker is alive (heartbeat)
            cyc = [i.get('last_cycle_at') or i.get('last_seen') for i in remote_alive]
            cyc = [c for c in cyc if c]
            if cyc:
                latest = max(latest or 0, max(cyc)) or latest
            fresh = True
        elif fresh:
            state = 'active'                 # a separate worker is producing checks
        elif remote:
            state = 'stale'                  # a worker was seen but is not alive now
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
        service's own ``control`` callable (the descriptor points at it) — including
        the external case: a service a dedicated container owns edits the shared
        desired-state it reconciles instead of flipping a local thread."""
        if action not in ('start', 'stop'):
            return False, 'bad_action'
        d = self._service_registry().get(name)
        if d is None:
            return False, 'unknown_service'
        if d.control is None:
            return False, 'not_controllable'   # a read-only service (worker/database)
        return d.control(action)

    # ── imperative commands (run-now / reload / clear) ──────────────────────────
    _SERVICE_COMMAND_ACTIONS = frozenset({'run_now', 'clear_status', 'reload', 'prune'})

    def _service_command(self, name: str, action: str, *, actor: str = '') -> tuple[bool, str]:
        """Enqueue a one-shot command for a service; the hosting instance (embedded
        here or a remote pod) claims + runs it.  When this process hosts the service
        embedded, drain it synchronously so the action takes effect immediately
        instead of waiting for the next heartbeat tick.

        ``reason`` is ``''`` on success (and the message carries the queued id) or a
        short code (``bad_action`` / ``unknown_service`` / ``not_controllable`` /
        ``no_queue``)."""
        if action not in self._SERVICE_COMMAND_ACTIONS:
            return False, 'bad_action'
        d = self._service_registry().get(name)
        if d is None:
            return False, 'unknown_service'
        if d.control is None:
            return False, 'not_controllable'   # read-only services take no commands
        store = getattr(self, '_service_commands_store', None)
        if store is None:
            return False, 'no_queue'
        cmd_id = store.enqueue(name, action, created_by=actor)
        # Local fast path: if we host this service embedded, run the queue now;
        # otherwise a dedicated container owns it — poke its instances so they drain
        # immediately instead of waiting for the next heartbeat tick.
        obj = self._embedded_services.get(name)
        hosted_here = False
        try:
            if obj is not None and obj.status().get('state') != 'external':
                obj._drain_commands()
                hosted_here = True
        except Exception:  # pylint: disable=broad-except
            pass
        if not hosted_here:
            self._poke_service_instances(name)
        return True, str(cmd_id)

    # ── HTTP poke (the accelerator; desired state still lives in the DB) ─────────
    def _poke_one(self, url: str, token: str) -> None:
        import urllib.request  # noqa: PLC0415
        try:
            req = urllib.request.Request(
                url, data=b'', method='POST',
                headers={'Authorization': f'Bearer {token}'})
            urllib.request.urlopen(req, timeout=2).read()  # nosec B310 (fixed scheme)
        except Exception:  # pylint: disable=broad-except
            pass            # best-effort: the periodic reconcile converges anyway

    def _poke_service_instances(self, service_key: str) -> None:
        """Best-effort ``POST /control/reconcile`` to every reachable remote instance
        of *service_key*, so a desired-state change / queued command takes effect
        now.  No-op when no control token is set (poke disabled) — the periodic
        reconcile still converges."""
        try:
            from lib.services.control_server import control_token  # noqa: PLC0415
            token = control_token()
            if not token:
                return
            for inst in self._service_instances_list(service_key):
                url = inst.get('control_url')
                # Poke every REACHABLE instance — one recently heard from, whatever its
                # run state. Crucially this includes 'stopped' (heartbeating but not
                # running): that is exactly the instance a Services-tab *start* must
                # wake to bind/spin up now, instead of waiting for its watch tick. Only
                # 'down'/'unknown' (not seen recently) are skipped as unreachable.
                if (not url or inst.get('is_self')
                        or inst.get('derived_state') not in ('alive', 'stale', 'stopped')):
                    continue
                threading.Thread(
                    target=self._poke_one,
                    args=(url.rstrip('/') + '/control/reconcile', token),
                    daemon=True).start()
        except Exception:  # pylint: disable=broad-except
            pass

    def _poke_services_for_config(self, changed) -> None:
        """After a config save, poke the external instances of every service whose
        section changed, so a desired-state edit (e.g. ``monitoring|enabled``)
        converges immediately on the remote worker."""
        if not changed:
            return
        keys = set(self._embedded_services.keys())
        affected = set()
        for path in changed:
            section = str(path).split('|', 1)[0]
            if section in keys:
                affected.add(section)
            elif section == 'syslog_db':
                affected.add('syslog')
        for key in affected:
            self._poke_service_instances(key)
