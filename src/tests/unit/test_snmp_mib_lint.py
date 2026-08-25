#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Saying why a MIB will not compile, before the compiler says it badly.

Two vendor MIBs broke here within a day, and both broke the same two ways. What the compiler
says about them points one step away from the cause: ``Bad grammar near offset 558`` names
where it gave up, and ``Unknown parents for symbols: netSnmpPassCounter64`` names the symbols
it could not *place* rather than the import that is missing.

The bar for a linter is not "does it find things" — it is **silence on everything that is
fine**. A first draft of this flagged 74 of 98 real MIBs and was worth less than nothing: a
finding only means "go and look at that line" while findings are rare. Both classes of noise
it produced are pinned below, because both were invisible until it was run over real files.
"""

from lib.core.snmp.mibs.lint import (_blank, declared_names, last_updated,
                                    lint_mib, module_name)


def _codes(text):
    return {f['code'] for f in lint_mib(text)}


def _symbols(text, code):
    return {f['symbol'] for f in lint_mib(text) if f['code'] == code}


# A perfectly ordinary MIB, written the way net-snmp writes them: indented.
CLEAN = '''EXAMPLE-MIB DEFINITIONS ::= BEGIN

IMPORTS
    OBJECT-TYPE, Integer32, Counter64, enterprises, MODULE-IDENTITY
        FROM SNMPv2-SMI
    DisplayString
        FROM SNMPv2-TC;

    exampleMib MODULE-IDENTITY
        LAST-UPDATED "202302080000Z"
        ORGANIZATION "example"
        CONTACT-INFO "x"
        DESCRIPTION  "x"
        ::= { enterprises 99 }

    exTable OBJECT-TYPE
        SYNTAX     SEQUENCE OF ExEntry
        MAX-ACCESS not-accessible
        STATUS     current
        DESCRIPTION "t"
        ::= { exampleMib 1 }

    exEntry OBJECT-TYPE
        SYNTAX     ExEntry
        MAX-ACCESS not-accessible
        STATUS     current
        DESCRIPTION "e"
        INDEX      { exIndex }
        ::= { exTable 1 }

    ExEntry ::=
        SEQUENCE {
            exIndex   Integer32,
            exName    DisplayString,
            exCount   Counter64
        }

    exIndex OBJECT-TYPE
        SYNTAX      Integer32
        MAX-ACCESS  not-accessible
        STATUS      current
        DESCRIPTION "i"
        ::= { exEntry 1 }

END
'''


class TestWhatAMibDeclares:
    """The descriptors are what a MIB *is*, in the only terms that survive being copied,
    renamed or re-indented — and the only way to tell two copies of one module from two
    modules that merely share a first line."""

    def test_it_names_what_the_file_defines(self):
        text = ('X-MIB DEFINITIONS ::= BEGIN\n'
                'xThing OBJECT-TYPE\n  SYNTAX INTEGER\n'
                'xOther OBJECT-IDENTITY\n'
                'END\n')
        assert declared_names(text) == {'xThing', 'xOther'}

    def test_a_name_inside_a_comment_is_not_a_definition(self):
        text = 'X-MIB DEFINITIONS ::= BEGIN\n-- xGhost OBJECT-TYPE\nEND\n'
        assert declared_names(text) == set()

    def test_a_file_that_defines_nothing_declares_nothing(self):
        assert declared_names('X-MIB DEFINITIONS ::= BEGIN\nEND\n') == set()
        assert declared_names('') == set()


class TestTheDateAMibDeclares:
    """`LAST-UPDATED` is what decides which of two copies of the same module stays, and it was
    only visible twenty lines into a diff. Reading a diff to find out which of two files is
    the older one is the long way round."""

    def _mib(self, body):
        return 'X-MIB DEFINITIONS ::= BEGIN\n' + body + '\nEND\n'

    def test_it_reads_the_four_digit_form(self):
        assert last_updated(self._mib('  LAST-UPDATED "200210160000Z"')) == '2002-10-16'

    def test_it_reads_the_two_digit_one_too(self):
        """SMIv1 writes the year in two digits, and a real vendor archive holds both forms —
        eighteen files of one and a hundred and seventy-nine of the other, in the library this
        came from."""
        assert last_updated(self._mib('  LAST-UPDATED "9901200000Z"')) == '1999-01-20'

    def test_a_two_digit_year_lands_in_the_right_century(self):
        """A `99` read as 2099 would sort as the newest file in the library — and the whole
        point of showing the date is deciding which copy is newer."""
        assert last_updated(self._mib('  LAST-UPDATED "0501010000Z"')) == '2005-01-01'
        assert last_updated(self._mib('  LAST-UPDATED "7001010000Z"')) == '1970-01-01'

    def test_the_module_identity_wins_over_the_revisions(self):
        """The REVISION clauses under it are the history; the first date is the module's own,
        and it repeats the newest of them."""
        text = self._mib('  LAST-UPDATED "200210160000Z"\n  REVISION "9901200000Z"')
        assert last_updated(text) == '2002-10-16'

    def test_a_commented_out_date_is_not_a_date(self):
        assert last_updated(self._mib('-- LAST-UPDATED "200210160000Z"')) == ''

    def test_a_mib_that_does_not_say_says_nothing(self):
        """A quarter of a real library: SNMPv2-TC carries textual conventions and no
        MODULE-IDENTITY at all. Guessing one would be worse than the blank."""
        assert last_updated(self._mib('  x OBJECT-TYPE')) == ''
        assert last_updated('') == ''


class TestItIsQuietAboutWhatIsFine:
    """Every one of these was a finding in the first draft, on real files that compile."""

    def test_a_clean_mib_says_nothing(self):
        assert lint_mib(CLEAN) == []

    def test_indented_definitions_are_still_definitions(self):
        """Half of net-snmp's MIBs indent every definition four spaces. Anchored at column
        zero this saw none of them — so their row types looked undefined, their tables looked
        like they pointed at nothing, and 74 of 98 files were 'wrong'."""
        assert _codes(CLEAN) == set()
        assert 'ExEntry' not in _symbols(CLEAN, 'missing-import')

    def test_the_brace_may_be_on_the_next_line(self):
        """`ExEntry ::=` then `SEQUENCE {` underneath is the common layout, and requiring them
        together made every such table a false positive."""
        assert 'sequence-of-unknown' not in _codes(CLEAN)

    def test_imports_is_not_an_object_called_imports(self):
        """`IMPORTS` followed on the next line by `OBJECT-TYPE,` matched 'a value definition
        whose name starts with a capital' in 74 files."""
        assert 'IMPORTS' not in _symbols(CLEAN, 'uppercase-descriptor')

    def test_end_is_not_one_either(self):
        text = CLEAN.replace('END\n', 'END\n\n-- a trailing note\n')
        assert 'END' not in _symbols(text, 'uppercase-descriptor')

    def test_a_type_defined_here_is_not_missing(self):
        assert lint_mib(CLEAN.replace('    DisplayString\n        FROM SNMPv2-TC;',
                                      '    ;\n\n    DisplayString ::= OCTET STRING')) == []

    def test_something_that_is_not_a_mib_gets_no_opinion(self):
        assert lint_mib('') == []
        assert lint_mib('MIBS = FOO BAR\n\nall:\n\tmake install\n') == []

    def test_a_name_inside_a_comment_or_a_description_is_not_code(self):
        """A DESCRIPTION quoting `SYNTAX Whatever` is prose, and a linter reading prose is a
        linter nobody believes twice."""
        text = CLEAN.replace('DESCRIPTION "t"',
                             'DESCRIPTION "see SYNTAX NotAThing for details"')
        assert 'NotAThing' not in _symbols(text, 'missing-import')


