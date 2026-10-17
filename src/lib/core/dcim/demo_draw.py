#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Draws the demo's own catalogue models: every face, and where each port and bay is on it.

One function per model draws its front, its rear and the views of its inside, in millimetres
—19 inches wide by its U, or the width of a half-width or a desktop unit—, and every socket and
bay it draws is registered **by the same call that draws it**. That is the point of drawing them
in code: a port cannot be drawn in one place and placed in another, because both come out of the
same line. The pictures are written to ``data/demo/faces/`` (``python -m
lib.core.dcim.demo_draw``) so they can be looked at and versioned; a test checks the files are
what this module draws.

The models imitate real classes of equipment —a 2U two-socket server with 24 SFF bays, a 48-port
PoE+ access switch with four SFP+ uplinks, a 1U LCD console drawer with an 8-port KVM— without
naming any vendor: the silkscreen says what a real one says (``MGMT``, ``CONSOLE``, ``PSU 1``),
and the model codes are the demo's own.
"""

from __future__ import annotations

import hashlib

#: 19 inches, one rack unit, and the width of a rack ear.
W19 = 482.6
U = 44.45
EAR = 16.0

# The palette: painted steel, the dark plastic of the sockets, the silkscreen.
STEEL = '#2b2f36'
STEEL_2 = '#353a43'
STEEL_3 = '#3f4550'
EDGE = '#4b5160'
HOLE = '#0d0f12'
CAGE = '#b9c1cc'
CAGE_EDGE = '#7b8494'
SILK = '#d6dae2'
SILK_DIM = '#8f98a8'
GOLD = '#c9a227'
GREEN = '#22c55e'
AMBER = '#f59e0b'
BLUE = '#38bdf8'
USB3 = '#2563eb'
VGA_BLUE = '#1e40af'
SERIAL = '#0f766e'
TOUCH = '#f97316'          # the terracotta of a hot-swap latch
PCB = '#0f3d2e'
PCB_EDGE = '#1f6b4f'


def _n(v) -> str:
    """A number as SVG wants it: short, and never ``-0``."""
    s = ('%.2f' % float(v)).rstrip('0').rstrip('.')
    return '0' if s in ('', '-0') else s


def view_id(key: str, view: str) -> str:
    """The id of a view: eight hex characters, the same every time the demo is installed."""
    return hashlib.md5(('demo:%s:%s' % (key, view)).encode('utf-8')).hexdigest()[:8]


class Face:
    """One picture: what is drawn on it, and the ports and bays it holds, in its millimetres."""

    def __init__(self, w: float, h: float):
        self.w, self.h = float(w), float(h)
        self._el: list = []
        self._defs: dict = {}
        #: ``(family, name, type, x, y, extra)``, in the order they were drawn.
        self.ports: list = []

    # ── writing ──

    def el(self, tag: str, **attrs) -> None:
        body = attrs.pop('_text', None)
        parts = []
        for k, v in attrs.items():
            if v is None:
                continue
            k = k.rstrip('_').replace('_', '-')
            parts.append('%s="%s"' % (k, _n(v) if isinstance(v, (int, float)) else v))
        if body is None:
            self._el.append('<%s %s/>' % (tag, ' '.join(parts)))
        else:
            self._el.append('<%s %s>%s</%s>' % (tag, ' '.join(parts), body, tag))

    def raw(self, text: str) -> None:
        self._el.append(text)

    def rect(self, x, y, w, h, fill, rx=0, stroke=None, sw=0.5, op=None) -> None:
        self.el('rect', x=x, y=y, width=w, height=h, rx=rx or None, fill=fill, stroke=stroke,
                stroke_width=sw if stroke else None, opacity=op)

    def circle(self, cx, cy, r, fill, stroke=None, sw=0.5) -> None:
        self.el('circle', cx=cx, cy=cy, r=r, fill=fill, stroke=stroke,
                stroke_width=sw if stroke else None)

    def line(self, x1, y1, x2, y2, stroke, sw=0.5) -> None:
        self.el('line', x1=x1, y1=y1, x2=x2, y2=y2, stroke=stroke, stroke_width=sw)

    def poly(self, pts, fill, stroke=None, sw=0.5) -> None:
        self.el('polygon', points=' '.join('%s,%s' % (_n(a), _n(b)) for a, b in pts), fill=fill,
                stroke=stroke, stroke_width=sw if stroke else None)

    def text(self, x, y, s, size=2.6, fill=SILK, anchor=None, bold=False, rotate=None) -> None:
        self.el('text', x=x, y=y, font_family='sans-serif', font_size=size, fill=fill,
                text_anchor=anchor, font_weight='bold' if bold else None,
                transform=('rotate(%s %s %s)' % (_n(rotate), _n(x), _n(y))) if rotate else None,
                _text=s.replace('&', '&amp;').replace('<', '&lt;'))

    def use_pattern(self, pid: str) -> str:
        """A fill pattern, declared once per picture: the perforation of a steel front, the
        grille of a fan. One `<pattern>` and not a thousand circles keeps the file small."""
        if pid not in self._defs:
            self._defs[pid] = _PATTERNS[pid]
        return 'url(#%s)' % pid

    def port(self, fam: str, name: str, typ: str, x: float, y: float, **extra) -> None:
        self.ports.append((fam, name, typ, float(x), float(y),
                           {k: v for k, v in extra.items() if v not in (None, '', [])}))

    def svg(self) -> str:
        defs = ('<defs>%s</defs>' % ''.join(self._defs[k] for k in sorted(self._defs))
                if self._defs else '')
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
                'viewBox="0 0 %s %s">%s%s</svg>\n'
                % (round(self.w * 4), round(self.h * 4), _n(self.w), _n(self.h), defs,
                   ''.join(self._el)))


_PATTERNS = {
    'perf': ('<pattern id="perf" width="2.4" height="2.08" patternUnits="userSpaceOnUse">'
             '<circle cx="0.6" cy="0.52" r="0.48" fill="#121418"/>'
             '<circle cx="1.8" cy="1.56" r="0.48" fill="#121418"/></pattern>'),
    'slots': ('<pattern id="slots" width="2.2" height="6" patternUnits="userSpaceOnUse">'
              '<rect x="0.5" y="0.6" width="1.1" height="4.8" rx="0.5" fill="#121418"/></pattern>'),
    'fins': ('<pattern id="fins" width="1.6" height="4" patternUnits="userSpaceOnUse">'
             '<rect x="0" y="0" width="0.7" height="4" fill="#c7ced8"/></pattern>'),
    'keys': ('<pattern id="keys" width="9.5" height="9.5" patternUnits="userSpaceOnUse">'
             '<rect x="0.6" y="0.6" width="8.3" height="8.3" rx="1" fill="#2a2e35" '
             'stroke="#454b56" stroke-width="0.3"/></pattern>'),
}


# ── the parts every face is made of ──────────────────────────────────────────────────────────

def chassis(f: Face, fill: str = STEEL, ears: int = 0) -> None:
    """The box. With *ears* (its U), the two rack ears and their screws."""
    f.rect(0, 0, f.w, f.h, fill, rx=1.5)
    f.rect(0.6, 0.6, f.w - 1.2, f.h - 1.2, 'none', rx=1.2, stroke=EDGE, sw=0.8)
    if ears:
        for x in (0, f.w - EAR):
            f.rect(x, 0, EAR, f.h, STEEL_3, rx=1)
            for i in range(ears):
                cy = i * U + U / 2
                f.rect(x + EAR / 2 - 3.4, cy - 1.7, 6.8, 3.4, HOLE, rx=1.7)
                f.circle(x + EAR / 2, cy, 2.3, '#9ca3af', stroke='#4b5563', sw=0.3)
                f.line(x + EAR / 2 - 1.3, cy, x + EAR / 2 + 1.3, cy, '#4b5563', 0.5)


def perf(f: Face, x, y, w, h, rx=1.0) -> None:
    """A perforated area: where the air goes in or out."""
    f.rect(x, y, w, h, STEEL_2, rx=rx)
    f.rect(x, y, w, h, f.use_pattern('perf'), rx=rx)


def led(f: Face, x, y, color=GREEN, r=0.9, label='', size=1.8) -> None:
    f.circle(x, y, r + 0.45, '#111317')
    f.circle(x, y, r, color)
    if label:
        f.text(x + r + 1.2, y + size / 3, label, size=size, fill=SILK_DIM)


def button(f: Face, x, y, r=2.6, ring=GREEN) -> None:
    """A round push button with its lit ring: power, or the identify button."""
    f.circle(x, y, r + 0.6, '#111317')
    f.circle(x, y, r, '#5b6270', stroke=ring, sw=0.6)
    f.circle(x, y, r * 0.45, 'none', stroke=SILK, sw=0.35)
    f.line(x, y - r * 0.6, x, y - r * 0.15, SILK, 0.35)


def screw(f: Face, x, y, r=1.6) -> None:
    f.circle(x, y, r, '#9ca3af', stroke='#4b5563', sw=0.3)
    f.line(x - r * 0.6, y, x + r * 0.6, y, '#4b5563', 0.4)


def handle(f: Face, x, y, w, h) -> None:
    """A pull handle: the bar and its two posts."""
    f.rect(x, y, w, h, '#5b6270', rx=min(w, h) / 2, stroke='#7b8494', sw=0.4)


def ground(f: Face, x, y) -> None:
    """The earthing point: two studs and the symbol."""
    screw(f, x, y, 1.4)
    screw(f, x + 5, y, 1.4)
    for i, w in enumerate((3.2, 2.2, 1.2)):
        yy = y + 3.4 + i * 0.8
        f.line(x + 2.5 - w / 2, yy, x + 2.5 + w / 2, yy, SILK_DIM, 0.3)
    f.line(x + 2.5, y + 2.2, x + 2.5, y + 3.4, SILK_DIM, 0.3)


# ── connectors: each one drawn where it is and registered at its centre ──────────────────────

def rj45(f: Face, x, y, fam, name, typ='1000base-t', down=False, leds=True, shell=CAGE, **kw):
    """An RJ45 jack, 12 × 10 mm from its top-left corner; the latch up, or *down* for the
    bottom row of a switch, which is how real ones are stacked."""
    f.rect(x, y, 12, 10, shell, rx=0.6, stroke=CAGE_EDGE, sw=0.3)
    f.rect(x + 1.2, y + 1.2, 9.6, 7.6, HOLE, rx=0.4)
    f.rect(x + 4.2, (y + 7.9) if down else (y + 0.4), 3.6, 1.7, HOLE)
    cy = (y + 2.3) if down else (y + 6.4)
    for i in range(8):
        f.line(x + 2.25 + i * 1.07, cy, x + 2.25 + i * 1.07, cy + 1.3, GOLD, 0.35)
    if leds:
        ly = (y + 7.3) if down else (y + 1.3)
        f.rect(x + 0.15, ly, 0.9, 1.4, GREEN)
        f.rect(x + 10.95, ly, 0.9, 1.4, AMBER)
    f.port(fam, name, typ, x + 6, y + 5, **kw)


def console_rj45(f: Face, x, y, fam, name, label='CONSOLE', **kw):
    """The serial console: an RJ45 in a blue-rimmed shell, which is how most equipment says
    "this one is not Ethernet"."""
    rj45(f, x, y, fam, name, 'rj-45', leds=False, shell='#7aa7d8', **kw)
    if label:
        f.text(x + 6, y - 1, label, size=1.9, fill=SILK_DIM, anchor='middle')


def sfp(f: Face, x, y, fam, name, typ='10gbase-x-sfpp', down=False, w=14.0, h=9.5, **kw):
    """An SFP/SFP+/SFP28 cage, from its top-left corner, with its link LED."""
    f.rect(x, y, w, h, CAGE, rx=0.4, stroke=CAGE_EDGE, sw=0.3)
    f.rect(x + 1, y + 1.3, w - 2, h - 2.6, '#111317', rx=0.3)
    f.rect(x + w / 2 - 2, (y + h - 1.1) if down else (y + 0.3), 4, 0.8, CAGE_EDGE)
    f.poly([(x + w - 2.2, (y - 0.9) if not down else (y + h + 0.9)),
            (x + w - 0.6, (y - 0.9) if not down else (y + h + 0.9)),
            (x + w - 1.4, (y - 0.1) if not down else (y + h + 0.1))], GREEN)
    f.port(fam, name, typ, x + w / 2, y + h / 2, **kw)


def qsfp(f: Face, x, y, fam, name, typ='100gbase-x-qsfp28', down=False, **kw):
    sfp(f, x, y, fam, name, typ, down=down, w=19.5, h=10.5, **kw)


def usb_a(f: Face, x, y, fam, name, gen='usb3.2g1', vertical=False, **kw):
    """A USB-A socket, 13 × 5.8 mm (or standing up); the tongue blue when it is USB 3."""
    w, h = (5.8, 13.0) if vertical else (13.0, 5.8)
    f.rect(x, y, w, h, CAGE, rx=0.4, stroke=CAGE_EDGE, sw=0.3)
    f.rect(x + 0.7, y + 0.7, w - 1.4, h - 1.4, HOLE, rx=0.3)
    lengua = USB3 if gen.startswith('usb3') else '#1f2329'
    if vertical:
        f.rect(x + 0.7, y + 1.6, 2.1, h - 3.2, lengua)
    else:
        f.rect(x + 1.6, y + 0.7, w - 3.2, 2.1, lengua)
    f.port(fam, name, 'usb-a', x + w / 2, y + h / 2, gen=gen, signals=['data'], **kw)


def usb_c(f: Face, x, y, fam, name, gen='usb3.2g2', **kw):
    f.rect(x, y, 8.9, 3.3, CAGE, rx=1.6, stroke=CAGE_EDGE, sw=0.3)
    f.rect(x + 0.6, y + 0.6, 7.7, 2.1, HOLE, rx=1.0)
    f.rect(x + 1.8, y + 1.35, 5.3, 0.6, '#3b4250')
    f.port(fam, name, 'usb-c', x + 4.45, y + 1.65, gen=gen, signals=['data', 'dp', 'power-out'],
           **kw)


def _dsub(f: Face, x, y, w, color, rows, vertical):
    """A D-sub shell —VGA or serial— with its two screw posts. Drawn lying down and turned
    when it stands in a rack ear."""
    h = 8.0
    g = []
    g.append('<polygon points="%s" fill="%s" stroke="%s" stroke-width="0.3"/>' % (
        ' '.join('%s,%s' % (_n(a), _n(b)) for a, b in (
            (x, y), (x + w, y), (x + w - 1.6, y + h), (x + 1.6, y + h))), CAGE, CAGE_EDGE))
    g.append('<polygon points="%s" fill="%s"/>' % (
        ' '.join('%s,%s' % (_n(a), _n(b)) for a, b in (
            (x + 1, y + 0.9), (x + w - 1, y + 0.9), (x + w - 2.3, y + h - 0.9),
            (x + 2.3, y + h - 0.9))), color))
    for r, (n, off) in enumerate(rows):
        for i in range(n):
            px = x + w / 2 + (i - (n - 1) / 2) * (w - 6) / max(1, 4) + off
            py = y + 2.2 + r * (h - 4.4) / max(1, len(rows) - 1)
            g.append('<circle cx="%s" cy="%s" r="0.38" fill="#0b0c0f"/>' % (_n(px), _n(py)))
    for sx in (x - 3.2, x + w + 3.2):
        g.append('<circle cx="%s" cy="%s" r="1.5" fill="#9ca3af" stroke="#4b5563" '
                 'stroke-width="0.3"/><circle cx="%s" cy="%s" r="0.6" fill="#4b5563"/>'
                 % (_n(sx), _n(y + h / 2), _n(sx), _n(y + h / 2)))
    cx, cy = x + w / 2, y + h / 2
    if vertical:
        f.raw('<g transform="rotate(90 %s %s)">%s</g>' % (_n(cx), _n(cy), ''.join(g)))
    else:
        f.raw('<g>%s</g>' % ''.join(g))
    return cx, cy


def vga(f: Face, cx, cy, fam, name, vertical=False, **kw):
    """A VGA (DE-15) socket centred on *cx, cy*: three rows of five, in PC99 blue."""
    _dsub(f, cx - 8.4, cy - 4, 16.8, VGA_BLUE, ((5, 0), (5, 0.6), (5, 0)), vertical)
    f.port(fam, name, 'vga', cx, cy, **kw)


def de9(f: Face, cx, cy, fam, name, vertical=False, **kw):
    """A serial DE-9 plug: five over four, in PC99 teal."""
    _dsub(f, cx - 8.4, cy - 4, 16.8, SERIAL, ((5, 0), (4, 0)), vertical)
    f.port(fam, name, 'de-9', cx, cy, **kw)


def hdmi(f: Face, x, y, fam, name, gen='hdmi2.0', **kw):
    f.poly([(x, y), (x + 14, y), (x + 14, y + 3.2), (x + 12.6, y + 4.6), (x + 1.4, y + 4.6),
            (x, y + 3.2)], CAGE, stroke=CAGE_EDGE, sw=0.3)
    f.rect(x + 1.6, y + 0.9, 10.8, 1.4, HOLE)
    f.port(fam, name, 'hdmi', x + 7, y + 2.3, gen=gen, signals=['hdmi', 'audio'], **kw)


def displayport(f: Face, x, y, fam, name, gen='dp1.4', **kw):
    f.poly([(x, y), (x + 16, y), (x + 16, y + 4.8), (x + 1.6, y + 4.8), (x, y + 3.2)], CAGE,
           stroke=CAGE_EDGE, sw=0.3)
    f.rect(x + 2, y + 1, 12, 1.6, HOLE)
    f.port(fam, name, 'displayport', x + 8, y + 2.4, gen=gen, signals=['dp', 'audio'], **kw)


def audio_jack(f: Face, cx, cy, fam, name, **kw):
    f.circle(cx, cy, 2.6, '#1f2329', stroke=CAGE_EDGE, sw=0.4)
    f.circle(cx, cy, 1.2, HOLE)
    f.port(fam, name, 'audio-3-5mm', cx, cy, signals=['audio'], **kw)


def sma(f: Face, cx, cy, fam, name, **kw):
    """An antenna socket: the gold threaded barrel of an SMA."""
    f.circle(cx, cy, 3.1, '#d4a72c', stroke='#8a6a12', sw=0.4)
    f.circle(cx, cy, 1.9, '#e2c25a', stroke='#8a6a12', sw=0.3)
    f.circle(cx, cy, 0.5, '#1f2329')
    f.port(fam, name, 'sma', cx, cy, **kw)


def iec_inlet(f: Face, cx, cy, fam, name, typ='iec-60320-c14', watts=0, volts='100-240',
              switch=False, **kw):
    """A mains inlet centred on *cx, cy*: the C14 of everything up to ten amps, with its
    chamfered top, or the wider C20 of a big supply."""
    if typ == 'iec-60320-c20':
        f.rect(cx - 12, cy - 9.5, 24, 19, '#111317', rx=1, stroke='#4b5563', sw=0.4)
        f.rect(cx - 9.5, cy - 7, 19, 14, '#262a31', rx=0.8)
        f.rect(cx - 6.6, cy + 0.6, 4.6, 1.8, '#cfd4dc')
        f.rect(cx + 2, cy + 0.6, 4.6, 1.8, '#cfd4dc')
        f.rect(cx - 0.9, cy - 5.2, 1.8, 4.6, '#cfd4dc')
    else:
        f.rect(cx - 12, cy - 9, 24, 18, '#111317', rx=1, stroke='#4b5563', sw=0.4)
        f.poly([(cx - 9.2, cy - 3.6), (cx - 5.6, cy - 6.8), (cx + 5.6, cy - 6.8),
                (cx + 9.2, cy - 3.6), (cx + 9.2, cy + 6.8), (cx - 9.2, cy + 6.8)], '#262a31')
        for px, py in ((cx - 5.2, cy + 1.6), (cx + 3.6, cy + 1.6), (cx - 0.8, cy - 5)):
            f.rect(px, py, 1.6, 4.4, '#cfd4dc')
    if switch:
        f.rect(cx + 13.5, cy - 6, 6, 12, '#111317', rx=0.6)
        f.rect(cx + 14.5, cy - 5, 4, 5, '#b91c1c', rx=0.4)
    f.port(fam, name, typ, cx, cy, volts=volts, watts=watts or None, **kw)


def dc_jack(f: Face, cx, cy, fam, name, volts='19', watts=0, **kw):
    f.circle(cx, cy, 3.6, CAGE, stroke=CAGE_EDGE, sw=0.4)
    f.circle(cx, cy, 2.5, HOLE)
    f.circle(cx, cy, 0.8, '#cfd4dc')
    f.port(fam, name, 'dc-terminal', cx, cy, volts=volts, watts=watts or None, **kw)


# ── modules: what slides in, registered as a bay ─────────────────────────────────────────────

def fan_grille(f: Face, cx, cy, r) -> None:
    f.circle(cx, cy, r, '#16181c', stroke=EDGE, sw=0.4)
    for k in (0.78, 0.56, 0.34):
        f.circle(cx, cy, r * k, 'none', stroke='#3b4250', sw=0.45)
    f.line(cx - r, cy, cx + r, cy, '#3b4250', 0.5)
    f.line(cx, cy - r, cx, cy + r, '#3b4250', 0.5)
    f.circle(cx, cy, r * 0.18, '#3b4250')


def psu(f: Face, x, y, w, h, n: int, inlet='iec-60320-c14', watts=800, volts='100-240',
        inlet_left=False) -> None:
    """A hot-swap power supply seen from behind: its fan, its handle, its terracotta release
    tab, its LED and its inlet. The supply is a bay (``PSU bay n``) and its inlet a power port
    (``PSUn``), each where it is."""
    f.rect(x, y, w, h, STEEL_3, rx=1, stroke='#6b7280', sw=0.5)
    r = min(h / 2 - 2.5, w * 0.2)
    iw = 24
    if inlet_left:
        ix, fx = x + 3 + iw / 2, x + w - 4 - r
    else:
        ix, fx = x + w - 3 - iw / 2, x + 4 + r
    fan_grille(f, fx, y + h / 2, r)
    gx0 = (x + 2 * r + 7) if not inlet_left else (x + iw + 6)
    gx1 = (x + w - iw - 6) if not inlet_left else (x + w - 2 * r - 7)
    if gx1 - gx0 > 4:
        f.rect(gx0, y + 3, gx1 - gx0, h - 6, f.use_pattern('slots'))
    f.rect(fx - 2, y + h - 2.6, 4, 1.6, TOUCH, rx=0.4)
    led(f, (x + 3.2) if not inlet_left else (x + w - 3.2), y + 3.2, GREEN, 0.8)
    f.text(fx, y + 3.8, 'PSU %d' % n, size=1.9, fill=SILK_DIM, anchor='middle')
    iec_inlet(f, ix, y + h / 2, 'power-ports', 'PSU%d' % n, inlet, watts=watts, volts=volts)
    f.port('module-bays', 'PSU bay %d' % n, 'psu-bay', fx, y + h / 2 + r * 0.55)


def fan_module(f: Face, x, y, w, h, name: str) -> None:
    """A hot-swap fan tray seen from behind: its grille, a pull tab and its LED."""
    f.rect(x, y, w, h, STEEL_3, rx=1, stroke='#6b7280', sw=0.5)
    r = min(w, h) / 2 - 2.2
    fan_grille(f, x + w / 2, y + h / 2, r)
    f.rect(x + w / 2 - 2.5, y + h - 2.4, 5, 1.6, TOUCH, rx=0.4)
    led(f, x + 2.8, y + 2.8, GREEN, 0.7)
    f.port('module-bays', name, 'fan-bay', x + w / 2, y + h / 2)


def drive_sff(f: Face, x, y, w, h, name: str) -> None:
    """A 2.5-inch caddy standing up: the honeycomb, the release button and its two LEDs."""
    f.rect(x, y, w, h, '#1c1f24', rx=0.6, stroke='#5c6475', sw=0.4)
    f.rect(x + 1.2, y + 4, w - 2.4, h * 0.55, f.use_pattern('perf'))
    f.rect(x + 1, y + h - h * 0.28, w - 2, h * 0.28 - 1, '#3b4250', rx=0.5)
    f.rect(x + w / 2 - 2, y + h - h * 0.28 + 1.4, 4, 2, TOUCH, rx=0.4)
    f.circle(x + w / 2 - 2.6, y + 2.2, 0.8, GREEN)
    f.circle(x + w / 2 + 2.6, y + 2.2, 0.8, BLUE)
    f.port('module-bays', name, 'drive-bay', x + w / 2, y + h / 2)


def drive_lff(f: Face, x, y, w, h, name: str) -> None:
    """A 3.5-inch caddy lying down: the lever on the left, the LEDs on the right."""
    f.rect(x, y, w, h, '#1c1f24', rx=0.6, stroke='#5c6475', sw=0.4)
    f.rect(x + 1, y + 1, w * 0.24, h - 2, '#3b4250', rx=0.5)
    f.rect(x + 2.2, y + h / 2 - 1.5, 3, 3, TOUCH, rx=0.4)
    f.rect(x + w * 0.24 + 3, y + 2, w * 0.66, h - 4, f.use_pattern('perf'))
    f.circle(x + w - 3, y + h / 2 - 2.6, 0.8, GREEN)
    f.circle(x + w - 3, y + h / 2 + 2.6, 0.8, BLUE)
    f.port('module-bays', name, 'drive-bay', x + w / 2, y + h / 2)


def drive_sff_flat(f: Face, x, y, w, h, name: str) -> None:
    """A 2.5-inch caddy lying down, as a 1U box takes it."""
    f.rect(x, y, w, h, '#1c1f24', rx=0.6, stroke='#5c6475', sw=0.4)
    f.rect(x + 1, y + 1, w * 0.26, h - 2, '#3b4250', rx=0.5)
    f.rect(x + 2, y + h / 2 - 1.2, 2.6, 2.4, TOUCH, rx=0.4)
    f.rect(x + w * 0.26 + 3, y + 2, w * 0.62, h - 4, f.use_pattern('perf'))
    f.circle(x + w - 2.6, y + h / 2 - 2, 0.7, GREEN)
    f.circle(x + w - 2.6, y + h / 2 + 2, 0.7, BLUE)
    f.port('module-bays', name, 'drive-bay', x + w / 2, y + h / 2)


def bracket(f: Face, x, y, w, h, name: str, fill='#9aa3ad') -> None:
    """The bracket of an expansion slot seen from behind —empty, with its vent slots— and
    the slot it closes, as a bay."""
    f.rect(x, y, w, h, fill, rx=0.5, stroke='#6b7280', sw=0.4)
    f.rect(x + 6, y + 2, w - 12, h - 4, f.use_pattern('slots'))
    screw(f, x + 2.8, y + h / 2, 1.2)
    f.port('module-bays', name, 'module-bay', x + w / 2, y + h / 2)


def blank_slot(f: Face, x, y, w, h, name: str, text='') -> None:
    """A module slot with its blank cover: two captive screws and the slot's number."""
    f.rect(x, y, w, h, STEEL_2, rx=0.8, stroke='#6b7280', sw=0.5)
    screw(f, x + 3.5, y + h / 2)
    screw(f, x + w - 3.5, y + h / 2)
    if text:
        f.text(x + w / 2, y + h / 2 + 0.9, text, size=2.4, fill=SILK_DIM, anchor='middle')
    f.port('module-bays', name, 'module-bay', x + w / 2, y + h / 2)


