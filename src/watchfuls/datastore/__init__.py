#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Datastore connectivity watchful — MySQL/MariaDB, PostgreSQL, MSSQL,
MongoDB, Redis, Valkey, Elasticsearch, OpenSearch, InfluxDB, Memcached."""

import concurrent.futures
import json
import os

from lib.modules import ModuleBase

from .actions import DatastoreActions
from .checks import DatastoreChecks
from . import deps
from .engines import EngineDrivers
from .tables import ConfigOptions

# What is left here is the module itself: the class, the loop over items and the resolution
# of an item's settings. The rest moved out by what it is about — which client libraries are
# installed (deps), the static lookups (tables), reaching a host that is not exposed
# (tunnel), how each engine is spoken to (engines), what to report about an item (checks) and
# what the panel invokes (actions). They are mixed back in below, so the class is unchanged
# from the outside.

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))



# ── Watchful ──────────────────────────────────────────────────────────────────

class Watchful(DatastoreChecks, EngineDrivers, DatastoreActions, ModuleBase):

    ITEM_SCHEMA = _SCHEMA
    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'test_connection', 'list_databases'})
    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])

    # If pymysql itself is missing the module cannot function at all → full disable.
    # If only optional backends are missing → warning badge, module stays usable.
    MISSING_DEPS: list[str] = deps._MISSING_BACKENDS if not deps._PYMYSQL else []
    PARTIAL_DEPS: list[str] = deps._MISSING_BACKENDS if deps._PYMYSQL else []

    def __init__(self, monitor):
        super().__init__(monitor, __package__)
    # ── Runtime monitoring ────────────────────────────────────────────

    def check(self):
        items = [k for k, v in self.get_conf('list', {}).items()
                 if (v if isinstance(v, bool) else
                     (v.get('enabled', self._DEFAULTS['enabled']) if isinstance(v, dict)
                      else self._DEFAULTS['enabled']))]
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, self.module_default('threads', self._default_threads))) as ex:
            futures = {ex.submit(self._ds_check, key): key for key in items}
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    _lbl = self.get_conf(['list', key, 'label'], '') or key
                    self.dict_return.set(key, False, self._msg('ds_error', _lbl, exc),
                                         name=_lbl)
        super().check()
        return self.dict_return

    # ── Config helpers ─────────────────────────────────────────────────

    def _get_conf(self, opt: ConfigOptions, key: str, default=None):
        if default is None:
            match opt:
                case ConfigOptions.port:
                    default = self.get_conf('port', self._DEFAULTS['port'])
                case ConfigOptions.ssh_port:
                    default = self.get_conf('ssh_port', self._DEFAULTS.get('ssh_port', 22))
                case ConfigOptions.db_index:
                    default = self.get_conf('db_index', self._DEFAULTS.get('db_index', 0))
                case ConfigOptions.tls:
                    default = self.get_conf('tls', self._DEFAULTS.get('tls', False))
                case ConfigOptions.timeout:
                    default = self.module_default('timeout', self._DEFAULTS.get('timeout', 10) or 10)
                case ConfigOptions.enabled:
                    default = self.get_conf('enabled', self._DEFAULTS['enabled'])
                case _:
                    default = self.get_conf(opt.name, self._DEFAULTS.get(opt.name, ''))
        # Read from the host-resolved item so host_uid-bound checks inherit the
        # host's connection; falls back to the default when the field is absent.
        item = self._resolved_item(key)
        val = item.get(opt.name, default) if isinstance(item, dict) else default
        match opt:
            case ConfigOptions.port | ConfigOptions.ssh_port | ConfigOptions.db_index | ConfigOptions.timeout:
                return self._parse_conf_int(val, default)
            case ConfigOptions.enabled | ConfigOptions.tls | ConfigOptions.ssh_verify_host:
                # Bool fields: a string parse would turn False into "False"
                # (truthy) — e.g. ssh_verify_host=False would wrongly enable strict
                # host-key checking.  Coerce to a real bool.
                return bool(val)
            case _:
                return self._parse_conf_str(val, default)
