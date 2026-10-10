#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where each port is on a model's face (catálogo › modelo › «Situar puertos»).

The libraries a catalogue is imported from say how many ports a model has and what they are
called, not where they are. A person places them on the front or rear picture; the table says
which models are done; a re-import keeps the work; and in the rack, a cable leaves its own port.
"""

import io
import os
import shutil
import tempfile

import pytest

from lib.core.dcim import catalog as dcim_catalog
from lib.core.dcim.catalog import CatalogStore, clean_port_map, port_slots
from lib.db import get_connector
from tests.conftest import _login
from tests.helpers import node_run, panel_bundle

_SWITCH = {'manufacturer': 'Acme', 'model': 'SW-8',
           'ports': {'interfaces': {'1000base-t': 8}, 'power-ports': {'iec-60320-c14': 1}},
           'port_list': {'interfaces': [{'name': 'gi%d' % (i + 1), 'type': '1000base-t'}
                                        for i in range(8)],
                         'power-ports': [{'name': 'PSU', 'type': 'iec-60320-c14'}]}}


@pytest.fixture()
def cat(tmp_path):
    return CatalogStore(get_connector(None, default_sqlite_path=str(tmp_path / 'data.db')))


class TestWhatCanBePlaced:

    def test_by_name_from_the_list_and_numbered_by_type_from_a_count(self):
        """Reported from the screen: a hand-written model listed «Puertos frontales 1, 2, 3»,
        and which of the three was the USB-C could not be told. Counted ports are numbered
        within their type."""
        assert port_slots(_SWITCH)[:2] == ['interfaces|gi1', 'interfaces|gi2']
        assert port_slots(_SWITCH)[-1] == 'power-ports|PSU'
        solo_cuenta = {'ports': {'front-ports': {'usb-a': 2, 'usb-c': 1}, 'module-bays': {'sodimm': 2}}}
        # Bays are placed too, on an inside view, after the connectors.
        assert port_slots(solo_cuenta) == ['front-ports|usb-a#1', 'front-ports|usb-a#2',
                                           'front-ports|usb-c#1', 'module-bays|sodimm#1',
                                           'module-bays|sodimm#2']


    def test_only_a_face_a_point_inside_and_a_port_the_model_has(self):
        slots = set(port_slots(_SWITCH))
        limpio = clean_port_map({
            'interfaces|gi1': {'f': 'front', 'x': 0.1, 'y': 0.5},
            'interfaces|gi2': {'f': 'rear', 'x': 2, 'y': -1},           # clamped into the picture
            'interfaces|gi3': {'f': 'top', 'x': 0.1, 'y': 0.1},         # no such face
            'interfaces|gi4': {'f': 'front', 'x': 'nan', 'y': 0.1},     # not a number
            'interfaces|gi99': {'f': 'front', 'x': 0.1, 'y': 0.1},      # not on this model
            'module-bays|1': {'f': 'front', 'x': 0.1, 'y': 0.1},        # not a socket
            'sin-familia': {'f': 'front', 'x': 0.1, 'y': 0.1}}, slots)
        assert limpio == {'interfaces|gi1': {'f': 'front', 'x': 0.1, 'y': 0.5},
                          'interfaces|gi2': {'f': 'rear', 'x': 1.0, 'y': 0.0}}


class TestTheStore:

    def test_saved_whole_counted_and_kept_in_the_history(self, cat):
        uid = cat.create(dict(_SWITCH), 'manual', actor='ana')
        assert cat.get(uid)['ports_total'] == 9 and cat.get(uid)['ports_placed'] == 0
        assert cat.set_port_map(uid, {'interfaces|gi1': {'f': 'front', 'x': .1, 'y': .3},
                                      'power-ports|PSU': {'f': 'rear', 'x': .9, 'y': .5}},
                                actor='ana')
        fila = cat.get(uid)
        assert fila['ports_placed'] == 2 and fila['rev'] == 2 and fila['updated_by'] == 'ana'
        # Whole: what is not sent again is no longer placed.
        cat.set_port_map(uid, {'interfaces|gi1': {'f': 'front', 'x': .2, 'y': .3}})
        assert set(cat.get(uid)['port_map']) == {'interfaces|gi1'}
        assert any(h.get('action') == 'port_map' for h in cat.revs.history(uid))

    def test_a_reimport_keeps_where_somebody_put_the_ports(self, cat):
        cat.replace('library', [dict(_SWITCH)])
        uid = cat.list('source = ?', ('library',))[0]['uid']
        cat.set_port_map(uid, {'interfaces|gi5': {'f': 'front', 'x': .5, 'y': .5}})
        cat.replace('library', [dict(_SWITCH)])
        nuevo = cat.list('source = ?', ('library',))[0]
        assert nuevo['uid'] != uid                      # the import made a new row…
        assert nuevo['port_map'] == {'interfaces|gi5': {'f': 'front', 'x': .5, 'y': .5}}


# ── Through the panel ────────────────────────────────────────────────────────────────────────

def _model(admin, **extra):
    return admin._dcim_catalog.create(dict(_SWITCH, **extra), 'manual', actor='t')


class TestTheRoute:

    def test_save_answer_the_count_and_drop_what_is_not_there(self, admin, client):
        _login(client)
        uid = _model(admin)
        r = client.put(f'/api/v1/dcim/catalog/{uid}/portmap', json={'map': {
            'interfaces|gi1': {'f': 'front', 'x': .1, 'y': .3},
            'interfaces|nope': {'f': 'front', 'x': .1, 'y': .3}}})
        assert r.status_code == 200 and r.get_json()['placed'] == 1
        assert r.get_json()['total'] == 9
        fila = next(t for t in client.get('/api/v1/dcim/catalog?q=sw-8').get_json()['types']
                    if t['uid'] == uid)
        assert fila['ports_placed'] == 1 and fila['ports_total'] == 9
        assert fila['port_slots'][0] == 'interfaces|gi1'
        assert fila['port_slot_types']['interfaces|gi1'] == '1000base-t'

    def test_without_a_map_or_a_model(self, admin, client):
        _login(client)
        uid = _model(admin)
        assert client.put(f'/api/v1/dcim/catalog/{uid}/portmap', json={}).status_code == 400
        assert client.put('/api/v1/dcim/catalog/nope/portmap',
                          json={'map': {}}).status_code == 404

    def test_it_takes_managing_the_catalogue(self, admin):
        from tests.integration.test_wa_dcim import _as
        uid = _model(admin)
        c = _as(admin, 'lector-pm', ['dcim_view', 'dcim_catalog_view'])
        assert c.put(f'/api/v1/dcim/catalog/{uid}/portmap',
                     json={'map': {}}).status_code == 403

    def test_the_rack_brings_each_items_ports(self, admin, client):
        _login(client)
        uid = _model(admin)
        admin._dcim_catalog.set_port_map(uid, {'interfaces|gi1': {'f': 'front', 'x': .1, 'y': .3}})
        site = client.post('/api/v1/dcim/sites', json={'name': 'S'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'R'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'K',
                                                         'u_height': 42}).get_json()['uid']
        client.post('/api/v1/dcim/items', json={'rack_uid': rack, 'label': 'sw', 'u_start': 1,
                                                 'u_height': 1, 'type_uid': uid})
        item = client.get(f'/api/v1/dcim/racks/{rack}').get_json()['items'][0]
        assert item['ports_at']['map'] == {'interfaces|gi1': {'f': 'front', 'x': .1, 'y': .3}}
        assert item['ports_at']['slots'][0] == 'interfaces|gi1'


_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="30"></svg>'
_MINI = {'manufacturer': 'Acme', 'model': 'Mini',
         'ports': {'module-bays': {'sodimm': 2, 'cpu-socket': 1}, 'front-ports': {'usb-a': 1}}}


class TestInsideViews:
    """Asked for from the screen: where the CPU and the memory go — on the board, or on a part of
    a server's chassis — so several named inside views, with the bays placed on each."""

    def test_add_rename_picture_and_drop_with_what_was_placed_on_it(self, admin, client):
        _login(client)
        uid = admin._dcim_catalog.create(dict(_MINI), 'manual', actor='t')
        r = client.post(f'/api/v1/dcim/catalog/{uid}/views',
                        data={'name': 'Placa', 'file': (io.BytesIO(_SVG), 'placa.svg')},
                        content_type='multipart/form-data')
        assert r.status_code == 200 and r.get_json()['image']
        vid = r.get_json()['id']
        primera = r.get_json()['image']
        assert client.post(f'/api/v1/dcim/catalog/{uid}/views', data={'name': ''},
                           content_type='multipart/form-data').status_code == 400
        assert client.put(f'/api/v1/dcim/catalog/{uid}/views/{vid}',
                          json={'name': 'Placa base'}).status_code == 200
        r = client.post(f'/api/v1/dcim/catalog/{uid}/views/{vid}/image',
                        data={'file': (io.BytesIO(_SVG), 'otra.svg')},
                        content_type='multipart/form-data')
        assert r.status_code == 200 and r.get_json()['image'] != primera
        # A bay on the view; a USB port cannot go on a face that does not exist.
        client.put(f'/api/v1/dcim/catalog/{uid}/portmap', json={'map': {
            'module-bays|sodimm#1': {'f': 'v:' + vid, 'x': .4, 'y': .5},
            'front-ports|usb-a#1': {'f': 'front', 'x': .5, 'y': .5},
            'module-bays|sodimm#2': {'f': 'v:deadbeef', 'x': .4, 'y': .5}}})
        fila = admin._dcim_catalog.get(uid)
        assert fila['views'] == [{'id': vid, 'name': 'Placa base', 'image': fila['views'][0]['image']}]
        assert set(fila['port_map']) == {'module-bays|sodimm#1', 'front-ports|usb-a#1'}
        # The table's mark counts connectors; the bays are counted apart.
        assert (fila['ports_placed'], fila['ports_total']) == (1, 1)
        assert (fila['bays_placed'], fila['bays_total']) == (1, 3)
        assert client.delete(f'/api/v1/dcim/catalog/{uid}/views/{vid}').status_code == 200
        fila = admin._dcim_catalog.get(uid)
        assert fila['views'] == [] and set(fila['port_map']) == {'front-ports|usb-a#1'}

    def test_it_takes_managing_the_catalogue(self, admin):
        from tests.integration.test_wa_dcim import _as
        uid = admin._dcim_catalog.create(dict(_MINI), 'manual', actor='t')
        c = _as(admin, 'lector-vistas', ['dcim_view', 'dcim_catalog_view'])
        assert c.post(f'/api/v1/dcim/catalog/{uid}/views', data={'name': 'X'},
                      content_type='multipart/form-data').status_code == 403

    def test_a_reimport_keeps_the_views(self, cat):
        cat.replace('library', [dict(_MINI)])
        uid = cat.list('source = ?', ('library',))[0]['uid']
        cat.set_views(uid, [{'id': 'abcd1234', 'name': 'Placa', 'image': ''}])
        cat.set_port_map(uid, {'module-bays|sodimm#1': {'f': 'v:abcd1234', 'x': .1, 'y': .1}})
        cat.replace('library', [dict(_MINI)])
        nuevo = cat.list('source = ?', ('library',))[0]
        assert nuevo['views'][0]['name'] == 'Placa'
        assert nuevo['port_map']['module-bays|sodimm#1']['f'] == 'v:abcd1234'

    def test_an_items_parts_bring_its_models_inside(self, admin, client):
        _login(client)
        uid = admin._dcim_catalog.create(dict(_MINI), 'manual', actor='t')
        admin._dcim_catalog.set_views(uid, [{'id': 'abcd1234', 'name': 'Placa', 'image': ''}])
        admin._dcim_catalog.set_port_map(uid, {'module-bays|sodimm#1': {'f': 'v:abcd1234',
                                                                        'x': .1, 'y': .1}})
        site = client.post('/api/v1/dcim/sites', json={'name': 'S'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'R'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'K',
                                                         'u_height': 42}).get_json()['uid']
        item = client.post('/api/v1/dcim/items', json={'rack_uid': rack, 'label': 'pc', 'u_start': 1,
                                                        'u_height': 1, 'type_uid': uid}).get_json()['uid']
        model = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()['model']
        assert model['views'][0]['id'] == 'abcd1234'
        assert model['port_map']['module-bays|sodimm#1']['f'] == 'v:abcd1234'
        assert 'module-bays|sodimm#1' in model['port_slots']


