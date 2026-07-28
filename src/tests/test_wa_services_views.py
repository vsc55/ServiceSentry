#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Services can be read four ways, and all four agree about what a service is.

Services is a CONTROL surface, so its views differ in what they put in the subject position.
The card grid puts the service there and everything about it in view at once — which is right
until there are instances, because then each one is only visible inside the card of the
service it belongs to. The fleet can be read one service at a time and never as a whole, and
that hides the two failures a multi-container install has and a single-container one does not:
a follower that stopped reporting while the leader carries on (the service still says RUNNING
and the redundancy is quietly gone), and a container left behind on an older version, which no
per-service card can show because drift is only visible when the versions sit side by side.

What must not differ is what a service MEANS. The state vocabulary, the badge, the instance
row and — most of all — the actions a user may take are decided once and composed by every
view. A view that assembled its own buttons would be a view free to offer Stop to somebody who
may not press it, and that is not a styling bug.
"""

import io
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVC = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'services')
VIEWS = os.path.join(SVC, '_views.html')
RENDER = os.path.join(SVC, '_render.html')
VIEW_FILES = {
    'table': os.path.join(SVC, '_view_table.html'),
    'fleet': os.path.join(SVC, '_view_fleet.html'),
    'strip': os.path.join(SVC, '_view_strip.html'),
}


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _strip_comments(js: str) -> str:
    """Code only. A guard that reads the prose trips over the comment explaining the rule it
    is checking, and every file here carries one."""
    js = re.sub(r'\{#.*?#\}', '', js, flags=re.S)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


class TestTheScanItself:
    """If these fail the guard is broken, not the layout."""

    def test_every_file_is_found(self):
        for p in (VIEWS, RENDER, *VIEW_FILES.values()):
            assert os.path.isfile(p), p

    def test_the_registry_lists_every_view(self):
        src = _strip_comments(_read(VIEWS))
        reg = src[src.index('const SERVICE_VIEWS'):]
        reg = reg[:reg.index('];')]
        for vid in ('cards', 'table', 'fleet', 'strip'):
            assert f"id: '{vid}'" in reg, f'{vid} is not in the registry'

    def test_the_bundle_includes_them_in_order(self):
        """The registry names render functions as STRINGS because the view files are
        concatenated after it. If a file is not included, its view silently falls back."""
        js = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                '_js_sections.html'))
        i_views = js.index('services/_views.html')
        for f in ('services/_view_table.html', 'services/_view_fleet.html',
                  'services/_view_strip.html'):
            assert f in js, f'{f} is never included'
            assert js.index(f) > i_views, f'{f} is included before the registry it registers in'


class TestAViewIsChromeOnly:
    """The rule: a view decides layout, never meaning."""

    def test_no_view_builds_its_own_action_buttons(self):
        """The one that is not cosmetic. `services_control` is checked inside
        _svcActionsHtml; a view that assembled its own buttons would be free to offer Stop to
        a user who may not press it."""
        for name, path in VIEW_FILES.items():
            body = _strip_comments(_read(path))
            assert 'servicesControl(' not in body, (
                f'{name} wires a control call itself instead of composing _svcActionsHtml')
            assert 'services_control' not in body, (
                f'{name} re-checks the permission — it must be asked in one place')

    def test_the_permission_is_asked_in_exactly_one_place(self):
        src = _strip_comments(_read(RENDER))
        assert src.count("includes('services_control')") == 1

    def test_no_view_invents_a_state_colour(self):
        """`stale` must be one colour everywhere. A view reaching into the table itself is
        free to drift from the badge beside it."""
        for name, path in VIEW_FILES.items():
            body = _strip_comments(_read(path))
            for cls in ("'success'", "'danger'", "'warning'"):
                assert f'_SVC_STATE_CLS[{cls}' not in body, name
            assert 'running:' not in body and 'stopped:' not in body, (
                f'{name} declares its own state vocabulary')

    def test_the_state_badge_comes_from_one_helper(self):
        src = _strip_comments(_read(VIEWS))
        assert 'function _svcStateBadge' in src
        for name in ('table', 'fleet'):
            assert '_svcStateBadge(' in _strip_comments(_read(VIEW_FILES[name])), name


class TestTheHeaderIsDrawnOnce:

    def test_the_views_do_not_draw_it(self):
        """Totals, switcher and Refresh live in the dispatcher so they cannot drift apart
        between layouts, and so a view is only ever responsible for the rows."""
        for name, path in VIEW_FILES.items():
            body = _strip_comments(_read(path))
            assert '_svcViewSwitcher' not in body, name
            assert 'svc_refresh' not in body, name

    def test_the_totals_state_the_whole_set(self):
        """A view that shows less than everything is only safe while the header above it
        cannot understate how much there is — the rule Status follows too."""
        body = _fn(_strip_comments(_read(VIEWS)), '_svcResultsHeader')
        assert '_svcTotals(' in body

    def test_the_totals_count_instances_too(self):
        """On a multi-container install "4 services" and "9 instances" are different facts,
        and the second is the one that moves."""
        body = _fn(_strip_comments(_read(VIEWS)), '_svcTotals')
        assert '_svcAllInstances(' in body


class TestSwitchingViewCostsNothing:

    def test_it_redraws_instead_of_refetching(self):
        """Every view reads the same payload. Fetching to answer a question about
        presentation would also race the poll timer that was about to fetch anyway."""
        body = _fn(_strip_comments(_read(VIEWS)), 'setServicesView')
        assert '_svcDrawBody()' in body
        assert 'apiGet' not in body

    def test_the_payload_is_kept(self):
        src = _strip_comments(_read(RENDER))
        assert '_svcLastData = resp.services' in src

    def test_the_choice_is_remembered(self):
        src = _strip_comments(_read(VIEWS))
        assert "localStorage.setItem(_SVC_VIEW_KEY" in src
        assert "localStorage.getItem(_SVC_VIEW_KEY" in src


class TestTheFleetViewIsThePoint:
    """The pivot the card grid cannot do: the instance in the subject position."""

    def test_it_reads_every_instance_across_every_service(self):
        body = _strip_comments(_read(VIEW_FILES['fleet']))
        assert '_svcAllInstances(' in body

    def test_it_offers_no_start_or_stop(self):
        """Those act on a SERVICE, and this page is not showing services. A button per row
        would invite pressing it against the row you happen to be looking at."""
        body = _strip_comments(_read(VIEW_FILES['fleet']))
        assert '_svcActionsHtml' not in body

    def test_a_service_with_no_leader_is_not_called_standby(self):
        """An active-active service has no leader at all; saying "standby" would invent a
        hierarchy it does not have. The backend publishes `leader` only where it applies."""
        body = _strip_comments(_read(VIEW_FILES['fleet']))
        assert "typeof lv === 'boolean'" in body

    def test_version_drift_is_computed_across_the_fleet(self):
        """It is a fact about the whole set, not about any row — with one version there is
        nothing to say, and no row can know that on its own."""
        body = _strip_comments(_read(VIEW_FILES['fleet']))
        assert 'versions.size > 1' in body
        assert 'svc_version_drift' in body

    def test_the_list_does_not_reorder_itself_on_a_timer(self):
        """Reported: rows changed places on every refresh.

        The first version sorted by newest heartbeat, which reads well and is unusable — the
        timestamp is the most volatile field in the row, so instances ticking at similar
        intervals overtook each other on every poll and the table moved under the cursor. A
        list that reorders itself on a timer cannot be read and cannot be clicked.

        So the comparator may not touch a heartbeat. It sorts by state, which changes only
        when something happened (a row jumping to the top IS the news), and then by identity,
        which does not change at all.
        """
        body = _strip_comments(_read(VIEW_FILES['fleet']))
        cmp_start = body.index('all.slice().sort(')
        comparator = body[cmp_start:body.index(';', cmp_start)]
        for volatile in ('last_cycle_at', 'last_seen'):
            assert volatile not in comparator, (
                f'the fleet sorts on {volatile} — that field changes on every poll, so the '
                f'order does too')
        assert '_svcRank(' in comparator, 'the sort no longer floats a problem to the top'
        assert 'localeCompare' in comparator, 'nothing stable breaks the tie'

    def test_the_rank_is_not_the_colour_vocabulary(self):
        """Only three ranks matter for an order — a problem, a maybe, and the rest. The badge
        keeps the full vocabulary; `external` is not worse than `stopped` in any way worth
        reordering a table for."""
        src = _strip_comments(_read(VIEWS))
        rank = src[src.index('const _SVC_RANK'):]
        rank = rank[:rank.index('};') + 2]
        assert 'down' in rank and 'stale' in rank
        assert 'external' not in rank and 'embedded' not in rank


class TestSilenceIsNotFreshness:

    def test_never_reported_is_not_drawn_as_a_time(self):
        """`_svcLastSeen` returns null for a service with no instances, which is a different
        statement from "long ago" and must not be rendered as if it were."""
        src = _strip_comments(_read(VIEWS))
        assert "return ts ? _svcAgo(ts) : '—';" in src
        body = _fn(src, '_svcLastSeen')
        assert 'return newest' in body and 'null' in body


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for vid in ('cards', 'table', 'fleet', 'strip'):
                assert f"'svc_view_{vid}':" in src, f'{lang} does not name the {vid} view'

    def test_every_column_is_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for col in ('service', 'state', 'last', 'host', 'role', 'mode', 'version',
                        'detail', 'actions'):
                assert f"'svc_col_{col}':" in src, f'{lang} does not name column {col}'
