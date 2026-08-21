#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: reading a MIB the way the compiler will.
#
"""Why this MIB will not compile, said before the compiler says it.

Two vendor MIBs broke in this panel within a day of each other, and both broke the same two
ways — ways a person can fix in a minute and a compiler describes in a sentence about an
offset:

* **A type is used and never imported.** ``NET-SNMP-PASS-MIB`` declares two objects with
  ``SYNTAX Counter64`` and ``SYNTAX Opaque`` and imports neither; Synology's SMB MIB uses
  ``DisplayString`` and imports neither. pysmi answers
  ``Unknown parents for symbols: netSnmpPassCounter64, netSnmpPassInteger64`` — the symbols it
  names are the ones it could not *place*, not the ones that are missing, so the message points
  one step away from the problem.
* **A descriptor starts with a capital letter.** In SMI the case of the first letter *is* the
  meaning: uppercase names a TYPE, lowercase a VALUE. Synology wrote every object in the file
  uppercase, so the parser stopped at the first one — ``Bad grammar near offset 558``, which
  says where it gave up and nothing about why.

So this reads the file the same way and says the thing itself, with the line. It is a linter
and not a parser: it must survive a file that does not parse, because that is the only kind it
is ever pointed at. It answers with what it is sure of and stays quiet otherwise — a linter
that cries wolf is worse than no linter, since the whole value here is that a finding means
*go and look at that line*.
"""

from __future__ import annotations

import re

# ── What the language brings, so it is never "missing" ───────────────────────
# The base ASN.1/SMI types and keywords a MIB may use without importing anything.
_BUILTIN_TYPES = frozenset({
    'INTEGER', 'OCTET', 'STRING', 'OBJECT', 'IDENTIFIER', 'NULL', 'BITS', 'SEQUENCE',
    'CHOICE', 'BOOLEAN', 'REAL', 'ANY', 'IA5String', 'NumericString', 'PrintableString',
    'UTF8String', 'VisibleString', 'TeletexString', 'UniversalString', 'BMPString',
    'GeneralizedTime', 'UTCTime', 'ObjectDescriptor',
})

_DEF_MACROS = (
    'OBJECT-TYPE', 'MODULE-IDENTITY', 'OBJECT-IDENTITY', 'NOTIFICATION-TYPE',
    'OBJECT-GROUP', 'NOTIFICATION-GROUP', 'MODULE-COMPLIANCE', 'TRAP-TYPE',
    'AGENT-CAPABILITIES',
)

# The words a definition can never be called. `IMPORTS` followed on the next line by
# `OBJECT-TYPE,` is not an object called IMPORTS, and half this file's first draft thought it
# was — in seventy-four of ninety-eight real MIBs.
_ASN1_KEYWORDS = frozenset({
    'IMPORTS', 'EXPORTS', 'BEGIN', 'END', 'DEFINITIONS', 'FROM', 'MACRO', 'SEQUENCE',
    'CHOICE', 'OBJECT', 'INTEGER', 'OCTET', 'NULL', 'BITS',
})

# `name MACRO` — a VALUE definition, which is what has to start lowercase.
#
# Leading whitespace is allowed because MIBs indent: half of net-snmp's write every definition
# four spaces in, and anchored at column zero this saw none of them — so their row types looked
# undefined and their tables looked like they pointed at nothing. The macro has to be on the
# SAME line, which is what tells a definition from a keyword that happens to precede one.
_VALUE_DEF_RE = re.compile(
    r'^[ \t]*([A-Za-z][A-Za-z0-9_-]*)[ \t]+(?:' + '|'.join(_DEF_MACROS) + r')\b',
    re.MULTILINE)
# `name OBJECT IDENTIFIER ::=` — also a value.
_OID_DEF_RE = re.compile(
    r'^[ \t]*([A-Za-z][A-Za-z0-9_-]*)[ \t]+OBJECT[ \t]+IDENTIFIER\s*::=', re.MULTILINE)
# `Name ::= …` — a TYPE definition (textual convention, SEQUENCE, subtype).
_TYPE_DEF_RE = re.compile(r'^[ \t]*([A-Za-z][A-Za-z0-9_-]*)\s*::=', re.MULTILINE)
# `Name ::= SEQUENCE {` — the row type a table's SEQUENCE OF must name. The brace lands on the
# next line as often as not.
_SEQ_TYPE_RE = re.compile(
    r'^[ \t]*([A-Za-z][A-Za-z0-9_-]*)\s*::=\s*SEQUENCE\s*\{', re.MULTILINE)

