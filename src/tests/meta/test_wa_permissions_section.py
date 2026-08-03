#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Access › Permissions — the section that assigns permissions to roles on a page.

Two things are worth pinning, and they are of different kinds.

**The API contract the screen leans on.**  The section sends ``{"permissions": [...]}``
and nothing else, so the endpoint must apply exactly the field it is given: if a partial
PUT ever started defaulting the fields it does not receive, saving a permission from this
screen would silently blank a role's name or disable it.  Those tests exercise the real
endpoint.

**The wiring of the section itself.**  It is JS in Jinja partials, with no JS runtime
here — so what is checked is what a missing piece would actually break: the sub-tab
exists in the shell, both layouts are loaded, and the labels resolve in both languages.
A section whose partial is not included renders an empty pane with no error anywhere.

This is the ONLY place permissions are assigned: the role modal's Permissions tab is
gone, and the modal must not send the field any more — two editors over one field is how
one screen silently undoes what the other saved.


Split by category: this file holds the structural guards (they read the repo's own source, docs
and templates); the rest of the original ``test_wa_permissions_section.py`` lives in
``tests/unit/test_wa_permissions_section.py``,
``tests/integration/test_wa_permissions_section.py``."""

import io
import os
import re


REPO = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
PARTIALS = os.path.join(REPO, 'lib', 'web_admin', 'templates', 'partials')


def _read(*parts) -> str:
    # utf-8-sig: some templates carry a BOM, and a stray ﻿ would break a literal match.
    return io.open(os.path.join(PARTIALS, *parts), encoding='utf-8-sig').read()


# ────────────────────────── The API contract ───────────────────────


# ────────────────────────── The section's wiring ───────────────────


class TestTheWiringItself:
    """Source-level, because the failures are silent: nothing raises, the screen just
    does less than it says."""

    def test_the_save_sends_permissions_and_nothing_else(self):
        """The counterpart of the API tests above, from this end: if a future edit adds
        `name` or `enabled` to the body, this screen starts overwriting fields it never
        showed the user."""
        src = _read('permissions', '_state.html')
        body = re.search(r"apiPut\('/api/v1/roles/[^;]*?\{([^}]*)\}", src, re.S)
        assert body, 'the PUT call could not be found — was the save rewritten?'
        assert body.group(1).strip() == 'permissions: perms'

    def test_the_draft_is_seeded_from_the_full_permission_list(self):
        """Granular keys survive only because the draft starts as the role's whole set.
        Every place that creates a draft must do it the same way."""
        src = _read('permissions', '_state.html')
        creations = re.findall(r'_permDraft\[uid\] = new Set\(([^)]*)\)', src)
        assert creations, 'no draft is ever created — the section cannot be edited'
        for expr in creations:
            assert expr.strip() == "rolesData[uid]?.permissions || []", \
                f'a draft seeded from {expr.strip()!r} would drop the keys not rendered here'

    def test_the_access_poll_only_redraws_on_a_real_change(self):
        """refreshAccessData replaces rolesData every 30 s. Redrawing regardless rebuilds
        the DOM under the reader — being thrown back to the top of a long matrix twice a
        minute — so the poll compares what it would draw, and skips an edit in progress
        outright (a draft is not stale: it is what the user typed)."""
        assert '_permAutoRefresh();' in _read('init', '_wiring.html')
        src = _read('permissions', '_state.html')
        guard = re.search(r'function _permAutoRefresh\(\)\s*\{(.*?)\n\}', src, re.S)
        assert guard, 'the poll hook is gone'
        assert '_permDirtyUids().length' in guard.group(1)
        assert '_permLastFingerprint' in guard.group(1), \
            'the poll redraws unconditionally again'

    def test_hiding_a_role_hides_it_everywhere(self):
        """The filter applies to the ROLE LIST, not to the columns — so the counters and
        what "only differences" compares follow it too. Filtering only the columns would
        let the screen call two roles identical because the one that disagreed is hidden."""
        src = _read('permissions', '_state.html')
        roles_fn = re.search(r'function _permRoles\(\)\s*\{(.*?)\n\}', src, re.S)
        assert roles_fn and '_permRoleVisible(' in roles_fn.group(1), \
            'the filter is applied somewhere downstream of _permRoles()'
        uniform = re.search(r'function _permIsUniform\(perm\)\s*\{(.*?)\n\}', src, re.S)
        assert uniform and '_permRoles()' in uniform.group(1)

    def test_hide_builtin_is_a_preset_not_a_second_state(self):
        """It shipped as a toolbar switch of its own for a day, which the picker made
        redundant — and two controls over one set is two chances to disagree. It writes the
        built-in UIDs into the picker's hidden set, and whether it looks active is derived
        from that set rather than stored."""
        src = _read('permissions', '_state.html')
        preset = re.search(r'function _permSetHideBuiltin\(on\)\s*\{(.*?)\n\}', src, re.S)
        assert preset and '_permHiddenRoles' in preset.group(1), \
            'hide-built-in keeps a flag of its own again'
        derived = re.search(r'function _permBuiltinHidden\(\)\s*\{(.*?)\n\}', src, re.S)
        assert derived and '_permHiddenRoles' in derived.group(1)
        assert 'permHideBuiltin' not in _read('permissions', '_pane.html'), \
            'the toolbar switch is back beside the picker that replaced it'

    def test_copying_stages_the_change_instead_of_sending_it(self):
        """The copy lands in the draft, so the result is reviewable before it exists: the
        copied cells go amber, Save sends them, Discard throws them away. Calling the API
        from here would be a second way to change permissions — one that skips the screen
        showing you what changed."""
        src = _read('permissions', '_copy.html')
        assert '_permDraft[uid]' in src, 'the copy does not go through the draft'
        for call in ('apiPut(', 'apiPost(', 'fetch('):
            assert call not in src, f'the copy talks to the API directly ({call})'

    def test_copying_only_targets_roles_you_may_edit(self):
        """Built-ins are refused by the API, and a non-editable role would look copied
        until the save failed."""
        src = _read('permissions', '_copy.html')
        apply_fn = re.search(r'function _permCopyApply\(\)\s*\{(.*?)\n\}', src, re.S)
        assert apply_fn and '_permCanEdit(uid)' in apply_fn.group(1), \
            'the apply loop trusts the checkbox list'

    def test_a_role_with_unsaved_changes_cannot_be_hidden(self):
        """Losing sight of an edit you have not saved is how it gets discarded by
        accident — and the picker is the one place you could do it in one click."""
        src = _read('permissions', '_state.html')
        visible = re.search(r'function _permRoleVisible\(uid\)\s*\{(.*?)\n\}', src, re.S)
        assert visible and '_permIsDirty(uid)' in visible.group(1)

    def test_hiding_them_all_says_so(self):
        """"No roles exist" and "the ones that exist are hidden" are different things; the
        second is a filter you can undo, and saying the first would be a lie."""
        assert 'perm_no_custom_roles' in _read('permissions', '_state.html')

    def test_a_redraw_keeps_where_you_were(self):
        """Replacing innerHTML resets every scroll container inside it — which happens on
        each keystroke of the filter too, not only on the poll."""
        src = _read('permissions', '_state.html')
        render = re.search(r'function renderPermissions\(\)\s*\{(.*?)\n\}', src, re.S)
        assert render and 'scrollTop' in render.group(1) and 'scrollLeft' in render.group(1), \
            'the render throws the reader back to the top'

    def test_it_uses_the_same_chrome_as_every_other_list_section(self):
        """It first shipped with a `.ss-toolbar`, which keeps its border, its rounded
        corners and its gap inside a full-bleed pane — so the section read as a card
        floating in a pane with no margins, next to a Users tab that runs edge to edge.
        The card chrome flattens automatically there; the toolbar does not."""
        src = _read('permissions', '_pane.html')
        assert 'ss-card-header' in src and 'ss-accent' in src
        assert 'ss-toolbar' not in src.split('#}')[-1], \
            'the toolbar is back — a full-bleed pane does not flatten it'

    def test_the_override_blocks_fold(self):
        """Every module × 4 actions unfolded would bury the catalog rows the matrix exists
        to compare — so the blocks start closed, and a search opens them (a match hidden
        behind a collapsed caption makes the search look like it found nothing)."""
        src = _read('permissions', '_matrix.html')
        assert '_permResToggle(' in src and 'if (shut) return h;' in src
        state = _read('permissions', '_state.html')
        collapsed = re.search(r'function _permResCollapsed\(prefix\)\s*\{(.*?)\n\}', state, re.S)
        assert collapsed and '_permQuery()' in collapsed.group(1), \
            'a collapsed block would swallow the rows a search just matched'

    def test_the_two_panes_are_a_row(self):
        """`.ss-vfill` is the vertical-fill helper, so it is a flex COLUMN. The two-pane
        layout needs a row, and `d-flex` alone does not give one — it sets `display`, not
        `flex-direction`. Without an explicit `flex-row` the panes stack: the role list on
        top and the permissions underneath, full width. That is how it shipped first."""
        src = _read('permissions', '_split.html')
        outer = re.search(r'return `<div class="([^"]*ss-vfill[^"]*)"', src)
        assert outer, 'the outer container of the split layout was not found'
        assert 'flex-row' in outer.group(1), \
            f'the two panes would stack: class="{outer.group(1)}" has no flex-row'

    def test_the_per_instance_permissions_are_shown(self):
        """They went missing on the first cut: a role can narrow a global flag down to one
        module, host or cluster (`module.ping.view`), and the section rendered only the 64
        catalog flags. Saving preserved them — they were simply invisible, which is worse
        than losing them, because the screen then says a role holds less than it does."""
        for layout in ('_matrix.html', '_split.html'):
            assert '_permVisibleResRows(' in _read('permissions', layout), \
                f'{layout} does not render the per-instance overrides'

    def test_the_resource_table_has_one_builder(self):
        """Both layouts draw the items × actions table from ONE function — the rows, the
        fallback to the global flag and the key format are defined once. A copy would be a
        second answer to "what may this role do to that host"."""
        assert 'function _permResTableHtml(' in _read('permissions', '_resources.html')
        assert '_permResTableHtml(' in _read('permissions', '_split.html')

    def test_the_resources_come_from_the_shared_registry(self):
        """Where modules/servers/clusters come from is `_PERM_RES_SPECS`. Listing them
        again in a layout would mean a new scoped resource shows up in one and not the
        other."""
        src = _read('permissions', '_state.html')
        assert '_PERM_RES_SPECS' in src
        for hardcoded in ("'module'", '"module"', "'server'", "'cluster'"):
            assert f'prefix: {hardcoded}' not in src, \
                'the section is re-declaring a resource instead of reading the registry'

    def test_the_role_modal_no_longer_edits_permissions(self):
        """There is ONE place permissions are assigned now. Two editors over the same
        field is how a screen silently undoes what the other saved — and the modal used to
        PUT every checkbox it held, including the ones it had not refreshed."""
        modal = _read('modals', '_access.html')
        assert 'rmTabPerms' not in modal and 'rolePermissionsGrid' not in modal
        src = _read('roles', '_modal.html')
        assert "apiPut('/api/v1/roles/" in src, 'the modal no longer saves the role at all?'
        put = re.search(r"const payload = .*?;", src, re.S)
        assert put and 'permissions' not in put.group(0),             'the modal is sending permissions again — a partial PUT must leave them alone'

    def test_the_modal_still_carries_permissions_when_cloning(self):
        """The one case where it must: a clone is a NEW role, and POST decides its whole
        permission set. Dropping this would turn "clone" into "create empty"."""
        src = _read('roles', '_modal.html')
        assert '_rolePermsForCreate = clone ? [...(src.permissions || [])] : []' in src
        assert 'permissions' in re.search(r"apiPost\('/api/v1/roles',[^)]*\)", src).group(0)


