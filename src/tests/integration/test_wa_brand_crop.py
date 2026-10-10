#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The brand's adjust dialog, in `node` on the panel's real script.

Asked from the screen: a picked picture should open in a window showing it beside the slot's
maximum and recommended size, and let it be cropped or resized to fit before it goes up. And
the empty name field should show the product's name as its placeholder. What these pin is the
arithmetic the dialog stands on — the drawing itself is a browser's:

- the box always keeps the slot's shape and stays inside the picture;
- it starts as the largest such box, centred;
- the result starts at the recommended size, brought inside the slot's limits;
- the dialog says what is wrong with a size before anything is sent;
- a format heavier than the slot takes falls back to a lighter one the slot accepts.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='no node: nothing to run the script with')

_PROBE = r"""
__out = {};
const cuadrada = {shape: 'square', rec: [512, 512], min_px: 128, max_px: 2048, kinds: ['svg', 'png', 'webp']};
const apaisada = {shape: 'landscape', rec: [1280, 854], min_px: 320, max_px: 4096, kinds: ['svg', 'png', 'jpg', 'webp']};
const ancha = {shape: 'wide', rec: [160, 160], min_px: 64, max_px: 640, kinds: ['png']};

__out.inicial = [_bcInitial('square', 1000, 600), _bcInitial('landscape', 600, 1000),
                 _bcInitial('wide', 2000, 100), _bcInitial('landscape', 1200, 800)];
// Dragging a corner far outside the picture: the box stays inside and square.
__out.resize = _bcResize([100, 100], [5000, 300], 'square', 1000, 600);
__out.resizeIzq = _bcResize([500, 500], [-300, 450], 'square', 1000, 600);
__out.resizeAlta = _bcResize([0, 0], [200, 900], 'landscape', 1000, 1000);
__out.resizeAncha = _bcResize([0, 0], [900, 50], 'wide', 1000, 1000);
__out.out = [_bcOutSize(cuadrada, 1), _bcOutSize(apaisada, 1.5), _bcOutSize(ancha, 2),
             _bcOutSize(cuadrada, 1 / 3)];
__out.problemas = [_bcSizeProblem(cuadrada, 64, 64), _bcSizeProblem(cuadrada, 512, 300),
                   _bcSizeProblem(apaisada, 400, 800), _bcSizeProblem(cuadrada, 512, 512)];
__out.formatos = [_bcFormats(cuadrada).map(f => f[2]), _bcFormats(ancha).map(f => f[2]),
                  _bcFormats(apaisada).map(f => f[2])];
__out.aspectoEntera = [_bcAspect({mode: 'fit', W: 300, H: 100, spec: cuadrada}),
                       _bcAspect({mode: 'fit', W: 300, H: 100, spec: apaisada}),
                       _bcAspect({mode: 'fit', W: 100, H: 300, spec: apaisada}),
                       _bcAspect({mode: 'crop', rect: {w: 200, h: 100}, spec: apaisada})];
__out.placeholder = FIELD_PICKERS['brand|name'].placeholder === PRODUCT_NAME && !!PRODUCT_NAME;
__out.abre = String(_brandCropOpen);

// ── Saving the name shows it at once ─────────────────────────────────────────
const marcados = [{textContent: APP_NAME}, {textContent: APP_NAME}];
const qsaOrig = document.querySelectorAll;
document.querySelectorAll = (sel) => sel === '[data-brand-name]' ? marcados : [];
document.title = APP_NAME + ' — Admin';
_brandApplyName('Acme NOC');
__out.vivo = [marcados.map(m => m.textContent), document.title];
_brandApplyName('');
__out.vacio = [marcados[0].textContent === PRODUCT_NAME, document.title === PRODUCT_NAME + ' — Admin'];
document.querySelectorAll = qsaOrig;
__out.guardar = String(saveConfig).includes("_brandApplyName(");

// ── A vector is drawn at a size, and the box measures the dialog, not the picture ──
const imgEl = {style: {}};
const wrapEl = {clientWidth: 900};
const getOrig = document.getElementById;
document.getElementById = (id) => ({bcWrap: wrapEl, bcImg: imgEl}[id] || null);
_bc = {svg: true, W: 0, H: 0};
_bcPlace();
__out.svgTamano = [imgEl.style.width, imgEl.style.height];
_bc = {svg: false, W: 1200, H: 800, rect: {x: 0, y: 0, w: 800, h: 800}};
_bcPlace();
__out.escala = _bc.k;
_bc = null;
document.getElementById = getOrig;
"""


