#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What a copy can hold — the catalogue, and which tables each part means.

The vocabulary both directions read. A copy is written part by part and a restore is applied
part by part, and the rule that says which tables a part covers has to give the SAME answer to
both — `core` is "every table nobody else claimed", so a second implementation of it would be
right until the day somebody adds a part.

That is also why the UI reads it from here through the API instead of grouping the manifest
itself: three answers to one rule is two too many.

Imports nothing from its siblings: it names tables, it does not open archives.
"""

from __future__ import annotations

import os


# Engine bookkeeping. Never dumped, never restored: they describe the storage, not the install,
# and writing SQLite's own statistics into a MySQL restore is at best noise.
INTERNAL_TABLES = frozenset({'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4'})


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
    # A directory of the CORE's own — the first one. Floor plans are files somebody uploaded,
    # and the database holds only their names: a copy without them restores rooms whose plans
    # are gone. On by default because they are small and irreplaceable, which is the pair of
    # properties that decides this.
    #
    # `dir_attr` is what makes the setting `web_admin|dcim_media_dir` reach this far: the
    # folder can be moved to another disk, and a copy that resolved `dcim_media` against
    # `var_dir` anyway would archive the empty default. Named here rather than at the call
    # site so the next configurable folder is one key, not another branch — see
    # `configured_dirs`.
    {'id': 'dcim_media', 'kind': 'dir', 'dir': 'dcim_media', 'dir_attr': '_DCIM_MEDIA_DIR',
     'default': True, 'required': False, 'label_key': 'backup_part_dcim_media'},
)

PART_IDS: tuple = tuple(p['id'] for p in PARTS)
_CLAIMED_TABLES: frozenset = frozenset(
    t for p in PARTS if p['kind'] == 'db' and p['tables'] for t in p['tables'])


def dir_parts() -> list:
    """Every part that is a DIRECTORY under ``var_dir`` — the core's own, then the modules'.

    One list because the two are copied and restored identically: a folder in, a folder out.
    The loops that do it used to ask for the modules' alone, which was right while the core had
    no directories of its own and stopped being right the day it did — and it would have failed
    the way this domain's failures do, by simply not copying something and saying nothing.
    """
    core = [{'id': p['id'], 'dir': p['dir'], 'default': p['default'],
             'label_i18n': {}, 'label_key': p['label_key']}
            for p in PARTS if p.get('kind') == 'dir']
    return core + module_parts()


def configured_dirs(holder) -> dict:
    """``{part_id: path}`` for every core part whose folder has been MOVED.

    The other half of :func:`part_dir`, which has always known how to honour an override and
    was never given one: `dirs` reached `create_backup` and `restore_backup` as a parameter
    nobody filled in, so an install with `web_admin|dcim_media_dir` set copied
    `<var_dir>/dcim_media` — the default folder, empty — and a restore would have put the
    floor plans back into a directory the panel does not read.

    *holder* is whatever object carries the resolved settings (the web admin), read by the
    attribute the part declares. Only the ones actually set are returned: an empty setting
    means "the default", and `part_dir` already knows what that is.

    Reading it on every call and not once at start-up is the same rule the setting itself
    follows — moving the folder must not need a restart.
    """
    out: dict = {}
    for p in PARTS:
        attr = p.get('dir_attr')
        if not attr:
            continue
        path = str(getattr(holder, attr, '') or '').strip()
        if path:
            out[p['id']] = path
    return out


def part_dir(part: dict, var_dir: str, dirs=None) -> str:
    """Dónde vive de verdad la carpeta de una parte.

    Casi siempre `<var_dir>/<lo declarado>`, que es lo que vale para todo lo de un módulo. Pero
    una parte del núcleo puede ser **configurable** —la de los planos lo es— y entonces resolver
    contra `var_dir` copiaría la carpeta por defecto, vacía, y lo diría como un éxito. Un fallo
    de copia que solo se ve en una restauración es el peor que hay.
    """
    override = str((dirs or {}).get(part.get('id')) or '').strip()
    if override:
        return override
    return os.path.join(var_dir, *str(part.get('dir') or '').split('/'))


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


def part_ids() -> set:
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


def tables_by_part(connector, parts: set, connectors=None) -> list:
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
                       if t not in INTERNAL_TABLES]
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


def tables_for(connector, parts: set, connectors=None) -> list:
    """Which tables the chosen *parts* cover, in a stable order."""
    return sorted({t for _pid, tabs in tables_by_part(connector, parts, connectors)
                   for t in tabs})


def tables_in_archive_by_part(in_zip: list, want: set) -> list:
    """``[(part_id, [tables])]`` for the wanted parts, in catalogue order.

    Grouped, because a restore is REPORTED by part — the unit somebody ticked in the form —
    while it is applied table by table. The mirror of `tables_by_part` on the way out, and
    kept as the one place that decides so the two directions cannot disagree about which
    tables a part means.

    Takes the TABLE NAMES an archive holds, not its member list: turning ``db/hosts.json``
    into ``hosts`` is the layout's business (`archive.member_tables`), and this module's job
    is the grouping. Kept apart so neither has to know the other's rule.
    """
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
