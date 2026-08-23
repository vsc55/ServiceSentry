#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The core does not import a module. It never has; now something says so.

``lib/`` is the foundation and ``watchfuls/`` is what gets plugged into it, and the
relationship only works in one direction: a watchful imports ``lib.modules.ModuleBase`` and
whatever else it needs, while the core learns about modules by **discovering** them — reading
their ``schema.json`` off disk, scanning for declarations — and never by importing one.

That is what makes a module removable. It is also what makes the core testable without one.

The rule was true and unwritten until SNMP started moving into ``lib/core/snmp``: a move like
that is exactly when somebody reaches for ``from watchfuls.snmp import …`` to finish a
half-migrated import, and nothing would have failed. The dependency would simply have become
a cycle in waiting — ``lib`` importing a module that imports ``lib``.

Reading a module's files is fine and is not what this checks: discovery opens ``schema.json``
by path on purpose.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
LIB = os.path.join(SRC, 'lib')

# `import watchfuls…` / `from watchfuls… import` at the start of a line (any indent), which
# covers the deferred-import-inside-a-function case too — a cycle broken by moving the import
# into the function body is still the core depending on a module.
_IMPORT = re.compile(r'^\s*(?:from|import)\s+watchfuls(?:\.|\s|$)', re.M)


def _py_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(base, f)


class TestTheDependencyPointsOneWay:

    def test_no_core_file_imports_a_watchful(self):
        offenders = []
        for path in _py_files(LIB):
            src = io.open(path, encoding='utf-8-sig').read()
            for m in _IMPORT.finditer(src):
                line = src.count('\n', 0, m.start()) + 1
                rel = os.path.relpath(path, SRC).replace(os.sep, '/')
                offenders.append(f'{rel}:{line}')
        assert not offenders, (
            'the core imports a watchful — discover it instead (read its schema.json), or '
            'move what is being reached for into lib/: ' + ', '.join(offenders))

    def test_the_scan_reaches_the_files_it_claims_to(self):
        """A guard that walks an empty tree passes for the wrong reason."""
        found = list(_py_files(LIB))
        assert len(found) > 100, f'only {len(found)} files under lib/ — the scan is wrong'
        assert any(p.endswith(os.path.join('snmp', 'profiles', '__init__.py'))
                   for p in found)

    def test_the_pattern_would_catch_one(self):
        """Positive control: the regex, not the absence of offenders, is what is trusted."""
        for line in ('import watchfuls.snmp',
                     'from watchfuls.snmp import profiles',
                     '    from watchfuls import ping',      # deferred, inside a function
                     'import watchfuls'):
            assert _IMPORT.search(line), line
        for line in ('# from watchfuls.snmp import profiles is what we must NOT do',
                     "path = os.path.join(base, 'watchfuls')",
                     'from lib.core.snmp import profiles'):
            assert not _IMPORT.search(line), line
