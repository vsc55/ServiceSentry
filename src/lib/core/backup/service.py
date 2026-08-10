#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Making a copy of this installation, and putting it back.

A backup here is a **zip of JSON**, not a dump of the database file. The panel runs on SQLite,
MySQL, PostgreSQL or SQL Server, and the copy has to survive the move: an install that grew on
SQLite and is being lifted onto MySQL is exactly when a backup is asked for, and a `.db` file
answers that with nothing. Rows in, rows out, through the connector both ways.

What a copy holds is declared in :data:`PARTS` rather than listed at each call site, so the API,
the UI and the restore all read the same catalogue and a part added here appears in all three.

The rule for ``core`` is deliberately inverted: it is every table **not** claimed by another
part, so a table added tomorrow — including the ones modules create at runtime through
``lib/db/module_tables.py`` — is in the backup by default instead of being silently missed. A
backup that quietly skips what it did not recognise is the failure you find out about once.

Flask-free: the routes hand it a connector and paths, and it answers with data.
"""

from __future__ import annotations

import base64
import io
import json
import os
import posixpath
import re
import zipfile

from lib.security.secret_manager import ENC_PREFIX
from lib.util.tools import fmt_bytes

# Format version of the archive itself. Bumped when the LAYOUT changes in a way an older
# reader cannot make sense of — not when a part is added, which older readers simply do not
# ask for. `restore` refuses a major it does not know rather than half-applying it.
FORMAT = 1

MANIFEST_NAME = 'manifest.json'
_DB_DIR = 'db'
_FILES_DIR = 'files'

# Engine bookkeeping. Never dumped, never restored: they describe the storage, not the install,
# and writing SQLite's own statistics into a MySQL restore is at best noise.
_INTERNAL_TABLES = frozenset({'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4'})

# A backup name is used as a FILENAME and echoed back in URLs. Anything outside this cannot be
# one, which is what keeps `..` and separators out of every path built from it.
_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')

# ── What a copy can hold ─────────────────────────────────────────────────────
#
# `default` is what the UI pre-ticks, not what the API assumes: a caller always says what it
# wants, so a part's default can change without changing what an existing script produces.
PARTS: tuple = (
    {'id': 'core', 'kind': 'db', 'tables': None, 'default': True, 'required': True,
     'label_key': 'backup_part_core'},
    {'id': 'config_file', 'kind': 'file', 'default': True, 'required': False,
     'label_key': 'backup_part_config_file'},
    {'id': 'history', 'kind': 'db', 'tables': ('history', 'check_state'),
     'default': False, 'required': False, 'label_key': 'backup_part_history'},
    {'id': 'audit', 'kind': 'db', 'tables': ('audit',),
     'default': False, 'required': False, 'label_key': 'backup_part_audit'},
    {'id': 'syslog', 'kind': 'db', 'tables': ('syslog', 'syslog_drops'),
     'default': False, 'required': False, 'label_key': 'backup_part_syslog'},
    {'id': 'mibs', 'kind': 'file', 'default': False, 'required': False,
     'label_key': 'backup_part_mibs'},
)

PART_IDS: tuple = tuple(p['id'] for p in PARTS)
_CLAIMED_TABLES: frozenset = frozenset(
    t for p in PARTS if p['kind'] == 'db' and p['tables'] for t in p['tables'])


def parts_catalogue() -> list:
    """The catalogue as the UI needs it — ids, defaults and i18n keys, no behaviour."""
    return [{'id': p['id'], 'default': p['default'], 'required': p['required'],
             'label_key': p['label_key'], 'kind': p['kind']} for p in PARTS]


def valid_name(name: str) -> bool:
    """Is *name* usable as a backup's file name?"""
    return bool(_NAME_RE.match(str(name or '')))


def backups_dir(var_dir: str, configured: str = '') -> str:
    """Where copies live: the configured directory, or ``<var_dir>/backups``.

    A parameter and not a constant because a copy on the same disk as the data it copies
    survives a mistake and nothing else. Resolved on every call, so moving it takes effect on
    the next copy rather than on the next restart — an operator who changed it mid-day would
    otherwise write to the old path and go looking in the new one.
    """
    configured = str(configured or '').strip()
    return configured or os.path.join(str(var_dir or ''), 'backups')


