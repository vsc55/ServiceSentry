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
# The engine is core now; the module keeps the check and its schema. Each source is
# named once, so the next move is a line rather than a hunt.
CORE_SNMP = os.path.join(SRC, 'lib', 'core', 'snmp')
ACTIONS = os.path.join(CORE_SNMP, 'actions.py')
PROFILES = os.path.join(CORE_SNMP, 'profiles.py')
SAMPLER = os.path.join(CORE_SNMP, 'sampler.py')
WEB = os.path.join(CORE_SNMP, 'web')
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

def _snmp_actions():
    """``(ACTIONS, READ_ONLY)`` — the operations the panel may invoke, and which change
    nothing.  Declared in ``lib/core/snmp/manifest.py`` since the library and the catalogue
    stopped being a check's business; asked of it rather than sliced out of source text,
    which is what these guards used to do when the only place to declare them was a module."""
    from lib.core.snmp.manifest import ACTIONS, READ_ONLY      # noqa: PLC0415
    return ACTIONS, READ_ONLY




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
        # Through the resolver now, and each name exists TWICE — once in the dialog and
        # once in the view, which is what the suffix is for.
        wanted = set(re.findall(r"_profEl\('(snmpProfiles\w+)'\)", js))
        wanted |= set(re.findall(r"getElementById\('(snmpProfiles\w+)'\)", js))
        assert wanted, 'the script looks up no element of its own screen'
        for eid in sorted(wanted):
            assert f'id="{eid}"' in html, f'{eid} is looked up but never declared'
            # …except the ones that only make sense with a device on the other end. The
            # catalogue is the reference: there is nothing to ask, so there is no Detect and
            # nowhere to put its answer, and the lookups return null and do nothing.
            if eid not in ('snmpProfilesModal', 'snmpProfilesDetectBtn',
                           'snmpProfilesDetectLabel', 'snmpProfilesDetected'):
                assert f'id="{eid}View"' in html, f'{eid} has no copy in the view'

    def test_the_catalogue_is_a_view_and_not_a_button_on_a_card(self):
        """It was a button on the module's card in Modules, throwing a dialog over whatever
        was on screen. A card in a list of modules is where you configure a module, not where
        you read its reference — so the catalogue is a view of the SNMP section, declared the
        way the other four are, and the module ships no toolbar at all any more."""
        from lib.core.snmp.manifest import PAGE          # noqa: PLC0415
        init = _read(os.path.join(SNMP, '__init__.py'))
        assert 'WATCHFUL_TOOLBAR: tuple[dict, ...] = ()' in init, \
            'the module card launches screens again'
        assert 'profiles' in [v['slug'] for v in PAGE['views']]
        assert 'function _snmpProfViewLoad(' in _read(UI)

    def test_the_picker_is_still_a_dialog(self):
        """One list read twice, and the second reading is a question a server's field asks —
        opened from inside another dialog, over the screen that asked. Only that one shows a
        modal, and it says which copy it is drawing before anything is looked up."""
        js = _read(UI)
        body = _fn(js, '_snmpProfOpen')
        assert 'if (pathStr) _snmpProfScope' in body, 'the picker can draw into the view'
        assert 'if (_snmpProfPath) {' in body, 'the catalogue still opens a dialog'

    def test_the_catalogue_has_the_panel_s_rail_and_the_picker_does_not(self):
        """Twenty-seven rows of which three are groups read as one list of twenty-seven, which
        is what a group exists not to be. The rail is the same one the library uses — one
        selected line, mutually exclusive — and it answers the two questions this list is
        asked: what an entry IS, and which group holds it.

        The picker keeps the plain list on purpose. It is a dialog opened from a field of a
        server to make one assignment, and a navigation column inside it would be a second
        place to get lost in on the way to ticking a box."""
        js, html = _read(UI), _read(MODALS)
        assert 'function _snmpProfRailPaint(' in js
        assert "getElementById('snmpProfRailBody')" in js
        # The body is raised by the shared shell, not built into the template — a rail in the
        # markup would be inside the pane it is supposed to sit beside.
        assert 'snmpProfRailBody' not in html
        assert '_snmpProfRailPaint()' in _fn(js, '_snmpProfRender')

    def test_the_rail_is_one_choice_and_never_two(self):
        """A column where some lines are a choice and others are switches behaves in two ways
        without saying so. This list is only ever asked "which of them"."""
        js = _read(UI)
        assert 'let _snmpProfRail ' in js, 'the selection is not a single value'
        assert '_snmpProfRail = key' in _fn(js, '_snmpProfSetRail')

    def test_a_line_that_would_filter_nothing_is_not_drawn(self):
        """"Not in any group" with no groups is a line that says what "All" says; a Source
        block whose every line reads "Shipped" filters nothing. Both are noise that looks like
        navigation."""
        body = _fn(_read(UI), '_snmpProfRailDefs')
        assert 'groups.length && loose.length' in body
        assert 'bySource.length < 2' in body

    def test_the_count_says_what_is_on_screen(self):
        """Saying "27" while nine rows are drawn is the count answering somebody else's
        question. On the picker it stays the other number — how many are ticked — because
        that is what somebody assigning profiles is keeping track of."""
        body = _fn(_read(UI), '_snmpProfRender')
        assert 'rows.length === _snmpProfItems.length' in body
        assert '_snmpProfSel.size' in body

    def test_the_list_says_where_the_groups_end(self):
        """Only while both kinds are on screen: under a rail line that already says which kind
        this is, a heading would be repeating the rail."""
        body = _fn(_read(UI), '_snmpProfRender')
        assert 'const mixed =' in body and 'rows.some(_snmpProfIsGroup)' in body

    def test_the_picker_starts_from_everything(self):
        """It has no rail and no way to change it, so a line left selected in the catalogue
        would be a picker silently hiding most of the catalogue."""
        assert '_snmpProfRail = ' in _fn(_read(UI), '_snmpProfOpen')

    def test_the_panel_writes_profiles_and_not_only_groups(self):
        """Writing a profile used to mean putting a JSON file on the machine, which rules it
        out for the box in the rack nobody wrote a profile for — the person who has that box
        is not always the person with a shell on the server. Both buttons are on the
        catalogue and neither is in the picker: a field of a server is where an assignment is
        made, not where the catalogue is decided."""
        js, html = _read(UI), _read(MODALS)
        assert 'id="snmpPrfNewBtn"' in html and 'id="snmpGrpNewBtn"' in html
        assert 'function _snmpPrfOpen(' in js and 'function _snmpPrfSave(' in js
        assert "_snmpProfPath ? 'none' : ''" in _fn(js, '_snmpProfOpen'), \
            'the picker offers to edit the catalogue'

    def test_the_form_is_checked_by_the_thing_that_reads_the_shipped_files(self):
        """One authority on what a profile is. The action hands the document to
        `profiles.normalise`, and the reason a metric was refused is asked for only AFTER
        `normalise_metric` has already said no — so the explanation cannot drift into
        disagreeing with the verdict."""
        acts = _read(ACTIONS)
        # `_fn` reads JavaScript; this one is Python, so the method is sliced out by hand.
        start = acts.index('    def save_profile(cls')
        body = acts[start:acts.index('    # ── Taking one back', start)]
        assert '_profiles.normalise_metric(m)' in body
        assert 'cls._metric_why(m)' in body
        assert 'if norm is None' in body, 'the reason is asked before the verdict'
        assert '_profiles.normalise(body) is None' in body

    def test_typing_never_redraws_the_metrics(self):
        """The inputs are the working copy. Anything that re-draws the list — adding a row,
        removing one, switching a value to a column — harvests them first, or it throws away
        whatever was being typed. A keystroke redrawing would take the cursor with it."""
        js = _read(UI)
        for fn in ('_snmpPrfAddMetric', '_snmpPrfDropMetric', '_snmpPrfToggleAdv',
                   '_snmpPrfSave'):
            assert '_snmpPrfHarvest()' in _fn(js, fn), f'{fn} redraws over what was typed'
        assert 'oninput="_snmpPrfRedraw' not in js, 'a keystroke redraws the list'

    def test_a_field_that_is_not_on_screen_keeps_what_it_had(self):
        """The less-used fields live behind a toggle. Rebuilding each metric from the inputs
        alone threw them away the moment anything redrew — and losing `width` on a 32-bit
        counter is not cosmetic: it is what tells a counter wrapping around from a device that
        rebooted, and without it every wrap is a four-billion spike that rescales the chart.

        An EMPTY input is not the same thing. That is somebody clearing a field."""
        body = _fn(_read(UI), '_snmpPrfHarvest')
        assert 'if (!el(f)) continue;' in body, 'a hidden field is harvested as empty'
        assert 'if (v(f)) m[f] = v(f); else delete m[f];' in body, 'a cleared field survives'
        # …and switching a column back to a single value leaves the column that named its
        # rows meaning nothing, so those go with it.
        assert "['index_label', 'scale_by', 'group'].includes(f)" in body

    def test_a_group_can_be_cloned_and_the_clone_is_a_new_one(self):
        """The shipped groups cannot be edited — a release would take the change back — so
        cloning is how an installation gets one of its own, and the case is the common one:
        "everything a Synology answers, minus the two profiles this model has not got".
        Twenty-three ticks against two clicks, and no way to notice a box left unticked.

        The membership travels; the identity does not. A clone that kept the id would not be
        a clone, it would be a failed save."""
        js = _strip_comments(_read(UI))
        body = _fn(js, '_snmpGrpOpen')
        assert 'function _snmpGrpOpen(gid, copy)' in js, 'the group form cannot be opened as a copy'
        assert "_snmpGrpEditing = (cur && !copy)" in body, 'a clone would overwrite the original'
        assert "profile_copy" in body and '_snmpGrpNameInput()' in body
        assert "cur.includes" in body, 'the clone starts empty'
        # …and the button is on the row, for groups as well as profiles.
        assert 'const dup = !pick;' in js, 'groups are not offered the duplicate button'
        assert '_snmpGrpOpen(${jsStr(p.id)}, true)' in _read(UI)

    def test_a_copy_carries_the_matrix_and_not_the_identity(self):
        """An OID matrix from a blank form is an afternoon; the same matrix with three OIDs
        changed is five minutes. What must NOT come along is how the original is recognised —
        two profiles claiming one device is a detection proposing the same thing twice."""
        body = _fn(_read(UI), '_snmpPrfOpen')
        assert "set('snmpPrfPrefix', (cur && !copy)" in body
        assert "set('snmpPrfProbe', (cur && !copy)" in body
        assert 'JSON.parse(JSON.stringify(cur.metrics' in body, \
            'the copy shares the original metric objects'

    def test_the_path_to_the_profile_folder_is_gone_from_the_screen(self):
        """It was the answer to "and how do I add one" when the only answer was a file on the
        machine. There are two buttons now, so it was a line that answered nothing anybody
        asks while looking at it."""
        js, html = _read(UI), _read(MODALS)
        assert 'snmpProfilesDir' not in html and 'snmpProfilesDir' not in js

    def test_an_oid_is_chosen_and_not_remembered(self):
        """Typing `1.3.6.1.4.1.6574.2.1.1.6` from memory is how a profile ends up measuring
        nothing and saying nothing about it: every digit is load-bearing and none is checked
        by anything until a device answers, or does not. The MIBs are compiled and their
        symbols are already in a catalogue, so all three OID fields ask them."""
        js, html = _read(UI), _read(MODALS)
        assert 'id="snmpOidPickModal"' in html
        assert 'function _snmpOidPick(' in js
        body = _fn(js, '_snmpPrfRender')
        for field in ("'oid'", "'index_label'", "'scale_by'"):
            assert f'_snmpPrfOidField(i, {field}' in body, f'{field} is typed from memory'

    def test_what_a_pick_adds_over_a_paste_is_the_syntax(self):
        """A symbol carries its SMI type, and that is what says whether the value is a counter
        — and how wide — a gauge, or not a number at all. It is the one thing about a metric
        nobody gets right from the OID, and the one that turns a counter wrapping around into
        a device that rebooted."""
        body = _fn(_read(UI), '_snmpOidMetricFrom')
        assert "out.kind = 'counter'; out.width = 64" in body
        assert "out.kind = 'counter'; out.width = 32" in body
        assert "out.kind = 'text'; out.chart = 'none'" in body

    def test_a_scalar_is_asked_for_its_instance(self):
        """A scalar's OID names the OBJECT; what an agent answers is its single instance,
        `.0`. Left off, the metric asks for a node and gets nothing — the most common way a
        hand-written profile is silently empty."""
        body = _fn(_read(UI), '_snmpOidMetricFrom')
        assert "{oid: sy.oid + '.0'}" in body
        assert '{walk: sy.oid}' in body, 'a table column is asked for an instance too'

    def test_only_what_can_be_read_is_offered(self):
        """A table and its row are structure, an object group is paperwork, and a
        not-accessible column is one the agent will never answer. Offering any of them is
        offering a metric that returns nothing for ever."""
        body = _fn(_read(UI), '_snmpOidUsable')
        assert "'MibScalar'" in body and "'MibTableColumn'" in body
        assert "!== 'not-accessible'" in body

    def test_the_column_that_names_the_rows_is_looked_for_among_the_siblings(self):
        """It is a column of THAT table. Nine thousand symbols is not a list to search for one
        of five siblings."""
        body = _fn(_read(UI), '_snmpOidPick')
        assert "field !== 'oid' && m.walk" in body
        assert "_snmpOidScope" in _fn(_read(UI), '_snmpOidRows')

    def test_the_two_copies_cannot_be_confused(self):
        """Both can be in the document at once. Two live copies of an id is a control that
        fills one box and reads the other, so the view suffixes its ids and every lookup
        goes through the resolver."""
        js, html = _read(UI), _read(MODALS)
        assert 'const _profEl = id =>' in js
        assert "document.getElementById('snmpProfilesBody')" not in js, \
            'a lookup bypasses the resolver'
        for eid in ('snmpProfilesBodyView', 'snmpProfilesSearchView', 'snmpProfilesTitleView'):
            assert f'id="{eid}"' in html, f'{eid} is not in the view template'

    def test_both_actions_are_declared_and_read_only(self):
        """An action absent from WATCHFUL_ACTIONS is a 404, and one absent from
        READ_ONLY_ACTIONS demands edit rights to LOOK at the catalogue — and writes an audit
        entry for every look."""
        actions, read_only = _snmp_actions()
        for name in ('list_profiles', 'detect_profiles'):
            assert name in actions, f'{name} is not callable'
            assert name in read_only, f'{name} demands edit rights to read'


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


