#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The last two table surfaces: Clusters, and fail2ban's two lists.

**Clusters** exist for redundancy — one check bound to several hosts, so that a machine going
down does not take the check with it. The table lists them and counts their members, which
reads fine and hides the two ways a cluster is a lie:

* one member. A failover pair with nothing to fail over to, and in the table it is a row with
  a "1" where another has a "3".
* several clusters pinned to the same host. Each row looks redundant on its own; they all go
  down together. That is a fact about the intersection of the rows, so no per-cluster view can
  show it — hence the pivot onto the host.

**fail2ban** lists addresses, and an IP is the one kind of row whose interesting fact is
almost never in the row. Forty bans are usually three networks (whoever is knocking rotates
the last octet), and a ban history is asked about repeats — an address banned six times is six
rows scattered through a log sorted by time.

All three new views are summaries: every filtered row, no pagination. A count of "6 bans" that
silently meant "6 on this page" would be worse than no count at all.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
P = os.path.join(TPL, 'partials')
CL_VIEWS = os.path.join(P, 'clusters', '_views.html')
CL_LIST = os.path.join(P, 'clusters', '_list.html')
CL_CARDS = os.path.join(P, 'clusters', '_view_cards.html')
CL_HOSTS = os.path.join(P, 'clusters', '_view_hosts.html')
IPB_VIEWS = os.path.join(P, 'ipban', '_views.html')
IPB_BANS = os.path.join(P, 'ipban', '_bans.html')
IPB_HIST = os.path.join(P, 'ipban', '_history.html')
IPB_NET = os.path.join(P, 'ipban', '_view_networks.html')
IPB_IPS = os.path.join(P, 'ipban', '_view_ips.html')
IPB_WL = os.path.join(P, 'ipban', '_whitelist.html')
IPB_REACH = os.path.join(P, 'ipban', '_view_reach.html')


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
        for p in (CL_VIEWS, CL_LIST, CL_CARDS, CL_HOSTS,
                  IPB_VIEWS, IPB_BANS, IPB_HIST, IPB_NET, IPB_IPS):
            assert os.path.isfile(p), p

    def test_the_registries_list_their_views(self):
        cl = _strip_comments(_read(CL_VIEWS))
        for vid in ('table', 'cards', 'hosts'):
            assert f"id: '{vid}'" in cl, f'clusters: {vid} is not registered'
        ipb = _strip_comments(_read(IPB_VIEWS))
        for const, ids in (('IPBAN_BANS_VIEWS', ('table', 'networks')),
                           ('IPBAN_HIST_VIEWS', ('table', 'ips'))):
            reg = ipb[ipb.index('const ' + const):]
            reg = reg[:reg.index('];')]
            for vid in ids:
                assert f"id: '{vid}'" in reg, f'{const}: {vid} is not registered'

    def test_the_bundle_includes_them_after_their_registries(self):
        js = _read(os.path.join(P, '_js_sections.html'))
        for reg, views in (('clusters/_views.html',
                            ('clusters/_view_cards.html', 'clusters/_view_hosts.html')),
                           ('ipban/_views.html',
                            ('ipban/_view_networks.html', 'ipban/_view_ips.html'))):
            for v in views:
                assert v in js, f'{v} is never included'
                assert js.index(v) > js.index(reg), f'{v} is included before {reg}'


