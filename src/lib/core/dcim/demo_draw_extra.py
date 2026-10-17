#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Draws the rest of the demo's catalogue: what is not a device in a U of its own.

`demo_draw` draws the fifteen devices; this draws everything else the demo places or fits, in
the same style and with the same rule —every socket and bay is registered by the call that
draws it—:

* the **cabinets** (``rack-types``): front and rear, as their doors are seen, at their outer
  size in millimetres;
* the **power**: the vertical 0U strips of every rack channel, the 1U strip of a small rack, the
  UPS on the floor beside a rack;
* the **passive** pieces of a rack: a blanking panel, a cable manager, a shelf;
* the **devices of a room**: a desktop PC, an IP phone, an access point, a dome camera, a
  display, a printer;
* the **modules** (``module-types``) that slide into a device's bays —its supplies, its fans,
  its network card, a storage controller, the optics in its cages—, each with its own ports;
* the **components** (``component-types``) that go inside —memory, processors, drives, a GPU—,
  seen as one holds them.

A module or a component has one picture (``front``) and no rear: it is seen out of its device.
"""

from __future__ import annotations

import math

from lib.core.dcim import demo_draw as d
from lib.core.dcim.demo_draw import (AMBER, BLUE, CAGE, CAGE_EDGE, EDGE, GOLD, GREEN, HOLE,
                                     PCB, PCB_EDGE, SILK, SILK_DIM, STEEL_3,
                                     TOUCH, U, W19, Face)

#: The mesh of a cabinet's door: the same hexagonal perforation as a device's front, at the size
#: a door has it —holes of 5 mm—, so it reads as a mesh at the scale of a whole cabinet.
d._PATTERNS.setdefault('mesh', (
    '<pattern id="mesh" width="12" height="10.4" patternUnits="userSpaceOnUse">'
    '<circle cx="3" cy="2.6" r="2.4" fill="#0d0f12"/>'
    '<circle cx="9" cy="7.8" r="2.4" fill="#0d0f12"/></pattern>'))

#: The black of a socket's plastic, and the white of a printer's or a phone's.
SOCKET = '#111317'
WHITE = '#e5e7eb'
WHITE_2 = '#d1d5db'


# ── sockets of a power strip ─────────────────────────────────────────────────────────────────

def c13(f: Face, cx, cy, name) -> None:
    """An IEC C13 outlet centred on *cx, cy*: the chamfered socket of a rack strip, three slots."""
    f.rect(cx - 8, cy - 7.5, 16, 15, SOCKET, rx=1, stroke='#4b5563', sw=0.3)
    f.poly([(cx - 6, cy - 3), (cx - 3.4, cy - 5.6), (cx + 3.4, cy - 5.6), (cx + 6, cy - 3),
            (cx + 6, cy + 5.6), (cx - 6, cy + 5.6)], '#262a31')
    for px in (cx - 3.6, cx + 2.6):
        f.rect(px, cy + 0.4, 1, 3.4, HOLE)
    f.rect(cx - 0.5, cy - 4.2, 1, 3, HOLE)
    f.port('power-outlets', name, 'iec-60320-c13', cx, cy)


def c19(f: Face, cx, cy, name) -> None:
    """An IEC C19 outlet: the wider 16 A socket a big supply's C20 cord goes in."""
    f.rect(cx - 9.5, cy - 7.5, 19, 15, SOCKET, rx=1, stroke='#4b5563', sw=0.3)
    f.rect(cx - 7.5, cy - 5.6, 15, 11.2, '#262a31', rx=0.8)
    f.rect(cx - 5.4, cy + 0.8, 3.6, 1.1, HOLE)
    f.rect(cx + 1.8, cy + 0.8, 3.6, 1.1, HOLE)
    f.rect(cx - 0.55, cy - 4.4, 1.1, 3.6, HOLE)
    f.port('power-outlets', name, 'iec-60320-c19', cx, cy)


def breaker(f: Face, x, y, label='') -> None:
    """A miniature circuit breaker: its toggle in the on position."""
    f.rect(x, y, 9, 14, '#1f2329', rx=0.8, stroke='#4b5563', sw=0.3)
    f.rect(x + 2.5, y + 2, 4, 6, '#e5e7eb', rx=0.5)
    if label:
        f.text(x + 4.5, y + 12.4, label, size=1.8, fill=SILK_DIM, anchor='middle')


def lcd(f: Face, x, y, w, h, s='', size=3.2) -> None:
    """A small backlit display: what a metered strip or a UPS reads out."""
    f.rect(x, y, w, h, '#0b1220', rx=0.8, stroke='#1e3a8a', sw=0.4)
    if s:
        f.text(x + w / 2, y + h / 2 + size / 3, s, size=size, fill='#38bdf8', anchor='middle',
               bold=True)


def gland(f: Face, cx, cy, fam, name, typ, volts, watts, label='') -> None:
    """Where a fixed mains cord leaves a strip: the gland, and the plug at its end is the
    strip's inlet."""
    f.circle(cx, cy, 6, '#1f2329', stroke='#4b5563', sw=0.4)
    f.circle(cx, cy, 3.6, '#0d0f12')
    f.circle(cx, cy, 2.4, '#2b2f36')
    if label:
        f.text(cx, cy + 10, label, size=2.2, fill=SILK_DIM, anchor='middle')
    f.port(fam, name, typ, cx, cy, volts=volts, watts=watts)


# ── the cabinets ─────────────────────────────────────────────────────────────────────────────

#: A 42U cabinet's outer height, and the others': the frame, the plinth and the roof added to
#: the units.
RACK_HEIGHT = {42: 2000.0, 24: 1200.0, 12: 635.0}


def _door_perf(f: Face, x, y, w, h, lock_x) -> None:
    """A perforated steel door: the mesh (the 80 % open area a cold aisle needs), its frame, the
    swing handle with its lock."""
    f.rect(x, y, w, h, '#23262c', rx=3, stroke=EDGE, sw=1.2)
    f.rect(x + 18, y + 22, w - 36, h - 44, '#3a404a', rx=2)
    f.rect(x + 18, y + 22, w - 36, h - 44, f.use_pattern('mesh'), rx=2)
    f.rect(lock_x - 8, y + h / 2 - 70, 16, 140, '#3f4550', rx=4, stroke='#6b7280', sw=0.6)
    f.rect(lock_x - 4, y + h / 2 - 54, 8, 80, '#9ca3af', rx=3)
    f.circle(lock_x, y + h / 2 + 48, 4.5, '#d4a72c', stroke='#8a6a12', sw=0.6)
    f.rect(lock_x - 0.8, y + h / 2 + 45, 1.6, 6, '#5b4a14')


def _rack_frame(f: Face, roof: bool = True) -> None:
    f.rect(0, 0, f.w, f.h, '#16181c', rx=4)
    if roof:
        f.rect(0, 0, f.w, 40, '#1f2329', rx=4)
        for k in range(6):
            f.rect(f.w / 2 - 150 + k * 52, 12, 40, 16, '#0d0f12', rx=3)
        f.rect(0, f.h - 100, f.w, 100, '#1f2329')
        for x in (30, f.w - 90):
            f.rect(x, f.h - 30, 60, 30, '#0d0f12', rx=2)


