#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The two things the backup screen gets wrong when nobody is watching.

Both were reported: a button that did nothing for as long as the server took, and a folder
picker that opened at the drive roots when the one folder that is always relevant is the one
the copies are already going to.

Read as text, like the rest of the frontend guards — there is no browser here. What they fix in
place is the ORDER of two calls, which is exactly the kind of thing a later edit reverses
without noticing.
"""

import io
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
RENDER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'backup', '_render.html')
ROUTES = os.path.join(SRC, 'lib', 'core', 'backup', 'routes.py')


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()


class TestThePickerAnswersTheClick:

    def test_the_modal_opens_before_the_fetch(self):
        """Awaiting the answer first meant the button did nothing at all until the server
        replied — and a button that does nothing is a button somebody presses again."""
        src = _read(RENDER)
        body = src[src.index('async function _openDirPicker'):src.index('async function _dirPickLoad')]
        i_open = body.index('_openBackupModal(')
        i_load = body.index('_dirPickLoad(')
        assert i_open < i_load, 'the picker still waits for the server before showing anything'

    def test_it_shows_a_spinner_while_it_waits(self):
        src = _read(RENDER)
        body = src[src.index('async function _openDirPicker'):src.index('async function _dirPickLoad')]
        assert 'spinner-border' in body, 'the modal opens empty with nothing to say it is loading'

    def test_walking_the_tree_refills_the_same_modal(self):
        """A second modal on top of the first is how a picker ends up with two OK buttons and
        only one of them wired. Counted against the ONE construction: every screen this
        section shows — create, restore, browse, and each step down the tree — goes through
        the same helper."""
        src = _read(RENDER)
        assert src.count('bootstrap.Modal.getOrCreateInstance') == 1, \
            'something builds a second modal instead of refilling the section one'


class TestItStartsWhereTheCopiesGo:

    def test_no_path_means_the_backup_folder(self):
        """The picker is opened to CHANGE a folder, so the folder in use is the one answer
        that is always relevant. The drive roots are where you end up, not where you start."""
        src = _read(ROUTES)
        body = src[src.index('def api_browse_dirs'):src.index('/api/v1/backups\', methods=[\'POST\']')]
        assert 'backup_svc.backups_dir(' in body, 'an empty path still answers with the roots'
        assert '_var_dir()' in body, 'nothing to fall back to before the first copy exists'

    def test_the_wait_says_which_folder(self):
        """A spinner alone says "something is happening"; naming the folder says WHAT, which
        is the difference between waiting and wondering whether the click registered."""
        src = _read(RENDER)
        assert 'backup_browse_scanning' in src
        body = src[src.index('async function _dirPickLoad'):]
        assert '_dirPickBusy(path)' in body[:400], \
            'only the first open shows it — walking into a slow mount looks frozen'


class TestWalkingDoesNotRebuildTheModal:
    """Reported as "clicking a drive collapses and expands the whole dialog".

    Handing Bootstrap a whole new body makes it re-centre the dialog, so it visibly shrank to
    nothing and grew back on every click — and the rail, which does not change, was thrown
    away and rebuilt to show the same six drives.
    """

    def test_only_the_folder_pane_is_repainted(self):
        src = _read(RENDER)
        assert "getElementById('dirPickMain')" in src, 'it rebuilds the whole body again'
        body = src[src.index("const pane = document.getElementById('dirPickMain')"):]
        assert 'pane.innerHTML = main' in body[:300]
        assert 'return;' in body[:600], 'it falls through and reopens the modal anyway'

    def test_the_rail_keeps_its_selection_in_step(self):
        """Not repainting it means nothing marks the new folder unless something says so."""
        src = _read(RENDER)
        assert "#dirPickRail .ss-rail-item" in src
        assert "classList.toggle('active'" in src

    def test_the_picker_opens_wide(self):
        """A two-pane file browser in a 500px dialog is two columns of ellipsis. Set per
        opening, because the same modal also shows a short form."""
        src = _read(RENDER)
        assert "classList.toggle('modal-lg'" in src
        assert "}, 'lg');" in src, 'the picker does not ask for the wide dialog'


class TestTheEmptyBoxSaysWhereCopiesGo:
    """The setting's default is "" meaning `<var_dir>/backups` — a path the registry cannot
    hold, because it depends on where the panel was installed. A blank box with a hint below it
    leaves the operator to work out what that resolves to on THIS install."""

    def test_the_picker_can_supply_a_placeholder(self):
        src = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                 '_field_render.html'))
        assert '_fieldPickerPlaceholder' in src
        assert '${_fpPh}' in src, 'the placeholder is computed and never used'

    def test_it_only_shows_when_the_field_is_empty(self):
        """A placeholder under a value is invisible; computing it there is work for nothing —
        and worse, it would suggest the box is empty when it is not."""
        src = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                 '_field_render.html'))
        assert "(value == null || value === '') ? _fieldPickerPlaceholder(pathStr) : ''" in src

    def test_it_asks_the_server_and_repaints(self):
        src = _read(RENDER)
        body = src[src.index('async function _backupDirPlaceholder'):]
        assert "apiGet('/api/v1/backups/browse')" in body[:600]
        assert 'res.configured' in body[:800]

    def test_it_never_repaints_over_an_edit(self):
        """Repainting Configuration from under an admin who is typing into it would throw the
        edit away to add a placeholder."""
        body = _read(RENDER)
        body = body[body.index('async function _backupDirPlaceholder'):]
        assert "!_isDirty('config')" in body[:900]


class TestTheTwoPanesStayInTheirLanes:
    """Reported from a screenshot: the rail spilled over the folder list and the path row sat
    on top of it."""

    def test_the_rail_sizes_itself(self):
        """`.ss-rail` carries `flex: 0 0 15.5rem`. Wrapped in a narrower box it kept insisting
        on 15.5rem and overflowed — the wrapper was the bug, not the width."""
        src = _read(RENDER)
        assert 'id="dirPickRail"' in src
        assert '<div id="dirPickRail"' not in src, 'the rail is wrapped again'

    def test_a_rail_label_is_a_name_not_a_path(self):
        """Both separators: a Windows path holds no forward slash, so a class with only `/`
        split nothing and the rail showed `D:\Source\Proyectos\...` where a name belongs."""
        src = _read(RENDER)
        body = src[src.index('function _dirPickLeaf'):]
        assert r'[\/]' in body[:400], 'the split only handles forward slashes'

    def test_the_panes_fill_the_dialog_instead_of_measuring_it(self):
        """`.modal-lg > .modal-content` is `resize: both` on purpose — these dialogs are meant
        to be dragged bigger. A child with a FIXED height defeats that: the box grows and the
        content stays put, which is the empty half that was reported. It fills, with a floor so
        it cannot collapse when the dialog is made small."""
        src = _read(RENDER)
        assert 'style="flex:1 1 auto;min-height:20rem"' in src,             'the picker measures the dialog instead of filling it'
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '#backupModal .modal-lg > .modal-content > .modal-body' in css,             'the body is not a column, so nothing inside it can fill'
        i = css.index('#backupModal .modal-lg')
        assert 'flex-direction: column' in css[i:css.index('}', i)]


class TestTheRailSaysWhereYouAre:
    """Reported: `C:\` lit while standing at `C:\`, and went dark the moment a folder in it
    was opened — losing the one thing the rail is for."""

    def test_it_lights_what_contains_the_folder_not_what_equals_it(self):
        src = _read(RENDER)
        assert 'function _dirPickMarkRail' in src
        body = src[src.index('function _dirPickMarkRail'):]
        assert 'startsWith(stem' in body[:700], 'still an exact comparison'

    def test_the_deepest_match_wins(self):
        """Standing in /mnt/nas/backups lights /mnt, not /; and the configured folder beats
        the drive it lives on."""
        src = _read(RENDER)
        body = src[src.index('function _dirPickMarkRail'):]
        assert 'stem.length > bestLen' in body[:900]

    def test_it_compares_on_a_separator_boundary(self):
        """A path is not inside /var because it starts with those four letters."""
        src = _read(RENDER)
        body = src[src.index('function _dirPickMarkRail'):]
        # chr(92) rather than a literal: a backslash inside a Python string inside a test
        # about backslashes is three layers of escaping and two of them are wrong.
        assert "stem + '" + chr(92) * 2 + "'" in body[:700], 'no backslash boundary'
        assert "stem + '/'" in body[:700], 'no forward-slash boundary'

    def test_both_paints_go_through_it(self):
        """The first open and every step afterwards: two ways of deciding which entry is lit
        is one way for them to disagree."""
        src = _read(RENDER)
        assert src.count('_dirPickMarkRail()') >= 2