@pytest.fixture(scope='module')
def out():
    """One `node` run for the whole module: starting it costs more than looking."""
    pytest.importorskip('flask')
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var,
                  pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    return node_run(panel_bundle(c), _PROBE)


class TestTheBox:
    def test_it_starts_as_the_largest_box_of_the_shape_centred(self, out):
        assert out['inicial'] == [
            {'x': 200, 'y': 0, 'w': 600, 'h': 600},
            {'x': 0, 'y': 200, 'w': 600, 'h': 600},
            {'x': 800, 'y': 0, 'w': 400, 'h': 100},
            {'x': 0, 'y': 0, 'w': 1200, 'h': 800},
        ]

    def test_resized_it_keeps_its_shape_and_stays_inside(self, out):
        r = out['resize']
        assert r['w'] == r['h'] and r['x'] + r['w'] <= 1000 and r['y'] + r['h'] <= 600
        r = out['resizeIzq']
        assert r['w'] == r['h'] and r['x'] >= 0 and r['x'] + r['w'] == 500

    def test_landscape_is_never_taller_than_wide_and_wide_never_past_four_to_one(self, out):
        assert out['resizeAlta']['h'] <= out['resizeAlta']['w']
        a = out['resizeAncha']
        assert a['w'] <= 4 * a['h']


class TestTheResult:
    def test_it_starts_at_the_recommended_size_within_the_limits(self, out):
        assert out['out'][0] == {'w': 512, 'h': 512}
        assert out['out'][1] == {'w': 1280, 'h': 853}
        assert out['out'][2] == {'w': 160, 'h': 80} or min(out['out'][2].values()) >= 64
        assert min(out['out'][3].values()) >= 128, 'brought up to the smallest side'

    def test_whole_with_margins_takes_the_shape_the_slot_allows(self, out):
        assert out['aspectoEntera'] == [1, 3, 1, 2]

    def test_it_says_what_is_wrong_before_sending(self, out):
        bajo, no_cuadrada, no_apaisada, bien = out['problemas']
        assert '64' in bajo and '128' in bajo
        assert no_cuadrada and no_apaisada and bien == ''

    def test_a_lighter_format_only_where_the_slot_takes_it(self, out):
        assert out['formatos'] == [['png', 'webp'], ['png'], ['png', 'webp', 'jpg']]


class TestTheName:
    def test_the_empty_field_shows_the_product_s_name(self, out):
        assert out['placeholder']


class TestThePictureLoads:
    def test_read_as_data_url_which_the_content_policy_allows(self, out):
        """Reported: a perfectly good PNG said «this slot does not take that kind of image» —
        it was opened through a `blob:` URL, and the panel's `img-src` is `'self' data:`."""
        assert 'readAsDataURL' in out['abre']
        assert 'createObjectURL' not in out['abre']


class TestSavingTheNameShowsItAtOnce:
    """Reported: the platform's name was saved and nothing changed until F5."""

    def test_every_marked_place_and_the_tab_title(self, out):
        assert out['vivo'] == [['Acme NOC', 'Acme NOC'], 'Acme NOC — Admin']

    def test_emptied_it_goes_back_to_the_product_s(self, out):
        assert out['vacio'] == [True, True]

    def test_the_save_applies_it(self, out):
        assert out['guardar']


class TestThePictureIsDrawnAtTheDialogsSize:
    """Seen in the browser: an SVG with only a viewBox showed as nothing, and a bitmap was drawn
    600 px wide whatever room the dialog had."""

    def test_a_vector_gets_a_size(self, out):
        assert out['svgTamano'] == ['480px', '480px']

    def test_a_bitmap_fills_the_width_there_is(self, out):
        assert abs(out['escala'] - 900 / 1200) < 1e-9 or out['escala'] < 900 / 1200
