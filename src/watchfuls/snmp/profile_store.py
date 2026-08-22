#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: the part of the profile catalogue written in the panel.
#
"""The catalogue an installation writes for itself.

Three things reach :func:`.profiles.catalog`, and each is where it is for a reason:

* **shipped** — JSON files in the module. They are reviewed in commits, travel with the
  release, and a package upgrade replaces them;
* **files** under ``<var_dir>/snmp_profiles`` — an installation's own, edited on the machine.
  They survive an upgrade, and they are how somebody works who would rather use an editor;
* **the database, through this module** — everything written in the panel.

The last one is what this file is, and the reason it is the database and not a fourth folder
is not tidiness: a deployment with a web container and a worker container **shares the
database and not the disk**. A profile written in the panel that the sampler could not read
would be a device assigned something that measures nothing, with no error anywhere. It rides
the database backup for the same reason.

**One table for two things that are one thing.** A *group* is an entry whose members are other
entries' ids; a *profile* is an entry whose members are OIDs. Everything downstream already
treats them as one kind — :func:`.profiles.normalise` validates either, the catalogue is one
map, the screen is one list, the sampler resolves ids — so storing them apart would be the one
place in the product that insisted they are different. What a row holds is the **document**
itself, exactly as the shipped files hold theirs.

**The id is not editable.** Servers reference an entry by id, so renaming one would not rename
anything: it would leave every device that used it pointing at nothing. The *name* is what
people read and it can change at any time; the id is chosen once.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata

from lib.db.module_tables import module_table
from lib.db.schema import Column

MODULE = 'snmp'

# One row per entry, and the entry itself is a JSON document. Not a column per field: what a
# profile IS is decided by `profiles.normalise`, which reads a document — a schema here would
# be a second declaration of the same shape, and the two would disagree the first time one of
# them gained a field.
SCHEMA = module_table(MODULE, 'catalog', (
    # The catalogue id, and the primary key because that IS the identity: it is what a server
    # stores, and two rows answering to one id is two answers to "what does this device
    # measure".
    Column('pid',        'TEXT', primary_key=True),
    Column('body',       'TEXT', nullable=False, default="'{}'"),
    Column('author',     'TEXT', nullable=False, default="''"),
    Column('created_at', 'REAL', nullable=False, default='0'),
    Column('updated_at', 'REAL', nullable=False, default='0'),
))

_T = SCHEMA.name

# The same shape the rest of the catalogue demands of an id: it lands in a JSON key, a config
# value and a URL fragment.
ID_RE = re.compile(r'^[a-z][a-z0-9_]*$')

# A name is a line in a list and a chip in a field; a description is the sentence under it.
MAX_LABEL_CHARS = 80
MAX_DESC_CHARS = 200
# How many profiles one group may hold. Far above any real family (Synology, the largest
# shipped, is fifteen) and low enough that a form cannot be used to write a megabyte.
MAX_MEMBERS = 100
# …and how many metrics one profile may declare. Every one of them is at least one SNMP round
# trip per cycle against a real device.
MAX_METRICS = 200


def slug(text: str) -> str:
    """An id proposed from a name — what the form fills in while somebody types.

    Only a proposal: the id is a separate field and the person can say otherwise. Deriving it
    silently and offering no way to see it is how ids end up being apologised for later.

    Accents are folded rather than replaced, because the alternative is what somebody reads
    when they name a group "Cámaras IP" and the form offers them `c_maras_ip`. The form has a
    mirror of this in JavaScript (`_snmpGrpSlug`); this is the shape it mirrors.
    """
    flat = unicodedata.normalize('NFD', str(text or '').strip().lower())
    flat = ''.join(c for c in flat if not unicodedata.combining(c))
    out = re.sub(r'[^a-z0-9]+', '_', flat).strip('_')
    if not out or not out[0].isalpha():
        out = 'g_' + out if out else ''
    return out[:48]


class CatalogStore:
    """Everything this installation wrote in the panel, on the shared connector."""

    def __init__(self, db) -> None:
        self._db = db
        self._db.reconcile_table(SCHEMA)

    # ── Reading ──────────────────────────────────────────────────────────────
    @staticmethod
    def _row(r) -> dict:
        try:
            body = json.loads(r[1] or '{}')
        except ValueError:
            body = {}                  # a row somebody hand-edited costs its own entry
        if not isinstance(body, dict):
            body = {}
        body['id'] = r[0] or ''        # the column is the identity, not what the blob claims
        return {'id': body['id'], 'body': body, 'author': r[2] or '',
                'created_at': float(r[3] or 0), 'updated_at': float(r[4] or 0)}

    def all(self) -> list[dict]:
        """Every entry, by id. The whole set, always: it is a handful of small documents and
        the catalogue is assembled from them in one go."""
        rows = self._db.fetchall(
            f'SELECT pid, body, author, created_at, updated_at FROM {_T} ORDER BY pid') or []
        return [self._row(r) for r in rows]

    def get(self, pid: str) -> dict | None:
        if not pid:
            return None
        r = self._db.fetchone(
            f'SELECT pid, body, author, created_at, updated_at FROM {_T} WHERE pid = ?',
            (pid,))
        return self._row(r) if r else None

    def documents(self) -> list[dict]:
        """The bodies, in the shape :func:`.profiles.catalog` takes.

        The store stays the only thing that knows what a row looks like, and the catalogue
        stays the only thing that knows what a profile looks like.
        """
        return [e['body'] for e in self.all()]

    # ── Writing ──────────────────────────────────────────────────────────────
    def save(self, pid: str, body: dict, *, author: str = '') -> dict:
        """Create or replace one entry. The row as it now stands.

        ``created_at`` survives an update: it says when this entry started existing, and an
        edit to its name is not a new entry. So does ``author`` — who wrote a thing is not
        rewritten by whoever last touched it.
        """
        now = time.time()
        blob = json.dumps(dict(body or {}, id=pid), ensure_ascii=False)
        with self._db.transaction():
            existed = self._db.fetchone(f'SELECT 1 FROM {_T} WHERE pid = ?', (pid,))
            if existed:
                self._db.execute(
                    f'UPDATE {_T} SET body = ?, updated_at = ? WHERE pid = ?',
                    (blob, now, pid))
            else:
                self._db.execute(
                    f'INSERT INTO {_T} (pid, body, author, created_at, updated_at) '
                    f'VALUES (?,?,?,?,?)', (pid, blob, author or '', now, now))
        return self.get(pid) or {}

    def delete(self, pid: str) -> bool:
        """Forget one entry. Whether there was one to forget.

        The devices that referenced it keep the id in their field: it stops resolving to
        anything, which is exactly what a deleted shipped profile does, and is visible in the
        field as a chip whose name is its own id. Rewriting other people's configuration
        because somebody deleted an entry is the larger surprise.
        """
        if not pid or not self._db.fetchone(f'SELECT 1 FROM {_T} WHERE pid = ?', (pid,)):
            return False
        with self._db.transaction():
            self._db.execute(f'DELETE FROM {_T} WHERE pid = ?', (pid,))
        return True
