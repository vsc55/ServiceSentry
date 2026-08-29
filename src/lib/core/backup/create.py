#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Making a copy: rows out through the connector, into a zip of JSON.

Not a dump of the database file. The panel runs on SQLite, MySQL, PostgreSQL or SQL Server,
and the copy has to survive the move: an install that grew on SQLite and is being lifted onto
MySQL is exactly when a backup is asked for, and a `.db` file answers that with nothing.

The other half of the pair is `restore.py`, and the two agree because neither decides what a
part means — `parts.py` does.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import zipfile

from lib.debug.debug_level import DebugLevel
from lib.util.tools import fmt_bytes

from .archive import (PARTS_PREFIX, archive_path, clean_cell, DB_DIR, file_sha256,
                      FILES_DIR, _log, backups_dir, FORMAT, MANIFEST_NAME, valid_name)
from . import parts as _parts
from .parts import conn_for, part_ids, tables_by_part, PARTS


def _dump_table(connector, table: str, keep_secrets: bool) -> dict:
    cols = [c.name for c in connector.describe_table(table)]
    if not cols:
        return {'columns': [], 'rows': []}
    quoted = ', '.join(connector.quote_ident(c) for c in cols)
    rows = connector.fetchall(f'SELECT {quoted} FROM {connector.quote_ident(table)}')
    return {
        'columns': cols,
        'rows': [[clean_cell(v, keep_secrets) for v in row] for row in rows],
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
                  progress_cb=None, connectors=None, dirs=None) -> dict:
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
    dest = archive_path(var_dir, name, backup_dir)
    if os.path.exists(dest):
        _log(f'> Backup > create >> refused, {name!r} already exists', DebugLevel.warning)
        return {'ok': False, 'message': 'a backup with that name already exists'}

    want = {str(p) for p in (parts or [])} | {p['id'] for p in PARTS if p['required']}
    want &= part_ids()
    _log(f'> Backup > create >> {name!r} parts={sorted(want)} '
         f'secrets={bool(include_secrets)} by={actor or "?"}')

    by_part = tables_by_part(connector, want, connectors)
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
                        member = f'{DB_DIR}/{table}.json'
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
                    zf.writestr(f'{FILES_DIR}/config.json', blob)
                    digests[f'{FILES_DIR}/config.json'] = hashlib.sha256(blob).hexdigest()
                    manifest['files']['config.json'] = 1
                # A part that was asked for and produced nothing is NOT ok. Silently writing a
                # copy without the config file, and calling it complete, is how a restore finds
                # out at the worst moment.
                steps.append({'part': 'config_file', 'ok': ok, 'tables': 0,
                              'rows': 1 if ok else 0,
                              'error': '' if ok else 'config.json not found'})
            # Every directory part, by the same rule for each: its own directory under
            # var_dir, into its own place in the archive. The core's own are in that list now
            # too (floor plans) — and it still names no module, which is what matters.
            for mp in _parts.dir_parts():
                if mp['id'] not in want:
                    continue
                n = _add_tree(zf, _parts.part_dir(mp, var_dir, dirs),
                              f'{PARTS_PREFIX}/{mp["id"]}')
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
            fh.write(f'{file_sha256(dest)}  {os.path.basename(dest)}\n')
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