def _rack_label(f: Face, code: str, y: float) -> None:
    f.rect(f.w / 2 - 70, y, 140, 28, '#0d0f12', rx=3)
    f.text(f.w / 2, y + 19, code, size=14, fill=SILK, anchor='middle', bold=True)


def rack_cabinet(code: str, units: int, width: float, split_rear: bool, side_ducts: bool):
    """A floor-standing cabinet: a single perforated door at the front, at the rear a single or
    a split one (a split rear door opens in a hot aisle without hitting the next row). An 800 mm
    network cabinet shows the vertical cable ducts either side of the 19-inch frame."""
    alto = RACK_HEIGHT[units]
    front = Face(width, alto)
    _rack_frame(front)
    _door_perf(front, 8, 44, width - 16, alto - 152, width - 50)
    if side_ducts:
        for x in (22, width - 120):
            front.rect(x, 70, 98, alto - 210, 'none', rx=2, stroke=SILK_DIM, sw=1)
        front.text(71, alto - 128, 'DUCT', size=12, fill=SILK_DIM, anchor='middle')
        front.text(width - 71, alto - 128, 'DUCT', size=12, fill=SILK_DIM, anchor='middle')
    _rack_label(front, code, 60)
    front.text(width / 2, alto - 60, '%dU · 19"' % units, size=16, fill=SILK_DIM,
               anchor='middle', bold=True)

    rear = Face(width, alto)
    _rack_frame(rear)
    if split_rear:
        mitad = (width - 20) / 2
        _door_perf(rear, 8, 44, mitad, alto - 152, 8 + mitad - 30)
        _door_perf(rear, 12 + mitad, 44, mitad, alto - 152, 12 + mitad + 30)
    else:
        _door_perf(rear, 8, 44, width - 16, alto - 152, 42)
    _rack_label(rear, code, alto - 200)
    rear.text(width / 2, alto - 60, 'REAR', size=16, fill=SILK_DIM, anchor='middle', bold=True)
    return {'front': front, 'rear': rear, 'views': []}


def wall_cabinet(code: str, units: int, width: float):
    """A wall-mounted cabinet: a toughened glass door with its lock —the switch and the panel
    seen through it, on their 19-inch rails— and a solid back with the keyhole slots it hangs
    from and the cable entry at the top."""
    alto = RACK_HEIGHT[units]
    front = Face(width, alto)
    front.rect(0, 0, width, alto, '#1f2329', rx=4)
    front.rect(12, 12, width - 24, alto - 24, '#0f172a', rx=3, stroke='#475569', sw=2)
    for x in (70, width - 82):
        front.rect(x, 30, 12, alto - 60, '#4b5563')
        for k in range(units * 3):
            front.rect(x + 4, 40 + k * (alto - 80) / (units * 3), 4, 3, HOLE)
    front.rect(12, 12, width - 24, alto - 24, '#93c5fd', rx=3, op=0.12)
    front.el('line', x1=40, y1=40, x2=width / 2, y2=alto / 2, stroke='#e0f2fe',
             stroke_width=2, opacity=0.25)
    front.rect(width - 44, alto / 2 - 40, 20, 80, '#3f4550', rx=4, stroke='#6b7280', sw=0.6)
    front.circle(width - 34, alto / 2 + 22, 5, '#d4a72c', stroke='#8a6a12', sw=0.6)
    _rack_label(front, code, alto - 60)

    rear = Face(width, alto)
    rear.rect(0, 0, width, alto, '#23262c', rx=4)
    rear.rect(10, 10, width - 20, alto - 20, 'none', rx=3, stroke=EDGE, sw=1.5)
    for x in (80, width - 100):
        for y in (60, alto - 100):
            rear.rect(x, y, 20, 40, '#0d0f12', rx=10)
            rear.circle(x + 10, y + 10, 8, '#0d0f12')
    rear.rect(width / 2 - 150, 24, 300, 50, '#0d0f12', rx=8)
    rear.text(width / 2, 56, 'CABLE ENTRY', size=12, fill=SILK_DIM, anchor='middle')
    rear.rect(width / 2 - 120, alto / 2 - 40, 240, 80, rear.use_pattern('slots'))
    _rack_label(rear, code, alto - 150)
    return {'front': front, 'rear': rear, 'views': []}


def rack612():
    """DM-RK42-612: the server cabinet of the data centre's rows: 42U, 600 × 1200 mm, a split
    rear door for the hot aisle."""
    return rack_cabinet('DM-RK42-612', 42, 600.0, True, False)


def rack810():
    """DM-RK42-810: the network cabinet: 42U, 800 × 1000 mm, with the vertical cable ducts the
    extra 200 mm are for."""
    return rack_cabinet('DM-RK42-810', 42, 800.0, True, True)


def rack610():
    """DM-RK42-610: the general cabinet of a server room or a small site: 42U, 600 × 1000."""
    return rack_cabinet('DM-RK42-610', 42, 600.0, False, False)


def rack608():
    """DM-RK24-608: the half-height cabinet of the lab: 24U, 600 × 800."""
    return rack_cabinet('DM-RK24-608', 24, 600.0, False, False)


def wall12():
    """DM-WM12-645: the wall cabinet of a corridor or a lab bench: 12U, 600 × 450, glass door."""
    return wall_cabinet('DM-WM12-645', 12, 600.0)


# ── power: the strips and the UPS ────────────────────────────────────────────────────────────

#: The length of a 0U strip for a 42U cabinet, and its width and depth.
PDU0_LEN = 1780.0
PDU0_W = 56.0


