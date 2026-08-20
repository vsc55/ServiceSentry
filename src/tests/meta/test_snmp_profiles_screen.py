#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The device-profile screen — the wiring that makes a catalogue visible.

A watchful ships its own UI as three files a convention picks up, and a screen made of them
fails in ways Python never sees: a modal whose id the JS looks up but the HTML never declares
is a button that does nothing; a picker registered against a path that no field ever has is a
field with no button; a string the JS asks for and no language file holds is a label that
reads as its own key.

This file pins the two things that decide whether the catalogue is reachable at all — the
screen is wired, and the FIELD that assigns profiles exists and is drawn as a list — and the
one property that makes assignment mean anything: the profiles are declared per DEVICE, which
is why a server, a switch and a NAS can carry different ones.
"""

import io
import json
import os
import re

from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
SNMP = os.path.join(SRC, 'watchfuls', 'snmp')
WEB = os.path.join(SNMP, 'web')
UI = os.path.join(WEB, 'profiles_ui.html')
MODALS = os.path.join(WEB, 'profiles_modals.html')
FIELD_RENDER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                            'core', '_field_render.html')
HOST_MODAL = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                          'servers', '_save.html')

# The field that carries the assignment, and the key a picker must be registered under for
# the renderer to find it (see _schemaKeyOf: the item's uid is dropped).
FIELD = 'device_profiles'
PICKER_KEY = 'snmp|servers|device_profiles'


def _schema():
    with io.open(os.path.join(SNMP, 'schema.json'), encoding='utf-8') as fh:
        return json.load(fh)


def _lang(code):
    with io.open(os.path.join(SNMP, 'lang', f'{code}.json'), encoding='utf-8') as fh:
        return json.load(fh)


class TestTheScreenIsWired:

    def test_the_files_are_named_so_the_convention_picks_them_up(self):
        """web_admin routes a module's UI files by SUFFIX (`*_ui.html` into the script block,
        `*_modals.html` before </body>). A file named anything else is simply never injected,
        and the failure is a button that does nothing."""
        assert os.path.isfile(UI) and UI.endswith('_ui.html')
        assert os.path.isfile(MODALS) and MODALS.endswith('_modals.html')

    def test_every_element_the_script_looks_up_exists_in_the_markup(self):
        """`getElementById` on a missing id returns null, and this screen fills a dozen of
        them by hand. The failure is a modal that opens empty."""
        js, html = _read(UI), _read(MODALS)
        wanted = set(re.findall(r"getElementById\('(snmpProfiles\w+)'\)", js))
        assert wanted, 'the script looks up no element of its own modal'
        for eid in sorted(wanted):
            assert f'id="{eid}"' in html, f'{eid} is looked up but never declared'

    def test_the_toolbar_button_calls_a_function_that_exists(self):
        """The module declares the button; nothing in the core knows what it opens."""
        init = _read(os.path.join(SNMP, '__init__.py'))
        assert "'onclick': 'openSnmpProfilesModal'" in init
        assert 'function openSnmpProfilesModal(' in _read(UI)

    def test_both_actions_are_declared_and_read_only(self):
        """An action absent from WATCHFUL_ACTIONS is a 404, and one absent from
        READ_ONLY_ACTIONS demands edit rights to LOOK at the catalogue — and writes an audit
        entry for every look."""
        init = _read(os.path.join(SNMP, '__init__.py'))
        actions = init.split('WATCHFUL_ACTIONS')[1].split('})')[0]
        read_only = init.split('READ_ONLY_ACTIONS')[1].split('})')[0]
        for name in ('list_profiles', 'detect_profiles'):
            assert f"'{name}'" in actions, f'{name} is not callable'
            assert f"'{name}'" in read_only, f'{name} demands edit rights to read'


class TestTheFieldThatAssignsThem:

    def test_the_device_carries_its_profiles(self):
        """On the SERVER and not on a check: what a machine IS does not change because
        somebody added a fourth OID check to it."""
        servers = _schema()['servers']
        assert FIELD in servers
        assert FIELD in servers['__field_order__'], 'declared but never drawn'

    def test_it_is_a_list_and_not_a_choice(self):
        """A NAS is the generic profile plus the interfaces plus its own disks. One profile
        per device would mean one monolithic profile per model, which is how a catalogue
        becomes unmaintainable."""
        meta = _schema()['servers'][FIELD]
        assert meta.get('multi') is True
        assert meta.get('default') == ''

    def test_the_picker_is_registered_against_the_kind_of_field(self):
        """Not against one item's path: every server draws this same field and each has its
        own uid in the path, so a per-item registration would never match anything."""
        js = _read(UI)
        assert f"FIELD_PICKERS['{PICKER_KEY}']" in js

    def test_the_renderer_finds_a_picker_by_that_key(self):
        """`_schemaKeyOf` drops the item uids, which is what turns a path into the identity a
        registration can be written against."""
        js = _strip_comments(_read(FIELD_RENDER))
        assert 'FIELD_PICKERS[_schemaKeyOf(pathStr)]' in js

    def test_a_multi_value_field_can_have_a_picker_too(self):
        """The chips branch used to return before the picker was even looked up, so several
        values meant typing them — and a profile id typed from memory is a device that
        measures nothing until somebody notices the spelling."""
        js = _strip_comments(_read(FIELD_RENDER))
        multi = js.split("kind: 'multi', key: pathStr")[1].split('_fieldRow')[0]
        assert '_mFp' in multi or '_fieldPickerBtn' in multi


class TestTheHostModalIsWhereItIsActuallyBound:
    """The Modules tab edits a module's own config; the host modal is where somebody says
    "this box is a NAS". It draws the same schema fields through a DIFFERENT renderer, and
    that renderer knew nothing about multi-value fields or pickers — so the field that had
    chips and a picker on one screen was a bare text box on the one that matters.
    """

    def test_a_multi_value_field_is_chips_here_too(self):
        """A list rendered as a text box is a list nobody can pick from, and the values are
        ids: typed from memory, a misspelt one is a device that measures nothing."""
        js = _strip_comments(_read(HOST_MODAL))
        assert 'f.multi' in js, 'the host modal ignores schema multi fields'
        multi = js.split('f.multi')[1].split('return fieldCtl')[1].split(');')[0]
        assert "kind: 'multi'" in multi

    def test_it_offers_the_picker_from_the_same_registry(self):
        """One registration has to serve both panes; a second registry would be two places
        for the same module to be wrong in."""
        js = _strip_comments(_read(HOST_MODAL))
        assert '_fieldPickerFor(' in js
        assert 'function _hostFieldPickerOpen(' in js

    def test_the_key_is_module_collection_field(self):
        """The same identity the Modules tab arrives at through _schemaKeyOf. A host draft has
        no path into modulesData, so the key has to be built rather than derived."""
        js = _strip_comments(_read(HOST_MODAL))
        fn = _fn(js, '_hostFieldSchemaKey')
        assert 'collection' in fn and '${mod}|${coll}|${name}' in fn

    def test_the_picker_is_opened_with_a_callback(self):
        """The host modal edits a draft that has not been saved: a picker that wrote straight
        into modulesData would put the value somewhere this pane never reads, and the field
        would come back empty the moment the modal repainted."""
        js = _strip_comments(_read(HOST_MODAL))
        fn = _fn(js, '_hostFieldPickerOpen')
        assert 'fp.open(' in fn and '_setHostCheckField(' in fn

    def test_the_profile_picker_honours_that_callback(self):
        """Otherwise the button opens, the ticks look right, and nothing is bound."""
        fn = _fn(_strip_comments(_read(UI)), '_snmpProfCommit')
        assert '_snmpProfOnPick' in fn
        assert fn.index('_snmpProfOnPick') < fn.index("updateField('modules'"), (
            'the callback must win over the modulesData path, not the other way round')


class TestNothingReadsAsItsOwnKey:

    def test_every_string_the_screen_asks_for_exists_in_both_languages(self):
        """A missing key falls back to the literal key, which puts `profile_src_shipped` on
        screen where a word belongs."""
        js = _read(UI)
        keys = set(re.findall(r"_snmpProfT\('(\w+)'", js))
        keys |= set(re.findall(r"_modUiStr\('snmp', '(\w+)'", js))
        assert keys, 'the screen asks for no translated string at all'
        for code in ('es_ES', 'en_EN'):
            ui = _lang(code).get('ui') or {}
            missing = sorted(k for k in keys if not ui.get(k))
            assert not missing, f'{code} is missing {missing}'

    def test_the_field_is_named_and_explained_in_both_languages(self):
        """An option whose label is missing shows its storage path, and one with no hint
        leaves "what do I put here" to be answered from the source."""
        for code in ('es_ES', 'en_EN'):
            data = _lang(code)
            assert (data.get('labels') or {}).get(FIELD), f'{code}: no label'
            assert (data.get('hints') or {}).get(FIELD), f'{code}: no hint'
            assert (data.get('group_labels') or {}).get(
                _schema()['servers'][FIELD]['group']), f'{code}: the group has no name'
