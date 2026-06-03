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

import asyncio
import concurrent.futures
import json
import os
import re
import threading
import uuid

from lib.debug import DebugLevel
from lib.modules import ModuleBase
from . import mib_resolver as _mib_resolver

# ── Optional dependency: pysmi (compile-time MIB support) ────────────────────
import importlib.util as _importlib_util
_HAS_PYSMI = _importlib_util.find_spec('pysmi') is not None

# ── Optional dependency: pysnmp ───────────────────────────────────────────────
# pysnmp 6+/7+ (lextudio fork) moved everything to pysnmp.hlapi.v3arch.asyncio.
_HAS_PYSNMP = False
try:
    from pysnmp.hlapi.v3arch.asyncio import (   # type: ignore[import]
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        UsmUserData,
        bulk_walk_cmd,
        get_cmd,
        walk_cmd,
        usmAesCfb128Protocol,
        usmAesCfb192Protocol,
        usmAesCfb256Protocol,
        usmDESPrivProtocol,
        usmHMACMD5AuthProtocol,
        usmHMACSHAAuthProtocol,
        usmNoAuthProtocol,
        usmNoPrivProtocol,
        usmHMAC128SHA224AuthProtocol,
        usmHMAC192SHA256AuthProtocol,
        usmHMAC256SHA384AuthProtocol,
        usmHMAC384SHA512AuthProtocol,
        usm3DESEDEPrivProtocol,
    )
    _HAS_PYSNMP = True
except ImportError:
    pass

# ── Filename / path-confinement helpers ──────────────────────────────────────
# Allowlist for MIB filenames: alphanumerics, underscore, hyphen, dot only.
# No spaces, no shell-special chars, no NTFS alternate-stream colons.
_SAFE_FILENAME_RE = re.compile(r'^[A-Za-z0-9_.-]+$')
_RAW_EXTENSIONS   = frozenset(('.mib', '.txt', '.my', ''))
_COMPILED_EXTENSION = '.py'


def _safe_mib_filename(name: str, kind: str = 'raw') -> str | None:
    """Return *name* if it is safe to use as a MIB filename, else ``None``.

    Validates:
    - Non-empty, no path separators, doesn't start with '.'
    - Only safe characters (allowlist — prevents NTFS streams, shell metacharacters)
    - Correct extension for *kind* ('raw' or 'compiled')
    """
    if not name or '/' in name or os.sep in name or name.startswith('.'):
        return None
    if not _SAFE_FILENAME_RE.match(name):
        return None
    ext = os.path.splitext(name)[1].lower()
    if kind == 'compiled' and ext != _COMPILED_EXTENSION:
        return None
    return name


def _confined_path(base_dir: str, *parts: str) -> str | None:
    """Return the resolved path of ``os.path.join(base_dir, *parts)`` only if
    the result is strictly inside *base_dir*; otherwise return ``None``.

    Belt-and-suspenders guard against any edge-case that slips past the name
    check (e.g. symlinks pointing outside the directory).
    """
    import pathlib
    base    = pathlib.Path(base_dir).resolve()
    target  = pathlib.Path(os.path.join(base_dir, *parts)).resolve()
    if not str(target).startswith(str(base) + os.sep) and target != base:
        return None
    return str(target)


# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA: dict = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)

# ── Protocol lookup tables (populated only when pysnmp is available) ──────────
if _HAS_PYSNMP:
    _AUTH_PROTOCOLS: dict = {
        'MD5':     usmHMACMD5AuthProtocol,
        'SHA':     usmHMACSHAAuthProtocol,
        'SHA-224': usmHMAC128SHA224AuthProtocol,
        'SHA-256': usmHMAC192SHA256AuthProtocol,
        'SHA-384': usmHMAC256SHA384AuthProtocol,
        'SHA-512': usmHMAC384SHA512AuthProtocol,
        'none':    usmNoAuthProtocol,
    }
    _PRIV_PROTOCOLS: dict = {
        'DES':     usmDESPrivProtocol,
        '3DES':    usm3DESEDEPrivProtocol,
        'AES-128': usmAesCfb128Protocol,
        'AES-192': usmAesCfb192Protocol,
        'AES-256': usmAesCfb256Protocol,
        'none':    usmNoPrivProtocol,
    }
else:
    _AUTH_PROTOCOLS = {}
    _PRIV_PROTOCOLS = {}

# Default values per schema section
_SERVER_DEFAULTS: dict = {k: v['default'] for k, v in _SCHEMA['servers'].items()
                          if isinstance(v, dict) and 'default' in v}
# checks schema is nested inside servers as a sub_collection
_CHECK_DEFAULTS: dict  = {k: v['default'] for k, v in _SCHEMA['servers']['checks'].items()
                          if isinstance(v, dict) and 'default' in v}


# ── Background MIB compilation job state ─────────────────────────────────────
# Maps job_id → progress/result dict.  Written by background threads, read by
# compile_mibs_status.  CPython dict updates are GIL-safe for simple values.
_compile_jobs: dict = {}

# ── Watchful class ────────────────────────────────────────────────────────────

