#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authorization holes of the physical inventory that the audit of 2026-10 proved by request.

Five of them, and all five had the same shape: the check was made on the thing being touched
and not on what the request REACHED through it.

* the rack history handed over every snapshot of another company's items after checking only
  that the reader may see the rack;
* moving an item, a rack or a room checked the owner of what moved and never the destination;
* a cable's ends could be rewritten, and its far end was never checked at all;
* deleting a site, room or rack left everything inside it orphaned — and an orphan's chain no
  longer reaches the owner declared on the site, so it became everybody's;
* a site's `photo` was writable by PUT, so DELETE /sites/<uid>/photo deleted any media file.

With app and session: what is being checked is the route's answer to a scoped caller.
"""

from __future__ import annotations

import io
import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from tests.conftest import _login                                   # noqa: E402
from tests.integration.test_wa_dcim import _as                      # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


def _post(client, url, body):
    return client.post(url, json=body).get_json()['uid']


@pytest.fixture()
def two(client):
    """Two companies, each with its own site, room, rack and item."""
    _login(client)
    a = _post(client, '/api/v1/orgs', {'name': 'A', 'short': 'A'})
    b = _post(client, '/api/v1/orgs', {'name': 'B', 'short': 'B'})
    sa = _post(client, '/api/v1/dcim/sites', {'name': 'SA'})
    sb = _post(client, '/api/v1/dcim/sites', {'name': 'SB'})
    client.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': sa, 'org_uid': a})
    client.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': sb, 'org_uid': b})
    ra = _post(client, '/api/v1/dcim/rooms', {'site_uid': sa, 'name': 'RA'})
    rb = _post(client, '/api/v1/dcim/rooms', {'site_uid': sb, 'name': 'RB'})
    ka = _post(client, '/api/v1/dcim/racks', {'room_uid': ra, 'name': 'KA', 'u_height': 42})
    kb = _post(client, '/api/v1/dcim/racks', {'room_uid': rb, 'name': 'KB', 'u_height': 42})
    ia = _post(client, '/api/v1/dcim/items',
               {'rack_uid': ka, 'u_start': 1, 'u_height': 1, 'label': 'IA'})
    ib = _post(client, '/api/v1/dcim/items',
               {'rack_uid': kb, 'u_start': 1, 'u_height': 1, 'label': 'SECRET-B'})
    return dict(a=a, b=b, sa=sa, sb=sb, ra=ra, rb=rb, ka=ka, kb=kb, ia=ia, ib=ib)


def _ua(admin, two):
    return _as(admin, 'ua', ['dcim_view', 'dcim_edit', 'dcim_cable_edit',
                             f'org.{two["a"]}.view'])


class TestLaHistoriaDelRack:
    """C1 — the history is filtered exactly like the rack it belongs to."""

    @pytest.fixture()
    def shared(self, client):
        """IT's rack with company B's server inside, and a revision after it."""
        _login(client)
        it = _post(client, '/api/v1/orgs', {'name': 'IT', 'short': 'IT'})
        b = _post(client, '/api/v1/orgs', {'name': 'B', 'short': 'B'})
        site = _post(client, '/api/v1/dcim/sites', {'name': 'DC'})
        room = _post(client, '/api/v1/dcim/rooms', {'site_uid': site, 'name': 'S1'})
        rack = _post(client, '/api/v1/dcim/racks', {'room_uid': room, 'name': 'R3',
                                                    'u_height': 42})
        client.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': site, 'org_uid': it})
        mine = _post(client, '/api/v1/dcim/items', {'rack_uid': rack, 'u_start': 1,
                                                    'label': 'SW-CORE'})
        theirs = _post(client, '/api/v1/dcim/items',
                       {'rack_uid': rack, 'u_start': 12, 'u_height': 2,
                        'label': 'DB03-NOMINAS', 'serial': 'SECRETO-1',
                        'asset': 'INV-B-77', 'device_uid': 'h-db03'})
        client.post('/api/v1/orgs/owner', json={'scope': 'item', 'uid': theirs, 'org_uid': b})
        # Renamed and re-numbered afterwards: both values must stay out of `changed` too.
        client.put(f'/api/v1/dcim/items/{theirs}',
                   json={'label': 'DB04-NOMINAS', 'serial': 'SECRETO-2'})
        client.put(f'/api/v1/dcim/racks/{rack}', json={'name': 'R3b'})
        return dict(it=it, b=b, rack=rack, mine=mine, theirs=theirs)

    def test_no_ensena_lo_ajeno_en_ninguna_version(self, admin, client, shared):
        c = _as(admin, 'uit', ['dcim_view', f'org.{shared["it"]}.view'])
        r = c.get(f'/api/v1/dcim/racks/{shared["rack"]}/history')
        assert r.status_code == 200
        body = r.data.decode()
        for secret in ('DB03-NOMINAS', 'DB04-NOMINAS', 'SECRETO-1', 'SECRETO-2',
                       'INV-B-77', 'h-db03'):
            assert secret not in body, secret
        # …and what is its own is still there: the history is not emptied, it is narrowed.
        assert 'SW-CORE' in body

    def test_lo_ajeno_sale_opaco_ocupando_su_sitio(self, admin, client, shared):
        c = _as(admin, 'uit', ['dcim_view', f'org.{shared["it"]}.view'])
        hist = c.get(f'/api/v1/dcim/racks/{shared["rack"]}/history').get_json()['history']
        newest = {i['uid']: i for i in hist[0]['data']['items']}
        assert newest[shared['theirs']].get('foreign') is True
        assert newest[shared['theirs']]['u_start'] == 12
        assert 'label' not in newest[shared['theirs']]
        for version in hist:
            for change in version['changed']:
                if change['uid'] == shared['theirs']:
                    assert change['field'] not in ('label', 'serial', 'asset', 'device_uid')

    def test_quien_lo_ve_todo_lo_sigue_viendo(self, client, shared):
        body = client.get(f'/api/v1/dcim/racks/{shared["rack"]}/history').data.decode()
        assert 'DB04-NOMINAS' in body and 'SECRETO-2' in body


class TestMoverEsEscribirEnElDestino:
    """C2 — moving something is writing into where it goes."""

    def test_un_equipo_propio_no_entra_en_un_rack_ajeno(self, admin, client, two):
        r = _ua(admin, two).put(f'/api/v1/dcim/items/{two["ia"]}',
                                json={'rack_uid': two['kb'], 'u_start': 10})
        assert r.status_code == 403
        assert admin._dcim_store.items.get(two['ia'])['rack_uid'] == two['ka']

    def test_un_rack_propio_no_entra_en_una_sala_ajena(self, admin, client, two):
        r = _ua(admin, two).put(f'/api/v1/dcim/racks/{two["ka"]}',
                                json={'room_uid': two['rb']})
        assert r.status_code == 403
        assert admin._dcim_store.racks.get(two['ka'])['room_uid'] == two['ra']

    def test_una_sala_propia_no_entra_en_una_sede_ajena(self, admin, client, two):
        r = _ua(admin, two).put(f'/api/v1/dcim/rooms/{two["ra"]}',
                                json={'site_uid': two['sb']})
        assert r.status_code == 403
        assert admin._dcim_store.rooms.get(two['ra'])['site_uid'] == two['sa']

    def test_un_destino_que_no_existe_es_404(self, admin, client, two):
        r = _ua(admin, two).put(f'/api/v1/dcim/racks/{two["ka"]}',
                                json={'room_uid': 'no-such-room'})
        assert r.status_code == 404

    def test_moverlo_dentro_de_lo_suyo_sigue_valiendo(self, admin, client, two):
        ra2 = _post(client, '/api/v1/dcim/rooms', {'site_uid': two['sa'], 'name': 'RA2'})
        ka2 = _post(client, '/api/v1/dcim/racks', {'room_uid': two['ra'], 'name': 'KA2',
                                                   'u_height': 42})
        ua = _ua(admin, two)
        assert ua.put(f'/api/v1/dcim/items/{two["ia"]}',
                      json={'rack_uid': ka2, 'u_start': 10}).status_code == 200
        assert ua.put(f'/api/v1/dcim/racks/{two["ka"]}',
                      json={'room_uid': ra2}).status_code == 200
        # Re-sending the parent it already has is not a move, and needs nothing more.
        assert ua.put(f'/api/v1/dcim/racks/{two["ka"]}',
                      json={'room_uid': ra2, 'name': 'KA-1'}).status_code == 200

    def test_ni_montarlo_en_la_bandeja_de_otro(self, admin, client, two):
        """Same rack, so no rack changes hands — but the tray it hangs from is B's."""
        site = _post(client, '/api/v1/dcim/sites', {'name': 'Shared'})
        room = _post(client, '/api/v1/dcim/rooms', {'site_uid': site, 'name': 'R'})
        rack = _post(client, '/api/v1/dcim/racks', {'room_uid': room, 'name': 'K',
                                                    'u_height': 42})
        mine = _post(client, '/api/v1/dcim/items', {'rack_uid': rack, 'u_start': 1,
                                                    'label': 'MINI'})
        tray = _post(client, '/api/v1/dcim/items', {'rack_uid': rack, 'u_start': 10,
                                                    'role': 'shelf', 'label': 'TRAY-B'})
        client.post('/api/v1/orgs/owner', json={'scope': 'item', 'uid': mine,
                                                'org_uid': two['a']})
        client.post('/api/v1/orgs/owner', json={'scope': 'item', 'uid': tray,
                                                'org_uid': two['b']})
        r = _ua(admin, two).put(f'/api/v1/dcim/items/{mine}', json={'parent_uid': tray})
        assert r.status_code == 403
        assert not admin._dcim_store.items.get(mine).get('parent_uid')


