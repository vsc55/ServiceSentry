#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A module's own files get into the backup because the MODULE says so.

The copy used to hold `var_dir/snmp_mibs/raw` because that path was written into
`lib/core/backup/service.py` — the core naming a module, which is the one thing this codebase
does not do. It held the SNMP module's files and would have missed the next module's, silently,
the way a backup that skips what it did not recognise always does.

What these guard is the declaration and the two halves that read it: the catalogue built from
`__backup_part__`, and that neither the copy nor the restore knows any module by name.
"""

import io
import json
import os
import re

from lib.core.backup import create as bk_create
from lib.core.backup import parts as bk_parts
from lib.core.backup import restore as bk_restore
from lib.modules.discovery.backup_parts import _safe_rel, backup_parts_catalog

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


def _module_parts(root, **kw):
    """Only the parts a MODULE under *root* contributes.

    The catalogue also carries what CORE packages declare (SNMP's MIB library), which is
    there whatever the watchfuls directory holds — these tests are about module
    contribution, so they filter to it rather than pretending the rest is absent."""
    return [p for p in backup_parts_catalog(root, **kw) if p.get('module')]


def _write_module(root, name, schema, lang=None):
    mdir = os.path.join(root, name)
    os.makedirs(os.path.join(mdir, 'lang'), exist_ok=True)
    with io.open(os.path.join(mdir, 'schema.json'), 'w', encoding='utf-8') as fh:
        json.dump(schema, fh)
    if lang is not None:
        with io.open(os.path.join(mdir, 'lang', 'es_ES.json'), 'w', encoding='utf-8') as fh:
            json.dump(lang, fh)
    return mdir


class TestTheCatalogueIsBuiltFromTheDeclaration:

    def test_a_module_contributes_its_directory(self, tmp_path):
        root = str(tmp_path)
        _write_module(root, 'thing', {'__backup_part__': {
            'id': 'stuff', 'dir': 'thing_files/raw', 'label_key': 'backup_part_stuff'}},
            {'pretty_name': 'Thing', 'ui': {'backup_part_stuff': 'Ficheros de Thing'}})
        got = _module_parts(root)
        assert got == [{'id': 'stuff', 'module': 'thing', 'dir': 'thing_files/raw',
                        'default': False,
                        'label_i18n': {'es_ES': 'Ficheros de Thing'}}]

    def test_the_id_defaults_to_the_module(self, tmp_path):
        root = str(tmp_path)
        _write_module(root, 'thing', {'__backup_part__': {'dir': 'x'}})
        assert _module_parts(root)[0]['id'] == 'thing'

    def test_the_label_falls_back_to_the_module_name(self, tmp_path):
        """Right when a module contributes ONE part: its own name is the answer, and it is
        already translated for every other screen."""
        root = str(tmp_path)
        _write_module(root, 'thing', {'__backup_part__': {'dir': 'x'}},
                      {'pretty_name': 'Cosa'})
        assert _module_parts(root)[0]['label_i18n'] == {'es_ES': 'Cosa'}

    def test_a_module_may_contribute_several(self, tmp_path):
        root = str(tmp_path)
        _write_module(root, 'thing', {'__backup_part__': [
            {'id': 'a', 'dir': 'one'}, {'id': 'b', 'dir': 'two', 'default': True}]})
        got = {p['id']: p for p in _module_parts(root)}
        assert set(got) == {'a', 'b'} and got['b']['default'] is True

    def test_a_module_without_the_declaration_contributes_nothing(self, tmp_path):
        root = str(tmp_path)
        _write_module(root, 'thing', {'__icon__': 'bi-x'})
        assert _module_parts(root) == []

    def test_a_broken_schema_does_not_cost_the_others_theirs(self, tmp_path):
        """Discovery is per file precisely so a bad module stays contained."""
        root = str(tmp_path)
        os.makedirs(os.path.join(root, 'bad'))
        with io.open(os.path.join(root, 'bad', 'schema.json'), 'w', encoding='utf-8') as fh:
            fh.write('{ not json')
        _write_module(root, 'good', {'__backup_part__': {'dir': 'x'}})
        assert [p['module'] for p in _module_parts(root)] == ['good']


class TestADeclarationCannotEscapeVarDir:
    """This directory is READ when a copy is made and WRITTEN when one is restored. A module
    that could point it anywhere would be choosing where the panel writes."""

    def test_paths_that_climb_out_are_dropped(self):
        assert _safe_rel('../../etc') == ''
        assert _safe_rel('a/../../b') == ''
        assert _safe_rel('/etc/passwd') == ''
        assert _safe_rel('C:\\Windows') == ''

    def test_an_ordinary_relative_path_is_kept_and_normalised(self):
        """Separators either way round, because a module may be written on either platform and
        the copy has to work on both."""
        assert _safe_rel('snmp_mibs/raw') == 'snmp_mibs/raw'
        assert _safe_rel('snmp_mibs\\raw\\') == 'snmp_mibs/raw'
        assert _safe_rel('\\snmp_mibs\\raw') == '', 'a rooted path is not a relative one'

    def test_an_empty_declaration_contributes_nothing(self, tmp_path):
        root = str(tmp_path)
        _write_module(root, 'thing', {'__backup_part__': {'id': 'x'}})
        assert _module_parts(root) == []

    def test_a_module_cannot_take_a_core_part_id(self, tmp_path):
        """`core` is every table nothing else claimed; a module shadowing it would replace the
        copy's tables with a directory."""
        root = str(tmp_path)
        _write_module(root, 'thing', {'__backup_part__': {'id': 'core', 'dir': 'x'}})
        assert _module_parts(root, reserved=bk_parts.PART_IDS) == []

    def test_two_modules_cannot_claim_the_same_id(self, tmp_path):
        root = str(tmp_path)
        _write_module(root, 'aaa', {'__backup_part__': {'id': 'same', 'dir': 'x'}})
        _write_module(root, 'bbb', {'__backup_part__': {'id': 'same', 'dir': 'y'}})
        assert [p['module'] for p in _module_parts(root)] == ['aaa']


class TestTheCoreNamesNoModule:
    """The rule this whole hook exists for."""

    def test_the_backup_service_carries_no_module_name(self):
        """Read out of its string LITERALS, not out of its prose: a comment may say the word
        `snmp` while explaining why nothing here does, and "backups" contains the name of a
        module called `ups`. What must not exist is a path or an id built from one."""
        src = io.open(os.path.join(SRC, 'lib', 'core', 'backup', 'service.py'),
                      encoding='utf-8').read()
        modules = {d for d in os.listdir(os.path.join(SRC, 'watchfuls'))
                   if not d.startswith('_')
                   and os.path.isdir(os.path.join(SRC, 'watchfuls', d))}
        tokens = set()
        for lit in re.findall(r"'([^'\n]*)'|\"([^\"\n]*)\"", src):
            tokens.update(re.split(r'[^A-Za-z0-9]+', lit[0] or lit[1]))
        # `syslog` is a core SERVICE with tables of its own, not a watchful — the module of
        # that name is a different thing, and the part named here is the service's.
        named = sorted((tokens & modules) - {'syslog'})
        assert named == [], f'the core names {named}'

    def test_the_core_catalogue_holds_no_module_part(self):
        assert 'mibs' not in bk_parts.PART_IDS

    def test_the_snmp_library_is_still_offered(self):
        """It used to be the MODULE that supplied it, and that was the failure: a backup part
        lives as long as the file declaring it, so removing the watchful took the MIB library
        out of every backup and said nothing — the archive is simply smaller, and you find
        out when you need it. The core declares it now, so `module` is empty on purpose."""
        got = {p['id']: p for p in bk_parts.parts_catalogue('es_ES')}
        assert 'mibs' in got, 'the SNMP MIB library is no longer offered to a backup'
        assert got['mibs']['module'] == '' 
        assert got['mibs'].get('label') and 'backup_part' not in got['mibs']['label']

    def test_a_module_part_is_labelled_not_keyed(self):
        """Its wording lives in the module's lang files, which the browser's catalogue does not
        hold — shipping the key alone would put `backup_part_mibs` on screen."""
        got = {p['id']: p for p in bk_parts.parts_catalogue('es_ES')}
        assert 'label_key' not in got['mibs']
        assert 'label' not in got['core'], 'a core part stopped carrying its key'


class TestTheFilesActuallyTravel:
    """The declaration is only half of it: the copy has to hold the module's files and the
    restore has to put them back where that module says they live."""

    @staticmethod
    def _db(tmp_path):
        from lib.db.schema import Column, TableSpec
        from lib.db.sqlite import SQLiteConnector
        con = SQLiteConnector(str(tmp_path / 'data.db'))
        con.reconcile_table(TableSpec(name='hosts',
                                      columns=[Column('uid', 'TEXT', nullable=True)]))
        con.execute("INSERT INTO hosts (uid) VALUES ('h1')")
        con.commit()
        return con

    @staticmethod
    def _declare(monkeypatch, pid='stuff', rel='thing_files/raw'):
        monkeypatch.setattr(bk_parts, 'module_parts', lambda: [
            {'id': pid, 'module': 'thing', 'dir': rel, 'default': False,
             'label_i18n': {'en_EN': 'Thing files'}}])

    def test_a_declared_directory_is_copied_and_restored(self, tmp_path, monkeypatch):
        self._declare(monkeypatch)
        var = tmp_path / 'var'
        raw = var / 'thing_files' / 'raw'
        os.makedirs(str(raw))
        io.open(str(raw / 'one.txt'), 'w', encoding='utf-8').write('hello')
        con = self._db(tmp_path)

        res = bk_create.create_backup(con, 'copia', var_dir=str(var), config_dir=str(tmp_path),
                                      parts=['core', 'stuff'], include_secrets=True)
        assert res['ok'], res
        assert res['manifest']['files']['stuff'] == 1
        step = next(s for s in res['manifest']['steps'] if s['part'] == 'stuff')
        assert step['ok'] and step['rows'] == 1

        os.remove(str(raw / 'one.txt'))
        out = bk_restore.restore_backup(con, str(var), 'copia', config_dir=str(tmp_path))
        assert out['ok'], out
        assert io.open(str(raw / 'one.txt'), encoding='utf-8').read() == 'hello'
        con.close()

    def test_the_archive_places_it_by_id_not_by_path(self, tmp_path, monkeypatch):
        """Derived from the id on both sides, so a copy and a restore cannot disagree about
        where the files are — and the archive carries no module's directory layout."""
        self._declare(monkeypatch)
        var = tmp_path / 'var'
        os.makedirs(str(var / 'thing_files' / 'raw'))
        io.open(str(var / 'thing_files' / 'raw' / 'one.txt'), 'w').write('x')
        con = self._db(tmp_path)
        bk_create.create_backup(con, 'copia', var_dir=str(var), config_dir=str(tmp_path),
                                parts=['core', 'stuff'], include_secrets=True)
        import zipfile
        with zipfile.ZipFile(str(var / 'backups' / 'copia.zip')) as zf:
            names = zf.namelist()
        assert 'files/parts/stuff/one.txt' in names, names
        con.close()

    def test_a_part_nobody_declares_is_not_copied(self, tmp_path, monkeypatch):
        """Asking for the part of a module that is not installed must not make a copy that
        claims to hold it."""
        monkeypatch.setattr(bk_parts, 'module_parts', lambda: [])
        con = self._db(tmp_path)
        res = bk_create.create_backup(con, 'copia', var_dir=str(tmp_path / 'var'),
                                      config_dir=str(tmp_path), parts=['core', 'stuff'],
                                      include_secrets=True)
        assert res['ok']
        assert 'stuff' not in res['manifest']['parts']
        con.close()

    def test_a_declared_directory_that_is_empty_marks_its_part(self, tmp_path, monkeypatch):
        """A part that was asked for and produced nothing is not ok. Writing a copy without it
        and calling it complete is how a restore finds out at the worst moment."""
        self._declare(monkeypatch)
        con = self._db(tmp_path)
        res = bk_create.create_backup(con, 'copia', var_dir=str(tmp_path / 'var'),
                                      config_dir=str(tmp_path), parts=['core', 'stuff'],
                                      include_secrets=True)
        step = next(s for s in res['manifest']['steps'] if s['part'] == 'stuff')
        assert not step['ok'] and res['manifest']['status'] == 'partial'
        con.close()
