#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: administering the MIB catalogue.
#
"""Getting MIBs onto the box, compiled and browsable - which is not monitoring at all.

Six hundred lines of the watchful never checked anything: they upload a MIB, compile raw
ASN.1 with pysmi, import a folder from GitHub or a file from a URL, list what is there and
answer for its contents. That is a small file manager with a background job runner, and it
sat in the same file as the check loop because it grew there.

It joins the two modules that already carried the rest of this subsystem:
:mod:`mib_resolver` (numeric OID to name) and :mod:`mib_catalog` (the symbol cache). Those
are libraries; this is the admin surface the panel drives.
"""

import concurrent.futures
import glob
import json
import logging
import os
import re
import threading
import uuid

import importlib.util as _importlib_util

from lib.debug import DebugLevel
from . import mib_resolver as _mib_resolver
from . import mib_catalog as _mib_catalog
from .client import _HAS_PYSNMP

# Optional dependency: pysmi is needed to COMPILE raw ASN.1, not to read an already
# compiled MIB - which is why it is a partial dependency and not a missing one.
_HAS_PYSMI = _importlib_util.find_spec('pysmi') is not None

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


# ── GitHub MIB repositories ───────────────────────────────────────────────────
# Curated repos that publish MIBs.  `folder` is a GitHub tree URL imported via
# the Contents API; `dep_template` is a raw URL with the @mib@ placeholder used
# as an HTTP source for resolving missing dependency MIBs while compiling.
_LOG = logging.getLogger(__name__)

# Directory holding one JSON file per known public MIB repository.  Drop a new
# file there to add a source — see mib_sources/README.md.
_MIB_SOURCES_DIR = os.path.join(os.path.dirname(__file__), 'mib_sources')


def _load_mib_sources(directory: str = _MIB_SOURCES_DIR) -> list[dict]:
    """Discover and validate the known MIB repositories declared as JSON files.

    Each ``*.json`` declares ``{name, folder, dep_templates[, order]}``.
    ``dep_templates`` is the list of pysmi HTTP source templates (``@mib@`` is
    replaced with the imported MIB module name) used to resolve dependencies
    during compilation — a repo lists one template per file extension it uses,
    because a single repo mixes extensions (e.g. Net-SNMP stores MIBs as .txt,
    .mib AND extension-less) and pysmi must try every variant to resolve an
    imported module by name.

    Malformed files are skipped with a warning so a bad source can never break
    module import.  Returns the repos sorted by ``order`` then ``name``.
    """
    repos: list[dict] = []
    for path in sorted(glob.glob(os.path.join(directory, '*.json'))):
        try:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            _LOG.warning('Skipping MIB source %s: %s', os.path.basename(path), exc)
            continue
        name    = str(data.get('name') or '').strip()
        folder  = str(data.get('folder') or '').strip()
        tpls    = data.get('dep_templates')
        if not isinstance(tpls, list):
            tpls = [tpls] if tpls else []
        tpls = [str(t).strip() for t in tpls if str(t).strip()]
        if not (name and folder and tpls) or _parse_github_folder(folder) is None:
            _LOG.warning('Skipping invalid MIB source %s (name/folder/dep_templates)',
                         os.path.basename(path))
            continue
        repos.append({'name': name, 'folder': folder, 'dep_templates': tpls,
                      'order': data.get('order', 1_000_000)})
    repos.sort(key=lambda r: (r.get('order', 1_000_000), r['name']))
    for r in repos:
        r.pop('order', None)
    return repos


# GitHub folder-URL parsers.
_GH_TREE_RE = re.compile(r'^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.+?))?/?$')
_GH_ROOT_RE = re.compile(r'^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$')

# Filenames that are never MIBs (matched case-insensitively, extension-less only).
_GH_SKIP_NAMES = frozenset({
    'readme', 'license', 'licence', 'copying', 'makefile', 'changelog',
    'authors', 'contributors', 'notice', 'todo', 'index', 'manifest',
})


def _parse_github_folder(url: str):
    """Parse a GitHub folder URL → (owner, repo, branch, path) or None.

    Accepts ``.../tree/<branch>/<path>``, ``.../tree/<branch>`` and bare
    ``github.com/<owner>/<repo>`` (root of the default branch).
    """
    m = _GH_TREE_RE.match(url.strip())
    if m:
        return m.group(1), m.group(2), m.group(3), (m.group(4) or '')
    m = _GH_ROOT_RE.match(url.strip())
    if m:
        return m.group(1), m.group(2), '', ''
    return None


