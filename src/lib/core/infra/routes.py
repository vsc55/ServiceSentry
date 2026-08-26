#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The fleet, live — the routes under /api/v1/infra.

Routes registered by this file:

    GET    /api/v1/infra/hosts             every machine, its state and how much of it is watched
    GET    /api/v1/infra/hosts/<uid>       one machine: what its checks last returned, as numbers
    POST   /api/v1/infra/hosts/<uid>/collect   run this machine's checks now, and record them
    POST   /api/v1/infra/hosts/<uid>/watch     say one row of it is worth an alert (or stop)
    GET    /api/v1/infra/collect              the collection in flight, if any
    GET    /api/v1/infra/collect/<job_id>      how that collection is going
    GET    /api/v1/infra/map              how the fleet is wired, out of what it answered
    GET    /api/v1/infra/map-layout       where the caller put the boxes, on either map
    PUT    /api/v1/infra/map-layout       …and where they want them kept

**Nothing here edits the FLEET.** The section shows what the fleet is doing; what the fleet IS
lives in the registry, behind the permissions the registry already has. An edit route here
would make ``infra_view`` a way around them — so no endpoint here creates, changes or deletes
a machine. The collect route does not even ride on ``infra_view``: it holds ``infra_collect``,
because starting minutes of polling is not the same act as looking at the result (see
manifest). The map arrangement writes one key on the CALLER's own account, which is where a
dashboard layout already lives: it is a preference about a picture, and it can name no machine
it was not already allowed to see.

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
from lib.core.hosts import profiles as host_profiles
from lib.core.hosts import store as host_store_mod
from lib.core.infra import jobs as infra_jobs
from lib.core.infra import service as infra_svc
from lib.core.infra import evidence as infra_evidence
from lib.core.infra import topology as infra_topology


