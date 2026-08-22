#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: edited MIB sources, and every version of them.
#
"""A MIB you can fix, and take back.

Vendors ship broken MIBs. SYNOLOGY-SMB-MIB is one: every descriptor in it starts with an
uppercase letter, which in SMI is a type reference and not a value, so the parser stops at the
first table definition and the file has never compiled anywhere. There is nothing to do about
that from here except let somebody correct it — and a correction you cannot undo is one nobody
dares make, which is why the history is the feature and the editing is only the button.

**The file on disk stays the working copy.** pysmi compiles files: it is handed directories
and reads what is in them, and an edit that lived only in a database would be an edit nothing
ever compiled. So a save writes the file *and* records the version. The first save also
records what was on disk before it as version 1, so "back to what the vendor shipped" is
always one click away — that is what "no version stored ⇒ the original" means here: until
somebody edits, there is nothing stored, and the moment they do, the original is kept.

Restoring never rewrites history: it writes the old content out as a NEW version. A history
that can be edited answers a different question from the one it is asked.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from lib.db.module_tables import module_table
from lib.db.schema import Column, Index

MODULE = 'snmp'

# One row per saved version. `content` is the whole file: MIBs are tens of kilobytes and a
# diff-based store would buy space at the price of being able to read a version on its own,
# which is the only thing anybody wants from it.
# ── Why the table is still called ``mod_snmp_mib_versions`` ───────────────────────────────────
# The code moved to the core; the table did not, and that is deliberate. A table name is a
# fact about DATA — every installation already has rows under this one — while where the code
# lives is a fact about the source tree, and renaming one because the other moved would spend
# a migration on tidiness. It buys nothing a reader of this file cannot get from this comment,
# and it can go wrong on a database this project does not own.
#
# ``module_table`` is kept for the same reason: it is what produces that exact name. If the
# name is ever changed it should be for a reason of its own, with the migration written and
# tested on all three engines.
SCHEMA = module_table(MODULE, 'mib_versions', (
    Column('uid',        'TEXT',    primary_key=True),
    # The MIB module name — what pysmi compiles by, and what survives the file being moved
    # from one imported folder to another.
    Column('mib',        'TEXT',    nullable=False, default="''"),
    # …and where it was when this version was written, which is what a save writes back to.
    Column('relpath',    'TEXT',    nullable=False, default="''"),
    Column('version',    'INTEGER', nullable=False, default='1'),
    Column('content',    'TEXT',    nullable=False, default="''"),
    Column('size',       'INTEGER', nullable=False, default='0'),
    Column('sha',        'TEXT',    nullable=False, default="''"),
    # The sha of what this version REPLACED. A version is an update on a base, and which base
    # is the question the numbers cannot answer: v2 is "the fix", but the fix to WHAT — and
    # when a vendor ships a new release the useful thing is not v2's content, it is the change
    # v1 → v2, which is only a change if you know it started at v1.
    Column('parent_sha', 'TEXT',    nullable=False, default="''"),
    Column('author',     'TEXT',    nullable=False, default="''"),
    Column('note',       'TEXT',    nullable=False, default="''"),
    Column('created_at', 'REAL',    nullable=False, default='0'),
), indexes=(Index('mib_versions_by_mib', ('mib', 'version')),))

_T = SCHEMA.name

# A MIB is tens of kilobytes; a megabyte is already not a MIB, and the editor is not a place
# to paste a disk image into the database.
MAX_SOURCE_BYTES = 1024 * 1024
# How many versions of ONE MIB are kept. Beyond this the oldest go — except version 1, which
# is the vendor's own and the only one that cannot be reconstructed from anywhere else.
MAX_VERSIONS = 30

# A note says what a change was for. It is a line in a list, so it is capped like one — a
# paragraph in that column pushes the buttons beside it off the row.
MAX_NOTE_CHARS = 200

NOTE_ORIGINAL = 'original'


def sha_of(text: str) -> str:
    return hashlib.sha256((text or '').encode('utf-8', 'replace')).hexdigest()


class MibVersionStore:
    """Every saved version of every edited MIB, on the shared connector.

    On the general database on purpose: a deployment with a web container and a worker
    container shares one, and a MIB corrected in the panel has to be the MIB the worker
    compiles. A file beside the MIBs would be per-container.
    """

    def __init__(self, db) -> None:
        self._db = db
        self._db.reconcile_table(SCHEMA)

    # ── Reading ──────────────────────────────────────────────────────────────
    def versions(self, mib: str) -> list[dict]:
        """Every version of *mib*, newest first, WITHOUT the content.

        The list is a list: shipping thirty copies of a hundred-kilobyte file to draw a
        dropdown is how a helpful feature becomes the reason a modal takes a second to open.
        """
        if not mib:
            return []
        rows = self._db.fetchall(
            f'SELECT uid, version, size, sha, author, note, created_at, relpath, parent_sha '
            f'FROM {_T} WHERE mib = ? ORDER BY version DESC', (mib,)) or []
        out = [{'uid': r[0], 'version': int(r[1]), 'size': int(r[2] or 0), 'sha': r[3] or '',
                'author': r[4] or '', 'note': r[5] or '', 'created_at': float(r[6] or 0),
                'relpath': r[7] or '', 'parent_sha': r[8] or ''} for r in rows]
        # …resolved to a version number, which is the only form anybody reads. A parent that
        # was deleted, or that predates this column, simply has none: an empty answer is the
        # right one and a wrong number would not be.
        by_sha = {v['sha']: v['version'] for v in out}
        for v in out:
            v['parent'] = by_sha.get(v['parent_sha'], 0)
        return out

    def current_versions(self) -> dict:
        """``{mib: highest version}`` for every MIB that has any.

        One query for the whole list: the manager draws two hundred rows, and a version
        lookup per row is two hundred round trips to answer a question about a badge.
        """
        rows = self._db.fetchall(f'SELECT mib, MAX(version) FROM {_T} GROUP BY mib') or []
        return {r[0]: int(r[1] or 0) for r in rows if r[0]}

    def content(self, uid: str) -> str | None:
        if not uid:
            return None
        row = self._db.fetchone(f'SELECT content FROM {_T} WHERE uid = ?', (uid,))
        return row[0] if row else None

    def version_with(self, mib: str, content: str) -> int:
        """The version number whose content is exactly *content*, or 0.

        The sha has been stored since the first row and never read. It is what stops the same
        bytes being filed twice: restore the fix, re-import the vendor, restore the fix
        again — four versions holding two distinct files, and at the cap it is the ones that
        mean something that get pushed out.
        """
        if not mib:
            return 0
        row = self._db.fetchone(
            f'SELECT version FROM {_T} WHERE mib = ? AND sha = ? ORDER BY version ASC',
            (mib, sha_of(content)))
        return int(row[0]) if row else 0

    def has_any(self, mib: str) -> bool:
        return bool(mib) and bool(
            self._db.fetchone(f'SELECT 1 FROM {_T} WHERE mib = ?', (mib,)))

    # ── Writing ──────────────────────────────────────────────────────────────
    def add(self, mib: str, relpath: str, content: str, *,
            author: str = '', note: str = '', parent: str = '') -> dict:
        """Record one version and return its row (without the content).

        Version numbers are per MIB and only ever go up, including across a delete of the
        file and a fresh import: they name a point in this MIB's history, and reusing one
        would make two different files answer to the same name.
        """
        now = time.time()
        with self._db.transaction():
            row = self._db.fetchone(
                f'SELECT COALESCE(MAX(version), 0) FROM {_T} WHERE mib = ?', (mib,))
            version = int((row and row[0]) or 0) + 1
            uid = str(uuid.uuid4())
            self._db.execute(
                f'INSERT INTO {_T} (uid, mib, relpath, version, content, size, sha, author, '
                f'note, created_at, parent_sha) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (uid, mib, relpath, version, content, len(content or ''),
                 sha_of(content), author or '', (note or '')[:MAX_NOTE_CHARS], now,
                 parent or ''))
            self._prune(mib)
        return {'uid': uid, 'version': version, 'size': len(content or ''),
                'sha': sha_of(content), 'author': author or '', 'parent_sha': parent or '',
                'note': (note or '')[:MAX_NOTE_CHARS], 'created_at': now, 'relpath': relpath}

    def drop_all(self, mib: str) -> int:
        """Delete every version of *mib*. How many went."""
        if not mib:
            return 0
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T} WHERE mib = ?', (mib,))
        n = int((row and row[0]) or 0)
        if n:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE mib = ?', (mib,))
        return n

    def drop(self, mib: str, uid: str) -> dict | None:
        """Delete one version. Returns the row that went, or None.

        Scoped to *mib* on purpose: the uid arrives from a browser, and a delete that accepts
        any uid is a delete of somebody else's history from a screen about this one.
        """
        if not mib or not uid:
            return None
        row = self._db.fetchone(
            f'SELECT version, note FROM {_T} WHERE uid = ? AND mib = ?', (uid, mib))
        if not row:
            return None
        with self._db.transaction():
            self._db.execute(f'DELETE FROM {_T} WHERE uid = ? AND mib = ?', (uid, mib))
        return {'uid': uid, 'version': int(row[0]), 'note': row[1] or ''}

    def _prune(self, mib: str) -> None:
        """Drop the oldest versions past the cap, never version 1.

        The vendor's own is the one version that cannot be got back from anywhere: the file
        it came from has been overwritten by every save since.
        """
        rows = self._db.fetchall(
            f'SELECT uid FROM {_T} WHERE mib = ? AND version > 1 ORDER BY version DESC',
            (mib,)) or []
        extra = rows[MAX_VERSIONS - 1:]
        for r in extra:
            self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (r[0],))
