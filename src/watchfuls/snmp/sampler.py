#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: turning a profile into numbers.
#
"""Sampling — where a device profile stops being a declaration.

A check asks one OID and compares the answer to something. This asks a whole **profile**: every
metric it declares, against one device, once per cycle, and records the values so they can be
charted. The difference matters more than it looks — a check produces a verdict, and this
produces a series, and a series has requirements a verdict does not:

* **it must mean the same thing every cycle.** A counter is turned into a rate against the
  previous sample, which is state that has to outlive both the instance (the monitor builds a
  fresh Watchful every cycle) and the process (systemd one-shot runs each cycle in a new one).
  It lives where ``fail_streak`` lives, in the status store, for exactly that reason;

* **a row has to keep its name.** A table metric is walked per index, and the index is not the
  name of anything a person recognises — so the profile's ``index_label`` column is walked
  beside it and the row is filed under what the device calls it. Under the index instead, the
  chart of "port 3" silently becomes a different port when the device renumbers.

Nothing here decides what a value means; that is the profile's job (:mod:`.profiles`) and the
counter maths' (:mod:`.metrics`). This decides what to ask, in what order, and under which key
the answer is stored.
"""

from __future__ import annotations

import re
import time

from lib.debug import DebugLevel

from lib.core.snmp import metrics as _metrics
from lib.core.snmp.profiles import store as _profile_store
from lib.core.snmp import profiles as _profiles
# Reading a metric off a device is core: the scheduler, the test screen and the host
# walk have to get the same answer, so there is one implementation of it.
from lib.core.snmp.sampler import _row_factor, _safe_key, read_metric
from lib.core.snmp.defaults import CONN_DEFAULTS as _SERVER_DEFAULTS

# Where a device's previous counter readings are kept between cycles.
_STATE_FIELD = 'snmp_prev'

# How many cycles of silence before a sampled device is called down. Fixed rather than
# configurable: one lost UDP datagram is not an outage, and a device that has answered nothing
# twice running is not a device having a bad moment. The OID checks have their own `alert`
# threshold because there the admin chose what to ask; here the profile did.
_SAMPLE_ALERT = 2


