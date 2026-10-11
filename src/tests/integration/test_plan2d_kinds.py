#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The plan catalogue: what a plan can hold, from the base, from its screen, and created there.

Asked for: the objects a plan can place —doors, desks, cameras, printers— belong to the plan
editor, not to the inventory, so any screen can reuse them, each saying which it uses and adding
its own; and on top of those, objects created from the screen itself.

The base objects and a screen's own are code (`lib/core/plan2d/kinds.py`, the inventory's in
`lib/core/dcim/plankinds.py`); the created ones are rows of `plan2d_kind`, managed under the
permission the screen named (`dcim_catalog_manage` for the inventory) and placed like any other:
a piece in `dc_feature`, equipment in `dc_item`. An object placed somewhere cannot be deleted.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login, _login_as                        # noqa: E402
from tests.helpers import node_run, panel_bundle, plan2d_catalog_js  # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')

_K = '/api/v1/plan2d/dcim/kinds'
_PALE = {'name': 'Palé', 'icon': 'bi-box', 'w_mm': 1200, 'd_mm': 800, 'h_mm': 150,
         'fill': '#aa5500', 'layer': 'floor'}
_LECTOR = {'name': 'Fichador', 'icon': 'bi-key', 'device': 1, 'mount': 'wall', 'w_mm': 150,
           'd_mm': 60, 'h_mm': 200, 'base_mm': 1300, 'fill': '#0055aa', 'abbr': 'Fch'}


