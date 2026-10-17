#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What each kind of bay takes is written once, for every kind of bay the catalogue declares.

The parts form offers a module or a component the bays its class fits (`_DC_BAY_TAKES` in
`partials/dcim/_parts.html`): a PSU bay takes power supplies, a drive bay drives. The kinds of
bay are the connectors document's (`data/connectors.json`, group `bay`, family `module-bays`).
A bay type added there and forgotten in the table is read as «takes anything» — no error, and
a drive bay offered a power supply. So every one of them must have its row, and the table must
name no bay the document does not have.
"""

import io
import json
import os
import re

from tests.helpers import _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
PARTS = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'dcim', '_parts.html')
CONNECTORS = os.path.join(SRC, 'lib', 'core', 'dcim', 'data', 'connectors.json')


def _bay_types() -> set:
    with io.open(CONNECTORS, encoding='utf-8') as fh:
        doc = json.load(fh)
    return {c['id'] for c in doc['connectors'] if isinstance(c, dict) and c.get('group') == 'bay'
            and 'module-bays' in (c.get('families') or ())}


def _table() -> dict:
    js = _read(PARTS)
    i = js.index('const _DC_BAY_TAKES = {')
    cuerpo = js[i:js.index('};', i)]
    return {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(
        r"'([a-z0-9-]+)':\s*\{kinds:\s*(null|\[[^\]]*\]),\s*modules:\s*(true|false)\}", cuerpo)}


class TestEveryBayHasItsRule:

    def test_the_document_has_bay_types(self):
        assert {'psu-bay', 'fan-bay', 'drive-bay', 'sfp-cage', 'module-bay'} <= _bay_types()

    def test_one_row_per_bay_type_and_none_invented(self):
        assert set(_table()) == _bay_types()

    def test_a_drive_bay_takes_no_module_and_a_psu_bay_only_power_supplies(self):
        t = _table()
        assert t['drive-bay'][1] == 'false' and 'disk' in t['drive-bay'][0]
        assert t['psu-bay'] == ("['psu']", 'true')
        assert t['module-bay'][0] == 'null'

    def test_the_classes_named_are_the_catalogues_and_the_parts(self):
        """The same words for a module (its catalogue class) and a component (its part class):
        a class named in the table that neither vocabulary has never matches anything."""
        import sys                                                  # noqa: PLC0415
        sys.path.insert(0, SRC)
        from lib.core.dcim import catalog                           # noqa: PLC0415
        from lib.core.dcim.store import PART_KINDS                  # noqa: PLC0415
        for bahia, (clases, modulos) in _table().items():
            for k in re.findall(r"'([a-z_]+)'", clases):
                assert k in PART_KINDS, (bahia, k)
                if modulos == 'true':
                    assert k in catalog.KINDS, (bahia, k)
