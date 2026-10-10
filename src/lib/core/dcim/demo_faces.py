#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo's own catalogue models: their names, their faces and where each port is.

The demo cannot lean on whatever catalogue an installation happens to have imported, so it
brings its own models — maker «Demo». Their front and rear pictures are SVG files in
``data/demo/faces/`` (``<key>.front.svg``, ``<key>.rear.svg``), in the repository so they can be
looked at, edited and versioned; each is drawn in millimetres, 19 inches wide (177 mm for the mini
PC) by its U, so the same picture serves the elevation and the 3D rack.

Where each port is drawn is written here, in those same millimetres: **a file edited so that a
socket moves has to be edited here too**, or the cable will leave from where the socket was.
``tests/integration/test_dcim_demo.py`` checks that every file is there and has the size its
model says.
"""

from __future__ import annotations

import io
import os

#: Where the pictures are.
FACES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'demo', 'faces')
_WMM = 482.6                  # 19 inches
_UMM = 44.45
#: The mini PC is not 19 inches wide.
WIDTH_MM = {'mini': 177.0}

# ── Where the ports are ───────────────────────────────────────────────────────────────────────
#
# Every model brings its ports by name, already placed, as `(family, name, type, face, x mm,
# y mm)` on its own picture. The names are the ones the demo's cables use, so in the rack a cable
# leaves its own port.

def _rows48(n: int, fam: str = 'interfaces', fmt: str = 'Gi1/0/%d', typ: str = '1000base-t') -> list:
    """A switch's RJ45 block: odd ports on top, even below, in groups of six."""
    out = []
    for k in range(n // 2):
        x = 40 + k * 13 + (k // 6) * 3 + 5.5
        out.append((fam, fmt % (2 * k + 1), typ, 'front', x, 11.5))
        out.append((fam, fmt % (2 * k + 2), typ, 'front', x, 28.5))
    return out


def _uplinks(fmt: str = 'Te1/1/%d') -> list:
    return [('interfaces', fmt % (1 + j + 2 * r), '10gbase-x-sfpp', 'front', 410 + j * 16 + 6.5,
             7 + r * 17 + 4.25) for r in range(2) for j in range(2)]


def _psus(u: float, xs=(20, 392), w: float = 70) -> list:
    """The inlet of each power supply on the rear: the dark socket at its right."""
    h = u * _UMM
    return [('power-ports', 'PSU%d' % (i + 1), 'iec-60320-c14', 'rear', x + w - 13, h / 2)
            for i, x in enumerate(xs)]


def _server_ports(u: int) -> list:
    h = u * _UMM
    return ([('interfaces', 'eth%d' % k, '10gbase-t', 'rear', 150 + k * 14 + 5.5, h / 2 + 0.5)
             for k in range(4)]
            + [('interfaces', 'sfp%d' % k, '25gbase-x-sfp28', 'rear', 220 + k * 16 + 6.5, h / 2 + 0.25)
               for k in range(2)]
            + _psus(u, (20, 392), 70))


def _storage_ports() -> list:
    h = 4 * _UMM
    out = []
    for k, y in enumerate((8, h / 2 + 4)):
        out += [('interfaces', 'ctrl%s-%d' % ('AB'[k], j), '10gbase-x-sfpp', 'rear',
                 110 + j * 18 + 6.5, y + 10.25) for j in range(4)]
    for i, (x, y) in enumerate(((14, 10), (14, h / 2 + 6), (392, 10), (392, h / 2 + 6))):
        out.append(('power-ports', 'PSU%d' % (i + 1), 'iec-60320-c14', 'rear', x + 76 - 13,
                    y + (h / 2 - 16) / 2))
    return out


def _core_ports() -> list:
    out = [('interfaces', 'Te1/0/%d' % (k + 1 + r * 24), '10gbase-x-sfpp', 'front',
            30 + k * 17.5 + 6.5, 8 + r * 40 + 4.25) for r in range(2) for k in range(24)]
    out += [('interfaces', 'Gi1/0/%d' % (k + 1), '1000base-t', 'front', 30 + k * 14 + 5.5, 30.5)
            for k in range(4)]
    return out + _psus(2)


def _router_ports(names: str = 'Gi0/%d') -> list:
    return ([('interfaces', names % k, '1000base-t', 'front', 140 + k * 14 + 5.5, 20.5)
             for k in range(8)]
            + [('interfaces', 'Te0/0/%d' % k, '10gbase-x-sfpp', 'front', 270 + k * 16 + 6.5, 20.25)
               for k in range(4)] + _psus(1))


def _firewall_ports() -> list:
    return ([('interfaces', 'port%d' % (k + 1), '1000base-t', 'front', 160 + k * 14 + 5.5, 20.5)
             for k in range(10)] + _psus(1))


def _patch_ports() -> list:
    return [('front-ports', str(k + 1), '8p8c', 'front', 40 + k * 17 + (k // 6) * 4 + 5.5, 20.5)
            for k in range(24)]


def _fiber_ports() -> list:
    return [('front-ports', str(k + 1), 'lc', 'front', 40 + k * 17 + 6, 21.5) for k in range(24)]


def _console_ports() -> list:
    return ([('console-server-ports', 'Port%d' % (k + 1), 'rj-45', 'front', 60 + k * 14 + 5.5, 20.5)
             for k in range(16)] + _psus(1))


def _mini_ports() -> list:
    return [('interfaces', 'eth0', '1000base-t', 'rear', 25.5, 22.5),
            ('power-ports', 'DC-IN', 'dc-terminal', 'rear', 150, 22)]


def ports_of(key: str) -> tuple:
    """``(ports, port_list, port_map)`` of a demo model, in the catalogue's own shapes."""
    u = MODELS[key][2]
    w = WIDTH_MM.get(key, _WMM)
    filas = PORTS.get(key, lambda: [])()
    cuentas: dict = {}
    lista: dict = {}
    sitio: dict = {}
    for fam, name, typ, face, x, y in filas:
        cuentas.setdefault(fam, {})
        cuentas[fam][typ] = cuentas[fam].get(typ, 0) + 1
        lista.setdefault(fam, []).append({'name': name, 'type': typ})
        sitio['%s|%s' % (fam, name)] = {'f': face, 'x': round(x / w, 4),
                                        'y': round(y / (u * _UMM), 4)}
    return cuentas, lista, sitio


#: The ports of each model, drawn where `MODELS` draws them.
PORTS = {
    'server': lambda: _server_ports(2), 'gpu': lambda: _server_ports(2),
    'node': lambda: _server_ports(1), 'storage': _storage_ports,
    'tor': lambda: _rows48(48) + _uplinks() + _psus(1),
    'access': lambda: _rows48(24) + _uplinks() + _psus(1),
    'core': _core_ports, 'router': _router_ports, 'cpe': _router_ports,
    'firewall': _firewall_ports, 'patch': _patch_ports, 'fiber': _fiber_ports,
    'console': _console_ports, 'mini': _mini_ports,
}


#: The models: key → (model, role, U, full depth). Their pictures are ``FACES_DIR/<key>.<face>.svg``.
MODELS = {
    'server':   ('DM-R2 Server 2U', 'server', 2, True),
    'gpu':      ('DM-G2 GPU Server 2U', 'server', 2, True),
    'node':     ('DM-N1 Half-width Node', 'server', 1, True),
    'storage':  ('DM-S4 Storage Array', 'storage', 4, True),
    'tor':      ('DM-S48 Switch 48p', 'switch', 1, False),
    'access':   ('DM-S24 Switch 24p', 'switch', 1, False),
    'core':     ('DM-C32 Core Switch', 'switch', 2, False),
    'router':   ('DM-RT1 Router', 'router', 1, False),
    'cpe':      ('DM-CPE Carrier Router', 'router', 1, False),
    'firewall': ('DM-FW1 Firewall', 'firewall', 1, False),
    'patch':    ('DM-PP24 Patch Panel', 'patch_panel', 1, False),
    'fiber':    ('DM-FP24 Fiber Panel', 'fiber_panel', 1, False),
    'console':  ('DM-CS16 Console Server', 'console', 1, False),
    'kvm':      ('DM-KVM8 KVM', 'kvm', 1, False),
    'mini':     ('DM-MINI Mini PC', 'server', 1, False),
}


def face(key: str, side: str) -> str:
    """The SVG of one face of a model, or ``''`` if it has none (a patch panel has no rear)."""
    path = os.path.join(FACES_DIR, '%s.%s.svg' % (key, side))
    if not os.path.isfile(path):
        return ''
    with io.open(path, encoding='utf-8') as fh:
        return fh.read()