class TestAPartsPlaceInside:
    """Asked for from the screen: once the inside pictures exist, placing the parts configured on
    that device — in a bay, or freely on a view when there is no bay for it."""

    def test_only_a_view_and_a_point_inside_are_kept(self):
        import json
        from lib.core.dcim.store import clean_place
        assert json.loads(clean_place({'v': 'abcd1234', 'x': 2, 'y': .5})) == \
            {'v': 'abcd1234', 'x': 1.0, 'y': .5}
        assert clean_place('{"v": "abcd1234", "x": 0.1, "y": 0.2}')
        for malo in ({'v': '../x', 'x': .1, 'y': .1}, {'v': 'abcd1234', 'x': 'nan', 'y': .1},
                     'no es json', None, ''):
            assert clean_place(malo) == ''

    def test_saved_through_the_parts_route(self, admin, client):
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'S'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'R'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'K',
                                                         'u_height': 42}).get_json()['uid']
        item = client.post('/api/v1/dcim/items', json={'rack_uid': rack, 'label': 'pc', 'u_start': 1,
                                                        'u_height': 1}).get_json()['uid']
        part = client.post('/api/v1/dcim/parts', json={'item_uid': item, 'kind': 'gpu'}).get_json()['uid']
        assert client.put(f'/api/v1/dcim/parts/{part}', json={
            'place': '{"v": "abcd1234", "x": 0.3, "y": 0.4}'}).status_code == 200
        guardada = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()['parts'][0]
        assert guardada['place'] == '{"v": "abcd1234", "x": 0.3, "y": 0.4}'
        client.put(f'/api/v1/dcim/parts/{part}', json={'place': '<script>'})
        assert client.get(f'/api/v1/dcim/items/{item}/parts').get_json()['parts'][0]['place'] == ''