def _archive_path(var_dir: str, name: str, configured: str = '') -> str:
    """The archive for *name*, or '' when the name could not be one.

    Built from a validated name rather than joined and checked afterwards: a name that cannot
    contain a separator cannot walk out of the directory, and there is no second path to keep
    the check in step with.
    """
    if not valid_name(name):
        return ''
    return os.path.join(backups_dir(var_dir, configured), f'{name}.zip')


# ── Secrets ──────────────────────────────────────────────────────────────────

def _strip_secrets(value):
    """Blank every encrypted value in *value*, at any depth.

    "Stored encrypted" IS the marker, and the only one worth using here. The alternative — a
    list of secret field names — exists (``ENCRYPT_KEYS``) but is only half the truth: watchful
    modules declare their own secret fields in their schemas, so a registry-driven pass would
    skip a module's API token and produce a backup that says it holds no secrets while holding
    one. Anything the panel wrote with the `enc:` prefix is a secret, whoever declared it.
    """
    if isinstance(value, str):
        return '' if value.startswith(ENC_PREFIX) else value
    if isinstance(value, dict):
        return {k: _strip_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_secrets(v) for v in value]
    return value


def _clean_cell(value, keep_secrets: bool):
    """One column value, ready for JSON — and stripped when secrets are being left out.

    A column holding JSON is walked as JSON: the credential store keeps its fields in a `data`
    blob, so the secret is a value *inside* the string rather than the string itself. Text that
    does not parse is left exactly as it was; guessing at it would corrupt the row.
    """
    if isinstance(value, (bytes, bytearray)):
        # Binary survives the round trip through base64 rather than a lossy decode.
        return {'__b64__': base64.b64encode(bytes(value)).decode('ascii')}
    if keep_secrets or not isinstance(value, str):
        return value
    if value.startswith(ENC_PREFIX):
        return ''
    if value[:1] in ('{', '['):
        try:
            return json.dumps(_strip_secrets(json.loads(value)))
        except (ValueError, TypeError):
            return value
    return value


def _restore_cell(value):
    """Undo :func:`_clean_cell` for a value on its way back into a row."""
    if isinstance(value, dict) and set(value) == {'__b64__'}:
        try:
            return base64.b64decode(value['__b64__'])
        except (ValueError, TypeError):
            return b''
    return value


# ── Building ─────────────────────────────────────────────────────────────────

def _tables_for(connector, parts: set) -> list:
    """Which tables the chosen *parts* cover, in a stable order."""
    present = [t for t in connector.list_tables() if t not in _INTERNAL_TABLES]
    chosen: list = []
    for p in PARTS:
        if p['kind'] != 'db' or p['id'] not in parts:
            continue
        if p['tables'] is None:      # `core`: everything nobody else claimed
            chosen += [t for t in present if t not in _CLAIMED_TABLES]
        else:
            chosen += [t for t in p['tables'] if t in present]
    # Stable and duplicate-free: a table claimed by two parts is dumped once.
    return sorted(dict.fromkeys(chosen))


def _dump_table(connector, table: str, keep_secrets: bool) -> dict:
    cols = [c.name for c in connector.describe_table(table)]
    if not cols:
        return {'columns': [], 'rows': []}
    quoted = ', '.join(connector.quote_ident(c) for c in cols)
    rows = connector.fetchall(f'SELECT {quoted} FROM {connector.quote_ident(table)}')
    return {
        'columns': cols,
        'rows': [[_clean_cell(v, keep_secrets) for v in row] for row in rows],
    }


def _add_tree(zf: zipfile.ZipFile, root: str, arc_prefix: str) -> int:
    """Copy a directory into the archive; returns how many files went in."""
    if not root or not os.path.isdir(root):
        return 0
    n = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, '/')
            try:
                zf.write(full, posixpath.join(arc_prefix, rel))
                n += 1
            except OSError:
                # One unreadable file must not cost the whole backup; the manifest's count
                # is what says how many actually made it in.
                continue
    return n


