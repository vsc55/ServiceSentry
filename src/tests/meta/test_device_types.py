#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What a device says it is — and the four ways that answer goes missing in silence.

The registry holds servers, but it also holds a NAS, a switch and a UPS: the section was
called "Servers" while the SNMP catalogue beside it shipped profiles for Mikrotik, Linksys
and two makes of UPS. So a device now declares what it is, the panel draws its icon, and you
can filter a fleet by it.

Every part of that can fail without raising. The catalogue is declared in Python and consumed
by JavaScript through the page context: drop the context entry and the picker offers one
option; miss a translation and it offers a raw id; misspell an icon and the badge simply has
no glyph, because an unknown Bootstrap Icons class is a class that styles nothing.
"""

import io
import os
import re

from tests.helpers import _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
ICONS_CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'bootstrap-icons.min.css')
CONSTANTS = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                         '_constants.html')
PAGES = os.path.join(SRC, 'lib', 'web_admin', 'routes', 'pages.py')
MODAL = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers',
                     '_modal.html')
SAVE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers', '_save.html')
LIST = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers', '_list.html')


def _types():
    """La SEMILLA — las once con las que se crea la tabla.

    Y no una lista en caliente, porque ya no hay ninguna: lo que decide qué clases existen es
    `device_type`, que se edita desde el panel. Lo que se comprueba aquí es que lo que se siembra
    esté bien formado, porque una siembra con un icono inventado o una clave de idioma que no
    existe se escribe una vez y se queda para siempre en la base de todo el mundo.
    """
    from lib.core.devices.stores.types import SEED        # noqa: PLC0415
    return SEED


class TestTheCatalogueIsUsable:

    def test_every_type_has_an_id_and_an_icon(self):
        for spec in _types():
            assert spec.get('id') and re.fullmatch(r'[a-z_]+', spec['id']), spec
            assert str(spec.get('icon') or '').startswith('bi-'), spec

    def test_no_id_is_declared_twice(self):
        ids = [t['id'] for t in _types()]
        assert len(ids) == len(set(ids)), ids

    def test_every_icon_exists_in_the_bundled_font(self):
        """An unknown `bi-*` class is not an error — it is a class that styles nothing, so
        the badge draws with a blank where its glyph should be and the page still looks
        finished. The font is vendored, so this is answerable here rather than by looking."""
        with io.open(ICONS_CSS, encoding='utf-8') as fh:
            css = fh.read()
        missing = [t['icon'] for t in _types() if f'.{t["icon"]}::before' not in css]
        assert not missing, f'not in bootstrap-icons: {missing}'

    def test_the_fallback_icon_exists_too(self):
        """It is what an unclassified device wears, which is every device that existed
        before the field did — so it is the one drawn most often. And it is NOT a class: it is
        the answer when there is none, so it is not in the table and cannot be deleted."""
        from lib.core.devices.stores.types import FALLBACK_ICON  # noqa: PLC0415
        with io.open(ICONS_CSS, encoding='utf-8') as fh:
            assert f'.{FALLBACK_ICON}::before' in fh.read()

    def test_every_seeded_class_names_a_translation_key_that_exists(self):
        """The seed is written once into a database and stays there. A `label_key` naming a key
        the catalogue does not have is a picker entry reading `host_type_whatever` — for the life
        of that installation, because nothing re-seeds over what is already in."""
        from lib.core.devices.stores.types import SEED     # noqa: PLC0415
        from lib.i18n import TRANSLATIONS                # noqa: PLC0415
        for lang in ('es_ES', 'en_EN'):
            words = TRANSLATIONS.get(lang) or {}
            missing = [t['id'] for t in SEED if not words.get('device_type_' + t['id'])]
            assert not missing, f'{lang} has no name for {missing}'

    def test_every_seeded_class_names_a_description_key_that_exists(self):
        """Its description travels the same road as its name, and for the same reason: written
        into the column it would be frozen in the language of whoever created the database.

        A key the catalogue does not have is worse than no description at all — `t()` answers with
        the key it was given, so the column would read `device_type_nas_desc` where a sentence is
        expected. The screen guards against that; this is what keeps the guard from having to."""
        from lib.core.devices.stores.types import SEED     # noqa: PLC0415
        from lib.i18n import TRANSLATIONS                # noqa: PLC0415
        for lang in ('es_ES', 'en_EN'):
            words = TRANSLATIONS.get(lang) or {}
            missing = [t['id'] for t in SEED
                       if not words.get('device_type_' + t['id'] + '_desc')]
            assert not missing, f'{lang} describes none of {missing}'

    def test_and_carries_a_fallback_name_of_its_own(self):
        """The key is what is shown; this is what is left if the key ever goes. A seeded row with
        neither is a blank entry in the picker."""
        from lib.core.devices.stores.types import SEED     # noqa: PLC0415
        assert all(str(t.get('name') or '').strip() for t in SEED)


class TestItIsNamedEverywhereItIsShown:

    def test_the_field_and_the_unset_option_are_named_too(self):
        """"Unclassified" is an option somebody picks and a filter value they choose, not an
        absence — without a word for it the picker's first entry is empty."""
        from lib.i18n import TRANSLATIONS                # noqa: PLC0415
        for lang in ('es_ES', 'en_EN'):
            words = TRANSLATIONS.get(lang) or {}
            for key in ('device_type', 'device_type_hint', 'device_type_unset', 'col_device_type'):
                assert words.get(key), f'{lang} is missing {key}'


