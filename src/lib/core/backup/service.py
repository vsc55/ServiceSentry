#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The shelf: which copies exist, how big, from which build, and removing one.

What was one 1180-line module is now the domain it always described — `archive.py` (where a
copy lives and how it is laid out), `parts.py` (what one can hold), `create.py`, `restore.py`,
`verify.py`, `locks.py` and `folders.py`. What stayed here is the shelf itself: the list, and
the two operations that are about an archive as a FILE rather than as data.

Read from DISK rather than from a table of its own. A catalogue in the database would be a
second source of truth about files somebody can copy in, move out or delete with the panel
stopped — and the day the two disagreed, the one that lies is the one that says a backup
exists.

Flask-free, like everything else in the package: the routes hand it paths and it answers with
data.
"""

from __future__ import annotations

import io
import os
import re

from lib.util.tools import fmt_bytes

from .archive import archive_path, backups_dir, read_manifest
from .locks import read_lock, LOCK_SUFFIX


# The build inside `0.0.1+build.58`. The semantic part deliberately stays at 0.0.1, so it is
# the counter that says which of two copies is the later one.
_BUILD_RE = re.compile(r'\+build\.(\d+)\b')


def version_relation(made_with: str, running: str) -> str:
    """How a copy's version stands to this install: same / older / newer / unknown.

    Nothing is REFUSED on the strength of this — the schema moves on almost every build, and a
    panel that turned down "old" copies would be useless on the one day it is needed. It exists
    so the person about to overwrite their install knows which way they are jumping: restoring a
    copy from a LATER build drops the columns this schema does not have yet, quietly, and that
    is a decision rather than an accident.
    """
    made_with, running = str(made_with or ''), str(running or '')
    if not made_with or not running:
        return 'unknown'
    if made_with == running:
        return 'same'
    a, b = _BUILD_RE.search(made_with), _BUILD_RE.search(running)
    if not a or not b:
        return 'unknown'
    return 'newer' if int(a.group(1)) > int(b.group(1)) else 'older'


def list_backups(var_dir: str, backup_dir: str = '', app_version: str = '') -> list:
    """Every readable archive in the backups directory, newest first.

    Read from DISK rather than from a table of its own. A catalogue in the database would be a
    second source of truth about files somebody can copy in, move out or delete with the panel
    stopped — and the day the two disagreed, the one that lies is the one that says a backup
    exists.
    """
    root = backups_dir(var_dir, backup_dir)
    if not os.path.isdir(root):
        return []
    out = []
    for fn in sorted(os.listdir(root)):
        if not fn.endswith('.zip'):
            continue
        full = os.path.join(root, fn)
        man = read_manifest(full)
        if man is None:
            continue                       # not ours, or written half way
        try:
            st = os.stat(full)
        except OSError:
            continue
        man['name'] = os.path.splitext(fn)[0]
        man['size'] = st.st_size
        # Formatted HERE, by the formatter the rest of the panel already uses. A JS version
        # would be a second answer to "bytes as a human reads them" — and `fmt_bytes` scales
        # in 1024s, so one counting in 1000s prints a different size for the same file
        # depending on which side of the wire did it.
        man['size_h'] = fmt_bytes(st.st_size)
        man['mtime'] = int(st.st_mtime)
        # Which way the version jumps, worked out HERE because the running version is
        # something only the caller knows — the service is handed it, like `create_backup` is,
        # rather than importing it and becoming one more thing that has to know where it lives.
        man['version_rel'] = version_relation(man.get('app_version'), app_version)
        # Protected from deletion — by retention and by the button alike. Read from the sidecar
        # beside the file, which is what makes it survive the panel being stopped, the folder
        # being moved and the copy being carried to another machine.
        lock = read_lock(full)
        man['locked'] = lock is not None
        man['lock_by'] = (lock or {}).get('by', '')
        man['lock_at'] = (lock or {}).get('at', '')
        out.append(man)
    out.sort(key=lambda m: m.get('mtime', 0), reverse=True)
    return out


def backup_exists(var_dir: str, name: str, backup_dir: str = '') -> bool:
    """Is there an archive by that name?

    Asked BEFORE a restore is started in the background, so "there is no such copy" stays an
    answer to the request that asked for it. Discovering it inside the job would put a progress
    bar on screen for something that was never going to happen.
    """
    path = archive_path(var_dir, name, backup_dir)
    return bool(path) and os.path.isfile(path)


def delete_backup(var_dir: str, name: str, backup_dir: str = '') -> bool:
    """Remove an archive and the files that describe it.

    **A locked copy is refused here**, not only in the route that asks. Retention already skips
    them, so this is the second of two guards — and it is the one that holds if a caller ever
    computes the doomed list some other way. A lock that only the UI honoured would be a lock
    that protects nothing on the day it matters.

    The sidecars go WITH the archive. Left behind, the `.lock` one is the dangerous half: a
    later copy taking the same name would be born protected, never pruned, and nothing on screen
    would explain why.
    """
    path = archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        return False
    if os.path.isfile(path + LOCK_SUFFIX):
        return False
    try:
        os.remove(path)
    except OSError:
        return False
    for extra in (path + '.sha256',):
        try:
            os.path.isfile(extra) and os.remove(extra)
        except OSError:
            pass
    return True


def archive_bytes(var_dir: str, name: str, backup_dir: str = '') -> io.BytesIO | None:
    """The archive as a stream, for the download endpoint."""
    path = archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'rb') as fh:
            return io.BytesIO(fh.read())
    except OSError:
        return None
