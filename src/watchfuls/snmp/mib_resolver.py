#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MIB resolver for the SNMP watchful.

Uses pysnmp's built-in compiled MIBs to map numeric OIDs to human-readable
names and official data types.  Custom pre-compiled Python MIB modules can
be loaded from extra directories via the module's ``mib_dirs`` setting.

For vendor MIBs in raw ASN.1 format, compile them first with pysmi:

    pip install pysmi
    mibdump.py --mib-source /path/to/raw \\
               --destination /path/to/compiled \\
               CISCO-MIB ENTITY-MIB ...

Then point ``mib_dirs`` to ``/path/to/compiled``.
"""
import json
import os
import re
import threading

# ── Type category tables ─────────────────────────────────────────────────────

NUMERIC_TYPES: frozenset = frozenset({
    'Integer', 'Integer32', 'Integer64', 'Unsigned32',
    'Counter32', 'Counter64', 'Gauge32', 'TimeTicks',
})
STRING_TYPES: frozenset = frozenset({
    'OctetString', 'DisplayString', 'SnmpAdminString',
    'TruthValue', 'PhysAddress', 'DateAndTime',
    'AutonomousType', 'TimeStamp', 'TimeInterval',
})
IP_TYPES:  frozenset = frozenset({'IpAddress'})
OID_TYPES: frozenset = frozenset({'ObjectIdentifier'})

_CAT_MAP: dict = {
    **{t: 'numeric' for t in NUMERIC_TYPES},
    **{t: 'string'  for t in STRING_TYPES},
    **{t: 'ip'      for t in IP_TYPES},
    **{t: 'oid'     for t in OID_TYPES},
}

# Default operator to pre-select per category when adding a discovered check
CATEGORY_DEFAULT_OPERATOR: dict = {
    'numeric': 'any',
    'string':  'contains',
    'ip':      'eq',
    'oid':     'eq',
    'unknown': 'any',
}


def get_category(snmp_type: str) -> str:
    """Map a pysnmp syntax class name to a broad category string.

    Returns one of: 'numeric', 'string', 'ip', 'oid', 'unknown'.
    """
    return _CAT_MAP.get(snmp_type, 'unknown')


# ── OID index ────────────────────────────────────────────────────────────────
# Pre-built flat dict  {oid_str: {mib_module, mib_name, mib_type}}  stored as
# JSON in {var_dir}/snmp_mibs/oid_index.json.  A single disk read (~30 ms)
# replaces hundreds of lazy pysnmp module loads (~900 ms each on first hit).

_OID_INDEX_FILE = 'oid_index.json'
_idx_lock: threading.Lock = threading.Lock()
_idx_cache: dict[str, dict] = {}   # var_dir → oid_index dict


def _idx_path(var_dir: str) -> str:
    return os.path.join(var_dir, 'snmp_mibs', _OID_INDEX_FILE)


def _load_idx(var_dir: str) -> dict:
    """Load index from disk; return empty dict on any error."""
    if not var_dir:
        return {}
    p = _idx_path(var_dir)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def get_oid_index(var_dir: str) -> dict:
    """Return in-memory OID index for *var_dir*, loading from disk if needed."""
    with _idx_lock:
        if var_dir not in _idx_cache:
            _idx_cache[var_dir] = _load_idx(var_dir)
        return _idx_cache[var_dir]


def index_needs_rebuild(var_dir: str) -> bool:
    """True if the index is missing or older than any compiled MIB file."""
    if not var_dir:
        return False
    p = _idx_path(var_dir)
    if not os.path.isfile(p):
        return True
    idx_mtime = os.path.getmtime(p)
    compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
    if not os.path.isdir(compiled_dir):
        return False
    return any(
        os.path.getmtime(os.path.join(compiled_dir, fn)) > idx_mtime
        for fn in os.listdir(compiled_dir)
        if fn.endswith('.py') and not fn.startswith('__')
    )


def build_oid_index(var_dir: str, extra_dirs: list[str] | None = None) -> int:
    """Build and persist the OID index from all available compiled MIBs.

    Loads pysnmp's built-in MIBs plus any user-compiled MIBs in
    ``{var_dir}/snmp_mibs/compiled/`` and *extra_dirs*.  Saves the result to
    ``{var_dir}/snmp_mibs/oid_index.json``.

    Returns the number of OIDs indexed.
    """
    try:
        from pysnmp.smi import builder as _sb  # type: ignore[import]
    except ImportError:
        return 0

    mb = _sb.MibBuilder()
    mb.loadTexts = False    # descriptions not needed for the index — faster build

    compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled') if var_dir else ''
    if compiled_dir and os.path.isdir(compiled_dir):
        mb.addMibSources(_sb.DirMibSource(compiled_dir))
    for d in (extra_dirs or []):
        if os.path.isdir(d):
            mb.addMibSources(_sb.DirMibSource(d))

    # Collect all MIB stems to load: user-compiled + pysnmp built-ins
    stems: list[str] = []
    if compiled_dir and os.path.isdir(compiled_dir):
        stems += [fn[:-3] for fn in os.listdir(compiled_dir)
                  if fn.endswith('.py') and not fn.startswith('__')]
    try:
        import pysnmp.smi.mibs as _pm  # type: ignore[import]
        _pdir = os.path.dirname(_pm.__file__)
        stems += [fn[:-3] for fn in os.listdir(_pdir)
                  if fn.endswith('.py') and not fn.startswith('__')]
    except Exception:
        pass

    for stem in set(stems):
        try:
            mb.loadModules(stem)
        except Exception:
            pass

    # Extract {oid → metadata} from every loaded symbol
    index: dict[str, dict] = {}
    raw = getattr(mb, 'mibSymbols', {})
    for mod_name, mod_syms in (raw.items() if hasattr(raw, 'items') else []):
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
                index[oid_str] = {
                    'mib_module': mod_name,
                    'mib_name':   sym_name,
                    'mib_type':   type(sym_obj).__name__,
                }
            except Exception:
                continue

    # Persist to disk
    if var_dir:
        p = _idx_path(var_dir)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(index, f, separators=(',', ':'))
        except Exception:
            pass

    # Update in-memory cache and invalidate resolver cache (may use new index)
    with _idx_lock:
        _idx_cache[var_dir] = index
    invalidate_cache()

    return len(index)


# ── MibResolver ──────────────────────────────────────────────────────────────

_lock: threading.Lock = threading.Lock()
_resolver_cache: dict = {}   # keyed by normalised mib_dirs + var_dir string


class MibResolver:
    """Stateful MIB resolver backed by a pre-built OID index with pysnmp fallback."""

    def __init__(self, mib_dirs: list | None = None, oid_index: dict | None = None):
        self._mib_dirs: list = [d for d in (mib_dirs or []) if os.path.isdir(d)]
        self._oid_index: dict = oid_index or {}
        self._mvc = self._build()

    # ── Public interface ──────────────────────────────────────────────────────

    def resolve(self, oid_str: str) -> dict:
        """Return MIB metadata for *oid_str* (dotted-decimal notation).

        When an OID index is loaded: pure O(1) dict lookup — no pysnmp I/O.
        Without an index: falls back to pysnmp's lazy MIB view (slow on cold start).

        Returns a dict with:
          mib_module  – MIB module name (e.g. 'SNMPv2-MIB') or ''
          mib_name    – object name + instance (e.g. 'sysDescr.0') or ''
          mib_type    – pysnmp syntax class name (e.g. 'DisplayString') or ''
        """
        empty = {'mib_module': '', 'mib_name': '', 'mib_type': ''}
        if not oid_str:
            return empty

        # ── Fast path: pre-built index ────────────────────────────────────────
        if self._oid_index:
            # Direct hit (query OID is itself a named object)
            entry = self._oid_index.get(oid_str)
            if entry:
                return {
                    'mib_module': entry['mib_module'],
                    'mib_name':   entry['mib_name'],
                    'mib_type':   entry['mib_type'],
                }
            # Prefix hit: strip instance suffix (.0, .1, .1.2, …)
            parts = oid_str.split('.')
            for depth in range(1, min(5, len(parts))):
                prefix = '.'.join(parts[:-depth])
                entry  = self._oid_index.get(prefix)
                if entry:
                    suffix = '.'.join(parts[-depth:])
                    return {
                        'mib_module': entry['mib_module'],
                        'mib_name':   f"{entry['mib_name']}.{suffix}",
                        'mib_type':   entry['mib_type'],
                    }
            # OID not in index — return empty immediately.
            # Do NOT fall through to pysnmp: resolveWithMib() on pysnmp 7 takes
            # ~900 ms on first call due to lazy module loading and returns only
            # generic SMI container names (e.g. 'mib-2'), not actual symbol names,
            # because IF-MIB / IP-MIB / HOST-RESOURCES-MIB etc. are absent from
            # pysnmp 7's built-in MIBs.  Compile those MIBs via the MIB Manager
            # to add them to the index.
            return empty

        # ── Fallback: pysnmp MIB view (no index available) ───────────────────
        if self._mvc is None:
            return empty
        try:
            from pysnmp.smi.rfc1902 import ObjectIdentity  # type: ignore[import]
            obj = ObjectIdentity(oid_str.strip().strip('.'))
            obj.resolveWithMib(self._mvc)
            mib_module, obj_name, indices = obj.getMibSymbol()
            suffix   = '.'.join(str(i) for i in indices) if indices else ''
            mib_name = f'{obj_name}.{suffix}' if suffix else str(obj_name)
            syntax   = obj.getSyntax()
            mib_type = type(syntax).__name__
            return {
                'mib_module': str(mib_module),
                'mib_name':   mib_name,
                'mib_type':   mib_type,
            }
        except Exception:
            return empty

    # ── Private ───────────────────────────────────────────────────────────────

    def _build(self):
        try:
            from pysnmp.smi import builder, view  # type: ignore[import]
            mib_builder = builder.MibBuilder()
            for d in self._mib_dirs:
                mib_builder.addMibSources(builder.DirMibSource(d))
            return view.MibViewController(mib_builder)
        except Exception:
            return None


def get_resolver(mib_dirs: list | None = None, var_dir: str = '') -> MibResolver:
    """Return a cached :class:`MibResolver` for *mib_dirs* + *var_dir*.

    When *var_dir* is provided, the pre-built OID index is loaded and injected
    into the resolver so that ``resolve()`` uses the fast O(1) path.
    """
    dirs      = sorted(d for d in (mib_dirs or []) if os.path.isdir(d))
    cache_key = '\0'.join(dirs) + '||' + var_dir
    with _lock:
        if cache_key not in _resolver_cache:
            oid_idx = get_oid_index(var_dir) if var_dir else {}
            _resolver_cache[cache_key] = MibResolver(dirs, oid_index=oid_idx)
        return _resolver_cache[cache_key]


def invalidate_cache() -> None:
    """Discard all cached resolvers (call after mib_dirs config changes)."""
    with _lock:
        _resolver_cache.clear()


# ── Default MIB directory helpers ────────────────────────────────────────────

def raw_dir_has_new_mibs(raw_dir: str, compiled_dir: str) -> bool:
    """True only when a raw MIB file is newer than all compiled .py modules.

    Avoids paying the ~800ms pysmi compiler-setup cost on every discover()
    call when nothing actually needs recompiling.
    """
    if not raw_dir or not os.path.isdir(raw_dir):
        return False
    raw_files = [
        f for f in os.listdir(raw_dir)
        if not f.startswith('.') and os.path.isfile(os.path.join(raw_dir, f))
    ]
    if not raw_files:
        return False
    newest_compiled = 0.0
    if os.path.isdir(compiled_dir):
        for fn in os.listdir(compiled_dir):
            if fn.endswith('.py') and not fn.startswith('__'):
                t = os.path.getmtime(os.path.join(compiled_dir, fn))
                if t > newest_compiled:
                    newest_compiled = t
    return any(
        os.path.getmtime(os.path.join(raw_dir, f)) > newest_compiled
        for f in raw_files
    )


def get_default_dirs(var_dir: str) -> list[str]:
    """Return the compiled MIB directory under *var_dir* if it exists.

    The application stores user-provided MIBs in::

        {var_dir}/snmp_mibs/compiled/   ← pysnmp-compatible Python modules
        {var_dir}/snmp_mibs/raw/        ← raw ASN.1 .mib files (compiled on demand)

    Returns a list with one entry when the directory exists, empty list otherwise.
    """
    if not var_dir:
        return []
    compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
    return [compiled_dir] if os.path.isdir(compiled_dir) else []


# SMIv1-relaxed parser dialect — enables support for older/vendor MIB syntax
# while remaining compatible with strict SMIv2 MIBs.
try:
    from pysmi.parser.dialect import smi_v1_relaxed as _SMI_DIALECT  # pysmi ≥1.x  # type: ignore[import]
except ImportError:
    try:
        from pysmi.parser.dialect import smiV1Relaxed as _SMI_DIALECT  # type: ignore[import]
    except ImportError:
        _SMI_DIALECT = None


# Hard timeout (seconds) for fetching dependency MIBs over HTTP, so a slow or
# unreachable mirror can never freeze a compilation.
_HTTP_FETCH_TIMEOUT = 15


def _http_reader_with_timeout(url: str, timeout: int):
    """Build a pysmi ``HttpReader`` whose requests honour a hard timeout.

    pysmi's ``HttpReader.get_data()`` calls ``session.get(url)`` with no timeout,
    so an unresponsive mirror (or a MIB it does not host) blocks the whole
    compile indefinitely.  We wrap the underlying requests session so every
    request gets a default timeout when none is supplied.
    """
    from pysmi.reader import HttpReader  # noqa: PLC0415
    reader = HttpReader(url)
    sess = getattr(reader, 'session', None)
    if sess is not None and hasattr(sess, 'request'):
        _orig_request = sess.request

        def _request(method, req_url, **kw):
            kw.setdefault('timeout', timeout)
            return _orig_request(method, req_url, **kw)

        sess.request = _request
    return reader


def compile_raw_mibs(raw_dir: str, compiled_dir: str,
                     mibs_filter: list | None = None,
                     http_templates: list | None = None,
                     should_cancel=None) -> dict:
    """Convenience wrapper — compiles all (or selected) raw MIBs without progress reporting.

    See :func:`compile_raw_mibs_progressive` for return-value documentation.
    """
    return compile_raw_mibs_progressive(raw_dir, compiled_dir,
                                        mibs_filter=mibs_filter,
                                        http_templates=http_templates,
                                        should_cancel=should_cancel)


def compile_raw_mibs_progressive(
    raw_dir: str,
    compiled_dir: str,
    progress_cb=None,
    mibs_filter: list | None = None,
    http_templates: list | None = None,
    should_cancel=None,
) -> dict:
    """Compile raw ASN.1 MIB files from *raw_dir* into *compiled_dir*.

    *progress_cb*, when provided, is called as
    ``progress_cb(current_mib: str | None, completed: int, total: int)``
    after each MIB is processed.  The final call passes ``current_mib=None``
    to signal completion.

    Requires ``pysmi`` to be installed (``pip install pysmi``).
    Already up-to-date compilations are skipped automatically.
    Creates *compiled_dir* if it does not yet exist.

    Standard MIBs required by vendor MIBs (e.g. SNMPv2-SMI, SNMPv2-TC) are
    fetched automatically from ``https://mibs.pysnmp.com/asn1/`` when they are
    not present locally.  pysnmp's built-in MIBs are treated as stubs so they
    are never re-compiled.

    The SMIv1-relaxed parser dialect is used so that both old (SMIv1) and
    modern (SMIv2) MIBs can be compiled with a single configuration.

    Returns a dict with one of three shapes::

        {'ok': True,  'compiled': True,  'partial': False, 'results': {…}}
        {'ok': True,  'compiled': False, 'partial': False, 'results': {…}}
        {'ok': True,  'compiled': True,  'partial': True,
         'failed': […], 'message': '…', 'results': {…}}   # partial success
        {'ok': False, 'message': '…',   'results': {…},
         'failed': […]}                                      # all failed / error
    """
    if not raw_dir or not os.path.isdir(raw_dir):
        return {'ok': False, 'message': f'raw_dir not found: {raw_dir}', 'results': {}}

    raw_mibs = sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(raw_dir)
        if not f.startswith('.') and os.path.isfile(os.path.join(raw_dir, f))
    )
    if mibs_filter:
        _keep = set(mibs_filter)
        raw_mibs = [m for m in raw_mibs if m in _keep]
    if not raw_mibs:
        return {'ok': True, 'compiled': False, 'partial': False, 'results': {}}

    try:
        from pysmi.reader import FileReader, HttpReader    # type: ignore[import]
        from pysmi.searcher import PyFileSearcher, StubSearcher  # type: ignore[import]
        from pysmi.writer import PyFileWriter              # type: ignore[import]
        from pysmi.parser.smi import parserFactory         # type: ignore[import]
        from pysmi.codegen.pysnmp import PySnmpCodeGen     # type: ignore[import]
        from pysmi.compiler import MibCompiler             # type: ignore[import]
    except ImportError:
        return {'ok': False, 'message': 'pysmi not installed (pip install pysmi)', 'results': {}}

    os.makedirs(compiled_dir, exist_ok=True)

    # Collect pysnmp built-in MIB names to stub (avoid re-fetching / re-compiling
    # MIBs that ship pre-compiled with pysnmp).
    _builtin_mibs: list[str] = []
    try:
        import pysnmp.smi.mibs as _pm                      # type: ignore[import]
        _pdir = os.path.dirname(_pm.__file__)
        _builtin_mibs = [
            os.path.splitext(f)[0]
            for f in os.listdir(_pdir)
            if f.endswith('.py') and not f.startswith('__')
        ]
    except Exception:
        pass

    try:
        parser  = parserFactory(**_SMI_DIALECT)() if _SMI_DIALECT else parserFactory()()
        compiler = MibCompiler(parser, PySnmpCodeGen(), PyFileWriter(compiled_dir))
        # pysmi ≥1.x uses add_sources / add_searchers; fall back to old names
        _add_src = getattr(compiler, 'add_sources',   None) or compiler.addSources
        _add_srh = getattr(compiler, 'add_searchers', None) or compiler.addSearchers

        # Local raw MIBs first; HTTP fallback for standard/dependency MIBs.
        # The HTTP reader is given a hard timeout: pysmi's HttpReader issues
        # `session.get(url)` with NO timeout, so a slow/unreachable mirror (or a
        # MIB the mirror doesn't host) would hang the whole compile forever
        # (the classic "stuck at MIB N/M" freeze).
        _add_src(FileReader(raw_dir))
        # User-configured GitHub raw templates (each must carry the @mib@ magic),
        # tried before the default mirror so dependency MIBs can come from repos
        # that publish them.
        for _tpl in (http_templates or []):
            _tpl = str(_tpl).strip()
            if _tpl:
                _add_src(_http_reader_with_timeout(_tpl, _HTTP_FETCH_TIMEOUT))
        _add_src(_http_reader_with_timeout('https://mibs.pysnmp.com/asn1/@mib@',
                                           _HTTP_FETCH_TIMEOUT))
        _add_srh(PyFileSearcher(compiled_dir))
        # RFC-1212/RFC-1215 are macro-only MIBs that pysmi cannot compile from
        # their HTTP source (the downloaded stub is incomplete ASN.1).  Always
        # stub them so pysmi never tries to download+parse them.
        #
        # For pysnmp built-in MIBs: stub only those that the user has NOT placed
        # in raw_dir.  If the user dropped SNMPv2-MIB.txt into raw_dir they want
        # it compiled to compiled_dir — do NOT stub it.  Built-ins that are not
        # present in raw_dir are still stubbed to avoid unnecessary HTTP downloads.
        _raw_mibs_set = set(raw_mibs)
        _macro_stubs  = ['RFC-1212', 'RFC-1215']
        _stubs = [m for m in list(_builtin_mibs) + _macro_stubs if m not in _raw_mibs_set]
        if _stubs:
            _add_srh(StubSearcher(*_stubs))
    except Exception as exc:
        return {'ok': False, 'message': str(exc), 'results': {}}

    total       = len(raw_mibs)
    all_results: dict = {}

    # Compile one MIB per call so progress advances smoothly and a cancel request
    # is honoured between every MIB.  (Batching pysmi by feeding many MIBs per
    # compile() call does not speed up the CPU-bound parsing — the dominant cost —
    # it only makes progress lurch in big steps, so it isn't worth it here.)
    completed = 0
    cancelled = False
    for i, mib in enumerate(raw_mibs):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        if progress_cb:
            progress_cb(mib, i, total)
        try:
            # ignoreErrors=True: if a dependency MIB can't be compiled (e.g.
            # RFC-1212 is a macro-only stub that pysmi can't parse from its
            # HTTP source), pysmi would otherwise roll back the whole batch as
            # 'unprocessed'.  With this flag, only the unresolvable dependency
            # is marked failed while the requesting MIB is still written out.
            all_results.update(dict(compiler.compile(mib, ignoreErrors=True) or {}))
        except Exception:
            all_results[mib] = 'unprocessed'
        completed = i + 1

    if progress_cb:
        progress_cb(None, completed if cancelled else total, total)

    if any(v == 'compiled' for v in all_results.values()):
        invalidate_cache()

    result = _classify_compile_results(raw_mibs, all_results)
    if cancelled:
        result['cancelled'] = True
        _done = sum(1 for v in all_results.values() if v in ('compiled', 'untouched'))
        result['message'] = f'Cancelled — {_done} of {total} processed'
    return result


# pysmi MibStatus values that mean the requested MIB was NOT produced.
_FAILED_STATUSES: frozenset = frozenset({'unprocessed', 'missing', 'failed'})


def _classify_compile_results(raw_mibs: list, all_results: dict) -> dict:
    """Turn pysmi's per-MIB status map into the module's result envelope.

    Statuses: 'compiled' (ok), 'untouched'/'borrowed' (ok, not rebuilt),
    'failed'/'missing'/'unprocessed' (failure).  Only *raw_mibs* (the ones the
    user asked to compile) count toward failure — dependency MIBs fetched over
    HTTP are not the user's concern.
    """
    compiled_any = any(v == 'compiled' for v in all_results.values())
    failed       = [m for m in raw_mibs if all_results.get(m) in _FAILED_STATUSES]

    if failed and compiled_any:
        n = sum(1 for v in all_results.values() if v == 'compiled')
        return {
            'ok':      True,
            'compiled': True,
            'partial': True,
            'failed':  failed,
            'results': all_results,
            'message': f'{n} compiled, {len(failed)} failed: {", ".join(failed)}',
        }
    if failed:
        return {
            'ok':      False,
            'message': f"Compilation failed for: {', '.join(failed)}",
            'failed':  failed,
            'results': all_results,
        }
    return {'ok': True, 'compiled': compiled_any, 'partial': False, 'results': all_results}
