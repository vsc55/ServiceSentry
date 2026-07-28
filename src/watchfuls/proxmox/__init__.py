#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSentry — Proxmox VE watchful
#
"""Watchful to monitor Proxmox VE via its REST API.

One configured item = one connection to a Proxmox node; the check queries the
whole cluster through it and emits several results (cluster quorum, per-node
status/maintenance, Ceph health, per-node network interfaces, per-node pending
updates), each keyed independently so they notify on their own state changes.

No external dependencies: HTTPS requests use ``urllib`` + ``ssl`` (same pattern
as the ``web`` watchful). Authentication is either an API token (header
``Authorization: PVEAPIToken=<id>=<secret>``) or username+password (a login
ticket placed in the ``PVEAuthCookie`` cookie).
"""

import concurrent.futures
import json
import os
import re

from lib.debug import DebugLevel
from lib.modules import ModuleBase

from .actions import ProxmoxActions
from .checks import ClusterChecks
from .client import PveClient, _split_hosts
from .page import ProxmoxPage
from .provision import ProxmoxProvision

# What is left here is the module itself: the class, the loop over items and the dispatch to
# one check. The four other questions moved out - talking to the API (client), what to ask
# about the cluster (checks), what the panel invokes (actions), what Overview shows (page),
# and writing the monitoring user into the cluster (provision). They are mixed back in below,
# so the class is unchanged from the outside.

_PERM_RE = re.compile(r"user[^ ]* '([^']+)'.*?permission[^ ]* '([^']+)'", re.I)

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)