class TestLasPuntasDeUnCable:
    """C3 — both ends of a cable are checked, on creation and on every edit."""

    def test_no_se_crea_hacia_un_equipo_ajeno(self, admin, client, two):
        r = _ua(admin, two).post('/api/v1/dcim/cables',
                                 json={'a_item': two['ia'], 'b_item': two['ib']})
        assert r.status_code == 403
        assert not admin._dcim_store.cables.list()

    def test_ni_hacia_uno_que_no_existe(self, admin, client, two):
        r = _ua(admin, two).post('/api/v1/dcim/cables',
                                 json={'a_item': two['ia'], 'b_item': 'no-such-item'})
        assert r.status_code == 404

    def test_sus_puntas_no_se_reescriben_hacia_lo_ajeno(self, admin, client, two):
        ia2 = _post(client, '/api/v1/dcim/items', {'rack_uid': two['ka'], 'u_start': 3,
                                                   'label': 'IA2'})
        ua = _ua(admin, two)
        cu = ua.post('/api/v1/dcim/cables',
                     json={'a_item': two['ia'], 'b_item': ia2}).get_json()['uid']
        r = ua.put(f'/api/v1/dcim/cables/{cu}', json={'a_item': two['ib'], 'b_item': two['ib']})
        assert r.status_code == 403
        r = ua.put(f'/api/v1/dcim/cables/{cu}', json={'b_item': two['ib']})
        assert r.status_code == 403
        row = admin._dcim_store.cables.get(cu)
        assert (row['a_item'], row['b_item']) == (two['ia'], ia2)

    def test_editarlo_no_salta_la_regla_del_puente(self, admin, client, two):
        ia2 = _post(client, '/api/v1/dcim/items', {'rack_uid': two['ka'], 'u_start': 3,
                                                   'label': 'IA2'})
        ua = _ua(admin, two)
        cu = ua.post('/api/v1/dcim/cables',
                     json={'a_item': two['ia'], 'b_item': ia2}).get_json()['uid']
        r = ua.put(f'/api/v1/dcim/cables/{cu}', json={'b_item': two['ia']})
        assert r.status_code == 400
        assert admin._dcim_store.cables.get(cu)['b_item'] == ia2

    def test_reenviar_el_cable_entero_sigue_valiendo(self, admin, client, two):
        ia2 = _post(client, '/api/v1/dcim/items', {'rack_uid': two['ka'], 'u_start': 3,
                                                   'label': 'IA2'})
        ia3 = _post(client, '/api/v1/dcim/items', {'rack_uid': two['ka'], 'u_start': 5,
                                                   'label': 'IA3'})
        ua = _ua(admin, two)
        cu = ua.post('/api/v1/dcim/cables',
                     json={'a_item': two['ia'], 'b_item': ia2}).get_json()['uid']
        assert ua.put(f'/api/v1/dcim/cables/{cu}',
                      json={'a_item': two['ia'], 'b_item': ia2,
                            'label': 'L-1'}).status_code == 200
        assert ua.put(f'/api/v1/dcim/cables/{cu}', json={'b_item': ia3}).status_code == 200
        assert admin._dcim_store.cables.get(cu)['b_item'] == ia3


