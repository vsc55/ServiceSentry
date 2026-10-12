#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A value inside a JS string in an inline handler is passed with `jsStr`, never `escAttr`/`esc`.

Found by the 2026-10-12 audit as stored XSS in the catalogue and the schemas:
``onclick="_dcCatDrop('${escAttr(name)}')"``. `escAttr` turns `'` into `&#39;`, and the HTML
parser turns it back into `'` BEFORE the handler runs — so a model named
``a');alert(document.domain);//`` closed the string and ran, and one named «O'Neil» left the
button doing nothing. `jsStr` (JSON-encode, then attribute-escape) is the one that survives
both parsers. Sixty-odd sites across the panel had the pattern; this keeps it from returning.

And `esc` — text, not attributes — now escapes quotes too, because it had ended up inside some
thirty attribute values; checked here by reading its body.
"""

from __future__ import annotations

import glob
import os
import re

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]

#: An inline handler attribute, opened with a double quote.
_ON = re.compile(r'\bon[a-z]+="')
#: A template value wrapped in single quotes: a JS string literal built from `esc`/`escAttr`.
_BAD = re.compile(r"'\$\{\s*(?:escAttr|esc)\(")


def _templates():
    pats = ('lib/web_admin/templates/**/*.html', 'lib/core/**/web/**/*.html', 'watchfuls/**/*.html')
    for pat in pats:
        yield from glob.glob(os.path.join(_SRC, pat), recursive=True)


def _inside_handler(text: str, pos: int) -> bool:
    """Whether *pos* sits inside an ``on…="…"`` attribute: the last handler opened before it
    has not been closed by a ``"`` that ends the attribute."""
    start = max(0, pos - 800)
    last = None
    for m in _ON.finditer(text, start, pos):
        last = m
    if not last:
        return False
    return not re.search(r'"(\s|>|$)', text[last.end():pos])


def test_no_esc_or_escattr_inside_a_js_string_in_a_handler():
    found = []
    for path in _templates():
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        for m in _BAD.finditer(text):
            if _inside_handler(text, m.start()):
                line = text.count('\n', 0, m.start()) + 1
                found.append(f'{os.path.relpath(path, _SRC)}:{line}')
    assert not found, ('a JS string in an inline handler built with esc/escAttr — use '
                       '${jsStr(value)} without the quotes:\n  ' + '\n  '.join(found))


def test_esc_escapes_quotes():
    with open(os.path.join(_SRC, 'lib/web_admin/templates/partials/core/_utils.html'),
              encoding='utf-8') as fh:
        text = fh.read()
    body = text[text.index('function esc(s)'):]
    body = body[:body.index('\n}') + 2]
    # By itself, or by being `escAttr`, which does.
    assert ('&quot;' in body and '&#39;' in body) or 'return escAttr(s)' in body, body
