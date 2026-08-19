#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""System › Access › API tokens — the screen, and the wiring a section needs to exist at all.

A section in this panel is not one file. It is a pane in its parent's markup, an entry in the
sidebar, a line in the permission gating, two includes in the JS bundle and a listener that
loads it when it opens — and every one of those was written by hand for this one. Miss the
gating and it is visible to everybody; miss the listener and it opens empty and stays empty;
miss the include and the pane is there with nothing to fill it. All five fail *silently* and
none of them fails in a way a Python test would otherwise notice, which is what this file is
for.

The other half is the two rules that stop this screen being an escalation. They are enforced in
the route (see tests/integration/test_wa_api_tokens.py) and they are also SHAPE here: the
picker offers only the caller's own permissions and does not offer `'*'` at all, so the screen
cannot ask the server for something the server is going to refuse.
"""

import os
import re

from tests.helpers import _fn, _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
LIST = os.path.join(TPL, 'partials', 'apitokens', '_list.html')
VIEWS = os.path.join(TPL, 'partials', 'apitokens', '_views.html')


class TestTheSectionIsWiredEndToEnd:
    """Five files, and a section that is only in four of them is broken in a way nothing says."""

    def test_the_pane_exists_in_its_parent(self):
        src = _read(os.path.join(TPL, 'partials', 'access', '_pane.html'))
        assert 'id="subtab-apitokens"' in src, 'no pane to draw into'
        assert 'id="apitokens-container"' in src, 'the pane has no container'
        assert 'id="subtab-apitokens-li"' in src, 'no tab button'

    def test_the_sidebar_offers_it(self):
        """The sub-tab bar is hidden — the sidebar is what drives these — so a section missing
        from it is a section with no way in."""
        assert "'sub': 'subtab-apitokens'" in _read(os.path.join(TPL, 'partials', '_sidebar.html'))

    def test_it_is_gated_by_the_sessions_permissions(self):
        """A token is standing access to this panel, which is exactly what that pair is about.
        Ungated, a viewer would see every credential in the installation."""
        src = _read(os.path.join(TPL, 'partials', 'init', '_table_features.html'))
        assert "getElementById('subtab-apitokens-li')" in src, 'the section is visible to anybody'
        block = src[src.index("getElementById('subtab-apitokens-li')"):][:200]
        assert 'hasAnySessions' in block

    def test_it_is_in_the_fallback_order(self):
        """Whoever cannot see any other Access sub-tab has to land on one that exists, or the
        section opens with every pane hidden."""
        src = _read(os.path.join(TPL, 'partials', 'init', '_table_features.html'))
        assert "'btn-subtab-apitokens'" in src

    def test_its_javascript_is_included(self):
        src = _read(os.path.join(TPL, 'partials', '_js_sections.html'))
        for part in ('partials/apitokens/_views.html', 'partials/apitokens/_list.html'):
            assert part in src, f'{part} is never included — the pane stays empty'

    def test_opening_it_loads_it(self):
        """Nothing else fetches this list: without the listener the section is an empty card
        with a Refresh button as the only way to see anything."""
        src = _read(os.path.join(TPL, 'partials', 'init', '_wiring.html'))
        assert "getElementById('btn-subtab-apitokens')" in src
        assert 'renderAllTokens' in src


class TestItIsTheSharedMachinery:
    """Every list in the panel comes out of one factory, and this one is not the exception."""

    def test_the_list_is_built_by_the_factory(self):
        src = _read(LIST)
        assert 'createListTable(' in src and "key: 'alltokens'" in src
        assert 'persist: true' in src, 'its columns are not remembered per user'
        assert 'filters:' in src and 'match:' in src, 'no filter strip on the longest list'

    def test_every_sortable_column_has_a_sort_value(self):
        """A column with a `sortKey` and no case sorts by the fallback: it looks sortable and
        quietly sorts by the owner."""
        src = _read(LIST)
        cols = set(re.findall(r"sortKey: '(\w+)'", src))
        handled = set(re.findall(r"case '(\w+)':", src))
        missing = {c for c in cols if c not in handled} - {'username'}
        assert not missing, f'sortable columns with no sort value: {missing}'

    def test_the_permission_picker_is_the_account_screens_own(self):
        """Minting for somebody else is the same decision as minting for yourself, and two
        copies of a list of 75 flags is two lists to keep grouped, named and in step."""
        src = _read(LIST)
        assert '_accTokenPermPicker(' in src, 'this screen builds its own permission list'
        assert 'PERM_GROUPS' not in src, 'a second catalog reader appeared'

    def test_the_grouped_views_are_a_rail_and_not_a_wall_of_cards(self):
        """Asked for from the screen. The first version drew one card per group down the page,
        which put "how many groups are there" above the fold and "what is in this one" three
        screens down, and made every group compete for the same width.

        The panel already owns this shape — an index down the side, the open thing beside it
        filling the rest — so the guard is that it uses the SAME rail, in a generic box rather
        than per-view CSS. `.ss-shell` is the page-level version and carries the negative
        margins that bleed a section to the pane's edges; inside a card those pull it out of
        its own box, which is why the box is its own class and not that one."""
        views = _read(VIEWS)
        assert 'ss-railbox' in views and 'ss-rail-item' in views, (
            'the grouped views draw their own layout again')
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-railbox {' in css, 'the box is per-view markup with no reusable class'
        assert '#alltokens' not in css and '#apitokens-container' not in css, (
            'per-id CSS decides a view layout')

    def test_the_rail_reaches_the_bottom_of_the_card(self):
        """Reported from the screen: the rail stopped at the height of its own items and left
        the rest of the card empty.

        `flex: 1 1 auto` only means something inside a flex CONTAINER, and the factory hands a
        view's body to a plain `.ss-vscroll` — a flex item that is not one. The same trap the
        /account pane hit, so the fix is the same and it lives with the box rather than with
        this view."""
        css = re.sub(r'/\*.*?\*/', '', _read(os.path.join(
            SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')), flags=re.S)
        m = re.search(r'\.ss-vscroll:has\(>\s*\.ss-railbox\)\s*\{([^}]*)\}', css)
        assert m, 'nothing makes the box that holds a rail a column, so the rail cannot grow'
        assert 'display: flex' in m.group(1) and 'overflow: hidden' in m.group(1), (
            'either the rail cannot grow, or it scrolls inside a second scrollbar')

    def test_the_activity_view_reuses_the_filter_strip(self):
        """A fourth view whose rows are CALLS and not tokens, and the thing that keeps it from
        needing a second set of filters: it is a summary, so it is handed every token the strip
        left standing and shows the calls OF THOSE. Filter to one account and it is that
        account's API traffic — one strip, one meaning, in every view."""
        views = _read(VIEWS)
        assert "id: 'activity'" in views and "mode: 'summary'" in views
        body = _fn(views, '_atkViewActivity')
        assert 'allowed.has(r.token_uid)' in body, (
            'the feed ignores the filters, so the strip means something different here')

    def test_the_feed_is_fetched_only_by_the_view_that_needs_it(self):
        """It is the biggest thing this section fetches and three of the four views never look
        at it."""
        assert "_atkView.is('activity')" in _read(LIST)

    def test_the_selection_survives_a_re_render(self):
        """The body is rebuilt on every render() call — a filter keystroke, the poll, a column
        toggle — so a selection living inside it would reset under the pointer."""
        views = _read(VIEWS)
        assert '_TOK_RAIL_SEL' in views
        assert 'groups.some(g => g.id === cur)' in views, (
            'a stale selection leaves the detail empty when the filters remove that group')

    def test_the_by_permission_view_is_one_function(self):
        """The account's list and this one ask the same question at two scopes. Two
        implementations would be two answers, and the copy that stopped drawing `'*'`
        specially would be the dangerous one — and the one nobody was looking at."""
        assert 'function _tokPermGroups(' in _read(VIEWS)
        assert '_tokPermGroups(' in _read(os.path.join(TPL, 'partials', 'account',
                                                       '_token_views.html'))


