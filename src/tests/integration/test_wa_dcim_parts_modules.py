#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The parts form of a device finds modules too, and offers each one the bays it fits.

Reported: the search of an item's parts («piezas») only looked at the component models, so a
mounted module —a PSU, a fan, a transceiver, an OCP card, a storage controller— could not be
picked again from the search once removed. Now it searches the module models as well, when the
device has a bay that takes modules, and by the bay families the catalogue declares
(`connectors.json`, group `bay`): a PSU bay takes power supplies, a fan bay fans, a drive bay
drives and no module, an SFP cage —a bay of that type, or an interface whose type is a cage—
transceivers, and a generic module bay anything. With a bay already chosen (clicked on the
face), only what fits it; and the list of bays of a part is the one its class fits.

All in node, over the panel's own bundle.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


_PROBE = r"""
const __o = {};
globalThis.__out = __o;
__wait = (async () => {
_dcimMay = () => true;
renderDcim = () => {};
showHtmlModal = () => {};
let pedidas = [];
const COMP = [{uid: 'c1', tree: 'component-types', kind: 'ssd', manufacturer: 'A', model: 'SSD'},
              {uid: 'c2', tree: 'component-types', kind: 'memory', manufacturer: 'A', model: 'DIMM'},
              {uid: 'c3', tree: 'component-types', kind: 'psu', manufacturer: 'A', model: 'PSU-c'}];
const MODS = [{uid: 'mp', tree: 'module-types', kind: 'psu', manufacturer: 'A', model: 'PSU 800'},
              {uid: 'mf', tree: 'module-types', kind: 'fan', manufacturer: 'A', model: 'Fan'},
              {uid: 'mt', tree: 'module-types', kind: 'transceiver', manufacturer: 'A', model: 'SFP'},
              {uid: 'mn', tree: 'module-types', kind: 'nic', manufacturer: 'A', model: 'OCP'},
              {uid: 'mm', tree: 'module-types', kind: 'module', manufacturer: 'A', model: 'Ctrl'},
              {uid: 'mx', tree: 'module-types', kind: 'server', manufacturer: 'A', model: 'Odd'}];
apiGet = async (u) => {
    pedidas.push(u);
    return {types: u.includes('tree=module-types') ? MODS : COMP};
};
const KINDS = ['disk', 'ssd', 'memory', 'cpu', 'nic', 'hba', 'gpu', 'psu', 'fan', 'transceiver',
               'jack', 'battery', 'module', 'accessory', 'other'];
const bay = (name, type) => type ? {name, type} : {name};
const FULL = {'module-bays': [bay('PSU bay 1', 'psu-bay'), bay('PSU bay 2', 'psu-bay'),
                              bay('Fan 1', 'fan-bay'), bay('Drive 0', 'drive-bay'),
                              bay('OCP 3.0', 'module-bay'), bay('Slot X', '')],
              'interfaces': [bay('eth0', '1000base-t'), bay('sfp0', '25gbase-x-sfp28')]};
const STRICT = {'module-bays': [bay('PSU bay 1', 'psu-bay'), bay('Drive 0', 'drive-bay')],
                'interfaces': [bay('eth0', '1000base-t')]};
const DRIVES = {'module-bays': [bay('Drive 0', 'drive-bay'), bay('Drive 1', 'drive-bay')]};
const abre = (lista) => {
    _dcBuild = null;
    _dcParts = {item: 'i1', parts: [], kinds: KINDS, model: {uid: 't1', port_list: lista}};
};
const busca = async (slot) => {
    _dcCompDraft = null;
    _dcCompStart('item');
    if (slot) _dcCompDraft.slot = slot;
    pedidas = [];
    await _dcCompSearch();
    return {asked: pedidas.slice(), rows: _dcCompDraft.rows.map(r => r.uid)};
};

// 1. The search, by what the device's bays take.
abre(FULL);
__o.full = await busca('');
__o.listHtml = _dcCompFormHtml('item');
abre(STRICT);
__o.strict = await busca('');
abre(DRIVES);
__o.drives = await busca('');
abre(FULL);
__o.inPsu = await busca('PSU bay 1');
__o.inDrive = await busca('Drive 0');
__o.inFan = await busca('fan 1');
__o.inCage = await busca('sfp0');
__o.inAny = await busca('OCP 3.0');

// 2. Taking one: the part's class from the model's, in the parts' vocabulary.
const toma = (uid) => { _dcCompTake(uid); const d = _dcCompDraft;
                        return {kind: d.kind, tree: d.tree, type: d.type_uid, model: d.model}; };
abre(FULL);
await busca('');
__o.takePsu = toma('mp');
await busca(''); __o.takeCtrl = toma('mm');
await busca(''); __o.takeOdd = toma('mx');
await busca(''); __o.takeSsd = toma('c1');

// 3. The bays offered to a part: the ones its class fits.
const huecos = (kind, mount, tree) => {
    _dcCompDraft = {where: 'item', kind, mount: mount || '', slot: '', qty: 1, kit_qty: 1,
                    tree: tree || ''};
    return _dcCompSlots().map(x => x.name);
};
__o.slots = {psu: huecos('psu'), fan: huecos('fan'), optic: huecos('transceiver'),
             ssd: huecos('ssd'), other: huecos('other'), memory: huecos('memory'),
             psuModule: huecos('psu', '', 'module-types'),
             opticModule: huecos('transceiver', '', 'module-types'),
             nicModule: huecos('nic', '', 'module-types'),
             psuStrict: (abre(STRICT), huecos('psu', '', 'module-types'))};
__o.pure = {
    psuInPsu: _dcBayTakes({fam: 'module-bays', type: 'psu-bay'}, 'module-types', 'psu'),
    fanInPsu: _dcBayTakes({fam: 'module-bays', type: 'psu-bay'}, 'module-types', 'fan'),
    modInDrive: _dcBayTakes({fam: 'module-bays', type: 'drive-bay'}, 'module-types', 'module'),
    ssdInDrive: _dcBayTakes({fam: 'module-bays', type: 'drive-bay'}, 'component-types', 'ssd'),
    optInCage: _dcBayTakes({fam: 'module-bays', type: 'sfp-cage'}, 'module-types', 'transceiver'),
    optInSfp: _dcBayTakes({fam: 'interfaces', type: '10gbase-x-sfpp'}, 'module-types', 'transceiver'),
    optInRj45: _dcBayTakes({fam: 'interfaces', type: '1000base-t'}, 'module-types', 'transceiver'),
    anyInGeneric: _dcBayTakes({fam: 'module-bays', type: 'module-bay'}, 'module-types', 'nic'),
    anyInUntyped: _dcBayTakes({fam: 'module-bays', type: ''}, 'module-types', 'psu'),
    modInNodeBay: _dcBayTakes({fam: 'device-bays', type: 'device-bay'}, 'module-types', 'psu'),
};
__o.table = Object.keys(_DC_BAY_TAKES);

// 4. From the face: clicking a PSU bay starts a part in it, and the search keeps to it.
abre(FULL);
_dcPmPutIn('PSU bay 2');
pedidas = [];
await _dcCompSearch();
__o.fromFace = {slot: _dcCompDraft.slot, rows: _dcCompDraft.rows.map(r => r.uid)};
})().then(() => {}, (e) => { __o.fallo = String(e && e.stack || e); });
"""


