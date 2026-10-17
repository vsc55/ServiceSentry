#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo's own catalogue models are complete, as real data of their class would be.

Reported: «Demo DM-KVM8 KVM» had no rear picture and no ports. Asked for: every model the demo
installs comes with its front and rear pictures —and pictures of its inside where a real one
would want them, a server's motherboard—, the right number and types of ports with each one
placed on its picture, its size, weight and power, and the dates of its life.

What is checked, for EVERY demo model, over a demo installed in a panel: both faces and every
view have a picture the media route serves as an SVG; every port is of a type the connector
catalogue knows for its family; every port and bay is placed, on a face the model has, inside
the picture; the physical and life-cycle fields are filled and coherent; the pictures on disk
are what `demo_draw` draws, so a socket cannot move in one and not in the other.
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


@pytest.fixture(scope='module')
def built():
    from lib.core.dcim import demo                                  # noqa: PLC0415
    from lib.core.dcim.catalog import CatalogStore                  # noqa: PLC0415
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    demo.build(wa._dcim_store, var_dir=var, lang='es_ES')
    c = wa.app.test_client()
    _login(c)
    cat = CatalogStore(wa._dcim_store._db)
    modelos = {r['model']: r for r in cat.list('source = ?', (demo.SOURCE,))}
    return wa, c, modelos


def _connectors() -> dict:
    with io.open(os.path.join(_SRC, 'lib', 'core', 'dcim', 'data', 'connectors.json'),
                 encoding='utf-8') as fh:
        return {x['id']: x for x in json.load(fh)['connectors']}


def _each(modelos):
    """The fifteen devices `demo_draw` draws itself —servers, switches, panels…—: the rest of
    the catalogue (the cabinets, the power, the room's devices, the modules and components) is
    checked class by class in `test_dcim_demo_catalogue_used`."""
    from lib.core.dcim import demo_draw, demo_faces                 # noqa: PLC0415
    for key in demo_draw.DRAWERS:
        yield key, modelos[demo_faces.MODELS[key][0]]