_IMPORTS_RE = re.compile(r'\bIMPORTS\b(.*?);', re.DOTALL)
_SYNTAX_RE = re.compile(r'\bSYNTAX\s+([A-Za-z][A-Za-z0-9_-]*)')
_SEQUENCE_OF_RE = re.compile(r'\bSEQUENCE\s+OF\s+([A-Za-z][A-Za-z0-9_-]*)')
# The body of a row type: `Name ::= SEQUENCE { field Type, field Type }`. A type can go
# missing here and nowhere else — a column whose type is never imported is not named by any
# SYNTAX clause in the file.
_SEQ_BODY_RE = re.compile(
    r'^[ \t]*[A-Za-z][A-Za-z0-9_-]*\s*::=\s*SEQUENCE\s*\{(.*?)\}', re.MULTILINE | re.DOTALL)
_SEQ_FIELD_RE = re.compile(r'([A-Za-z][A-Za-z0-9_-]*)\s+([A-Za-z][A-Za-z0-9_-]*)')

# Comments and strings are found by SCANNING, not by two regexes taking turns. The turns
# were the bug: strings were blanked first, so a stray `"` inside a comment —
#
#     --     configuration information. "
#
# opened a string that ran to the next quote hundreds of lines later, and everything in
# between disappeared, module declaration included. Two real MIBs in LibreNMS are written
# that way (DELL-NETWORKING-DCB-MIB, DSR4410MD-MIB) and both were refused as "not a MIB".
#
# Doing it the other way round only swaps which mistake is made: a `--` inside a DESCRIPTION
# would then start a comment. Whichever opens FIRST wins, which is what a lexer does and what
# this is.


_MODULE_NAME_RE = re.compile(
    r'^\s*([A-Za-z][A-Za-z0-9_-]*)\s+DEFINITIONS\s*(?:IMPLICIT\s+TAGS\s*)?::=\s*BEGIN',
    re.MULTILINE)


def module_name(text: str) -> str:
    """The module this text declares itself to be, or ``''``.

    The identity of a MIB, and the only stable one: pysmi compiles by module name, writes
    ``<NAME>.py``, and resolves every ``IMPORTS`` by name against the directories it is given.
    A file can be renamed or moved between vendor folders; what it calls itself cannot change
    without it becoming a different module.
    """
    return _in_header(text, lambda t: _first(_MODULE_NAME_RE, _blank(t)))


# How much of a file to look at before looking at more. A MIB says what it is in its first
# lines; a legal preamble can be long, and ADIC's runs to a hundred and sixteen. Reading the
# whole 200 KB to answer a question the first 16 KB answers is what made opening the section
# take a minute — over five thousand files, the difference is the wait.
_HEADER_WINDOWS = (16000, 64000, 200000)


def _in_header(text: str, answer):
    """Ask *answer* about the head of *text*, widening only while it says nothing."""
    src = text or ''
    prev = 0
    for size in _HEADER_WINDOWS:
        if prev >= len(src):
            break
        got = answer(src[:size])
        if got:
            return got
        prev = size
    return ''


def _first(rx, text: str) -> str:
    m = rx.search(text)
    return m.group(1) if m else ''


# `LAST-UPDATED "200210160000Z"` in the MODULE-IDENTITY. Both widths are in the wild — SMIv2
# writes the year in four digits and SMIv1 in two — and a real vendor archive holds both.
_LAST_UPDATED_RE = re.compile(r'\bLAST-UPDATED\s+"([0-9]{10,12})Z"', re.IGNORECASE)


def last_updated(text: str) -> str:
    """The date the MIB says it was last revised, as ``YYYY-MM-DD``, or ``''``.

    The FIRST one, which is the MODULE-IDENTITY's: the REVISION clauses below it carry the
    history, and the newest of them is what this one repeats.

    A two-digit year is SMIv1 and is read the way every SMI tool reads it — 70 and above is
    the nineteen-hundreds. These MIBs are from the nineties; a `99` that came out as 2099
    would sort as the newest file in the library.
    """
    # Comments blanked, STRINGS KEPT: the date lives inside a quoted string, and _blank()
    # takes those out too — it exists for the linter, which reads code and must not read
    # prose. Here the prose is the answer.
    d = _in_header(text, lambda t: _first(_LAST_UPDATED_RE, _no_comments(t)))
    if not d:
        return ''
    if len(d) == 10:                            # YYMMDDHHMM
        yy = int(d[:2])
        d = ('19' if yy >= 70 else '20') + d
    return f'{d[0:4]}-{d[4:6]}-{d[6:8]}'


