#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The room equipment and the fans are classes of the catalogue, and the demo uses them.

Reported: the demo's PCs, IP phones, Wi-Fi APs, cameras, displays and printers were of class
`other`, because the catalogue's vocabulary (`catalog.KINDS`) had no word for them — although an
item placed in a room already had them as roles (`ITEM_ROLES`) and the plans drew each with its
icon. And a fan module could only be a `module`, so nothing told a fan bay what fits it.

Installations that already have models of class `other` keep them: nothing is migrated. The
class is a correction anybody can make from the model's sheet, and guessing it from a name
would write a deduction as if it were a fact.
"""

from __future__ import annotations

import os
import sys

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lib.core.dcim import catalog                                   # noqa: E402
from lib.core.dcim.store import ITEM_ROLES, PART_KINDS              # noqa: E402

ROOM = ('pc', 'phone', 'ap', 'camera', 'display', 'printer')


class TestTheVocabulary:

    def test_the_room_equipment_has_its_class_with_the_item_roles_words(self):
        for k in ROOM:
            assert k in catalog.KINDS and k in ITEM_ROLES, k
        assert catalog.kinds_for('device-types') == catalog.KINDS
        assert catalog.kinds_for('rack-types') == ()

    def test_every_device_class_but_the_catalogue_only_ones_is_an_item_role(self):
        """Why they line up: a model's class is the role it suggests when it is placed
        (`service.role_hint`), and a class no item can have suggests nothing."""
        solo_catalogo = {'rack', 'transceiver', 'psu', 'nic', 'module', 'fan',
                         'access_gateway', 'access_lock', 'access_reader', 'access_controller',
                         'turnstile'}
        assert set(catalog.KINDS) - solo_catalogo <= set(ITEM_ROLES)

    def test_a_fan_is_a_module_class_and_a_part_class(self):
        assert 'fan' in catalog.kinds_for('module-types') and 'fan' in PART_KINDS

    def test_a_fan_module_is_read_as_a_fan_from_its_name(self):
        for nombre in ('X1 Fan Module', 'Chassis fan tray', 'FT-40 FanTray'):
            assert catalog.kind_of({'tree': 'module-types', 'model': nombre}) == 'fan', nombre
        # …and only from those words: a «fan-out cable» module is not one.
        assert catalog.kind_of({'tree': 'module-types', 'model': 'Fan-out module'}) == 'module'


class TestTheDemoUsesThem:

    def test_its_office_models_are_of_their_class(self):
        from lib.core.dcim import demo_faces                        # noqa: PLC0415
        for k in ROOM:
            assert demo_faces.MODELS[k][1] == k, k
        assert not [k for k, v in demo_faces.MODELS.items() if v[1] == 'other']

    def test_its_fans_are_fans(self):
        from lib.core.dcim import demo_faces                        # noqa: PLC0415
        for k in ('fansrv', 'fantray'):
            assert demo_faces.MODULES[k][1] == 'fan' and demo_faces.MODULES[k][2] == 'fan', k
        for k, (_n, clase, pieza, _t) in demo_faces.MODULES.items():
            assert clase in catalog.kinds_for('module-types') and pieza in PART_KINDS, k
