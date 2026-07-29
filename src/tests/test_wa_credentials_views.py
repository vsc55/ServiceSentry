#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The credential catalogue can be read four ways, and all four agree what a credential is.

The table answers "what have I got" and nothing else. Two questions it cannot answer sit on
top of the same data:

* what KIND of secret each one is — an SSH identity and a tenant app registration are not
  the same animal (one reaches a machine, the other is an application with consented
  permissions and no host behind it), and sorting by Type only interleaves them;
* who still REFERENCES it — which is not part of a credential at all. Its consumers live in
  the hosts store and inside every module's config, so the catalogue cannot see them, and a
  secret nobody references is a secret nobody rotates and that stays valid.

What must not differ between the views is what a credential MEANS: the type badge, the
disabled marker and — most of all — the actions a user may take are decided once and
composed by every view. A view that assembled its own buttons would be a view free to offer
Delete to somebody who may not press it, and that is not a styling bug.

These are static guards over the markup and the wiring, like the rest of the panel's UI
tests; the bulk usage endpoint they lean on is covered in test_credentials.py.
"""

import io
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
CRED = os.path.join(TPL, 'partials', 'credentials')
VIEWS = os.path.join(CRED, '_views.html')
LIST = os.path.join(CRED, '_list.html')
PICKER = os.path.join(CRED, '_picker.html')
VIEW_FILES = {
    'cards': os.path.join(CRED, '_view_cards.html'),
    'types': os.path.join(CRED, '_view_types.html'),
    'usage': os.path.join(CRED, '_view_usage.html'),
}


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _strip_comments(js: str) -> str:
    """Code only. A guard that reads the prose trips over the comment explaining the rule it
    is checking, and every file here carries one."""
    js = re.sub(r'\{#.*?#\}', '', js, flags=re.S)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


class TestTheScanItself:
    """If these fail the guard is broken, not the layout."""

    def test_every_file_is_found(self):
        for p in (VIEWS, LIST, PICKER, *VIEW_FILES.values()):
            assert os.path.isfile(p), p

    def test_the_registry_lists_every_view(self):
        src = _strip_comments(_read(VIEWS))
        reg = src[src.index('const CREDENTIAL_VIEWS'):]
        reg = reg[:reg.index('];')]
        for vid in ('table', 'cards', 'types', 'usage'):
            assert f"id: '{vid}'" in reg, f'{vid} is not in the registry'

    def test_the_bundle_includes_them_after_the_registry(self):
        """The registry names render functions as STRINGS because the view files are
        concatenated after it. A file that is never included makes its view silently
        fall back to an empty body."""
        js = _read(os.path.join(TPL, 'partials', '_js_sections.html'))
        i_views = js.index('credentials/_views.html')
        for f in ('credentials/_view_cards.html', 'credentials/_view_types.html',
                  'credentials/_view_usage.html'):
            assert f in js, f'{f} is never included'
            assert js.index(f) > i_views, f'{f} is included before the registry it registers in'


class TestAViewIsChromeOnly:
    """The rule: a view decides layout, never meaning."""

    def test_no_view_builds_its_own_action_buttons(self):
        """The one that is not cosmetic. The credentials_* permissions become buttons inside
        _credActionsHtml; a view that assembled its own would be free to offer Delete to a
        user who may not press it."""
        for name, path in VIEW_FILES.items():
            body = _strip_comments(_read(path))
            for wired in ('deleteCred(', 'cloneCred(', 'openEditCredModal('):
                assert wired not in body, (
                    f'{name} wires {wired} itself instead of composing _credActionsHtml')

    def test_the_table_composes_the_same_builder(self):
        """Including the table: the moment one of the four builds its own buttons, "which
        buttons does a credential have" has two answers."""
        src = _strip_comments(_read(LIST))
        assert re.search(r'actions:\s*\(uid, ctx\)\s*=>\s*_credActionsHtml\(', src), \
            'the table no longer composes the shared action builder'

    def test_the_permissions_are_asked_in_one_place(self):
        """canEdit/canAdd/canDelete are resolved in prepare() and turned into controls in
        exactly one function."""
        views = _strip_comments(_read(VIEWS))
        assert views.count('function _credActionsHtml') == 1
        body = _fn(views, '_credActionsHtml')
        for flag in ('ctx.canEdit', 'ctx.canAdd', 'ctx.canDelete'):
            assert flag in body, f'{flag} is no longer decided here'
        for name, path in VIEW_FILES.items():
            assert 'currentUser.permissions' not in _strip_comments(_read(path)), (
                f'{name} reads the permission set itself instead of using the prepared ctx')

    def test_no_view_picks_the_type_colour_itself(self):
        """A type's colour comes from the hash the Overview widget uses, so a type wears one
        colour panel-wide — including types this build has never seen, since a module brings
        its own. A view reaching for the palette itself is free to drift from it."""
        for name, path in VIEW_FILES.items():
            body = _strip_comments(_read(path))
            assert '_dwCredBadgeCls' not in body, f'{name} colours the type itself'
        for name in ('cards', 'usage'):
            assert '_credTypeBadge(' in _strip_comments(_read(VIEW_FILES[name])), (
                f'{name} no longer composes the shared type badge')


