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
import difflib
import glob
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import uuid
import zipfile

import importlib.util as _importlib_util

from lib import APP_NAME
from lib.debug import DebugLevel
from . import mib_resolver as _mib_resolver
from . import mib_catalog as _mib_catalog
from . import mib_versions as _mib_versions
from . import mib_lint as _mib_lint
from .client import _HAS_PYSNMP

# Optional dependency: pysmi is needed to COMPILE raw ASN.1, not to read an already
# compiled MIB - which is why it is a partial dependency and not a missing one.
_HAS_PYSMI = _importlib_util.find_spec('pysmi') is not None

# Bounds on the compile-error store. One parser message is a line; these are the caps that
# keep a pathological MIB (or a folder of two thousand) from turning a diagnostic aid into a
# file worth worrying about.
# The note on a version an import wrote over an edit. It is the sentence somebody
# reads three weeks later, wondering where their fix went.
_NOTE_IMPORTED = 'replaced by an import'

_MAX_ERROR_CHARS = 2000
_MAX_ERROR_ENTRIES = 1000

# A diff is read on screen, so it is bounded like something read on screen. Three lines of
# context is what makes a one-line change legible without turning the whole file into the
# answer.
_DIFF_CONTEXT = 3
_DIFF_MAX_LINES = 4000
# What the not-a-version side is called. A label, not a version number, because it is the
# only side that can change under you while you look at it.
_CURRENT_LABEL = 'current'

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


# A directory segment inside the raw tree: what a repository or an archive is allowed to
# create. Deliberately narrower than a filename — no dots at all, so `..` cannot be spelled
# even before _confined_path gets a chance to catch it.
_SAFE_DIRNAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]*$')


def _normalized(text: str) -> str:
    """The text of a MIB, as the only thing worth comparing two copies by.

    Line endings out, because they are not content: a vendor ships CRLF, the panel writes
    what it was handed, and a byte comparison then says "different" about two files that are
    the same MIB. Everything downstream already works this way — :func:`difflib.unified_diff`
    compares ``splitlines()`` and never sees a CRLF — so a comparison that does not is one
    that reports a difference and then diffs to nothing.
    """
    return '\n'.join(str(text or '').splitlines())


def _text_of(path: str) -> str | None:
    """A MIB file as text with its line endings normalised, or ``None``."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with io.open(path, encoding='utf-8-sig', errors='replace') as fh:
            return _normalized(fh.read())
    except OSError:
        return None


# Beside the tree and not inside it: `raw/` is the library, and a bookkeeping file in it
# would be one more thing every listing has to know to skip.
_REPAIR_MARK = '.line-endings-repaired'

# Archive imports in flight, by job id. Beside `_github_jobs` and kept apart from it: they
# report different things, and one dict answering two questions is how a poll for one job
# ends up reading the other one's numbers.
_archive_jobs: dict = {}

# The content hash of a raw MIB, cached on (mtime, size). The listing hashes every copy of
# every duplicated module on every refresh, and on a library where thirty modules arrive twice
# that is the refresh — while the answer only changes when the file does.
_SHA_CACHE: dict = {}


def _sha_of_file(path: str) -> str:
    """The hash of a file's TEXT, normalised the way :func:`_text_of` normalises it."""
    if not path:
        return ''
    try:
        st = os.stat(path)
        key = (st.st_mtime, st.st_size)
    except OSError:
        return ''
    hit = _SHA_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    text = _text_of(path)
    sha = _mib_versions.sha_of(text)[:12] if text is not None else ''
    _SHA_CACHE[path] = (key, sha)
    return sha


# The descriptors a raw MIB declares, cached on (mtime, size). Only ever asked about files
# whose module name collides, so the cost is the size of the ambiguity.
_NAMES_CACHE: dict = {}


def _declared_names(path: str) -> set:
    if not path:
        return set()
    try:
        st = os.stat(path)
        key = (st.st_mtime, st.st_size)
    except OSError:
        return set()
    hit = _NAMES_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    text = _text_of(path)
    names = _mib_lint.declared_names(text) if text is not None else set()
    _NAMES_CACHE[path] = (key, names)
    return names


def _kinship(paths: list) -> int:
    """How much of the smaller MIB the others also declare, as a percentage — or ``-1``.

    Copies of one module share their descriptors whatever else changed between vintages: an
    IF-MIB against an older IF-MIB comes out at 98%. Two MIBs that merely share a first line
    come out at 0, and the difference is not a matter of degree.

    ``-1`` when one of them declares nothing at all, because a percentage of nothing would be
    an answer where there is none.
    """
    sets = [_declared_names(p) for p in paths]
    if not sets or any(not s for s in sets):
        return -1
    common = set.intersection(*sets)
    return int(100 * len(common) / min(len(s) for s in sets))


def _unified_diff(a_text: str, a_label: str, b_text: str, b_label: str) -> dict:
    """The one place a difference is turned into a diff — versions and files alike.

    Both callers used to build this themselves, which is one derivation of the same question
    too many: the day the context or the cap changes, one of them keeps the old answer.
    """
    lines = list(difflib.unified_diff(
        a_text.splitlines(), b_text.splitlines(),
        a_label, b_label, lineterm='', n=_DIFF_CONTEXT))
    truncated = len(lines) > _DIFF_MAX_LINES
    if truncated:
        lines = lines[:_DIFF_MAX_LINES]
    return {'ok': True, 'diff': '\n'.join(lines), 'a': a_label, 'b': b_label,
            'identical': not lines, 'truncated': truncated}


def _safe_mib_relpath(name: str, kind: str = 'raw') -> str | None:
    """A relative path under the MIB directory, or ``None`` when it is not safe to use.

    Files keep the folder they came from: LibreNMS publishes one directory per vendor, and a
    vendor archive has its own layout. Flattening them puts two files called ``ENTITY-MIB`` in
    one place, where one silently overwrites the other and the panel shows a single entry —
    which is how an imported repository can leave you with a MIB that is not the one you think
    it is.

    Every segment is validated on its own, the last one as a filename, and the caller still
    passes the result through :func:`_confined_path`.
    """
    raw = str(name or '').replace('\\', '/').strip().strip('/')
    if not raw:
        return None
    parts = [p for p in raw.split('/')]
    if len(parts) > _mib_resolver.RAW_MAX_DEPTH:
        return None
    for seg in parts[:-1]:
        if seg in ('', '.', '..') or not _SAFE_DIRNAME_RE.match(seg):
            return None
    if _safe_mib_filename(parts[-1], kind) is None:
        return None
    return '/'.join(parts)


def _archive_cache_dir(var_dir: str) -> str:
    """Where a downloaded archive is kept between uses. Beside the library, not inside it."""
    return os.path.join(var_dir, 'snmp_mibs', _ARCHIVE_CACHE) if var_dir else ''


def _cache_slot(cache_dir: str, url: str):
    """``(zip_path, etag_path)`` for *url*, or ``('', '')`` with no cache."""
    if not cache_dir:
        return '', ''
    key = hashlib.sha1(url.encode('utf-8', 'replace')).hexdigest()[:16]
    return os.path.join(cache_dir, key + '.zip'), os.path.join(cache_dir, key + '.etag')


def _prune_archive_cache(cache_dir: str, keep: int = 2, max_age_days: int = 7) -> None:
    """Keep the last few archives and nothing old.

    A cached archive is 86 MB of somebody's disk; keeping every one ever downloaded is a
    cache that only grows. Two is the flow this exists for — compare, then import — with room
    for a second source in between.
    """
    if not cache_dir or not os.path.isdir(cache_dir):
        return
    try:
        names = os.listdir(cache_dir)
        # A download that died half way leaves its `.part`. Anything older than an hour is
        # not somebody's download in flight, it is somebody's crash.
        stale = time.time() - 3600
        for f in names:
            p = os.path.join(cache_dir, f)
            if f.endswith('.part') and os.path.getmtime(p) < stale:
                _rm_quiet(p)
        zips = [os.path.join(cache_dir, f) for f in names if f.endswith('.zip')]
        zips.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        cutoff = time.time() - max_age_days * 86400
        for i, p in enumerate(zips):
            if i < keep and os.path.getmtime(p) >= cutoff:
                continue
            _rm_quiet(p)
            _rm_quiet(p[:-4] + '.etag')
    except OSError:
        pass


def _download_archive(url: str, max_bytes: int, on_progress=None, cache_dir: str = '',
                      fresh: bool = False):
    """Stream *url* to a file. Returns ``(path, '')`` or ``(None, message)``.

    **Kept and revalidated.** Comparing an archive and then importing it is the same 86 MB
    twice, and pressing Compare first is exactly what the panel asks you to do — the second
    download answers a question the first one already answered. So the file is kept beside the
    library with the ETag the server gave it, and every use asks the server whether that copy
    is still current: a 304 costs one request and no megabytes, and a server that does not do
    conditional requests simply sends the file again, which is what happened before.

    *fresh* asks for the file itself and not for an opinion about it: no conditional
    request, and whatever comes back replaces what was there. Reusing is the right default —
    the server is asked every time and a changed archive downloads by itself — but "ask
    again" and "fetch it again" are different requests, and only one of them can be made by
    pressing the same button twice.

    Returns ``(path, message, from_cache)``. The path may be the cached copy — the caller
    prunes the cache, it does not delete what it was handed — and *from_cache* is what lets
    the report say why it was instant.

    To a file and not to memory, because the thing this exists for is a whole-repository zip
    of tens of megabytes — and because :class:`zipfile.ZipFile` wants to seek, which is what a
    file gives it for free.

    *on_progress* is called with ``(bytes_so_far, bytes_total)`` once per chunk. It is the
    only thing that can be said honestly while this runs: 86 MB over somebody's line is a
    minute of a button that otherwise looks stuck. ``bytes_total`` is 0 when the server sends
    no ``Content-Length`` — a bar with no end is still a bar that is moving.
    """
    import tempfile           # noqa: PLC0415
    import urllib.error       # noqa: PLC0415
    import urllib.request     # noqa: PLC0415

    cached, etag_path = _cache_slot(cache_dir, url)
    etag = ''
    if fresh:
        _rm_quiet(cached)
        _rm_quiet(etag_path)
    elif cached and os.path.isfile(cached) and os.path.isfile(etag_path):
        try:
            with io.open(etag_path, encoding='utf-8') as fh:
                etag = fh.read().strip()
        except OSError:
            etag = ''

    # IN the cache directory, and this is not a detail: `os.replace` cannot move a file
    # across volumes on Windows, and the system temp is on C: while somebody's data directory
    # is on D:. Every download went to C:, every rename failed, the failure was swallowed as
    # "then keep the temp file" — so nothing was ever cached, every use downloaded again, and
    # each one left 86 MB behind. Born on the destination volume, the rename is a rename.
    if cache_dir:
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            cache_dir, cached, etag_path = '', '', ''
    fd, path = tempfile.mkstemp(prefix='ss-mib-archive-', suffix='.part',
                                dir=cache_dir or None)
    total = 0
    _last_etag = ''
    try:
        headers = {'User-Agent': APP_NAME}
        if etag:
            headers['If-None-Match'] = etag
        req = urllib.request.Request(url, headers=headers)
        # The file object FIRST, so the descriptor is adopted before anything can raise.
        # Opened inside the same `with` as the request, it is never adopted at all when the
        # request throws — and an unclosed handle on Windows is a file that cannot be
        # deleted, which is how a 304 (an exception, in urllib) left its empty `.part`.
        with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(req, timeout=180) as r:
            # Defensively: a response without headers is not a reason to lose the
            # download, it is a reason to have no total.
            try:
                _h = getattr(r, 'headers', None) or {}
                expected = int(_h.get('Content-Length') or 0)
                _last_etag = _h.get('ETag') or ''
            except (AttributeError, TypeError, ValueError):
                expected = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    # Out of the loop rather than out of the function: the temp file is still
                    # open here, and on Windows a delete under an open handle fails — which
                    # is how a refused download used to leave its half behind.
                    break
                out.write(chunk)
                if on_progress is not None:
                    on_progress(total, expected)
    except urllib.error.HTTPError as exc:
        _rm_quiet(path)
        # 304: the copy on disk IS the answer. Anything else is a failure like any other.
        if exc.code == 304 and cached and os.path.isfile(cached):
            return cached, '', True
        return None, str(exc), False
    except Exception as exc:   # pylint: disable=broad-except
        _rm_quiet(path)
        return None, str(exc), False
    if total > max_bytes:
        _rm_quiet(path)
        return None, 'Archive too large', False
    if not cached:
        return path, '', False
    # Into the cache with the tag that identifies it, so the next use can ask instead of
    # downloading. A cache that cannot be revalidated is a guess with a disk cost.
    try:
        os.replace(path, cached)
        new_etag = str(_last_etag or '').strip()
        if new_etag:
            with io.open(etag_path, 'w', encoding='utf-8') as fh:
                fh.write(new_etag)
        else:
            _rm_quiet(etag_path)
        return cached, '', False
    except OSError:
        # Could not be filed. The file is still the answer to THIS call — the caller deletes
        # it, having been handed something that is not in the cache.
        return path, '', False