class TestTheDeviceIsWhereTheDeviceIsConfigured:
    """What a device IS — the profiles it carries and who you have to be to ask it — is a
    property of the device, so it is edited on the host, not on each check bound to it.

    That moves the same field onto a third renderer: the per-protocol PROFILE form, which
    has no check index to hang a value on and, until now, no identity of its own to speak of
    — SSH was the only profile that carried a credential, which read like a rule and was
    only ever a consequence of being the only one with anything to carry.
    """

    def test_the_snmp_profile_carries_the_identity_not_just_the_address(self):
        hp = _schema().get('__host_profile__') or {}
        fields = set(hp.get('fields') or [])
        assert hp.get('key') == 'snmp' and hp.get('address_field') == 'host'
        assert {'community', 'version', 'device_profiles'} <= fields
        # …and NOT how long we wait for it: two entries for one box would then migrate
        # into two hosts because one of them had a longer timeout.
        assert not ({'timeout', 'retries'} & fields)

    def test_a_multi_value_field_works_on_a_profile_too(self):
        """The check branch keys its adapter on `mod|idx|field`; a profile has no idx, so
        without a branch of its own the field falls through to a text box holding a
        comma-separated list — which looks editable and is the one thing nobody should
        type by hand."""
        js = _strip_comments(_read(HOST_MODAL))
        assert 'ctx.idx == null && ctx.proto' in js, 'no profile branch for multi fields'
        branch = js.split('ctx.idx == null && ctx.proto')[1].split('return fieldCtl')[1]
        assert "kind: 'multi'" in branch.split(');')[0]
        assert '_setProfileField(' in _fn(js, '_hostProfilePickerOpen')

    def test_the_actions_beside_the_picker_come_with_it(self):
        """The picker and "test against the device" are registered together against the same
        field; a pane that drew one and not the other would answer "which profiles" and not
        "and does the device agree", which is the half that is not guessable."""
        js = _strip_comments(_read(HOST_MODAL))
        fn = _fn(js, '_hostProfilePickerBtn')
        assert 'fp.actions' in fn and '_hostProfileActionRun' in fn

    def test_an_action_run_from_a_host_says_which_device(self):
        """A form the user is in the middle of filling in IS the device under test — and its
        secrets are masks, so the draft travels and the server resolves it exactly as it
        resolves a scheduled check."""
        js = _strip_comments(_read(HOST_MODAL))
        fn = _fn(js, '_hostProfileActionCfg')
        assert '_host' in fn and 'host_uid' in fn and 'profiles' in fn

    def test_both_panes_reach_the_device_through_one_place(self):
        """`_snmpDeviceCfg` is state, and stale state here means asking the last host
        somebody looked at. Both entry points must set it — to a provider or to null."""
        js = _strip_comments(_read(UI))
        for fname in ('_snmpProfOpenFor', '_snmpTestOpen'):
            assert '_snmpDeviceCfg =' in _fn(js, fname), f'{fname} leaves it stale'
        # And everything that talks to the device reads it through the one resolver.
        for fname in ('_snmpProfDetect', '_snmpTestRun'):
            assert '_snmpCfgFor(' in _fn(js, fname), f'{fname} bypasses the resolver'
        assert 'getPath(modulesData' not in _fn(js, '_snmpTestRun')

    def test_the_profile_form_is_actually_drawn_somewhere(self):
        """`_renderProfileFields` existed, was correct, and **nobody called it**: the element
        it repaints (`hmProfFields_<proto>`) was only ever looked up, never created. The
        per-protocol section had been removed from the modal when the profiles were narrowed
        to an address, and the renderer stayed behind — so a widened profile would have been
        a form that renders perfectly into a page that never asks for it.

        Dead code that reads as live code is exactly what a guard is for: nothing failed, no
        test went red, and the screen simply had no connection form."""
        checks = _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers', '_checks.html')))
        monitoring = _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers', '_monitoring.html')))
        block = _fn(checks, '_hostProfileBlock')
        assert '_renderProfileFields(' in block, 'the block does not draw the fields'
        assert 'hmProfFields_' in block, 'nothing creates the element the repaint looks up'
        # Called from both card shapes — one check per host, and several.
        assert '_hostProfileBlock(' in _fn(checks, '_renderSingleCheck')
        assert '_hostProfileBlock(' in monitoring, 'multi-check cards draw no profile'
        # …and kept on the repaint, or editing a check silently drops the connection form.
        assert '_hostProfileBlock(' in _fn(checks, '_refreshSingleCheck')

    def test_a_credential_is_offered_for_any_protocol_that_declares_one(self):
        """SSH had a credential picker and nothing else did. The device's identity is the
        same kind of thing whatever the protocol, and an SNMP community reused across forty
        switches is exactly what the credential manager is for."""
        js = _strip_comments(_read(HOST_MODAL))
        fn = _fn(js, '_renderProfileFields')
        assert '_credTypeForModule(' in fn, 'the profile form knows only about ssh'
        assert "'cred_uid'" in fn and 'credentialOptions(' in fn
        # Picking one must clear the inline copy, or two places hold one secret and the
        # stale one wins the day somebody rotates the other.
        assert '_profileCredFields(' in _fn(js, '_setProfileField')