class TestTheAnswerReachesTheBrowser:
    """Declared in Python, drawn in JavaScript. Everything between them is wiring, and
    wiring that comes undone here empties a picker rather than breaking a page."""

    def test_the_page_hands_the_catalogue_to_the_template(self):
        """And **the panel's catalogue, not the constant.**

        The list used to be the eleven declared in `manifest.py`, and the page handed exactly
        those. It is two lists now — those plus the ones this installation added — and a page
        still reading the constant would serve a picker that is missing every class somebody
        created, until the process restarts. Nothing fails: the class exists, the API returns
        it, and the picker simply does not have it.
        """
        src = _read(PAGES)
        assert 'device_types=' in src, 'the context never carries them'
        assert 'device_types_catalog(wa)' in src, 'the page serves a code list, not the table'
        assert 'DEVICE_TYPES' not in src, 'the constant is back'

    def test_the_template_publishes_it_and_the_two_helpers(self):
        js = _read(CONSTANTS)
        assert 'const DEVICE_TYPES = {{ device_types' in js, 'not exposed to the page'
        for fn in ('function deviceTypeIcon', 'function deviceTypeLabel'):
            assert fn in js, f'{fn} is gone — every caller falls back to nothing'

    def test_a_class_this_house_added_is_named_by_its_own_words(self):
        """`t()` falls back to the key it was given, so consulting the language catalogue first
        answers with that key — which is then what the picker shows, beside ten real words. The
        stored label has to be consulted FIRST."""
        js = _strip_comments(_read(CONSTANTS))
        assert 'DEVICE_TYPE_LABELS' in js, 'the typed-in names never reach the browser'
        cuerpo = js.split('function deviceTypeLabel', 1)[1].split('\n}', 1)[0]
        assert cuerpo.index('DEVICE_TYPE_LABELS') < cuerpo.index('DEVICE_TYPE_KEYS'), \
            'the language catalogue is asked first, so the key wins over the real name'

    def test_and_a_class_is_looked_up_by_uid_not_by_its_short_name(self):
        """`devices.device_type` holds the class UID, so every one of these maps has to be keyed by
        it. Keyed by the short name each of them answers nothing for every device on screen — no
        icon, no translated class, and a picker with nothing selected."""
        js = _strip_comments(_read(CONSTANTS))
        for mapa in ('DEVICE_TYPE_ICONS', 'DEVICE_TYPE_LABELS', 'DEVICE_TYPE_KEYS'):
            linea = js.split('const %s' % mapa, 1)[1].split(';', 1)[0]
            assert 'x.uid' in linea, '%s is not keyed by uid' % mapa
            assert 'x.id' not in linea, '%s still keys by the old id' % mapa

    def test_the_modal_offers_it_and_the_save_carries_it(self):
        """The picker without the payload is the failure that looks like it worked: you
        choose "Switch", press save, and the row comes back unclassified."""
        modal = _strip_comments(_read(MODAL))
        assert 'DEVICE_TYPES.map' in modal, 'the modal offers no types'
        assert "_deviceDraft.device_type=this.value" in modal
        assert "device_type: device.device_type" in modal, 'editing loses the stored value'
        save = _strip_comments(_read(SAVE))
        assert 'device_type: d.device_type' in save, 'the save drops it'

    def test_what_the_icon_repaint_looks_up_is_something_that_exists(self):
        """A repaint that reads an id nothing creates finds nothing, does nothing, and leaves
        a page that looks finished. It has happened here before — `_renderProfileFields` was
        dead for exactly this reason (docs/caso-diagnostico.md) — so the id it wants and the
        element that carries it are pinned against each other.

        And it has to be called from BOTH ways in: opening a new device and opening an
        existing one. Wired to the picker alone, the icon would be right only after you
        changed the answer."""
        modal = _strip_comments(_read(MODAL))
        deps = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                  'modals', '_deps.html'))
        assert "getElementById('hmTypeIcon')" in modal
        assert 'id="hmTypeIcon"' in deps, 'the repaint has no element to paint'
        assert modal.count('_refreshDeviceTypeIcon()') >= 3, \
            'not called from both open paths and the picker'

    def test_the_list_draws_it_and_can_filter_by_it(self):
        # The fleet list is Infrastructure's since the registry's own list went there.
        js = _strip_comments(_read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                                'infra', '_list.html')))
        assert "id: 'device_type'" in js, 'no column'
        assert "key: 'type'" in js, 'no filter'
        assert 'deviceTypeIcon(h.device_type)' in js, 'the row shows no icon'
        # "Unclassified" has to be selectable on its own: it is how somebody finds the
        # devices added in a hurry, and it is not the same question as "any".
        assert "f.type === '-'" in js, 'no way to ask for the unclassified ones'


