#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``docs/ref-esquema-bd.md`` describes the tables that actually exist, and all of them.

The document is the only place the physical schema is explained in prose: what each table is
for, which column carries what, and which relationships are references-by-UID rather than
foreign keys (the engine never emits `FOREIGN KEY`). That makes it the thing somebody reads
before touching a store — and a schema document that has quietly drifted is worse than none,
because it is read with the confidence that only a written-down answer earns.

Nothing kept it honest until now. The tables matched by hand on the day this was written; the
next `TableSpec` added would not have failed anything by going undocumented.

The comparison runs both ways deliberately. A table missing from the doc is the obvious rot; a
table documented but gone from the code is the one that survives longest, because nobody greps
for a name that no longer exists.
"""

import ast
import io
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(SRC, 'lib')
DOC = os.path.join(os.path.dirname(SRC), 'docs', 'ref-esquema-bd.md')


def _const(node):
    return node.value if isinstance(node, ast.Constant) else None


def _specs_from_code() -> dict:
    """``{table: [column names, in declaration order]}`` from every ``TableSpec(...)``.

    Read with AST rather than by importing: a store module pulls in connectors and service
    packages, and this guard is about what the source SAYS, not what a live process assembles.
    """
    out: dict = {}
    for base, dirs, files in os.walk(LIB):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for fname in files:
            if not fname.endswith('.py'):
                continue
            src = io.open(os.path.join(base, fname), encoding='utf-8').read()
            if 'TableSpec(' not in src:
                continue
            for node in ast.walk(ast.parse(src)):
                if not (isinstance(node, ast.Call)
                        and getattr(node.func, 'id', '') == 'TableSpec'):
                    continue
                name, cols_node = None, None
                if node.args:
                    name = _const(node.args[0])
                    if len(node.args) > 1:
                        cols_node = node.args[1]
                for kw in node.keywords:
                    if kw.arg == 'name':
                        name = _const(kw.value)
                    elif kw.arg == 'columns':
                        cols_node = kw.value
                if not name:
                    continue
                cols = []
                if isinstance(cols_node, (ast.List, ast.Tuple)):
                    for el in cols_node.elts:
                        if isinstance(el, ast.Call) and getattr(el.func, 'id', '') == 'Column':
                            if el.args:
                                cols.append(_const(el.args[0]))
                            else:
                                cols += [_const(k.value) for k in el.keywords if k.arg == 'name']
                out[name] = [c for c in cols if c]
    return out


def _specs_from_doc() -> dict:
    """``{table: [column names]}`` from each ``### `name`` section's column table."""
    text = io.open(DOC, encoding='utf-8').read()
    out: dict = {}
    parts = re.split(r'^### `([a-z_0-9]+)`', text, flags=re.M)
    for i in range(1, len(parts), 2):
        # Stop at the next heading of ANY level: without this the last table section swallows
        # the rest of the document, and the per-engine type map is a markdown table too.
        body = re.split(r'^#{2,3} ', parts[i + 1], maxsplit=1, flags=re.M)[0]
        cols = []
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith('|'):
                continue
            cell = line.strip('|').split('|')[0].strip()
            if cell == 'Columna' or not cell or set(cell) <= {'-', ' '}:
                continue
            cols.append(cell.strip('`'))
        out[parts[i]] = cols
    return out


CODE = _specs_from_code()
DOCUMENTED = _specs_from_doc()


class TestEveryTableIsAccountedFor:

    def test_no_table_is_undocumented(self):
        """The obvious rot: a store gains a table and the reference never hears about it."""
        missing = sorted(set(CODE) - set(DOCUMENTED))
        assert not missing, f'declared but not in ref-esquema-bd.md: {missing}'

    def test_no_documented_table_is_gone(self):
        """The rot that lasts longest: nobody greps for a table that no longer exists, so a
        section describing one outlives every reader who could have noticed."""
        stale = sorted(set(DOCUMENTED) - set(CODE))
        assert not stale, f'documented but no TableSpec declares them: {stale}'

    def test_the_headline_count_is_the_real_one(self):
        """The intro states a number. A reader uses it to decide whether the list looks
        complete, which is exactly the kind of check a stale number defeats."""
        text = io.open(DOC, encoding='utf-8').read()
        m = re.search(r'Hay \*\*(\d+) tablas\*\*', text)
        assert m, 'the table count sentence is gone — update this guard with what replaced it'
        assert int(m.group(1)) == len(CODE), \
            f'the doc says {m.group(1)} tables, the code declares {len(CODE)}'


class TestEveryColumnIsAccountedFor:
    """One test per rule, not one per table.

    Parametrising over the thirty-three tables was the first shape of this, and it multiplied
    eight test functions into a hundred and four — far enough above the file's `def` count that
    `test_docs_tests_inventory` flagged it as a rotten declaration, and rightly: every other
    file in the suite sits under 3×, so widening that ceiling for this one would have blunted
    the check for the other hundred and thirty.

    Reporting every drifted table in one message is better anyway. Parametrising showed the
    first failure alphabetically; this shows all of them, which is what somebody who has just
    renamed a column actually needs.
    """

    def test_no_column_is_undocumented(self):
        bad = []
        for table in sorted(set(CODE) & set(DOCUMENTED)):
            missing = [c for c in CODE[table] if c not in DOCUMENTED[table]]
            if missing:
                bad.append(f'{table}: {missing}')
        assert not bad, 'columns declared but not documented — ' + '; '.join(bad)

    def test_no_documented_column_is_gone(self):
        bad = []
        for table in sorted(set(CODE) & set(DOCUMENTED)):
            stale = [c for c in DOCUMENTED[table] if c not in CODE[table]]
            if stale:
                bad.append(f'{table}: {stale}')
        assert not bad, 'documented columns that do not exist — ' + '; '.join(bad)

    def test_the_order_matches_the_declaration(self):
        """Column order is how the two are read side by side. It is also load-bearing for the
        reconcile: a column missing from the END is added in place, while one missing from the
        MIDDLE forces a full table rebuild — so a doc that lists them in another order hides
        which change is cheap and which rewrites the table."""
        bad = []
        for table in sorted(set(CODE) & set(DOCUMENTED)):
            if CODE[table] != DOCUMENTED[table] and set(CODE[table]) == set(DOCUMENTED[table]):
                bad.append(f'{table}: code={CODE[table]} doc={DOCUMENTED[table]}')
        assert not bad, 'same columns, different order — ' + '; '.join(bad)


class TestTheGuardIsLookingAtSomething:
    """A guard over a parser that silently matches nothing passes for ever."""

    def test_it_found_the_tables(self):
        assert len(CODE) >= 30, f'only {len(CODE)} TableSpec found — the scan is broken'

    def test_it_found_the_columns(self):
        empty = sorted(t for t, cols in CODE.items() if not cols)
        assert not empty, f'TableSpec with no columns parsed: {empty}'
        empty_doc = sorted(t for t, cols in DOCUMENTED.items() if not cols)
        assert not empty_doc, f'documented tables with no column table: {empty_doc}'
