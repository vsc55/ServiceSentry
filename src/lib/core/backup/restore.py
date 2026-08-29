#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Putting a copy back, table by table — and saying what did not survive the trip.

A table is emptied and refilled, not merged: a backup is a statement about what the install
looked like, and merging would produce a third state that never existed anywhere. Each
database gets ONE transaction, because the system tables have to land together or not at all.

`archive_contents` is here rather than in `archive.py` on purpose: it answers "what could this
restore apply", read from the same member list `restore_backup` reads and grouped by the same
rule, so the form cannot offer something the restore would not consider.
"""

from __future__ import annotations

import json
import os
import zipfile

from lib import APP_NAME
from lib.debug.debug_level import DebugLevel

from .archive import (archive_path, DB_DIR, FILES_DIR, _log, member_tables, PARTS_PREFIX,
                      read_manifest, restore_cell, FORMAT, MANIFEST_NAME)
from . import parts as _parts
from .parts import conn_for, tables_in_archive_by_part, PARTS


def archive_contents(var_dir: str, name: str, backup_dir: str = '') -> dict:
    """What one archive holds, part by part and table by table.

    Exists for the restore form's advanced half, which offers the TABLES inside a part rather
    than the part alone. The grouping is worked out here and not in the browser on purpose:
    `core` means "every table nobody else claimed", and that rule already decides what a copy
    holds and what a restore applies — a third answer to it, computed in JavaScript from the
    manifest, would be right until the day somebody adds a part.

    Read from the archive's own member list, which is what `restore_backup` reads, so the form
    offers exactly what the restore would consider. The row counts come from the manifest,
    which is the only place they exist without decompressing every member.
    """
    path = archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        return {'ok': False, 'message': 'backup not found'}
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            man = json.loads(zf.read(MANIFEST_NAME).decode('utf-8'))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return {'ok': False, 'message': f'not a {APP_NAME} backup'}
    counts = man.get('tables') or {}
    by_part = tables_in_archive_by_part(member_tables(names), set(man.get('parts') or []))
    parts = [{'id': pid,
              'tables': [{'name': t, 'rows': int(counts.get(t) or 0)} for t in tabs]}
             for pid, tabs in by_part if tabs]
    return {'ok': True, 'parts': parts}


def restore_backup(connector, var_dir: str, name: str, *, parts=None, tables=None,
                   config_dir: str = '', backup_dir: str = '', progress_cb=None,
                   connectors=None, dirs=None) -> dict:
    """Put an archive's contents back, table by table.

    *parts* narrows what is applied; None means everything the archive holds. A table is
    emptied and refilled, not merged: a backup is a statement about what the install looked
    like, and merging would produce a third state that never existed anywhere.

    *tables* narrows it FURTHER, to named tables inside those parts; None means every table the
    parts cover, which is what every caller before this asked for. It is the finer grain the
    form calls "advanced", and it is genuinely finer-grained rather than safer: restoring
    `hosts` without `credentials` leaves rows pointing at a credential that is no longer there,
    and nothing here will stop it — the parts are a curated grouping, a hand-picked list of
    tables is not. What it is FOR is the opposite case, the one part-level restore cannot
    express: a bad import touched one table and everything else on the install has moved on
    since the copy was taken.

    A part left with none of its tables chosen is dropped entirely rather than reported as an
    empty step: it was excluded, and a checklist line saying "0 rows, ok" about something
    nobody asked for reads as a failure.

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
    path = archive_path(var_dir, name, backup_dir)
    if not path or not os.path.isfile(path):
        _log(f'> Backup > restore >> {name!r} not found', DebugLevel.warning)
        return {'ok': False, 'message': 'backup not found'}
    man = read_manifest(path)
    if man is None:
        _log(f'> Backup > restore >> {name!r} is not one of ours', DebugLevel.warning)
        return {'ok': False, 'message': f'not a {APP_NAME} backup'}
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
    # None and an empty list are different answers, and reading them the same way would be the
    # dangerous half: `tables=[]` says "no table at all", and treating it as "every table"
    # would rewrite the whole install for somebody who asked for nothing.
    only = None if tables is None else {str(t) for t in tables}

    restored: dict = {}
    files: dict = {}
    # What the live schema could not take. Empty is the normal answer; anything in it is the
    # difference between "restored" and "restored, and here is what did not survive the trip".
    skipped: dict = {}
    _log(f'> Backup > restore >> {name!r} parts={sorted(want)} '
         + (f'tables={sorted(only)} ' if only is not None else '')
         + f'made with {man.get("app_version") or "?"}',
         # A restore of hand-picked tables is not the operation the parts describe: what is left
         # alone is left alone on purpose, and the log is where somebody works out afterwards
         # why half the install is older than the other half.
         DebugLevel.warning if only is not None else DebugLevel.info)

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
            by_part = tables_in_archive_by_part(member_tables(names), want)
            if only is not None:
                by_part = [(pid, [t for t in tabs if t in only]) for pid, tabs in by_part]
                by_part = [(pid, tabs) for pid, tabs in by_part if tabs]
            # Every directory part, the core's own included — see `parts.dir_parts`. Asked
            # for the modules' alone, a floor plan went into the archive and never came out
            # of it, which is the worst shape a backup bug takes: it only shows at a restore.
            file_parts = [mp for mp in _parts.dir_parts() if mp['id'] in want]
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
                                zf.read(f'{DB_DIR}/{table}.json').decode('utf-8'))
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
                member = f'{FILES_DIR}/config.json'
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
                n = _extract_tree(zf, names, f'{PARTS_PREFIX}/{mp["id"]}',
                                  _parts.part_dir(mp, var_dir, dirs))
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
            'secrets': bool(man.get('secrets')),
            # Whether this was the parts as they come or a hand-picked list. Answered in the
            # RESULT rather than left to whoever asked, because the report on screen and the
            # audit line both have to say it — "148 rows in 9 tables" reads as a full restore
            # unless something says the other tables were left as they are.
            'partial': only is not None}


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
    rows = [tuple(restore_cell(r[i]) for i in idx) for r in (payload.get('rows') or [])]
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
