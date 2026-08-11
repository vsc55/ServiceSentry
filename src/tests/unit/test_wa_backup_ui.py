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
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
RENDER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'backup', '_render.html')
ROUTES = os.path.join(SRC, 'lib', 'core', 'backup', 'routes.py')
PICKER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'backup',
                      '_picker.html')
TASKS  = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'backup',
                      '_tasks.html')
RUN    = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'backup',
                      '_run.html')
DETAIL = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'backup',
                      '_detail.html')
RESTORE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'backup',
                       '_restore.html')


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()


def _ui() -> str:
    """The section's whole front end, as text.

    Several files because the render shell has a size limit and the picker and the schedule are
    screens in their own right — but they are ONE surface, and a guard that named the file a
    function happens to live in would fail the next time one is split. This is that split, and
    it broke fifteen of these before this helper existed.
    """
    return (_read(RENDER) + _read(PICKER) + _read(TASKS) + _read(RUN)
            + _read(DETAIL) + _read(RESTORE))


class TestThePickerAnswersTheClick:

    def test_the_modal_opens_before_the_fetch(self):
        """Awaiting the answer first meant the button did nothing at all until the server
        replied — and a button that does nothing is a button somebody presses again."""
        src = _ui()
        body = src[src.index('async function _openDirPicker'):src.index('async function _dirPickLoad')]
        i_open = body.index('_openBackupModal(')
        i_load = body.index('_dirPickLoad(')
        assert i_open < i_load, 'the picker still waits for the server before showing anything'

    def test_it_shows_a_spinner_while_it_waits(self):
        src = _ui()
        body = src[src.index('async function _openDirPicker'):src.index('async function _dirPickLoad')]
        assert 'spinner-border' in body, 'the modal opens empty with nothing to say it is loading'

    def test_walking_the_tree_refills_the_same_modal(self):
        """A second modal on top of the first is how a picker ends up with two OK buttons and
        only one of them wired. Counted against the ONE construction: every screen this
        section shows — create, restore, browse, and each step down the tree — goes through
        the same helper."""
        src = _ui()
        # Every construction must target the section's OWN modal. Counting calls was the first
        # version of this and it was wrong: `getOrCreateInstance` returns the same instance for
        # the same element, so opening and closing it are two legitimate calls. What must never
        # happen is a second modal ELEMENT.
        # The element ids the section touches must all belong to ITS modal. Counting
        # `getOrCreateInstance` calls was the first version and was wrong twice over: the same
        # element yields the same instance, so opening and closing are two legitimate calls,
        # and the element is fetched into a variable first, so the call site does not name it.
        ids = set(re.findall(r"getElementById\('(\w*[Mm]odal\w*)'\)", src))
        assert ids, 'nothing shows a modal at all'
        # `infoModal` is the panel's SHARED one, opened through `showInfoModal` like every
        # other section does — a report the restore hands over, not a dialog this section
        # builds. What must not exist is a second modal of its OWN.
        stray = {i for i in ids if not i.startswith('backupModal') and i != 'infoModal'}
        assert not stray, f'a second modal element is used: {stray}'


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
        src = _ui()
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
        src = _ui()
        assert "getElementById('dirPickMain')" in src, 'it rebuilds the whole body again'
        body = src[src.index("const pane = document.getElementById('dirPickMain')"):]
        assert 'pane.innerHTML = main' in body[:300]
        assert 'return;' in body[:600], 'it falls through and reopens the modal anyway'

    def test_the_rail_keeps_its_selection_in_step(self):
        """Not repainting it means nothing marks the new folder unless something says so."""
        src = _ui()
        assert "#dirPickRail .ss-rail-item" in src
        assert "classList.toggle('active'" in src

    def test_the_picker_opens_wide(self):
        """A two-pane file browser in a 500px dialog is two columns of ellipsis. Set per
        opening, because the same modal also shows a short form."""
        src = _ui()
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
        src = _ui()
        body = src[src.index('async function _backupDirPlaceholder'):]
        assert "apiGet('/api/v1/backups/browse')" in body[:600]
        assert 'res.configured' in body[:800]

    def test_it_never_repaints_over_an_edit(self):
        """Repainting Configuration from under an admin who is typing into it would throw the
        edit away to add a placeholder."""
        body = _ui()
        body = body[body.index('async function _backupDirPlaceholder'):]
        assert "!_isDirty('config')" in body[:900]


