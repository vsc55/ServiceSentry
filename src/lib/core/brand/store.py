#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - the brand's pictures, in the main database.
#
"""Where an installation's own pictures are kept: the main database, base64, in pieces.

In the database and not in a folder beside the configuration: every process of an installation
— the web, the workers, the events service that sends the emails — already shares the database,
and a folder would be one more thing to mount in each container and one more thing a backup has
to be told about. A backup carries every table of the main database without being told.

**In pieces, because of MySQL.** There is no binary column type the four engines share, and a
MySQL ``TEXT`` holds 64 KB — a logo of a few hundred is common. So a picture is base64 split
into chunks of :data:`CHUNK` characters, one row each, numbered by ``part``, and read back in
order. Every row of a slot carries the same ``mime``/``sha``/size, so reading the first one
answers "what is in this slot" without touching the rest.

``sha`` is the picture's version: what the panel puts in its URL (``/brand/logo?v=<sha>``), so
a browser can keep a picture for a year and still ask again the moment it changes.
"""

from __future__ import annotations

import base64
import hashlib
import threading
import time
import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.util.entity_audit import utc_now_iso as _now

BRAND_ASSET_SCHEMA = TableSpec(
    name='brand_asset',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('slot',       'TEXT', nullable=False, default="''"),     # favicon | logo | mark | email
        Column('part',       'INTEGER', nullable=False, default='0'),   # chunk number, from 0
        Column('mime',       'TEXT', nullable=False, default="''"),
        Column('sha',        'TEXT', nullable=False, default="''"),     # sha256 of the whole picture
        Column('size',       'INTEGER', nullable=False, default='0'),   # bytes of the whole picture
        Column('width',      'INTEGER', nullable=False, default='0'),   # 0 = not known (SVG, ICO…)
        Column('height',     'INTEGER', nullable=False, default='0'),
        Column('data',       'TEXT', nullable=False, default="''"),     # base64 chunk
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_brand_asset_slot', ('slot', 'part')),),
)

_T = BRAND_ASSET_SCHEMA.name

#: Base64 characters per row: under MySQL's 65 535-byte ``TEXT``, with room to spare.
CHUNK = 48_000

#: How long a process trusts what it last read. Every page render asks for the versions; a
#: picture uploaded on one web process shows on the others within this, without each request
#: costing a query.
TTL = 10.0


class BrandStore:
    """The four slots' pictures. A slot with no rows shows the shipped file."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._lock = threading.Lock()
        self._meta: dict | None = None
        self._meta_at = 0.0
        self._db.reconcile_table(BRAND_ASSET_SCHEMA)

    # ── Reading ──────────────────────────────────────────────────────────────
    def meta(self) -> dict:
        """``{slot: {mime, sha, size, width, height}}`` for the slots that have a picture."""
        with self._lock:
            if self._meta is not None and time.monotonic() - self._meta_at < TTL:
                return self._meta
        try:
            rows = self._db.fetchall(
                f'SELECT slot, mime, sha, size, width, height FROM {_T} WHERE part = 0') or ()
        except Exception:  # pylint: disable=broad-except
            rows = ()
        out = {r[0]: {'mime': r[1], 'sha': r[2], 'size': int(r[3] or 0),
                      'width': int(r[4] or 0), 'height': int(r[5] or 0)} for r in rows}
        with self._lock:
            self._meta, self._meta_at = out, time.monotonic()
        return out

    def get(self, slot: str) -> tuple[bytes, str] | None:
        """``(bytes, mime)`` of a slot's picture, or ``None`` when it has none."""
        try:
            rows = self._db.fetchall(
                f'SELECT data, mime FROM {_T} WHERE slot = ? ORDER BY part', (str(slot),)) or ()
        except Exception:  # pylint: disable=broad-except
            return None
        if not rows:
            return None
        try:
            return base64.b64decode(''.join(r[0] or '' for r in rows)), rows[0][1]
        except (ValueError, TypeError):
            return None

    # ── Writing ──────────────────────────────────────────────────────────────
    def put(self, slot: str, data: bytes, mime: str, *, width: int = 0, height: int = 0,
            actor: str = '') -> str:
        """Replace a slot's picture; returns its version (``sha``). All its rows in one
        transaction: half a picture is a broken image on the sign-in page."""
        sha = hashlib.sha256(data).hexdigest()
        texto = base64.b64encode(data).decode('ascii')
        trozos = [texto[i:i + CHUNK] for i in range(0, len(texto), CHUNK)] or ['']
        now = _now()
        with self._db.transaction():
            self._db.execute(f'DELETE FROM {_T} WHERE slot = ?', (str(slot),))
            for n, trozo in enumerate(trozos):
                self._db.execute(
                    f'INSERT INTO {_T}(uid, slot, part, mime, sha, size, width, height, data, '
                    'created_at, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (uuid.uuid4().hex, str(slot), n, mime, sha, len(data), int(width or 0),
                     int(height or 0), trozo, now, now, str(actor or '')))
        self.forget()
        return sha

    def delete(self, slot: str) -> bool:
        """Back to the shipped picture. ``True`` when there was one of its own."""
        with self._db.transaction():
            n = self._db.execute(f'DELETE FROM {_T} WHERE slot = ?', (str(slot),))
        self.forget()
        return bool(n)

    def forget(self) -> None:
        with self._lock:
            self._meta = None
