#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two things that could not be read on screen.

* On the floor plan a room's name was sized from the room's short side alone: «Sala de reuniones
  Atlántico» in a seven-metre room drew twice as wide as the room, over its neighbours. It now
  shrinks to 90 % of the room's width, and is cut with «…» when even the smallest size does not
  fit; the size line fits on its own.
* On the site map, the line joining two sites was a thin coloured stroke that vanished on a
  satellite map, and its label, in the secondary grey, could not be read at all. It now runs
  over a halo of the background colour, and the label has an outline.
"""

from __future__ import annotations

import shutil

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = [pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed'),
              pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')]

_PROBE = r"""
__out = {};
const ancho = (o) => o.texto.length * o.tam * 0.5;
const largo = _dcsFitName('Sala de reuniones Atlántico', 70, 12);
__out.largo = [largo.tam, largo.texto, ancho(largo) <= 70 * 0.9 + 1e-9];
const corto = _dcsFitName('Office', 70, 12);
__out.corto = [corto.tam, corto.texto];
const estrecha = _dcsFitName('Sala de reuniones Atlántico con nombre larguísimo', 20, 12);
__out.estrecha = [estrecha.tam, estrecha.texto.endsWith('…'), ancho(estrecha) <= 20 * 0.9 + 1e-9];

_dcmData = () => ({links: [{uid: 't1', a_site: 'a', b_site: 'b', state: 'ok', kind: 'fiber',
                            label: 'Troncal Madrid–Valencia'}]});
_dcmAt = (s) => s.uid === 'a' ? {x: 10, y: 10} : {x: 200, y: 50};
_dcmScale = () => 1;
_dcmTileUrl = () => 'https://tiles.example/{z}/{x}/{y}.png';
const MUNDO = [{uid: 'm', lat: 40.42, lon: -3.69}, {uid: 'd', lat: 32.78, lon: -96.80},
               {uid: 'p', lat: 18.47, lon: -66.11}, {uid: 'z', lat: -26.11, lon: 28.06},
               {uid: 't', lat: 25.03, lon: 121.57}];
_dcmAt = (s) => ssGeoProject(s.lat, s.lon);
const caja = _dcmExtent(MUNDO, 0.45);
__out.encuadre = [caja.width / SS_GEO_WORLD,
                  MUNDO.every(s => { const q = ssGeoProject(s.lat, s.lon);
                      return q.x >= caja.x && q.x <= caja.x + caja.width
                          && q.y >= caja.y && q.y <= caja.y + caja.height; })];
_dcmAt = (s) => s.uid === 'a' ? {x: 10, y: 10} : {x: 200, y: 50};
__out.enlaceQuieto = _dcmLinks([{uid: 'a'}, {uid: 'b'}], 'labels');
_dcmHotLink = 't1';
__out.enlace = _dcmLinks([{uid: 'a'}, {uid: 'b'}]);
_dcmHotLink = '';
_dcmHot = 'a';
__out.enlaceSede = _dcmLinks([{uid: 'a'}, {uid: 'b'}], 'labels');
_dcmHot = '';
_dcmData = () => ({links: [
    {uid: 'l1', a_site: 'a', b_site: 'b', state: 'ok', kind: 'mpls', label: 'MPLS'},
    {uid: 'l2', a_site: 'b', b_site: 'a', state: 'error', kind: 'ipsec', label: 'IPsec'}]});
_dcmHot = 'a';               // the site pointed at: both its links say their names
__out.dos = _dcmLinks([{uid: 'a'}, {uid: 'b'}]);
_dcmHot = '';
__out.lineas = _dcmLinks([{uid: 'a'}, {uid: 'b'}], 'lines');
__out.rotulos = _dcmLinks([{uid: 'a'}, {uid: 'b'}], 'labels');
_dcsSel = null;
const sala = _dcsRoom({uid: 'r1', name: 'Sala de bombas PCI y grupo electrógeno', width_mm: 2800, depth_mm: 8700,
                       pos_x: 0, pos_y: 0, rotation: 0});
__out.sala = [...sala.matchAll(/<text[^>]*font-size="([\d.]+)"/g)].map(m => Number(m[1]));

// A: two sites down twenty pixels apart: the one with more checks down keeps the card.
// In this order a plain tie would hand the spot to «Respaldo»: only the tie-break saves «Demo».
const JUNTAS = [{uid: 'dem', name: 'Demo', state: 'error', ok: 375, total: 474},
                {uid: 'res', name: 'Respaldo', state: 'error', ok: 4, total: 7}];
_dcmAt = (s) => s.uid === 'res' ? {x: 1000, y: 1000} : {x: 1015, y: 1004};
_dcmHot = '';
__out.juntas = Object.keys(_dcmLabels(JUNTAS));
__out.pin = _dcmSite(JUNTAS[1], 1, false);
// C: a link label moves along its arc off a site's card, or is left out when nowhere is free.
const DOS = [{uid: 'a', name: 'A', state: 'error', ok: 0, total: 3}, {uid: 'b', name: 'B', state: 'ok'}];
_dcmData = () => ({links: [{uid: 'x', a_site: 'a', b_site: 'b', state: 'error', kind: 'mpls',
                            label: 'IPsec Respaldo'}]});