def create_backup(connector, name: str, *, var_dir: str, config_dir: str,
                  parts, include_secrets: bool, actor: str = '',
                  app_version: str = '', engine: str = '', backup_dir: str = '') -> dict:
    """Write ``<var_dir>/backups/<name>.zip`` and return its manifest.

    *parts* is whatever the caller asked for; the required ones are added whether or not it
    did, because a copy without them restores nothing and the caller finds out later.
    """
    if not valid_name(name):
        return {'ok': False, 'message': 'invalid backup name'}
    dest = _archive_path(var_dir, name, backup_dir)
    if os.path.exists(dest):
        return {'ok': False, 'message': 'a backup with that name already exists'}

    want = {str(p) for p in (parts or [])} | {p['id'] for p in PARTS if p['required']}
    want &= set(PART_IDS)

    tables = _tables_for(connector, want)
    counts: dict = {}
    try:
        # Inside a try because the directory is CONFIGURED: a path that does not exist, cannot
        # be created or is not a path at all is an ordinary outcome here, and this function's
        # contract is to report failure as a value. Left outside, an unusable backup folder
        # raised through every caller — including the scheduler thread, where it would have
        # taken the thread down and stopped automatic copies until somebody restarted.
        os.makedirs(backups_dir(var_dir, backup_dir), exist_ok=True)
    except (OSError, ValueError) as exc:
        return {'ok': False, 'message': str(exc)}

    manifest = {
        'format': FORMAT,
        'name': name,
        'created_by': actor or '',
        'app_version': app_version or '',
        'engine': engine or '',
        'parts': sorted(want),
        'secrets': bool(include_secrets),
        'tables': counts,
        'files': {},
    }

    tmp = dest + '.part'
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
            for table in tables:
                data = _dump_table(connector, table, include_secrets)
                counts[table] = len(data['rows'])
                zf.writestr(f'{_DB_DIR}/{table}.json',
                            json.dumps(data, ensure_ascii=False, separators=(',', ':')))
            if 'config_file' in want and config_dir:
                cfg = os.path.join(config_dir, 'config.json')
                if os.path.isfile(cfg):
                    zf.write(cfg, f'{_FILES_DIR}/config.json')
                    manifest['files']['config.json'] = 1
            if 'mibs' in want:
                n = _add_tree(zf, os.path.join(var_dir, 'snmp_mibs', 'raw'),
                              f'{_FILES_DIR}/snmp_mibs/raw')
                manifest['files']['snmp_mibs'] = n
            # Written LAST so a manifest that is present is a manifest that is true: an
            # archive interrupted half way has no manifest at all, and `read_manifest`
            # refuses it instead of reporting a copy that holds less than it claims.
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=1))
        os.replace(tmp, dest)
    except Exception as exc:      # pylint: disable=broad-except
        for p in (tmp, dest):
            try:
                os.path.exists(p) and os.remove(p)
            except OSError:
                pass
        return {'ok': False, 'message': str(exc)}

    manifest['size'] = os.path.getsize(dest)
    return {'ok': True, 'manifest': manifest}


# ── Reading ──────────────────────────────────────────────────────────────────

