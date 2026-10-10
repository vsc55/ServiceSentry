#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Why a device is in trouble, said where it is clicked — in `node`, and over the demo.

Asked for: clicking a device in error or warning should say the error or warning that raised
it, not only its colour. A device with a machine behind it says its failing checks, asked of the
same route as the device's own modal (and under its permissions); a demo item says the reason
the demo gave it. The 3D card, the rack's list, the item's form, the board and the plan's
inspector all say it.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

_PROBE = r"""
__out = {};
// A demo item says its reason, a fine one says nothing, one with a device waits for its checks.
const demo = _dcimWhyHtml({state: 'error', demo_reason: 'Fuente 2 sin tensión'}, 'w1');
__out.demo = [demo.includes('Fuente 2 sin tensión'), demo.includes('alert-danger'),
              !demo.includes('data-why-wait')];
__out.bien = _dcimWhyHtml({state: 'ok', demo_reason: 'x'}, 'w2');
__out.sinVigilar = _dcimWhyHtml({state: '', demo_reason: 'x'}, 'w3');
const conMaquina = _dcimWhyHtml({state: 'warning', device_uid: 'd1', demo_reason: 'no se usa'}, 'w4');
__out.conMaquina = [conMaquina.includes('data-why-wait'), !conMaquina.includes('no se usa'),
                    conMaquina.includes('alert-warning')];
__out.sinMotivo = _dcimWhyHtml({state: 'error'}, 'w5').includes(t('dcim_why_unknown'));

// Its failing checks, and only those, each with its message (from the cache: no await).
let puesto = '';
const espera = {set outerHTML(v) { puesto = v; }, textContent: ''};
document.getElementById = () => ({querySelector: () => espera});
_dcimWhyCache.set('d1', {t: Date.now(), data: {results: [
    {name: 'Ping', ok: true, level: 'ok', message: 'responde'},
    {name: 'RAID', ok: false, level: 'error', message: 'md0 degradado'},
    {name: 'Temperatura', ok: false, level: 'warning', message: '88 °C'}]}});
_dcimWhyFill('w4', {state: 'warning', device_uid: 'd1'});
__out.fallan = [puesto.includes('md0 degradado'), puesto.includes('88 °C'), !puesto.includes('responde')];
// Without permission to see the machine: says so, not a hole.
_dcimWhyCache.set('d2', {t: Date.now(), data: null});
_dcimWhyFill('w6', {state: 'error', device_uid: 'd2'});
__out.sinPermiso = espera.textContent === t('dcim_why_noperm');

// Where it is said.
__out.donde = {
    tarjeta3d: _dc3dCardHtml({name: 'srv', kind: 'S', tipo: 'item', uid: 'a', state: 'error',
                              reason: 'RAID fallido'}).includes('RAID fallido'),
    pieza3d: _dc3dCardHtml({name: 'Puerta', kind: 'Puerta', tipo: 'feature', uid: 'f', state: 'warning',
                            reason: 'pila baja'}).includes('pila baja'),
    listaRack: String(_dcimItemRow).includes('_dcimWhyOpenUid('),
    formulario: String(_dcimFormBody).includes("_dcimWhyHtml(row"),
    cuadro: _dcimTroubleRow({state: 'error', name: 'SW', item_uid: 'i', rack_uid: 'k', site: 's',
                             room: 'r', rack: 'k', reason: 'Las dos fuentes'}).includes('Las dos fuentes'),
    inspector: String(_dcpAccessHtml).includes("_dcimWhyHtml(f"),
};

// «Go to device»: to its page in Infrastructure, from every card that has one.
const conDisp = _dc3dCardHtml({name: 'srv', kind: 'S', tipo: 'item', uid: 'a', state: 'ok', device: 'dv1'});
const sinDisp = _dc3dCardHtml({name: 'srv', kind: 'S', tipo: 'item', uid: 'a', state: 'ok'});
__out.ir = {
    tarjeta: conDisp.includes('_dcimOpenDevice(' + jsStr('dv1') + ')') && conDisp.includes(t('dcim_go_device')),
    primero: conDisp.indexOf(t('dcim_go_device')) < conDisp.indexOf(t('edit')),
    sinDispositivoLoDice: sinDisp.includes(t('dcim_no_device_linked')) && !sinDisp.includes('_dcimOpenDevice'),
    pieza: _dc3dCardHtml({name: 'IQ', kind: 'Lector', tipo: 'feature', uid: 'f', device: 'dv2'})
               .includes('_dcimOpenDevice(' + jsStr('dv2') + ')'),
    cuadro: _dcimTroubleRow({state: 'error', name: 'SW', item_uid: 'i', rack_uid: 'k', site: 's', room: 'r',
                             rack: 'k', device_uid: 'dv3'}).includes('_dcimOpenDevice(' + jsStr('dv3') + ')'),
    cuadroSin: !_dcimTroubleRow({state: 'error', name: 'SW', item_uid: 'i', rack_uid: 'k', site: 's',
                                 room: 'r', rack: 'k'}).includes('_dcimOpenDevice'),
    ventana: String(_dcimWhyOpen).includes('_dcimGoDeviceBtn('),
};
"""


