#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo's structured cabling (`demo_cabling`): an office as an installer would leave it.

Every desk has a double outlet with the PC on A and the phone on B; every outlet's back is a
horizontal run to a patch panel of its floor's distribution rack, no longer than the 90 m the
standard allows; the panel's back goes to a port of an access switch, and the switch up to the
core. A fibre ring joins the distribution racks, and a copper trunk the data centre's two
network racks. What is checked is that the cabling holds together: every end device reaches a
switch, and no port takes two cables.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest

from lib.core.dcim import demo
from lib.core.dcim import service as dcim_svc
from lib.core.dcim.store import DcimStore
from lib.db import get_connector

_END = ('pc', 'phone', 'printer', 'ap', 'camera', 'display')


@pytest.fixture(scope='module')
def office(tmp_path_factory):
    path = tmp_path_factory.mktemp('cabling')
    db = get_connector(None, default_sqlite_path=str(path / 'data.db'))
    store = DcimStore(db)
    made = demo.build(store, var_dir=str(path))
    rooms = [r for k in demo.UID_KEYS for r in store.rooms_of(made[k])]
    items = {i['uid']: i for r in rooms for i in store.items_in_room(r['uid'])}
    racked = {i['uid']: i for r in rooms for k in store.racks_of(r['uid'])
              for i in store.items_of(k['uid'])}
    cables = store.cables_of(list(items) + list(racked))
    return store, items, racked, cables


class TestTheDesks:

    def test_an_office_full_of_end_devices(self, office):
        _store, items, _racked, _cables = office
        n = Counter(i['role'] for i in items.values())
        assert n['pc'] >= 40 and n['phone'] >= 30 and n['outlet'] >= n['pc']
        assert n['printer'] >= 1 and n['ap'] >= 5 and n['camera'] >= 5 and n['display'] >= 1

    def test_every_end_device_reaches_a_switch_port(self, office):
        store, items, _racked, _cables = office
        sin = []
        for uid, it in items.items():
            if it['role'] not in _END:
                continue
            # Its data paths: the power lead into its socket is a path too, and ends there.
            paths = [p for p in dcim_svc.trace(store, uid)
                     if (p[1].get('cable') or {}).get('kind') != 'power']
            if not paths or any(p[-1]['role'] != 'switch' for p in paths):
                sin.append(it['label'])
        assert sin == []

    def test_a_pc_goes_through_its_outlet_and_a_patch_panel(self, office):
        store, items, _racked, _cables = office
        pc = next(u for u, i in items.items() if i['role'] == 'pc')
        roles = [h['role'] for h in dcim_svc.trace(store, pc)[0]]
        assert roles == ['pc', 'outlet', 'patch_panel', 'switch']


class TestTheCables:

    def test_no_port_takes_two_cables(self, office):
        _store, _items, _racked, cables = office
        ends = Counter((c[s + '_item'], c[s + '_port']) for c in cables for s in 'ab')
        assert [e for e, n in ends.items() if n > 1] == []

    def test_every_outlet_jack_is_a_horizontal_run_of_90_m_at_most(self, office):
        _store, items, racked, cables = office
        outlets = {u for u, i in items.items() if i['role'] == 'outlet'}
        runs = [c for c in cables if (c['a_item'] in outlets and c['b_item'] in racked)
                or (c['b_item'] in outlets and c['a_item'] in racked)]
        assert len(runs) == 2 * len(outlets)                    # A and B, both cabled
        assert all(0 < int(c['length_mm']) <= 90000 for c in runs)
        assert {racked[c['b_item'] if c['b_item'] in racked else c['a_item']]['role']
                for c in runs} == {'patch_panel'}

    def test_a_fibre_ring_that_closes_and_a_trunk_between_the_network_racks(self, office):
        _store, _items, _racked, cables = office
        ring = [c for c in cables if str(c.get('label') or '').startswith('ANILLO-')]
        assert len(ring) >= 4 and all(c['kind'] == 'fiber' for c in ring)
        # A ring: every panel on it has exactly two fibres of it.
        panels = Counter(c[s + '_item'] for c in ring for s in 'ab')
        assert set(panels.values()) == {2}
        trunk = [c for c in cables if str(c.get('label') or '').startswith('TRONCAL-N01-N02')]
        assert len(trunk) == 12

    def test_every_access_switch_has_an_uplink(self, office):
        _store, _items, racked, cables = office
        idf = [u for u, i in racked.items()
               if i['role'] == 'switch' and re.match(r'SW-(P\d|S)-\d+$', str(i.get('label') or ''))]
        assert idf
        for sw in idf:
            ports = [c[s + '_port'] for c in cables for s in 'ab' if c[s + '_item'] == sw]
            assert any(str(p).startswith('Te') for p in ports), racked[sw]['label']


