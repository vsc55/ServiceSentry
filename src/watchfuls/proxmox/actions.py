#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSentry - Proxmox VE watchful: what the panel invokes.
#
"""Test a connection, test the privileges, list the nodes.

All three answer the same underlying question from a different angle - can we reach this
cluster and are we allowed to read what we need - which is why they live together and not
with the checks: none of them emits a result or notifies anyone.
"""

from .client import _split_hosts


class ProxmoxActions:
    """Operations the UI calls by name (see ``WATCHFUL_ACTIONS``)."""

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
