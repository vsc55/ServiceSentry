#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Every import of the project's own code names something that exists.

A deferred import — inside a function, to break a cycle or to keep a start-up light — is only
looked up when that line runs. Renaming `lib/core/hosts/` to `lib/core/devices/` turned
``from lib.core.hosts.store import HostsStore`` in the SNMP sampler into
``from lib.core.devices.store import DevicesStore``: the package is `stores`, the import raised,
the sampler's ``except`` swallowed it, and a port somebody marked as the line to the internet
stopped reporting when it went down. The whole suite stayed green except for two tests that
happened to walk that branch.

This reads every ``import`` / ``from … import`` of `lib`, `watchfuls` and `tests` in the tree,
at any indent, and checks it against the files on disk — without importing anything, so it
runs the same with or without Flask.
"""

import ast
import os
import re
import warnings

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
OURS = ('lib', 'watchfuls', 'tests')
SKIP_DIRS = {'__pycache__', '.venv', 'venv', 'node_modules', '.git'}


def _py_files():
    for base, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(base, f)


def _module_file(dotted):
    """The file that defines *dotted*, or None. A package is its ``__init__.py``."""
    path = os.path.join(SRC, *dotted.split('.'))
    for cand in (path + '.py', os.path.join(path, '__init__.py')):
        if os.path.isfile(cand):
            return cand
    if os.path.isdir(path):           # a namespace package (no __init__) still imports
        return path
    return None


def _defines(module_file, name):
    """Whether *name* can be imported from *module_file*: a submodule beside it, or a word its
    source binds. A word anywhere is generous on purpose — the failure this catches is a name
    that is not there at all."""
    if os.path.isdir(module_file):
        return False
    if os.path.basename(module_file) == '__init__.py':
        pkg = os.path.dirname(module_file)
        if os.path.isfile(os.path.join(pkg, name + '.py')) or os.path.isdir(
                os.path.join(pkg, name)):
            return True
    with open(module_file, encoding='utf-8') as fh:
        src = fh.read()
    return re.search(r'\b%s\b' % re.escape(name), src) is not None


def _broken_imports():
    broken = []
    for path in _py_files():
        try:
            with open(path, encoding='utf-8') as fh, warnings.catch_warnings():
                warnings.simplefilter('ignore', SyntaxWarning)   # escapes in other files' strings
                tree = ast.parse(fh.read(), filename=path)
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = os.path.relpath(path, SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split('.')[0] in OURS and not _module_file(alias.name):
                        broken.append(f'{rel}:{node.lineno} import {alias.name}')
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module.split('.')[0] not in OURS:
                    continue
                mod = _module_file(node.module)
                if not mod:
                    broken.append(f'{rel}:{node.lineno} from {node.module} (no such module)')
                    continue
                for alias in node.names:
                    if alias.name != '*' and not _defines(mod, alias.name):
                        broken.append(f'{rel}:{node.lineno} from {node.module} '
                                      f'import {alias.name} (not defined there)')
    return broken


class TestEveryImportResolves:

    def test_no_import_names_a_module_or_a_name_that_is_gone(self):
        broken = _broken_imports()
        assert not broken, 'imports that would raise when that line runs:\n  ' + \
            '\n  '.join(broken)

    @pytest.mark.parametrize('line, expected', [
        ('from lib.core.devices.stores import DevicesStore', True),
        ('from lib.core.devices.store import DevicesStore', False),
        ('from lib.core.devices.stores import HostsStore', False),
    ])
    def test_the_check_tells_a_live_import_from_a_dead_one(self, line, expected):
        """The guard bites: the exact import that broke the SNMP sampler is caught, and the
        right one is not."""
        node = ast.parse(line).body[0]
        mod = _module_file(node.module)
        ok = bool(mod) and all(_defines(mod, a.name) for a in node.names)
        assert ok is expected