def _pdu_vertical(code: str, banks: list, inlet: tuple, meter: str):
    """A vertical 0U strip, its top on the picture's top. *banks*: ``[(label, kinds)]``, each
    bank's outlets from the top down (``'c13'`` / ``'c19'``) behind its breaker; *inlet*: the
    type, volts and watts of the plug at the end of its fixed cord. The meter and its network
    management port at the top, as a metered strip has them."""
    front = Face(PDU0_W, PDU0_LEN)
    front.rect(0, 0, PDU0_W, PDU0_LEN, '#1f2329', rx=3)
    front.rect(1, 1, PDU0_W - 2, PDU0_LEN - 2, 'none', rx=2.6, stroke=EDGE, sw=0.8)
    front.rect(4, 8, PDU0_W - 8, 168, '#2b2f36', rx=2)
    front.text(PDU0_W / 2, 20, code, size=4.6, fill=SILK, anchor='middle', bold=True)
    lcd(front, 8, 26, PDU0_W - 16, 18, meter, 5)
    d.led(front, 12, 52, GREEN, 1.2)
    d.led(front, PDU0_W - 12, 52, AMBER, 1.2)
    d.rj45(front, PDU0_W / 2 - 6, 62, 'interfaces', 'NET', '1000base-t')
    front.text(PDU0_W / 2, 80, 'NET MGMT', size=2.6, fill=SILK_DIM, anchor='middle')
    d.console_rj45(front, PDU0_W / 2 - 6, 92, 'console-ports', 'Serial', label='')
    front.text(PDU0_W / 2, 110, 'SERIAL', size=2.6, fill=SILK_DIM, anchor='middle')
    d.usb_a(front, PDU0_W / 2 - 2.9, 120, 'console-ports', 'USB', gen='usb2', vertical=True)
    front.text(PDU0_W / 2, 142, 'USB', size=2.6, fill=SILK_DIM, anchor='middle')
    n = sum(len(k) for _l, k in banks)
    y = 190.0
    paso = (PDU0_LEN - 190 - 120 - len(banks) * 26) / max(1, n)
    numero = 0
    colores = ('#2563eb', '#dc2626', '#16a34a')
    for b, (etiqueta, tipos) in enumerate(banks):
        front.rect(4, y, PDU0_W - 8, 22, colores[b % 3], rx=1.5, op=0.85)
        breaker(front, 6, y + 4)
        front.text(PDU0_W / 2 + 6, y + 14, etiqueta, size=4, fill='#ffffff', anchor='middle',
                   bold=True)
        y += 26
        for tipo in tipos:
            numero += 1
            cy = y + paso / 2
            (c19 if tipo == 'c19' else c13)(front, PDU0_W / 2 + 4, cy, str(numero))
            front.text(9, cy + 1.4, str(numero), size=3.6, fill=SILK_DIM, anchor='middle')
            y += paso
    typ, volts, watts = inlet
    gland(front, PDU0_W / 2, PDU0_LEN - 40, 'power-ports', 'Inlet', typ, volts, watts,
          label='INPUT')

    rear = Face(PDU0_W, PDU0_LEN)
    rear.rect(0, 0, PDU0_W, PDU0_LEN, '#2b2f36', rx=3)
    rear.rect(1, 1, PDU0_W - 2, PDU0_LEN - 2, 'none', rx=2.6, stroke=EDGE, sw=0.8)
    for cy in (150, PDU0_LEN - 150):
        rear.circle(PDU0_W / 2, cy, 9, '#9ca3af', stroke='#4b5563', sw=0.6)
        rear.circle(PDU0_W / 2, cy, 4, '#4b5563')
    rear.rect(10, 400, PDU0_W - 20, PDU0_LEN - 800, rear.use_pattern('slots'))
    rear.rect(6, PDU0_LEN / 2 - 30, PDU0_W - 12, 60, '#e5e7eb', rx=1)
    rear.text(PDU0_W / 2, PDU0_LEN / 2 - 8, code, size=4, fill='#1f2937', anchor='middle',
              bold=True)
    rear.text(PDU0_W / 2, PDU0_LEN / 2 + 8, '%s V~' % volts, size=3.6, fill='#1f2937',
              anchor='middle')
    rear.text(PDU0_W / 2, PDU0_LEN / 2 + 20, '%d W max' % watts, size=3.6, fill='#1f2937',
              anchor='middle')
    return {'front': front, 'rear': rear, 'views': []}


def pdu0u16():
    """DM-PDU0-16: a metered 0U strip on a 16 A single-phase feed: 20 C13 and 4 C19 in one
    bank, its plug a C20."""
    return _pdu_vertical('DM-PDU0-16', [('L1 16A', ['c13'] * 10 + ['c19'] * 4 + ['c13'] * 10)],
                         ('iec-60320-c20', '230', 3680), '3.7 kW')


def pdu0u32():
    """DM-PDU0-32: a metered 0U strip on a 32 A single-phase feed: two banks of 12 behind their
    breakers, 18 C13 and 6 C19, its plug an IEC 60309 32 A."""
    banco = ['c13'] * 4 + ['c19'] * 3 + ['c13'] * 5
    return _pdu_vertical('DM-PDU0-32', [('B1 16A', banco), ('B2 16A', banco)],
                         ('iec-60309-p-n-e-4h', '230', 7360), '7.4 kW')


def pdu0u3p():
    """DM-PDU0-3P: a switched 0U strip on a three-phase 32 A feed (22 kW): a bank per phase,
    each of six C13 and two C19, its plug an IEC 60309 3P+N+E."""
    banco = ['c13'] * 3 + ['c19'] * 2 + ['c13'] * 3
    return _pdu_vertical('DM-PDU0-3P', [('L1', banco), ('L2', banco), ('L3', banco)],
                         ('iec-60309-3p-n-e-4h', '400', 22080), '22 kW')


def pdu1u():
    """DM-PDU1-16: a horizontal 1U strip for a small rack: ten C13 and two C19 on one 16 A
    breaker, its inlet a C20."""
    front = Face(W19, U)
    d.chassis(front, '#1f2329', ears=1)
    front.text(36, 15, 'DM-PDU1-16', size=3, fill=SILK, bold=True)
    breaker(front, 36, 20, '16A')
    for k in range(10):
        c13(front, 70 + k * 26, U / 2, str(k + 1))
        front.text(70 + k * 26, 41.6, str(k + 1), size=2.2, fill=SILK_DIM, anchor='middle')
    for k in range(2):
        c19(front, 340 + k * 30, U / 2, str(11 + k))
        front.text(340 + k * 30, 41.6, str(11 + k), size=2.2, fill=SILK_DIM, anchor='middle')
    d.iec_inlet(front, 432, U / 2, 'power-ports', 'Inlet', 'iec-60320-c20', watts=3680,
                volts='230')
    rear = Face(W19, U)
    d.chassis(rear, '#2b2f36')
    rear.rect(40, 8, 400, 28.45, rear.use_pattern('slots'))
    rear.rect(180, 14, 120, 16, '#e5e7eb', rx=1)
    rear.text(240, 24.6, 'DM-PDU1-16 · 230 V~ 16 A', size=3, fill='#1f2937', anchor='middle')
    return {'front': front, 'rear': rear, 'views': []}


