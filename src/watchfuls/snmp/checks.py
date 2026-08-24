#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: one check, and the loop over them.
#
"""Checking — an OID, an operator and a value the admin expects.

The oldest half of this module and the one nothing else depends on: a *check* names a server
and an OID, reads it, and compares the answer to something. That is a verdict, and it is a
different job from :mod:`.sampler`, which asks a whole profile and records a series — the two
were written years apart and share only the client underneath them.

It lives here rather than in the package's ``__init__`` for the reason the other four do: the
file that declares the module should say what the module IS, and reading a hundred and ninety
lines of comparison logic to find out is how a package's front door stops being one.
"""

import concurrent.futures
import re

from lib.debug import DebugLevel

from lib.core.snmp import devices as _devices
from lib.core.snmp.client import _HAS_PYSNMP
from .defaults import _CHECK_DEFAULTS, _SERVER_DEFAULTS


class SnmpChecks:
    """The check loop and one check, mixed into ``Watchful``."""

    # ── Public API ─────────────────────────────────────────────────────────────

    def check(self):
        if not self.is_enabled:
            self._debug('SNMP: module disabled, skipping.', DebugLevel.info)
            return self.dict_return

        if not _HAS_PYSNMP:
            self._debug(
                'SNMP: pysnmp is not installed. Install with: pip install pysnmp',
                DebugLevel.error,
            )
            return self.dict_return

        # Iterate servers; each carries its own 'checks' sub-collection and, when a device
        # profile is assigned to it, a set of metrics to sample. The two are independent: a
        # check says whether something is TRUE of the device, sampling says what it is DOING,
        # and a device may well be worth one and not the other.
        items: list[tuple[str, dict, dict]] = []
        sampled: list[tuple[str, dict]] = []
        bound: set[str] = set()      # hosts an item SAMPLES, enabled or not
        unsampled: dict = {}         # …and ones it only checks, which is worth saying
        for srv_key, srv in self.get_conf('servers', {}).items():
            if not isinstance(srv, dict):
                continue
            # Covered means "this item SAMPLES it", which is why the condition is the
            # profiles and not merely the binding. Reported from the panel: a switch whose
            # SNMP profile test returned OIDs was in nobody's collection, because the module
            # item bound to it carried OID checks and no device profiles — so it claimed the
            # host from the registry fallback and then sampled nothing. A device sampled by
            # nobody, with no error anywhere and no line on any screen.
            #
            # Collected BEFORE the enabled gate on purpose: a disabled item still speaks for
            # its host. Somebody switched that device off, and resuming it from the other end
            # because the configuration also lives on the host would be an upgrade quietly
            # undoing a decision. That is about a decision somebody made; an item with no
            # profiles is not a decision about sampling at all.
            _uid = str(srv.get('host_uid') or '').strip()
            if _uid and self.profiles_of(srv):
                bound.add(_uid)
            elif _uid and (srv.get('checks') or {}):
                # …and one that only holds checks is worth SAYING, because from the outside
                # "collect now" on that device looks like a button that does nothing.
                unsampled[_uid] = str(srv.get('label') or '').strip() or _uid
            if not srv.get('enabled', _SERVER_DEFAULTS['enabled']):
                continue
            if self.profiles_of(srv):
                sampled.append((srv_key, srv))
            for chk_key, chk_cfg in (srv.get('checks') or {}).items():
                if not isinstance(chk_cfg, dict):
                    continue
                if chk_cfg.get('enabled', _CHECK_DEFAULTS['enabled']):
                    items.append((f'{srv_key}.{chk_key}', chk_cfg, srv))

        # …and every host that IS an SNMP device without anybody having said so twice. A host
        # with a community and device profiles assigned is a device; that used to be worth
        # nothing until a module entry pointed back at it, which made the module — not the
        # device — the thing that decided it was worth looking at.
        sampled.extend(_devices.devices_to_sample(
            getattr(self._monitor, '_hosts_store', None), bound))

        # Whoever is watching gets told about the devices this module will NOT sample, once
        # and by name. Silence is what made the reported bug unreadable: the device somebody
        # pressed the button for simply was not in the list, alongside two that were.
        left = {uid: name for uid, name in unsampled.items()
                if uid not in {str((s or {}).get('host_uid') or '') for _k, s in sampled}}
        if left:
            self.report_progress(', '.join(sorted(left.values())),
                                 step=self._msg('snmp_step_unsampled',
                                                lang=self.watcher_lang()))

        # Friendly label per result key (keys are opaque "<srv_uid>.<chk_uid>").
        labels = {k: (str(c.get('label') or '').strip() or k) for k, c, _ in items}

        max_workers = max(1, self.module_default('threads', self.module_field_default('threads')))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._check_item, key, cfg, srv): key
                for key, cfg, srv in items
            }
            # Sampling shares the pool: it is the same conversation with the same devices, and
            # a second pool would double the sockets this module opens against a network the
            # admin sized for one.
            futures.update({
                pool.submit(self._sample_item, srv_key, srv): srv_key
                for srv_key, srv in sampled
            })
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f'SNMP: {labels.get(key, key)} — unhandled exception: {exc}', DebugLevel.error)
                    _lbl = labels.get(key, key)
                    self.dict_return.set(key, False,
                                         self._msg('snmp_error', _lbl, exc), name=_lbl)

        super().check()
        return self.dict_return

    # ── Private helpers ────────────────────────────────────────────────────────

    def _check_item(self, key: str, cfg: dict, server: dict | None = None):
        """Execute a single OID check and store the result.

        ``server`` is the parent server profile dict — passed directly from
        ``check()`` since checks are now nested inside each server item.
        """
        if server is None:
            server = {}
        # Host-centric: if the server references a host, merge its address +
        # SNMP credential profile (no-op for classic inline servers).
        server = self.resolve_host(server)
        # Bound host in maintenance → resolve_host disables it: skip the check.
        if server.get('_host_maintenance') or not server.get('enabled', True):
            return

        host      = str(server.get('host',      '') or '').strip()
        port      = int(server.get('port',      _SERVER_DEFAULTS['port'])      or _SERVER_DEFAULTS['port'])
        version   = str(server.get('version',   _SERVER_DEFAULTS['version'])   or _SERVER_DEFAULTS['version']).strip()
        community = str(server.get('community', _SERVER_DEFAULTS['community']) or _SERVER_DEFAULTS['community']).strip()
        timeout   = max(1, int(server.get('timeout',  _SERVER_DEFAULTS['timeout'])  or _SERVER_DEFAULTS['timeout']))
        retries   = max(0, int(server.get('retries',  _SERVER_DEFAULTS['retries'])  or _SERVER_DEFAULTS['retries']))

        # SNMPv3 credentials come from the server profile
        v3_username   = str(server.get('snmpv3_username',      '') or '')
        v3_auth_key   = str(server.get('snmpv3_auth_key',      '') or '')
        v3_priv_key   = str(server.get('snmpv3_priv_key',      '') or '')
        v3_auth_proto = str(server.get('snmpv3_auth_protocol',
                                       _SERVER_DEFAULTS.get('snmpv3_auth_protocol', 'MD5')))
        v3_priv_proto = str(server.get('snmpv3_priv_protocol',
                                       _SERVER_DEFAULTS.get('snmpv3_priv_protocol', 'DES')))

        oid      = (cfg.get('oid') or '').strip() or _CHECK_DEFAULTS['oid']
        operator = str(cfg.get('operator') or 'any').strip()
        expected = str(cfg.get('value', '') or '').strip()
        t_alert  = int(cfg.get('alert', _CHECK_DEFAULTS['alert']))
        label    = str(cfg.get('label', '') or key).strip() or key

        if not host:
            self._debug(f'SNMP: {label} — no server host configured, skipping.', DebugLevel.warning)
            self.dict_return.set(key, False, self._msg('snmp_no_host', label), name=label)
            return

        raw_value, err = self._snmp_get(
            host=host, port=port,
            version=version, community=community,
            timeout=timeout, retries=retries,
            oid=oid,
            v3_username=v3_username,
            v3_auth_key=v3_auth_key,
            v3_priv_key=v3_priv_key,
            v3_auth_proto=v3_auth_proto,
            v3_priv_proto=v3_priv_proto,
        )

        if err:
            # Consecutive-failure debounce, persisted via fail_streak (status
            # store) so it survives fresh instances per cycle AND fresh
            # processes in systemd one-shot mode.  status stays True while
            # within the grace window; at the threshold the check goes DOWN.
            streak = self.fail_streak(key, True)
            status = streak < max(1, t_alert)
            msg    = self._msg('snmp_up' if status else 'snmp_down', label, err)
            self._debug(f'SNMP: {label} — error: {err} (fails={streak}/{t_alert})', DebugLevel.warning)
            self._emit(key, status, msg, {'oid': oid, 'error': err}, name=label)
            return

        self.fail_streak(key, False)
        status = self._evaluate(raw_value, operator, expected)
        msg    = self._msg('snmp_up' if status else 'snmp_down', label, raw_value)
        self._debug(
            f'SNMP: {key} — OID={oid} value={raw_value!r} '
            f'op={operator} expected={expected!r} → {status}',
            DebugLevel.info,
        )
        self._emit(key, status, msg, {
            'oid':      oid,
            'value':    raw_value,
            'operator': operator,
            'expected': expected,
        }, name=label)

    # ── Value evaluation ───────────────────────────────────────────────────────

    @staticmethod
    def _evaluate(raw: str, operator: str, expected: str) -> bool:
        """Compare *raw* (string from SNMP response) against *expected*.

        Numeric operators cast both values to float.
        ``any`` always returns True (connectivity-only check).
        """
        if operator == 'any':
            return True

        raw_s = str(raw).strip()

        if operator == 'contains':
            return expected in raw_s

        if operator == 'regex':
            try:
                return bool(re.search(expected, raw_s))
            except re.error:
                return False

        if operator in ('eq', 'ne', 'gt', 'lt', 'gte', 'lte'):
            try:
                r_num = float(raw_s)
                e_num = float(expected)
                return {
                    'eq':  r_num == e_num,
                    'ne':  r_num != e_num,
                    'gt':  r_num >  e_num,
                    'lt':  r_num <  e_num,
                    'gte': r_num >= e_num,
                    'lte': r_num <= e_num,
                }[operator]
            except (ValueError, TypeError):
                if operator == 'eq':
                    return raw_s == expected
                if operator == 'ne':
                    return raw_s != expected
                return False

        return False