# ── the inside: boards seen from above, the front at the top ─────────────────────────────────

def board(f: Face, x, y, w, h) -> None:
    f.rect(x, y, w, h, PCB, rx=1.5, stroke=PCB_EDGE, sw=0.6)


def tray(f: Face) -> None:
    """The chassis seen from above with its lid off: the tray and a FRONT / REAR mark."""
    f.rect(0, 0, f.w, f.h, '#1a1d22', rx=2)
    f.rect(1, 1, f.w - 2, f.h - 2, 'none', rx=1.8, stroke=EDGE, sw=1)
    f.text(f.w / 2, 4.6, 'FRONT', size=3, fill=SILK_DIM, anchor='middle', bold=True)
    f.text(f.w / 2, f.h - 2.2, 'REAR', size=3, fill=SILK_DIM, anchor='middle', bold=True)


def cpu(f: Face, x, y, w, h, name: str) -> None:
    """A CPU socket under its heatsink: the fins run front to back, with the air."""
    f.rect(x - 2, y - 2, w + 4, h + 4, '#1f2329', rx=1)
    f.rect(x, y, w, h, '#aeb6c1', rx=1, stroke='#6b7280', sw=0.5)
    f.rect(x + 2, y + 2, w - 4, h - 4, f.use_pattern('fins'))
    for sx, sy in ((x + 3, y + 3), (x + w - 3, y + 3), (x + 3, y + h - 3), (x + w - 3, y + h - 3)):
        screw(f, sx, sy, 1.5)
    f.rect(x + w / 2 - 9, y + h / 2 - 3.2, 18, 6.4, '#1f2329', rx=0.8)
    f.text(x + w / 2, y + h / 2 + 1.2, name, size=3.2, fill=SILK, anchor='middle', bold=True)
    f.port('module-bays', name, 'module-bay', x + w / 2, y + h / 2)


