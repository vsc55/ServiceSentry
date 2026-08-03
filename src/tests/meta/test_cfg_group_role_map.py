#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A new Group → Role mapping must survive pressing Save.

The reported symptom was a save that lied: adding a row in Configuration › Authentication ›
SSO (OIDC), pressing Save and reloading left the new mapping gone, while the toast had said
it saved.  Changing the Role of a mapping that already existed always worked.

That asymmetry is the whole diagnosis.  The two halves go through different handlers:

* the Role ``<select>`` calls ``_grmUpdate`` directly — synchronous, so the value is staged
  in ``_dirtyFields`` before the click reaches Save;
* the group-id ``<input>`` calls ``_grmRowIdChanged``, which for a section with a directory
  group source (oidc, saml2, ldap all declare one) **awaited a name lookup first**.  The
  handler runs on ``change``, which fires when the Save button takes focus, so the click
  landed while the lookup was in flight: ``saveConfig`` sent every dirty field except this
  one, reported success truthfully, and the mapping was staged a moment later with nobody
  left to save it.

Two things keep it fixed, and both are checked here: the mapping is staged before anything
is awaited, and the input stages on every keystroke rather than only on blur — so what is
pending always matches what is on screen.

**The second half of the same story.** With the mapping saved, the Save button then went
straight back to "unsaved changes" after announcing success — F5 showed the value stored,
and pressing Save a second time was what quietened it.  Same widget, opposite direction:
`markDirty` decides the button by comparing `configData` against `_serverConfigData`, the
snapshot of what the server holds, and this widget saves one field **on its own**
(`group_display_names` — names it resolved itself, which the user never typed and should
not have to save).  That out-of-band save dropped the path from `_dirtyFields` but never
moved the snapshot, so the two disagreed for good and the button believed it.

