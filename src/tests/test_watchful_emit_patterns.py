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
"""

import ast
import io
import os
import pathlib

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def _is_manual(node) -> bool:
    """Pattern B: send_msg passed (4th positional or by keyword) to suppress the
    monitor's own notification."""
    kw = {k.arg for k in node.keywords}
    return len(node.args) >= 4 or 'send_msg' in kw


class TestTheScanItself:

    def test_watchfuls_are_found(self):
        assert WATCHFULS.is_dir(), f'no watchfuls directory at {WATCHFULS}'

    def test_set_calls_are_found(self):
        calls = list(_set_calls())
        assert len(calls) > 10, f'only {len(calls)} dict_return.set calls found — scan broken'


class TestEveryResultIsNamed:

    def test_automatic_results_carry_an_explicit_name(self):
        """Pattern A must pass ``name``: the monitor's fallback resolves the bound HOST,
        which is a different thing from the check's own label. Eleven sites got this wrong
        — every one of them an error/unsupported branch, i.e. exactly the moment the
        notification matters most."""
        missing = [f'{mod}:{line}' for mod, line, n in _set_calls()
                   if not _is_manual(n) and 'name' not in {k.arg for k in n.keywords}]
        assert not missing, (
            'dict_return.set() without name= (the alert would be labelled with the bound '
            'host, not the check): ' + ', '.join(missing))

    def test_other_data_name_is_not_mistaken_for_the_real_one(self):
        """``other_data={'name': …}`` does NOT feed the notification: ``get_name()`` reads
        the top-level field. Two modules carried that mistake, looking correct at a glance."""
        wrong = []
        for mod, line, n in _set_calls():
            if 'name' in {k.arg for k in n.keywords}:
                continue
            for k in n.keywords:
                if k.arg == 'other_data' and isinstance(k.value, ast.Dict):
                    keys = [x.value for x in k.value.keys
                            if isinstance(x, ast.Constant)]
                    if 'name' in keys:
                        wrong.append(f'{mod}:{line}')
        assert not wrong, (
            "other_data={'name': …} without a top-level name= — get_name() will not see "
            'it: ' + ', '.join(wrong))


class TestManualPatternStaysRare:

    def test_manual_emit_is_the_exception_not_the_rule(self):
        """Pattern B is legitimate but costlier: it splits the decision between module and
        monitor, and it is where the severity-dropped-on-notify bug lived. This does not
        forbid it — it makes a silent drift towards it visible."""
        manual = {mod for mod, _l, n in _set_calls() if _is_manual(n)}
        # Only service_status still pairs by hand; everything else goes through
        # ModuleBase._emit or the automatic path.
        assert manual <= {'watchfuls/service_status/__init__.py'}, (
            'new hand-rolled set(send_msg=False) found — use ModuleBase._emit, or the '
            f'automatic pattern: {sorted(manual)}')