def dimm(f: Face, x, y, w, h, name: str, color='#111827') -> None:
    """A DIMM slot along the airflow, with its two latches."""
    f.rect(x, y, w, h, color, rx=0.4)
    if w > h:                                   # a SODIMM lying across the board
        f.rect(x - 1.6, y - 0.3, 2.2, h + 0.6, '#e5e7eb', rx=0.3)
        f.rect(x + w - 0.6, y - 0.3, 2.2, h + 0.6, '#e5e7eb', rx=0.3)
        f.rect(x + w * 0.42, y + h / 2 - 0.25, 2, 0.5, '#374151')
    else:
        f.rect(x - 0.3, y - 1.6, w + 0.6, 2.2, '#e5e7eb', rx=0.3)
        f.rect(x - 0.3, y + h - 0.6, w + 0.6, 2.2, '#e5e7eb', rx=0.3)
        f.rect(x + w / 2 - 0.25, y + h * 0.42, 0.5, 2, '#374151')
    f.port('module-bays', name, 'module-bay', x + w / 2, y + h / 2)


def m2(f: Face, x, y, w, h, name: str, label='M.2') -> None:
    """An M.2 slot: the connector at one end, the standoff at the other, the card's outline."""
    f.rect(x, y, w, h, 'none', rx=0.8, stroke='#9ca3af', sw=0.35)
    f.rect(x + 1, y, w - 2, 3, '#111827')
    f.circle(x + w / 2, y + h - 2.2, 1.3, '#d4a72c')
    f.text(x + w / 2, y + h / 2, label, size=2.4, fill=SILK_DIM, anchor='middle',
           rotate=90 if h > w * 2 else None)
    f.port('module-bays', name, 'module-bay', x + w / 2, y + h / 2)


def chip(f: Face, x, y, w, h, s='', fill='#1f2329') -> None:
    f.rect(x, y, w, h, fill, rx=0.6, stroke='#4b5563', sw=0.3)
    if s:
        f.text(x + w / 2, y + h / 2 + 1, s, size=2.4, fill=SILK_DIM, anchor='middle')


def fan_top(f: Face, x, y, w, h, name: str) -> None:
    """A fan module from above: its frame, its rotor and its handle."""
    f.rect(x, y, w, h, STEEL_3, rx=1, stroke='#6b7280', sw=0.4)
    r = min(w, h) / 2 - 2
    fan_grille(f, x + w / 2, y + h / 2, r)
    f.rect(x + w / 2 - 4, y + 0.6, 8, 2, TOUCH, rx=0.5)
    f.port('module-bays', name, 'fan-bay', x + w / 2, y + h / 2)


def dimm_bank(f: Face, x, y, n, name_of, h=133.0, pitch=7.0, w=5.0) -> float:
    """*n* DIMM slots side by side from *x*; hands back where the bank ends."""
    for i in range(n):
        dimm(f, x + i * pitch, y, w, h, name_of(i))
    return x + n * pitch


