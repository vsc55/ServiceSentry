#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: what the panel invokes.
#
"""Discovery, and the audit detail that describes every action's outcome.

``discover`` walks a server and reports the OIDs it found, so an admin picks from a list
instead of typing an OID from a vendor PDF. ``audit_detail`` is the other half of an action:
what the audit log should say once one has run.
"""

import asyncio
import os

from . import mib_resolver as _mib_resolver
from .client import _HAS_PYSNMP
from .defaults import _SERVER_DEFAULTS


class SnmpActions:
    """Operations the UI calls by name (see ``WATCHFUL_ACTIONS``)."""

    @classmethod
    def audit_detail(cls, action: str, result: dict) -> dict | None:
        """Return extra fields for the audit log entry, or None to suppress.

        Returning None skips the audit entry entirely (e.g. intermediate polls).
        The route handler merges the returned dict with {module, action}.
        """
        _done = result.get('done')  # None = regular action; bool = compile job

        # Suppress intermediate compile/import-status polls (job still running).
        if action in ('compile_mibs_status', 'import_mib_from_github_status') and _done is False:
            return None
        # Suppress the GitHub import kickoff — the meaningful audit (ok/failed
        # counts + which files failed) is recorded on the final status read.
        if action == 'import_mib_from_github_start':
            return None

        detail: dict = {'ok': result.get('ok', True)}

        if action == 'compile_mibs_start' and not _done:
            detail['name'] = f'compile started ({result.get("total", 0)} MIBs)'
        elif action == 'import_mib_from_github_status' and _done:
            _imp   = int(result.get('imported', 0) or 0)
            _nfail = int(result.get('failed', 0) or 0)
            _names = list(result.get('failed_names') or [])
            detail['imported'] = _imp
            detail['failed']   = _nfail
            if _names:
                detail['failed_names'] = _names
            _name = f'GitHub import: {_imp} ok, {_nfail} failed'
            if result.get('truncated'):
                _name += ' (truncated)'
            if _names:
                _shown = ', '.join(_names[:10])
                _more  = len(_names) - 10
                if _more > 0:
                    _shown += f', +{_more} more'
                _name += f' — failed: {_shown}'
            detail['name'] = _name
        elif _done:
            for _f in ('compiled', 'partial', 'failed', 'result_ok', 'message', 'total'):
                if _f in result:
                    detail[_f] = result[_f]
            _msg  = result.get('message', '')
            _ntot = result.get('total', 0)
            if _msg:
                detail['name'] = _msg
            elif result.get('compiled'):
                detail['name'] = f'{_ntot} MIBs compiled'
            else:
                detail['name'] = 'already up-to-date'
        else:
            detail['name'] = action
        return detail

    # ── Discovery ──────────────────────────────────────────────────────────────

    @classmethod
    def discover(cls, config: dict | None = None) -> list:
        """Walk all enabled servers and return discovered OIDs.

        ``config`` is the full module config dict (sent as POST body by the UI).
        Returns a list of ``{name, display_name, status}`` dicts where:
        - ``name``         — numeric OID string
        - ``display_name`` — current value (truncated, prefixed with server key)
        - ``status``       — SNMP type (e.g. OctetString, Integer32)
        """
        if not _HAS_PYSNMP:
            return []

        cfg     = config or {}
        servers = cfg.get('servers', {})
        if not isinstance(servers, dict):
            return []

        # Determine application data directory injected by the route handler.
        var_dir = str(cfg.get('__var_dir__') or '').strip()

        # Ensure raw MIB directory exists, then compile only when new raw files
        # have appeared since the last compilation.  Calling compile_raw_mibs()
        # unconditionally costs ~800 ms every discover (pysmi setup), so the
        # mtime check avoids that overhead when nothing has changed.
        if var_dir:
            raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')
            compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
            os.makedirs(raw_dir, exist_ok=True)
            if _mib_resolver.raw_dir_has_new_mibs(raw_dir, compiled_dir):
                _mib_resolver.compile_raw_mibs(raw_dir, compiled_dir)

        # Build/refresh OID index if missing or older than any compiled MIB.
        # Done once (~0.6 s); subsequent calls load from disk in ~30 ms.
        mib_dirs_raw    = str(cfg.get('mib_dirs') or '').strip()
        mib_dirs_custom = [d.strip() for d in mib_dirs_raw.split(',') if d.strip()]
        if var_dir and _mib_resolver.index_needs_rebuild(var_dir):
            _mib_resolver.build_oid_index(var_dir, mib_dirs_custom)

        # Build resolver: default compiled dir first, then user-specified dirs.
        default_dirs = _mib_resolver.get_default_dirs(var_dir)
        # dict.fromkeys preserves order and removes duplicates
        all_dirs = list(dict.fromkeys(default_dirs + mib_dirs_custom))
        resolver = _mib_resolver.get_resolver(all_dirs, var_dir=var_dir)

        results: list[dict] = []
        per_server = max(1, 300 // max(1, len(servers))) if servers else 300

        for srv_key, srv in servers.items():
            if not isinstance(srv, dict):
                continue
            if not srv.get('enabled', True):
                continue
            host      = str(srv.get('host', '') or '').strip()
            if not host:
                continue
            port      = int(srv.get('port',      _SERVER_DEFAULTS['port'])      or _SERVER_DEFAULTS['port'])
            version   = str(srv.get('version',   _SERVER_DEFAULTS['version'])   or _SERVER_DEFAULTS['version']).strip()
            community = str(srv.get('community', _SERVER_DEFAULTS['community']) or _SERVER_DEFAULTS['community']).strip()
            timeout   = max(1, int(srv.get('timeout',  _SERVER_DEFAULTS['timeout'])  or _SERVER_DEFAULTS['timeout']))
            retries   = max(0, int(srv.get('retries',  _SERVER_DEFAULTS['retries'])  or _SERVER_DEFAULTS['retries']))

            try:
                oids = asyncio.run(cls._snmp_walk(
                    host, port, version, community, timeout, retries,
                    max_oids=per_server,
                ))
            except Exception:  # pylint: disable=broad-except
                continue

            for item in oids:
                mib_info = resolver.resolve(item['name'])
                results.append({
                    'name':         item['name'],
                    'display_name': f'[{srv_key}] {item["display_name"]}',
                    'status':       item['status'],
                    'mib_category': item.get('mib_category', 'unknown'),
                    **mib_info,   # mib_module, mib_name, mib_type
                })

        return results