class TestTheTwoPanesStayInTheirLanes:
    """Reported from a screenshot: the rail spilled over the folder list and the path row sat
    on top of it."""

    def test_the_rail_sizes_itself(self):
        """`.ss-rail` carries `flex: 0 0 15.5rem`. Wrapped in a narrower box it kept insisting
        on 15.5rem and overflowed — the wrapper was the bug, not the width."""
        src = _ui()
        assert 'id="dirPickRail"' in src
        assert '<div id="dirPickRail"' not in src, 'the rail is wrapped again'

    def test_a_rail_label_is_a_name_not_a_path(self):
        """Both separators: a Windows path holds no forward slash, so a class with only `/`
        split nothing and the rail showed `D:\Source\Proyectos\...` where a name belongs."""
        src = _ui()
        body = src[src.index('function _dirPickLeaf'):]
        assert r'[\/]' in body[:400], 'the split only handles forward slashes'

    def test_the_panes_fill_the_dialog_instead_of_measuring_it(self):
        """`.modal-lg > .modal-content` is `resize: both` on purpose — these dialogs are meant
        to be dragged bigger. A child with a FIXED height defeats that: the box grows and the
        content stays put, which is the empty half that was reported. It fills, with a floor so
        it cannot collapse when the dialog is made small."""
        src = _ui()
        assert 'style="flex:1 1 auto;min-height:20rem"' in src,             'the picker measures the dialog instead of filling it'
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '#backupModal .modal-lg > .modal-content > .modal-body' in css,             'the body is not a column, so nothing inside it can fill'
        i = css.index('#backupModal .modal-lg')
        assert 'flex-direction: column' in css[i:css.index('}', i)]


class TestTheRailSaysWhereYouAre:
    """Reported: `C:\` lit while standing at `C:\`, and went dark the moment a folder in it
    was opened — losing the one thing the rail is for."""

    def test_it_lights_what_contains_the_folder_not_what_equals_it(self):
        src = _ui()
        assert 'function _dirPickMarkRail' in src
        body = src[src.index('function _dirPickMarkRail'):]
        assert 'startsWith(stem' in body[:700], 'still an exact comparison'

    def test_the_deepest_match_wins(self):
        """Standing in /mnt/nas/backups lights /mnt, not /; and the configured folder beats
        the drive it lives on."""
        src = _ui()
        body = src[src.index('function _dirPickMarkRail'):]
        assert 'stem.length > bestLen' in body[:900]

    def test_it_compares_on_a_separator_boundary(self):
        """A path is not inside /var because it starts with those four letters."""
        src = _ui()
        body = src[src.index('function _dirPickMarkRail'):]
        # chr(92) rather than a literal: a backslash inside a Python string inside a test
        # about backslashes is three layers of escaping and two of them are wrong.
        assert "stem + '" + chr(92) * 2 + "'" in body[:700], 'no backslash boundary'
        assert "stem + '/'" in body[:700], 'no forward-slash boundary'

    def test_both_paints_go_through_it(self):
        """The first open and every step afterwards: two ways of deciding which entry is lit
        is one way for them to disagree."""
        src = _ui()
        assert src.count('_dirPickMarkRail()') >= 2


class TestTheApiHelpersDoNotShareAShape:
    """Both halves of this have now cost a bug, and both looked identical on screen: a request
    that worked, announcing itself as an error.

        apiGet / apiPut     -> the parsed BODY
        apiPost / apiDelete -> {status, data}

    Reading `res.ok` off the second pair, or `res.status` off the first, reads a key that is
    never there. Delete said "error" with the file already gone; saving a task said it with the
    task already created.
    """

    def test_the_check_understands_both(self):
        src = _ui()
        body = src[src.index('function _apiOk'):src.index('function _apiErr')]
        assert "typeof res.status === 'number'" in body, 'it assumes one shape again'
        assert 'res.ok !== false' in body, 'the body-returning helpers are not handled'

    def test_the_error_message_is_read_from_both(self):
        src = _ui()
        body = src[src.index('function _apiErr'):]
        assert 'res.data && res.data.error' in body[:300]
        assert 'res.error' in body[:300]

    def test_every_call_site_goes_through_it(self):
        """Four helpers and two conventions is exactly the thing not to remember per call.

        Checked against the PATTERN a call site would use, and only on code lines: the comment
        explaining the trap says `res.ok` too, and a guard that trips over the prose explaining
        the rule it is checking fails for being right."""
        src = _ui() + _read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'backup', '_tasks.html'))
        code = [ln for ln in src.splitlines()
                if not ln.strip().startswith(('//', '*', '/*'))]
        for bad in ('res && res.ok', 'if (res.ok)'):
            hits = [ln for ln in code if bad in ln]
            assert not hits, f'a call site reads the response shape directly: {hits}'