def _uid(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


class TestTheCatalogue:

    def test_the_inventory_offers_base_objects_and_its_own(self, client):
        _login(client)
        d = client.get(_K).get_json()
        k = d['kinds']
        assert k['door']['source'] == 'base' and k['door']['label'] == 'plan2d_kind_door'
        assert k['aisle']['source'] == 'screen' and k['aisle']['label'] == 'dcim_kind_aisle'
        assert k['camera']['device'] and k['camera']['mount'] == 'wall'
        assert list(k)[:3] == ['aisle', 'zone', 'column'], 'the palette keeps its order'
        assert d['manage'] is True and d['devices'] is True and 'bi-box' in d['icons']

    def test_a_screen_nobody_registered_is_not_there(self, client):
        _login(client)
        assert client.get('/api/v1/plan2d/nope/kinds').status_code == 404

    def test_read_with_the_screens_view_permission(self, admin):
        sin = _login_as(admin, 'nadie', perms=[])
        assert sin.get(_K).status_code == 403
        mira = _login_as(admin, 'mira', perms=['dcim_view'])
        d = mira.get(_K).get_json()
        assert d['kinds'] and d['manage'] is False

    def test_managed_with_the_permission_the_screen_named(self, admin):
        mira = _login_as(admin, 'mira2', perms=['dcim_view'])
        assert mira.post(_K, json=_PALE).status_code == 403
        gestor = _login_as(admin, 'gestor', perms=['dcim_view', 'dcim_catalog_manage'])
        assert gestor.post(_K, json=_PALE).status_code == 200


class TestCreatedObjects:

    def test_created_ones_join_the_catalogue_with_a_minted_key(self, client):
        _login(client)
        r = client.post(_K, json=_PALE).get_json()
        assert r['key'].startswith('u-') and len(r['key']) == 12
        spec = client.get(_K).get_json()['kinds'][r['key']]
        assert spec['name'] == 'Palé' and spec['source'] == 'custom' and spec['layer'] == 'floor'
        assert spec['look']['fill'] == '#aa5500' and (spec['w'], spec['d']) == (1200, 800)

    @pytest.mark.parametrize('malo', [
        {'name': ''}, {'name': 'x' * 61}, {'icon': 'evil" onclick="x'}, {'icon': 'bi-nope'},
        {'w_mm': 0}, {'w_mm': 'abc'}, {'h_mm': 10 ** 9}, {'layer': 'roof'},
        {'fill': 'red'}, {'fill': 'var(--x)'}, {'line': '#12'}, {'dash': '1;2'},
        {'abbr': 'abcde'}, {'device': 1, 'mount': 'sky'},
    ])
    def test_what_is_not_an_object_is_refused(self, client, malo):
        _login(client)
        r = client.post(_K, json=dict(_PALE, **malo))
        assert r.status_code == 400, (malo, r.get_json())

    def test_one_of_another_screen_is_not_found(self, client):
        _login(client)
        uid = client.post(_K, json=_PALE).get_json()['uid']
        assert client.put(f'/api/v1/plan2d/nope/kinds/{uid}', json={'name': 'x'}).status_code == 404
        assert client.put(f'{_K}/no-such', json={'name': 'x'}).status_code == 404

    def test_editing_keeps_its_key(self, client):
        _login(client)
        r = client.post(_K, json=_PALE).get_json()
        assert client.put(f'{_K}/{r["uid"]}', json={'name': 'Palé europeo', 'w_mm': 1200}).status_code == 200
        spec = client.get(_K).get_json()['kinds'][r['key']]
        assert spec['name'] == 'Palé europeo'


class TestPlacingThem:
    """A created piece goes to `dc_feature`, created equipment to `dc_item`, like the base ones."""

    @pytest.fixture()
    def room(self, client):
        _login(client)
        site = _uid(client.post('/api/v1/dcim/sites', json={'name': 'S'}))
        return _uid(client.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'Almacén'}))

    def test_a_created_piece_is_placed_and_measured_as_it_says(self, client, room):
        pale = client.post(_K, json=_PALE).get_json()['key']
        f = _uid(client.post('/api/v1/dcim/features', json={'room_uid': room, 'kind': pale}))
        d = client.get(f'/api/v1/dcim/rooms/{room}/features').get_json()
        fila = [x for x in d['features'] if x['uid'] == f][0]
        assert (fila['width_mm'], fila['depth_mm']) == (1200, 800), 'its size, not 600 × 600'
        assert pale in d['kinds'], 'the plan draws it from its kinds'

    def test_created_equipment_is_a_room_item_with_its_box(self, client, room):
        lector = client.post(_K, json=_LECTOR).get_json()['key']
        i = _uid(client.post(f'/api/v1/dcim/rooms/{room}/items', json={'role': lector}))
        items = client.get(f'/api/v1/dcim/rooms/{room}/items').get_json()['items']
        caja = [x for x in items if x['uid'] == i][0]['box']
        assert (caja['w'], caja['d'], caja['base'], caja['mount']) == (150, 60, 1300, 'wall')

    def test_a_piece_is_not_equipment_and_the_other_way_round(self, client, room):
        pale = client.post(_K, json=_PALE).get_json()['key']
        lector = client.post(_K, json=_LECTOR).get_json()['key']
        assert client.post(f'/api/v1/dcim/rooms/{room}/items', json={'role': pale}).status_code == 400
        assert client.post('/api/v1/dcim/features', json={'room_uid': room, 'kind': lector}).status_code == 400

    def test_one_in_use_cannot_be_deleted_nor_change_what_it_is(self, client, room):
        r = client.post(_K, json=_PALE).get_json()
        f = _uid(client.post('/api/v1/dcim/features', json={'room_uid': room, 'kind': r['key']}))
        assert client.delete(f'{_K}/{r["uid"]}').status_code == 409
        assert client.put(f'{_K}/{r["uid"]}', json={'device': 1, 'mount': 'wall'}).status_code == 409
        client.delete(f'/api/v1/dcim/features/{f}')
        assert client.delete(f'{_K}/{r["uid"]}').status_code == 200
        assert r['key'] not in client.get(_K).get_json()['kinds']


