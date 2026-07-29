#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Syslog can be read three ways, and all three are looking at the same page.

This is the one section whose rows arrive already filtered, sorted and paged BY THE SERVER:
what is on screen is one page of a query, not a slice of something the browser holds. That
changes what a view may do — every one of them keeps the pager, because here it is the
control that LOADS the next rows, not a presentation trick — and it changes what a count
means, because the store can hold millions of rows and the browser has a few dozen.

Two shapes the table cannot be:

* a STREAM. Reading a log in a grid means re-reading five column headers per line to follow
  one machine's story, and spends a third of the width on chrome.
* PATTERNS. Five hundred lines are usually a dozen distinct messages repeated, and the one
  that matters is often the one that appears twice.

The guards below are mostly about the second: it counts, so it must say what it counted over,
and the grouping that makes it possible must stay conservative — two different messages
collapsing into one is a worse failure than two similar ones staying apart.
"""

import io
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
SL = os.path.join(TPL, 'partials', 'syslog')
VIEWS = os.path.join(SL, '_views.html')
COLUMNS = os.path.join(SL, '_columns.html')
RENDER = os.path.join(SL, '_render.html')
VIEW_FILES = {
    'stream': os.path.join(SL, '_view_stream.html'),
    'patterns': os.path.join(SL, '_view_patterns.html'),
}


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _strip_comments(js: str) -> str:
    js = re.sub(r'\{#.*?#\}', '', js, flags=re.S)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


class TestTheScanItself:

    def test_every_file_is_found(self):
        for p in (VIEWS, COLUMNS, RENDER, *VIEW_FILES.values()):
            assert os.path.isfile(p), p

    def test_the_registry_lists_every_view(self):
        src = _strip_comments(_read(VIEWS))
        reg = src[src.index('const SYSLOG_VIEWS'):]
        reg = reg[:reg.index('];')]
        for vid in ('table', 'stream', 'patterns'):
            assert f"id: '{vid}'" in reg, f'{vid} is not in the registry'

    def test_the_bundle_includes_them_after_the_registry(self):
        js = _read(os.path.join(TPL, 'partials', '_js_sections.html'))
        i_views = js.index('syslog/_views.html')
        for f in ('syslog/_view_stream.html', 'syslog/_view_patterns.html'):
            assert f in js, f'{f} is never included'
            assert js.index(f) > i_views, f'{f} is included before the registry it registers in'


class TestEveryViewShowsTheSamePage:

    def test_no_view_re_queries_the_store(self):
        """These queries are the expensive ones in the panel. Re-running one to change how
        the same rows are drawn would also race the auto-refresh timer."""
        body = _fn(_strip_comments(_read(VIEWS)), 'setSyslogView')
        assert '_slRenderTable()' in body
        assert '_loadSyslog' not in body and 'apiGet' not in body
        for name, path in VIEW_FILES.items():
            assert 'apiGet' not in _strip_comments(_read(path)), name

    def test_every_view_is_handed_the_loaded_page(self):
        src = _strip_comments(_read(COLUMNS))
        assert '_slViewBody(_slRowsData)' in src

    def test_the_pager_survives_every_view(self):
        """Here the pager is what loads the next rows from the server, not a slice of
        something already in the browser — taking it away would strand the user on page one."""
        body = _fn(_strip_comments(_read(COLUMNS)), '_slRenderTable')
        i_pager = body.index("for (const el of [pagerTop, pagerBot]) if (el) el.style.display = '';")
        i_dispatch = body.index('if (_slView().render)')
        assert i_pager < i_dispatch, 'the alternate views return before the pager is shown'

    def test_the_column_chooser_belongs_to_the_table(self):
        """It is in the section header, which is written once and outside the body — so the
        dispatcher refreshes it, or it would keep offering columns to a view without any."""
        body = _fn(_strip_comments(_read(COLUMNS)), '_slRenderTable')
        assert '_slView().cols' in body
        assert 'sl-col-chooser' in body
        assert 'sl-view-switcher' in body, 'the switcher never repaints its active button'
        assert 'sl-col-chooser' in _read(RENDER) and 'sl-view-switcher' in _read(RENDER)


class TestOneSeverityVocabulary:

    def test_no_view_picks_the_severity_colour_itself(self):
        """`err` is one colour everywhere, including beside the same message in another
        view."""
        for name, path in VIEW_FILES.items():
            body = _strip_comments(_read(path))
            assert '_SYSLOG_SEV_CLS' not in body, f'{name} reaches for the palette itself'
            assert '_slSevBadge(' in body or '_slSevClass(' in body, name

    def test_the_stream_says_the_severity_as_well_as_colours_it(self):
        """Colour alone would leave the stream unreadable to anyone who cannot separate the
        reds from the greys, and it is the view with the least other context."""
        body = _strip_comments(_read(VIEW_FILES['stream']))
        assert '_slSevBadge(m)' in body, 'the severity name is gone from the line'

    def test_the_arrival_time_is_read_the_same_way_everywhere(self):
        """`received_at` is what the store recorded and `ts` is what the sender claimed; a
        device with a wrong clock is common enough that the first is the one to trust."""
        body = _fn(_strip_comments(_read(VIEWS)), '_slWhen')
        assert 'm.received_at ||' in body
        for name, path in VIEW_FILES.items():
            assert 'received_at' not in _strip_comments(_read(path)), \
                f'{name} decides for itself which timestamp to believe'


class TestPatternsCountHonestly:

    def test_it_says_what_it_counted_over(self):
        """The database can hold millions of rows and the browser has one page of them. A
        bare number would be read as "the log"."""
        body = _strip_comments(_read(VIEW_FILES['patterns']))
        assert '_slLoadedHeader(' in body
        header = _fn(_strip_comments(_read(VIEWS)), '_slLoadedHeader')
        assert "tf('sl_of_loaded', n)" in header

    def test_the_loaded_message_names_the_number(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            m = re.search(r"'sl_of_loaded':\s*'([^']*)'", src)
            assert m, lang
            assert '{}' in m.group(1), f'{lang}: sl_of_loaded lost its count'

    def test_the_grouping_never_touches_words(self):
        """It is a reading aid, not an identifier: numbers, addresses, UUIDs, hex blobs and
        quoted strings are replaced, and nothing else. Two different messages collapsing into
        one is a worse failure than two similar ones staying apart."""
        body = _fn(_strip_comments(_read(VIEWS)), '_slPattern')
        assert '‹addr›' in body and '‹n›' in body
        assert '[a-zA-Z]' not in body, 'the pattern rule started rewriting words'

    def test_addresses_are_replaced_before_bare_numbers(self):
        """Order matters: an IPv4 contains digits, so the number rule running first would eat
        it a piece at a time and the pattern would stop matching itself."""
        body = _fn(_strip_comments(_read(VIEWS)), '_slPattern')
        assert body.index('‹addr›') < body.index('‹n›')

    def test_severity_is_part_of_the_key(self):
        """The same text at `err` and at `info` is two different events, and merging them
        would let a warning hide inside chatter."""
        body = _fn(_strip_comments(_read(VIEW_FILES['patterns'])), '_slViewPatterns')
        assert 'm.severity' in body and '_slPattern(m.message)' in body

    def test_the_hosts_are_listed_not_just_counted(self):
        """One message from twelve machines and twelve from one machine are different
        incidents, and a count alone cannot tell them apart."""
        body = _strip_comments(_read(VIEW_FILES['patterns']))
        assert 'g.hosts' in body and '_chipList(' in body

    def test_the_rare_line_is_findable(self):
        """The point of collapsing is that the line which appears twice stops being buried;
        counting them is what makes that visible."""
        body = _strip_comments(_read(VIEW_FILES['patterns']))
        assert 'sl_count_once' in body


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for vid in ('table', 'stream', 'patterns'):
                assert f"'sl_view_{vid}':" in src, f'{lang} does not name the {vid} view'

    def test_the_vocabulary_exists_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for key in ('sl_count_patterns', 'sl_count_once', 'sl_col_count',
                        'sl_col_window', 'sl_of_loaded'):
                assert f"'{key}':" in src, f'{lang} is missing {key}'