def _ups(code: str, units: int, va: str, outlets: list, inlet: tuple):
    """A rack/tower UPS: its LCD and buttons behind the vented bezel at the front; at the rear
    its outlet groups, its inlet, the network management card, USB, serial and the EPO."""
    alto = units * U
    front = Face(W19, alto)
    d.chassis(front, '#1d2026', ears=units)
    d.perf(front, 22, 6, 300, alto - 12)
    front.rect(330, 6, 130.6, alto - 12, '#24272d', rx=1.5)
    lcd(front, 340, 12, 70, 26, va, 6)
    for k, c in enumerate((GREEN, AMBER, '#ef4444')):
        d.led(front, 420 + k * 10, 18, c, 1.2)
    for k in range(4):
        front.circle(345 + k * 18, 52, 5, '#3b4250', stroke=SILK_DIM, sw=0.4)
    d.button(front, 440, 52, 5)
    front.text(395, alto - 10, code, size=4.4, fill=SILK, anchor='middle', bold=True)

    rear = Face(W19, alto)
    d.chassis(rear, '#1d2026')
    typ, volts, watts = inlet
    if typ == 'iec-60309-p-n-e-4h':
        gland(rear, 40, alto / 2, 'power-ports', 'AC IN', typ, volts, watts, label='INPUT')
    else:
        d.iec_inlet(rear, 40, alto / 2, 'power-ports', 'AC IN', typ, watts=watts, volts=volts)
    breaker(rear, 62, alto / 2 - 7, 'IN')
    x = 90.0
    for k, tipo in enumerate(outlets):
        cy = alto / 2 - 10 if k % 2 == 0 else alto / 2 + 10
        (c19 if tipo == 'c19' else c13)(rear, x + 12, cy, str(k + 1))
        if k % 2 == 1 or k == len(outlets) - 1:
            x += 28
    rear.text(x / 2 + 40, alto - 4, 'OUTPUT · %s V~' % volts, size=2.4, fill=SILK_DIM,
              anchor='middle')
    rear.rect(330, 8, 60, alto - 16, '#2b2f36', rx=1, stroke='#6b7280', sw=0.5)
    d.rj45(rear, 344, alto / 2 - 5, 'interfaces', 'NMC', '1000base-t')
    rear.text(360, 14, 'NMC', size=2.4, fill=SILK_DIM, anchor='middle')
    d.console_rj45(rear, 400, alto / 2 - 5, 'console-ports', 'Serial', label='')
    rear.text(406, alto / 2 - 7, 'SERIAL', size=2, fill=SILK_DIM, anchor='middle')
    rear.rect(420, alto / 2 - 4, 9, 8, CAGE, rx=0.8, stroke=CAGE_EDGE, sw=0.3)
    rear.rect(421.8, alto / 2 - 2.4, 5.4, 4.8, HOLE, rx=0.5)
    rear.port('console-ports', 'USB', 'usb-b', 424.5, alto / 2)
    rear.text(424.5, alto / 2 - 6, 'USB', size=2, fill=SILK_DIM, anchor='middle')
    rear.rect(440, alto / 2 - 6, 16, 12, '#b91c1c', rx=1)
    rear.text(448, alto / 2 + 1.2, 'EPO', size=2.6, fill='#ffffff', anchor='middle', bold=True)
    d.ground(rear, 462, 8)
    return {'front': front, 'rear': rear, 'views': []}


def ups1k5():
    """DM-UPS1500: 1.5 kVA / 1350 W line-interactive, 2U rack/tower: six C13 out, C14 in."""
    return _ups('DM-UPS1500', 2, '1500 VA', ['c13'] * 6, ('iec-60320-c14', '230', 1500))


def ups3k():
    """DM-UPS3000: 3 kVA / 2700 W on-line double conversion, 2U: eight C13 and one C19 out,
    C20 in."""
    return _ups('DM-UPS3000', 2, '3000 VA', ['c13'] * 8 + ['c19'],
                ('iec-60320-c20', '230', 3000))


def ups6k():
    """DM-UPS6000: 6 kVA / 6000 W on-line double conversion, 4U with its batteries: six C13 and
    four C19 out, fed from a 32 A IEC 60309."""
    return _ups('DM-UPS6000', 4, '6000 VA', ['c13'] * 6 + ['c19'] * 4,
                ('iec-60309-p-n-e-4h', '230', 6600))


# ── the passive pieces of a rack ─────────────────────────────────────────────────────────────

def blank():
    """DM-BP1: a tool-less 1U blanking panel —it clips into the square holes—, ribbed so it
    does not flex. It closes a U so the hot air does not come back round to the front."""
    front = Face(W19, U)
    d.chassis(front, '#1b1d22', ears=1)
    for k in range(3):
        front.rect(30, 10 + k * 9.5, W19 - 60, 4, '#23262c', rx=2)
    front.text(W19 - 22, 41, 'DM-BP1', size=2, fill=SILK_DIM, anchor='end')
    rear = Face(W19, U)
    rear.rect(0, 0, W19, U, '#15171b', rx=1.5)
    for x in (4, W19 - 14):
        rear.rect(x, 10, 10, 24.45, '#6b7280', rx=1.5)
    rear.rect(30, 6, W19 - 60, 32.45, 'none', rx=1, stroke=EDGE, sw=0.6)
    return {'front': front, 'rear': rear, 'views': []}


def cablemgr():
    """DM-CM1: a 1U horizontal cable manager: five D-rings in front of a brush strip, so the
    patch leads cross to the switch below without hanging over its ports."""
    front = Face(W19, U)
    d.chassis(front, '#1b1d22', ears=1)
    front.rect(26, 15, W19 - 52, 14.45, '#0d0f12', rx=2)
    for k in range(40):
        front.line(30 + k * 10.6, 16, 32 + k * 10.6, 28.45, '#374151', 1.2)
    for k in range(5):
        x = 40 + k * 100
        front.rect(x, 4, 14, 36.45, '#2b2f36', rx=6, stroke='#6b7280', sw=0.6)
        front.rect(x + 3, 9, 8, 26.45, '#1b1d22', rx=4)
    front.text(W19 - 22, 42, 'DM-CM1', size=2, fill=SILK_DIM, anchor='end')
    rear = Face(W19, U)
    rear.rect(0, 0, W19, U, '#15171b', rx=1.5)
    rear.rect(16, 6, W19 - 32, 32.45, '#23262c', rx=1)
    for k in range(5):
        d.screw(rear, 47 + k * 100, U / 2, 2)
    return {'front': front, 'rear': rear, 'views': []}


def shelf():
    """DM-SH1: a 1U vented cantilever shelf, bolted to the front posts only: 500 mm deep, 25 kg.
    The lab's mini PCs sit on it."""
    front = Face(W19, U)
    d.chassis(front, '#262a30', ears=1)
    front.rect(20, 28, W19 - 40, 12, '#3f4550', rx=1)
    front.rect(26, 6, W19 - 52, 18, '#1b1d22', rx=1)
    front.rect(26, 6, W19 - 52, 18, front.use_pattern('slots'))
    front.text(W19 - 24, 37, 'DM-SH1 · 25 kg', size=2.4, fill=SILK, anchor='end')
    rear = Face(W19, U)
    rear.rect(0, 0, W19, U, '#15171b', rx=1.5)
    rear.rect(20, 30, W19 - 40, 8, '#3f4550', rx=1)
    rear.rect(30, 8, W19 - 60, 16, rear.use_pattern('slots'))
    return {'front': front, 'rear': rear, 'views': []}


# ── the devices of a room ────────────────────────────────────────────────────────────────────