class TestTheTwoListsAreToldApart:
    """Reported: the schedule and the copies it produced ran together, with no way to see where
    one ended and the other began."""

    def test_the_copies_get_their_own_heading(self):
        assert "t('backup_copies')" in _read(RENDER)

    def test_the_rail_is_what_tells_them_apart_now(self):
        """It was a border, back when the two lists were stacked in one pane. With the rail
        each is its own view, and a rule under the only thing on screen is a second horizontal
        line below the table's own last row — which is what was reported."""
        src = _read(TASKS)
        assert 'border-bottom' not in src, 'the block draws a rule under itself again'
        assert 'ss-rail-item' in _ui(), 'nothing navigates between the two lists'


class TestTheSectionNavigatesByRail:
    """The same shell Configuration and Modules use. It earns its width because each TASK is an
    entry: selecting one shows the copies IT took, which is what makes per-task retention
    visible instead of something to deduce from file names. A rail holding only "schedule" and
    "copies" would have been two clicks for two lists."""

    def test_it_asks_for_the_shared_shell(self):
        src = _ui()
        assert 'ssRailShell(c, true' in src, 'it builds its own two-column layout again'

    def test_one_place_decides_what_belongs_to_a_task(self):
        """The count on a rail entry and the rows in the pane must not be able to disagree."""
        src = _ui()
        assert 'function _backupsFor' in src
        body = src[src.index('function _backupRailHtml'):]
        assert '_backupsFor(' in body[:1200], 'the rail counts by its own rule'

    def test_the_slug_matches_the_servers(self):
        """`task_slug` decides the file name; this decides which files a task owns. Two
        implementations of one rule is how a task's copies stop being found by the screen that
        lists them."""
        js = _ui()
        js = js[js.index('function _bkSlug'):]
        for piece in ('A-Za-z0-9_-', 'slice(0, 32)', 'toLowerCase()'):
            assert piece in js[:400], piece
        py = _read(os.path.join(SRC, 'lib', 'core', 'backup', 'schedule.py'))
        assert '[^A-Za-z0-9_-]+' in py and '[:32].lower()' in py

    def test_the_chosen_view_is_remembered(self):
        """A section you come back to should be where you left it."""
        assert 'ss_backup_view' in _ui()

    def test_the_toolbar_offers_the_action_of_the_pane_under_it(self):
        """Reported: "Create a copy" sat over the schedule. The wrong verb next to the wrong
        list, and the one you came for — new task — was the one missing."""
        src = _ui()
        body = src[src.index('function _backupSyncToolbar'):]
        assert "_backupView === 'tasks'" in body[:700]
        assert 'btnNewBackupTask' in body[:900] and 'btnNewBackup' in body[:1000]

    def test_the_schedule_block_does_not_add_a_second_one(self):
        """Two of the same button on one page is one of them being the wrong place to look."""
        # Checked against the ADD ICON, not against `openTaskModal('')`: the quotes are
        # escaped in the JS source, so the obvious string never matched and this guard passed
        # for a whole round while the button was still on screen.
        tasks = _read(TASKS)
        assert 'bi-plus-lg' not in tasks, 'the block grew its own add button again'
        pane = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                  'backup', '_pane.html'))
        assert pane.count('openTaskModal') == 1, 'the toolbar is the one place it lives'


class TestTheCopiesTableSortsLikeTheOthers:
    """Reported: the copies table did not sort by column while every other list does."""

    def test_it_uses_the_shared_header_renderer(self):
        """A table that sorts differently from its neighbours is one somebody has to learn
        twice — same caret, same hover, same click target."""
        assert '_thSortInner(' in _ui(), 'it draws its own header again'

    def test_size_and_time_compare_as_numbers(self):
        """As text, "9 MiB" sorts above "10 MiB" and 2026-08-09 above 2026-08-10 — a sort that
        looks like it worked."""
        body = _ui()
        body = body[body.index('function _bkSorted'):]
        assert 'Number(a[_bkSort])' in body[:700]

    def test_it_sorts_a_copy_of_the_list(self):
        """Sorting `_backups` in place would reorder what the rail counts from, and the two
        would disagree the moment a count was taken between two clicks."""
        body = _ui()
        body = body[body.index('function _bkSorted'):]
        assert 'rows.slice().sort' in body[:400], 'it sorts the array the rail reads'

    def test_newest_first_by_default(self):
        """The copy you want is almost always the last one taken."""
        src = _ui()
        assert "_bkSort = localStorage.getItem('ss_backup_sort') || 'mtime'" in src
        assert "_bkSortDir = localStorage.getItem('ss_backup_sort_dir') || 'desc'" in src


