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
