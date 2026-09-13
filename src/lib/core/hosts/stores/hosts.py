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
        # How the panel RUNS COMMANDS on this device, which is not the same question as
        # what the device is (`device_type`) or which protocols it answers (`profiles`):
        #
        #   'none'   — it does not run any. The default, and the answer for most equipment: a
        #              switch, a router, a UPS or a NAS is read over SNMP and there is nothing
        #              to run a shell command on. It used to default to 'local', which meant
        #              the panel's OWN machine — so a check bound to a new switch measured the
        #              panel's CPU and filed it under the switch's name, with nothing to say
        #              it had. Now that is refused instead.
        #   'local'  — commands run on the machine the panel is running on.
        #   'remote' — over SSH, with the connection stored in profiles['ssh'].
        Column('kind',        'TEXT', nullable=False, default="'none'"),
        # Operating system: 'auto' (local→this host's platform; remote→detected
        # over SSH) or a fixed token (linux/windows/darwin/freebsd/other).
        Column('os',          'TEXT', nullable=False, default="'auto'"),
        # When 1 the host is in maintenance: every check bound to it is skipped.
        Column('maintenance', 'INTEGER', nullable=False, default="0"),
        # When 1 the host is a *virtual* entity (a VIP / cluster to monitor, not a
        # physical machine).  Purely descriptive: lets the UI and the Overview widget
        # separate physical hosts from virtual ones (keepalived VIP, proxmox cluster…).
        Column('virtual',     'INTEGER', nullable=False, default="0"),
        # What the device IS — one of the classes in `host_type` (see hosts/types.py).
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
        # De dónde salió este dispositivo, y cuál de los suyos es allí. Vacío es lo normal: uno
        # dado de alta aquí no viene de ningún sitio.
        #
        # Dos columnas y no una, por la misma razón que en `org`: son dos preguntas. «¿Esto lo
        # mantiene otro?» decide si una importación puede pisarlo, y «¿cuál de los suyos es?»
        # es lo único que permite volver a importar sin duplicar — por el NOMBRE no se puede,
        # porque renombrar un activo en el origen crearía aquí un segundo y dejaría el primero
        # huérfano sin que nada lo dijera.
        #
        # Las últimas, para que una base de datos que ya existe las reciba por ADD COLUMN.
        Column('source',      'TEXT', nullable=False, default="''"),
        Column('external_id', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_hosts_name', ('name',)),
             Index('idx_hosts_source', ('source', 'external_id'))),
)

_T = _HOSTS_SCHEMA.name  # table name — single source of truth

