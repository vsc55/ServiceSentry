#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A row that reports a state, not a control that leaves the screen.

Admin › System › Edit user carries a second-factor row: a badge saying whether the account has
one, and a button that takes it off. Two different questions, and conflating them is what went
wrong — twice, both times reported from the screen.

The row began as a CONTROL: drawn only for an account that HAS a factor and only for a holder
of ``mfa_reset_others``, on the reasoning that a button nobody can press is noise on a modal
that already has four tabs. True of the button. False of the badge, which answers a question
about the ACCOUNT — the same one the users table answers in its MFA column, so nothing appears
here that the list did not already show. And "not set up" is precisely the state worth seeing.

Applied at the moment of the reset, the same rule was worse: the block vanished under the
pointer that had just clicked it, leaving a toast as the only evidence anything had happened. A
piece of UI that removes itself is indistinguishable from one that broke.

So the two are split, and this file pins the split:

* **the badge** is drawn for every existing account, in one of its two states, on open and
  after a reset alike;
* **the button** appears only when there is a factor to take off and the viewer may take it;
* **the row** is hidden for a NEW account only — there is no account yet to have a factor.

The guards read the two functions rather than the rendered page: which classes end up on an
element after a click is not something a request can answer.
"""

import os
import re
from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
JS = os.path.join(TPL, 'partials', 'users', '_modal.html')
MARKUP = os.path.join(TPL, 'partials', 'modals', '_user.html')


def _js() -> str:
    return _strip_comments(_read(JS))


class TestTheScanItself:

    def test_the_two_functions_are_found(self):
        assert _fn(_js(), '_umMfaPaint')
        assert _fn(_js(), '_umResetMfa')


class TestTheRowStaysAfterAReset:

    def test_the_reset_does_not_hide_the_row(self):
        """**The regression.** `umMfaGroup` is the block; hiding it here is what made the
        section disappear at the exact moment it had something to say."""
        body = _fn(_js(), '_umResetMfa')
        assert not re.search(r"umMfaGroup[^\n]*d-none", body), \
            'the reset hides the whole row again — it has to report the new state, not leave'

    def test_it_repaints_to_the_off_state_instead(self):
        assert '_umMfaPaint(false' in _fn(_js(), '_umResetMfa')

    def test_the_repaint_happens_only_after_the_server_agreed(self):
        """Painting "not set up" before the call would be a screen that disagrees with the
        database for as long as the request takes — and forever if it fails."""
        body = _fn(_js(), '_umResetMfa')
        i_call, i_paint = body.index('apiDelete'), body.index('_umMfaPaint(false')
        assert i_call < i_paint, 'the row is repainted before the request is even sent'
        assert 'return' in body[i_call:i_paint], (
            'nothing bails out between the call and the repaint: a refusal would leave the row '
            'saying "not set up" while the account still has its factor')


class TestTheTwoStatesAreBothDrawn:

    def test_it_paints_either_state(self):
        body = _fn(_js(), '_umMfaPaint')
        assert 'mfa_state_on' in body and 'mfa_state_off' in body
        # Not colour alone: the badge carries its own words, and they are the state.
        assert 'text-bg-success' in body and 'text-bg-secondary' in body

    def test_only_the_button_comes_and_goes(self):
        """The badge is the state and is always drawn. The button needs BOTH a factor to take
        off and somebody allowed to take it."""
        body = _fn(_js(), '_umMfaPaint')
        m = re.search(r"umMfaReset[^\n]*d-none[^\n]*", body)
        assert m, 'the reset button survives an account with no factor — it would 404 on itself'
        assert 'canReset' in m.group(0), \
            'the button stopped checking the permission — it is offered to whoever can open this'
        assert 'umMfaGroup' not in body, 'the paint function must not touch the row visibility'

    def test_the_badge_it_paints_exists_in_the_markup(self):
        assert 'id="umMfaState"' in _read(MARKUP)


class TestOpeningIsTheOtherMoment:

    def _open_block(self) -> str:
        m = re.search(r"getElementById\('umMfaGroup'\)(.*?)\n    \}", _js(), re.S)
        assert m, 'the open-time visibility block changed shape'
        return m.group(1)

    def test_only_a_new_account_has_no_row(self):
        """A new account has nothing to say here — there is no account yet to have a factor.
        Every existing one gets the row, in whichever state it is in."""
        toggle = re.search(r"classList\.toggle\('d-none',([^)]*)\)", self._open_block())
        assert toggle, 'the row visibility is decided some other way now'
        assert 'isNew' in toggle.group(1)
        assert 'u.mfa' not in toggle.group(1), (
            'an account without a factor loses the row again — "not set up" is the state most '
            'worth seeing, and it is the same fact the users table already shows')
        assert 'mfa_reset_others' not in toggle.group(1), \
            'the permission hides the whole row again instead of just the button'

    def test_both_the_state_and_the_permission_reach_the_paint(self):
        call = re.search(r"_umMfaPaint\(([^;]*)\);", self._open_block())
        assert call, 'the row is no longer painted on open'
        assert 'u.mfa' in call.group(1) and 'mfa_reset_others' in call.group(1)

    def test_opening_repaints_the_row(self):
        """Without this, resetting one account and then opening another that HAS a factor
        would show it as "not set up" — the stale paint from the previous open."""
        assert '_umMfaPaint(' in self._open_block()


class TestTheAccountPageRemembersItsSection:
    """Reloading `/account` while on Security put you back on Preferences. Every other
    sub-navigation in the panel remembers (`ss_active_subtab_infra`, `ss_active_subtab_access`,
    the module views), and this one used to reset ON PURPOSE — the argument was that reopening
    on a half-typed password form is not where anybody left off. That argument does not survive
    contact with a reload: the fields are emptied on open anyway, so what the reset actually
    threw away was the only thing worth keeping, which is where you were.

    The stored id is validated before it is used. A section that was renamed, or a key written
    by an older build, would otherwise open the page on a pane that is not there — every
    section hidden and nothing to say why.
    """

    def _render(self) -> str:
        return _strip_comments(_read(os.path.join(
            os.path.dirname(os.path.dirname(JS)), 'account', '_render.html')))

    def test_choosing_a_section_stores_it(self):
        body = _fn(self._render(), '_accSection')
        assert 'localStorage.setItem' in body
        assert '_ACC_SECTION_KEY' in body

    def test_opening_restores_it(self):
        body = _fn(self._render(), 'initAccountPage')
        assert 'localStorage.getItem' in body
        assert '_accSection(' in body

    def test_an_id_that_no_longer_exists_falls_back(self):
        """Otherwise a renamed section leaves the page with every pane hidden."""
        body = _fn(self._render(), 'initAccountPage')
        assert 'getElementById(want)' in body or 'document.getElementById' in body
        assert "'acctab-prefs'" in body, 'there is no fallback section to land on'

    def test_the_storage_call_cannot_take_the_page_down(self):
        """`localStorage` throws outright in a browser with storage disabled, and this runs on
        the way IN to the page — an exception here would leave it half-drawn."""
        for name in ('_accSection', 'initAccountPage'):
            body = _fn(self._render(), name)
            if 'localStorage' in body:
                assert 'try' in body and 'catch' in body, name


class TestTheTokenDialogSpeaksTheSameLanguageAsAccessPermissions:
    """Reported from the panel: "the permissions are not being translated".

    The create dialog was listing raw flags — `users_view`, `servers_edit` — because it built
    its own list out of `currentUser.permissions`. The panel already has one catalog with one
    set of names (`PERM_GROUPS` + `permission_labels`), used by Access › Permissions, and a
    second list of the same thing is a second list to translate, group and keep in step.

    The flag stays visible beside the name on purpose: it is what the token actually carries
    and what the API and the token list speak, so hiding it would make the two screens
    disagree about what a permission is called.
    """

    TOK = os.path.join(TPL, 'partials', 'account', '_tokens.html')

    def test_the_list_is_built_by_the_shared_factory(self):
        """Reported from the screen: "use the same table design as the rest — the Last used
        header is two lines, it needs sorting and a column chooser".

        All three are things `createListTable` already does for every other entity table, and
        all three were missing because this one was written by hand. So the fix is not three
        fixes: it is joining the factory, which also brings pagination, column widths,
        reordering and the per-user persistence of the lot."""
        src = _read(self.TOK)
        assert 'createListTable(' in src, 'the tokens list is hand-written again'
        assert "key: 'apitokens'" in src
        assert 'persist: true' in src.lower(), (
            'the table does not join the persistence registry, so its columns are not '
            'remembered per user like every other table')

    def test_it_declares_a_sort_value_for_every_sortable_column(self):
        """A column with a `sortKey` and no case in `sortValue` sorts by the fallback — it
        looks sortable and quietly sorts by name."""
        import re as _re
        src = _read(self.TOK)
        cols = set(_re.findall(r"sortKey: '(\w+)'", src))
        handled = set(_re.findall(r"case '(\w+)':", src))
        missing = {c for c in cols if c not in handled} - {'name'}
        assert not missing, f'sortable columns with no sort value: {missing}'

    def test_it_ships_the_shared_filter_strip(self):
        """The other half of the same report: every list section in the panel carries the
        collapsible filter bar, and this one carried none — so finding a token among twenty
        meant reading twenty rows. `spec.filters` is the shared bar, so the only thing this
        screen writes is `match()`."""
        src = _read(self.TOK)
        assert 'filters:' in src, 'the tokens list has no filter strip'
        assert 'match:' in src, 'a filter bar that filters nothing'
        for key in ("key: 'q'", "key: 'state'", "key: 'perm'"):
            assert key in src, f'the filter bar lost {key}'

    def test_the_pane_is_full_bleed_like_every_other_list(self):
        """A list inside a card inside a settings page is a frame within a frame; every other
        list section in the panel goes edge to edge with the same class."""
        pane = re.search(r'<div class="([^"]*)" id="acctab-tokens"',
                         _read(os.path.join(TPL, 'partials', 'account', '_page.html')))
        assert pane, 'the tokens pane is gone'
        assert 'ss-fullbleed' in pane.group(1), 'the tokens list is boxed in a card again'

    def test_revoked_tokens_are_hidden_by_default(self):
        """The list answers "what can be used right now"; the record is one click away.

        A revoked token is kept on purpose — "it stopped working" and "it was never here" are
        different answers, and only one is actionable — but it is history, and history mixed
        into a list of live credentials is what makes the list hard to read: rotate a few
        times and the working token is outnumbered by its own past.

        The switch sits beside the header buttons rather than in the filter bar, which is
        collapsed by default, and it is remembered per user like the columns are."""
        src = _read(self.TOK)
        assert 'headerLead:' in src and 'tokShowRevoked' in src, (
            'the switch is not beside the header buttons')
        assert 'persistExtra:' in src and 'show_revoked' in src, (
            'the switch is not remembered per user')
        assert re.search(r"let _tokShowRevoked = .*?'ss_apitokens_show_revoked'\) === '1'", src, re.S), (
            'the default is not "hidden" — only a stored \'1\' may show the revoked ones')
        assert "f.state !== 'revoked'" in src, (
            'the standing default silently beats an explicit ask for the revoked ones — the '
            'list empties and says nothing about why')
        assert '_accTokens.some(tk => tk.revoked)' in src, (
            '"no tokens" is a lie when they are all there and merely not shown')

    def test_a_filter_outside_the_bar_still_runs(self):
        """Reported from the screen: "I tick hide revoked and nothing happens".

        The factory skips `match()` when no field in the filter bar is set — a fair shortcut
        for a list nobody is filtering, and exactly wrong for a control that filters from
        OUTSIDE the bar: the bar was empty, so the rule never ran and the switch did nothing
        at all, silently. `spec.filters.always` is how a table says its filtering does not
        live only in the bar."""
        factory = _read(os.path.join(TPL, 'partials', 'core', '_list_table.html'))
        assert 'spec.filters.always' in factory, (
            'the factory only filters when the bar has a value, so a control outside it is '
            'a switch that does nothing')
        assert re.search(r'if \(n \|\| extra\)', factory), (
            'the extra filter is computed and then not used to decide whether match() runs')
        assert 'always: () =>' in _read(self.TOK), 'the tokens list does not declare it'

    def test_both_dialogs_share_one_permission_picker(self):
        """Creating a token and editing its scope are the same decision at two different
        moments. Two copies of a list this long is two lists to keep grouped, named and in
        step with the catalog — and the copy that drifts is the one nobody is looking at."""
        src = _read(self.TOK)
        assert src.count('function _accTokenPermPicker(') == 1
        for fn in ('_accTokenNew', '_accTokenEdit'):
            assert '_accTokenPermPicker(' in _fn(src, fn), f'{fn} builds its own picker'
        assert src.count('function _accTokenReadPerms(') == 1, (
            'the picker is read back in two places, so a change to it has two homes')

    def test_it_uses_the_shared_catalog(self):
        src = _read(self.TOK)
        assert 'PERM_GROUPS' in src, 'the dialog builds its own permission list again'
        assert '_permLabel(' in src, 'raw flags are shown instead of their names'

    def test_the_hint_is_offered_too(self):
        assert '_permHint(' in _read(self.TOK)

    def test_a_flag_in_no_group_is_still_pickable(self):
        """A permission added without a group would silently be impossible to give a token."""
        assert 'orphans' in _read(self.TOK)

    def test_only_the_callers_own_permissions_are_offered(self):
        """Server-side the request is refused anyway; offering more would be a list of
        things that produce a 403 when you tick them."""
        src = _read(self.TOK)
        assert 'currentUser.permissions' in src and 'mine.has(p)' in src

    def test_the_token_list_names_them_as_well(self):
        """Two screens, one vocabulary: the list showed raw flags while the dialog showed
        names, which reads as two different things."""
        src = _read(self.TOK)
        assert src.count('_permLabel(') >= 2
