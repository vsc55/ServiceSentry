#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What a device means in the fleet list, decided once — now that the list is Infrastructure's.

The device registry had a list of its own, readable five ways, beside Infrastructure's list of
the same devices with their state. Two lists of one fleet, and the one where devices were added
was not the one where anybody looked at them. The registry's list went into Infrastructure:
its actions, its bulk delete, its "new device" with the imports hanging from it, its class
filter and its coverage view. Its own views of the state and of the classes were not moved —
Infrastructure's board and rail already answer those.

What is guarded here is what came with it and still must not differ:

* Servers is the section with PER-DEVICE permissions (`server.<uid>.edit` grants exactly one
  row), so the buttons are built in one place and the fleet list composes them.
* Coverage — which devices are actually watched — has four answers and not two, and a device
  read through its own connection profiles is watched.
* A summary is handed every filtered row, never one page.
"""

import os
import re
from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
SRV = os.path.join(TPL, 'partials', 'servers')
INFRA = os.path.join(TPL, 'partials', 'infra')
VIEWS = os.path.join(SRV, '_views.html')
LIST = os.path.join(SRV, '_list.html')
COVERAGE = os.path.join(SRV, '_view_coverage.html')
FLEET = os.path.join(INFRA, '_list.html')
FACTORY = os.path.join(TPL, 'partials', 'core', '_list_table.html')


class TestTheRegistryLivesInTheFleet:

    def test_its_own_list_and_views_are_gone(self):
        """One list of the fleet: a second one is a second place for the two to disagree."""
        assert 'createListTable(' not in _strip_comments(_read(LIST))
        for f in ('_view_cards.html', '_view_status.html', '_view_types.html'):
            assert not os.path.exists(os.path.join(SRV, f)), f
        js = _read(os.path.join(TPL, 'partials', '_js_sections.html'))
        assert 'servers/_view_coverage.html' in js
        assert js.index('servers/_view_coverage.html') > js.index('servers/_views.html')

    def test_the_fleet_carries_its_buttons_and_its_bulk_delete(self):
        fleet = _strip_comments(_read(FLEET))
        assert '_serversToolbar(' in fleet, 'nowhere to add a device'
        assert 'selectable: ctx => ctx.canDelete' in fleet
        assert 'bulkBar: (ctx, sel) => _serversBulkBar(ctx.canDelete)' in fleet
        assert 'selected: () => _selectedServers' in fleet
        assert "selectAll: '_infraSelectAll', toggleOne: '_infraToggleOne'" in fleet

    def test_whatever_redrew_the_registry_redraws_the_fleet(self):
        """Saving, cloning and deleting a device all call `renderServers()`. It asks the server
        again: a device just created is not in a list fetched before it existed."""
        body = _fn(_strip_comments(_read(LIST)), 'renderServers')
        assert 'renderInfra()' in body

    def test_a_device_in_the_coverage_opens_its_page(self):
        """«Two devices watched by nothing» is followed by «which ones, and why»."""
        body = _fn(_strip_comments(_read(VIEWS)), '_srvDeviceLine')
        assert 'infraOpen(' in body

    def test_the_toolbar_has_no_second_refresh(self):
        body = _fn(_strip_comments(_read(LIST)), '_serversToolbar')
        assert 'reloadDevices()' not in body and '_devicesNewHtml()' in body


class TestPerDevicePermissionsAreAskedOnce:
    """The one that is not cosmetic."""

    def test_the_buttons_are_built_in_one_place(self):
        views = _strip_comments(_read(VIEWS))
        assert views.count('function _srvActionsHtml') == 1
        body = _fn(views, '_srvActionsHtml')
        assert '_canEditDevice(device.uid)' in body and '_canDeleteDevice(device.uid)' in body, \
            'the per-device permission is no longer what decides the buttons'

    def test_the_fleet_composes_the_same_builder(self):
        body = _fn(_strip_comments(_read(FLEET)), '_infraRowActions')
        assert '_srvActionsHtml(dev, ' in body

    def test_the_coverage_view_does_not_re_derive_the_permission(self):
        """`server.<uid>.edit` grants exactly one row. A view that asked `devices_edit`
        instead would hide the buttons from somebody who may press them on that device — or,
        the other way round, show them everywhere."""
        body = _strip_comments(_read(COVERAGE))
        assert '_canEditDevice' not in body and 'currentUser.permissions' not in body
        assert 'openEditDeviceModal(' not in body and 'deleteDevice(' not in body


class TestASummaryIsNotAPage:

    def test_the_factory_knows_what_a_summary_is(self):
        src = _strip_comments(_read(FACTORY))
        assert "const summary = mode === 'summary'" in src
        assert 'summary ? rows : rows.slice(' in src
        assert 'spec.cardsBody(pageRows, ctx, rows)' in src
        assert "const pagination = summary ? ''" in src

    def test_the_coverage_view_declares_it(self):
        views = _strip_comments(_read(os.path.join(INFRA, '_views.html')))
        line = [l for l in views.splitlines() if "id: 'coverage'" in l][0]
        assert "mode: 'summary'" in line and "render: '_infraCoverageBody'" in line

    def test_it_states_the_whole_fleet(self):
        """A view showing three groups must never suggest the fleet is three devices."""
        body = _strip_comments(_read(COVERAGE))
        assert '_summaryHeader(' in body
        assert "_summaryChip('bi-hdd-network', t('srv_count_devices'), devices.length)" in body

    def test_it_reads_the_registry_record(self):
        """The connection profiles are not in the fleet payload; the registry's record is."""
        body = _fn(_strip_comments(_read(FLEET)), '_infraCoverageBody')
        assert 'devicesData[u]' in body and '_srvViewCoverage(' in body


