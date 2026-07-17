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
import ssl
import urllib.error
import urllib.parse
import urllib.request

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)


class PveError(Exception):
    """Proxmox API error carrying the HTTP status code (0 = connection error)."""

    def __init__(self, code: int, msg: str = ''):
        self.code = code
        self.msg = msg
        super().__init__(f'HTTP {code}: {msg}' if code else (msg or 'connection error'))


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

# Least-privilege privilege set for the provisioned monitoring role: system-level
# reads (cluster/ceph/ha status, nodes, network) need Sys.Audit; reading storage
# status (/nodes/{node}/storage) needs Datastore.Audit. Still far tighter than the
# built-in PVEAuditor role.
#
# NOTE: the apt/update LIST endpoint (GET /nodes/{node}/apt/update) is gated behind
# Sys.Modify in Proxmox — even though it's a read — so the *updates* check needs
# Sys.Modify too. It's NOT in the base set (it broadens the token to node-modify);
# provisioning adds it only when the admin opts in (config 'allow_updates').
_MONITOR_PRIVS = 'Sys.Audit, Datastore.Audit'
_UPDATES_PRIV = 'Sys.Modify'

# Extracts "(/path, Priv)" from a Proxmox 403 "Permission check failed (...)" body.
_PERM_RE = re.compile(r'Permission check failed \(([^,]+),\s*([^)\n]+)\)')


def _split_hosts(value: str) -> list:
    """Split a host field into a candidate address list (comma/space/newline) — a
    Proxmox cluster has several nodes, so the check can fail over between them."""
    return [h for h in re.split(r'[,\s]+', str(value or '').strip()) if h]


def _shq(value: str) -> str:
    """POSIX single-quote a value for safe interpolation into an SSH command."""
    return "'" + str(value).replace("'", "'\\''") + "'"


def _extract_json(text: str):
    """Return the JSON object found in *text* (the ``pveum ... --output-format
    json`` stdout), or None. Tolerates surrounding noise."""
    text = (text or '').strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # pylint: disable=broad-except
        pass
    start, end = text.find('{'), text.rfind('}')
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except Exception:  # pylint: disable=broad-except
            return None
    return None


