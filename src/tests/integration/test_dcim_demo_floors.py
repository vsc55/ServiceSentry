#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo's floors, laid out to the rules in force in Spain.

Reported from the screen: the second floor had «dwarf corridors» — rooms 500 mm apart, a
380 mm slot between two partitions that read as a corridor nobody could walk down — and an
office building whose only way out of a 30 m floor was a stair in one corner. Asked for: think
as an architect, a designer and an electrical and cabling installer, and keep each to its
regulations. What is checked here is what those rules measure on a plan:

* CTE DB-SUA 9 / DB-SI 3 — corridors of 1.20 m clear at least, two exits from every floor and
  no evacuation route longer than 50 m;
* CTE DB-SUA 9 — an accessible lift and an accessible toilet on every floor where people work;
* CTE DB-SUA 2 — nothing hung in a corridor below 2.20 m sticking out into it;
* CTE DB-SI 1 — the special-risk rooms (power, generator, batteries, fire pumps, data rooms)
  behind a self-closing fire door;
* UNE-EN 50174-2 — data and power along the corridor in separate trays.
"""

from __future__ import annotations

import math

import pytest

from lib.core.dcim import demo
from lib.core.dcim.store import DcimStore
from lib.db import get_connector

_CLEAR = 1200                    # an accessible corridor's clear width (CTE DB-SUA 9)
_ROUTE = 50000                   # the longest evacuation route with two exits (CTE DB-SI 3)
_RISK = ('room_ene', 'room_gen', 'room_bat', 'room_pci', 'room_cpd', 'room_hpc', 'room_srv')
#: The free space each thing with a front needs before it, mm: a rack or a UPS is worked on from
#: there (1 m, UNE-EN 50600-2-2 / TIA-942), a cabinet is opened, a desk is sat at.
_FRONT = {'rack': 1000, 'ups': 1000, 'panel': 1000, 'cabinet': 700, 'crac': 800, 'bench': 600,
          'turnstile': 1000}


@pytest.fixture(scope='module')
def building(tmp_path_factory):
    path = tmp_path_factory.mktemp('floors')
    store = DcimStore(get_connector(None, default_sqlite_path=str(path / 'data.db')))
    made = demo.build(store, var_dir=str(path), lang='es_ES')
    store.made = made
    w = demo.texts('es_ES')
    floors = []
    for floor in store.floors_of(made['site']):
        salas = store.rooms.list('floor_uid = ?', (floor['uid'],))
        rooms = [r for r in salas if float(r['width_mm'] or 0)]
        area = next(r for r in salas if not float(r['width_mm'] or 0))
        floors.append((floor, rooms, area, store.walls_of(floor['uid'])))
    return store, w, floors


def _box(r):
    x, y = float(r['pos_x']), float(r['pos_y'])
    return x, y, x + float(r['width_mm']), y + float(r['depth_mm'])


class TestCorridors:

    def test_two_rooms_share_a_wall_or_leave_a_corridor_between_them(self, building):
        """No slot between two rooms: either they share the partition, or what is between them
        is a corridor a wheelchair goes down — 1.20 m clear, the partitions' half on each side
        taken off."""
        _store, _w, floors = building
        malos = []
        for floor, rooms, _area, _walls in floors:
            for i, a in enumerate(rooms):
                ax0, ay0, ax1, ay1 = _box(a)
                for b in rooms[i + 1:]:
                    bx0, by0, bx1, by1 = _box(b)
                    if ay0 < by1 and by0 < ay1:                   # side by side
                        gap = max(bx0 - ax1, ax0 - bx1)
                    elif ax0 < bx1 and bx0 < ax1:                 # one above the other
                        gap = max(by0 - ay1, ay0 - by1)
                    else:
                        continue
                    if gap < 0 or 0 < gap - demo._INNER < _CLEAR:
                        malos.append((floor['name'], a['name'], b['name'], gap))
        assert malos == []

    def test_every_room_opens_onto_the_corridor(self, building):
        _store, _w, floors = building
        for floor, rooms, _area, walls in floors:
            puertas = [m for m in walls if m['kind'] == 'door' and float(m['thick_mm']) < 200]
            for r in rooms:
                x0, _y0, x1, _y1 = _box(r)
                assert any(float(p['y1']) in demo._HALL and x0 <= float(p['x1']) <= x1
                           for p in puertas), (floor['name'], r['name'])

    def test_nothing_hung_in_the_corridor_sticks_out_below_2_20_m(self, building):
        store, _w, floors = building
        for _floor, _rooms, area, _walls in floors:
            for rack in store.racks_of(area['uid']):
                assert float(rack['base_mm'] or 0) >= 2200, rack['name']


class TestWaysOut:

    def test_two_exits_from_every_floor(self, building):
        """The stair core at the east end, and a door in the west façade at the end of the
        corridor: the exterior escape stair, or the street on the ground floor."""
        _store, w, floors = building
        for floor, _rooms, _area, walls in floors:
            assert floor['core_kind'] == 'stairs'
            oeste = [m for m in walls if m['kind'] == 'door' and float(m['x1']) == float(m['x2'])
                     == demo._OUTER / 2]
            assert oeste and all(demo._HALL[0] <= float(m['y1']) <= demo._HALL[1] for m in oeste), \
                floor['name']

    def test_no_route_is_longer_than_50_m(self, building):
        """From the far corner of every room to its door, then along the corridor to the nearer
        of the two exits — measured as one walks, along and across, never through a wall."""
        _store, _w, floors = building
        mid = sum(demo._HALL) / 2
        largas = []
        for floor, rooms, _area, walls in floors:
            puertas = [m for m in walls if m['kind'] == 'door' and float(m['thick_mm']) < 200]
            for r in rooms:
                x0, y0, x1, y1 = _box(r)
                p = next(m for m in puertas if float(m['y1']) in demo._HALL
                         and x0 <= float(m['x1']) <= x1)
                px, py = (float(p['x1']) + float(p['x2'])) / 2, float(p['y1'])
                dentro = max(abs(px - x) for x in (x0, x1)) + max(abs(py - y) for y in (y0, y1))
                hasta = min(px + abs(py - mid),                                   # west door
                            abs(demo._CORE[0] - px) + abs(demo._CORE[1] - py))    # stair core
                if dentro + hasta > _ROUTE:
                    largas.append((floor['name'], r['name'], round((dentro + hasta) / 1000, 1)))
        assert largas == []

    def test_no_room_stands_in_the_stair_core(self, building):
        _store, _w, floors = building
        cx, cy = demo._CORE
        for floor, rooms, _area, _walls in floors:
            for r in rooms:
                x0, y0, x1, y1 = _box(r)
                assert not (x0 < cx + 1500 and cx - 1500 < x1 and y0 < cy + 1500
                            and cy - 1500 < y1), (floor['name'], r['name'])


class TestForEveryone:

    def test_an_accessible_lift_on_every_floor(self, building):
        store, w, floors = building
        for floor, _rooms, area, _walls in floors:
            assert any(f['label'] == w['lift'] for f in store.features_of(area['uid'])), \
                floor['name']

    def test_toilets_with_an_accessible_one_where_people_work(self, building):
        """On every floor with desks or a meeting room, at the same place on each (the drains go
        straight down), and the accessible one with room for a wheelchair to turn (Ø 1.50 m)."""
        store, w, floors = building
        sitios = set()
        for floor, rooms, _area, _walls in floors:
            nombres = {r['name'] for r in rooms}
            if floor['level'] < 0:
                continue
            assert w['room_wc'] in nombres, floor['name']
            wc = next(r for r in rooms if r['name'] == w['room_wc'])
            sitios.add((wc['pos_x'], wc['pos_y']))
            acc = [f for f in store.features_of(wc['uid']) if f['label'] == w['wc_accessible']]
            assert acc and min(float(acc[0]['width_mm']), float(acc[0]['depth_mm'])) >= 1500
        assert len(sitios) == 1


class TestFireAndCables:

    def test_special_risk_rooms_behind_a_fire_door(self, building):
        store, w, floors = building
        for _floor, rooms, _area, _walls in floors:
            for r in rooms:
                if r['name'] not in {w[k] for k in _RISK}:
                    continue
                puertas = [f for f in store.features_of(r['uid'])
                           if f['kind'] == 'door' and f['label'] in ('', w['door_fire'])]
                assert puertas and all(f['label'] == w['door_fire'] for f in puertas), r['name']

    def test_data_and_power_in_separate_trays_along_the_corridor(self, building):
        store, w, floors = building
        for floor, _rooms, area, _walls in floors:
            bandejas = {f['label']: f for f in store.features_of(area['uid'])
                        if f['kind'] == 'tray'}
            datos, fuerza = bandejas.get(w['tray_data']), bandejas.get(w['tray_power'])
            assert datos and fuerza, floor['name']
            # Apart, not one over the other: there is corridor between them.
            hueco = float(fuerza['pos_y']) - (float(datos['pos_y']) + float(datos['depth_mm']))
            assert hueco >= 300, (floor['name'], hueco)
            for t in (datos, fuerza):
                assert demo._HALL[0] < float(t['pos_y']) < demo._HALL[1]


def _ante(x, y, w, d, rot, W, D):
    """The free space before a piece's front —its ``pos_y`` side before turning— up to its
    room's wall, in mm."""
    a = math.radians(rot)
    n = (math.sin(a), -math.cos(a))
    px, py = x + w / 2 + n[0] * d / 2, y + d / 2 + n[1] * d / 2
    t = [v for v in ((W - px) / n[0] if n[0] > 1e-6 else None, -px / n[0] if n[0] < -1e-6 else None,
                     (D - py) / n[1] if n[1] > 1e-6 else None, -py / n[1] if n[1] < -1e-6 else None)
         if v is not None]
    return min(t)


