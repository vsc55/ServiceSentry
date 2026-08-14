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
            # The audit entry keeps BOTH lists, and the reason for each failure — the
            # only place either can be answered later, since re-running the import to
            # find out costs another few hundred requests against GitHub's 60/h
            # anonymous limit.
            _imported_names = [str(n) for n in (result.get('imported_names') or [])]
            _failed_detail  = [d for d in (result.get('failed_detail') or [])
                               if isinstance(d, dict)]
            if _imported_names:
                detail['imported_names'] = _imported_names
            if _failed_detail:
                detail['failed_detail'] = _failed_detail
            elif _names:
                detail['failed_names'] = _names
            _name = f'GitHub import: {_imp} ok, {_nfail} failed'
            if result.get('truncated'):
                _name += ' (truncated)'
            # The summary line stays a COUNT. It named the first ten failures for a
            # while, which reads well for three and turned into six lines of prose for
            # twelve behind a TLS timeout each — in a table cell, where the row is the
            # index and not the record. Which files, and why, are the structured fields
            # above; the entry opens onto them.
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

        # Ensure the raw MIB directory exists, then compile the few files that are
        # waiting — and ONLY while they are few.  A discovery used to compile whatever
        # had appeared since the last one, which is fine for a MIB dropped in by hand
        # and is an hour of parsing after a folder import: ~2.7 s per MIB, and a vendor
        # repository brings hundreds.  Past the limit they stay raw and the MIB manager
        # compiles them when asked, with a progress bar and a cancel button.
        if var_dir:
            raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')
            compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
            os.makedirs(raw_dir, exist_ok=True)
            _pending = _mib_resolver.pending_raw_mibs(raw_dir, compiled_dir)
            if _pending and len(_pending) <= _mib_resolver.AUTO_COMPILE_LIMIT:
                _mib_resolver.compile_raw_mibs(raw_dir, compiled_dir, mibs_filter=_pending)

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
                # The v3 identity travels with the request, exactly as it does for a check.
                # Discovery used to walk with the community string whatever the version, so a
                # v3 server answered nothing and the empty result read as "this device has no
                # OIDs" rather than "nobody asked it properly".
                oids = asyncio.run(cls._snmp_walk(
                    host, port, version, community, timeout, retries,
                    max_oids=per_server,
                    v3_username=str(srv.get('snmpv3_username', '') or ''),
                    v3_auth_key=str(srv.get('snmpv3_auth_key', '') or ''),
                    v3_priv_key=str(srv.get('snmpv3_priv_key', '') or ''),
                    v3_auth_proto=str(srv.get('snmpv3_auth_protocol',
                                              _SERVER_DEFAULTS['snmpv3_auth_protocol'])
                                      or _SERVER_DEFAULTS['snmpv3_auth_protocol']),
                    v3_priv_proto=str(srv.get('snmpv3_priv_protocol',
                                              _SERVER_DEFAULTS['snmpv3_priv_protocol'])
                                      or _SERVER_DEFAULTS['snmpv3_priv_protocol']),
                ))
            except Exception:  # pylint: disable=broad-except
                continue

            # Which server answered, but only when that is a question. The discovery hangs off
            # `checks`, INSIDE one server, so the modal asks one and the prefix repeated the
            # same name down every row while eating the 160 px the value has to live in — and
            # the value is the only thing that says whether an OID is worth adding.
            #
            # The server's NAME when it is shown, never its key: items are rekeyed by uid when
            # stored, so the key is a 36-character UUID and it filled that column on its own.
            srv_label = str(srv.get('label') or '').strip() or srv_key
            prefix = f'[{srv_label}] ' if len(servers) > 1 else ''
            for item in oids:
                mib_info = resolver.resolve(item['name'])
                results.append({
                    'name':         item['name'],
                    'display_name': f'{prefix}{item["display_name"]}',
                    'status':       item['status'],
                    'mib_category': item.get('mib_category', 'unknown'),
                    **mib_info,   # mib_module, mib_name, mib_type
                })

        return results