class TestTheScreenCannotAskForWhatTheServerRefuses:
    """The route is the enforcement; this is the shape that keeps the screen honest."""

    def test_the_all_switch_says_whose_permissions_it_means(self):
        """`'*'` is not one statement but two. On your own token it is "all of MINE" and
        concedes nothing — you cannot exceed yourself. On somebody else's it is "all of
        THEIRS, as it changes", which is the useful reading and the one that grows without
        anybody deciding. A switch that reads "all my permissions" on a dialog about another
        account is the wrong sentence, and the dangerous half of it is the one it hides."""
        picker = _fn(_read(os.path.join(TPL, 'partials', 'account', '_tokens.html')),
                     '_accTokenPermPicker')
        assert 'preset.forOther' in picker, 'the switch reads the same for both meanings'
        assert 'api_token_perms_all_other_label' in picker
        assert 'forOther: true' in _read(LIST), 'the admin dialog does not say whose they are'

    def test_the_switch_is_hidden_exactly_where_the_server_refuses_it(self):
        """A switch that 400s is worse than no switch. The server takes `'*'` from an
        administrator, for an account that HAS a permission set to resolve it against — so the
        built-in identity and a delegated user-manager get the checkboxes and nothing else."""
        src = _read(LIST)
        assert 'noAll: !isAdmin || !!data.unbounded' in src
        picker = _fn(_read(os.path.join(TPL, 'partials', 'account', '_tokens.html')),
                     '_accTokenPermPicker')
        assert 'preset.noAll' in picker, 'the picker cannot be asked to drop the "all" switch'

    def test_the_static_equivalent_is_offered_instead(self):
        """Reported from the screen: "All my permissions" is there on my own settings and not
        here.

        It cannot be: `'*'` is DYNAMIC — "whatever the owner has, forever" — so a token minted
        that way for somebody else keeps pace with an account the minter does not control, and
        the minter has seen the secret. Grant that account a permission next year and the token
        widens with nobody deciding it.

        What the dialog offers instead is a button that ticks everything on offer, which writes
        the same set down as a list: it stays where it was put, and the intersection still
        narrows it if the owner is demoted."""
        picker = _fn(_read(os.path.join(TPL, 'partials', 'account', '_tokens.html')),
                     '_accTokenPermPicker')
        assert '_accTokPermsAll(' in picker, 'no way to pick a whole set without ticking 75 boxes'
        assert 'preset.noAll ?' in picker, (
            'the shortcut is drawn even where the "all of mine" switch already is — two ways '
            'to say the same thing, one of them dynamic and one not')

    def test_a_star_token_keeps_its_meaning_through_clone_and_edit(self):
        """`'*'` flattened to an empty list is a token that silently stops following the
        account it was minted to follow — the one change of meaning nothing on screen would
        report."""
        src = _read(LIST)
        assert "tk.permissions === '*' ? [] :" not in src, (
            "cloning or editing a '*' token drops it back to an explicit list")
        assert 'wasAll' in _fn(src, '_atkOwnerChanged'), (
            'switching account clears the "all of theirs" choice without saying so')

    def test_the_system_owner_is_offered_only_to_an_administrator(self):
        """Cosmetic — the route refuses a non-admin asking for it — but an option that 403s
        when chosen is an option that should not be there."""
        src = _read(LIST)
        assert "currentUser.role === 'admin'" in src
        # The filter on the owner list, not an appended option: the listing already contains
        # the built-in identities, so what an administrator gets is the one that is not
        # filtered OUT rather than an extra one bolted on (which is how it came to be listed
        # twice in the first place).
        assert "isAdmin || n !== 'system'" in src, 'the system option is offered to everybody'

    def test_the_owner_list_has_one_entry_per_account(self):
        """Reported from the screen: `system` appeared twice.

        `/api/v1/users` already carries the built-in identities — they have a name, a UID and a
        row in that listing on purpose — and the dialog appended `system` on top of it. The
        list is built from that response alone now, filtered by who may own a token:
        `anonymous` never may (it is the name the log uses for "we do not know who", and a
        token is an identification), and `system` only for an administrator."""
        src = _read(LIST)
        assert '<option value="system">system</option>' not in src, (
            'system is appended on top of the listing that already contains it')
        assert "n !== 'anonymous'" in src, 'an option the route answers 400 to'
        assert "isAdmin || n !== 'system'" in src

    def test_an_account_that_cannot_sign_in_says_so(self):
        """The hook refuses a token whose owner is disabled or marked no-login, so minting one
        for such an account produces a credential that is handed over and then does nothing for
        reasons nobody can see from here."""
        src = _read(LIST)
        assert 'user_disabled' in src and 'login_disabled' in src

    def test_the_system_owner_says_what_it_means(self):
        """Its scope is fixed at creation and nothing narrows it afterwards. A screen that
        offers that without saying so is one where the difference is discovered later."""
        assert 'api_token_system_hint' in _read(LIST)