class TestEveryDemoModelIsComplete:

    def test_every_model_of_the_demo_is_installed(self, built):
        from lib.core.dcim import demo_faces                        # noqa: PLC0415
        _wa, _c, modelos = built
        assert set(modelos) == {demo_faces.name_of(k) for k in demo_faces.every()}

    def test_front_rear_and_views_have_pictures_the_panel_serves(self, built):
        """The reported one: the KVM had no rear. Every face and every view, served as SVG."""
        _wa, c, modelos = built
        for key, r in _each(modelos):
            nombres = [r['front_image'], r['rear_image']] + [v['image'] for v in r['views']]
            assert all(nombres), (key, nombres)
            for nombre in nombres:
                resp = c.get('/api/v1/dcim/media/' + nombre)
                assert resp.status_code == 200, (key, nombre)
                assert resp.mimetype == 'image/svg+xml'
                assert resp.data.lstrip().startswith(b'<svg') and b'viewBox' in resp.data

    def test_the_kvm_and_the_servers_show_their_inside(self, built):
        """An extra view where a real one would want it: the board of each server, the
        controllers of the array, the KVM drawer opened."""
        _wa, _c, modelos = built
        for key in ('server', 'gpu', 'node', 'storage', 'kvm', 'mini'):
            r = dict(_each(modelos))[key]
            assert r['views'] and all(v['name'] and v['image'] for v in r['views']), key

    def test_every_port_is_a_known_type_of_its_family(self, built):
        """Only the connector catalogue's types, and each in a family that type belongs to:
        a VGA is a front or rear port, a C14 a power port, a drive bay a module bay."""
        _wa, _c, modelos = built
        conocidos = _connectors()
        for key, r in _each(modelos):
            assert r['ports'] and r['port_list'], key
            for fam, filas in r['port_list'].items():
                for p in filas:
                    tipo = conocidos.get(p['type'])
                    assert tipo, (key, fam, p)
                    assert fam in tipo['families'], (key, fam, p)
            # The counts are the list counted: the two answers cannot disagree.
            for fam, tipos in r['ports'].items():
                assert sum(tipos.values()) == len(r['port_list'][fam]), (key, fam)

    def test_every_port_and_bay_is_placed_on_a_face_it_has(self, built):
        """The badge reads «situados»: all the connectors and all the bays, each on the front,
        the rear or one of its views, inside the picture."""
        _wa, _c, modelos = built
        for key, r in _each(modelos):
            assert r['ports_total'] and r['ports_placed'] == r['ports_total'], key
            assert r['bays_placed'] == r['bays_total'], key
            caras = {'front', 'rear'} | {'v:' + v['id'] for v in r['views']}
            assert set(r['port_map']) == set(r['port_slots']), key
            usadas = {}
            for slot, pos in r['port_map'].items():
                assert pos['f'] in caras, (key, slot, pos)
                assert 0 < pos['x'] < 1 and 0 < pos['y'] < 1, (key, slot, pos)
                # Two sockets in the same spot is a drawing where one hides the other.
                sitio = (pos['f'], round(pos['x'], 3), round(pos['y'], 3))
                assert sitio not in usadas, (key, slot, usadas.get(sitio))
                usadas[sitio] = slot
            # And a patch panel's sides are what they say: front ports on the front.
            for slot, pos in r['port_map'].items():
                fam = slot.split('|', 1)[0]
                if fam in ('front-ports', 'rear-ports'):
                    assert pos['f'] == fam.split('-')[0], (key, slot)

    def test_the_counts_a_real_model_of_each_class_has(self, built):
        """Not "some ports": the ones the class has. A 48-port switch with its uplinks, its
        console and its two supplies; a two-socket server with its bays, DIMMs and risers."""
        _wa, _c, modelos = built
        r = dict(_each(modelos))
        cuenta = (lambda k, fam, typ: r[k]['ports'].get(fam, {}).get(typ, 0))
        assert cuenta('tor', 'interfaces', '1000base-t') == 49           # 48 + management
        assert cuenta('tor', 'interfaces', '10gbase-x-sfpp') == 4
        assert cuenta('tor', 'console-ports', 'rj-45') == 1
        assert cuenta('tor', 'power-ports', 'iec-60320-c14') == 2
        assert cuenta('access', 'interfaces', '1000base-t') == 24
        assert cuenta('core', 'interfaces', '10gbase-x-sfpp') == 48
        assert cuenta('core', 'interfaces', '100gbase-x-qsfp28') == 4
        assert cuenta('server', 'module-bays', 'drive-bay') == 24
        assert len([p for p in r['server']['port_list']['module-bays']
                    if p['name'].startswith('DIMM ')]) == 32
        assert cuenta('gpu', 'power-ports', 'iec-60320-c20') == 2
        assert len([p for p in r['gpu']['port_list']['module-bays']
                    if p['name'].startswith('GPU ')]) == 8
        assert cuenta('storage', 'module-bays', 'drive-bay') == 24
        assert cuenta('patch', 'front-ports', '8p8c') == 24
        assert cuenta('patch', 'rear-ports', '110-punch') == 24
        assert cuenta('fiber', 'front-ports', 'lc-upc') == 24
        assert cuenta('fiber', 'rear-ports', 'lc-upc') == 24
        assert cuenta('console', 'console-server-ports', 'rj-45') == 16
        assert cuenta('kvm', 'console-server-ports', 'rj-45') == 9       # 8 servers + chain
        assert cuenta('kvm', 'rear-ports', 'vga') == 1
        assert cuenta('kvm', 'power-ports', 'iec-60320-c14') == 1
        assert cuenta('mini', 'power-ports', 'dc-terminal') == 1

    def test_the_power_inlets_say_what_they_take(self, built):
        """Every inlet with its voltage and the watts of its supply; a passive panel has none
        and says it is not powered."""
        _wa, _c, modelos = built
        for key, r in _each(modelos):
            entradas = r['port_list'].get('power-ports') or []
            if not r['is_powered']:
                assert not entradas and key in ('patch', 'fiber'), key
                continue
            assert entradas and r['power_type'] in ('internal', 'external'), key
            for p in entradas:
                assert p.get('volts') and int(p.get('watts') or 0) > 0, (key, p)

    def test_physical_and_lifecycle_fields_are_filled_and_coherent(self, built):
        _wa, _c, modelos = built
        for key, r in _each(modelos):
            e = r['extra']
            assert r['u_tenths'] > 0 and r['airflow'] and r['kind'], key
            assert r['part_number'] and '\n' in r['description'], key
            for campo in ('width_mm', 'height_mm', 'depth_mm', 'weight', 'warranty_years'):
                assert float(e.get(campo) or 0) > 0, (key, campo)
            assert e['weight_unit'] == 'kg'
            # The box fits its U: no taller than its units, no wider than 19 inches.
            assert float(e['height_mm']) <= r['u_tenths'] / 10 * 44.45, key
            assert float(e['width_mm']) <= 482.6, key
            if r['is_powered']:
                assert 0 < float(e['typical_power_w']) <= float(e['max_power_w']), key
            fechas = [e.get(k) for k in ('launched', 'end_of_sale', 'eol')]
            assert all(f and _ISO.match(f) for f in fechas), (key, fechas)
            assert fechas[0] < fechas[1] <= fechas[2], (key, fechas)
            if r['is_powered']:
                for k in ('end_of_maintenance', 'end_of_security', 'last_contract_attach',
                          'last_contract_renewal'):
                    assert _ISO.match(str(e.get(k) or '')), (key, k)
                    assert e['end_of_sale'] <= e[k] <= e['eol'], (key, k, e[k])

    def test_the_dates_give_the_catalogue_something_to_warn_about(self, built):
        """Some current, one or two near the end of support and one already past it — so the
        sheet's red and the «support that expires» have something to show."""
        from datetime import date, timedelta                        # noqa: PLC0415
        _wa, _c, modelos = built
        hoy = date.today().isoformat()
        pronto = (date.today() + timedelta(days=182)).isoformat()
        fines = [r['extra']['eol'] for _k, r in _each(modelos)]
        assert any(f <= hoy for f in fines)
        assert any(hoy < f <= pronto for f in fines)
        assert len([f for f in fines if f > pronto]) >= len(fines) // 2

    def test_a_c20_supply_is_fed_by_a_c19_cord(self, built):
        """The GPU server's 2000 W supplies take a C20: the demo plugs them with C19-C20."""
        wa, _c, modelos = built
        store = wa._dcim_store
        gpu = modelos['DM-G2 GPU Server 2U']['uid']
        server = modelos['DM-R2 Server 2U']['uid']
        cords = {}
        for f in store.feeds.list():
            it = store.items.get(f['item_uid']) or {}
            cords.setdefault(it.get('type_uid'), set()).add(f['category'])
        assert cords[gpu] == {'c19-c20'} and cords[server] == {'c13-c14'}