class Watchful(ModuleBase):
    """Multi-server SNMP OID monitoring."""

    ITEM_SCHEMA = _SCHEMA

    MISSING_DEPS: list[str]  = [] if _HAS_PYSNMP else ['pysnmp']
    PARTIAL_DEPS: list[str]  = [] if _HAS_PYSMI  else ['pysmi']

    WATCHFUL_ACTIONS: frozenset[str] = frozenset({
        'discover',
        'list_mibs',
        'compile_mibs',
        'compile_mibs_start',
        'compile_mibs_status',
        'delete_mib',
        'upload_mib',
        'import_mib_from_url',
        'get_mib_details',
        'get_raw_mib_details',
        'get_all_symbols',
        'build_oid_index',
    })

    # Actions that produce no side effects — audit logging is suppressed for them.
    READ_ONLY_ACTIONS: frozenset[str] = frozenset({
        'discover',
        'list_mibs',
        'get_mib_details',
        'get_raw_mib_details',
        'get_all_symbols',
    })

    @classmethod
    def audit_detail(cls, action: str, result: dict) -> dict | None:
        """Return extra fields for the audit log entry, or None to suppress.

        Returning None skips the audit entry entirely (e.g. intermediate polls).
        The route handler merges the returned dict with {module, action}.
        """
        _done = result.get('done')  # None = regular action; bool = compile job

        # Suppress intermediate compile-status polls (job still running).
        if action == 'compile_mibs_status' and _done is False:
            return None

        detail: dict = {'ok': result.get('ok', True)}

        if action == 'compile_mibs_start' and not _done:
            detail['name'] = f'compile started ({result.get("total", 0)} MIBs)'
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

    # Toolbar buttons injected into the module card body by the dashboard.
    # Each entry is rendered as a generic button — no module-specific code in web_admin.
    WATCHFUL_TOOLBAR: tuple[dict, ...] = (
        {'icon': 'bi-database-gear', 'label_key': 'file_manager',
         'onclick': 'openFileManagerModal'},
        {'icon': 'bi-diagram-3',     'label_key': 'mib_browser',
         'onclick': 'openMibBrowserModal'},
    )

    # Legacy compat alias so ModuleBase helpers that expect _DEFAULTS still work
    _DEFAULTS        = _CHECK_DEFAULTS
    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)
        self._fail_count: dict[str, int] = {}
        self._startup_compile_mibs()

    # ── Startup MIB compilation ────────────────────────────────────────────────

    def _startup_compile_mibs(self) -> None:
        """Compile raw ASN.1 MIBs at module startup.

        Reads ``var_dir`` from the monitor, ensures the ``snmp_mibs/raw/``
        directory exists (so users know where to drop ``.mib`` files) and
        tries to compile any new or updated files into ``snmp_mibs/compiled/``
        using pysmi (if installed).  All outcomes are logged for auditability.
        """
        var_dir = str(getattr(self._monitor, 'dir_var', '') or '').strip()
        if not var_dir:
            return

        raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')
        compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
        os.makedirs(raw_dir, exist_ok=True)

        # Count raw MIB files so we can warn if pysmi is missing
        try:
            raw_files = [
                f for f in os.listdir(raw_dir)
                if not f.startswith('.') and os.path.isfile(os.path.join(raw_dir, f))
            ]
        except OSError:
            raw_files = []

        # Only invoke pysmi when new/updated raw MIBs exist.  compile_raw_mibs()
        # initialises an HttpReader (→ DNS lookup for mibs.pysnmp.com) even for
        # already-compiled MIBs, which can block for 45+ seconds on slow networks.
        if not _mib_resolver.raw_dir_has_new_mibs(raw_dir, compiled_dir):
            compile_result = {'ok': True, 'compiled': False}
        else:
            compile_result = _mib_resolver.compile_raw_mibs(raw_dir, compiled_dir)

        if not compile_result.get('ok'):
            self._debug(
                f'SNMP: MIB compilation error — {compile_result.get("message", "unknown error")}',
                DebugLevel.warning,
            )
        elif compile_result.get('compiled'):
            self._debug(
                f'SNMP: MIB compilation complete — '
                f'raw={raw_dir}  compiled={compiled_dir}',
                DebugLevel.info,
            )
        elif raw_files:
            # Files present but nothing compiled: either up-to-date or pysmi missing
            if _HAS_PYSMI:
                self._debug(
                    f'SNMP: MIB files already up-to-date in {compiled_dir}',
                    DebugLevel.debug,
                )
            else:
                self._debug(
                    f'SNMP: {len(raw_files)} raw MIB file(s) found in {raw_dir} '
                    f'but pysmi is not installed — install it to enable auto-compilation '
                    f'(pip install pysmi)',
                    DebugLevel.warning,
                )
        else:
            self._debug(
                f'SNMP: MIB directory ready — drop .mib files in {raw_dir} '
                f'to add custom MIBs',
                DebugLevel.debug,
            )

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

    # ── MIB manager ────────────────────────────────────────────────────────────

    @classmethod
    def list_mibs(cls, config: dict | None = None) -> dict:
        """Return lists of raw and compiled MIB files together with pysmi status."""
        cfg = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')      if var_dir else ''
        compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled') if var_dir else ''

        def _listdir(path):
            if not path or not os.path.isdir(path):
                return []
            items = []
            for f in sorted(os.listdir(path)):
                if f.startswith('.') or f.startswith('__'):
                    continue
                fp = os.path.join(path, f)
                if os.path.isfile(fp):
                    st = os.stat(fp)
                    items.append({'name': f, 'size': st.st_size, 'mtime': int(st.st_mtime)})
            return items

        return {
            'ok':              True,
            'raw':             _listdir(raw_dir),
            'compiled':        _listdir(compiled_dir),
            'pysmi_available': _HAS_PYSMI,
            'raw_dir':         raw_dir,
            'compiled_dir':    compiled_dir,
        }

    @classmethod
    def compile_mibs(cls, config: dict | None = None) -> dict:
        """Force compilation of raw ASN.1 MIBs and invalidate the resolver cache."""
        cfg = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        if not var_dir:
            return {'ok': False, 'message': 'var_dir not available'}
        raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')
        compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
        os.makedirs(raw_dir, exist_ok=True)
        # Invalidate cache so any newly compiled MIBs are picked up immediately
        _mib_resolver.invalidate_cache()
        return _mib_resolver.compile_raw_mibs(raw_dir, compiled_dir)

    @classmethod
    def compile_mibs_start(cls, config: dict | None = None) -> dict:
        """Start an async MIB compilation job and return a job_id for polling."""
        cfg      = config or {}
        var_dir  = str(cfg.get('__var_dir__') or '').strip()
        if not var_dir:
            return {'ok': False, 'message': 'var_dir not available'}

        raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')
        compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
        os.makedirs(raw_dir, exist_ok=True)

        try:
            raw_mibs = sorted(
                os.path.splitext(f)[0]
                for f in os.listdir(raw_dir)
                if not f.startswith('.') and os.path.isfile(os.path.join(raw_dir, f))
            )
        except OSError:
            raw_mibs = []

        # Optional filter: compile only the requested MIB names (strip extensions).
        mibs_req = cfg.get('mibs', None)
        mibs_filter: list | None = None
        if isinstance(mibs_req, list) and mibs_req:
            mibs_filter = [os.path.splitext(str(m))[0] for m in mibs_req if m]
            _keep = set(mibs_filter)
            raw_mibs = [m for m in raw_mibs if m in _keep]

        if not raw_mibs:
            return {'ok': True, 'done': True, 'compiled': False, 'partial': False,
                    'results': {}, 'failed': [], 'total': 0, 'completed': 0}

        job_id = uuid.uuid4().hex[:12]
        _compile_jobs[job_id] = {
            'done': False, 'total': len(raw_mibs), 'completed': 0,
            'current': None, 'result_ok': None, 'compiled': False,
            'partial': False, 'failed': [], 'message': '',
        }

        def _progress_cb(current, completed, _total):
            _compile_jobs[job_id]['current']   = current
            _compile_jobs[job_id]['completed'] = completed

        def _run():
            _mib_resolver.invalidate_cache()
            result = _mib_resolver.compile_raw_mibs_progressive(
                raw_dir, compiled_dir, _progress_cb, mibs_filter=mibs_filter,
            )
            _compile_jobs[job_id].update({
                'done':      True,
                'result_ok': result.get('ok', False),
                'compiled':  result.get('compiled', False),
                'partial':   result.get('partial', False),
                'failed':    result.get('failed', []),
                'message':   result.get('message', ''),
                'current':   None,
                'completed': len(raw_mibs),
            })

        threading.Thread(target=_run, daemon=True).start()
        return {'ok': True, 'job_id': job_id, 'total': len(raw_mibs), 'done': False}

    @classmethod
    def compile_mibs_status(cls, config: dict | None = None) -> dict:
        """Poll the status of an async compilation job started by compile_mibs_start."""
        cfg    = config or {}
        job_id = str(cfg.get('job_id') or '').strip()
        if job_id not in _compile_jobs:
            return {'ok': False, 'message': 'Job not found or already collected'}
        job = dict(_compile_jobs[job_id])   # snapshot
        if job.get('done'):
            del _compile_jobs[job_id]       # cleanup on first done-read
        else:
            job.pop('result_ok', None)      # don't send None result while running
        return {'ok': True, **job}

    @classmethod
    def delete_mib(cls, config: dict | None = None) -> dict:
        """Delete a single raw or compiled MIB file."""
        cfg     = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        name    = str(cfg.get('name')  or '').strip()
        kind    = str(cfg.get('kind')  or '').strip()   # 'raw' or 'compiled'
        if not var_dir or not name or kind not in ('raw', 'compiled'):
            return {'ok': False, 'message': 'Invalid parameters'}
        if not _safe_mib_filename(name, kind):
            return {'ok': False, 'message': 'Invalid file name'}
        base = os.path.join(var_dir, 'snmp_mibs', kind)
        path = _confined_path(base, name)
        if not path or not os.path.isfile(path):
            return {'ok': False, 'message': 'File not found'}
        os.remove(path)
        _mib_resolver.invalidate_cache()
        return {'ok': True}

    @classmethod
    def get_mib_details(cls, config: dict | None = None) -> dict:
        """Return symbol list and source code for a compiled MIB .py file."""
        cfg     = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        name    = str(cfg.get('name') or '').strip()
        if not var_dir or not name:
            return {'ok': False, 'message': 'Invalid parameters'}
        if not _safe_mib_filename(name, 'compiled'):
            return {'ok': False, 'message': 'Invalid file name'}
        mib_stem     = os.path.splitext(name)[0]
        compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
        file_path    = _confined_path(compiled_dir, mib_stem + '.py')
        if not file_path or not os.path.isfile(file_path):
            return {'ok': False, 'message': 'File not found'}

        try:
            with open(file_path, encoding='utf-8') as fh:
                source = fh.read()
        except OSError as exc:
            return {'ok': False, 'message': str(exc)}

        symbols: list[dict] = []
        if _HAS_PYSNMP:
            try:
                from pysnmp.smi import builder  # type: ignore[import]
                mb = builder.MibBuilder()
                mb.loadTexts = True   # load DESCRIPTION / STATUS / MAX-ACCESS
                mib_dirs_raw    = str(cfg.get('mib_dirs') or '').strip()
                mib_dirs_custom = [d.strip() for d in mib_dirs_raw.split(',') if d.strip()]
                default_dirs    = _mib_resolver.get_default_dirs(var_dir)
                for d in list(dict.fromkeys(default_dirs + mib_dirs_custom)):
                    if os.path.isdir(d):
                        mb.addMibSources(builder.DirMibSource(d))
                mb.loadModules(mib_stem)
                raw_syms = getattr(mb, 'mibSymbols', {})
                mib_syms = raw_syms.get(mib_stem, {}) if hasattr(raw_syms, 'get') else {}
                for sym_name, sym_obj in sorted(mib_syms.items()):
                    try:
                        oid_tuple = sym_obj.getName()
                        oid_str   = '.'.join(str(x) for x in oid_tuple) if oid_tuple else ''

                        def _str_attr(obj, *attrs):
                            for a in attrs:
                                v = getattr(obj, a, None)
                                if v is not None:
                                    s = str(v).strip()
                                    if s and s not in ('None', ''):
                                        return s
                            return ''

                        symbols.append({
                            'name':   sym_name,
                            'oid':    oid_str,
                            'type':   type(sym_obj).__name__,
                            'status': _str_attr(sym_obj, 'status', '_status'),
                            'access': _str_attr(sym_obj, 'maxAccess', '_maxAccess'),
                            'units':  _str_attr(sym_obj, 'units', '_units'),
                            'desc':   _str_attr(sym_obj, 'description', '_description'),
                        })
                    except Exception:  # pylint: disable=broad-except
                        pass
            except Exception:  # pylint: disable=broad-except
                pass

        return {'ok': True, 'module': mib_stem, 'symbols': symbols, 'source': source}

    @classmethod
    def build_oid_index(cls, config: dict | None = None) -> dict:
        """Build and save the OID resolution index for fast discover().

        Loads all compiled and built-in MIBs once, saves the resulting
        {oid → mib_module/mib_name/mib_type} index to disk so that
        subsequent discover() calls skip the slow per-OID MIB lookup.
        """
        cfg      = config or {}
        var_dir  = str(cfg.get('__var_dir__') or '').strip()
        extra    = [d.strip() for d in cfg.get('mib_dirs', '').split(',') if d.strip()]
        count    = _mib_resolver.build_oid_index(var_dir, extra)
        return {'ok': True, 'count': count}

    @classmethod
    def get_all_symbols(cls, config: dict | None = None) -> dict:
        """Load every compiled MIB and return a flat list of all OID symbols."""
        cfg = config or {}
        if not _HAS_PYSNMP:
            return {'ok': False, 'message': 'pysnmp not available'}

        var_dir      = cfg.get('__var_dir__', '')
        compiled_dir = (
            os.path.join(var_dir, 'snmp_mibs', 'compiled') if var_dir else ''
        )
        extra_dirs = [
            d.strip() for d in cfg.get('mib_dirs', '').split(',') if d.strip()
        ]

        stems: list[str] = []
        if compiled_dir and os.path.isdir(compiled_dir):
            stems = [
                fn[:-3] for fn in os.listdir(compiled_dir)
                if fn.endswith('.py') and not fn.startswith('__')
            ]
        if not stems:
            return {'ok': True, 'symbols': []}

        from pysnmp.smi import builder  # pylint: disable=import-outside-toplevel
        mb = builder.MibBuilder()
        mb.loadTexts = True
        if compiled_dir and os.path.isdir(compiled_dir):
            mb.addMibSources(builder.DirMibSource(compiled_dir))
        for _d in extra_dirs:
            if os.path.isdir(_d):
                mb.addMibSources(builder.DirMibSource(_d))

        for stem in stems:
            try:
                mb.loadModules(stem)
            except Exception:  # pylint: disable=broad-except
                pass

        def _sa(obj, *attrs):
            for a in attrs:
                v = getattr(obj, a, None)
                if v is None:
                    continue
                s = str(v).strip()
                if s and s not in ('None', '""', "''"):
                    return s
            return ''

        def _sym_type_info(sym_obj):
            """Extract enum values, integer range, and base category from a pysnmp object."""
            # Named values (enums / booleans)
            _nv = (getattr(sym_obj, 'namedValues', None) or
                   getattr(type(sym_obj), 'namedValues', None))
            enum_vals: list[dict] = []
            if _nv and hasattr(_nv, 'items'):
                try:
                    enum_vals = sorted(
                        [{'name': str(n), 'value': int(v)} for n, v in _nv.items()],
                        key=lambda x: x['value'],
                    )
                except Exception:  # pylint: disable=broad-except
                    pass

            # Integer range (ValueRangeConstraint in subtypeSpec)
            rmin = rmax = None
            try:
                _spec = (getattr(sym_obj, 'subtypeSpec', None) or
                         getattr(type(sym_obj), 'subtypeSpec', None))
                if _spec:
                    _stack = [_spec]
                    while _stack:
                        _c = _stack.pop()
                        if hasattr(_c, 'components'):
                            _stack.extend(list(_c.components))
                        elif hasattr(_c, 'start') and hasattr(_c, 'stop'):
                            rmin, rmax = int(_c.start), int(_c.stop)
                            break
            except Exception:  # pylint: disable=broad-except
                pass

            # Base category
            _tn = type(sym_obj).__name__
            _is_bool = (
                len(enum_vals) == 2 and {ev['value'] for ev in enum_vals} == {1, 2}
                and any(
                    ev['name'].lower() in ('true', 'enabled', 'yes', 'up')
                    for ev in enum_vals
                )
            ) if enum_vals else False
            if _is_bool:
                cat = 'boolean'
            elif enum_vals:
                cat = 'enum'
            elif _tn == 'IpAddress':
                cat = 'ip'
            elif _tn == 'ObjectIdentifier':
                cat = 'oid'
            elif any(x in _tn for x in ('String', 'Display', 'Text', 'Octet')):
                cat = 'string'
            elif any(x in _tn for x in ('Counter', 'Gauge', 'Ticks', 'Unsigned')):
                cat = 'unsigned'
            elif 'Integer' in _tn:
                cat = 'integer'
            else:
                cat = 'other'

            return enum_vals, rmin, rmax, cat

        symbols: list[dict] = []
        raw_syms = getattr(mb, 'mibSymbols', {})
        for mod_name, mod_syms in (
            raw_syms.items() if hasattr(raw_syms, 'items') else []
        ):
            if not isinstance(mod_syms, dict):
                continue
            for sym_name, sym_obj in mod_syms.items():
                try:
                    oid_obj = getattr(sym_obj, 'name', None)
                    if oid_obj is None:
                        continue
                    oid_str = (
                        '.'.join(str(x) for x in oid_obj)
                        if hasattr(oid_obj, '__iter__') else str(oid_obj)
                    )
                    if not oid_str or not re.match(r'^\d[\d.]*\d$', oid_str):
                        continue
                    _enum, _rmin, _rmax, _cat = _sym_type_info(sym_obj)
                    symbols.append({
                        'name':          sym_name,
                        'oid':           oid_str,
                        'module':        mod_name,
                        'type':          type(sym_obj).__name__,
                        'base_category': _cat,
                        'enum_values':   _enum,
                        'range_min':     _rmin,
                        'range_max':     _rmax,
                        'status': _sa(sym_obj, 'status',      '_status'),
                        'access': _sa(sym_obj, 'maxAccess',   '_maxAccess'),
                        'units':  _sa(sym_obj, 'units',       '_units'),
                        'desc':   _sa(sym_obj, 'description', '_description'),
                    })
                except Exception:  # pylint: disable=broad-except
                    continue

        return {'ok': True, 'symbols': symbols}

    @classmethod
    def get_raw_mib_details(cls, config: dict | None = None) -> dict:
        """Read a raw ASN.1 MIB file and extract structured definition info."""
        cfg     = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        name    = str(cfg.get('name') or '').strip()
        if not var_dir or not name:
            return {'ok': False, 'message': 'Invalid parameters'}
        if not _safe_mib_filename(name, 'raw'):
            return {'ok': False, 'message': 'Invalid file name'}
        raw_dir   = os.path.join(var_dir, 'snmp_mibs', 'raw')
        file_path = _confined_path(raw_dir, name)
        if not file_path or not os.path.isfile(file_path):
            return {'ok': False, 'message': 'File not found'}

        try:
            with open(file_path, encoding='utf-8', errors='replace') as fh:
                source = fh.read()
        except OSError as exc:
            return {'ok': False, 'message': str(exc)}

        # ── Helpers ───────────────────────────────────────────────────────────

        def _q(text, keyword):
            """Extract a single-word value after a keyword."""
            m = re.search(rf'\b{re.escape(keyword)}\s+(\S+)', text)
            return m.group(1).rstrip(',').strip() if m else ''

        def _syntax(text):
            """Extract SYNTAX value (may span multiple lines)."""
            m = re.search(
                r'\bSYNTAX\s+(.*?)(?=\n[ \t]*(?:UNITS|ACCESS|MAX-ACCESS|STATUS|'
                r'DESCRIPTION|REFERENCE|INDEX|AUGMENTS|DEFVAL|OBJECTS|NOTIFICATIONS|'
                r'::=)|\Z)',
                text, re.DOTALL,
            )
            if not m:
                return ''
            return re.sub(r'\s+', ' ', m.group(1)).strip().rstrip(',')

        def _desc(text):
            """Extract DESCRIPTION quoted string (handles multi-line and escaped quotes)."""
            m = re.search(r'\bDESCRIPTION\s+"((?:[^"]|"")*)"', text, re.DOTALL)
            if not m:
                return ''
            raw = m.group(1).replace('""', '"')
            # Collapse internal whitespace to single spaces, preserve paragraphs
            paragraphs = re.split(r'\n\s*\n', raw)
            cleaned = '\n\n'.join(
                re.sub(r'[ \t]*\n[ \t]*', ' ', p).strip()
                for p in paragraphs
            )
            return cleaned.strip()

        # ── Module name ───────────────────────────────────────────────────────
        m = re.search(
            r'^([A-Za-z][A-Za-z0-9_-]*)\s+DEFINITIONS\s*(?:IMPLICIT\s+TAGS\s*)?::=\s*BEGIN',
            source, re.MULTILINE,
        )
        module_name = m.group(1) if m else ''

        # ── Imports ───────────────────────────────────────────────────────────
        imports: list[dict] = []
        imp_m = re.search(r'\bIMPORTS\b(.*?);', source, re.DOTALL | re.IGNORECASE)
        if imp_m:
            for syms_raw, mod in re.findall(
                r'([\w\s,\n-]+?)\s+FROM\s+([A-Za-z][A-Za-z0-9_-]*)',
                imp_m.group(1),
            ):
                syms = [s.strip() for s in re.split(r'[\s,]+', syms_raw.strip()) if s.strip()]
                if mod and syms:
                    imports.append({'module': mod, 'symbols': syms})

        # ── Object definitions ────────────────────────────────────────────────
        # Locate every top-level definition (macro keyword at start of body)
        _MACROS = (
            'OBJECT-TYPE', 'MODULE-IDENTITY', 'NOTIFICATION-TYPE', 'OBJECT-GROUP',
            'NOTIFICATION-GROUP', 'MODULE-COMPLIANCE', 'TRAP-TYPE',
            'TEXTUAL-CONVENTION', 'AGENT-CAPABILITIES',
        )
        _DEF_RE = re.compile(
            r'^([A-Za-z][A-Za-z0-9_-]*)\s+(' + '|'.join(_MACROS) + r')\b',
            re.MULTILINE,
        )
        # Also capture plain OID assignments
        _OID_RE = re.compile(
            r'^([A-Za-z][A-Za-z0-9_-]*)\s+OBJECT\s+IDENTIFIER\s*::=',
            re.MULTILINE,
        )

        all_starts = sorted(
            [(m.start(), m.group(1), m.group(2)) for m in _DEF_RE.finditer(source)]
            + [(m.start(), m.group(1), 'OBJECT IDENTIFIER') for m in _OID_RE.finditer(source)],
            key=lambda t: t[0],
        )

        objects_detail: list[dict] = []
        seen: set[str] = {module_name} if module_name else set()
        for idx, (start, obj_name, obj_kind) in enumerate(all_starts):
            if obj_name in seen:
                continue
            seen.add(obj_name)
            end = all_starts[idx + 1][0] if idx + 1 < len(all_starts) else len(source)
            block = source[start:end]

            entry: dict = {'name': obj_name, 'kind': obj_kind, 'desc': _desc(block)}
            if obj_kind == 'OBJECT-TYPE':
                entry['syntax'] = _syntax(block)
                entry['units']  = _q(block, 'UNITS').strip('"')
                entry['access'] = _q(block, 'MAX-ACCESS') or _q(block, 'ACCESS')
                entry['status'] = _q(block, 'STATUS')
            elif obj_kind in ('NOTIFICATION-TYPE', 'OBJECT-GROUP',
                              'NOTIFICATION-GROUP', 'MODULE-COMPLIANCE'):
                entry['status'] = _q(block, 'STATUS')
            objects_detail.append(entry)

        return {
            'ok':             True,
            'module':         module_name,
            'imports':        imports,
            'objects':        [o['name'] for o in objects_detail],
            'objects_detail': objects_detail,
            'source':         source,
        }

    @classmethod
    def upload_mib(cls, config: dict | None = None) -> dict:
        """Save a raw ASN.1 MIB file to the ``snmp_mibs/raw/`` directory.

        Receives the file as plain text in ``config['content']`` (MIB files are
        always ASCII/UTF-8) together with ``config['filename']``.  Path traversal
        and unsupported extensions are rejected.
        """
        cfg      = config or {}
        var_dir  = str(cfg.get('__var_dir__') or '').strip()
        filename = os.path.basename(str(cfg.get('filename') or '').strip())
        content  = cfg.get('content', '')

        if not var_dir:
            return {'ok': False, 'message': 'var_dir not available'}
        if not _safe_mib_filename(filename, 'raw'):
            return {'ok': False, 'message': 'Invalid filename'}
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _RAW_EXTENSIONS:
            return {'ok': False, 'message': f'File type not allowed: {ext}'}

        raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        dest = _confined_path(raw_dir, filename)
        if not dest:
            return {'ok': False, 'message': 'Invalid filename'}
        with open(dest, 'w', encoding='utf-8') as fh:
            fh.write(content if isinstance(content, str) else '')
        return {'ok': True, 'filename': filename}

    @classmethod
    def import_mib_from_url(cls, config: dict | None = None) -> dict:
        """Fetch a raw ASN.1 MIB file from a URL and save it to ``snmp_mibs/raw/``.

        Accepts any direct URL that returns MIB text, and also converts GitHub
        ``/blob/`` viewer URLs to their raw equivalent automatically:
        ``https://github.com/user/repo/blob/branch/path/file.mib``
        → ``https://raw.githubusercontent.com/user/repo/branch/path/file.mib``
        """
        import re
        import requests as _requests

        cfg     = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        url     = str(cfg.get('url') or '').strip()

        if not var_dir:
            return {'ok': False, 'message': 'var_dir not available'}
        if not url:
            return {'ok': False, 'message': 'url is required'}

        # Convert GitHub blob URL to raw URL
        url = re.sub(
            r'^https?://github\.com/([^/]+)/([^/]+)/blob/(.+)$',
            r'https://raw.githubusercontent.com/\1/\2/\3',
            url,
        )

        # Derive filename from the final path segment (strip query/fragment)
        filename = os.path.basename(url.split('?')[0].split('#')[0])
        if not filename:
            return {'ok': False, 'message': 'Could not determine filename from URL'}
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _RAW_EXTENSIONS:
            return {'ok': False, 'message': f'File type not allowed: {ext}'}
        if not ext:
            filename += '.mib'
        if not _safe_mib_filename(filename, 'raw'):
            return {'ok': False, 'message': 'Invalid filename derived from URL'}

        try:
            resp = _requests.get(url, timeout=15)
            resp.raise_for_status()
            content = resp.text
        except Exception as exc:  # noqa: BLE001
            return {'ok': False, 'message': f'Download failed: {exc}'}

        raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        dest = _confined_path(raw_dir, filename)
        if not dest:
            return {'ok': False, 'message': 'Invalid filename'}
        try:
            with open(dest, 'w', encoding='utf-8') as fh:
                fh.write(content)
        except OSError as exc:
            return {'ok': False, 'message': f'Save failed: {exc}'}

        return {'ok': True, 'filename': filename}

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

        # Iterate servers; each server carries its own 'checks' sub-collection.
        items: list[tuple[str, dict, dict]] = []
        for srv_key, srv in self.get_conf('servers', {}).items():
            if not isinstance(srv, dict):
                continue
            if not srv.get('enabled', _SERVER_DEFAULTS['enabled']):
                continue
            for chk_key, chk_cfg in (srv.get('checks') or {}).items():
                if not isinstance(chk_cfg, dict):
                    continue
                if chk_cfg.get('enabled', _CHECK_DEFAULTS['enabled']):
                    items.append((f'{srv_key}.{chk_key}', chk_cfg, srv))

        max_workers = self.get_conf('threads', self._DEFAULT_THREADS)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._check_item, key, cfg, srv): key
                for key, cfg, srv in items
            }
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f'SNMP: {key} — unhandled exception: {exc}', DebugLevel.error)
                    self.dict_return.set(key, False, f'SNMP: {key} 💥 {exc}')

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
            self._debug(f'SNMP: {key} — no server host configured, skipping.', DebugLevel.warning)
            self.dict_return.set(key, False, f'SNMP: {label} ⚠ server not configured')
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
            self._fail_count[key] = self._fail_count.get(key, 0) + 1
            status = self._fail_count[key] < t_alert
            icon   = '🔼' if status else '🔽'
            msg    = f'SNMP: {label} {icon} [{err}]'
            self._debug(f'SNMP: {key} — error: {err}', DebugLevel.warning)
            self.dict_return.set(key, status, msg, False, {'oid': oid, 'error': err})
            if self.check_status(status, self.name_module, key):
                self.send_message(msg, status)
            return

        self._fail_count[key] = 0
        status = self._evaluate(raw_value, operator, expected)
        icon   = '🔼' if status else '🔽'
        msg    = f'SNMP: {label} {icon} [{raw_value}]'
        self._debug(
            f'SNMP: {key} — OID={oid} value={raw_value!r} '
            f'op={operator} expected={expected!r} → {status}',
            DebugLevel.info,
        )
        self.dict_return.set(key, status, msg, False, {
            'oid':      oid,
            'value':    raw_value,
            'operator': operator,
            'expected': expected,
        })
        if self.check_status(status, self.name_module, key):
            self.send_message(msg, status)

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

    # ── SNMP GET ───────────────────────────────────────────────────────────────

    @staticmethod
    def _snmp_get(
        host: str,
        port: int,
        version: str,
        community: str,
        timeout: int,
        retries: int,
        oid: str,
        v3_username: str = '',
        v3_auth_key: str = '',
        v3_priv_key: str = '',
        v3_auth_proto: str = 'MD5',
        v3_priv_proto: str = 'DES',
    ) -> tuple:
        """Synchronous SNMP GET wrapping the asyncio API."""
        if not _HAS_PYSNMP:
            return None, 'pysnmp is not installed'

        async def _run() -> tuple:
            if version == '3':
                auth_data = UsmUserData(
                    v3_username or 'public',
                    authKey=v3_auth_key or None,
                    privKey=v3_priv_key or None,
                    authProtocol=_AUTH_PROTOCOLS.get(v3_auth_proto, usmHMACMD5AuthProtocol),
                    privProtocol=_PRIV_PROTOCOLS.get(v3_priv_proto, usmDESPrivProtocol),
                )
            else:
                mp_model  = 0 if version == '1' else 1
                auth_data = CommunityData(community, mpModel=mp_model)

            transport = await UdpTransportTarget.create(
                (host, port), timeout=timeout, retries=retries
            )
            error_indication, error_status, error_index, var_binds = await get_cmd(
                SnmpEngine(), auth_data, transport, ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
            if error_indication:
                return None, str(error_indication)
            if error_status:
                idx = int(error_index) - 1
                return None, f'{error_status.prettyPrint()} at index {idx}'
            for _, val in var_binds:
                return str(val), None
            return None, 'no OID data returned'

        try:
            return asyncio.run(_run())
        except Exception as exc:  # pylint: disable=broad-except
            return None, str(exc)

    # ── SNMP Walk (used by discover) ───────────────────────────────────────────

    @staticmethod
    async def _snmp_walk(
        host: str,
        port: int,
        version: str,
        community: str,
        timeout: int,
        retries: int,
        max_oids: int = 300,
    ) -> list:
        """Async SNMP walk — mib-2 and enterprises subtrees run in parallel.

        GETBULK (v2c/v3, maxRepetitions=50) reduces round-trips to ~ceil(n/50).
        Both subtrees are walked concurrently via asyncio.gather(), cutting
        wall-clock time roughly in half vs sequential walks.
        Falls back to sequential GETNEXT for SNMPv1.
        """
        mp_model  = 0 if version == '1' else 1
        auth_data = CommunityData(community, mpModel=mp_model)
        use_bulk  = version != '1'

        async def _walk_subtree(root_oid: str, limit: int) -> list[dict]:
            transport = await UdpTransportTarget.create(
                (host, port), timeout=timeout, retries=retries
            )
            engine  = SnmpEngine()
            context = ContextData()
            root    = ObjectType(ObjectIdentity(root_oid))
            items: list[dict] = []
            if use_bulk:
                cmd = bulk_walk_cmd(
                    engine, auth_data, transport, context,
                    0, 50, root,            # nonRepeaters=0, maxRepetitions=50
                    lexicographicMode=False,
                )
            else:
                cmd = walk_cmd(
                    engine, auth_data, transport, context, root,
                    lexicographicMode=False,
                )
            try:
                async for err_ind, err_st, _, var_binds in cmd:
                    if err_ind or err_st:
                        break
                    for vb in var_binds:
                        oid_str   = str(vb[0])
                        val_obj   = vb[1]
                        val_str   = val_obj.prettyPrint()
                        if len(val_str) > 120:
                            val_str = val_str[:117] + '…'
                        snmp_type = type(val_obj).__name__
                        items.append({
                            'name':         oid_str,
                            'display_name': val_str,
                            'status':       snmp_type,
                            'mib_category': _mib_resolver.get_category(snmp_type),
                        })
                        if len(items) >= limit:
                            break
                    if len(items) >= limit:
                        break
            except Exception:  # pylint: disable=broad-except
                pass
            return items

        per_subtree = max(1, max_oids // 2)
        subtrees    = ['1.3.6.1.2.1', '1.3.6.1.4.1']   # mib-2, enterprises

        if use_bulk:
            # Parallel: both subtrees walk simultaneously
            gathered = await asyncio.gather(
                *[_walk_subtree(oid, per_subtree) for oid in subtrees],
                return_exceptions=True,
            )
            results: list[dict] = []
            for chunk in gathered:
                if isinstance(chunk, list):
                    results.extend(chunk)
        else:
            # SNMPv1: sequential (GETBULK not available)
            results = []
            for oid in subtrees:
                if len(results) >= max_oids:
                    break
                results.extend(await _walk_subtree(oid, max_oids - len(results)))

        return results[:max_oids]