class TestTheDemoStateIsNotWritable:

    def test_no_request_writes_an_items_demo_state(self, admin, client):
        """Only the demo writes it: through a request anybody could paint a real item red."""
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'S'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'R'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'K',
                                                         'u_height': 42}).get_json()['uid']
        item = client.post('/api/v1/dcim/items', json={'rack_uid': rack, 'label': 'x', 'u_start': 1,
                                                        'u_height': 1, 'demo_state': 'error',
                                                        'demo_reason': 'x'}).get_json()['uid']
        client.put(f'/api/v1/dcim/items/{item}', json={'demo_state': 'error', 'demo_reason': 'x',
                                                        'label': 'y'})
        fila = client.get(f'/api/v1/dcim/racks/{rack}').get_json()['items'][0]
        assert fila['label'] == 'y' and not fila.get('demo_state') and not fila['state']
        assert not fila.get('demo_reason')


# ── In the browser ───────────────────────────────────────────────────────────────────────────

_PROBE = r"""
__out = {};
// Two rows, odd on top: port 1 top-left, 2 below it, the last column at the second click.
const dos = _dcPmSpread(6, {x: 0.1, y: 0.2}, {x: 0.5, y: 0.6}, true);
__out.dos = dos.map(p => [Number(p.x.toFixed(2)), Number(p.y.toFixed(2))]);
const fila = _dcPmSpread(3, {x: 0, y: 0.5}, {x: 1, y: 0.5}, false);
__out.fila = fila.map(p => p.x);
// The table's mark: none, some, all — and nothing for a model with no ports.
_dcimMay = () => false;
__out.badge = [_dcPmBadge({ports_total: 0}), _dcPmBadge({ports_total: 4, ports_placed: 0}),
               _dcPmBadge({ports_total: 4, ports_placed: 2}), _dcPmBadge({ports_total: 4, ports_placed: 4})];
// In the rack: a port by its name, by the number it ends in, and a power inlet by its order.
const pa = {slots: ['interfaces|gi1', 'interfaces|gi2', 'interfaces|gi7', 'power-ports|PSU1', 'power-ports|PSU2'],
            map: {'interfaces|gi1': {f: 'front', x: 0.25, y: 0.5}, 'interfaces|gi7': {f: 'rear', x: 0.8, y: 0.5},
                  'power-ports|PSU2': {f: 'rear', x: 0.9, y: 0.4}}};
__out.at = [_dcr3dPortAt(pa, 'interfaces', 'gi1'), _dcr3dPortAt(pa, 'interfaces', 'GI1'),
            _dcr3dPortAt(pa, 'interfaces', 'Gi1/0/3'), _dcr3dPortAt(pa, 'interfaces', 'eth9'),
            _dcr3dPortAt(pa, 'power-ports', '', 2), _dcr3dPortAt(null, 'interfaces', 'gi1')];
// The front picture is seen towards +z, so its left (x = 0.25) is the larger x of the box.
const e = {x: 0, y: 0, w: 1, h: 1, z: 0, fondo: 0.5};
__out.punto = [_dcr3dPortPoint(e, {f: 'front', x: 0.25, y: 0.5}), _dcr3dPortPoint(e, {f: 'rear', x: 0.25, y: 0.5})];
// And a cable leaves from there.
const sc = _dcr3dScene({rack: {uid: 'k', u_height: 10, width_mm: 600, depth_mm: 1000},
    items: [{uid: 'a', role: 'server', u_start: 1, u_height: 1, face: 'full', placement: 'u', ports_at: pa},
            {uid: 'b', role: 'switch', u_start: 5, u_height: 1, face: 'full', placement: 'u'}]},
    {redes: true, cables: {cables: [{a_item: 'a', a_port: 'gi1', b_item: 'b', kind: 'copper'}]}});
const caja = sc.cajas.find(k => k.lee && k.lee.uid === 'a');
const primero = sc.cajas.find(k => k.cable);
__out.sale = [primero.m[12] > caja.m[12] + caja.m[0] * 0.5, primero.m[14] < caja.m[14]];
// The model form, in tabs: what it is, how it is outside, how it connects; and the ports tab
// carries the placing editor for the model being edited.
let __html = '';
showHtmlModal = (titulo, h) => { __html = h; };
__out.embebido = '';
const _embedReal = _dcPmEmbed;
_dcPmEmbed = (r) => { __out.embebido = r.uid; };
_dcCat = {rows: [], lifecycle_fields: []};
_dcBrands = {rows: []};
const modelo = {uid: 'm1', manufacturer: 'Acme', model: 'X', tree: 'device-types',
                ports: {interfaces: {'1000base-t': 2}}, port_slots: ['interfaces|1', 'interfaces|2'],
                extra: {}};
_dcCatEdit(modelo, false);
const datos = __html;
_dcCatFormGo('phys');
const fisico = __html;
_dcCatFormGo('ports');
const puertos = __html;
__out.form = {
    datos: datos.includes('_dcCatForm.description') && !datos.includes("_dcCatForm['full_depth']")
           && !datos.includes('dcPmBody'),
    fisico: fisico.includes("_dcCatForm['full_depth']") && !fisico.includes('_dcCatForm.description')
            && !fisico.includes('dcPmBody'),
    puertos: puertos.includes('dcPmBody') && !puertos.includes('_dcCatForm.description'),
    pestanas: ['phys', 'ports'].every(k => datos.includes(`_dcCatFormGo('${k}')`)),
};
// A model not saved yet has nothing to place: the tab says to save first.
_dcCatEdit(null, false);
_dcCatFormGo('ports');
__out.nuevo = !__html.includes('dcPmBody');
_dcPmEmbed = _embedReal;
// How a port is named in the list: by its type and number when it has no name of its own.
_dcSpeedName = (tipo) => ({'usb-c': 'USB-C', '1000base-t': '1 Gbps'})[tipo] || tipo;
const nombrada = {port_slot_types: {'front-ports|usb-c#1': 'usb-c', 'interfaces|eth0': '1000base-t'}};
__out.nombres = [_dcPmName('front-ports|usb-c#1', nombrada), _dcPmName('interfaces|eth0', nombrada),
                 _dcPmType('interfaces|eth0', nombrada), _dcPmType('front-ports|usb-c#1', nombrada)];
// Inside views: faces of the editor, and which part is in which bay of an item.
const conVistas = {front_image: 'f.png', rear_image: '', views: [{id: 'abcd1234', name: 'Placa', image: 'p.png'}]};
__out.carasVista = _dcPmFaces(conVistas).map(x => [x.f, x.name, x.image]);
_dcBaySlug = (n) => String(n || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
_dcSpeedName = (tipo) => ({'sodimm': 'SODIMM', 'cpu-socket': 'Socket CPU'})[tipo] || tipo;
const dentro = _dcPmInsideOf({port_slots: ['module-bays|sodimm#1', 'module-bays|sodimm#2', 'module-bays|cpu-socket#1',
                                           'front-ports|usb-a#1'],
                              port_map: {'module-bays|sodimm#1': {f: 'v:abcd1234', x: .3, y: .4},
                                         'module-bays|sodimm#2': {f: 'v:abcd1234', x: .3, y: .5},
                                         'front-ports|usb-a#1': {f: 'front', x: .5, y: .5}}},
                             [{uid: 'p1', kind: 'memory', brand: 'Kingston', model: '16GB', slot: 'SODIMM-1'}]);
__out.dentro = dentro.map(b => [b.name, b.view, b.part ? b.part.uid : null]);
// An item's parts, inside: in a bay, free on a view, with a slot not drawn, or nowhere.
const modeloDentro = {views: [{id: 'abcd1234', name: 'Placa'}],
    port_slots: ['module-bays|sodimm#1', 'module-bays|sodimm#2'],
    port_map: {'module-bays|sodimm#1': {f: 'v:abcd1234', x: .3, y: .4}}};
const piezas = [{uid: 'm', kind: 'memory', slot: 'SODIMM 1'},
                {uid: 'g', kind: 'gpu', place: '{"v": "abcd1234", "x": 0.5, "y": 0.5}'},
                {uid: 's', kind: 'ssd', slot: 'NVMe 1'},
                {uid: 'n', kind: 'other'},
                {uid: 'x', kind: 'nic', place: '{"v": "ffffffff", "x": 0.5, "y": 0.5}'}];
__out.donde = _dcPmPartsWhere(modeloDentro, piezas).map(w => [w.part.uid, w.where]);
// Reported from a browser run: adding an inside view after placing, before saving, threw the
// placed positions away and «Guardar» no longer sent them. The editor keeps them now.
// Opening on the inside view when only bays are placed; the table's mark counts them.
__out.abreVista = _dcPmStartFace({views: [{id: 'abcd1234'}]}, {'module-bays|x#1': {f: 'v:abcd1234'}});
__out.marcaBahias = _dcPmBadge({ports_total: 2, ports_placed: 0, bays_total: 3, bays_placed: 3});
// Putting a part in a bay: in again takes it out, a kit of two takes a second, a full one moves.
__out.huecos = [_dcPmInSlots({slot: 'SODIMM 1', qty: 1}, 'SODIMM 1'),
                _dcPmInSlots({slot: 'SODIMM 1', qty: 1, kit_qty: 2}, 'SODIMM 2'),
                _dcPmInSlots({slot: 'SODIMM 1', qty: 1}, 'SODIMM 2')];
// Several at once: Ctrl and Shift in the list, a box on the picture, moved and removed together.
_dcPmDraw = () => {};
const varias = {uid: 'v', port_slots: ['interfaces|1', 'interfaces|2', 'interfaces|3', 'interfaces|4'],
                port_map: {'interfaces|1': {f: 'front', x: 0.1, y: 0.5}, 'interfaces|2': {f: 'front', x: 0.2, y: 0.5},
                           'interfaces|3': {f: 'front', x: 0.9, y: 0.5}, 'interfaces|4': {f: 'rear', x: 0.15, y: 0.5}}};
_dcPmStart(varias, false);
_dcPmPick(0);
_dcPmPick(2, {ctrlKey: true});
const conCtrl = _dcPm.marked.slice().sort();
_dcPmPick(0);
_dcPmPick(2, {shiftKey: true});
const conShift = _dcPm.marked.slice().sort();
const enCaja = _dcPmInBox(_dcPm, {x: 0.05, y: 0.4}, {x: 0.3, y: 0.6});
_dcPm.marked = enCaja;
_dcPmNudge(0.85, 0);
const movidas = ['interfaces|1', 'interfaces|2', 'interfaces|4'].map(k => _dcPm.map[k].x);
_dcPmUnplace();
__out.varias = {conCtrl, conShift, enCaja, movidas,
                quedan: Object.keys(_dcPm.map).sort(), deshacer: _dcPm.undo.length};
// Each face lists what can go on it: a front port only in front, a rear port only behind, and
// what is placed on one face no longer on the other.
const caras = {uid: 'c', port_slots: ['front-ports|1', 'rear-ports|1', 'interfaces|eth0', 'interfaces|eth1'],
               port_map: {'interfaces|eth1': {f: 'rear', x: 0.5, y: 0.5}}};
_dcPmStart(caras, false);
// Only eth1 is placed, behind: the editor opens on the face that has something.
__out.abreDetras = _dcPm.face;
_dcPmFace('front');
const delante = _dcPmFaceSlots(_dcPm);
_dcPmFace('rear');
const detras = _dcPmFaceSlots(_dcPm);
const elegidaDetras = _dcPm.sel;
// Placing one by one behind goes on to the next one that goes behind.
_dcPm.sel = 1;
_dcPmClick({target: {classList: {contains: () => false}}, clientX: 0, clientY: 0});
__out.caras = {delante, detras, elegidaDetras, siguiente: _dcPm.sel,
               situada: _dcPm.map['rear-ports|1'] && _dcPm.map['rear-ports|1'].f};
"""