def outline(f: Face, x, y, w, h, s='', dash=True) -> None:
    """Something drawn for orientation and not placed: a riser cage, the drive cage."""
    f.el('rect', x=x, y=y, width=w, height=h, rx=1, fill='none', stroke=SILK_DIM,
         stroke_width=0.5, stroke_dasharray='2 1.4' if dash else None)
    if s:
        f.text(x + w / 2, y + 4, s, size=2.6, fill=SILK_DIM, anchor='middle')


# ── the models ───────────────────────────────────────────────────────────────────────────────

def _server_front(f: Face, bays: int, code: str) -> None:
    chassis(f, STEEL, ears=2)
    # The left ear: power, the system health and the identify button.
    button(f, 8, 15)
    led(f, 8, 26, GREEN, 0.9)
    led(f, 8, 31, AMBER, 0.9)
    button(f, 8, 74, 2.0, ring=BLUE)
    for i in range(bays):
        drive_sff(f, 22 + i * 15.2, 6, 14.6, 76.9, 'Bay %d' % i)
    x0 = 22 + bays * 15.2 + 4
    perf(f, x0, 6, 462 - x0, 60)
    f.rect(x0, 70, 462 - x0, 12.9, '#22262d', rx=0.8)
    f.text(x0 + 4, 78.6, code, size=4.2, fill=SILK, bold=True)
    # The right ear: a front VGA and USB for the crash cart.
    vga(f, 474.6, 26, 'front-ports', 'VGA (front)', vertical=True)
    usb_a(f, 471.7, 50, 'front-ports', 'USB (front)', gen='usb2', vertical=True)


def _rear_io(f: Face, x, y, *, eth: int, eth_typ='10gbase-t', serial=True) -> float:
    """The rear I/O of a server: serial, VGA, two USB, the BMC and the onboard LAN; from *x*,
    on a strip that starts at *y*. Hands back where it ends."""
    if serial:
        de9(f, x + 10, y + 7, 'console-ports', 'Serial')
        x += 24
    vga(f, x + 10, y + 7, 'rear-ports', 'VGA')
    x += 24
    usb_a(f, x, y + 1, 'rear-ports', 'USB 1')
    usb_a(f, x, y + 8.5, 'rear-ports', 'USB 2')
    x += 17
    rj45(f, x, y + 2, 'interfaces', 'bmc', '1000base-t')
    f.text(x + 6, y + 15, 'BMC', size=2, fill=SILK_DIM, anchor='middle')
    x += 16
    button(f, x + 2, y + 7, 1.8, ring=BLUE)
    x += 8
    for k in range(eth):
        rj45(f, x + k * 13, y + 2, 'interfaces', 'eth%d' % k, eth_typ)
        f.text(x + k * 13 + 6, y + 15, str(k), size=2, fill=SILK_DIM, anchor='middle')
    return x + eth * 13


def _ocp(f: Face, x, y, n=2, typ='25gbase-x-sfp28') -> None:
    """An OCP 3.0 network card: its bracket, the bay it is in, and its cages."""
    w = 18 + n * 16
    f.rect(x, y, w, 15, '#9aa3ad', rx=0.5, stroke='#6b7280', sw=0.4)
    screw(f, x + 3, y + 7.5, 1.3)
    for k in range(n):
        sfp(f, x + 8 + k * 16, y + 2.75, 'interfaces', 'sfp%d' % k, typ)
    f.text(x + w - 4, y + 13.6, 'OCP', size=1.8, fill='#374151', anchor='middle')
    f.port('module-bays', 'OCP 3.0', 'module-bay', x + w - 4, y + 4)


def server():
    """DM-R2: a 2U two-socket server, 24 SFF bays, three risers, OCP 3.0, two 800 W
    supplies. The demo's workhorse."""
    front = Face(W19, 2 * U)
    _server_front(front, 24, 'DM-R2')

    rear = Face(W19, 2 * U)
    chassis(rear, STEEL)
    for n, (x, slots) in enumerate(((6, (1, 2)), (144, (3, 4)), (356.6, (5, 6)))):
        rear.rect(x - 2, 3, 124, 42, STEEL_2, rx=1)
        rear.text(x + 60, 47.6, 'RISER %d' % (n + 1), size=1.8, fill=SILK_DIM, anchor='middle')
        for j, s in enumerate(slots):
            bracket(rear, x, 5 + j * 20, 120, 18, 'Slot %d' % s)
    psu(rear, 6, 49, 92, 37, 1, watts=800)
    psu(rear, 384.6, 49, 92, 37, 2, watts=800, inlet_left=True)
    _ocp(rear, 268, 50)
    _rear_io(rear, 104, 68, eth=4)
    rear.text(331, 66, 'DM-R2', size=3, fill=SILK_DIM, bold=True)

    inside = Face(434, 750)
    tray(inside)
    outline(inside, 8, 8, 418, 100, 'DRIVE CAGE · 24 × 2.5"')
    for i in range(24):
        inside.rect(14 + i * 17, 16, 15, 86, '#2a2e35', rx=0.5, stroke='#4b5563', sw=0.3)
    inside.rect(8, 110, 418, 4, '#14532d')
    for k in range(6):
        fan_top(inside, 11 + k * 69.5, 120, 64, 40, 'Fan %d' % (k + 1))
    board(inside, 8, 168, 418, 400)
    for c, (x0, banco) in enumerate(((22, 'A'), (226, 'B'))):
        fin = dimm_bank(inside, x0, 200, 8, lambda i, b=banco: 'DIMM %s%d' % (b, i + 1))
        cpu(inside, fin + 3, 228, 76, 76, 'CPU%d' % (c + 1))
        dimm_bank(inside, fin + 82, 200, 8, lambda i, b=banco: 'DIMM %s%d' % (b, i + 9))
    chip(inside, 182, 360, 30, 30, 'PCH')
    chip(inside, 230, 372, 16, 16, 'BMC')
    m2(inside, 150, 420, 22, 80, 'M.2 1', 'M.2 2280')
    m2(inside, 262, 420, 22, 80, 'M.2 2', 'M.2 2280')
    for x, s in ((6, 'RISER 1'), (155, 'RISER 2'), (304, 'RISER 3')):
        outline(inside, x, 580, 124, 70, s)
    outline(inside, 6, 660, 96, 84, 'PSU 1')
    outline(inside, 332, 660, 96, 84, 'PSU 2')
    outline(inside, 230, 660, 90, 40, 'OCP 3.0')
    return {'front': front, 'rear': rear, 'views': [('board', 'view_board', inside)]}


def gpu():
    """DM-G2: a 2U two-socket server for inference, eight single-width low-profile GPUs on
    four risers, eight NVMe bays and two 2000 W supplies on C20 inlets."""
    front = Face(W19, 2 * U)
    chassis(front, STEEL, ears=2)
    button(front, 8, 15)
    led(front, 8, 26, GREEN, 0.9)
    led(front, 8, 31, AMBER, 0.9)
    usb_a(front, 5.1, 56, 'front-ports', 'USB (front)', gen='usb3.2g1', vertical=True)
    for i in range(8):
        drive_sff(front, 22 + i * 15.2, 6, 14.6, 76.9, 'Bay %d' % i)
    perf(front, 148, 6, 314, 66)
    front.rect(148, 74, 314, 9, '#22262d', rx=0.8)
    front.text(152, 80.6, 'DM-G2', size=4.2, fill=SILK, bold=True)
    front.text(458, 80.4, 'NVMe', size=3, fill=SILK_DIM, anchor='end')
    led(front, 474.6, 15, BLUE, 0.9)

    rear = Face(W19, 2 * U)
    chassis(rear, STEEL)
    for x, primera in ((5, 1), (357.6, 5)):
        rear.rect(x - 2, 2, 124, 85, STEEL_2, rx=1)
        for j in range(4):
            bracket(rear, x, 4 + j * 20.6, 120, 18.4, 'GPU %d' % (primera + j), fill='#7c8591')
    _ocp(rear, 134, 6)
    _rear_io(rear, 186, 2, eth=2, serial=False)
    rear.text(240, 26, 'DM-G2', size=3, fill=SILK_DIM, bold=True)
    psu(rear, 130, 47, 110, 39, 1, inlet='iec-60320-c20', watts=2000, volts='200-240')
    psu(rear, 243.6, 47, 110, 39, 2, inlet='iec-60320-c20', watts=2000, volts='200-240',
        inlet_left=True)

    inside = Face(434, 800)
    tray(inside)
    outline(inside, 8, 8, 130, 100, '8 × NVMe')
    for i in range(8):
        inside.rect(14 + i * 15.2, 16, 13.6, 86, '#2a2e35', rx=0.5, stroke='#4b5563', sw=0.3)
    perf(inside, 146, 12, 280, 92)
    inside.rect(8, 110, 418, 4, '#14532d')
    for k in range(6):
        fan_top(inside, 11 + k * 69.5, 120, 64, 46, 'Fan %d' % (k + 1))
    board(inside, 8, 174, 418, 380)
    for c, (x0, banco) in enumerate(((36, 'A'), (230, 'B'))):
        fin = dimm_bank(inside, x0, 204, 6, lambda i, b=banco: 'DIMM %s%d' % (b, i + 1))
        cpu(inside, fin + 3, 234, 76, 76, 'CPU%d' % (c + 1))
        dimm_bank(inside, fin + 82, 204, 6, lambda i, b=banco: 'DIMM %s%d' % (b, i + 7))
    chip(inside, 196, 380, 30, 30, 'PCH')
    chip(inside, 236, 392, 16, 16, 'BMC')
    m2(inside, 150, 430, 22, 80, 'M.2 1', 'M.2 2280')
    m2(inside, 262, 430, 22, 80, 'M.2 2', 'M.2 2280')
    for x, s in ((6, 'GPU 1-4'), (304, 'GPU 5-8')):
        outline(inside, x, 566, 124, 226, s)
        for j in range(4):
            inside.rect(x + 6 + j * 28, 580, 22, 200, '#4b5563', rx=1, stroke='#6b7280', sw=0.4)
    outline(inside, 136, 566, 162, 36, 'OCP 3.0 · I/O')
    outline(inside, 136, 610, 80, 182, 'PSU 1')
    outline(inside, 218, 610, 80, 182, 'PSU 2')
    return {'front': front, 'rear': rear, 'views': [('board', 'view_board', inside)]}


#: A half-width node: half of 19 inches less the rails.
HALF = 217.0


