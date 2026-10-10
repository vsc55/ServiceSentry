#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo site (``main.py dcim demo``): it holds everything the inventory can hold, every
bolted item fits where the panel would have let it go, it refuses to duplicate itself, and
removing it leaves nothing behind — not a row, not a plan file, not a company."""

import os
import sqlite3
from types import SimpleNamespace

import pytest

from lib.cli import commands
from lib.core.dcim import demo
from lib.core.dcim import demo_faces
from lib.core.dcim.store import DcimStore
from lib.db import get_connector

_TABLES = ('dc_site', 'dc_floor', 'dc_floor_wall', 'dc_room', 'dc_rack', 'dc_item', 'dc_feature',
           'dc_shelf_item', 'dc_pdu', 'dc_feed', 'dc_cable', 'dc_link', 'dc_row', 'dc_source',
           'dc_part', 'org', 'org_owner', 'dc_type')

#: The files the demo leaves: a plan per floor and the faces of its own models.
_FILES = len(demo._FLOORS) + sum(1 for k in demo_faces.MODELS
                                  for side in ('front', 'rear') if demo_faces.face(k, side))


@pytest.fixture()
def built(tmp_path):
    db = get_connector(None, default_sqlite_path=str(tmp_path / 'data.db'))
    store = DcimStore(db)
    made = demo.build(store, var_dir=str(tmp_path))
    return store, made, tmp_path


def _counts(path) -> dict:
    con = sqlite3.connect(str(path / 'data.db'))
    try:
        # Of the catalogue, the demo's own models only: the general catalogue's —the basics the
        # panel ships, Salto's access control among them— are real data the demo brings in if
        # missing, and they stay when the demo goes.
        return {t: con.execute('SELECT COUNT(*) FROM ' + t + (
                    " WHERE source = 'demo'" if t == 'dc_type' else '')).fetchone()[0]
                for t in _TABLES}
    finally:
        con.close()


def _media(path) -> list:
    out = []
    for root, _dirs, files in os.walk(str(path / 'dcim_media')):
        out += [os.path.join(root, f) for f in files]
    return out


class TestWhatTheDemoHolds:

    def test_every_table_of_the_inventory_has_rows(self, built):
        _store, _made, path = built
        empty = [t for t, n in _counts(path).items() if not n]
        assert not empty, empty

    def test_three_floors_with_plan_walls_core_and_a_general_area(self, built):
        store, made, path = built
        floors = store.floors_of(made['site'])
        assert sorted(f['level'] for f in floors) == [-1, 0, 1, 2, 3]
        for floor in floors:
            assert floor['plan'] and floor['plan_mm'] == 30000 and floor['core_kind'] == 'stairs'
            kinds = {w['kind'] for w in store.walls_of(floor['uid'])}
            assert {'wall', 'door'} <= kinds
        assert any(f['area_uid'] for f in floors)
        assert len(_media(path)) == _FILES
        for name in _media(path):
            with open(name, 'rb') as fh:
                assert fh.read(4) == b'<svg'

    def test_every_room_is_placed_on_a_floor_but_the_recovery_one(self, built):
        store, made, _path = built
        assert all(r['floor_uid'] for r in store.rooms_of(made['site']))
        assert not any(r['floor_uid'] for r in store.rooms_of(made['site_dr']))

    def test_placements_faces_and_halves_are_all_used(self, built):
        store, made, _path = built
        items = [i for r in store.rooms_of(made['site']) for k in store.racks_of(r['uid'])
                 for i in store.items_of(k['uid'])]
        assert {i['placement'] for i in items} == {'u', 'side', 'near'}
        assert {i['face'] for i in items} == {'full', 'front', 'rear'}
        assert any(int(i['u_slots']) == 2 and not i['parent_uid'] for i in items)
        assert any(i['parent_uid'] for i in items)
        assert all(not i['u_start'] for i in items if i['placement'] != 'u')

    def test_no_two_bolted_items_overlap(self, built):
        """Each item, checked against the others as the API would check a move to its own
        place: it has to fit with everything else still there."""
        store, made, _path = built
        for room in store.rooms_of(made['site']) + store.rooms_of(made['site_dr']):
            for rack in store.racks_of(room['uid']):
                for it in store.items_of(rack['uid']):
                    if it['placement'] != 'u' or it['parent_uid']:
                        continue
                    slot = {'u_slots': it['u_slots'], 'u_slot': it['u_slot'],
                            'u_slot_span': it['u_slot_span']}
                    assert store.fits(rack['uid'], it['u_start'], it['u_height'], it['face'],
                                      ignore=it['uid'], slot=slot), (rack['name'], it['label'])

    def test_the_power_chain_reaches_the_street(self, built):
        store, made, _path = built
        sources = {s['uid']: s for s in store.sources_of(made['site'])}
        assert {s['kind'] for s in sources.values()} == {'mains', 'panel', 'ups', 'generator'}
        for s in sources.values():
            if s['kind'] == 'ups':
                up, hops = s, 0
                while up.get('upstream_uid'):
                    up, hops = sources[up['upstream_uid']], hops + 1
                assert up['kind'] == 'mains' and hops >= 1
        assert any(s['item_uid'] for s in sources.values())

    def test_every_pdu_hangs_from_a_source_and_has_its_item(self, built):
        store, made, _path = built
        for room in store.rooms_of(made['site']):
            for rack in store.racks_of(room['uid']):
                for pdu in store.pdus_of(rack['uid']):
                    assert pdu['source_uid'] and pdu['item_uid'], rack['name']

    def test_the_cabling_crosses_racks_floors_and_sites(self, built):
        store, made, _path = built
        rack_of, floor_of = {}, {}
        for room in store.rooms_of(made['site']):
            for rack in store.racks_of(room['uid']):
                for it in store.items_of(rack['uid']):
                    rack_of[it['uid']], floor_of[it['uid']] = rack['uid'], room['floor_uid']
        cables = store.cables_of(list(rack_of))
        assert {c['kind'] for c in cables} >= {'copper', 'fiber', 'dac'}
        assert any(rack_of[c['a_item']] != rack_of.get(c['b_item']) for c in cables)
        assert any(floor_of[c['a_item']] != floor_of.get(c['b_item']) for c in cables
                   if c['b_item'] in floor_of)
        links = store.links_of([made['site']])
        assert len(links) == 2 and all(l['b_site'] == made['site_dr'] for l in links)

    def test_what_is_bolted_shows_a_picture(self, built):
        """Asked for from the screen: the demo's items were plain boxes. Each one that is not a
        blank, a tray or a PDU points at one of the demo's own models, and that model has its
        front drawn."""
        from lib.core.dcim.catalog import CatalogStore
        store, made, _path = built
        cat = CatalogStore(store._db)
        sin = []
        for site in (made['site'], made['site_dr']):
            for room in store.rooms_of(site):
                for rack in store.racks_of(room['uid']):
                    for it in store.items_of(rack['uid']):
                        if it['role'] in ('blank', 'shelf', 'pdu', 'ups'):
                            continue
                        model = cat.get(it['type_uid']) if it['type_uid'] else None
                        if not model or not model.get('front_image'):
                            sin.append((rack['name'], it['label']))
        assert not sin, sin
        assert {r['manufacturer'] for r in cat.list('source = ?', (demo.SOURCE,))} == {demo.MAKER}

    def test_its_models_bring_their_ports_placed_and_its_cables_find_them(self, built):
        """The demo draws its faces, so it knows where each socket is: every model with ports
        has all of them placed, and both ends of every cable between its own items name a port
        that is there — so in the rack a cable leaves its own port."""
        from lib.core.dcim.catalog import CatalogStore
        store, made, _path = built
        cat = CatalogStore(store._db)
        modelos = {r['uid']: r for r in cat.list('source = ?', (demo.SOURCE,))}
        assert all(r['ports_placed'] == r['ports_total'] for r in modelos.values())
        assert sum(r['ports_total'] for r in modelos.values()) > 200
        items = {}
        for room in store.rooms_of(made['site']) + store.rooms_of(made['site_dr']):
            for rack in store.racks_of(room['uid']):
                for it in store.items_of(rack['uid']):
                    items[it['uid']] = it
        sueltas = []
        for c in store.cables_of(list(items)):
            for lado in ('a', 'b'):
                it = items.get(c[lado + '_item'])
                modelo = modelos.get((it or {}).get('type_uid'))
                if not modelo or not modelo['port_list'].get('interfaces'):
                    continue
                nombres = {p['name'] for p in modelo['port_list']['interfaces']}
                if c[lado + '_port'] not in nombres:
                    sueltas.append((it['label'], c[lado + '_port']))
        assert not sueltas, sueltas

    def test_its_pictures_are_files_of_the_size_their_model_says(self):
        """The faces are SVG files in the repository, so they can be looked at and versioned.
        Each one is as wide as its model (19 inches, or the mini PC's 177 mm) and as tall as its
        U, in millimetres — the scale the port positions in `demo_faces` are written in."""
        import re
        sin = [k for k in demo_faces.MODELS if not demo_faces.face(k, 'front')]
        assert not sin, sin
        nombres = set(os.listdir(demo_faces.FACES_DIR))
        esperados = {'%s.%s.svg' % (k, s) for k in demo_faces.MODELS for s in ('front', 'rear')
                     if demo_faces.face(k, s)}
        assert nombres == esperados                      # no stray file nobody reads
        for nombre in sorted(nombres):
            key = nombre.split('.')[0]
            svg = demo_faces.face(key, nombre.split('.')[1])
            caja = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
            ancho = demo_faces.WIDTH_MM.get(key, 482.6)
            alto = demo_faces.MODELS[key][2] * 44.45
            assert caja and abs(float(caja.group(1)) - ancho) < 0.01, nombre
            assert abs(float(caja.group(2)) - alto) < 0.01, nombre

    def test_outlets_follow_the_u_they_feed(self, built):
        """Checked in the browser: in order of creation, the top item's cord went to the
        bottom of the strip and crossed the whole rack."""
        store, made, _path = built
        for room in store.rooms_of(made['site']):
            for rack in store.racks_of(room['uid']):
                for pdu in store.pdus_of(rack['uid']):
                    feeds = sorted(store.feeds_of([pdu['uid']]), key=lambda f: f['outlet'])
                    us = [int(store.items.get(f['item_uid'])['u_start'] or 0) for f in feeds]
                    assert us == sorted(us), (rack['name'], pdu['name'], us)
                    outlets = [f['outlet'] for f in feeds]
                    assert len(set(outlets)) == len(outlets) <= int(pdu['outlets'])

    def test_a_whole_building_offices_meeting_rooms_and_every_kind_of_cooling(self, built):
        """Asked for: offices, meeting rooms, private offices, floor communications rooms, a
        data room cooled by splits and others with their airflow — as detailed as possible."""
        from lib.core.dcim.catalog import CatalogStore
        store, made, _path = built
        w = demo.texts('es_ES')
        rooms = {r['name']: r for r in store.rooms_of(made['site'])}
        for key in ('room_open2', 'room_open3', 'room_meet_a', 'room_meet_b', 'room_meet0',
                    'room_meet3', 'room_off_dir', 'room_off_fin', 'room_off_rrhh', 'room_off_it',
                    'room_off_cto', 'room_idf2', 'room_idf3', 'room_srv', 'room_hpc',
                    'room_recep', 'room_train', 'room_kitchen', 'room_bat'):
            assert w[key] in rooms, key
        refrigeracion = {r['cooling'] for r in rooms.values()}
        assert {'split', 'cold_aisle', 'hot_aisle', 'room', 'none'} <= refrigeracion
        # Desks: 24 on the second floor and 18 on the third, each named by floor and number.
        puestos = [f for r in rooms.values() for f in store.features_of(r['uid'])
                   if f['kind'] == 'bench']
        assert len([f for f in puestos if f['label'].startswith('P2.')]) == 24
        assert len([f for f in puestos if f['label'].startswith('P3.')]) == 18
        # The HPC room: its racks on a contained hot aisle with in-row coolers between them.
        hpc = rooms[w['room_hpc']]
        piezas = store.features_of(hpc['uid'])
        assert len(store.racks_of(hpc['uid'])) == 12
        assert len([f for f in piezas if f['kind'] == 'crac']) == 4
        assert any(f['kind'] == 'aisle' for f in piezas)
        # The server room: wall splits, no containment.
        srv = store.features_of(rooms[w['room_srv']]['uid'])
        assert len([f for f in srv if f['kind'] == 'crac' and f['base_mm']]) == 2
        assert not any(f['kind'] == 'aisle' for f in srv)
        # Every floor's communications room reaches both cores over fibre, and its desk panels
        # are cabled to their switches port for port.
        for key in ('room_idf2', 'room_idf3'):
            rack = store.racks_of(rooms[w[key]]['uid'])[0]
            items = store.items_of(rack['uid'])
            cables = store.cables_of([i['uid'] for i in items])
            assert len([c for c in cables if c['kind'] == 'fiber']) >= 2
            assert len([c for c in cables if c['a_port'].isdigit()]) % 24 == 0
        # And the models say which way the air goes through them.
        flujo = {r['model']: r['airflow'] for r in CatalogStore(store._db).list(
            'source = ?', (demo.SOURCE,))}
        assert flujo['DM-R2 Server 2U'] == 'front-to-rear'
        assert flujo['DM-S48 Switch 48p'] == 'rear-to-front'

    def test_nothing_in_a_room_overlaps_and_every_door_gives_onto_a_corridor(self, built):
        """Seen in a browser: two desk islands overlapped, a round table sat on its desk, and
        doors opened onto a 0.5 m gap in front of the next room. Pieces of a room do not overlap
        each other (doors, trays, aisles and the containment are meant to), and in front of
        every room's door there is at least 1.2 m before the next room."""
        import math
        store, made, _path = built

        def caja(f):
            w, d = float(f['width_mm']), float(f['depth_mm'])
            if int(f['rotation'] or 0) % 180 == 90:
                cx, cy = float(f['pos_x']) + w / 2, float(f['pos_y']) + d / 2
                return (cx - d / 2, cy - w / 2, cx + d / 2, cy + w / 2)
            return (float(f['pos_x']), float(f['pos_y']), float(f['pos_x']) + w,
                    float(f['pos_y']) + d)

        def pisa(a, b):
            return min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1

        sueltas = ('door', 'tray', 'aisle', 'zone', 'label')
        for floor in store.floors_of(made['site']):
            salas = store.rooms.list('floor_uid = ?', (floor['uid'],))
            for room in salas:
                piezas = [f for f in store.features_of(room['uid']) if f['kind'] not in sueltas]
                for i, a in enumerate(piezas):
                    for b in piezas[i + 1:]:
                        if f'{a["base_mm"]}' != f'{b["base_mm"]}':
                            continue                 # one on the wall above the other
                        assert not pisa(caja(a), caja(b)), (room['name'], a['label'], b['label'])
            muros = [m for m in store.walls_of(floor['uid']) if m['kind'] == 'door'
                     and float(m['thick_mm']) < 200]
            cajas = [(r['name'], float(r['pos_x']), float(r['pos_y']),
                      float(r['pos_x']) + float(r['width_mm'] or 0),
                      float(r['pos_y']) + float(r['depth_mm'] or 0))
                     for r in salas if r['width_mm']]
            for m in muros:
                x, y = (float(m['x1']) + float(m['x2'])) / 2, float(m['y1'])
                for nombre, x0, y0, x1, y1 in cajas:
                    if x0 <= x <= x1 and not (y0 - 1 <= y <= y1 + 1):
                        assert min(abs(y - y0), abs(y - y1)) >= 1200, (floor['name'], nombre, x, y)

    def test_some_items_in_warning_and_in_error_without_watching_anything(self, built):
        """Asked for: demo items in warning and in error. They carry a demo state —no device, no
        check, nothing for the monitor to probe and no alert— that every screen reads through
        `item_state`, and they say so in their description."""
        from collections import Counter
        from lib.core.dcim import service
        store, made, _path = built
        items = [i for r in store.rooms_of(made['site']) for k in store.racks_of(r['uid'])
                 for i in store.items_of(k['uid'])]
        estados = Counter(service.item_state(i, {}) for i in items)
        assert estados['error'] >= 4 and estados['warning'] >= 7 and estados['ok'] > 200
        assert estados[''] > 0                       # some still unwatched, as in real life
        assert not any(i['device_uid'] for i in items)
        assert all(i['description'] for i in items if i['demo_state'])
        nombres = {i['label'] for i in items}
        assert set(demo._TROUBLE) <= nombres        # every item in trouble exists

    def test_access_control_a_gateway_per_floor_cylinders_lockers_and_turnstiles(self, built):
        """Asked for: a Salto KS-like system — IQ gateways, Neo cylinders on doors, XS4 Locker
        locks on lockers, turnstiles. One gateway per floor; every lock hangs from its own floor's
        gateway; a few in trouble, saying why."""
        from collections import Counter
        from lib.core.dcim import service
        store, made, _path = built
        por_planta = {}
        for floor in store.floors_of(made['site']):
            salas = store.rooms.list('floor_uid = ?', (floor['uid'],))
            por_planta[floor['uid']] = [f for r in salas for f in store.features_of(r['uid'])]
        todas = [f for fs in por_planta.values() for f in fs]
        iqs = [f for f in todas if f['kind'] == 'reader']
        assert len(iqs) == 5 and all(f['model'].startswith('Salto IQ') for f in iqs)
        cerraduras = Counter((f['kind'], f['lock']) for f in todas if f['lock'])
        assert cerraduras[('door', 'cylinder')] >= 14
        assert cerraduras[('cabinet', 'locker')] >= 5
        assert cerraduras[('turnstile', 'reader')] == 2
        for fs in por_planta.values():
            propios = {f['uid'] for f in fs if f['kind'] == 'reader'}
            assert all(f['hub_uid'] in propios for f in fs if f['lock']), 'a lock on another floor'
        estados = Counter(service.item_state(f, {}) for f in todas if f['lock'] or f['kind'] == 'reader')
        assert estados['error'] >= 1 and estados['warning'] >= 2 and estados['ok'] > 20
        assert all(f['serial'] for f in todas if f['lock'] or f['kind'] == 'reader')
        # And each points at its model in the GENERAL catalogue —the basics the panel ships, Salto
        # among them—, not at a demo copy: they are real models and stay when the demo goes.
        from lib.core.dcim import basics
        from lib.core.dcim.catalog import CatalogStore
        cat = CatalogStore(store._db)
        modelos = {f['type_uid'] for f in todas if f['lock'] or f['kind'] == 'reader'}
        assert '' not in modelos
        filas = [cat.get(u) for u in modelos]
        assert {r['source'] for r in filas} == {basics.SOURCE}
        assert {r['manufacturer'] for r in filas} == {'Salto', basics.MAKER}
        assert {r['kind'] for r in filas} == {'access_gateway', 'access_lock', 'turnstile'}
        demo.remove(store, var_dir=str(_path))
        assert all(cat.get(u) for u in modelos)

    def test_the_whole_building_on_the_map_with_what_hangs_on_its_walls(self, built):
        """Asked for: the IQ hangs on a wall and was in the middle of the room; and the whole
        building on the map — doors, fire hose reels, extinguishers, panels, all of it. What hangs
        on a wall touches a wall of its room; every room has a smoke detector and an emergency
        light; every floor has hose reels, call points and its panel; the reception, a first aid
        kit and a defibrillator."""
        from collections import Counter
        store, made, _path = built
        en_pared = demo._WALL_KINDS
        w = demo.texts('es_ES')
        for floor in store.floors_of(made['site']):
            salas = store.rooms.list('floor_uid = ?', (floor['uid'],))
            todas = Counter()
            for room in salas:
                piezas = store.features_of(room['uid'])
                todas.update(f['kind'] for f in piezas)
                W, D = float(room['width_mm'] or 0), float(room['depth_mm'] or 0)
                if not W:                                # the corridors: the floor's general area
                    continue
                tipos = {f['kind'] for f in piezas}
                assert {'smoke_detector', 'emergency_light', 'extinguisher'} <= tipos, room['name']
                for f in piezas:
                    if f['kind'] not in en_pared:
                        continue
                    fw, fd = float(f['width_mm']), float(f['depth_mm'])
                    if int(f['rotation'] or 0) % 180 == 90:
                        fw, fd = fd, fw
                    cx = float(f['pos_x']) + float(f['width_mm']) / 2
                    cy = float(f['pos_y']) + float(f['depth_mm']) / 2
                    hueco = min(cx - fw / 2, cy - fd / 2, W - cx - fw / 2, D - cy - fd / 2)
                    # On the wall's inner face: half a partition in from the room's edge, which
                    # is the wall's centre line.
                    assert abs(hueco - demo._FACE) < 1, (room['name'], f['kind'], f['label'], hueco)
            assert todas['hose_reel'] >= 1 and todas['fire_alarm'] >= 2, floor['name']
            # Nothing on a corridor wall in a door's gap (seen in a browser: a hose reel 10 cm
            # into an office door). The corridor pieces are the general area's, in floor mm.
            area = next(r for r in salas if not float(r['width_mm'] or 0))
            puertas = [m for m in store.walls_of(floor['uid'])
                       if m['kind'] == 'door' and float(m['thick_mm']) < 200]
            for f in store.features_of(area['uid']):
                # The emergency light hangs OVER the door, at 2.2 m: above the gap, not in it.
                if f['kind'] not in en_pared or f['kind'] == 'emergency_light':
                    continue
                fw, fd = float(f['width_mm']), float(f['depth_mm'])
                if int(f['rotation'] or 0) % 180 == 90:
                    fw, fd = fd, fw
                cx = float(f['pos_x']) + float(f['width_mm']) / 2
                cy = float(f['pos_y']) + float(f['depth_mm']) / 2
                for m in puertas:
                    x1, x2 = sorted((float(m['x1']), float(m['x2'])))
                    pisa = min(cx + fw / 2, x2) - max(cx - fw / 2, x1) > 1
                    assert not (pisa and abs(cy - float(m['y1'])) < 400), (floor['name'], f['kind'], f['label'])
            # And each floor's corridor extinguishers carry its own floor's name.
            tags = {f['label'] for f in store.features_of(area['uid']) if f['kind'] == 'extinguisher'}
            assert len({t.split()[-1] for t in tags}) <= 1
            assert todas['panel'] >= 1, floor['name']
        recepcion = next(r for r in store.rooms_of(made['site']) if r['name'] == w['room_recep'])
        assert {'first_aid', 'aed'} <= {f['kind'] for f in store.features_of(recepcion['uid'])}

    def test_a_rack_in_a_corridor_hangs_on_a_wall(self, built):
        """Seen in a browser: the corridor rack stood loose in the middle of the entrance hall.
        A rack out of a room hangs on a wall —its back on a partition's face, clear of its
        doors— and not on the floor in the way."""
        store, made, _path = built
        vistos = 0
        for floor in store.floors_of(made['site']):
            area = next(r for r in store.rooms.list('floor_uid = ?', (floor['uid'],))
                        if not float(r['width_mm'] or 0))
            muros = store.walls_of(floor['uid'])
            for r in store.racks.list('room_uid = ?', (area['uid'],)):
                vistos += 1
                assert int(r['base_mm'] or 0) > 0, r['name']
                assert int(r['rotation'] or 0) == 0, r['name']
                x1, x2 = float(r['pos_x']), float(r['pos_x']) + float(r['width_mm'])
                atras = float(r['pos_y']) + float(r['depth_mm'])

                def sobre(m):
                    mx1, mx2 = sorted((float(m['x1']), float(m['x2'])))
                    cara = float(m['y1']) - float(m['thick_mm'] or 0) / 2
                    return (float(m['y1']) == float(m['y2']) and abs(cara - atras) < 1
                            and mx1 <= x1 and x2 <= mx2)

                def hueco(m):
                    mx1, mx2 = sorted((float(m['x1']), float(m['x2'])))
                    return (abs(float(m['y1']) - atras) < 400
                            and min(x2, mx2) - max(x1, mx1) > 1)

                assert any(m['kind'] != 'door' and sobre(m) for m in muros), r['name']
                assert not any(m['kind'] == 'door' and hueco(m) for m in muros), r['name']
        assert vistos >= 1

    def test_two_racks_belong_to_the_customer(self, built):
        store, _made, _path = built
        name = demo.texts('es_ES')['org_customer']
        customer = next(o for o in store.orgs.list() if o['name'] == name)
        assert list(store.owners_map().values()).count(customer['uid']) == 2


class TestThePanelOverIt:
    """Seen with the demo built: the inventory's board took «an eternity» to load. Its route
    asked for the fleet's state, the owners and the reader's reach once PER ITEM — three whole
    reads for each of the demo's hundreds of items. Once per request now."""

    def test_the_board_and_the_capacity_read_the_fleet_state_once(self, tmp_path, monkeypatch):
        pytest.importorskip('flask')
        from lib.core.dcim import service as dcim_svc                # noqa: PLC0415
        from lib.web_admin import WebAdmin                           # noqa: PLC0415
        from tests.conftest import _login                            # noqa: PLC0415
        cfg, var = tmp_path / 'cfg', tmp_path / 'var'
        cfg.mkdir()
        var.mkdir()
        (cfg / 'config.json').write_text('{}', encoding='utf-8')
        wa = WebAdmin(str(cfg), 'admin', 'secret', str(var),
                      pw_require_upper=False, pw_require_digit=False)
        wa._csrf_enabled = False
        wa.app.config['TESTING'] = True
        demo.build(wa._dcim_store, var_dir=str(var))
        c = wa.app.test_client()
        _login(c)
        lecturas = []
        real = dcim_svc.states_for
        monkeypatch.setattr(dcim_svc, 'states_for', lambda *a, **k: lecturas.append(1) or real(*a, **k))
        for url in ('/api/v1/dcim/board', '/api/v1/dcim/fits'):
            lecturas.clear()
            r = c.get(url)
            assert r.status_code == 200, url
            assert len(lecturas) <= 1, (url, len(lecturas))

    def test_the_site_summary_counts_its_devices_by_state(self, tmp_path):
        """Asked for: the site's summary should say, loud, how many devices are fine, warn or
        are down — not only the worst. The tree brings the counts; the summary paints a card per
        state, the down and the warning ones highlighted when there are any."""
        pytest.importorskip('flask')
        import shutil                                                # noqa: PLC0415
        from lib.web_admin import WebAdmin                           # noqa: PLC0415
        from tests.conftest import _login                            # noqa: PLC0415
        from tests.helpers import node_run, panel_bundle             # noqa: PLC0415
        cfg, var = tmp_path / 'cfg', tmp_path / 'var'
        cfg.mkdir()
        var.mkdir()
        (cfg / 'config.json').write_text('{}', encoding='utf-8')
        wa = WebAdmin(str(cfg), 'admin', 'secret', str(var),
                      pw_require_upper=False, pw_require_digit=False)
        wa._csrf_enabled = False
        wa.app.config['TESTING'] = True
        made = demo.build(wa._dcim_store, var_dir=str(var))
        c = wa.app.test_client()
        _login(c)
        sede = next(x for x in c.get('/api/v1/dcim/sites').get_json()['sites']
                    if x['uid'] == made['site'])
        n = sede['roll']['counts']
        assert n['error'] > 0 and n['warning'] > 0 and n['ok'] > 0, n
        if shutil.which('node') is None:
            return
        out = node_run(panel_bundle(c), '__out = {}; const h = _dcimStateKpis(%s); '
                       '__out.rojo = /border-danger[^"]*bg-danger-subtle/.test(h); '
                       '__out.amarillo = h.includes("bg-warning-subtle"); '
                       '__out.alCuadro = h.includes("_dcimOpenBoard()"); '
                       '__out.ceroApagado = !_dcimStateKpis({ok: 3, warning: 0, error: 0, '
                       'unwatched: 0}).includes("bg-danger-subtle"); '
                       '__out.enLaFicha = String(_dcimDetailSite).includes("_dcimStateKpis(")'
                       % __import__('json').dumps(n))
        assert {k: out.get(k) for k in ('rojo', 'amarillo', 'alCuadro', 'ceroApagado',
                                        'enLaFicha')} == dict.fromkeys(
            ('rojo', 'amarillo', 'alCuadro', 'ceroApagado', 'enLaFicha'), True)


class TestItsWords:

    def test_every_language_says_the_same_things(self):
        """A key missing from a translation falls back to Spanish in the middle of an English
        demo; one extra is a word nobody uses."""
        import glob
        import json
        files = glob.glob(os.path.join(demo.TEXTS_DIR, '*.json'))
        keys = {os.path.basename(p): set(json.load(open(p, encoding='utf-8'))) for p in files}
        assert len(keys) >= 2
        assert len({frozenset(k) for k in keys.values()}) == 1, keys

    def test_built_in_english_and_removed_from_any_language(self, tmp_path):
        store = DcimStore(get_connector(None, default_sqlite_path=str(tmp_path / 'data.db')))
        made = demo.build(store, var_dir=str(tmp_path), lang='en_EN', area_word='general area')
        names = {r['name'] for r in store.rooms_of(made['site'])}
        assert 'Main data centre' in names and 'CPD principal' not in names
        assert store.sites.get(made['site_dr'])['name'] == 'Demo · DR'
        assert demo.remove(store, var_dir=str(tmp_path)) == 2
        assert not any(_counts(tmp_path).values())


class TestBuildingItAgain:

    def test_it_refuses_to_duplicate_itself(self, built):
        store, _made, path = built
        with pytest.raises(demo.DemoError):
            demo.build(store, var_dir=str(path))
        assert _counts(path)['dc_site'] == 2

    def test_replace_rebuilds_with_the_same_counts_and_no_stray_files(self, built):
        store, made, path = built
        before = _counts(path)
        again = demo.build(store, var_dir=str(path), replace=True)
        assert _counts(path) == before
        assert again['site'] != made['site']
        assert len(_media(path)) == _FILES

    def test_remove_leaves_nothing_behind(self, built):
        store, _made, path = built
        assert demo.remove(store, var_dir=str(path)) == 2
        assert not any(_counts(path).values())
        assert not _media(path)

    def test_remove_keeps_what_is_not_the_demo(self, built):
        """Other sites and companies stay, and so does a demo model somebody put to use on an
        item of their own."""
        from lib.core.dcim.catalog import CatalogStore
        store, _made, path = built
        other = store.sites.create({'name': 'Real'})
        org = store.orgs.create({'name': 'Otra'})
        store.set_owner('site', other, org)
        room = store.rooms.create({'site_uid': other, 'name': 'Sala'})
        rack = store.racks.create({'room_uid': room, 'name': 'R', 'u_height': 42})
        cat = CatalogStore(store._db)
        usado = cat.list('source = ?', (demo.SOURCE,))[0]
        store.items.create({'rack_uid': rack, 'label': 'mío', 'u_start': 1, 'u_height': 1,
                            'type_uid': usado['uid']})
        demo.remove(store, var_dir=str(path))
        assert [s['name'] for s in store.sites.list()] == ['Real']
        assert [o['name'] for o in store.orgs.list()] == ['Otra']
        assert [r['uid'] for r in cat.list('source = ?', (demo.SOURCE,))] == [usado['uid']]


class TestTheCommand:

    def _run(self, d, **kw):
        # Sin bajar las fotos del fabricante: una prueba no sale a internet.
        args = SimpleNamespace(cmd='dcim', sub='demo', replace=False, remove=False, no_images=True)
        for k, v in kw.items():
            setattr(args, k, v)
        return commands.run(args, d, d)

    def test_create_refuse_replace_remove(self, tmp_path, capsys):
        d = str(tmp_path)
        assert self._run(d) == 0
        assert "demo site 'Demo' created" in capsys.readouterr().out
        assert self._run(d) == 1
        assert '--replace' in capsys.readouterr().err
        assert self._run(d, replace=True) == 0
        assert self._run(d, remove=True) == 0
        assert 'demo removed (2 sites)' in capsys.readouterr().out
        assert self._run(d, remove=True) == 0
        assert 'no demo' in capsys.readouterr().out

    def test_it_speaks_the_language_it_is_given(self, tmp_path):
        """`-l` reaches the command. The CLI read `web_admin.lang`, which no setting writes, and
        `-l` went nowhere: a Spanish panel got an English demo."""
        d = str(tmp_path)
        assert self._run(d, lang='es_ES') == 0
        store = DcimStore(get_connector(None, default_sqlite_path=str(tmp_path / 'data.db')))
        assert {f['name'] for f in store.floors.list()} == {'Sótano', 'Planta baja',
                                                            'Planta primera', 'Planta segunda',
                                                            'Planta tercera'}

    def test_the_panel_language_is_default_lang(self, tmp_path):
        from lib.cli.context import CliContext
        d = str(tmp_path)
        ctx = CliContext(d, d)
        cfg = ctx._config_mgr.read() or {}                  # noqa: SLF001
        cfg.setdefault('web_admin', {})['default_lang'] = 'es_ES'
        assert ctx._config_mgr.write(cfg)                   # noqa: SLF001
        assert CliContext(d, d).lang == 'es_ES'