@pytest.fixture(scope='module')
def out():
    pytest.importorskip('flask')
    if shutil.which('node') is None:
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
    return node_run(panel_bundle(c), _PROBE)


class TestTheEditor:

    def test_two_rows_odd_on_top_and_one_row_spread(self, out):
        assert out['dos'] == [[0.1, 0.2], [0.1, 0.6], [0.3, 0.2], [0.3, 0.6], [0.5, 0.2], [0.5, 0.6]]
        assert out['fila'] == [0, 0.5, 1]

    def test_the_tables_mark(self, out):
        nada, ninguno, algunos, todos = out['badge']
        assert nada == ''
        assert 'bg-secondary' in ninguno and '2/4' in algunos and 'bg-warning' in algunos
        assert 'bg-success' in todos


class TestTheModelForm:

    def test_its_data_in_tabs_and_the_ports_tab_places_them(self, out):
        """Reported from the screen: the data tab was a column of twenty fields, and there was
        no way to place the ports from the form."""
        assert out['form'] == {'datos': True, 'fisico': True, 'puertos': True, 'pestanas': True}
        assert out['embebido'] == 'm1'
        assert out['nuevo']


class TestPortNames:

    def test_a_counted_port_by_its_type_a_named_one_with_its_type_beside(self, out):
        assert out['nombres'] == ['USB-C 1', 'eth0', '1 Gbps', '']