class Watchful(ClusterChecks, PveClient, ProxmoxActions, ProxmoxPage,
               ProxmoxProvision, ModuleBase):
    """Monitors Proxmox VE clusters/nodes through the REST API."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {
        k: v['default']
        for k, v in _SCHEMA['list'].items()
        if isinstance(v, dict) and 'default' in v
    }
    _MODULE_DEFAULTS = {
        k: v['default']
        for k, v in _SCHEMA['__module__'].items()
        if isinstance(v, dict) and 'default' in v
    }

    # 'provision_token' and 'fix_permissions' are WRITE actions (they change the
    # Proxmox cluster over SSH), so they are intentionally NOT in READ_ONLY_ACTIONS
    # → they require module edit rights and get audited.
    WATCHFUL_ACTIONS: frozenset[str] = frozenset(
        {'test_connection', 'test_permissions', 'provision_token', 'fix_permissions', 'list_nodes'})
    READ_ONLY_ACTIONS: frozenset[str] = frozenset(
        {'test_connection', 'test_permissions', 'list_nodes'})

    def __init__(self, monitor):
        super().__init__(monitor, __package__)


    def check(self):
        if not self.is_enabled:
            self._debug('Proxmox: module disabled, skipping check.', DebugLevel.info)
            return self.dict_return

        names = []
        for key, value in self.get_conf('list', {}).items():
            if not isinstance(value, dict):
                continue
            it = self._resolved_item(key)
            if it.get('enabled', self._DEFAULTS['enabled']):
                names.append(key)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, self.module_default('threads', self._default_threads))
        ) as executor:
            futures = {executor.submit(self._check_item, name): name for name in names}
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f'Check: {name} — Exception: {exc}', DebugLevel.error)
                    _lbl = self.get_conf(['list', name, 'label'], '') or name
                    # send_msg left at its default: this branch used to pass False, which
                    # suppresses the monitor's notification — and nothing sent one by hand,
                    # so an unhandled exception went red in the panel and told nobody.
                    self.dict_return.set(name, False, self._msg('px_error', _lbl, exc),
                                         name=_lbl)

        super().check()
        return self.dict_return

    def _emit_exc(self, key: str, label: str, what: str, exc: Exception,
                  extra: dict = None) -> None:
        """Emit a check failure, classifying a Proxmox 403 as a WARNING with a clear
        'insufficient permission' message instead of a hard error."""
        if getattr(exc, 'code', 0) == 403:
            m = _PERM_RE.search(getattr(exc, 'msg', '') or str(exc))
            detail = (self._msg('px_perm_detail', m.group(2).strip(), m.group(1).strip())
                      if m else str(exc))
            self._emit(key, False,
                       self._msg('px_perm_insufficient', label, what, detail),
                       extra, severity='warning')
        else:
            self._emit(key, False, self._msg('px_check_fail', label, what, exc), extra)

    # ── Per-item check ────────────────────────────────────────────────────

    def _check_item(self, name: str) -> None:
        it = self._resolved_item(name)
        label = (it.get('label', '') or '').strip() or name
        port = int(it.get('port', 0) or self._DEFAULTS['port'])
        verify_ssl = bool(it.get('verify_ssl', False))
        timeout = int(it.get('timeout', 0)
                      or self.module_default('timeout', self._MODULE_DEFAULTS['timeout']))
        alert = int(it.get('alert', 0)
                    or self.module_default('alert', self._MODULE_DEFAULTS['alert']))

        auth_args = (
            str(it.get('auth_method', 'token') or 'token'),
            str(it.get('token_id', '') or ''), str(it.get('token_secret', '') or ''),
            str(it.get('username', '') or ''), str(it.get('password', '') or ''),
        )
        # Candidate addresses for the connection, in priority order:
        #   1. the cluster VIP/FQDN (a floating address that always reaches the
        #      live cluster, independent of which node currently holds it);
        #   2. the configured/bound host(s) (the field accepts several addresses);
        #   3. the cluster node IPs discovered last cycle (cached in the cluster
        #      result) — so one node going down doesn't blind the whole check.
        candidates = _split_hosts(it.get('vip', '') or '') + _split_hosts(it.get('host', '') or '')
        candidates = list(dict.fromkeys(candidates)) or [name]   # dedupe, keep order
        prev = (self.get_status_find(f'{name}/cluster', self.name_module) or {}).get('other_data', {}) or {}
        for ip in (prev.get('node_ips') or []):
            if ip and str(ip) not in candidates:
                candidates.append(str(ip))
        # Cluster roster (host↔node mapping, set by resolve_host for a multi-host
        # binding): correlate each API node with its host, derive the node
        # maintenance set from each member host's maintenance state, and label
        # nodes by host.  No manual node list — a node is "in maintenance" iff its
        # mapped host is (host status + node mapping already express it).
        members = it.get('__cluster_members__') or []
        node_host = {m['node']: m for m in members
                     if isinstance(m, dict) and str(m.get('node') or '').strip()}
        maint = {m['node'] for m in members
                 if isinstance(m, dict) and m.get('maintenance') and str(m.get('node') or '').strip()}
        try:
            conn, _used = self._connect_failover(candidates, port, verify_ssl, timeout, auth_args)
        except Exception as exc:  # pylint: disable=broad-except
            # All candidates unreachable → smooth transient blips with the threshold.
            streak = self.fail_streak(name, True)
            effective = streak < alert
            icon = '🔽' if not effective else '🔼'
            self._emit(name, effective,
                       self._msg('px_conn_fail', label, icon, len(candidates), exc),
                       {'error': str(exc), 'candidates': candidates})
            return
        self.fail_streak(name, False)   # connected → reset the streak

        # Preflight: warn (not error) if the token is missing any privilege the
        # enabled checks need — so a 403 surfaces as a clear, single aviso.
        if it.get('check_permissions', True):
            self._chk_permissions(conn, name, label, it)

        # Node list is shared by the nodes/network/updates/storage checks.
        need_nodes = (it.get('check_nodes', True) or it.get('check_network', False)
                      or it.get('check_updates', True) or it.get('check_storage', False))
        nodes = []
        if need_nodes:
            try:
                nodes = self._pve_get(conn, '/nodes') or []
            except Exception as exc:  # pylint: disable=broad-except
                self._emit_exc(f'{name}/nodes', label, self._msg('px_what_nodes'), exc)

        if it.get('check_cluster', True):
            self._chk_cluster(conn, name, label)
        if it.get('check_nodes', True):
            self._chk_nodes(conn, name, label, nodes, maint, node_host)
        if it.get('check_ceph', False):
            self._chk_ceph(conn, name, label)
        if it.get('check_network', False):
            self._chk_network(conn, name, label, nodes, maint, node_host)
        if it.get('check_updates', True):
            threshold = int(it.get('updates_threshold', 1) or 0)
            self._chk_updates(conn, name, label, nodes, threshold, maint, node_host)
        if it.get('check_storage', False):
            st_threshold = int(it.get('storage_threshold', 90) or 0)
            self._chk_storage(conn, name, label, nodes, st_threshold, maint, node_host)
