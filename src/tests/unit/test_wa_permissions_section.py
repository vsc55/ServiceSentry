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


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_permissions_section.py`` lives in
``tests/integration/test_wa_permissions_section.py``,
``tests/meta/test_wa_permissions_section.py``."""

import os

import pytest


REPO = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
PARTIALS = os.path.join(REPO, 'lib', 'web_admin', 'templates', 'partials')


# ────────────────────────── The API contract ───────────────────────


# ────────────────────────── The section's wiring ───────────────────


class TestItSpeaksBothLanguages:
    """A label that resolves to its own key is the visible failure mode of a missing
    translation, and it only shows up on the page."""

    KEYS = ('subtab_permissions', 'perm_layout', 'perm_view_matrix', 'perm_view_matrix_tt',
            'perm_view_split', 'perm_view_split_tt', 'perm_only_diff', 'perm_only_diff_tt',
            'perm_discard', 'perm_discard_tt', 'perm_discard_confirm', 'perm_roles_updated',
            'perm_count_of', 'perm_count_scoped', 'perm_group_grant_all',
            'perm_group_revoke_all', 'perm_no_match', 'perm_no_differences',
            'perm_builtin_readonly', 'perm_res_expand', 'perm_res_collapse',
            'perm_hide_builtin_tt', 'perm_no_custom_roles',
            'perm_roles_pick_tt', 'perm_roles_search_ph', 'perm_roles_all',
            'perm_roles_none', 'perm_role_dirty_shown',
            'perm_copy', 'perm_copy_tt', 'perm_copy_title', 'perm_copy_from',
            'perm_copy_from_hint', 'perm_copy_to', 'perm_copy_targets_hint',
            'perm_copy_mode', 'perm_copy_replace', 'perm_copy_replace_hint',
            'perm_copy_add', 'perm_copy_add_hint', 'perm_copy_identical',
            'perm_copy_no_targets', 'perm_copy_stage', 'perm_copy_staged',
            'col_permission', 'role_perms_moved')

    @pytest.mark.parametrize('lang', ['en_EN', 'es_ES'])
    def test_every_new_key_is_translated(self, lang):
        table = __import__(f'lib.i18n.lang.{lang}', fromlist=['LANG']).LANG
        for key in self.KEYS:
            assert table.get(key), f'{lang} is missing {key}'

    def test_the_placeholders_match_across_languages(self):
        """`tf()` substitutes one {} per argument, in order: a translation with a
        different count silently drops or leaves a literal "{}" on screen."""
        en_t = __import__('lib.i18n.lang.en_EN', fromlist=['LANG']).LANG
        es_t = __import__('lib.i18n.lang.es_ES', fromlist=['LANG']).LANG
        for key in self.KEYS:
            assert en_t[key].count('{}') == es_t[key].count('{}'), key