class TestInsideInTheBrowser:

    def test_each_view_is_a_face_of_the_editor(self, out):
        assert out['carasVista'][2] == ['v:abcd1234', 'Placa', 'p.png']
        assert [c[0] for c in out['carasVista'][:2]] == ['front', 'rear']

    def test_which_part_is_in_which_bay_by_the_same_name_the_slot_list_uses(self, out):
        """A bay is named as the list a part's slot is chosen from names it («SODIMM 1»), and
        matched loosely: «SODIMM-1» is the same slot. Unplaced bays and connectors are not
        listed; the CPU socket is not placed, so it is not either."""
        assert out['dentro'] == [['SODIMM 1', 'abcd1234', 'p1'], ['SODIMM 2', 'abcd1234', None]]


class TestAPartsPlaceInTheBrowser:

    def test_where_each_part_is(self, out):
        assert out['donde'] == [['m', 'bay'], ['g', 'free'], ['s', 'slot'], ['n', 'none'],
                                ['x', 'none']]           # a place on a view the model lacks

    def test_putting_a_part_in_a_bay(self, out):
        assert out['huecos'] == [[], ['SODIMM 1', 'SODIMM 2'], ['SODIMM 2']]


class TestWhatLookedUnsaved:
    """From a browser run of «I place the ports on the board's picture and they are not there
    when I open it again»."""

    def test_adding_a_view_keeps_what_is_placed_and_not_saved(self):
        """Adding an inside view or changing a view's picture after placing, before saving,
        threw the placed positions away (`_dcPm = null`), and «Guardar» no longer sent them —
        silently. Checked on the source: these run on `fetch` and `FormData`, which the node
        harness does not have."""
        import re
        src = io.open(os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                                   'lib', 'web_admin', 'templates', 'partials', 'dcim',
                                   '_portmap.html'), encoding='utf-8').read()
        for fn in ('_dcCatViewAdd', '_dcCatViewImg', '_dcCatViewDrop'):
            cuerpo = re.search(r'function %s\(.*?\n}\n' % fn, src.replace('\r\n', '\n'),
                               re.S).group(0)
            assert '_dcPm = null' not in cuerpo, fn

    def test_it_opens_on_the_face_that_has_something_and_the_mark_counts_bays(self, out):
        assert out['abreVista'] == 'v:abcd1234'
        assert '3/5' in out['marcaBahias']