class TestClustersPivotOntoTheHost:

    def test_a_single_member_cluster_is_named(self):
        """It is a failover pair with nothing to fail over to, and the Members column reads
        "1" the same way it reads "3"."""
        # A one-liner, so it is read from the file rather than through _fn (which needs a
        # closing brace at column 0 and would silently swallow whatever follows).
        src = _strip_comments(_read(CL_VIEWS))
        assert 'function _clIsAlone(row) { return _clMembers(row).length < 2; }' in src
        assert 'cl_alone' in _strip_comments(_read(CL_CARDS))
        assert 'cl_count_alone' in _strip_comments(_read(CL_HOSTS))

    def test_the_host_view_counts_the_shared_ones(self):
        """Several clusters on one machine all go down together, and every one of them looks
        redundant on its own row."""
        body = _fn(_strip_comments(_read(CL_HOSTS)), '_clViewHosts')
        assert 'h.clusters.length > 1' in body
        assert 'cl_count_shared' in body

    def test_the_busiest_host_leads(self):
        body = _fn(_strip_comments(_read(CL_HOSTS)), '_clViewHosts')
        assert '(b.clusters.length - a.clusters.length)' in body

    def test_it_offers_no_per_cluster_actions(self):
        """Those act on a CLUSTER and this view is showing hosts; a button per row would
        invite pressing it against the row in front of you."""
        assert '_clActionsHtml' not in _strip_comments(_read(CL_HOSTS))

    def test_the_per_cluster_permission_is_asked_in_one_place(self):
        """`cluster.<uid>.edit` grants exactly one row — the same granular shape as Servers."""
        views = _strip_comments(_read(CL_VIEWS))
        assert views.count('function _clActionsHtml') == 1
        body = _fn(views, '_clActionsHtml')
        assert "_clCan(uid, 'edit')" in body and "_clCan(uid, 'delete')" in body
        assert 'actions: row => _clActionsHtml(row)' in _strip_comments(_read(CL_LIST))

    def test_no_view_invents_the_status(self):
        """A cluster must not look healthy in one view and broken in the one beside it."""
        for name, path in (('cards', CL_CARDS), ('hosts', CL_HOSTS)):
            assert '_clStatusAgg(' not in _strip_comments(_read(path)), \
                f'{name} aggregates the status itself instead of composing the badge'

    def test_unknown_is_not_painted_as_a_state(self):
        """A cluster the daemon has not reported on yet has no state, and green would say it
        has."""
        body = _fn(_strip_comments(_read(CL_VIEWS)), '_clStateBadge')
        assert 'if (!meta) return' in body

    def test_the_summary_is_not_a_page(self):
        src = _strip_comments(_read(CL_VIEWS))
        reg = src[src.index('const CLUSTER_VIEWS'):]
        reg = reg[:reg.index('];')]
        for line in reg.splitlines():
            if "id: 'hosts'" in line:
                assert "mode: 'summary'" in line
        lst = _strip_comments(_read(CL_LIST))
        assert 'bodyMode: () => _clView.mode()' in lst
        assert 'cardsBody: (rows, ctx, all) => _clView.body(rows, ctx, all)' in lst


class TestFail2banGroupsAddresses:

    def test_the_network_rule_is_stated_and_blunt(self):
        """/24 and /64: the two sizes that correlate with "the same person". Deriving a prefix
        from the addresses present would make the grouping change every time a ban expires."""
        body = _fn(_strip_comments(_read(IPB_VIEWS)), '_ipbNetwork')
        assert '/24' in body and '/64' in body

    def test_both_views_use_the_same_arithmetic(self):
        for name, path in (('networks', IPB_NET), ('ips', IPB_IPS)):
            body = _strip_comments(_read(path))
            assert '_ipbNetwork(' in body, name
            assert '.split(\'.\')' not in body, f'{name} does its own address arithmetic'

    def test_the_busiest_network_leads(self):
        body = _fn(_strip_comments(_read(IPB_NET)), '_ipbBansNetworks')
        assert '(b.ips.length - a.ips.length)' in body

    def test_the_addresses_are_listed_not_only_counted(self):
        """Which ones is what you copy into a range ban."""
        body = _strip_comments(_read(IPB_NET))
        assert '_chipList(g.ips' in body and ', 8)' in body

    def test_a_ban_and_its_unban_are_one_incident(self):
        """Counting both ends would turn six bans into twelve rows and "six times" into a
        number about the log rather than about the offender."""
        body = _fn(_strip_comments(_read(IPB_IPS)), '_ipbHistByIp')
        assert "e.event === 'unbanned'" in body
        assert 'a.bans++' in body

    def test_the_repeat_offender_leads(self):
        body = _fn(_strip_comments(_read(IPB_IPS)), '_ipbHistByIp')
        assert '(y.bans - x.bans)' in body
        assert 'ipb_count_repeat' in body

    def test_neither_summary_is_paginated(self):
        for name, path, guard in (('bans', IPB_BANS, "_ipbBansView.is('table')"),
                                  ('history', IPB_HIST, "_ipbHistView.is('table')")):
            src = _strip_comments(_read(path))
            assert f'if (!{guard})' in src, f'{name} still pages its summary'
            assert '.body(sorted, null, sorted)' in src, \
                f'{name} hands the summary something other than every filtered row'

    def test_the_column_chooser_belongs_to_the_table(self):
        for name, path, guard in (('bans', IPB_BANS, "_ipbBansView.is('table')"),
                                  ('history', IPB_HIST, "_ipbHistView.is('table')")):
            src = _strip_comments(_read(path))
            assert f'{guard} ? _buildColChooser' in src, name

    def test_each_table_keeps_its_own_switcher(self):
        """Bans and history are two lists in one section; choosing a view for one must not
        redraw the other into it."""
        src = _strip_comments(_read(IPB_VIEWS))
        assert "createViewState('ss_ipban_bans_view'" in src
        assert "createViewState('ss_ipban_hist_view'" in src


