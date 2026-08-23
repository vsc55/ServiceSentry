#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The fleet, live — the routes under /api/v1/infra.

Routes registered by this file:

    GET    /api/v1/infra/hosts             every machine, its state and how much of it is watched
    GET    /api/v1/infra/hosts/<uid>       one machine: what its checks last returned, as numbers
    POST   /api/v1/infra/hosts/<uid>/collect   run this machine's checks now, and record them
    GET    /api/v1/infra/collect              the collection in flight, if any
    GET    /api/v1/infra/collect/<job_id>      how that collection is going

**Nothing here edits.** The section shows what the fleet is doing; what the fleet IS lives in
the registry, behind the permissions the registry already has. An edit route here would make
``infra_view`` a way around them — so the one non-GET endpoint changes no record of its own,
and still does not ride on ``infra_view``: it holds ``infra_collect``, because starting minutes
of polling is not the same act as looking at the result (see manifest).

**Where the data comes from — and where it does not.** Every fact is read through the domain
that owns it: the hosts store owns the machines, ``hosts.service`` owns "what state is this
host in" and "what did its checks last return" (the same functions the host modal uses), and
the history metadata owns which of a result's numbers are measurements and what they are
called. This section composes; it does not compute a second answer to any of those questions,
because a second answer is one that can disagree.