class TestTheTwoWaysVendorMibsActuallyBreak:

    def test_a_type_used_and_never_imported(self):
        """NET-SNMP-PASS-MIB, exactly: two objects with `SYNTAX Counter64` and
        `SYNTAX Opaque`, and an IMPORTS that lists neither."""
        text = CLEAN.replace('Counter64, ', '').replace('        exCount   Counter64\n', '')
        text = text.replace('SYNTAX      Integer32', 'SYNTAX      Counter64', 1)
        assert _symbols(text, 'missing-import') == {'Counter64'}

    def test_the_finding_carries_the_line(self):
        """A finding without the right line is a finding somebody has to go and find."""
        text = CLEAN.replace('Counter64, ', '')
        found = [f for f in lint_mib(text) if f['code'] == 'missing-import']
        assert found
        line = found[0]['line']
        assert 'Counter64' in text.splitlines()[line - 1]

    def test_a_descriptor_that_starts_with_a_capital(self):
        """Synology's SMB MIB, exactly: every object named with an initial capital, which in
        SMI is a TYPE reference — so the parser stops at the first one."""
        text = CLEAN.replace('    exIndex OBJECT-TYPE', '    ExIndex OBJECT-TYPE')
        assert _symbols(text, 'uppercase-descriptor') == {'ExIndex'}

    def test_it_suggests_the_name_it_should_have(self):
        text = CLEAN.replace('    exIndex OBJECT-TYPE', '    ExIndex OBJECT-TYPE')
        msg = [f for f in lint_mib(text) if f['code'] == 'uppercase-descriptor'][0]['message']
        assert 'exIndex' in msg

    def test_a_table_whose_syntax_names_an_object(self):
        """The other half of the Synology defect: the SEQUENCE type was called `SMBCpuInfo`
        and the table said `SEQUENCE OF SMBCpuEntry`, which is the row OBJECT."""
        text = CLEAN.replace('    ExEntry ::=', '    ExInfo ::=')
        text = text.replace('SYNTAX     ExEntry\n', 'SYNTAX     ExInfo\n')
        assert 'sequence-of-value' in _codes(text) or 'sequence-of-unknown' in _codes(text)

    def test_findings_come_in_file_order(self):
        """They are read against the file, top to bottom."""
        text = CLEAN.replace('Counter64, ', '')
        text = text.replace('    exIndex OBJECT-TYPE', '    ExIndex OBJECT-TYPE')
        lines = [f['line'] for f in lint_mib(text)]
        assert lines == sorted(lines)


