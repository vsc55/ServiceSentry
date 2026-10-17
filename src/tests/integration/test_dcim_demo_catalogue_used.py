#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""On a clean installation the demo brings, and uses, a model of everything it places.

Reported: «you only made demo devices — no racks, no modules. Make all of it and use it in the
demo, so it is 100 % working on a clean install; the demo companies' offices use those
elements». Before, a clean install with the demo had 45 racks of no model, 85 strips, 50
blanking panels, a shelf and four UPS of no model, the offices' 214 devices of no model, 14
parts written by hand, no template and no platform.

What is checked, over a demo installed on an EMPTY panel (no library imported, no basics
brought in): each of the four trees has demo models, every one complete for its class —its
pictures, its ports typed and placed, its physical and life data—; every rack, every placed
device and every fitted part points at a demo model of the right tree; the servers' and the
switches' bays are filled from their templates, which name a platform; the optics are in the
cages the fibre reaches; both companies and all six sites use them; the library counts each
model placed; installing twice changes nothing and removing leaves no demo row behind.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_ISO = re.compile(r'^\d{4}-\d{2}-\d{2}$')
#: What a room holds and has no model by decision: a wall outlet's and a socket's jacks are
#: chosen outlet by outlet (`jacks`), so the catalogue is not where their ports come from.
_NO_MODEL = ('outlet', 'power_outlet')


def _panel():
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    return wa, var


@pytest.fixture(scope='module')
def built():
    from lib.core.dcim import demo                                  # noqa: PLC0415
    from lib.core.dcim.catalog import CatalogStore                  # noqa: PLC0415
    wa, var = _panel()
    cat = CatalogStore(wa._dcim_store._db)
    assert cat.count() == 0                                         # a clean install
    made = demo.build(wa._dcim_store, var_dir=var, lang='es_ES')
    c = wa.app.test_client()
    _login(c)
    return wa, c, made, cat


def _demo_rows(cat) -> dict:
    from lib.core.dcim import demo                                  # noqa: PLC0415
    return {r['uid']: r for r in cat.list('source = ?', (demo.SOURCE,))}


def _by_key(cat) -> dict:
    from lib.core.dcim import demo_faces                            # noqa: PLC0415
    por_nombre = {r['model']: r for r in _demo_rows(cat).values()}
    return {k: por_nombre[demo_faces.name_of(k)] for k in demo_faces.every()}


def _connectors() -> dict:
    with io.open(os.path.join(_SRC, 'lib', 'core', 'dcim', 'data', 'connectors.json'),
                 encoding='utf-8') as fh:
        return {x['id']: x for x in json.load(fh)['connectors']}


def _demo_items(store, made) -> list:
    from lib.core.dcim import demo                                  # noqa: PLC0415
    out = []
    for site in (made[k] for k in demo.UID_KEYS):
        for room in store.rooms_of(site):
            for rack in store.racks_of(room['uid']):
                out += [dict(i, _site=site, _rack=rack) for i in store.items_of(rack['uid'])]
            out += [dict(i, _site=site, _rack=None) for i in store.items_in_room(room['uid'])]
    return out