class TestRunningATaskShowsProgress:
    """A copy of a large install takes minutes. A button that hangs until it finishes is one
    the browser or a proxy gives up on, leaving the operator unable to tell whether it worked."""

    def test_it_starts_a_job_and_polls(self):
        src = _ui()
        body = src[src.index('async function runBackupTask'):]
        assert 'job_id' in body[:700], 'it still waits for the whole copy in one request'
        # The polling moved into the start both kinds share — followed rather than pinned to
        # this function, because pinning it is what would forbid the sharing.
        start = src[src.index('function _bkStartWatching'):]
        assert '_bkPollJob(' in start[:900], 'nothing follows the job once it is started'

    def test_it_appears_in_the_list_at_once(self):
        """The copy IS being made; a list showing nothing until it finishes is the screen
        disagreeing with the disk for as long as it takes."""
        src = _ui()
        assert 'function _bkRunningRow' in src
        assert '${running}' in src, 'the running row is built and never placed'

    def test_progress_is_counted_in_tables(self):
        """Rows are unbounded and the archive's size is unknown until it closes; the table is
        the only unit that means anything."""
        src = _ui()
        body = src[src.index('function _bkRunningRow'):]
        assert 'r.step' in body[:800] and 'r.total' in body[:800]

    def test_the_running_row_opens_the_detail(self):
        """The row has one line to say it in; the dialog is where somebody who wants to watch
        it can."""
        src = _ui()
        assert '_bkOpenRunningDetail()' in src
        body = src[src.index('async function _bkPollJob'):]
        assert '_bkJobBody()' in body, 'the open dialog never updates'

    def test_a_job_that_is_gone_stops_the_wait(self):
        """Jobs live in the process's memory, so a null answer after a restart is not something
        more waiting will fix."""
        src = _ui()
        body = src[src.index('async function _bkPollJob'):]
        assert 'if (!job)' in body[:700], 'it polls for ever after a restart'

    def test_it_says_so_when_it_finishes(self):
        src = _ui()
        body = src[src.index('async function _bkPollJob'):]
        assert 'job.done' in body[:900] and 'showToast' in body[:1100]
        assert 'renderBackups()' in body[:1200], 'the new copy never appears in the list'


class TestASuggestedNameDoesNotCollide:
    """`create_backup` refuses to overwrite, so a suggestion without seconds makes the second
    copy of a minute fail on a collision the operator did not cause and cannot see — and the
    moment you take two by hand is the moment you are trying something and repeating it.

    The scheduler's names have carried seconds since they existed; this is the same rule in the
    one place that had its own copy of it."""

    def test_the_manual_suggestion_carries_seconds(self):
        src = _ui()
        # Anchored on the newline: `_openBackupModal` contains this name too, and `index`
        # finds that one first — which would have sliced from the wrong function.
        body = src[src.index(chr(10) + 'function openBackupModal'):]
        assert 'getSeconds()' in body[:700], 'two copies in one minute suggest the same name'

    def test_the_scheduler_carries_them_too(self):
        py = _read(os.path.join(SRC, 'lib', 'core', 'backup', 'schedule.py'))
        assert '%H%M%S' in py, 'the automatic names lost their seconds'