class TestBorrarUnContenedor:
    """C4 — a container with inventory inside is refused; an empty one takes its drawing."""

    def _refused(self, client, url, kind):
        r = client.delete(url)
        assert r.status_code == 409
        data = r.get_json()
        assert data['error'] and data['error'] != 'dcim_container_not_empty'
        assert data['contains'].get(kind)
        return data

    def test_una_sede_con_salas_no_se_borra(self, admin, client, two):
        self._refused(client, f'/api/v1/dcim/sites/{two["sa"]}', 'rooms')
        st = admin._dcim_store
        assert st.sites.get(two['sa']) and st.rooms.get(two['ra']) and st.items.get(two['ia'])

    def test_una_sala_con_racks_no_se_borra(self, admin, client, two):
        self._refused(client, f'/api/v1/dcim/rooms/{two["ra"]}', 'racks')
        assert admin._dcim_store.rooms.get(two['ra'])

    def test_un_rack_con_equipos_no_se_borra(self, admin, client, two):
        self._refused(client, f'/api/v1/dcim/racks/{two["ka"]}', 'items')
        assert admin._dcim_store.racks.get(two['ka'])

    def test_ni_uno_con_una_regleta(self, admin, client, two):
        k = _post(client, '/api/v1/dcim/racks', {'room_uid': two['ra'], 'name': 'K2',
                                                 'u_height': 42})
        _post(client, '/api/v1/dcim/pdus', {'rack_uid': k, 'name': 'P', 'outlets': 8})
        self._refused(client, f'/api/v1/dcim/racks/{k}', 'pdus')

    def test_lo_ajeno_sigue_escondido_tras_intentarlo(self, admin, client, two):
        """The orphan was visible to everybody: the site's owner no longer reached it."""
        client.delete(f'/api/v1/dcim/sites/{two["sa"]}')
        ub = _as(admin, 'ub', ['dcim_view', f'org.{two["b"]}.view'])
        assert ub.get(f'/api/v1/dcim/racks/{two["ka"]}').status_code == 403

    def test_lo_que_no_existe_es_404(self, client, two):
        assert client.delete('/api/v1/dcim/sites/no-such-site').status_code == 404

    def test_una_sala_vacia_se_lleva_su_dibujo(self, admin, client, two):
        room = _post(client, '/api/v1/dcim/rooms', {'site_uid': two['sa'], 'name': 'Empty'})
        client.post('/api/v1/dcim/features', json={'room_uid': room, 'kind': 'column'})
        assert admin._dcim_store.features_of(room)
        assert client.delete(f'/api/v1/dcim/rooms/{room}').status_code == 200
        assert not admin._dcim_store.features_of(room)

    def test_una_sede_vacia_se_lleva_sus_plantas_y_su_plano(self, admin, client):
        _login(client)
        site = _post(client, '/api/v1/dcim/sites', {'name': 'Empty'})
        floor = _post(client, '/api/v1/dcim/floors', {'site_uid': site, 'name': 'Baja'})
        area = client.post(f'/api/v1/dcim/floors/{floor}/area').get_json()['room_uid']
        plan = client.post(f'/api/v1/dcim/floors/{floor}/plan',
                           data={'file': (io.BytesIO(PNG), 'p.png')},
                           content_type='multipart/form-data').get_json()['plan']
        assert client.get(f'/api/v1/dcim/media/{plan}').status_code == 200
        assert client.delete(f'/api/v1/dcim/sites/{site}').status_code == 200
        st = admin._dcim_store
        assert not st.floors.get(floor) and not st.rooms.get(area)
        assert client.get(f'/api/v1/dcim/media/{plan}').status_code == 404