class TestSeveralAtOnce:

    def test_select_with_ctrl_shift_or_a_box_move_and_remove_together(self, out):
        """Asked for from the screen: choosing several ports to remove or move them at once."""
        v = out['varias']
        assert v['conCtrl'] == [0, 2] and v['conShift'] == [0, 1, 2]
        # The box takes what is inside it on this face: not port 3 (outside), not 4 (rear).
        assert v['enCaja'] == [0, 1]
        # Moved together, and stopped at the edge of the picture; the rear one did not move.
        assert v['movidas'] == [pytest.approx(0.95), 1, 0.15]
        assert v['quedan'] == ['interfaces|3', 'interfaces|4'] and v['deshacer'] == 2


class TestEachFaceItsOwn:

    def test_each_face_lists_what_can_go_on_it(self, out):
        """Reported from the screen: every port was listed on both faces, though a front port
        is on the front and a rear one on the rear."""
        c = out['caras']
        assert out['abreDetras'] == 'rear'
        assert c['delante'] == [0, 2]          # front port, eth0; not the rear port, not eth1
        assert c['detras'] == [1, 2, 3]        # rear port, eth0 and eth1 (placed behind)
        assert c['elegidaDetras'] == 1         # the first unplaced one behind
        assert c['situada'] == 'rear' and c['siguiente'] == 2

    def test_the_server_refuses_a_front_port_behind(self):
        slots = {'front-ports|1', 'rear-ports|1'}
        assert clean_port_map({'front-ports|1': {'f': 'rear', 'x': .1, 'y': .1},
                               'rear-ports|1': {'f': 'front', 'x': .1, 'y': .1}}, slots) == {}
        assert clean_port_map({'front-ports|1': {'f': 'front', 'x': .1, 'y': .1}},
                              slots) == {'front-ports|1': {'f': 'front', 'x': .1, 'y': .1}}