class TestTheFourViewsShareOnePage:

    def test_the_non_table_views_go_through_the_factory(self):
        """Filtering, sorting and pagination stay in createListTable. A view that fetched or
        filtered on its own could show a different set of rows than the pagination band above
        it claims."""
        src = _strip_comments(_read(LIST))
        assert 'cardsBody: (uids, ctx, all) => _credViewBody(uids, ctx, all)' in src
        assert 'bodyMode: () => _credBodyMode()' in src

    def test_the_grouped_views_are_summaries_not_pages(self):
        """They count things — how many of each type, how many orphans — and a count over one
        page is a statement about the pagination instead: three SSH credentials when there
        are ten, and a different three on the next page. The factory hands a `summary` body
        every filtered row and drops the pagination bands."""
        src = _strip_comments(_read(VIEWS))
        reg = src[src.index('const CREDENTIAL_VIEWS'):]
        reg = reg[:reg.index('];')]
        for line in reg.splitlines():
            for vid in ('types', 'usage'):
                if f"id: '{vid}'" in line:
                    assert "mode: 'summary'" in line, f'{vid} is drawn as a page again'
        assert "v.mode === 'summary' ? allUids : uids" in _fn(src, '_credViewBody')

    def test_no_view_fetches_the_catalogue_again(self):
        """Every view reads the same `credentialsData`. The usage map is the one extra fetch
        and it is a different fact, asked once, in the shared core."""
        for name, path in VIEW_FILES.items():
            body = _strip_comments(_read(path))
            assert "apiGet('/api/v1/credentials'" not in body, name

    def test_the_switcher_is_drawn_by_the_header_not_the_views(self):
        src = _strip_comments(_read(LIST))
        assert 'headerLead: () => _credViewSwitcher()' in src
        for name, path in VIEW_FILES.items():
            assert '_credViewSwitcher' not in _strip_comments(_read(path)), name

    def test_the_column_chooser_belongs_to_the_table(self):
        """It configures columns; the other three have none."""
        src = _strip_comments(_read(LIST))
        assert "showChooser: mode => mode === 'table'" in src

    def test_the_choice_is_remembered_both_ways(self):
        """Locally for this browser, and in the user's table config so it follows them to the
        next one — persistExtra writes it, applyExtra reads it back."""
        views = _strip_comments(_read(VIEWS))
        assert 'localStorage.setItem(_CRED_VIEW_KEY' in views
        assert 'localStorage.getItem(_CRED_VIEW_KEY' in views
        src = _strip_comments(_read(LIST))
        assert 'persistExtra: () => ({ view: _credViewId() })' in src
        assert 'applyExtra:' in src and '_credApplyView' in src

    def test_switching_view_does_not_refetch(self):
        body = _fn(_strip_comments(_read(VIEWS)), 'setCredentialsView')
        assert 'renderCredentials()' in body
        assert 'apiGet' not in body and 'loadCredentials' not in body


class TestASelectionYouCannotSee:

    def test_the_grouped_views_declare_that_they_do_not_select(self):
        src = _strip_comments(_read(VIEWS))
        reg = src[src.index('const CREDENTIAL_VIEWS'):]
        reg = reg[:reg.index('];')]
        for line in reg.splitlines():
            for vid in ('types', 'usage'):
                if f"id: '{vid}'" in line:
                    assert 'select: false' in line, f'{vid} claims it can show a selection'
            for vid in ('table', 'cards'):
                if f"id: '{vid}'" in line:
                    assert 'select: true' in line, f'{vid} draws checkboxes but says otherwise'

    def test_switching_to_one_of_them_clears_the_selection(self):
        """Otherwise the bulk bar stays armed over rows that are no longer on screen, and the
        next click deletes something the user cannot see."""
        body = _fn(_strip_comments(_read(VIEWS)), 'setCredentialsView')
        assert '_selectedCredentials.clear()' in body
        assert 'v.select' in body, 'the clear no longer keys off the view that can show it'


