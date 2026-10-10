#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The 3D viewer is one engine, shared, and it knows nothing of what it draws.

It was written inside the inventory for one room, then reused for a floor and a building, and
the rack and the circuits want it too. It kept ONE global viewer with fixed element ids, so a
second viewer on the same page would have drawn into the first one's canvas. It moved to
`infra/_viewer3d.html` with one instance per box; these guards keep the split from eroding:

- the engine finds its parts inside its own box, never by a fixed id;
- the engine names nothing of the inventory;
- WebGL lives in the engine only — a second copy of the matrices or the shaders in a section
  is a second viewer that drifts from the first;
- the engine is loaded before the sections that draw on it.
"""

from __future__ import annotations

import os
import re

from tests.helpers import _fn, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
PARTIALS = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials')
ENGINE = os.path.join(PARTIALS, 'infra', '_viewer3d.html')
TOOLS = os.path.join(PARTIALS, 'infra', '_viewer3d_tools.html')
DCIM = os.path.join(PARTIALS, 'dcim')


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _engine() -> str:
    # Both halves: the viewer's grammar and what was added once whole buildings were drawn.
    return _strip_comments(_read(ENGINE) + chr(10) + _read(TOOLS))


class TestOneViewerPerBox:

    def test_no_part_is_found_by_a_fixed_id(self):
        """`getElementById('dc3d-canvas')` is how the first version found its canvas, and why
        there could only be one."""
        assert not re.search(r"getElementById\(\s*['\"`]", _engine())

    def test_the_viewers_are_kept_by_box(self):
        js = _engine()
        assert 'const _SS3D = new Map()' in js
        assert '_SS3D.set(id, V)' in js


class TestTheEngineKnowsNothingOfTheInventory:

    def test_no_inventory_name_in_its_code(self):
        js = _engine()
        for word in ('_dc', 'dcim', '_ds3'):
            assert word not in js, word


class TestWebGlLivesInTheEngineOnly:

    def test_no_section_of_the_inventory_draws_by_itself(self):
        for name in sorted(os.listdir(DCIM)):
            if not name.endswith('.html'):
                continue
            js = _strip_comments(_read(os.path.join(DCIM, name)))
            for webgl in ("getContext('webgl'", 'createShader', 'drawElements',
                          'new Float32Array(16)'):
                assert webgl not in js, f'{name}: {webgl}'

    def test_the_engine_is_loaded_before_what_draws_on_it(self):
        bundle = _read(os.path.join(PARTIALS, '_js_sections.html'))
        engine = bundle.index('partials/infra/_viewer3d.html')
        assert engine < bundle.index('partials/dcim/_room3d.html')
        assert engine < bundle.index('partials/dcim/_site3d.html')


class TestThePlansKeepTheViewerCurrent:

    def test_both_plans_rebuild_the_3d_when_they_redraw(self):
        """Dragging, turning, the inspector and undo repaint only the plan's drawing, without
        `renderDcim`: without this the open 3D kept showing what was there before."""
        for f, fn in (('_plan.html', '_dcpRedraw'), ('_siteplan.html', '_dcsRedraw')):
            assert '_dc3dSoon()' in _fn(_read(os.path.join(DCIM, f)), fn), fn

    def test_a_rebuilt_scene_reuses_its_images(self):
        """A rebuild follows every edit of a plan; uploading the same plan again each time
        filled the card with copies nothing freed."""
        assert 'V.texs.has(p.data)' in _engine()


class TestWhatLiesUnderThePlansIsDrawnFirst:

    def test_translucent_slabs_before_the_images(self):
        """Reported: a floor slab made see-through was blended over the plan on it, and the plan
        vanished at 99 %. Translucent `bajo` boxes go before the images, the rest after."""
        body = _fn(_engine(), 'ss3dDraw')
        assert body.index('V.escena.bajos') < body.index('_ss3dDrawPlans(') < body.index('V.escena.vidrios')


class TestItDrawsOnlyWhenSomethingChanged:

    def test_the_loop_compares_before_drawing_and_sleeps(self):
        """It drew sixty frames a second for a picture standing still — a laptop's battery
        spent on an open pane nobody was looking at."""
        loop = _fn(_engine(), '_ss3dLoop')
        assert '_ss3dFirma(V)' in loop and 'V.idle < 20' in loop

    def test_the_solid_boxes_are_baked(self):
        assert '_ss3dBatchDraw(V, vp)' in _fn(_engine(), 'ss3dDraw')
