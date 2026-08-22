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
import contextlib
import io
import os
import re
import threading

from . import lint as _mib_lint

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

# How many MIBs an IMPLICIT compile may take on — the one nobody asked for, that runs because
# a discovery was clicked or because the module started.
#
# Parsing ASN.1 costs ~2.7 s per MIB on a normal box and it is 89% of the compile, so this is
# not a setup cost that can be tuned away: the number of files is the number of seconds.  One
# dropped into raw/ should still just work, which is what the automatic path was for.  A folder
# import brings hundreds — 988 in the case this was found through — and at that size an implicit
# compile is not a convenience, it is a panel that does not start for an hour with nothing on
# screen to say why.
#
# Above the limit the files stay raw and the MIB manager compiles them when asked: that path
# already exists, and it has a progress bar and a cancel button, which is what an hour of work
# needs and an implicit one can never have.
AUTO_COMPILE_LIMIT: int = 5


# How deep a MIB tree may go. A vendor archive nests one or two levels; anything past this
# is a directory that got where it is by accident, and walking it is time nobody asked for.
RAW_MAX_DEPTH = 4


def iter_raw_mibs(raw_dir: str) -> list:
    """Every raw MIB under *raw_dir*, as ``(relative path, absolute path)``.

    Recursive, because an imported repository or vendor archive keeps its own folders: LibreNMS
    publishes one directory per vendor, and flattening them puts two files called
    ``ENTITY-MIB`` in the same place, where one silently wins. The relative path is what the
    panel shows and what identifies a file for deletion; the absolute one is what opens it.
    """
    out = []
    if not raw_dir or not os.path.isdir(raw_dir):
        return out
    base = os.path.abspath(raw_dir)
    for root, dirs, files in os.walk(base):
        depth = root[len(base):].count(os.sep)
        if depth >= RAW_MAX_DEPTH:
            dirs[:] = []
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not d.startswith('__'))
        rel_root = root[len(base):].lstrip(os.sep).replace(os.sep, '/')
        for f in sorted(files):
            if f.startswith('.'):
                continue
            # No `isfile` here: `os.walk` has already separated the files from the
            # directories, and asking the filesystem again is five thousand more calls on a
            # library with LibreNMS in it. Whatever is left (a broken link) fails its `stat`
            # at the one place that needs one, and is skipped there.
            out.append((f'{rel_root}/{f}' if rel_root else f, os.path.join(root, f)))
    return out


def resolve_raw_sources(raw_dir: str, mibs) -> dict:
    """For each module name, the file pysmi would actually read — relative to *raw_dir*.

    Asked OF pysmi rather than worked out here. Which copy wins when several files carry the
    same module name follows pysmi's own order — every directory of the walk, and inside each
    one an extension order of its own — and a second implementation of that rule would be
    right until the version that changed it, with nothing to say it had stopped being right.

    In one batch because the reader re-walks the whole tree on every single lookup, and the
    tree does not change between two names asked in the same breath: the walk is done once and
    handed back to it. A name nothing answers for is absent from the result.
    """
    names = [str(m).strip() for m in (mibs or []) if str(m).strip()]
    if not raw_dir or not names or not os.path.isdir(raw_dir):
        return {}
    base = os.path.abspath(raw_dir)
    try:
        from pysmi.reader import FileReader    # type: ignore[import]
        reader = FileReader(raw_dir)
        _subdirs = getattr(reader, 'get_subdirs', None) or getattr(reader, 'getSubdirs')
        _dirs = list(_subdirs(raw_dir, True, True))
        reader.get_subdirs = lambda path, recursive=True, ignoreErrors=True: _dirs
        reader.getSubdirs = reader.get_subdirs
        _get = getattr(reader, 'get_data', None) or getattr(reader, 'getData')
    except Exception:                           # pylint: disable=broad-except
        return {}

    out = {}
    for mib in names:
        try:
            info = _get(mib)
        except Exception:                       # pylint: disable=broad-except
            continue
        if isinstance(info, tuple):             # pysmi returns (MibInfo, data)
            info = info[0]
        path = str(getattr(info, 'path', '') or '')
        if path.startswith('file://'):
            path = path[len('file://'):]
        try:
            rel = os.path.relpath(path, base)
        except ValueError:                      # another drive on Windows
            continue
        if not rel.startswith('..'):
            out[mib] = rel.replace(os.sep, '/')
    return out


