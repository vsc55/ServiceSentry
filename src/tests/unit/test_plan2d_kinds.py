#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The plan catalogue's rules, without an app: the base objects, a screen's registration, what an
object created from a screen may say, and the inventory's catalogue as it always was."""

from __future__ import annotations

import pytest

from lib.core.plan2d import kinds as p2k


class TestTheBase:

    def test_each_base_object_is_complete(self):
        for k, s in p2k.BASE.items():
            assert s['label'] == 'plan2d_kind_' + k
            assert s['icon'].startswith('bi-') and s['layer'] in p2k.LAYERS, k
            assert s['w'] > 0 and s['d'] > 0 and s['h'] > 0 and 'fill' in s['look'], k
            if s.get('device'):
                assert s['mount'] in p2k.MOUNTS, k

    def test_and_has_its_name_in_both_languages(self):
        from lib.i18n.lang.es_ES import LANG as ES                   # noqa: PLC0415
        from lib.i18n.lang.en_EN import LANG as EN                   # noqa: PLC0415
        for s in p2k.BASE.values():
            assert s['label'] in ES and s['label'] in EN, s['label']


class TestOneNamePerObject:

    def test_a_base_object_has_no_second_key_with_the_same_text(self):
        """Its name is `plan2d_kind_<id>` and nothing else: the inventory's `dcim_kind_door` or
        `dcim_role_camera` said the same, and two keys for one name drift apart on the first
        translation that touches only one."""
        from lib.i18n.lang.es_ES import LANG as ES                   # noqa: PLC0415
        from lib.i18n.lang.en_EN import LANG as EN                   # noqa: PLC0415
        for k in p2k.BASE:
            for viejo in ('dcim_kind_' + k, 'dcim_role_' + k):
                assert viejo not in ES and viejo not in EN, viejo


class TestScreens:

    def test_a_screen_takes_base_objects_and_adds_its_own(self):
        p2k.register_screen('t-a', base=('door', 'mine', 'pc'), view_perm='v', manage_perm='m',
                            own={'mine': {'label': 'x', 'icon': 'bi-box', 'w': 1, 'd': 1, 'h': 1,
                                          'layer': 'room', 'look': {'fill': '#000000'}}})
        k = p2k.code_kinds('t-a')
        assert list(k) == ['door', 'mine', 'pc']
        assert (k['door']['source'], k['mine']['source']) == ('base', 'screen')

    def test_a_screen_cannot_name_what_does_not_exist(self):
        with pytest.raises(ValueError):
            p2k.register_screen('t-b', base=('door', 'nope'), view_perm='v', manage_perm='m')

    def test_nor_take_a_key_of_a_created_object(self):
        with pytest.raises(ValueError):
            p2k.register_screen('t-c', base=(), view_perm='v', manage_perm='m',
                                own={'u-x': {'label': 'x', 'icon': 'bi-box', 'w': 1, 'd': 1, 'h': 1,
                                             'layer': 'room', 'look': {'fill': '#000000'}}})

    def test_the_catalogue_copies_so_nobody_edits_the_base(self):
        p2k.register_screen('t-d', base=('door',), view_perm='v', manage_perm='m')
        p2k.code_kinds('t-d')['door']['look']['fill'] = '#ffffff'
        assert p2k.BASE['door']['look']['fill'] != '#ffffff'


class TestCreatedObjects:

    def _ok(self, **cambios):
        return p2k.custom_clean(dict({'name': 'Palé', 'icon': 'bi-box'}, **cambios))

    def test_defaults_fill_what_is_not_sent(self):
        d = self._ok()
        assert p2k.custom_bad(d) == ''
        assert (d['w_mm'], d['layer'], d['fill'], d['device']) == (600, 'room', '#94a3b8', 0)

    def test_numbers_typed_as_text_are_numbers(self):
        assert self._ok(w_mm='1200')['w_mm'] == 1200

    @pytest.mark.parametrize('cambio,error', [
        ({'name': '  '}, 'plan2d_kind_bad_name'),
        ({'icon': 'bi-box" onmouseover="x'}, 'plan2d_kind_bad_icon'),
        ({'w_mm': 5}, 'plan2d_kind_bad_size'),
        ({'base_mm': -1}, 'plan2d_kind_bad_size'),
        ({'w_mm': True}, 'plan2d_kind_bad_size'),
        ({'layer': 'roof'}, 'plan2d_kind_bad_layer'),
        ({'fill': '#fff'}, 'plan2d_kind_bad_color'),
        ({'line': 'url(#x)'}, 'plan2d_kind_bad_color'),
        ({'dash': '4 3 2'}, 'plan2d_kind_bad_dash'),
        ({'abbr': 'ABCDE'}, 'plan2d_kind_bad_abbr'),
        ({'device': 1, 'mount': 'sky'}, 'plan2d_kind_bad_mount'),
    ])
    def test_what_it_may_not_say(self, cambio, error):
        assert p2k.custom_bad(self._ok(**cambio)) == error

    def test_equipment_only_where_the_screen_keeps_it(self):
        d = self._ok(device=1, mount='wall')
        assert p2k.custom_bad(d) == ''
        assert p2k.custom_bad(d, devices=False) == 'plan2d_kind_no_devices'

    def test_editing_starts_from_what_it_was(self):
        d = p2k.custom_clean({'name': 'Nuevo'}, current={'name': 'Viejo', 'w_mm': 900, 'fill': '#123456'})
        assert (d['name'], d['w_mm'], d['fill']) == ('Nuevo', 900, '#123456')


