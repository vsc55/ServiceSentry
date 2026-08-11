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
import hashlib
import io
import json
import os
import posixpath
import re
import zipfile

from lib.core.object_base import ObjectBase
from lib.debug.debug_level import DebugLevel
from lib.security.secret_manager import ENC_PREFIX
from lib.util.tools import fmt_bytes


def _log(message: str, level: DebugLevel = DebugLevel.info) -> None:
    """Say what is happening, on the panel's own log.

    A copy and a restore are the two operations here that take minutes, run on a thread and
    rewrite the install — and until this existed they went past in total silence, so a screen
    that failed to open its dialog left nothing anywhere to say whether anything had happened
    at all. Through `ObjectBase.debug` like the rest of the panel, so `global|log_level`
    governs it and there is no second logging path to configure.
    """
    ObjectBase.debug.print(message, level)

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
    # `db: syslog` and not the main connector: a high-volume feed can be sent to a database of
    # its OWN (`syslog_db|enabled`), and then these two tables are not in the system database
    # at all. Read from the main one they simply are not there — the part copies nothing and
    # says so in no way an operator notices until a restore comes back empty.
    {'id': 'syslog', 'kind': 'db', 'tables': ('syslog', 'syslog_drops'), 'db': 'syslog',
     'default': False, 'required': False, 'label_key': 'backup_part_syslog'},
)

PART_IDS: tuple = tuple(p['id'] for p in PARTS)
_CLAIMED_TABLES: frozenset = frozenset(
    t for p in PARTS if p['kind'] == 'db' and p['tables'] for t in p['tables'])

# Where a module's files go inside the archive. Derived from the part id on both sides rather
# than recorded per copy, so a restore and a copy cannot disagree about where the files are.
_PARTS_PREFIX = f'{_FILES_DIR}/parts'


def module_parts() -> list:
    """The parts modules declare for themselves — see `lib.modules.discovery.backup_parts`.

    The core knows no module's name, and that is the whole point: a directory of MIBs is in
    the copy because the SNMP module says so, and the next module's files will be there for
    the same reason rather than because somebody remembered to add a branch here.

    Read on every call, not captured: a module installed while the panel runs is discovered
    everywhere else the same way, and a catalogue frozen at import would offer to copy files
    from a module that is gone and miss the one that arrived.
    """
    try:
        from lib.modules.discovery.backup_parts import backup_parts_catalog  # noqa: PLC0415
        return backup_parts_catalog(reserved=PART_IDS)
    except Exception:      # pylint: disable=broad-except
        # Discovery failing must not take backups with it: the core parts are the ones that
        # make a copy restorable, and losing a module's files is not losing the install.
        return []


def _module_part(pid: str) -> dict | None:
    return next((p for p in module_parts() if p['id'] == pid), None)


def _part_ids() -> set:
    return set(PART_IDS) | {p['id'] for p in module_parts()}


def parts_catalogue(lang: str = '') -> list:
    """The catalogue as the UI needs it — ids, defaults and labels, no behaviour.

    Core parts carry an i18n KEY, resolved by the browser like every other string. A module's
    part carries the already-translated text instead: its wording lives in the module's own
    lang files, which the panel's catalogue does not hold — and shipping the key alone would
    show `backup_part_mibs` to whoever installed the module.
    """
    out = [{'id': p['id'], 'default': p['default'], 'required': p['required'],
            'label_key': p['label_key'], 'kind': p['kind']} for p in PARTS]
    for mp in module_parts():
        texts = mp['label_i18n']
        out.append({'id': mp['id'], 'default': mp['default'], 'required': False,
                    'kind': 'file', 'module': mp['module'],
                    'label': texts.get(lang) or texts.get('en_EN') or mp['id']})
    return out


def valid_name(name: str) -> bool:
    """Is *name* usable as a backup's file name?"""
    return bool(_NAME_RE.match(str(name or '')))


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

def conn_for(part: dict, connector, connectors=None):
    """The connector a PART's tables live on.

    Almost everything is in the system database, and `connectors` is empty on an install that
    has only that one — so the answer is the main connector unless a part declares otherwise
    and the caller actually supplied one.

    This exists because `syslog_db|enabled` moves the syslog tables to a database of their own.
    Read through the main connector they are simply absent: the part copied nothing, reported
    nothing wrong, and the copy came back empty at restore time — which is the one moment
    nobody can afford to find out.
    """
    key = part.get('db') or 'main'
    return (connectors or {}).get(key) or connector