def module_index(raw_dir: str) -> dict:
    """Every module declared under *raw_dir*, mapped to the file that declares it.

    The index pysmi does not have. It resolves an ``IMPORTS`` by trying the module name as a
    FILE name — ``DIFFSERV-DSCP-TC``, ``DIFFSERV-DSCP-TC.txt``, ``.mib``, ``.my`` — which in a
    vendor archive finds nothing at all: the file is called
    ``diffserv-dscp-tc-rfc3289.mib``, its neighbour declaring ``DNS-SERVER-MIB`` is called
    ``rfc1611.mib``, and the Linksys modules are all ``ls*.mib``. Every one of those imports
    came back "missing", and the MIB that needed them failed with nothing to show for it.

    First file wins, in walk order, which is the same rule the rest of the module uses for a
    name claimed twice.
    """
    out: dict = {}
    for _rel, full in iter_raw_mibs(raw_dir):
        name = raw_facts(full)['module']
        if name and name not in out:
            out[name] = full
    return out


def _module_reader(raw_dir: str):
    """A pysmi source that answers by declared module name, or ``None``.

    Built as a pysmi ``AbstractReader`` so the compiler treats it like any other source: it is
    asked first, answers the names it knows, and steps aside for everything else. The index is
    built on the first question and not before — a compile that resolves everything from the
    file names never pays for it.
    """
    try:
        from pysmi.reader.base import AbstractReader   # type: ignore[import]
        from pysmi.mibinfo import MibInfo              # type: ignore[import]
        from pysmi import error as _pysmi_error        # type: ignore[import]
    except ImportError:
        return None

    class _ModuleNameReader(AbstractReader):
        """Resolves a MIB by the name it declares inside itself."""

        def __init__(self, path):
            self._path = path
            self._index = None

        def __str__(self):
            return f'ModuleNameReader{{"{self._path}"}}'

        def get_data(self, mibname, **options):
            if self._index is None:
                self._index = module_index(self._path)
            full = self._index.get(mibname)
            if not full:
                raise _pysmi_error.PySmiReaderFileNotFoundError(mibname=mibname, reader=self)
            try:
                st = os.stat(full)
                with io.open(full, encoding='utf-8-sig', errors='replace') as fh:
                    data = fh.read(self.maxMibSize)
            except OSError:
                raise _pysmi_error.PySmiReaderFileNotFoundError(mibname=mibname, reader=self)
            return (MibInfo(path=f'file://{full}', file=os.path.basename(full),
                            name=mibname, mtime=st.st_mtime),
                    data)

        # pysmi < 1.x spelling, for the same reason the rest of this module carries both.
        getData = get_data

    return _ModuleNameReader(raw_dir)


def raw_mib_dirs(raw_dir: str) -> list:
    """*raw_dir* and every sub-directory holding MIBs — what pysmi needs as file sources.

    pysmi resolves an imported module by NAME against the directories it was given, and knows
    nothing about a tree. One source per directory is what lets a vendor MIB in a sub-folder
    import a standard one sitting beside it.
    """
    if not raw_dir or not os.path.isdir(raw_dir):
        return []
    seen = {os.path.abspath(raw_dir)}
    for rel, full in iter_raw_mibs(raw_dir):
        seen.add(os.path.dirname(full))
    return sorted(seen)


# A raw MIB has TWO names and they are routinely different: the file it is FOUND by, and
# the module it BECOMES. `trunk.mib` in a switch vendor's archive declares IEEE8023-LAG-MIB;
# `rfc2011.mib` declares IP-MIB. pysmi is asked for the first (that is how the file is
# located) and writes the second (that is what the module is called), so anything that judges
# "is this compiled?" by the file name judges it by a name nothing will ever produce.
#
# Cached on (mtime, size), because the listing asks this of every file on every refresh and
# the answer only changes when the file does.
_MODULE_NAME_CACHE: dict = {}


# MIBs that are MACRO DEFINITIONS and nothing else. pysmi cannot compile them from any
# source — there is nothing to compile, only grammar for other MIBs to use — and pysnmp has
# them built in. They are stubbed so the compiler never tries.
#
# Unconditionally, which is the whole point and was not what the code did: the stub list was
# filtered by "not present in raw_dir", a rule that is right for the ordinary built-ins (drop
# SNMPv2-MIB.txt in and you mean it to be compiled) and wrong for these two, because there is
# no version of them anybody can compile. A vendor archive that ships one — MG-Soft's
# `RFC-1212.my`, whose entire body is `SMI OBJECT-TYPE`, an SMIC directive pysmi has never
# heard of — cancelled its own stub and earned a "Bad grammar near offset 285" on every run,
# for ever, with nothing anybody could do about it.
MACRO_ONLY_MIBS: tuple = ('RFC-1212', 'RFC-1215')