class TestTheInventoryCatalogue:
    """The inventory's pieces and room items come from the catalogue now; their sizes and layers
    are the ones they always had, so nothing already drawn moves."""

    def test_pieces_keep_their_measures(self):
        from lib.core.dcim.store import FEATURE_KINDS                # noqa: PLC0415
        assert (FEATURE_KINDS['aisle']['w'], FEATURE_KINDS['aisle']['layer']) == (4800, 'floor')
        assert (FEATURE_KINDS['tray']['base'], FEATURE_KINDS['tray']['layer']) == (2720, 'air')
        assert FEATURE_KINDS['cabinet']['front'] is True
        assert 'camera' not in FEATURE_KINDS, 'equipment is not a piece'
        assert len(FEATURE_KINDS) == 21

    def test_room_items_keep_their_boxes(self):
        from lib.core.dcim.store import ROOM_ITEM_DEFAULTS           # noqa: PLC0415
        assert ROOM_ITEM_DEFAULTS == {
            'pc': (180, 300, 330, 750, 'desk'), 'phone': (190, 200, 110, 750, 'desk'),
            'printer': (520, 480, 420, 0, 'floor'), 'ap': (230, 230, 45, 2950, 'ceiling'),
            'camera': (130, 130, 120, 2750, 'wall'), 'display': (1450, 90, 830, 900, 'wall'),
            'outlet': (86, 45, 86, 300, 'wall'), 'power_outlet': (86, 45, 86, 300, 'wall')}

    def test_every_room_item_kind_is_an_item_role(self):
        from lib.core.dcim.store import ITEM_ROLES, ROOM_ITEM_DEFAULTS   # noqa: PLC0415
        assert set(ROOM_ITEM_DEFAULTS) <= set(ITEM_ROLES)


class TestPaletteGroups:
    """Each object is looked for in a palette group: what it is for."""

    def test_every_base_object_has_a_group(self):
        for k, s in p2k.BASE.items():
            assert s['group'] in p2k.GROUP_IDS, k

    def test_and_every_group_its_name_in_both_languages(self):
        from lib.i18n.lang.es_ES import LANG as ES                   # noqa: PLC0415
        from lib.i18n.lang.en_EN import LANG as EN                   # noqa: PLC0415
        for g in p2k.groups():
            assert g['label'] in ES and g['label'] in EN and g['icon'].startswith('bi-'), g

    def test_the_inventory_puts_each_of_its_own_in_a_group(self):
        import lib.core.dcim.plankinds  # noqa: F401, PLC0415
        k = p2k.code_kinds('dcim')
        assert {x for x in k if k[x]['group'] == 'datacenter'} == {'aisle', 'panel', 'ups', 'crac', 'tray'}
        assert {x for x in k if k[x]['group'] == 'access'} == {'turnstile', 'reader'}
        assert not [x for x in k if k[x]['group'] == 'other']

    def test_an_own_object_without_a_group_goes_to_other_and_a_bad_one_is_refused(self):
        spec = {'label': 'x', 'icon': 'bi-box', 'w': 1, 'd': 1, 'h': 1, 'layer': 'room',
                'look': {'fill': '#000000'}}
        p2k.register_screen('t-g', base=(), view_perm='v', manage_perm='m', own={'mine': spec})
        assert p2k.code_kinds('t-g')['mine']['group'] == 'other'
        with pytest.raises(ValueError):
            p2k.register_screen('t-h', base=(), view_perm='v', manage_perm='m',
                                own={'mine': dict(spec, group='nope')})

    def test_a_created_object_goes_to_other(self):
        assert p2k.custom_spec({'name': 'Palé', 'icon': 'bi-box'})['group'] == 'other'

