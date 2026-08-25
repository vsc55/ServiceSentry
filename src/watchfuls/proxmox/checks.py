#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSentry - Proxmox VE watchful: what it asks about the cluster.
#
"""One family of questions: is this cluster healthy.

Quorum, per-node status and maintenance, Ceph, per-node network interfaces, pending updates
and storage usage - plus the privilege check that runs first, because a check reporting
"cannot read that" is more useful than one reporting a cluster with no nodes.

Each result is keyed independently so it notifies on its own state change: a node coming back
should not be silenced by Ceph still being unhappy.
"""

from .client import PveError


# Proxmox apt/update entry fields that mark a security update (defensive: the API
# does not expose a dedicated flag, so we look for "security" in the origin/title).
def _is_security(upd: dict) -> bool:
    blob = ' '.join(
        str(upd.get(k, '')) for k in ('Origin', 'Title', 'Section', 'Priority')
    ).lower()
    return 'security' in blob


# Substrings in a Ceph error that mean "Ceph is simply not installed/initialised"
# (so the check reports it as not-configured instead of failing).
_CEPH_ABSENT = ('rados', 'not initialized', 'not installed', 'binary',
                'no such file', 'command', 'unable to')


class ClusterChecks:
    """The per-item checks, mixed into ``Watchful``."""

    @staticmethod
    def _required_privs(it: dict) -> list:
        """[(priv, path, feature)] the item's *enabled* checks need from Proxmox."""
        req = [('Sys.Audit', '/', 'base')]                 # cluster/nodes/ceph/ha/network
        if it.get('check_storage', False):
            req.append(('Datastore.Audit', '/', 'storage'))
        if it.get('check_updates', True):
            # GET /nodes/{node}/apt/update is gated behind Sys.Modify in Proxmox.
            req.append(('Sys.Modify', '/nodes', 'updates'))
        return req

    @staticmethod
    def _perm_has(perms: dict, path: str, priv: str) -> bool:
        """True if *priv* is granted on *path* or any ancestor (perms propagate down).
        *perms* is the GET /access/permissions effective map ({path: {priv: 1}})."""
        parts = [p for p in str(path).split('/') if p]
        checks, cur = ['/'], ''
        for p in parts:
            cur += '/' + p
            checks.append(cur)
        return any(isinstance(perms.get(c), dict) and perms[c].get(priv) for c in checks)

    def _chk_permissions(self, conn: dict, name: str, label: str, it: dict) -> None:
        """Preflight: verify the monitoring token holds every privilege the enabled
        checks need; report any missing as a single warning (not a hard error)."""
        key = f'{name}/permissions'
        try:
            perms = self._pve_get(conn, '/access/permissions') or {}
        except Exception as exc:  # pylint: disable=broad-except
            self._emit_exc(key, label, self._msg('px_what_perms'), exc)
            return
        if not isinstance(perms, dict):
            perms = {}
        missing = [f'{p} ({path})' for p, path, _f in self._required_privs(it)
                   if not self._perm_has(perms, path, p)]
        if missing:
            self._emit(key, False,
                       self._msg('px_perms_missing', label, ', '.join(missing)),
                       {'missing': ', '.join(missing)}, severity='warning')
        else:
            self._emit(key, True, self._msg('px_perms_ok', label))

    @staticmethod
    def _node_tag(node: str, node_host: dict) -> str:
        """`` (host name)`` suffix when the API node maps to a registry host."""
        m = (node_host or {}).get(node)
        return f' ({m["name"]})' if m and m.get('name') else ''

    @staticmethod
    def _node_extra(node: str, node_host: dict) -> dict:
        """Host identity to attach to a node's result (host_uid/host_name)."""
        m = (node_host or {}).get(node)
        if not isinstance(m, dict):
            return {}
        out = {}
        if m.get('host_uid'):
            out['host_uid'] = m['host_uid']
        if m.get('name'):
            out['host_name'] = m['name']
        return out

    # ── Individual checks ─────────────────────────────────────────────────

    def _chk_cluster(self, conn: dict, name: str, label: str) -> None:
        key = f'{name}/cluster'
        try:
            data = self._pve_get(conn, '/cluster/status') or []
        except Exception as exc:  # pylint: disable=broad-except
            self._emit_exc(key, label, self._msg('px_what_cluster'), exc)
            return
        cluster = next((e for e in data if e.get('type') == 'cluster'), None)
        nodes = [e for e in data if e.get('type') == 'node']
        online = sum(1 for e in nodes if e.get('online'))
        # Cache the cluster's node IPs so the next cycle can fail over between
        # nodes even if only one address was configured.
        node_ips = [str(e['ip']) for e in nodes if e.get('ip')]
        if cluster is None:
            self._emit(key, True, self._msg('px_standalone', label),
                       {'standalone': True, 'node_ips': node_ips})
            return
        quorate = bool(cluster.get('quorate'))
        cname = cluster.get('name', '')
        icon = '🔼' if quorate else '🔽'
        qtxt = self._msg('px_quorum_ok' if quorate else 'px_quorum_lost')
        self._emit(key, quorate,
                   self._msg('px_cluster', label, icon, cname, qtxt, online, len(nodes)),
                   {'quorate': quorate, 'nodes_online': online, 'nodes_total': len(nodes),
                    'node_ips': node_ips})

    def _chk_nodes(self, conn: dict, name: str, label: str, nodes: list,
                   maint: set = frozenset(), node_host: dict = None) -> None:
        # Maintenance is reported by the HA manager (only when HA is configured).
        ha = {}
        try:
            for e in (self._pve_get(conn, '/cluster/ha/status/current') or []):
                node = e.get('node') or e.get('name')
                if node and (e.get('type') == 'node' or 'node' in e):
                    ha[node] = str(e.get('status', '')).lower()
        except Exception:  # pylint: disable=broad-except
            pass   # no HA → no maintenance info
        for n in nodes:
            node = n.get('node')
            if not node:
                continue
            key = f'{name}/node/{node}'
            tag = self._node_tag(node, node_host)
            extra = self._node_extra(node, node_host)
            online = str(n.get('status', '')) == 'online'
            if node in maint:
                # User-declared maintenance: never alert (e.g. powered off on purpose).
                self._emit(key, True, self._msg('px_node_maint_manual', label, node, tag),
                           {'maintenance': True, **extra})
            elif not online:
                self._emit(key, False, self._msg('px_node_offline', label, node, tag), extra)
            elif ha.get(node) == 'maintenance':
                self._emit(key, True, self._msg('px_node_maint', label, node, tag),
                           {'maintenance': True, **extra})
            else:
                self._emit(key, True, self._msg('px_node_online', label, node, tag), extra)

    def _chk_ceph(self, conn: dict, name: str, label: str) -> None:
        key = f'{name}/ceph'
        try:
            data = self._pve_get(conn, '/cluster/ceph/status') or {}
        except PveError as exc:
            low = str(exc.msg).lower()
            if exc.code in (404, 501) or any(t in low for t in _CEPH_ABSENT):
                self._emit(key, True, self._msg('px_ceph_absent', label))
                return
            self._emit_exc(key, label, 'Ceph', exc)
            return
        except Exception as exc:  # pylint: disable=broad-except
            self._emit_exc(key, label, 'Ceph', exc)
            return
        # Ceph says one of THREE things, and this read two of them. `HEALTH_WARN` is the one
        # a cluster spends its time in — a disk being backfilled, a clock a second out, a pool
        # over its target ratio — and every one of those came out RED, beside the failures that
        # mean a phone call. A rack that is permanently red is a rack nobody looks at.
        #
        # Anything unrecognised is a warning too, and deliberately not an error: an answer this
        # panel has no word for is not the same statement as `HEALTH_ERR`, and inventing the
        # worse of the two is the panel deciding something Ceph did not say.
        health = str((data.get('health') or {}).get('status') or '').upper()
        ok = (health == 'HEALTH_OK')
        bad = (health == 'HEALTH_ERR')
        icon = '🔼' if ok else ('🔽' if bad else '⚠')
        self._emit(key, ok, self._msg('px_ceph', label, icon, health or self._msg('px_unknown')),
                   {'health': health}, severity='' if (ok or bad) else 'warning')

    def _chk_network(self, conn: dict, name: str, label: str, nodes: list,
                     maint: set = frozenset(), node_host: dict = None) -> None:
        for n in nodes:
            node = n.get('node')
            if not node or node in maint or str(n.get('status', '')) != 'online':
                continue
            key = f'{name}/net/{node}'
            tag = self._node_tag(node, node_host)
            extra = self._node_extra(node, node_host)
            try:
                ifaces = self._pve_get(conn, f'/nodes/{node}/network') or []
            except Exception as exc:  # pylint: disable=broad-except
                self._emit_exc(key, label, f'{self._msg("px_what_net")} {node}{tag}', exc, extra)
                continue
            # Flag autostart interfaces that are not currently active (down).
            down = [i.get('iface') for i in ifaces
                    if i.get('type') != 'loopback' and i.get('autostart') and not i.get('active')]
            down = [d for d in down if d]
            if down:
                self._emit(key, False,
                           self._msg('px_net_down', label, node, tag, ', '.join(down)),
                           {'down': down, **extra})
            else:
                self._emit(key, True, self._msg('px_net_ok', label, node, tag), extra)

    def _chk_updates(self, conn: dict, name: str, label: str, nodes: list,
                     threshold: int, maint: set = frozenset(), node_host: dict = None) -> None:
        for n in nodes:
            node = n.get('node')
            if not node or node in maint or str(n.get('status', '')) != 'online':
                continue
            key = f'{name}/updates/{node}'
            tag = self._node_tag(node, node_host)
            extra = self._node_extra(node, node_host)
            try:
                ups = self._pve_get(conn, f'/nodes/{node}/apt/update') or []
            except Exception as exc:  # pylint: disable=broad-except
                self._emit_exc(key, label, f'{self._msg("px_what_updates")} {node}{tag}', exc, extra)
                continue
            total = len(ups)
            security = sum(1 for u in ups if _is_security(u))
            if security > 0:
                self._emit(key, False,
                           self._msg('px_upd_security', label, node, tag, security, total),
                           {'total': total, 'security': security, **extra},
                           severity='warning')
            elif threshold > 0 and total >= threshold:
                self._emit(key, True,
                           self._msg('px_upd_available', label, node, tag, total),
                           {'total': total, 'security': 0, **extra})
            else:
                self._emit(key, True, self._msg('px_upd_ok', label, node, tag),
                           {'total': total, 'security': 0, **extra})

    def _chk_storage(self, conn: dict, name: str, label: str, nodes: list,
                     threshold: int, maint: set = frozenset(), node_host: dict = None) -> None:
        for n in nodes:
            node = n.get('node')
            if not node or node in maint or str(n.get('status', '')) != 'online':
                continue
            key = f'{name}/storage/{node}'
            tag = self._node_tag(node, node_host)
            extra = self._node_extra(node, node_host)
            try:
                stores = self._pve_get(conn, f'/nodes/{node}/storage') or []
            except Exception as exc:  # pylint: disable=broad-except
                self._emit_exc(key, label, f'{self._msg("px_what_storage")} {node}{tag}', exc, extra)
                continue
            down, full = [], []   # enabled-but-inactive, and over-usage-threshold
            for s in stores:
                if not s.get('enabled', 1):
                    continue          # disabled storage: skip
                sid = s.get('storage') or '?'
                if not s.get('active', 1):
                    down.append(sid)
                    continue
                total = s.get('total') or 0
                frac = s.get('used_fraction')
                if frac is None:
                    frac = (s.get('used') or 0) / total if total else 0
                pct = round((frac or 0) * 100)
                if threshold > 0 and pct >= threshold:
                    full.append(f'{sid} {pct}%')
            if down or full:
                parts = []
                if down:
                    parts.append(self._msg('px_storage_inactive', ', '.join(down)))
                if full:
                    parts.append(self._msg('px_storage_full', ', '.join(full)))
                self._emit(key, False,
                           self._msg('px_storage_bad', label, node, tag, ' · '.join(parts)),
                           {'down': down, 'full': full, **extra})
            else:
                self._emit(key, True, self._msg('px_storage_ok', label, node, tag), extra)