class TestTheDetailReadsTheManifest:
    """What a copy holds is decided when it is MADE, and the screen that shows it months later
    has to say the same thing. Everything the dialog prints comes out of the manifest the
    archive carries; the day one of these is worked out at display time, two panels looking at
    the same file can disagree about whether it is good."""

    def test_the_row_offers_it(self):
        assert 'openBackupDetail(' in _read(RENDER), 'the copies list has no way in'

    def test_it_names_who_made_it_and_with_what(self):
        body = _read(DETAIL)
        for key in ('created_by', 'app_version', 'engine'):
            assert 'b.' + key in body, 'the detail drops ' + key

    def test_it_counts_the_rows_from_the_tables_it_carries(self):
        """A copy that came out short is a copy whose row count says so — the number has to be
        the one in the file, not a fresh count of the database it came from."""
        body = _read(DETAIL)
        assert 'b.tables' in body and 'reduce(' in body

    def test_it_lists_the_digests(self):
        body = _read(DETAIL)
        assert 'b.sha256' in body, 'no way to see what Verify compares against'
        assert 'backup_detail_nosha' in body, 'an older copy shows an empty list with no reason'

    def test_it_shows_the_checklist_the_run_showed(self):
        body = _read(DETAIL)
        assert 'b.steps' in body and '_bkStepsTable' in body

    def test_it_says_whether_the_copy_is_good(self):
        body = _read(DETAIL)
        assert "b.status === 'partial'" in body and "b.status === 'error'" in body

    def test_it_is_wired_into_the_page(self):
        """A partial nobody includes is a dialog that throws on the first click."""
        page = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                  '_js_sections.html'))
        assert 'partials/backup/_detail.html' in page


class TestTheHandMadeCopyIsWatchedToo:
    """Reported: it showed nothing at all until it finished. The request was awaited, so there
    was no job to draw a bar against — and the schedule already had every piece needed.

    One start path for both, because a second one is a second place for the progress to be
    left out, which is how this one came to have none."""

    def test_it_starts_a_job_instead_of_waiting(self):
        src = _ui()
        body = src[src.index('async function _createBackup'):]
        assert 'job_id' in body[:700], 'the form still awaits the whole copy'
        assert '_bkStartWatching(' in body[:900]

    def test_both_kinds_go_through_the_same_start(self):
        src = _ui()
        run = src[src.index('async function runBackupTask'):src.index('function _bkStartWatching')]
        assert '_bkStartWatching(' in run, 'the task run has its own start again'

    def test_the_hand_made_one_opens_the_dialog(self):
        """Its form was just there, so the modal is where the eye already is — unlike a task
        run, which is started from a row and shows in that row."""
        src = _ui()
        body = src[src.index('function _bkStartWatching'):]
        assert 'what.manual' in body[:600]

    def test_it_waits_for_the_form_to_close_first(self):
        """Bootstrap ignores `show()` during the hide transition, so opening the progress
        dialog straight after the form's OK closed it would open nothing at all."""
        src = _ui()
        assert "'hidden.bs.modal'" in src, 'the progress dialog races the form closing'

    def test_the_running_row_finds_the_manual_list(self):
        """It has no task to show under, so `task:<id>` matches nothing and it would be
        invisible in every list but "all"."""
        src = _ui()
        body = src[src.index('function _bkRunningInView'):]
        assert "'manual'" in body[:900] and "'all'" in body[:900]


class TestTheDialogIsNotTakenAway:
    """Reported: watching a copy from the dialog, it closed itself the moment the copy ended.

    That is the instant its outcome is worth reading — and a partial copy, the one outcome that
    needs somebody to act on it, was dismissed by the screen on their behalf, leaving a toast as
    the only trace."""

    def test_finishing_repaints_the_dialog_instead_of_closing_it(self):
        src = _ui()
        body = src[src.index('async function _bkPollJob'):]
        assert '_bkJobDoneBody(' in body, 'nothing replaces the progress bar'
        assert '_closeBackupModal' not in src and '.hide()' not in body, \
            'it still hides the dialog when the job ends'

    def test_it_says_how_the_copy_turned_out(self):
        src = _ui()
        body = src[src.index('function _bkJobDoneBody'):]
        assert 'backup_status_partial' in body[:900] and 'job.error' in body[:900]
        assert '_bkStepsHtml(' in body[:1400], 'the checklist vanishes with the bar'

    def test_it_offers_the_copy_it_made(self):
        """And only when there is one: a run that failed produced no file, and a button
        leading to nothing is worse than no button."""
        src = _ui()
        body = src[src.index('function _bkJobDoneBody'):]
        assert 'job.created' in body[:1200] and 'openBackupDetail(' in body[:1400]

    def test_the_list_is_refreshed_before_the_detail_is_offered(self):
        """`openBackupDetail` reads the copy out of the list it already has; offering it before
        the refresh lands is offering a button that silently does nothing."""
        src = _ui()
        body = src[src.index('async function _bkPollJob'):]
        i_refresh = body.index('await renderBackups()')
        i_paint = body.index('_bkJobDoneBody(')
        assert i_refresh < i_paint