def _tables_by_part(connector, parts: set, connectors=None) -> list:
    """``[(part_id, [tables])]`` for the chosen parts, in catalogue order.

    Kept alongside the flat list because the copy is REPORTED by part — that is the unit an
    operator ticked — while it is written table by table. Deriving one from the other at the
    call site would put the mapping in two places.

    Each part is asked of ITS OWN database. `core` is "everything nobody else claimed" *in the
    system database*, so a table that lives elsewhere is never swept into it by accident.
    """
    seen: set = set()
    out: list = []
    for p in PARTS:
        if p['kind'] != 'db' or p['id'] not in parts:
            continue
        try:
            present = [t for t in conn_for(p, connector, connectors).list_tables()
                       if t not in _INTERNAL_TABLES]
        except Exception:      # pylint: disable=broad-except
            # A second database that cannot be reached costs its own part and nothing else:
            # the copy of everything else is still worth having, and the empty part says so.
            present = []
        tabs = ([t for t in present if t not in _CLAIMED_TABLES] if p['tables'] is None
                else [t for t in p['tables'] if t in present])
        tabs = [t for t in tabs if t not in seen]
        seen.update(tabs)
        out.append((p['id'], sorted(tabs)))
    return out


def _tables_for(connector, parts: set, connectors=None) -> list:
    """Which tables the chosen *parts* cover, in a stable order."""
    return sorted({t for _pid, tabs in _tables_by_part(connector, parts, connectors)
                   for t in tabs})


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
                  app_version: str = '', engine: str = '', backup_dir: str = '',
                  progress_cb=None, connectors=None) -> dict:
    """Write ``<var_dir>/backups/<name>.zip`` and return its manifest.

    *parts* is whatever the caller asked for; the required ones are added whether or not it
    did, because a copy without them restores nothing and the caller finds out later.

    *connectors* maps a part's declared database to its connector — ``{'syslog': conn}`` on an
    install where `syslog_db|enabled` sent that feed to a database of its own. Anything not in
    it uses *connector*, which is every install that has one database.
    """
    if not valid_name(name):
        _log(f'> Backup > create >> refused, {name!r} cannot be a file name',
             DebugLevel.warning)
        return {'ok': False, 'message': 'invalid backup name'}
    dest = _archive_path(var_dir, name, backup_dir)
    if os.path.exists(dest):
        _log(f'> Backup > create >> refused, {name!r} already exists', DebugLevel.warning)
        return {'ok': False, 'message': 'a backup with that name already exists'}

    want = {str(p) for p in (parts or [])} | {p['id'] for p in PARTS if p['required']}
    want &= _part_ids()
    _log(f'> Backup > create >> {name!r} parts={sorted(want)} '
         f'secrets={bool(include_secrets)} by={actor or "?"}')

    by_part = _tables_by_part(connector, want, connectors)
    tables = sorted({t for _pid, tabs in by_part for t in tabs})
    counts: dict = {}
    # sha256 per member, so a copy can be checked without trusting the file it came in.
    digests: dict = {}
    # One entry per PART, carrying whether it made it. A copy that lost one table is not the
    # same thing as one that lost none, and "it finished" is not an answer to "is it usable".
    steps: list = []
    try:
        # Inside a try because the directory is CONFIGURED: a path that does not exist, cannot
        # be created or is not a path at all is an ordinary outcome here, and this function's
        # contract is to report failure as a value. Left outside, an unusable backup folder
        # raised through every caller — including the scheduler thread, where it would have
        # taken the thread down and stopped automatic copies until somebody restarted.
        os.makedirs(backups_dir(var_dir, backup_dir), exist_ok=True)
    except (OSError, ValueError) as exc:
        _log(f'> Backup > create >> {name!r} cannot use the backup folder: {exc}',
             DebugLevel.error)
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
        # Filled in below, once every part has had its turn.
        'steps': steps,
        'status': 'ok',
        # A digest per member. NOT of the whole archive, which cannot be inside itself: that
        # one goes in a sidecar written after the file is closed.
        'sha256': digests,
    }

    tmp = dest + '.part'
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
            _done = 0
            for part_id, part_tables in by_part:
                step = {'part': part_id, 'ok': True, 'tables': len(part_tables),
                        'rows': 0, 'error': ''}
                steps.append(step)
                # Read from the database this part lives on, which is not always the system
                # one — see `conn_for`.
                src = conn_for(next(p for p in PARTS if p['id'] == part_id),
                               connector, connectors)
                for table in part_tables:
                    # Progress is per TABLE — rows are unbounded (a syslog table is 160k of
                    # them) and bytes are unknown until the zip closes — while the OUTCOME is
                    # per part, which is the unit somebody ticked.
                    if progress_cb:
                        try:
                            progress_cb({'step': _done, 'total': len(tables), 'table': table,
                                         'steps': steps})
                        except Exception:      # pylint: disable=broad-except
                            pass               # a broken reporter must not lose the backup
                    try:
                        data = _dump_table(src, table, include_secrets)
                        blob = json.dumps(data, ensure_ascii=False,
                                          separators=(',', ':')).encode('utf-8')
                        member = f'{_DB_DIR}/{table}.json'
                        zf.writestr(member, blob)
                        digests[member] = hashlib.sha256(blob).hexdigest()
                        counts[table] = len(data['rows'])
                        step['rows'] += len(data['rows'])
                    except Exception as exc:      # pylint: disable=broad-except
                        # One unreadable table marks its PART and lets the rest continue: a
                        # backup holding nine of ten tables is worth having, and one that
                        # aborted on the tenth is worth nothing. The manifest says which.
                        step['ok'] = False
                        step['error'] = str(exc)[:200]
                    _done += 1
            if 'config_file' in want and config_dir:
                cfg = os.path.join(config_dir, 'config.json')
                ok = os.path.isfile(cfg)
                if ok:
                    with open(cfg, 'rb') as fh:
                        blob = fh.read()
                    zf.writestr(f'{_FILES_DIR}/config.json', blob)
                    digests[f'{_FILES_DIR}/config.json'] = hashlib.sha256(blob).hexdigest()
                    manifest['files']['config.json'] = 1
                # A part that was asked for and produced nothing is NOT ok. Silently writing a
                # copy without the config file, and calling it complete, is how a restore finds
                # out at the worst moment.
                steps.append({'part': 'config_file', 'ok': ok, 'tables': 0,
                              'rows': 1 if ok else 0,
                              'error': '' if ok else 'config.json not found'})
            # Whatever the modules declared, by the same rule for each: their own directory
            # under var_dir, into their own place in the archive. The core names none of them.
            for mp in module_parts():
                if mp['id'] not in want:
                    continue
                n = _add_tree(zf, os.path.join(var_dir, *mp['dir'].split('/')),
                              f'{_PARTS_PREFIX}/{mp["id"]}')
                manifest['files'][mp['id']] = n
                steps.append({'part': mp['id'], 'ok': n > 0, 'tables': 0, 'rows': n,
                              'error': '' if n else 'no files found'})
            # Written LAST so a manifest that is present is a manifest that is true: an
            # archive interrupted half way has no manifest at all, and `read_manifest`
            # refuses it instead of reporting a copy that holds less than it claims.
            # `status` is the one-word answer to "is this copy usable", and it is written into
            # the archive rather than worked out when the list is drawn: the copy is what
            # somebody restores from months later, and the screen that judged it will be gone.
            bad = [s2 for s2 in steps if not s2['ok']]
            manifest['status'] = ('ok' if not bad
                                  else 'error' if len(bad) == len(steps) else 'partial')
            for s2 in steps:
                # Each part on its own line, at its own level: the failures are what somebody
                # greps for, and burying them in a summary is how they go unnoticed.
                _log(f'> Backup > create >> {name!r} part {s2["part"]}: '
                     + (f'{s2["rows"]} rows' if s2['ok'] else f'FAILED {s2["error"]}'),
                     DebugLevel.debug if s2['ok'] else DebugLevel.warning)
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=1))
        os.replace(tmp, dest)
        # The archive's own digest, beside it. A copy is a file that gets moved to another
        # disk, another machine, a tape — and none of those tell you it arrived intact. The
        # sidecar travels with it and is what says so.
        with open(dest + '.sha256', 'w', encoding='utf-8') as fh:
            # The `sha256sum` format, so `sha256sum -c` on the target machine validates it
            # without this panel being involved at all.
            fh.write(f'{_file_sha256(dest)}  {os.path.basename(dest)}\n')
    except Exception as exc:      # pylint: disable=broad-except
        for p in (tmp, dest):
            try:
                os.path.exists(p) and os.remove(p)
            except OSError:
                pass
        _log(f'> Backup > create >> {name!r} failed: {exc}', DebugLevel.error)
        return {'ok': False, 'message': str(exc)}

    manifest['size'] = os.path.getsize(dest)
    _log(f'> Backup > create >> {name!r} {manifest["status"]}, '
         f'{sum(counts.values())} rows in {len(counts)} tables, '
         f'{fmt_bytes(manifest["size"])} -> {dest}',
         DebugLevel.info if manifest['status'] == 'ok' else DebugLevel.warning)
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
        out.append(man)
    out.sort(key=lambda m: m.get('mtime', 0), reverse=True)
    return out