class TestUsageIsADifferentFact:
    """Who references a credential is not part of the credential."""

    def test_it_is_asked_once_for_the_whole_catalogue(self):
        """Not once per row: the server walks every host profile and every module check
        whichever way it is asked, so N calls repeat one scan N times."""
        views = _strip_comments(_read(VIEWS))
        assert "apiGet('/api/v1/credentials/usage')" in views
        assert 'apiGet' not in _strip_comments(_read(VIEW_FILES['usage'])), \
            'the usage view fetches on its own again — per credential is the shape to avoid'

    def test_never_loaded_is_not_drawn_as_loaded_and_empty(self):
        """A question nobody asked and the answer "nothing uses this" would otherwise look
        alike — and the second one is a call to action."""
        body = _fn(_strip_comments(_read(VIEW_FILES['usage'])), '_credViewUsage')
        assert '_credEnsureUsage()' in body
        assert '_credUsagePending()' in body

    def test_a_failed_fetch_does_not_retry_itself(self):
        """_credEnsureUsage runs from render() and its fetch redraws when it lands, so
        retrying on error would be request → redraw → request against a server already
        saying no."""
        body = _fn(_strip_comments(_read(VIEWS)), '_credEnsureUsage')
        assert "_credUsageState === 'error'" in body, 'the error state re-arms the fetch'

    def test_a_refresh_drops_the_cached_map(self):
        """It can go stale for reasons the catalogue never sees — a host or a check edited in
        another section — so every path that refetches the catalogue invalidates it."""
        body = _fn(_strip_comments(_read(PICKER)), 'loadCredentials')
        assert '_credInvalidateUsage()' in body

    def test_the_orphan_count_is_catalogue_wide(self):
        """Counted over the page it would shrink as the user pages through, which is worse
        than not counting at all."""
        body = _fn(_strip_comments(_read(VIEWS)), '_credOrphanUids')
        assert 'credentialsData' in body, 'the orphan count reads the page instead of the set'

    def test_the_rows_keep_the_sort_the_user_chose(self):
        """Floating the unused ones to the top reads well and silently overrides the table's
        sort. The badge says the same thing without moving anything."""
        body = _strip_comments(_read(VIEW_FILES['usage']))
        assert '.sort(' not in body, 'the usage view re-sorts the page under the user'
        assert "t('cred_unused')" in body, 'nothing marks the unused rows any more'


class TestGroupingTellsTheTruth:

    def test_the_empty_types_line_is_computed_over_the_catalogue(self):
        """"No credentials of this type" is a statement about the installation. Computed over
        the page it would change as you page, which would make it a lie."""
        body = _fn(_strip_comments(_read(VIEW_FILES['types'])), '_credUnusedTypesNote')
        assert 'credentialsData' in body
        assert '_credTypeKeys()' in body

    def test_a_type_no_module_declares_any_more_is_still_shown(self):
        """A module was removed and its credentials outlived it — exactly the case worth
        seeing rather than dropping on the floor."""
        body = _strip_comments(_read(VIEW_FILES['types']))
        assert '!known.includes(ct)' in body
        assert 'cred_type_unknown' in body


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for vid in ('table', 'cards', 'types', 'usage'):
                assert f"'cred_view_{vid}':" in src, f'{lang} does not name the {vid} view'

    def test_the_usage_wording_exists_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for key in ('cred_usage_loading', 'cred_usage_error', 'cred_unused',
                        'cred_unused_n', 'cred_all_used', 'cred_types_empty',
                        'cred_type_unknown'):
                assert f"'{key}':" in src, f'{lang} is missing {key}'

    def test_the_orphan_banner_takes_both_numbers(self):
        """"3 unused" alone is unreadable — 3 out of 4 and 3 out of 400 are different news."""
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            m = re.search(r"'cred_unused_n':\s*'([^']*)'", src)
            assert m, lang
            assert m.group(1).count('{}') == 2, f'{lang}: cred_unused_n lost a placeholder'


class TestTheViewModeRestoreIsRegistryDriven:
    """Sessions used to be restored by a hardcoded `tc.sessions.view` line, so every table
    that grew a second preference had to edit the persistence layer. Now the table declares
    both directions and the loop calls them."""

    def test_the_persistence_loop_calls_the_table_back(self):
        src = _strip_comments(_read(os.path.join(TPL, 'partials', 'init', '_persistence.html')))
        body = _fn(src, '_applyUserTableConfig')
        assert 'td.applyExtra(cfg)' in body
        assert 'td.applyExtra({})' in body, 'a cleared layout no longer resets the view mode'
        # Restoring one named table by hand here is the shape this replaced: the next table
        # with a second preference would have had to come and edit this function too.
        assert '_sessionsViewMode' not in body, 'the hardcoded sessions restore came back'
        assert '_credViewMode' not in body, 'credentials grew a hardcoded restore of its own'

    def test_the_factory_carries_it_from_the_spec_to_the_loop(self):
        lt = _strip_comments(_read(os.path.join(TPL, 'partials', 'core', '_list_table.html')))
        assert 'applyExtra: spec.applyExtra' in lt
        pers = _strip_comments(_read(os.path.join(TPL, 'partials', 'init', '_persistence.html')))
        assert 'applyExtra: d.applyExtra' in pers

    def test_both_tables_that_persist_a_view_declare_the_way_back(self):
        for rel in (('sessions', '_list.html'), ('credentials', '_list.html')):
            src = _strip_comments(_read(os.path.join(TPL, 'partials', *rel)))
            assert 'persistExtra:' in src and 'applyExtra:' in src, rel
