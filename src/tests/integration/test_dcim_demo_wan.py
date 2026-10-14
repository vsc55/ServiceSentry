#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo's WAN: four sites on the map and the links between them.

Asked for: two links between «Demo» and «Demo · Respaldo» for HA, both visible and one of them
DOWN, so the map shows what a link in error looks like; and two more sites —Texas and Puerto
Rico— so the map holds a small WAN. A link's state is the worst of the items that end it
(`links_roll`): the IPsec used to end on no item at all and read «unwatched», never down.
"""

import pytest

from lib.core.dcim import demo
from lib.core.dcim import service as dcim_svc
from lib.core.dcim.store import DcimStore
from lib.db import get_connector


def _store(path):
    return DcimStore(get_connector(None, default_sqlite_path=str(path / 'data.db')))


@pytest.fixture(scope='module')
def wan(tmp_path_factory):
    path = tmp_path_factory.mktemp('wan')
    store = _store(path)
    made = demo.build(store, var_dir=str(path))
    return store, made


def _rolled(store) -> dict:
    """Every link with its state, as the board computes it: the items' demo state."""
    estados = {}
    for site in store.sites.list():
        for room in store.rooms_of(site['uid']):
            for rack in store.racks_of(room['uid']):
                for it in store.items_of(rack['uid']):
                    estados[it['uid']] = dcim_svc.item_state(it, {})
    return dcim_svc.links_roll(store.links_of(), store.sites.list(), estados)


def _between(rolled, a, b) -> list:
    return [l for l in rolled['links'] if {l['a_site'], l['b_site']} == {a, b}]


class TestTheSites:

    def test_six_sites_with_texas_and_puerto_rico(self, wan):
        store, made = wan
        assert made['sites'] == 6 and len(demo.find(store)) == 6
        tx, pr = store.sites.get(made['site_tx']), store.sites.get(made['site_pr'])
        assert 25.8 <= float(tx['lat']) <= 36.5 and -106.7 <= float(tx['lon']) <= -93.5
        assert tx['timezone'] == 'America/Chicago' and tx['name'] == 'Demo · Texas'
        assert 17.8 <= float(pr['lat']) <= 18.6 and -67.3 <= float(pr['lon']) <= -65.2
        assert pr['timezone'] == 'America/Puerto_Rico' and pr['name'] == 'Demo · Puerto Rico'
        for site in (tx, pr):
            assert site['address']
            rooms = store.rooms_of(site['uid'])
            assert len(rooms) == 1
            racks = store.racks_of(rooms[0]['uid'])
            roles = sorted(i['role'] for k in racks for i in store.items_of(k['uid']))
            assert {'router', 'firewall', 'switch', 'server'} <= set(roles)
            assert {s['kind'] for s in store.sources_of(site['uid'])} == {'mains', 'ups'}

    def test_every_small_site_is_watched_mostly_ok(self, wan):
        store, made = wan
        for key in demo.BRANCHES:
            if key == 'site_za':
                continue                     # offline on purpose: see TestFarSites
            room = store.rooms_of(made[key])[0]
            activos = [i for k in store.racks_of(room['uid']) for i in store.items_of(k['uid'])
                       if i['role'] != 'pdu']
            estados = [dcim_svc.item_state(i, {}) for i in activos]
            assert '' not in estados, key
            assert estados.count('ok') >= len(estados) - 1, key


class TestTheLinks:

    def test_demo_and_its_recovery_centre_two_links_mpls_up_and_ipsec_down(self, wan):
        store, made = wan
        dos = _between(_rolled(store), made['site'], made['site_dr'])
        assert sorted((l['kind'], l['state']) for l in dos) == [('ipsec', 'error'),
                                                                ('mpls', 'ok')]
        ipsec = next(l for l in dos if l['kind'] == 'ipsec')
        fw = store.items.get(ipsec['b_item'])
        assert fw['label'] == 'FW-DR' and fw['demo_state'] == 'error'
        assert fw['demo_reason'] == demo.texts('es_ES')['why_ipsec_down']
        assert store.items.get(ipsec['a_item'])['role'] == 'firewall'

    def test_texas_by_mpls_and_puerto_rico_by_sdwan(self, wan):
        store, made = wan
        rolled = _rolled(store)
        tx = _between(rolled, made['site'], made['site_tx'])
        pr = _between(rolled, made['site_tx'], made['site_pr'])
        assert [(l['kind'], l['state']) for l in tx] == [('mpls', 'ok')]
        assert [(l['kind'], l['state']) for l in pr] == [('sdwan', 'warning')]
        assert not _between(rolled, made['site'], made['site_pr'])

    def test_no_demo_link_is_left_unwatched(self, wan):
        store, _made = wan
        rolled = _rolled(store)
        assert len(rolled['links']) == 7
        assert all(l['a_item'] and l['b_item'] and l['state'] for l in rolled['links'])

    def test_the_board_carries_the_links_with_their_state(self, tmp_path):
        """The map draws what `/api/v1/dcim/board` hands it: the IPsec in error there."""
        pytest.importorskip('flask')
        from lib.web_admin import WebAdmin                           # noqa: PLC0415
        from tests.conftest import _login                            # noqa: PLC0415
        cfg, var = tmp_path / 'cfg', tmp_path / 'var'
        cfg.mkdir()
        var.mkdir()
        (cfg / 'config.json').write_text('{}', encoding='utf-8')
        wa = WebAdmin(str(cfg), 'admin', 'secret', str(var),
                      pw_require_upper=False, pw_require_digit=False)
        wa._csrf_enabled = False
        wa.app.config['TESTING'] = True
        made = demo.build(wa._dcim_store, var_dir=str(var))
        c = wa.app.test_client()
        _login(c)
        links = c.get('/api/v1/dcim/board').get_json()['links']
        got = sorted((l['kind'], l['state']) for l in links
                     if {l['a_site'], l['b_site']} == {made['site'], made['site_dr']})
        assert got == [('ipsec', 'error'), ('mpls', 'ok')]
        assert sorted(l['state'] for l in links) == ['error', 'error', 'ok', 'ok', 'ok', 'ok',
                                                     'warning']