class TestTheClassesTabIsWiredEverywhereItHasToBe:
    """A catalogue entry is four files, and missing one of them fails **silently and
    differently** each time: not declared and it exists but nobody finds it; no pane and the
    sidebar points at nothing; no `shown.bs.tab` handler and it opens empty; not in the
    visibility list and it stays hidden for everyone. None of the four raises.

    It is the screen the whole point of this work hangs on — where the classes are managed — so
    the four are pinned together rather than trusted to a memory of having done them. It was a
    sub-tab of the device registry; it is an entry of the Catalogue since the registry's list
    moved to Infrastructure.
    """

    CONSTANTS = os.path.join(SRC, 'lib', 'web_admin', 'constants.py')
    PANE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers',
                        '_pane.html')
    WIRING = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'init',
                          '_wiring.html')
    FEATURES = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'init',
                            '_table_features.html')

    def test_the_sidebar_offers_it(self):
        src = _read(self.CONSTANTS)
        fila = src.split("{'id': 'devtypes'", 1)[1].split('},', 1)[0]
        assert "'group': 'catalog'" in fila, 'declared, but not in the Catalogue'

    def test_the_pane_has_its_tab_and_its_container(self):
        pane = _read(self.PANE)
        assert 'id="tab-devtypes"' in pane, 'the sidebar would point at nothing'
        assert 'id="devicetypes-container"' in pane, 'the renderer has nowhere to draw'

    def test_and_runs_full_bleed_like_the_other_lists(self):
        """Inside a `.ss-fullbleed` pane the card loses its border, corners and shadow on its
        own — which is what makes every list of the panel read as one kind of screen. With
        ordinary padding it came out as a bordered box. Reported from the screen."""
        pane = _read(self.PANE)
        trozo = pane.split('id="tab-devtypes"', 1)[0].rsplit('<div class="tab-pane', 1)[1]
        assert 'ss-fullbleed' in trozo and 'ss-fullbleed-top' in trozo, trozo[:90]

    def test_opening_it_draws_it(self):
        wiring = _read(self.WIRING)
        cuerpo = wiring.split("getElementById('btn-tab-devtypes')", 1)[1].split('});', 1)[0]
        assert 'renderDeviceTypes()' in cuerpo, 'it opens empty'

    def test_and_somebody_can_see_it(self):
        feats = _read(self.FEATURES)
        assert "getElementById('tab-devtypes-li')" in feats, 'hidden for everyone'

    def test_the_screen_uses_the_panel_s_table_and_not_one_of_its_own(self):
        """It hand-rolled its own: header, filter strip, checkboxes, bulk bin — with the shared
        factory that Devices, Companies, Clusters and the inventory all use sitting right there.
        What came out was a list that behaved unlike every other list in its own section: no
        accent strip, no filter bar, no column chooser, no sorting, no paging. Reported from the
        screen.

        `renderDeviceTypes` is not defined here any more — the factory generates it from
        `globalPrefix.render`, which is also what the sub-tab wiring calls."""
        js = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers',
                                '_types.html'))
        assert 'createListTable({' in js, 'the screen builds its own table again'
        assert "containerId: 'devicetypes-container'" in js
        assert "render: 'renderDeviceTypes'" in js, 'the sub-tab calls a function nothing defines'
        assert "selectableRow:" in js, 'a class in use would become selectable'

    def test_and_the_inventory_catalogue_points_at_it(self):
        """It is not where they live — that catalogue describes equipment in general — but it is
        where somebody goes looking for a catalogue. A link, not a second copy of the screen."""
        cat = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'dcim',
                                 '_catalog.html'))
        # El DESTINO de la navegación, no la palabra suelta.
        assert "_navTab('#tab-devtypes')" in cat


