#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — SNMP monitoring watchful.
#
# Defines a set of *servers* (connection profiles) and a set of *checks*
# (OID queries), where each check references a server by its key.
# Multiple servers and multiple checks per server are supported.
#
# Optional dependency: pysnmp >= 6  (pip install pysnmp)
"""SNMP watchful — multi-server OID monitoring."""

import concurrent.futures
import re

from lib.debug import DebugLevel
from lib.modules import ModuleBase

from . import profiles as _profiles
from .actions import SnmpActions
from .client import SnmpClient, _HAS_PYSNMP
from .defaults import _SCHEMA, _CHECK_DEFAULTS, _SERVER_DEFAULTS
from .mib_admin import MibAdmin, _HAS_PYSMI
from . import mib_versions as _mib_versions
from .sampler import SnmpSampler

# What is left here is the module itself: the class, the loop over items and the dispatch to
# one check. Everything that answered a different question moved out - speaking SNMP to a
# device (client), administering the MIB catalogue (mib_admin), and the operations the panel
# invokes (actions). They are mixed back in below, so the class is unchanged from the outside.


class Watchful(MibAdmin, SnmpClient, SnmpActions, SnmpSampler, ModuleBase):
    """Multi-server SNMP OID monitoring."""

    ITEM_SCHEMA = _SCHEMA

    MISSING_DEPS: list[str]  = [] if _HAS_PYSNMP else ['pysnmp']
    PARTIAL_DEPS: list[str]  = [] if _HAS_PYSMI  else ['pysmi']

    WATCHFUL_ACTIONS: frozenset[str] = frozenset({
        'discover',
        'list_profiles',
        'detect_profiles',
        'list_mibs',
        'compile_mibs',
        'compile_mibs_start',
        'compile_mibs_status',
        'compile_mibs_cancel',
        'delete_mib',
        'upload_mib',
        'import_mib_from_url',
        'import_mib_from_github',
        'import_mib_from_github_start',
        'import_mib_from_github_status',
        'import_mib_archive',
        'get_mib_details',
        'get_raw_mib_details',
        'get_all_symbols',
        'build_oid_index',
        'save_mib_source',
        'diff_mib_versions',
        'restore_mib_version',
        'list_mib_versions',
        'get_mib_version',
        'lint_mib_source',
        'delete_mib_version',
        'orphan_versions',
        'diff_mib_files',
        'restore_orphan',
        'forget_mib_versions',
    })

    # Actions that produce no side effects — audit logging is suppressed for them.
    READ_ONLY_ACTIONS: frozenset[str] = frozenset({
        'discover',
        'list_profiles',
        'detect_profiles',
        'list_mibs',
        'get_mib_details',
        'get_raw_mib_details',
        'get_all_symbols',
        'list_mib_versions',
        'get_mib_version',
        'diff_mib_versions',
        'lint_mib_source',
        'orphan_versions',
        'diff_mib_files',
    })


    # Toolbar buttons injected into the module card body by the dashboard.
    # Each entry is rendered as a generic button — no module-specific code in web_admin.
    WATCHFUL_TOOLBAR: tuple[dict, ...] = (
        {'icon': 'bi-database-gear', 'label_key': 'file_manager',
         'onclick': 'openFileManagerModal'},
        {'icon': 'bi-diagram-3',     'label_key': 'mib_browser',
         'onclick': 'openMibBrowserModal'},
        {'icon': 'bi-grid-3x3-gap',  'label_key': 'device_profiles',
         'onclick': 'openSnmpProfilesModal'},
    )

    # Legacy compat alias so ModuleBase helpers that expect _DEFAULTS still work
    _DEFAULTS        = _CHECK_DEFAULTS
    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])


    def __init__(self, monitor):
        super().__init__(monitor, __package__)
        self._startup_compile_mibs()

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
        for srv_key, srv in self.get_conf('servers', {}).items():
            if not isinstance(srv, dict):
                continue
            if not srv.get('enabled', _SERVER_DEFAULTS['enabled']):
                continue
            if self.profiles_of(srv):
                sampled.append((srv_key, srv))
            for chk_key, chk_cfg in (srv.get('checks') or {}).items():
                if not isinstance(chk_cfg, dict):
                    continue
                if chk_cfg.get('enabled', _CHECK_DEFAULTS['enabled']):
                    items.append((f'{srv_key}.{chk_key}', chk_cfg, srv))

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


def discover_history_fields(lang: str = 'en_EN', var_dir: str = '') -> dict:
    """Every value a device profile can record, named — see lib.modules.history_fields.

    What this module charts is not knowable at build time: it is decided by the profiles
    installed, which are files, and one of them was written for the box in somebody's rack
    after this release shipped. The static __history__ in schema.json says a check has no
    numeric field, which is true of a check; a sampled metric arrives with a name only if the
    profile that declared it is asked.

    The UNION of the catalogue, not the profiles actually assigned: a field's label answers
    "what is this series", which does not depend on which device happens to serve it, and
    working out the assignments would mean reading the module configuration from a function
    whose whole point is that it does not need it.
    """
    cdir = _profiles.custom_dir(var_dir)
    catalog = _profiles.catalog(custom=_profiles.load_dir(cdir) if cdir else None)
    out: dict = {}
    for prof in catalog.values():
        # First profile to name a field wins: two profiles measuring "cpu_user" are measuring
        # the same thing, and the alternative is a label that changes with dict order.
        for field, meta in _profiles.history_fields(prof, lang).items():
            out.setdefault(field, meta)
    return out


def discover_db_tables():
    """The tables this module keeps in the shared database.

    Edited MIB sources and their history. On the general connector rather than a file beside
    the MIBs because a deployment with a web container and a worker container shares the
    database and not the disk — and a MIB corrected in the panel has to be the MIB the worker
    compiles.
    """
    return [_mib_versions.SCHEMA]
