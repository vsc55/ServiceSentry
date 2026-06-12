#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persisted MIB symbol catalog for the SNMP watchful.

The MIB Browser needs the full set of symbols (name, OID, type, enum values,
range, description…) extracted from every user-compiled MIB.  Re-loading all
compiled pysnmp modules with ``loadTexts=True`` on *every* browser open is slow
and scales with the number of compiled MIBs.

This module extracts that catalog **once** (after a compilation) into a local
SQLite cache file::

    {var_dir}/snmp_mibs/mib_catalog.db   →  table ``symbols``

so that ``get_all_symbols`` becomes a cheap ``SELECT`` (cached in memory and
invalidated by the DB file's mtime) instead of a full pysnmp load.

This is a *local derived cache*, intentionally a standalone sqlite3 file rather
than the application database (which may be remote and must not hold per-install
MIB cache).  The browser still loads the whole catalog and builds its tree
client-side — only the server-side extraction is cached.
"""
import json
import os
import re
import sqlite3
import threading

_CATALOG_DB = 'mib_catalog.db'

# var_dir → (db_mtime, symbols list).  Guards against re-reading the DB on every
# browser open; invalidated when the DB file's mtime changes (i.e. a rebuild).
_lock: threading.Lock = threading.Lock()
_cache: dict[str, tuple[float, list]] = {}

# Columns persisted per symbol.  ``enum_values`` is stored as a JSON string.
_COLUMNS = (
    'oid', 'name', 'module', 'type', 'base_category',
    'enum_values', 'range_min', 'range_max',
    'status', 'access', 'units', 'desc',
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS symbols (
    {', '.join(f'{c} TEXT' for c in _COLUMNS if c not in ('range_min', 'range_max'))},
    range_min INTEGER,
    range_max INTEGER
);
CREATE INDEX IF NOT EXISTS idx_symbols_oid    ON symbols(oid);
CREATE INDEX IF NOT EXISTS idx_symbols_module ON symbols(module);
"""


def catalog_path(var_dir: str) -> str:
    return os.path.join(var_dir, 'snmp_mibs', _CATALOG_DB)


def catalog_needs_rebuild(var_dir: str, compiled_dir: str | None = None) -> bool:
    """True if the catalog DB is missing or older than any compiled MIB file."""
    if not var_dir:
        return False
    p = catalog_path(var_dir)
    if not os.path.isfile(p):
        return True
    db_mtime = os.path.getmtime(p)
    cdir = compiled_dir or os.path.join(var_dir, 'snmp_mibs', 'compiled')
    if not os.path.isdir(cdir):
        return False
    return any(
        os.path.getmtime(os.path.join(cdir, fn)) > db_mtime
        for fn in os.listdir(cdir)
        if fn.endswith('.py') and not fn.startswith('__')
    )


# ── Symbol extraction (moved from Watchful.get_all_symbols) ──────────────────

def _sa(obj, *attrs) -> str:
    """Return the first non-empty stringified attribute among *attrs*."""
    for a in attrs:
        v = getattr(obj, a, None)
        if v is None:
            continue
        s = str(v).strip()
        if s and s not in ('None', '""', "''"):
            return s
    return ''


def _sym_type_info(sym_obj):
    """Extract (enum_values, range_min, range_max, base_category) from a symbol."""
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


def extract_symbols(mib_builder) -> list[dict]:
    """Walk a loaded pysnmp ``MibBuilder`` and return the rich symbol list."""
    symbols: list[dict] = []
    raw_syms = getattr(mib_builder, 'mibSymbols', {})
    for mod_name, mod_syms in (raw_syms.items() if hasattr(raw_syms, 'items') else []):
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
    return symbols


# ── Build / read the SQLite catalog ──────────────────────────────────────────

def write_catalog(var_dir: str, symbols: list[dict]) -> int:
    """Persist *symbols* to the catalog DB (full replace).  Returns the count."""
    if not var_dir:
        return 0
    p = catalog_path(var_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    rows = [
        tuple(
            json.dumps(s.get('enum_values') or []) if c == 'enum_values'
            else s.get(c)
            for c in _COLUMNS
        )
        for s in symbols
    ]
    con = sqlite3.connect(p)
    try:
        con.executescript(_SCHEMA)
        con.execute('DELETE FROM symbols')
        con.executemany(
            f"INSERT INTO symbols ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
            rows,
        )
        con.commit()
    finally:
        con.close()
    with _lock:
        _cache.pop(var_dir, None)
    return len(rows)


def build_catalog(var_dir: str, extra_dirs: list[str] | None = None) -> int:
    """Load every user-compiled MIB and persist its symbols to the catalog DB.

    Mirrors the stem selection of the old in-line ``get_all_symbols`` (the
    compiled dir + *extra_dirs* only — pysnmp built-ins are intentionally NOT
    included, so the browser shows the same set as before).  Returns the number
    of symbols written.
    """
    if not var_dir:
        return 0
    compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
    extra = [d for d in (extra_dirs or []) if os.path.isdir(d)]
    stems: list[str] = []
    if os.path.isdir(compiled_dir):
        stems = [fn[:-3] for fn in os.listdir(compiled_dir)
                 if fn.endswith('.py') and not fn.startswith('__')]
    if not stems and not extra:
        return write_catalog(var_dir, [])

    try:
        from pysnmp.smi import builder  # noqa: PLC0415
    except ImportError:
        return 0

    mb = builder.MibBuilder()
    mb.loadTexts = True
    if os.path.isdir(compiled_dir):
        mb.addMibSources(builder.DirMibSource(compiled_dir))
    for d in extra:
        mb.addMibSources(builder.DirMibSource(d))
    for stem in stems:
        try:
            mb.loadModules(stem)
        except Exception:  # pylint: disable=broad-except
            pass

    return write_catalog(var_dir, extract_symbols(mb))


def read_catalog(var_dir: str) -> list[dict]:
    """Return the full symbol catalog, cached in memory by DB mtime."""
    if not var_dir:
        return []
    p = catalog_path(var_dir)
    if not os.path.isfile(p):
        return []
    mtime = os.path.getmtime(p)
    with _lock:
        cached = _cache.get(var_dir)
        if cached and cached[0] == mtime:
            return cached[1]

    con = sqlite3.connect(p)
    try:
        cur = con.execute(f"SELECT {', '.join(_COLUMNS)} FROM symbols")
        col_idx = {c: i for i, c in enumerate(_COLUMNS)}
        symbols: list[dict] = []
        for row in cur.fetchall():
            try:
                enum = json.loads(row[col_idx['enum_values']] or '[]')
            except (ValueError, TypeError):
                enum = []
            symbols.append({
                'name':          row[col_idx['name']],
                'oid':           row[col_idx['oid']],
                'module':        row[col_idx['module']],
                'type':          row[col_idx['type']],
                'base_category': row[col_idx['base_category']],
                'enum_values':   enum,
                'range_min':     row[col_idx['range_min']],
                'range_max':     row[col_idx['range_max']],
                'status':        row[col_idx['status']],
                'access':        row[col_idx['access']],
                'units':         row[col_idx['units']],
                'desc':          row[col_idx['desc']],
            })
    finally:
        con.close()

    with _lock:
        _cache[var_dir] = (mtime, symbols)
    return symbols


def invalidate_catalog(var_dir: str | None = None) -> None:
    """Drop the in-memory catalog cache (all entries, or just *var_dir*)."""
    with _lock:
        if var_dir is None:
            _cache.clear()
        else:
            _cache.pop(var_dir, None)


def discard(var_dir: str) -> None:
    """Delete the on-disk catalog and drop its cache so it is rebuilt lazily.

    Use this after compiled MIBs are removed: deletion doesn't make the
    remaining files newer, so the mtime-based ``catalog_needs_rebuild`` can't
    detect it.  Discarding is O(1) (one file unlink) — far cheaper than
    rebuilding the catalog on every deletion — and the next ``get_all_symbols``
    rebuilds it once.
    """
    if not var_dir:
        return
    try:
        os.remove(catalog_path(var_dir))
    except OSError:
        pass
    invalidate_catalog(var_dir)
