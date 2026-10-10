#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo building's structured cabling, as a cabling engineer would lay it.

Every floor has its distribution rack —the ground floor's and the basement's in the
communications room (COM-01), the first floor's in the data centre's network row (N01), the
office floors' in their IDF— and every workstation is wired back to it:

* a **double outlet** on each desk, the PC on jack A and the IP phone on jack B, each by a 2 m
  patch cord;
* the **horizontal cable** (Cat 6A) from each jack's back (``A-R``) to the back of a port of a
  patch panel in the rack (``N-R``), its length the route along the ceiling trays;
* the panel's **front** port to the access switch, port for port (`DcimStore` passes through
  a passive's ``N`` ↔ ``N-R``, so a PC traces to its switch port);
* access points on the ceiling of every room big enough to need one, cameras in the corridors
  and at the data centre's door, a printer in each printing area, and in every meeting room a
  display and a conference phone, all wired the same way;
* the access switches' **uplinks** to both cores through the fibre: switch → jumper → the
  rack's fibre panel → **fibre trunk** → the data centre's fibre panel → jumper → core;
* a **fibre ring** joining the data centre's two network racks and the floors' distribution
  racks panel to panel, and a **copper trunk** between the two network racks.

Patch panels and switches are added to each rack as the ports run out, 24 at a time.
"""

from __future__ import annotations

#: Where each distribution rack has room for a patch panel (with its cable manager under it)
#: and its access switch, from the top down: ``(U of the panel, U of the switch)``.
_LAYOUT = {
    'idf': [(40, 27), (38, 26), (36, 25), (34, 24), (32, 23), (30, 22)],
    'com': [(34, 26), (32, 25), (30, 24), (28, 23)],
    'cpd': [(30, 24), (28, 23)],
}
#: The cores' free ports for the access switches' uplinks: the rows take 1–16, the HPC room
#: 17–28, the server room 36, the odd rack 40, the stack 47 and the operators 48.
_CORE_PORTS = (29, 30, 31, 32, 33, 34, 35, 37, 38, 39, 41, 42, 43, 44, 45, 46)

#: Rooms with no access point: the data rooms and the plant rooms.
_NO_AP = {'cpd', 'hpc', 'srv', 'ene', 'gen', 'bat', 'pci', 'idf2', 'idf3', 'com', 'wc'}
#: Rooms whose desks carry a PC and no phone (workbenches, the training room's seats).
_PC_ONLY = {'lab', 'exp', 'alm', 'train', 'stage'}
#: Where a corridor runs on each floor, in floor millimetres (y): the cameras hang there.
_CORRIDOR_Y = {'floor_ground': 10000, 'floor_first': 10000, 'floor_second': 10000,
               'floor_third': 10000, 'floor_basement': 10000}
#: What a distribution rack serves: floor → the one it is in.
_SERVED_BY = {'floor_ground': 'com', 'floor_basement': 'com', 'floor_first': 'cpd',
              'floor_second': 'P2', 'floor_third': 'P3'}
_LEVEL = {'floor_basement': -1, 'floor_ground': 0, 'floor_first': 1, 'floor_second': 2,
          'floor_third': 3}


class _Cabling:
    """The ports as they are used: which patch panel port comes next in each rack, which fibre
    port in each fibre panel, which core port for the next uplink."""

    def __init__(self, b, net, geo):
        self.b, self.net, self.geo = b, net, geo
        self.fibre = {}
        self.cores = list(_CORE_PORTS)

    # ── the fibre ──

    def fibre_port(self, panel: str) -> int:
        n = self.fibre.get(panel, 0) + 1
        if n > 24:
            raise RuntimeError('fibre panel full')
        self.fibre[panel] = n
        return n

    def uplink(self, dist: dict, sw: str, k: int) -> None:
        """The access switch's two uplinks, one to each core: through the fibre trunk from a
        distribution rack, or straight to the core in the data centre's own network rack."""
        b, net = self.b, self.net
        boca = self.cores.pop(0)
        for n, core in enumerate(net['cores']):
            etiqueta = '%s-%d-C%d' % (dist['tag'], k + 1, n + 1)
            if dist['kind'] == 'cpd':
                b.cable(sw, 'Te1/1/%d' % (n + 1), core, 'Te1/0/%d' % boca, kind='dac',
                        category='dac-passive', color='black', length=2000, label=etiqueta)
                continue
            cpd = net['cpd_fiber'][n]
            p_local, p_cpd = self.fibre_port(dist['fiber']), self.fibre_port(cpd)
            b.cable(sw, 'Te1/1/%d' % (n + 1), dist['fiber'], str(p_local), kind='fiber',
                    category='os2', color='yellow', length=1000, label=etiqueta)
            b.cable(dist['fiber'], '%d-R' % p_local, cpd, '%d-R' % p_cpd, kind='fiber',
                    category='os2', color='yellow', length=self.trunk_length(dist),
                    label='TR-' + etiqueta)
            b.cable(cpd, str(p_cpd), core, 'Te1/0/%d' % boca, kind='fiber', category='os2',
                    color='yellow', length=2000, label=etiqueta)

    def trunk_length(self, dist: dict) -> int:
        """From a distribution rack to the data centre: up or down the riser, along the trays."""
        x, y = self.geo['rack_xy'][dist['rack']]
        cx, cy = self.geo['rack_xy'][self.net['cpd_rack']]
        pisos = abs(_LEVEL[dist['floor']] - _LEVEL['floor_first'])
        return int(min(150000, abs(x - cx) + abs(y - cy) + pisos * 4000 + 8000) // 500 * 500)

    # ── the copper ──

    def add_pair(self, dist: dict) -> dict:
        """A patch panel, its cable manager and its access switch, the panel's front ports
        cabled to the switch's, and the switch's uplinks."""
        b, w = self.b, self.b.w
        k = len(dist['pairs'])
        u_panel, u_sw = _LAYOUT[dist['kind']][k]
        letra = 'ABCDEF'[k]
        pp = b.item(dist['rack'], w['patch_desks'] % ('%s-%s' % (dist['tag'], letra)), 'patch_panel',
                    u_panel, face='front', model='patch')
        b.item(dist['rack'], w['cable_manager'], 'blank', u_panel - 1, face='front')
        sw = b.item(dist['rack'], 'SW-%s-%d' % (dist['tag'], k + 1), 'switch', u_sw, model='tor')
        if isinstance(dist['power'], tuple):
            b.dual(sw, 'switch', dist['power'])
        else:
            b.feed(sw, dist['power'], 370)                  # PoE: the phones and the APs
        for port in range(1, 25):
            b.cable(pp, str(port), sw, 'Gi1/0/%d' % port, category='cat6a',
                    color='blue' if port % 2 else 'grey', length=500,
                    label='%s-%s%02d' % (dist['tag'], letra, port))
        self.uplink(dist, sw, k)
        par = {'pp': pp, 'letter': letra, 'next': 1}
        dist['pairs'].append(par)
        return par

    def horizontal(self, dist: dict, item: str, port: str, xy: tuple, floor: str) -> None:
        """The horizontal cable from an item's port —an outlet's back, an access point's— to the
        next free port at the back of a patch panel in its floor's rack."""
        par = next((p for p in dist['pairs'] if p['next'] <= 24), None) or self.add_pair(dist)
        n = par['next']
        par['next'] += 1
        rx, ry = self.geo['rack_xy'][dist['rack']]
        pisos = abs(_LEVEL[floor] - _LEVEL[dist['floor']])
        largo = abs(xy[0] - rx) + abs(xy[1] - ry) + 6000 + pisos * 4000 + 3000
        self.b.cable(item, port, par['pp'], '%d-R' % n, category='cat6a', color='white',
                     length=int(min(90000, largo) // 500 * 500),
                     label='%s-%s%02d' % (dist['tag'], par['letter'], n))


def _room_item(b, room: str, role: str, label: str, x: float, y: float, rot: int = 0,
               **extra) -> str:
    data = {'room_uid': room, 'rack_uid': '', 'placement': 'room', 'u_start': 0, 'u_height': 0,
            'face': 'full', 'role': role, 'label': label, 'pos_x': round(x), 'pos_y': round(y),
            'rotation': rot}
    data.update(extra)
    return b.new('items', data)


def _on_desk(desk: dict, fx: float, fy: float, w: int, d: int) -> tuple:
    """Where an item of ``w × d`` sits on a desk, at the fractions ``(fx, fy)`` of the desk —
    ``fy`` from the edge where one sits (the desk's front, its ``pos_y`` side before turning,
    as every piece's) to its back—, turned with it. The PC and the outlet go at the back: they
    were on the edge where one sits."""
    x, y = float(desk['pos_x']), float(desk['pos_y'])
    dw, dd = float(desk['width_mm']), float(desk['depth_mm'])
    if int(desk.get('rotation') or 0) % 360 == 180:
        fx, fy = 1 - fx, 1 - fy
    return x + fx * dw - w / 2, y + fy * dd - d / 2


def build(b, site: str, floors: dict, net: dict) -> dict:
    """Wire the whole building. Returns counts of what it put: ``{endpoints, outlets, ...}``."""
    from lib.core.dcim.demo import _FLOORS                 # noqa: PLC0415
    from lib.core.dcim.store import ROOM_ITEM_DEFAULTS      # noqa: PLC0415
    w = b.w
    # Where everything is on its floor, in floor millimetres.
    room_xy = {}
    for key, _lvl, rooms, _win, _ent in _FLOORS:
        for rk, x, y, _w, _d in rooms:
            room_xy[(key, rk)] = (x, y)
    uid_room = {}
    for fkey, floor in floors.items():
        for rk, uid in floor['rooms'].items():
            uid_room[uid] = (fkey, rk)
    rack_xy = {}
    for fkey, floor in floors.items():
        for rk, uid in floor['rooms'].items():
            ox, oy = room_xy[(fkey, rk)]
            for r in b.s.racks_of(uid):
                rack_xy[r['uid']] = (ox + float(r['pos_x'] or 0), oy + float(r['pos_y'] or 0))
    cab = _Cabling(b, net, {'rack_xy': rack_xy})
    dists = net['dists']
    cuenta = {'endpoints': 0, 'outlets': 0, 'aps': 0, 'cameras': 0, 'printers': 0, 'displays': 0}

    def size(role):
        return ROOM_ITEM_DEFAULTS[role][:2]

    def wire(fkey, room, item_uid, port, x, y):
        ox, oy = room_xy[uid_room[room]]
        cab.horizontal(dists[_SERVED_BY[fkey]], item_uid, port, (ox + x, oy + y), fkey)

    def outlet_for(fkey, room, label, x, y, rot, mount='desk', base=None):
        extra = {'mount': mount}
        if base is not None:
            extra['base_mm'] = base
        o = _room_item(b, room, 'outlet', label, x, y, rot, **extra)
        cuenta['outlets'] += 1
        for jack in ('A', 'B'):
            wire(fkey, room, o, jack + '-R', x, y)
        return o

    def patch(a, a_port, o, jack, color='grey'):
        b.cable(a, a_port, o, jack, category='cat6a', color=color, length=2000)

    for fkey, floor in floors.items():
        lvl_tag = {'floor_basement': 'S', 'floor_ground': 'P0', 'floor_first': 'P1',
                   'floor_second': 'P2', 'floor_third': 'P3'}[fkey]
        for rk, room in floor['rooms'].items():
            W, D, _arriba = floor['size'][rk]
            piezas = b.s.features_of(room)
            # The desks: a double outlet on each, the PC on A and the phone on B.
            if rk.startswith('meet'):
                mesa = next((f for f in piezas if f['kind'] == 'bench'), None)
                dw, dd = size('display')
                tv = _room_item(b, room, 'display', 'TV-%s' % w['room_' + rk], (W - dw) / 2, 60,
                                180)
                o = outlet_for(fkey, room, 'R-TV-%s' % w['room_' + rk], W / 2 - 43, 60, 180,
                               mount='wall')
                patch(tv, 'hdmi-lan', o, 'A')
                cuenta['displays'] += 1
                if mesa:
                    pw, pd = size('phone')
                    tel = _room_item(b, room, 'phone', 'TEL-%s' % w['room_' + rk],
                                     float(mesa['pos_x']) + float(mesa['width_mm']) / 2 - pw / 2,
                                     float(mesa['pos_y']) + float(mesa['depth_mm']) / 2 - pd / 2)
                    patch(tel, 'eth0', o, 'B', 'yellow')
                    cuenta['endpoints'] += 2
            elif rk != 'kitchen':
                for desk in [f for f in piezas if f['kind'] == 'bench']:
                    nombre = str(desk.get('label') or '').replace(' ', '')
                    rot = int(desk.get('rotation') or 0)
                    ow, od = size('outlet')
                    x, y = _on_desk(desk, 0.5, 0.95, ow, od)
                    o = outlet_for(fkey, room, nombre, x, y, rot)
                    pw, pd = size('pc')
                    x, y = _on_desk(desk, 0.2, 0.75, pw, pd)
                    pc = _room_item(b, room, 'pc', 'PC-%s' % nombre, x, y, rot)
                    patch(pc, 'eth0', o, 'A')
                    cuenta['endpoints'] += 1
                    solo_pc = rk in _PC_ONLY and desk.get('label') != w['trainer']
                    if not solo_pc:
                        tw, td = size('phone')
                        x, y = _on_desk(desk, 0.78, 0.55, tw, td)
                        tel = _room_item(b, room, 'phone', 'TEL-%s' % nombre, x, y, rot)
                        patch(tel, 'eth0', o, 'B', 'yellow')
                        cuenta['endpoints'] += 1
            # A printer in each printing area, on the floor, with its own outlet.
            for zona in [f for f in piezas if f['kind'] == 'zone' and f.get('label') == w['printer']]:
                iw, idd = size('printer')
                x = float(zona['pos_x']) + (float(zona['width_mm']) - iw) / 2
                y = float(zona['pos_y']) + (float(zona['depth_mm']) - idd) / 2
                imp = _room_item(b, room, 'printer', 'IMP-%s' % lvl_tag, x, y)
                o = outlet_for(fkey, room, 'R-IMP-%s' % lvl_tag, x + iw + 100, y, 0, mount='floor', base=0)
                patch(imp, 'eth0', o, 'A')
                cuenta['printers'] += 1
            # An access point in the middle of the ceiling of every room big enough to need one.
            if rk not in _NO_AP and W * D >= 15e6:
                aw, ad = size('ap')
                ap = _room_item(b, room, 'ap', 'AP-%s-%s' % (lvl_tag, rk.upper()), W / 2 - aw / 2,
                                D / 2 - ad / 2)
                wire(fkey, room, ap, 'eth0', W / 2, D / 2)
                cuenta['aps'] += 1
            # And a camera on the data centre's door.
            if rk == 'cpd':
                cw, cd = size('camera')
                cam = _room_item(b, room, 'camera', 'CAM-CPD', W / 2 + 900, D - 200, 0)
                wire(fkey, room, cam, 'eth0', W / 2, D)
                cuenta['cameras'] += 1
        # Two cameras in each floor's corridor, at either end, on the ceiling.
        # (Su zona común: si nadie la ha hecho aún, se hace, como la hace el control de acceso.)
        from lib.core.dcim.demo import _area                # noqa: PLC0415
        area = b.s.floors.get(floor['uid']).get('area_uid') or _area(b, floor)
        if area:
            uid_room[area] = (fkey, '__area__')
            room_xy[(fkey, '__area__')] = (0, 0)
            y = _CORRIDOR_Y[fkey]
            for n, x in enumerate((1500, 28000)):
                cam = _room_item(b, area, 'camera', 'CAM-%s-%d' % (lvl_tag, n + 1), x, y, 0,
                                 mount='ceiling', base_mm=2900)
                wire(fkey, area, cam, 'eth0', x, y)
                cuenta['cameras'] += 1
    _cctv(b, floors, net, cuenta, wire, outlet_for, patch)
    _backbone(b, net, cab)
    return cuenta


#: The CCTV cameras beyond the corridors' and the data centre door's: ``(floor, room, label, x,
#: y, mount, height)`` — room millimetres; ``room`` ``None`` is the floor's general area. Where
#: a security consultant puts them: the way in and the turnstiles, the façade at the entrance,
#: the loading dock, both ends of each contained aisle, the server and energy rooms, the car
#: park — what is worth recording and nothing of the desks (people at work are not filmed:
#: LOPDGDD art. 89).
_CAMERAS = (
    ('floor_first', 'cpd', 'CAM-CPD-A1', 1100, 2900, 'wall', 2700),
    ('floor_first', 'cpd', 'CAM-CPD-A2', 6700, 2900, 'wall', 2700),
    ('floor_third', 'hpc', 'CAM-HPC-1', 1100, 3300, 'wall', 2700),
    ('floor_third', 'srv', 'CAM-SRV-1', 6600, 300, 'wall', 2700),
    ('floor_basement', 'ene', 'CAM-ENE-1', 12800, 8200, 'wall', 2700),
    ('floor_basement', None, 'CAM-PARK-1', 3600, 13400, 'ceiling', 2600),
    ('floor_basement', None, 'CAM-PARK-2', 10000, 13400, 'ceiling', 2600),
    ('floor_basement', None, 'CAM-PARK-3', 16400, 13400, 'ceiling', 2600),
    ('floor_ground', None, 'CAM-HALL-1', 15000, 12200, 'ceiling', 2900),
    ('floor_ground', None, 'CAM-EXT-ACC', 16600, 19450, 'wall', 2700),
    ('floor_ground', 'exp', 'CAM-DOCK-1', 7300, 200, 'wall', 2700),
)


def _cctv(b, floors, net, cuenta, wire, outlet_for, patch) -> None:
    """The video surveillance system (UNE-EN 62676): the cameras, PoE from the floor's access
    switch over their own horizontal run, as any outlet; the recorder in the data centre's
    second network rack, with its disks and a link to each core; a monitor in reception and a
    two-screen video wall in the NOC, each on its own outlet; and the «area under video
    surveillance» signs where one comes in — the street door, the car park, the dock
    (LOPDGDD art. 22.4)."""
    w = b.w
    for fkey, rk, label, x, y, mount, alto in _CAMERAS:
        floor = floors[fkey]
        room = floor['rooms'][rk] if rk else b.s.floors.get(floor['uid'])['area_uid']
        cam = _room_item(b, room, 'camera', label, x, y, 0, mount=mount, base_mm=alto)
        wire(fkey, room, cam, 'eth0', x, y)
        cuenta['cameras'] += 1
    # The recorder: 64 channels, eight disks, in the second network rack, to both cores.
    core1, core2 = net['cores'][:2]
    rack = b.s.items.get(core2)['rack_uid']
    pdus = tuple(p['uid'] for p in b.s.pdus_of(rack))
    # (Lo que es y cuánto guarda, en sus discos: la descripción del equipo la pisa su estado.)
    nvr = b.item(rack, 'NVR-01', 'storage', 26, 4, depth_mm=700, model='storage')
    b.dual(nvr, 'storage', pdus, watts=320)
    b.cable(nvr, 'ctrlA-0', core1, 'Gi1/0/3', color='red', length=3000, label='NVR-CORE1')
    b.cable(nvr, 'ctrlB-0', core2, 'Gi1/0/3', color='red', length=2000, label='NVR-CORE2')
    b.new('parts', {'item_uid': nvr, 'kind': 'hdd', 'size': '8 TB', 'qty': 8,
                    'model': 'Surveillance HDD', 'description': w['nvr_desc']})
    # Where it is watched from: reception and the NOC.
    for fkey, rk, label, x in (('floor_ground', 'recep', 'MON-CCTV-1', 1500),
                               ('floor_first', 'noc', 'VW-NOC-1', 2000),
                               ('floor_first', 'noc', 'VW-NOC-2', 3600)):
        floor = floors[fkey]
        room = floor['rooms'][rk]
        _W, D, _arriba = floor['size'][rk]
        pantalla = _room_item(b, room, 'display', label, x, D - 150, 0, mount='wall', base_mm=1400)
        o = outlet_for(fkey, room, 'R-' + label, x + 600, D - 150, 0, mount='wall')
        patch(pantalla, 'eth0', o, 'A')
        cuenta['displays'] += 1
    # The signs, where one comes in.
    for fkey, rk, x, y in (('floor_ground', None, 12300, 18900), ('floor_basement', None, 1000, 11400),
                           ('floor_ground', 'exp', 4000, 300)):
        floor = floors[fkey]
        room = floor['rooms'][rk] if rk else b.s.floors.get(floor['uid'])['area_uid']
        b.feature(room, 'label', w['cctv_sign'], x, y)


def _backbone(b, net, cab: _Cabling) -> None:
    """The fibre ring from panel to panel —the data centre's two network racks and every
    distribution rack— and the copper trunk between the two network racks."""
    paneles = [net['cpd_fiber'][0]] + [d['fiber'] for d in net['dists'].values()
                                       if d['kind'] != 'cpd' and d.get('fiber')] + [net['cpd_fiber'][1]]
    vistos = []
    for p in paneles:
        if p not in vistos:
            vistos.append(p)
    anillo = vistos + [vistos[0]]
    for n, (a, z) in enumerate(zip(anillo, anillo[1:])):
        pa, pz = cab.fibre_port(a), cab.fibre_port(z)
        b.cable(a, '%d-R' % pa, z, '%d-R' % pz, kind='fiber', category='os2', color='aqua',
                length=30000, label='ANILLO-%02d' % (n + 1))
    p1, p2 = net['cpd_patch']
    for port in range(13, 25):
        b.cable(p1, '%d-R' % port, p2, '%d-R' % port, category='cat6a', color='green',
                length=1500, label='TRONCAL-N01-N02-%02d' % port)
