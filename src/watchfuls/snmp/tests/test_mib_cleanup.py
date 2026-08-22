#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What deleting a MIB leaves behind.

`compiled/` is flat, and every file in it is named after the MODULE — `IEEE8023-LAG-MIB.py`,
whatever the source was called and whichever vendor folder it sat in. So deleting a folder of
sources cannot take its compilations with it: nothing in the library's shape says which .py
came from where. They stay, loadable, impossible to rebuild, and — until this — counted as
"dependencies pysmi pulled in", which is what three hundred and seventy-four leftovers looked
like beside three real ones.

The one record of where a .py came from is the header pysmi writes into it, and that is what
tells the two apart:

* a path under `raw/` that is not there any more → a leftover, and nothing needs it;
* no path under `raw/` at all → pysmi resolved it from its own bundled MIBs or over HTTP. It
  cannot be rebuilt from anything here either, and every module importing it stops loading
  the day it goes.

And the folder itself: `os.remove` removes files, so an emptied vendor folder stays as a
folder — as does the parent whose only content is that folder.
"""

import io
import os

import pytest

from watchfuls.snmp.mib_admin import MibAdmin as MA


_MIB = 'A-MIB DEFINITIONS ::= BEGIN\nEND\n'


@pytest.fixture()
def tree(tmp_path):
    """A var_dir with an empty raw folder — each test drops in what it needs."""
    (tmp_path / 'snmp_mibs' / 'raw').mkdir(parents=True)
    return {'__var_dir__': str(tmp_path)}


def _raw(cfg, relpath, module=None):
    """A source file, declaring *module* (its own name by default)."""
    name = module or os.path.splitext(os.path.basename(relpath))[0]
    path = os.path.join(cfg['__var_dir__'], 'snmp_mibs', 'raw', *relpath.split('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(f'{name} DEFINITIONS ::= BEGIN\nEND\n')
    return path


def _compiled(cfg, mib, source_rel=None):
    """A .py as pysmi leaves it. Without *source_rel*, one it did not read out of `raw/`."""
    comp = os.path.join(cfg['__var_dir__'], 'snmp_mibs', 'compiled')
    os.makedirs(comp, exist_ok=True)
    head = '# Produced by pysmi\n'
    if source_rel:
        raw = os.path.join(cfg['__var_dir__'], 'snmp_mibs', 'raw', *source_rel.split('/'))
        head = f'# ASN.1 source file://{raw}\n' + head
    path = os.path.join(comp, f'{mib}.py')
    with io.open(path, 'w', encoding='utf-8') as fh:
        fh.write(head)
    return path


def _names(report):
    return sorted(e['mib'] for e in report['stray'])


class TestACompilationWhoseSourceIsGone:

    def test_it_is_reported(self, tree):
        _compiled(tree, 'A-MIB', 'librenms/acme/A-MIB')     # …and no such file
        out = MA.library_leftovers(tree)
        assert out['ok'] is True
        assert _names(out) == ['A-MIB']
        assert out['stray'][0]['source'] == 'librenms/acme/A-MIB'
        assert out['stray'][0]['size'] > 0
        assert out['stray_bytes'] == out['stray'][0]['size']

    def test_a_source_that_is_still_there_is_not(self, tree):
        _raw(tree, 'librenms/acme/A-MIB')
        _compiled(tree, 'A-MIB', 'librenms/acme/A-MIB')
        assert _names(MA.library_leftovers(tree)) == []

    def test_a_source_that_moved_folder_is_not(self, tree):
        """The .py names the file it read. That file being gone is not the question — the
        question is whether anything still DECLARES the module, wherever it now lives."""
        _raw(tree, 'custom/A-MIB')
        _compiled(tree, 'A-MIB', 'librenms/acme/A-MIB')
        assert _names(MA.library_leftovers(tree)) == []

    def test_a_source_under_another_file_name_is_not(self, tree):
        """`trunk.mib` declares IEEE8023-LAG-MIB. Comparing file names deletes what is still
        there and keeps what is not."""
        _raw(tree, 'custom/trunk.mib', module='IEEE8023-LAG-MIB')
        _compiled(tree, 'IEEE8023-LAG-MIB', 'librenms/ieee/IEEE8023-LAG-MIB')
        assert _names(MA.library_leftovers(tree)) == []

    def test_a_dependency_pysmi_found_elsewhere_is_not(self, tree):
        """No path under `raw/` in its header: pysmi resolved it from its own bundled MIBs
        or over HTTP. Nothing here can rebuild it, and every module importing it stops
        loading the day it goes."""
        _compiled(tree, 'SNMPv2-TC')
        assert _names(MA.library_leftovers(tree)) == []

    def test_only_the_python_files_are_looked_at(self, tree):
        """pysmi leaves `__pycache__` and the odd `.json` beside its output."""
        comp = os.path.join(tree['__var_dir__'], 'snmp_mibs', 'compiled')
        _compiled(tree, 'A-MIB', 'librenms/acme/A-MIB')
        os.makedirs(os.path.join(comp, '__pycache__'))
        io.open(os.path.join(comp, 'index.json'), 'w', encoding='utf-8').write('{}')
        assert _names(MA.library_leftovers(tree)) == ['A-MIB']


class TestSweepingThemUp:

    def test_it_deletes_the_leftovers_and_nothing_else(self, tree):
        _raw(tree, 'custom/B-MIB')
        _compiled(tree, 'A-MIB', 'librenms/acme/A-MIB')     # gone
        _compiled(tree, 'B-MIB', 'custom/B-MIB')            # still there
        _compiled(tree, 'SNMPv2-TC')                        # a dependency
        out = MA.clean_library(tree)
        assert out['ok'] is True and out['compiled_deleted'] == 1
        left = sorted(os.listdir(os.path.join(tree['__var_dir__'], 'snmp_mibs', 'compiled')))
        assert left == ['B-MIB.py', 'SNMPv2-TC.py']

    def test_a_tidy_library_reports_nothing_done(self, tree):
        _raw(tree, 'custom/B-MIB')
        _compiled(tree, 'B-MIB', 'custom/B-MIB')
        assert MA.clean_library(tree) == {'ok': True, 'compiled_deleted': 0,
                                          'folders_removed': 0}

    def test_it_reads_the_library_again_rather_than_trusting_the_report(self, tree):
        """Between the report and the click somebody may have imported the very source that
        makes a leftover a compiled module again."""
        _compiled(tree, 'A-MIB', 'librenms/acme/A-MIB')
        assert _names(MA.library_leftovers(tree)) == ['A-MIB']
        _raw(tree, 'librenms/acme/A-MIB')
        assert MA.clean_library(tree)['compiled_deleted'] == 0

    def test_the_symbol_catalogue_goes_when_something_did(self, tree, monkeypatch):
        """It names modules that are no longer there, and no timestamp can notice that."""
        from lib.core.snmp.mibs import catalog as mib_catalog
        seen = []
        monkeypatch.setattr(mib_catalog, 'discard', lambda v: seen.append(v))
        MA.clean_library(tree)
        assert seen == []
        _compiled(tree, 'A-MIB', 'librenms/acme/A-MIB')
        MA.clean_library(tree)
        assert seen == [tree['__var_dir__']]

    def test_no_var_dir_is_refused_by_both(self, tree):
        assert MA.library_leftovers({})['ok'] is False
        assert MA.clean_library({})['ok'] is False


class TestTheFoldersThemselves:

    def test_an_emptied_folder_is_reported_and_removed(self, tree):
        raw = os.path.join(tree['__var_dir__'], 'snmp_mibs', 'raw')
        os.makedirs(os.path.join(raw, 'librenms', 'acme'))
        assert MA.library_leftovers(tree)['empty_dirs'] == ['librenms', 'librenms/acme']
        assert MA.clean_library(tree)['folders_removed'] == 2
        assert os.listdir(raw) == [] or os.listdir(raw) == ['.facts-cache.json']

    def test_a_folder_with_a_file_below_it_survives(self, tree):
        _raw(tree, 'librenms/acme/A-MIB')
        assert MA.library_leftovers(tree)['empty_dirs'] == []
        MA.clean_library(tree)
        assert os.path.isdir(os.path.join(tree['__var_dir__'], 'snmp_mibs',
                                          'raw', 'librenms', 'acme'))

    def test_the_library_itself_is_never_removed(self, tree):
        raw = os.path.join(tree['__var_dir__'], 'snmp_mibs', 'raw')
        MA.clean_library(tree)
        assert os.path.isdir(raw)

    def test_a_folder_holding_only_empty_folders_is_empty_too(self, tree):
        """Walking bottom-up and stopping at the first branch leaves the parent behind, and
        one more click leaves its parent."""
        raw = os.path.join(tree['__var_dir__'], 'snmp_mibs', 'raw')
        os.makedirs(os.path.join(raw, 'a', 'b', 'c'))
        _raw(tree, 'a/keep/A-MIB')
        out = MA.library_leftovers(tree)
        assert out['empty_dirs'] == ['a/b', 'a/b/c']
        assert MA.clean_library(tree)['folders_removed'] == 2
        assert sorted(os.listdir(os.path.join(raw, 'a'))) == ['keep']