class TestInTheRack:

    def test_a_port_by_name_by_number_and_an_inlet_by_order(self, out):
        nombre, mayus, numero, falta, psu2, sin = out['at']
        assert nombre == {'f': 'front', 'x': 0.25, 'y': 0.5} and mayus == nombre
        # «Gi1/0/3» is the third interface of the model, whatever it is called: here, gi7.
        assert numero == {'f': 'rear', 'x': 0.8, 'y': 0.5}
        assert falta is None and sin is None
        assert psu2 == {'f': 'rear', 'x': 0.9, 'y': 0.4}

    def test_the_point_on_its_face_and_the_cable_leaves_from_it(self, out):
        delante, detras = out['punto']
        assert delante[0] == pytest.approx(0.75) and delante[2] < 0
        assert detras[0] == pytest.approx(0.25) and detras[2] > 0.5
        assert out['sale'] == [True, True]


def test_the_catalogue_module_lists_what_can_be_placed():
    """Connectors outside and bays inside; the table's mark counts the connectors only."""
    assert set(dcim_catalog.PLACEABLE) == set(dcim_catalog.CONNECTORS) | set(dcim_catalog.BAYS)
    assert 'module-bays' in dcim_catalog.BAYS and 'module-bays' not in dcim_catalog.CONNECTORS