def register(app, wa):
    infra_view_req = wa._perm_required('infra_view')

    infra_collect_req = wa._perm_required('infra_collect')
    infra_watch_req = wa._perm_required('infra_watch')

    def _may_see(uid, perms):
        """Whether this caller may see ONE machine — the same rule as the listing below."""
        return 'devices_view' in perms or f'server.{uid}.view' in perms

    def _visible(hosts, perms):
        """The hosts this caller may see — the same rule as the registry's own listing."""
        if 'devices_view' in perms:
            return hosts
        return [h for h in hosts if _may_see(h.get('uid'), perms)]

    def _said_sources(bound_by_host):
        """``sources_of`` for whichever modules the fleet has a check bound to.

        The names — and the BRANDS — of the things that answer come from the modules, and
        asking one costs a pass over everything it has installed: 30 ms for the SNMP watchful,
        which loads its whole profile catalogue to answer. So it is asked once for the whole
        fleet rather than once per machine, and only for the modules something is actually
        bound to: an installation with no SNMP pays nothing, which is most of them.
        """
        mods = {m for mods in (bound_by_host or {}).values() for m in mods}
        lang = session.get('lang') or wa._DEFAULT_LANG
        named = {mod: (history_svc.history_meta(wa._modules_dir, mod, lang,
                                                wa._var_dir or '') or {}).get('sources') or {}
                 for mod in sorted(mods)}
        return infra_svc.sources_of({}, named)

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
        bound = hosts_svc._host_bound_modules(wa)
        hosts_svc.enrich_hosts(
            hosts, hosts_svc._host_statuses(wa), bound,
            infra_svc.fleet_identity(wa._read_check_status(), hosts, _said_sources(bound)))
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
        statuses, bound_mods = hosts_svc._host_statuses(wa), hosts_svc._host_bound_modules(wa)
        hosts_svc.enrich_hosts([record], statuses, bound_mods)

        # What is bound to this host, per bare module: {bare: {item_key: label}}.
        bound: dict = {}
        for (bare, _coll), items in _checks_for_host(wa, uid).items():
            for key, item in items.items():
                bound.setdefault(bare, {})[key] = str((item or {}).get('label') or '').strip()
        status_raw = wa._read_check_status()
        # …and what a module recorded about the HOST itself, with no check behind it: a device
        # read because the registry says it is one. The status column has always counted those
        # and this page did not, so a switch sampled that way went red in the fleet and showed
        # four empty tabs when opened — the machine with the numbers being the one nobody could
        # see. One source for both, so they cannot disagree again.
        sampled = hosts_svc.host_sampled_keys(status_raw, uid)
        # …and, where the live state says nothing about the device ITSELF, what the history
        # remembers. A machine in maintenance has its checks skipped, so the cycle after that
        # prunes every key the module stopped returning — which for a device sampled through
        # the registry is all of them, leaving this page nothing to build a row out of.
        # Reported from the screen: a switch put into maintenance opened onto four empty tabs,
        # with a year of history sitting behind it and `purge_maintenance_states` keeping it
        # for exactly this.
        #
        # Only then: this is the unfiltered read of the history index, and a machine whose
        # live state is there does not need it.
        every_series = None
        hist_store = getattr(wa, '_history', None)
        if not sampled and hist_store is not None:
            try:
                every_series = hist_store.latest_by_series() or []
            except Exception:                       # pylint: disable=broad-except
                every_series = []
            sampled = hosts_svc.host_recorded_keys(every_series, uid)
        for bare, keys in sampled.items():
            for key in keys:
                bound.setdefault(bare, {}).setdefault(key, '')
        # The last sample of each series, as the fallback for a check with no live state —
        # a host in maintenance has had its live records purged, and "nothing here" would
        # read as a machine that has never reported.
        #
        # `latest_by_series` and not `get_index`: the index also counts the samples, dates the
        # first one and works out the uptime, none of which this page reads, and paying for
        # them is a second pass over the whole history plus a sort of it. Reported from the
        # screen as "clicking a device takes seconds, and the URL changes before anything
        # does" — ~700 ms of that was this call, on a 54.000-row history, for four fields.
        #
        # …and only the modules bound to THIS machine. The fallback can only ever contribute
        # a series that maps to one of its own checks, so the rest of the fleet's is fetched
        # and discarded.
        hist_by_mod: dict = {}
        if hist_store is not None and bound:
            try:
                # Reused where the block above already had to read the lot: two passes over
                # the history for one click is one more than anybody needs.
                rows = (every_series if every_series is not None
                        else hist_store.latest_by_series(list(bound)))
                for series in rows:
                    hist_by_mod.setdefault(series.get('module'), []).append(series)
            except Exception:                       # pylint: disable=broad-except
                pass                                # a chart is not worth failing the page for
        results = hosts_svc.build_host_status(bound, status_raw, hist_by_mod)

        lang = session.get('lang') or wa._DEFAULT_LANG
        meta = {mod: history_svc.history_meta(wa._modules_dir, mod, lang, wa._var_dir or '')
                for mod in bound}
        fields = {mod: (m or {}).get('fields') or {} for mod, m in meta.items()}
        # …and what to CALL each thing that answered. A profile of pure identity facts charts
        # nothing, so it is in no field map and its card was headed with its raw id.
        named = {mod: (m or {}).get('sources') or {} for mod, m in meta.items()}
        said = infra_svc.sources_of(fields, named)
        # …and who made this one, off the scan the page has already taken. Through
        # `enrich_hosts` and not by hand: it is the one place that knows the device's word is
        # allowed to answer `auto` and never to overrule a setting somebody chose, and a second
        # copy of that rule here is the copy that would drift. The two reads it needs are the
        # ones taken above, so this pass is dict work.
        hosts_svc.enrich_hosts([record], statuses, bound_mods,
                               infra_svc.fleet_identity(status_raw, [record], said))
        # What to call a module that groups nothing — its own name, out of its own lang
        # file, so the core still holds no string naming one.
        names = {mod: history_svc._pretty_name(wa._modules_dir, mod, lang) for mod in bound}
        # `results` is the one thing on this page no other tab is built from, which is what
        # makes withholding it possible at all: the measurements and the attributes below are
        # what Details draws, so they go whatever the other tab flags say. A flag that looks
        # like a wall and is a curtain is worse than none — see the domain manifest.
        return jsonify({'host':       infra_svc.fleet_row(record),
                        'results':    results if 'infra_results_view' in perms else [],
                        'metrics':    infra_svc.metrics(results, fields, names),
                        'attributes': infra_svc.attributes(results, said)})

    @app.route('/api/v1/infra/hosts/<uid>/watch', methods=['POST'])
    @infra_watch_req
    def api_infra_watch(uid):
        """Say that one row of this machine is worth an alert, or stop saying it.

        A switch port that is down may be a PC switched off at seven — which is not news, and
        made a rack of half-populated switches permanently red — or it may be the link to a
        server, which is a phone call. Nothing in any MIB separates the two: what is at the
        other end of the cable is knowledge about THIS installation, and this is where it is
        recorded.

        The one thing on this section that WRITES, and it deliberately does not write the
        registry: no name, no address, no credential — one flag against one row, behind a
        permission of its own. The narrowing every other route here applies still applies: a
        machine you may not see is not a machine you may set a flag on.
        """
        store = getattr(wa, '_hosts_store', None)
        record = store.get(uid, decrypt=False) if store is not None else None
        if not record:
            return jsonify({'error': wa._t('host_not_found')}), 404
        if not _may_see(uid, set(wa._get_session_permissions() or [])):
            return jsonify({'error': wa._t('access_denied')}), 403
        body = request.get_json(silent=True) or {}
        module = str(body.get('module') or '').strip()
        row = str(body.get('row') or '').strip()
        if not module or not row:
            return jsonify({'error': wa._t('infra_watch_bad')}), 400
        on = bool(body.get('on'))
        # …and what the row IS, when the screen says so. Checked against the store's own
        # vocabulary rather than passed through: a word the core does not act on is a mark that
        # reads as a promise and does nothing.
        role = host_store_mod.HostsStore.watch_role(body.get('role'))
        actor = session.get('username', '')
        if not store.set_watch(uid, module, row, on, role=role, actor=actor):
            return jsonify({'error': wa._t('save_failed')}), 500
        wa._audit('infra_watch', detail={'host': record.get('name') or uid,
                                         'module': module, 'row': row,
                                         'role': role, 'on': bool(on)})
        return jsonify({'ok': True, 'watch': (store.get(uid, decrypt=False) or {}).get('watch')})

    @app.route('/api/v1/infra/map', methods=['GET'])
    @infra_view_req
    def api_infra_map():
        """How the fleet is wired together, as far as what it has already answered can say.

        Nothing here asks a device anything: the networks come from the addresses each machine
        reported and the prefix beside each one, and the edges from the next hop each machine
        uses for what it cannot deliver itself. A map that cost a fresh conversation with forty
        machines would be a map somebody turns off.

        What it is NOT is a cable diagram. "These two have an address on one network" is a
        statement about reachability, not about a port on a switch — that is LLDP, which only
        the machines running an agent for it answer. Every edge says how it was arrived at so
        the screen can draw the difference instead of flattening it.
        """
        store = getattr(wa, '_hosts_store', None)
        if store is None:
            return jsonify({'networks': [], 'nodes': [], 'edges': [], 'unplaced': []})
        hosts = store.list(decrypt=False)
        status_seed = wa._read_check_status()
        bound_mods = hosts_svc._host_bound_modules(wa)
        hosts_svc.enrich_hosts(
            hosts, hosts_svc._host_statuses(wa), bound_mods,
            infra_svc.fleet_identity(status_seed, hosts, _said_sources(bound_mods)))
        hosts = _visible(hosts, set(wa._get_session_permissions() or []))
        # Read ONCE for the whole fleet and not once per machine: the state table and the
        # history index are the two expensive reads on this path, and a map of forty machines
        # would be forty of each.
        status_raw = wa._read_check_status()
        hist_by_mod: dict = {}
        # …and flat, for the other question this same read answers: WHICH machines the history
        # remembers at all. A machine in maintenance has its live keys pruned, so without this
        # it falls off the map entirely — the same disappearance the device page had.
        every_series: list = []
        hist_store = getattr(wa, '_history', None)
        if hist_store is not None:
            try:
                every_series = list(hist_store.get_index())
                for series in every_series:
                    hist_by_mod.setdefault(series.get('module'), []).append(series)
            except Exception:                       # pylint: disable=broad-except
                pass                                # a map is not worth failing the page for
        lang = session.get('lang') or wa._DEFAULT_LANG
        meta_cache: dict = {}
        attrs_by_host: dict = {}
        for host in hosts:
            uid = str(host.get('uid') or '')
            bound: dict = {}
            for (bare, _coll), items in _checks_for_host(wa, uid).items():
                for key, item in items.items():
                    bound.setdefault(bare, {})[key] = str((item or {}).get('label') or '').strip()
            # A device sampled through the registry has no item to be bound BY, and its
            # addresses are exactly what places it on the map.
            sampled = (hosts_svc.host_sampled_keys(status_raw, uid)
                       or hosts_svc.host_recorded_keys(every_series, uid))
            for bare, keys in sampled.items():
                for key in keys:
                    bound.setdefault(bare, {}).setdefault(key, '')
            for mod in bound:
                if mod not in meta_cache:
                    meta_cache[mod] = history_svc.history_meta(
                        wa._modules_dir, mod, lang, wa._var_dir or '')
            results = hosts_svc.build_host_status(bound, status_raw, hist_by_mod)
            fields = {mod: (meta_cache.get(mod) or {}).get('fields') or {} for mod in bound}
            # …and what to CALL each thing that answered, which a profile of pure identity
            # facts can only say here: it charts nothing, so it is in no field map.
            named = {mod: (meta_cache.get(mod) or {}).get('sources') or {} for mod in bound}
            attrs_by_host[uid] = infra_svc.attributes(
                results, infra_svc.sources_of(fields, named))
        # What devices SAW, which is what places a machine on a switch port when it speaks
        # no LLDP. Its own store because a forwarding table is hundreds of volatile rows that
        # are not checks (see lib/core/infra/evidence.py); read here in one go for every kind.
        evidence: dict = {}
        db = getattr(wa, '_db_connector', None) or getattr(wa, '_db', None)
        if db is not None:
            try:
                store = infra_evidence.EvidenceStore(db)
                for kind in ('fdb', 'bridgeport', 'ifname', 'arp'):
                    evidence[kind] = store.by_device(kind)
            except Exception:                       # pylint: disable=broad-except
                evidence = {}                       # a map without the ports beats no map
        return jsonify(infra_topology.build(hosts, attrs_by_host, evidence))

    @app.route('/api/v1/infra/map-layout', methods=['GET', 'PUT'])
    @infra_view_req
    def api_infra_map_layout():
        """Where the caller has PUT the boxes, on each of the two maps.

        The browser keeps its own copy as the hand moves them, which is what makes dragging
        instant and what makes it work with no account at all. THIS is the copy that follows
        somebody to another machine — and it is written by a button, on purpose: an
        arrangement persisted on every pointer move would be a round trip per frame.

        Gated by `devices_view` and nothing more: you can only arrange a map you can see, and
        where a box sits is a fact about a picture rather than about the fleet.
        """
        user = wa._users.get(session.get('username', ''))
        if user is None:
            return jsonify({'layouts': {}})
        if request.method == 'GET':
            return jsonify({'layouts': infra_svc.map_layouts_of(user)})
        data, err = wa._require_json()
        if err:
            return err
        layouts = infra_svc.normalise_map_layouts(data.get('layouts'))
        # An empty arrangement is not one to keep: it is "put it back the way the map had it",
        # and storing `{}` would leave the account holding a decision nobody made.
        if layouts:
            user['infra_map_layouts'] = layouts
        else:
            user.pop('infra_map_layouts', None)
        # …and the field this replaced goes with the first save that carries it forward, so
        # the two cannot drift into disagreeing about where somebody put a box.
        for was in infra_svc.LINK_LAYOUT_WAS.values():
            user.pop(was, None)
        wa._persist_users()
        wa._audit('infra_link_layout',
                  detail={'boxes': sum(len(v) for v in layouts.values())})
        return jsonify({'ok': True, 'layouts': layouts})

    def _modules_to_collect(uid, record=None):
        """The enabled modules with at least one enabled check bound to this machine.

        The modules are then RUN narrowed to this machine (``_run_checks(only_host=…)``), which
        is what the button says it does. It did not always: a module ran with its whole
        configuration, because the monitor prunes from the state it just wrote every key the
        run did not report (``monitor._prune_orphan_status``) — so a narrowed run would have
        deleted the other thirty-nine machines' live state. The prune is now off for a narrowed
        run, which is the difference between "this run did not find that key" and "this run was
        never asked about it". Reported from the screen: a collection of one NAS sat on "still
        working" with six devices in it, five of which nobody had asked about, and could not
        land because one of THOSE was not answering.

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
        out = {bare for (bare, _coll), items in _checks_for_host(wa, uid).items()
               if _enabled(bare)
               and any((it or {}).get('enabled') is not False for it in items.values())}
        # A device the registry alone makes a device has no item to be enabled, and refusing
        # to collect it would be the button saying "nothing to run" about a machine whose
        # numbers are on the screen behind it.
        out |= {bare for bare in hosts_svc.host_sampled_keys(wa._read_check_status(), uid)
                if _enabled(bare)}
        # …and one that has never been sampled has recorded nothing to be found that way. The
        # line above reads the RESULTS, so it can only name a module that has already run:
        # a device whose module item was removed a minute ago, and which the registry alone
        # now makes a device, offered its ping and left out the collection that is the reason
        # anybody pressed the button. What the host's own record DECLARES answers before the
        # first cycle, which is when it is asked.
        out |= {bare for bare in host_profiles.profile_sampled_modules(record or {})
                if _enabled(bare)}
        return sorted(out)

    def _modules_to_collect_all():
        """What watches the DEVICES IN THE LIST — the union of what each of them would run.

        The button lives in the device list and that is what it is about. Written first as
        "every enabled module with anything to run", it swept up the modules that watch no
        device at all — a Microsoft 365 tenant, an Azure subscription — and the dialog opened
        on seventeen lines for a fleet of seventeen machines. Reported from the screen in
        exactly those words: "I mean the devices in the infrastructure list".

        So it is the same question `_modules_to_collect` answers, asked of every machine and
        unioned — which also means the two can never disagree about what watches a device.
        The configuration and the live state are read ONCE here rather than per machine: the
        per-device path re-reads both, which is right for one host and is forty times the work
        for a fleet.
        """
        saved = wa._load_modules() or {}

        def _enabled(bare):
            for key in (bare, f'watchfuls.{bare}'):
                cfg = saved.get(key)
                if isinstance(cfg, dict):
                    return bool(cfg.get('enabled', True))
            return True

        store = getattr(wa, '_hosts_store', None)
        try:
            hosts = store.list(decrypt=False) if store is not None else []
        except Exception:                       # pylint: disable=broad-except
            hosts = []
        uids = {str((h or {}).get('uid') or '').strip() for h in hosts or ()}
        uids.discard('')
        if not uids:
            return []

        def _binds(item):
            """Whether one item watches a machine that is in the list.

            BOTH bindings, because there are two and the second is not a special case: a
            cluster check — a keepalived VIP, a Proxmox cluster — is ONE item bound to several
            machines through ``host_uids``, which is the core's own convention (host_binding,
            authz and the permission service all key on it). Read only as ``host_uid`` it
            binds to nothing, so a module watching eight machines on this very screen was left
            out of the button that says it collects them.
            """
            if not isinstance(item, dict) or item.get('enabled') is False:
                return False
            if str(item.get('host_uid') or '').strip() in uids:
                return True
            many = item.get('host_uids')
            return isinstance(many, list) and any(str(u).strip() in uids for u in many)

        out = set()
        # An enabled item bound to a machine that is IN THE LIST. Bound to nothing, or to a
        # machine the registry no longer has, is not a device on this screen.
        for mod_key, mod_cfg in saved.items():
            if not isinstance(mod_cfg, dict):
                continue
            bare = str(mod_key).strip().rsplit('.', 1)[-1]
            if bare in out or not _enabled(bare):
                continue
            for coll, items in mod_cfg.items():
                if str(coll).startswith('__') or not isinstance(items, dict):
                    continue
                if any(_binds(it) for it in items.values()):
                    out.add(bare)
                    break
        # The devices the REGISTRY alone makes devices: no item anywhere to be found above,
        # and the numbers on the screen behind the button come from them.
        status_raw = wa._read_check_status()
        for host in hosts or ():
            out |= {b for b in host_profiles.profile_sampled_modules(host) if _enabled(b)}
            out |= {b for b in hosts_svc.host_sampled_keys(
                status_raw, str((host or {}).get('uid') or '')) if _enabled(b)}
        return sorted(out)

    @app.route('/api/v1/infra/collect', methods=['POST'])
    @infra_collect_req
    def api_infra_collect_all():
        """Collect from the WHOLE fleet, from the list rather than from one machine.

        The per-device button narrows its run to that device (`only_host`), which is what
        makes it quick and what keeps it from walking somebody else's rack. This is the other
        question — "refresh everything" — and it is the un-narrowed run: every module with its
        whole configuration, which is what a scheduler cycle is. The orphan prune therefore
        stays ON, because this run really did cover everything.

        Behind `devices_view` as well as `infra_collect`, and that is the point of asking
        twice. `infra_collect` says which ACT you may perform; a run over the whole fleet
        polls machines a narrowed operator may not be allowed to see, so the flag that says
        "you see the whole fleet" is what decides you may refresh it. Somebody scoped to three
        racks still has the per-device button, which is scoped the same way they are.
        """
        if 'devices_view' not in set(wa._get_session_permissions() or []):
            return jsonify({'error': wa._t('access_denied')}), 403
        modules = _modules_to_collect_all()
        if not modules:
            return jsonify({'error': wa._t('infra_collect_nothing_all')}), 409
        if not wa._modules_dir:
            return jsonify({'error': wa._t('checks_no_modules_dir')}), 500
        if not wa._check_lock.acquire(blocking=False):
            return jsonify({'error': wa._t('checks_already_running')}), 409
        try:
            job_id = infra_jobs.start_collect(
                wa, '', wa._t('infra_collect_all_scope'), modules,
                actor=session.get('username', ''), ip=request.remote_addr or '',
                lang=session.get('lang', '') or wa._DEFAULT_LANG)
        except Exception:                       # pylint: disable=broad-except
            wa._check_lock.release()
            raise
        return jsonify({'ok': True, 'job_id': job_id, 'modules': modules})

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
        modules = _modules_to_collect(uid, record)
        if not modules:
            # Not an error and not a lie: a machine nobody watches has nothing to collect,
            # and reporting "done" would draw a fresh timestamp over an empty screen.
            return jsonify({'error': wa._t('infra_collect_nothing')}), 409
        # AFTER deciding there is something to run, and that order is the fix rather than the
        # detail. This is a precondition of RUNNING — the executor loads the modules' code
        # from that directory — and it was being checked before working out whether anything
        # was going to run at all. What a machine with no checks bound to it has to say is
        # "there is nothing to collect", and that answer does not depend on where the module
        # code lives: the configuration this reads comes from the database.
        #
        # So a host nobody watches answered 500 "Modules directory not configured", which
        # reads as a broken server and is neither the truth nor actionable. Found by the
        # integration suite, which had never been run against this route: three of its tests
        # asked for 409 and got 500, and had done so since the route was written.
        if not wa._modules_dir:
            return jsonify({'error': wa._t('checks_no_modules_dir')}), 500
        # The same lock the Status screen's run takes, so the two cannot overlap — they would
        # be running the same modules against the same state table. Taken HERE and released by
        # the job: between deciding to start and the thread actually starting there must be no
        # window in which a second request also decides it is the only one.
        if not wa._check_lock.acquire(blocking=False):
            return jsonify({'error': wa._t('checks_already_running')}), 409
        try:
            job_id = infra_jobs.start_collect(
                wa, uid, str(record.get('name') or ''), modules,
                actor=session.get('username', ''), ip=request.remote_addr or '',
                # The language of whoever pressed the button, read while there is still a
                # request to read it from: the checklist is written on a worker thread, and
                # its words are for this person and not for whoever the alerts are sent to.
                lang=session.get('lang', '') or wa._DEFAULT_LANG)
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