def node():
    """DM-N1: a half-width 1U node —two of them share a U—, one socket, two SFF bays, two
    500 W supplies."""
    front = Face(HALF, U)
    chassis(front, STEEL)
    handle(front, 3, 6, 4, 32.45)
    drive_sff_flat(front, 10, 4.5, 72, 17, 'Bay 0')
    drive_sff_flat(front, 10, 23, 72, 17, 'Bay 1')
    perf(front, 88, 4.5, 92, 35.5)
    button(front, 190, 12)
    led(front, 190, 22, GREEN, 0.8)
    led(front, 190, 27, AMBER, 0.8)
    usb_a(front, 199.5, 15.5, 'front-ports', 'USB (front)', gen='usb3.2g1', vertical=True)
    front.text(184, 38.4, 'DM-N1', size=2.6, fill=SILK, bold=True)
    handle(front, 210, 6, 4, 32.45)

    rear = Face(HALF, U)
    chassis(rear, STEEL)
    bracket(rear, 4, 3.5, 79, 15, 'Slot 1')
    rj45(rear, 4, 23, 'interfaces', 'eth0', '10gbase-t')
    rj45(rear, 17, 23, 'interfaces', 'eth1', '10gbase-t')
    sfp(rear, 31, 23.25, 'interfaces', 'sfp0', '25gbase-x-sfp28')
    sfp(rear, 46, 23.25, 'interfaces', 'sfp1', '25gbase-x-sfp28')
    rj45(rear, 62, 23, 'interfaces', 'bmc', '1000base-t')
    console_rj45(rear, 76, 23, 'console-ports', 'Serial', label='')
    rear.text(23, 39.5, '10G', size=1.8, fill=SILK_DIM, anchor='middle')
    rear.text(53, 39.5, '25G', size=1.8, fill=SILK_DIM, anchor='middle')
    rear.text(68, 39.5, 'BMC', size=1.8, fill=SILK_DIM, anchor='middle')
    rear.text(82, 39.5, 'IOIOI', size=1.6, fill=SILK_DIM, anchor='middle')
    psu(rear, 92, 3.5, 61, 37.45, 1, watts=500)
    psu(rear, 154, 3.5, 61, 37.45, 2, watts=500)

    inside = Face(HALF, 600)
    tray(inside)
    outline(inside, 6, 8, 80, 86, '2 × 2.5"')
    inside.rect(12, 18, 68, 30, '#2a2e35', rx=0.5)
    inside.rect(12, 54, 68, 30, '#2a2e35', rx=0.5)
    for k in range(4):
        fan_top(inside, 8 + k * 51, 104, 47, 40, 'Fan %d' % (k + 1))
    board(inside, 6, 152, 205, 300)
    fin = dimm_bank(inside, 20, 180, 4, lambda i: 'DIMM A%d' % (i + 1))
    cpu(inside, fin + 4, 210, 76, 76, 'CPU1')
    dimm_bank(inside, fin + 84, 180, 4, lambda i: 'DIMM A%d' % (i + 5))
    chip(inside, 30, 340, 26, 26, 'PCH')
    chip(inside, 64, 346, 14, 14, 'BMC')
    m2(inside, 150, 330, 22, 80, 'M.2 1', 'M.2 2280')
    outline(inside, 4, 470, 90, 120, 'RISER')
    outline(inside, 98, 470, 116, 120, 'PSU 1 · PSU 2')
    return {'front': front, 'rear': rear, 'views': [('board', 'view_board', inside)]}


def storage():
    """DM-S4: a 4U dual-controller array, 24 LFF bays, four SFP+ host ports per controller,
    two supply-and-cooling modules."""
    h = 4 * U
    front = Face(W19, h)
    chassis(front, STEEL, ears=4)
    button(front, 8, 18)
    led(front, 8, 30, GREEN, 1.0)
    led(front, 8, 36, AMBER, 1.0)
    led(front, 8, 42, BLUE, 1.0)
    front.rect(468.6, 14, 12, 9, '#111317', rx=0.6)
    front.text(474.6, 20.8, '01', size=5, fill='#ef4444', anchor='middle', bold=True)
    for r in range(6):
        for c in range(4):
            drive_lff(front, 24 + c * 103, 8 + r * 27.4, 101, 26.4, 'Disk %d' % (r * 4 + c))
    perf(front, 438, 8, 24, 162)
    front.text(450, 100, 'DM-S4', size=4, fill=SILK, bold=True, anchor='middle', rotate=-90)

    rear = Face(W19, h)
    chassis(rear, STEEL)
    for n, x in ((1, 6), (2, 386.6)):
        rear.rect(x, 5, 90, 168, STEEL_3, rx=1, stroke='#6b7280', sw=0.5)
        fan_grille(rear, x + 45, 42, 30)
        fan_grille(rear, x + 45, 106, 30)
        rear.rect(x + 41, 168, 8, 2.4, TOUCH, rx=0.5)
        led(rear, x + 6, 10, GREEN, 0.9)
        rear.text(x + 45, 11, 'PSU %d' % n, size=2.2, fill=SILK_DIM, anchor='middle')
        iec_inlet(rear, x + 45, 152, 'power-ports', 'PSU%d' % n, watts=1100, switch=True)
        rear.port('module-bays', 'PSU bay %d' % n, 'psu-bay', x + 45, 74)
    for letra, y in (('A', 5), ('B', 91)):
        x = 100
        rear.rect(x, y, 282.6, 82, STEEL_3, rx=1, stroke='#6b7280', sw=0.5)
        handle(rear, x + 3, y + 30, 3.4, 22)
        handle(rear, x + 276, y + 30, 3.4, 22)
        rear.text(x + 12, y + 8, 'CONTROLLER %s' % letra, size=2.6, fill=SILK, bold=True)
        led(rear, x + 250, y + 7, GREEN, 0.9, 'OK')
        led(rear, x + 262, y + 7, AMBER, 0.9, '!')
        for j in range(4):
            sfp(rear, x + 14 + j * 18, y + 24, 'interfaces', 'ctrl%s-%d' % (letra, j))
            rear.text(x + 21 + j * 18, y + 39, str(j), size=2, fill=SILK_DIM, anchor='middle')
        rear.text(x + 48, y + 20, 'HOST 10GbE', size=2, fill=SILK_DIM, anchor='middle')
        rj45(rear, x + 100, y + 24, 'interfaces', 'mgmt%s' % letra, '1000base-t')
        rear.text(x + 106, y + 20, 'MGMT', size=2, fill=SILK_DIM, anchor='middle')
        console_rj45(rear, x + 118, y + 24, 'console-ports', 'console%s' % letra, label='')
        rear.text(x + 124, y + 20, 'IOIOI', size=2, fill=SILK_DIM, anchor='middle')
        for j in range(2):
            ex = x + 140 + j * 22
            rear.rect(ex, y + 24, 18, 9.5, CAGE, rx=0.6, stroke=CAGE_EDGE, sw=0.3)
            rear.rect(ex + 1.5, y + 26, 15, 5.5, HOLE, rx=0.5)
            rear.port('rear-ports', 'exp%s-%d' % (letra, j + 1), 'other', ex + 9, y + 28.75)
        rear.text(x + 160, y + 20, 'SAS EXP', size=2, fill=SILK_DIM, anchor='middle')
        usb_a(rear, x + 192, y + 26, 'rear-ports', 'USB %s' % letra, gen='usb2')
        perf(rear, x + 14, y + 46, 254, 30)
        rear.port('module-bays', 'Controller %s' % letra, 'module-bay', x + 230, y + 30)

    inside = Face(434, 400)
    inside.rect(0, 0, 434, 400, '#1a1d22', rx=2)
    inside.text(217, 6, 'CONTROLLERS · TOP COVER OFF', size=3, fill=SILK_DIM, anchor='middle',
                bold=True)
    for letra, x in (('A', 8), ('B', 222)):
        inside.rect(x, 12, 204, 380, STEEL_3, rx=1.5, stroke='#6b7280', sw=0.6)
        inside.text(x + 102, 22, 'CONTROLLER %s' % letra, size=3, fill=SILK, anchor='middle',
                    bold=True)
        board(inside, x + 6, 28, 192, 300)
        inside.rect(x + 66, 70, 70, 70, '#aeb6c1', rx=1)
        inside.rect(x + 68, 72, 66, 66, inside.use_pattern('fins'))
        inside.text(x + 101, 108, 'SoC', size=3, fill='#1f2329', anchor='middle', bold=True)
        dimm(inside, x + 30, 60, 5, 133, 'Cache %s1' % letra)
        dimm(inside, x + 40, 60, 5, 133, 'Cache %s2' % letra)
        m2(inside, x + 150, 60, 22, 60, 'Boot %s' % letra, 'M.2 2260')
        inside.rect(x + 60, 220, 90, 40, '#1e3a8a', rx=2, stroke='#3b82f6', sw=0.5)
        inside.text(x + 105, 243, 'SUPERCAP', size=2.8, fill=SILK, anchor='middle')
        inside.port('module-bays', 'BBU %s' % letra, 'module-bay', x + 105, 240)
        inside.rect(x + 20, 280, 160, 26, '#9aa3ad', rx=1)
        inside.text(x + 100, 297, 'HOST INTERFACE CARD', size=2.6, fill='#1f2329',
                    anchor='middle')
        inside.port('module-bays', 'HIC %s' % letra, 'module-bay', x + 100, 293)
        inside.rect(x + 10, 340, 184, 46, '#111317', rx=1)
        inside.text(x + 102, 366, 'MIDPLANE CONNECTOR', size=2.6, fill=SILK_DIM, anchor='middle')
    return {'front': front, 'rear': rear, 'views': [('controllers', 'view_controllers', inside)]}


