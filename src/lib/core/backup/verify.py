#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checking a copy against its own checksums.

Two questions with two failure modes, which is the whole reason both digests exist — see
:func:`verify_backup`. Its own module because it is also its own PERMISSION: walking every
member of a multi-gigabyte archive and hashing it is minutes of disk and CPU, not reading a
list.
"""

from __future__ import annotations

import hashlib
import os
import zipfile

from lib import APP_NAME

from .archive import archive_path, file_sha256, read_manifest


def verify_backup(var_dir: str, name: str, backup_dir: str = '') -> dict:
    """Check a copy against its own checksums.

    Two questions, and they fail differently:

    * **The file** — its digest against the `.sha256` sidecar. This is the one that catches a
      truncated download, a bad disk or a half-finished transfer.
    * **The contents** — every member against the manifest. This catches an archive that is
      intact as a file but whose data was altered, and it is the only one that can be asked at
      all when the sidecar was lost in the move.

    A missing sidecar is reported, not treated as a failure: copies written before checksums
    existed have none, and calling those corrupt would be the check lying.
    """
    path = archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        return {'ok': False, 'message': 'backup not found'}
    man = read_manifest(path)
    if man is None:
        return {'ok': False, 'message': f'not a {APP_NAME} backup'}

    out = {'ok': True, 'file': 'missing', 'members': 0, 'bad': []}
    side = path + '.sha256'
    if os.path.isfile(side):
        try:
            with open(side, encoding='utf-8') as fh:
                want = fh.read().split()[0].strip()
            out['file'] = 'ok' if want == file_sha256(path) else 'bad'
        except (OSError, IndexError):
            out['file'] = 'unreadable'
    expected = man.get('sha256') or {}
    if not expected:
        out['members'] = 0
        out['ok'] = out['file'] != 'bad'
        return out
    try:
        with zipfile.ZipFile(path) as zf:
            for member, want in expected.items():
                try:
                    got = hashlib.sha256(zf.read(member)).hexdigest()
                except KeyError:
                    out['bad'].append({'member': member, 'why': 'missing'})
                    continue
                if got != want:
                    out['bad'].append({'member': member, 'why': 'changed'})
                out['members'] += 1
    except (OSError, zipfile.BadZipFile) as exc:
        return {'ok': False, 'message': str(exc)}
    out['ok'] = not out['bad'] and out['file'] != 'bad'
    return out