# How much of a file is enough to see what it is. A licence banner is fifty lines; a
# readme says what it is in the first three.
_PREVIEW_LINES = 80
_PREVIEW_BYTES = 8192


def _head_lines(text: str, lines: int = _PREVIEW_LINES) -> str:
    """The first *lines* of *text*, for a row that has to justify itself."""
    return '\n'.join(str(text or '').splitlines()[:lines])


def _member_head(zf, member) -> str:
    """The start of an archive member WITHOUT reading the member.

    The one case that needs this is the file refused for being too large: reading it whole is
    exactly what was refused, and eight kilobytes of it is what says whether the refusal was
    right.
    """
    try:
        with zf.open(member) as fh:
            return _head_lines(fh.read(_PREVIEW_BYTES).decode('utf-8', errors='replace'))
    except Exception:  # pylint: disable=broad-except
        return ''


def _rm_quiet(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _import_via_zip(cls_admin, cfg: dict, url: str) -> dict | None:
    """Finish a GitHub folder import from a ZIP, or ``None`` when there is none to use.

    ``codeload`` is not the API: one request, no allowance to spend, which is the way past a
    limit that a folder-per-request walk cannot get past. It costs a whole-repository download
    to pick one folder out of — 86 MB for LibreNMS — which is why this runs after the API has
    already said no, and not before.

    Two things have to be decided, and they come from different places. WHICH archive is the
    source's to declare (``archive`` in its JSON): it may publish a release tarball, another
    branch or a mirror, and a codeload URL built from the folder URL is a guess that happens
    to be right for a repository nobody described. WHICH FOLDER of it is the request's: asked
    for ``mibs/synology``, importing all of ``mibs`` would be importing four thousand files
    somebody did not ask for.
    """
    src = _import_source(url)
    declared = str(src.get('archive') or '').strip()
    zip_url, path = _github_zip(url)
    if declared:
        # The part of the request BELOW what the source describes, appended to the folder the
        # source says its archive keeps MIBs in. Same answer for the folder itself (no tail),
        # and the right one for a vendor inside it.
        base = str(_import_source_path(src) or '')
        tail = path[len(base):].strip('/') if base and path.startswith(base) else ''
        only = str(src.get('archive_only') or path or '')
        only = f'{only}/{tail}'.strip('/') if tail else only
        return cls_admin.import_mib_archive({**cfg, 'url': declared, 'only': only,
                                             'subdir': _import_subdir(url), 'dry_run': False})
    if not zip_url:
        return None
    return cls_admin.import_mib_archive({**cfg, 'url': zip_url, 'only': path,
                                         'subdir': _import_subdir(url), 'dry_run': False})


def _import_source_path(src: dict) -> str:
    """The repository path a source's ``folder`` points at, or ``''``."""
    parsed = _parse_github_folder(str(src.get('folder') or ''))
    return str(parsed[3] or '').strip('/') if parsed else ''


def _github_zip(url: str) -> tuple:
    """A GitHub folder URL as ``(zip url, path inside the repo)``, or ``(None, '')``.

    ``codeload`` serves the repository as one file and is not the API: it costs no request
    against the sixty an hour, which is the whole reason to prefer it for a repository whose
    folders would cost four hundred.
    """
    parsed = _parse_github_folder(url)
    if not parsed:
        return None, ''
    owner, repo, branch, path = parsed
    branch = branch or 'master'
    return (f'https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}',
            str(path or '').strip('/'))


def _member_inner(member, strip: str = '') -> str:
    """A zip member's path with the wrapper folder removed, using forward slashes."""
    inner = str(getattr(member, 'filename', '')).replace('\\', '/').strip('/')
    if strip and (inner == strip or inner.startswith(strip + '/')):
        inner = inner[len(strip):].strip('/')
    return inner


def _archive_wrapper(members) -> str:
    """The single top-level directory every member sits under, or ``''``.

    Archives are usually packed with one wrapper folder — Synology's is called "MIB files" —
    and it belongs to the packaging, not to the layout. Keeping it buries every MIB one level
    deeper for no reason, and the day the vendor renames it, the next import lands beside the
    old one instead of updating it.

    Only when ALL of them share it: a mixed archive has real structure and it is kept whole.
    """
    tops = set()
    for m in members:
        head = str(getattr(m, 'filename', '')).replace('\\', '/').strip('/').split('/')
        if len(head) < 2:
            return ''            # something sits at the root: there is no wrapper
        tops.add(head[0])
    return tops.pop() if len(tops) == 1 else ''


def _safe_archive_subdir(name: str) -> str:
    """The one folder an archive import unpacks into, or ``''``.

    Named after the source rather than derived from the archive, because an archive's top
    directory is whatever the vendor felt like calling it that year — Synology's is literally
    "MIB files" — and a folder that renames itself between releases is a second copy of every
    MIB rather than an update of the first.
    """
    slug = re.sub(r'[^A-Za-z0-9._-]+', '_', str(name or '').strip()).strip('_.')
    return slug if slug and _SAFE_DIRNAME_RE.match(slug) else ''


def _confined_path(base_dir: str, *parts: str) -> str | None:
    """Return the path of ``os.path.join(base_dir, *parts)`` only if it is strictly inside
    *base_dir*; otherwise ``None``.

    Belt-and-suspenders guard against anything that slips past the name check — a symlink
    pointing out of the directory, above all.

    It used to resolve BOTH sides with ``pathlib.Path.resolve()``, and that made the answer
    depend on what happened to exist on disk at that instant: on Windows ``resolve()`` returns
    an extended-length prefix (backslash backslash question-mark backslash) for a path
    it can open and the plain form for one it cannot, so ``target.startswith(base)`` was
    false whenever the two disagreed. With sixteen
    threads importing into a folder they are also creating, files were refused as "rejected" —
    a different handful every run, three to six out of seventy-nine, with nothing in the
    message to say the path was fine and the comparison was not.

    So: the base is resolved once (it is ours and it is stable), the target is joined onto it
    and normalised **lexically**, and the target is only resolved when it EXISTS — which is
    the only case where a symlink has anywhere to point.
    """
    base   = os.path.realpath(base_dir)
    target = os.path.normpath(os.path.join(base, *parts))
    nbase, ntarget = os.path.normcase(base), os.path.normcase(target)
    if ntarget != nbase and not ntarget.startswith(nbase + os.sep):
        return None
    if os.path.exists(target):
        nreal = os.path.normcase(os.path.realpath(target))
        if nreal != nbase and not nreal.startswith(nbase + os.sep):
            return None
    return target


# ── GitHub MIB repositories ───────────────────────────────────────────────────
# Curated repos that publish MIBs.  `folder` is a GitHub tree URL imported via
# the Contents API; `dep_template` is a raw URL with the @mib@ placeholder used
# as an HTTP source for resolving missing dependency MIBs while compiling.
_LOG = logging.getLogger(__name__)

# Directory holding one JSON file per known public MIB repository.  Drop a new
# file there to add a source — see mib_sources/README.md.
_MIB_SOURCES_DIR = os.path.join(os.path.dirname(__file__), 'mib_sources')

# A vendor publishes its MIBs as one archive, and every MIB inside carries the date it was
# last changed in its own MODULE-IDENTITY. That is what makes an update comparable: not the
# file's timestamp (which says when it was downloaded) and not its size, but the version the
# author wrote into it.
_LAST_UPDATED_RE = re.compile(r'LAST-UPDATED\s+"([0-9]{10,13}Z)"', re.IGNORECASE)

# What one archive may unpack. A zip is somebody else's file, and these numbers are what stop
# it from being a way to fill a disk.
#
# The byte cap is for a DOWNLOAD, not for memory: an archive is streamed to a temporary file
# and read from there. A whole-repository zip is the case that needs it — LibreNMS' is 86 MB,
# where its MIBs are a few — and holding one in memory to pick a folder out of it is the kind
# of thing that works on a laptop and kills a container.
#
# The file cap counts what is IMPORTED, applied after the folder filter: a repository zip
# carries twenty thousand files that have nothing to do with MIBs, and counting those against
# a ceiling meant for the import would truncate it before reaching them.
_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
# No ceiling on how many files an archive may hold. There was one — two thousand — and
# LibreNMS ships 4830 MIBs, so the comparison answered about less than half of the archive
# and said so in a footnote. A ceiling that turns the main use of a feature into a footnote is
# not protecting anything: the download is already bounded by _MAX_ARCHIVE_BYTES, the work
# runs in the background with progress and a Stop, and the reader wanted the whole answer.
#
# Nor on how big one file may be. That one refused ALAXALA's AX-SMC-MIB — 11.2 MiB and a
# perfectly real MIB — for being what it is. What remains is not a policy about MIBs but a
# memory guard: nothing is read into memory that is bigger than the archive it arrived in.
_MAX_MEMBER_BYTES = _MAX_ARCHIVE_BYTES
# How many rows of a comparison carry their diff. Enough to read a report; not so many that
# an archive whose every file differs answers with a megabyte of diff nobody opened.
_MAX_DIFFS = 60
# Where downloaded archives wait between a comparison and the import that follows it.
_ARCHIVE_CACHE = '.archive-cache'


def _mib_last_updated(text: str) -> str:
    """The ``LAST-UPDATED`` stamp of a MIB, or ``''``.

    ``"201309110000Z"`` — sortable as a string, which is the whole reason to compare it that
    way rather than parsing it into a date nobody needs.
    """
    m = _LAST_UPDATED_RE.search(text or '')
    return m.group(1).upper() if m else ''


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
        archive = str(data.get('archive') or '').strip()
        tpls    = data.get('dep_templates')
        if not isinstance(tpls, list):
            tpls = [tpls] if tpls else []
        tpls = [str(t).strip() for t in tpls if str(t).strip()]
        # A source is a folder, an archive, or both. Vendors publish one file; projects that
        # host MIBs publish a directory — and the same vendor can be both, which is the case
        # worth supporting rather than choosing between.
        if folder and _parse_github_folder(folder) is None:
            _LOG.warning('Skipping MIB source %s: folder is not a GitHub URL',
                         os.path.basename(path))
            continue
        if not name or not (folder or archive):
            _LOG.warning('Skipping invalid MIB source %s (needs name + folder or archive)',
                         os.path.basename(path))
            continue
        if folder and not tpls:
            _LOG.warning('Skipping MIB source %s: a folder needs dep_templates',
                         os.path.basename(path))
            continue
        # What this repository keeps beside its MIBs. Net-SNMP has `nodemap` and `rfclist`;
        # the next source will have something else, and neither is anything this module should
        # have been told about in its own source code.
        skips = data.get('skip_names')
        if not isinstance(skips, list):
            skips = [skips] if skips else []
        entry = {'name': name, 'dep_templates': tpls,
                 'order': data.get('order', 1_000_000),
                 'skip_names': sorted({str(x).strip().lower() for x in skips if str(x).strip()}),
                 # Where this source lands under raw/: named after the SOURCE, not after
                 # whatever the vendor called the folder inside it that year, and not after
                 # the repository, which is a name GitHub happens to have. It used to be set
                 # for archives only — so every folder import emptied itself into the root,
                 # where ninety Net-SNMP files sit with no vendor beside them and the next
                 # source that ships an ENTITY-MIB of its own overwrites this one's.
                 'subdir': _safe_archive_subdir(data.get('subdir') or name)}
        if folder:
            entry['folder'] = folder
        if archive:
            entry['archive'] = archive
            # Which folder INSIDE the archive holds the MIBs, for an archive that is not a
            # MIB archive: a repository zip carries the whole project and the MIBs are under
            # one path of it. Declared here because every repository lays itself out
            # differently, and a name written into this module would be a name it has no
            # business knowing.
            _only = str(data.get('archive_only') or '').strip().strip('/')
            if _only:
                entry['archive_only'] = _only
        repos.append(entry)
    repos.sort(key=lambda r: (r.get('order', 1_000_000), r['name']))
    for r in repos:
        r.pop('order', None)
    return repos


# GitHub folder-URL parsers.
_GH_TREE_RE = re.compile(r'^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.+?))?/?$')
_GH_ROOT_RE = re.compile(r'^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$')

# The furniture EVERY repository has, whoever publishes it: a readme, a licence, a makefile.
# This is knowledge about git, not about any vendor — which is why it lives here and the names
# a particular repository happens to keep beside its MIBs do not. Those go in that source's own
# JSON (`skip_names`), because the module has no business knowing that net-snmp ships a file
# called `nodemap`, and the next source somebody adds will keep something else entirely.
#
# All of it is only an optimisation: `_is_mib_source` reads the file and is what decides. What
# a name buys is an HTTP request not made, against an anonymous rate limit of sixty an hour.
# Matched case-insensitively, extension-less only.
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


# What a MIB says about itself. Every other rule here is a guess about a NAME; this one
# reads the file — and a name is exactly what the offenders are good at: net-snmp's `mibs/`
# folder ships `nodemap`, `rfclist`, `ianalist`, `mibfetch` and `smistrip`, none of which is a
# MIB and all of which look like one from outside.
#
# Asked of the parser that already answers it, rather than with a second regex of its own.
# The second regex was wrong in a way only real files show: it read the RAW text, so
# `NAME`, a comment, and then `DEFINITIONS ::= BEGIN` on the next line did not match — and
# ASN.1 does not care where a comment falls between two tokens. LibreNMS ships several
# written that way (FROGFOOT-RESOURCES-MIB, ADIC-INTELLIGENT-STORAGE-MIB), and every import
# quietly refused them as "not a MIB" while the panel's own module-name reader, which blanks
# comments first, read their names perfectly well.


def _is_mib_source(text: str) -> bool:
    """Does *text* define a MIB module?

    Applied AFTER the bytes are in hand, wherever they came from — a folder, a URL, an
    archive — because the answer does not depend on how they arrived, and a check written
    once per importer is a check that is right in two of them.
    """
    return bool(_mib_lint.module_name(text or ''))


def _looks_like_mib_file(name: str, skip: frozenset = frozenset()) -> bool:
    """Heuristic: is *name* worth fetching?

    *skip* is the extra names the SOURCE declared — what that repository keeps beside its
    MIBs, which only that repository knows.
    """
    ext = os.path.splitext(name)[1].lower()
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    if stem in _GH_SKIP_NAMES or stem in skip:
        return False
    if ext in ('.mib', '.txt', '.my'):
        return True
    if ext == '':   # extension-less repos (e.g. LibreNMS) name files as the MIB
        return bool(_SAFE_FILENAME_RE.match(name))
    return False


def _truthy_import(value) -> bool:
    """Coerce a config value (str/bool) to bool, defaulting truthy."""
    return str(value).strip().lower() not in ('false', '0', 'no', 'off', 'none', '')


# Known public MIB repositories, loaded from mib_sources/*.json at import
# (defined after _parse_github_folder, which the loader uses for validation).
_KNOWN_MIB_REPOS: list[dict] = _load_mib_sources()


def _import_source(url: str) -> dict:
    """The declared source *url* belongs to, or ``{}`` for a URL somebody typed."""
    u = (url or '').strip().rstrip('/')
    for src in _KNOWN_MIB_REPOS:
        folder = str(src.get('folder') or '').rstrip('/')
        if folder and (u == folder or u.startswith(folder + '/')):
            return src
    return {}


def _import_skip_names(url: str) -> frozenset:
    """The names *url*'s source says are not MIBs. Empty for anything undeclared — a repo
    nobody described gets the universal list and the content check, which is enough."""
    return frozenset(_import_source(url).get('skip_names') or ())


def _import_subdir(url: str) -> str:
    """Which folder under ``raw/`` an import of *url* belongs in.

    A declared source says so (``subdir`` in its JSON); anything else is named after the
    repository it came from. Never the root: an import is a batch from one place, and a root
    holding four vendors' worth of files is one where the next ENTITY-MIB overwrites the last.
    """
    declared = _safe_archive_subdir(str(_import_source(url).get('subdir') or ''))
    if declared:
        return declared
    parsed = _parse_github_folder(url)
    return _safe_archive_subdir(parsed[1]) if parsed else ''


def _rate_limit_reset(exc) -> str | None:
    """``''`` or a local time when *exc* is GitHub's rate limit, ``None`` when it is not.

    A 403 alone is not it — a private repository answers 403 too — so what decides is the
    header GitHub sends with the refusal. The time comes back as text because it is going
    into a message, and the only thing anybody does with it is wait until then.
    """
    hdrs = getattr(exc, 'headers', None)
    if getattr(exc, 'code', None) not in (403, 429) or hdrs is None:
        return None
    if str(hdrs.get('X-RateLimit-Remaining', '')).strip() != '0':
        return None
    try:
        return time.strftime('%H:%M', time.localtime(int(hdrs.get('X-RateLimit-Reset'))))
    except (TypeError, ValueError):
        return ''


def _run_github_import(var_dir: str, url: str, recursive: bool, progress_cb=None,
                       subdir: str = '', skip_names: frozenset = frozenset(),
                       on_overwrite=None, token: str = '') -> dict:
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

    API calls and file count are capped, and the cap depends on *token*: unauthenticated
    GitHub allows sixty requests an hour, which one folder per request spends on the first
    forty sub-folders of a repository like LibreNMS — it has some four hundred. With a token
    the allowance is five thousand an hour and the cap moves with it. A ``truncated`` flag
    signals when a cap was hit, and ``rate_limited`` when GitHub said no.
    """
    import urllib.request  # noqa: PLC0415
    from lib.security.net_guard import validate_external_url  # noqa: PLC0415

    parsed = _parse_github_folder(url)
    if not parsed:
        return {'ok': False, 'message': 'Not a recognised GitHub folder URL'}
    owner, repo, branch, path = parsed

    raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
    os.makedirs(raw_dir, exist_ok=True)

    # Forty of the sixty an anonymous hour allows, leaving room for the downloads that
    # follow; five hundred when a token lifts the allowance to five thousand.
    _MAX_API_CALLS = 500 if token else 40
    _MAX_FILES, _MAX_DEPTH = 1000, 5
    rate_limited = ''
    imported: list = []
    failed:   list = []
    skipped:  list = []      # downloaded, read, and not a MIB after all
    truncated = False

    def _get_json(p):
        ref = f'?ref={branch}' if branch else ''
        u = f'https://api.github.com/repos/{owner}/{repo}/contents/{p}{ref}'
        if validate_external_url(u):
            return None
        _h = {'User-Agent': APP_NAME, 'Accept': 'application/vnd.github+json'}
        if token:
            _h['Authorization'] = f'Bearer {token}'
        req = urllib.request.Request(u, headers=_h)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def _save(dl_url, name):
        # Under the source's own folder. Net-SNMP alone is ninety files; emptied into the
        # root they are ninety rows with no vendor beside them, and the next import that
        # ships an ENTITY-MIB of its own silently overwrites this one's.
        rel = _safe_mib_relpath(f'{subdir}/{name}' if subdir else name, 'raw')
        if not rel or validate_external_url(dl_url):
            return False
        dest = _confined_path(raw_dir, *rel.split('/'))
        if not dest:
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        _h = {'User-Agent': APP_NAME}
        if token:
            _h['Authorization'] = f'Bearer {token}'
        req = urllib.request.Request(dl_url, headers=_h)
        with urllib.request.urlopen(req, timeout=20) as r:
            content = r.read().decode('utf-8', errors='replace')
        # The name got it this far; the content decides. A file that was never a MIB is not
        # a failed import — nothing went wrong, it simply was not one — so it is skipped and
        # not counted against the run.
        if not _is_mib_source(content):
            return 'skip'
        # An unchanged file is not rewritten. Whether a MIB needs compiling is decided by
        # comparing its mtime against the compiled module, so rewriting identical bytes
        # marks it stale and buys a re-parse — ~2.7 s of ASN.1 each, for a file that did
        # not change. Re-importing a folder to pick up a handful of new MIBs invalidated
        # every one already compiled from it, which is how a second import came to cost as
        # much as the first.
        # …compared as CONTENT and not as bytes (see :func:`_normalized`). Read with
        # errors='replace' because this is a COMPARISON, not a read: a file with a stray byte
        # would otherwise raise UnicodeDecodeError — which is not an OSError, so it escaped
        # this guard and failed the import of a file that was merely unusual.
        if _text_of(dest) == _normalized(content):
            return True
        # About to replace a file somebody may have corrected by hand. The import still
        # wins — it is what was asked for, and a vendor's newer MIB is usually the point —
        # but an edit that disappears without a word is an edit you find out about the next
        # time the same compile error comes back.
        if on_overwrite is not None:
            try:
                on_overwrite(rel, content)
            except Exception:  # pylint: disable=broad-except
                pass
        # newline='' or Windows translates every '\n' on the way out: a CRLF
        # file arrives as '\r\n' and would be stored as '\r\r\n'.
        with open(dest, 'w', encoding='utf-8', newline='') as fh:
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
            # Out of allowance: every call after this one fails the same way, and walking the
            # queue to prove it turns one condition into twenty-five identical rows of
            # "rate limit exceeded" — a screen that reads like twenty-five broken folders.
            _reset = _rate_limit_reset(exc)
            if _reset is not None:
                rate_limited = _reset
                truncated = True
                break
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
            if etype != 'file' or not _looks_like_mib_file(name, skip_names):
                continue
            dl = e.get('download_url')
            if dl:
                # The path this file has INSIDE the imported folder, so the tree survives the
                # import. `path` is the repo-relative root the caller asked for.
                epath = str(e.get('path') or '')
                rel = epath[len(path):].lstrip('/') if path and epath.startswith(path) else name
                to_download.append((rel or name, dl))

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
                if ok == 'skip':
                    skipped.append(name)
                elif ok:
                    imported.append(subdir + '/' + name if subdir else name)
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
    if skipped:
        msg += f', {len(skipped)} not MIBs'
    if rate_limited != '':
        # The one thing worth saying, and what to do about it. "Truncated — import a
        # sub-folder for the rest" is advice for a cap WE chose; this is GitHub refusing, and
        # importing a sub-folder next costs another request against an allowance that is
        # already gone.
        msg += (' — GitHub rate limit reached'
                + (f' (resets at {rate_limited})' if rate_limited else '')
                + ('' if token else '. Add a GitHub token to raise it from 60 to 5000 an hour'))
    elif truncated:
        msg += ' (truncated — import a sub-folder for the rest)'
    elif not imported and not failed:
        msg = 'No MIB files found in that folder'
    return {
        'ok':        bool(imported) or (not failed and not truncated),
        'imported':  sorted(imported),
        'failed':    failed,
        'skipped':   sorted(skipped),
        'count':     len(imported),
        'total':     total,
        'truncated': truncated,
        'rate_limited': rate_limited != '',
        'rate_limit_reset': rate_limited or '',
        'authenticated': bool(token),
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

        # Count raw MIB files so we can warn if pysmi is missing. Recursive: an imported
        # archive or repository keeps its folders, and counting only the top level reports
        # zero for an installation whose MIBs all came from one.
        raw_files = [rel for rel, _full in _mib_resolver.iter_raw_mibs(raw_dir)]

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

    # ── Why a MIB did not compile, kept next to the MIBs ─────────────────────
    #
    # A compile of two hundred MIBs is not something anyone watches to the end, and the
    # failures are exactly what you come back for. Held only in the page, the reasons die
    # with the modal and the rows go back to reading "pending" — which is also what a MIB
    # nobody has compiled yet says, so the one state you must not confuse with anything is
    # the one that gets forgotten first. So it is written down, beside the files it is about.
    @staticmethod
    def _errors_path(var_dir: str) -> str:
        return os.path.join(var_dir, 'snmp_mibs', 'compile_errors.json') if var_dir else ''

    @classmethod
    def _read_compile_errors(cls, var_dir: str) -> dict:
        path = cls._errors_path(var_dir)
        if not path or not os.path.isfile(path):
            return {}
        try:
            with io.open(path, encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @classmethod
    def _write_compile_errors(cls, var_dir: str, data: dict) -> None:
        """Atomically, because the compile job writes this while the panel is reading it."""
        path = cls._errors_path(var_dir)
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + '.tmp'
            with io.open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, path)
        except OSError as exc:
            logging.getLogger(APP_NAME).warning('MIB compile errors not saved: %s', exc)

    @classmethod
    def _record_compile_errors(cls, var_dir: str, attempted: list, errors: dict,
                               raw_index: dict) -> None:
        """Fold one job's verdict into the store.

        A job speaks for the MIBs it covered and for no others: its entries are cleared and
        the new failures written, so compiling one row never erases what is known about the
        rest. Each failure records the source it was about — its size and mtime — because an
        error is only true of the file that produced it, and the answer to a broken MIB is
        usually a new copy of it.
        """
        if not var_dir:
            return
        store = cls._read_compile_errors(var_dir)
        for name in attempted:
            store.pop(name, None)
        for name, msg in (errors or {}).items():
            src = raw_index.get(name) or {}
            store[str(name)] = {
                'error':  str(msg)[:_MAX_ERROR_CHARS],
                'at':     int(time.time()),
                'source': src.get('name', ''),
                'size':   src.get('size', 0),
                'mtime':  src.get('mtime', 0),
            }
        # A store nobody prunes is a store that grows for ever; the newest are the ones worth
        # keeping, and anything past the cap is older than a user's memory of it anyway.
        if len(store) > _MAX_ERROR_ENTRIES:
            keep = sorted(store.items(), key=lambda kv: kv[1].get('at', 0),
                          reverse=True)[:_MAX_ERROR_ENTRIES]
            store = dict(keep)
        cls._write_compile_errors(var_dir, store)

    @staticmethod
    def _live_compile_errors(store: dict, raw_index: dict, compiled: set) -> dict:
        """The stored reasons that are still true, as ``{mib: entry}``.

        Three ways a recorded failure stops being one, and every one of them leaves a red row
        that cannot be cleared by doing the obvious thing: the MIB compiled since; its source
        was replaced (a fixed file is a different file — same name, other bytes); or the
        source is gone entirely. Pruning on READ rather than on write means a file dropped
        into the folder by hand counts too, and nothing has to notice it happening.
        """
        live = {}
        for name, entry in (store or {}).items():
            if not isinstance(entry, dict) or not entry.get('error'):
                continue
            if name in compiled:
                continue
            src = raw_index.get(name)
            if not src:
                continue
            if entry.get('size') and (int(entry.get('size') or 0) != int(src.get('size') or 0)
                                      or int(entry.get('mtime') or 0) != int(src.get('mtime') or 0)):
                continue
            live[name] = entry
        return live


    # ── Editing a MIB, and taking it back ────────────────────────────────────
    #
    # Vendors ship broken MIBs, and a correction nobody can undo is a correction nobody dares
    # make — so the history is the feature and the editor is the button. The FILE stays the
    # working copy: pysmi is handed directories and compiles what it finds in them, so an edit
    # that lived only in the database would be an edit nothing ever compiled.
    @staticmethod
    def _versions_store(cfg: dict):
        db = cfg.get('__connector__')
        return _mib_versions.MibVersionStore(db) if db is not None else None

    @staticmethod
    def _raw_path_of(var_dir: str, name: str) -> tuple:
        """Resolve a raw MIB relpath to (absolute path, module name), or (None, '').

        The module name comes from INSIDE the file — ``X-MIB DEFINITIONS ::= BEGIN`` — and
        falls back to the file's stem only when it cannot be read. That is the identity
        everything else already uses: pysmi compiles by module name, writes ``<NAME>.py``, and
        resolves every ``IMPORTS`` by name. Keyed on the file name instead, a MIB renamed or
        moved to another vendor folder lost its history — which is the one thing a history
        must not do, since renaming a file is not editing it.
        """
        rel = _safe_mib_relpath(name, 'raw')
        if not var_dir or not rel:
            return None, ''
        path = _confined_path(os.path.join(var_dir, 'snmp_mibs', 'raw'), *rel.split('/'))
        if not path:
            return None, ''
        stem = os.path.splitext(os.path.basename(rel))[0]
        try:
            with io.open(path, encoding='utf-8-sig', errors='replace') as fh:
                declared = _mib_lint.module_name(fh.read())
        except OSError:
            declared = ''
        return path, (declared or stem)

    @classmethod
    def _write_source(cls, cfg: dict, name: str, content: str, note: str) -> dict:
        """Write *content* to the raw MIB and record the version. The one write path.

        Both saving and restoring come through here, because they are the same act: the file
        becomes something, and the history says what it was. Restoring writes the old bytes
        out as a NEW version rather than winding the history back — a history that can be
        edited answers a different question from the one it is asked.
        """
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        store   = cls._versions_store(cfg)
        if store is None:
            return {'ok': False, 'message': 'database not available'}
        path, mib = cls._raw_path_of(var_dir, name)
        if not path or not os.path.isfile(path):
            return {'ok': False, 'message': 'Invalid file name'}
        if len(content) > _mib_versions.MAX_SOURCE_BYTES:
            return {'ok': False, 'message': 'Source too large'}

        rel = _safe_mib_relpath(name, 'raw')
        author = str(cfg.get('__user__') or '')
        try:
            with io.open(path, encoding='utf-8-sig', errors='replace') as fh:
                current = fh.read()
        except OSError as exc:
            return {'ok': False, 'message': str(exc)}

        # Nothing to do, and saying so is better than a version that records no change.
        if _mib_versions.sha_of(current) == _mib_versions.sha_of(content):
            return {'ok': True, 'unchanged': True, 'mib': mib,
                    'versions': store.versions(mib)}

        try:
            # The vendor's own, kept the first time somebody touches it — after that the
            # file it came from has been overwritten and there is nowhere else to get it.
            if not store.has_any(mib):
                store.add(mib, rel, current, author='', note=_mib_versions.NOTE_ORIGINAL)
            # What this was written on top of. It is what turns a list of contents into a
            # history: the change is `parent → this`, and without the parent there is no
            # change, only a document.
            store.add(mib, rel, content, author=author, note=note,
                      parent=_mib_versions.sha_of(current))
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': f'History not saved: {exc}'}

        try:
            tmp = path + '.tmp'
            with io.open(tmp, 'w', encoding='utf-8', newline='') as fh:
                fh.write(content)
            os.replace(tmp, path)
        except OSError as exc:
            # The version is already in: an edit recorded but not written is recoverable,
            # the other way round is not.
            return {'ok': False, 'message': str(exc), 'mib': mib,
                    'versions': store.versions(mib)}

        # The compiled module and the recorded failure are both about the bytes that were
        # there a moment ago. The error store prunes itself on read (it remembers the size
        # and mtime it was about), so nothing to do there — but the index is stale now.
        _mib_resolver.invalidate_cache()
        return {'ok': True, 'mib': mib, 'relpath': rel, 'versions': store.versions(mib)}

    @classmethod
    def save_mib_source(cls, config: dict | None = None) -> dict:
        """Write an edited MIB source and record it as a new version."""
        cfg  = config or {}
        name = str(cfg.get('name') or '').strip()
        if not name or 'content' not in cfg:
            return {'ok': False, 'message': 'Invalid parameters'}
        return cls._write_source(cfg, name, str(cfg.get('content') or ''),
                                 str(cfg.get('note') or ''))

    @classmethod
    def restore_mib_version(cls, config: dict | None = None) -> dict:
        """Put a stored version back on disk, as a new version."""
        cfg  = config or {}
        name = str(cfg.get('name') or '').strip()
        uid  = str(cfg.get('uid')  or '').strip()
        store = cls._versions_store(cfg)
        if store is None:
            return {'ok': False, 'message': 'database not available'}
        content = store.content(uid)
        if content is None:
            return {'ok': False, 'message': 'Version not found'}
        rows = {r['uid']: r for r in store.versions(
            os.path.splitext(os.path.basename(_safe_mib_relpath(name, 'raw') or ''))[0])}
        src = rows.get(uid)
        if src is None:
            return {'ok': False, 'message': 'Version not found'}
        return cls._write_source(cfg, name, content, f'restored from v{src["version"]}')

    @classmethod
    def list_mib_versions(cls, config: dict | None = None) -> dict:
        """Every stored version of one MIB, newest first — without the content."""
        cfg   = config or {}
        store = cls._versions_store(cfg)
        if store is None:
            return {'ok': True, 'versions': []}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        _path, mib = cls._raw_path_of(var_dir, str(cfg.get('name') or ''))
        if not mib:
            return {'ok': False, 'message': 'Invalid file name'}
        return {'ok': True, 'mib': mib, 'versions': store.versions(mib)}

    @classmethod
    def _overwrite_recorder(cls, cfg: dict):
        """A callback that files the incoming content as a version, for MIBs with a history.

        Only for those: recording every file of every import would fill the store with vendor
        copies nobody asked to keep. A MIB with a history is one somebody edited, and that is
        exactly the edit an import is about to replace — so the replacement becomes the next
        version, and going back to the fix is one click instead of an archaeology exercise.
        """
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        store = cls._versions_store(cfg)
        if store is None or not var_dir:
            return None
        replaced: list = []

        def _record(rel: str, incoming: str) -> None:
            mib = os.path.splitext(os.path.basename(rel))[0]
            if not store.has_any(mib):
                return
            path = _confined_path(os.path.join(var_dir, 'snmp_mibs', 'raw'), *rel.split('/'))
            if not path:
                return
            try:
                with io.open(path, encoding='utf-8-sig', errors='replace') as fh:
                    current = fh.read()
            except OSError:
                return
            if _mib_versions.sha_of(current) == _mib_versions.sha_of(incoming):
                return
            # An edit IS being replaced, so it is reported either way — but content this MIB
            # has already been through is not filed twice. Nothing is lost: those exact bytes
            # are already one restore away, under the version they came in as.
            if not store.version_with(mib, incoming):
                store.add(mib, rel, incoming, author='', note=_NOTE_IMPORTED,
                          parent=_mib_versions.sha_of(current))
            replaced.append(mib)

        _record.replaced = replaced      # read once the import is done
        return _record

    @classmethod
    def orphan_versions(cls, config: dict | None = None) -> dict:
        """Every version of one MIB whose file is gone, by module name.

        The orphan rows have no file, so they cannot go through :meth:`_raw_path_of` like
        everything else — the module name IS the whole handle.
        """
        cfg = config or {}
        store = cls._versions_store(cfg)
        mib = str(cfg.get('mib') or '').strip()
        if store is None or not mib:
            return {'ok': False, 'message': 'Invalid parameters'}
        return {'ok': True, 'mib': mib, 'versions': store.versions(mib)}

    @classmethod
    def restore_orphan(cls, config: dict | None = None) -> dict:
        """Write a stored version back out, recreating the file it came from.

        The path comes from the version itself: a version knows where it lived, which is the
        only record left once the file is gone.
        """
        cfg = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        store = cls._versions_store(cfg)
        mib = str(cfg.get('mib') or '').strip()
        uid = str(cfg.get('uid') or '').strip()
        if store is None or not var_dir or not mib:
            return {'ok': False, 'message': 'Invalid parameters'}
        rows = {v['uid']: v for v in store.versions(mib)}
        row = rows.get(uid) or (store.versions(mib) or [None])[0]
        if row is None:
            return {'ok': False, 'message': 'Version not found'}
        content = store.content(row['uid'])
        if content is None:
            return {'ok': False, 'message': 'Version not found'}
        rel = _safe_mib_relpath(row.get('relpath') or f'{mib}.txt', 'raw')
        if not rel:
            return {'ok': False, 'message': 'Invalid file name'}
        dest = _confined_path(os.path.join(var_dir, 'snmp_mibs', 'raw'), *rel.split('/'))
        if not dest:
            return {'ok': False, 'message': 'Invalid file name'}
        if os.path.isfile(dest):
            return {'ok': False, 'message': 'A file is already there'}
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with io.open(dest, 'w', encoding='utf-8', newline='') as fh:
                fh.write(content)
        except OSError as exc:
            return {'ok': False, 'message': str(exc)}
        _mib_resolver.invalidate_cache()
        return {'ok': True, 'mib': mib, 'relpath': rel, 'version': row['version']}

    @classmethod
    def forget_mib_versions(cls, config: dict | None = None) -> dict:
        """Drop the whole history of a MIB — for one whose file is gone for good."""
        cfg = config or {}
        store = cls._versions_store(cfg)
        mib = str(cfg.get('mib') or '').strip()
        if store is None or not mib:
            return {'ok': False, 'message': 'Invalid parameters'}
        return {'ok': True, 'mib': mib, 'removed': store.drop_all(mib)}

    @classmethod
    def delete_mib_version(cls, config: dict | None = None) -> dict:
        """Remove one stored version of one MIB.

        The history is the reason anybody dares edit a vendor MIB, so it is not tidied up
        automatically beyond the cap — but a version somebody knows is junk should not have to
        stay for ever either.
        """
        cfg = config or {}
        store = cls._versions_store(cfg)
        if store is None:
            return {'ok': False, 'message': 'database not available'}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        _path, mib = cls._raw_path_of(var_dir, str(cfg.get('name') or ''))
        if not mib:
            return {'ok': False, 'message': 'Invalid file name'}
        gone = store.drop(mib, str(cfg.get('uid') or '').strip())
        if gone is None:
            return {'ok': False, 'message': 'Version not found'}
        return {'ok': True, 'mib': mib, 'removed': gone,
                'versions': store.versions(mib)}

    @classmethod
    def lint_mib_source(cls, config: dict | None = None) -> dict:
        """Read a MIB the way the compiler will, and say what will stop it.

        Takes *content* when there is an editor open — the point is to answer before saving —
        and falls back to the file named by *name*. Read-only either way.
        """
        cfg = config or {}
        text = cfg.get('content')
        if text is None:
            var_dir = str(cfg.get('__var_dir__') or '').strip()
            path, _mib = cls._raw_path_of(var_dir, str(cfg.get('name') or ''))
            if not path or not os.path.isfile(path):
                return {'ok': False, 'message': 'File not found'}
            try:
                with io.open(path, encoding='utf-8-sig', errors='replace') as fh:
                    text = fh.read()
            except OSError as exc:
                return {'ok': False, 'message': str(exc)}
        return {'ok': True,
                'findings': _mib_lint.lint_mib(str(text), str(cfg.get('name') or ''))}

    @classmethod
    def diff_mib_versions(cls, config: dict | None = None) -> dict:
        """A unified diff between two versions, or between one and the file as it is now.

        Server-side because both sides are already here and the browser holds neither: the
        version list is deliberately shipped without content, so diffing in the page would
        mean fetching two whole files to throw most of them away.

        *uid* is one side; *other* is the second, and an empty *other* means the file on disk
        — which is the comparison anybody actually wants ("what did I change since v3?").
        """
        cfg   = config or {}
        store = cls._versions_store(cfg)
        if store is None:
            return {'ok': False, 'message': 'database not available'}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        path, mib = cls._raw_path_of(var_dir, str(cfg.get('name') or ''))
        if not mib:
            return {'ok': False, 'message': 'Invalid file name'}

        rows = {r['uid']: r for r in store.versions(mib)}

        def _side(uid):
            """(text, label) for one side of the comparison."""
            uid = str(uid or '').strip()
            if not uid:
                if not path or not os.path.isfile(path):
                    return None, ''
                try:
                    with io.open(path, encoding='utf-8-sig', errors='replace') as fh:
                        return fh.read(), _CURRENT_LABEL
                except OSError:
                    return None, ''
            row = rows.get(uid)
            if row is None:
                return None, ''
            text = store.content(uid)
            return (None, '') if text is None else (text, f'v{row["version"]}')

        a_text, a_label = _side(cfg.get('other'))
        b_text, b_label = _side(cfg.get('uid'))
        if a_text is None or b_text is None:
            return {'ok': False, 'message': 'Version not found'}

        return _unified_diff(a_text, a_label, b_text, b_label)

    @classmethod
    def get_mib_version(cls, config: dict | None = None) -> dict:
        """One stored version, with its content — for reading before restoring it."""
        cfg   = config or {}
        store = cls._versions_store(cfg)
        if store is None:
            return {'ok': False, 'message': 'database not available'}
        content = store.content(str(cfg.get('uid') or '').strip())
        if content is None:
            return {'ok': False, 'message': 'Version not found'}
        return {'ok': True, 'source': content}

    @classmethod
    def _duplicate_sources(cls, raw_dir: str, compiled_dir: str, raw_files: list) -> dict:
        """The MODULES carried by more than one file, and what is in each of them.

        Grouped by module and not by file name, because the module is what collides:
        several files called ``SNMPv2-TC`` are one name pysmi resolves to a single file,
        and two files with different names that both declare ``IP-MIB`` are two
        compilations writing the same ``IP-MIB.py``, the second over the first. A vendor
        archive brings its own copy of the standard MIBs, so both arrive by themselves —
        and a stripped copy replacing the real one breaks the MIBs that import it, three
        modules from where anybody would look.

        WHICH modules collide is free — it is a grouping of facts the listing already has.
        Everything else about them is not, and this used to do all of it on every load, for
        panels nobody had opened:

        * hashing every copy and comparing what each declares (257 collisions over 529 files);
        * and, for the ones with nothing compiled yet, asking pysmi which file it WOULD read.
          That one is not merely slow, it is quadratic in disguise: the reader tries every
          name variant in every directory it was given, so 151 lookups over a library of 408
          folders came to **1.19 million** filesystem checks and **four minutes** — measured,
          not guessed. One of those lookups, for one module, is a quarter of a second.

        Both answers moved to :meth:`mib_dupe_details`, which is asked when somebody opens a
        group. What is left here reads nothing at all.
        """
        by_module: dict = {}
        for f in raw_files:
            by_module.setdefault(f['module'], []).append(f)

        out: dict = {}
        for mib, files in by_module.items():
            if len(files) < 2:
                continue
            entries = [{'name': f['name'], 'size': f['size'],
                        'updated': f.get('updated', '')}
                       for f in sorted(files, key=lambda x: x['name'])]
            # Which copy the compiled module was ACTUALLY built from, read off the .py
            # where pysmi records it. A fact, where 'which one would pysmi read' is a
            # prediction — and the two disagree exactly when it matters, because a vendor
            # archive landing beside an older library changes the second and not the first.
            used = _mib_resolver.compiled_source(compiled_dir, mib)
            out[mib] = {
                'files': entries,
                'used':  used,
                'compiled_from': bool(used),
            }
        return out

    @classmethod
    def mib_dupe_details(cls, config: dict | None = None) -> dict:
        """What the copies of ONE module actually hold: their hashes, whether they are the
        same content, and whether they are versions of each other at all.

        Split off the listing because of what it costs: hashing every colliding file, reading
        each of them and comparing what they declare took four minutes on a library with
        LibreNMS in it — 257 collisions across 529 files — and it was paid on every load of
        the section, for panels nobody had opened. Which modules collide is a grouping of
        facts already in hand; this is the part that reads.
        """
        cfg = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        mib = str(cfg.get('mib') or '').strip()
        names = [str(n) for n in (cfg.get('names') or []) if str(n).strip()]
        if not var_dir or not mib or not names:
            return {'ok': False, 'message': 'Missing arguments'}
        raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
        paths, shas = [], {}
        for name in sorted(names):
            p = _confined_path(raw_dir, *name.split('/'))
            if not p:
                return {'ok': False, 'message': 'Invalid filename'}
            paths.append(p)
            shas[name] = _sha_of_file(p)
        # Which copy pysmi would read, when nothing has been compiled from any of them —
        # the only answer available then, and it costs a walk of the whole tree, which is
        # why it is here and not in the listing.
        used = str(cfg.get('used') or '')
        if not used:
            stems = sorted({os.path.splitext(os.path.basename(n))[0] for n in names})
            found = _mib_resolver.resolve_raw_sources(raw_dir, stems)
            for stem in stems:
                if found.get(stem):
                    used = found[stem]
                    break
        return {
            'ok': True,
            'mib': mib,
            'used': used,
            'sha': shas,
            # Same CONTENT, not the same bytes — see :func:`_text_of`.
            'same': len(set(shas.values())) == 1 and all(shas.values()),
            # Whether these are copies at all. The panel offered one answer — "pick the one
            # that stays" — to two different problems, and for the second one it is the wrong
            # answer: deleting either of two MIBs that only share a header loses everything
            # that MIB declares.
            'kinship': _kinship(paths),
        }

    @classmethod
    def diff_mib_files(cls, config: dict | None = None) -> dict:
        """A unified diff between two raw MIB files — for deciding which copy stays.

        The version diff answers "what did I change"; this one answers "which of these two is
        the one I want", which is the question a duplicate actually poses.
        """
        cfg = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw') if var_dir else ''
        if not raw_dir:
            return {'ok': False, 'message': 'var_dir not available'}
        sides = []
        for key in ('a', 'b'):
            rel = _safe_mib_relpath(str(cfg.get(key) or ''), 'raw')
            path = _confined_path(raw_dir, *rel.split('/')) if rel else None
            text = _text_of(path or '')
            if text is None:
                return {'ok': False, 'message': 'File not found'}
            sides.append((text, rel))
        return _unified_diff(sides[0][0], sides[0][1], sides[1][0], sides[1][1])

    @classmethod
    def list_mibs(cls, config: dict | None = None) -> dict:
        """Return lists of raw and compiled MIB files together with pysmi status."""
        cfg = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')      if var_dir else ''
        compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled') if var_dir else ''
        cls._repair_line_endings(raw_dir)
        # What was read out of every file last time, if it is still true. Five thousand
        # headers is most of what opening this section costs, and none of it changes while
        # the files do not.
        _mib_resolver.facts_cache_load(raw_dir)

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
                    items.append({'name': f, 'size': st.st_size, 'mtime': int(st.st_mtime),
                                  # The raw file it was built from, as pysmi recorded it.
                                  # Cheap (a 2 KB header, cached) and the only way to notice
                                  # that a compiled module outlived its source.
                                  'source': _mib_resolver.compiled_source(
                                      path, os.path.splitext(f)[0])})
            return items

        _facts = _mib_resolver.raw_facts

        _walk = _mib_resolver.iter_raw_mibs(raw_dir)

        def _list_raw(path):
            # Recursive: an imported repository or vendor archive keeps its own folders, and a
            # listing that showed only the top level would hide everything that was imported.
            items = []
            for rel, full in _walk:
                if os.path.basename(rel).startswith('__'):
                    continue
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                items.append({'name': rel, 'size': st.st_size, 'mtime': int(st.st_mtime),
                              'folder': os.path.dirname(rel),
                              # What pysmi will CALL it, which is what the .py gets named and
                              # therefore the only name "is this compiled?" can be asked
                              # about. `trunk.mib` is IEEE8023-LAG-MIB; `rfc2011.mib` is
                              # IP-MIB. The file name is how the file is found, no more.
                              'module': _facts(full, st)['module'] or
                                        os.path.splitext(os.path.basename(rel))[0],
                              # The date the MIB declares for itself. Free here (same read,
                              # same cache) and it is what decides which of two copies of a
                              # standard module is the one to keep.
                              'updated': _facts(full, st)['updated']})
            return items

        raw_files      = _list_raw(raw_dir)
        compiled_files = _listdir(compiled_dir)
        # Keyed by MIB NAME, which is what a compile error is about: pysmi compiles a module
        # by name, and which folder its source sits in is where it was found. The name comes
        # from inside the file — `trunk.mib` produces IEEE8023-LAG-MIB — and an index keyed on
        # the file name never meets the error, the compiled module or the history.
        raw_index = {f['module']: f for f in raw_files}
        errors = cls._live_compile_errors(
            cls._read_compile_errors(var_dir), raw_index,
            {os.path.splitext(f['name'])[0] for f in compiled_files})
        # A failure recorded against a MIB that is no longer compiled at all is a failure
        # about a run that cannot happen again.
        for _m in _mib_resolver.MACRO_ONLY_MIBS:
            errors.pop(_m, None)

        # Which MIBs are no longer the file the vendor shipped. A row that says only
        # "compiled, 6.0 KB" cannot tell an untouched vendor file from one somebody fixed
        # three weeks ago, and that is the first thing you want to know when it misbehaves.
        try:
            _vstore = cls._versions_store(cfg)
            edited = _vstore.current_versions() if _vstore is not None else {}
        except Exception:  # pylint: disable=broad-except
            edited = {}

        # History with no file behind it. Deleting a MIB keeps its versions — losing an edit
        # because somebody removed a file to re-import it clean is the opposite of what a
        # history is for — but kept and never shown is a thing that exists and cannot be
        # reached: no row to click, no way to bring it back, no way to clear it out.
        _known = {f['module'] for f in raw_files}
        _known |= {os.path.splitext(f['name'])[0] for f in compiled_files}
        orphans = {m: v for m, v in edited.items() if m not in _known}

        _mib_resolver.facts_cache_save(raw_dir)
        return {
            'ok':              True,
            'raw':             raw_files,
            'compiled':        compiled_files,
            'errors':          errors,
            'edited':          edited,
            'orphans':         orphans,
            'dupes':           cls._duplicate_sources(raw_dir, compiled_dir, raw_files),
            # What a compile with scope 'pending' will walk, from the function that decides
            # it. The panel used to count its own pending ROWS instead — one row per module,
            # where the job walks one unit per file NAME — so the button promised 14 and the
            # bar went to 15. Counting the work and doing the work must be one answer.
            'pending':         _mib_resolver.pending_raw_mibs(raw_dir, compiled_dir,
                                                                files=_walk),
            # The modules that are macros and nothing else: no .py is produced for them and
            # none is missing. A row with no compiled module and no error reads as a compile
            # that quietly did nothing.
            'macro_only':      list(_mib_resolver.MACRO_ONLY_MIBS),
            'pysmi_available': _HAS_PYSMI,
            'raw_dir':         raw_dir,
            'compiled_dir':    compiled_dir,
            'known_repos':     _KNOWN_MIB_REPOS,
            'mib_repos':       cls._repo_templates(cfg),
        }

    @classmethod
    def _repair_line_endings(cls, raw_dir: str) -> int:
        """Undo, once, what a broken writer left in the library.

        Every file imported before this was fixed went out through Python's text mode, which
        on Windows adds a ``\r`` to every line terminator on the way out: an LF file was
        stored as CRLF, and a CRLF file as ``\r\r\n``. Nothing crashed and nothing said so:
        the compiler does not mind whitespace. What it cost was everything that COMPARES the
        file — the source viewer showed a blank line between every line, and the archive
        report called every MIB in the library "newer than installed", forever, because
        importing it could not make the bytes match either.

        So the undo is the exact inverse — **one** ``\r`` removed from each line terminator —
        and not "collapse ``\r\r\n``". That distinction is not academic: some MIBs really
        do ship with ``\r\r\n`` (LibreNMS carries a few dozen), and collapsing theirs
        deletes a blank line the vendor wrote. Removing exactly what was added restores the
        bytes that arrived, whatever they were.

        In place, and keeping the modification time. The change is whitespace, so the
        compiled module is still current — and touching two thousand mtimes would order a
        rebuild of the whole library: hours of ASN.1 for a repair no compiler can see.

        Once, guarded by a marker beside the tree: whatever arrives afterwards is written
        correctly, so there is nothing to look for on every listing.
        """
        if not raw_dir or not os.path.isdir(raw_dir):
            return 0
        mark = os.path.join(os.path.dirname(raw_dir), _REPAIR_MARK)
        if os.path.exists(mark):
            return 0
        fixed = 0
        for _rel, full in _mib_resolver.iter_raw_mibs(raw_dir):
            try:
                with open(full, 'rb') as fh:
                    blob = fh.read()
                # One CR off each terminator, however many it has: `\r\n` → `\n`,
                # `\r\r\n` → `\r\n`, `\n` → untouched.
                repaired = re.sub(rb'\r(\r*\n)', rb'\1', blob)
                if repaired == blob:
                    continue
                st = os.stat(full)
                with open(full, 'wb') as fh:
                    fh.write(repaired)
                os.utime(full, (st.st_atime, st.st_mtime))
                fixed += 1
            except OSError:
                continue
        try:
            with open(mark, 'w', encoding='utf-8') as fh:
                fh.write('')
        except OSError:
            pass
        return fixed

    @classmethod
    def list_mib_sources(cls, config: dict | None = None) -> dict:
        """Where MIBs can be imported FROM: the known repositories and archives.

        The same two keys `list_mibs` ends with, and none of what it does to get there.
        That answer walks the whole raw tree, reads a header out of every file, hashes the
        colliding ones and works out what is pending — seconds on a library that has had
        LibreNMS imported into it — and the import screen was asking for all of it to fill
        two dropdowns. This reads a list that is already in memory.
        """
        return {
            'ok':          True,
            'known_repos': _KNOWN_MIB_REPOS,
            'mib_repos':   cls._repo_templates(config or {}),
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

        # Recursive, and by MIB NAME: pysmi compiles a module by name and writes one file
        # per name, so what a folder a MIB sits in changes is where it was found, not what it
        # is called. Scanning only the top level found nothing at all on an installation whose
        # MIBs all arrived inside a vendor archive — and a compile with nothing to compile
        # finishes instantly and looks like a button that does not work.
        raw_mibs = sorted({os.path.splitext(os.path.basename(rel))[0]
                           for rel, _full in _mib_resolver.iter_raw_mibs(raw_dir)})

        # Scope. 'pending' is the honest default for a button somebody presses without
        # reading it: it walks only what has no compiled module or one older than its source,
        # so the progress bar counts the work and not the inventory — 0/2000 while three
        # files need compiling is a bar that says nothing. 'all' walks everything AND forces
        # the rebuild, which is the case pysmi's timestamp check cannot see.
        scope = str(cfg.get('scope') or '').strip().lower()
        rebuild = scope == 'all'
        if scope == 'pending':
            _pending = set(_mib_resolver.pending_raw_mibs(raw_dir, compiled_dir))
            raw_mibs = [m for m in raw_mibs if m in _pending]
            if not raw_mibs:
                return {'ok': True, 'done': True, 'compiled': False, 'partial': False,
                        'results': {}, 'failed': [], 'total': 0, 'completed': 0,
                        'up_to_date': True}

        # Optional filter: compile only the requested MIBs. The panel selects FILES, which now
        # carry their folder, and this compiles NAMES — so the path is dropped here rather
        # than making every caller remember to.
        mibs_req = cfg.get('mibs', None)
        if isinstance(mibs_req, list) and mibs_req:
            _keep = {os.path.splitext(os.path.basename(str(m)))[0] for m in mibs_req if m}
            raw_mibs = [m for m in raw_mibs if m in _keep]

        if not raw_mibs:
            return {'ok': True, 'done': True, 'compiled': False, 'partial': False,
                    'results': {}, 'failed': [], 'total': 0, 'completed': 0}

        # The compiler is handed EXACTLY the list this job counted. It used to be told nothing
        # unless the caller sent an explicit selection, so it re-derived its own work list
        # from the directory — everything — while the job reported the narrowed total. On
        # screen that was "Compiling 28 / 3" and a progress bar at 933%: the scope had
        # narrowed the number and not the work. Two derivations of "what to compile" that can
        # disagree is one too many, so there is one, and every scope goes through it.
        mibs_filter = list(raw_mibs)

        job_id = uuid.uuid4().hex[:12]
        _cancel = threading.Event()
        _compile_jobs[job_id] = {
            'done': False, 'phase': 'compiling', 'total': len(raw_mibs), 'completed': 0,
            'current': None, 'result_ok': None, 'compiled': False,
            'partial': False, 'failed': [], 'errors': {}, 'message': '', 'cancelled': False,
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
                rebuild=rebuild,
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
            try:
                # What the job actually REACHED, not what it set out to do: a cancelled
                # run must not clear the reason held for a MIB it never got to.
                # By MODULE, which is what a result is about — the job's own list, since
                # the mapping from the file names it was given belongs to whoever did the
                # mapping. Keyed by file name instead, nothing ever matched: the store was
                # never cleared, so a MIB that had since compiled kept its old red row.
                _attempted = list(result.get('attempted') or [])
                cls._record_compile_errors(
                    var_dir, _attempted, result.get('errors', {}),
                    {(_mib_resolver.raw_facts(_full)['module']
                      or os.path.splitext(os.path.basename(rel))[0]):
                        {'name': rel, 'size': _st.st_size, 'mtime': int(_st.st_mtime)}
                     for rel, _full in _mib_resolver.iter_raw_mibs(raw_dir)
                     for _st in [os.stat(_full)]})
            except OSError:      # a listing that fails must not lose the compile's result
                pass
            _compile_jobs[job_id].update({
                'done':      True,
                'result_ok': result.get('ok', False),
                'compiled':  result.get('compiled', False),
                'partial':   result.get('partial', False),
                'failed':    result.get('failed', []),
                # Why each one failed. A count of failures is not actionable; "Bad grammar
                # at line 21" is — and it is the difference between a vendor shipping a
                # broken file and a bug in the compiler here.
                'errors':    result.get('errors', {}),
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
        # Raw MIBs live in a tree (a repository's own folders survive the import); compiled
        # modules are flat, because pysmi keys them by MIB name and nothing else.
        rel = _safe_mib_relpath(name, kind) if kind == 'raw' else _safe_mib_filename(name, kind)
        if not rel:
            return {'ok': False, 'message': 'Invalid file name'}
        base = os.path.join(var_dir, 'snmp_mibs', kind)
        path = _confined_path(base, *rel.split('/'))
        if not path or not os.path.isfile(path):
            return {'ok': False, 'message': 'File not found'}
        # Which module this is, read BEFORE the file goes: the name lives inside it, and
        # afterwards there is nothing left to read it from.
        _mib = ''
        if kind == 'raw':
            _mib = cls._raw_path_of(var_dir, name)[1]
        os.remove(path)
        _mib_resolver.invalidate_cache()
        # Deleting a compiled MIB leaves the symbol catalog stale (removal does
        # not make the remaining files newer, so mtime-based staleness won't
        # catch it).  DISCARD it (one file unlink) rather than rebuilding here —
        # rebuilding on every deletion makes bulk-delete extremely slow.  The
        # next MIB Browser open rebuilds the catalog once, lazily.
        if kind == 'compiled':
            _mib_catalog.discard(var_dir)
        # Only when asked for, and never by default: the ordinary reason to delete a raw MIB
        # is to import it again cleanly, and that is exactly when the edit that came before is
        # worth still having.
        dropped = 0
        if kind == 'raw' and _truthy_import(cfg.get('with_history', False)):
            store = cls._versions_store(cfg)
            if store is not None:
                dropped = store.drop_all(_mib)
        return {'ok': True, 'history_deleted': dropped}

    # ── What a deletion leaves behind ──────────────────────────────────────────
    #
    # Deleting a source does not delete what was made from it, and it cannot: the compiled
    # module is a file of its own, flat in `compiled/`, named after the MODULE and carrying
    # no trace of the folder its source came from — nothing in the library's shape says
    # "these 381 .py files belong to the vendor folder you just removed". So they stay,
    # loadable, uncompilable and unaccounted for.
    #
    # pysmi does record where it read from, in a header of its own that
    # :func:`mib_resolver.compiled_source` knows how to read — which is what makes the
    # leftovers findable at all.

    @staticmethod
    def _declared_modules(raw_dir: str) -> set:
        """Every module name the raw library declares — from inside the files, not from
        their names. `trunk.mib` is IEEE8023-LAG-MIB, and a compiled module is named after
        what it declares, so this is the only set the two sides can be compared on."""
        out = set()
        for rel, full in _mib_resolver.iter_raw_mibs(raw_dir):
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.add(_mib_resolver.raw_facts(full, st)['module']
                    or os.path.splitext(os.path.basename(rel))[0])
        return out

    @classmethod
    def _stray_compiled(cls, raw_dir: str, compiled_dir: str) -> list:
        """Compiled modules whose source is no longer in the library.

        Two answers are NOT strays, and both would be destructive to treat as one:

        * a module some raw file still declares — the source is there, whatever the file is
          called and whichever folder it moved to;
        * one pysmi did not read out of `raw/` at all — a dependency it resolved from its own
          bundled MIBs or over HTTP. Nothing can rebuild those, and the modules that import
          them stop loading the moment they go.
        """
        if not os.path.isdir(compiled_dir):
            return []
        _mib_resolver.facts_cache_load(raw_dir)
        declared = cls._declared_modules(raw_dir)
        _mib_resolver.facts_cache_save(raw_dir)
        out = []
        for f in sorted(os.listdir(compiled_dir)):
            if not f.endswith('.py') or f.startswith('__') or f.startswith('.'):
                continue
            mib = f[:-3]
            if mib in declared:
                continue
            src = _mib_resolver.compiled_source(compiled_dir, mib)
            if not src:
                continue
            try:
                size = os.path.getsize(os.path.join(compiled_dir, f))
            except OSError:
                continue
            out.append({'name': f, 'mib': mib, 'source': src, 'size': size})
        return out

    @staticmethod
    def _empty_raw_dirs(raw_dir: str) -> list:
        """Folders under `raw/` with no file anywhere beneath them.

        Deleting every MIB in a vendor folder leaves the folder: `os.remove` removes files.
        A folder is empty here when nothing under it is a file — a parent whose only content
        is empty folders is empty too, which is why this asks about the whole subtree
        instead of walking bottom-up and stopping at the first branch.
        """
        if not os.path.isdir(raw_dir):
            return []
        seen, keep = set(), set()
        for root, _dirs, files in os.walk(raw_dir):
            if root != raw_dir:
                seen.add(root)
            if not files:
                continue
            node = root
            while len(node) > len(raw_dir):
                keep.add(node)
                node = os.path.dirname(node)
        return sorted(os.path.relpath(d, raw_dir).replace(os.sep, '/')
                      for d in seen - keep)

    @classmethod
    def library_leftovers(cls, config: dict | None = None) -> dict:
        """What is left over from deleting MIBs, without deleting any of it."""
        cfg     = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        if not var_dir:
            return {'ok': False, 'message': 'Invalid parameters'}
        raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')
        compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
        stray = cls._stray_compiled(raw_dir, compiled_dir)
        dirs  = cls._empty_raw_dirs(raw_dir)
        return {
            'ok':          True,
            'stray':       stray,
            'stray_bytes': sum(e['size'] for e in stray),
            'empty_dirs':  dirs,
        }

    @classmethod
    def clean_library(cls, config: dict | None = None) -> dict:
        """Delete the leftovers :meth:`library_leftovers` reports, and nothing else.

        It re-reads them rather than taking a list from the caller: between the report and
        the click somebody may have imported the very sources that would make a stray a
        source again, and a delete list from a minute ago cannot know that.
        """
        cfg     = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        if not var_dir:
            return {'ok': False, 'message': 'Invalid parameters'}
        raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')
        compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
        removed = 0
        for entry in cls._stray_compiled(raw_dir, compiled_dir):
            # From `os.listdir` of that one directory: a name, never a path.
            path = os.path.join(compiled_dir, os.path.basename(entry['name']))
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
        # Deepest first: a parent is only empty once its children are gone.
        folders = 0
        for rel in sorted(cls._empty_raw_dirs(raw_dir),
                          key=lambda r: r.count('/'), reverse=True):
            target = _confined_path(raw_dir, *rel.split('/'))
            if not target:
                continue
            try:
                os.rmdir(target)
                folders += 1
            except OSError:
                pass
        if removed:
            # The symbol catalogue names modules that are no longer there. Discarded, not
            # rebuilt: the next MIB Browser open pays for one rebuild, this click does not.
            _mib_catalog.discard(var_dir)
        _mib_resolver.invalidate_cache()
        return {'ok': True, 'compiled_deleted': removed, 'folders_removed': folders}

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
        rel = _safe_mib_relpath(name, 'raw')
        if not rel:
            return {'ok': False, 'message': 'Invalid file name'}
        raw_dir   = os.path.join(var_dir, 'snmp_mibs', 'raw')
        file_path = _confined_path(raw_dir, *rel.split('/'))
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
        # An extension somebody picked in a file dialog says even less than a repository's
        # name does. A .txt that is not a MIB lands in the list as a MIB that never compiles.
        if not _is_mib_source(content):
            return {'ok': False, 'message': 'That file does not define a MIB module'}

        raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        dest = _confined_path(raw_dir, filename)
        if not dest:
            return {'ok': False, 'message': 'Invalid filename'}
        with open(dest, 'w', encoding='utf-8', newline='') as fh:
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

        # One file asked for by name goes where it was asked for — the root — because there
        # is no source to file it under, and inventing one would hide it from the person who
        # just typed its URL. But it still has to BE a MIB.
        if not _is_mib_source(content):
            return {'ok': False, 'message': 'That URL does not return a MIB'}

        raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        dest = _confined_path(raw_dir, filename)
        if not dest:
            return {'ok': False, 'message': 'Invalid filename'}
        try:
            with open(dest, 'w', encoding='utf-8', newline='') as fh:
                fh.write(content)
        except OSError as exc:
            return {'ok': False, 'message': f'Save failed: {exc}'}

        return {'ok': True, 'filename': filename}

    @classmethod
    def _zip_first(cls, cfg: dict, url: str, recursive: bool) -> dict | None:
        """The archive INSTEAD of the walk, when the walk is the wrong tool for this import.

        A folder-per-request walk is the cheap way to fetch a folder and the wrong way to
        fetch a tree: LibreNMS' `mibs/` is four hundred vendor folders, which is four hundred
        requests against an allowance of sixty an hour. Waiting for GitHub to say no was not
        enough — with allowance left the walk does not fail, it *truncates*, and comes back
        with the first forty folders and a message nobody reads as "this did not work".

        So: a RECURSIVE import of a folder whose source publishes an archive goes straight to
        the archive. Everything else still walks — a single folder is one request, and its
        files come from raw.github without touching the allowance at all.
        """
        if not recursive:
            return None
        src = _import_source(url)
        if not str(src.get('archive') or '').strip():
            return None
        # …and only for the WHOLE folder the source publishes. A vendor inside it is one
        # request to list and a handful of direct downloads — spending 86 MB on ten files
        # would be trading one waste for a bigger one. If that walk turns out not to finish,
        # the fallback still has the same archive waiting.
        parsed = _parse_github_folder(url)
        path = str((parsed[3] if parsed else '') or '').strip('/')
        if path != _import_source_path(src):
            return None
        return _import_via_zip(cls, cfg, url)

    @classmethod
    def _finish_by_zip(cls, cfg: dict, url: str, out: dict) -> dict:
        """After a walk that did not finish, import the same folder from the ZIP.

        Not only when GitHub refused: a walk that stopped at its own ceiling has the same
        problem and the same answer. What it did fetch is not wasted — the archive importer
        compares before writing, so the files already here are recognised as unchanged.
        """
        if not (out.get('rate_limited') or out.get('truncated')):
            return out
        alt = _import_via_zip(cls, cfg, url)
        if alt is None or not alt.get('ok'):
            return out
        _n = int(alt.get('written', 0) or 0)
        out['zip_fallback'] = True
        out['truncated'] = bool(alt.get('truncated'))
        out['count'] = int(out.get('count', 0) or 0) + _n
        out['ok'] = True
        out['message'] = (f"{out.get('message', '')} — finished from the repository ZIP "
                          f"instead: {alt.get('message', '')}").strip(' —')
        return out

    @staticmethod
    def _github_token(cfg: dict) -> str:
        """The token to authenticate the import with, or ``''``.

        Read from the config the ACTION was given, which is the module's own configuration —
        the same place the repository templates come from. A token is not required for
        anything: without one the import works exactly as before, against sixty requests an
        hour instead of five thousand.
        """
        return str((cfg or {}).get('github_token') or '').strip()

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
        _rec = cls._overwrite_recorder(cfg)
        direct = cls._zip_first(cfg, url, recursive)
        if direct is not None:
            return direct
        out = _run_github_import(var_dir, url, recursive, subdir=_import_subdir(url),
                                 token=cls._github_token(cfg),
                                 skip_names=_import_skip_names(url), on_overwrite=_rec)
        out = cls._finish_by_zip(cfg, url, out)
        if _rec is not None and _rec.replaced:
            out['replaced_edited'] = sorted(_rec.replaced)
        return out

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

        # Built HERE and not in the thread: it needs the connector out of the config, and the
        # config is a request-scoped thing.
        _rec = cls._overwrite_recorder(cfg)
        # Read here and not inside the thread: the job outlives the request, and the
        # config it was started with is the one it should run under.
        _token = cls._github_token(cfg)

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
            # A recursive import of a source that publishes an archive never walks: four
            # hundred folders is four hundred requests, and the allowance is sixty an hour.
            result = cls._zip_first(cfg, url, recursive)
            if result is None:
                result = _run_github_import(var_dir, url, recursive, _progress_cb,
                                            subdir=_import_subdir(url),
                                            skip_names=_import_skip_names(url),
                                            on_overwrite=_rec, token=_token)
                # …and a walk that did not finish — refused, or stopped at its own ceiling —
                # is finished from the same zip. Reported as one import, because that is what
                # it was.
                result = cls._finish_by_zip(cfg, url, result)
            if _rec is not None and _rec.replaced:
                result['replaced_edited'] = sorted(_rec.replaced)
            # An archive result counts in `written`/`total`; the job (and the panel polling
            # it) reads `count`. One import, one set of numbers.
            if result.get('written') is not None and result.get('count') is None:
                result['count'] = int(result.get('written') or 0)
                result['total'] = int(result.get('total') or result['count'])
                result['imported'] = [i['name'] for i in (result.get('items') or [])
                                      if i.get('written')]
                result['failed'] = []
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

    # ── Importing a vendor's archive ──────────────────────────────────────────

    @classmethod
    def import_mib_archive(cls, config: dict | None = None, on_progress=None) -> dict:
        """Download a ZIP of MIBs and compare it against what is already here.

        A vendor publishes its MIBs as one archive, and this is the other half of the known
        sources: the ones on GitHub are folders, and the ones like Synology's are a file. Both
        end up in the same tree.

        **Comparison, not overwrite.** Every MIB carries a ``LAST-UPDATED`` stamp written by
        its author, and that is what says whether the archive is newer than what is installed —
        the file's own timestamp says only when it was downloaded. Each member comes back
        labelled `new`, `updated`, `same_version`, `unchanged` or `older`, and:

        * `dry_run` reports all of that and writes nothing, which is the answer to "is it worth
          updating";
        * every member is looked at — there is no ceiling on how many files an archive may
          hold, because the one that was here answered about 2000 of LibreNMS's 4830 and
          called the rest a footnote;
        * an `older` member is **skipped** unless `force` is set. Re-importing last year's
          archive over a MIB somebody updated by hand is a silent downgrade, and the symptom
          shows up much later as an OID that stopped resolving.
        """
        import urllib.request  # noqa: PLC0415
        from lib.security.net_guard import validate_external_url  # noqa: PLC0415

        cfg = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        if not var_dir:
            return {'ok': False, 'message': 'No data directory', 'items': []}
        # Before comparing anything against the library: a file this never touched would
        # come back as a difference that no import can settle.
        cls._repair_line_endings(os.path.join(var_dir, 'snmp_mibs', 'raw'))
        url = str(cfg.get('url') or '').strip()
        subdir = str(cfg.get('subdir') or '').strip()
        # A known source can be named instead of pasting its URL, so the panel offers the
        # vendor rather than asking somebody to remember where the file lives.
        source = str(cfg.get('source') or '').strip().lower()
        if source:
            for src in _KNOWN_MIB_REPOS:
                if str(src.get('name', '')).strip().lower() == source and src.get('archive'):
                    url = str(src['archive'])
                    subdir = subdir or str(src.get('subdir') or '')
                    cfg = {**cfg, 'only': cfg.get('only') or src.get('archive_only') or ''}
                    break
        if not url:
            return {'ok': False, 'message': 'No archive URL', 'items': []}
        if validate_external_url(url):
            return {'ok': False, 'message': 'Refused URL', 'items': []}
        subdir = _safe_archive_subdir(subdir)

        dry_run = _truthy_import(cfg.get('dry_run'))
        force = _truthy_import(cfg.get('force'))
        # The folder INSIDE the archive that is wanted, when the archive is not a MIB archive
        # at all: a whole repository zip is the way to import from GitHub without spending an
        # API request per folder, and of the twenty thousand files in one, the MIBs are under
        # a single path.
        only = str(cfg.get('only') or '').strip().strip('/')

        _say = on_progress if callable(on_progress) else (lambda *_a: None)
        _cache = _archive_cache_dir(var_dir)
        _fresh = _truthy_import(cfg.get('redownload', False)) and 'redownload' in cfg
        path, err, from_cache = _download_archive(
            url, _MAX_ARCHIVE_BYTES, cache_dir=_cache, fresh=_fresh,
            on_progress=lambda done, total: _say('downloading', done, total))
        if path is None:
            return {'ok': False, 'message': err, 'items': []}

        raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
        items, written, skipped = [], 0, 0
        found = 0
        try:
            with zipfile.ZipFile(path) as zf:
                members = [m for m in zf.infolist()
                           if not m.is_dir() and _looks_like_mib_file(os.path.basename(m.filename))]
                # The wrapper first — `librenms-master/` — because the folder asked for is a
                # path in the REPOSITORY and knows nothing about how the zip was named.
                strip = _archive_wrapper(members)
                if only:
                    _pref = f'{only}/'
                    members = [m for m in members
                               if _member_inner(m, strip).startswith(_pref)]
                    strip = f'{strip}/{only}'.strip('/')
                found = len(members)
                # Every member is a file read off the disk and compared, so a vendor
                # library is thousands of them: what phase it is in and how far it has got
                # are the two things anybody watching wants.
                _phase = 'comparing' if dry_run else 'importing'
                # "The content differs" is a claim, and the row could not back it up: same
                # module, same LAST-UPDATED, and no way to see what the difference was. The
                # diff is free here — both texts are already in hand — and capped, because
                # four thousand of them is a payload nobody asked for.
                _diffs = 0
                for _i, member in enumerate(members):
                    _say(_phase, _i, len(members))
                    row = cls._archive_member(zf, member, raw_dir, subdir, dry_run, force,
                                              strip, want_diff=dry_run and _diffs < _MAX_DIFFS)
                    if row.get('diff'):
                        _diffs += 1
                    items.append(row)
                    if row.get('written'):
                        written += 1
                    elif row['state'] in ('older', 'rejected'):
                        skipped += 1
        except zipfile.BadZipFile:
            # A kept copy that will not open is not an answer, it is a dead end: the button
            # would report "Not a ZIP archive" for ever with nothing to press. Thrown away and
            # fetched again, once — if the SERVER is serving something that is not a zip, the
            # second attempt says so and stops.
            if from_cache:
                _rm_quiet(path)
                return cls.import_mib_archive({**cfg, 'redownload': True}, on_progress)
            return {'ok': False, 'message': 'Not a ZIP archive', 'items': []}
        finally:
            # The cached copy is NOT deleted: the import that usually follows a comparison is
            # about to want exactly this file. Anything that did not end up in the cache is —
            # it is nobody's, and 86 MB of nobody's is what filled a disk with 93 of them.
            # A `.part` is a download that never became a cache entry — the rename failed,
            # or there was no cache to file it in. Either way it is nobody's.
            if path and (path.endswith('.part') or not _cache):
                _rm_quiet(path)
            _prune_archive_cache(_cache)

        if written:
            _mib_resolver.invalidate_cache()
        items.sort(key=lambda i: i['name'])
        changed = [i for i in items if i['state'] in ('new', 'updated')]
        # Counted apart, and said out loud: "0 newer" with twenty rows on screen reads as a
        # report that contradicts itself.
        same_ver = [i for i in items if i['state'] == 'same_version']
        return {
            'ok':       True,
            'items':    items,
            'total':    len(items),
            'written':  written,
            'skipped':  skipped,
            'changed':  len(changed),
            'dry_run':  dry_run,
            'subdir':   subdir,
            'only':     only,
            # How many members of the archive were MIB-shaped. Every one of them is
            # looked at now; the number is still worth answering, because "4830 seen, 7
            # differ" is a different report from "7 differ".
            'found':    found,
            'same_version': len(same_ver),
            # Why it was instant. Comparing and then importing is the same archive twice, and
            # the second time it is not downloaded at all.
            'cached':   from_cache,
            'message':  ((f'{len(changed)} of {len(items)} MIB(s) newer than installed'
                          if dry_run else f'{written} MIB file(s) imported')
                         + (f' — {len(same_ver)} differ with no new version' if same_ver else '')),
        }

    @classmethod
    def import_mib_archive_start(cls, config: dict | None = None) -> dict:
        """Start the archive import in the background and return a job_id to poll.

        The same shape as the GitHub import, and for the same reason: the work is a download
        of tens of megabytes followed by thousands of comparisons, and a request that answers
        when all of it is over is a screen with nothing to say for a minute or two.
        """
        cfg = config or {}
        if not str(cfg.get('__var_dir__') or '').strip():
            return {'ok': False, 'message': 'No data directory'}

        job_id = uuid.uuid4().hex[:12]
        _archive_jobs[job_id] = {'done': False, 'phase': 'downloading',
                                 'completed': 0, 'total': 0, 'result': None}

        def _progress_cb(phase, completed, total):
            job = _archive_jobs.get(job_id)
            if job is not None:
                job['phase'], job['completed'], job['total'] = phase, completed, total

        def _run():
            try:
                result = cls.import_mib_archive(cfg, on_progress=_progress_cb)
            except Exception as exc:  # pylint: disable=broad-except
                result = {'ok': False, 'message': str(exc), 'items': []}
            job = _archive_jobs.get(job_id)
            if job is not None:
                job.update({'done': True, 'result': result})

        threading.Thread(target=_run, daemon=True).start()
        return {'ok': True, 'job_id': job_id, 'done': False}

    @classmethod
    def import_mib_archive_status(cls, config: dict | None = None) -> dict:
        """Poll an archive import started by *_start; the finished report arrives here."""
        job_id = str((config or {}).get('job_id') or '').strip()
        if job_id not in _archive_jobs:
            return {'ok': False, 'message': 'Job not found or already collected'}
        job = dict(_archive_jobs[job_id])
        if not job.get('done'):
            job.pop('result', None)
            return {'ok': True, **job}
        del _archive_jobs[job_id]          # cleanup on the first done-read
        return {**(job.get('result') or {}), 'done': True}

    @classmethod
    def _archive_member(cls, zf, member, raw_dir, subdir, dry_run, force, strip='',
                        want_diff=False) -> dict:
        """One file out of the archive: what it is, what is here, and what was done."""
        name = os.path.basename(member.filename)
        # The archive's own folders are kept — a vendor lays its MIBs out for a reason — under
        # the source's subdirectory, so two vendors shipping an ENTITY-MIB stay two files.
        # Each segment is sanitised rather than rejected: Synology's archive has a folder
        # literally called "MIB files", and refusing a space would refuse the whole vendor.
        inner = os.path.dirname(member.filename).replace('\\', '/').strip('/')
        if strip and (inner == strip or inner.startswith(strip + '/')):
            inner = inner[len(strip):].strip('/')
        parts = [p for p in ([subdir] + [_safe_archive_subdir(seg)
                                         for seg in inner.split('/')]) if p]
        rel = _safe_mib_relpath('/'.join(parts + [name]), 'raw')
        row = {'name': '/'.join(parts + [name]), 'state': 'rejected', 'written': False,
               'version': '', 'installed': '', 'size': int(member.file_size or 0)}
        # WHY, because "rejected" on its own is a word, not an answer — and the three
        # reasons want three different things done about them.
        if not rel:
            row['reason'] = 'name'
            return row
        if member.file_size > _MAX_MEMBER_BYTES:
            row['reason'] = 'too_big'
            row['limit'] = _MAX_MEMBER_BYTES
            row['preview'] = _member_head(zf, member)
            return row
        dest = _confined_path(raw_dir, *rel.split('/'))
        if not dest:
            row['reason'] = 'path'
            return row
        row['name'] = rel
        try:
            incoming = zf.read(member).decode('utf-8', errors='replace')
        except Exception:  # pylint: disable=broad-except
            row['reason'] = 'unreadable'
            return row
        # A vendor archive carries its own readme, its licence and sometimes a spreadsheet.
        # None of them is a MIB, and the name is not what settles that.
        if not _is_mib_source(incoming):
            row['state'] = 'not_a_mib'
            # The file itself, so the call can be checked instead of trusted. A vendor
            # archive carries readmes and licences — and it also carries MIBs written in a
            # shape a detector had not met, which is how this one was found.
            row['preview'] = _head_lines(incoming)
            return row

        row['version'] = _mib_last_updated(incoming)
        # As CONTENT, not as bytes: the same MIB shipped with CRLF and stored with LF is the
        # same MIB, and comparing the bytes said "newer" about every one of them, forever.
        current = _text_of(dest)

        if current is None:
            row['state'] = 'new'
        elif current == _normalized(incoming):
            row['state'] = 'unchanged'
        else:
            row['installed'] = _mib_last_updated(current)
            # Both stamped and the installed one is newer: this archive is behind. Comparing
            # the strings works because the format sorts (YYYYMMDDHHMMZ), and an unstamped
            # file cannot be compared at all — a difference is then simply a difference.
            if row['version'] and row['installed'] and row['installed'] > row['version']:
                row['state'] = 'older'
            elif row['version'] and row['installed'] == row['version']:
                # The content differs and the author calls it the same revision. Saying
                # "updated" there claims something nobody claimed: 201505011057Z →
                # 201505011057Z is not an update, whatever it is. It is still imported — a
                # vendor does re-cut a MIB without touching the stamp — but the row says what
                # it actually is, and the summary does not count it as newer.
                row['state'] = 'same_version'
            else:
                row['state'] = 'updated'
            # What the difference IS. The row claimed one and could not back it up: same
            # module, same date, and no way to see what had changed. Free here — both texts
            # are already in hand — and asked for by the caller, because the budget belongs
            # to the report and not to one member of it.
            if want_diff:
                _d = _unified_diff(current, 'installed', _normalized(incoming), 'archive')
                row['diff'] = _d['diff']
                row['diff_truncated'] = _d['truncated']

        if dry_run or row['state'] == 'unchanged':
            return row
        if row['state'] == 'older' and not force:
            return row
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'w', encoding='utf-8', newline='') as fh:
                fh.write(incoming)
            row['written'] = True
        except OSError as exc:
            row['state'] = 'rejected'
            row['error'] = str(exc)
        return row