@pytest.fixture(scope='module')
def out():
    """One `node` run for the whole module: starting it costs more than looking."""
    if shutil.which(os.environ.get('SS_NODE') or 'node') is None:
        pytest.skip('no node: nothing to run the script with')
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    res = node_run(panel_bundle(c), _PROBE)
    assert not res.get('fallo'), res.get('fallo')
    return res


class TestTheSearch:

    def test_it_looks_in_modules_when_a_bay_takes_them(self, out):
        assert any('tree=component-types' in u for u in out['full']['asked'])
        assert any('tree=module-types' in u for u in out['full']['asked'])
        # A generic module bay takes any module, so all of them are offered with the components.
        assert set(out['full']['rows']) == {'c1', 'c2', 'c3', 'mp', 'mf', 'mt', 'mn', 'mm', 'mx'}
        assert 'module-types' not in out['listHtml'] or 'PSU 800' in out['listHtml']

    def test_only_the_modules_some_bay_fits(self, out):
        # A PSU bay and a drive bay: power supplies, and no fan, optic, card or controller.
        assert set(out['strict']['rows']) == {'c1', 'c2', 'c3', 'mp'}

    def test_drive_bays_take_no_module_so_none_is_asked(self, out):
        assert [u for u in out['drives']['asked'] if 'module-types' in u] == []
        assert set(out['drives']['rows']) == {'c1', 'c2', 'c3'}

    def test_with_a_bay_chosen_only_what_fits_it(self, out):
        assert set(out['inPsu']['rows']) == {'mp', 'c3'}
        assert set(out['inDrive']['rows']) == {'c1'}
        assert set(out['inFan']['rows']) == {'mf'}         # matched however it was typed
        assert set(out['inCage']['rows']) == {'mt'}
        assert set(out['inAny']['rows']) == {'c1', 'c2', 'c3', 'mp', 'mf', 'mt', 'mn', 'mm', 'mx'}

    def test_from_the_face_the_bay_is_kept(self, out):
        assert out['fromFace']['slot'] == 'PSU bay 2'
        assert set(out['fromFace']['rows']) == {'mp', 'c3'}

    def test_a_module_says_so_in_the_list(self, out):
        assert 'PSU 800' in out['listHtml']
        i = out['listHtml'].index('PSU 800')
        assert 'bg-info-subtle' in out['listHtml'][max(0, i - 400):i]