class TestTheWhitelistMeasuresItsHoles:
    """A whitelist entry is a hole, deliberately made, and the table shows neither how big it
    is nor whether another entry already made it."""

    def test_the_reach_view_is_registered_and_wired(self):
        src = _strip_comments(_read(IPB_VIEWS))
        reg = src[src.index('const IPBAN_WL_VIEWS'):]
        reg = reg[:reg.index('];')]
        assert "id: 'reach'" in reg and "mode: 'summary'" in reg
        wl = _strip_comments(_read(IPB_WL))
        assert "if (!_ipbWlView.is('table'))" in wl, 'the summary is still paged'
        assert "_ipbWlView.is('table') ? _buildColChooser" in wl
        assert '_ipbWlView.switcher(' in wl

    def test_the_address_maths_is_unsigned(self):
        """JavaScript's bitwise operators work on SIGNED 32-bit ints, so without `>>> 0` every
        address from 128.0.0.0 up comes out negative — and containment comparisons against it
        silently answer the opposite of the truth."""
        body = _fn(_strip_comments(_read(IPB_REACH)), '_ipbParseV4')
        assert '>>> 0' in body

    def test_ipv6_is_listed_but_not_compared(self):
        """Getting 128-bit arithmetic subtly wrong would mean calling an entry redundant when
        it is the only thing exempting a host. No answer is better than that one."""
        body = _fn(_strip_comments(_read(IPB_REACH)), '_ipbParseV4')
        assert "s.includes(':')" in body and 'return null' in body
        row = _fn(_strip_comments(_read(IPB_REACH)), '_ipbWlReachRow')
        assert 'ipb_reach_unknown' in row, 'an unmeasured entry no longer says so'

    def test_an_unmeasured_entry_is_not_drawn_as_zero(self):
        """"0 addresses" reads as an entry that exempts nothing, which is the opposite of "we
        did not measure this one"."""
        row = _fn(_strip_comments(_read(IPB_REACH)), '_ipbWlReachRow')
        assert "r.net\n" in row or 'r.net' in row
        assert '—' in row

    def test_duplicates_do_not_cover_each_other(self):
        """Two entries naming the same range would each be marked redundant because of the
        other, and deleting "the redundant one" twice removes the rule entirely."""
        body = _fn(_strip_comments(_read(IPB_REACH)), '_ipbWlViewReach')
        assert 'o.net.prefix === r.net.prefix' in body and 'o.i < r.i' in body

    def test_the_widest_entry_leads(self):
        body = _fn(_strip_comments(_read(IPB_REACH)), '_ipbWlViewReach')
        assert 'b.net ? b.net.size : 0' in body

    def test_the_broad_threshold_is_stated_on_screen(self):
        """A badge whose rule nobody can see is a badge nobody can act on."""
        src = _strip_comments(_read(IPB_REACH))
        assert 'const _IPB_BROAD_PREFIX = 24' in src
        assert "tf('ipb_broad_hint', _IPB_BROAD_PREFIX)" in src
        for lang in ('en_EN', 'es_ES'):
            txt = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            m = re.search(r"'ipb_broad_hint':\s*'([^']*)'", txt)
            assert m and '{}' in m.group(1), f'{lang}: the hint no longer names the threshold'


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        keys = ['cl_view_table', 'cl_view_cards', 'cl_view_hosts',
                'ipb_view_table', 'ipb_view_networks', 'ipb_view_ips', 'ipb_view_reach']
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for k in keys:
                assert f"'{k}':" in src, f'{lang} does not name {k}'

    def test_the_vocabulary_exists_in_both_languages(self):
        keys = ['cl_alone', 'cl_count_clusters', 'cl_count_hosts', 'cl_count_alone',
                'cl_count_shared', 'cl_count_orphan', 'cl_col_clusters', 'cl_col_in_clusters',
                'ipb_count_networks', 'ipb_count_clustered', 'ipb_count_repeat',
                'ipb_col_network', 'ipb_col_addresses', 'ipb_col_bans', 'ipb_col_max_level',
                'ipb_col_window', 'ipb_repeat']
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for k in keys:
                assert f"'{k}':" in src, f'{lang} is missing {k}'