class TestEveryTreeHasCompleteModels:

    def test_each_tree_has_its_demo_models(self, built):
        from lib.core.dcim import demo_faces                        # noqa: PLC0415
        _wa, _c, _made, cat = built
        filas = _demo_rows(cat).values()
        por_arbol = {}
        for r in filas:
            por_arbol.setdefault(r['tree'], set()).add(r['model'])
        for arbol, claves in demo_faces.TREES:
            assert claves and por_arbol.get(arbol) == {demo_faces.name_of(k) for k in claves}, \
                arbol
        assert set(por_arbol) == {'device-types', 'rack-types', 'module-types',
                                  'component-types'}

    def test_every_model_has_its_pictures_served(self, built):
        """A front for every model; a rear for what has one —a device, a cabinet—; and the
        media route serves each as an SVG."""
        _wa, c, _made, cat = built
        for key, r in _by_key(cat).items():
            nombres = [r['front_image']]
            if r['tree'] in ('device-types', 'rack-types'):
                nombres.append(r['rear_image'])
            assert all(nombres), (key, nombres)
            for nombre in nombres:
                resp = c.get('/api/v1/dcim/media/' + nombre)
                assert resp.status_code == 200 and resp.mimetype == 'image/svg+xml', key

    def test_ports_and_bays_are_typed_and_placed(self, built):
        """Where the class has ports —a strip's outlets, a UPS's, a supply's inlet, an optic's
        LC, a card's cages— each is of a type its family knows and is placed on its picture."""
        _wa, _c, _made, cat = built
        conocidos = _connectors()
        # A blanking panel, a cable manager, a shelf and a fan have no port to have.
        sin_puertos = {'blank', 'cablemgr', 'shelf', 'fansrv', 'fantray'}
        for key, r in _by_key(cat).items():
            if r['tree'] in ('rack-types', 'component-types') or key in sin_puertos:
                assert not r['port_list'], key
                continue
            assert r['port_list'], key
            for fam, filas in r['port_list'].items():
                for p in filas:
                    assert fam in conocidos[p['type']]['families'], (key, fam, p)
            assert r['ports_total'] and r['ports_placed'] == r['ports_total'], key
            assert r['bays_placed'] == r['bays_total'], key

    def test_the_power_is_what_the_class_takes_and_gives(self, built):
        """A strip gives as many outlets as its PDU row says and takes one inlet; a UPS too; a
        supply module takes its inlet; a PoE device says what it draws on its port."""
        _wa, _c, _made, cat = built
        r = _by_key(cat)
        cuenta = (lambda k, fam, typ: r[k]['ports'].get(fam, {}).get(typ, 0))
        assert cuenta('pdu0u32', 'power-outlets', 'iec-60320-c13') == 18
        assert cuenta('pdu0u32', 'power-outlets', 'iec-60320-c19') == 6
        assert cuenta('pdu0u3p', 'power-ports', 'iec-60309-3p-n-e-4h') == 1
        assert cuenta('pdu1u', 'power-outlets', 'iec-60320-c13') == 10
        assert cuenta('ups3k', 'power-ports', 'iec-60320-c20') == 1
        assert cuenta('psu2000', 'power-ports', 'iec-60320-c20') == 1
        assert cuenta('sfp10lr', 'front-ports', 'lc-upc') == 1
        assert cuenta('ocp25', 'interfaces', '25gbase-x-sfp28') == 2
        for key, f in r.items():
            if f['tree'] not in ('device-types', 'module-types') or not f['is_powered']:
                continue
            if f['tree'] == 'module-types' and f['kind'] != 'psu':
                continue                     # a fan, a card, an optic: fed through its bay
            if f['power_type'] == 'poe':
                assert any('power-in' in (p.get('signals') or []) and p.get('watts')
                           for p in f['port_list']['interfaces']), key
                continue
            entradas = f['port_list'].get('power-ports') or []
            assert entradas and all(p.get('volts') and p.get('watts') for p in entradas), key

    def test_physical_and_life_data_of_every_class(self, built):
        """A cabinet with its outer size, its frame, its weight and its load; everything else
        with its size and weight; all with part number, two-line description and the dates of
        its life in order."""
        from lib.core.dcim import demo_faces                        # noqa: PLC0415
        _wa, _c, _made, cat = built
        for key, r in _by_key(cat).items():
            e = r['extra']
            assert r['part_number'] and '\n' in r['description'] and r['brand_uid'], key
            if r['tree'] == 'rack-types':
                _n, u, w, d, h, forma = demo_faces.RACKS[key]
                assert r['u_tenths'] == u * 10 and e['form_factor'] == forma, key
                assert (e['outer_width'], e['outer_depth'], e['outer_height']) == (w, d, h), key
                assert e['outer_unit'] == 'mm' and e['width'] == 19
                assert 0 < e['weight'] < e['max_weight'] and e['mounting_depth'] < d, key
            else:
                for campo in ('width_mm', 'height_mm', 'depth_mm', 'weight', 'warranty_years'):
                    assert float(e.get(campo) or 0) > 0, (key, campo)
            if r['tree'] == 'component-types':
                assert r['kind'] and (r['size'] or r['kind'] in ('cpu', 'battery')), key
            fechas = [e.get(k) for k in ('launched', 'end_of_sale', 'eol')]
            assert all(f and _ISO.match(f) for f in fechas), (key, fechas)
            assert fechas[0] < fechas[1] <= fechas[2], (key, fechas)

    def test_no_demo_model_is_flagged_by_the_library_summary(self, built):
        """The Summary's data-quality figures, for the demo's models: none without a picture,
        none a device without ports (a blanking panel or a shelf has none to have), none with
        a brand written and no brand record, none written by hand."""
        _wa, c, _made, _cat = built
        for filtro in ('img=none', 'ports=none', 'brand_uid=none'):
            d = c.get('/api/v1/dcim/catalog?limit=200&' + filtro).get_json()
            assert not [t['model'] for t in d['types'] if t.get('source') == 'demo'], filtro
        d = c.get('/api/v1/dcim/catalog?limit=200&source=manual').get_json()
        assert not [t for t in d['types'] if t.get('manufacturer') == 'Demo']