class TestReadingAMibIsLexingIt:
    """Comments and strings were found by two regexes taking turns, and the turns were the
    bug. Both shapes below are in LibreNMS, and both were being read wrong."""

    def test_a_quote_inside_a_comment_does_not_open_a_string(self):
        """DELL-NETWORKING-DCB-MIB has `--     configuration information. "` in its header.
        Blanking strings FIRST made that quote open one, which ran to the next quote hundreds
        of lines later and took the module declaration with it — so a real MIB came back
        nameless, and the importer refused it as "not a MIB"."""
        text = ('-- some prose. "\n'
                '-- and more\n'
                'DELL-NETWORKING-DCB-MIB DEFINITIONS ::= BEGIN\n'
                'END\n')
        assert module_name(text) == 'DELL-NETWORKING-DCB-MIB'

    def test_a_double_dash_inside_a_string_does_not_open_a_comment(self):
        """The mistake the other order would make instead. A DESCRIPTION is prose, and prose
        has dashes in it — whichever token opens FIRST wins, which is what a lexer does."""
        text = ('X-MIB DEFINITIONS ::= BEGIN\n'
                'x OBJECT-TYPE\n'
                '    DESCRIPTION "ranges 1--10 apply"\n'
                '    ::= { y 1 }\n'
                'END\n')
        masked = _blank(text)
        assert '::= { y 1 }' in masked, 'the rest of the file was eaten as a comment'

    def test_the_date_survives_a_comment_that_opens_a_quote(self):
        """`last_updated` keeps strings (the date lives in one) and blanks comments, and it
        reads them with the same scanner — the stray quote used to hide the date too."""
        text = ('-- header. "\n'
                'X-MIB DEFINITIONS ::= BEGIN\n'
                '    LAST-UPDATED "201204160000Z"\n'
                'END\n')
        assert last_updated(text) == '2012-04-16'

    def test_masking_never_moves_a_line(self):
        """Every finding is reported at a line number. Blanking that changed the length of
        the file would report every one of them somewhere else."""
        text = 'A\n-- c "\nB "s -- t"\nC\n'
        assert len(_blank(text)) == len(text)
        assert _blank(text).count('\n') == text.count('\n')