class TestTheJacksAndTheSockets:
    """Asked for: power sockets in the demo, and the outlets with their jacks — two RJ45 at least
    in each. Every desk has a socket beside its outlet; the sockets hang from the building's
    sources, so the plan shows the three kinds (UPS, generator, mains)."""

    def test_every_outlet_has_two_rj45_at_least_and_says_only_what_it_may(self, office):
        from lib.core.dcim import connectors                         # noqa: PLC0415
        puede = {c['id'] for c in connectors.jacks('outlet')}
        malas = []
        for it in office[1].values():
            if it['role'] != 'outlet':
                continue
            bocas = dcim_svc.jack_list(it)
            rj45 = sum(b['n'] for b in bocas if b['connector'] == '8p8c')
            if rj45 < 2 or any(b['connector'] not in puede for b in bocas):
                malas.append((it['label'], bocas))
        assert malas == []

    def test_every_pc_printer_and_display_is_plugged_into_a_socket(self, office):
        """Reported: the demo's PCs showed no outlet and no socket. Each is cabled to its outlet
        and its power lead goes into jack A of the socket beside it."""
        store, items, _racked, cables = office
        sin = []
        for uid, it in items.items():
            if it['role'] not in ('pc', 'printer', 'display'):
                continue
            mios = store.cables_of([uid])
            corriente = [c for c in mios if c['kind'] == 'power'
                         and items.get(c['b_item'] if c['a_item'] == uid else c['a_item'], {}).get('role') == 'power_outlet']
            datos = [c for c in mios if c['kind'] != 'power']
            if len(corriente) != 1 or not datos:
                sin.append(it['label'])
        assert sin == []

    def test_a_meeting_rooms_display_outlet_has_its_hdmi(self, office):
        tv = [it for it in office[1].values() if it['role'] == 'outlet' and str(it['label']).startswith('R-TV-')]
        assert tv and all(any(b['connector'] == 'hdmi' for b in dcim_svc.jack_list(it)) for it in tv)

    def test_a_socket_by_every_desk_on_a_source_of_the_site(self, office):
        from lib.core.dcim import connectors                         # noqa: PLC0415
        store, items, _racked, _cables = office
        n = Counter(i['role'] for i in items.values())
        assert n['power_outlet'] >= n['pc']
        puede = {c['id'] for c in connectors.jacks('power_outlet')}
        clases = Counter()
        for it in items.values():
            if it['role'] != 'power_outlet':
                continue
            bocas = dcim_svc.jack_list(it)
            assert bocas and all(b['connector'] in puede for b in bocas), it['label']
            src = store.sources.get(it['source_uid'])
            room = store.rooms.get(it['room_uid'])
            assert src and src['site_uid'] == room['site_uid'], it['label']
            clases[src['kind']] += 1
        assert clases['ups'] >= 1 and clases['generator'] == 1 and clases['panel'] >= n['pc'] // 2


class TestWhereTheyStand:

    def test_inside_their_room(self, office):
        store, items, _racked, _cables = office
        fuera = []
        for it in items.values():
            room = store.rooms.get(it['room_uid'])
            W, D = float(room.get('width_mm') or 0), float(room.get('depth_mm') or 0)
            x, y = float(it['pos_x'] or 0), float(it['pos_y'] or 0)
            if W and D and not (0 <= x <= W and 0 <= y <= D):
                fuera.append((it['label'], room['name'], x, y, W, D))
        assert fuera == []


class TestTheCCTV:
    """Asked for: the demo lacked the whole CCTV side. A video surveillance system as installed
    (UNE-EN 62676): cameras where it is worth recording, a recorder, where it is watched from,
    and the signs the law asks for where one comes in."""

    def test_cameras_where_it_is_worth_recording_and_not_over_the_desks(self, office):
        store, items, _racked, _cables = office
        rooms = {}
        for it in items.values():
            if it['role'] == 'camera':
                room = store.rooms.get(it['room_uid'])
                rooms.setdefault(room['name'], []).append(it['label'])
        etiquetas = {l for ls in rooms.values() for l in ls}
        assert len(etiquetas) >= 20
        for prefijo in ('CAM-PARK-', 'CAM-HALL-', 'CAM-EXT-', 'CAM-DOCK-', 'CAM-CPD', 'CAM-HPC-',
                        'CAM-SRV-', 'CAM-ENE-'):
            assert any(e.startswith(prefijo) for e in etiquetas), prefijo
        # People at work are not filmed (LOPDGDD art. 89): no camera in an office or open space.
        w = demo.texts('es_ES')
        oficinas = {w[k] for k in ('room_open2', 'room_open3', 'room_off_dir', 'room_off_fin',
                                   'room_off_rrhh', 'room_off_it', 'room_off_cto', 'room_off_ops')}
        assert not oficinas & set(rooms)

    def test_a_recorder_in_the_data_centre_to_both_cores_with_its_disks(self, office):
        store, _items, racked, cables = office
        nvr = next(u for u, i in racked.items() if i['label'] == 'NVR-01')
        a = {c['b_item'] if c['a_item'] == nvr else c['a_item'] for c in cables
             if nvr in (c['a_item'], c['b_item'])}
        assert {racked[u]['label'] for u in a} == {'CORE-1', 'CORE-2'}
        # A disk is a `disk` —the parts' vocabulary—, not an `hdd`: an unknown kind is one no
        # filter and no screen of the parts finds.
        discos = [p for p in store.parts_of([nvr]) if p['kind'] == 'disk']
        assert discos and discos[0]['qty'] == 8
        assert '30' in discos[0]['description']              # how long it keeps (LOPDGDD 22.3)
        assert racked[nvr]['demo_state'] == 'warning'

    def test_watched_from_reception_and_the_noc(self, office):
        store, items, _racked, _cables = office
        pantallas = {i['label'] for i in items.values() if i['role'] == 'display'}
        assert {'MON-CCTV-1', 'VW-NOC-1', 'VW-NOC-2'} <= pantallas
        for label in ('MON-CCTV-1', 'VW-NOC-1'):
            uid = next(u for u, i in items.items() if i['label'] == label)
            assert dcim_svc.trace(store, uid)[0][-1]['role'] == 'switch'

    def test_the_signs_where_one_comes_in(self, office):
        store, items, _racked, _cables = office
        w = demo.texts('es_ES')
        rooms = {it['room_uid'] for it in items.values()}
        letreros = [f for r in rooms for f in store.features_of(r) if f['label'] == w['cctv_sign']]
        assert len(letreros) >= 3
