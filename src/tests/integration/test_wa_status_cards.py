#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A status card opened by hand shows its checks, in `node` on the panel's real script.

Reported from the screen: under Sistema › Estado an all-OK card (Ping, 15/15) turned its
chevron down and opened onto nothing. The card body was drawn with "only problems" already
applied, so every passing check had been left out of it, and the header click only showed the
empty body. What these tests pin:

- with the filter on, a card shows only its problems and SAYS how many it left out;
- opening a card by hand draws it again with every check;
- closing it again goes back to what the filter shows;
- with the filter off, nothing is hidden and nothing is said.
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
const checks = {};
for (let i = 0; i < 15; i++) checks['host' + i] = {status: true, other_data: {}};
const mixed = {a: {status: true, other_data: {}}, b: {status: false, message: 'down', other_data: {}}};
_stLastData = {ping: checks, web: mixed};
const rows = (html) => (html.match(/class="mt-1">\s*<i/g) || []).length;
const hiddenLine = (html) => html.includes('bi-eye-slash');

// ── Filter on, untouched ────────────────────────────────────────────────────────
_stOnlyProblems = true;
const allOk = _renderOneStatusCard('ping', checks);
__out.okRows = rows(allOk);
__out.okSaysHidden = hiddenLine(allOk) && allOk.includes(tf('st_rows_hidden', 15));
__out.okCollapsed = allOk.includes('ss-card-checks" style="display:none"');
const mix = _renderOneStatusCard('web', mixed);
__out.mixRows = rows(mix);
__out.mixSaysHidden = mix.includes(tf('st_rows_hidden', 1));

// ── Opened by hand: every check ─────────────────────────────────────────────────
let replaced = null;
const body = {style: {display: 'none'}};
const card = {getAttribute: () => 'ping', querySelector: () => body,
              replaceWith: (el) => { replaced = el; }};
const header = {closest: () => card, querySelector: () => null};
const origCreate = document.createElement;
document.createElement = (tag) => {
    const d = {firstElementChild: null};
    Object.defineProperty(d, 'innerHTML', {set(v) { d.html = v; d.firstElementChild = {html: v}; }});
    return d;
};
_toggleStatusCard(header);
__out.openedRows = replaced ? rows(replaced.html) : -1;
__out.openedNoHiddenLine = replaced ? !hiddenLine(replaced.html) : false;
__out.openedShown = replaced ? !replaced.html.includes('ss-card-checks" style="display:none"') : false;

// ── Closed again: back to what the filter shows ─────────────────────────────────
body.style.display = '';
replaced = null;
_toggleStatusCard(header);
__out.closedRows = replaced ? rows(replaced.html) : -1;
__out.closedHidden = replaced ? replaced.html.includes('ss-card-checks" style="display:none"') : false;
document.createElement = origCreate;

// ── Filter off ──────────────────────────────────────────────────────────────────
_stOnlyProblems = false;
_stCardOpen.clear();
const plain = _renderOneStatusCard('web', mixed);
__out.plainRows = rows(plain);
__out.plainSilent = !hiddenLine(plain);
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


class TestTheFilterSaysWhatItHides:
    def test_an_all_ok_card_lists_nothing_and_says_so(self, out):
        assert out['okRows'] == 0
        assert out['okSaysHidden']
        assert out['okCollapsed']

    def test_a_card_with_a_problem_lists_it_and_counts_the_rest(self, out):
        assert out['mixRows'] == 1
        assert out['mixSaysHidden']


class TestOpeningACardShowsEveryCheck:
    def test_opened_by_hand_it_lists_all_fifteen(self, out):
        assert out['openedRows'] == 15
        assert out['openedNoHiddenLine']
        assert out['openedShown']

    def test_closed_again_it_goes_back_to_the_filter(self, out):
        assert out['closedRows'] == 0
        assert out['closedHidden']


class TestWithoutTheFilter:
    def test_nothing_hidden_nothing_said(self, out):
        assert out['plainRows'] == 2
        assert out['plainSilent']
