#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A link to a section has to land on a section that exists.

``test_docs_line_links.py`` guards the links that point INTO the source with a line number,
on the argument that they are the most useful links in the reference docs and the most
fragile thing in them. Links between documents — ``[explica-mfa.md](explica-mfa.md#el-alta)``,
and the whole table of contents of ``ref-tests.md`` — are just as fragile and were guarded by
nothing: rename a heading and every link that named it goes quiet. Nothing errors, nothing
404s; the reader lands at the top of the page and assumes they misread the reference.

Two were already broken when this was written — ``explica-web-admin.md`` pointing at a
``#sistema-de-permisos`` that no longer exists, and the ``ref-tests.md`` index still linking
section 81 by a title it lost.

**The slug rule is GitHub's, and getting it approximately right is worse than not writing the
guard.** Both mistakes were made while building this and both are silent:

* collapsing runs of whitespace. GitHub maps EACH space to a hyphen, so
  ``## SCIM 2.0 — [routes.py](…)`` becomes ``scim-20--libprovidersscimroutespy`` with two
  hyphens where the em dash was. Collapse them and every heading of that (very common) shape
  reports as broken — 129 false positives, which is a guard nobody will keep.
* dropping a markdown link's text instead of unwrapping it. The slug comes from what is
  RENDERED, so ``[routes.py](../src/…)`` contributes ``routespy``, not nothing.

Combining marks are kept, which is not decoration: ``## ☁️ m365 — …`` slugs with the
variation selector still in it, and stripping it invents a permanent failure on a link that
works.
"""

import io
import os
import re
import unicodedata

DOCS = os.path.join(os.path.dirname(
    os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]), 'docs')

# [text](file.md#anchor) or [text](#anchor) — the file part is optional (same-document link).
_LINK = re.compile(r'\]\(([a-zA-Z0-9._-]*\.md)?#([^)\s]+)\)')
_HEADING = re.compile(r'^#{1,6}\s+(.+?)\s*$', re.M)
_MD_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')
_INLINE = re.compile(r'`|\*|<[^>]*>')


def _keep(ch: str) -> bool:
    """What GitHub does not throw away: word characters, spaces, hyphens — and combining
    marks, which is how an emoji heading keeps its variation selector."""
    return (ch.isalnum() or ch in '_-' or ch.isspace()
            or unicodedata.category(ch).startswith('M'))


def _slug(heading: str) -> str:
    text = _MD_LINK.sub(lambda m: m.group(1), heading)   # unwrap: keep the rendered text
    text = _INLINE.sub('', text).lower().strip()
    text = ''.join(c for c in text if _keep(c))
    return re.sub(r'\s', '-', text)                      # EACH space, never a run


def _docs() -> dict:
    return {f: io.open(os.path.join(DOCS, f), encoding='utf-8').read()
            for f in sorted(os.listdir(DOCS)) if f.endswith('.md')}


def _anchors() -> dict:
    return {f: {_slug(h) for h in _HEADING.findall(txt)} for f, txt in _docs().items()}


def _links() -> list:
    """`[(source, target_file, anchor)]` for every link into a document in docs/."""
    out = []
    for f, txt in _docs().items():
        for target, anchor in _LINK.findall(txt):
            out.append((f, target or f, anchor))
    return out


class TestTheScanItself:
    """If these fail the guard is broken, not the docs."""

    def test_the_docs_directory_exists(self):
        assert os.path.isdir(DOCS), f'no docs/ at {DOCS}'

    def test_enough_links_matched_to_mean_anything(self):
        assert len(_links()) > 100, (
            f'only {len(_links())} section links matched — the link format changed and this '
            f'guard would pass vacuously')

    def test_the_slug_rule_is_githubs(self):
        """The two mistakes that make this guard useless, pinned as examples."""
        assert _slug('SCIM 2.0 — [lib/providers/scim/routes.py](../src/x.py)') == \
            'scim-20--libprovidersscimroutespy'
        assert _slug('## Quién debe llevar uno'.lstrip('# ')) == 'quién-debe-llevar-uno'
        assert _slug('`code` and **bold**') == 'code-and-bold'


class TestEveryAnchorLands:

    def test_the_target_document_exists(self):
        known = set(_anchors())
        missing = sorted({f'{src} -> {tgt}' for src, tgt, _a in _links() if tgt not in known})
        assert not missing, 'links to documents that do not exist: ' + '; '.join(missing)

    def test_every_anchor_names_a_real_heading(self):
        anchors = _anchors()
        bad = [f'{src} -> {tgt}#{a}' for src, tgt, a in _links()
               if tgt in anchors and a.lower() not in anchors[tgt]]
        assert not bad, ('links to sections that do not exist (a renamed heading leaves the '
                         'reader at the top of the page with no error): ' + '; '.join(bad))