def read_manifest(path: str) -> dict | None:
    """The manifest inside an archive, or None when it is not one of ours."""
    try:
        with zipfile.ZipFile(path) as zf:
            data = json.loads(zf.read(MANIFEST_NAME).decode('utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def list_backups(var_dir: str, backup_dir: str = '') -> list:
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
        out.append(man)
    out.sort(key=lambda m: m.get('mtime', 0), reverse=True)
    return out


def delete_backup(var_dir: str, name: str, backup_dir: str = '') -> bool:
    path = _archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


# ── Restoring ────────────────────────────────────────────────────────────────

def restore_backup(connector, var_dir: str, name: str, *, parts=None,
                   config_dir: str = '', backup_dir: str = '') -> dict:
    """Put an archive's contents back, table by table.

    *parts* narrows what is applied; None means everything the archive holds. A table is
    emptied and refilled, not merged: a backup is a statement about what the install looked
    like, and merging would produce a third state that never existed anywhere.

    All of it runs in ONE transaction. A restore that stopped half way — users back, roles
    not — leaves an install nobody can log into, which is worse than the state it started in.
    """
    path = _archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        return {'ok': False, 'message': 'backup not found'}
    man = read_manifest(path)
    if man is None:
        return {'ok': False, 'message': 'not a ServiceSentry backup'}
    if int(man.get('format') or 0) > FORMAT:
        return {'ok': False,
                'message': f'backup format {man.get("format")} is newer than this install'}

    # Exactly what was asked for, and nothing added. `required` says what a COPY must contain
    # — one without `core` restores nothing — and reading it as "must also be applied" would
    # make every partial restore a full one, which is the opposite of the point: restoring
    # only the hosts after a bad import must not also roll back the users.
    want = set(man.get('parts') or [])
    if parts is not None:
        want &= {str(p) for p in parts}

    restored: dict = {}
    files: dict = {}
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            wanted_tables = _tables_in_archive(names, want)
            with connector.transaction():
                for table in wanted_tables:
                    payload = json.loads(zf.read(f'{_DB_DIR}/{table}.json').decode('utf-8'))
                    restored[table] = _load_table(connector, table, payload)
            if 'config_file' in want and config_dir:
                member = f'{_FILES_DIR}/config.json'
                if member in names:
                    with open(os.path.join(config_dir, 'config.json'), 'wb') as fh:
                        fh.write(zf.read(member))
                    files['config.json'] = 1
            if 'mibs' in want:
                files['snmp_mibs'] = _extract_tree(
                    zf, names, f'{_FILES_DIR}/snmp_mibs/raw',
                    os.path.join(var_dir, 'snmp_mibs', 'raw'))
    except Exception as exc:      # pylint: disable=broad-except
        return {'ok': False, 'message': str(exc), 'tables': restored}

    return {'ok': True, 'tables': restored, 'files': files,
            'secrets': bool(man.get('secrets'))}


def _tables_in_archive(names: set, want: set) -> list:
    """Archive members under ``db/`` that belong to the wanted parts."""
    in_zip = sorted(n[len(_DB_DIR) + 1:-5] for n in names
                    if n.startswith(f'{_DB_DIR}/') and n.endswith('.json'))
    out: list = []
    for p in PARTS:
        if p['kind'] != 'db' or p['id'] not in want:
            continue
        if p['tables'] is None:
            out += [t for t in in_zip if t not in _CLAIMED_TABLES]
        else:
            out += [t for t in p['tables'] if t in in_zip]
    return sorted(dict.fromkeys(out))


def _load_table(connector, table: str, payload: dict) -> int:
    """Empty *table* and refill it from *payload*; returns how many rows went in.

    Only the columns the LIVE table still has are written. A backup taken before a column was
    added (or after one was dropped) is exactly the backup somebody reaches for, and refusing
    it over a schema that moved on would make the feature useless at the one moment it matters.
    """
    if not connector.table_exists(table):
        return 0
    live = {c.name for c in connector.describe_table(table)}
    cols = [c for c in (payload.get('columns') or []) if c in live]
    if not cols:
        return 0
    idx = [payload['columns'].index(c) for c in cols]
    quoted = ', '.join(connector.quote_ident(c) for c in cols)
    marks = ', '.join(['?'] * len(cols))
    connector.execute(f'DELETE FROM {connector.quote_ident(table)}')
    rows = [tuple(_restore_cell(r[i]) for i in idx) for r in (payload.get('rows') or [])]
    if rows:
        connector.executemany(
            f'INSERT INTO {connector.quote_ident(table)} ({quoted}) VALUES ({marks})', rows)
    return len(rows)


def _extract_tree(zf: zipfile.ZipFile, names: set, prefix: str, dest_root: str) -> int:
    """Write every archive member under *prefix* into *dest_root*."""
    n = 0
    for member in sorted(names):
        if not member.startswith(prefix + '/'):
            continue
        rel = member[len(prefix) + 1:]
        # The archive is data, and a member named `../../etc/passwd` is what a hostile one
        # looks like. Normalised and confined, never joined and trusted.
        target = os.path.normpath(os.path.join(dest_root, rel))
        if not target.startswith(os.path.normpath(dest_root) + os.sep):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            with open(target, 'wb') as fh:
                fh.write(zf.read(member))
            n += 1
        except OSError:
            continue
    return n


def archive_bytes(var_dir: str, name: str, backup_dir: str = '') -> io.BytesIO | None:
    """The archive as a stream, for the download endpoint."""
    path = _archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'rb') as fh:
            return io.BytesIO(fh.read())
    except OSError:
        return None


# ── Browsing for a folder ────────────────────────────────────────────────────

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
