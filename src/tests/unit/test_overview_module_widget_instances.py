#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A module widget can be added more than once, and each copy is configured on its own.

One card cannot answer "how is Microsoft 365" — the question is really several: how full is
the storage, how much of the directory registered MFA, how close are the licences to running
out. Those are different scopes of the same widget, and wanting two of them on screen at the
same time is the normal case rather than an exotic one.

The mechanism for that was already built and never turned on: instance ids carry a ``:N``
suffix, ``mws``/``mwlvl`` are stored per instance, and the add bar keeps offering a widget
whose declaration says ``multi``. What was missing was the declaration — and, once two
instances of one kind exist, a reason to tell them apart at a glance, which is the ring.

The ring is the same bargain as everywhere else in this codebase: the MODULE says which two
measurements are a fraction worth drawing and hands the numbers over already divided; the
core divides nothing and knows no metric names. What the core decides is where it goes and
what colour it is — and the colour comes from the entry's own state, so a card the module
called a warning cannot carry a green ring.


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_overview_module_widget_instances.py`` lives in
``tests/meta/test_overview_module_widget_instances.py``."""

import os
import re
import sys
from tests.helpers import _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
OV = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'overview')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _strip_comments(js: str) -> str:
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)




class TestEachInstanceKeepsItsOwnSettings:

    def test_the_three_settings_are_saved_per_instance(self):
        src = _strip_comments(_read(os.path.join(OV, '_layout.html')))
        for key in ('mws', 'mwlvl', 'mwchart'):
            assert f'el.dataset.{key} ?' in src, f'{key} is not persisted with the layout'

    def test_a_saved_default_layout_keeps_them(self):
        """An admin publishing a default hands everyone the arrangement AND the
        configuration. Dropping these would give them the right boxes showing the wrong
        things — and it used to."""
        from lib.core.overview.service import normalize_layout, INSTANCE_KEYS
        out = normalize_layout([{'id': 'mw_m365_table:1', 'cols': 4, 'h': 340,
                                 'mws': 'licenses', 'mwlvl': 'warn', 'mwchart': '1'}])
        assert out[0]['mws'] == 'licenses'
        assert out[0]['mwlvl'] == 'warn'
        assert out[0]['mwchart'] == '1'
        assert set(INSTANCE_KEYS) == {'mws', 'mwlvl', 'mwchart'}

    def test_absent_settings_are_not_invented(self):
        """A widget with no scope must not come back carrying an empty one — '' and absent
        mean the same thing to the reader but not to a diff of two layouts."""
        from lib.core.overview.service import normalize_layout
        out = normalize_layout([{'id': 'mw_m365_table:1', 'cols': 4}])
        assert 'mws' not in out[0] and 'mwchart' not in out[0]

    def test_junk_entries_are_still_dropped(self):
        from lib.core.overview.service import normalize_layout
        assert normalize_layout(['nope', {'cols': 2}, None]) == []
        assert normalize_layout('not a list') == []


class TestTheModuleSuppliesTheRatio:

    @staticmethod
    def _widget(status: dict) -> dict:
        from watchfuls.m365 import Watchful
        return Watchful.overview_widget({}, status, 'en_EN')

    def test_a_kind_that_measures_a_fraction_carries_one(self):
        out = self._widget({'k/securescore': {'status': True,
                                              'other_data': {'score': 61, 'max': 100}}})
        e = next(x for x in out['entries'] if x['id'] == 'securescore')
        assert e['chart'] == {'used': 61.0, 'total': 100.0, 'pct': 61.0}

    def test_a_kind_that_measures_nothing_of_the_sort_carries_none(self):
        out = self._widget({'k/health': {'status': True,
                                         'other_data': {'service': 'Exchange'}}})
        e = next(x for x in out['entries'] if x['id'] == 'health')
        assert 'chart' not in e

    def test_a_missing_total_produces_no_ratio_rather_than_a_zero(self):
        """The failure this guards: a ring drawn from a missing total is a confident-looking
        0%, and a card is the worst place to put one."""
        out = self._widget({'k/onedrive': {'status': True,
                                           'other_data': {'used_bytes': 5}}})   # no limit
        e = next(x for x in out['entries'] if x['id'] == 'onedrive')
        assert 'chart' not in e

    def test_the_ratio_is_summed_across_that_kind(self):
        """A card is an aggregate by nature — it already says N of M OK — so the fraction it
        shows is the same kind of statement. (The module PAGE draws one ring per row instead,
        on purpose: there, summing the sites would hide which one is filling up.)"""
        out = self._widget({
            'k/site/a': {'status': True, 'other_data': {'used_bytes': 30, 'total_bytes': 100}},
            'k/site/b': {'status': True, 'other_data': {'used_bytes': 10, 'total_bytes': 100}},
        })
        e = next(x for x in out['entries'] if x['id'] == 'site')
        assert e['chart']['used'] == 40.0 and e['chart']['total'] == 200.0
        assert e['chart']['pct'] == 20.0

    def test_one_incomplete_result_disqualifies_the_whole_kind(self):
        """Summing what is present and ignoring what is not would report a fuller-looking
        fraction than the truth, which is the direction that matters."""
        out = self._widget({
            'k/site/a': {'status': True, 'other_data': {'used_bytes': 30, 'total_bytes': 100}},
            'k/site/b': {'status': True, 'other_data': {'used_bytes': 10}},
        })
        e = next(x for x in out['entries'] if x['id'] == 'site')
        assert 'chart' not in e

    def test_each_row_carries_its_own(self):
        """The single-kind view lists the results; there the per-row fraction is the useful
        one, for the same reason the page draws it per row."""
        out = self._widget({
            'k/site/a': {'status': True, 'other_data': {'used_bytes': 90, 'total_bytes': 100,
                                                        'name': 'A'}},
            'k/site/b': {'status': True, 'other_data': {'used_bytes': 10, 'total_bytes': 100,
                                                        'name': 'B'}},
        })
        e = next(x for x in out['entries'] if x['id'] == 'site')
        pcts = sorted(r['chart']['pct'] for r in e['rows'])
        assert pcts == [10.0, 90.0]


class TestTheCoreOnlyDraws:

    def _js(self) -> str:
        return _strip_comments(_read(os.path.join(OV, '_widgets.html')))

    def test_no_metric_name_reaches_the_core(self):
        """Which measurements are a fraction is the module's answer. The day the core knows
        that `used_bytes` exists is the day adding a module means editing the core."""
        js = self._js()
        for name in ('used_bytes', 'limit_bytes', 'total_bytes', 'assigned', 'registered',
                     'securescore', 'licensed'):
            assert name not in js, f'the core names {name}'

    def test_it_refuses_to_draw_without_a_total(self):
        js = self._js()
        body = js[js.index('function _dwMwDonut'):]
        assert 'chart.total > 0' in body[:400]

    def test_the_colour_comes_from_the_state_not_from_the_percentage(self):
        """Two signals disagreeing about one record is worse than either being wrong alone:
        a card the module called a warning must not carry a green ring."""
        js = self._js()
        body = js[js.index('function _dwMwDonut'):js.index('function _dwMwWantsChart')]
        assert "state === 'error'" in body and "state === 'warn'" in body
        assert not re.search(r'pct\s*(>=|>)\s*\d', body), (
            'the ring is picking its own colour from a threshold')

    def test_the_aggregate_scope_draws_none(self):
        """Storage, a score, licences and MFA coverage cannot be added together; a ring there
        would be a number with no question behind it."""
        js = self._js()
        seg = js[js.index("if (scope === 'sum')"):]
        seg = seg[:seg.index('if (scope)')]
        assert 'chart' not in seg

    def test_the_ring_is_opt_in_per_instance(self):
        js = self._js()
        assert '_dwMwWantsChart(id, item)' in js
        layout = _strip_comments(_read(os.path.join(OV, '_layout.html')))
        assert 'function _dwSetModuleChart' in layout

    def test_it_needs_no_charting_library(self):
        """A ring does not justify a dependency, and the CSP forbids fetching one."""
        js = self._js()
        body = js[js.index('function _dwMwDonut'):js.index('function _dwMwWantsChart')]
        assert '<svg' in body and 'stroke-dasharray' in body


class TestTheLabelExists:

    def test_the_toggle_is_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            assert "'dw_mw_chart':" in src, f'{lang} does not name the ring toggle'


class TestEveryWidgetDeclaresItsPermissionGate:
    """`widget_allowed` treats a widget with no declared gate as open to any logged-in user.

    That is a fail-OPEN default on the one endpoint that serves widget data
    (`/api/v1/overview/widget/<id>`), and the gate is declared by the widget itself — core
    or module. Today all of them declare one, which is why this is a guard and not a fix:
    the next widget to forget it would be readable by everybody, and nothing would say so.

    Found while auditing `lib/core` on 2026-08-15. The default is left alone deliberately —
    changing it would break a module mid-upgrade with a blank card and no explanation, while
    a red test names the widget and the file.
    """

    def test_no_widget_is_served_without_a_gate(self):
        from lib.core.overview.discovery import discover_overview_widgets   # noqa: PLC0415
        naked = []
        for w in discover_overview_widgets():
            perms = w.get('perms') or {}
            if not (perms.get('any') or perms.get('prefix')):
                naked.append(w.get('id'))
        assert not naked, (
            f'these widgets declare no permission gate, so any logged-in user can read '
            f'their data: {naked}. Add perms.any or perms.prefix to the descriptor.')

    def test_the_scan_actually_sees_widgets(self):
        """Guard the guard: an empty discovery would make the test above pass vacuously."""
        from lib.core.overview.discovery import discover_overview_widgets   # noqa: PLC0415
        assert len(discover_overview_widgets()) > 10