def pc():
    """DM-PC5: a small-form-factor desktop: power and USB at the front, at the rear the gigabit
    port, two DisplayPort, four USB and the C14 of its 180 W supply."""
    front = Face(290, 95)
    front.rect(0, 0, 290, 95, '#22252b', rx=3)
    front.rect(2, 2, 286, 91, 'none', rx=2.6, stroke=EDGE, sw=0.6)
    d.perf(front, 10, 10, 180, 75, rx=2)
    d.button(front, 210, 24, 4.4, ring=BLUE)
    d.usb_a(front, 228, 14, 'front-ports', 'USB 1', gen='usb3.2g2')
    d.usb_a(front, 228, 24, 'front-ports', 'USB 2', gen='usb3.2g2')
    d.usb_c(front, 230, 36, 'front-ports', 'USB-C')
    d.audio_jack(front, 250, 54, 'front-ports', 'Audio')
    front.text(276, 86, 'DM-PC5', size=4.4, fill=SILK, anchor='end', bold=True)
    rear = Face(290, 95)
    rear.rect(0, 0, 290, 95, '#22252b', rx=3)
    d.iec_inlet(rear, 30, 24, 'power-ports', 'psu', watts=180)
    d.fan_grille(rear, 30, 66, 20)
    d.rj45(rear, 70, 12, 'interfaces', 'eth0', '1000base-t')
    d.displayport(rear, 90, 12, 'rear-ports', 'DP 1')
    d.displayport(rear, 90, 22, 'rear-ports', 'DP 2')
    for k in range(4):
        d.usb_a(rear, 116 + (k % 2) * 16, 12 + (k // 2) * 10, 'rear-ports', 'USB %d' % (k + 3),
                gen='usb3.2g1' if k < 2 else 'usb2')
    d.audio_jack(rear, 160, 18, 'rear-ports', 'Line out')
    for k in range(2):
        d.bracket(rear, 70 + k * 100, 46, 96, 16, 'PCIe %d' % (k + 1))
    rear.rect(250, 10, 30, 76, '#2b2f36', rx=2)
    rear.rect(258, 40, 14, 10, '#111317', rx=2)
    rear.text(265, 60, 'LOCK', size=3, fill=SILK_DIM, anchor='middle')
    return {'front': front, 'rear': rear, 'views': []}


def phone():
    """DM-IP4: a desk IP phone: colour screen, line keys, keypad and handset; at the back the
    PoE port it is fed by and the PC port the desk's computer can hang from."""
    front = Face(210, 190)
    front.rect(0, 0, 210, 190, '#1f2329', rx=10)
    front.rect(8, 10, 54, 170, '#2b2f36', rx=22, stroke='#4b5563', sw=0.8)
    front.rect(74, 12, 126, 62, '#0b1220', rx=3, stroke='#1e3a8a', sw=0.6)
    front.text(137, 46, '12:00 · Ext 2001', size=8, fill='#38bdf8', anchor='middle')
    for r in range(4):
        for c in range(3):
            front.rect(92 + c * 30, 86 + r * 22, 24, 16, '#3b4250', rx=3)
            front.text(104 + c * 30, 97 + r * 22, '123456789*0#'[r * 3 + c], size=8, fill=SILK,
                       anchor='middle')
    d.led(front, 196, 16, '#ef4444', 2)
    rear = Face(210, 190)
    rear.rect(0, 0, 210, 190, '#2b2f36', rx=10)
    rear.rect(20, 20, 170, 150, 'none', rx=8, stroke=EDGE, sw=0.8)
    d.rj45(rear, 60, 100, 'interfaces', 'eth0', '1000base-t', signals=['ethernet', 'power-in'],
           watts=7)
    rear.text(66, 120, 'NET · PoE', size=6, fill=SILK_DIM, anchor='middle')
    d.rj45(rear, 120, 100, 'interfaces', 'pc', '1000base-t')
    rear.text(126, 120, 'PC', size=6, fill=SILK_DIM, anchor='middle')
    rear.rect(150, 100, 9, 8, CAGE, rx=1, stroke=CAGE_EDGE, sw=0.3)
    rear.port('rear-ports', 'Headset', 'other', 154.5, 104)
    rear.text(154.5, 120, 'HS', size=6, fill=SILK_DIM, anchor='middle')
    rear.text(105, 60, 'DM-IP4', size=12, fill=SILK, anchor='middle', bold=True)
    return {'front': front, 'rear': rear, 'views': []}


def ap():
    """DM-AP7: a ceiling Wi-Fi 7 access point —2.4, 5 and 6 GHz radios—, fed by PoE+ on its
    2.5 GbE port."""
    front = Face(230, 230)
    front.rect(0, 0, 230, 230, '#f3f4f6', rx=40, stroke=WHITE_2, sw=2)
    front.rect(20, 20, 190, 190, '#e5e7eb', rx=32)
    front.circle(115, 115, 14, 'none', stroke='#38bdf8', sw=3)
    front.circle(115, 115, 4, '#38bdf8')
    front.text(115, 200, 'DM-AP7', size=10, fill='#6b7280', anchor='middle', bold=True)
    for k, (x, y, banda) in enumerate(((60, 60, '2.4'), (170, 60, '5'), (115, 165, '6'))):
        front.circle(x, y, 10, 'none', stroke='#9ca3af', sw=1)
        front.text(x, y + 3, banda, size=7, fill='#9ca3af', anchor='middle')
        front.port('interfaces', 'wlan%d' % k, 'ieee802.11be', x, y)
    rear = Face(230, 230)
    rear.rect(0, 0, 230, 230, '#d1d5db', rx=40)
    rear.rect(40, 40, 150, 150, '#9ca3af', rx=10)
    for x, y in ((50, 50), (170, 50), (50, 170), (170, 170)):
        d.screw(rear, x + 5, y + 5, 3)
    d.rj45(rear, 90, 110, 'interfaces', 'eth0', '2.5gbase-t', signals=['ethernet', 'power-in'],
           watts=25)
    rear.text(96, 132, 'ETH0 · PoE+', size=7, fill='#1f2937', anchor='middle')
    d.dc_jack(rear, 150, 115, 'power-ports', 'DC 48V', volts='48', watts=25)
    return {'front': front, 'rear': rear, 'views': []}


def camera():
    """DM-CAM4: a 4 MP IR dome camera for ceiling or wall, fed by PoE."""
    front = Face(140, 140)
    front.circle(70, 70, 69, '#f3f4f6', stroke=WHITE_2, sw=2)
    front.circle(70, 70, 46, '#111317', stroke='#4b5563', sw=1)
    front.circle(70, 70, 20, '#1e293b', stroke='#64748b', sw=1)
    front.circle(70, 70, 8, '#0b1220')
    front.circle(64, 64, 3, '#93c5fd')
    for k in range(8):
        a = k * math.pi / 4
        front.circle(70 + 33 * math.cos(a), 70 + 33 * math.sin(a), 2.4, '#7f1d1d')
    rear = Face(140, 140)
    rear.circle(70, 70, 69, '#d1d5db')
    rear.circle(70, 70, 50, 'none', stroke='#9ca3af', sw=1.4)
    d.rj45(rear, 64, 64, 'interfaces', 'eth0', '1000base-t', signals=['ethernet', 'power-in'],
           watts=9)
    rear.text(70, 92, 'PoE · 802.3af', size=6, fill='#1f2937', anchor='middle')
    rear.text(70, 112, 'DM-CAM4', size=8, fill='#374151', anchor='middle', bold=True)
    return {'front': front, 'rear': rear, 'views': []}


def display():
    """DM-DS55: a 55-inch professional display for 18/7 use: at the back HDMI, the network port
    it is managed and fed signage from, USB and its C8 inlet."""
    front = Face(1232, 710)
    front.rect(0, 0, 1232, 710, '#0d0f12', rx=6)
    front.rect(10, 10, 1212, 682, '#111827', rx=2)
    front.rect(10, 10, 1212, 682, '#1e3a8a', rx=2, op=0.18)
    front.text(616, 360, 'DM-DS55', size=40, fill='#334155', anchor='middle', bold=True)
    d.led(front, 1210, 700, '#ef4444', 2.2)
    rear = Face(1232, 710)
    rear.rect(0, 0, 1232, 710, '#2b2f36', rx=6)
    for x in (416, 816):
        for y in (155, 555):
            rear.circle(x, y, 6, '#0d0f12')
    rear.rect(150, 250, 220, 200, '#1f2329', rx=4)
    d.hdmi(rear, 170, 270, 'rear-ports', 'HDMI 1')
    d.hdmi(rear, 170, 290, 'rear-ports', 'HDMI 2')
    d.rj45(rear, 200, 320, 'interfaces', 'eth0', '1000base-t')
    d.usb_a(rear, 230, 350, 'rear-ports', 'USB', gen='usb2')
    rear.text(260, 440, 'INPUT', size=12, fill=SILK_DIM, anchor='middle')
    rear.rect(1000, 600, 80, 60, '#1f2329', rx=4)
    rear.rect(1028, 622, 24, 16, '#111317', rx=8)
    rear.port('power-ports', 'psu', 'iec-60320-c8', 1040, 630, volts='100-240', watts=180)
    rear.text(1040, 655, 'AC IN', size=8, fill=SILK_DIM, anchor='middle')
    rear.rect(500, 300, 232, 110, rear.use_pattern('slots'))
    return {'front': front, 'rear': rear, 'views': []}


def printer():
    """DM-MFP4: an A4 colour multifunction printer: scanner lid, touch panel and two trays;
    at the back the gigabit port, USB and its C14 inlet."""
    front = Face(420, 460)
    front.rect(0, 0, 420, 460, '#f3f4f6', rx=8, stroke=WHITE_2, sw=2)
    front.rect(10, 10, 400, 60, '#e5e7eb', rx=4)
    front.rect(300, 80, 100, 60, '#0b1220', rx=4, stroke='#1e3a8a', sw=1)
    front.text(350, 115, 'COPY · SCAN', size=8, fill='#38bdf8', anchor='middle')
    front.rect(20, 160, 380, 70, '#d1d5db', rx=4)
    front.text(210, 200, 'OUTPUT', size=10, fill='#6b7280', anchor='middle')
    for k in range(2):
        y = 250 + k * 95
        front.rect(20, y, 380, 85, '#e5e7eb', rx=4, stroke=WHITE_2, sw=1)
        front.rect(170, y + 30, 80, 14, '#9ca3af', rx=7)
        front.text(40, y + 22, 'TRAY %d · A4' % (k + 1), size=9, fill='#6b7280')
    d.usb_a(front, 270, 100, 'front-ports', 'USB (front)', gen='usb2')
    front.text(30, 120, 'DM-MFP4', size=14, fill='#374151', bold=True)
    rear = Face(420, 460)
    rear.rect(0, 0, 420, 460, '#e5e7eb', rx=8, stroke=WHITE_2, sw=2)
    rear.rect(40, 80, 160, 70, '#d1d5db', rx=4)
    d.rj45(rear, 60, 100, 'interfaces', 'eth0', '1000base-t')
    rear.rect(110, 100, 9, 8, CAGE, rx=1, stroke=CAGE_EDGE, sw=0.3)
    rear.port('rear-ports', 'USB', 'usb-b', 114.5, 104)
    rear.text(120, 140, 'LAN · USB', size=8, fill='#374151', anchor='middle')
    d.iec_inlet(rear, 360, 400, 'power-ports', 'psu', watts=1100, switch=True)
    rear.rect(240, 200, 150, 120, rear.use_pattern('slots'))
    return {'front': front, 'rear': rear, 'views': []}


# ── modules: what slides into a device's bay ─────────────────────────────────────────────────

def _psu_end(w: float, h: float, inlet: str, watts: int, volts: str, code: str):
    """A hot-swap supply out of its bay, seen from its handle end: what one holds to slide it
    in. Its inlet is its one port."""
    f = Face(w, h)
    f.rect(0, 0, w, h, STEEL_3, rx=1, stroke='#6b7280', sw=0.5)
    r = min(h / 2 - 2.5, w * 0.2)
    d.fan_grille(f, 4 + r, h / 2, r)
    gx0, gx1 = 2 * r + 7, w - 30
    if gx1 - gx0 > 4:
        f.rect(gx0, 3, gx1 - gx0, h - 6, f.use_pattern('slots'))
    f.rect(4 + r - 2, h - 2.6, 4, 1.6, TOUCH, rx=0.4)
    d.led(f, 3.2, 3.2, GREEN, 0.8)
    f.text(4 + r, 3.8, code, size=1.8, fill=SILK_DIM, anchor='middle')
    d.iec_inlet(f, w - 15, h / 2, 'power-ports', 'AC', inlet, watts=watts, volts=volts)
    return {'front': f, 'rear': None, 'views': []}


def psu800():
    return _psu_end(92, 37, 'iec-60320-c14', 800, '100-240', '800W')


def psu2000():
    return _psu_end(110, 39, 'iec-60320-c20', 2000, '200-240', '2000W')


def psu500():
    return _psu_end(61, 37.45, 'iec-60320-c14', 500, '100-240', '500W')


def psu1100():
    return _psu_end(88, 36.45, 'iec-60320-c14', 1100, '100-240', '1100W')


def psu400():
    return _psu_end(84, 36.45, 'iec-60320-c14', 400, '100-240', '400W')


def pcm():
    """DM-PCM1100: a storage array's power and cooling module —two fans and an 1100 W supply in
    one piece—, as it comes out of the array's rear."""
    f = Face(90, 168)
    f.rect(0, 0, 90, 168, STEEL_3, rx=1, stroke='#6b7280', sw=0.5)
    d.fan_grille(f, 45, 37, 30)
    d.fan_grille(f, 45, 101, 30)
    f.rect(41, 163, 8, 2.4, TOUCH, rx=0.5)
    d.led(f, 6, 5, GREEN, 0.9)
    f.text(45, 6, 'PCM', size=2.2, fill=SILK_DIM, anchor='middle')
    d.iec_inlet(f, 45, 147, 'power-ports', 'AC', watts=1100, switch=True)
    return {'front': f, 'rear': None, 'views': []}


def fansrv():
    """DM-FAN60: a server's hot-swap fan: its frame, its rotor and its pull tab."""
    f = Face(64, 40)
    f.rect(0, 0, 64, 40, STEEL_3, rx=1, stroke='#6b7280', sw=0.4)
    d.fan_grille(f, 32, 20, 18)
    f.rect(28, 0.6, 8, 2, TOUCH, rx=0.5)
    d.led(f, 4, 4, GREEN, 0.7)
    return {'front': f, 'rear': None, 'views': []}


def fantray():
    """DM-FT40: the hot-swap fan tray of the network gear, seen from its handle."""
    f = Face(48, 36.45)
    f.rect(0, 0, 48, 36.45, STEEL_3, rx=1, stroke='#6b7280', sw=0.5)
    d.fan_grille(f, 24, 18.2, 15.8)
    f.rect(21.5, 34, 5, 1.6, TOUCH, rx=0.4)
    d.led(f, 2.8, 2.8, GREEN, 0.7)
    return {'front': f, 'rear': None, 'views': []}


def ocp25():
    """DM-OCP25-2: an OCP 3.0 network card with two 25 GbE SFP28 cages."""
    f = Face(76, 15)
    f.rect(0, 0, 76, 15, '#9aa3ad', rx=0.5, stroke='#6b7280', sw=0.4)
    d.screw(f, 3, 7.5, 1.3)
    for k in range(2):
        d.sfp(f, 10 + k * 18, 2.75, 'interfaces', 'sfp%d' % k, '25gbase-x-sfp28')
    f.text(64, 9, 'OCP 25G', size=2, fill='#374151', anchor='middle')
    d.led(f, 72, 4, GREEN, 0.6)
    return {'front': f, 'rear': None, 'views': []}


def ctrl():
    """DM-S4-CTRL: a controller of the storage array out of its slot: four 10 GbE SFP+ host
    ports, management, console, two SAS expansion ports and its USB."""
    f = Face(282.6, 82)
    f.rect(0, 0, 282.6, 82, STEEL_3, rx=1, stroke='#6b7280', sw=0.5)
    d.handle(f, 3, 30, 3.4, 22)
    d.handle(f, 276, 30, 3.4, 22)
    f.text(12, 8, 'DM-S4-CTRL', size=2.6, fill=SILK, bold=True)
    d.led(f, 250, 7, GREEN, 0.9, 'OK')
    d.led(f, 262, 7, AMBER, 0.9, '!')
    for j in range(4):
        d.sfp(f, 14 + j * 18, 24, 'interfaces', 'host%d' % j)
        f.text(21 + j * 18, 39, str(j), size=2, fill=SILK_DIM, anchor='middle')
    f.text(48, 20, 'HOST 10GbE', size=2, fill=SILK_DIM, anchor='middle')
    d.rj45(f, 100, 24, 'interfaces', 'mgmt', '1000base-t')
    f.text(106, 20, 'MGMT', size=2, fill=SILK_DIM, anchor='middle')
    d.console_rj45(f, 118, 24, 'console-ports', 'console', label='')
    for j in range(2):
        ex = 140 + j * 22
        f.rect(ex, 24, 18, 9.5, CAGE, rx=0.6, stroke=CAGE_EDGE, sw=0.3)
        f.rect(ex + 1.5, 26, 15, 5.5, HOLE, rx=0.5)
        # The module's only face is its front: what is a rear port on the array is a front
        # port of the controller out of it.
        f.port('front-ports', 'exp-%d' % (j + 1), 'other', ex + 9, 28.75)
    f.text(160, 20, 'SAS EXP', size=2, fill=SILK_DIM, anchor='middle')
    d.usb_a(f, 192, 26, 'front-ports', 'USB', gen='usb2')
    d.perf(f, 14, 46, 254, 30)
    return {'front': f, 'rear': None, 'views': []}


def _optic(code: str, label: str, band: str):
    """An SFP+ optic seen from above: the bail latch, its label and, at the front, the duplex LC
    socket the fibre goes into —its one port—."""
    f = Face(14, 56.5)
    f.rect(0, 0, 14, 56.5, '#c7ced8', rx=0.8, stroke=CAGE_EDGE, sw=0.3)
    f.rect(1, 1, 12, 9, '#111317', rx=0.6)
    for x in (3.2, 10.8):
        f.circle(x, 5.5, 1.4, '#e5e7eb')
    f.port('front-ports', 'LC', 'lc-upc', 7, 5.5)
    f.rect(0.6, 11, 12.8, 4, band, rx=0.6)
    f.rect(1.6, 18, 10.8, 30, '#f8fafc', rx=0.6)
    f.text(7, 33, code, size=1.6, fill='#1f2937', anchor='middle', rotate=90)
    f.text(7, 46, label, size=1.4, fill='#4b5563', anchor='middle')
    f.rect(3, 50, 8, 5, GOLD, rx=0.4)
    return {'front': f, 'rear': None, 'views': []}


def sfp10sr():
    """DM-SFP10-SR: 10GBASE-SR, 850 nm over multimode, 300 m on OM3 and 400 m on OM4. The
    bail is beige, as every short-reach optic's."""
    return _optic('DM-SFP10-SR', '850nm', '#d6c7a1')


def sfp10lr():
    """DM-SFP10-LR: 10GBASE-LR, 1310 nm over single-mode, 10 km. Its bail is blue."""
    return _optic('DM-SFP10-LR', '1310nm', '#2563eb')


# ── components: what goes inside ─────────────────────────────────────────────────────────────

def _dimm(code: str, w: float, h: float, chips: int, rdimm: bool, label: str):
    """A memory module from the front: its chips, the register in the middle of an RDIMM, its
    label, the gold fingers and the key notch."""
    f = Face(w, h)
    f.rect(0, 0, w, h - 3.6, PCB, rx=0.8, stroke=PCB_EDGE, sw=0.4)
    for k in range(chips):
        cw = (w - 8 - (6 if rdimm else 0)) / chips
        x = 3 + k * cw + (6 if rdimm and k >= chips // 2 else 0)
        f.rect(x, 4, cw - 1.2, h * 0.36, '#111317', rx=0.3)
    if rdimm:
        f.rect(w / 2 - 4, 6, 8, 6, '#1f2329', rx=0.3, stroke='#4b5563', sw=0.2)
    f.rect(w * 0.2, h * 0.52, w * 0.6, h * 0.22, '#f8fafc', rx=0.4)
    f.text(w / 2, h * 0.52 + h * 0.15, label, size=min(2.6, h * 0.1), fill='#1f2937',
           anchor='middle')
    f.rect(0, h - 3.6, w, 3.6, GOLD)
    f.rect(w * 0.47, h - 3.6, 1.6, 3.6, '#ffffff')
    f.text(w - 2, 2.4 + h * 0.36 + 3, code, size=1.6, fill=SILK_DIM, anchor='end')
    return {'front': f, 'rear': None, 'views': []}


def rdimm32():
    return _dimm('DM-RD5-32', 133.35, 31.25, 10, True, '32GB 2Rx8 DDR5-4800 RDIMM')


def rdimm64():
    return _dimm('DM-RD5-64', 133.35, 31.25, 10, True, '64GB 2Rx4 DDR5-5600 RDIMM')


def sodimm16():
    return _dimm('DM-SD5-16', 69.6, 30, 4, False, '16GB 1Rx8 DDR5-5600')


def cpu32():
    """DM-X32: a 32-core server processor seen from above: its integrated heat spreader, the
    triangle that says which way it goes in, its marking."""
    f = Face(77.5, 56.5)
    f.rect(0, 0, 77.5, 56.5, '#14532d', rx=1, stroke=PCB_EDGE, sw=0.4)
    f.rect(6, 5, 65.5, 46.5, '#c7ced8', rx=1.5, stroke='#9ca3af', sw=0.4)
    f.poly([(2, 2), (6, 2), (2, 6)], GOLD)
    f.text(38.75, 24, 'DM-X32', size=5, fill='#1f2937', anchor='middle', bold=True)
    f.text(38.75, 31, '32C · 2.4 GHz · 270 W', size=2.8, fill='#374151', anchor='middle')
    f.text(38.75, 37, 'Q3K2  ES', size=2.4, fill='#6b7280', anchor='middle')
    return {'front': f, 'rear': None, 'views': []}


def _drive_top(w: float, h: float, code: str, lines: tuple, connector: str):
    f = Face(w, h)
    f.rect(0, 0, w, h, '#9ca3af', rx=1.5, stroke='#6b7280', sw=0.5)
    f.rect(4, 4, w - 8, h - 8, '#b8c0cb', rx=1)
    f.rect(8, 10, w - 16, h * 0.42, '#f8fafc', rx=0.8)
    f.text(w / 2, 18, code, size=min(5, w / 14), fill='#1f2937', anchor='middle', bold=True)
    for k, s in enumerate(lines):
        f.text(w / 2, 26 + k * 6, s, size=min(3.2, w / 24), fill='#374151', anchor='middle')
    f.rect(w / 2 - w * 0.3, h - 6, w * 0.6, 5, '#111317', rx=0.5)
    f.text(w / 2, h - 8, connector, size=2.2, fill='#1f2937', anchor='middle')
    for x, y in ((6, h * 0.6), (w - 6, h * 0.6), (6, h - 14), (w - 6, h - 14)):
        d.screw(f, x, y, 1.4)
    return f


def nvme192():
    """DM-NV3-1T9: a 2.5-inch 15 mm U.2 NVMe drive, 1.92 TB, seen from its label side."""
    f = _drive_top(69.85, 100.45, 'DM-NV3-1T9', ('1.92 TB · NVMe U.2', 'PCIe 4.0 x4', '1 DWPD'),
                   'SFF-8639')
    return {'front': f, 'rear': None, 'views': []}


def ssd480():
    """DM-SA3-480: a 2.5-inch 7 mm SATA SSD, 480 GB: the firewall's log disk."""
    f = _drive_top(69.85, 100.45, 'DM-SA3-480', ('480 GB · SATA 6 Gb/s', '2.5" 7 mm'),
                   'SATA')
    return {'front': f, 'rear': None, 'views': []}


def hdd8t():
    """DM-HD7-8T: a 3.5-inch 8 TB 7200 rpm SAS disk, from its label side."""
    f = _drive_top(101.6, 147, 'DM-HD7-8T', ('8 TB · SAS 12 Gb/s', '7200 RPM · 256 MB',
                                              '512e · SED'), 'SAS')
    return {'front': f, 'rear': None, 'views': []}


def m2boot():
    """DM-M2-480: an M.2 2280 NVMe boot drive, 480 GB."""
    f = Face(22, 80)
    f.rect(0, 0, 22, 80, PCB, rx=0.8, stroke=PCB_EDGE, sw=0.3)
    f.rect(0, 76, 22, 4, GOLD)
    f.rect(16.2, 76, 1.6, 4, '#ffffff')
    for k in range(2):
        f.rect(3, 8 + k * 24, 16, 18, '#111317', rx=0.4)
    f.rect(3, 56, 16, 14, '#1f2329', rx=0.4)
    f.circle(11, 2.6, 1.8, 'none', stroke=GOLD, sw=0.5)
    f.text(11, 40, 'DM-M2-480', size=1.8, fill=SILK, anchor='middle', rotate=90)
    return {'front': f, 'rear': None, 'views': []}


def gpu24():
    """DM-L24: a single-slot, low-profile inference GPU with 24 GB, passively cooled by the
    server's fans, on PCIe x16."""
    f = Face(168, 68.9)
    f.rect(0, 0, 168, 64, '#1f2329', rx=1.5, stroke='#4b5563', sw=0.5)
    f.rect(4, 4, 150, 56, f.use_pattern('fins'))
    f.rect(40, 22, 70, 20, '#111317', rx=1)
    f.text(75, 35, 'DM-L24 · 24 GB', size=4, fill=SILK, anchor='middle', bold=True)
    f.rect(158, 0, 10, 64, '#9aa3ad')
    f.rect(20, 64, 100, 4.9, GOLD)
    f.rect(36, 64, 1.6, 4.9, '#ffffff')
    return {'front': f, 'rear': None, 'views': []}


def bbu():
    """DM-SCAP: the supercapacitor pack that keeps a storage controller's cache while it writes
    it to flash after a power cut."""
    f = Face(90, 40)
    f.rect(0, 0, 90, 40, '#1e3a8a', rx=2, stroke='#3b82f6', sw=0.5)
    for k in range(3):
        f.rect(6 + k * 27, 6, 24, 22, '#1e40af', rx=4, stroke='#60a5fa', sw=0.4)
    f.text(45, 36, 'DM-SCAP · 9.6 V', size=3.2, fill=SILK, anchor='middle')
    return {'front': f, 'rear': None, 'views': []}


#: Who draws each one.
DRAWERS = {
    'rack612': rack612, 'rack810': rack810, 'rack610': rack610, 'rack608': rack608,
    'wall12': wall12,
    'pdu0u16': pdu0u16, 'pdu0u32': pdu0u32, 'pdu0u3p': pdu0u3p, 'pdu1u': pdu1u,
    'ups1k5': ups1k5, 'ups3k': ups3k, 'ups6k': ups6k,
    'blank': blank, 'cablemgr': cablemgr, 'shelf': shelf,
    'pc': pc, 'phone': phone, 'ap': ap, 'camera': camera, 'display': display,
    'printer': printer,
    'psu800': psu800, 'psu2000': psu2000, 'psu500': psu500, 'psu1100': psu1100,
    'psu400': psu400, 'pcm': pcm, 'fansrv': fansrv, 'fantray': fantray, 'ocp25': ocp25,
    'ctrl': ctrl, 'sfp10sr': sfp10sr, 'sfp10lr': sfp10lr,
    'rdimm32': rdimm32, 'rdimm64': rdimm64, 'sodimm16': sodimm16, 'cpu32': cpu32,
    'nvme192': nvme192, 'ssd480': ssd480, 'hdd8t': hdd8t, 'm2boot': m2boot, 'gpu24': gpu24,
    'bbu': bbu,
}