def _row_actions() -> str:
    """The buttons a row draws. One function, because the table and the grouped views both
    draw them — a set that differs by view is a view free to offer an action the other one
    refuses."""
    return _fn(_read(LIST), '_atkRowActions')


class TestTheRowOffersWhatTheAccountScreenDoes:
    """It shipped revoke-only, which made this screen a place to CUT access and not to manage
    it — every other operation meant telling the person to do it themselves, which is exactly
    what does not work for a token nobody owns any more."""

    def test_the_four_actions_are_there(self):
        actions = _row_actions()
        for fn in ('_atkEdit', '_atkRotate', '_atkClone', '_atkRevoke'):
            assert fn in actions, f'the row cannot {fn}'

    def test_each_action_is_gated_by_the_permission_it_needs(self):
        """Editing, rotating and cloning change or mint a credential for an account, so they
        need `users_edit`; revoking is the sessions permission. Client-side only — the routes
        check again — but a button that 403s is a button that should not be drawn."""
        actions = _row_actions()
        assert '_canMintForOthers()' in actions and '_canRevokeTokens()' in actions

    def test_an_orphan_offers_only_revoke(self):
        """A token whose account is gone has nobody to bound a new scope by, and rotating one
        is keeping a leftover credential alive rather than cleaning it up."""
        actions = _row_actions()
        assert 'tk.username' in actions, 'an orphan is offered edit and rotate'