class TestTheRowKeepsOnlyWhatCannotWait:
    """The Contents column repeated the same four part labels on every line — a column that
    said nothing about the copy in front of it once Details lists them properly.

    Two of the things it carried are not contents, though, and they must not need a click: a
    copy that lost a part is not a copy, and one taken without secrets restores credentials
    that authenticate against nothing — found out at restore time, which is too late."""

    def test_the_parts_are_no_longer_repeated_in_the_row(self):
        body = _read(RENDER)
        row = body[body.index('function _backupRow'):]
        assert 'label_key' not in row[:1400], 'the row still lists every part it holds'

    def test_a_secretless_copy_still_says_so_in_the_list(self):
        """It was taken correctly, so the status column calls it good — and it will still
        restore credentials that authenticate against nothing."""
        src = _ui()
        marks = src[src.index('function _bkRowMarks'):]
        assert 'b.secrets' in marks[:400]
        row = src[src.index('function _backupRow'):]
        assert '_bkRowMarks(b)' in row[:1400], 'the marks are built and never placed'

    def test_a_good_copy_is_marked_with_nothing(self):
        """Silence is the good news. A green tick on every line is a column of ticks nobody
        reads, and the one row without it stops standing out."""
        src = _ui()
        marks = src[src.index('function _bkRowMarks'):]
        end = marks.index('\n}')
        assert 'success' not in marks[:end]

    def test_the_running_row_spans_what_is_left(self):
        """One column fewer: a span that still counts the old one pushes the actions cell out
        of the table."""
        src = _ui()
        # Counted off the finished row, not the header: the header is built by calling `th(…)`
        # per column, so there is no literal tag to count there — and the two rows sitting in
        # the same table is precisely the thing that has to keep adding up.
        row = src[src.index('function _backupRow'):]
        cells = row[:row.index('\n}')].count('<td')
        assert cells > 1
        assert 'colspan="%d"' % (cells - 1) in src, f'the progress bar does not span {cells - 1}'


class TestTheListSaysWhetherACopyIsGood:
    """"Is this copy any good" is the question you ask of a list of backups, and it was only
    answerable one copy at a time by opening the dialog."""

    def test_the_column_is_there_and_sorts(self):
        src = _read(RENDER)
        head = src[src.index('<thead class="ss-thead-sticky"'):]
        assert "'status'" in head[:head.index('</tr>')], 'no status column'
        row = src[src.index('function _backupRow'):]
        assert '_bkStatusCell(b)' in row[:1500], 'the header has a column the rows do not fill'

    def test_it_says_all_four_answers(self):
        src = _read(RENDER)
        cell = src[src.index('function _bkStatusCell'):]
        end = cell.index('\n}')
        for key in ('backup_status_ok', 'backup_status_partial', 'backup_status_error',
                    'backup_status_unknown'):
            assert key in cell[:end], f'{key} is never shown'

    def test_a_copy_from_before_verdicts_is_not_called_good(self):
        """A green badge on a copy nobody ever checked is the one lie this column could tell —
        and the dialog has to give the same answer, or the two disagree about the same file."""
        src = _read(RENDER)
        cell = src[src.index('function _bkStatusCell'):]
        assert "b.status === 'ok'" in cell[:cell.index('\n}')], \
            'anything unrecognised falls through to "good"'
        assert 'backup_status_unknown' in _read(DETAIL), 'the dialog still calls it good'

    def test_it_sorts_by_how_bad_it_is(self):
        """Alphabetically the order is error, ok, partial — the two answers that need
        attention either side of the one that does not."""
        src = _read(RENDER)
        rank = src[src.index('function _bkStatusRank'):]
        body = rank[:rank.index('\n}')]
        assert body.index('error') < body.index('partial') < body.index('ok')
        sort = src[src.index('function _bkSorted'):]
        assert '_bkStatusRank(' in sort[:900], 'the column sorts by its label'