def raw_facts(path: str, st=None) -> dict:
    """What a raw MIB DECLARES about itself: its module name and its date.

    One read for both, because they come out of the same header and the listing asks for both
    about every file. ``{'module': str, 'updated': str}``, either of them ``''``.
    """
    if not path:
        return {'module': '', 'updated': ''}
    # *st* is the caller's stat when it already has one: the listing stats every file to
    # show its size, and asking again for the cache key is a second five thousand calls for
    # an answer already in hand.
    try:
        st = st if st is not None else os.stat(path)
        key = (st.st_mtime, st.st_size)
    except OSError:
        return {'module': '', 'updated': ''}
    hit = _MODULE_NAME_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        with io.open(path, encoding='utf-8-sig', errors='replace') as fh:
            text = fh.read(_MODULE_NAME_READ)
    except OSError:
        return {'module': '', 'updated': ''}
    facts = {'module': _mib_lint.module_name(text),
             'updated': _mib_lint.last_updated(text)}
    _MODULE_NAME_CACHE[path] = (key, facts)
    return facts


def raw_module_name(path: str) -> str:
    """The module a raw MIB declares, or ``''`` when it declares none.

    Read from inside the file — ``X-MIB DEFINITIONS ::= BEGIN`` — because that is the only
    name pysmi knows a module by: it compiles to ``<MODULE>.py`` and resolves every ``IMPORTS``
    against it. The file name is how the file is found and nothing more.
    """
    return raw_facts(path)['module']


# Enough of a file to find its header past any preamble. Vendor MIBs open with licences of
# two hundred lines; nothing puts the declaration further in than this.
_MODULE_NAME_READ = 200000


# ── What was read out of each file, kept between runs ────────────────────────────────
# The in-memory cache above answers the second question about a file; this one answers the
# first, after a restart. A library with LibreNMS in it is five thousand files, and reading
# the head of every one of them is most of the time the section takes to open — a wait paid
# again on every restart, for facts that only change when a file does.
#
# Keyed by path RELATIVE to the raw folder so a data directory that moves does not invalidate
# everything, and validated on (mtime, size) exactly like the memory cache: this is a
# shortcut, never an authority.
_FACTS_FILE = '.facts-cache.json'


def _facts_cache_path(raw_dir: str) -> str:
    return os.path.join(os.path.dirname(raw_dir), _FACTS_FILE) if raw_dir else ''


def facts_cache_load(raw_dir: str) -> None:
    """Prime the fact cache from disk. Silent about everything: a cache that fails is a
    cache that is not there, which is a slower answer and never a wrong one."""
    path = _facts_cache_path(raw_dir)
    if not path or not os.path.isfile(path):
        return
    try:
        with io.open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    for rel, row in data.items():
        try:
            mtime, size, module, updated = row
            full = os.path.join(raw_dir, *str(rel).split('/'))
            _MODULE_NAME_CACHE.setdefault(
                full, ((float(mtime), int(size)),
                       {'module': str(module), 'updated': str(updated)}))
        except (TypeError, ValueError):
            continue


def facts_cache_save(raw_dir: str) -> None:
    """Write back what is known about the files that are still there."""
    path = _facts_cache_path(raw_dir)
    if not path:
        return
    base = os.path.abspath(raw_dir)
    out = {}
    for full, (key, facts) in list(_MODULE_NAME_CACHE.items()):
        ap = os.path.abspath(full)
        if not ap.startswith(base):
            continue
        rel = os.path.relpath(ap, base).replace(os.sep, '/')
        out[rel] = [key[0], key[1], facts.get('module', ''), facts.get('updated', '')]
    try:
        tmp = path + '.part'
        with io.open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, separators=(',', ':'))
        os.replace(tmp, path)
    except OSError:
        pass


# Which raw file a compiled module was built from, cached on (mtime, size): a .py only
# changes provenance when it is written again, and the listing asks about every one of them.
_SOURCE_CACHE: dict = {}


