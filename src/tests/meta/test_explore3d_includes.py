#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""/3d loads a CHOSEN part of the panel's script, and nothing it runs on load may need the rest.

The page (`explore3d.html`) does not load the panel's whole bundle: it takes the core, the 3D
engine and the inventory's pieces. Function bodies only run when called, but a statement at the
top of a file runs while the page loads — and if it names something defined in a file the page
did not include, the page dies there with a `ReferenceError` and draws nothing. That happened
twice while it was being written (`FIELD_PICKERS`, `createListTable`), and it will happen again
the day somebody adds a line like that to an inventory partial: the panel keeps working, so
nobody sees /3d go blank. This reads the files and says which line and which name.
"""

from __future__ import annotations

import io
import os
import re

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_TPL = os.path.join(_SRC, 'lib', 'web_admin', 'templates')
#: Where `core/…` includes resolve: the 3D viewer lives in its own package
#: (`lib/core/view3d/web/`), which the template loader reaches through `lib`.
_LIB = os.path.join(_SRC, 'lib')
_PAGE = 'core/view3d/web/explore3d.html'


def _path(rel):
    return os.path.join(_LIB if rel.startswith('core/') else _TPL, rel)
_DECL = re.compile(r'^(?:async\s+)?function\s+(\w+)|^(?:let|const|var)\s+(\w+)', re.M)


def _text(rel):
    s = io.open(_path(rel), encoding='utf-8').read()
    return re.sub(r'\{#.*?#\}', '', s, flags=re.S)


def _included():
    page = io.open(_path(_PAGE), encoding='utf-8').read()
    return [p for p in re.findall(r'include "((?:partials|core)/[^"]+)"', page) if '_modals' not in p]


def test_the_page_includes_files_that_exist():
    falta = [p for p in _included() if not os.path.isfile(_path(p))]
    assert not falta, falta


def test_nothing_it_runs_on_load_needs_a_file_it_does_not_include():
    incluidos = _included()
    definidos = set()
    for rel in incluidos:
        definidos |= {a or b for a, b in _DECL.findall(_text(rel))}
    # Where each name of the panel is defined, to name the file that would be missing.
    donde = {}
    for base, sub in ((_TPL, 'partials'), (_LIB, os.path.join('core', 'view3d', 'web'))):
        for raiz, _dirs, ficheros in os.walk(os.path.join(base, sub)):
            for f in ficheros:
                if f.endswith('.html'):
                    rel = os.path.relpath(os.path.join(raiz, f), base).replace(os.sep, '/')
                    for a, b in _DECL.findall(_text(rel)):
                        donde.setdefault(a or b, rel)
    malos = []
    for rel in incluidos:
        nivel = 0
        for n, linea in enumerate(_text(rel).split('\n'), 1):
            codigo = re.sub(r'//.*$', '', linea)
            if (nivel == 0 and codigo and not codigo[0].isspace()
                    and not re.match(r'(async\s+)?function|/\*|\*|\}|\)|\]', codigo)):
                for nombre in set(re.findall(r'\b([A-Za-z_]\w*)\b', codigo)):
                    if nombre not in definidos and donde.get(nombre) not in (None, *incluidos):
                        malos.append(f'{rel}:{n} uses {nombre} from {donde[nombre]}')
            nivel += codigo.count('{') - codigo.count('}')
    assert not malos, ('explore3d.html would stop on load — include the file, or move the '
                       'statement into a function: ' + '; '.join(malos))


def test_no_constant_it_reads_lives_in_a_file_it_does_not_include():
    """Inside a function too. Reported from the screen: opening a rack in /3d did nothing — the
    rack's 3D read `_DC_QUIET_ROLES`, defined in the devices screen, which /3d does not include,
    and the `ReferenceError` came on the click, not on load, so the guard above let it through.
    A constant (`_UPPER_CASE`) is never guarded with `typeof`, so naming one from a file the page
    does not include is always a bug."""
    incluidos = _included()
    definidos = set()
    for rel in incluidos:
        definidos |= {a or b for a, b in _DECL.findall(_text(rel))}
    donde = {}
    for base, sub in ((_TPL, 'partials'), (_LIB, os.path.join('core', 'view3d', 'web'))):
        for raiz, _dirs, ficheros in os.walk(os.path.join(base, sub)):
            for f in ficheros:
                if f.endswith('.html'):
                    rel = os.path.relpath(os.path.join(raiz, f), base).replace(os.sep, '/')
                    for a, b in _DECL.findall(_text(rel)):
                        donde.setdefault(a or b, rel)
    malos = set()
    for rel in incluidos:
        for n, linea in enumerate(_text(rel).split('\n'), 1):
            codigo = re.sub(r'//.*$', '', linea)
            for nombre in re.findall(r'\b(_[A-Z][A-Z0-9_]{2,})\b', codigo):
                if nombre not in definidos and donde.get(nombre) not in (None, *incluidos):
                    malos.add(f'{rel}:{n} uses {nombre} from {donde[nombre]}')
    assert not malos, ('explore3d.html would fail when this runs — include the file, or move '
                       'the constant to one it includes: ' + '; '.join(sorted(malos)))
