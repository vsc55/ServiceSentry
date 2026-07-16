#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Keepalived (VRRP virtual-IP) watchful
#
"""Watchful to monitor a Keepalived VRRP virtual IP (VIP) across an HA cluster.

Host-centric / multi-host binding: one configured item = one VIP guarded by a
cluster of member hosts (the HA nodes, bound via ``host_uids``).  At the cluster
level you configure the VIP; per member host you configure its *priority*
(weight) — stored on the host's ``keepalived`` profile and editable in the
cluster's Hosts tab.

Each cycle the check connects to every member host (locally or over SSH, via
:meth:`ModuleBase.host_exec`) and reads two things:

  * the keepalived service state (``systemctl is-active keepalived``);
  * whether that node currently holds the VIP (``ip -o addr show`` — the VRRP
    MASTER is the node that owns the floating address).

It then emits per-node results (``<key>/node/<host>``) plus a cluster roll-up
for the VIP (``<key>/vip``): OK when exactly one node holds it, an *error* when
no node does (VIP down), and a *warning* on split-brain (several holders).  With
``check_priority`` on, it also warns (``<key>/priority``) when the VIP sits on a
node that is not the highest-priority one currently alive.

Linux only (keepalived/VRRP is a Linux stack).  No external dependencies.
"""

import json
import os
import re

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)

# Extract bare IP addresses (v4/v6, without CIDR mask) from `ip -o addr show`.
_ADDR_RE = re.compile(r'\binet6?\s+([^\s/]+)')
# The SVC=<state> line our probe command prints before the address dump.
_SVC_RE = re.compile(r'^SVC=(\S+)', re.MULTILINE)


def _to_int(value, default=None):
    """Best-effort int (a per-host priority may be blank/str/None)."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _addr_set(out: str) -> set:
    """Set of bare IP addresses present in `ip -o addr show` output."""
    return {a.split('/')[0] for a in _ADDR_RE.findall(out or '')}


def _svc_state(out: str) -> str:
    """The keepalived service state from our probe's ``SVC=<state>`` line."""
    m = _SVC_RE.search(out or '')
    return (m.group(1) if m else 'unknown').strip().lower()