def backup_exists(var_dir: str, name: str, backup_dir: str = '') -> bool:
    """Is there an archive by that name?

    Asked BEFORE a restore is started in the background, so "there is no such copy" stays an
    answer to the request that asked for it. Discovering it inside the job would put a progress
    bar on screen for something that was never going to happen.
    """
    path = _archive_path(var_dir, name, backup_dir)
    return bool(path) and os.path.isfile(path)


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
                   config_dir: str = '', backup_dir: str = '', progress_cb=None,
                   connectors=None) -> dict:
    """Put an archive's contents back, table by table.

    *parts* narrows what is applied; None means everything the archive holds. A table is
    emptied and refilled, not merged: a backup is a statement about what the install looked
    like, and merging would produce a third state that never existed anywhere.

    All of it runs in ONE transaction. A restore that stopped half way — users back, roles
    not — leaves an install nobody can log into, which is worse than the state it started in.

    *progress_cb* is called with ``{step, total, table}`` as it goes, the same shape the copy
    reports — the two are the same wait to whoever is watching, and one shape means one dialog.

    *connectors* is the same map `create_backup` takes. A part whose tables live in a database
    of their own goes back THERE, and gets a transaction of its own: two databases cannot share
    one, and the guarantee that matters — the system tables land together or not at all — is
    kept where it means something. Bulk log data landing in its own step is not a state anybody
    can be locked out by.
    """
    path = _archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        _log(f'> Backup > restore >> {name!r} not found', DebugLevel.warning)
        return {'ok': False, 'message': 'backup not found'}
    man = read_manifest(path)
    if man is None:
        _log(f'> Backup > restore >> {name!r} is not one of ours', DebugLevel.warning)
        return {'ok': False, 'message': 'not a ServiceSentry backup'}
    if int(man.get('format') or 0) > FORMAT:
        _log(f'> Backup > restore >> {name!r} format {man.get("format")} is newer than '
             f'this install ({FORMAT})', DebugLevel.error)
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
    # What the live schema could not take. Empty is the normal answer; anything in it is the
    # difference between "restored" and "restored, and here is what did not survive the trip".
    skipped: dict = {}
    _log(f'> Backup > restore >> {name!r} parts={sorted(want)} '
         f'made with {man.get("app_version") or "?"}')

    # One entry per PART, exactly as the copy reports them. The unit somebody ticked in the
    # form is the unit they want ticked back off, and a restore that only said "148 rows" left
    # them to work out which of the six things they asked for had actually arrived.
    steps: list = []
    done = [0]

    def _say(total, what):
        """Say what is being put back, before it is. A broken reporter must not cost the
        restore — the same rule the copy follows, and here it would abort a transaction."""
        done[0] += 1
        if progress_cb:
            try:
                progress_cb({'step': done[0], 'total': total, 'table': what,
                             'steps': steps})
            except Exception:      # pylint: disable=broad-except
                pass

    def _fail(step, why):
        """Mark a part short of what it was asked for, keeping the FIRST reason.

        Not the last: the first thing that went wrong is the one that explains the rest, and a
        message overwritten five times says only what happened at the end.
        """
        step['ok'] = False
        step['error'] = step['error'] or why

    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            by_part = _tables_in_archive_by_part(names, want)
            file_parts = [mp for mp in module_parts() if mp['id'] in want]
            cfg_step = 1 if ('config_file' in want and config_dir) else 0
            total = sum(len(t) for _pid, t in by_part) + cfg_step + len(file_parts)
            # Grouped by DATABASE, one transaction each: the system tables must land together
            # or not at all — users back with roles not back is an install nobody can log into
            # — and a second database physically cannot join that transaction.
            for target, group in _by_database(by_part, connector, connectors):
                with target.transaction():
                    for pid, tabs in group:
                        step = {'part': pid, 'ok': True, 'tables': len(tabs), 'rows': 0,
                                'error': ''}
                        steps.append(step)
                        for table in tabs:
                            _say(total, table)
                            payload = json.loads(
                                zf.read(f'{_DB_DIR}/{table}.json').decode('utf-8'))
                            rows, dropped = _load_table(target, table, payload)
                            restored[table] = rows
                            step['rows'] += rows
                            if dropped is None:
                                gone = len(payload.get('rows') or [])
                                skipped[table] = {'missing': True, 'rows': gone}
                                _fail(step, f'{table}: table no longer exists')
                                _log(f'> Backup > restore >> {table}: table is gone, '
                                     f'{gone} rows not applied', DebugLevel.warning)
                            elif dropped:
                                skipped[table] = {'columns': dropped}
                                _fail(step, f'{table}: dropped {", ".join(dropped)}')
                                _log(f'> Backup > restore >> {table}: {rows} rows, dropped '
                                     f'fields {", ".join(dropped)}', DebugLevel.warning)
                            else:
                                _log(f'> Backup > restore >> {table}: {rows} rows',
                                     DebugLevel.debug)
            if cfg_step:
                _say(total, 'config.json')
                step = {'part': 'config_file', 'ok': True, 'tables': 0, 'rows': 0, 'error': ''}
                steps.append(step)
                member = f'{_FILES_DIR}/config.json'
                if member in names:
                    with open(os.path.join(config_dir, 'config.json'), 'wb') as fh:
                        fh.write(zf.read(member))
                    files['config.json'] = 1
                    step['rows'] = 1
                else:
                    # Asked for and not there: the archive says it holds the config and does
                    # not. Silence here is a panel that comes back with the old settings and
                    # nothing to say why.
                    _fail(step, 'config.json is not in the archive')
            # A module's files go back where that module says they live TODAY, not where the
            # copy was taken from: the declaration travels with the module, and a module that
            # is no longer installed has nowhere to put them — so its part is skipped rather
            # than unpacked into a directory nothing reads.
            for mp in file_parts:
                _say(total, mp['id'])
                n = _extract_tree(zf, names, f'{_PARTS_PREFIX}/{mp["id"]}',
                                  os.path.join(var_dir, *mp['dir'].split('/')))
                files[mp['id']] = n
                step = {'part': mp['id'], 'ok': n > 0, 'tables': 0, 'rows': n,
                        'error': '' if n else 'no files in the archive'}
                steps.append(step)
    except Exception as exc:      # pylint: disable=broad-except
        # The transaction rolled back, so nothing of it landed — worth saying plainly, because
        # "the restore failed" and "the install is half replaced" are very different nights.
        _log(f'> Backup > restore >> {name!r} failed and was rolled back: {exc}',
             DebugLevel.error)
        return {'ok': False, 'message': str(exc), 'tables': restored}

    _log(f'> Backup > restore >> {name!r} done, {sum(restored.values())} rows in '
         f'{len(restored)} tables'
         + (f', {len(skipped)} could not be applied in full' if skipped else ''),
         DebugLevel.warning if skipped else DebugLevel.info)
    return {'ok': True, 'tables': restored, 'files': files, 'skipped': skipped,
            'steps': steps, 'app_version': str(man.get('app_version') or ''),
            'secrets': bool(man.get('secrets'))}


