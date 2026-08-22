#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The fleet, live — read-only routes under /api/v1/infra.

Routes registered by this file:

    GET    /api/v1/infra/hosts             every machine, its state and how much of it is watched
    GET    /api/v1/infra/hosts/<uid>       one machine: what its checks last returned, as numbers

**Nothing here writes.** The section shows what the fleet is doing; what the fleet IS lives in
the registry, behind the permissions the registry already has. A write route here would make
``infra_view`` a way around them.

**Where the data comes from — and where it does not.** Every fact is read through the domain
that owns it: the hosts store owns the machines, ``hosts.service`` owns "what state is this
host in" and "what did its checks last return" (the same functions the host modal uses), and
the history metadata owns which of a result's numbers are measurements and what they are
called. This section composes; it does not compute a second answer to any of those questions,
because a second answer is one that can disagree.

**Who may see what.** Gated by ``infra_view``, and the fleet is narrowed exactly the way
``/api/v1/hosts`` narrows it: the whole list for ``servers_view``, otherwise only the hosts
the caller holds ``server.<uid>.view`` for. One model for "which machines are mine to see",
not two.
"""

from flask import jsonify, session

from lib.core.history import service as history_svc
from lib.core.hosts import service as hosts_svc
from lib.core.hosts.service import _checks_for_host
from lib.core.infra import service as infra_svc


def register(app, wa):
    infra_view_req = wa._perm_required('infra_view')

    def _visible(hosts, perms):
        """The hosts this caller may see — the same rule as the registry's own listing."""
        if 'servers_view' in perms:
            return hosts
        return [h for h in hosts if f"server.{h.get('uid')}.view" in perms]

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
        if 'servers_view' not in perms and f'server.{uid}.view' not in perms:
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
        return jsonify({'host':    infra_svc.fleet_row(record),
                        'results': results,
                        'metrics': infra_svc.metrics(results, fields)})