class Watchful(ModuleBase):
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

    # ── Monitoring loop ───────────────────────────────────────────────────

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
                    self.dict_return.set(name, False, self._msg('px_error', _lbl, exc), False)

        super().check()
        return self.dict_return

    def _resolved_item(self, key: str) -> dict:
        """Item config for *key* with any referenced host merged in (no-op when
        inline). Cached per check cycle (the monitor builds a fresh instance each
        cycle)."""
        cache = self.__dict__.setdefault('_resolved_items', {})
        if key not in cache:
            raw = self.get_conf(['list', key], {})
            cache[key] = self.resolve_host(raw) if isinstance(raw, dict) else {}
        return cache[key]

    def _emit(self, key: str, status: bool, message: str, other: dict = None,
              severity: str = None) -> None:
        """Record a result and notify only on a status change (like the other
        watchfuls). ``severity='warning'`` marks a non-OK result as an aviso
        (yellow in the UI) instead of a hard error."""
        name = (self.get_conf(['list', str(key).split('/')[0], 'label'], '') or '').strip()
        self.dict_return.set(key, status, message, False, other or {}, severity, name=name)
        if self.check_status(status, self.name_module, key):
            self.send_message(message, status, item=name)

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
        health = str((data.get('health') or {}).get('status') or '').upper()
        ok = (health == 'HEALTH_OK')
        icon = '🔼' if ok else '🔽'
        self._emit(key, ok, self._msg('px_ceph', label, icon, health or self._msg('px_unknown')),
                   {'health': health})

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

    # ── API client (stateless; usable from the test_connection classmethod) ─

    @staticmethod
    def _request(url: str, *, method: str = 'GET', data: dict = None,
                 headers: dict = None, verify_ssl: bool = True,
                 timeout: int = 10) -> tuple[int, str]:
        """Low-level HTTPS request. Returns (status_code, body_text).

        Raises ``PveError`` on HTTP error (with the status code) or on a
        connection/transport error (code 0).
        """
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('User-Agent', 'ServiceSentry/1.0')
        req.add_header('Accept', 'application/json')
        for k, v in (headers or {}).items():
            req.add_header(k, v)

        kwargs: dict = {}
        if not verify_ssl and url.startswith('https://'):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs['context'] = ctx
        try:
            with urllib.request.urlopen(req, timeout=timeout, **kwargs) as resp:
                return resp.status, resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = exc.read().decode('utf-8', errors='replace')
            except Exception:  # pylint: disable=broad-except
                pass
            raise PveError(exc.code, (detail or str(exc))[:300]) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise PveError(0, str(getattr(exc, 'reason', exc))) from exc

    @classmethod
    def _connect(cls, host: str, port: int, verify_ssl: bool, timeout: int,
                 auth_method: str, token_id: str, token_secret: str,
                 username: str, password: str) -> dict:
        """Build a connection context (base URL + auth headers). For password
        auth it logs in to obtain a ticket. Raises ``PveError`` on failure."""
        base = f'https://{host}:{port}/api2/json'
        # SSRF guard (blocks link-local/metadata; private hosts allowed) like web.
        from lib.security.net_guard import validate_external_url  # noqa: PLC0415
        reason = validate_external_url(f'https://{host}:{port}')
        if reason:
            raise PveError(0, f'Bloqueado: {reason}')

        if auth_method == 'password':
            if not username:
                raise PveError(0, 'usuario requerido')
            code, text = cls._request(
                f'{base}/access/ticket', method='POST',
                data={'username': username, 'password': password},
                verify_ssl=verify_ssl, timeout=timeout,
            )
            ticket = ((json.loads(text or '{}') or {}).get('data') or {}).get('ticket')
            if not ticket:
                raise PveError(code, 'login fallido')
            headers = {'Cookie': f'PVEAuthCookie={ticket}'}
        else:
            if not token_id or not token_secret:
                raise PveError(0, 'token_id y token_secret requeridos')
            headers = {'Authorization': f'PVEAPIToken={token_id}={token_secret}'}

        return {'base': base, 'headers': headers,
                'verify_ssl': verify_ssl, 'timeout': timeout}

    @classmethod
    def _pve_get(cls, conn: dict, path: str):
        """GET *path* and return the JSON ``data`` payload (raises on HTTP error)."""
        _code, text = cls._request(
            conn['base'] + path, headers=conn['headers'],
            verify_ssl=conn['verify_ssl'], timeout=conn['timeout'],
        )
        return (json.loads(text or '{}') or {}).get('data')

    def _connect_failover(self, candidates: list, port: int, verify_ssl: bool,
                          timeout: int, auth_args: tuple):
        """Try each candidate node address until one connects AND answers a cheap
        probe (``/version``); a Proxmox cluster has several nodes, so a single one
        being down must not blind the whole check.  Returns ``(conn, address)`` or
        raises the last error.  (Instance method so the per-check ``_pve_get`` and
        this probe share the same path — and the same test patch.)"""
        last = None
        for addr in candidates:
            try:
                conn = self._connect(addr, port, verify_ssl, timeout, *auth_args)
                self._pve_get(conn, '/version')   # probe: reachable + authenticated
                return conn, addr
            except Exception as exc:  # pylint: disable=broad-except
                last = exc
        raise last or PveError(0, 'sin nodos alcanzables')

    # ── Web action ────────────────────────────────────────────────────────

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/proxmox/test_connection

        Connects with the item's settings and returns a one-line summary
        (cluster name, quorum, node count, Ceph presence).
        Returns {"ok": bool, "message": str}.
        """
        candidates = (_split_hosts(config.get('vip') or '') + _split_hosts(config.get('host') or '')
                      or _split_hosts(config.get('_item_key') or ''))
        candidates = list(dict.fromkeys(candidates))
        if not candidates:
            return {'ok': False, 'message': 'Host requerido'}
        port = int(config.get('port') or cls._DEFAULTS['port'])
        verify_ssl = bool(config.get('verify_ssl', False))
        timeout = int(config.get('timeout') or cls._MODULE_DEFAULTS.get('timeout', 10))
        auth_args = (
            str(config.get('auth_method') or 'token'),
            str(config.get('token_id') or ''), str(config.get('token_secret') or ''),
            str(config.get('username') or ''), str(config.get('password') or ''),
        )
        # Failover across the candidate node addresses (inline so this classmethod
        # stays self-contained).
        conn, last = None, None
        for addr in candidates:
            try:
                c = cls._connect(addr, port, verify_ssl, timeout, *auth_args)
                cls._pve_get(c, '/version')
                conn = c
                break
            except Exception as exc:  # pylint: disable=broad-except
                last = exc
        if conn is None:
            return {'ok': False, 'message': f'Error: {last}'}
        try:
            status = cls._pve_get(conn, '/cluster/status') or []
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': f'Error: {exc}'}

        cluster = next((e for e in status if e.get('type') == 'cluster'), None)
        nodes = [e for e in status if e.get('type') == 'node']
        online = sum(1 for e in nodes if e.get('online'))
        ceph = 'n/d'
        try:
            cdata = cls._pve_get(conn, '/cluster/ceph/status') or {}
            ceph = str((cdata.get('health') or {}).get('status') or '') or 'n/d'
        except Exception:  # pylint: disable=broad-except
            ceph = 'no instalado'

        if cluster:
            qtxt = 'OK' if cluster.get('quorate') else 'PERDIDO'
            msg = (f"Clúster '{cluster.get('name', '')}' · quórum {qtxt} · "
                   f"{online}/{len(nodes)} nodos online · Ceph: {ceph}")
        else:
            msg = f'Nodo standalone (sin clúster) · Ceph: {ceph}'
        return {'ok': True, 'message': msg}

    @classmethod
    def test_permissions(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/proxmox/test_permissions

        Connect with the configured token and verify it holds every privilege the
        currently-enabled checks need (Sys.Audit always; Datastore.Audit for
        storage; Sys.Modify for the apt/update list). Read-only.

        Returns {"ok": bool, "message": str,
                 "results": [{priv, path, feature, ok}, …]}.
        """
        candidates = (_split_hosts(config.get('vip') or '') + _split_hosts(config.get('host') or '')
                      or _split_hosts(config.get('_item_key') or ''))
        candidates = list(dict.fromkeys(candidates))
        if not candidates:
            return {'ok': False, 'message': 'Host requerido'}
        port = int(config.get('port') or cls._DEFAULTS['port'])
        verify_ssl = bool(config.get('verify_ssl', False))
        timeout = int(config.get('timeout') or cls._MODULE_DEFAULTS.get('timeout', 10))
        auth_args = (
            str(config.get('auth_method') or 'token'),
            str(config.get('token_id') or ''), str(config.get('token_secret') or ''),
            str(config.get('username') or ''), str(config.get('password') or ''),
        )
        conn, last = None, None
        for addr in candidates:
            try:
                c = cls._connect(addr, port, verify_ssl, timeout, *auth_args)
                cls._pve_get(c, '/version')
                conn = c
                break
            except Exception as exc:  # pylint: disable=broad-except
                last = exc
        if conn is None:
            return {'ok': False, 'message': f'Error: {last}'}
        try:
            perms = cls._pve_get(conn, '/access/permissions') or {}
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': f'Error: {exc}'}
        if not isinstance(perms, dict):
            perms = {}
        results = [
            {'priv': priv, 'path': path, 'feature': feature,
             'ok': cls._perm_has(perms, path, priv)}
            for priv, path, feature in cls._required_privs(config)
        ]
        all_ok = all(r['ok'] for r in results)
        miss = [f"{r['priv']} ({r['path']})" for r in results if not r['ok']]
        msg = ('Todos los permisos necesarios están concedidos' if all_ok
               else 'Faltan permisos: ' + ', '.join(miss))
        # ok=True means "the test ran" (connected + queried); the per-privilege
        # verdict is in `info` so the result modal shows it even when some are
        # missing (the modal mode only renders info on ok=True).
        info = [[f"{r['priv']} ({r['path']})", '✅' if r['ok'] else '❌']
                for r in results]
        return {'ok': True, 'all_ok': all_ok, 'message': msg,
                'variant': 'success' if all_ok else 'warning',
                'info': info, 'results': results}

    @classmethod
    def list_nodes(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/proxmox/list_nodes

        Return the cluster member node names — for the host↔node mapping picker,
        so the user assigns each member host its node without typing it by hand.
        Returns {"ok": bool, "items": [node, …], "message": str}.
        """
        candidates = (_split_hosts(config.get('vip') or '') + _split_hosts(config.get('host') or '')
                      or _split_hosts(config.get('_item_key') or ''))
        candidates = list(dict.fromkeys(candidates))
        if not candidates:
            return {'ok': False, 'message': 'Host requerido', 'items': []}
        port = int(config.get('port') or cls._DEFAULTS['port'])
        verify_ssl = bool(config.get('verify_ssl', False))
        timeout = int(config.get('timeout') or cls._MODULE_DEFAULTS.get('timeout', 10))
        auth_args = (
            str(config.get('auth_method') or 'token'),
            str(config.get('token_id') or ''), str(config.get('token_secret') or ''),
            str(config.get('username') or ''), str(config.get('password') or ''),
        )
        conn, last = None, None
        for addr in candidates:
            try:
                c = cls._connect(addr, port, verify_ssl, timeout, *auth_args)
                cls._pve_get(c, '/version')
                conn = c
                break
            except Exception as exc:  # pylint: disable=broad-except
                last = exc
        if conn is None:
            return {'ok': False, 'message': f'Error: {last}', 'items': []}
        try:
            status = cls._pve_get(conn, '/cluster/status') or []
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': f'Error: {exc}', 'items': []}
        names = [str(e.get('name')) for e in status
                 if e.get('type') == 'node' and e.get('name')]
        if not names:                      # standalone node (no cluster section)
            try:
                names = [str(n.get('node')) for n in (cls._pve_get(conn, '/nodes') or [])
                         if n.get('node')]
            except Exception:  # pylint: disable=broad-except
                names = []
        names = sorted(dict.fromkeys(names))
        return {'ok': True, 'items': names, 'message': f'{len(names)} nodo(s)'}

    @classmethod
    def _widget_labels(cls, lang: str) -> dict:
        """The ``widget`` label section from the module's lang/ (fallback en_EN)."""
        ldir = os.path.join(os.path.dirname(__file__), 'lang')
        for fn in (f'{lang}.json', 'en_EN.json'):
            p = os.path.join(ldir, fn)
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding='utf-8') as fh:
                    w = (json.load(fh) or {}).get('widget')
                if isinstance(w, dict):
                    return w
            except (OSError, ValueError):
                pass
        return {}

    @classmethod
    def overview_widget(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """Overview-widget data hook (generic shape consumed by the core renderer):
        one ``entry`` per cluster check (name + status + stats + node rows) plus an
        ``aggregate``.  All domain strings come from this module's lang."""
        lbl = cls._widget_labels(lang)
        l_nodes = lbl.get('nodes', 'Nodes')
        l_quorum = lbl.get('quorum', 'Quorum')
        l_ceph = lbl.get('ceph', 'Ceph')
        l_clusters = lbl.get('clusters', 'Clusters')
        entries = []
        agg_nodes_total = agg_nodes_ok = 0
        agg_ok = True
        for uid, it in (items or {}).items():
            if not isinstance(it, dict):
                continue
            pref = f'{uid}/'
            own = {k: v for k, v in (status or {}).items()
                   if isinstance(v, dict) and k.startswith(pref)}
            cl = own.get(f'{uid}/cluster') or {}
            clod = cl.get('other_data') or {}
            ce = own.get(f'{uid}/ceph')
            rows, n_ok, n_total = [], 0, 0
            for nk in sorted(k for k in own if k.startswith(f'{uid}/node/')):
                nv = own[nk]
                nod = nv.get('other_data') or {}
                n_total += 1
                is_ok = nv.get('status') is True
                if is_ok:
                    n_ok += 1
                nm = nk.split('/node/', 1)[1]
                host = nod.get('host_name', '')
                rows.append({
                    'name':  f'{nm} ({host})' if host else nm,
                    'state': 'warn' if nod.get('maintenance') else ('ok' if is_ok else 'error'),
                    'detail': '',
                })
            err = any(v.get('status') is False for v in own.values())
            stats = [{
                'label': l_nodes, 'value': f'{n_ok}/{n_total}',
                'state': 'ok' if (n_total and n_ok == n_total) else ('error' if n_total else 'none'),
            }]
            if cl:
                q = clod.get('quorate')
                stats.append({'label': l_quorum,
                              'value': ('OK' if q else 'KO') if q is not None else '—',
                              'state': 'ok' if q else ('error' if q is not None else 'none')})
            if isinstance(ce, dict):
                health = (ce.get('other_data') or {}).get('health') or ''
                stats.append({'label': l_ceph,
                              'value': health or ('OK' if ce.get('status') else 'KO'),
                              'state': 'ok' if ce.get('status') else 'error'})
            entries.append({
                'id':    uid,
                'name':  str(it.get('label') or '').strip() or uid,
                'ok':    not err,
                'stats': stats,
                'rows':  rows,
            })
            agg_nodes_total += n_total
            agg_nodes_ok += n_ok
            if err:
                agg_ok = False
        return {
            'entries': entries,
            'aggregate': {
                'count_label': l_clusters,
                'count': len(entries),
                'ok': agg_ok,
                'stats': [{
                    'label': l_nodes, 'value': f'{agg_nodes_ok}/{agg_nodes_total}',
                    'state': 'ok' if (agg_nodes_total and agg_nodes_ok == agg_nodes_total) else 'error',
                }],
            },
        }

    @classmethod
    def _provision_ssh(cls, config: dict, cmd: str, *, timeout: int = 30) -> dict:
        """Run *cmd* on a Proxmox node over SSH (root/sudo), reusing the host's SSH
        profile/credential — the shared connection path behind ``provision_token``
        and ``fix_permissions``.

        Resolves the SSH target from the modal fields, falling back to the bound
        host's ``__host__`` SSH context; tries each candidate address in turn behind
        the SSRF guard.  Returns ``{'ok': True, 'out', 'err', 'code'}`` on a
        successful run, else ``{'ok': False, 'message': <reason>}``.
        """
        from lib.core.hosts import ssh_client  # noqa: PLC0415
        from lib.security.net_guard import validate_external_url  # noqa: PLC0415

        # When the check is bound to a host, the route injects the resolved host
        # context (__host__): address + the host's SSH profile (user/port/secret,
        # credential already applied) — the SAME SSH path the host-aware checks
        # use.  Reuse it so provisioning reaches the node on the host's real SSH
        # address/port, not a guessed default.  An explicit modal value still wins.
        host_ctx = config.get('__host__') if isinstance(config.get('__host__'), dict) else {}
        host_ssh = host_ctx.get('ssh') if isinstance(host_ctx.get('ssh'), dict) else {}

        def _conn(key, default=''):
            v = config.get(key)
            if v not in (None, '', 0):
                return v
            v = host_ssh.get(key)
            if v not in (None, '', 0):
                return v
            return default

        host = ((config.get('host') or '').strip()
                or str(host_ctx.get('address') or '').strip()
                or (config.get('_item_key') or '').strip())
        # The host field may list several addresses (comma/space separated) for
        # API failover — provisioning only needs one reachable node, so split and
        # try each in turn rather than handing the whole string to SSH.
        candidates = _split_hosts(host)
        if not candidates:
            return {'ok': False, 'message': 'Host requerido'}
        ssh_user = str(_conn('ssh_user', 'root') or 'root').strip() or 'root'
        ssh_port = int(_conn('ssh_port', 22) or 22)
        ssh_password = config.get('ssh_password') or host_ssh.get('ssh_password') or None
        ssh_key = (config.get('ssh_key') or host_ssh.get('ssh_key') or '').strip() or None  # key file path
        ssh_key_string = config.get('ssh_key_string') or host_ssh.get('ssh_key_string') or None  # inline key
        # Host-key policy: mirror the host-aware checks — default AutoAdd (accept
        # unknown keys on first contact), honouring the host's ssh_verify_host.
        ssh_verify = bool(host_ssh.get('ssh_verify_host', config.get('ssh_verify_host', False)))
        if not ssh_password and not ssh_key and not ssh_key_string:
            return {'ok': False,
                    'message': 'Indica una contraseña o clave SSH (o una credencial SSH) para el aprovisionamiento'}

        if not ssh_client.HAS_PARAMIKO:
            return {'ok': False, 'message': 'paramiko no está instalado (pip install paramiko)'}

        # Connect over SSH via the shared ssh_client (same path as the host-aware
        # checks): it accepts an inline key text directly and honours the host-key
        # policy.  Try each candidate node until one connects.
        out = err = ''
        code = None
        connected = False
        last_err = None
        for cand in candidates:
            reason = validate_external_url(f'https://{cand}:{ssh_port}')
            if reason:
                last_err = f'{cand}: bloqueado ({reason})'
                continue
            client = None
            try:
                client = ssh_client.connect(
                    address=cand, port=ssh_port, user=ssh_user,
                    password=ssh_password or '', key_path=ssh_key or '',
                    key_string=ssh_key_string or '', verify_host=ssh_verify, timeout=timeout)
                out, err, code = ssh_client.run_command(client, cmd, timeout=timeout)
                connected = True
                break
            except Exception as exc:  # pylint: disable=broad-except
                last_err = f'{cand}:{ssh_port} → {exc}'
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:  # pylint: disable=broad-except
                        pass
        if not connected:
            hint = ''
            if last_err and 'known_hosts' in last_err:
                hint = (' La clave del host no está en known_hosts y el perfil SSH del host '
                        'tiene la verificación activada: desactívala o añade la clave.')
            return {'ok': False,
                    'message': (f'SSH: {last_err or "ningún host alcanzable"}.{hint} '
                                f'La acción conecta por SSH (puerto {ssh_port}) '
                                f'al nodo Proxmox, no a la API (8006): revisa que el puerto SSH, '
                                f'la dirección de gestión y el firewall sean correctos.')}
        return {'ok': True, 'out': (out or '').strip(), 'err': (err or '').strip(), 'code': code}

    @classmethod
    def provision_token(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/proxmox/provision_token

        Connects to the Proxmox node over **SSH** (root or a sudo-capable user)
        and provisions an API token, then returns the generated token id + secret
        so the UI fills the form (result mode ``fields``).

        Two modes (``mode`` input):
          * ``create`` (default) — idempotently create a read-only monitoring user
            and grant the ``PVEAuditor`` role at ``/``, then (re)create the token.
          * ``renew`` — only rotate the token secret (remove + add); assumes the
            user and role already exist (lighter, for secret rotation).

        Returns {"ok": bool, "message": str, "fields": {auth_method, token_id,
        token_secret}}.
        """
        user = (config.get('prov_user') or 'servicesentry@pve').strip()
        token = (config.get('prov_token') or 'monitoring').strip()
        role = (config.get('prov_role') or 'ServiceSentryMonitor').strip()
        mode = (config.get('mode') or 'create').strip().lower()

        # Opt-in: the updates check needs Sys.Modify (Proxmox gates apt/update list
        # behind it). Off by default to keep the token least-privilege.
        allow_updates = str(config.get('allow_updates', '')).lower() in ('1', 'true', 'yes', 'on')
        privs = f'{_MONITOR_PRIVS}, {_UPDATES_PRIV}' if allow_updates else _MONITOR_PRIVS
        qu, qt, qr, qp = _shq(user), _shq(token), _shq(role), _shq(privs)
        token_cmd = (
            f"pveum user token remove {qu} {qt} 2>/dev/null; "
            f"pveum user token add {qu} {qt} --privsep 0 "
            f"--comment 'ServiceSentry' --output-format json"
        )
        if mode == 'renew':
            # Rotate the secret only: assumes the user + role already exist.
            cmd = token_cmd
        else:
            # Idempotent, least-privilege: create a custom role with exactly the
            # privileges the checks need (modify keeps it in sync if it existed),
            # create the user (ignore "already exists"), grant that role at / (it
            # propagates), then (re)create the token for a fresh secret.
            cmd = (
                f"pveum role add {qr} -privs {qp} 2>/dev/null; "
                f"pveum role modify {qr} -privs {qp}; "
                f"pveum user add {qu} --comment 'ServiceSentry monitoring (read-only)' 2>/dev/null; "
                f"pveum acl modify / --users {qu} --roles {qr} && "
                + token_cmd
            )

        res = cls._provision_ssh(config, cmd)
        if not res.get('ok'):
            return {'ok': False, 'message': res.get('message', 'SSH: error')}
        out, err, code = res.get('out', ''), res.get('err', ''), res.get('code')
        data = _extract_json(out)
        secret = (data or {}).get('value')
        full_id = (data or {}).get('full-tokenid') or f'{user}!{token}'
        if not secret:
            detail = (err or out or f'exit {code}')[:300]
            return {'ok': False, 'message': f'No se pudo crear el token: {detail}'}

        if mode == 'renew':
            message = (f'Secreto del token «{full_id}» renovado. '
                       f'Credenciales rellenadas — guarda el módulo.')
        else:
            message = (f'Usuario «{user}» y token «{full_id}» creados con el rol «{role}» '
                       f'(privilegios: {privs}). Credenciales rellenadas — guarda el módulo.')
        return {
            'ok': True,
            'message': message,
            'fields': {
                'auth_method': 'token',
                'token_id': full_id,
                'token_secret': secret,
            },
        }

    @classmethod
    def fix_permissions(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/proxmox/fix_permissions

        Grant the privileges the item's *enabled* checks need to the identity the
        configured credential already uses, over **SSH** (root/sudo) — the same path
        as ``provision_token`` but WITHOUT rotating the token, so an existing token
        keeps working with more privileges.

        Ensures a custom role (``prov_role``, default ``ServiceSentryMonitor``) holds
        exactly the required privileges (``Sys.Audit``; ``Datastore.Audit`` for the
        storage check; ``Sys.Modify`` for the updates check) and grants it at ``/``
        to the token's own user — and to the token itself, covering a
        privilege-separated token.  Then re-verifies over the API and returns the
        fresh per-privilege verdict (same shape as ``test_permissions``).

        Returns {"ok": bool, "all_ok": bool, "message": str, "variant": str,
                 "info": [[label, ✅/❌], …]}.
        """
        auth_method = str(config.get('auth_method') or 'token').strip().lower()
        role = (config.get('prov_role') or 'ServiceSentryMonitor').strip()
        # Exactly the privileges the enabled checks need (deduped, order preserved).
        privs = list(dict.fromkeys(p for p, _path, _f in cls._required_privs(config)))
        if not privs:
            return {'ok': False, 'message': 'No hay privilegios que conceder'}

        # Grant to the identity the credential uses: the token's own user (parsed
        # from token_id 'user@realm!tokenname'), else the password user.  A privsep
        # token has its own ACLs, so also grant on the token itself for token auth.
        token_id = str(config.get('token_id') or '').strip()
        token_grant = ''
        if auth_method == 'token':
            if not token_id:
                return {'ok': False, 'message': 'Falta token_id para conceder permisos'}
            user = token_id.split('!', 1)[0]
            token_grant = f"pveum acl modify / --tokens {_shq(token_id)} --roles {_shq(role)}; "
        else:
            user = str(config.get('username') or '').strip()
            if not user:
                return {'ok': False, 'message': 'Falta el usuario para conceder permisos'}

        qu, qr, qp = _shq(user), _shq(role), _shq(', '.join(privs))
        # Idempotent: create the role if absent, sync its privileges, grant it at /
        # (propagates) to the user and — for a privsep token — to the token too.
        cmd = (
            f"pveum role add {qr} -privs {qp} 2>/dev/null; "
            f"pveum role modify {qr} -privs {qp}; "
            f"pveum acl modify / --users {qu} --roles {qr}; "
            + token_grant
        ).rstrip('; ')

        res = cls._provision_ssh(config, cmd)
        if not res.get('ok'):
            return {'ok': False, 'message': res.get('message', 'SSH: error')}

        # Re-verify over the API so the result modal shows the updated verdict.
        note = f'Permisos concedidos a «{user}» (rol «{role}»: {", ".join(privs)}). '
        verify = cls.test_permissions(config)
        if isinstance(verify, dict) and verify.get('ok'):
            verify = dict(verify)
            verify['message'] = note + str(verify.get('message', ''))
            return verify
        return {'ok': True, 'all_ok': False, 'variant': 'warning',
                'message': note + 'No se pudo re-verificar por API: '
                                  + str((verify or {}).get('message', ''))}
