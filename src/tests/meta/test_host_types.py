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
    from lib.core.hosts.manifest import HOST_TYPES      # noqa: PLC0415
    return HOST_TYPES


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
        before the field did — so it is the one drawn most often."""
        from lib.core.hosts.manifest import HOST_TYPE_FALLBACK_ICON   # noqa: PLC0415
        with io.open(ICONS_CSS, encoding='utf-8') as fh:
            assert f'.{HOST_TYPE_FALLBACK_ICON}::before' in fh.read()

    def test_an_unknown_type_resolves_to_the_generic_icon(self):
        from lib.core.hosts.manifest import (HOST_TYPE_FALLBACK_ICON,  # noqa: PLC0415
                                             host_type_icon)
        assert host_type_icon('nas') == 'bi-hdd-stack'
        assert host_type_icon('') == HOST_TYPE_FALLBACK_ICON
        assert host_type_icon('nonesuch') == HOST_TYPE_FALLBACK_ICON


class TestItIsNamedEverywhereItIsShown:

    def test_every_type_is_translated_in_both_languages(self):
        from lib.i18n import TRANSLATIONS                # noqa: PLC0415
        for lang in ('es_ES', 'en_EN'):
            words = TRANSLATIONS.get(lang) or {}
            missing = [t['id'] for t in _types() if not words.get('host_type_' + t['id'])]
            assert not missing, f'{lang} has no name for {missing}'

    def test_the_field_and_the_unset_option_are_named_too(self):
        """"Unclassified" is an option somebody picks and a filter value they choose, not an
        absence — without a word for it the picker's first entry is empty."""
        from lib.i18n import TRANSLATIONS                # noqa: PLC0415
        for lang in ('es_ES', 'en_EN'):
            words = TRANSLATIONS.get(lang) or {}
            for key in ('host_type', 'host_type_hint', 'host_type_unset', 'col_host_type'):
                assert words.get(key), f'{lang} is missing {key}'


class TestTheAnswerReachesTheBrowser:
    """Declared in Python, drawn in JavaScript. Everything between them is wiring, and
    wiring that comes undone here empties a picker rather than breaking a page."""

    def test_the_page_hands_the_catalogue_to_the_template(self):
        src = _read(PAGES)
        assert 'host_types=' in src, 'the context never carries them'
        assert 'HOST_TYPES' in src

    def test_the_template_publishes_it_and_the_two_helpers(self):
        js = _read(CONSTANTS)
        assert 'const HOST_TYPES = {{ host_types' in js, 'not exposed to the page'
        for fn in ('function hostTypeIcon', 'function hostTypeLabel'):
            assert fn in js, f'{fn} is gone — every caller falls back to nothing'

    def test_the_modal_offers_it_and_the_save_carries_it(self):
        """The picker without the payload is the failure that looks like it worked: you
        choose "Switch", press save, and the row comes back unclassified."""
        modal = _strip_comments(_read(MODAL))
        assert 'HOST_TYPES.map' in modal, 'the modal offers no types'
        assert "_hostDraft.device_type=this.value" in modal
        assert "device_type: host.device_type" in modal, 'editing loses the stored value'
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
        assert modal.count('_refreshHostTypeIcon()') >= 3, \
            'not called from both open paths and the picker'

    def test_the_list_draws_it_and_can_filter_by_it(self):
        js = _strip_comments(_read(LIST))
        assert "id: 'type'" in js, 'no column'
        assert "key: 'type'" in js, 'no filter'
        assert 'hostTypeIcon(host.device_type)' in js, 'the row shows no icon'
        # "Unclassified" has to be selectable on its own: it is how somebody finds the
        # devices added in a hurry, and it is not the same question as "any".
        assert "f.type === '-'" in js, 'no way to ask for the unclassified ones'