_PROBE = r"""
currentUser = {permissions: ['dcim_view', 'dcim_edit', 'dcim_catalog_manage']};
_dcimData = {orgs: [], sites: []};
renderDcim = () => {};
__out = {};
const cat = P2D_CAT.dcim;
const propio = Object.keys(cat.kinds).find(k => cat.kinds[k].source === 'custom' && !cat.kinds[k].device);
const equipo = Object.keys(cat.kinds).find(k => cat.kinds[k].source === 'custom' && cat.kinds[k].device);
// Lo que DCIM saca del catálogo: el dibujo, el icono, el nombre y la paleta de equipos.
__out.dibujo = _dcpLook(propio).fill;
__out.dibujoBase = _dcpLook('door').fill;
__out.icono = _dcpIcon(propio);
__out.nombres = [_dcPieceName(propio), _dcPieceName('door'), _dcRoleName(equipo), _dcRoleName('server')];
__out.equipoLook = _dcriLook(equipo);
__out.paletaEquipos = _dcriRoles();
// El editor, en el inspector del plano de la sala.
__out.boton = p2dKindsButton(_dcpP2d);
_dcpP2d.kindsOpen = true;
__out.lista = p2dInspector(_dcpP2d, () => 'CUERPO');
p2dKindNew('room');
__out.formulario = p2dInspector(_dcpP2d, () => 'CUERPO');
p2dKindField('room', 'device', 1);
__out.conMontaje = p2dInspector(_dcpP2d, () => 'CUERPO').includes('plan2d_mount_') ||
                   p2dInspector(_dcpP2d, () => 'CUERPO').includes(t('plan2d_mount_wall'));
p2dKindEdit('room', propio);
__out.editando = [_dcpP2d.kindEdit.name, _dcpP2d.kindEdit.w_mm, _dcpP2d.kindEdit.fill];
_dcpP2d.kindsOpen = false; _dcpP2d.kindEdit = null;
__out.cerrado = p2dInspector(_dcpP2d, () => 'CUERPO');
// Sin el catálogo (una pantalla que no ha abierto ningún plano), los nombres siguen saliendo.
const guardado = P2D_CAT.dcim;
delete P2D_CAT.dcim;
__out.sinCatalogo = [_dcRoleName('camera'), _dcPieceName('door'), _dcPieceName('aisle'), _dcRoleName('server')];
P2D_CAT.dcim = guardado;
// Sin permiso de gestión, sin botón.
P2D_CAT.dcim = Object.assign({}, cat, {manage: false});
__out.sinBoton = p2dKindsButton(_dcpP2d);
"""


@pytest.fixture(scope='module')
def out():
    """One `node` run, with a piece and an equipment created on the server first."""
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    assert c.post(_K, json=_PALE).status_code == 200
    assert c.post(_K, json=_LECTOR).status_code == 200
    return node_run(panel_bundle(c), plan2d_catalog_js(c) + _PROBE)


@pytest.mark.skipif(shutil.which('node') is None, reason='no node to run the script with')
class TestInTheBrowser:

    def test_the_plan_draws_from_the_catalogue(self, out):
        assert out['dibujo'] == '#aa5500'
        assert out['dibujoBase'] == 'var(--bs-warning)'
        assert out['icono'] == 'bi-box'

    def test_names_come_from_the_catalogue_and_the_rest_from_their_key(self, out):
        assert out['nombres'][0] == 'Palé' and out['nombres'][2] == 'Fichador'
        assert out['nombres'][1] and out['nombres'][1] != 'plan2d_kind_door'
        assert out['nombres'][3] and out['nombres'][3] != 'dcim_role_server', 'a rack role keeps its name'

    def test_created_equipment_joins_the_palette_with_its_look(self, out):
        assert out['equipoLook'] == {'abbr': 'Fch', 'fill': '#0055aa', 'icon': 'bi-key'}
        assert out['paletaEquipos'][:8] == ['pc', 'phone', 'printer', 'ap', 'camera', 'display', 'outlet',
                                            'power_outlet']
        assert len(out['paletaEquipos']) == 9

    def test_the_editor_lists_creates_and_edits(self, out):
        assert 'data-p2dkinds' in out['boton']
        assert 'Palé' in out['lista'] and 'Fichador' in out['lista'] and 'data-p2dkindnew' in out['lista']
        assert 'CUERPO' not in out['lista'], 'while open, the editor takes the inspector'
        assert 'data-p2dkindform' in out['formulario']
        assert out['conMontaje']
        assert out['editando'] == ['Palé', 1200, '#aa5500']
        assert out['cerrado'] == 'CUERPO'

    def test_names_without_the_catalogue_loaded(self, out):
        """The base objects' names live only in `plan2d_kind_*` now; a screen that never opened a
        plan (templates, the device list) still names a camera and a door, and a data-centre
        piece and a rack role by the inventory's own keys."""
        camara, puerta, pasillo, servidor = out['sinCatalogo']
        for nombre, clave in ((camara, 'camera'), (puerta, 'door'), (pasillo, 'aisle'), (servidor, 'server')):
            assert nombre and not nombre.startswith(('plan2d_kind_', 'dcim_kind_', 'dcim_role_')), (clave, nombre)

    def test_no_button_without_the_permission(self, out):
        assert out['sinBoton'] == ''