class TestTheClassesScreenIsWiredToItsOwnMarkup:
    """A repaint that looks up an id nothing creates finds nothing, does nothing, and leaves a
    page that looks finished. It has happened in this codebase before — `_renderProfileFields`
    was dead for exactly that reason (docs/caso-diagnostico.md) — so every id this screen reaches
    for is pinned against the element that carries it.
    """

    JS = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers',
                      '_types.html')
    DEPS = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'modals',
                        '_deps.html')
    CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')

    def test_the_edit_dialog_it_opens_exists(self):
        js, deps = _read(self.JS), _read(self.DEPS)
        assert "getElementById('deviceTypeEditModal')" in js
        assert 'id="deviceTypeEditModal"' in deps, 'it opens a dialog that is not there'
        assert 'id="deviceTypeEditBody"' in deps, 'the body has nowhere to draw'
        assert 'id="deviceTypeEditTitle"' in deps, 'the title never says which of the two it is'

    def test_and_its_save_button_calls_the_save(self):
        """The dialog's footer lives in the markup and the function in the JS: a footer wired to
        nothing is a Save button that closes nothing and saves nothing."""
        assert '_htSave()' in _read(self.DEPS)

    def test_the_icon_picker_draws_icons_and_not_their_names(self):
        """Choosing between `hdd-stack` and `hdd-network` by reading two words is guessing which
        was which — and what is being chosen is a drawing."""
        js = _strip_comments(_read(self.JS))
        rejilla = js.split('function _htIconGridHtml', 1)[1].split('\n}', 1)[0]
        assert '<i class="bi ' in rejilla, 'the picker lists names instead of icons'
        assert 'ss-icon-pick' in rejilla

    def test_and_that_grid_has_styles_of_its_own(self):
        """Unstyled, the twenty buttons are twenty full-width blocks stacked down the dialog —
        and nothing fails, it just draws wrong."""
        css = _read(self.CSS)
        # Con la llave: el nombre suelto lo cumple cualquier regla que lo lleve dentro
        # —`.ss-icon-grid-x` incluida— así que renombrarla daba verde. Encontrado mutándolo.
        for clase in ('.ss-icon-grid {', '.ss-icon-pick {', '.ss-icon-pick.active {'):
            assert clase in css, clase

    def test_every_offered_icon_exists_in_the_bundled_font(self):
        """An unknown `bi-*` class is not an error — it is a class that styles nothing, so the
        picker draws a blank square and the dialog still looks finished."""
        js = _read(self.JS)
        crudo = js.split('const HT_ICONS = [', 1)[1].split(']', 1)[0]
        iconos = [t.strip().strip("'\"") for t in crudo.split(',') if t.strip()]
        assert len(iconos) >= 10, iconos
        with io.open(ICONS_CSS, encoding='utf-8') as fh:
            css = fh.read()
        faltan = [i for i in iconos if f'.{i}::before' not in css]
        assert not faltan, f'not in bootstrap-icons: {faltan}'

    def test_the_add_button_carries_a_dropdown_like_the_other_two_screens(self):
        """Companies and Devices both hang "other ways for one to appear" off their add button
        rather than growing the toolbar. This is the third, and it is the same act."""
        js = _strip_comments(_read(self.JS))
        nuevo = js.split('function _htNewHtml', 1)[1].split('\n}', 1)[0]
        assert 'dropdown-toggle-split' in nuevo, 'no caret'
        assert '_htOpenEdit' in nuevo, 'the caret ate the add button'
        assert '_htSeed()' in nuevo, 'the basics are not in the menu'
        assert 'a.fn' in nuevo, 'a declared action would have nowhere to go'

    def test_clicking_a_row_lands_on_the_devices_by_type_view(self):
        """"This one is worn by twelve" is followed by "which twelve?", and having to go and
        rebuild that with a filter by hand is doing by hand what the screen already knows."""
        js = _strip_comments(_read(self.JS))
        ir = js.split('function _htGoDevices', 1)[1].split('\n}', 1)[0]
        # The fleet is Infrastructure's: its rail, grouped by class, with this one picked.
        assert "_infraView.apply('rail')" in ir, 'it lands on whatever view was last used'
        assert "'ss_infra_group_by', 'device_type'" in ir, 'the rail is grouped by something else'
        assert 'ss_infra_rail_pick' in ir, 'the rail opens on the wrong class'
        assert "_navTab('#tab-infra')" in ir, 'it never leaves the classes screen'
        assert "infraOpen('')" in ir, 'it navigates to a device page instead of the fleet'

    def test_the_grid_view_is_the_panel_card_grid(self):
        """It had its own — its own grid, its own card — written beside the shared pieces that
        draw the cards in Devices, Sessions and the rest. What came out sat flush against the
        panel edges (the margins come with the shared grid) and was a different shape of card
        from its neighbours in its own section. Reported from the screen.

        Pinned by NAME and not by look, because that is the whole difference: a screen declares
        what a card says, never how a card is drawn."""
        js = _strip_comments(_read(self.JS))
        rejilla = js.split('function _htGridBody', 1)[1].split('\n}', 1)[0]
        assert '_cardGrid(' in rejilla, 'the grid is hand-rolled again'
        assert '_entityCard(' in rejilla, 'the card is hand-rolled again'
        assert 'ss-ht-card' not in js, 'its own card class is back'

    def test_the_description_is_a_box_you_can_write_a_sentence_in(self):
        """A one-line input for a sentence shows six words of it and scrolls sideways for the
        rest, which is the shape that makes people not write it. Reported from the screen."""
        js = _strip_comments(_read(self.JS))
        cuerpo = js.split('function _htDrawEdit', 1)[1].split('\n}', 1)[0]
        assert '<textarea' in cuerpo and 'id="htDesc"' in cuerpo, 'the description is an input'
        assert 'device_types_desc_hint' in cuerpo, 'nothing says what it is for'

    def test_and_the_dialog_is_wide_and_in_two_columns(self):
        """The whole font's two thousand icons open inside it: in a narrow dialog that is a
        four-wide strip with an endless scroll while half the dialog sits empty."""
        assert 'modal-lg' in _read(self.DEPS), 'the dialog is narrow again'
        js = _strip_comments(_read(self.JS))
        cuerpo = js.split('function _htDrawEdit', 1)[1].split('\n}', 1)[0]
        assert 'col-md-' in cuerpo, 'a single column again'
        # Y con la llave, como la rejilla corta de arriba: el nombre suelto lo cumple cualquier
        # regla que lo lleve dentro.
        assert '.ss-icon-grid-tall {' in _read(self.CSS), 'the long list has no height of its own'

    def test_the_icon_loader_speaks_for_itself(self):
        """It borrowed the provider's wording — «Consultando Freshservice» — because the spinner
        beside it looked the same. Anyone who read it was told a connector was being queried to
        draw a list of pictures. Reported from the screen."""
        js = _strip_comments(_read(self.JS))
        assert "t('fs_working')" not in js, 'a core screen names a provider'
        assert "t('device_types_icons_load')" in js, 'the spinner says nothing'

    def test_the_dialog_declares_its_width_instead_of_offering_to_resize_it(self):
        """`modal-lg` alone brings the resize handle and the maximise button (`_modalResizable`),
        and what gets maximised here is the empty space under the icons. A width the opener has
        declared is a decision; a button to undo it is offering that it does not count."""
        deps = _read(self.DEPS)
        dlg = deps.split('id="deviceTypeEditModal"', 1)[1].split('>', 2)[1]
        assert 'ss-modal-wide' in dlg, 'the maximise button is back'

    def test_the_uid_is_a_field_you_can_copy_and_not_a_line_of_text(self):
        """It is what every relation is made with, so it gets picked up and pasted — into a query,
        into a ticket. As running text it can only be selected by hand, and this is the shape
        Users, Groups and Credentials already use for the same thing."""
        js = _strip_comments(_read(self.JS))
        cuerpo = js.split('function _htDrawEdit', 1)[1].split('\n}', 1)[0]
        assert 'id="htUid"' in cuerpo and 'readonly' in cuerpo, 'the uid is not a field'
        assert '_copyToClipboard(' in cuerpo, 'nothing copies it'

    def test_the_long_icon_list_does_not_repeat_the_short_one(self):
        """The twenty on top came out twice in the same dialog, the selected one among them —
        which is what makes you doubt whether they are the same icon. Reported from the screen.

        Pinned on the subtraction being made against the SHORT grid's own list and not against
        the constant: the short one puts the class's own icon in front when it is not one of the
        twenty, so subtracting only the twenty leaves exactly that one repeated."""
        js = _strip_comments(_read(self.JS))
        larga = js.split('function _htIconsExtra', 1)[1].split('\n}', 1)[0]
        assert '_htIconsShort()' in larga, 'it subtracts the constant, not what is drawn'

    def test_no_column_reaches_the_chooser_without_a_name(self):
        """The chooser prints `col.label()` and nothing else, so a column with an empty label is a
        blank row in that menu — and, if it is `always`, a tickbox that cannot be touched and does
        not say what it is for. That is what the icon column was. Reported from the screen.

        It is checked on the declaration and not on the rendering because an empty string draws
        perfectly well: nothing fails, there is just a gap where a word should be."""
        js = _strip_comments(_read(self.JS))
        cols = js.split('const _HT_COLS = [', 1)[1].split('\n];', 1)[0]
        assert "label: () => ''" not in cols, 'a column would show up nameless in the chooser'
        assert "'icon'" not in cols, 'the icon is a column again'

    def test_the_columns_that_come_up_are_the_ones_you_read_a_row_by(self):
        """What is it, what for, who maintains it, how many wear it — in that order, which is the
        order the declaration gives since the header follows `_HT_COLS`.

        The identifiers are not among them: neither the short name nor the uid says anything while
        looking down a list, and left on they are two columns of monospace between the four that
        are actually read. They are a click away in the chooser on the day they are wanted. Chosen
        from the screen."""
        js = _strip_comments(_read(self.JS))
        crudo = js.split('const _HT_DEFAULT_COLS = new Set([', 1)[1].split(']', 1)[0]
        puestas = [c.strip().strip("'\"") for c in crudo.split(',') if c.strip()]
        assert puestas == ['description', 'source', 'used'], puestas
        # Y en ese orden sobre la tabla: la cabecera sigue a `_HT_COLS`, así que el orden en que
        # se leen es el de la declaración y no el de este conjunto.
        cols = js.split('const _HT_COLS = [', 1)[1].split('\n];', 1)[0]
        sitios = [cols.index("id: '%s'" % c) for c in ['name'] + puestas]
        assert sitios == sorted(sitios), 'the header would not read in that order'


