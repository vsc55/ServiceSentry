#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Every HTTP route must be documented where a reader will look for it.

Routes live with the thing they serve, so the URL surface is spread across ~30 modules. Two
places keep it discoverable, and both drifted before this test existed:

* each route module's own header lists its exact endpoints;
* ``lib/web_admin/routes/__init__.py`` is the index of the whole surface, by prefix.

The checks are deliberately mechanical (a path either appears or it does not), so adding an
endpoint without documenting it fails here rather than being noticed months later.
"""

import ast
import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
LIB = os.path.join(SRC, 'lib')
INDEX = os.path.join(LIB, 'web_admin', 'routes', '__init__.py')

_ROUTE_RE = re.compile(r"@app\.route\(\s*'([^']+)'")


def _route_modules():
    """{path: (routes, module docstring)} for every module registering Flask routes."""
    out = {}
    for root, dirs, files in os.walk(LIB):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if not f.endswith('.py'):
                continue
            p = os.path.join(root, f)
            txt = io.open(p, encoding='utf-8-sig', errors='replace').read()
            paths = sorted(set(_ROUTE_RE.findall(txt)))
            if paths:
                out[os.path.relpath(p, SRC)] = (paths, ast.get_docstring(ast.parse(txt)) or '')
    return out


class TestPerModuleHeaders:

    def test_every_route_is_listed_in_its_module_header(self):
        missing = [(mod, r) for mod, (routes, doc) in sorted(_route_modules().items())
                   for r in routes if r not in doc]
        assert not missing, 'routes absent from their own module docstring: ' + ', '.join(
            f'{r} ({mod})' for mod, r in missing)

    def test_headers_use_the_real_parameter_names(self):
        """A header saying ``/api/v1/ipbans/<ip>`` for a route declared ``<path:ip>`` reads
        fine but stops matching, which is how the drift started. The check above already
        enforces this — this one just names the failure mode."""
        mods = _route_modules()
        assert mods, 'no route modules found — the scan is broken, not the docs'


class TestSurfaceIndex:

    def _globs(self):
        head = io.open(INDEX, encoding='utf-8-sig').read().split('── path convention')[0]
        return {g for g in re.findall(r'(/[A-Za-z0-9_<>:/\.-]+)\*?', head) if len(g) > 4}

    def test_every_route_falls_under_an_indexed_prefix(self):
        """The index lists prefixes (``/api/v1/users*``), not endpoints — a new DOMAIN has to
        appear there, a new endpoint inside a known one does not."""
        globs = self._globs()
        uncovered = sorted({
            r for routes, _ in _route_modules().values() for r in routes
            if len(r) > 4 and not any(r == g or r.startswith(g.rstrip('*')) for g in globs)})
        assert not uncovered, f'not under any prefix in routes/__init__.py: {uncovered}'