class TestFarSites:
    """South Africa, entirely offline, and Taiwan, fine with two paths."""

    def test_south_africa_is_in_johannesburg_and_entirely_down(self, wan):
        store, made = wan
        za = store.sites.get(made['site_za'])
        assert -27.0 <= float(za['lat']) <= -25.5 and 27.5 <= float(za['lon']) <= 28.6
        assert za['timezone'] == 'Africa/Johannesburg'
        room = store.rooms_of(za['uid'])[0]
        activos = [i for k in store.racks_of(room['uid']) for i in store.items_of(k['uid'])
                   if i['role'] != 'pdu']
        assert activos and {dcim_svc.item_state(i, {}) for i in activos} == {'error'}
        assert {i['demo_reason'] for i in activos} == {demo.texts('es_ES')['why_site_offline']}

    def test_south_africa_hangs_off_one_link_and_it_is_down(self, wan):
        store, made = wan
        rolled = _rolled(store)
        suyos = [l for l in rolled['links'] if made['site_za'] in (l['a_site'], l['b_site'])]
        assert [(l['kind'], l['state']) for l in suyos] == [('mpls', 'error')]
        assert any(a['kind'] == 'single_link' and a['site'] == made['site_za']
                   for a in rolled['warnings'])

    def test_taiwan_has_two_paths_both_up(self, wan):
        store, made = wan
        tw = store.sites.get(made['site_tw'])
        assert 24.5 <= float(tw['lat']) <= 25.5 and 121.0 <= float(tw['lon']) <= 122.0
        assert tw['timezone'] == 'Asia/Taipei'
        rolled = _rolled(store)
        assert [(l['kind'], l['state']) for l in _between(rolled, made['site'], made['site_tw'])]             == [('mpls', 'ok')]
        assert [(l['kind'], l['state']) for l in _between(rolled, made['site_tx'], made['site_tw'])]             == [('sdwan', 'ok')]



class TestEveryRoomHasADoor:

    def test_every_room_of_every_site_has_a_door(self, wan):
        """The small sites' technical rooms had none: a closed box in the plan and the walk.
        A floor's general area (its corridors) is the one room without a door of its own."""
        store, made = wan
        areas = {f.get('area_uid') for k in demo.UID_KEYS
                 for f in store.floors_of(made[k]) if f.get('area_uid')}
        sin = [(k, r['name']) for k in demo.UID_KEYS for r in store.rooms_of(made[k])
               if r['uid'] not in areas
               and not any(f['kind'] == 'door' for f in store.features_of(r['uid']))]
        assert not sin, sin


class TestRemovingAndBuildingAgain:

    def test_removal_takes_all_six_sites_and_their_links(self, tmp_path):
        """Built in English, removed: the small sites are found by their names in every
        language, so none is left behind with its links."""
        store = _store(tmp_path)
        made = demo.build(store, var_dir=str(tmp_path), lang='en_EN')
        assert store.sites.get(made['site_dr'])['name'] == 'Demo · DR'
        assert demo.remove(store, var_dir=str(tmp_path)) == 6
        assert not store.sites.list() and not store.links_of()
        assert not store.rooms.list() and not store.racks.list() and not store.sources.list()

    def test_rebuilding_does_not_duplicate_them(self, tmp_path):
        store = _store(tmp_path)
        demo.build(store, var_dir=str(tmp_path))
        with pytest.raises(demo.DemoError):
            demo.build(store, var_dir=str(tmp_path))
        again = demo.build(store, var_dir=str(tmp_path), replace=True)
        names = sorted(s['name'] for s in store.sites.list())
        assert names == sorted(['Demo', 'Demo · Respaldo', 'Demo · Texas', 'Demo · Puerto Rico',
                                'Demo · Sudáfrica', 'Demo · Taiwán'])
        assert len(store.links_of()) == 7 and again['links'] == 7