def compiled_source(compiled_dir: str, mib: str) -> str:
    """The raw file ``<mib>.py`` was made from, relative to the raw folder, or ``''``.

    pysmi writes it into the header of everything it produces (``ASN.1 source file://…``),
    which makes it the only answer about a compiled module that is a record rather than a
    guess — and the only way to notice that one has outlived the file it came from. No
    timestamp can say that: deleting a source makes nothing newer.
    """
    path = os.path.join(compiled_dir or '', f'{mib}.py')
    try:
        st = os.stat(path)
        key = (st.st_mtime, st.st_size)
    except OSError:
        return ''
    hit = _SOURCE_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        with io.open(path, encoding='utf-8', errors='replace') as fh:
            head = fh.read(2048)
    except OSError:
        return ''
    m = re.search(r'ASN\.1 source file://(.+)', head)
    src = m.group(1).strip().replace(chr(92), '/') if m else ''
    i = src.find('/raw/')
    rel = src[i + 5:] if i >= 0 else ''
    _SOURCE_CACHE[path] = (key, rel)
    return rel


def pending_raw_mibs(raw_dir: str, compiled_dir: str, files=None) -> list:
    """Names of raw MIBs with no compiled module, or one older than the source.

    *files* is the walk of the raw tree, when the caller already has one: the listing needs
    the same five thousand entries this does, and walking twice is a second helping of the
    most expensive thing either of them does.

    Per FILE, where :func:`raw_dir_has_new_mibs` answers per DIRECTORY against the newest
    compiled module of them all. That coarser answer is what made the automatic compile an
    all-or-nothing job: one new file made the whole directory "new", and the compile that
    followed walked every name in it.
    """
    if not raw_dir or not os.path.isdir(raw_dir):
        return []
    compiled_mtime: dict = {}
    if compiled_dir and os.path.isdir(compiled_dir):
        for fn in os.listdir(compiled_dir):
            if fn.endswith('.py') and not fn.startswith('__'):
                try:
                    compiled_mtime[fn[:-3]] = os.path.getmtime(os.path.join(compiled_dir, fn))
                except OSError:
                    continue
    # Which files carry which module, because both questions below are about the module and
    # neither is about the file's name.
    by_module: dict = {}
    for rel, path in (iter_raw_mibs(raw_dir) if files is None else files):
        by_module.setdefault(
            raw_module_name(path) or os.path.splitext(os.path.basename(rel))[0], []
        ).append((rel, path))

    out = []
    for mib, files in by_module.items():
        # A macro-only MIB produces no module and is not supposed to: counted as pending it
        # is a number that never goes down and a compile that runs for ever.
        if mib in MACRO_ONLY_MIBS:
            continue
        # Asked for by FILE name — that is how pysmi locates the source — but answered against
        # the MODULE name, which is what it writes. Judged by the file name, `trunk.mib` has
        # no `trunk.py` and never will: it compiles perfectly, into IEEE8023-LAG-MIB.py, and
        # is reported pending for ever while every run recompiles it and calls it untouched.
        done = compiled_mtime.get(mib)
        # A compiled module whose SOURCE is gone. No timestamp can say this — deleting a file
        # makes nothing newer — so left to the clock the module stays "up to date" while what
        # is loaded came from a file nobody can open any more. Deleting one copy of a module
        # that arrived twice is exactly how it happens.
        src = compiled_source(compiled_dir, mib) if done is not None else ''
        _rels = {rel.lower() for rel, _p in files}
        orphaned = bool(src) and src.lower() not in _rels
        for rel, path in files:
            stem = os.path.splitext(os.path.basename(rel))[0]
            if stem in out:
                continue
            try:
                if done is None or orphaned or os.path.getmtime(path) > done:
                    out.append(stem)
            except OSError:
                continue
    return out


def raw_dir_has_new_mibs(raw_dir: str, compiled_dir: str) -> bool:
    """True only when a raw MIB file is newer than all compiled .py modules.

    Avoids paying the ~800ms pysmi compiler-setup cost on every discover()
    call when nothing actually needs recompiling.
    """
    if not raw_dir or not os.path.isdir(raw_dir):
        return False
    raw_files = [full for _rel, full in iter_raw_mibs(raw_dir)]
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
_HTTP_FETCH_TIMEOUT = 8

# …and how many times one source may time out before it is written off for the rest of this
# compilation. A timeout alone is not the problem: pysmi asks each source for SEVERAL name
# variants of every missing module (`SNMPv2-SMI`, `.txt`, `.mib`, …), so ONE unreachable mirror
# costs the timeout times the variants times the modules — twenty MIBs behind a dead host is
# hours, and on screen it is a progress bar frozen at 0 with nothing to say why.
_HTTP_DEAD_AFTER = 2

