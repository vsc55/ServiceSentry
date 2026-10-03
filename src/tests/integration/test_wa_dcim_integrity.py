#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integrity holes of the physical inventory that the audit of 2026-10 proved by request.

None of them is about who may see what (that is `test_wa_dcim_authz.py`); they are about
what a write leaves behind:

* numbers stored unchecked (`u_height: "abc"`, `nan`, `Infinity`) that turned reads into 500s;
* a rack shrunk under its own equipment;
* a deleted item that left its power leads, cables and components behind;
* a tray moved without what is mounted on it;
* another company's item reduced to so little geometry that it was drawn in the wrong place;
* the site filter of the item search listing every site;
* a room import that emptied the room before reading the file;
* a client-chosen `uid` on create;
* a deleted item whose ownership claim vanished, so the rack history gave it to the rack owner.

With app and session: what is checked is the route's answer.
"""

from __future__ import annotations

import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from tests.conftest import _login                                   # noqa: E402
from tests.integration.test_wa_dcim import _as                      # noqa: E402


def _post(client, url, body):
    r = client.post(url, json=body)
    assert r.status_code == 200, (url, r.status_code, r.get_json())
    return r.get_json()['uid']


@pytest.fixture()
def rack(client):
    """One site, room and 42U rack, written by the administrator."""
    _login(client)
    site = _post(client, '/api/v1/dcim/sites', {'name': 'DC'})
    room = _post(client, '/api/v1/dcim/rooms', {'site_uid': site, 'name': 'S1'})
    k = _post(client, '/api/v1/dcim/racks', {'room_uid': room, 'name': 'R1', 'u_height': 42})
    return dict(site=site, room=room, rack=k)


class TestLosNumerosDeUnContenedor:
    """C6 / C13 — a numeric column only takes a finite number within its range."""

    def test_una_altura_de_texto_es_400_y_nada_se_rompe(self, admin, client, rack):
        r = client.put(f'/api/v1/dcim/racks/{rack["rack"]}', json={'u_height': 'abc'})
        assert r.status_code == 400
        assert r.get_json()['field'] == 'u_height'
        assert admin._dcim_store.racks.get(rack['rack'])['u_height'] == 42
        assert client.get('/api/v1/dcim/sites').status_code == 200
        assert client.get(f'/api/v1/dcim/racks/{rack["rack"]}').status_code == 200

    def test_ni_al_crearlo(self, client, rack):
        for malo in ('abc', 0, 1000, 'nan', [1]):
            r = client.post('/api/v1/dcim/racks', json={'room_uid': rack['room'],
                                                        'name': f'X{malo}', 'u_height': malo})
            assert r.status_code == 400, malo

    def test_un_numero_escrito_como_texto_se_guarda_como_numero(self, admin, client, rack):
        uid = _post(client, '/api/v1/dcim/racks', {'room_uid': rack['room'], 'name': 'R2',
                                                   'u_height': '24', 'width_mm': ''})
        fila = admin._dcim_store.racks.get(uid)
        assert fila['u_height'] == 24 and fila['width_mm'] == 600

    def test_una_planta_con_nivel_nan_es_400(self, client, rack):
        for malo in ('nan', 'inf', 'abc'):
            r = client.post('/api/v1/dcim/floors', json={'site_uid': rack['site'],
                                                         'name': 'P', 'level': malo})
            assert r.status_code == 400, malo

    def test_infinity_en_una_posicion_de_u_es_400(self, client, rack):
        r = client.post('/api/v1/dcim/items', data='{"rack_uid": "%s", "u_start": Infinity}'
                        % rack['rack'], content_type='application/json')
        assert r.status_code == 400

    def test_una_toma_de_texto_es_400(self, client, rack):
        item = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 1})
        pdu = _post(client, '/api/v1/dcim/pdus', {'rack_uid': rack['rack'], 'name': 'A',
                                                  'feed': 'a', 'outlets': 8})
        r = client.post('/api/v1/dcim/feeds', json={'item_uid': item, 'pdu_uid': pdu,
                                                    'outlet': 'abc'})
        assert r.status_code == 400


class TestEncogerUnRack:
    """C11 — a rack is not made shorter than what is bolted into it."""

    def test_no_queda_por_debajo_de_lo_montado(self, admin, client, rack):
        _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 40,
                                             'label': 'TOP'})
        r = client.put(f'/api/v1/dcim/racks/{rack["rack"]}', json={'u_height': 24})
        assert r.status_code == 409
        assert admin._dcim_store.racks.get(rack['rack'])['u_height'] == 42

    def test_hasta_lo_mas_alto_que_hay_si(self, admin, client, rack):
        _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 40,
                                             'label': 'TOP'})
        r = client.put(f'/api/v1/dcim/racks/{rack["rack"]}', json={'u_height': 40})
        assert r.status_code == 200
        assert admin._dcim_store.racks.get(rack['rack'])['u_height'] == 40


class TestBorrarUnEquipo:
    """C7 — what hangs off an item goes with it."""

    def test_libera_su_toma(self, admin, client, rack):
        uno = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 1})
        dos = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 2})
        pdu = _post(client, '/api/v1/dcim/pdus', {'rack_uid': rack['rack'], 'name': 'A',
                                                  'feed': 'a', 'outlets': 8})
        _post(client, '/api/v1/dcim/feeds', {'item_uid': uno, 'pdu_uid': pdu, 'outlet': 3})
        assert client.delete(f'/api/v1/dcim/items/{uno}').status_code == 200
        assert admin._dcim_store.feeds.list('item_uid = ?', (uno,)) == []
        r = client.post('/api/v1/dcim/feeds', json={'item_uid': dos, 'pdu_uid': pdu,
                                                    'outlet': 3})
        assert r.status_code == 200, r.get_json()

    def test_se_lleva_sus_cables_y_sus_piezas(self, admin, client, rack):
        uno = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 1})
        dos = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 2})
        _post(client, '/api/v1/dcim/cables', {'a_item': dos, 'b_item': uno,
                                              'a_port': 'eth0', 'b_port': 'eth1'})
        _post(client, '/api/v1/dcim/parts', {'item_uid': uno, 'kind': 'disk', 'qty': 2})
        assert client.delete(f'/api/v1/dcim/items/{uno}').status_code == 200
        store = admin._dcim_store
        assert store.cables_of([uno]) == [] and store.cables_of([dos]) == []
        assert store.parts_of([uno]) == []


class TestMoverUnaBandeja:
    """C8 — what is mounted on a tray moves with it."""

    def test_lo_montado_va_con_ella(self, admin, client, rack):
        bandeja = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'],
                                                       'u_start': 10, 'label': 'TRAY'})
        hijo = _post(client, '/api/v1/dcim/items', {'parent_uid': bandeja, 'label': 'KID'})
        r = client.put(f'/api/v1/dcim/items/{bandeja}', json={'u_start': 20})
        assert r.status_code == 200
        assert admin._dcim_store.items.get(hijo)['u_start'] == 20

    def test_tambien_a_otro_rack(self, admin, client, rack):
        otro = _post(client, '/api/v1/dcim/racks', {'room_uid': rack['room'], 'name': 'R2',
                                                    'u_height': 42})
        bandeja = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'],
                                                       'u_start': 10, 'label': 'TRAY'})
        hijo = _post(client, '/api/v1/dcim/items', {'parent_uid': bandeja, 'label': 'KID'})
        r = client.put(f'/api/v1/dcim/items/{bandeja}',
                       json={'rack_uid': otro, 'u_start': 5, 'face': 'front'})
        assert r.status_code == 200
        fila = admin._dcim_store.items.get(hijo)
        assert (fila['rack_uid'], fila['u_start'], fila['face']) == (otro, 5, 'front')
        assert hijo not in [i['uid'] for i in
                            client.get(f'/api/v1/dcim/racks/{rack["rack"]}').get_json()['items']]


class TestLoAjenoConSuForma:
    """C9 — an opaque item keeps its geometry, so it is drawn where it is."""

    @pytest.fixture()
    def compartido(self, client, rack):
        b = _post(client, '/api/v1/orgs', {'name': 'B', 'short': 'B'})
        it = _post(client, '/api/v1/orgs', {'name': 'IT', 'short': 'IT'})
        client.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': rack['site'],
                                                'org_uid': it})
        k = rack['rack']
        ups = _post(client, '/api/v1/dcim/items', {'rack_uid': k, 'placement': 'near',
                                                   'label': 'UPS'})
        tray = _post(client, '/api/v1/dcim/items', {'rack_uid': k, 'u_start': 10,
                                                    'label': 'TRAY'})
        kid = _post(client, '/api/v1/dcim/items', {'parent_uid': tray, 'label': 'KID'})
        half = _post(client, '/api/v1/dcim/items', {'rack_uid': k, 'u_start': 12,
                                                    'u_slots': 2, 'u_slot': 2,
                                                    'label': 'HALF'})
        mine = _post(client, '/api/v1/dcim/items', {'rack_uid': k, 'u_start': 20,
                                                    'label': 'BBOX'})
        client.post('/api/v1/orgs/owner', json={'scope': 'item', 'uid': mine, 'org_uid': b})
        return dict(b=b, ups=ups, tray=tray, kid=kid, half=half)

    def test_conserva_donde_y_cuanto(self, admin, client, rack, compartido):
        cb = _as(admin, 'ub', ['dcim_view', f'org.{compartido["b"]}.view'])
        items = {i['uid']: i for i in
                 cb.get(f'/api/v1/dcim/racks/{rack["rack"]}').get_json()['items']}
        assert items[compartido['ups']]['foreign'] is True
        assert items[compartido['ups']]['placement'] == 'near'
        assert items[compartido['kid']]['parent_uid'] == compartido['tray']
        assert (items[compartido['half']]['u_slots'], items[compartido['half']]['u_slot']) \
            == (2, 2)

    def test_y_sigue_sin_decir_que_es(self, admin, client, rack, compartido):
        cb = _as(admin, 'ub', ['dcim_view', f'org.{compartido["b"]}.view'])
        body = cb.get(f'/api/v1/dcim/racks/{rack["rack"]}').data.decode()
        for secreto in ('UPS', 'TRAY', 'KID', 'HALF'):
            assert secreto not in body, secreto


class TestLasSedesDelBuscador:
    """C10 — the site filter of the item search lists only what the reader may see."""

    def test_no_lista_sedes_ajenas(self, admin, client):
        _login(client)
        a = _post(client, '/api/v1/orgs', {'name': 'A', 'short': 'A'})
        b = _post(client, '/api/v1/orgs', {'name': 'B', 'short': 'B'})
        sa = _post(client, '/api/v1/dcim/sites', {'name': 'SEDE-A'})
        sb = _post(client, '/api/v1/dcim/sites', {'name': 'SEDE-SECRETA-B'})
        client.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': sa, 'org_uid': a})
        client.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': sb, 'org_uid': b})
        ca = _as(admin, 'ua', ['dcim_view', f'org.{a}.view'])
        sedes = [s['name'] for s in ca.get('/api/v1/dcim/items').get_json()['sites']]
        assert sedes == ['SEDE-A']
        # …and whoever sees the fleet still gets both.
        todas = {s['name'] for s in client.get('/api/v1/dcim/items').get_json()['sites']}
        assert todas == {'SEDE-A', 'SEDE-SECRETA-B'}


class TestImportarUnPlano:
    """C12 — a malformed file changes nothing in the room."""

    def test_una_pieza_que_no_es_un_objeto_no_vacia_la_sala(self, admin, client, rack):
        _post(client, '/api/v1/dcim/features', {'room_uid': rack['room'], 'kind': 'column'})
        r = client.post(f'/api/v1/dcim/rooms/{rack["room"]}/import',
                        json={'features': ['x'], 'room': {'width_mm': 9000}})
        assert r.status_code == 400
        assert len(admin._dcim_store.features_of(rack['room'])) == 1
        assert admin._dcim_store.rooms.get(rack['room'])['width_mm'] != 9000

    def test_un_fichero_bueno_sigue_sustituyendo_las_piezas(self, admin, client, rack):
        _post(client, '/api/v1/dcim/features', {'room_uid': rack['room'], 'kind': 'column'})
        r = client.post(f'/api/v1/dcim/rooms/{rack["room"]}/import',
                        json={'features': [{'kind': 'door', 'rotation': 'nan'},
                                           {'kind': 'no-such-kind'}]})
        assert r.status_code == 200
        assert r.get_json()['features'] == 1 and r.get_json()['skipped'] == 1
        assert [f['kind'] for f in admin._dcim_store.features_of(rack['room'])] == ['door']


class TestElUidLoPoneElPanel:
    """C14 — a create ignores a `uid` and the audit columns sent by the client."""

    def test_un_uid_propuesto_no_se_usa(self, admin, client, rack):
        uid = _post(client, '/api/v1/dcim/racks', {'room_uid': rack['room'], 'name': 'R9',
                                                   'uid': 'elegido-por-mi'})
        assert uid != 'elegido-por-mi'
        assert admin._dcim_store.racks.get('elegido-por-mi') is None

    def test_uno_que_ya_existe_no_es_500(self, client, rack):
        r = client.post('/api/v1/dcim/racks', json={'room_uid': rack['room'], 'name': 'R9',
                                                    'uid': rack['rack']})
        assert r.status_code == 200
        assert r.get_json()['uid'] != rack['rack']

    def test_ni_en_un_equipo_ni_en_un_cable(self, admin, client, rack):
        item = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 1,
                                                    'uid': 'mio-1', 'updated_by': 'otro'})
        assert item != 'mio-1'
        assert admin._dcim_store.items.get(item)['updated_by'] != 'otro'
        pdu = _post(client, '/api/v1/dcim/pdus', {'rack_uid': rack['rack'], 'name': 'A',
                                                  'feed': 'a', 'uid': 'mio-2'})
        assert pdu != 'mio-2'


class TestLaHistoriaDeUnEquipoBorrado:
    """C1 residual — a deleted item keeps, in the rack history, the owner it said it had."""

    @pytest.fixture()
    def borrado(self, client, rack):
        it = _post(client, '/api/v1/orgs', {'name': 'IT', 'short': 'IT'})
        b = _post(client, '/api/v1/orgs', {'name': 'B', 'short': 'B'})
        client.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': rack['site'],
                                                'org_uid': it})
        suyo = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 1,
                                                    'label': 'SW-IT'})
        ajeno = _post(client, '/api/v1/dcim/items', {'rack_uid': rack['rack'], 'u_start': 5,
                                                     'label': 'NOMINAS-B',
                                                     'serial': 'SECRETO-B'})
        client.post('/api/v1/orgs/owner', json={'scope': 'item', 'uid': ajeno, 'org_uid': b})
        # One more version after the claim, and then both are gone.
        client.put(f'/api/v1/dcim/racks/{rack["rack"]}', json={'name': 'R1b'})
        assert client.delete(f'/api/v1/dcim/items/{ajeno}').status_code == 200
        assert client.delete(f'/api/v1/dcim/items/{suyo}').status_code == 200
        return dict(it=it, b=b)

    def test_el_dueno_del_rack_no_ve_lo_ajeno_borrado(self, admin, client, rack, borrado):
        c = _as(admin, 'uit', ['dcim_view', f'org.{borrado["it"]}.view'])
        r = c.get(f'/api/v1/dcim/racks/{rack["rack"]}/history')
        assert r.status_code == 200
        body = r.data.decode()
        assert 'NOMINAS-B' not in body and 'SECRETO-B' not in body
        # The record of claims never travels either: it names B's company.
        assert borrado['b'] not in body
        # …and what was its own is still read in the history.
        assert 'SW-IT' in body

    def test_quien_lo_ve_todo_lo_sigue_viendo(self, client, rack, borrado):
        body = client.get(f'/api/v1/dcim/racks/{rack["rack"]}/history').data.decode()
        assert 'NOMINAS-B' in body
