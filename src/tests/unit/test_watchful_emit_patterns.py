#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A watchful reports a result in one of two ways, and both must name the item.

There are two legitimate patterns (see ``docs/ref-watchful-emit.md``):

* **A — automatic**: ``dict_return.set(...)`` and the monitor notifies from its own digest
  path, reading the severity off the stored result.  The default.
* **B — manual**: :meth:`ModuleBase._emit` (``send_msg=False`` + ``check_status`` +
  ``send_message``).  For the three things A cannot express.

The failure this guards against is real and was found in **eleven** call sites: a module
using B on its main path and A in its exception branch, without passing ``name`` to the
latter.  The monitor then falls back to resolving the BOUND HOST, so the same check
appeared in notifications under two different names depending on how it failed — "A
example.com" normally, "ns1" when it raised.

Mechanical on purpose: an argument is either there or it is not.


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_watchful_emit_patterns.py`` lives in
``tests/meta/test_watchful_emit_patterns.py``."""

import ast
import io
import os
import pathlib

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
WATCHFULS = pathlib.Path(SRC) / 'watchfuls'


def _set_calls():
    """Every ``self.dict_return.set(...)`` in a watchful → (module, line, node)."""
    for p in sorted(WATCHFULS.rglob('*.py')):
        if 'tests' in p.parts or p.name == 'watchful.py':
            continue
        tree = ast.parse(io.open(p, encoding='utf-8-sig').read())
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == 'set'
                    and isinstance(n.func.value, ast.Attribute)
                    and n.func.value.attr == 'dict_return'):
                yield str(p.relative_to(SRC)).replace(os.sep, '/'), n.lineno, n


class TestTheScanItself:

    def test_watchfuls_are_found(self):
        assert WATCHFULS.is_dir(), f'no watchfuls directory at {WATCHFULS}'

    def test_set_calls_are_found(self):
        calls = list(_set_calls())
        assert len(calls) > 10, f'only {len(calls)} dict_return.set calls found — scan broken'