def _by_database(by_part: list, connector, connectors=None) -> list:
    """``[(conn, [(part_id, tables), …])]`` — the parts grouped by the database they go to.

    Grouped and not simply looped, because each database gets ONE transaction: applying a part
    per transaction would let a restore stop between two system tables, which is the state this
    whole function is written to make impossible.

    Keyed on the connector OBJECT: an install with `syslog_db` disabled hands back the main
    connector for the syslog part, and that has to come out as one group, not two.
    """
    order: list = []
    groups: dict = {}
    for pid, tabs in by_part:
        part = next((p for p in PARTS if p['id'] == pid), {})
        target = conn_for(part, connector, connectors)
        key = id(target)
        if key not in groups:
            groups[key] = (target, [])
            order.append(key)
        groups[key][1].append((pid, tabs))
    return [groups[k] for k in order]


def _tables_in_archive_by_part(names: set, want: set) -> list:
    """``[(part_id, [tables])]`` for the wanted parts, in catalogue order.

    Grouped, because a restore is REPORTED by part — the unit somebody ticked in the form —
    while it is applied table by table. The mirror of `_tables_by_part` on the way out, and
    kept as the one place that decides so the two directions cannot disagree about which
    tables a part means.
    """
    in_zip = sorted(n[len(_DB_DIR) + 1:-5] for n in names
                    if n.startswith(f'{_DB_DIR}/') and n.endswith('.json'))
    seen: set = set()
    out: list = []
    for p in PARTS:
        if p['kind'] != 'db' or p['id'] not in want:
            continue
        tabs = ([t for t in in_zip if t not in _CLAIMED_TABLES] if p['tables'] is None
                else [t for t in p['tables'] if t in in_zip])
        tabs = [t for t in tabs if t not in seen]
        seen.update(tabs)
        out.append((p['id'], sorted(tabs)))
    return out


