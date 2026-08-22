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

from . import metrics as _metrics
from . import profile_store as _profile_store
from . import profiles as _profiles
from .defaults import _SERVER_DEFAULTS

# A key segment lands in a result key, a history row and a chart legend. Anything that would
# split the key (`/`) or read as a path has to go, or a port called "eth0/1" becomes two.
_KEY_SAFE = re.compile(r'[^0-9A-Za-z._:-]+')

# Where a device's previous counter readings are kept between cycles.
_STATE_FIELD = 'snmp_prev'

# How many cycles of silence before a sampled device is called down. Fixed rather than
# configurable: one lost UDP datagram is not an outage, and a device that has answered nothing
# twice running is not a device having a bad moment. The OID checks have their own `alert`
# threshold because there the admin chose what to ask; here the profile did.
_SAMPLE_ALERT = 2


def _safe_key(text: str, fallback: str) -> str:
    out = _KEY_SAFE.sub('_', str(text or '').strip()).strip('_')
    return out or fallback


def _row_factor(column, index):
    """The multiplier this row's ``scale_by`` column gave, or 1 when it gave nothing usable.

    One, and never zero or a dropped reading: the factor is a detail ABOUT the value, and a
    device that answers the value but not the unit has still answered the value. Reporting a
    volume as empty because its block size was missing would be a wrong number where an
    imprecise one was available.
    """
    try:
        got = float(str((column or {}).get(index, '')).strip())
    except (TypeError, ValueError):
        return 1
    return got if got > 0 else 1


def read_metric(metric: dict, conn: dict, get, walk, columns: dict) -> tuple:
    """One metric declaration, read off one device. Returns ``(rows, error)``.

    A row is ``{'index', 'key', 'name', 'raw', 'factor'}``; a scalar metric produces exactly
    one whose index, key and name are empty, because it IS the device's own value and has
    nothing to be one row of.

    Free of the monitor on purpose. What "read this metric" means — one GET, or a walk plus
    the columns that name and scale its rows — is the same question whether the answer is
    going into a series or onto the screen of somebody testing a profile against the box in
    front of them. Two implementations of it would agree until the day they did not, and the
    day they did not is the day the test says the profile works and the sampler records
    nothing. *get* and *walk* are the two primitives, passed in because the caller decides
    what it is talking to.

    *columns* is a cache the caller owns, and the reason an interface table with five metrics
    against one name column is one walk and not five: whatever fills it stays filled for the
    rest of the device.
    """
    if metric.get('oid'):
        raw, err = get(oid=metric['oid'], **conn)
        if err:
            return [], err
        return [{'index': '', 'key': '', 'name': '', 'raw': raw, 'factor': 1}], None

    walked, err = walk(oid=metric['walk'], **conn)
    if err and not walked:
        return [], err
    idx = metric.get('index_label') or ''
    idx_oids = list(idx) if isinstance(idx, (list, tuple)) else ([idx] if idx else [])
    by_oid = metric.get('scale_by') or ''
    for extra in idx_oids + ([by_oid] if by_oid else []):
        if extra not in columns:
            found, _e = walk(oid=extra, **conn)
            columns[extra] = found or {}
    grp = metric.get('group') or ''
    out = []
    for index, raw in walked.items():
        # The device's own name for the row, and the index only when it has none: an SNMP
        # index is not the port on the front of the switch, and a chart legend that says
        # "3" is one nobody can act on. Where there is no name, the table's own id goes in
        # front of the index — storage row 3 and processor row 3 are not the same row.
        parts = [str((columns.get(o) or {}).get(index, '') or '').strip()
                 for o in idx_oids]
        name = ' / '.join(p for p in parts if p)
        if name:
            row_key, row_name = _safe_key(name, index), name
        else:
            row_key = f'{grp}.{index}' if grp else index
            row_name = row_key
        out.append({'index': index, 'key': row_key, 'name': row_name, 'raw': raw,
                    'factor': _row_factor(columns.get(by_oid), index) if by_oid else 1})
    return out, (err or None)


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
        for prof in assigned:
            for metric in prof.get('metrics') or ():
                ok, err = self._sample_metric(metric, conn, now, state, rows, columns)
                answered = answered or ok
                if err:
                    errors.append(f"{metric['key']}: {err}")
                if probe and answered:
                    break
            if probe and answered:
                break

        self._save_sample_state(srv_key, state)
        self._emit_samples(srv_key, label, rows, answered, errors)

    def _sample_metric(self, metric: dict, conn: dict, now: float,
                       state: dict, rows: dict, columns: dict) -> tuple:
        """Read one metric into *rows*. Returns ``(answered, error)``."""
        got, err = read_metric(metric, conn, self._snmp_get, self._snmp_walk_oid, columns)
        if err and not got:
            return False, err
        for r in got:
            self._store_value(rows, r['key'], r['name'], metric, r['raw'], now, state,
                              factor=r['factor'])
        return True, (err or None)

    def _store_value(self, rows: dict, row_key: str, row_name: str, metric: dict,
                     raw, now: float, state: dict, factor=1) -> None:
        """Put one reading where it belongs — a number in the series, a name beside it.

        *factor* is the per-row multiplier a ``scale_by`` column supplied. It is applied to the
        RESULT and not to the raw reading, which is the same rule the profile's own ``scale``
        follows and matters for the same reason: scaling a counter before differentiating it
        would move the point at which it wraps.
        """
        row = rows.setdefault(row_key, {'name': row_name, 'values': {}, 'attrs': {}})
        if metric.get('kind') == 'text':
            row['attrs'][metric.get('role') or metric['key']] = _metrics.attribute(metric, raw)
            return
        prev = (state.get(row_key) or {}).get(metric['key'])
        value, new_state = _metrics.sample(metric, raw, prev, now)
        if new_state is not None:
            state.setdefault(row_key, {})[metric['key']] = new_state
        if value is not None:
            row['values'][metric['key']] = _metrics.scale_value(value, factor)

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
            self._emit(key, True,
                       self._msg('snmp_sampled', name, len(row['values'])),
                       data, name=name)
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
