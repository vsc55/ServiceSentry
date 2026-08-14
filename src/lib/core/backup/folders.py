#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The folder picker behind the backup-directory setting.

**Not backup code**, and that is why it is not in one of the files that is. It opens no
archive, reads no manifest and touches no connector: it walks directories so a person can
choose one, and its routes are gated on `config_edit` — the permission that edits the field —
rather than on anything named `backup_*`.

It lives in this package because that field is the only thing it serves, and a shared
"browse the filesystem" utility is a bigger promise than anybody asked for.
"""

from __future__ import annotations

import os


def list_dirs(path: str = '') -> dict:
    """The sub-directories of *path*, for the folder picker behind the backup-dir field.

    Directories ONLY — never file names. The picker's job is to choose a folder, and every
    file name it showed on the way would be information the screen did not need to do it.

    This is not a new grant. Whoever can reach it can already type any path into the setting
    and read the result back from the error message; the picker makes visible what the field
    already allowed, which is why it is gated on the same permission that edits the field and
    not on a weaker one.

    An empty *path* answers with the roots: the drive letters on Windows, ``/`` elsewhere. A
    path that cannot be read comes back as an empty list with ``readable: false`` rather than
    an error — half the folders on a machine are unreadable to the account the panel runs as,
    and each of them is an ordinary answer, not a fault.
    """
    raw = str(path or '').strip()
    if not raw:
        return {'ok': True, 'path': '', 'parent': None, 'roots': _roots(),
                'dirs': [], 'readable': True, 'writable': False}
    # Normalised before anything is done with it: `a/b/../../etc` is a path somebody typed,
    # and the answer has to be about where it actually lands.
    here = os.path.abspath(os.path.expanduser(raw))
    parent = os.path.dirname(here)
    out = {'ok': True, 'path': here, 'roots': _roots(),
           'parent': parent if parent and parent != here else None,
           'dirs': [], 'readable': False, 'writable': False}
    try:
        with os.scandir(here) as it:
            for e in sorted(it, key=lambda x: x.name.lower()):
                try:
                    if e.is_dir():
                        out['dirs'].append({'name': e.name, 'path': e.path})
                except OSError:
                    continue      # a broken link or a mount that is not there
        out['readable'] = True
        out['writable'] = os.access(here, os.W_OK)
    except OSError:
        pass
    return out


_ROOTS_CACHE: list = []


def _roots() -> list:
    """Where the picker starts. Windows has several; everything else has one.

    On Windows this asks the KERNEL for the drive bitmask instead of probing each letter with
    `os.path.exists`. Measured on a box with two network mappings, probing A–Z took **6.6
    seconds** the first time — a disconnected mapping blocks until it gives up, and the roots
    are rebuilt on every request, so every step through the folder tree paid it again. The
    bitmask is a single call with no I/O at all.

    Cached for the life of the process on top. A drive appearing is not something to rescan
    for on every click, and the picker accepts a typed path regardless.
    """
    global _ROOTS_CACHE      # pylint: disable=global-statement
    if _ROOTS_CACHE:
        return list(_ROOTS_CACHE)
    if os.name != 'nt':
        # Not one button. Unix has a single tree, so "/" is the only true root — and starting
        # every operator at "/" to walk down to /mnt/nas/backups is the picker being correct
        # and useless at the same time. The rest are the places a backup actually goes: where
        # removable and network volumes are mounted, plus the account's home. Listed only when
        # they exist, so a container without /media does not show a button that leads nowhere.
        _ROOTS_CACHE = ['/'] + [d for d in ('/mnt', '/media', '/srv', '/opt', '/var',
                                            os.path.expanduser('~'))
                                if d and d != '/' and os.path.isdir(d)]
        return list(_ROOTS_CACHE)
    try:
        import ctypes      # noqa: PLC0415 — Windows only
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        _ROOTS_CACHE = [chr(65 + i) + ':' + os.sep for i in range(26) if mask >> i & 1]
    except Exception:      # pylint: disable=broad-except
        # No ctypes, or a Windows that will not answer: fall back to the slow probe once
        # rather than showing no roots at all.
        import string      # noqa: PLC0415
        _ROOTS_CACHE = [d + ':' + os.sep for d in string.ascii_uppercase
                        if os.path.exists(d + ':' + os.sep)]
    return list(_ROOTS_CACHE)


def make_dir(parent: str, name: str) -> dict:
    """Create *name* inside *parent*, for the picker's "new folder" button.

    The name is a single component and is checked as one: `..`, a separator or a drive letter
    is not a folder name, it is a way to create a directory somewhere else. Rejected outright
    rather than sanitised — silently turning `../x` into `x` would create a folder the operator
    did not ask for and did not see.

    Creating one where the panel cannot write is a normal outcome (the account it runs as is
    usually not root), so it comes back as a message, not an exception.
    """
    base = str(parent or '').strip()
    leaf = str(name or '').strip()
    if not base or not os.path.isdir(base):
        return {'ok': False, 'message': 'parent folder does not exist'}
    if not leaf or leaf in ('.', '..') or os.sep in leaf or (os.altsep and os.altsep in leaf) \
            or ':' in leaf:
        return {'ok': False, 'message': 'invalid folder name'}
    target = os.path.join(base, leaf)
    if os.path.exists(target):
        return {'ok': False, 'message': 'that folder already exists'}
    try:
        os.mkdir(target)
    except OSError as exc:
        return {'ok': False, 'message': str(exc)}
    return {'ok': True, 'path': target}