class TestTheDialogFollowsTheAccount:
    """Reported from the screen: "when creating a new one it shows ALL the permissions".

    It was offering the CALLER's set whoever the token was for, so minting one for a viewer
    showed all of them and let you tick sixty that viewer does not have. Nothing broke — the
    request-time intersection drops them — which is the problem: the list claimed the token
    could do things it could never do, and the first evidence otherwise was a 403 in something
    scripted."""

    def test_it_asks_the_server_what_that_account_has(self):
        """Roles, group membership and disabled groups decide the answer. Computing it again
        in the browser would be a second implementation of the permission system, with the
        checkboxes riding on whichever copy drifted."""
        src = _read(LIST)
        assert '/permissions' in src and 'apiGet(' in src
        assert 'limitTo' in src, 'the picker is not bounded by that account'

    def test_changing_the_account_redraws_the_checkboxes(self):
        body = _fn(_read(LIST), '_atkOwnerChanged')
        assert 'innerHTML' in body and '_accTokenPermPicker(' in body

    def test_the_built_in_identity_is_bounded_by_the_caller_alone(self):
        """It has no set to intersect with, so an empty list of checkboxes would be the wrong
        answer rather than an honest one."""
        assert 'data.unbounded' in _read(LIST)

    def test_the_picker_takes_the_bound(self):
        picker = _fn(_read(os.path.join(TPL, 'partials', 'account', '_tokens.html')),
                     '_accTokenPermPicker')
        assert 'preset.limitTo' in picker