# Where the standard modules come from when the installation has no copy of its own. Order is
# preference: the first that answers wins, and a MIB missing from one is simply looked for in
# the next.
_DEFAULT_MIB_SOURCES = (
    'https://raw.githubusercontent.com/net-snmp/net-snmp/master/mibs/@mib@.txt',
    'https://raw.githubusercontent.com/net-snmp/net-snmp/master/mibs/@mib@',
    'https://mibs.pysnmp.com/asn1/@mib@',
)


class _OsThatOverwrites:
    """``os`` for pysmi's writer, with a ``rename`` that replaces the destination.

    pysmi writes a compiled module to a temporary file and then ``os.rename``s it into place.
    On POSIX that overwrites; **on Windows it raises** when the destination exists
    (``WinError 183``). So on Windows pysmi could never rebuild a module it had already
    written: every recompile of an existing MIB failed with *failure writing file …: cannot
    create a file when that file already exists*, which meant an edited MIB stayed outdated
    for ever and "rebuild everything" could not rebuild anything at all. ``os.replace`` is the
    same call with POSIX semantics on both platforms.

    A proxy rather than a patch of ``os.rename`` itself — that one is shared by the whole
    process — and installed only for the length of a compilation.
    """

    def __init__(self, real) -> None:
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def rename(self, src, dst):
        return self._real.replace(src, dst)


@contextlib.contextmanager
def _pysmi_overwrites():
    """Let pysmi replace a module it has already written, on Windows too."""
    try:
        from pysmi.writer import pyfile as _pyfile  # noqa: PLC0415
    except ImportError:
        yield
        return
    original = _pyfile.os
    _pyfile.os = _OsThatOverwrites(original)
    try:
        yield
    finally:
        _pyfile.os = original