class TestTheChipsReadAsNames:
    """The field stores profile ids, which is the right thing to store — they survive a
    rename, they are what the API speaks and what a bug report quotes. They are not what a
    person reads: a row of `hr_storage`, `if_generic`, `ucd_linux` on a host form says nothing
    about what is being measured, by somebody who is deciding whether the assignment is right.
    """

    def test_the_chips_renderer_asks_for_a_label(self):
        js = _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'core', '_field_chips.html')))
        assert 'const CHIP_LABELS' in js
        assert '_chipLabel(key, v)' in js

    def test_the_key_is_module_and_field_so_both_panes_hit_it(self):
        """The Modules tab path carries the item's uid and the host modal's carries its index;
        neither is part of what the FIELD is, and a registry keyed by either would work on one
        screen and not the other."""
        js = _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'core', '_field_chips.html')))
        fn = _fn(js, '_chipLabelKey')
        assert 'parts[0]' in fn and 'parts[parts.length - 1]' in fn

    def test_the_module_registers_one_for_its_field(self):
        js = _read(UI)
        assert f"CHIP_LABELS['{PICKER_KEY.split('|')[0]}|{FIELD}']" in js

    def test_the_id_is_not_lost_when_a_name_replaces_it(self):
        """It is the string that identifies the profile everywhere else, so it stays in the
        tooltip rather than disappearing behind a translation."""
        js = _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'core', '_field_chips.html')))
        assert 'title="${escAttr(_tip)}"' in js

    def test_a_catalogue_that_cannot_be_read_leaves_the_ids(self):
        """Which is the old behaviour and a working screen — not a retry loop, and not chips
        that vanish."""
        fn = _fn(_strip_comments(_read(UI)), '_snmpProfNamesLoad')
        assert '_snmpProfNamesFrom((d && d.ok && d.items) || [])' in fn


