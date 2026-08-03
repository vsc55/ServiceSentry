#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Users, Roles, Groups and Sessions are four tables over ONE graph.

A user holds a role directly, belongs to groups, and a group grants roles. Each table shows
its own row and the edge leaving it, which means the composition — what an account can
actually DO — is written down nowhere. The Users table has a role column; an account whose
column says "viewer" and which sits in a group mapped to admin IS an admin, and the table
says viewer.

That is the question an access review asks, and the panel could not answer it: you opened
Groups, read member lists, and held the composition in your head. So each section gained the
view that looks at the graph from its own corner — users → effective access, roles → who
holds it, groups → what it grants — and all three read the SAME helpers, because two views
disagreeing about who is an admin is worse than neither existing.

One backend rule is reproduced client-side and these guards pin it: a DISABLED group grants
nothing (`_is_admin_requester` checks `enabled`). Over-reporting access is the one direction
an access review must not be wrong in — it sends you chasing something that is not there and
buries what is.

Sessions is the fourth: one row per session is right for revoking one and wrong for "is
anybody logged in who should not be", where twelve rows can be one person with twelve tabs.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
P = os.path.join(TPL, 'partials')
ACCESS = os.path.join(P, 'access', '_views.html')
UTILS = os.path.join(P, 'core', '_utils.html')
SECTIONS = {
    'users':    (os.path.join(P, 'users', '_views.html'),    os.path.join(P, 'users', '_list.html'),
                 os.path.join(P, 'users', '_view_access.html'),  'USER_VIEWS',    '_usrView'),
    'roles':    (os.path.join(P, 'roles', '_views.html'),    os.path.join(P, 'roles', '_list.html'),
                 os.path.join(P, 'roles', '_view_usage.html'),   'ROLE_VIEWS',    '_rolView'),
    'groups':   (os.path.join(P, 'groups', '_views.html'),   os.path.join(P, 'groups', '_list.html'),
                 os.path.join(P, 'groups', '_view_access.html'), 'GROUP_VIEWS',   '_grpView'),
    'sessions': (os.path.join(P, 'sessions', '_views.html'), os.path.join(P, 'sessions', '_list.html'),
                 os.path.join(P, 'sessions', '_view_users.html'), 'SESSION_VIEWS', '_sesView'),
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
        assert os.path.isfile(ACCESS)
        for name, (views, lst, view, _, _s) in SECTIONS.items():
            for p in (views, lst, view):
                assert os.path.isfile(p), f'{name}: {p}'

    def test_every_registry_has_its_views(self):
        for name, (views, _l, _v, const, _s) in SECTIONS.items():
            src = _strip_comments(_read(views))
            reg = src[src.index('const ' + const):]
            reg = reg[:reg.index('];')]
            assert reg.count("id: '") >= 3, f'{name} lost a view'
            assert "mode: 'summary'" in reg, f'{name} has no summary view'

    def test_the_bundle_loads_the_graph_before_the_sections(self):
        """The three access views call the same helpers; a section loading first would call
        them before they exist."""
        js = _read(os.path.join(P, '_js_sections.html'))
        i_access = js.index('access/_views.html')
        for rel in ('users/_views.html', 'roles/_views.html', 'groups/_views.html',
                    'sessions/_views.html'):
            assert js.index(rel) > i_access, f'{rel} loads before the access graph'

    def test_each_view_file_loads_after_its_registry(self):
        js = _read(os.path.join(P, '_js_sections.html'))
        for rel_reg, rel_view in (('users/_views.html', 'users/_view_access.html'),
                                  ('roles/_views.html', 'roles/_view_usage.html'),
                                  ('groups/_views.html', 'groups/_view_access.html'),
                                  ('sessions/_views.html', 'sessions/_view_users.html')):
            assert js.index(rel_view) > js.index(rel_reg), f'{rel_view} loads too early'


class TestOneGraphNotThree:
    """The composition is computed in one place, or two views disagree about who is admin."""

    def test_membership_is_walked_in_one_place(self):
        access = _strip_comments(_read(ACCESS))
        assert access.count('function _accGroupsOf') == 1
        assert access.count('function _accRolesViaGroups') == 1
        for name in ('users', 'roles', 'groups'):
            body = _strip_comments(_read(SECTIONS[name][2]))
            assert '.members || []).includes(' not in body, (
                f'{name} walks the membership list itself instead of using the shared helper')

    def test_a_disabled_group_grants_nothing(self):
        """The backend skips it (`_is_admin_requester` checks `enabled`). Reporting access the
        server would refuse is the one direction an access review must not be wrong in."""
        body = _fn(_strip_comments(_read(ACCESS)), '_accRolesViaGroups')
        assert 'g.enabled === false' in body and 'continue' in body

    def test_admin_is_recognised_by_its_key_not_its_label(self):
        """An administrator may rename the role; the key is what the backend matches on."""
        body = _fn(_strip_comments(_read(ACCESS)), '_accIsAdminRole')
        assert "=== 'admin'" in body and 'rd.key' in body

    def test_the_three_access_views_read_the_shared_helpers(self):
        # `_accIsAdminRole` is passed to `.some()` in the groups view, so no parenthesis.
        for name, helper in (('users', '_accEffective('),
                             ('roles', '_accUsersOfRole('),
                             ('groups', '_accIsAdminRole')):
            body = _strip_comments(_read(SECTIONS[name][2]))
            assert helper in body, f'{name} no longer reads the shared graph'


class TestUsersShowWhatTheRoleColumnCannot:

    def test_it_separates_direct_from_inherited(self):
        body = _strip_comments(_read(SECTIONS['users'][2]))
        assert 'usr_col_direct' in body and 'usr_col_via_groups' in body

    def test_admin_through_a_group_is_called_out(self):
        """It is the only difference that changes what somebody can do to everything, and the
        Users table has never shown it."""
        body = _strip_comments(_read(SECTIONS['users'][2]))
        assert 'eff.adminViaGroup' in body
        assert 'usr_admin_via_group' in body

    def test_the_warning_counts_only_the_hidden_ones(self):
        """An admin whose role column already says admin is not news; the banner is about the
        ones the table cannot show."""
        body = _fn(_strip_comments(_read(SECTIONS['users'][2])), '_usrViewAccess')
        assert '!r.eff.adminDirect && r.eff.adminViaGroup' in body

    def test_a_disabled_group_is_shown_but_marked(self):
        """It IS how the account is configured — hiding it would misreport the configuration —
        but it grants nothing today, so the row must not read as access the user has."""
        body = _strip_comments(_read(SECTIONS['users'][2]))
        assert 'usr_group_disabled_hint' in body


class TestRolesCountTheirReach:

    def test_reach_is_a_union(self):
        """A user who holds the role directly and is also in a group that grants it must not
        be counted twice, or a role could report more holders than the installation has
        users."""
        body = _fn(_strip_comments(_read(SECTIONS['roles'][2])), '_rolViewUsage')
        assert 'new Set(direct)' in body and 'reach.add(' in body

    def test_a_disabled_group_adds_nobody(self):
        body = _fn(_strip_comments(_read(SECTIONS['roles'][2])), '_rolViewUsage')
        assert 'if (!g.enabled) continue;' in body

    def test_a_role_nobody_holds_is_marked_not_alarmed(self):
        """Dead configuration is worth seeing before an audit asks, and it is not an error."""
        body = _strip_comments(_read(SECTIONS['roles'][2]))
        assert '_accUnusedBadge(' in body and 'rol_unused' in body


class TestGroupsSayWhatTheyDoToday:

    def test_the_three_idle_states_are_distinguished(self):
        """Disabled, no roles, and no members are three different reasons a group does
        nothing, and the table's separate columns can only be read as a pair of numbers."""
        body = _fn(_strip_comments(_read(SECTIONS['groups'][2])), '_grpAccessRow')
        for key in ('grp_effect_disabled', 'grp_effect_no_roles', 'grp_effect_no_members',
                    'grp_effect_grants'):
            assert key in body, key

    def test_admin_granting_groups_lead(self):
        """Membership of one is the strongest thing on this page, and it is granted from a
        different screen than the role it implies."""
        body = _fn(_strip_comments(_read(SECTIONS['groups'][2])), '_grpViewAccess')
        assert 'rank' in body and 'r.admin ? 0' in body


class TestSessionsPerUser:

    def test_it_counts_addresses_and_lists_them(self):
        """Several sessions from one address is somebody working; the same account from four
        addresses is a question — and which four is what answers it."""
        body = _strip_comments(_read(SECTIONS['sessions'][2]))
        assert 'a.ips' in body and 'ses_count_multi_ip' in body

    def test_the_busiest_account_leads(self):
        body = _fn(_strip_comments(_read(SECTIONS['sessions'][2])), '_sesViewUsers')
        assert '(y.n - x.n)' in body


class TestTheSharedViewState:
    """Four sections were about to copy the same twenty lines of "read localStorage, validate
    against the registry, fall back to the first view"."""

    def test_the_factory_exists_and_validates(self):
        body = _fn(_strip_comments(_read(UTILS)), 'createViewState')
        assert 'views.some(v => v.id === id)' in body
        assert 'views[0].id' in body, 'an unknown stored id no longer falls back'
        assert "v.mode === 'summary' ? allRows : pageRows" in body

    def test_every_access_section_uses_it(self):
        for name, (views, _l, _v, const, state) in SECTIONS.items():
            src = _strip_comments(_read(views))
            assert f'createViewState(' in src, f'{name} rolls its own view state again'
            assert f'const {state} = createViewState(' in src, name

    def test_each_list_is_wired_to_its_state(self):
        for name, (_vw, lst, _v, _c, state) in SECTIONS.items():
            src = _strip_comments(_read(lst))
            assert f'bodyMode: () => {state}.mode()' in src, name
            assert f'{state}.body(' in src, name
            assert f'{state}.switcher(' in src, name
            assert f'persistExtra: () => ({{ view: {state}.id() }})' in src, name
            assert f'applyExtra: cfg => {state}.apply(cfg && cfg.view)' in src, name

    def test_the_card_views_keep_the_id_the_toggle_used(self):
        """These four had a card/table toggle before they had a switcher, and the stored value
        was 'card'. Renaming the id would silently reset everybody to the table."""
        for name in ('users', 'roles', 'groups', 'sessions'):
            src = _strip_comments(_read(SECTIONS[name][0]))
            assert "id: 'card'," in src, f'{name} renamed its card view'

    def test_the_old_toggle_names_still_resolve(self):
        """Anything still calling _setUsersView must not hit a hole."""
        for name, fn in (('users', '_setUsersView'), ('roles', '_setRolesView'),
                         ('groups', '_setGroupsView'), ('sessions', '_setSessionsView')):
            src = _strip_comments(_read(SECTIONS[name][1]))
            assert f'function {fn}(' in src, f'{name}: {fn} is gone'

    def test_the_persistence_layer_has_no_view_variables_left(self):
        """It used to reach for `_sessionsViewMode` by name; the tables own their preferences
        now (persistExtra / applyExtra)."""
        src = _strip_comments(_read(os.path.join(P, 'init', '_persistence.html')))
        assert 'ViewMode' not in src


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        keys = ['usr_view_table', 'usr_view_cards', 'usr_view_access',
                'rol_view_table', 'rol_view_cards', 'rol_view_usage',
                'grp_view_table', 'grp_view_cards', 'grp_view_access',
                'ses_view_table', 'ses_view_cards', 'ses_view_users']
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for k in keys:
                assert f"'{k}':" in src, f'{lang} does not name {k}'

    def test_the_vocabulary_exists_in_both_languages(self):
        keys = ['usr_count_admins', 'usr_count_via_groups', 'usr_admin_via_group',
                'usr_admin_via_group_n', 'usr_col_direct', 'usr_col_via_groups',
                'usr_group_disabled_hint', 'rol_count_roles', 'rol_count_unused',
                'rol_col_reach', 'rol_col_direct', 'rol_col_groups', 'rol_unused',
                'grp_count_groups', 'grp_count_admin', 'grp_count_idle', 'grp_count_disabled',
                'grp_col_effect', 'grp_effect_disabled', 'grp_effect_no_roles',
                'grp_effect_no_members', 'grp_effect_grants', 'grp_grants_admin',
                'ses_count_multi_ip', 'ses_col_sessions', 'ses_col_oldest']
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for k in keys:
                assert f"'{k}':" in src, f'{lang} is missing {k}'

    def test_the_two_counted_messages_keep_their_placeholder(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for k in ('usr_admin_via_group_n', 'grp_effect_grants'):
                m = re.search(r"'" + k + r"':\s*'([^']*)'", src)
                assert m, f'{lang}: {k}'
                assert '{}' in m.group(1), f'{lang}: {k} lost its count'
