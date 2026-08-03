#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para lib/util/tools.py — bytes2human, fmt_bytes/to_bytes y la regla de que hay
UN solo formateador de tamaños en el proyecto.

Split by category: this file holds the structural guards (they read the repo's own source, docs
and templates); the rest of the original ``test_tools.py`` lives in
``tests/unit/test_tools.py``."""

import io
import os


SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]














class TestThereIsOneByteFormatter:
    """`fmt_bytes` scales in 1024s. A browser-side formatter counting in 1000s would print a
    different size for the same number depending on which side of the wire formatted it —
    and the panel would be quietly inconsistent with its own alerts and Status bar, which is
    the kind of wrong that never gets reported as a bug, only doubted.

    Caught in review: a JS `formatBytes` had been written before anyone checked whether the
    project already answered this. It did.
    """

    def test_the_server_sends_the_formatted_size(self):
        src = io.open(os.path.join(SRC, 'lib', 'core', 'config', 'routes.py'),
                      encoding='utf-8').read()
        assert 'fmt_bytes(' in src, 'the response stopped carrying a formatted size'

    def test_the_browser_does_not_format_bytes_itself(self):
        """Not a style rule: the two would disagree on the same input."""
        import glob                                              # noqa: PLC0415
        pat = os.path.join(SRC, 'lib', 'web_admin', 'templates', '**', '*.html')
        for path in glob.glob(pat, recursive=True):
            body = io.open(path, encoding='utf-8', errors='replace').read()
            assert 'function formatBytes' not in body, \
                f'{os.path.basename(path)} defines a second byte formatter'
            # The ladder itself is the tell — a scaling loop needs the unit names.
            assert "['B', 'KB', 'MB'" not in body, \
                f'{os.path.basename(path)} scales byte units in the browser'

    def test_the_toast_prints_what_the_server_sent(self):
        body = io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                    'cfg', '_db_maintenance.html'), encoding='utf-8').read()
        assert 'freed.freed_human' in body, 'the toast stopped printing the server\'s figure'
        # Strict `=== 0`, so "reclaimed nothing" is a different branch from "would not say".
        # A loose `== 0` matches null too, and the engine that refuses to disclose a size
        # would be reported as having freed nothing.
        assert 'bytes_freed === 0' in body, \
            'unknown is being treated as a number again — it would render as "freed nothing"'
