#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keeping one copy, whatever the counter says.

"Keep this one" — the copy taken before a migration, the one that is known good, the last one
from before an incident. Retention cannot express it: the buckets answer *how much history*,
and the two floors answer *never leave the task with nothing*. None of them can say "this
particular archive, whatever the calendar decides".

Its own module because it is a PROTOCOL and not a flag: a sidecar file beside the archive, a
damaged marker that still counts as locked, and a guard that has to hold for every caller
rather than only for the button that asks.
"""

from __future__ import annotations

import json
import os
import time

from lib.debug.debug_level import DebugLevel

from .archive import archive_path, _log


# ── The lock ─────────────────────────────────────────────────────────────────
#
# "Keep this one" — the copy taken before a migration, the one that is known good, the last one
# from before an incident. Retention cannot express it: the buckets answer *how much history*,
# and the two floors answer *never leave the task with nothing*. None of them can say "this
# particular archive, whatever the calendar decides".
#
# A SIDECAR FILE and not a column. `list_backups` reads the directory precisely so there is no
# second source of truth about files somebody can copy in, move out or delete with the panel
# stopped — and a lock kept in a table would be exactly that, with the failure mode that the row
# says "protected" about an archive that is no longer there. The flag lives beside the thing it
# protects, like the `.sha256` does, and moves with it.

LOCK_SUFFIX = '.lock'


def read_lock(archive_path: str) -> dict | None:
    """Who locked the archive and when, or None when it is not locked.

    An unreadable or half-written marker still counts as LOCKED — with an empty author rather
    than an exception. The file's existence is the flag; its contents are a courtesy, and
    treating a damaged courtesy as "not protected" is how a lock fails in the one direction it
    must not.
    """
    try:
        with open(archive_path + LOCK_SUFFIX, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {} if os.path.isfile(archive_path + LOCK_SUFFIX) else None


def is_locked(var_dir: str, name: str, backup_dir: str = '') -> bool:
    path = archive_path(var_dir, name, backup_dir)
    return bool(path) and os.path.isfile(path + LOCK_SUFFIX)


def set_lock(var_dir: str, name: str, locked: bool, actor: str = '',
             backup_dir: str = '') -> dict:
    """Protect *name* from being deleted, or stop protecting it.

    Answers `{'ok': …}` rather than raising: the caller is a route, and a read-only backups
    directory is a thing an operator can produce — it should read as "could not lock" and not as
    a traceback on a copy that is otherwise fine.
    """
    path = archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        return {'ok': False, 'message': 'backup not found'}
    try:
        if locked:
            with open(path + LOCK_SUFFIX, 'w', encoding='utf-8') as fh:
                json.dump({'by': str(actor or ''),
                           'at': time.strftime('%Y-%m-%d %H:%M:%S')}, fh)
        elif os.path.isfile(path + LOCK_SUFFIX):
            os.remove(path + LOCK_SUFFIX)
    except OSError as exc:
        _log(f'> Backup > lock >> {name!r} could not be '
             + ('locked' if locked else 'unlocked') + f': {exc}', DebugLevel.error)
        return {'ok': False, 'message': str(exc)}
    _log(f'> Backup > lock >> {name!r} ' + ('locked' if locked else 'unlocked')
         + f' by {actor or "?"}')
    return {'ok': True, 'locked': bool(locked)}