_COLS = ('uid', 'name', 'address', 'kind', 'os', 'maintenance', 'virtual', 'device_type',
         'tags', 'description',
         'profiles', 'modules', 'created_at', 'updated_at', 'updated_by', 'watch',
         'source', 'external_id')
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
         profiles, modules, c_at, u_at, u_by, watch, source, external_id) = row
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
            # …y de dónde salió, si es que salió de algún sitio.
            'source':      source or '',
            'external_id': external_id or '',
        }

    #: How commands are run on a device. See the `kind` column for what each means.
    KINDS = ('none', 'local', 'remote')

    @staticmethod
    def _norm_kind(value) -> str:
        """One of :data:`KINDS`, defaulting to ``none``.

        Anything unrecognised is ``none`` and not ``local``: the two differ in where a command
        RUNS, and guessing "the panel's own machine" from a value nobody wrote is how a check
        comes to measure the wrong box quietly. A record that says nothing gets nothing.
        """
        v = str(value or '').strip().lower()
        return v if v in HostsStore.KINDS else 'none'

    def _norm_device_type(self, value) -> str:
        """A declared class, or '' — an unrecognised one is not an error worth refusing a
        save over, and storing it would put a word on screen that nothing can translate.

        **Declared means the `host_type` table, and nothing else.** It used to mean a tuple in
        `manifest.py`, so a class this installation had added arrived here, was offered by the
        screen, and was dropped on the way in: no error anywhere, and a device that quietly lost
        the one thing that had been said about it.

        Read **through this same connector** rather than through the panel: this store is also
        built by the monitor and by the workers, which have no panel — and a rule that depended
        on who is asking would accept a value in one process and blank it in the next.
        """
        # Sin bajar a minúsculas: lo que lleva esta columna es el `uid` de una clase, y un
        # identificador opaco no tiene mayúsculas que corregir — tocarlo es cambiarlo.
        v = str(value or '').strip()
        if not v:
            return ''
        try:
            # Una consulta a la tabla, y **no** construir su almacén: el constructor reconcilia
            # el esquema, y esto se llama en CADA guardado de un dispositivo — así que importar
            # cuatrocientos son cuatrocientas reconciliaciones. En SQLite cuesta poco; contra
            # MySQL o PostgreSQL son cuatrocientas rondas al catálogo del motor.
            fila = self._db.fetchone('SELECT 1 FROM host_type WHERE uid = ?', (v,))
        except Exception:  # pylint: disable=broad-except
            # Una tabla que todavía no está deja al dispositivo sin clasificar, que es una
            # respuesta válida — y no impide guardarlo, que es lo que importa.
            return ''
        return v if fila else ''

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

    def count_by_device_type(self) -> dict:
        """``{clase: cuántos}`` de una consulta, sin traerse la flota.

        La pantalla de clases enseña ese número en cada fila y lo mira antes de dejar quitar una.
        Calculándolo en Python había que **leer todos los dispositivos** —descifrado aparte, cada
        fila son cuatro `json.loads`— y con tres mil máquinas eso son cien milisegundos por
        pregunta. Aquí lo cuenta el motor, que es lo que sabe hacer.
        """
        filas = self._db.fetchall(
            f'SELECT device_type, COUNT(*) FROM {_T} '
            "WHERE device_type <> '' GROUP BY device_type")
        return {r[0]: int(r[1] or 0) for r in (filas or ()) if r and r[0]}

    def count_with_device_type(self, device_type: str) -> int:
        """Cuántos llevan puesta ESA clase. Lo que se pregunta antes de borrarla."""
        v = str(device_type or '')
        if not v:
            return 0
        fila = self._db.fetchone(
            f'SELECT COUNT(*) FROM {_T} WHERE device_type = ?', (v,))
        return int((fila or (0,))[0] or 0)

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
                    # Los huecos, CONTADOS y no escritos a mano: la lista literal que había aquí
                    # se quedó corta en cuanto la tabla creció por el final, y lo que da entonces
                    # es un error del motor sobre un número de columnas — no sobre la columna que
                    # falta.
                    f'INSERT INTO {_T} ({self._qsel}) '
                    f'VALUES ({", ".join("?" * len(_COLS))})',
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
                     json.dumps(data.get('watch') or [], ensure_ascii=False),
                     # Y de dónde salió. Vacío cuando lo teclea una persona, que es lo normal.
                     str(data.get('source') or ''), str(data.get('external_id') or '')),
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
        # De dónde salió se CONSERVA cuando no viene, y no se borra por omisión. Esta ruta la usa
        # el cuadro de editar un dispositivo, que manda la ficha entera y no sabe de esto: sin
        # esta línea, corregir una descripción soltaría el dispositivo de su origen en silencio y
        # la siguiente importación lo crearía otra vez, duplicado.
        origen = self._db.fetchone(
            f'SELECT source, external_id FROM {_T} WHERE uid = ?', (uid,)) or ('', '')
        source = data.get('source')
        source = origen[0] or '' if source is None else str(source or '')
        external_id = data.get('external_id')
        external_id = origen[1] or '' if external_id is None else str(external_id or '')
        try:
            with self._db.transaction():
                self._db.execute(
                    f'UPDATE {_T} SET name=?, address=?, kind=?, os=?, maintenance=?, {self._qvirtual}=?, '
                    'device_type=?, '
                    'tags=?, description=?, profiles=?, modules=?, source=?, external_id=?, '
                    'updated_at=?, updated_by=? WHERE uid=?',
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
                     source, external_id,
                     _now(), actor or '', uid),
                )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    #: What one watched row is keyed by, wherever it is compared.
    @staticmethod
    def watch_key(module: str, row: str) -> str:
        return f'{str(module or "").strip()}\u0000{str(row or "").strip()}'

    #: What a marked row can be said to BE, beyond "worth an alert".
    #:
    #: `wan` is the one that exists: the port a machine reaches the internet through. A port
    #: somebody marked is a port they are watching; a port they marked as the LINE is one whose
    #: loss is not an amber row on a switch, it is the office being offline — and no MIB says
    #: which of thirty ports that is. Only whoever ran the cable knows, which is the same
    #: reason the plain mark exists at all.
    #:
    #: A closed vocabulary, because every one of them costs the core a behaviour: a word it
    #: passed through and ignored would be a mark that reads as a promise and does nothing.
    WATCH_ROLES = ('wan',)

    @classmethod
    def watch_role(cls, raw) -> str:
        """One role, or ``''`` — an ordinary mark."""
        role = str(raw or '').strip().lower()
        return role if role in cls.WATCH_ROLES else ''

    def watch(self, uid: str) -> set:
        """The rows of *uid* somebody has said are worth an alert, as comparison keys."""
        host = self.get(uid, decrypt=False) or {}
        return {self.watch_key(w.get('module'), w.get('row')) for w in host.get('watch') or ()}

    def watch_roles(self, uid: str) -> dict:
        """``{comparison key: role}`` for the marked rows that say what they ARE.

        Apart from :meth:`watch` because they answer different questions and one of them is
        asked far more often: every cycle asks "is this row marked", and only the sampler that
        found one asks "as what".
        """
        host = self.get(uid, decrypt=False) or {}
        out = {}
        for w in host.get('watch') or ():
            role = self.watch_role((w or {}).get('role'))
            if role:
                out[self.watch_key(w.get('module'), w.get('row'))] = role
        return out

    def set_watch(self, uid: str, module: str, row: str, on: bool, *,
                  role: str = '', actor: str = '') -> bool:
        """Mark one row of one machine as worth an alert, or stop.

        *role* says what the row IS (see :data:`WATCH_ROLES`) — ``''`` is an ordinary mark. A
        role always implies the mark: a port declared as the line out is a port being watched,
        and offering the two as separate switches would be offering a state where the answer to
        "tell me when the internet goes" is "no".

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
            entry = {'module': mod, 'row': row}
            found = self.watch_role(role)
            if found:
                entry['role'] = found
            kept.append(entry)
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