def _http_reader_with_timeout(url: str, timeout: int):
    """Build a pysmi ``HttpReader`` that honours a hard timeout AND gives up on a dead host.

    pysmi's ``HttpReader.get_data()`` calls ``session.get(url)`` with no timeout, so an
    unresponsive mirror blocks a compilation indefinitely. A timeout alone is not enough
    either: pysmi asks each source for several name variants of every missing module and
    swallows the error between tries, so an unreachable host is paid for once per variant, per
    module. That is the difference between a compile that is slow and one that looks frozen —
    which is what a mirror going offline actually did.

    So the timeout is per request, and after :data:`_HTTP_DEAD_AFTER` consecutive failures the
    reader stops making them: it raises straight away, pysmi catches it exactly as it catches a
    real failure, and the remaining sources are reached in microseconds. One success resets the
    count, because a mirror that answered is not dead.
    """
    from pysmi.reader import HttpReader  # noqa: PLC0415
    reader = HttpReader(url)
    sess = getattr(reader, 'session', None)
    if sess is not None and hasattr(sess, 'request'):
        _orig_request = sess.request
        _state = {'fails': 0}

        def _request(method, req_url, **kw):
            if _state['fails'] >= _HTTP_DEAD_AFTER:
                raise OSError(f'source gave up after {_state["fails"]} failures: {url}')
            kw.setdefault('timeout', timeout)
            try:
                resp = _orig_request(method, req_url, **kw)
            except Exception:
                _state['fails'] += 1
                raise
            # A 404 is an answer: this mirror simply does not host that MIB, and the next
            # variant or the next source might. Only a host that will not talk counts.
            _state['fails'] = 0
            return resp

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
    rebuild: bool = False,
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

    # …except the macro-only pair, which is never asked for. A StubSearcher covers them as
    # DEPENDENCIES, and that is all it can do: asked to compile one by name, pysmi parses the
    # source before it consults a searcher, so a local copy fails at the parse and no amount
    # of stubbing gets in front of it. The list of what to compile is where this belongs.
    #
    # Both names are kept, because both questions get asked about the same file: pysmi is
    # HANDED a file name, and everything that reasons about what a MIB *is* — what it
    # supersedes, what already exists — has to use the module the file declares.
    _pairs = []
    for rel, _full in iter_raw_mibs(raw_dir):
        _stem = os.path.splitext(os.path.basename(rel))[0]
        _mod = raw_module_name(_full) or _stem
        if _mod in MACRO_ONLY_MIBS:
            continue
        _pairs.append((_stem, _mod))
    if mibs_filter:
        _keep = set(mibs_filter)
        _pairs = [p for p in _pairs if p[0] in _keep]
    raw_mibs = sorted({stem for stem, _mod in _pairs})
    # What this library DECLARES, whatever its files are called. The stub decision below is
    # the one thing that must be answered with these and not with the file names.
    raw_modules = {mod for _stem, mod in _pairs}
    if not raw_mibs:
        return {'ok': True, 'compiled': False, 'partial': False, 'results': {}}

    try:
        from pysmi.reader import FileReader    # type: ignore[import]
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
        # One source per directory: pysmi resolves an imported module by name against the
        # directories it was given and knows nothing about a tree, so a MIB in a vendor
        # sub-folder could not import the standard one sitting beside it.
        # By declared module name FIRST: an IMPORTS names a module, and in a vendor archive
        # the file that holds it is called something else entirely. Asked for a name it does
        # not know, this reader steps aside and the directory readers below answer.
        _by_module = _module_reader(raw_dir)
        if _by_module is not None:
            _add_src(_by_module)
        for _dir in raw_mib_dirs(raw_dir):
            _add_src(FileReader(_dir))
        # User-configured GitHub raw templates (each must carry the @mib@ magic),
        # tried before the default mirror so dependency MIBs can come from repos
        # that publish them.
        for _tpl in (http_templates or []):
            _tpl = str(_tpl).strip()
            if _tpl:
                _add_src(_http_reader_with_timeout(_tpl, _HTTP_FETCH_TIMEOUT))
        # The fallbacks for the standard modules every vendor MIB imports (SNMPv2-SMI, -TC,
        # -CONF, NET-SNMP-TC). Net-SNMP's own repository first because it is the one that
        # answers: the pysnmp mirror that used to be the only default stopped responding, and
        # with it every compilation on an installation that had no local copy of a standard
        # MIB. It stays as a second chance rather than being removed — it may well come back,
        # and a source that does not answer now costs two timeouts instead of a compilation.
        for _default in _DEFAULT_MIB_SOURCES:
            _add_src(_http_reader_with_timeout(_default, _HTTP_FETCH_TIMEOUT))
        _add_srh(PyFileSearcher(compiled_dir))
        # RFC-1212/RFC-1215 are macro-only MIBs that pysmi cannot compile from
        # their HTTP source (the downloaded stub is incomplete ASN.1).  Always
        # stub them so pysmi never tries to download+parse them.
        #
        # For pysnmp built-in MIBs: stub only those that the user has NOT placed
        # in raw_dir.  If the user dropped SNMPv2-MIB.txt into raw_dir they want
        # it compiled to compiled_dir — do NOT stub it.  Built-ins that are not
        # present in raw_dir are still stubbed to avoid unnecessary HTTP downloads.
        # The macro-only pair is stubbed either way: see MACRO_ONLY_MIBS. There is no
        # copy of them anybody can compile, so "the user placed one here" cannot mean
        # "compile it" — it only means a permanent error nobody can clear.
        # By MODULE name, and this is not a detail: a stub says "you already have this,
        # do not compile it", and what the user placed in the library is a FILE. Asked of the
        # file name, `rfc2571.mib` is not called SNMP-FRAMEWORK-MIB, so the copy the user
        # imported was stubbed away — never compiled, no module written, and reported pending
        # for ever while every run recompiled it and answered "untouched". The same identity
        # split that pysmi has everywhere: it LOCATES by file name and WRITES the module's.
        # Two files in one real library: SNMP-FRAMEWORK-MIB and RFC1213-MIB, both from the
        # MIB set that ships with Windows.
        _stubs = [m for m in _builtin_mibs if m not in raw_modules]
        _stubs += list(MACRO_ONLY_MIBS)
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
    with _pysmi_overwrites():
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
                # `rebuild` is the difference between "compile what needs it" and "do it
                # again anyway". pysmi's default is to compare timestamps and answer 'untouched',
                # which is right almost always — and useless in the case you reach for this:
                # pysmi itself was upgraded, or a dependency changed in a way no mtime here
                # reflects, and the output is stale while every file looks current.
                all_results.update(dict(
                    compiler.compile(mib, ignoreErrors=True, rebuild=rebuild) or {}))
            except Exception:
                all_results[mib] = 'unprocessed'
            completed = i + 1

    if progress_cb:
        progress_cb(None, completed if cancelled else total, total)

    if any(v == 'compiled' for v in all_results.values()):
        invalidate_cache()

    # Which module each requested file turned out to be, and which of them the job actually
    # reached — a cancelled run must not speak for what it never got to.
    _modules = {stem: (raw_module_name(full) or stem)
                for stem in raw_mibs
                for full in [_source_of(raw_dir, stem)] if full}
    result = _classify_compile_results(raw_mibs, all_results, _modules)
    if cancelled:
        result['cancelled'] = True
        _done = sum(1 for v in all_results.values() if v in ('compiled', 'untouched'))
        result['message'] = f'Cancelled — {_done} of {total} processed'
    return result