def _switch_leds(f: Face, x=19.5) -> None:
    for i, (c, s) in enumerate(((GREEN, 'SYS'), (GREEN, 'FAN'), (GREEN, 'PS1'), (AMBER, 'PS2'))):
        led(f, x + (i % 2) * 9, 12 + (i // 2) * 8, c, 0.8, s, 1.6)


def _rj45_rows(f: Face, x0, n, fmt, typ='1000base-t', y_top=11.4, group=6, pitch=13.0,
               gap=3.0) -> float:
    """A switch's RJ45 block: odd ports on top, even below, in groups; the numbers printed above
    and below. Hands back where it ends."""
    for k in range(n // 2):
        x = x0 + k * pitch + (k // group) * gap
        rj45(f, x, y_top, 'interfaces', fmt % (2 * k + 1), typ)
        rj45(f, x, y_top + 11.6, 'interfaces', fmt % (2 * k + 2), typ, down=True)
        f.text(x + 6, y_top - 1.0, str(2 * k + 1), size=2.1, fill=SILK_DIM, anchor='middle')
        f.text(x + 6, y_top + 21.6 + 2.6, str(2 * k + 2), size=2.1, fill=SILK_DIM,
               anchor='middle')
    k = n // 2 - 1
    return x0 + k * pitch + (k // group) * gap + 12


def _uplinks(f: Face, x0, fmt='Te1/1/%d', y_top=11.0) -> None:
    for r in range(2):
        for j in range(2):
            sfp(f, x0 + j * 16.5, y_top + r * 12, 'interfaces', fmt % (1 + j + 2 * r),
                down=bool(r))
    f.text(x0 + 15, y_top - 1.6, 'SFP+', size=2.1, fill=SILK_DIM, anchor='middle')


def tor():
    """DM-S48: a 1U 48-port gigabit switch, PoE+ on every port, four SFP+ uplinks, console
    and management at the front, two hot-swap supplies and two fan trays at the rear."""
    front = Face(W19, U)
    chassis(front, '#262a30', ears=1)
    _switch_leds(front)
    fin = _rj45_rows(front, 40, 48, 'Gi1/0/%d')
    console_rj45(front, fin + 8, 11.4, 'console-ports', 'Console')
    rj45(front, fin + 8, 23, 'interfaces', 'Mgmt0', '1000base-t', down=True)
    front.text(fin + 14, 37.6, 'MGMT', size=1.9, fill=SILK_DIM, anchor='middle')
    usb_a(front, fin + 24, 15, 'front-ports', 'USB', gen='usb2', vertical=True)
    _uplinks(front, 410)
    front.text(447, 40.2, 'DM-S48 · PoE+', size=2.2, fill=SILK_DIM, anchor='end')

    rear = Face(W19, U)
    chassis(rear, '#262a30')
    ground(rear, 12, 14)
    rear.text(14.5, 30, 'DM-S48', size=2.4, fill=SILK_DIM, anchor='middle', bold=True)
    perf(rear, 30, 6, 150, 32.45)
    fan_module(rear, 186, 4, 48, 36.45, 'Fan 1')
    fan_module(rear, 238, 4, 48, 36.45, 'Fan 2')
    psu(rear, 296, 4, 88, 36.45, 1, watts=1100)
    psu(rear, 388, 4, 88, 36.45, 2, watts=1100)
    return {'front': front, 'rear': rear, 'views': []}


def access():
    """DM-S24: a 1U 24-port gigabit access switch with four SFP+ uplinks and a fixed internal
    supply."""
    front = Face(W19, U)
    chassis(front, '#262a30', ears=1)
    _switch_leds(front)
    fin = _rj45_rows(front, 40, 24, 'Gi1/0/%d')
    _uplinks(front, fin + 10)
    console_rj45(front, fin + 50, 11.4, 'console-ports', 'Console')
    usb_a(front, fin + 51.2, 26, 'front-ports', 'USB', gen='usb2')
    perf(front, fin + 72, 8, 446 - fin - 72, 28.45)
    front.text(458, 40.2, 'DM-S24', size=2.4, fill=SILK_DIM, anchor='end', bold=True)

    rear = Face(W19, U)
    chassis(rear, '#262a30')
    ground(rear, 14, 14)
    fan_grille(rear, 110, U / 2, 15)
    fan_grille(rear, 150, U / 2, 15)
    perf(rear, 180, 6, 220, 32.45)
    rear.text(240, 40.5, 'DM-S24 · 100-240 V~ 50/60 Hz 2.5 A', size=2, fill=SILK_DIM)
    iec_inlet(rear, 444, U / 2, 'power-ports', 'AC IN', watts=150, switch=False)
    return {'front': front, 'rear': rear, 'views': []}


def core():
    """DM-C32: a 2U aggregation/core switch: 48 SFP+, four QSFP28 100G, four gigabit copper
    service ports, two expansion slots, four fan trays and two supplies."""
    front = Face(W19, 2 * U)
    chassis(front, '#262a30', ears=2)
    for i, (c, s) in enumerate(((GREEN, 'SYS'), (GREEN, 'FAN'), (GREEN, 'PS1'), (GREEN, 'PS2'),
                                (BLUE, 'ID'))):
        led(front, 22 + i * 11, 8, c, 0.8, s, 1.6)
    for k in range(24):
        x = 24 + k * 14.6 + (k // 8) * 3
        sfp(front, x, 18, 'interfaces', 'Te1/0/%d' % (2 * k + 1))
        sfp(front, x, 29, 'interfaces', 'Te1/0/%d' % (2 * k + 2), down=True)
        if k % 2 == 0:
            front.text(x + 7, 16.4, str(2 * k + 1), size=2, fill=SILK_DIM, anchor='middle')
    for r in range(2):
        for j in range(2):
            qsfp(front, 390 + j * 21.5, 17 + r * 12.5, 'interfaces',
                 'Hu1/0/%d' % (49 + j + 2 * r), down=bool(r))
    front.text(411, 14.6, 'QSFP28 100G', size=2, fill=SILK_DIM, anchor='middle')
    for k in range(4):
        rj45(front, 24 + k * 13, 56, 'interfaces', 'Gi1/0/%d' % (k + 1))
        front.text(30 + k * 13, 70.4, str(k + 1), size=2, fill=SILK_DIM, anchor='middle')
    rj45(front, 84, 56, 'interfaces', 'Mgmt0', '1000base-t')
    front.text(90, 70.4, 'MGMT', size=1.9, fill=SILK_DIM, anchor='middle')
    console_rj45(front, 98, 56, 'console-ports', 'Console', label='')
    front.text(104, 70.4, 'CONSOLE', size=1.9, fill=SILK_DIM, anchor='middle')
    usb_a(front, 114, 58, 'front-ports', 'USB', gen='usb2')
    blank_slot(front, 136, 50, 160, 34, 'Slot 1', 'EXPANSION 1')
    blank_slot(front, 300, 50, 160, 34, 'Slot 2', 'EXPANSION 2')
    front.text(28, 80.6, 'DM-C32', size=3.6, fill=SILK, bold=True)

    rear = Face(W19, 2 * U)
    chassis(rear, '#262a30')
    ground(rear, 10, 8)
    for k in range(4):
        fan_module(rear, 8 + k * 68, 18, 64, 66, 'Fan %d' % (k + 1))
    psu(rear, 286, 8, 92, 40, 1, watts=1100)
    psu(rear, 382, 8, 92, 40, 2, watts=1100)
    perf(rear, 286, 52, 188, 32)
    rear.text(380, 47.6, 'DM-C32', size=2.4, fill=SILK_DIM, anchor='middle', bold=True)
    return {'front': front, 'rear': rear, 'views': []}


def router():
    """DM-RT1: a 1U edge router, eight gigabit ports, four SFP+, two module slots, two
    hot-swap supplies."""
    front = Face(W19, U)
    chassis(front, '#2d3138', ears=1)
    for i, (c, s) in enumerate(((GREEN, 'SYS'), (GREEN, 'ACT'), (GREEN, 'PS1'), (GREEN, 'PS2'))):
        led(front, 20 + (i % 2) * 9, 14 + (i // 2) * 8, c, 0.8, s, 1.6)
    console_rj45(front, 42, 17, 'console-ports', 'Console')
    rj45(front, 56, 17, 'interfaces', 'Mgmt0', '1000base-t')
    front.text(62, 16, 'MGMT', size=1.9, fill=SILK_DIM, anchor='middle')
    usb_a(front, 71, 15.5, 'front-ports', 'USB', gen='usb2', vertical=True)
    for k in range(8):
        rj45(front, 86 + k * 13, 17, 'interfaces', 'Gi0/%d' % k)
        front.text(92 + k * 13, 16, str(k), size=2, fill=SILK_DIM, anchor='middle')
    front.text(138, 33.5, '10/100/1000', size=2, fill=SILK_DIM, anchor='middle')
    for k in range(4):
        sfp(front, 196 + k * 16, 17.25, 'interfaces', 'Te0/0/%d' % k)
        front.text(203 + k * 16, 16, str(k), size=2, fill=SILK_DIM, anchor='middle')
    front.text(227, 33.5, 'SFP+', size=2, fill=SILK_DIM, anchor='middle')
    blank_slot(front, 266, 6, 96, 32.45, 'NIM 1', 'NIM 1')
    blank_slot(front, 366, 6, 96, 32.45, 'NIM 2', 'NIM 2')
    front.text(24, 38.5, 'DM-RT1', size=2.4, fill=SILK, bold=True)

    rear = Face(W19, U)
    chassis(rear, '#2d3138')
    ground(rear, 12, 14)
    psu(rear, 30, 4, 84, 36.45, 1, watts=400)
    psu(rear, 118, 4, 84, 36.45, 2, watts=400)
    fan_module(rear, 210, 4, 120, 36.45, 'Fan tray')
    perf(rear, 336, 6, 140, 32.45)
    rear.text(406, 40.6, 'DM-RT1', size=2.2, fill=SILK_DIM, anchor='middle', bold=True)
    return {'front': front, 'rear': rear, 'views': []}


def cpe():
    """DM-CPE: the half-width, fanless carrier router an operator leaves at the customer's:
    eight gigabit ports, two SFP+ for the access fibre, an internal supply."""
    front = Face(HALF, U)
    chassis(front, '#e5e7eb')
    for i, (c, s) in enumerate(((GREEN, 'PWR'), (GREEN, 'SYS'), (GREEN, 'WAN'), (AMBER, 'ALM'))):
        led(front, 6 + (i % 2) * 9, 14 + (i // 2) * 8, c, 0.8)
        front.text(8 + (i % 2) * 9, 17.6 + (i // 2) * 8, s, size=1.5, fill='#4b5563')
    console_rj45(front, 25, 17, 'console-ports', 'Console', label='')
    front.text(31, 15.8, 'CON', size=1.9, fill='#4b5563', anchor='middle')
    for k in range(8):
        rj45(front, 41 + k * 13, 17, 'interfaces', 'Gi0/%d' % k)
        front.text(47 + k * 13, 15.8, str(k), size=2, fill='#4b5563', anchor='middle')
    for k in range(2):
        sfp(front, 150 + k * 16, 17.25, 'interfaces', 'Te0/0/%d' % k)
        front.text(157 + k * 16, 15.8, 'WAN%d' % k, size=1.8, fill='#4b5563', anchor='middle')
    front.text(212, 38, 'DM-CPE', size=2.6, fill='#1f2937', anchor='end', bold=True)

    rear = Face(HALF, U)
    chassis(rear, '#d1d5db')
    ground(rear, 10, 14)
    rear.rect(30, 8, 120, 28.45, '#c3c8cf', rx=1)
    rear.rect(30, 8, 120, 28.45, rear.use_pattern('slots'), rx=1)
    rear.text(90, 41, '100-240 V~ 50/60 Hz 0.6 A', size=1.9, fill='#374151', anchor='middle')
    iec_inlet(rear, 182, U / 2, 'power-ports', 'AC IN', watts=60)
    return {'front': front, 'rear': rear, 'views': []}


def firewall():
    """DM-FW1: a 1U firewall: sixteen gigabit copper, eight gigabit SFP, four SFP+, dedicated
    MGMT and HA ports, a log SSD, two supplies and three fans."""
    front = Face(W19, U)
    chassis(front, '#3b1d1d', ears=1)
    for i, (c, s) in enumerate(((GREEN, 'PWR'), (GREEN, 'STA'), (GREEN, 'HA'), (AMBER, 'ALM'))):
        led(front, 20 + (i % 2) * 9, 12 + (i // 2) * 8, c, 0.8, s, 1.6)
    console_rj45(front, 42, 11.4, 'console-ports', 'Console')
    usb_a(front, 42.5, 26, 'front-ports', 'USB', gen='usb3.2g1')
    rj45(front, 60, 11.4, 'interfaces', 'mgmt', '1000base-t')
    front.text(66, 10.4, 'MGMT', size=1.9, fill=SILK_DIM, anchor='middle')
    rj45(front, 60, 23, 'interfaces', 'ha', '1000base-t', down=True)
    front.text(66, 37.6, 'HA', size=1.9, fill=SILK_DIM, anchor='middle')
    for k in range(8):
        x = 82 + k * 13 + (k // 4) * 3
        rj45(front, x, 11.4, 'interfaces', 'port%d' % (2 * k + 1))
        rj45(front, x, 23, 'interfaces', 'port%d' % (2 * k + 2), down=True)
        front.text(x + 6, 10.4, str(2 * k + 1), size=2, fill=SILK_DIM, anchor='middle')
        front.text(x + 6, 37.6, str(2 * k + 2), size=2, fill=SILK_DIM, anchor='middle')
    for k in range(4):
        x = 196 + k * 15.5
        sfp(front, x, 11.4, 'interfaces', 'port%d' % (17 + 2 * k), '1000base-x-sfp')
        sfp(front, x, 23.4, 'interfaces', 'port%d' % (18 + 2 * k), '1000base-x-sfp', down=True)
        front.text(x + 7, 10.2, str(17 + 2 * k), size=2, fill=SILK_DIM, anchor='middle')
    for j in range(2):
        for r in range(2):
            x = 266 + j * 16
            sfp(front, x, 11.4 + r * 12, 'interfaces', 'x%d' % (1 + j * 2 + r), down=bool(r))
    front.text(281, 10.2, 'SFP+', size=2, fill=SILK_DIM, anchor='middle')
    drive_sff_flat(front, 312, 13, 70, 18.45, 'SSD')
    front.text(347, 37.2, 'LOG SSD', size=1.9, fill=SILK_DIM, anchor='middle')
    front.rect(392, 9, 66, 26.45, '#111317', rx=1)
    front.text(425, 25, 'DM-FW1', size=4.4, fill='#f87171', anchor='middle', bold=True)

    rear = Face(W19, U)
    chassis(rear, '#2d3138')
    ground(rear, 12, 14)
    for k in range(3):
        fan_module(rear, 32 + k * 50, 4, 46, 36.45, 'Fan %d' % (k + 1))
    perf(rear, 186, 6, 102, 32.45)
    psu(rear, 294, 4, 88, 36.45, 1, watts=400)
    psu(rear, 386, 4, 88, 36.45, 2, watts=400)
    return {'front': front, 'rear': rear, 'views': []}


def _panel_positions(n=24) -> list:
    """The x of each position of a 24-port panel, in four groups of six, from the front."""
    return [40 + k * 17 + (k // 6) * 4 + 5.5 for k in range(n)]


def patch():
    """DM-PP24: a 1U Cat 6A shielded patch panel, 24 keystone jacks, punched down at the rear
    onto a cable support bar."""
    front = Face(W19, U)
    chassis(front, '#1f2329', ears=1)
    xs = _panel_positions()
    for g in range(4):
        x0 = xs[g * 6] - 6.5
        front.rect(x0, 5, 6 * 17 - 4, 5.2, '#f3f4f6', rx=0.5)
        front.text(x0 + 2, 9, 'CAT 6A', size=2.2, fill='#374151')
    for k, cx in enumerate(xs):
        x = cx - 5.5
        front.rect(x - 1, 14.5, 13, 13, '#111827', rx=0.6)
        f_x = x - 0.5
        rj45(front, f_x, 16, 'front-ports', str(k + 1), '8p8c', leds=False, shell='#6b7280')
        front.text(cx + 0.5, 33, str(k + 1), size=2.4, fill=SILK, anchor='middle')
    front.text(463, 41.4, 'DM-PP24', size=2, fill=SILK_DIM, anchor='end')

    # From behind, position 1 is on the right: the panel turned round.
    rear = Face(W19, U)
    rear.rect(0, 0, W19, U, '#15171b', rx=1.5)
    rear.rect(10, 4, W19 - 20, 3, '#6b7280', rx=1)
    rear.rect(10, 37.45, W19 - 20, 3, '#6b7280', rx=1)
    for k, cx in enumerate(xs):
        rx_ = W19 - cx - 0.5
        rear.rect(rx_ - 6.5, 10, 13, 24, '#374151', rx=0.8, stroke='#6b7280', sw=0.3)
        for i, c in enumerate(('#2563eb', '#f97316', '#16a34a', '#92400e')):
            rear.rect(rx_ - 5.5 + i * 2.9, 12, 2.2, 6, c, rx=0.4)
        rear.rect(rx_ - 4, 22, 8, 9, '#111827', rx=0.6)
        rear.text(rx_, 33.4, str(k + 1), size=2, fill=SILK_DIM, anchor='middle')
        rear.port('rear-ports', '%d-R' % (k + 1), '110-punch', rx_, 22)
    rear.text(W19 / 2, 43, 'T568B', size=1.8, fill=SILK_DIM, anchor='middle')
    return {'front': front, 'rear': rear, 'views': []}


def fiber():
    """DM-FP24: a 1U sliding fibre panel, 24 LC/UPC duplex single-mode adapters, loaded from
    both sides."""
    front = Face(W19, U)
    chassis(front, '#1f2329', ears=1)
    xs = [40 + k * 17 + (k // 6) * 4 + 6 for k in range(24)]

    def adaptador(f, cx, cy, fam, name):
        f.rect(cx - 6.4, cy - 4.2, 12.8, 8.4, '#2563eb', rx=0.8, stroke='#1e40af', sw=0.3)
        for dx in (-3.1, 3.1):
            f.rect(cx + dx - 2.2, cy - 2.6, 4.4, 5.2, '#0b1220', rx=0.5)
            f.circle(cx + dx, cy, 0.7, '#e5e7eb')
        f.port(fam, name, 'lc-upc', cx, cy)

    for k, cx in enumerate(xs):
        adaptador(front, cx, 21.5, 'front-ports', str(k + 1))
        front.text(cx, 30.6, str(k + 1), size=2.2, fill=SILK, anchor='middle')
    for g in range(4):
        x0 = xs[g * 6] - 7
        front.rect(x0, 6, 6 * 17 - 3, 5, '#fde047', rx=0.5)
        front.text(x0 + 2, 9.8, 'OS2 · LC/UPC', size=2.2, fill='#1f2937')
    handle(front, 22, 34, 14, 3.4)
    handle(front, 446.6, 34, 14, 3.4)
    front.text(463, 41.4, 'DM-FP24', size=2, fill=SILK_DIM, anchor='end')

    rear = Face(W19, U)
    rear.rect(0, 0, W19, U, '#15171b', rx=1.5)
    rear.rect(10, 3, W19 - 20, U - 6, '#2b2f36', rx=1, stroke=EDGE, sw=0.6)
    for k, cx in enumerate(xs):
        adaptador(rear, W19 - cx, 20, 'rear-ports', '%d-R' % (k + 1))
        rear.text(W19 - cx, 29, str(k + 1), size=2, fill=SILK_DIM, anchor='middle')
    for x in (30, W19 - 54):
        rear.rect(x, 33, 24, 7, '#111317', rx=3.5)
        rear.text(x + 12, 38.2, 'ENTRY', size=1.8, fill=SILK_DIM, anchor='middle')
    return {'front': front, 'rear': rear, 'views': []}


def console():
    """DM-CS16: a 1U out-of-band console server: sixteen RS-232 ports on RJ45, two USB console
    ports, two gigabit network ports and an SFP, an LTE modem for when the network is what
    failed, and two supplies."""
    front = Face(W19, U)
    chassis(front, '#262a30', ears=1)
    for i, (c, s) in enumerate(((GREEN, 'PWR'), (GREEN, 'NET'), (BLUE, 'LTE'), (AMBER, 'ALM'))):
        led(front, 20 + (i % 2) * 9, 12 + (i // 2) * 8, c, 0.8, s, 1.6)
    for k in range(16):
        x = 46 + k * 13.5 + (k // 8) * 6
        console_rj45(front, x, 17, 'console-server-ports', 'Port%d' % (k + 1), label=str(k + 1))
    front.text(158, 33, 'SERIAL RS-232', size=2, fill=SILK_DIM, anchor='middle')
    for k in range(2):
        rj45(front, 278 + k * 13, 17, 'interfaces', 'NET%d' % (k + 1), '1000base-t')
        front.text(284 + k * 13, 16, 'NET%d' % (k + 1), size=1.8, fill=SILK_DIM, anchor='middle')
    sfp(front, 306, 17.25, 'interfaces', 'SFP', '1000base-x-sfp')
    front.text(313, 16, 'SFP', size=1.8, fill=SILK_DIM, anchor='middle')
    usb_a(front, 328, 13, 'console-server-ports', 'USB1', gen='usb2')
    usb_a(front, 328, 22, 'console-server-ports', 'USB2', gen='usb2')
    front.text(334.5, 32, 'USB CON', size=1.8, fill=SILK_DIM, anchor='middle')
    console_rj45(front, 348, 17, 'console-ports', 'Console', label='LOCAL')
    front.rect(372, 10, 86, 24.45, '#111317', rx=1)
    front.text(415, 25, 'DM-CS16', size=4, fill=SILK, anchor='middle', bold=True)

    rear = Face(W19, U)
    chassis(rear, '#262a30')
    ground(rear, 12, 14)
    sma(rear, 60, U / 2, 'rear-ports', 'ANT1')
    sma(rear, 80, U / 2, 'rear-ports', 'ANT2')
    rear.text(70, 34, 'LTE MAIN · DIV', size=1.8, fill=SILK_DIM, anchor='middle')
    rear.rect(96, 15, 22, 14, '#111317', rx=1)
    rear.text(107, 24, 'SIM', size=2.4, fill=SILK_DIM, anchor='middle')
    rear.port('interfaces', 'wwan0', 'lte', 107, 22)
    perf(rear, 130, 6, 230, 32.45)
    iec_inlet(rear, 384, U / 2, 'power-ports', 'PSU1', watts=40, switch=True)
    iec_inlet(rear, 440, U / 2, 'power-ports', 'PSU2', watts=40, switch=True)
    rear.text(412, 41.4, 'PSU 1 · PSU 2  100-240 V~', size=1.8, fill=SILK_DIM, anchor='middle')
    return {'front': front, 'rear': rear, 'views': []}


def kvm():
    """DM-KVM8: a 1U rack console drawer —a 17-inch LCD that folds down onto a keyboard and a
    touchpad— with an 8-port CAT KVM switch built in: the servers plug into its RJ45s through
    their USB/VGA adapters, and its LAN port reaches it over IP."""
    front = Face(W19, U)
    chassis(front, '#24272d', ears=1)
    handle(front, 24, 31, 434.6, 6)
    front.rect(60, 6, 362.6, 21, '#1b1e23', rx=1.2, stroke='#3b4250', sw=0.4)
    front.text(241.3, 19, 'DM-KVM8 · 17" LCD CONSOLE · 8-PORT KVM', size=3, fill=SILK_DIM,
               anchor='middle')
    led(front, 30, 12, GREEN, 0.9, 'PWR', 1.7)
    led(front, 30, 20, BLUE, 0.9, 'KVM', 1.7)
    front.rect(436, 9, 18, 14, '#3b4250', rx=1)
    front.text(445, 17.6, 'PUSH', size=2.2, fill=SILK, anchor='middle')
    usb_a(front, 424.6, 14, 'front-ports', 'USB (front)', gen='usb2', vertical=True)

    rear = Face(W19, U)
    chassis(rear, '#24272d')
    for k in range(8):
        rj45(rear, 30 + k * 14, 17, 'console-server-ports', 'KVM%d' % (k + 1), 'rj-45',
             leds=True)
        rear.text(36 + k * 14, 15.8, str(k + 1), size=2, fill=SILK_DIM, anchor='middle')
    rear.text(85, 33.6, 'CAT5e/6 SERVER PORTS', size=1.9, fill=SILK_DIM, anchor='middle')
    rj45(rear, 152, 17, 'console-server-ports', 'Chain', 'rj-45')
    rear.text(158, 15.8, 'CHAIN', size=1.8, fill=SILK_DIM, anchor='middle')
    rj45(rear, 170, 17, 'interfaces', 'LAN', '1000base-t')
    rear.text(176, 15.8, 'LAN', size=1.8, fill=SILK_DIM, anchor='middle')
    vga(rear, 206, 22, 'rear-ports', 'VGA')
    usb_a(rear, 224, 14, 'rear-ports', 'USB 1', gen='usb2')
    usb_a(rear, 224, 24, 'rear-ports', 'USB 2', gen='usb2')
    rear.text(220, 36, 'LOCAL CONSOLE', size=1.8, fill=SILK_DIM, anchor='middle')
    perf(rear, 250, 6, 160, 32.45)
    iec_inlet(rear, 440, U / 2, 'power-ports', 'PSU1', watts=45, switch=True)

    opened = Face(434, 380)
    opened.rect(0, 0, 434, 380, '#16181c', rx=2)
    opened.rect(37, 6, 360, 228, '#24272d', rx=4, stroke='#3b4250', sw=0.8)
    opened.rect(47, 16, 340, 205, '#0b1220', rx=1)
    opened.rect(47, 16, 340, 205, 'none', rx=1, stroke='#1e3a8a', sw=0.6)
    opened.text(217, 115, '17" TFT · 1280 × 1024', size=7, fill='#334155', anchor='middle')
    opened.text(217, 128, 'OSD: Scroll Lock ×2', size=4, fill='#334155', anchor='middle')
    led(opened, 380, 228, GREEN, 1.2)
    opened.rect(12, 240, 410, 132, '#24272d', rx=3, stroke='#3b4250', sw=0.8)
    opened.rect(24, 250, 300, 112, opened.use_pattern('keys'), rx=1)
    opened.rect(340, 262, 70, 52, '#2a2e35', rx=3, stroke='#454b56', sw=0.4)
    opened.rect(340, 320, 33, 12, '#2a2e35', rx=1.5, stroke='#454b56', sw=0.4)
    opened.rect(377, 320, 33, 12, '#2a2e35', rx=1.5, stroke='#454b56', sw=0.4)
    opened.text(375, 352, 'TOUCHPAD', size=3, fill=SILK_DIM, anchor='middle')
    return {'front': front, 'rear': rear, 'views': [('open', 'view_open', opened)]}


#: The mini PC is not a rack unit's width.
MINI = 177.0


def mini():
    """DM-MINI: the mini PC of the lab shelf: an embedded processor, two SODIMMs, two M.2 and a
    2.5-inch bay, dual 2.5 GbE, two HDMI and a DisplayPort, and its 19 V brick."""
    front = Face(MINI, U)
    chassis(front, '#c7ccd4')
    button(front, 16, U / 2, 3.4, ring=BLUE)
    usb_a(front, 34, 12, 'front-ports', 'USB 1', gen='usb3.2g2')
    usb_a(front, 34, 26, 'front-ports', 'USB 2', gen='usb3.2g2')
    usb_c(front, 52, 20.6, 'front-ports', 'USB-C')
    audio_jack(front, 68, U / 2, 'front-ports', 'Audio')
    led(front, 80, 16, '#ffffff', 0.7)
    front.text(170, 38, 'DM-MINI', size=3, fill='#374151', anchor='end', bold=True)
    front.rect(96, 8, 70, 16, '#b4bac3', rx=1.5)
    front.rect(96, 8, 70, 16, front.use_pattern('slots'), rx=1.5)

    rear = Face(MINI, U)
    chassis(rear, '#9ca3af')
    dc_jack(rear, 14, U / 2, 'power-ports', 'DC-IN', volts='19', watts=90)
    rj45(rear, 26, 10, 'interfaces', 'eth0', '2.5gbase-t')
    rj45(rear, 26, 24, 'interfaces', 'eth1', '2.5gbase-t', down=True)
    hdmi(rear, 44, 10, 'rear-ports', 'HDMI 1')
    hdmi(rear, 44, 18, 'rear-ports', 'HDMI 2')
    displayport(rear, 43, 26.5, 'rear-ports', 'DP')
    usb_a(rear, 66, 10, 'rear-ports', 'USB 3', gen='usb3.2g1')
    usb_a(rear, 66, 19, 'rear-ports', 'USB 4', gen='usb3.2g1')
    usb_a(rear, 66, 28, 'rear-ports', 'USB 5', gen='usb2')
    rear.rect(86, 6, 72, 32.45, '#8b929c', rx=1.5)
    rear.rect(86, 6, 72, 32.45, rear.use_pattern('slots'), rx=1.5)
    rear.rect(162, 18, 7, 4.5, '#1f2329', rx=1)
    rear.text(165.5, 28, 'LOCK', size=1.6, fill='#1f2937', anchor='middle')

    inside = Face(MINI - 7, 175)
    inside.rect(0, 0, inside.w, inside.h, '#1a1d22', rx=2)
    inside.text(inside.w / 2, 5, 'FRONT', size=3, fill=SILK_DIM, anchor='middle', bold=True)
    board(inside, 6, 8, 158, 160)
    inside.rect(20, 40, 36, 36, '#aeb6c1', rx=1)
    inside.rect(22, 42, 32, 32, inside.use_pattern('fins'))
    inside.text(38, 60, 'SoC', size=3, fill='#1f2329', anchor='middle', bold=True)
    inside.circle(38, 104, 18, '#16181c', stroke=EDGE, sw=0.5)
    inside.text(38, 106, 'BLOWER', size=2.4, fill=SILK_DIM, anchor='middle')
    dimm(inside, 66, 30, 69, 5, 'SODIMM 1')
    dimm(inside, 66, 42, 69, 5, 'SODIMM 2')
    m2(inside, 70, 58, 80, 22, 'M.2 SSD', 'M.2 2280 NVMe')
    m2(inside, 70, 88, 30, 22, 'M.2 WLAN', 'M.2 2230')
    outline(inside, 106, 92, 54, 70, '2.5" SATA', dash=False)
    inside.port('module-bays', 'SATA bay', 'drive-bay', 133, 130)
    inside.text(inside.w / 2, 173.4, 'REAR', size=3, fill=SILK_DIM, anchor='middle', bold=True)
    return {'front': front, 'rear': rear, 'views': [('board', 'view_board', inside)]}


#: Who draws each model.
DRAWERS = {
    'server': server, 'gpu': gpu, 'node': node, 'storage': storage, 'tor': tor,
    'access': access, 'core': core, 'router': router, 'cpe': cpe, 'firewall': firewall,
    'patch': patch, 'fiber': fiber, 'console': console, 'kvm': kvm, 'mini': mini,
}


def drawers() -> dict:
    """Who draws every demo model: the fifteen devices above and the rest of the catalogue
    —the cabinets, the power, the passive pieces, the room's devices, the modules and the
    components—, drawn in `demo_draw_extra` with the same parts. Read when asked and not at
    import: that module imports this one."""
    from lib.core.dcim import demo_draw_extra    # noqa: PLC0415
    return dict(DRAWERS, **demo_draw_extra.DRAWERS)

_CACHE: dict = {}


def draw(key: str) -> dict:
    """``{'front': Face, 'rear': Face or None, 'views': [(id, name_key, Face)]}`` of a model, drawn
    once per process: the demo reads it once per model and the tests read it many times."""
    if key not in _CACHE:
        out = drawers()[key]()
        out['views'] = [(view_id(key, vid), nombre, cara) for vid, nombre, cara in out['views']]
        _CACHE[key] = out
    return _CACHE[key]


def files(key: str) -> dict:
    """``{file name: svg}`` of a model: ``<key>.front.svg``, ``<key>.rear.svg`` (when it has a
    rear) and one ``<key>.<view id>.svg`` per view."""
    d = draw(key)
    out = {'%s.front.svg' % key: d['front'].svg()}
    # A module or a component is seen out of its device: one picture, no rear.
    if d['rear'] is not None:
        out['%s.rear.svg' % key] = d['rear'].svg()
    for vid, _nombre, cara in d['views']:
        out['%s.%s.svg' % (key, vid)] = cara.svg()
    return out


def write(folder: str) -> list:
    """Write every model's pictures into *folder*; hands back the names written."""
    import io                                    # noqa: PLC0415
    import os                                    # noqa: PLC0415
    hechos = []
    for key in drawers():
        for nombre, svg in files(key).items():
            with io.open(os.path.join(folder, nombre), 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(svg)
            hechos.append(nombre)
    return hechos


if __name__ == '__main__':                       # pragma: no cover - the regeneration step
    import os
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
    from lib.core.dcim import demo_faces          # noqa: PLC0415
    for viejo in os.listdir(demo_faces.FACES_DIR):
        if viejo.endswith('.svg'):
            os.remove(os.path.join(demo_faces.FACES_DIR, viejo))
    print('\n'.join(write(demo_faces.FACES_DIR)))