class TestThePicturesAreWhatIsDrawn:

    def test_the_files_on_disk_are_what_the_drawing_code_makes(self):
        """The port positions come from the drawing code; the files must be its output, or a
        socket would sit in one place on the picture and in another in the port map. Rewrite
        them with ``python -m lib.core.dcim.demo_draw``."""
        from lib.core.dcim import demo_draw, demo_faces              # noqa: PLC0415
        for key in demo_faces.every():
            for nombre, svg in demo_draw.files(key).items():
                with io.open(os.path.join(demo_faces.FACES_DIR, nombre), encoding='utf-8',
                             newline='') as fh:
                    assert fh.read() == svg, nombre

    def test_every_port_is_drawn_inside_its_picture(self):
        from lib.core.dcim import demo_draw, demo_faces              # noqa: PLC0415
        for key in demo_faces.every():
            d = demo_draw.draw(key)
            caras = [c for c in (d['front'], d['rear']) if c is not None]
            caras += [c for _v, _n, c in d['views']]
            for cara in caras:
                for fam, name, _t, x, y, _e in cara.ports:
                    assert 0 < x < cara.w and 0 < y < cara.h, (key, fam, name, x, y)

    def test_no_vendor_name_on_any_picture(self):
        """The models are fictitious: the silkscreen says what a real one says, never whose."""
        from lib.core.dcim import demo_faces                        # noqa: PLC0415
        prohibidas = ('idrac', 'ilo', 'cisco', 'dell', 'hpe', 'juniper', 'aruba', 'fortinet',
                      'supermicro', 'lenovo', 'nvidia', 'intel', 'amd', 'aten', 'raritan')
        for key in demo_faces.every():
            for nombre in demo_faces.files_of(key):
                texto = ' '.join(re.findall(r'>([^<]+)</text>',
                                            demo_faces._read(nombre))).lower()
                for p in prohibidas:
                    assert not re.search(r'\b%s\b' % p, texto), (nombre, p)

    def test_the_view_names_are_said_in_every_language(self):
        from lib.core.dcim import demo, demo_faces                   # noqa: PLC0415
        for lang in ('es_ES', 'en_EN'):
            w = demo.texts(lang)
            for key in demo_faces.every():
                assert w.get('model_desc_' + key), (lang, key)
                for _vid, clave, _f in demo_faces.views_of(key):
                    assert w.get(clave), (lang, clave)