class TestTheDemoUsesThem:

    def test_every_rack_is_a_demo_cabinet_of_its_size(self, built):
        from lib.core.dcim import demo_faces                        # noqa: PLC0415
        wa, _c, made, cat = built
        store = wa._dcim_store
        modelos = _demo_rows(cat)
        todos = store.racks.list()
        assert len(todos) == 45
        for r in todos:
            m = modelos.get(r['type_uid'])
            assert m and m['tree'] == 'rack-types', r['name']
            key = next(k for k in demo_faces.RACKS if demo_faces.name_of(k) == m['model'])
            _n, u, w, d, _h, _f = demo_faces.RACKS[key]
            assert (r['u_height'], r['width_mm'], r['depth_mm']) == (u, w, d), r['name']

    def test_every_placed_device_is_a_demo_model(self, built):
        """In a rack —servers, switches, strips, UPS, blanking panels, cable managers, the
        shelf— and in a room —PCs, phones, access points, cameras, displays, printers—."""
        wa, _c, made, cat = built
        modelos = _demo_rows(cat)
        sin = []
        for it in _demo_items(wa._dcim_store, made):
            if it['role'] in _NO_MODEL and not it['_rack']:
                continue
            m = modelos.get(it['type_uid'])
            if not m or m['tree'] != 'device-types':
                sin.append((it['role'], it['label']))
        assert not sin, sin[:20]

    def test_every_strip_and_ups_has_the_model_its_row_says(self, built):
        """A PDU row's outlets are its strip's; a vertical strip is in a rack channel, a 1U one
        in a U; a three-phase strip feeds the GPU racks."""
        wa, _c, made, cat = built
        store = wa._dcim_store
        modelos = _demo_rows(cat)
        for it in _demo_items(store, made):
            if it['role'] != 'pdu':
                continue
            m = modelos[it['type_uid']]
            assert (it['placement'] == 'side') == (m['u_tenths'] == 0), it['label']
            for pdu in store.pdus.list('item_uid = ?', (it['uid'],)):
                assert pdu['outlets'] == sum(m['ports']['power-outlets'].values()), it['label']
                if pdu['capacity_w'] > 7400:
                    assert m['model'].startswith('DM-PDU0-3P'), it['label']

    def test_every_fitted_part_is_a_demo_module_or_component(self, built):
        wa, _c, _made, cat = built
        modelos = _demo_rows(cat)
        partes = wa._dcim_store.parts.list()
        assert len(partes) > 1000
        for p in partes:
            m = modelos.get(p['type_uid'])
            assert m and m['tree'] in ('module-types', 'component-types'), p
            assert p['model'] == m['model'] and p['brand'] == 'Demo', p

    def test_the_servers_bays_are_filled_from_their_templates(self, built):
        """Every demo server, switch, router, firewall, array and mini PC was created from its
        template: its parts are the template's, each in bays its model has —the CPU sockets,
        the DIMM slots, the drive bays, the supplies, the fans—."""
        from lib.core.dcim.builds import BuildStore                 # noqa: PLC0415
        from lib.core.dcim import demo                              # noqa: PLC0415
        wa, _c, made, cat = built
        store = wa._dcim_store
        modelos = _demo_rows(cat)
        builds = BuildStore(store._db)
        por_modelo = {b['type_uid']: b for b in builds.list()}
        con_plantilla = {cat.get(b['type_uid'])['model'] for b in builds.list()}
        assert len(con_plantilla) == len(demo.BUILDS)
        vistos = 0
        for it in _demo_items(store, made):
            m = modelos.get(it['type_uid'])
            if not m or m['model'] not in con_plantilla or it['label'] == 'NVR-01':
                continue
            b = por_modelo[it['type_uid']]
            assert it['build_uid'] == b['uid'], it['label']
            mias = sorted((p['type_uid'], p['slot'], p['qty']) for p in store.parts_of([it['uid']])
                          if p['kind'] != 'transceiver')
            assert mias == sorted((p['type_uid'], p['slot'], p['qty'])
                                  for p in builds.parts_of(b['uid'])), it['label']
            bahias = {x['name'] for x in m['port_list'].get('module-bays', ())}
            for p in store.parts_of([it['uid']]):
                if p['kind'] != 'transceiver':
                    assert set(p['slot'].split(', ')) <= bahias, (it['label'], p['slot'])
            vistos += 1
        assert vistos > 250
        r2 = next(r for r in modelos.values() if r['model'] == 'DM-R2 Server 2U')
        srv = next(i for i in _demo_items(store, made) if i['type_uid'] == r2['uid'])
        clases = {p['kind']: p['qty'] for p in store.parts_of([srv['uid']])}
        assert clases == {'cpu': 2, 'memory': 16, 'ssd': 2, 'psu': 2, 'fan': 6, 'nic': 1} \
            or clases.get('memory') == 16 and clases.get('cpu') == 2 and clases.get('psu') == 2

    def test_every_template_names_its_model_and_a_platform(self, built):
        from lib.core.dcim.builds import BuildStore                 # noqa: PLC0415
        from lib.core.dcim.platforms import PlatformStore           # noqa: PLC0415
        from lib.core.dcim import demo                              # noqa: PLC0415
        wa, _c, _made, cat = built
        modelos = _demo_rows(cat)
        plats = {p['uid']: p for p in PlatformStore(wa._dcim_store._db).list()}
        marca = cat.brands.by_slug('demo')
        for b in BuildStore(wa._dcim_store._db).list():
            assert modelos[b['type_uid']]['tree'] == 'device-types', b['name']
            p = plats[b['platform_uid']]
            assert p['extra'].get('eol'), b['name']
            if p['name'] in demo.PLATFORMS:
                assert p['brand_uid'] == marca['uid'], p['name']
            assert b['front_image'] and b['rear_image'], b['name']

    def test_the_optics_are_in_the_cages_the_fibre_reaches(self, built):
        """Every fibre end in an SFP+ cage of a demo device has its optic fitted in that port
        —short reach on OM4, long reach on OS2— and no optic sits in a port nobody cabled."""
        wa, _c, made, cat = built
        store = wa._dcim_store
        modelos = _demo_rows(cat)
        items = {i['uid']: i for i in _demo_items(store, made)}
        esperado = set()
        for c in store.cables_of(list(items)):
            if c['kind'] != 'fiber':
                continue
            for lado in ('a', 'b'):
                m = modelos.get(items[c[lado + '_item']]['type_uid']) or {}
                cajas = {p['name'] for p in m.get('port_list', {}).get('interfaces', ())
                         if p['type'] in ('10gbase-x-sfpp', '1000base-x-sfp')}
                if c[lado + '_port'] in cajas:
                    optica = 'SR' if c['category'] in ('om3', 'om4') else 'LR'
                    esperado.add((c[lado + '_item'], c[lado + '_port'], optica))
        puesto = set()
        for p in store.parts.list("kind = 'transceiver'"):
            optica = modelos[p['type_uid']]['model'].split('-')[2][:2]
            for boca in p['slot'].split(', '):
                puesto.add((p['item_uid'], boca, optica))
        assert esperado and puesto == esperado

    def test_both_companies_and_all_six_sites_use_them(self, built):
        """Every site has racks of a demo cabinet holding demo devices with their parts; the
        customer's rented racks too; the main site's offices have their PCs and phones."""
        from lib.core.dcim import demo                              # noqa: PLC0415
        wa, _c, made, cat = built
        store = wa._dcim_store
        modelos = _demo_rows(cat)
        items = _demo_items(store, made)
        for k in demo.UID_KEYS:
            suyos = [i for i in items if i['_site'] == made[k]]
            assert suyos and all(i['_rack'] is None or modelos.get(i['_rack']['type_uid'])
                                 for i in suyos), k
            assert {modelos[i['type_uid']]['tree'] for i in suyos if i['type_uid']} \
                == {'device-types'}, k
            assert store.parts_of([i['uid'] for i in suyos]), k
            for rol in ('blank', 'patch_panel', 'server', 'switch', 'router', 'firewall', 'pdu'):
                assert any(i['role'] == rol for i in suyos), (k, rol)
        cliente = next(o for o in store.orgs.list()
                       if o['name'] == demo.texts('es_ES')['org_customer'])
        alquilados = [s for (scope, s), org in store.owners_map().items()
                      if scope == 'rack' and org == cliente['uid']]
        assert len(alquilados) == 2
        for rack in alquilados:
            dentro = store.items_of(rack)
            assert dentro and all(modelos.get(i['type_uid']) for i in dentro)
            assert store.parts_of([i['uid'] for i in dentro])
        oficina = [i for i in items if i['_site'] == made['site'] and not i['_rack']]
        roles = {i['role'] for i in oficina if modelos.get(i['type_uid'])}
        assert {'pc', 'phone', 'ap', 'camera', 'display', 'printer'} <= roles

    def test_the_library_counts_every_demo_model_placed(self, built):
        """«Placed» > 0 for every demo model of every tree: the cabinets by their racks, the
        devices by their items, the modules and components by the parts fitted."""
        _wa, c, _made, _cat = built
        d = c.get('/api/v1/dcim/catalog?source=demo&placed=1&limit=200').get_json()
        filas = [t for t in d['types'] if t['source'] == 'demo']
        assert len(filas) == len(_demo_rows(_cat))
        assert not [t['model'] for t in filas if not t['placed']]
        resumen = c.get('/api/v1/dcim/catalog/summary').get_json()
        assert resumen