def declared_names(text: str) -> set:
    """Every descriptor this MIB defines — the objects, types and identities it declares.

    What a MIB *is*, in the only terms that survive being copied, renamed or re-indented. Two
    files that carry the same module name and share none of these are not two copies of one
    MIB: they are two different MIBs with the same first line, which a vendor archive produces
    by copy-pasting a header and which no amount of diffing will make sense of.
    """
    return {m.group(1) for m in _VALUE_DEF_RE.finditer(_blank(text or ''))}


def _no_comments(text: str) -> str:
    """The file with its comments blanked out. Strings survive."""
    return _mask(text, strings=False)


def _blank(text: str) -> str:
    """The file with comments and quoted text blanked out, newlines kept.

    Line numbers have to survive — a finding without the right line is a finding somebody has
    to go and find — so everything is replaced by spaces of the same length rather than cut.
    """
    return _mask(text, strings=True)


def _mask(text: str, strings: bool) -> str:
    """One left-to-right pass, blanking comments and (optionally) quoted text.

    Same length, same newlines: every masked character becomes a space, so a line number is
    still a line number afterwards.

    ASN.1's two rules, applied in the only order that is not a guess — whichever opens first:
    a comment runs from ``--`` to the next ``--`` or the end of its line; a string runs from
    ``"`` to the next ``"``, may span lines, and doubles the quote to escape it.
    """
    src = text or ''
    n = len(src)
    if n == 0:
        return src
    # Jumped, not walked: `_OPENS` finds the next `"` or `--` at C speed and everything
    # between two of them is copied in one slice. A character-at-a-time loop over the 200 KB
    # of every file in a five-thousand-MIB library is a minute of somebody's afternoon.
    out = []
    at = 0
    i = 0
    while i < n:
        m = _OPENS.search(src, i)
        if m is None:
            break
        i = m.start()
        if src[i] == '"':
            j = i + 1
            while True:
                k = src.find('"', j)
                if k < 0:
                    j = n
                    break
                if k + 1 < n and src[k + 1] == '"':      # "" — an escaped quote
                    j = k + 2
                    continue
                j = k + 1
                break
            if not strings:
                i = j
                continue
        else:
            end = src.find('\n', i + 2)
            end = n if end < 0 else end
            k = src.find('--', i + 2)
            j = k + 2 if 0 <= k < end else end
        out.append(src[at:i])
        out.append(_spaces(src[i:j]))
        at = j
        i = j
    out.append(src[at:])
    return ''.join(out)


# The two things that open something in ASN.1. Whichever comes first wins — that is the whole
# rule, and it is the one the two-regex version could not express.
_OPENS = re.compile(r'"|--')


def _spaces(chunk: str) -> str:
    """*chunk* with every character but the newlines turned into a space.

    The length and the lines have to survive: a finding is reported at a line number, and one
    reported at the wrong line is one somebody has to go and find.
    """
    if '\n' not in chunk:
        return ' ' * len(chunk)
    return '\n'.join(' ' * len(part) for part in chunk.split('\n'))


def _line_of(text: str, pos: int) -> int:
    return text.count('\n', 0, pos) + 1


def _imported(body: str) -> set:
    m = _IMPORTS_RE.search(body)
    if not m:
        return set()
    out = set()
    for chunk in re.split(r'\bFROM\b', m.group(1))[:-1]:
        # The module name of the previous FROM trails into this chunk; symbols are what is
        # left once it is dropped.
        for sym in re.split(r'[\s,]+', chunk.strip()):
            sym = sym.strip()
            if sym and re.match(r'^[A-Za-z][A-Za-z0-9_-]*$', sym):
                out.add(sym)
    return out