class TestTakingOne:

    def test_the_parts_class_comes_from_the_model(self, out):
        assert out['takePsu'] == {'kind': 'psu', 'tree': 'module-types', 'type': 'mp',
                                  'model': 'PSU 800'}
        assert out['takeCtrl']['kind'] == 'module'
        # A module carrying a class no part has (a device's, by mistake) is a module.
        assert out['takeOdd']['kind'] == 'module'
        assert out['takeSsd'] == {'kind': 'ssd', 'tree': 'component-types', 'type': 'c1',
                                  'model': 'SSD'}


class TestTheBaysOffered:

    def test_each_class_its_bays(self, out):
        s = out['slots']
        assert s['psu'] == ['PSU bay 1', 'PSU bay 2', 'OCP 3.0', 'Slot X']
        assert s['fan'] == ['Fan 1', 'OCP 3.0', 'Slot X']
        # The bays made for it first, then the generic ones (where an M.2 SSD goes).
        assert s['optic'] == ['sfp0', 'OCP 3.0', 'Slot X']
        assert s['ssd'] == ['Drive 0', 'OCP 3.0', 'Slot X']
        assert s['memory'] == ['OCP 3.0', 'Slot X']
        # A MODULE goes only in the bays made for it when the device has any — nobody puts a
        # power supply in a DIMM slot —; a module no bay is made for, in the generic ones.
        assert s['psuModule'] == ['PSU bay 1', 'PSU bay 2']
        assert s['opticModule'] == ['sfp0']
        assert s['nicModule'] == ['OCP 3.0', 'Slot X']
        assert s['psuStrict'] == ['PSU bay 1']
        # A part that does not say what it is is offered every bay, as before.
        assert s['other'] == ['PSU bay 1', 'PSU bay 2', 'Fan 1', 'Drive 0', 'OCP 3.0', 'Slot X']

    def test_the_rule(self, out):
        p = out['pure']
        assert p['psuInPsu'] and not p['fanInPsu']
        assert not p['modInDrive'] and p['ssdInDrive']
        assert p['optInCage'] and p['optInSfp'] and not p['optInRj45']
        assert p['anyInGeneric'] and p['anyInUntyped'] and not p['modInNodeBay']
        assert set(out['table']) == {'psu-bay', 'fan-bay', 'sfp-cage', 'drive-bay', 'module-bay'}