_dcmAt = (s) => s.uid === 'a' ? {x: 0, y: 0} : {x: 300, y: 0};
__out.aparta = _dcmLinks(DOS, 'labels');
_dcmAt = (s) => s.uid === 'a' ? {x: 0, y: 0} : {x: 0, y: -60};
__out.tapado = _dcmLinks(DOS, 'labels');
_dcmHotLink = 'x';
__out.tapadoSenalado = _dcmLinks(DOS, 'labels');
_dcmHotLink = '';

// D: going to the board closes the site plan that was open, or a click on the map went back.
_dcsPlan = {site: {uid: 'r'}, floors: []};
_dcimOpenBoard = () => null;
_dcimMark = () => {};
_dcPlanLeave = () => {};
_dcimGo('board');
__out.planTrasCuadro = _dcsPlan;
"""


@pytest.fixture()
def out(client):
    _login(client)
    return node_run(panel_bundle(client), _PROBE)


def test_a_long_room_name_fits_its_room(out):
    tam, texto, cabe = out['largo']
    assert texto == 'Sala de reuniones Atlántico' and tam < 12 and cabe


def test_a_short_room_name_keeps_its_size(out):
    assert out['corto'] == [12, 'Office']


def test_a_name_that_cannot_fit_is_cut(out):
    tam, cortado, cabe = out['estrecha']
    assert tam == 4.5 and cortado and cabe


def test_the_site_link_has_a_halo_and_an_outlined_label(out):
    svg = out['enlace']
    assert svg.count('<path') == 3, 'no halo under the link (plus its hover band)'
    assert 'stroke="var(--bs-body-bg)"' in svg
    assert 'paint-order="stroke"' in svg and 'Troncal Madrid–Valencia' in svg
    assert 'var(--bs-secondary-color)' not in svg


def test_two_links_between_the_same_sites_do_not_overlap(out):
    """Two links for HA between the same pair drew on the same straight line: one was seen and
    their labels were written on top of each other."""
    import re
    svg = out['dos']
    trazos = re.findall(r'<g data-link="(l\d)"><path d="([^"]+)"', svg)
    assert [u for u, _ in trazos] == ['l1', 'l2']
    assert trazos[0][1] != trazos[1][1], 'both links follow the same path'
    rotulos = dict((m[2], (float(m[0]), float(m[1]))) for m in
                   re.findall(r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*>([^<]+)</text>', svg))
    (x1, y1), (x2, y2) = rotulos['MPLS'], rotulos['IPsec']
    assert abs(x1 - x2) + abs(y1 - y2) > 20, 'the two labels are drawn on top of each other'
    assert 'var(--bs-danger)' in svg and 'var(--bs-success)' in svg


def test_link_labels_are_a_layer_above_the_site_boxes(out):
    """With the initial framing a site's box covered the label of the link leaving it."""
    assert '<text' not in out['lineas'] and '<path' in out['lineas']
    # MPLS is fine, so only the IPsec (in error) shows its label without pointing at it.
    assert '<path' not in out['rotulos'] and 'IPsec' in out['rotulos']
    assert 'MPLS' not in out['rotulos']
    import os
    src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
    html = open(os.path.join(src, 'lib', 'web_admin', 'templates', 'partials', 'dcim',
                             '_sitemap.html'), encoding='utf-8').read()
    assert html.index('-pins">') < html.index('-linklabels"'), 'labels drawn under the boxes'


def test_the_size_line_is_never_bigger_than_the_name(out):
    nombre, medida = out['sala']
    assert medida <= nombre


def test_a_healthy_link_shows_its_label_only_when_pointed_at_or_its_site_is(out):
    """Seven long labels on one map were a tangle: a link that is fine says its name when the
    pointer is on it, or when one of its two sites is the one pointed at."""
    assert 'Troncal' not in out['enlaceQuieto']
    assert 'Troncal' in out['enlace'] and 'Troncal' in out['enlaceSede']


def test_the_initial_framing_hugs_the_sites(out):
    """It opened on the whole world: a 40 % square stretched to the panel's shape. Six sites
    spread from Dallas to Taipei still fit, with less than the full width of the world."""
    ancho, dentro = out['encuadre']
    assert dentro, 'a site is outside the initial framing'
    assert ancho < 0.85, ancho


def test_of_two_sites_down_side_by_side_the_worse_keeps_the_card(out):
    """«Demo» (99 checks down) lost its card to «Respaldo» (3 down) twenty pixels away."""
    assert out['juntas'] == ['dem'], out['juntas']


def test_leaving_a_pin_stops_pointing_at_it(out):
    """The highlight stayed after the pointer left the pin: every other site dimmed for good."""
    assert 'onpointerleave="_dcmCool()"' in out['pin']
    assert 'class="ss-ping' not in out['pin'] or 'pointer-events="none"' in out['pin']


def test_a_link_label_moves_off_a_card_or_waits_to_be_pointed_at(out):
    import re
    x = float(re.search(r'<text x="([-\d.]+)"', out['aparta']).group(1))
    ancho = len('IPsec Respaldo') * 12.5 * 0.56
    assert x - ancho / 2 >= 105, 'the label is written over the card'
    assert 'IPsec Respaldo' not in out['tapado']
    assert 'IPsec Respaldo' in out['tapadoSenalado']


def test_going_to_the_board_closes_the_open_site_plan(out):
    """From a site's plan to the board by the sidebar, a click on another site on the map went
    back to the plan that had been open."""
    assert out['planTrasCuadro'] is None