class SnmpSampler:
    """Reading a device through its assigned profiles."""

    # ── The catalogue this monitor sees ────────────────────────────────────────

    def _profile_catalog(self) -> dict:
        """Shipped profiles plus whatever this installation added, cached per instance.

        Per instance and not per process: the monitor builds a fresh Watchful each cycle, so
        this re-reads once a cycle, which is what makes a profile dropped into the folder take
        effect without a restart — and is far too cheap to be worth a stale cache.
        """
        cached = getattr(self, '_prof_cache', None)
        if cached is not None:
            return cached
        var_dir = str(getattr(self._monitor, 'dir_var', '') or '').strip()
        cdir = _profiles.custom_dir(var_dir)
        # What the panel wrote is part of the catalogue here too. It lives in the shared
        # database precisely so this side sees it: a deployment with a web container and a
        # worker container shares one, and a profile or a grouping made in the panel that the
        # sampler could not read would be a device assigned nothing at all.
        db = getattr(self, 'db', None)
        written = _profile_store.CatalogStore(db).documents() if db is not None else None
        catalog = _profiles.catalog(
            custom=_profiles.load_dir(cdir) if cdir else None, written=written)
        self._prof_cache = catalog
        return catalog

    @staticmethod
    def profiles_of(server: dict) -> list:
        """The profile ids assigned to one server, in the order they were chosen."""
        return _profiles.assigned(server)

    # ── One device, one cycle ─────────────────────────────────────────────────

    def _sample_item(self, srv_key: str, srv: dict) -> None:
        """Sample one server, resolving its bound host exactly as a check does.

        Same gate as a check, and for the same reason: a host in maintenance is a machine
        somebody is working on, and a graph of it during the work is a graph of the work.
        """
        server = self.resolve_host(srv)
        if server.get('_host_maintenance') or not server.get('enabled', True):
            return
        label = str(server.get('label') or '').strip() or srv_key
        self._sample_server(srv_key, server, label)

    def _sample_server(self, srv_key: str, server: dict, label: str) -> None:
        """Read every metric of every profile assigned to *server* and record the values."""
        catalog = self._profile_catalog()
        # `expand` is where a group stops being one: what comes back is profiles with metrics
        # in them, deduplicated, so two groups that share a profile do not sample it twice.
        assigned = [catalog[p] for p in _profiles.expand(catalog, self.profiles_of(server))]
        if not assigned:
            return

        conn = self._conn_params(server)
        if not conn:
            return

        now = time.time()
        state = self._sample_state(srv_key)
        rows: dict = {}          # row key → {'name': …, 'values': {}, 'attrs': {}}
        answered = False
        errors: list = []

        # One walk per SUPPORTING column, however many metrics name it: an interface table
        # is one profile with five columns against one name column, and asking the device five
        # times is four round trips spent on an answer that cannot have changed.
        columns: dict = {}

        # A PROBE stops at the first metric that answers. Sampling reads every metric of every
        # profile the device has, which on a NAS with fifteen of them is dozens of walks of
        # hundreds of round trips each — and a probe records none of it: its answer is a graph
        # nobody is drawing. What the test has to establish is that the profiles reach the
        # device, and one value that comes back establishes it. The full sweep is the
        # scheduler's job, on its own cycle, where the numbers are kept.
        probe = self.is_probe
        # Which profile it is on, for whoever is watching. This loop IS the five minutes: a
        # Synology carries twenty-four profiles and each is a walk of hundreds of round trips,
        # all of it inside one module — so a screen that only sees module boundaries shows 0 %
        # for the whole sampling and looks like something that has hung. Reported exactly that
        # way from the panel. `report_progress` is a no-op unless somebody pressed a button.
        lang = self._notify_lang()
        for _i, prof in enumerate(assigned, 1):
            # `label_of` and not `prof['label']`: a profile names itself per language
            # (`{'en_EN': …, 'es_ES': …}`), and printing the dict is what happens when you
            # forget — reported from the panel as a progress line with a Python dict in it.
            # The configured NOTIFY language, because that is the one a module already uses
            # for every sentence it produces; a worker thread has no session to ask.
            self.report_progress(
                f'{label} — {_profiles.label_of(prof, lang)} ({_i}/{len(assigned)})')
            for metric in prof.get('metrics') or ():
                ok, err = self._sample_metric(metric, conn, now, state, rows, columns,
                                              source=str(prof.get('id') or ''), lang=lang)
                answered = answered or ok
                if err:
                    errors.append(f"{metric['key']}: {err}")
                if probe and answered:
                    break
            if probe and answered:
                break

        self._save_sample_state(srv_key, state)
        self._emit_samples(srv_key, label, rows, answered, errors)

    def _sample_metric(self, metric: dict, conn: dict, now: float, state: dict, rows: dict,
                       columns: dict, source: str = '', lang: str = '') -> tuple:
        """Read one metric into *rows*. Returns ``(answered, error)``."""
        got, err = read_metric(metric, conn, self._snmp_get, self._snmp_walk_oid, columns)
        if err and not got:
            return False, err
        # Resolved once per metric, not once per row: an interface table is one metric and
        # forty rows, and the words are the same for all of them. Only the levels worth
        # reporting are kept — an `ok` or an `info` state is a badge and not a finding.
        states = {}
        if metric.get('states'):
            _name = _profiles.label_of(metric, lang)
            states = {v: {'level': spec['level'], 'label': str(spec.get('label') or ''),
                          'metric': _name}
                      for v, spec in (_profiles.states_of(metric, lang) or {}).items()
                      if spec.get('level') in ('bad', 'warn')}
        for r in got:
            self._store_value(rows, r['key'], r['name'], metric, r['raw'], now, state,
                              factor=r['factor'], source=source, states=states)
        return True, (err or None)

    def _store_value(self, rows: dict, row_key: str, row_name: str, metric: dict,
                     raw, now: float, state: dict, factor=1, source: str = '',
                     states: dict | None = None) -> None:
        """Put one reading where it belongs — a number in the series, a name beside it.

        *factor* is the per-row multiplier a ``scale_by`` column supplied. It is applied to the
        RESULT and not to the raw reading, which is the same rule the profile's own ``scale``
        follows and matters for the same reason: scaling a counter before differentiating it
        would move the point at which it wraps.

        *source* is the profile the reading came from, and the attributes are filed UNDER it.
        They were filed flat, and that was not untidiness: a device carries several profiles,
        several of them describe a *different piece of equipment* — a NAS and the UPS plugged
        into it both answer "vendor", "model", "version" — and a flat dict means the second
        one silently overwrites the first. So the panel showed one machine's serial beside
        another machine's firmware, and WHICH survived depended on the order the profiles
        happened to be sampled in. Nothing was reported wrong; a fact was simply gone.
        """
        row = rows.setdefault(row_key, {'name': row_name, 'values': {}, 'attrs': {},
                                        'states': []})
        if metric.get('kind') == 'text':
            bucket = row['attrs'].setdefault(source or '_', {})
            bucket[metric.get('role') or metric['key']] = _metrics.attribute(metric, raw)
            return
        prev = (state.get(row_key) or {}).get(metric['key'])
        value, new_state = _metrics.sample(metric, raw, prev, now)
        if new_state is not None:
            state.setdefault(row_key, {})[metric['key']] = new_state
        if value is not None:
            row['values'][metric['key']] = _metrics.scale_value(value, factor)
            # What the profile SAYS this number means, kept beside it. The map is already
            # written down — it is what paints the badge — and until now the check threw it
            # away: a NAS could answer "system status: Failed" and "update available" every
            # cycle and the panel recorded the row as fine, because a sample was treated as
            # something that either arrived or did not. A profile that has gone to the trouble
            # of saying which values are BAD is a profile whose device can be checked.
            spec = (states or {}).get(str(value))
            if spec:
                row['states'].append(spec)

    # ── What comes out ────────────────────────────────────────────────────────

    def _emit_samples(self, srv_key: str, label: str, rows: dict,
                      answered: bool, errors: list) -> None:
        """One result for the device's own metrics, one per row of every table it serves."""
        if not answered:
            # Nothing answered at all. Debounced like a check, because a single lost datagram
            # is not an outage — and reported once for the device rather than once per metric,
            # which would be forty notifications about one unplugged cable.
            streak = self.fail_streak(f'{srv_key}/metrics', True)
            status = streak < _SAMPLE_ALERT
            reason = errors[0] if errors else 'no answer'
            self._debug(f'SNMP: {label} — sampling got nothing: {reason} '
                        f'(fails={streak}/{_SAMPLE_ALERT})', DebugLevel.warning)
            self._emit(f'{srv_key}/metrics', status,
                       self._msg('snmp_sample_down', label, reason),
                       {'error': reason}, name=label, change_msg=reason)
            return

        self.fail_streak(f'{srv_key}/metrics', False)
        for row_key, row in rows.items():
            key = f'{srv_key}/metrics' if not row_key else f'{srv_key}/{row_key}'
            name = label if not row_key else f'{label} — {row["name"]}'
            data = dict(row['values'])
            # The attributes travel WITH the numbers rather than as a series of their own:
            # a model and a serial are what identify the thing being charted, and a chart of
            # them would be a chart of nothing.
            if row['attrs']:
                data['_attrs'] = row['attrs']
            if row['name']:
                data['_row'] = row['name']
            # The verdict, and it comes from the PROFILE. A profile that has gone to the
            # trouble of saying which of a value's meanings are bad has said everything needed
            # to check the device — and until now that was thrown away: a NAS could answer
            # "system status: Failed" every cycle and the row was recorded as fine, because a
            # sample was treated as something that either arrived or did not.
            #
            # Worst first, and only ONE reported: a row with four unhappy states is one row in
            # trouble, and four messages about it is four notifications for one machine.
            bad = [f for f in row['states'] if f['level'] == 'bad']
            warn = [f for f in row['states'] if f['level'] == 'warn']
            worst = (bad or warn or [None])[0]
            if worst is None:
                self._emit(key, True,
                           self._msg('snmp_sampled', name, len(row['values'])),
                           data, name=name)
            else:
                # `warning` and not a failure for a warn level: the panel already knows the
                # difference — an amber state is not a machine that is down — and a pending
                # DSM update must not paint a NAS red.
                self._emit(key, False,
                           self._msg('snmp_state_bad' if bad else 'snmp_state_warn',
                                     name, worst['metric'], worst['label']),
                           data, name=name,
                           severity=None if bad else 'warning',
                           change_msg=f"{worst['metric']}={worst['label']}")
        if errors:
            # Partial answers are normal — a profile assigned to a device that serves half of
            # it costs those metrics and nothing else, and it is visible where it happened.
            self._debug(f'SNMP: {label} — {len(errors)} metric(s) unanswered: '
                        f'{"; ".join(errors[:5])}', DebugLevel.info)

    # ── State that has to outlive the process ─────────────────────────────────

    def _sample_state(self, srv_key: str) -> dict:
        """The previous cycle's counter readings for one device."""
        if not self.is_monitor_exist:
            return {}
        try:
            got = self._monitor.status.get_conf(
                [self.name_module, f'{srv_key}/metrics', _STATE_FIELD], {})
            return dict(got) if isinstance(got, dict) else {}
        except Exception:  # pylint: disable=broad-except
            return {}

    def _save_sample_state(self, srv_key: str, state: dict) -> None:
        if not self.is_monitor_exist:
            return
        try:
            self._monitor.status.set_conf(
                [self.name_module, f'{srv_key}/metrics', _STATE_FIELD], state)
            self._monitor._status_counts_dirty = True  # noqa: SLF001 — monitor-owned flag
        except Exception:  # pylint: disable=broad-except
            pass

    # ── The connection, as the device profile needs it ────────────────────────

    def _conn_params(self, server: dict) -> dict | None:
        """The kwargs both primitives take, or None when there is nothing to talk to."""
        host = str(server.get('host', '') or '').strip()
        if not host:
            return None
        return dict(
            host=host,
            port=int(server.get('port', _SERVER_DEFAULTS['port']) or _SERVER_DEFAULTS['port']),
            version=str(server.get('version', _SERVER_DEFAULTS['version'])
                        or _SERVER_DEFAULTS['version']).strip(),
            community=str(server.get('community', _SERVER_DEFAULTS['community'])
                          or _SERVER_DEFAULTS['community']).strip(),
            timeout=max(1, int(server.get('timeout', _SERVER_DEFAULTS['timeout'])
                               or _SERVER_DEFAULTS['timeout'])),
            retries=max(0, int(server.get('retries', _SERVER_DEFAULTS['retries'])
                               or _SERVER_DEFAULTS['retries'])),
            v3_username=str(server.get('snmpv3_username', '') or ''),
            v3_auth_key=str(server.get('snmpv3_auth_key', '') or ''),
            v3_priv_key=str(server.get('snmpv3_priv_key', '') or ''),
            v3_auth_proto=str(server.get('snmpv3_auth_protocol',
                                         _SERVER_DEFAULTS['snmpv3_auth_protocol'])
                              or _SERVER_DEFAULTS['snmpv3_auth_protocol']),
            v3_priv_proto=str(server.get('snmpv3_priv_protocol',
                                         _SERVER_DEFAULTS['snmpv3_priv_protocol'])
                              or _SERVER_DEFAULTS['snmpv3_priv_protocol']),
        )