class TestTheRackModelThroughTheApi:

    def test_a_rack_keeps_a_cabinet_model_and_drops_anything_else(self, built):
        wa, c, made, cat = built
        r = _by_key(cat)
        sala = wa._dcim_store.rooms_of(made['site_tx'])[0]['uid']
        uid = c.post('/api/v1/dcim/racks', json={'room_uid': sala, 'name': 'X1',
                                                 'type_uid': r['rack610']['uid']}).get_json()['uid']
        assert wa._dcim_store.racks.get(uid)['type_uid'] == r['rack610']['uid']
        c.put('/api/v1/dcim/racks/' + uid, json={'type_uid': r['server']['uid']})
        assert wa._dcim_store.racks.get(uid)['type_uid'] == r['rack610']['uid']
        c.put('/api/v1/dcim/racks/' + uid, json={'type_uid': 'nope'})
        assert wa._dcim_store.racks.get(uid)['type_uid'] == r['rack610']['uid']
        c.put('/api/v1/dcim/racks/' + uid, json={'type_uid': ''})
        assert wa._dcim_store.racks.get(uid)['type_uid'] == ''
        wa._dcim_store.racks.delete(uid)


class TestInstallTwiceAndRemove:

    def test_installing_twice_is_refused_and_writes_nothing(self):
        from lib.core.dcim import demo                              # noqa: PLC0415
        from lib.core.dcim.builds import BuildStore                 # noqa: PLC0415
        from lib.core.dcim.catalog import CatalogStore              # noqa: PLC0415
        wa, var = _panel()
        store = wa._dcim_store
        demo.build(store, var_dir=var)
        cat = CatalogStore(store._db)
        antes = (cat.count(), len(BuildStore(store._db).list()), len(store.parts.list()))
        with pytest.raises(demo.DemoError):
            demo.build(store, var_dir=var)
        assert (cat.count(), len(BuildStore(store._db).list()), len(store.parts.list())) == antes

    def test_remove_leaves_no_demo_row_and_twice_is_a_no_op(self):
        from lib.core.dcim import demo                              # noqa: PLC0415
        from lib.core.dcim.builds import BuildStore                 # noqa: PLC0415
        from lib.core.dcim.catalog import CatalogStore              # noqa: PLC0415
        from lib.core.dcim.platforms import PlatformStore           # noqa: PLC0415
        wa, var = _panel()
        store = wa._dcim_store
        demo.build(store, var_dir=var)
        assert demo.remove(store, var_dir=var) == 6
        cat = CatalogStore(store._db)
        assert not cat.list('source = ?', (demo.SOURCE,))
        assert not BuildStore(store._db).list()
        assert not [p for p in PlatformStore(store._db).list() if p['name'] in demo.PLATFORMS]
        assert not cat.brands.by_slug('demo')
        for t in (store.racks, store.items, store.parts, store.pdus, store.cables):
            assert not t.list(), t
        assert demo.remove(store, var_dir=var) == 0
        # The real systems the servers ran stay, as the access control models do.
        assert {p['name'] for p in PlatformStore(store._db).list()} >= set(demo.REAL_PLATFORMS)

    def test_remove_keeps_a_cabinet_model_a_user_rack_uses(self):
        from lib.core.dcim import demo                              # noqa: PLC0415
        from lib.core.dcim.catalog import CatalogStore              # noqa: PLC0415
        wa, var = _panel()
        store = wa._dcim_store
        demo.build(store, var_dir=var)
        cat = CatalogStore(store._db)
        armario = next(r for r in cat.list('source = ?', (demo.SOURCE,))
                       if r['tree'] == 'rack-types')
        sitio = store.sites.create({'name': 'Real'})
        sala = store.rooms.create({'site_uid': sitio, 'name': 'Sala'})
        store.racks.create({'room_uid': sala, 'name': 'R', 'type_uid': armario['uid']})
        demo.remove(store, var_dir=var)
        assert [r['uid'] for r in cat.list('source = ?', (demo.SOURCE,))] == [armario['uid']]
        assert cat.brands.by_slug('demo')