class TestRestoringAcrossVersionsIsNotSilent:
    """A copy from a LATER build loses the columns this schema does not have yet. That has to
    be a decision before the button, and a report after it — never a toast with a number."""

    def test_the_dialog_says_which_build_made_the_copy(self):
        src = _read(RESTORE)
        assert '_bkVersionNote(b)' in src, 'the note is built and never placed'
        note = src[src.index('function _bkVersionNote'):]
        assert 'backup_restore_newer' in note[:700] and 'backup_restore_older' in note[:900]

    def test_a_newer_copy_is_a_warning_and_an_older_one_is_not(self):
        """Both are worth saying; only one of them loses anything."""
        note = _read(RESTORE)
        body = note[note.index('function _bkVersionNote'):]
        newer = body[body.index("'newer'"):body.index("'older'")]
        assert 'alert-warning' in newer
        assert 'alert' not in body[body.index("'older'"):body.index('return \'\';')]

    def test_nothing_is_refused_over_a_version(self):
        """The schema moves on almost every build; a panel that turned down "old" copies would
        be useless on the one day it is needed."""
        src = _ui()
        assert 'version_rel' not in src[src.index('async function _restoreBackup'):], \
            'the restore itself now depends on the version'

    def test_what_did_not_go_in_is_shown_not_toasted(self):
        """A toast says a number and disappears; this is the one thing somebody has to read,
        so it replaces the progress bar in the dialog they were already watching."""
        body = _read(RESTORE)
        done = body[body.index('function _bkRestoreDoneBody'):]
        assert 'job.skipped' in done, 'the report is thrown away'
        assert 'backup_skipped_table' in done and 'backup_skipped_cols' in done

    def test_the_reload_waits_for_the_report_to_be_read(self):
        """The page reloads after a restore because everything on it was read before the
        tables changed — but reloading out from under the one thing somebody has to read
        would make the report pointless."""
        src = _ui()
        body = src[src.index('function _bkReloadWhenClosed'):]
        assert "'hidden.bs.modal'" in body[:500]
        assert 'dialogIsOpen' in body[:400], 'nobody reading it still waits for a close'

    def test_the_log_carries_it_too(self):
        """A restore is the moment nobody is looking ten minutes later; "which columns went" is
        asked months afterwards, when the answer on screen is long gone."""
        src = _read(os.path.join(SRC, 'lib', 'core', 'backup', 'runner.py'))
        body = src[src.index("wa._audit_write('backup_restored'"):]
        # To the call's own closing line, not to the first `})` — several values in there are
        # `res.get(..., {})`, and slicing at one of those cuts the entry in half.
        entry = body[:body.index('\n            })')]
        assert "'skipped'" in entry and "'from_version'" in entry


class TestTheRestoreDialogShowsItHappening:
    """Reported: the window said nothing and did nothing until it was over. It goes through the
    same job the copies do — bar, table being written, outcome, and only then the reload."""

    def test_it_starts_a_job_instead_of_waiting(self):
        body = _read(RESTORE)
        fn = body[body.index('async function _restoreBackup'):]
        assert 'job_id' in fn[:600], 'the dialog still awaits the whole restore'
        assert '_bkStartWatching(' in fn[:900], 'a second way of watching the same thing'

    def test_it_draws_no_row_in_the_list(self):
        """A restore adds nothing to any list — it replaces what the install already holds, and
        a row for it would be the screen inventing a copy that is not being made."""
        src = _ui()
        body = src[src.index('function _bkRunningInView'):]
        assert '_bkRunning.restore' in body[:400]

    def test_the_dialog_is_titled_for_what_it_is_doing(self):
        src = _ui()
        body = src[src.index('function _bkRunningTitle'):]
        assert 'backup_restore' in body[:400] and 'backup_create' in body[:400]

    def test_finishing_replaces_the_bar_with_the_outcome(self):
        src = _ui()
        body = src[src.index('async function _bkPollJob'):]
        assert '_bkRestoreDoneBody(job)' in body, 'a restore ends with the copy dialog'

    def test_the_page_is_re_read_only_after_the_restore(self):
        """Everything on screen was read before the tables changed under it — but a copy
        changed nothing on it, so reloading for one would be gratuitous."""
        src = _ui()
        body = src[src.index('async function _bkPollJob'):]
        assert '_bkReloadWhenClosed(' in body
        assert "job.kind === 'restore'" in body[:900], 'it reloads after a copy too'