class Watchful(ModuleBase):
    """Monitors a Keepalived VRRP virtual IP across its member hosts."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])
    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    # ── Monitoring loop ───────────────────────────────────────────────────

    def check(self):
        if not self.is_enabled:
            self._debug('Keepalived: module disabled, skipping.', DebugLevel.info)
            return self.dict_return

        items = [(k, v) for k, v in self.get_conf('list', {}).items()
                 if isinstance(v, dict) and v.get('enabled', self._DEFAULTS['enabled'])]
        self.run_parallel(items, self._check_item, 'Keepalived')
        super().check()
        return self.dict_return

    def _emit(self, key: str, status: bool, message: str, other: dict = None,
              severity: str = None) -> None:
        """Record a result and notify only on a status change (like the other
        watchfuls). ``severity='warning'`` marks a non-OK result as an aviso
        (yellow in the UI) instead of a hard error."""
        name = (self.get_conf(['list', str(key).split('/')[0], 'label'], '') or '').strip()
        self.dict_return.set(key, status, message, False, other or {}, severity, name=name)
        if self.check_status(status, self.name_module, key):
            self.send_message(message, status, item=name)

    def _check_item(self, key: str, raw: dict) -> None:
        it = self.resolve_host(raw)
        if not it.get('enabled', True):
            return
        label = (it.get('label') or '').strip() or key
        vip_raw = str(it.get('vip') or '').strip()
        vip_ip = vip_raw.split('/')[0].strip()
        vrid = _to_int(it.get('router_id')) or None      # 0/blank → not set
        vip_extra = {'vip': vip_ip, **({'vrid': vrid} if vrid else {})}
        timeout = self.module_default('timeout', self._MODULE_DEFAULTS['timeout'])
        check_service = it.get('check_service', self._DEFAULTS['check_service'])
        check_vip = it.get('check_vip', self._DEFAULTS['check_vip'])
        check_priority = it.get('check_priority', self._DEFAULTS['check_priority'])

        members = it.get('__cluster_members__') or []
        if not members:
            self._emit(key, False,
                       self._msg('ka_no_members', label), severity='warning')
            return
        if not vip_ip:
            self._emit(f'{key}/vip', False,
                       self._msg('ka_no_vip', label),
                       {'vip': ''}, severity='warning')

        # One probe per member host: service state + its current addresses.
        # Match the VIP by address across all interfaces (interface names can differ
        # between nodes, e.g. eth0 vs ens18), so no per-interface filter is needed.
        probe = ('echo "SVC=$(systemctl is-active keepalived 2>/dev/null || echo unknown)"; '
                 'ip -o addr show 2>/dev/null')

        holders = []          # (name, priority) of nodes currently holding the VIP
        alive_prio = []       # (name, priority) of reachable, service-active nodes
        for m in members:
            uid = str(m.get('host_uid') or '').strip()
            name = (m.get('name') or uid or '?').strip()
            extra = {'host_uid': uid, 'host_name': name}
            if m.get('maintenance'):
                # A member in maintenance does not fail the cluster — skip its node.
                continue
            mi = self.resolve_host({'host_uid': uid}) if uid else it
            if mi.get('_host_maintenance'):
                continue
            priority = _to_int(mi.get('priority'))
            out, err, code = self.host_exec(mi, probe, timeout=timeout)
            if code != 0 and not (out or '').strip():
                self._emit(f'{key}/node/{name}', False,
                           self._msg('ka_host_unreachable', label, name,
                                     (err or '').strip() or code), extra)
                continue

            svc = _svc_state(out)
            holds = bool(vip_ip) and vip_ip in _addr_set(out)
            node_extra = {**extra, 'service': svc, 'holds_vip': holds}
            if priority is not None:
                node_extra['priority'] = priority

            if check_service and svc != 'active':
                self._emit(f'{key}/node/{name}', False,
                           self._msg('ka_service', label, name, svc), node_extra)
            else:
                role = 'MASTER' if holds else 'BACKUP'
                prio_txt = self._msg('ka_prio_suffix', priority) if priority is not None else ''
                self._emit(f'{key}/node/{name}', True,
                           self._msg('ka_node_ok', label, name, role, svc, prio_txt),
                           node_extra)
                if svc == 'active':
                    alive_prio.append((name, priority))
            if holds:
                holders.append((name, priority))

        # ── VIP roll-up: exactly one holder is healthy ────────────────────
        if check_vip and vip_ip:
            if len(holders) == 1:
                self._emit(f'{key}/vip', True,
                           self._msg('ka_vip_active', label, vip_ip, holders[0][0]),
                           {**vip_extra, 'holder': holders[0][0], 'holders': 1})
            elif not holders:
                self._emit(f'{key}/vip', False,
                           self._msg('ka_vip_none', label, vip_ip),
                           {**vip_extra, 'holders': 0})
            else:
                names = ', '.join(h[0] for h in holders)
                self._emit(f'{key}/vip', False,
                           self._msg('ka_vip_split', label, vip_ip, names),
                           {**vip_extra, 'holders': len(holders)}, severity='warning')

        # ── Priority: the VIP should sit on the highest-priority alive node ─
        if check_priority and len(holders) == 1:
            rated = [(n, p) for n, p in alive_prio if p is not None]
            hn, hp = holders[0]
            if rated and hp is not None:
                top = max(p for _, p in rated)
                if hp < top:
                    self._emit(f'{key}/priority', False,
                               self._msg('ka_prio_low', label, hn, hp, top),
                               {'holder': hn, 'holder_priority': hp, 'top_priority': top},
                               severity='warning')
                else:
                    self._emit(f'{key}/priority', True,
                               self._msg('ka_prio_ok', label),
                               {'holder': hn, 'holder_priority': hp})
