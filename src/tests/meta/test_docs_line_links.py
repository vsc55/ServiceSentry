#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A documentation link that names a line must point at that line.

The docs link into the source with a line anchor — ``[store.py:28](../src/…/store.py#L28)``.
Those are the most useful links in the reference docs and the most fragile thing in them:
**any edit above the target silently shifts it**, and nothing notices.  Two of them were
already off by one after a file was rewritten — harmless-looking, but a reader following
the link lands on the wrong statement and concludes the doc is describing something else.

The checks are mechanical, so they cannot judge whether line 28 is the *right* line — only
that the anchor is internally consistent and lands somewhere real:

* the target file exists;
* the line is inside the file;
* the text's ``:N`` agrees with the anchor's ``#LN`` (the two are written by hand,
  separately, and drifted before);
* the line is not blank — a link that lands on whitespace has certainly rotted.

What it deliberately does not do is forbid line anchors.  They are worth their upkeep;
they just need something watching them.
"""

import io
import os
import re

DOCS = os.path.join(os.path.dirname(
    os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]), 'docs')
ROOT = os.path.dirname(DOCS)

# [text:42](../src/path/to/file.py#L42)  — text and anchor both carry the number.
_LINK_RE = re.compile(r'\[([^\]]+)\]\((\.\./src/[^)#]+)#L(\d+)\)')


def _links():
    """(doc, doc_line, text, target_path, anchor_line) for every line-anchored link."""
    out = []
    for name in sorted(os.listdir(DOCS)):
        if not name.endswith('.md'):
            continue
        path = os.path.join(DOCS, name)
        for i, line in enumerate(io.open(path, encoding='utf-8-sig'), 1):
            for text, rel, num in _LINK_RE.findall(line):
                target = os.path.normpath(os.path.join(DOCS, rel))
                out.append((name, i, text, target, int(num)))
    return out


class TestTheScanItself:
    """If these fail the guard is broken, not the docs."""

    def test_the_docs_directory_exists(self):
        assert os.path.isdir(DOCS), f'no docs/ at {DOCS}'

    def test_links_are_found(self):
        links = _links()
        assert len(links) > 20, (
            f'only {len(links)} line-anchored links matched — the format changed and this '
            f'guard would pass vacuously')


class TestEveryAnchorLands:

    def test_the_target_file_exists(self):
        missing = [f'{d}:{ln} -> {os.path.relpath(t, ROOT)}'
                   for d, ln, _txt, t, _n in _links() if not os.path.isfile(t)]
        assert not missing, 'links to files that do not exist: ' + '; '.join(missing)

    def test_the_line_is_inside_the_file(self):
        bad = []
        for doc, ln, _txt, target, num in _links():
            if not os.path.isfile(target):
                continue                                   # covered above
            total = sum(1 for _ in io.open(target, encoding='utf-8-sig'))
            if num > total:
                bad.append(f'{doc}:{ln} -> {os.path.relpath(target, ROOT)}#L{num} '
                           f'(the file has {total} lines)')
        assert not bad, 'anchors past the end of their file: ' + '; '.join(bad)

    def test_the_line_is_not_blank(self):
        """A link that lands on whitespace has certainly rotted — the statement it named
        moved, and the anchor stayed."""
        bad = []
        for doc, ln, _txt, target, num in _links():
            if not os.path.isfile(target):
                continue
            lines = io.open(target, encoding='utf-8-sig').readlines()
            if num <= len(lines) and not lines[num - 1].strip():
                bad.append(f'{doc}:{ln} -> {os.path.relpath(target, ROOT)}#L{num}')
        assert not bad, 'anchors landing on a blank line: ' + '; '.join(bad)


class TestTextAndAnchorAgree:

    def test_a_link_whose_text_names_a_line_names_the_same_one(self):
        """``[store.py:28](…#L28)`` writes the number twice, by hand. They drifted before:
        a rewrite moved the target and only one of the two was updated."""
        bad = []
        for doc, ln, text, target, num in _links():
            m = re.search(r':(\d+)$', text.strip())
            if m and int(m.group(1)) != num:
                bad.append(f'{doc}:{ln} text says :{m.group(1)} but the anchor is #L{num} '
                           f'({os.path.relpath(target, ROOT)})')
        assert not bad, 'link text and anchor disagree: ' + '; '.join(bad)