@pytest.fixture(scope='module')
def built():
    pytest.importorskip('flask')
    from lib.core.dcim import demo                                  # noqa: PLC0415
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    demo.build(wa._dcim_store, var_dir=var, lang='es_ES')
    c = wa.app.test_client()
    _login(c)
    return wa, c


class TestTheDemoSaysWhy:

    def test_every_item_in_trouble_has_its_reason_and_the_fine_ones_none(self, built):
        from lib.core.dcim import demo, service                     # noqa: PLC0415
        wa, _c = built
        s = wa._dcim_store
        items = [i for r in s.racks.list() for i in s.items_of(r['uid'])]
        for i in items:
            malo = service.item_state(i, {}) in ('error', 'warning')
            assert bool(i['demo_reason']) == malo, (i['label'], i['demo_state'], i['demo_reason'])
        assert set(demo._WHY) == set(demo._TROUBLE)

    def test_the_access_pieces_in_trouble_too(self, built):
        wa, _c = built
        s = wa._dcim_store
        piezas = [f for r in s.rooms.list() for f in s.features_of(r['uid'])
                  if f['demo_state'] in ('error', 'warning')]
        assert piezas and all(f['demo_reason'] for f in piezas)

    def test_the_board_brings_it_with_each_row(self, built):
        _wa, c = built
        filas = c.get('/api/v1/dcim/board').get_json()['trouble']
        assert filas and all(f['reason'] for f in filas)


@pytest.fixture(scope='module')
def out(built):
    if shutil.which('node') is None:
        pytest.skip('no node: nothing to run the script with')
    _wa, c = built
    return node_run(panel_bundle(c), _PROBE)


class TestTheScreensSayIt:

    def test_a_demo_item_says_its_reason_and_a_fine_one_nothing(self, out):
        assert out['demo'] == [True, True, True]
        assert out['bien'] == '' and out['sinVigilar'] == ''

    def test_one_with_a_device_asks_for_its_checks(self, out):
        assert out['conMaquina'] == [True, True, True]
        assert out['sinMotivo'] is True

    def test_only_the_failing_checks_with_their_message(self, out):
        assert out['fallan'] == [True, True, True]

    def test_without_permission_it_says_so(self, out):
        assert out['sinPermiso'] is True

    def test_go_to_device_from_every_card_that_has_one(self, out):
        """Asked for: beside Edit, a button that goes to the device's own data —its SNMP
        results, its modules—; and where there is none, the card says why there is no button."""
        assert out['ir'] == dict.fromkeys(
            ('tarjeta', 'primero', 'sinDispositivoLoDice', 'pieza', 'cuadro', 'cuadroSin',
             'ventana'), True)

    def test_said_wherever_it_is_clicked(self, out):
        assert out['donde'] == dict.fromkeys(
            ('tarjeta3d', 'pieza3d', 'listaRack', 'formulario', 'cuadro', 'inspector'), True)
