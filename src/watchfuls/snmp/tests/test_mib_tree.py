#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Raw MIBs live in a tree, and everything that reads them has to know.

Once an import keeps the folder a file came from, a MIB that used to sit in ``raw/`` sits in
``raw/synology/``. Every place that scanned that directory flat then reports **nothing** — and
"nothing" is not an error anywhere in this module: the count says zero, the compile job finds no
work and finishes instantly, and the button reads as broken. Three separate scans had to be
found by hand after the first one was fixed, which is what this file is for.

The other half is the join between what the panel SELECTS and what pysmi COMPILES. The panel
selects files, which now carry their folder; pysmi compiles module names, which never do. A
selection of ``synology/SYNOLOGY-DISK-MIB.txt`` filtered against the name
``SYNOLOGY-DISK-MIB`` matches nothing, and the compile again does nothing at all.
"""

import os

import pytest

from watchfuls.snmp import mib_resolver


def _tree(tmp_path):
    """A raw directory the way an archive import leaves it: some loose, some in folders."""
    raw = tmp_path / 'raw'
    (raw / 'synology').mkdir(parents=True)
    (raw / 'vendor' / 'deep').mkdir(parents=True)
    (raw / 'LOOSE-MIB.txt').write_text('LOOSE-MIB DEFINITIONS ::= BEGIN\nEND\n', encoding='utf-8')
    (raw / 'synology' / 'SYNOLOGY-DISK-MIB.txt').write_text('x', encoding='utf-8')
    (raw / 'synology' / 'SYNOLOGY-UPS-MIB.txt').write_text('x', encoding='utf-8')
    (raw / 'vendor' / 'deep' / 'DEEP-MIB.mib').write_text('x', encoding='utf-8')
    (raw / '.hidden.txt').write_text('x', encoding='utf-8')
    return raw


class TestWalkingTheTree:

    def test_a_mib_in_a_folder_is_found(self, tmp_path):
        raw = _tree(tmp_path)
        found = {rel for rel, _f in mib_resolver.iter_raw_mibs(str(raw))}
        assert 'synology/SYNOLOGY-DISK-MIB.txt' in found
        assert 'vendor/deep/DEEP-MIB.mib' in found
        assert 'LOOSE-MIB.txt' in found, 'files that were already flat still count'

    def test_hidden_files_are_not_mibs(self, tmp_path):
        raw = _tree(tmp_path)
        assert all(not os.path.basename(rel).startswith('.')
                   for rel, _f in mib_resolver.iter_raw_mibs(str(raw)))

    def test_the_relative_path_uses_forward_slashes(self, tmp_path):
        """It is an identifier that travels to the browser and comes back to delete a file;
        a backslash on Windows would make it a different string on the way home."""
        raw = _tree(tmp_path)
        assert all('\\' not in rel for rel, _f in mib_resolver.iter_raw_mibs(str(raw)))

    def test_a_directory_that_does_not_exist_is_empty(self, tmp_path):
        assert mib_resolver.iter_raw_mibs(str(tmp_path / 'nope')) == []

    def test_the_walk_is_bounded(self, tmp_path):
        """A raw directory is where files get dropped by hand, and one of them will one day be
        a symlink or an unpacked kernel tree."""
        raw = tmp_path / 'raw'
        deep = raw
        for i in range(mib_resolver.RAW_MAX_DEPTH + 3):
            deep = deep / f'l{i}'
        deep.mkdir(parents=True)
        (deep / 'TOO-DEEP-MIB.txt').write_text('x', encoding='utf-8')
        assert mib_resolver.iter_raw_mibs(str(raw)) == []


class TestWhatPysmiIsGiven:

    def test_every_folder_holding_mibs_is_a_source(self, tmp_path):
        """pysmi resolves an imported module by NAME against the directories it was given and
        knows nothing about a tree — so a vendor MIB in a sub-folder could not import the
        standard one sitting beside it."""
        raw = _tree(tmp_path)
        dirs = mib_resolver.raw_mib_dirs(str(raw))
        assert os.path.abspath(str(raw)) in dirs
        assert os.path.abspath(str(raw / 'synology')) in dirs
        assert os.path.abspath(str(raw / 'vendor' / 'deep')) in dirs

    def test_a_folder_with_no_mibs_is_not_a_source(self, tmp_path):
        raw = tmp_path / 'raw'
        (raw / 'empty').mkdir(parents=True)
        assert mib_resolver.raw_mib_dirs(str(raw)) == [os.path.abspath(str(raw))]


class TestWhatNeedsCompiling:

    def test_a_mib_in_a_folder_is_pending(self, tmp_path):
        """The scan that answers "what is there to compile". Flat, it answered *nothing* for an
        installation whose MIBs all arrived inside one archive — and a compile with nothing to
        compile finishes instantly and looks like a button that does not work."""
        raw = _tree(tmp_path)
        compiled = tmp_path / 'compiled'
        compiled.mkdir()
        pending = mib_resolver.pending_raw_mibs(str(raw), str(compiled))
        assert 'SYNOLOGY-DISK-MIB' in pending and 'DEEP-MIB' in pending

    def test_it_answers_module_names_and_not_paths(self, tmp_path):
        """pysmi compiles a module by name and writes one file per name; which folder it was
        found in is where it was found, not what it is called."""
        raw = _tree(tmp_path)
        pending = mib_resolver.pending_raw_mibs(str(raw), str(tmp_path / 'none'))
        assert all('/' not in p and not p.endswith('.txt') for p in pending)

    def test_one_name_is_asked_for_once(self, tmp_path):
        """Two vendor folders can each hold a SNMPv2-SMI. They are one module to compile, and
        asking twice compiles it twice."""
        raw = tmp_path / 'raw'
        (raw / 'a').mkdir(parents=True)
        (raw / 'b').mkdir(parents=True)
        (raw / 'a' / 'SHARED-MIB.txt').write_text('x', encoding='utf-8')
        (raw / 'b' / 'SHARED-MIB.txt').write_text('x', encoding='utf-8')
        assert mib_resolver.pending_raw_mibs(str(raw), '') == ['SHARED-MIB']

    def test_a_compiled_module_settles_its_source_wherever_it_lives(self, tmp_path):
        raw = _tree(tmp_path)
        compiled = tmp_path / 'compiled'
        compiled.mkdir()
        for stem in ('LOOSE-MIB', 'SYNOLOGY-DISK-MIB', 'SYNOLOGY-UPS-MIB', 'DEEP-MIB'):
            p = compiled / f'{stem}.py'
            p.write_text('# compiled', encoding='utf-8')
            os.utime(p, (2 ** 31, 2 ** 31))     # far newer than the sources
        assert mib_resolver.pending_raw_mibs(str(raw), str(compiled)) == []

    def test_the_shortcut_sees_a_mib_in_a_folder(self, tmp_path):
        """`raw_dir_has_new_mibs` is what decides whether to pay the compiler's start-up cost.
        Blind to folders, it says no and the automatic compile never runs."""
        raw = _tree(tmp_path)
        assert mib_resolver.raw_dir_has_new_mibs(str(raw), str(tmp_path / 'none')) is True


class TestAFileIsFoundByOneNameAndBecomesAnother:
    """The bug this whole distinction exists for.

    `trunk.mib`, in a switch vendor's archive, declares IEEE8023-LAG-MIB. pysmi is asked for
    `trunk` — that is how it locates the file — and writes `IEEE8023-LAG-MIB.py`, because that
    is what the module is called. Anything that then asks "is `trunk` compiled?" is asking
    about a file that will never exist: the MIB compiles perfectly, is reported PENDING for
    ever, and every compile run does it again and answers "already up to date".

    On a real library that was 132 pending of which 117 were an illusion, and 97 modules
    labelled dependencies that the user had shipped themselves.
    """

    def test_the_module_comes_from_inside_the_file(self, tmp_path):
        p = tmp_path / 'trunk.mib'
        p.write_text('IEEE8023-LAG-MIB DEFINITIONS ::= BEGIN\nEND\n', encoding='utf-8')
        assert mib_resolver.raw_module_name(str(p)) == 'IEEE8023-LAG-MIB'

    def test_a_file_that_declares_nothing_answers_nothing(self, tmp_path):
        """Rather than guessing from the name — the caller has the file name already and can
        decide what to do with it; a guess dressed as an answer cannot be told apart."""
        p = tmp_path / 'notes.txt'
        p.write_text('a list of OIDs\n', encoding='utf-8')
        assert mib_resolver.raw_module_name(str(p)) == ''
        assert mib_resolver.raw_module_name('') == ''
        assert mib_resolver.raw_module_name(str(tmp_path / 'gone.mib')) == ''

    def test_pending_asks_about_the_MODULE(self, tmp_path):
        """The bug, exactly: a compiled IEEE8023-LAG-MIB.py means `trunk.mib` is done."""
        raw = tmp_path / 'raw'
        raw.mkdir()
        (raw / 'trunk.mib').write_text('IEEE8023-LAG-MIB DEFINITIONS ::= BEGIN\nEND\n',
                                       encoding='utf-8')
        compiled = tmp_path / 'compiled'
        compiled.mkdir()
        assert mib_resolver.pending_raw_mibs(str(raw), str(compiled)) == ['trunk']
        done = compiled / 'IEEE8023-LAG-MIB.py'
        done.write_text('# compiled', encoding='utf-8')
        os.utime(done, (2 ** 31, 2 ** 31))
        assert mib_resolver.pending_raw_mibs(str(raw), str(compiled)) == []

    def test_a_py_named_after_the_FILE_settles_nothing(self, tmp_path):
        """`trunk.py` is not what this MIB compiles to, and treating it as proof would be the
        same mistake standing on its head."""
        raw = tmp_path / 'raw'
        raw.mkdir()
        (raw / 'trunk.mib').write_text('IEEE8023-LAG-MIB DEFINITIONS ::= BEGIN\nEND\n',
                                       encoding='utf-8')
        compiled = tmp_path / 'compiled'
        compiled.mkdir()
        wrong = compiled / 'trunk.py'
        wrong.write_text('# compiled', encoding='utf-8')
        os.utime(wrong, (2 ** 31, 2 ** 31))
        assert mib_resolver.pending_raw_mibs(str(raw), str(compiled)) == ['trunk']

    def test_it_still_answers_the_name_the_COMPILER_needs(self, tmp_path):
        """pysmi locates a source by file name. Handed the module name, it would look for a
        file called IEEE8023-LAG-MIB, find none, and go to the internet for it."""
        raw = tmp_path / 'raw'
        raw.mkdir()
        (raw / 'trunk.mib').write_text('IEEE8023-LAG-MIB DEFINITIONS ::= BEGIN\nEND\n',
                                       encoding='utf-8')
        assert mib_resolver.pending_raw_mibs(str(raw), '') == ['trunk']

    def test_the_answer_is_remembered_until_the_file_changes(self, tmp_path):
        """Every file in the library is asked on every refresh, and the answer only changes
        when the file does."""
        p = tmp_path / 'x.mib'
        p.write_text('A-MIB DEFINITIONS ::= BEGIN\nEND\n', encoding='utf-8')
        assert mib_resolver.raw_module_name(str(p)) == 'A-MIB'
        assert str(p) in mib_resolver._MODULE_NAME_CACHE
        p.write_text('BB-MIB DEFINITIONS ::= BEGIN\nEND\n', encoding='utf-8')
        assert mib_resolver.raw_module_name(str(p)) == 'BB-MIB', \
            'a cache keyed on nothing that changes is a cache that lies'


class TestACompiledModuleCanOutliveItsSource:
    """Deleting one copy of a module that arrived twice leaves the other one behind — and a
    compiled module built from the copy that went.

    No timestamp can say so: deleting a file makes nothing newer, so the clock keeps calling
    the module up to date while what is loaded came from a file nobody can open any more.
    What does say so is pysmi's own header, which records the source path of everything it
    writes.
    """

    def _pair(self, tmp_path, source_rel):
        raw = tmp_path / 'raw'
        (raw / 'net-snmp').mkdir(parents=True)
        (raw / 'custom').mkdir(parents=True)
        (raw / 'net-snmp' / 'X-MIB.txt').write_text('X-MIB DEFINITIONS ::= BEGIN\nEND\n',
                                                    encoding='utf-8')
        (raw / 'custom' / 'rfc2575.mib').write_text('X-MIB DEFINITIONS ::= BEGIN\nEND\n',
                                                    encoding='utf-8')
        compiled = tmp_path / 'compiled'
        compiled.mkdir()
        py = compiled / 'X-MIB.py'
        py.write_text(f'# ASN.1 source file://{raw / source_rel}\n', encoding='utf-8')
        os.utime(py, (2 ** 31, 2 ** 31))        # newer than both sources
        return raw, compiled

    def test_the_header_says_where_it_came_from(self, tmp_path):
        raw, compiled = self._pair(tmp_path, 'net-snmp/X-MIB.txt')
        assert mib_resolver.compiled_source(str(compiled), 'X-MIB') == 'net-snmp/X-MIB.txt'

    def test_while_that_file_is_there_nothing_is_pending(self, tmp_path):
        raw, compiled = self._pair(tmp_path, 'net-snmp/X-MIB.txt')
        assert mib_resolver.pending_raw_mibs(str(raw), str(compiled)) == []

    def test_once_it_is_gone_the_module_is_pending_again(self, tmp_path):
        """The `.py` is left alone by that delete — it is what pysnmp loads and dropping it
        would take the module out of service — so the only thing that can raise a hand is
        this."""
        raw, compiled = self._pair(tmp_path, 'net-snmp/X-MIB.txt')
        os.remove(raw / 'net-snmp' / 'X-MIB.txt')
        assert mib_resolver.pending_raw_mibs(str(raw), str(compiled)) == ['rfc2575']

    def test_a_module_with_no_header_is_not_dragged_in(self, tmp_path):
        """A `.py` that records no source says nothing about its provenance, and treating
        silence as "gone" would recompile the whole library for ever."""
        raw, compiled = self._pair(tmp_path, 'net-snmp/X-MIB.txt')
        py = compiled / 'X-MIB.py'
        py.write_text('# no header here\n', encoding='utf-8')
        os.utime(py, (2 ** 31, 2 ** 31))
        assert mib_resolver.pending_raw_mibs(str(raw), str(compiled)) == []

    def test_the_answer_is_remembered_until_the_py_changes(self, tmp_path):
        raw, compiled = self._pair(tmp_path, 'net-snmp/X-MIB.txt')
        assert mib_resolver.compiled_source(str(compiled), 'X-MIB') == 'net-snmp/X-MIB.txt'
        py = compiled / 'X-MIB.py'
        py.write_text(f'# ASN.1 source file://{raw / "custom" / "rfc2575.mib"}\n\n',
                      encoding='utf-8')
        assert mib_resolver.compiled_source(str(compiled), 'X-MIB') == 'custom/rfc2575.mib'

    def test_nothing_compiled_means_no_provenance(self, tmp_path):
        assert mib_resolver.compiled_source(str(tmp_path), 'NOPE-MIB') == ''


class TestAMibThatIsOnlyMacros:
    """RFC-1212 and RFC-1215 define grammar for other MIBs to use and nothing else. pysmi
    cannot compile them into anything — there is nothing in them to compile — and pysnmp has
    them built in, which is why they were stubbed in the first place.

    Reported from the panel: `Bad grammar near offset 285 at MIB RFC-1212`, on every run,
    with nothing anybody could do about it. A vendor archive had shipped MG-Soft's variant,
    whose entire body is `SMI OBJECT-TYPE` — an SMIC directive pysmi has never heard of — and
    the stub list was filtered by "not present in raw_dir". That rule is right for the
    ordinary built-ins (drop SNMPv2-MIB.txt in and you mean it compiled) and wrong for these
    two, where a local copy cannot mean "compile it" because no copy of them compiles.
    """

    def _tree(self, tmp_path, name='RFC-1212.my', body='SMI OBJECT-TYPE'):
        raw = tmp_path / 'raw'
        raw.mkdir()
        (raw / name).write_text(f'RFC-1212 DEFINITIONS ::= BEGIN\n{body}\nEND\n',
                                encoding='utf-8')
        (raw / 'A-MIB.txt').write_text('A-MIB DEFINITIONS ::= BEGIN\nEND\n', encoding='utf-8')
        return raw

    def test_it_is_never_pending(self, tmp_path):
        """Counted as pending it is a number that never goes down and a compile that runs for
        ever, since nothing it does can produce the module being waited for."""
        raw = self._tree(tmp_path)
        assert mib_resolver.pending_raw_mibs(str(raw), '') == ['A-MIB']

    def test_it_is_never_asked_for(self, tmp_path):
        """A stub covers it as a DEPENDENCY and that is all a stub can do: asked to compile
        one by name, pysmi parses the source before it consults a searcher."""
        pytest.importorskip('pysmi')
        raw = self._tree(tmp_path)
        out = mib_resolver.compile_raw_mibs(str(raw), str(tmp_path / 'compiled'),
                                            mibs_filter=['RFC-1212'])
        assert out['ok'] is True
        assert out.get('results') == {}, 'it was handed to the compiler'

    def test_it_is_recognised_by_its_MODULE_and_not_its_file_name(self, tmp_path):
        """The vendor's copy is called `RFC-1212.my` and lives in a folder called
        `RFC-1212.my_for_MG-Soft`. Neither is the name that identifies it."""
        raw = self._tree(tmp_path, name='macros.txt')
        assert mib_resolver.pending_raw_mibs(str(raw), '') == ['A-MIB']

    def test_the_ordinary_built_ins_are_not_treated_that_way(self, tmp_path):
        """A local SNMPv2-MIB.txt IS meant to be compiled — that rule stays, and this is the
        line between the two."""
        raw = tmp_path / 'raw'
        raw.mkdir()
        (raw / 'SNMPv2-MIB.txt').write_text('SNMPv2-MIB DEFINITIONS ::= BEGIN\nEND\n',
                                            encoding='utf-8')
        assert mib_resolver.pending_raw_mibs(str(raw), '') == ['SNMPv2-MIB']

    def test_the_pair_is_named_once(self, tmp_path):
        """Two lists of the same two names is one of them being updated on its own."""
        assert mib_resolver.MACRO_ONLY_MIBS == ('RFC-1212', 'RFC-1215')


class TestAnImportIsResolvedByTheNameItAsksFor:
    """Reported from the panel: seven MIBs that stay pending, compile without error, and stay
    pending. Two separate faults, both of them the file-name/module-name split again.

    pysmi resolves an ``IMPORTS`` by trying the module name as a FILE name. In a vendor
    archive that finds nothing: `DIFFSERV-DSCP-TC` lives in `diffserv-dscp-tc-rfc3289.mib`,
    `DNS-SERVER-MIB` in `rfc1611.mib`, and every Linksys module in an `ls*.mib`. Each of those
    imports came back "missing" and took the MIB that needed it down with it.
    """

    @pytest.fixture(autouse=True)
    def _offline(self, monkeypatch):
        """No HTTP sources. A MIB that fails to parse is then looked for on the mirrors —
        several of them, several name variants each, a timeout apiece — which is thirty
        seconds per test and a suite that fails differently on a machine with no network.
        What is being measured here is local resolution.
        """
        monkeypatch.setattr(mib_resolver, '_DEFAULT_MIB_SOURCES', ())

    def _archive(self, tmp_path):
        """A vendor archive: files named nothing like the modules they hold."""
        raw = tmp_path / 'raw'
        raw.mkdir()
        (raw / 'vendor-base.mib').write_text(
            'VENDOR-BASE-MIB DEFINITIONS ::= BEGIN\n'
                        'vendorThing OBJECT IDENTIFIER ::= { 1 3 6 1 4 1 99999 }\n'
            'END\n', encoding='utf-8')
        (raw / 'vendor-leaf.mib').write_text(
            'VENDOR-LEAF-MIB DEFINITIONS ::= BEGIN\n'
            'IMPORTS vendorThing FROM VENDOR-BASE-MIB;\n'
            'vendorLeaf OBJECT IDENTIFIER ::= { vendorThing 1 }\n'
            'END\n', encoding='utf-8')
        return raw

    def test_the_index_maps_a_module_to_the_file_that_holds_it(self, tmp_path):
        raw = self._archive(tmp_path)
        idx = mib_resolver.module_index(str(raw))
        assert os.path.basename(idx['VENDOR-BASE-MIB']) == 'vendor-base.mib'
        assert os.path.basename(idx['VENDOR-LEAF-MIB']) == 'vendor-leaf.mib'

    def test_a_module_nobody_declares_is_not_in_it(self, tmp_path):
        raw = self._archive(tmp_path)
        assert 'NOPE-MIB' not in mib_resolver.module_index(str(raw))

    def test_the_reader_answers_by_declared_name(self, tmp_path):
        """As a pysmi source, so the compiler treats it like any other: asked for a name it
        does not know it steps aside and the directory readers answer."""
        pytest.importorskip('pysmi')
        raw = self._archive(tmp_path)
        reader = mib_resolver._module_reader(str(raw))
        info, data = reader.get_data('VENDOR-BASE-MIB')
        assert info.name == 'VENDOR-BASE-MIB'
        assert 'vendorThing' in data
        from pysmi import error as pysmi_error
        with pytest.raises(pysmi_error.PySmiReaderFileNotFoundError):
            reader.get_data('NOT-HERE-MIB')

    def test_the_dependency_is_found_when_the_file_is_named_otherwise(self, tmp_path):
        """The whole point: `VENDOR-LEAF-MIB` imports `VENDOR-BASE-MIB`, and no file is
        called that."""
        pytest.importorskip('pysmi')
        raw = self._archive(tmp_path)
        out = mib_resolver.compile_raw_mibs(str(raw), str(tmp_path / 'compiled'),
                                            mibs_filter=['vendor-leaf'])
        res = out.get('results', {})
        assert res.get('VENDOR-BASE-MIB') == 'compiled', \
            'the import was not resolved to the file that holds it'
        assert res.get('VENDOR-LEAF-MIB') == 'compiled'


class TestAFailureHasToBeVisible:
    """The other half of the same report: they compiled "without error" and stayed pending.

    pysmi answers with EITHER name depending on how it went — a module it compiled comes back
    under the MODULE's name, one it could not parse under the name it was HANDED, because it
    never got far enough to read the module out of the file. The verdict was looked up under
    the file name only, so for every MIB whose file is not named after its module the failure
    was invisible: no error, no compiled module, pending for ever.
    """

    @pytest.fixture(autouse=True)
    def _offline(self, monkeypatch):
        """No HTTP sources. A MIB that fails to parse is then looked for on the mirrors —
        several of them, several name variants each, a timeout apiece — which is thirty
        seconds per test and a suite that fails differently on a machine with no network.
        What is being measured here is local resolution.
        """
        monkeypatch.setattr(mib_resolver, '_DEFAULT_MIB_SOURCES', ())

    def _broken(self, tmp_path):
        raw = tmp_path / 'raw'
        raw.mkdir()
        (raw / 'notthename.mib').write_text(
            'ROTO-MIB DEFINITIONS ::= BEGIN\nthis is not SMI }{\nEND\n', encoding='utf-8')
        return raw

    def test_a_failure_is_reported_under_the_module_name(self, tmp_path):
        """Which is what the panel keys its rows and its stored reasons by."""
        pytest.importorskip('pysmi')
        raw = self._broken(tmp_path)
        out = mib_resolver.compile_raw_mibs(str(raw), str(tmp_path / 'compiled'),
                                            mibs_filter=['notthename'])
        assert out['ok'] is False
        assert out['failed'] == ['ROTO-MIB']

    def test_the_reason_comes_with_it(self, tmp_path):
        """A red row with no reason is a row nobody can act on — and the reason is filed under
        the same name, or it is lost on the way."""
        pytest.importorskip('pysmi')
        raw = self._broken(tmp_path)
        out = mib_resolver.compile_raw_mibs(str(raw), str(tmp_path / 'compiled'),
                                            mibs_filter=['notthename'])
        assert 'ROTO-MIB' in (out.get('errors') or {})
        assert out['errors']['ROTO-MIB']

    def test_the_job_says_what_it_reached(self, tmp_path):
        """`attempted` is what clears the stored reasons: a job speaks for the MIBs it
        covered. Listed by file name against a result keyed by module, it was always empty —
        so nothing was ever cleared and a MIB that had since compiled kept its old red row."""
        pytest.importorskip('pysmi')
        raw = self._broken(tmp_path)
        out = mib_resolver.compile_raw_mibs(str(raw), str(tmp_path / 'compiled'),
                                            mibs_filter=['notthename'])
        assert out.get('attempted') == ['ROTO-MIB']


class TestNothingScansItFlatAnyMore:

    def test_no_module_lists_the_raw_directory_directly(self):
        """Three separate places had to be found by hand after the first was fixed, and each
        one failed the same silent way. The shared walker is the only way in."""
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ('mib_admin.py', 'mib_resolver.py'):
            with open(os.path.join(here, name), encoding='utf-8') as fh:
                src = fh.read()
            # `iter_raw_mibs` itself walks; everything else has to go through it.
            body = src.split('def iter_raw_mibs')[0] + \
                src.split('def iter_raw_mibs')[-1].split('def raw_mib_dirs')[-1]
            assert 'os.listdir(raw_dir)' not in body, f'{name} still scans the raw dir flat'


class TestADeadMirrorCannotCostTheCompilation:
    """A timeout alone does not save a compile. pysmi asks each source for several NAME
    VARIANTS of every missing module and swallows the error between tries, so one unreachable
    host is paid for once per variant, per module — twenty MIBs behind a dead mirror is hours,
    and on screen it is a progress bar frozen at 0 with nothing to say why. That is what
    happened when the mirror that used to be the only default stopped answering.
    """

    def _reader(self, monkeypatch, outcomes):
        """An HttpReader whose session answers from a script instead of the network."""
        calls = []

        class _Session:
            def request(self, method, url, **kw):
                calls.append(kw.get('timeout'))
                out = outcomes.pop(0) if outcomes else 'ok'
                if out == 'boom':
                    raise OSError('unreachable')
                return out

        class _Reader:
            def __init__(self, url):
                self.session = _Session()

        monkeypatch.setattr('pysmi.reader.HttpReader', _Reader)
        return mib_resolver._http_reader_with_timeout('https://x.invalid/@mib@', 3), calls

    def test_every_request_carries_the_timeout(self, monkeypatch):
        """pysmi asks with none of its own, which is how a mirror blocks a compile forever."""
        reader, calls = self._reader(monkeypatch, ['ok'])
        reader.session.request('GET', 'https://x.invalid/A')
        assert calls == [3]

    def test_a_host_that_will_not_talk_is_written_off(self, monkeypatch):
        reader, calls = self._reader(monkeypatch, ['boom'] * 10)
        for _ in range(mib_resolver._HTTP_DEAD_AFTER):
            with pytest.raises(OSError):
                reader.session.request('GET', 'https://x.invalid/A')
        before = len(calls)
        with pytest.raises(OSError):
            reader.session.request('GET', 'https://x.invalid/B')
        assert len(calls) == before, 'it went to the network again after giving up'

    def test_an_answer_resets_it(self, monkeypatch):
        """A 404 is an answer: the mirror simply does not host that MIB, and the next module
        might be there. Only a host that will not talk counts against it."""
        reader, calls = self._reader(monkeypatch, ['boom', 'ok', 'boom', 'ok'])
        with pytest.raises(OSError):
            reader.session.request('GET', 'https://x.invalid/A')
        reader.session.request('GET', 'https://x.invalid/B')
        with pytest.raises(OSError):
            reader.session.request('GET', 'https://x.invalid/C')
        reader.session.request('GET', 'https://x.invalid/D')
        assert len(calls) == 4


class TestAModuleCanBeCompiledTwice:
    """pysmi writes a compiled module to a temporary file and then ``os.rename``s it into
    place. On POSIX that overwrites. **On Windows it raises** when the destination exists —
    ``WinError 183``, "cannot create a file when that file already exists" — so pysmi could
    never rebuild a module it had already written.

    Which is to say: on Windows, an edited MIB stayed outdated for ever, and "rebuild
    everything" could not rebuild anything at all. It surfaced as a compile error naming a
    temporary file, on a MIB whose source was perfectly fine.
    """

    def test_rename_replaces_an_existing_module_inside_the_context(self, tmp_path):
        pyfile = pytest.importorskip('pysmi.writer.pyfile')
        src = tmp_path / 'tmp1'
        dst = tmp_path / 'DEST-MIB.py'
        src.write_text('new', encoding='utf-8')
        dst.write_text('old', encoding='utf-8')
        with mib_resolver._pysmi_overwrites():
            pyfile.os.rename(str(src), str(dst))
        assert dst.read_text(encoding='utf-8') == 'new'

    def test_the_real_os_is_put_back(self, tmp_path):
        """It is a proxy on the writer's module and not a patch of `os.rename` itself, which
        the whole process shares — and it is installed only for the length of a compilation."""
        pyfile = pytest.importorskip('pysmi.writer.pyfile')
        before = pyfile.os
        with mib_resolver._pysmi_overwrites():
            assert pyfile.os is not before
        assert pyfile.os is before

    def test_it_is_put_back_even_when_the_compile_blows_up(self, tmp_path):
        pyfile = pytest.importorskip('pysmi.writer.pyfile')
        before = pyfile.os
        with pytest.raises(RuntimeError):
            with mib_resolver._pysmi_overwrites():
                raise RuntimeError('boom')
        assert pyfile.os is before

    def test_everything_else_still_reaches_the_real_os(self, tmp_path):
        """The writer uses more of `os` than rename; a proxy that answered only that one
        would break the module it is there to help."""
        pyfile = pytest.importorskip('pysmi.writer.pyfile')
        with mib_resolver._pysmi_overwrites():
            assert pyfile.os.path.isdir(str(tmp_path)) is True
            assert callable(pyfile.os.makedirs)

    def test_the_compiler_actually_uses_it(self):
        """A context manager nothing enters is a fix that is not applied."""
        import inspect
        src = inspect.getsource(mib_resolver.compile_raw_mibs_progressive)
        assert 'with _pysmi_overwrites():' in src


class TestWhereTheStandardModulesComeFrom:

    def test_a_live_source_is_tried_first(self):
        """Every vendor MIB imports SNMPv2-SMI/-TC/-CONF, so whichever source answers for
        those decides whether anything compiles at all on an installation with no local copy."""
        assert mib_resolver._DEFAULT_MIB_SOURCES
        assert 'net-snmp' in mib_resolver._DEFAULT_MIB_SOURCES[0]

    def test_every_default_carries_the_placeholder(self):
        for tpl in mib_resolver._DEFAULT_MIB_SOURCES:
            assert '@mib@' in tpl

    def test_more_than_one_is_offered(self):
        """A single default is a single point of failure, and it failed."""
        assert len(mib_resolver._DEFAULT_MIB_SOURCES) > 1
