#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The host registry can be read four ways, and two of them are about the fleet.

Servers is the one list where the rows are not the point: what you want from it is a state
of the fleet, and a table gives you that one host at a time. Three things it leaves out:

* how the fleet is RIGHT NOW. There is a status column you can sort by, which answers "which
  host is worst" and never "how many are broken".
* which hosts are not actually being MONITORED. The modules column draws "0/0" and "0/3" in
  the same grey pill: one was never given a check, the other had every check switched off,
  and both mean the fleet is smaller than the list looks. That is how a panel stays green
  while a machine is down.
* what a host IS as one object rather than eight columns you turn on and read left to right.

The two grouped views are SUMMARIES: they are handed every row the filters left standing, not
the page, and they draw no pagination — a count that shrank as you paged would be worse than
no count. The factory learned that mode for this section (`bodyMode: 'summary'`).

And the part that is not cosmetic: Servers is the section with PER-HOST permissions
(`server.<uid>.edit` grants exactly one row), so a view assembling its own buttons would be a
view that forgot the granular case exists. They are built in one place.
"""

import os
import re
from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
SRV = os.path.join(TPL, 'partials', 'servers')
VIEWS = os.path.join(SRV, '_views.html')
LIST = os.path.join(SRV, '_list.html')
FACTORY = os.path.join(TPL, 'partials', 'core', '_list_table.html')
VIEW_FILES = {
    'cards': os.path.join(SRV, '_view_cards.html'),
    'status': os.path.join(SRV, '_view_status.html'),
    'coverage': os.path.join(SRV, '_view_coverage.html'),
}


class TestTheScanItself:

    def test_every_file_is_found(self):
        for p in (VIEWS, LIST, *VIEW_FILES.values()):
            assert os.path.isfile(p), p

    def test_the_registry_lists_every_view(self):
        src = _strip_comments(_read(VIEWS))
        reg = src[src.index('const SERVER_VIEWS'):]
        reg = reg[:reg.index('];')]
        for vid in ('table', 'cards', 'status', 'coverage'):
            assert f"id: '{vid}'" in reg, f'{vid} is not in the registry'

    def test_the_bundle_includes_them_after_the_registry(self):
        js = _read(os.path.join(TPL, 'partials', '_js_sections.html'))
        i_views = js.index('servers/_views.html')
        for f in ('servers/_view_cards.html', 'servers/_view_status.html',
                  'servers/_view_coverage.html'):
            assert f in js, f'{f} is never included'
            assert js.index(f) > i_views, f'{f} is included before the registry it registers in'


class TestPerHostPermissionsAreAskedOnce:
    """The one that is not cosmetic."""

    def test_the_buttons_are_built_in_one_place(self):
        views = _strip_comments(_read(VIEWS))
        assert views.count('function _srvActionsHtml') == 1
        body = _fn(views, '_srvActionsHtml')
        assert '_canEditHost(host.uid)' in body and '_canDeleteHost(host.uid)' in body, \
            'the per-host permission is no longer what decides the buttons'

    def test_the_table_composes_the_same_builder(self):
        src = _strip_comments(_read(LIST))
        assert 'actions: (host, ctx) => _srvActionsHtml(host, ctx)' in src

    def test_no_view_re_derives_the_permission(self):
        """`server.<uid>.edit` grants exactly one row. A view that asked `servers_edit`
        instead would hide the buttons from somebody who may press them on that host — or,
        the other way round, show them everywhere."""
        for name, path in VIEW_FILES.items():
            body = _strip_comments(_read(path))
            assert '_canEditHost' not in body, f'{name} re-checks the per-host permission'
            assert 'currentUser.permissions' not in body, name
            assert 'openEditHostModal(' not in body, f'{name} wires the edit itself'
            assert 'deleteHost(' not in body, f'{name} wires the delete itself'


class TestASummaryIsNotAPage:

    def test_the_factory_knows_what_a_summary_is(self):
        """'cards' is an alternate body over the same page; 'summary' is a body describing
        the whole filtered set. The difference is the row list it is handed and whether the
        pagination bands are drawn at all."""
        # The factory's render() is nested inside createListTable, so this reads the file.
        src = _strip_comments(_read(FACTORY))
        assert "const summary = mode === 'summary'" in src
        assert 'summary ? rows : rows.slice(' in src
        assert 'spec.cardsBody(pageRows, ctx, rows)' in src
        assert "const pagination = summary ? ''" in src

    def test_the_grouped_views_declare_it(self):
        src = _strip_comments(_read(VIEWS))
        reg = src[src.index('const SERVER_VIEWS'):]
        reg = reg[:reg.index('];')]
        for line in reg.splitlines():
            for vid in ('status', 'coverage'):
                if f"id: '{vid}'" in line:
                    assert "mode: 'summary'" in line, f'{vid} is drawn as a page again'
            if "id: 'cards'" in line:
                assert "mode: 'cards'" in line

    def test_a_summary_is_handed_every_filtered_row(self):
        body = _fn(_strip_comments(_read(VIEWS)), '_srvViewBody')
        assert "v.mode === 'summary' ? allRows : pageRows" in body
        src = _strip_comments(_read(LIST))
        assert 'cardsBody: (rows, ctx, all) => _srvViewBody(rows, ctx, all)' in src

    def test_both_summaries_state_the_whole_fleet(self):
        """A view showing three groups must never suggest the fleet is three hosts."""
        for name in ('status', 'coverage'):
            body = _strip_comments(_read(VIEW_FILES[name]))
            assert '_summaryHeader(' in body, name
            assert "_summaryChip('bi-hdd-network', t('srv_count_hosts'), hosts.length)" in body, name

    def test_the_column_chooser_belongs_to_the_table(self):
        src = _strip_comments(_read(LIST))
        assert "showChooser: mode => mode === 'table'" in src


class TestOneStatusVocabulary:

    def test_no_view_paints_its_own_status(self):
        """Maintenance is orange and not yellow, everywhere. A view reaching for the palette
        itself is free to make the same host look like two different states in two views of
        the same page."""
        for name, path in VIEW_FILES.items():
            body = _strip_comments(_read(path))
            assert 'text-bg-success' not in body or name != 'cards', name
            assert '#fd7e14' not in body or name in ('cards', 'status'), name
        for name in ('cards', 'status', 'coverage'):
            body = _strip_comments(_read(VIEW_FILES[name]))
            if name != 'status':
                assert '_srvStatusBadge(' in body, f'{name} no longer composes the shared badge'

    def test_no_checks_is_not_a_fifth_state(self):
        """"We do not know how this machine is" is not a shade of "fine". It gets its own
        group rather than a colour beside ok/warning/error."""
        src = _strip_comments(_read(VIEWS))
        assert "const _SRV_STATES = ['error', 'warning', 'maintenance', 'ok', '']" in src
        assert 'srv_status_unknown' in src

    def test_the_worst_group_leads(self):
        body = _fn(_strip_comments(_read(VIEW_FILES['status'])), '_srvViewStatus')
        assert '_SRV_STATES' in body, 'the group order is no longer the shared one'

    def test_an_empty_error_group_is_not_drawn(self):
        """…and the header still states the total, which is what makes the absence readable
        instead of ambiguous."""
        body = _strip_comments(_read(VIEW_FILES['status']))
        assert 'filter(s => (by.get(s) || []).length)' in body
        assert 'srv_all_healthy' in body


class TestCoverageHasThreeAnswers:

    def test_never_checked_and_all_disabled_are_not_the_same(self):
        """0/0 was never given a check; 0/3 had every check switched off, which is worse
        because the row looks configured. The table draws both in the same grey pill."""
        body = _fn(_strip_comments(_read(VIEWS)), '_srvCoverage')
        assert "return 'none'" in body and "'inactive'" in body and "'ok'" in body
        assert 'modules_total' in body and 'modules_active' in body

    def test_the_gaps_lead(self):
        body = _strip_comments(_read(VIEW_FILES['coverage']))
        assert "['none', 'inactive', 'ok']" in body

    def test_the_pill_always_shows_both_numbers(self):
        """"3" alone cannot say whether the other two were never added or were turned off."""
        body = _fn(_strip_comments(_read(VIEWS)), '_srvModulesPill')
        assert '${act}/${tot}' in body

    def test_the_ratio_names_both_numbers(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            m = re.search(r"'srv_cov_ratio':\s*'([^']*)'", src)
            assert m, lang
            assert m.group(1).count('{}') == 2, f'{lang}: srv_cov_ratio lost a number'


class TestSwitchingViewIsPresentationOnly:

    def test_it_redraws_instead_of_refetching(self):
        body = _fn(_strip_comments(_read(VIEWS)), 'setServersView')
        assert 'renderServers()' in body
        assert 'apiGet' not in body and 'loadHosts' not in body

    def test_a_selection_is_not_carried_into_a_summary(self):
        """The summaries draw no checkboxes, so it would leave the bulk-delete bar armed over
        rows that are no longer on screen."""
        body = _fn(_strip_comments(_read(VIEWS)), 'setServersView')
        assert '_selectedServers.clear()' in body
        assert "mode === 'summary'" in body

    def test_the_choice_is_remembered_both_ways(self):
        src = _strip_comments(_read(VIEWS))
        assert 'localStorage.setItem(_SRV_VIEW_KEY' in src
        assert 'localStorage.getItem(_SRV_VIEW_KEY' in src
        lst = _strip_comments(_read(LIST))
        assert 'persistExtra: () => ({ view: _srvViewId() })' in lst
        assert 'applyExtra: cfg => _srvApplyView(cfg && cfg.view)' in lst


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for vid in ('table', 'cards', 'status', 'coverage'):
                assert f"'srv_view_{vid}':" in src, f'{lang} does not name the {vid} view'

    def test_the_vocabulary_exists_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for key in ('srv_status_unknown', 'srv_count_hosts', 'srv_all_healthy',
                        'srv_cov_none', 'srv_cov_inactive', 'srv_cov_ok',
                        'srv_cov_none_hint', 'srv_cov_inactive_hint', 'srv_cov_ok_hint',
                        'srv_cov_ratio'):
                assert f"'{key}':" in src, f'{lang} is missing {key}'