class TestTheDomainIsLaidOutTheWayItReads:
    """Two tables and a question layer, and the layout says which is which.

    It used to be `store.py` (the fleet) and `types.py` (the classes) side by side with everything
    else, and `types.py` held both the table and the half-dozen functions the rest of the panel
    calls about classes — so reading the catalogue meant importing the module that declares
    columns and indexes. Asked from the screen.
    """

    STORES = os.path.join(SRC, 'lib', 'core', 'devices', 'stores')
    CLASSES = os.path.join(SRC, 'lib', 'core', 'devices', 'classes.py')

    def test_each_table_is_a_file_named_after_it(self):
        """The point of the folder: searching the repo for `device_type` lands in one place and not
        three. `lib.core.dcim.store` is the same arrangement with twelve."""
        for archivo, tabla in (('devices.py', "name='devices'"),
                               ('types.py', "name='device_type'")):
            src = _read(os.path.join(self.STORES, archivo))
            assert src.count('TableSpec(') == 1, f'{archivo} declares more than one table'
            assert tabla in src, f'{archivo} is not the one that declares {tabla}'

    def test_and_both_can_be_imported_without_knowing_which_file(self):
        """`from lib.core.devices.stores import DevicesStore, DeviceTypesStore` — a caller that only
        wants a store has no business knowing which file it landed in."""
        init = _read(os.path.join(self.STORES, '__init__.py'))
        for nombre in ('DevicesStore', 'DeviceTypesStore'):
            assert nombre in init, f'{nombre} is not re-exported'

    def test_the_questions_about_classes_are_not_in_the_table_file(self):
        """`catalog`, `ensure`, `known`, `uid_for`, `in_use`, `usage`: what the routes, the
        Freshservice provider and the page call. They are a layer above the store — the panel is
        being asked a question, not the table."""
        api = _read(self.CLASSES)
        tabla = _read(os.path.join(self.STORES, 'types.py'))
        for fn in ('def catalog(', 'def ensure(', 'def known(', 'def uid_for(',
                   'def in_use(', 'def usage('):
            assert fn in api, f'{fn} is not in classes.py'
            assert fn not in tabla, f'{fn} is back in the table file'
        assert 'TableSpec(' not in api, 'classes.py declares a table'