def _looks_like_mib_file(name: str) -> bool:
    """Heuristic: is *name* a MIB file we should import?"""
    ext = os.path.splitext(name)[1].lower()
    if ext in ('.mib', '.txt', '.my'):
        return True
    if ext == '':   # extension-less repos (e.g. LibreNMS) name files as the MIB
        stem = name.lower()
        return stem not in _GH_SKIP_NAMES and bool(_SAFE_FILENAME_RE.match(name))
    return False


def _truthy_import(value) -> bool:
    """Coerce a config value (str/bool) to bool, defaulting truthy."""
    return str(value).strip().lower() not in ('false', '0', 'no', 'off', 'none', '')


# Known public MIB repositories, loaded from mib_sources/*.json at import
# (defined after _parse_github_folder, which the loader uses for validation).
_KNOWN_MIB_REPOS: list[dict] = _load_mib_sources()


def _run_github_import(var_dir: str, url: str, recursive: bool, progress_cb=None) -> dict:
    """Import every MIB file from a GitHub repository folder into raw/.

    *url* is a GitHub folder URL (``.../tree/<branch>/<path>`` or a bare repo
    URL).  Runs in two phases so progress can report a real ``X / total``:

    1. **Discover** — BFS the folder tree via the GitHub Contents API
       (recursing into sub-folders when *recursive* is set) to enumerate every
       file that looks like a MIB (.mib/.txt/.my, or an extension-less
       MIB-named file).  No downloads happen yet; this yields the *total*.
    2. **Download** — fetch each discovered file, invoking
       *progress_cb(completed, total, failed, current)* after each so callers
       can render a determinate progress bar.

    API calls and file count are capped (unauthenticated GitHub allows
    60 req/h); a ``truncated`` flag signals when a cap was hit.
    """
    import urllib.request  # noqa: PLC0415
    from lib.security.net_guard import validate_external_url  # noqa: PLC0415

    parsed = _parse_github_folder(url)
    if not parsed:
        return {'ok': False, 'message': 'Not a recognised GitHub folder URL'}
    owner, repo, branch, path = parsed

    raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
    os.makedirs(raw_dir, exist_ok=True)

    _MAX_API_CALLS, _MAX_FILES, _MAX_DEPTH = 40, 1000, 5
    imported: list = []
    failed:   list = []
    truncated = False

    def _get_json(p):
        ref = f'?ref={branch}' if branch else ''
        u = f'https://api.github.com/repos/{owner}/{repo}/contents/{p}{ref}'
        if validate_external_url(u):
            return None
        req = urllib.request.Request(u, headers={
            'User-Agent': 'ServiceSentry',
            'Accept': 'application/vnd.github+json',
        })
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def _save(dl_url, name):
        if not _safe_mib_filename(name, 'raw') or validate_external_url(dl_url):
            return False
        dest = _confined_path(raw_dir, name)
        if not dest:
            return False
        req = urllib.request.Request(dl_url, headers={'User-Agent': 'ServiceSentry'})
        with urllib.request.urlopen(req, timeout=20) as r:
            content = r.read().decode('utf-8', errors='replace')
        # An unchanged file is not rewritten. Whether a MIB needs compiling is decided by
        # comparing its mtime against the compiled module, so rewriting identical bytes
        # marks it stale and buys a re-parse — ~2.7 s of ASN.1 each, for a file that did
        # not change. Re-importing a folder to pick up a handful of new MIBs invalidated
        # every one already compiled from it, which is how a second import came to cost as
        # much as the first.
        try:
            if os.path.isfile(dest):
                with open(dest, encoding='utf-8') as fh:
                    if fh.read() == content:
                        return True
        except OSError:
            pass
        with open(dest, 'w', encoding='utf-8') as fh:
            fh.write(content)
        return True

    _progress_lock = threading.Lock()

    def _report(total, name=None):
        if progress_cb is not None:
            try:
                with _progress_lock:
                    progress_cb(len(imported), total, len(failed), name)
            except Exception:  # pylint: disable=broad-except
                pass

    # ── Phase 1: discover every MIB file (folder traversal only, no downloads) ──
    to_download: list = []   # (name, download_url)
    api_calls = 0
    queue = [(path, 0)]
    while queue:
        cur, depth = queue.pop(0)
        if api_calls >= _MAX_API_CALLS or len(to_download) >= _MAX_FILES:
            truncated = True
            break
        api_calls += 1
        try:
            entries = _get_json(cur)
        except Exception as exc:  # pylint: disable=broad-except
            failed.append({'name': cur or '(root)', 'error': str(exc)})
            continue
        if not isinstance(entries, list):
            failed.append({'name': cur or '(root)', 'error': 'not a folder'})
            continue
        for e in entries:
            if len(to_download) >= _MAX_FILES:
                truncated = True
                break
            etype, name = e.get('type'), e.get('name', '')
            if etype == 'dir':
                if recursive and depth < _MAX_DEPTH:
                    queue.append((e.get('path', ''), depth + 1))
                continue
            if etype != 'file' or not _looks_like_mib_file(name):
                continue
            dl = e.get('download_url')
            if dl:
                to_download.append((name, dl))

    total = len(to_download)
    _report(total, None)   # announce the total before downloading

    # ── Phase 2: download the discovered files concurrently ──
    # Sequential downloads (one fresh TLS connection per file) are painfully slow
    # for repos with hundreds of small MIBs.  A thread pool overlaps the network
    # latency; list.append + the progress lock keep the shared state consistent.
    _io_lock = threading.Lock()

    def _fetch(item):
        name, dl = item
        try:
            ok = _save(dl, name)
            with _io_lock:
                if ok:
                    imported.append(name)
                else:
                    failed.append({'name': name, 'error': 'rejected'})
        except Exception as exc:  # pylint: disable=broad-except
            with _io_lock:
                failed.append({'name': name, 'error': str(exc)})
        _report(total, name)

    if to_download:
        workers = max(1, min(16, len(to_download)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_fetch, to_download))

    if imported:
        _mib_resolver.invalidate_cache()

    msg = f'{len(imported)} MIB file(s) imported'
    if truncated:
        msg += ' (truncated — import a sub-folder for the rest)'
    elif not imported and not failed:
        msg = 'No MIB files found in that folder'
    return {
        'ok':        bool(imported) or (not failed and not truncated),
        'imported':  sorted(imported),
        'failed':    failed,
        'count':     len(imported),
        'total':     total,
        'truncated': truncated,
        'message':   msg,
    }