class TestAnOidHungOffNothing:
    """`host OBJECT IDENTIFIER ::= { mib-2 25 }` with no `mib-2` in the IMPORTS. pysmi answers
    "Unknown parent symbol: mib_2" — under a name it mangled, about a module it names by the
    FILE, and with nothing pointing at the import that is missing. Somebody then reads a MIB
    of forty thousand lines looking for a symbol that is not in it, because what is missing
    is the line that would have brought it IN.

    Values are checked here and nowhere else in this linter, and the difference is what the
    mistake costs: an unknown TYPE is resolved late and reported clearly by pysmi, while an
    unknown PARENT stops the module dead — there is no tree left to hang anything on.

    Not archaeology either: this is the HOST-RESOURCES-MIB that ships with Windows 10 Pro
    22H2."""

    BROKEN = """HOST-RESOURCES-MIB DEFINITIONS ::= BEGIN

IMPORTS
    DisplayString             FROM RFC1213-MIB
    TimeTicks,
    OBJECT-TYPE,
    Counter, Gauge            FROM RFC1155-SMI;

host     OBJECT IDENTIFIER ::= { mib-2 25 }
hrSystem OBJECT IDENTIFIER ::= { host 1 }

END
"""

    def _codes(self, text, name='X-MIB.mib'):
        return [(f['code'], f['symbol']) for f in lint_mib(text, name)]

    def test_the_parent_nobody_brought_in(self):
        assert ('unknown-oid-parent', 'mib-2') in self._codes(
            self.BROKEN, 'HOST-RESOURCES-MIB.mib')

    def test_and_it_says_what_to_do_about_it(self):
        f = [x for x in lint_mib(self.BROKEN, 'HOST-RESOURCES-MIB.mib')
             if x['code'] == 'unknown-oid-parent'][0]
        assert f['line'] == 9
        assert 'IMPORTS' in f['message']

    def test_importing_it_settles_it(self):
        fixed = self.BROKEN.replace('    DisplayString  ', '    DisplayString, mib-2  ')
        assert not [c for c in self._codes(fixed, 'HOST-RESOURCES-MIB.mib')
                    if c[0] == 'unknown-oid-parent']

    def test_a_parent_this_file_defines_further_down(self):
        """Read top to bottom, `padre` is unknown on the line that uses it. The whole file is
        one scope, and a MIB that defines things after using them is ordinary."""
        text = """X-MIB DEFINITIONS ::= BEGIN
IMPORTS enterprises FROM RFC1155-SMI;
hijo  OBJECT IDENTIFIER ::= { padre 1 }
padre OBJECT IDENTIFIER ::= { enterprises 99 }
END
"""
        assert not self._codes(text)

    def test_a_definition_written_across_two_lines_is_still_a_definition(self):
        """A great many MIBs put the name on a line of its own:

            radiusAccServMIBConformance
                          OBJECT IDENTIFIER ::= { radiusAccServMIB 2 }

        Read as one line only, every definition written that way is invisible and everything
        hanging off it is reported as an orphan. Twenty-four of those in one real library."""
        text = """X-MIB DEFINITIONS ::= BEGIN
IMPORTS enterprises FROM RFC1155-SMI;
padre
        OBJECT IDENTIFIER ::= { enterprises 99 }
hijo    OBJECT IDENTIFIER ::= { padre 1 }
END
"""
        assert not self._codes(text)

    def test_the_roots_of_the_tree_are_nobody_s_to_import(self):
        text = """X-MIB DEFINITIONS ::= BEGIN
org OBJECT IDENTIFIER ::= { iso 3 }
END
"""
        assert not self._codes(text)

    def test_an_oid_written_out_in_numbers_names_nothing(self):
        text = """X-MIB DEFINITIONS ::= BEGIN
raro OBJECT IDENTIFIER ::= { 1 3 6 1 4 1 311 }
END
"""
        assert not self._codes(text)

    def test_an_enumeration_is_not_an_assignment(self):
        """`Estado ::= INTEGER { arriba(1) }` has braces and a name in front of them, and
        neither of those is an object hanging off a parent."""
        text = """X-MIB DEFINITIONS ::= BEGIN
Estado ::= INTEGER { arriba(1), abajo(2) }
END
"""
        assert not self._codes(text)

    def test_an_object_type_hung_off_a_missing_parent_counts_too(self):
        """It is the same failure: the parent is what places the object, whether the thing
        being placed is a subtree or a single object."""
        text = """X-MIB DEFINITIONS ::= BEGIN
IMPORTS OBJECT-TYPE FROM RFC1155-SMI;
cosa OBJECT-TYPE
    SYNTAX  INTEGER
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "x"
    ::= { noSeSabe 1 }
END
"""
        assert ('unknown-oid-parent', 'noSeSabe') in self._codes(text)
