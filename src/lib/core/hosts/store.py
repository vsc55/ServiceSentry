#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for monitored hosts (servers).

A *host* is a target you monitor (by address) together with its per-protocol
connection profiles — SSH, SNMP, database, HTTP… — so the same server's
connection details are defined **once** and reused by every watchful module's
checks instead of being re-entered per module.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default;
PostgreSQL/MySQL through the same interface), like the other entity stores.

Secret values inside the per-protocol ``profiles`` (ssh/db passwords, SNMPv3
keys, tokens…) are encrypted at rest with :mod:`lib.security.secret_manager` using the
same value-level Fernet scheme as the module config / ``config.json``.  ``get``
and ``list`` return decrypted profiles (so the monitor can connect); the API
route is responsible for masking secrets before sending them to the client.

Schema::

    hosts(uid PK, name UNIQUE, address, tags(json list), description,
          profiles(json {protocol: {field: value}}),
          created_at, updated_at, updated_by)
"""

from __future__ import annotations

import json
import uuid

from lib.security import secret_manager
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore, EncryptedPayloadMixin

_HOSTS_SCHEMA = TableSpec(
    name='hosts',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''", unique=True),
        Column('address',     'TEXT', nullable=False, default="''"),
        # 'local' (monitored directly, no SSH) or 'remote' (reachable via the
        # SSH connection stored in profiles['ssh']).
        Column('kind',        'TEXT', nullable=False, default="'local'"),
        # Operating system: 'auto' (local→this host's platform; remote→detected
        # over SSH) or a fixed token (linux/windows/darwin/freebsd/other).
        Column('os',          'TEXT', nullable=False, default="'auto'"),
        # When 1 the host is in maintenance: every check bound to it is skipped.
        Column('maintenance', 'INTEGER', nullable=False, default="0"),
        # When 1 the host is a *virtual* entity (a VIP / cluster to monitor, not a
        # physical machine).  Purely descriptive: lets the UI and the Overview widget
        # separate physical hosts from virtual ones (keepalived VIP, proxmox cluster…).
        Column('virtual',     'INTEGER', nullable=False, default="0"),
        # What the device IS (see manifest.HOST_TYPES): server, nas, switch, ups…
        # Empty = unclassified, which is what every device created before this had and
        # what one created in a hurry still has.  Named `device_type` rather than `type`
        # because the short word is a keyword in enough dialects to be worth avoiding.
        Column('device_type', 'TEXT', nullable=False, default="''"),
        Column('tags',        'TEXT', nullable=False, default="'[]'"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('profiles',    'TEXT', nullable=False, default="'{}'"),
        # Modules this server is monitored by (so a module added with no checks
        # yet still persists).  JSON list of bare module names.
        Column('modules',     'TEXT', nullable=False, default="'[]'"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
        # The rows of this machine somebody has said are worth an alert. A switch port that
        # is down may be a PC switched off at seven — which is not news and made a rack of
        # half-populated switches permanently red — or it may be the link to a server, which
        # is a phone call. Nothing in any MIB separates those two: what is at the other end of
        # the cable is knowledge about THIS installation, so it is recorded against the
        # machine and not in a profile, which describes equipment in general.
        #
        # JSON list of `{"module": …, "row": …}`. Kept LAST because a missing column can only
        # be added by ADD COLUMN when it is trailing, which is how an existing database gets
        # this one without a migration.
        Column('watch',       'TEXT', nullable=False, default="'[]'"),
    ),
    indexes=(Index('idx_hosts_name', ('name',)),),
)

_T = _HOSTS_SCHEMA.name  # table name — single source of truth

_COLS = ('uid', 'name', 'address', 'kind', 'os', 'maintenance', 'virtual', 'device_type',
         'tags', 'description',
         'profiles', 'modules', 'created_at', 'updated_at', 'updated_by', 'watch')
_SELECT = ', '.join(_COLS)


from lib.util.entity_audit import utc_now_iso as _now   # one timestamp format


class HostsStore(EncryptedPayloadMixin, BaseStore):
    """Relational store for monitored hosts (backend-agnostic)."""

    _TABLE = _T

    def __init__(self, db: BaseConnector, *, fernet=None, secret_keys=None) -> None:
        super().__init__(db)
        self._fernet = fernet
        self._secret_keys = secret_keys or secret_manager.ENCRYPT_KEYS
        # ``virtual`` is a reserved word in MySQL. Quote the whole column list (dialect-aware)
        # for SELECT/INSERT, and ``virtual`` on its own for the UPDATE SET clause, so the raw
        # runtime SQL works on MySQL/MariaDB, not just SQLite.
        self._qsel = ', '.join(db.quote_ident(c) for c in _COLS)
        self._qvirtual = db.quote_ident('virtual')
        self._bootstrap()

    # ── Schema ──────────────────────────────────────────────────────────────
    def _bootstrap(self) -> None:
        self._db.reconcile_table(_HOSTS_SCHEMA)

    # ── Secret encryption (value-level, inside profiles) ──────────────────────

    # ── Row mapping ───────────────────────────────────────────────────────────
    def _row_to_host(self, row, decrypt: bool) -> dict:
        (uid, name, address, kind, os_, maintenance, virtual, dev_type, tags, desc,
         profiles, modules, c_at, u_at, u_by, watch) = row
        try:
            watch_l = json.loads(watch) if watch else []
        except (ValueError, TypeError):
            watch_l = []
        try:
            tags_l = json.loads(tags) if tags else []
        except (ValueError, TypeError):
            tags_l = []
        try:
            mods_l = json.loads(modules) if modules else []
        except (ValueError, TypeError):
            mods_l = []
        try:
            prof = json.loads(profiles) if profiles else {}
        except (ValueError, TypeError):
            prof = {}
        if decrypt:
            prof = self._decrypt(prof)
        return {
            'uid':         uid,
            'name':        name,
            'address':     address,
            'kind':        kind or 'local',
            'os':          os_ or 'auto',
            'maintenance': bool(maintenance),
            'virtual':     bool(virtual),
            'device_type': dev_type or '',
            'tags':        tags_l if isinstance(tags_l, list) else [],
            'description': desc or '',
            'profiles':    prof if isinstance(prof, dict) else {},
            'modules':     mods_l if isinstance(mods_l, list) else [],
            'created_at':  c_at or '',
            'updated_at':  u_at or '',
            'updated_by':  u_by or '',
            # …and the rows of it somebody said are worth an alert.
            'watch':       [w for w in (watch_l if isinstance(watch_l, list) else [])
                            if isinstance(w, dict) and w.get('module') and w.get('row')],
        }

    @staticmethod
    def _norm_kind(value) -> str:
        return 'remote' if str(value or '').strip().lower() == 'remote' else 'local'

    @staticmethod
    def _norm_device_type(value) -> str:
        """A declared type, or '' — an unrecognised one is not an error worth refusing a
        save over, and storing it would put a word on screen that nothing can translate."""
        from .manifest import host_type_ids  # noqa: PLC0415
        v = str(value or '').strip().lower()
        return v if v in host_type_ids() else ''

    @staticmethod
    def _norm_os(value) -> str:
        from lib.util.os_detect import OPTIONS  # noqa: PLC0415
        v = str(value or 'auto').strip().lower()
        return v if v in OPTIONS else 'auto'

    # ── Read ──────────────────────────────────────────────────────────────────
    def list(self, *, decrypt: bool = True) -> list[dict]:
        """Return all hosts ordered by name."""
        return [self._row_to_host(r, decrypt)
                for r in self._db.fetchall(f'SELECT {self._qsel} FROM {_T} ORDER BY name')]

    def get(self, uid: str, *, decrypt: bool = True) -> dict | None:
        row = self._db.fetchone(f'SELECT {self._qsel} FROM {_T} WHERE uid = ?', (uid,))
        return self._row_to_host(row, decrypt) if row else None

    def get_by_name(self, name: str, *, decrypt: bool = True) -> dict | None:
        row = self._db.fetchone(f'SELECT {self._qsel} FROM {_T} WHERE name = ?', (name,))
        return self._row_to_host(row, decrypt) if row else None

    # ── Write ─────────────────────────────────────────────────────────────────
    def create(self, data: dict, *, actor: str = '') -> str | None:
        """Insert a new host.  Returns its uid, or None on invalid/duplicate name."""
        name = str(data.get('name') or '').strip()
        if not name:
            return None
        if self._db.fetchone(f'SELECT 1 FROM {_T} WHERE name = ?', (name,)):
            return None  # duplicate name
        uid = str(data.get('uid') or uuid.uuid4())
        now = _now()
        try:
            with self._db.transaction():
                self._db.execute(
                    f'INSERT INTO {_T} ({self._qsel}) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (uid, name, str(data.get('address') or ''),
                     self._norm_kind(data.get('kind')),
                     self._norm_os(data.get('os')),
                     1 if data.get('maintenance') else 0,
                     1 if data.get('virtual') else 0,
                     self._norm_device_type(data.get('device_type')),
                     json.dumps(data.get('tags') or [], ensure_ascii=False),
                     str(data.get('description') or ''),
                     json.dumps(self._encrypt(data.get('profiles') or {}), ensure_ascii=False),
                     json.dumps(data.get('modules') or [], ensure_ascii=False),
                     now, now, actor or '',
                     # A machine is created watching nothing: what matters on it is said
                     # later, on the screen where its rows are.
                     json.dumps(data.get('watch') or [], ensure_ascii=False)),
                )
            return uid
        except Exception:  # pylint: disable=broad-except
            return None

    def update(self, uid: str, data: dict, *, actor: str = '') -> bool:
        """Update an existing host.  ``profiles`` is replaced wholesale (the
        caller should have restored any masked secrets first)."""
        if not self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,)):
            return False
        name = str(data.get('name') or '').strip()
        if not name:
            return False
        # Reject a rename that collides with another host's name.
        clash = self._db.fetchone(f'SELECT uid FROM {_T} WHERE name = ? AND uid <> ?', (name, uid))
        if clash:
            return False
        try:
            with self._db.transaction():
                self._db.execute(
                    f'UPDATE {_T} SET name=?, address=?, kind=?, os=?, maintenance=?, {self._qvirtual}=?, '
                    'device_type=?, '
                    'tags=?, description=?, profiles=?, modules=?, updated_at=?, updated_by=? WHERE uid=?',
                    (name, str(data.get('address') or ''),
                     self._norm_kind(data.get('kind')),
                     self._norm_os(data.get('os')),
                     1 if data.get('maintenance') else 0,
                     1 if data.get('virtual') else 0,
                     self._norm_device_type(data.get('device_type')),
                     json.dumps(data.get('tags') or [], ensure_ascii=False),
                     str(data.get('description') or ''),
                     json.dumps(self._encrypt(data.get('profiles') or {}), ensure_ascii=False),
                     json.dumps(data.get('modules') or [], ensure_ascii=False),
                     _now(), actor or '', uid),
                )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    #: What one watched row is keyed by, wherever it is compared.
    @staticmethod
    def watch_key(module: str, row: str) -> str:
        return f'{str(module or "").strip()}\u0000{str(row or "").strip()}'

    def watch(self, uid: str) -> set:
        """The rows of *uid* somebody has said are worth an alert, as comparison keys."""
        host = self.get(uid, decrypt=False) or {}
        return {self.watch_key(w.get('module'), w.get('row')) for w in host.get('watch') or ()}

    def set_watch(self, uid: str, module: str, row: str, on: bool, *, actor: str = '') -> bool:
        """Mark one row of one machine as worth an alert, or stop.

        Its OWN update and not a pass through :meth:`update`, which replaces the whole record:
        saying "tell me when this port goes down" would otherwise mean holding the machine's
        name, address and every stored credential, and would need the permission to edit the
        registry rather than the one to say what matters on a screen you are already reading.
        """
        mod, row = str(module or '').strip(), str(row or '').strip()
        if not mod or not row:
            return False
        host = self.get(uid, decrypt=False)
        if host is None:
            return False
        want = self.watch_key(mod, row)
        kept = [w for w in host.get('watch') or ()
                if self.watch_key(w.get('module'), w.get('row')) != want]
        if on:
            kept.append({'module': mod, 'row': row})
        try:
            with self._db.transaction():
                self._db.execute(
                    f'UPDATE {_T} SET watch=?, updated_at=?, updated_by=? WHERE uid=?',
                    (json.dumps(kept, ensure_ascii=False), _now(), actor or '', uid))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, uid: str) -> bool:
        try:
            row = self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,))
            if not row:
                return False
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
            return True
        except Exception:  # pylint: disable=broad-except
            return False