class TestLaFotoDeUnaSede:
    """C5 — `photo` is minted by its upload, so deleting it only removes a file it minted."""

    def _plan(self, client):
        _login(client)
        site = _post(client, '/api/v1/dcim/sites', {'name': 'S2'})
        room = _post(client, '/api/v1/dcim/rooms', {'site_uid': site, 'name': 'R'})
        r = client.post(f'/api/v1/dcim/rooms/{room}/plan',
                        data={'file': (io.BytesIO(PNG), 'p.png')},
                        content_type='multipart/form-data')
        return room, r.get_json()['plan']

    def test_no_se_escribe_por_put(self, admin, client):
        _room, name = self._plan(client)
        s1 = _post(client, '/api/v1/dcim/sites', {'name': 'S1'})
        assert client.put(f'/api/v1/dcim/sites/{s1}', json={'photo': name}).status_code == 200
        assert admin._dcim_store.sites.get(s1)['photo'] == ''
        s3 = _post(client, '/api/v1/dcim/sites', {'name': 'S3', 'photo': name})
        assert admin._dcim_store.sites.get(s3)['photo'] == ''

    def test_quitarla_no_borra_el_plano_de_otro(self, admin, client):
        room, name = self._plan(client)
        s1 = _post(client, '/api/v1/dcim/sites', {'name': 'S1'})
        client.put(f'/api/v1/dcim/sites/{s1}', json={'photo': name})
        assert client.delete(f'/api/v1/dcim/sites/{s1}/photo').status_code == 200
        assert client.get(f'/api/v1/dcim/media/{name}').status_code == 200
        assert admin._dcim_store.rooms.get(room)['plan'] == name

    def test_ni_con_una_referencia_de_antes(self, admin, client):
        """A reference written before `photo` was minted: the file other record shows stays."""
        _room, name = self._plan(client)
        s1 = _post(client, '/api/v1/dcim/sites', {'name': 'S1'})
        admin._dcim_store.sites.update(s1, {'photo': name}, actor='test')
        assert client.delete(f'/api/v1/dcim/sites/{s1}/photo').status_code == 200
        assert client.get(f'/api/v1/dcim/media/{name}').status_code == 200

    def test_la_suya_si_se_borra(self, admin, client):
        _login(client)
        s1 = _post(client, '/api/v1/dcim/sites', {'name': 'S1'})
        name = client.post(f'/api/v1/dcim/sites/{s1}/photo',
                           data={'file': (io.BytesIO(PNG), 'p.png')},
                           content_type='multipart/form-data').get_json()['photo']
        assert client.get(f'/api/v1/dcim/media/{name}').status_code == 200
        assert client.delete(f'/api/v1/dcim/sites/{s1}/photo').status_code == 200
        assert client.get(f'/api/v1/dcim/media/{name}').status_code == 404