class TestNothingReadsAsItsOwnKey:

    def test_every_string_the_screen_asks_for_exists_in_both_languages(self):
        """A missing key falls back to the literal key, which puts `profile_src_shipped` on
        screen where a word belongs."""
        js = _read(UI)
        keys = set(re.findall(r"_snmpProfT\('(\w+)'", js))
        keys |= set(re.findall(r"_snmpTestT\('(\w+)'", js))
        keys |= set(re.findall(r"_modUiStr\('snmp', '(\w+)'", js))
        # A key BUILT from a value (`'test_step_' + s.key`) is captured here as its bare
        # prefix, and the real key only exists at run time — the same exclusion the core
        # i18n guard makes, and the checklist has a guard of its own for exactly those.
        keys = {k for k in keys if not k.endswith('_')}
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


class TestTheMibManagerScreen:
    """Two ways the MIB manager misleads without erroring, both found on screen."""

    def test_a_source_with_no_folder_is_not_offered_as_one(self):
        """Synology publishes an archive of twenty MIBs; the mirror that hosts three of them
        is a dependency source for compiling, not the place to import from. Listed in the
        folder dropdown it looks like the main way in, and it is the small version."""
        js = _strip_comments(_read(os.path.join(WEB, '_ui.html')))
        block = js.split('function _mibPopulateRepoSelect')[1].split('function ')[0]
        assert 'if (!r.folder) continue' in block

    def test_the_import_report_is_read_at_the_height_of_the_page(self):
        """It used to cap itself: a first import is twenty "new" rows, and inside a dialog a
        list left to grow pushes the buttons that act on it off the bottom of the screen.

        The cap was the dialog's fault, and the dialog is gone — importing is a view of the
        section now, precisely because comparing against LibreNMS answers four thousand rows
        and no capped box is a way to read that. So the report fills instead: `.ss-vfill`
        down to one `.ss-vscroll`, header and count pinned, only the list scrolling."""
        js = _strip_comments(_read(os.path.join(WEB, '_ui.html')))
        fn = _fn(js, '_mibArchiveReport')
        assert 'ss-vfill' in fn and 'ss-vscroll' in fn
        assert 'ss-scroll-box' not in fn, 'still capped at the height of a dialog'
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-vfill' in css and '.ss-vscroll' in css, \
            'the chain the report relies on does not exist'

    def test_the_bounded_box_is_a_reusable_class_and_not_an_id(self):
        """The panel has one rule about layout CSS: a generic class, never a per-id rule."""
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '#mibArchiveResult' not in css