def lint_mib(text: str, filename: str = '') -> list[dict]:
    """Findings for one MIB source, as ``[{line, code, symbol, message}]``.

    Empty when there is nothing this is sure about — which includes a file it cannot make
    sense of at all. Being quiet is the right answer far more often than guessing.
    """
    if not text or 'DEFINITIONS' not in text:
        return []
    body = _blank(text)

    values = {m.group(1) for m in _VALUE_DEF_RE.finditer(body)
              if m.group(1) not in _ASN1_KEYWORDS}
    values |= {m.group(1) for m in _OID_DEF_RE.finditer(body)
               if m.group(1) not in _ASN1_KEYWORDS}
    types = {m.group(1) for m in _TYPE_DEF_RE.finditer(body)}
    seq_types = {m.group(1) for m in _SEQ_TYPE_RE.finditer(body)}
    imported = _imported(body)
    known = values | types | imported | _BUILTIN_TYPES

    out: list[dict] = []

    # ── A file that is not named after the module it declares ────────────────
    # pysmi resolves an imported module by NAME against the directories it was given: it looks
    # for a file called after the module. Named anything else, this MIB is one that every MIB
    # importing it fails to find — and the failure lands on THEM, naming symbols they cannot
    # resolve, with nothing pointing here.
    declared = module_name(text)
    stem = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0] if filename else ''
    if declared and stem and declared != stem:
        out.append({
            'line': 1,
            'code': 'filename-mismatch',
            'symbol': declared,
            'message': (f'This file declares "{declared}" but is called "{stem}". A MIB is '
                        f'resolved by the name of its module, so anything importing it will '
                        f'not find it here. Rename the file to {declared}.'),
        })

    # ── A descriptor that starts with a capital letter ────────────────────────
    for m in _VALUE_DEF_RE.finditer(body):
        name = m.group(1)
        if name in _ASN1_KEYWORDS:
            continue
        if name[:1].isupper():
            out.append({
                'line': _line_of(body, m.start()),
                'code': 'uppercase-descriptor',
                'symbol': name,
                'message': (f'"{name}" defines a value, so it must start with a lowercase '
                            f'letter: an initial capital is a TYPE reference in SMI. '
                            f'Suggested: {name[0].lower() + name[1:]}'),
            })

    # ── A type used and neither imported nor defined here ────────────────────
    def _unknown_type(sym: str) -> bool:
        # Only an initial capital is a type reference; anything lowercase is a value, and a
        # value this MIB does not define is somebody else's problem (and pysmi's).
        return bool(sym) and sym[0].isupper() and sym not in known

    seen_missing = set()
    for m in _SYNTAX_RE.finditer(body):
        sym = m.group(1)
        if not _unknown_type(sym):
            continue
        seen_missing.add(sym)
        out.append({
            'line': _line_of(body, m.start()),
            'code': 'missing-import',
            'symbol': sym,
            'message': (f'"{sym}" is used as a type and is neither imported nor defined in '
                        f'this MIB. Add it to the IMPORTS of the module that defines it.'),
        })

    # …and in the columns of a row type, which no SYNTAX clause names.
    for m in _SEQ_BODY_RE.finditer(body):
        for fm in _SEQ_FIELD_RE.finditer(m.group(1)):
            sym = fm.group(2)
            if sym in seen_missing or not _unknown_type(sym):
                continue
            seen_missing.add(sym)
            out.append({
                'line': _line_of(body, m.start(1) + fm.start(2)),
                'code': 'missing-import',
                'symbol': sym,
                'message': (f'"{sym}" is the type of a column and is neither imported nor '
                            f'defined in this MIB. Add it to the IMPORTS of the module that '
                            f'defines it.'),
            })

    # ── SEQUENCE OF pointing at something that is not a row type ─────────────
    for m in _SEQUENCE_OF_RE.finditer(body):
        sym = m.group(1)
        if sym in seq_types:
            continue
        line = _line_of(body, m.start())
        if sym in values:
            out.append({
                'line': line,
                'code': 'sequence-of-value',
                'symbol': sym,
                'message': (f'"SEQUENCE OF {sym}" names an object, not a type. A table\'s '
                            f'syntax must name the SEQUENCE type its rows have.'),
            })
        elif sym not in known:
            out.append({
                'line': line,
                'code': 'sequence-of-unknown',
                'symbol': sym,
                'message': (f'"SEQUENCE OF {sym}" names something this MIB never defines as '
                            f'a SEQUENCE.'),
            })

    out.sort(key=lambda f: (f['line'], f['code'], f['symbol']))
    return out