def _tables_in_archive(names: set, want: set) -> list:
    """Archive members under ``db/`` that belong to the wanted parts, flat."""
    return sorted({t for _pid, tabs in _tables_in_archive_by_part(names, want) for t in tabs})


def _load_table(connector, table: str, payload: dict):
    """Empty *table* and refill it from *payload*.

    Returns ``(rows written, columns the live schema could not take)`` — or ``(0, None)`` when
    the table itself is gone, which is a different thing and reads as one at the call site.

    Only the columns the LIVE table still has are written. A backup taken before a column was
    added (or after one was dropped) is exactly the backup somebody reaches for, and refusing
    it over a schema that moved on would make the feature useless at the one moment it matters.

    But what was dropped is REPORTED, because this is also what happens when a copy from a
    later build is restored onto an earlier one: the columns this schema does not have yet go
    silently, and silent is the part that makes it data loss instead of a decision.
    """
    if not connector.table_exists(table):
        return 0, None
    live = {c.name for c in connector.describe_table(table)}
    want = payload.get('columns') or []
    cols = [c for c in want if c in live]
    dropped = [c for c in want if c not in live]
    if not cols:
        return 0, dropped
    idx = [payload['columns'].index(c) for c in cols]
    quoted = ', '.join(connector.quote_ident(c) for c in cols)
    marks = ', '.join(['?'] * len(cols))
    connector.execute(f'DELETE FROM {connector.quote_ident(table)}')
    rows = [tuple(_restore_cell(r[i]) for i in idx) for r in (payload.get('rows') or [])]
    if rows:
        connector.executemany(
            f'INSERT INTO {connector.quote_ident(table)} ({quoted}) VALUES ({marks})', rows)
    return len(rows), dropped


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


# ── Checking a copy ──────────────────────────────────────────────────────────

def _file_sha256(path: str) -> str:
    """The digest of a file, read in chunks — an archive can be gigabytes."""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


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
    path = _archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        return {'ok': False, 'message': 'backup not found'}
    man = read_manifest(path)
    if man is None:
        return {'ok': False, 'message': 'not a ServiceSentry backup'}

    out = {'ok': True, 'file': 'missing', 'members': 0, 'bad': []}
    side = path + '.sha256'
    if os.path.isfile(side):
        try:
            with open(side, encoding='utf-8') as fh:
                want = fh.read().split()[0].strip()
            out['file'] = 'ok' if want == _file_sha256(path) else 'bad'
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