The fix is one shared `applySavedField`: version token, dirty set and snapshot move
together, because they describe the same fact.  Splitting them is how a save reports
success and leaves the UI contradicting it.
"""

import io
import os
import re

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
WIDGET = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'cfg', 'auth',
                      '_group_role_map.html')
SAVE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'actions', '_save.html')


def _widget() -> str:
    return io.open(WIDGET, encoding='utf-8-sig').read()


def _save() -> str:
    return io.open(SAVE, encoding='utf-8-sig').read()


def _strip_comments(js: str) -> str:
    """Code only.  The first version of this guard searched the prose too and tripped over
    the word "await" in the comment explaining the fix."""
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


def _fn(src: str, name: str) -> str:
    """The body of a top-level JS function in the widget, comments removed."""
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return _strip_comments(m.group(1))


class TestTheValueIsStagedBeforeAnythingIsAwaited:

    def test_the_mapping_is_staged_unconditionally_before_any_branch(self):
        """The row's value must reach `_dirtyFields` on EVERY path, before the function can
        take one that awaits.

        "Before the first await" is not enough, and checking that was this guard's own
        first mistake: the buggy version did stage early — inside an ``if`` that returns —
        so the textually-first call came before the textually-first await while the path
        the user actually walks staged nothing until the lookup came back. The invariant is
        that it happens before any branching at all.
        """
        body = _fn(_widget(), '_grmRowIdChanged')
        first_update = body.find('_grmUpdate(')
        first_branch = body.find('if (')
        assert first_update != -1, 'the handler no longer stages the mapping at all'
        assert first_branch == -1 or first_update < first_branch, (
            'the mapping is staged inside a branch again — on the path that awaits the '
            'name lookup, a save landing in between sends every field except this one and '
            'still reports success')

    def test_the_lookup_only_decorates_the_name(self):
        """Why staging early is correct rather than a race patch: the mapping is
        {group: role}. The awaited lookup fills the display-name column, which is a
        different config field."""
        body = _fn(_widget(), '_grmRowIdChanged')
        assert '_lookupGroupName' in body
        assert 'group_role_map' not in body, (
            'the handler now decides the mapping itself — then staging it early is no '
            'longer enough')


class TestWhatIsPendingMatchesWhatIsOnScreen:

    def test_typing_stages_the_value_not_just_the_dirty_flag(self):
        """`oninput="markDirty('config')"` lit the Save button while leaving the field out
        of the payload: the button said "there are changes" and the save disagreed."""
        src = _widget()
        inputs = re.findall(r'class="[^"]*grm-group[^"]*"[^>]*?oninput="([^"]*)"', src, re.S)
        assert inputs, 'the group-id inputs were not found — did the markup change?'
        for handler in inputs:
            assert '_grmUpdate' in handler, (
                f'a group-id input stages nothing on input ({handler!r}); its value would '
                'only reach the payload on blur')

    def test_every_row_source_agrees(self):
        """Rows are built in two places — the initial render and "Add" — and a fix applied
        to one of them is how this comes back."""
        src = _widget()
        assert len(re.findall(r'class="[^"]*grm-group', src)) == 2


class TestTheOtherHalfStillWorks:

    def test_the_role_select_stages_synchronously(self):
        """The half that always worked, pinned so a refactor does not make both async."""
        src = _widget()
        assert re.search(r'class="form-select form-select-sm grm-role"\s*\n?\s*'
                         r'onchange="_grmUpdate\(', src)

    def test_removing_a_row_stages_too(self):
        assert '_grmUpdate(sec)' in _fn(_widget(), '_grmRemoveRow')


class TestASaveThatSucceedsLeavesTheButtonAtRest:
    """The second reported symptom: saved correctly, and the button said otherwise."""

    def test_the_reconciliation_is_defined_once(self):
        """`markDirty` judges the button by comparing `configData` with
        `_serverConfigData`. A save that updates one and not the other makes the comparison
        permanently wrong — so the three things that describe "the server has this now" move
        in a single function."""
        src = _save()
        assert 'function applySavedField(' in src
        body = _fn(src, 'applySavedField')
        assert '_fieldVersions[path]' in body
        assert '_dirtyFields.delete(path)' in body
        assert '_serverConfigData[sec][field]' in body

    def test_the_main_save_uses_it(self):
        """It was inlined in `saveConfig`, which is why the widget's own save could get it
        wrong: there was no shared definition to reuse."""
        body = _fn(_save(), 'saveConfig')
        assert 'applySavedField(' in body
        assert '_serverConfigData[sec][field]' not in body, \
            'saveConfig reconciles the snapshot itself again — the widget would drift from it'

    def test_the_widgets_own_save_uses_it_too(self):
        """`group_display_names` is saved without the user pressing anything, so it has to
        finish the job a save does — including putting the button back to rest."""
        body = _fn(_widget(), '_saveDisplayNames')
        assert 'applySavedField(' in body, (
            'the out-of-band save reconciles by hand again; dropping the path from '
            '_dirtyFields without moving the snapshot is exactly what left the button '
            'claiming unsaved changes after a successful save')

    def test_it_does_not_re_judge_the_button(self):
        """`markDirty` can only ever LIGHT the button — it never leaves it alone. This path
        stages nothing, so it has nothing to re-judge, and calling it right after a save had
        cleared the badge is a way to put the badge straight back."""
        assert 'markDirty(' not in _fn(_widget(), '_saveDisplayNames')

    def test_the_dirty_set_is_not_edited_behind_the_helpers_back(self):
        assert '_dirtyFields.delete' not in _fn(_widget(), '_saveDisplayNames')

    def test_a_clean_save_makes_the_snapshot_mean_what_it_says(self):
        """"Nothing pending" has to be TRUE, not merely displayed. `markDirty` compares the
        two objects, so a field that differs WITHOUT being staged — written by a widget
        outside the dirty set, normalised locally, anything — makes the next `markDirty`
        light the button for a change nobody made and nobody can clear. Mirroring only the
        saved paths cannot see such a field; taking the whole snapshot when everything the
        user staged was accepted can."""
        body = _fn(_save(), 'saveConfig')
        assert '_serverConfigData = deepClone(configData)' in body
        idx_snap = body.index('_serverConfigData = deepClone(configData)')
        # The LAST clearDirty is the one in the everything-accepted branch; the first is the
        # early return for "nothing was staged", which has no snapshot to take.
        assert idx_snap < body.rindex("clearDirty('config')"), \
            'the snapshot must be taken before the badge is cleared'


class TestResolvingANameDoesNotDirtyTheMapping:

    def test_the_mapping_is_staged_exactly_once(self):
        """Once, unconditionally, at the top. The paths below only fill the display-name
        column, and re-staging the mapping there would put it back into `_dirtyFields`
        after a save had already taken it — a finished save looking pending again."""
        body = _fn(_widget(), '_grmRowIdChanged')
        assert body.count('_grmUpdate(sec)') == 1, (
            'the mapping is staged more than once; the extra calls run after the name '
            'lookup, which does not change the mapping')

    def test_the_later_paths_stage_names_only(self):
        body = _fn(_widget(), '_grmRowIdChanged')
        assert body.count('_grmUpdateNamesOnly(sec)') >= 2

    def test_a_resolved_name_is_never_staged_as_a_user_edit(self):
        """**The one that closes the class.** The names are decoration the widget looks up
        itself; the user never typed them. Putting them through `updateField` staged them as
        an edit, and the lookup finishes AFTER the save it raced — so it staged into a dirty
        set that had just been emptied, and the button went back to "unsaved changes"
        seconds after announcing success. Writing straight into `configData` means the
        automatic path cannot light the button at all, whatever the ordering."""
        body = _fn(_widget(), '_grmUpdateNamesOnly')
        assert 'updateField(' not in body, (
            'resolving a display name stages it as a user edit again — that is what lit the '
            'Save button behind a save that had already succeeded')
        assert 'setPath(configData' in body

    def test_a_name_that_could_not_be_saved_leaves_no_phantom_edit(self):
        """The other half of writing outside the dirty machinery: if the save fails, the
        field must go back to what the server is known to hold. Otherwise it is a difference
        the user cannot see, did not cause and can only clear by saving."""
        body = _fn(_widget(), '_saveDisplayNames')
        assert '_serverConfigData?.[sec]' in body and 'setPath(configData' in body

    def test_the_bulk_resolver_agrees(self):
        """`_grmAutoResolveNames` fills in names after a directory fetch — same rule."""
        body = _fn(_widget(), '_grmAutoResolveNames')
        assert '_grmUpdateNamesOnly(sec)' in body and '_grmUpdate(sec)' not in body


@pytest.mark.parametrize('section', ['oidc', 'saml2', 'ldap'])
def test_the_sections_this_affects_declare_a_group_source(section):
    """The bug only bites where a name lookup exists. If a provider ever stops declaring
    one, the async path is dead code — and if a new one starts, it inherits the fix."""
    from lib.config.group_sources import discover_group_sources    # noqa: PLC0415
    assert section in {s['section'] for s in discover_group_sources()}