class TestWhichWayThingsFace:

    def test_nothing_faces_a_wall(self, building):
        """Reported from the screen: racks, cabinets and desks of the demo faced the wall — a lab
        rack with its front 30 cm from it, a wall cabinet hung front to the wall, the battery
        racks, the UPSs, the kitchen counters. A thing's front faces its room, with the space
        it is worked from before it. A split on the wall blows down from up high: not counted."""
        store, _w, _floors = building
        malos = []
        for site in (store.made['site'], store.made['site_dr']):
            for room in store.rooms_of(site):
                W, D = float(room.get('width_mm') or 0), float(room.get('depth_mm') or 0)
                if not W:
                    continue
                cosas = [('rack', r['name'], r, 0) for r in store.racks_of(room['uid'])]
                cosas += [(f['kind'], f['label'], f, f.get('base_mm') or 0)
                          for f in store.features_of(room['uid']) if f['kind'] in _FRONT]
                for kind, nombre, c, base in cosas:
                    if kind == 'crac' and base:
                        continue
                    libre = _ante(float(c['pos_x']), float(c['pos_y']), float(c['width_mm']),
                                  float(c['depth_mm']), int(c['rotation'] or 0), W, D)
                    if libre < _FRONT[kind]:
                        malos.append((room['name'], kind, nombre, round(libre)))
        assert malos == []

    def test_a_desks_pc_and_outlet_are_at_its_back(self, building):
        """And on a desk, the PC and the outlet at the back, not on the edge where one sits."""
        store, _w, floors = building
        for _floor, rooms, _area, _walls in floors:
            for room in rooms:
                mesas = {f['label'].replace(' ', ''): f for f in store.features_of(room['uid'])
                         if f['kind'] == 'bench'}
                for it in store.items_in_room(room['uid']):
                    if it['role'] != 'pc' or not str(it['label']).startswith('PC-'):
                        continue
                    mesa = mesas.get(str(it['label'])[3:])
                    if not mesa:
                        continue
                    cy = float(it['pos_y']) + 100
                    y0, dd = float(mesa['pos_y']), float(mesa['depth_mm'])
                    # Its front is pos_y before turning: the back is the far half.
                    detras = cy > y0 + dd / 2 if int(mesa['rotation'] or 0) % 360 == 0                         else cy < y0 + dd / 2
                    assert detras, (room['name'], it['label'])
