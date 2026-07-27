#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The breadcrumb names the path you would follow to reach the section.

It read the active sidebar item and its sub-item and stopped there, so a section nested two
levels deep announced itself as "Infrastructure / Servers" and one nested one level deep as
plain "Services" — the same title a first-level section gets. Both dropped the group they
live in, which is the part that tells you *where you are*: you find Servers by opening
System, then Infrastructure. A path missing its first step is not a path.

The rule has two halves and the second matters as much:

* a section inside a sidebar group is named by its whole chain — "System / Services",
  "System / Infrastructure / Servers";
* a first-level section (Overview, History, Syslog…) belongs to no group and is just itself.
  Prefixing it would name a place it does not live in.

These are static guards over the markup and the builder, in the same spirit as the rest of
the panel's UI tests: what is pinned is that the group is read from whichever group actually
contains the active item, and that a section outside every group gets no prefix.
"""

import io
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
WIRING = os.path.join(TPL, 'partials', 'init', '_sidebar.html')
MARKUP = os.path.join(TPL, 'partials', '_sidebar.html')


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _fn(src: str, name: str) -> str:
    m = re.search(r'^function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}', src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


class TestTheScanItself:

    def test_the_builder_is_found(self):
        assert _fn(_read(WIRING), '_sbUpdateBreadcrumb')

    def test_the_sidebar_has_groups(self):
        """The whole fix rests on the group being a real element with a label."""
        src = _read(MARKUP)
        assert 'ss-sb-group' in src and 'ss-sb-parent' in src


class TestThePathStartsAtTheGroup:

    def test_the_group_is_part_of_the_crumb(self):
        body = _fn(_read(WIRING), '_sbUpdateBreadcrumb')
        assert 'ss-sb-group' in body, (
            'the breadcrumb ignores the group again, so a nested section announces itself '
            'with the same shape as a first-level one')

    def test_it_is_the_group_containing_the_active_item(self):
        """Read from the active item upwards — not "the first group in the sidebar", which
        would be right by luck while there is only one."""
        body = _fn(_read(WIRING), '_sbUpdateBreadcrumb')
        assert re.search(r"closest\('\.ss-sb-group'\)", body), \
            'the group is not resolved from the active item'

    def test_it_takes_that_groups_own_header(self):
        """`:scope >` matters: a nested group would otherwise contribute its child's header."""
        body = _fn(_read(WIRING), '_sbUpdateBreadcrumb')
        assert ':scope > .ss-sb-parent' in body

    def test_the_group_comes_first(self):
        body = _fn(_read(WIRING), '_sbUpdateBreadcrumb')
        m = re.search(r'const parts = \[([^\]]*)\]', body)
        assert m, 'the crumb parts are no longer assembled as a list'
        order = [p.strip() for p in m.group(1).split(',')]
        assert order[0].startswith('_txt(group')
        assert order[1].startswith('_txt(top')
        assert order[2].startswith('_txt(sub')


class TestAFirstLevelSectionIsJustItself:

    def test_the_standalone_sections_are_outside_every_group(self):
        """Overview / History / Syslog are rendered before the group, so `closest` finds
        nothing and they keep their bare name. If they ever move inside one, they would
        silently acquire a prefix — this is what would notice."""
        src = _read(MARKUP)
        head = src.split('ss-sb-group', 1)[0]
        assert 'standalone_specs' in head, \
            'the first-level sections moved; they would now inherit a group prefix'

    def test_missing_parts_are_dropped_not_rendered_empty(self):
        """`filter(Boolean)` is what keeps a section with no group from starting with a
        separator."""
        body = _fn(_read(WIRING), '_sbUpdateBreadcrumb')
        assert '.filter(Boolean)' in body


class TestTheGroupHeaderIsNeverTheSection:

    def test_the_parent_link_is_excluded_from_the_item_lookup(self):
        """The group header carries `.ss-sb-item` too. Without excluding it, an active group
        header would be read as the section and the crumb would repeat it."""
        body = _fn(_read(WIRING), '_sbUpdateBreadcrumb')
        m = re.search(r"const top = document\.querySelector\(\s*'([^']*)'", body)
        assert m, 'the active-item lookup changed shape'
        assert ':not(.ss-sb-parent)' in m.group(1)

    def test_the_separator_is_still_escaped_markup(self):
        """The labels come from the DOM but are user-visible strings; they are escaped, and
        only the separator is markup."""
        body = _fn(_read(WIRING), '_sbUpdateBreadcrumb')
        assert 'esc(p)' in body
