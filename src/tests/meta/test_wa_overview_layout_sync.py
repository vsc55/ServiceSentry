#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The dashboard layout belongs to the ACCOUNT, and `localStorage` only holds a draft.

Reported as "the same user sees a different Overview at `https://panel.example` than at
`http://10.0.0.1:8080`". Both are the same account, the same database and the same browser —
but `localStorage` is scoped to the ORIGIN (scheme + host + port), so those two are two
separate stores, and the layout was read from the local one FIRST, unconditionally.

That alone would be a per-host quirk. What made it a bug with no way out is the pair of rules
that surrounded it: every drag, resize and filter wrote the local copy, while only the explicit
"Save" reached the database — so the copy that always won was also the copy that nothing ever
reconciled. Saving the layout in one session left the other session showing a months-old
arrangement **forever**, and nothing on screen said it was looking at a draft.

The fix is the shape the table config already had forty lines away (`_syncRemoteTableConfig`):
the account is authoritative, the local copy is a cache, and the keepalive poll adopts what
another session saved. The one thing a dashboard needs on top of that is a way to tell a DRAFT
apart from a stale cache — without it, the two are the same bytes, which is how the stale one
got to win. That is the dirty flag, and these tests are mostly about it.

Source guards: this is one function's worth of precedence rules in a Jinja template, and the
failure mode is silent (a wrong layout renders perfectly). Reading the rules is what catches a
future edit that reinstates "local always wins".
"""

import os

from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
LAYOUT = os.path.join(TPL, 'partials', 'overview', '_layout.html')
RENDER = os.path.join(TPL, 'partials', 'overview', '_render.html')
POLLING = os.path.join(TPL, 'partials', 'core', '_polling.html')


def _js(name: str) -> str:
    return _strip_comments(_fn(_read(LAYOUT), name))


class TestTheAccountIsTheLayout:

    def test_the_draft_is_read_only_when_it_is_a_draft(self):
        """The regression, in one line: the local copy behind `_dwIsDirty()`."""
        src = _js('_dwLoad')
        assert '_dwIsDirty()' in src, '_dwLoad no longer asks whether the local copy is a draft'
        i_dirty = src.index('_dwIsDirty()')
        i_local = src.index('localStorage.getItem(_dwKey())')
        assert i_dirty < i_local, 'the local copy is read before the draft flag is consulted'

    def test_the_account_is_read_and_the_cache_refreshed_from_it(self):
        src = _js('_dwLoad')
        assert 'currentUser.dashboard_layout' in src
        i_db = src.index('currentUser.dashboard_layout')
        i_set = src.index('localStorage.setItem(_dwKey()')
        assert i_db < i_set, 'the cache is written before the account is read'

    def test_an_empty_account_drops_the_local_copy(self):
        """An empty `dashboard_layout` means "I follow the org default". A leftover local
        copy would outlive that choice and quietly keep the old arrangement."""
        assert 'localStorage.removeItem(_dwKey())' in _js('_dwLoad')

    def test_the_local_copy_is_never_the_last_word(self):
        """Whatever the order, `_dwLoad` may not return the local copy without having
        looked at the account first — that is the whole bug."""
        src = _js('_dwLoad')
        assert src.index('currentUser.dashboard_layout') < src.rindex('return')


class TestADraftIsMarked:

    def test_an_edit_raises_the_flag_and_a_non_edit_does_not(self):
        """`_dwSave` is what every drag, resize and filter calls — including the one that
        fires when edit mode simply closes. Marking unconditionally would badge a dashboard
        nobody touched, and a badge that cries wolf is a badge people stop reading."""
        src = _js('_dwSave')
        assert '_dwMarkDirty(' in src
        assert '_dwBaseline' in src, 'the draft is not compared against anything'

    def test_the_baseline_is_what_the_account_would_show(self):
        """A draft is a draft AGAINST something, and that something is the account — not
        what happens to be rendered, or a draft would look identical to itself."""
        src = _js('_dwLoad')
        assert '_dwBaseline = JSON.stringify(account)' in src
        assert src.index('_dwBaseline') < src.index('_dwIsDirty()'), (
            'the baseline is set after the draft path returns, so a draft never gets one')

    def test_both_writers_serialise_the_grid_the_same_way(self):
        """`_dwSave` (draft) and `_dwSaveDb` (account) read the same DOM. A different
        fallback in each is a difference no edit caused — and, now that the two are
        compared, a permanent phantom "unsaved"."""
        import re
        cols = {re.search(r"cols:\s*parseInt\(el\.dataset\.cols\) \|\| (\d+)", _js(n)).group(1)
                for n in ('_dwSave', '_dwSaveDb', '_dwSetDefault')}
        assert len(cols) == 1, f'three serialisers, {len(cols)} different column fallbacks: {cols}'

    def test_saving_to_the_account_lowers_it(self):
        src = _js('_dwSaveDb')
        assert '_dwMarkDirty(false)' in src
        assert src.index('r.ok') < src.index('_dwMarkDirty(false)'), (
            'the draft is cleared before the account has accepted it — a failed save would '
            'look saved and then be overwritten by the next poll')

    def test_the_three_ways_out_of_a_draft_all_clear_it(self):
        for name in ('_dwReset', '_dwClearConfig', '_dwResetFactory'):
            assert '_dwMarkDirty(' in _js(name), f'{name} leaves the draft flag standing'

    def test_the_flag_has_its_own_key(self):
        """Sharing `_dwKey` would mean the flag disappears with the layout it describes."""
        src = _read(LAYOUT)
        assert "'ss_layout2_dirty_'" in src and "'ss_layout2_'" in src

    def test_the_screen_says_so(self):
        """A draft nobody can see is a draft mistaken for the real layout — which is how
        this was reported in the first place."""
        assert 'dwDirtyBadge' in _read(RENDER), 'no unsaved marker in the controls bar'
        assert 'dashboard_unsaved' in _read(RENDER)
        assert "getElementById('dwDirtyBadge')" in _js('_dwPaintDirty')

    def test_the_badge_does_not_carry_the_bars_auto_margin(self):
        """Reported the moment it shipped: "you moved Edit Layout and Fullscreen sideways".

        The badge starts `d-none`, a `d-none` element takes no part in the flex layout, and
        the `ms-auto` that pushes the toolbar to the right was ON the badge — so the margin
        vanished with it and the buttons drifted left exactly when there was nothing to
        report. The auto margin belongs to a wrapper that is always there."""
        import re
        badge = re.search(r'<span class="badge[^>]*id="dwDirtyBadge"', _read(RENDER), re.S)
        assert badge, 'the badge markup moved — re-aim this guard'
        assert 'ms-auto' not in badge.group(0), (
            'ms-auto sits on an element that can be hidden; it disappears with it')


class TestOtherSessionsConverge:

    def test_the_keepalive_feeds_the_dashboard_too(self):
        src = _strip_comments(_read(POLLING))
        assert '_syncRemoteDashboard' in src, 'the poll still only syncs the table config'
        assert src.count('await r.json()') == 1, (
            'the /me body is read twice — the second read gets an empty stream')

    def test_it_refuses_to_touch_an_edit_in_progress(self):
        """Converging is worth less than destroying work somebody is in the middle of."""
        src = _js('_syncRemoteDashboard')
        for guard in ('_dwSavePending', '_dwEditing', '_dwIsDirty()'):
            assert guard in src, f'{guard} does not hold the sync back'

    def test_an_in_flight_save_holds_it_back(self):
        """Our own PUT and the poll race: a /me snapshot taken before the save landed
        would revert the layout that was just saved."""
        src = _js('_dwSaveDb')
        assert '_dwSavePending = true' in src
        assert 'finally' in src, 'a failed save would leave the flag set and stop all syncing'

    def test_it_updates_both_copies(self):
        src = _js('_syncRemoteDashboard')
        assert 'currentUser.dashboard_layout = incoming' in src
        assert 'localStorage.setItem(_dwKey()' in src and 'localStorage.removeItem(_dwKey())' in src

    def test_it_does_nothing_when_nothing_changed(self):
        """The poll runs every 20 s; re-rendering the overview each time would refetch
        `/api/v1/modules/overview` forever."""
        assert 'JSON.stringify(incoming) === JSON.stringify(mine)' in _js('_syncRemoteDashboard')

    def test_it_only_redraws_what_is_on_screen(self):
        src = _js('_syncRemoteDashboard')
        assert 'offsetParent' in src, 'redraws a pane that may not even be visible'