class TestTheProgressDialogActuallyOpens:
    """Reported: press Restore, the form closes and nothing happens at all.

    Bootstrap ignores `show()` during a hide transition. Testing `classList.contains('show')`
    looked like enough and was the bug: the class comes off at the START of the hide and
    `hidden.bs.modal` fires at its END, so in between there is no class to test and no event
    yet to wait for — and the reply to the request that starts the job lands in exactly that
    window."""

    def test_it_does_not_decide_on_the_class_alone(self):
        src = _ui()
        body = src[src.index('function _bkWhenModalClosed'):]
        end = body.index('\n}')
        assert "'hidden.bs.modal'" in body[:end], 'nothing waits for the close'
        assert 'setTimeout(' in body[:end], \
            'mid-transition there is no class to test and the dialog never opens'

    def test_whichever_answers_first_wins_and_only_once(self):
        """Both paths can fire — the event and the floor — and opening the dialog twice would
        reset it under whoever is reading it."""
        src = _ui()
        body = src[src.index('function _bkWhenModalClosed'):]
        end = body.index('\n}')
        assert 'let done = false' in body[:end] and 'if (!done)' in body[:end]


class TestTheRestoreDialogTicksItsPartsOff:
    """The copy shows a checklist while it runs; putting one back showed a bar and a number,
    and left the operator to work out which of the things they ticked had arrived."""

    def test_the_running_dialog_draws_them(self):
        """`_bkJobBody` already renders `steps` — what it needed was a restore that sends
        them, which is why the checklist is the SAME function for both."""
        src = _ui()
        body = src[src.index('function _bkJobBody'):]
        assert '_bkStepsHtml(r.steps)' in body[:900]

    def test_the_finished_dialog_keeps_them(self):
        done = _read(RESTORE)
        body = done[done.index('function _bkRestoreDoneBody'):]
        assert '_bkStepsHtml(job.steps)' in body, 'the checklist vanishes when it ends'

    def test_the_job_carries_the_final_word(self):
        """It is filled in as the restore goes, but a run that failed leaves it half written —
        the answer is the one the function returned."""
        src = _read(os.path.join(SRC, 'lib', 'core', 'backup', 'runner.py'))
        body = src[src.index('def start_restore'):]
        assert "'steps': res.get('steps'" in body


class TestTheScheduleAndTheVerifyHaveTheirOwnGrants:
    """Two decisions rode on permissions about ARCHIVES and are not about archives at all.

    Changing the schedule destroys no file and quietly halves the protection; verifying writes
    nothing but hashes every member of a multi-gigabyte copy."""

    def test_the_schedule_is_its_own_flag(self):
        man = _read(os.path.join(SRC, 'lib', 'core', 'backup', 'manifest.py'))
        assert "'flag': 'backup_schedule'" in man and "'flag': 'backup_verify'" in man

    def test_the_task_routes_ask_for_it(self):
        src = _read(ROUTES)
        assert "schedule_req = wa._perm_required('backup_schedule')" in src
        for route in ("@app.route('/api/v1/backups/tasks', methods=['PUT'])",
                      "@app.route('/api/v1/backups/tasks/<uid>', methods=['DELETE'])"):
            after = src[src.index(route):]
            assert '@schedule_req' in after[:120], route

    def test_running_a_task_is_still_making_a_copy(self):
        """It produces a copy exactly like the Create button; one grant should not be two ways
        to the same result."""
        src = _read(ROUTES)
        after = src[src.index("@app.route('/api/v1/backups/tasks/<uid>/run'"):]
        assert '@create_req' in after[:120]

    def test_verifying_asks_for_its_own(self):
        src = _read(ROUTES)
        after = src[src.index("@app.route('/api/v1/backups/<name>/verify'"):]
        assert '@verify_req' in after[:120]

    def test_the_buttons_follow_the_same_flags(self):
        """A button that 403s is worse than no button: it says the panel is broken rather than
        that the grant is missing."""
        tasks = _read(TASKS)
        assert "perms.has('backup_schedule')" in tasks
        assert "perms.has('backup_create')" not in tasks, 'the task row still asks the old one'
        render = _read(RENDER)
        assert "perms.has('backup_verify')" in render
        assert "perms.has('backup_schedule')" in render, 'New task ignores the schedule grant'


class TestARestoreTellsTheOtherProcesses:
    """On a multi-container install the workers are running against a `config` table the
    restore has just replaced wholesale. They converge on their own — each polls the shared
    database every 15 seconds — but the panel already has a way to say "now"."""

    def test_it_pokes_every_service_and_not_a_chosen_few(self):
        src = _read(ROUTES)
        body = src[src.index('def _invalidate_caches'):]
        assert '_poke_service_instances(' in body, 'the workers wait out their poll'
        assert '_embedded_services' in body, 'it names services instead of asking'

    def test_the_restore_is_the_one_that_calls_it(self):
        src = _read(ROUTES)
        assert '_invalidate_caches(wa)' in src