class TestOneStatusVocabulary:

    def test_the_coverage_composes_the_shared_badge(self):
        assert '_srvStatusBadge(' in _strip_comments(_read(COVERAGE))


class TestCoverageHasFourAnswers:

    def test_never_checked_and_all_disabled_are_not_the_same(self):
        """0/0 was never given a check; 0/3 had every check switched off, which is worse
        because the row looks configured."""
        body = _fn(_strip_comments(_read(VIEWS)), '_srvCoverage')
        for state in ("'none'", "'inactive'", "'ok'", "'profiles'"):
            assert state in body, state
        assert 'modules_total' in body and 'modules_active' in body

    def test_a_device_read_by_its_own_profiles_is_not_unmonitored(self):
        """Reported from the screen: every switch in the rack wore a red "monitored by
        nothing" while the panel was collecting from it every cycle."""
        body = _fn(_strip_comments(_read(VIEWS)), '_srvSampledByProfile')
        assert 'device_profiles' in body, 'nothing looks at what the record assigns'
        assert 'Array.isArray(' in body, (
            'one profile is stored as a string and several as a list; only one shape is read')
        cov = _fn(_strip_comments(_read(VIEWS)), '_srvCoverage')
        assert '_srvSampledByProfile(' in cov, 'the coverage never asks'

    def test_it_names_the_field_and_not_a_protocol(self):
        body = _fn(_strip_comments(_read(VIEWS)), '_srvSampledByProfile')
        for word in ("'snmp'", '"snmp"'):
            assert word not in body, 'a protocol is written into the rule'

    def test_the_gaps_lead(self):
        assert "['none', 'inactive', 'profiles', 'ok']" in _strip_comments(_read(COVERAGE))

    def test_every_answer_has_a_bucket(self):
        body = _strip_comments(_read(COVERAGE))
        assert 'Object.fromEntries(order.map(' in body, (
            'the buckets are written out by hand beside the order')
        assert '|| buckets.none' in body, 'an unknown answer still throws'
        views = _strip_comments(_read(VIEWS))
        declared = set(re.findall(r"^\s{4}(\w+):\s*\{ cls:", views, re.M))
        for k in ('none', 'inactive', 'ok', 'profiles'):
            assert k in declared, f'{k} has no badge'

    def test_the_chip_takes_its_colour_from_the_badge(self):
        body = _strip_comments(_read(COVERAGE))
        assert '_SRV_COVERAGE[k].cls' in body
        assert "k === 'none' ? 'text-bg-danger'" not in body

    def test_the_pill_always_shows_both_numbers(self):
        body = _fn(_strip_comments(_read(VIEWS)), '_srvModulesPill')
        assert '${act}/${tot}' in body

    def test_the_ratio_names_both_numbers(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            m = re.search(r"'srv_cov_ratio':\s*'([^']*)'", src)
            assert m, lang
            assert m.group(1).count('{}') == 2, f'{lang}: srv_cov_ratio lost a number'


class TestTheLabelsExist:

    def test_the_vocabulary_exists_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for key in ('srv_view_coverage', 'srv_count_devices', 'infra_coverage_none',
                        'srv_cov_none', 'srv_cov_inactive', 'srv_cov_ok',
                        'srv_cov_none_hint', 'srv_cov_inactive_hint', 'srv_cov_ok_hint',
                        'srv_cov_ratio'):
                assert f"'{key}':" in src, f'{lang} is missing {key}'