# ── Background MIB compilation job state ─────────────────────────────────────
# Maps job_id → progress/result dict.  Written by background threads, read by
# compile_mibs_status.  CPython dict updates are GIL-safe for simple values.
_compile_jobs: dict = {}

# Maps job_id → progress/result dict for async GitHub folder imports.  Same
# GIL-safe write/poll pattern as _compile_jobs.
_github_jobs: dict = {}


class MibAdmin:
    """Upload, compile, import, list and inspect MIBs. Mixed into ``Watchful``."""

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
        #
        # And only for the FEW that are waiting.  This runs at module startup, so
        # compiling everything new meant that importing a vendor folder — hundreds of
        # files, ~2.7 s of ASN.1 parsing each — bought a panel that does not come up for
        # the best part of an hour, with nothing on screen to say what it is doing. Past
        # the limit they stay raw until the MIB manager is told to compile them.
        _pending = _mib_resolver.pending_raw_mibs(raw_dir, compiled_dir)
        if not _pending:
            compile_result = {'ok': True, 'compiled': False}
        elif len(_pending) > _mib_resolver.AUTO_COMPILE_LIMIT:
            compile_result = {'ok': True, 'compiled': False}
            self._debug(
                f'SNMP: {len(_pending)} raw MIB file(s) are not compiled — too many to do '
                f'at startup, compile them from the MIB manager (raw={raw_dir})',
                DebugLevel.info,
            )
        else:
            compile_result = _mib_resolver.compile_raw_mibs(
                raw_dir, compiled_dir, mibs_filter=_pending)

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
            'known_repos':     _KNOWN_MIB_REPOS,
            'mib_repos':       cls._repo_templates(cfg),
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
        return _mib_resolver.compile_raw_mibs(
            raw_dir, compiled_dir, http_templates=cls._repo_templates(cfg))

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
        _cancel = threading.Event()
        _compile_jobs[job_id] = {
            'done': False, 'phase': 'compiling', 'total': len(raw_mibs), 'completed': 0,
            'current': None, 'result_ok': None, 'compiled': False,
            'partial': False, 'failed': [], 'message': '', 'cancelled': False,
            '_cancel': _cancel,
        }

        def _progress_cb(current, completed, _total):
            _compile_jobs[job_id]['current']   = current
            _compile_jobs[job_id]['completed'] = completed

        _idx_extra = [d.strip() for d in str(cfg.get('mib_dirs') or '').split(',') if d.strip()]
        _repo_tpls = cls._repo_templates(cfg)

        def _run():
            _mib_resolver.invalidate_cache()
            result = _mib_resolver.compile_raw_mibs_progressive(
                raw_dir, compiled_dir, _progress_cb, mibs_filter=mibs_filter,
                http_templates=_repo_tpls, should_cancel=_cancel.is_set,
            )
            # Rebuild the OID index so newly compiled symbols resolve immediately
            # (otherwise names only appear after the next discover()), and the
            # browser symbol catalog so the first MIB Browser open is instant.
            # This is the "indexing" phase — reported so the progress bar can
            # show it instead of looking like the compile is still running.
            # Skip indexing when cancelled (the user wants it to stop now).
            if result.get('compiled') and not _cancel.is_set():
                _compile_jobs[job_id]['phase'] = 'indexing'
                _compile_jobs[job_id]['current'] = None
                try:
                    _mib_resolver.build_oid_index(var_dir, _idx_extra)
                except Exception:  # pylint: disable=broad-except
                    pass
                try:
                    _mib_catalog.build_catalog(var_dir, _idx_extra)
                except Exception:  # pylint: disable=broad-except
                    pass
            _compile_jobs[job_id].update({
                'done':      True,
                'result_ok': result.get('ok', False),
                'compiled':  result.get('compiled', False),
                'partial':   result.get('partial', False),
                'failed':    result.get('failed', []),
                'message':   result.get('message', ''),
                'cancelled': result.get('cancelled', False),
                'current':   None,
                'completed': _compile_jobs[job_id].get('completed', 0),
            })

        threading.Thread(target=_run, daemon=True).start()
        return {'ok': True, 'job_id': job_id, 'total': len(raw_mibs), 'done': False}

    @classmethod
    def compile_mibs_cancel(cls, config: dict | None = None) -> dict:
        """Request cancellation of a running compile job.

        Sets the job's cancel flag; the background thread stops between batches
        (a single pysmi compile() call can't be interrupted), so a few more MIBs
        may finish before it halts.  Returns ok even if the job already ended.
        """
        cfg    = config or {}
        job_id = str(cfg.get('job_id') or '').strip()
        job    = _compile_jobs.get(job_id)
        if job and isinstance(job.get('_cancel'), threading.Event):
            job['_cancel'].set()
            return {'ok': True, 'cancelling': True}
        return {'ok': True, 'cancelling': False}

    @classmethod
    def compile_mibs_status(cls, config: dict | None = None) -> dict:
        """Poll the status of an async compilation job started by compile_mibs_start."""
        cfg    = config or {}
        job_id = str(cfg.get('job_id') or '').strip()
        if job_id not in _compile_jobs:
            return {'ok': False, 'message': 'Job not found or already collected'}
        job = dict(_compile_jobs[job_id])   # snapshot
        job.pop('_cancel', None)            # threading.Event — not JSON-serialisable
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
        # Deleting a compiled MIB leaves the symbol catalog stale (removal does
        # not make the remaining files newer, so mtime-based staleness won't
        # catch it).  DISCARD it (one file unlink) rather than rebuilding here —
        # rebuilding on every deletion makes bulk-delete extremely slow.  The
        # next MIB Browser open rebuilds the catalog once, lazily.
        if kind == 'compiled':
            _mib_catalog.discard(var_dir)
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
        try:
            _mib_catalog.build_catalog(var_dir, extra)
        except Exception:  # pylint: disable=broad-except
            pass
        return {'ok': True, 'count': count}

    @classmethod
    def get_all_symbols(cls, config: dict | None = None) -> dict:
        """Return a flat list of all OID symbols from every compiled MIB.

        Served from the persisted SQLite catalog (``snmp_mibs/mib_catalog.db``),
        which is (re)built only when stale.  This avoids re-loading every pysnmp
        module with ``loadTexts=True`` on every browser open — the old behaviour
        that scaled poorly with the number of compiled MIBs.  See mib_catalog.py.
        """
        cfg = config or {}
        if not _HAS_PYSNMP:
            return {'ok': False, 'message': 'pysnmp not available'}

        var_dir = cfg.get('__var_dir__', '')
        if not var_dir:
            return {'ok': True, 'symbols': []}
        extra_dirs = [
            d.strip() for d in str(cfg.get('mib_dirs', '') or '').split(',') if d.strip()
        ]
        compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
        if _mib_catalog.catalog_needs_rebuild(var_dir, compiled_dir):
            _mib_catalog.build_catalog(var_dir, extra_dirs)
        return {'ok': True, 'symbols': _mib_catalog.read_catalog(var_dir)}

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

        # SSRF guard: block non-HTTP(S) schemes and link-local/metadata targets.
        from lib.security.net_guard import validate_external_url  # noqa: PLC0415
        _reason = validate_external_url(url)
        if _reason:
            return {'ok': False, 'message': f'Blocked: {_reason}'}

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

    @staticmethod
    def _repo_templates(cfg: dict) -> list:
        """Parse the ``mib_repos`` config (newline/comma separated raw templates)."""
        raw = str((cfg or {}).get('mib_repos') or '').strip()
        return [t.strip() for t in re.split(r'[\n,]+', raw) if t.strip()]

    @classmethod
    def import_mib_from_github(cls, config: dict | None = None) -> dict:
        """Import every MIB file from a GitHub repository folder into raw/
        (synchronous).  See :func:`_run_github_import` for the BFS details."""
        cfg     = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        url     = str(cfg.get('url') or '').strip()
        recursive = _truthy_import(cfg.get('recursive', True))
        if not var_dir:
            return {'ok': False, 'message': 'var_dir not available'}
        return _run_github_import(var_dir, url, recursive)

    @classmethod
    def import_mib_from_github_start(cls, config: dict | None = None) -> dict:
        """Start an async GitHub folder import and return a job_id for polling.

        Mirrors compile_mibs_start: a background thread runs the BFS while the
        front-end polls import_mib_from_github_status for the running file count.
        """
        cfg     = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        url     = str(cfg.get('url') or '').strip()
        recursive = _truthy_import(cfg.get('recursive', True))
        if not var_dir:
            return {'ok': False, 'message': 'var_dir not available'}
        if not _parse_github_folder(url):
            return {'ok': False, 'message': 'Not a recognised GitHub folder URL'}

        job_id = uuid.uuid4().hex[:12]
        _github_jobs[job_id] = {
            'done': False, 'phase': 'downloading', 'imported': 0, 'total': 0, 'failed': 0,
            'current': None, 'truncated': False, 'message': '',
        }

        def _progress_cb(completed, total, failed, current):
            job = _github_jobs.get(job_id)
            if job is not None:
                job['imported'], job['total'] = completed, total
                job['failed'], job['current'] = failed, current

        def _run():
            result = _run_github_import(var_dir, url, recursive, _progress_cb)
            _failed = result.get('failed', [])
            _github_jobs[job_id].update({
                'done':         True,
                'result_ok':    result.get('ok', False),
                'imported':     result.get('count', 0),
                'total':        result.get('total', result.get('count', 0)),
                'failed':       len(_failed),
                # Keep the failed file names (capped) so the UI and the audit log
                # can report *which* files failed, not just how many — and WHY, which
                # is the question a name alone always leads to: "rejected" (the file
                # did not look like a MIB) and an HTTP error are different problems
                # with different answers, and re-running the import to find out costs
                # another few hundred requests against a 60/h rate limit.
                'failed_names': [str(f.get('name', '')) for f in _failed][:50],
                'failed_detail': [{'name':  str(f.get('name', '')),
                                   'error': str(f.get('error', ''))} for f in _failed][:50],
                # …and the ones that WORKED. "81 ok" answers how many; after a partial
                # import the question is which, and the alternative is listing the
                # folder by hand and diffing it against what is on disk.
                'imported_names': [str(n) for n in (result.get('imported') or [])][:200],
                'truncated':    result.get('truncated', False),
                'message':      result.get('message', ''),
                'current':      None,
            })

        threading.Thread(target=_run, daemon=True).start()
        return {'ok': True, 'job_id': job_id, 'done': False}

    @classmethod
    def import_mib_from_github_status(cls, config: dict | None = None) -> dict:
        """Poll the status of an async GitHub import started by *_start."""
        cfg    = config or {}
        job_id = str(cfg.get('job_id') or '').strip()
        if job_id not in _github_jobs:
            return {'ok': False, 'message': 'Job not found or already collected'}
        job = dict(_github_jobs[job_id])   # snapshot
        if job.get('done'):
            del _github_jobs[job_id]       # cleanup on first done-read
        else:
            job.pop('result_ok', None)
        return {'ok': True, **job}