**Who may see what.** Gated by ``infra_view``, and the fleet is narrowed exactly the way
``/api/v1/hosts`` narrows it: the whole list for ``devices_view``, otherwise only the hosts
the caller holds ``server.<uid>.view`` for. One model for "which machines are mine to see",
not two — and the collect route applies the SAME narrowing on top of its own flag, so holding
``infra_collect`` never becomes a way to touch a machine you cannot see.
"""

from flask import jsonify, request, session

from lib.core.history import service as history_svc
from lib.core.hosts import service as hosts_svc
from lib.core.hosts.service import _checks_for_host
from lib.core.infra import jobs as infra_jobs
from lib.core.infra import service as infra_svc


def register(app, wa):
    infra_view_req = wa._perm_required('infra_view')

    infra_collect_req = wa._perm_required('infra_collect')

    def _may_see(uid, perms):
        """Whether this caller may see ONE machine — the same rule as the listing below."""
        return 'devices_view' in perms or f'server.{uid}.view' in perms

    def _visible(hosts, perms):
        """The hosts this caller may see — the same rule as the registry's own listing."""
        if 'devices_view' in perms:
            return hosts
        return [h for h in hosts if _may_see(h.get('uid'), perms)]

    @app.route('/api/v1/infra/hosts', methods=['GET'])
    @infra_view_req
    def api_infra_hosts():
        """The fleet: one row per machine, ordered worst first.

        The secrets never leave the store: the row is a whitelist projection (see
        ``infra.service._HOST_FIELDS``), so the per-protocol profiles — which hold the bound
        credential of everything that reaches the machine — are not in the payload at all,
        rather than being masked on the way out.
        """
        store = getattr(wa, '_hosts_store', None)
        if store is None:
            return jsonify({'hosts': [], 'summary': infra_svc.summary([])})
        # `decrypt=False`: this route never reads a profile, so there is nothing to decrypt
        # and no plaintext to mask — the projection drops the whole field either way.
        hosts = store.list(decrypt=False)
        hosts_svc.enrich_hosts(hosts, hosts_svc._host_statuses(wa),
                               hosts_svc._host_bound_modules(wa))
        rows = infra_svc.fleet(_visible(hosts, set(wa._get_session_permissions() or [])))
        return jsonify({'hosts': rows, 'summary': infra_svc.summary(rows)})

    @app.route('/api/v1/infra/hosts/<uid>', methods=['GET'])
    @infra_view_req
    def api_infra_host(uid):
        """One machine: its identity, what every check bound to it last said, and the numbers.

        ``results`` is the same shape the host modal shows (live values, falling back to
        history when a check has no live state). ``metrics`` is the subset of those results'
        data that the producing module DECLARED as a measurement, each with its label, its
        unit and the coordinates of the series behind it — so the screen can chart a value
        without knowing anything about the module that produced it.
        """
        store = getattr(wa, '_hosts_store', None)
        record = store.get(uid, decrypt=False) if store is not None else None
        if not record:
            return jsonify({'error': wa._t('host_not_found')}), 404
        perms = set(wa._get_session_permissions() or [])
        if not _may_see(uid, perms):
            return jsonify({'error': wa._t('access_denied')}), 403
        hosts_svc.enrich_hosts([record], hosts_svc._host_statuses(wa),
                               hosts_svc._host_bound_modules(wa))

        # What is bound to this host, per bare module: {bare: {item_key: label}}.
        bound: dict = {}
        for (bare, _coll), items in _checks_for_host(wa, uid).items():
            for key, item in items.items():
                bound.setdefault(bare, {})[key] = str((item or {}).get('label') or '').strip()
        status_raw = wa._read_check_status()
        # The history index, grouped by module, is the fallback for a check with no live
        # state — a host in maintenance has had its live records purged, and "nothing here"
        # would read as a machine that has never reported.
        hist_by_mod: dict = {}
        hist_store = getattr(wa, '_history', None)
        if hist_store is not None:
            try:
                for series in hist_store.get_index():
                    hist_by_mod.setdefault(series.get('module'), []).append(series)
            except Exception:                       # pylint: disable=broad-except
                pass                                # a chart is not worth failing the page for
        results = hosts_svc.build_host_status(bound, status_raw, hist_by_mod)

        lang = session.get('lang') or wa._DEFAULT_LANG
        fields = {mod: (history_svc.history_meta(wa._modules_dir, mod, lang,
                                                 wa._var_dir or '').get('fields') or {})
                  for mod in bound}
        return jsonify({'host':       infra_svc.fleet_row(record),
                        'results':    results,
                        'metrics':    infra_svc.metrics(results, fields),
                        'attributes': infra_svc.attributes(
                            results, infra_svc.sources_of(fields))})

    def _modules_to_collect(uid):
        """The enabled modules with at least one enabled check bound to this machine.

        Whole MODULES and not this host's items alone, and that is not laziness. A module runs
        once for its whole configuration and the monitor prunes, from the state it just wrote,
        every key the run did not report (``monitor._prune_orphan_status``) — so a run narrowed
        to one machine would report one machine's keys and silently delete the other thirty-
        nine's. The collection therefore costs what a scheduler cycle of those modules costs,
        which is the honest price of "give me a fresh number now".

        A module the admin disabled is skipped: "collect" must not be a way to run something
        that was turned off. A module ABSENT from the configuration is enabled — absent means
        not-added, not off (lib/modules/discovery/schemas.py), and the same asymmetry decides
        it everywhere else.
        """
        saved = wa._load_modules() or {}

        def _enabled(bare):
            for key in (bare, f'watchfuls.{bare}'):
                cfg = saved.get(key)
                if isinstance(cfg, dict):
                    return bool(cfg.get('enabled', True))
            return True
        return sorted({bare for (bare, _coll), items in _checks_for_host(wa, uid).items()
                       if _enabled(bare)
                       and any((it or {}).get('enabled') is not False for it in items.values())})

    @app.route('/api/v1/infra/hosts/<uid>/collect', methods=['POST'])
    @infra_collect_req
    def api_infra_collect(uid):
        """Run this machine's checks now, so the screen stops showing an hour-old answer.

        The section draws what the last cycle recorded, and how old that is depends on the
        interval — plus, for a device sampled by a full SNMP profile, the several minutes the
        sampling itself takes. Somebody who has just fixed a disk does not want to know what
        was true at 19:20, and until this route existed the only way to ask was the Status
        screen's "run all", which is every module for every machine.

        The SAME executor the scheduler cycle uses (``wa._run_checks`` →
        ``monitoring.executor.run_checks``), so what lands in check state and in history is
        produced by the one path that knows how to produce it. A second implementation of
        "run a check and record it" is a second answer to what a check result means; this
        section already refuses to have one of those for every other fact it shows.

        **It answers with a job id, not with results.** A collection runs for as long as the
        devices take — a NAS with a full SNMP profile is minutes — and a request held open
        that long is one a browser or a reverse proxy gives up on, leaving the operator unable
        to tell whether it worked. So the work goes on a thread and the browser polls, exactly
        as the backup copies and the MIB compile already do. That is also what lets the dialog
        be CLOSED without cancelling anything: nothing about the run depends on somebody
        watching it.
        """
        store = getattr(wa, '_hosts_store', None)
        record = store.get(uid, decrypt=False) if store is not None else None
        if not record:
            return jsonify({'error': wa._t('host_not_found')}), 404
        if not _may_see(uid, set(wa._get_session_permissions() or [])):
            return jsonify({'error': wa._t('access_denied')}), 403
        if not wa._modules_dir:
            return jsonify({'error': wa._t('checks_no_modules_dir')}), 500
        modules = _modules_to_collect(uid)
        if not modules:
            # Not an error and not a lie: a machine nobody watches has nothing to collect,
            # and reporting "done" would draw a fresh timestamp over an empty screen.
            return jsonify({'error': wa._t('infra_collect_nothing')}), 409
        # The same lock the Status screen's run takes, so the two cannot overlap — they would
        # be running the same modules against the same state table. Taken HERE and released by
        # the job: between deciding to start and the thread actually starting there must be no
        # window in which a second request also decides it is the only one.
        if not wa._check_lock.acquire(blocking=False):
            return jsonify({'error': wa._t('checks_already_running')}), 409
        try:
            job_id = infra_jobs.start_collect(
                wa, uid, str(record.get('name') or ''), modules,
                actor=session.get('username', ''), ip=request.remote_addr or '')
        except Exception:                           # pylint: disable=broad-except
            wa._check_lock.release()                # nothing started, so nothing will release
            raise
        return jsonify({'ok': True, 'job_id': job_id, 'modules': modules})

    @app.route('/api/v1/infra/collect', methods=['GET'])
    @infra_collect_req
    def api_infra_collect_running():
        """The collection in flight, or ``{}`` — what a reloaded page asks to find its way back.

        F5 does not stop a collection: the work is a thread here, and nothing about it depends
        on a browser being open. What the reload loses is the job id, so without this the bar
        disappears while the device is still being polled and the screen looks idle in the
        middle of a five-minute run.

        The answer is the server's and not the browser's, which is why this is a route and not
        a value kept in `localStorage`: a second tab, a colleague's laptop and the person who
        closed the window and came back all get the same true answer, and none of them can be
        left holding an id for a run that ended somewhere else.

        Narrowed like everything else here: a caller who may not see the machine is told there
        is nothing running, which is what "nothing you may see is running" should look like.
        """
        job = infra_jobs.running_job()
        if not job or not _may_see(job.get('host'), set(wa._get_session_permissions() or [])):
            return jsonify({})
        return jsonify(job)

    @app.route('/api/v1/infra/collect/<job_id>', methods=['GET'])
    @infra_collect_req
    def api_infra_collect_status(job_id):
        """How the collection is going: which modules have landed and which are still out.

        Behind ``infra_collect`` and not ``infra_view``, and then narrowed AGAIN to the host
        the job belongs to. A job id is a short random string, but "hard to guess" is not a
        permission — without the second check, anyone who could poll would learn the name of
        a machine they are not allowed to see, from the job of somebody who is.

        A job this process does not know is a 404, and that is the truth rather than a
        failure: the jobs live in memory, so a restart forgets them, and a browser that comes
        back to a panel that has been restarted is asking about a run that no longer exists.
        """
        job = infra_jobs.job_status(job_id)
        if not job:
            return jsonify({'error': wa._t('infra_collect_unknown_job')}), 404
        if not _may_see(job.get('host'), set(wa._get_session_permissions() or [])):
            return jsonify({'error': wa._t('access_denied')}), 403
        return jsonify(job)