class TestTheDeviceGetsAskedWhetherItAgrees:
    """The assignment is wrong in two directions and the panel could only show one of them.

    A profile naming an OID the device does not serve leaves an empty chart, which somebody
    eventually notices. A device serving something no assigned profile names is INVISIBLE —
    nothing is missing on any screen, because nothing ever said it could be there. The second
    one is why the test walks the device instead of only reading what it was told to read,
    and it is the half these guards are about: it cannot be derived from the catalogue by
    anybody, so if the sweep goes, the screen quietly becomes half a screen that still looks
    complete.
    """

    def test_every_element_the_test_dialog_looks_up_exists_in_the_markup(self):
        """`getElementById` on a missing id returns null and the failure is silent: a dialog
        that opens with an empty body and no error anywhere."""
        js, html = _read(UI), _read(MODALS)
        wanted = set(re.findall(r"_snmpTestEl\('(snmpTest\w+)'\)", js))
        wanted |= set(re.findall(r"getElementById\('(snmpTest\w+)'\)", js))
        assert wanted, 'the dialog looks up no element of its own'
        for eid in sorted(wanted):
            assert f'id="{eid}"' in html, f'{eid} is looked up but never declared'

    def test_the_button_hangs_off_the_field_it_is_about(self):
        """Which profiles this device carries, and what the device makes of them, are the
        same subject. Anywhere else on the form it is a button whose subject the reader has
        to work out — and the renderer must not learn that one of its two hundred fields is
        a list of profiles, which is why it goes in the same registry as the picker."""
        js = _strip_comments(_read(UI))
        block = js.split("FIELD_PICKERS['snmp|servers|device_profiles']")[1].split('};')[0]
        assert 'actions:' in block and '_snmpTestOpen(' in block
        render = _read(FIELD_RENDER)
        assert 'fp.actions' in _fn(render, '_fieldPickerBtn'), \
            'the renderer draws no action a picker registers'

    def test_the_dialog_asks_the_moment_it_opens(self):
        """There is nothing to configure in it: the assignment is the question and it is on
        the screen behind. A dialog that opens empty with a button in the middle is one
        extra click on every single use."""
        assert '_snmpTestRun(' in _fn(_strip_comments(_read(UI)), '_snmpTestOpen')

    def test_a_late_answer_for_a_closed_dialog_is_dropped(self):
        """A sweep of a slow device outlives the dialog that asked for it, and two runs
        overlap the moment somebody presses it twice. The later answer must not paint over
        the newer one."""
        body = _fn(_strip_comments(_read(UI)), '_snmpTestRun')
        assert 'const gen = ++_snmpTestGen' in body
        assert 'if (gen !== _snmpTestGen)' in body

    def test_both_halves_are_reachable_and_neither_is_the_default_answer(self):
        """One of them is the question nobody could ask before. Buried behind the other it
        would go unread — so they are two switched views of one dialog, each saying how much
        it holds."""
        body = _fn(_strip_comments(_read(UI)), '_snmpTestRender')
        assert "_snmpTestGapHtml(d, q)" in body and "_snmpTestReadHtml(d, q)" in body
        assert "['gap'" in body or "'gap'," in body

    def test_the_dialog_watches_the_work_instead_of_waiting_for_it(self):
        """A NAS with a family group is a minute of work on a bad day, and a spinner held for
        a minute is indistinguishable from a hung screen. What somebody watching wants to know
        is WHICH step is slow — a fact the server had and was throwing away."""
        actions, read_only = _snmp_actions()
        for action in ('test_profiles_start', 'test_profiles_status'):
            assert action in actions, action
            assert action in read_only, action
        body = _fn(_strip_comments(_read(UI)), '_snmpTestRun')
        assert "'test_profiles_start'" in body and "'test_profiles_status'" in body
        assert 'st.done' in body, 'the poll never ends'

    def test_the_checklist_names_the_same_steps_the_server_reports(self):
        """The list is drawn whole before the first answer arrives, from a list of keys held
        in the JS — so a step added on one side and not the other is a line that never fills
        in, or one that fills in and is never drawn. Neither raises anything."""
        js = _read(UI)
        drawn = re.search(r'const _SNMP_TEST_STEPS = \[(.*?)\]', js, re.S).group(1)
        drawn = re.findall(r"'(\w+)'", drawn)
        acts = _read(ACTIONS)
        served = re.search(r"ORDER = \((.*?)\)", acts, re.S).group(1)
        assert drawn == re.findall(r"'(\w+)'", served), 'the two lists have drifted'

    def test_every_step_has_a_name_in_both_languages(self):
        """The labels are looked up by a key BUILT from the step id (`'test_step_' + key`), so
        the guard that reads literal `_snmpTestT('…')` calls cannot see them: a missing one
        would put `test_step_sweep` on screen where a sentence belongs."""
        js = _read(UI)
        drawn = re.findall(r"'(\w+)'",
                           re.search(r'const _SNMP_TEST_STEPS = \[(.*?)\]', js, re.S).group(1))
        assert drawn, 'the checklist draws no steps at all'
        for code in ('es_ES', 'en_EN'):
            ui = _lang(code).get('ui') or {}
            missing = [k for k in drawn if not ui.get('test_step_' + k)]
            assert not missing, f'{code} has no name for {missing}'

    def test_the_action_is_registered_and_changes_nothing(self):
        """An action absent from `WATCHFUL_ACTIONS` is a 404 whatever the UI calls it. And it
        reads a device and writes nothing, which is what puts it among the read-only ones —
        the same rights that already let somebody discover the device's OIDs."""
        actions, read_only = _snmp_actions()
        assert 'test_profiles' in actions and 'test_profiles' in read_only

    def test_what_the_profile_reads_is_not_reported_as_uncaptured(self):
        """The column that NAMES the rows and the one that scales them are values this
        assignment is already using. Listed as uncaptured they send somebody to write a
        metric for a number the profile is holding — and a metric declares a COLUMN while the
        device answers one OID per row under it, so the comparison is containment and never
        equality. As equality, every interface on the switch reads as uncaptured."""
        py = _read(ACTIONS)
        block = py.split('def _test_read(')[1].split('    @staticmethod')[0]
        assert "m.get('index_label')" in block and "m.get('scale_by')" in block
        assert 'def _covered_by(' in py and "'.'.join(parts[:i]) in roots" in py
