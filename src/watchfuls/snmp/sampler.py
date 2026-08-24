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

def _skipped(metric: dict, text: str) -> bool:
    """Whether the profile said this reading is not an answer (`skip`).

    Compiled per call and cached by `re`: these run once per row of one walk, and a cache of
    our own would be a second place for a pattern to go stale. A pattern that fails here is
    treated as no filter — normalise already rejected the ones that do not compile, and a
    fact that vanishes for a reason nobody can see is worse than one with noise in it.
    """
    pat = metric.get('skip')
    if not pat or not text:
        return False
    try:
        return re.search(pat, text) is not None
    except re.error:
        return False


# Where a device's previous counter readings are kept between cycles.
#
# Under `module_state`, and that word is the whole point. The monitor's status dict LOOKS
# free-form — `set_conf` takes any path and returns True — but what survives a cycle is what
# the `check_state` table has a column for, and `status.read()` at the top of every cycle
# rebuilds each entry from those columns. A field written anywhere else is in memory until
# the next read and gone after it, with no error at either end.
#
# That is exactly what happened here: every counter in every profile — interface traffic,
# packets, errors and discards, the TCP/UDP/ICMP/IP counters, disk and volume I/O — was
# writing its baseline into a dict that was thrown away seconds later, so every sample was
# the FIRST sample and no rate was ever computed. The panel showed the gauges and simply had
# no line where a counter should be, which reads as a device that does not serve them.
_STATE_ROOT = 'module_state'
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
        # Nothing assigned, nothing to say: a device this module is not sampling must not
        # appear in a checklist of what the module is doing.
        wanted = self.profiles_of(server)
        if not wanted:
            return
        # The phases, in the module's own words. The core has no vocabulary for "which
        # profile of a Synology am I on" and would be inventing one for the other twenty
        # modules if it did — so the words are here, translated like every other sentence
        # this module produces, and the panel draws whatever arrives.
        # `watcher_lang()` and not the notification language: this line is read by the
        # person standing in front of the screen, who chose a language in the panel. Reported
        # as a Spanish dialog with "Reading the metrics" in it.
        # `scope=label`: this module samples its devices in a THREAD POOL, so several of
        # these are in flight at once. Without saying which machine each line is about they
        # all write into one, and the counter jumps between machines and freezes wherever the
        # last thread left it — reported from the screen as a finished run showing "3/24" of
        # a device nobody had asked about.
        watching = self.watcher_lang()
        self.report_progress(label, scope=label,
                             step=self._msg('snmp_step_resolve', lang=watching))
        catalog = self._profile_catalog()
        # `expand` is where a group stops being one: what comes back is profiles with metrics
        # in them, deduplicated, so two groups that share a profile do not sample it twice.
        assigned = [catalog[p] for p in _profiles.expand(catalog, wanted)]
        if not assigned:
            return

        conn = self._conn_params(server)
        if not conn:
            return

        now = time.time()
        state = self._sample_state(srv_key)
        rows: dict = {}          # row key → {'name': …, 'values': {}, 'attrs': {}}
        sightings: dict = {}     # evidence kind → {what was seen: where}
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
        # Which of this machine's rows somebody said are worth an alert. Read once for the
        # device: it is one small list and the alternative is a database round trip per
        # metric of every profile it carries.
        watched = self._watched_rows(server)
        for _i, prof in enumerate(assigned, 1):
            # `label_of` and not `prof['label']`: a profile names itself per language
            # (`{'en_EN': …, 'es_ES': …}`), and printing the dict is what happens when you
            # forget — reported from the panel as a progress line with a Python dict in it.
            # The configured NOTIFY language, because that is the one a module already uses
            # for every sentence it produces; a worker thread has no session to ask.
            # One PHASE, whose counter moves — not one line per profile. Twenty-four
            # lines scrolling past is a list nobody reads; "Leyendo las métricas 7/24,
            # Synology — discos" is the sentence somebody watching actually wants.
            # The profile's SHORT name where it has one: "Synology — SMART attributes
            # (SYNOLOGY-SMART-MIB)" is a MIB filename in a line that has room for a few words,
            # and the same shortening is what the family rail and the summary already use.
            _lg = watching or lang
            _name = _profiles.short_label_of(prof, _lg) or _profiles.label_of(prof, _lg)
            self.report_progress(_name, scope=label,
                                 step=self._msg('snmp_step_read', lang=watching),
                                 n=_i, total=len(assigned))
            for metric in prof.get('metrics') or ():
                ok, err = self._sample_metric(metric, conn, now, state, rows, columns,
                                              source=str(prof.get('id') or ''), lang=lang,
                                              sightings=sightings, watched=watched)
                answered = answered or ok
                if err:
                    errors.append(f"{metric['key']}: {err}")
                if probe and answered:
                    break
            if probe and answered:
                break

        self._save_sample_state(srv_key, state)
        self._save_sightings(server, sightings)
        self._emit_samples(srv_key, label, rows, answered, errors)

    def _watched_rows(self, server: dict) -> set:
        """The rows of this machine somebody has said are worth an alert.

        Empty for a device with no host bound to it, and empty when the registry cannot be
        reached: a cycle that fails because of a preference is worse than one that reports a
        little less. What it turns back ON is a verdict the profile switched off — see
        `verdict` in the profile format — so the failure mode of an empty answer is the
        current behaviour and not a device that stops being checked.
        """
        uid = str(server.get('host_uid') or server.get('_host_uid') or '').strip()
        store = getattr(self._monitor, '_hosts_store', None) if self.is_monitor_exist else None
        if not uid or store is None:
            return set()
        try:
            return store.watch(uid)
        except Exception as exc:      # pylint: disable=broad-except
            self._debug(f'SNMP: watched rows not read: {exc}', DebugLevel.warning)
            return set()

    def _sample_metric(self, metric: dict, conn: dict, now: float, state: dict, rows: dict,
                       columns: dict, source: str = '', lang: str = '',
                       sightings: dict | None = None, watched: set | None = None) -> tuple:
        """Read one metric into *rows*. Returns ``(answered, error)``."""
        got, err = read_metric(metric, conn, self._snmp_get, self._snmp_walk_oid, columns)
        if err and not got:
            return False, err
        # Resolved once per metric, not once per row: an interface table is one metric and
        # forty rows, and the words are the same for all of them. Only the levels worth
        # reporting are kept — an `ok` or an `info` state is a badge and not a finding.
        # …and a column the profile says COLOURS without JUDGING keeps none of them. An
        # access port with nothing plugged into it is `down`, which is worth a red mark beside
        # that port and is not a fault of the switch — the badge is drawn from the same map on
        # the screen, so what changes here is only whether it becomes a finding.
        #
        # …unless somebody has said THIS row matters. Then the same reading is news again, and
        # the map that was already written down is what says so. Two levels of decision and
        # they belong to different people: the profile knows what ifOperStatus means on every
        # switch ever made, and only whoever ran the cable knows that gi3 goes to the server.
        quiet = metric.get('verdict') is False
        states = {}
        if metric.get('states') and (not quiet or watched):
            _name = _profiles.label_of(metric, lang)
            states = {v: {'level': spec['level'], 'label': str(spec.get('label') or ''),
                          'metric': _name}
                      for v, spec in (_profiles.states_of(metric, lang) or {}).items()
                      if spec.get('level') in ('bad', 'warn')}
        # A sighting is not a reading: it goes to the evidence store and never becomes a
        # result. Handled here rather than in `_store_value` because it does not belong in
        # `rows` at all — not even as an empty one, which would still be a `check_state` row.
        # A column the profile wants as one total. Each row is still sampled the ordinary
        # way — a counter needs ITS OWN baseline, and summing raw counters before
        # differentiating them would produce a spike every time a port is added — and what is
        # recorded is the sum of the per-row results, under the device itself.
        if str(metric.get('aggregate') or '') == 'sum':
            total, seen = 0.0, False
            for r in got:
                prev = (state.get(r['key']) or {}).get(metric['key'])
                value, new_state = _metrics.sample(metric, r['raw'], prev, now)
                if new_state is not None:
                    state.setdefault(r['key'], {})[metric['key']] = new_state
                if value is not None:
                    total += float(_metrics.scale_value(value, r['factor']))
                    seen = True
            if seen:
                row = rows.setdefault('', {'name': '', 'values': {}, 'attrs': {},
                                           'states': []})
                row['values'][metric['key']] = total
            return True, (err or None)
        kind = str(metric.get('evidence') or '')
        if kind and sightings is not None:
            seen = sightings.setdefault(kind, {})
            for r in got:
                key = str(r['name'] or r['index'] or '').strip()
                if key:
                    seen[key] = _metrics.attribute(metric, r['raw'])
            return True, (err or None)
        for r in got:
            # A quiet column judges only the rows that were named. The row key is what the
            # screen marked, which is the name the device gave it before any split.
            mine = states
            if quiet and states:
                mine = states if self._is_watched(watched, r['name'], r['key']) else {}
            self._store_value(rows, r['key'], r['name'], metric, r['raw'], now, state,
                              factor=r['factor'], source=source, states=mine)
        return True, (err or None)

    def _is_watched(self, watched, *names) -> bool:
        """Whether any of the names this row goes by was marked.

        More than one because a row is filed under the name the device composed and read back
        under the key that name was made safe as — and which of the two the screen sent
        depends on the table. Cheap either way: this is a set of a handful.
        """
        if not watched:
            return False
        return any(self._hosts_watch_key(n) in watched for n in names if n)

    def _hosts_watch_key(self, row: str) -> str:
        """The key the registry files a watched row under — ITS function, not a second copy
        of the composition: two places building this string is two places to get it wrong the
        day one of them changes."""
        from lib.core.hosts.store import HostsStore   # noqa: PLC0415
        # The BARE name — `snmp` and not `watchfuls.snmp`. It is what a result records as its
        # module and therefore what the screen sends back when somebody marks a row; the
        # dotted one is this class's import path and matches nothing anybody stored.
        bare = str(self.name_module or '').rsplit('.', 1)[-1]
        return HostsStore.watch_key(bare, row)

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
        # A table the profile declared as being ABOUT the box (`of_device`) does not get a
        # row each: its readings fold into one fact on the device itself, in the order the
        # agent walked them. `ipAddrTable` is the case — its rows are one machine's addresses,
        # and one address per row is an answer to "what is this box on the network" filed in
        # five places nothing opens.
        if metric.get('kind') == 'text':
            text = _metrics.attribute(metric, raw)
            if _skipped(metric, text):
                return          # the profile said this reading is not an answer
            if metric.get('of_device'):
                self._store_device_fact(rows, metric, text, source)
                return
            row = rows.setdefault(row_key, {'name': row_name, 'values': {}, 'attrs': {},
                                            'states': []})
            bucket = row['attrs'].setdefault(source or '_', {})
            bucket[metric.get('role') or metric['key']] = text
            return
        row = rows.setdefault(row_key, {'name': row_name, 'values': {}, 'attrs': {},
                                        'states': []})
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

    #: What separates the readings of an `of_device` table when they are read as one fact.
    _FACT_JOIN = ', '

    def _store_device_fact(self, rows: dict, metric: dict, text: str, source: str) -> None:
        """Append one reading to the device's own fact for *metric*.

        Called once per row of the walk, so it accumulates. Empty readings are dropped (a
        column the agent left blank is not an address) and repeats are dropped with them —
        two interfaces answering the same address is one address, and "192.168.1.1,
        192.168.1.1" reads as a machine with a problem it does not have.
        """
        if not text:
            return
        row = rows.setdefault('', {'name': '', 'values': {}, 'attrs': {}, 'states': []})
        bucket = row['attrs'].setdefault(source or '_', {})
        key = metric.get('role') or metric['key']
        seen = [p for p in str(bucket.get(key) or '').split(self._FACT_JOIN) if p]
        if text in seen:
            return
        bucket[key] = self._FACT_JOIN.join(seen + [text])

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

    def _save_sightings(self, server: dict, sightings: dict) -> None:
        """Hand what this device SAW to the store that keeps sightings.

        Filed under the HOST and not the server key: the map joins across machines, and a
        machine is what it joins on. A server with no host bound to it is a sighting nobody
        can place, so it is dropped rather than filed under something that is not a machine.

        Written even when a kind came back empty — a switch that has forgotten every MAC is a
        switch whose forwarding table is empty, and leaving last cycle's in place would draw
        cables that were unplugged last week.
        """
        if not sightings:
            return
        uid = str(server.get('host_uid') or server.get('_host_uid') or '').strip()
        db = getattr(self, 'db', None)
        if not uid or db is None:
            return
        try:
            from lib.core.infra.evidence import EvidenceStore   # noqa: PLC0415
            store = EvidenceStore(db)
            for kind, seen in sightings.items():
                store.replace(uid, kind, seen)
        except Exception as exc:      # pylint: disable=broad-except
            # Evidence is a nicety on top of the cycle. A map that misses a link is a worse
            # map; a cycle that fails because of one is a worse panel.
            self._debug(f'SNMP: sightings not stored: {exc}', DebugLevel.warning)

    # ── State that has to outlive the process ─────────────────────────────────

    def _sample_state(self, srv_key: str) -> dict:
        """The previous cycle's counter readings for one device."""
        if not self.is_monitor_exist:
            return {}
        try:
            got = self._monitor.status.get_conf(
                [self.name_module, f'{srv_key}/metrics', _STATE_ROOT, _STATE_FIELD], {})
            return dict(got) if isinstance(got, dict) else {}
        except Exception:  # pylint: disable=broad-except
            return {}

    def _save_sample_state(self, srv_key: str, state: dict) -> None:
        if not self.is_monitor_exist:
            return
        try:
            self._monitor.status.set_conf(
                [self.name_module, f'{srv_key}/metrics', _STATE_ROOT, _STATE_FIELD], state)
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
