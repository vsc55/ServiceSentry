#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The rooms of a site by floor, in every layout of the inventory, in `node` on the panel's
real script.

Reported from the screen: «Planta 0 · zona general» — the room that IS floor 0, where what is
in no room goes — was listed as a room beside «Expediciones», which is a room ON floor 0. What
these tests pin:

- the rooms on no floor stay where they were; each floor follows, lowest first, with its
  general area drawn as the floor itself and its rooms inside it;
- the general area is not counted as a room;
- the tree, the list, the detail, the cards and the table all say the same;
- searching hides a floor with nothing found, and the sites listing says which room is each
  floor's general area.
"""

from __future__ import annotations

import io
import json
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
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
const rack = (uid) => ({uid, name: uid, u_height: 42, used_u: 0, roll: {}});
const site = {
    uid: 's', name: 'Mirasol', org_uid: '',
    floor_list: [{uid: 'f1', name: 'Planta 1', level: 1, area_uid: ''},
                 {uid: 'f0', name: 'Planta 0', level: 0, area_uid: 'z0'}],
    rooms: [{uid: 'cpd', name: 'CPD', floor_uid: '', rackList: [rack('R01')], roll: {}},
            {uid: 'exp', name: 'Expediciones', floor_uid: 'f0', rackList: [rack('R02'), rack('R03')],
             roll: {state: 'error'}},
            {uid: 'z0', name: 'Planta 0 · zona general', floor_uid: 'f0', rackList: [rack('R09')], roll: {}}],
};
_dcimData = {orgs: [], sites: [site]};
_dcimQuery = '';

const g = _dcimByFloor(site);
__out.loose = g.loose.map(r => r.uid);
__out.floors = g.floors.map(p => [p.floor.uid, p.area ? p.area.uid : '', p.rooms.map(r => r.uid), p.key]);
__out.totals = _dcimFloorTotals(g.floors[0]);
__out.state = _dcimFloorState(g.floors[0]);
__out.siteRooms = _dcimSiteTotals(site).rooms;

// ── Every layout: the general area is the floor, Expediciones inside it ─────────
const sinZona = (html) => !html.includes('zona general');
const orden = (html, ...w) => w.every((x, i) => i === 0 || html.indexOf(w[i - 1]) < html.indexOf(x));
_dcimSel = {site: 's', room: ''};
_dcimTreeOpen = new Set(['s']);
const tree = _dcimNavRooms(site);
__out.tree = [sinZona(tree), orden(tree, 'CPD', 'Planta 0', 'Expediciones', 'Planta 1'),
              tree.includes('ss-tree-sub2')];
const detail = _dcimDetailRooms(site);
__out.detail = [sinZona(detail), orden(detail, 'CPD', 'Planta 0', 'R09', 'Expediciones', 'Planta 1'),
                detail.includes('_dcsOpen(&quot;s&quot;,&quot;f0&quot;)') || detail.includes("_dcsOpen(\"s\",\"f0\")")];
const list = _dcimListRooms(site);
__out.list = [sinZona(list), orden(list, 'CPD', 'Planta 0', 'R09', 'Expediciones')];
const cards = _dcimCardRooms(site);
__out.cards = [sinZona(cards), orden(cards, 'CPD', 'Planta 0', 'Expediciones', 'Planta 1')];
_dcimTableGroup = 'tree'; _dcimTableKind = '';
_dcimFold = new Set();
const rows = _dcimTableRows([site]);
__out.table = rows.map(r => [r.kind, r.name, r.depth]);
_dcimTableGroup = 'none';
__out.tableFlat = _dcimTableRows([site]).filter(r => r.kind !== 'rack').map(r => [r.kind, r.name, r.where]);

// ── Searching hides an empty floor ──────────────────────────────────────────────
_dcimQuery = 'Expediciones';
__out.searched = _dcimByFloor(site).floors.map(p => p.floor.uid);
_dcimQuery = '';
"""


@pytest.fixture(scope='module')
def app():
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
    return c


@pytest.fixture(scope='module')
def out(app):
    """One `node` run for the whole module: starting it costs more than looking."""
    return node_run(panel_bundle(app), _PROBE)


class TestTheSplit:
    def test_rooms_on_no_floor_stay_first(self, out):
        assert out['loose'] == ['cpd']

    def test_each_floor_lowest_first_with_its_area_and_rooms(self, out):
        assert out['floors'] == [['f0', 'z0', ['exp'], 'z0'], ['f1', '', [], 'floor-f1']]

    def test_a_floor_adds_up_its_area_and_its_rooms(self, out):
        assert out['totals']['racks'] == 3 and out['totals']['rooms'] == 1
        assert out['state'] == 'error', 'the worst of what is on it'

    def test_the_general_area_is_not_a_room(self, out):
        assert out['siteRooms'] == 2


class TestEveryLayoutSaysTheSame:
    def test_the_tree(self, out):
        assert out['tree'] == [True, True, True]

    def test_the_detail(self, out):
        assert out['detail'] == [True, True, True]

    def test_the_list(self, out):
        assert out['list'] == [True, True]

    def test_the_cards(self, out):
        assert out['cards'] == [True, True]

    def test_the_table_by_tree(self, out):
        assert out['table'] == [
            ['site', 'Mirasol', 0],
            ['room', 'CPD', 1], ['rack', 'R01', 2],
            ['floor', 'Planta 0', 1], ['rack', 'R09', 2],
            ['room', 'Expediciones', 2], ['rack', 'R02', 3], ['rack', 'R03', 3],
            ['floor', 'Planta 1', 1],
        ]

    def test_the_table_flat_says_the_floor_in_where(self, out):
        assert ['room', 'Expediciones', 'Mirasol › Planta 0'] in out['tableFlat']
        assert not any(k == 'floor' or 'zona general' in n for k, n, _ in out['tableFlat'])


class TestSearching:
    def test_a_floor_with_nothing_found_is_hidden(self, out):
        assert out['searched'] == ['f0']


class TestTheListingSaysTheArea:
    def test_each_floor_carries_its_general_area(self, app):
        r = app.post('/api/v1/dcim/sites', json={'name': 'S1'})
        uid = json.loads(r.data)['uid']
        f = json.loads(app.post('/api/v1/dcim/floors',
                                json={'site_uid': uid, 'name': 'P0', 'level': 0}).data)['uid']
        area = json.loads(app.post(f'/api/v1/dcim/floors/{f}/area').data)['room_uid']
        sites = json.loads(app.get('/api/v1/dcim/sites').data)['sites']
        planta = next(s for s in sites if s['uid'] == uid)['floor_list'][0]
        assert planta['area_uid'] == area