# pysmi MibStatus values that mean the requested MIB was NOT produced.
_FAILED_STATUSES: frozenset = frozenset({'unprocessed', 'missing', 'failed'})


def _compile_error(status) -> str:
    """Why a MIB failed, in one line.

    A pysmi status is a string subclass, and the string only ever says *that* it failed —
    the cause is hung off the object as ``.error``. Dropping it is how a malformed vendor
    file becomes a row that stays "pending" forever with nothing to act on: the user cannot
    tell a broken MIB from one nobody has compiled yet, and both look like a bug in here.
    """
    err = getattr(status, 'error', None)
    if err is None:
        return ''
    msg = str(getattr(err, 'msg', '') or err).strip().replace('\n', ' ')
    return msg[:2000]


def _compile_errors(failed: list, all_results: dict) -> dict:
    out = {}
    for m in failed:
        msg = _compile_error(all_results.get(m))
        if msg:
            out[m] = msg
    return out


def _source_of(raw_dir: str, stem: str) -> str:
    """The file a requested name refers to — the first whose stem matches, in walk order.

    The same order pysmi's own reader walks, so the module this resolves to is the module it
    will compile.
    """
    for rel, full in iter_raw_mibs(raw_dir):
        if os.path.splitext(os.path.basename(rel))[0] == stem:
            return full
    return ''


def _classify_compile_results(raw_mibs: list, all_results: dict,
                              modules: dict | None = None) -> dict:
    """Turn pysmi's per-MIB status map into the module's result envelope.

    Statuses: 'compiled' (ok), 'untouched'/'borrowed' (ok, not rebuilt),
    'failed'/'missing'/'unprocessed' (failure).  Only *raw_mibs* (the ones the
    user asked to compile) count toward failure — dependency MIBs fetched over
    HTTP are not the user's concern.

    *raw_mibs* holds the names pysmi was ASKED for, which are file names; *all_results* is
    keyed by the module names pysmi ANSWERS with. Matched against each other directly, a MIB
    whose file is not named after its module can never be found in its own result — so its
    failure was invisible, and a compile that produced nothing reported no error and left the
    row pending. *modules* is the map between the two.

    And pysmi answers with EITHER name depending on how it went: a module it compiled comes
    back under the module's name, one it could not parse under the name it was handed, because
    it never got far enough to read the module out of the file. Both are one MIB and both have
    to be looked for, or the failures go missing again in the other direction.
    """
    _mod = (lambda m: (modules or {}).get(m, m))
    # Status per requested MIB, filed under the name the panel knows it by.
    _status = {}
    for m in raw_mibs:
        st = all_results.get(_mod(m))
        if st is None:
            st = all_results.get(m)
        if st is not None:
            _status[_mod(m)] = st

    compiled_any = any(v == 'compiled' for v in all_results.values())
    failed       = [m for m, st in _status.items() if st in _FAILED_STATUSES]

    if failed and compiled_any:
        n = sum(1 for v in all_results.values() if v == 'compiled')
        return {
            'ok':      True,
            'compiled': True,
            'partial': True,
            'failed':  failed,
            'errors':  _compile_errors(failed, _status),
            'results': all_results,
            'attempted': list(_status),
            'message': f'{n} compiled, {len(failed)} failed: {", ".join(failed)}',
        }
    if failed:
        return {
            'ok':      False,
            'message': f"Compilation failed for: {', '.join(failed)}",
            'failed':  failed,
            'errors':  _compile_errors(failed, _status),
            'results': all_results,
            'attempted': list(_status),
        }
    return {'ok': True, 'compiled': compiled_any, 'partial': False, 'results': all_results,
            'attempted': list(_status)}
