#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Credentials is a section of its own, not a sub-tab of Infrastructure.

It arrived under Infrastructure when the catalogue was reusable SSH identities, and the
comment that justified the move said exactly that. It stopped being true: half the catalogue
is now Entra ID app registrations — reached by tenant, with no host behind them at all — and
the flows built around them (rotate a secret, grant and consent the roles an app is missing)
never touch a machine.

Two structural reasons, beyond the population:

* its neighbours under Infrastructure, Servers and Clusters, are things you MONITOR. A
  credential is not monitored; it is the secret you reach other things WITH.
* its consumers are spread across hosts, modules and providers alike, so hanging it off any
  one of them asserts a belonging that is not real.

Not Access either: that is users, groups, roles and sessions — who may enter the panel.
These are machine identities the panel uses on its way out, and putting them together would
make one word mean two things.

The guards below are static, over the markup and the wiring, like the rest of the panel's UI
tests. What they defend is that the section exists at the top level, that nothing still
points at the retired sub-tab, and that its permission gate did not come along for the ride.
"""

import os
import re
from tests.helpers import _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
SIDEBAR = os.path.join(TPL, 'partials', '_sidebar.html')
DASH = os.path.join(TPL, 'dashboard.html')
PANE = os.path.join(TPL, 'partials', 'credentials', '_pane.html')
SRV_PANE = os.path.join(TPL, 'partials', 'servers', '_pane.html')
FEATURES = os.path.join(TPL, 'partials', 'init', '_table_features.html')
WIRING = os.path.join(TPL, 'partials', 'init', '_wiring.html')
MANIFEST = os.path.join(SRC, 'lib', 'core', 'credentials', 'manifest.py')


def _strip_comments(src: str) -> str:
    """Code only. A guard that reads the prose trips over the comment explaining the very
    rule it checks — and every file here carries one."""
    src = re.sub(r'\{#.*?#\}', '', src, flags=re.S)          # jinja
    src = re.sub(r'<!--.*?-->', '', src, flags=re.S)         # html
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)          # js block
    src = re.sub(r'^\s*//.*$', '', src, flags=re.M)          # js line
    return re.sub(r'^\s*#.*$', '', src, flags=re.M)          # python


class TestTheScanItself:

    def test_every_file_is_found(self):
        for p in (SIDEBAR, DASH, PANE, SRV_PANE, FEATURES, WIRING, MANIFEST):
            assert os.path.isfile(p), p


class TestItIsATopLevelSection:

    def test_the_panel_registry_lists_it(self):
        """The tabs moved out of the sidebar template and into a registry: their ORDER is
        alphabetical by the translated label, and a template cannot sort by a string it has
        not looked up yet. What this guards is unchanged — Credentials is a section of the
        System panel and not a sub-tab of something else."""
        from lib.web_admin.constants import PANEL_TABS       # noqa: PLC0415
        assert any(t['id'] == 'credentials' for t in PANEL_TABS)

    def test_it_declares_no_sub_tabs(self):
        """A section with sub-tabs is a container. This one holds a single list."""
        src = _strip_comments(_read(SIDEBAR))
        subs = re.search(r'set subtabs = \{(.*?)\n\}', src, re.S)
        assert subs, 'subtabs is gone — this guard needs updating'
        assert 'credentials' not in subs.group(1)

    def test_the_pane_exists_and_the_shell_includes_it(self):
        assert 'id="tab-credentials"' in _read(PANE)
        assert 'partials/credentials/_pane.html' in _read(DASH)

    def test_infrastructure_no_longer_carries_it(self):
        src = _strip_comments(_read(SRV_PANE))
        assert 'credentials' not in src, (
            'the Infrastructure pane still holds credentials markup')


class TestNothingStillPointsAtTheOldSubTab:
    """A dead target is worse than a missing one: Bootstrap activates nothing and says
    nothing, so the section simply does not open and there is no error to follow."""

    def test_no_file_targets_the_retired_sub_pane(self):
        for path in (SIDEBAR, DASH, PANE, SRV_PANE, FEATURES, WIRING, MANIFEST):
            assert '#subtab-credentials' not in _strip_comments(_read(path)), path
            assert 'btn-subtab-credentials' not in _strip_comments(_read(path)), path

    def test_the_overview_widget_points_at_the_section(self):
        """It said #tab-access long after the tab had left Access, so clicking the widget
        opened the wrong pane and then hunted for a sub-tab living inside a third one."""
        nav = re.search(r"'nav':\s*\{([^}]*)\}", _strip_comments(_read(MANIFEST)))
        assert nav, 'the credentials widget declares no nav'
        assert "'#tab-credentials'" in nav.group(1)
        assert "'sub'" not in nav.group(1)

    def test_a_stored_sub_tab_from_before_does_not_strand_infrastructure(self):
        """Someone whose last visit left #subtab-credentials saved must still land on a
        visible Infrastructure sub-tab, not on none at all."""
        src = _strip_comments(_read(FEATURES))
        block = src[src.index('_savedInfra'):]
        assert "closest('li')?.style.display !== 'none'" in block
        assert 'btn-subtab-srv-hosts' in block


class TestTheGateTravelledWithIt:

    def test_the_section_is_shown_by_its_own_permissions(self):
        src = _strip_comments(_read(FEATURES))
        assert "getElementById('tab-credentials-li')" in src
        m = re.search(r"tab-credentials-li'\);\s*\n.*?display = (\w+)", src)
        assert m and m.group(1) == 'hasAnyCredential'

    def test_infrastructure_is_no_longer_revealed_by_a_credential_permission(self):
        """Before, holding only credentials_view opened Infrastructure — for its sake. With
        the section gone from there, that would be an empty tab."""
        src = _strip_comments(_read(FEATURES))
        line = re.search(r'serversLi\.style\.display = \(([^)]*)\)', src)
        assert line, 'the Infrastructure gate is gone — this guard needs updating'
        assert 'hasAnyCredential' not in line.group(1)

    def test_it_still_loads_on_access(self):
        """The list is fetched when the section opens, not at boot: a panel that loaded
        every section's data up front would pay for all of them to show one."""
        src = _strip_comments(_read(WIRING))
        assert "getElementById('btn-tab-credentials')" in src
        block = src[src.index("getElementById('btn-tab-credentials')"):]
        assert 'loadCredentials()' in block[:400] and 'renderCredentials()' in block[:400]
