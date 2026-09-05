#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las rutas del inventario físico, y sobre todo el rack compartido.

Un armario con equipos de varias sociedades **rompe que ver un sitio sea ver lo que hay
dentro**. El de la filial B tiene que ver el rack, tiene que ver que la U 12 está ocupada —si
no, planificar es imposible— y no puede ver de quién es ni cómo se llama.

Ahí es donde una fuga se cuela sin que nadie la note, porque la pantalla *se ve bien*: enseña
un rack, con sus huecos, con sus cajas. Lo que se comprueba aquí es que de las cajas ajenas no
sale ni un nombre, ni un modelo, ni un número de serie, ni el host al que apuntan — y que la
cuenta de lo que hay tampoco los delata.

Con app y sesión: es lo que hace el filtro, y probarlo sin HTTP sería probar otra cosa.
"""

from __future__ import annotations

import io
import os
import sys

import pytest
from werkzeug.security import generate_password_hash

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from tests.conftest import _login                                   # noqa: E402


def _as(admin, username, perms):
    """Una sesión con EXACTAMENTE esos permisos — que es como se prueba un estrechamiento.

    Por un ROL propio y no por una lista en la cuenta: los permisos en vigor se resuelven del
    rol (`_get_session_permissions`), así que pegárselos al usuario no le da ninguno.
    """
    role = f'r-{username}'
    admin._custom_roles[role] = {
        'uid': role, 'name': role, 'description': '', 'permissions': list(perms),
        'enabled': True, 'created_at': '2026-08-26T00:00:00Z',
        'updated_at': '2026-08-26T00:00:00Z', 'updated_by': 'test'}
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash('pw-secret')}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': 'pw-secret'},
           follow_redirects=True)
    return c


@pytest.fixture()
def fleet(client):
    """El caso del holding: un rack del departamento de IT con 2U de una filial dentro."""
    _login(client)
    it = client.post('/api/v1/dcim/orgs', json={'name': 'IT del grupo'}).get_json()['uid']
    b = client.post('/api/v1/dcim/orgs', json={'name': 'Filial B'}).get_json()['uid']
    site = client.post('/api/v1/dcim/sites', json={'name': 'DC Norte'}).get_json()['uid']
    room = client.post('/api/v1/dcim/rooms',
                       json={'site_uid': site, 'name': 'Sala 1'}).get_json()['uid']
    rack = client.post('/api/v1/dcim/racks',
                       json={'room_uid': room, 'name': 'R3', 'u_height': 42}).get_json()['uid']
    client.post('/api/v1/dcim/owner', json={'scope': 'site', 'uid': site, 'org_uid': it})
    mine = client.post('/api/v1/dcim/items',
                       json={'rack_uid': rack, 'u_start': 1, 'u_height': 1,
                             'label': 'SW-CORE', 'host_uid': 'h-sw'}).get_json()['uid']
    theirs = client.post('/api/v1/dcim/items',
                         json={'rack_uid': rack, 'u_start': 12, 'u_height': 2,
                               'label': 'DB03-NOMINAS', 'serial': 'SECRETO-1',
                               'host_uid': 'h-db03'}).get_json()['uid']
    client.post('/api/v1/dcim/owner', json={'scope': 'item', 'uid': theirs, 'org_uid': b})
    return {'it': it, 'b': b, 'site': site, 'room': room, 'rack': rack,
            'mine': mine, 'theirs': theirs}


class TestHaceFaltaSesionYPermiso:

    def test_sin_sesion_no_hay_inventario(self, client):
        assert client.get('/api/v1/dcim/sites').status_code == 401

    def test_sin_la_bandera_tampoco(self, admin):
        c = _as(admin, 'nadie', [])
        assert c.get('/api/v1/dcim/sites').status_code == 403

    def test_decir_de_quien_es_algo_es_otra_bandera(self, admin, fleet):
        """Mover un equipo de U es ordenar el armario; cambiar de quién es, mover propiedad."""
        c = _as(admin, 'ordenanza', ['dcim_view', 'dcim_all_view', 'dcim_edit'])
        r = c.post('/api/v1/dcim/owner',
                   json={'scope': 'rack', 'uid': fleet['rack'], 'org_uid': fleet['b']})
        assert r.status_code == 403


class TestElRackCompartido:
    """Lo que ve quien solo tiene una de las empresas."""

    def _b(self, admin, fleet):
        return _as(admin, 'filial-b', ['dcim_view', f'org.{fleet["b"]}.view'])

    def test_ve_el_rack_y_ve_que_la_u_esta_ocupada(self, admin, fleet):
        r = self._b(admin, fleet).get(f'/api/v1/dcim/racks/{fleet["rack"]}')
        assert r.status_code == 200
        items = r.get_json()['items']
        assert len(items) == 2, 'un item que desaparece hace el armario improvisable'
        ajeno = [i for i in items if i.get('foreign')][0]
        assert ajeno['u_start'] == 1 and ajeno['u_height'] == 1

    def test_y_de_lo_ajeno_no_sale_nada_mas(self, admin, fleet):
        body = self._b(admin, fleet).get(f'/api/v1/dcim/racks/{fleet["rack"]}').data.decode()
        for leak in ('SW-CORE', 'h-sw'):
            assert leak not in body, leak

    def test_lo_suyo_lo_ve_entero(self, admin, fleet):
        items = self._b(admin, fleet).get(
            f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
        suyo = [i for i in items if not i.get('foreign')][0]
        assert suyo['label'] == 'DB03-NOMINAS' and suyo['serial'] == 'SECRETO-1'

    def test_el_hueco_libre_es_de_todos(self, admin, fleet):
        """«Quedan 6U libres» no dice de quién es nada, y es la mitad del valor de tener esto:
        negárselo a quien no ve los nombres del vecino haría improvisable un armario
        compartido."""
        free = self._b(admin, fleet).get(
            f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['free']
        assert 2 in free['front'] and 1 not in free['front']
        assert 13 not in free['rear'], 'la U del vecino sigue ocupada aunque no se vea de quién'

    def test_no_puede_mover_lo_ajeno(self, admin, fleet):
        """Contra el dueño de lo que se CAMBIA: mover el servidor de otro una U sigue siendo
        tocar el servidor de otro."""
        c = _as(admin, 'filial-b-edit',
                ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        r = c.put(f'/api/v1/dcim/items/{fleet["mine"]}', json={'label': 'MIO AHORA'})
        assert r.status_code == 403
        assert c.delete(f'/api/v1/dcim/items/{fleet["mine"]}').status_code == 403

    def test_pero_si_lo_suyo(self, admin, fleet):
        c = _as(admin, 'filial-b-edit2',
                ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        assert c.put(f'/api/v1/dcim/items/{fleet["theirs"]}',
                     json={'label': 'DB03'}).status_code == 200

    def test_y_solo_ve_su_empresa_en_la_lista(self, admin, fleet):
        orgs = self._b(admin, fleet).get('/api/v1/dcim/orgs').get_json()['orgs']
        assert [o['uid'] for o in orgs] == [fleet['b']]

    def test_sin_ninguna_empresa_ve_lo_que_nadie_ha_reclamado(self, admin, client, fleet):
        """`None` y `set()` son respuestas distintas: a quien se le dio la sección y ninguna
        empresa le toca ver **lo que nadie ha reclamado**, que el primer día es todo — un rack
        sin fichar no es un secreto. Lo que no le toca es lo que alguien ya dijo que es suyo.

        Antes abría cualquier armario escribiendo su uid, incluso los de una sociedad con la que
        no tiene nada que ver, y el listado sí se los escondía: dos pantallas discrepando.
        """
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Sin Fichar'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': site, 'name': 'S'}).get_json()['uid']
        libre = client.post('/api/v1/dcim/racks',
                            json={'room_uid': room, 'name': 'RSF'}).get_json()['uid']
        c = _as(admin, 'recien-llegado', ['dcim_view'])
        # Lo no reclamado, entero y sin error.
        abierto = c.get(f'/api/v1/dcim/racks/{libre}')
        assert abierto.status_code == 200
        assert abierto.get_json()['rack']['name'] == 'RSF'
        # Y lo de una sociedad con la que no tiene nada que ver, no.
        assert c.get(f'/api/v1/dcim/racks/{fleet["rack"]}').status_code == 403

class TestLaUEsUnSitioYSoloCabeUnaCosa:

    def test_lo_que_se_solapa_se_rechaza_antes_de_escribirse(self, client, fleet):
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': fleet['rack'], 'u_start': 13, 'u_height': 1})
        assert r.status_code == 400

    def test_por_la_otra_cara_si_cabe(self, client, fleet):
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': fleet['rack'], 'u_start': 30, 'face': 'rear'})
        assert r.status_code == 200
        r2 = client.post('/api/v1/dcim/items',
                         json={'rack_uid': fleet['rack'], 'u_start': 30, 'face': 'front'})
        assert r2.status_code == 200

    def test_lo_que_se_sale_del_rack_no(self, client, fleet):
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': fleet['rack'], 'u_start': 41, 'u_height': 4})
        assert r.status_code == 400

    def test_moverse_a_donde_ya_esta_uno_mismo_no_choca_consigo(self, client, fleet):
        r = client.put(f'/api/v1/dcim/items/{fleet["theirs"]}',
                       json={'u_start': 12, 'u_height': 2, 'face': 'full'})
        assert r.status_code == 200


class TestLaPertenencia:

    def test_se_hereda_y_lo_dicho_manda(self, client, fleet):
        items = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
        by_uid = {i['uid']: i for i in items}
        assert by_uid[fleet['mine']]['org_uid'] == fleet['it']     # heredado de la sede
        assert by_uid[fleet['theirs']]['org_uid'] == fleet['b']    # dicho en el item

    def test_dejar_de_decirlo_devuelve_a_lo_heredado(self, client, fleet):
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'item', 'uid': fleet['theirs'], 'org_uid': ''})
        items = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
        assert {i['uid']: i for i in items}[fleet['theirs']]['org_uid'] == fleet['it']

    def test_borrar_una_empresa_no_deja_pertenencias_colgando(self, client, fleet):
        """Si no, el resolutor devuelve un uid que no se puede buscar en ninguna parte."""
        assert client.delete(f'/api/v1/dcim/orgs/{fleet["b"]}').status_code == 200
        items = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
        assert {i['uid']: i for i in items}[fleet['theirs']]['org_uid'] == fleet['it']

    def test_un_ambito_inventado_se_rechaza(self, client, fleet):
        r = client.post('/api/v1/dcim/owner',
                        json={'scope': 'planeta', 'uid': 'marte', 'org_uid': fleet['b']})
        assert r.status_code == 400


class TestElCatalogo:

    def test_se_consulta_con_su_propia_bandera(self, admin):
        c = _as(admin, 'sin-catalogo', ['dcim_view'])
        assert c.get('/api/v1/dcim/catalog').status_code == 403

    def test_importar_es_otra_mas(self, admin):
        c = _as(admin, 'lector-catalogo', ['dcim_view', 'dcim_catalog_view'])
        assert c.post('/api/v1/dcim/catalog/import', json={'path': '/x'}).status_code == 403

    def test_una_ruta_que_no_existe_se_dice_antes_de_lanzar_nada(self, client):
        _login(client)
        r = client.post('/api/v1/dcim/catalog/import',
                        json={'path': '/no/existe/en/ningun/sitio'})
        assert r.status_code == 400

    def test_y_sin_ruta_tampoco(self, client):
        _login(client)
        assert client.post('/api/v1/dcim/catalog/import', json={}).status_code == 400

    # ── La biblioteca de GitHub ─────────────────────────────────────────────────────────
    #
    # Nada de esto habla con GitHub: lo que se comprueba son las decisiones de la ruta —quién
    # puede, qué queda escrito, y qué llega a la pantalla cuando lo de fuera falla—.

    def _sin_red(self, monkeypatch, salida):
        """El catálogo contesta lo que se le diga, sin salir a internet."""
        from lib.core.dcim import catalog
        monkeypatch.setattr(catalog, 'browse', lambda url='', token='': salida)

    def test_mirar_la_biblioteca_pide_permiso_de_importar(self, admin):
        """Mirar cuesta una petición a una máquina ajena hecha por este servidor. Es un acto y
        no una vista, así que lo pide el mismo permiso que importar."""
        c = _as(admin, 'lector-biblioteca', ['dcim_view', 'dcim_catalog_view'])
        assert c.get('/api/v1/dcim/catalog/browse').status_code == 403

    def test_los_fabricantes_llegan_con_su_cuenta(self, client, monkeypatch):
        _login(client)
        self._sin_red(monkeypatch, {'vendors': [{'name': 'HP', 'device_types': 2,
                                                 'module_types': 1}],
                                    'paths': ['device-types/HP/a.yaml'], 'error': ''})
        d = client.get('/api/v1/dcim/catalog/browse').get_json()
        assert d['vendors'][0]['name'] == 'HP' and d['vendors'][0]['device_types'] == 2

    def test_el_indice_entero_no_sale_a_la_pantalla(self, client, monkeypatch):
        """Once mil rutas son tres megas que el navegador no usa para nada, y por cada persona
        que abra la pantalla."""
        _login(client)
        self._sin_red(monkeypatch, {'vendors': [], 'paths': ['a'] * 11000, 'error': ''})
        assert 'paths' not in client.get('/api/v1/dcim/catalog/browse').get_json()

    def test_un_fallo_llega_con_su_motivo_y_no_como_un_400_mudo(self, client, monkeypatch):
        """Un 400 aquí es exactamente el «Error» sin explicación que hubo que arreglar: el
        envoltorio de GET del panel devuelve `null` ante cualquier respuesta que no sea 2xx, y
        el cuerpo —donde va el motivo— se pierde antes de que nadie lo lea."""
        _login(client)
        self._sin_red(monkeypatch, {'vendors': [], 'paths': [], 'error': 'not_found'})
        r = client.get('/api/v1/dcim/catalog/browse')
        assert r.status_code == 200
        d = r.get_json()
        assert d['error'] and d['detail'] == 'not_found'

    def test_mirar_queda_registrado_salga_como_salga(self, client, monkeypatch):
        """Lo que faltaba cuando la pantalla solo sabía decir «Error»: la línea que cuenta a qué
        dirección se preguntó y qué contestó."""
        _login(client)
        vistos = []
        from lib.web_admin import app as _app
        monkeypatch.setattr(_app.WebAdmin, '_audit',
                            lambda self, ev, **kw: vistos.append((ev, kw.get('detail') or {})),
                            raising=False)
        self._sin_red(monkeypatch, {'vendors': [], 'paths': [], 'error': 'rate_limited'})
        client.get('/api/v1/dcim/catalog/browse')
        evento = [v for v in vistos if v[0] == 'dcim_catalog_browse']
        assert evento and evento[0][1]['error'] == 'rate_limited'
        assert evento[0][1]['ok'] is False

    def test_importar_de_github_no_exige_una_ruta_del_disco(self, client, monkeypatch):
        """«Falta la ruta o el archivo zip» al importar de GitHub: la comprobación de la ruta
        estaba escrita arriba y corría antes de mirar de dónde venía lo que se pedía."""
        _login(client)
        from lib.core.dcim import jobs
        monkeypatch.setattr(jobs, 'start_import',
                            lambda *a, **kw: ('trabajo-de-mentira', ''))
        r = client.post('/api/v1/dcim/catalog/import', json={'vendors': ['HP']})
        assert r.status_code == 200 and r.get_json()['job'] == 'trabajo-de-mentira'

    def test_lo_elegido_queda_escrito_por_su_nombre(self, client, monkeypatch):
        """Dentro de un año la pregunta será «¿de dónde salió este modelo?», y un número de
        fabricantes no la contesta."""
        _login(client)
        vistos = []
        from lib.core.dcim import jobs
        from lib.web_admin import app as _app
        monkeypatch.setattr(jobs, 'start_import', lambda *a, **kw: ('j', ''))
        monkeypatch.setattr(_app.WebAdmin, '_audit',
                            lambda self, ev, **kw: vistos.append((ev, kw.get('detail') or {})),
                            raising=False)
        client.post('/api/v1/dcim/catalog/import', json={'vendors': ['HP', 'Eaton']})
        linea = [v for v in vistos if v[0] == 'dcim_catalog_import'][0][1]
        assert 'HP' in linea['vendors'] and 'Eaton' in linea['vendors']

    def test_subir_algo_que_no_es_un_zip_se_dice_antes_de_guardarlo(self, client):
        """Lo dicen sus primeros bytes y no su nombre: la extensión es una afirmación de quien
        lo sube, y lo que se va a abrir es el contenido."""
        _login(client)
        r = client.post('/api/v1/dcim/catalog/upload',
                        data={'file': (io.BytesIO(b'no soy un zip'), 'x.zip')},
                        content_type='multipart/form-data')
        assert r.status_code == 400

    def test_subir_sin_fichero_tampoco_vale(self, client):
        _login(client)
        r = client.post('/api/v1/dcim/catalog/upload', data={},
                        content_type='multipart/form-data')
        assert r.status_code == 400

    def test_subir_pide_permiso_de_importar(self, admin):
        c = _as(admin, 'lector-subida', ['dcim_view', 'dcim_catalog_view'])
        assert c.post('/api/v1/dcim/catalog/upload', data={},
                      content_type='multipart/form-data').status_code == 403

    def test_el_listado_dice_cuantos_hay_y_no_solo_cuantos_enseña(self, client):
        """Con un tope de doscientos y ninguna cuenta, un catálogo de seis mil enseñaba
        doscientos como si fueran todos: quien buscara el de la fila mil doscientos concluiría
        que no se importó."""
        _login(client)
        d = client.get('/api/v1/dcim/catalog').get_json()
        assert 'total' in d and 'offset' in d and 'limit' in d

    def test_y_de_donde_se_trae_viaja_con_el_listado(self, client):
        """La pantalla enseña la dirección ANTES de traer nada, y quien la haya cambiado en la
        configuración tiene que ver la suya y no la de NetBox en el hueco donde va a pulsar."""
        _login(client)
        assert client.get('/api/v1/dcim/catalog').get_json()['library_url']

    # ── Quitar, que es la mitad que faltaba ─────────────────────────────────────────────
    #
    # Importar reemplaza una importación ENTERA. Eso deja sin respuesta «este modelo sobra» y
    # también «esta importación no era la que quería»: la única salida era reimportar las otras
    # para que `replace` se llevara esta por delante — rehacer lo bueno para deshacer lo malo.

    def _dos_modelos(self, admin):
        """Dos modelos de dos orígenes, metidos por el almacén y no por la API.

        Por la fixture y no por `current_app`: eso último solo existe dentro de una petición, y
        aquí se deja algo puesto ANTES de pedir nada — que es de lo que va el test.
        """
        cat = admin._dcim_catalog                              # noqa: SLF001
        cat.replace('library', [{'manufacturer': 'HP', 'model': 'DL380',
                                 'slug': 'dl380', 'u_tenths': 20}])
        cat.replace('a-mano', [{'manufacturer': 'Nadie', 'model': 'Cacharro',
                                'slug': 'cacharro', 'u_tenths': 10}])
        return {r['model']: r['uid'] for r in cat.list()}

    def test_quitar_varios_es_una_peticion_y_no_cuatrocientas(self, admin, client):
        """Quien marca cuatrocientas filas no quiere cuatrocientas idas y venidas — y un
        borrado a medias por una conexión caída deja un catálogo que nadie sabe cómo quedó."""
        _login(client)
        uids = self._dos_modelos(admin)
        r = client.post('/api/v1/dcim/catalog/drop', json={'uids': list(uids.values())})
        assert r.status_code == 200 and r.get_json()['count'] == 2
        assert client.get('/api/v1/dcim/catalog').get_json()['total'] == 0

    def test_vaciar_un_origen_no_toca_los_demas(self, admin, client):
        """El origen es la unidad en la que ENTRARON, así que es la unidad en la que se van —
        y lo tecleado a mano tiene que sobrevivir a que se vacíe la biblioteca."""
        _login(client)
        self._dos_modelos(admin)
        r = client.post('/api/v1/dcim/catalog/drop', json={'source': 'library'})
        assert r.get_json()['count'] == 1
        quedan = client.get('/api/v1/dcim/catalog').get_json()['types']
        assert [x['model'] for x in quedan] == ['Cacharro']

    def test_sin_nada_marcado_no_se_borra_nada(self, admin, client):
        """Una petición vacía que borrara todo sería la peor forma de vaciar un catálogo: la
        que pasa por no haber marcado nada."""
        _login(client)
        self._dos_modelos(admin)
        assert client.post('/api/v1/dcim/catalog/drop', json={}).status_code == 400
        assert client.get('/api/v1/dcim/catalog').get_json()['total'] == 2

    def test_los_origenes_viajan_con_su_cuenta(self, admin, client):
        """Se elige de una lista y no se teclea: equivocarse en una letra vacía cero modelos y
        no lo dice nadie. Y la cuenta es lo que hace que la confirmación se piense."""
        _login(client)
        self._dos_modelos(admin)
        fuentes = {f['name']: f['count']
                   for f in client.get('/api/v1/dcim/catalog').get_json()['sources']}
        assert fuentes == {'library': 1, 'a-mano': 1}

    def test_quitar_uno_se_lleva_su_imagen(self, admin, client):
        """Nadie más la mira: la guardó esta importación y le apunta esta fila. Dejarla es
        dejar un fichero inalcanzable en una carpeta que crece toda la vida del panel."""
        _login(client)
        from lib.core.dcim import media
        var = admin._var_dir or ''                             # noqa: SLF001
        cat = admin._dcim_catalog                              # noqa: SLF001
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 32
        cat.replace('library', [{'manufacturer': 'HP', 'model': 'DL380', 'slug': 'dl380',
                                 'u_tenths': 20, '_images': {'front': png}}], var)
        fila = cat.list()[0]
        assert fila['front_image'] and media.read(var, fila['front_image'])[0]
        client.delete(f"/api/v1/dcim/catalog/{fila['uid']}")
        assert media.every(var) == []

    def test_el_listado_trae_los_fabricantes_para_entrar_por_ellos(self, admin, client):
        """Ocho mil filas paginadas de doscientas no son una lista, son un archivo por el que
        pasear. Y nadie llega preguntándose qué habrá en la fila mil doscientos: llega con una
        marca escrita en la chapa del aparato que tiene delante."""
        _login(client)
        self._dos_modelos(admin)
        marcas = client.get('/api/v1/dcim/catalog').get_json()['makers']
        assert sorted(m[0] for m in marcas) == ['HP', 'Nadie']

    def test_el_tipo_acota_tambien_la_rejilla_de_marcas(self, admin, client):
        """«Quién fabrica switches» se pregunta antes de saber de qué marca es el aparato, y era
        justo la que no se podía hacer: el filtro solo salía en la tabla."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        cat.replace('library', [
            {'manufacturer': 'A', 'model': 'SW', 'ports': {'interfaces': {'1g': 48}}},
            {'manufacturer': 'B', 'model': 'PDU', 'ports': {'power-outlets': {'c13': 8}}},
        ])
        d = client.get('/api/v1/dcim/catalog?kind=switch').get_json()
        assert [m[0] for m in d['makers']] == ['A'], 'la rejilla enseñaba marcas sin ninguno'
        assert d['total'] == 1

    def test_bajar_a_un_fabricante_acota_en_el_servidor(self, admin, client):
        """Acotar en el navegador sería traerse los ocho mil para enseñar cuarenta."""
        _login(client)
        self._dos_modelos(admin)
        d = client.get('/api/v1/dcim/catalog?maker=HP').get_json()
        assert d['total'] == 1 and [r['model'] for r in d['types']] == ['DL380']

    def test_los_basicos_entran_sin_descargar_nada(self, client):
        """Para la primera tarde —hay un armario delante y hace falta una caja de 1U que se
        llame algo— y para la sala sin salida a internet, donde es lo único que va a haber."""
        _login(client)
        r = client.post('/api/v1/dcim/catalog/basics', json={})
        assert r.status_code == 200 and r.get_json()['count'] > 10
        arboles = {x['tree'] for x in client.get(
            '/api/v1/dcim/catalog').get_json()['types']}
        assert {'device-types', 'rack-types', 'module-types'} <= arboles

    def test_lo_recien_importado_sale_en_el_listado_y_en_las_marcas(self, admin, client):
        """«Termina de importar, me lleva al catálogo y no sale lo nuevo.»

        Lo primero es descartar al servidor: si la respuesta de después de importar ya trae los
        modelos y las marcas, lo que se quedó viejo es la pantalla — y son dos arreglos muy
        distintos.
        """
        _login(client)
        client.post('/api/v1/dcim/catalog/basics', json={})
        d = client.get('/api/v1/dcim/catalog').get_json()
        from lib.core.dcim import basics
        assert d['total'] == basics.count()
        assert 'Genérico' in [m[0] for m in d['makers']]
        assert d['sources'] and d['sources'][0]['name'] == 'core'
        assert d['kinds'], 'el filtro de tipo se queda sin opciones'

    def test_pero_un_filtro_puesto_ANTES_esconde_lo_nuevo(self, admin, client):
        """Y aquí está lo que sí puede pasar: la pantalla conserva el fabricante, el tipo y la
        búsqueda de antes de importar. Con cualquiera de los tres puesto, la respuesta es
        correcta y no trae ni una fila de lo que se acaba de meter."""
        _login(client)
        client.post('/api/v1/dcim/catalog/basics', json={})
        d = client.get('/api/v1/dcim/catalog?maker=NoExiste').get_json()
        assert d['total'] == 0 and d['types'] == []

    def test_los_basicos_no_se_llevan_por_delante_la_biblioteca(self, admin, client):
        """Dos orígenes, y `replace` trabaja por origen. Con la misma etiqueta, meter los
        básicos borraría los ocho mil modelos descargados."""
        _login(client)
        self._dos_modelos(admin)
        client.post('/api/v1/dcim/catalog/basics', json={})
        fuentes = {f['name']: f['count']
                   for f in client.get('/api/v1/dcim/catalog').get_json()['sources']}
        assert fuentes['library'] == 1 and fuentes['core'] > 10

    def test_los_basicos_piden_permiso_de_importar(self, admin):
        c = _as(admin, 'lector-basicos', ['dcim_view', 'dcim_catalog_view'])
        assert c.post('/api/v1/dcim/catalog/basics', json={}).status_code == 403

    def test_se_puede_corregir_la_clase_de_un_modelo(self, admin, client):
        """`N9K-PAC-650W-B` es una fuente y la regla dice «Otro»: mira los puertos, y una fuente
        declara un `power-ports` y nada más, igual que media docena de cosas distintas."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        cat.replace('library', [{'manufacturer': 'Cisco', 'model': 'N9K-PAC-650W-B',
                                 'ports': {'power-ports': {'': 1}}}])
        uid = cat.list()[0]['uid']
        assert client.put(f'/api/v1/dcim/catalog/{uid}',
                          json={'kind': 'psu'}).status_code == 200
        assert cat.list()[0]['kind'] == 'psu'

    def test_se_puede_escribir_un_modelo_que_no_esta_en_ninguna_biblioteca(self, admin, client):
        """El armario que montó el electricista, la bandeja con su cargador."""
        _login(client)
        r = client.post('/api/v1/dcim/catalog',
                        json={'manufacturer': 'Taller', 'model': 'Armario a medida',
                              'tree': 'rack-types', 'kind': 'rack', 'u_height': 30})
        assert r.status_code == 200
        fila = admin._dcim_catalog.get(r.get_json()['uid'])   # noqa: SLF001
        assert fila['tree'] == 'rack-types' and fila['u_tenths'] == 300
        assert fila['source'] == 'manual', 'una importación se lo llevaría'

    def test_clonar_deja_dos_filas_y_no_toca_la_primera(self, admin, client):
        """Casi ningún modelo se escribe desde cero: lo que hay en una sala es «como el R640
        pero con la otra fuente». Teclear veinte campos para cambiar uno es el trabajo que nadie
        hace, y entonces no se registra."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        cat.replace('library', [{'manufacturer': 'Dell', 'model': 'R640',
                                 'ports': {'interfaces': {'1g': 4}}}])
        origen = cat.list()[0]
        r = client.post('/api/v1/dcim/catalog',
                        json={'from': origen['uid'], 'manufacturer': 'Dell',
                              'model': 'R640 (copia)', 'tree': 'device-types'})
        assert r.status_code == 200
        clon = cat.get(r.get_json()['uid'])
        assert clon['source'] == 'manual', 'una importación se lo llevaría'
        assert cat.get(origen['uid']), 'el original tiene que seguir ahí'
        assert clon['ports'] == origen['ports'], 'los puertos van con el clon'

    def test_LAS_IMAGENES_SE_COPIAN_Y_NO_SE_COMPARTEN(self, admin, client):
        """Dos filas apuntando al mismo fichero es una bomba de relojería: borrar cualquiera de
        las dos se lo lleva, y la otra se queda enseñando un hueco sin que nada haya fallado. Es
        el agujero que ya se tapó al reimportar."""
        _login(client)
        from lib.core.dcim import media
        cat = admin._dcim_catalog                              # noqa: SLF001
        var = admin._var_dir or ''                             # noqa: SLF001
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 32
        cat.replace('library', [{'manufacturer': 'Dell', 'model': 'R640',
                                 '_images': {'front': png}}], var)
        origen = cat.list()[0]
        assert origen['front_image']
        r = client.post('/api/v1/dcim/catalog',
                        json={'from': origen['uid'], 'manufacturer': 'Dell',
                              'model': 'R640 (copia)'})
        clon = cat.get(r.get_json()['uid'])
        assert clon['front_image'], 'el clon se quedó sin imagen'
        assert clon['front_image'] != origen['front_image'], 'comparten el mismo fichero'
        # Y borrar el original deja al clon con la suya.
        client.delete(f"/api/v1/dcim/catalog/{origen['uid']}")
        assert media.read(var, clon['front_image'])[0], 'borrar el original vació al clon'

    def test_se_puede_poner_la_imagen_de_una_cara(self, admin, client):
        """La biblioteca trae las de mil doscientos modelos y ninguna de los demás — y ninguna,
        por definición, de lo que alguien escriba a mano. Un alzado sin imagen es una caja gris
        con un nombre dentro."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        uid = cat.create({'manufacturer': 'Taller', 'model': 'Cacharro'})
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 32
        r = client.post(f'/api/v1/dcim/catalog/{uid}/image/front',
                        data={'file': (io.BytesIO(png), 'foto.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 200
        assert cat.get(uid)['front_image'] == r.get_json()['image']

    def test_la_que_sustituye_se_borra_del_disco(self, admin, client):
        """Sin eso, cada cambio deja un fichero al que no apunta nadie y la carpeta crece durante
        toda la vida de la instalación. Es el mismo agujero que se tapó al reimportar."""
        _login(client)
        from lib.core.dcim import media
        cat = admin._dcim_catalog                              # noqa: SLF001
        var = admin._var_dir or ''                             # noqa: SLF001
        uid = cat.create({'manufacturer': 'Taller', 'model': 'Cacharro'})
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 32
        for _ in range(2):
            client.post(f'/api/v1/dcim/catalog/{uid}/image/front',
                        data={'file': (io.BytesIO(png), 'foto.png')},
                        content_type='multipart/form-data')
        assert media.every(var) == [cat.get(uid)['front_image']]

    def test_quitarla_la_borra_tambien(self, admin, client):
        _login(client)
        from lib.core.dcim import media
        cat = admin._dcim_catalog                              # noqa: SLF001
        var = admin._var_dir or ''                             # noqa: SLF001
        uid = cat.create({'manufacturer': 'Taller', 'model': 'Cacharro'})
        client.post(f'/api/v1/dcim/catalog/{uid}/image/front',
                    data={'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 32), 'f.png')},
                    content_type='multipart/form-data')
        assert client.delete(f'/api/v1/dcim/catalog/{uid}/image/front').status_code == 200
        assert cat.get(uid)['front_image'] == '' and media.every(var) == []

    def test_lo_que_no_es_una_imagen_no_entra(self, admin, client):
        """El tipo lo decide lo que hay DENTRO del fichero: una extensión es una afirmación de
        quien sube."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        uid = cat.create({'manufacturer': 'Taller', 'model': 'Cacharro'})
        r = client.post(f'/api/v1/dcim/catalog/{uid}/image/front',
                        data={'file': (io.BytesIO(b'no soy una imagen'), 'foto.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 400

    def test_una_cara_que_no_existe_no_es_una_cara(self, admin, client):
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        uid = cat.create({'manufacturer': 'Taller', 'model': 'Cacharro'})
        assert client.post(f'/api/v1/dcim/catalog/{uid}/image/lateral',
                           data={}, content_type='multipart/form-data').status_code == 404

    def test_poner_una_imagen_pide_permiso_de_importar(self, admin):
        c = _as(admin, 'lector-imagen', ['dcim_view', 'dcim_catalog_view'])
        assert c.post('/api/v1/dcim/catalog/x/image/front', data={},
                      content_type='multipart/form-data').status_code == 403

    def test_sin_nombre_no_se_crea(self, client):
        _login(client)
        assert client.post('/api/v1/dcim/catalog',
                           json={'manufacturer': '', 'model': 'X'}).status_code == 400

    def test_una_clase_inventada_no_se_guarda(self, admin, client):
        """El vocabulario es cerrado. Una clase que solo existe en una petición sale en un
        filtro que nadie puede volver a elegir."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        uid = cat.create({'manufacturer': 'A', 'model': 'B', 'kind': 'server'})
        client.put(f'/api/v1/dcim/catalog/{uid}', json={'kind': 'inventada'})
        assert cat.get(uid)['kind'] == 'server'

    def test_escribir_y_corregir_piden_permiso_de_importar(self, admin):
        c = _as(admin, 'lector-edicion', ['dcim_view', 'dcim_catalog_view'])
        assert c.post('/api/v1/dcim/catalog', json={}).status_code == 403
        assert c.put('/api/v1/dcim/catalog/x', json={}).status_code == 403

    def test_quitar_pide_permiso_de_importar(self, admin):
        c = _as(admin, 'lector-borrado', ['dcim_view', 'dcim_catalog_view'])
        assert c.post('/api/v1/dcim/catalog/drop', json={'uids': ['x']}).status_code == 403


class TestElCicloQueHaceLaPantalla:
    """Crear una sede, meterle una sala, un rack y algo dentro, y deshacerlo."""

    def test_todo_lo_que_se_crea_contesta_200_con_su_uid(self, client):
        """**200 y no 201.** Los dos son correctos en REST; en este panel todos los clientes
        leen `status === 200`, así que un dominio que conteste 201 es un dominio cuyo cliente
        lee un éxito como un fallo. Pasó: la sede se creaba y la pantalla decía que no, y solo
        un F5 lo desmentía."""
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Sur'})
        assert site.status_code == 200 and site.get_json()['uid']
        room = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': site.get_json()['uid'], 'name': 'Sala A'})
        assert room.status_code == 200
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': room.get_json()['uid'], 'name': 'R1',
                                 'u_height': 24})
        assert rack.status_code == 200
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack.get_json()['uid'], 'u_start': 3,
                                 'label': 'PATCH-1'})
        assert item.status_code == 200

    def test_y_lo_creado_aparece_donde_toca(self, client):
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Este'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': site, 'name': 'Sala B'}).get_json()['uid']
        client.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'R9'})
        tree = client.get('/api/v1/dcim/sites').get_json()['sites']
        card = [x for x in tree if x['uid'] == site][0]
        assert [r['name'] for r in card['rooms']] == ['Sala B']
        assert card['rooms'][0]['racks'] == 1
        # …y los racks de una sala se piden aparte: el árbol lleva una CUENTA, porque cuarenta
        # salas mandarían todos los racks de todas para dibujar un número.
        racks = client.get(f'/api/v1/dcim/racks?room={room}').get_json()['racks']
        assert [r['name'] for r in racks] == ['R9']

    def test_y_se_puede_borrar_una_sede(self, client):
        """No había forma de hacerlo desde la pantalla. Reportado desde la pantalla."""
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Oeste'}).get_json()['uid']
        assert client.delete(f'/api/v1/dcim/sites/{site}').status_code == 200
        assert not [x for x in client.get('/api/v1/dcim/sites').get_json()['sites']
                    if x['uid'] == site]

    def test_una_sala_sin_nombre_no_se_crea(self, client):
        _login(client)
        assert client.post('/api/v1/dcim/rooms', json={'name': 'Sin sede'}).status_code == 400

    def test_los_racks_de_una_sala_que_no_se_pide_no_llegan(self, client):
        _login(client)
        assert client.get('/api/v1/dcim/racks').get_json()['racks'] == []

class TestLasZonasHorarias:
    """La zona de una sede se elige de una lista, y la lista la ofrece **el servidor**: es quien
    tendrá que interpretar el valor el día que una pantalla enseñe la hora local de un sitio, y
    un nombre que no sepa resolver es un registro que no sirve.

    Vacío es una respuesta de verdad y se devuelve como tal: `zoneinfo` lee la base de datos de
    zonas del sistema, y hay dos formas corrientes de no tener ninguna —Windows sin `tzdata` y
    un contenedor recortado—. La pantalla entonces usa la del navegador, que no es autoritativa
    pero es mucho mejor que texto libre."""

    def test_basta_con_tener_sesion(self, admin):
        """Sin permiso: las zonas del mundo no son secreto de nadie, y pedir `dcim_view` para
        leerlas era heredar el permiso del primero que pasó por ahí. Vive en `/api/v1/util/`,
        con el resto de ayudantes que no son de ningún dominio."""
        c = _as(admin, 'cualquiera', [])
        assert c.get('/api/v1/util/timezones').status_code == 200

    def test_devuelve_una_lista_y_de_donde_sale(self, client):
        _login(client)
        r = client.get('/api/v1/util/timezones')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data['zones'], list)
        # `source` dice cuál de las dos contestó, para que un vacío no se confunda con un fallo.
        assert data['source'] in ('server', '')
        assert bool(data['zones']) == (data['source'] == 'server')

    def test_y_si_las_hay_son_nombres_de_zona_de_verdad(self, client):
        _login(client)
        zones = client.get('/api/v1/util/timezones').get_json()['zones']
        if not zones:
            return          # esta máquina no tiene tzdata: lo dice, y la pantalla se apaña
        assert 'UTC' in zones or any('/' in z for z in zones)
        assert zones == sorted(zones), 'sin ordenar, filtrar escribiendo es una lotería'

    def test_una_zona_se_guarda_tal_cual_se_eligio(self, client):
        """Se guarda el nombre, no un desplazamiento: `+01:00` deja de ser cierto dos veces al
        año, y `Europe/Madrid` no."""
        _login(client)
        uid = client.post('/api/v1/dcim/sites',
                          json={'name': 'DC TZ', 'timezone': 'Europe/Madrid'}).get_json()['uid']
        site = [x for x in client.get('/api/v1/dcim/sites').get_json()['sites']
                if x['uid'] == uid][0]
        assert site['timezone'] == 'Europe/Madrid'

class TestEnlazarUnItemConSuMaquina:
    """Sin esto el alzado sale gris entero, que es tanto como no tenerlo: el color en vivo lee
    `host_uid`, y `host_uid` no se podía escribir desde ninguna parte.

    La lista de máquinas es **de este dominio** y no la de Infraestructura, por dos motivos que
    empujan igual: aquélla va tras `infra_view`, que quien ordena armarios no tiene por qué
    tener; y devuelve la forma entera de una máquina, de la que esto necesita cuatro campos."""

    def _host(self, client, name='DB03'):
        r = client.post('/api/v1/hosts', json={'name': name, 'address': '10.0.0.9'})
        assert r.status_code == 200, r.get_json()
        return r.get_json()['uid']

    def test_ofrece_las_maquinas_del_registro(self, client, fleet):
        _login(client)
        uid = self._host(client)
        rows = client.get('/api/v1/dcim/hosts').get_json()['hosts']
        assert uid and any(h['uid'] == uid and h['name'] == 'DB03' for h in rows)

    def test_y_solo_cuatro_campos_de_cada_una(self, client, fleet):
        """Un selector que se trae el estado, las etiquetas y los módulos de cada máquina cuesta
        lo que cuesta la pantalla de la flota."""
        _login(client)
        self._host(client)
        rows = client.get('/api/v1/dcim/hosts').get_json()['hosts']
        assert set(rows[0]) == {'uid', 'name', 'address', 'device_type'}

    def test_un_rol_acotado_solo_ve_las_suyas(self, admin, client, fleet):
        """Se estrecha con la regla del REGISTRO, porque lo que se ofrece son sus fichas."""
        _login(client)
        self._host(client)
        c = _as(admin, 'sin-registro', ['dcim_view', 'dcim_all_view'])
        assert c.get('/api/v1/dcim/hosts').get_json()['hosts'] == []

    def test_y_enlazado_el_item_lo_devuelve(self, client, fleet):
        _login(client)
        uid = self._host(client, 'SW-CORE-2')
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'host_uid': uid}).get_json()['uid']
        items = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
        fila = [i for i in items if i['uid'] == item][0]
        assert fila['host_uid'] == uid
        # …y con él llega el estado, que es todo el sentido del enlace. Sin checks todavía no
        # hay ninguno, y eso NO es «bien»: es que nadie lo mira.
        assert fila['state'] == ''


class TestElPlanoDeLaSala:
    """Subir un plano es lo único de esta sección donde el nombre lo elige quien sube.

    Y por eso es lo único donde un fallo no se ve venir: el catálogo de MIB trajo una travesía
    de rutas exactamente de esta forma. Lo que se comprueba aquí es que por la red no entra un
    nombre —ni por el fichero, ni por el cuerpo de un PUT— y que quitar el plano se lleva el
    fichero y no solo la referencia.
    """

    PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 40

    def _sube(self, c, room, blob=None, filename='../../evil.png'):
        return c.post(f'/api/v1/dcim/rooms/{room}/plan',
                      data={'file': (io.BytesIO(blob or self.PNG), filename)},
                      content_type='multipart/form-data')

    def test_se_sube_y_la_sala_lo_lleva(self, client, fleet):
        _login(client)
        r = self._sube(client, fleet['room'])
        assert r.status_code == 200
        name = r.get_json()['plan']
        sites = client.get('/api/v1/dcim/sites').get_json()['sites']
        sala = [x for s in sites for x in s['rooms'] if x['uid'] == fleet['room']][0]
        assert sala['plan'] == name

    def test_y_el_nombre_no_es_el_que_traia_el_fichero(self, client, fleet):
        """`../../evil.png` es un nombre que nunca llega a un disco: el que se guarda lo acuña
        el panel, y su extensión la decide el CONTENIDO."""
        _login(client)
        name = self._sube(client, fleet['room']).get_json()['plan']
        assert 'evil' not in name and '..' not in name and name.endswith('.png')

    def test_lo_que_no_es_una_imagen_no_entra(self, client, fleet):
        _login(client)
        r = self._sube(client, fleet['room'], blob=b'#!/bin/sh\nrm -rf /\n', filename='x.png')
        assert r.status_code == 400
        assert client.get(f'/api/v1/dcim/media/{"a" * 8}-0000-0000-0000-00000000.png'
                          ).status_code == 404

    def test_se_sirve_con_su_tipo_y_sin_adivinar(self, client, fleet):
        _login(client)
        name = self._sube(client, fleet['room']).get_json()['plan']
        r = client.get(f'/api/v1/dcim/media/{name}')
        assert r.status_code == 200 and r.data == self.PNG
        assert r.headers['Content-Type'].startswith('image/png')
        assert r.headers['X-Content-Type-Options'] == 'nosniff'

    def test_un_svg_se_sirve_como_descarga(self, client, fleet):
        """Un SVG subido es un documento que puede traer script dentro, y este panel no va a
        ser el origen que lo ejecute."""
        _login(client)
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>'
        name = self._sube(client, fleet['room'], blob=svg, filename='p.svg').get_json()['plan']
        r = client.get(f'/api/v1/dcim/media/{name}')
        assert r.headers.get('Content-Disposition') == 'attachment'

    def test_un_nombre_inventado_no_se_sirve(self, client, fleet):
        _login(client)
        assert client.get('/api/v1/dcim/media/..%2f..%2fconfig.json').status_code in (400, 404)

    def test_cambiar_el_plano_se_lleva_el_anterior(self, client, fleet):
        """Si no, cada resubida deja un fichero al que ya no apunta nadie y la carpeta crece
        durante toda la vida de la instalación."""
        _login(client)
        viejo = self._sube(client, fleet['room']).get_json()['plan']
        nuevo = self._sube(client, fleet['room']).get_json()['plan']
        assert viejo != nuevo
        assert client.get(f'/api/v1/dcim/media/{viejo}').status_code == 404
        assert client.get(f'/api/v1/dcim/media/{nuevo}').status_code == 200

    def test_quitarlo_borra_el_fichero_y_no_solo_la_referencia(self, client, fleet):
        _login(client)
        name = self._sube(client, fleet['room']).get_json()['plan']
        assert client.delete(f'/api/v1/dcim/rooms/{fleet["room"]}/plan').status_code == 200
        assert client.get(f'/api/v1/dcim/media/{name}').status_code == 404

    def test_el_nombre_no_se_escribe_por_el_crud(self, client, fleet):
        """`plan` lo acuña la ruta de subida. Escribible por el PUT genérico, cualquiera podría
        apuntar una sala a la imagen de otra sin subir nada."""
        _login(client)
        client.put(f'/api/v1/dcim/rooms/{fleet["room"]}',
                   json={'plan': 'robado.png', 'name': 'Sala 1'})
        sites = client.get('/api/v1/dcim/sites').get_json()['sites']
        sala = [x for s in sites for x in s['rooms'] if x['uid'] == fleet['room']][0]
        assert sala['plan'] == ''
        assert sala['name'] == 'Sala 1'          # …y lo demás del cuerpo sí se guarda

    def test_pero_la_escala_si(self, client, fleet):
        """La escala es un dato que alguien mide, no un nombre que el panel acuñe."""
        _login(client)
        client.put(f'/api/v1/dcim/rooms/{fleet["room"]}', json={'plan_mm': 8000})
        sites = client.get('/api/v1/dcim/sites').get_json()['sites']
        sala = [x for s in sites for x in s['rooms'] if x['uid'] == fleet['room']][0]
        assert int(sala['plan_mm']) == 8000

    def test_subir_es_editar_y_hace_falta_la_bandera(self, admin, fleet):
        c = _as(admin, 'mirona', ['dcim_view', 'dcim_all_view'])
        r = c.post(f'/api/v1/dcim/rooms/{fleet["room"]}/plan',
                   data={'file': (io.BytesIO(self.PNG), 'p.png')},
                   content_type='multipart/form-data')
        assert r.status_code == 403

    def test_y_una_sala_que_no_existe_es_un_404(self, client, fleet):
        _login(client)
        assert self._sube(client, 'no-existe').status_code == 404


class TestLaCajaVaciaDiceAQueEquivale:
    """«Vacío = el sitio por defecto» es cierto y no sirve de nada si no se ve cuál es.

    Depende de dónde se instaló el panel, así que el registro no puede llevarlo escrito y el
    operador se queda adivinando. Lo mismo que hace la carpeta de copias.
    """

    def test_dice_la_carpeta_efectiva(self, client, fleet):
        _login(client)
        r = client.get('/api/v1/dcim/media-dir')
        assert r.status_code == 200
        assert r.get_json()['configured'].endswith('dcim_media')

    def test_y_preguntar_no_la_crea(self, admin, client, fleet):
        """Un GET que pinta una pantalla no tiene por qué dejar un directorio detrás, y menos
        uno que a lo mejor no se usa nunca."""
        _login(client)
        sitio = client.get('/api/v1/dcim/media-dir').get_json()['configured']
        assert not os.path.exists(sitio)

    def test_es_la_pantalla_de_configuracion_la_que_pregunta(self, admin, fleet):
        """Es una ruta del disco del servidor: la pide quien puede cambiarla, no quien puede
        ver el inventario."""
        c = _as(admin, 'inventarista', ['dcim_view', 'dcim_all_view', 'dcim_edit'])
        assert c.get('/api/v1/dcim/media-dir').status_code == 403


class TestElCuadroDeMando:
    """Un cuadro que dice «3 incidencias» y hay que ir a buscarlas obliga a hacer el trabajo que
    venía a ahorrar. Lo que se comprueba aquí es lo contrario: que cada cosa que está mal viene
    con el camino entero hasta ella —sede, sala, rack, U— y que **el camino no cuenta lo ajeno**.

    Eso último es lo que se rompe sin que nadie lo note: un cuadro es un sitio muy cómodo para
    filtrar de menos, porque la pantalla se ve perfecta con datos que no debería estar
    enseñando.
    """

    def test_sin_nada_roto_no_hay_lista(self, client, fleet):
        _login(client)
        b = client.get('/api/v1/dcim/board').get_json()
        assert b['trouble'] == []
        assert b['totals']['sites'] == 1

    def test_las_baldosas_cuentan_por_sede(self, client, fleet):
        _login(client)
        b = client.get('/api/v1/dcim/board').get_json()
        sede = [s for s in b['sites'] if s['uid'] == fleet['site']][0]
        assert sede['racks'] == 1 and sede['rooms'] == 1
        # Dos items, ninguno vigilado todavía: eso NO es «bien», es que nadie los mira.
        assert sede['total'] == 2 and sede['unwatched'] == 2 and sede['ok'] == 0

    def test_ve_la_sede_donde_tiene_algo_y_ninguna_mas(self, admin, client, fleet):
        """La regla del holding: se llega a una caja **o porque se ve, o porque contiene algo
        tuyo**. La filial tiene 2U en el rack de la sede del departamento, así que ve el camino
        hasta ellas —la sede y la sala por el nombre— y nada más de esa sede.

        Sin la segunda mitad su pantalla salía vacía: ni sedes, ni salas, ni racks, y su propio
        equipo inalcanzable salvo que alguien le pasara una URL. La parte más probada del
        dominio quedaba fuera del alcance de quien la necesita.
        """
        _login(client)
        # Otra sede del departamento donde la filial no tiene nada.
        ajena = client.post('/api/v1/dcim/sites', json={'name': 'DC Ajeno'}).get_json()['uid']
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'site', 'uid': ajena, 'org_uid': fleet['it']})
        c = _as(admin, 'solo-filial', ['dcim_view', f'org.{fleet["b"]}.view'])
        b = c.get('/api/v1/dcim/board').get_json()
        assert [s['uid'] for s in b['sites']] == [fleet['site']]
        # …y de esa sede cuenta solo lo suyo: el equipo del departamento no entra en el total.
        assert b['sites'][0]['total'] == 1


    def test_el_desglose_por_empresa_solo_cuenta_lo_visible(self, admin, client, fleet):
        _login(client)
        todo = client.get('/api/v1/dcim/board').get_json()
        por_empresa = {o['uid']: o for o in todo['orgs']}
        assert por_empresa[fleet['b']]['total'] == 1     # el suyo
        assert por_empresa[fleet['it']]['total'] == 1    # y el del departamento

    def test_hace_falta_la_bandera(self, admin, fleet):
        c = _as(admin, 'sin-nada', [])
        assert c.get('/api/v1/dcim/board').status_code == 403

    def test_sin_sesion_tampoco(self, client):
        assert client.get('/api/v1/dcim/board').status_code == 401


class TestDisenarLaSala:
    """Las piezas de una sala —columnas, puertas, climatizadores, bandejas— no son de nadie: no
    las compró ninguna sociedad del grupo, están ahí. Así que el permiso se mira en **la sala**,
    y esa es la parte que se rompe en silencio: preguntado de la pieza, la respuesta sería
    «cualquiera», y cualquiera podría recolocar las columnas de una sala que no puede ni abrir.
    """

    def _pieza(self, c, room, kind='column', **extra):
        body = {'room_uid': room, 'kind': kind}
        body.update(extra)
        return c.post('/api/v1/dcim/features', json=body)

    def test_se_pone_una_pieza_y_sale_en_la_sala(self, client, fleet):
        _login(client)
        r = self._pieza(client, fleet['room'], 'column', pos_x=7900, pos_y=4200)
        assert r.status_code == 200
        uid = r.get_json()['uid']
        d = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()
        assert [f['uid'] for f in d['features']] == [uid]

    def test_viene_con_sus_medidas_de_fabrica(self, client, fleet):
        """Una pieza sin tamaño se dibuja como un punto, y hay que estirarla a mano para
        descubrir que era una mampara."""
        _login(client)
        self._pieza(client, fleet['room'], 'wall')
        f = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()['features'][0]
        assert f['width_mm'] == 4000 and f['depth_mm'] == 100

    def test_y_el_catalogo_viaja_con_la_lista(self, client, fleet):
        """Las medidas de fábrica las decide el servidor: una paleta con las suyas sería una
        segunda verdad sobre lo que mide una puerta."""
        _login(client)
        d = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()
        assert d['kinds']['door']['w'] == 1000
        assert d['layers'] == ['floor', 'room', 'air']

    def test_un_tipo_inventado_no_entra(self, client, fleet):
        """Es una caja que el dibujo no sabe pintar y que ninguna leyenda explica."""
        _login(client)
        r = self._pieza(client, fleet['room'], 'teletransportador')
        assert r.status_code == 400
        d = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()
        assert d['features'] == []

    def test_ni_cambiando_el_tipo_despues(self, client, fleet):
        _login(client)
        uid = self._pieza(client, fleet['room']).get_json()['uid']
        r = client.put(f'/api/v1/dcim/features/{uid}', json={'kind': 'teletransportador'})
        assert r.status_code == 400

    def test_se_mueve_y_se_gira(self, client, fleet):
        _login(client)
        uid = self._pieza(client, fleet['room']).get_json()['uid']
        client.put(f'/api/v1/dcim/features/{uid}',
                   json={'pos_x': 1200, 'pos_y': 600, 'rotation': 90, 'label': 'Columna'})
        f = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()['features'][0]
        assert (f['pos_x'], f['pos_y'], f['rotation'], f['label']) == (1200, 600, 90, 'Columna')

    def test_una_pieza_no_se_muda_de_sala_por_el_cuerpo(self, client, fleet):
        """Cambiar `room_uid` sería mover una columna a una sala cuyo permiso no se ha mirado."""
        _login(client)
        otra = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': fleet['site'], 'name': 'Sala 2'}).get_json()['uid']
        uid = self._pieza(client, fleet['room']).get_json()['uid']
        client.put(f'/api/v1/dcim/features/{uid}', json={'room_uid': otra})
        assert client.get(f'/api/v1/dcim/rooms/{otra}/features').get_json()['features'] == []
        assert len(client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features'
                              ).get_json()['features']) == 1

    def test_se_quita(self, client, fleet):
        _login(client)
        uid = self._pieza(client, fleet['room']).get_json()['uid']
        assert client.delete(f'/api/v1/dcim/features/{uid}').status_code == 200
        assert client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features'
                          ).get_json()['features'] == []

    def test_el_permiso_se_mira_en_la_sala(self, admin, client, fleet):
        """Aquí es donde se cuela: la pieza no es de nadie, así que preguntarle a ella da que
        sí. Lo que decide es quién puede tocar la sala donde está."""
        _login(client)
        it = fleet['it']
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'room', 'uid': fleet['room'], 'org_uid': it})
        c = _as(admin, 'de-la-filial', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        assert self._pieza(c, fleet['room']).status_code == 403

    def test_mirar_es_otra_bandeja_que_editar(self, admin, fleet):
        c = _as(admin, 'mirona-sala', ['dcim_view', 'dcim_all_view'])
        assert c.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').status_code == 200
        assert self._pieza(c, fleet['room']).status_code == 403

    def test_una_sala_que_no_existe_es_un_404(self, client, fleet):
        _login(client)
        assert self._pieza(client, 'no-existe').status_code == 404
        assert client.get('/api/v1/dcim/rooms/no-existe/features').status_code == 404

    def test_la_sala_guarda_sus_medidas_y_su_baldosa(self, client, fleet):
        """Se escriben desde el plano, que es donde se descubre que hacen falta."""
        _login(client)
        client.put(f'/api/v1/dcim/rooms/{fleet["room"]}',
                   json={'width_mm': 13000, 'depth_mm': 8500, 'tile_mm': 500})
        sites = client.get('/api/v1/dcim/sites').get_json()['sites']
        sala = [x for s in sites for x in s['rooms'] if x['uid'] == fleet['room']][0]
        assert (sala['width_mm'], sala['depth_mm'], sala['tile_mm']) == (13000, 8500, 500)


class TestLlevarseElPlanoYTraerlo:
    """Importar es la operación que puede destruir trabajo de otro, así que lo que se comprueba
    es sobre todo **lo que NO hace**.

    Un rack es un registro con equipos dentro. Un fichero de hace dos meses que no lo nombre no
    puede borrarlo: eso sería tirar el inventario de alguien por pulsar un botón que dice
    «importar», y no habría forma de saber que ha pasado hasta buscar el armario.
    """

    def _plano(self, **extra):
        base = {'version': 1, 'room': {'width_mm': 13000, 'depth_mm': 8500, 'tile_mm': 600},
                'racks': [], 'features': [
                    {'kind': 'column', 'label': 'Columna', 'pos_x': 7900, 'pos_y': 4200,
                     'width_mm': 500, 'depth_mm': 500, 'rotation': 0}]}
        base.update(extra)
        return base

    def test_las_piezas_se_reemplazan_enteras(self, client, fleet):
        """Media importación mezclada con lo que había deja una sala que no es ni la de antes ni
        la del fichero."""
        _login(client)
        client.post('/api/v1/dcim/features', json={'room_uid': fleet['room'], 'kind': 'door'})
        r = client.post(f'/api/v1/dcim/rooms/{fleet["room"]}/import', json=self._plano())
        assert r.status_code == 200 and r.get_json()['features'] == 1
        d = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()
        assert [f['kind'] for f in d['features']] == ['column']

    def test_y_las_medidas_de_la_sala_vienen_con_ellas(self, client, fleet):
        _login(client)
        client.post(f'/api/v1/dcim/rooms/{fleet["room"]}/import', json=self._plano())
        sites = client.get('/api/v1/dcim/sites').get_json()['sites']
        sala = [x for s in sites for x in s['rooms'] if x['uid'] == fleet['room']][0]
        assert (sala['width_mm'], sala['depth_mm']) == (13000, 8500)

    def test_un_rack_que_el_fichero_no_nombra_NO_se_borra(self, client, fleet):
        """La prueba que importa: dentro de ese rack hay equipos."""
        _login(client)
        antes = client.get(f'/api/v1/dcim/racks?room={fleet["room"]}').get_json()['racks']
        client.post(f'/api/v1/dcim/rooms/{fleet["room"]}/import', json=self._plano())
        despues = client.get(f'/api/v1/dcim/racks?room={fleet["room"]}').get_json()['racks']
        assert {r['uid'] for r in antes} == {r['uid'] for r in despues}
        # …y sigue teniendo lo que tenía dentro.
        items = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
        assert len(items) == 2

    def test_los_racks_se_emparejan_por_nombre_y_solo_se_mueven(self, client, fleet):
        """Por nombre, que es como los llama la gente y lo que escribiría quien teclee un plano
        a mano. Y solo la posición: lo que hay dentro no está en el fichero."""
        _login(client)
        plano = self._plano(racks=[{'name': 'R3', 'pos_x': 2400, 'pos_y': 1200,
                                    'rotation': 90, 'u_height': 12}])
        r = client.post(f'/api/v1/dcim/rooms/{fleet["room"]}/import', json=plano)
        assert r.get_json()['racks_moved'] == 1 and r.get_json()['racks_new'] == 0
        rack = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['rack']
        assert (rack['pos_x'], rack['pos_y'], rack['rotation']) == (2400, 1200, 90)
        assert rack['u_height'] == 42, 'la altura de un rack existente no la decide un fichero'

    def test_un_rack_que_no_existe_se_crea(self, client, fleet):
        _login(client)
        plano = self._plano(racks=[{'name': 'R9', 'pos_x': 0, 'pos_y': 0, 'u_height': 24}])
        r = client.post(f'/api/v1/dcim/rooms/{fleet["room"]}/import', json=plano)
        assert r.get_json()['racks_new'] == 1
        racks = client.get(f'/api/v1/dcim/racks?room={fleet["room"]}').get_json()['racks']
        nuevo = [x for x in racks if x['name'] == 'R9'][0]
        assert nuevo['u_height'] == 24

    def test_un_tipo_que_esta_version_no_conoce_se_salta_y_se_dice(self, client, fleet):
        """Reventar la importación entera por una pieza desconocida convierte un fichero casi
        bueno en ninguno. Saltarla en silencio hace creer que entró todo."""
        _login(client)
        plano = self._plano(features=[{'kind': 'reactor-nuclear', 'pos_x': 0, 'pos_y': 0},
                                      {'kind': 'door', 'pos_x': 0, 'pos_y': 0}])
        r = client.post(f'/api/v1/dcim/rooms/{fleet["room"]}/import', json=plano).get_json()
        assert r['features'] == 1 and r['skipped'] == 1

    def test_una_coordenada_mal_escrita_no_tumba_la_importacion(self, client, fleet):
        _login(client)
        plano = self._plano(features=[{'kind': 'door', 'pos_x': 'por ahí', 'pos_y': None}])
        r = client.post(f'/api/v1/dcim/rooms/{fleet["room"]}/import', json=plano)
        assert r.status_code == 200 and r.get_json()['features'] == 1

    def test_un_fichero_que_no_es_un_plano_se_rechaza(self, client, fleet):
        _login(client)
        r = client.post(f'/api/v1/dcim/rooms/{fleet["room"]}/import',
                        json={'esto': 'no es un plano'})
        assert r.status_code == 400

    def test_importar_es_editar_la_sala(self, admin, client, fleet):
        _login(client)
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'room', 'uid': fleet['room'], 'org_uid': fleet['it']})
        c = _as(admin, 'ajena', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        r = c.post(f'/api/v1/dcim/rooms/{fleet["room"]}/import', json=self._plano())
        assert r.status_code == 403


class TestLaPotenciaEnUnArmarioCompartido:
    """La arista fina de esta pantalla: qué se puede decir de la alimentación de un armario que
    comparten dos sociedades.

    Los **totales** de una regleta son de todos —cuántas tomas quedan, cuánto se ha declarado—
    porque sin eso la filial no puede saber si le cabe otro servidor, igual que «la U 12 está
    ocupada». De quién es cada cable, no. Y un aviso sobre el equipo del vecino no se le cuenta:
    ni puede arreglarlo ni tiene por qué saber que existe.
    """

    def _compartido(self, c, fleet):
        """El caso de verdad: un armario SIN reclamar con equipos de dos sociedades dentro.

        Con la sede en manos del departamento —como en la fixture general— la filial no ve el
        armario en absoluto, así que no habría nada que estrechar. Lo que hace interesante un
        armario compartido es justo que el armario no es de nadie y lo de dentro sí.
        """
        site = c.post('/api/v1/dcim/sites', json={'name': 'DC Sur'}).get_json()['uid']
        room = c.post('/api/v1/dcim/rooms',
                      json={'site_uid': site, 'name': 'Sala compartida'}).get_json()['uid']
        rack = c.post('/api/v1/dcim/racks',
                      json={'room_uid': room, 'name': 'RC1', 'u_height': 42}).get_json()['uid']
        suyo = c.post('/api/v1/dcim/items',
                      json={'rack_uid': rack, 'u_start': 1,
                            'label': 'SW-DEPT'}).get_json()['uid']
        c.post('/api/v1/dcim/owner',
               json={'scope': 'item', 'uid': suyo, 'org_uid': fleet['it']})
        return rack, suyo

    def _pdus(self, c, rack):
        a = c.post('/api/v1/dcim/pdus', json={'rack_uid': rack, 'name': 'PDU-A', 'feed': 'a',
                                              'outlets': 8, 'capacity_w': 3680}).get_json()['uid']
        b = c.post('/api/v1/dcim/pdus', json={'rack_uid': rack, 'name': 'PDU-B', 'feed': 'b',
                                              'outlets': 8, 'capacity_w': 3680}).get_json()['uid']
        return a, b

    def test_se_declara_una_regleta_y_sus_cables(self, client, fleet):
        _login(client)
        a, b = self._pdus(client, fleet['rack'])
        client.post('/api/v1/dcim/feeds', json={'item_uid': fleet['mine'], 'pdu_uid': a,
                                                'outlet': 3, 'watts_said': 220})
        p = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/power').get_json()
        pa = [x for x in p['pdus'] if x['uid'] == a][0]
        assert pa['used'] == 1 and pa['free'] == 7 and pa['watts_said'] == 220

    def test_los_totales_de_la_regleta_los_ve_la_filial(self, admin, client, fleet):
        """Sin esto no puede planificar: no sabría si le queda toma para otro servidor."""
        _login(client)
        rack, suyo = self._compartido(client, fleet)
        a, _ = self._pdus(client, rack)
        client.post('/api/v1/dcim/feeds',
                    json={'item_uid': suyo, 'pdu_uid': a, 'watts_said': 900})
        c = _as(admin, 'filial-luz', ['dcim_view', f'org.{fleet["b"]}.view'])
        p = c.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        pa = [x for x in p['pdus'] if x['uid'] == a][0]
        assert pa['free'] == 7 and pa['watts_said'] == 900

    def test_pero_no_de_quien_es_ese_cable(self, admin, client, fleet):
        _login(client)
        rack, suyo = self._compartido(client, fleet)
        a, _ = self._pdus(client, rack)
        client.post('/api/v1/dcim/feeds', json={'item_uid': suyo, 'pdu_uid': a})
        c = _as(admin, 'filial-luz2', ['dcim_view', f'org.{fleet["b"]}.view'])
        crudo = str(c.get(f'/api/v1/dcim/racks/{rack}/power').get_json())
        assert 'SW-DEPT' not in crudo and suyo not in crudo

    def test_ni_el_aviso_sobre_el_equipo_del_vecino(self, admin, client, fleet):
        """«SW-DEPT cuelga de una sola rama» es el problema del departamento de IT: la filial
        ni puede arreglarlo ni tiene por qué saber que existe."""
        _login(client)
        rack, suyo = self._compartido(client, fleet)
        a, _ = self._pdus(client, rack)
        client.post('/api/v1/dcim/feeds', json={'item_uid': suyo, 'pdu_uid': a})
        avisos = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()['warnings']
        assert [w['kind'] for w in avisos] == ['single_branch']
        c = _as(admin, 'filial-luz3', ['dcim_view', f'org.{fleet["b"]}.view'])
        p = c.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert [w for w in p['warnings'] if w['kind'] == 'single_branch'] == []

    def test_una_rama_inventada_no_entra(self, client, fleet):
        _login(client)
        r = client.post('/api/v1/dcim/pdus',
                        json={'rack_uid': fleet['rack'], 'feed': 'c', 'name': 'X'})
        assert r.status_code == 400

    def test_quitar_una_regleta_se_lleva_sus_cables(self, client, fleet):
        """Dejarlos sería una lista de equipos alimentados por algo que ya no existe, y el
        recuento de tomas de la siguiente saldría mal sin que nadie supiera por qué."""
        _login(client)
        a, b = self._pdus(client, fleet['rack'])
        client.post('/api/v1/dcim/feeds', json={'item_uid': fleet['mine'], 'pdu_uid': a})
        client.delete(f'/api/v1/dcim/pdus/{a}')
        p = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/power').get_json()
        assert [x['uid'] for x in p['pdus']] == [b]
        assert p['items'] and all(not it['feeds'] for it in p['items'])

    def test_enchufar_es_editar_el_armario(self, admin, client, fleet):
        _login(client)
        a, _ = self._pdus(client, fleet['rack'])
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'rack', 'uid': fleet['rack'], 'org_uid': fleet['it']})
        c = _as(admin, 'filial-luz4', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        r = c.post('/api/v1/dcim/feeds', json={'item_uid': fleet['theirs'], 'pdu_uid': a})
        assert r.status_code == 403

    def test_y_mirar_es_otra_bandera(self, admin, fleet):
        c = _as(admin, 'sin-luz', [])
        assert c.get(f'/api/v1/dcim/racks/{fleet["rack"]}/power').status_code == 403


class TestElColorYLaMaquinaDeUnaRegleta:
    """Dos cosas que hacen usable la pantalla de potencia y que no se ven en el modelo.

    El color, porque un armario se mira desde la puerta de la sala y azul y rojo se distinguen
    de un vistazo. Y la máquina, porque **una PDU gestionada está en el registro como cualquier
    otra cosa que conteste**: enlazarla convierte una fila de inventario en un dato vivo.
    """

    def test_una_regleta_nueva_toma_el_color_de_su_rama(self, client, fleet):
        _login(client)
        a = client.post('/api/v1/dcim/pdus',
                        json={'rack_uid': fleet['rack'], 'feed': 'a'}).get_json()['uid']
        b = client.post('/api/v1/dcim/pdus',
                        json={'rack_uid': fleet['rack'], 'feed': 'b'}).get_json()['uid']
        p = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/power').get_json()
        color = {x['uid']: x['color'] for x in p['pdus']}
        assert color[a] == p['feed_colors']['a'] and color[b] == p['feed_colors']['b']
        assert color[a] != color[b], 'azul y rojo tienen que distinguirse desde la puerta'

    def test_y_el_suyo_manda_si_lo_tiene(self, client, fleet):
        """Hay salas con tres alimentaciones y salas donde el color estaba decidido antes de que
        llegara este panel."""
        _login(client)
        uid = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': fleet['rack'], 'feed': 'a',
                                'color': '#00aa55'}).get_json()['uid']
        p = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/power').get_json()
        assert [x for x in p['pdus'] if x['uid'] == uid][0]['color'] == '#00aa55'

    def test_el_color_lo_resuelve_el_servidor(self, client, fleet):
        """En un solo sitio: dos decidiendo de qué color va la rama A acaban pintándola de dos
        colores distintos en dos vistas de lo mismo."""
        _login(client)
        client.post('/api/v1/dcim/pdus', json={'rack_uid': fleet['rack'], 'feed': 'none'})
        p = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/power').get_json()
        assert p['pdus'][0]['color'] == p['feed_colors']['none']

    def test_una_regleta_se_enlaza_con_una_maquina(self, client, fleet):
        _login(client)
        host = client.post('/api/v1/hosts', json={'name': 'PDU-RACK3', 'address': '10.0.0.9',
                                                  'enabled': True}).get_json()
        uid = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': fleet['rack'], 'feed': 'a'}).get_json()['uid']
        hid = host.get('uid') or (host.get('data') or {}).get('uid')
        client.put(f'/api/v1/dcim/pdus/{uid}', json={'host_uid': hid})
        p = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/power').get_json()
        fila = [x for x in p['pdus'] if x['uid'] == uid][0]
        assert fila['host_uid'] == hid
        # …y con la máquina llega el estado, que es todo el sentido del enlace. Sin checks
        # todavía no hay ninguno, y eso NO es «bien»: es que nadie la mira.
        assert fila['state'] == ''

    def test_y_se_puede_desenlazar(self, client, fleet):
        _login(client)
        uid = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': fleet['rack'], 'host_uid': 'h-x'}).get_json()['uid']
        client.put(f'/api/v1/dcim/pdus/{uid}', json={'host_uid': ''})
        p = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/power').get_json()
        assert [x for x in p['pdus'] if x['uid'] == uid][0]['host_uid'] == ''


class TestElCableadoDeclarado:
    """Las rutas del cableado. Lo que se comprueba aquí es sobre todo el estrechamiento y que la
    pantalla abre aunque el mapa de la flota no esté disponible."""

    def test_se_declara_un_cable_y_vuelve_con_sus_nombres(self, client, fleet):
        _login(client)
        r = client.post('/api/v1/dcim/cables',
                        json={'a_item': fleet['mine'], 'a_port': 'Gi1/0/7',
                              'b_item': fleet['theirs'], 'b_port': 'eth0',
                              'label': 'A-07', 'color': '#3b82f6'})
        assert r.status_code == 200
        d = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/cables').get_json()
        fila = d['cables'][0]
        assert fila['label'] == 'A-07'
        assert fila['a_label'] == 'SW-CORE' and fila['b_label'] == 'DB03-NOMINAS'

    def test_sin_sondas_la_pantalla_abre_igual(self, client, fleet):
        """Lo declarado se lee aunque no haya nada con lo que contrastarlo.

        Con `check=1`: el contraste se pide aparte desde que esperarlo dejaba la pestaña en
        blanco, y sin pedirlo no hay recuentos porque no se ha mirado nada.
        """
        _login(client)
        client.post('/api/v1/dcim/cables',
                    json={'a_item': fleet['mine'], 'b_item': fleet['theirs']})
        d = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/cables?check=1').get_json()
        assert len(d['cables']) == 1
        assert d['counts']['undeclared'] == 0

    def test_y_la_primera_vuelta_trae_las_filas_sin_recuentos(self, client, fleet):
        _login(client)
        client.post('/api/v1/dcim/cables',
                    json={'a_item': fleet['mine'], 'b_item': fleet['theirs']})
        d = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/cables').get_json()
        assert len(d['cables']) == 1 and d['counts'] == {} and d['checked'] is False

    def test_un_cable_del_vecino_no_es_suyo_que_reconciliar(self, admin, client, fleet):
        """Solo los equipos que este lector ve aportan cables: uno ajeno no es suyo, y su
        etiqueta diría de qué máquina es."""
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Este'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': site, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': room, 'name': 'RE1'}).get_json()['uid']
        suyo = client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': 1,
                                 'label': 'SW-DEPT'}).get_json()['uid']
        otro = client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': 2,
                                 'label': 'DB-DEPT'}).get_json()['uid']
        for uid in (suyo, otro):
            client.post('/api/v1/dcim/owner',
                        json={'scope': 'item', 'uid': uid, 'org_uid': fleet['it']})
        client.post('/api/v1/dcim/cables',
                    json={'a_item': suyo, 'b_item': otro, 'label': 'SECRETA-1'})
        c = _as(admin, 'filial-cable', ['dcim_view', f'org.{fleet["b"]}.view'])
        d = c.get(f'/api/v1/dcim/racks/{rack}/cables').get_json()
        assert d['cables'] == []
        assert 'SECRETA-1' not in str(d)

    def test_declarar_es_su_propia_bandera(self, admin, client, fleet):
        """Tocar el cableado es una bandera aparte de ordenar el armario: mover un equipo de U
        y decir por dónde va un cable son dos trabajos y dos personas."""
        _login(client)
        c = _as(admin, 'solo-ordena', ['dcim_view', 'dcim_all_view', 'dcim_edit'])
        r = c.post('/api/v1/dcim/cables',
                   json={'a_item': fleet['mine'], 'b_item': fleet['theirs']})
        assert r.status_code == 403

    def test_y_se_quita(self, client, fleet):
        _login(client)
        uid = client.post('/api/v1/dcim/cables',
                          json={'a_item': fleet['mine'],
                                'b_item': fleet['theirs']}).get_json()['uid']
        assert client.delete(f'/api/v1/dcim/cables/{uid}').status_code == 200
        d = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}/cables').get_json()
        assert d['cables'] == []


class TestLosEnlacesEntreSedes:
    """Un enlace une DOS sedes, y eso decide su permiso: cambiarlo cambia lo que se ve en las
    dos puntas, así que hace falta poder editar las dos. Pedir permiso sobre una sola dejaría
    dibujar líneas hasta sedes que quien las dibuja no puede ni abrir."""

    def _otra(self, c, nombre='DC Sur'):
        return c.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']

    def test_se_declara_y_sale_en_el_cuadro(self, client, fleet):
        _login(client)
        otra = self._otra(client)
        r = client.post('/api/v1/dcim/links',
                        json={'a_site': fleet['site'], 'b_site': otra, 'kind': 'mpls',
                              'provider': 'Telco A', 'circuit_id': 'TA-99123',
                              'label': 'MPLS-1', 'bandwidth_mbps': 100})
        assert r.status_code == 200
        b = client.get('/api/v1/dcim/board').get_json()
        assert [l['label'] for l in b['links']] == ['MPLS-1']
        assert b['links'][0]['a_name'] and b['links'][0]['b_name']

    def test_un_enlace_a_una_sede_que_no_se_ve_no_se_dibuja(self, admin, client, fleet):
        """El mapa dibuja líneas entre cajas: una línea a una caja que no está sale al vacío."""
        _login(client)
        otra = self._otra(client)
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'site', 'uid': otra, 'org_uid': fleet['it']})
        client.post('/api/v1/dcim/links', json={'a_site': fleet['site'], 'b_site': otra})
        c = _as(admin, 've-una-sola', ['dcim_view'])
        b = c.get('/api/v1/dcim/board').get_json()
        assert b['links'] == []

    def test_hacen_falta_dos_sedes_distintas(self, client, fleet):
        _login(client)
        r = client.post('/api/v1/dcim/links',
                        json={'a_site': fleet['site'], 'b_site': fleet['site']})
        assert r.status_code == 400

    def test_una_clase_inventada_no_entra(self, client, fleet):
        _login(client)
        otra = self._otra(client)
        r = client.post('/api/v1/dcim/links',
                        json={'a_site': fleet['site'], 'b_site': otra, 'kind': 'paloma'})
        assert r.status_code == 400

    def test_hace_falta_poder_editar_LAS_DOS(self, admin, client, fleet):
        _login(client)
        otra = self._otra(client, 'DC Ajeno')
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'site', 'uid': otra, 'org_uid': fleet['it']})
        c = _as(admin, 'media-punta', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        r = c.post('/api/v1/dcim/links', json={'a_site': fleet['site'], 'b_site': otra})
        assert r.status_code == 403

    def test_y_una_punta_no_se_cambia_por_el_cuerpo(self, client, fleet):
        """Mover una punta sería llevar el enlace a una sede cuyo permiso no se ha mirado."""
        _login(client)
        otra, tercera = self._otra(client), self._otra(client, 'DC Este')
        uid = client.post('/api/v1/dcim/links',
                          json={'a_site': fleet['site'], 'b_site': otra}).get_json()['uid']
        client.put(f'/api/v1/dcim/links/{uid}', json={'b_site': tercera, 'label': 'X'})
        b = client.get('/api/v1/dcim/board').get_json()
        fila = b['links'][0]
        assert fila['b_site'] == otra and fila['label'] == 'X'

    def test_se_quita(self, client, fleet):
        _login(client)
        otra = self._otra(client)
        uid = client.post('/api/v1/dcim/links',
                          json={'a_site': fleet['site'], 'b_site': otra}).get_json()['uid']
        assert client.delete(f'/api/v1/dcim/links/{uid}').status_code == 200
        assert client.get('/api/v1/dcim/board').get_json()['links'] == []


class TestDondeCabeEsto:
    """La pantalla que alguien abre con un albarán en la mano: llega un servidor de 2U y 350 W,
    ¿dónde lo meto? Lo que se comprueba aquí es que la ocupación cuenta **lo de todos** aunque
    quien pregunta no pueda ver lo que hay dentro."""

    def test_un_armario_vacio_lo_admite_todo(self, client, fleet):
        _login(client)
        d = client.get('/api/v1/dcim/fits?u=1&branches=0').get_json()
        fila = [r for r in d['racks'] if r['uid'] == fleet['rack']][0]
        assert fila['fits'] is True
        assert fila['site'] and fila['room'], 'dice dónde está, para poder ir'

    def test_la_U_ocupada_por_otro_sigue_ocupada(self, admin, client, fleet):
        """Decir que está libre porque quien pregunta no puede ver lo que hay dentro mandaría a
        alguien con un servidor a un sitio donde no entra."""
        _login(client)
        # El rack de la fixture tiene 42U con dos equipos dentro, uno de ellos ajeno.
        c = _as(admin, 'busca-sitio', ['dcim_view', f'org.{fleet["b"]}.view'])
        # La filial no ve la sede de la fixture, así que se monta un armario sin reclamar.
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Libre'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': site, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': room, 'name': 'RL1', 'u_height': 4}).get_json()['uid']
        ajeno = client.post('/api/v1/dcim/items',
                            json={'rack_uid': rack, 'u_start': 2,
                                  'u_height': 2}).get_json()['uid']
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'item', 'uid': ajeno, 'org_uid': fleet['it']})
        d = c.get('/api/v1/dcim/fits?u=3&branches=0').get_json()
        fila = [r for r in d['racks'] if r['uid'] == rack][0]
        assert fila['fits'] is False, 'las U 2 y 3 están ocupadas aunque no vea por qué'
        assert fila['reasons'][0]['best'] == 1

    def test_pide_dos_ramas_por_defecto(self, client, fleet):
        """Lo normal es lo redundante: un armario que no puede dar dos ramas a un servidor de
        dos fuentes no es un armario donde ese servidor deba ir."""
        _login(client)
        d = client.get('/api/v1/dcim/fits?u=1').get_json()
        fila = [r for r in d['racks'] if r['uid'] == fleet['rack']][0]
        assert d['need']['branches'] == 2
        assert [x['why'] for x in fila['reasons']] == ['no_outlets']

    def test_y_con_las_dos_regletas_puestas_ya_cabe(self, client, fleet):
        _login(client)
        for rama in ('a', 'b'):
            client.post('/api/v1/dcim/pdus',
                        json={'rack_uid': fleet['rack'], 'feed': rama, 'outlets': 8})
        d = client.get('/api/v1/dcim/fits?u=1').get_json()
        fila = [r for r in d['racks'] if r['uid'] == fleet['rack']][0]
        assert fila['fits'] is True

    def test_un_armario_que_no_se_ve_no_sale(self, admin, client, fleet):
        _login(client)
        c = _as(admin, 'sin-armarios', ['dcim_view', f'org.{fleet["b"]}.view'])
        d = c.get('/api/v1/dcim/fits?u=1').get_json()
        assert [r for r in d['racks'] if r['uid'] == fleet['rack']] == []

    def test_hace_falta_la_bandera(self, admin, fleet):
        c = _as(admin, 'nada-fits', [])
        assert c.get('/api/v1/dcim/fits?u=1').status_code == 403


class TestLaHoraLocalDeUnaSede:
    """«Son las cuatro de la mañana allí» es lo que decide si se llama ahora o se espera, y es la
    primera pregunta al mirar una sede que no es la de uno."""

    def test_la_zona_viaja_con_la_sede(self, client, fleet):
        _login(client)
        client.put(f'/api/v1/dcim/sites/{fleet["site"]}',
                   json={'timezone': 'Europe/Madrid'})
        b = client.get('/api/v1/dcim/board').get_json()
        sede = [s for s in b['sites'] if s['uid'] == fleet['site']][0]
        assert sede['timezone'] == 'Europe/Madrid'

    def test_y_sin_zona_es_una_cadena_vacia_y_no_un_hueco(self, client, fleet):
        """Que falte la clave y que la zona esté vacía se leen distinto en el navegador, y solo
        una de las dos es cierta."""
        _login(client)
        b = client.get('/api/v1/dcim/board').get_json()
        sede = [s for s in b['sites'] if s['uid'] == fleet['site']][0]
        assert sede['timezone'] == ''


class TestNoSeCreaDentroDeLoAjeno:
    """Crear algo dentro de un contenedor es escribir en ese contenedor.

    Salió de auditar la sección entera ruta por ruta: el alta genérica de sedes, salas y racks
    validaba el nombre y **no miraba de quién era el padre**, así que alguien con permiso de
    editar y acotado a su sociedad podía crear una sala dentro de una sede que ni siquiera puede
    listar — y a partir de ahí un rack dentro, y equipos dentro del rack.

    No daba ningún error y no se veía: lo creado aparecía en la sede de otro, que es donde el
    dueño de esa sede lo encontraría un día sin saber de dónde salió.
    """

    def _ajena(self, client, fleet):
        """Una sede del departamento, que la filial no puede ni ver."""
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC del IT'}).get_json()['uid']
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'site', 'uid': site, 'org_uid': fleet['it']})
        room = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': site, 'name': 'Sala IT'}).get_json()['uid']
        return site, room

    def test_no_se_crea_una_sala_en_una_sede_ajena(self, admin, client, fleet):
        _login(client)
        site, _ = self._ajena(client, fleet)
        c = _as(admin, 'intruso-sala', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        r = c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'Mía'})
        assert r.status_code == 403
        _login(client)
        salas = [x for s in client.get('/api/v1/dcim/sites').get_json()['sites']
                 if s['uid'] == site for x in s['rooms']]
        assert [x['name'] for x in salas] == ['Sala IT']

    def test_ni_un_rack_en_una_sala_ajena(self, admin, client, fleet):
        _login(client)
        _, room = self._ajena(client, fleet)
        c = _as(admin, 'intruso-rack', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        r = c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'Mío'})
        assert r.status_code == 403

    def test_ni_dentro_de_un_padre_que_no_existe(self, admin, client, fleet):
        """Un uid inventado no puede ser una puerta trasera: sin padre no hay dónde crearlo."""
        _login(client)
        r = client.post('/api/v1/dcim/rooms', json={'site_uid': 'no-existe', 'name': 'X'})
        assert r.status_code == 404

    def test_pero_una_sede_nueva_sigue_creandose(self, admin, fleet):
        """Una sede no está dentro de nada: quien puede editar el inventario puede crear una, y
        no es de nadie hasta que alguien lo diga."""
        c = _as(admin, 'crea-sede', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        assert c.post('/api/v1/dcim/sites', json={'name': 'DC Propio'}).status_code == 200

    def test_y_en_lo_propio_tambien(self, admin, client, fleet):
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Filial'}).get_json()['uid']
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'site', 'uid': site, 'org_uid': fleet['b']})
        c = _as(admin, 'dueno-filial', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        assert c.post('/api/v1/dcim/rooms',
                      json={'site_uid': site, 'name': 'Suya'}).status_code == 200


class TestElNombreDelVecinoNoSaleNiPorLaPuertaDeAtras:
    """Un equipo ajeno se dibuja ocupando y anónimo — pero conserva su `uid`, porque sin él el
    dibujo no podría colocarlo. Ese uid es la puerta de atrás.

    Salió de auditar la sección: la reconciliación de cableado necesita los equipos del OTRO
    extremo para poder nombrarlos, y los cargaba sin preguntar si quien mira puede verlos. Basta
    con declarar un cable hacia el uid del vecino —que la pantalla del rack compartido ya te ha
    dado— para que la respuesta te devuelva su etiqueta.

    No es un fallo de dibujo: es exactamente el dato que el rack compartido existe para no dar.
    """

    def test_declarar_un_cable_hacia_lo_ajeno_no_revela_su_nombre(self, admin, client, fleet):
        _login(client)
        # Un armario compartido: sin dueño, con un equipo del departamento dentro.
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Mixto'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': site, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': room, 'name': 'RM1'}).get_json()['uid']
        del_it = client.post('/api/v1/dcim/items',
                             json={'rack_uid': rack, 'u_start': 20,
                                   'label': 'NOMINAS-DB'}).get_json()['uid']
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'item', 'uid': del_it, 'org_uid': fleet['it']})

        c = _as(admin, 'curiosa', ['dcim_view', 'dcim_edit', 'dcim_cable_edit',
                                   f'org.{fleet["b"]}.view'])
        # La filial mete lo suyo y comprueba que ya conoce el uid del vecino: la pantalla del
        # rack compartido se lo da, porque sin él no podría dibujar la U ocupada.
        mio = c.post('/api/v1/dcim/items',
                     json={'rack_uid': rack, 'u_start': 1, 'label': 'MIO'}).get_json()['uid']
        visto = c.get(f'/api/v1/dcim/racks/{rack}').get_json()['items']
        ajeno = [i for i in visto if i['uid'] != mio][0]
        assert ajeno['uid'] == del_it and not ajeno.get('label'), (
            'el rack compartido da el uid y esconde el nombre — esa es la premisa')

        # Y ahora la puerta de atrás: un cable hacia ese uid.
        c.post('/api/v1/dcim/cables', json={'a_item': mio, 'b_item': del_it})
        d = c.get(f'/api/v1/dcim/racks/{rack}/cables').get_json()
        assert 'NOMINAS-DB' not in str(d), 'el nombre del vecino salió por el otro extremo'


class TestUnRackQueElListadoEsconde:
    """El listado deja fuera los racks que quien mira no puede ver. Abrirlo por uid lo enseñaba.

    Dos pantallas discrepando sobre la misma cosa, y la permisiva alcanzable escribiendo un uid
    — que es la definición de esta clase de agujero. Lo que se ve al abrirlo no es poco: el
    nombre del armario, de qué sociedad es, cuántas U le quedan y cuánto tiene dentro.

    Que un rack COMPARTIDO se pueda abrir no es lo mismo: ese sí se ve en el listado, y lo que
    se esconde de él son los nombres de los equipos ajenos. La regla es una sola y las dos
    pantallas tienen que aplicarla igual.
    """

    def _ajeno(self, client, fleet):
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Cerrado'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': site, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': room, 'name': 'SECRETO-1'}).get_json()['uid']
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'site', 'uid': site, 'org_uid': fleet['it']})
        return rack

    def test_no_sale_en_el_listado(self, admin, client, fleet):
        _login(client)
        rack = self._ajeno(client, fleet)
        c = _as(admin, 'fuera-1', ['dcim_view', f'org.{fleet["b"]}.view'])
        visto = [x for s in c.get('/api/v1/dcim/sites').get_json()['sites']
                 for r in s['rooms'] for x in r.get('rackList', [])]
        assert rack not in [x['uid'] for x in visto]

    def test_y_tampoco_abriendolo_por_uid(self, admin, client, fleet):
        _login(client)
        rack = self._ajeno(client, fleet)
        c = _as(admin, 'fuera-2', ['dcim_view', f'org.{fleet["b"]}.view'])
        r = c.get(f'/api/v1/dcim/racks/{rack}')
        assert r.status_code == 403
        assert 'SECRETO-1' not in str(r.get_json())

    def test_pero_uno_compartido_si_se_abre(self, admin, client, fleet):
        """La otra mitad de la regla: un armario sin reclamar con equipos de varias sociedades
        se abre, y lo que se esconde son los nombres de lo ajeno — no el armario."""
        _login(client)
        site = client.post('/api/v1/dcim/sites', json={'name': 'DC Común'}).get_json()['uid']
        room = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': site, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': room, 'name': 'RC9'}).get_json()['uid']
        ajeno = client.post('/api/v1/dcim/items',
                            json={'rack_uid': rack, 'u_start': 5,
                                  'label': 'NO-MIRAR'}).get_json()['uid']
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'item', 'uid': ajeno, 'org_uid': fleet['it']})
        c = _as(admin, 'comparte', ['dcim_view', f'org.{fleet["b"]}.view'])
        d = c.get(f'/api/v1/dcim/racks/{rack}').get_json()
        assert d['rack']['name'] == 'RC9'
        assert 'NO-MIRAR' not in str(d)
        assert d['free']['count'] < d['free']['height'], 'la U ocupada se sigue viendo ocupada'


class TestLasFilasDeUnaSala:

    def test_se_declara_una_fila_y_viaja_con_el_plano(self, client, fleet):
        _login(client)
        uid = client.post('/api/v1/dcim/rows',
                          json={'room_uid': fleet['room'], 'name': 'B',
                                'front_aisle': 'Frío 1',
                                'rear_aisle': 'Caliente 2'}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()
        assert [f['name'] for f in d['rows']] == ['B']
        assert d['rows'][0]['uid'] == uid

    def test_un_rack_se_pone_en_una_fila_y_la_fila_lo_cuenta(self, client, fleet):
        _login(client)
        uid = client.post('/api/v1/dcim/rows',
                          json={'room_uid': fleet['room'], 'name': 'A'}).get_json()['uid']
        client.put(f'/api/v1/dcim/racks/{fleet["rack"]}', json={'row_uid': uid})
        d = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()
        assert d['rows'][0]['racks'] == 1 and d['loose'] == []

    def test_deshacer_una_fila_no_deshace_sus_armarios(self, client, fleet):
        """Una fila es una forma de ordenar. Borrarla deja los racks sueltos, que es un estado
        real — no se lleva por delante el inventario."""
        _login(client)
        uid = client.post('/api/v1/dcim/rows',
                          json={'room_uid': fleet['room'], 'name': 'A'}).get_json()['uid']
        client.put(f'/api/v1/dcim/racks/{fleet["rack"]}', json={'row_uid': uid})
        assert client.delete(f'/api/v1/dcim/rows/{uid}').status_code == 200
        d = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()
        assert d['rows'] == []
        assert [r['uid'] for r in d['loose']] == [fleet['rack']]

    def test_declararlas_es_ordenar_la_sala(self, admin, client, fleet):
        _login(client)
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'room', 'uid': fleet['room'], 'org_uid': fleet['it']})
        c = _as(admin, 'sin-sala', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        r = c.post('/api/v1/dcim/rows', json={'room_uid': fleet['room'], 'name': 'X'})
        assert r.status_code == 403

    def test_y_el_aviso_del_aire_llega_a_la_pantalla(self, client, fleet):
        _login(client)
        client.post('/api/v1/dcim/rows', json={'room_uid': fleet['room'], 'name': 'A',
                                               'rear_aisle': 'Caliente 1'})
        client.post('/api/v1/dcim/rows', json={'room_uid': fleet['room'], 'name': 'C',
                                               'front_aisle': 'Caliente 1'})
        d = client.get(f'/api/v1/dcim/rooms/{fleet["room"]}/features').get_json()
        assert [w['kind'] for w in d['warnings']] == ['hot_intake']
        assert d['warnings'][0]['label'] == 'C'


class TestLaCadenaElectricaAguasArriba:
    """Las cuatro instalaciones reales, por HTTP. Y lo que se audita: echar un bypass no es
    editar un campo, es una maniobra que deja sin protección a todo lo que cuelga."""

    def _cadena(self, c, site):
        red = c.post('/api/v1/dcim/sources',
                     json={'site_uid': site, 'name': 'Acometida',
                           'kind': 'mains'}).get_json()['uid']
        cg = c.post('/api/v1/dcim/sources',
                    json={'site_uid': site, 'name': 'CGBT', 'kind': 'panel',
                          'upstream_uid': red}).get_json()['uid']
        sai = c.post('/api/v1/dcim/sources',
                     json={'site_uid': site, 'name': 'SAI 1', 'kind': 'ups',
                           'upstream_uid': cg, 'autonomy_min': 8}).get_json()['uid']
        sal = c.post('/api/v1/dcim/sources',
                     json={'site_uid': site, 'name': 'Cuadro salida', 'kind': 'panel',
                           'upstream_uid': sai}).get_json()['uid']
        return red, cg, sai, sal

    def test_la_regleta_dice_de_que_cuadro_cuelga(self, client, fleet):
        _login(client)
        _, _, sai, sal = self._cadena(client, fleet['site'])
        pdu = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': fleet['rack'], 'feed': 'a', 'name': 'PDU-A',
                                'source_uid': sal}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/sources?site={fleet["site"]}').get_json()
        assert [n['name'] for n in d['paths'][pdu]['now']] == [
            'Cuadro salida', 'SAI 1', 'CGBT', 'Acometida']

    def test_una_fuente_se_corrige_sin_borrarla(self, client, fleet):
        """Antes solo se podía declarar y borrar, y al borrar una fuente lo que colgaba de ella
        se queda sin decir de qué cuelga: corregir un nombre costaba rehacer la rama."""
        _login(client)
        red, cg, sai, _ = self._cadena(client, fleet['site'])
        r = client.put(f'/api/v1/dcim/sources/{sai}',
                       json={'name': 'SAI principal', 'capacity_w': 6000,
                             'upstream_uid': red})
        assert r.status_code == 200
        fuentes = {f['uid']: f for f in
                   client.get(f'/api/v1/dcim/sources?site={fleet["site"]}').get_json()['sources']}
        assert fuentes[sai]['name'] == 'SAI principal'
        assert fuentes[sai]['capacity_w'] == 6000
        assert fuentes[sai]['upstream_uid'] == red

    def test_una_fuente_no_puede_colgar_de_si_misma_ni_de_lo_que_cuelga_de_ella(self, client,
                                                                                fleet):
        """El árbol se dibuja desde las raíces hacia abajo, así que una cadena cerrada sobre sí
        misma no tiene raíz: las dos filas del ciclo desaparecen de la pantalla, y con ellas el
        botón con el que se arreglaría. Un dato que se escribe y no se puede corregir es peor que
        uno que se rechaza."""
        _login(client)
        _, cg, sai, _ = self._cadena(client, fleet['site'])
        assert client.put(f'/api/v1/dcim/sources/{cg}',
                          json={'upstream_uid': cg}).status_code == 400
        # `cg` alimenta a `sai`: colgarlo de él cerraría la cadena.
        assert client.put(f'/api/v1/dcim/sources/{cg}',
                          json={'upstream_uid': sai}).status_code == 400
        fuentes = {f['uid']: f for f in
                   client.get(f'/api/v1/dcim/sources?site={fleet["site"]}').get_json()['sources']}
        assert fuentes[cg]['upstream_uid'] not in (cg, sai)

    def test_un_padre_que_no_existe_no_entra(self, client, fleet):
        """Se dibuja lo que cuelga de la raíz y hacia abajo: una fila cuyo padre no existe no
        está bajo la raíz ni bajo nadie, y no se dibuja — desaparece sin decir por qué."""
        _login(client)
        assert client.post('/api/v1/dcim/sources',
                           json={'site_uid': fleet['site'], 'name': 'Huérfano',
                                 'kind': 'panel',
                                 'upstream_uid': 'no-existe'}).status_code == 400
        _, cg, _, _ = self._cadena(client, fleet['site'])
        assert client.put(f'/api/v1/dcim/sources/{cg}',
                          json={'upstream_uid': 'no-existe'}).status_code == 400

    def test_clonar_una_fuente_se_lleva_lo_que_cuelga(self, client, fleet):
        """Un cuadro de sala se declara igual en la sala de al lado, con sus SAI y sus cuadros de
        salida detrás: a mano son quince filas y cuatro sitios donde equivocarse de padre."""
        _login(client)
        red, cg, sai, sal = self._cadena(client, fleet['site'])
        r = client.post(f'/api/v1/dcim/sources/{cg}/clone')
        assert r.status_code == 200
        assert r.get_json()['n'] == 3          # el cuadro, su SAI y el cuadro de salida
        nuevo = r.get_json()['uid']
        fuentes = {f['uid']: f for f in
                   client.get(f'/api/v1/dcim/sources?site={fleet["site"]}').get_json()['sources']}
        # La copia cuelga de donde colgaba el original, no del original.
        assert fuentes[nuevo]['upstream_uid'] == red
        # Y lo que colgaba cuelga de la COPIA: si apuntara al viejo, el clon sería una fila
        # suelta y el original tendría dos ramas iguales.
        clones = [f for f in fuentes.values() if f['upstream_uid'] == nuevo]
        assert [f['name'] for f in clones] == ['SAI 1']
        assert fuentes[sai]['upstream_uid'] == cg

    def test_el_clon_no_se_lleva_el_bypass_ni_lo_enchufado(self, client, fleet):
        """El bypass es una maniobra en curso y no una forma de estar cableado: copiarlo sería
        afirmar que a la copia también se le está saltando ahora mismo. Y una regleta cuelga de
        la fuente, no es la fuente."""
        _login(client)
        _, cg, sai, sal = self._cadena(client, fleet['site'])
        client.put(f'/api/v1/dcim/sources/{sai}', json={'bypass': 1})
        client.post('/api/v1/dcim/pdus', json={'rack_uid': fleet['rack'], 'feed': 'a',
                                               'name': 'PDU-A', 'source_uid': sal})
        client.post(f'/api/v1/dcim/sources/{cg}/clone')
        d = client.get(f'/api/v1/dcim/sources?site={fleet["site"]}').get_json()
        copias = [f for f in d['sources'] if f['kind'] == 'ups' and f['uid'] != sai]
        assert copias and all(not int(f['bypass'] or 0) for f in copias)
        # Una sola regleta: la del original. La copia no se lleva lo que hay enchufado.
        assert len(d['paths']) == 1

    def test_echar_el_bypass_saca_al_SAI_de_la_cadena_y_lo_dice(self, client, fleet):
        _login(client)
        _, _, sai, sal = self._cadena(client, fleet['site'])
        pdu = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': fleet['rack'], 'feed': 'a', 'name': 'PDU-A',
                                'source_uid': sal}).get_json()['uid']
        client.put(f'/api/v1/dcim/sources/{sai}', json={'bypass': 1})
        d = client.get(f'/api/v1/dcim/sources?site={fleet["site"]}').get_json()
        assert 'SAI 1' not in [n['name'] for n in d['paths'][pdu]['now']]
        malo = [w for w in d['warnings'] if w['kind'] == 'on_bypass']
        assert malo and malo[0]['ups'] == ['SAI 1']

    def test_y_esa_maniobra_queda_en_la_auditoria(self, admin, client, fleet):
        """Quién lo echó y cuándo es lo primero que se pregunta cuando algo se apaga tres meses
        después."""
        _login(client)
        _, _, sai, _ = self._cadena(client, fleet['site'])
        client.put(f'/api/v1/dcim/sources/{sai}', json={'bypass': 1})
        tienda = getattr(admin, '_audit_store', None)
        if tienda is None:
            pytest.skip('sin almacén de auditoría en esta configuración')
        eventos = [e for e in tienda.get_all() if e.get('event') == 'dcim_bypass']
        assert eventos, 'la maniobra no dejó rastro'
        detalle = eventos[0].get('detail')
        if isinstance(detalle, str):
            import json as _json
            detalle = _json.loads(detalle)
        assert detalle['name'] == 'SAI 1' and detalle['on'] is True

    def test_borrar_un_cuadro_deja_lo_de_abajo_SIN_DECIR_de_que_cuelga(self, client, fleet):
        """Dejar el uid apuntando a nada haría que la cadena terminara en un sitio que no
        existe y nadie sabría por qué."""
        _login(client)
        _, _, sai, sal = self._cadena(client, fleet['site'])
        pdu = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': fleet['rack'], 'feed': 'a',
                                'source_uid': sal}).get_json()['uid']
        client.delete(f'/api/v1/dcim/sources/{sal}')
        d = client.get(f'/api/v1/dcim/sources?site={fleet["site"]}').get_json()
        assert d['paths'][pdu]['known'] is False
        assert 'SAI 1' in [f['name'] for f in d['sources']], 'el SAI sigue existiendo'

    def test_una_clase_inventada_no_entra(self, client, fleet):
        _login(client)
        r = client.post('/api/v1/dcim/sources',
                        json={'site_uid': fleet['site'], 'name': 'X', 'kind': 'molino'})
        assert r.status_code == 400

    def test_declararla_es_editar_la_sede(self, admin, client, fleet):
        _login(client)
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'site', 'uid': fleet['site'], 'org_uid': fleet['it']})
        c = _as(admin, 'sin-sede-luz', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        r = c.post('/api/v1/dcim/sources',
                   json={'site_uid': fleet['site'], 'name': 'Mío', 'kind': 'panel'})
        assert r.status_code == 403


class TestLoQueLlevaDentroUnEquipo:
    """Los componentes cuelgan de un equipo, así que el permiso es el del equipo — y eso importa
    en un armario compartido: los discos del servidor de la filial no son cosa del departamento,
    aunque el armario sea suyo.

    Un componente ajeno **no se lista siquiera**. A diferencia de un equipo, que tiene que salir
    ocupando U para que la sala sea planificable, un disco no ocupa nada que nadie más necesite
    saber.
    """

    def test_se_apunta_lo_que_lleva(self, client, fleet):
        _login(client)
        r = client.post('/api/v1/dcim/parts',
                        json={'item_uid': fleet['mine'], 'kind': 'disk', 'slot': 'bahía 1-6',
                              'model': 'ST4000NM', 'size': '4 TB', 'qty': 6})
        assert r.status_code == 200
        d = client.get(f'/api/v1/dcim/items/{fleet["mine"]}/parts').get_json()
        assert d['parts'][0]['qty'] == 6 and d['parts'][0]['size'] == '4 TB'

    def test_seis_discos_son_una_fila_con_un_seis(self, client, fleet):
        """Nadie apunta el número de serie de cada uno, y obligar a ello garantiza que no se
        apunte ninguno."""
        _login(client)
        client.post('/api/v1/dcim/parts',
                    json={'item_uid': fleet['mine'], 'kind': 'disk', 'qty': 6})
        d = client.get(f'/api/v1/dcim/items/{fleet["mine"]}/parts').get_json()
        assert len(d['parts']) == 1

    def test_una_clase_inventada_no_entra(self, client, fleet):
        _login(client)
        r = client.post('/api/v1/dcim/parts',
                        json={'item_uid': fleet['mine'], 'kind': 'reactor'})
        assert r.status_code == 400

    def test_de_un_equipo_ajeno_no_se_lista_ni_uno(self, admin, client, fleet):
        _login(client)
        client.post('/api/v1/dcim/parts',
                    json={'item_uid': fleet['mine'], 'kind': 'disk', 'serial': 'SECRETO-9'})
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'item', 'uid': fleet['mine'], 'org_uid': fleet['it']})
        c = _as(admin, 'curiosa-partes', ['dcim_view', f'org.{fleet["b"]}.view'])
        r = c.get(f'/api/v1/dcim/items/{fleet["mine"]}/parts')
        assert r.status_code == 403
        assert 'SECRETO-9' not in str(r.get_json())

    def test_ni_se_le_pueden_meter(self, admin, client, fleet):
        _login(client)
        client.post('/api/v1/dcim/owner',
                    json={'scope': 'item', 'uid': fleet['mine'], 'org_uid': fleet['it']})
        c = _as(admin, 'mete-partes', ['dcim_view', 'dcim_edit', f'org.{fleet["b"]}.view'])
        r = c.post('/api/v1/dcim/parts', json={'item_uid': fleet['mine'], 'kind': 'disk'})
        assert r.status_code == 403

    def test_corregir_una_pieza_no_pierde_lo_que_no_se_toca(self, client, fleet):
        """El rodeo —quitarla y volver a añadirla— pierde lo que no se estaba corrigiendo, que en
        la pieza de una máquina es el número de serie."""
        _login(client)
        uid = client.post('/api/v1/dcim/parts',
                          json={'item_uid': fleet['mine'], 'kind': 'disk', 'slot': 'bahía 1',
                                'model': 'ST4000', 'serial': 'SN-7',
                                'qty': 1}).get_json()['uid']
        assert client.put(f'/api/v1/dcim/parts/{uid}',
                          json={'slot': 'bahía 3', 'qty': 2}).status_code == 200
        p = client.get(f'/api/v1/dcim/items/{fleet["mine"]}/parts').get_json()['parts'][0]
        assert p['slot'] == 'bahía 3' and p['qty'] == 2
        assert p['serial'] == 'SN-7' and p['model'] == 'ST4000'

    def test_un_componente_no_se_muda_de_equipo_por_el_cuerpo(self, client, fleet):
        _login(client)
        uid = client.post('/api/v1/dcim/parts',
                          json={'item_uid': fleet['mine'], 'kind': 'psu'}).get_json()['uid']
        client.put(f'/api/v1/dcim/parts/{uid}',
                   json={'item_uid': fleet['theirs'], 'size': '750 W'})
        d = client.get(f'/api/v1/dcim/items/{fleet["mine"]}/parts').get_json()
        assert len(d['parts']) == 1 and d['parts'][0]['size'] == '750 W'

    def test_el_rol_de_un_equipo_se_valida(self, client, fleet):
        _login(client)
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': fleet['rack'], 'u_start': 30, 'role': 'tostadora'})
        assert r.status_code == 400

    def test_y_un_panel_de_parcheo_deja_de_contar_como_sin_vigilar(self, client, fleet):
        """El cambio que se ve en la pantalla: el armario deja de pedir explicaciones sobre
        algo que no contesta por naturaleza."""
        _login(client)
        antes = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['roll']
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': fleet['rack'], 'u_start': 40, 'u_height': 1,
                          'label': 'Patch 1-24', 'role': 'patch_panel'})
        d = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['roll']
        assert d['total'] == antes['total'] + 1
        assert d['unwatched'] == antes['unwatched'], 'el panel no añadió un desatendido'
        assert d['passive'] == 1


class TestLasPlantillasDeEquipo:
    """El escalón entre el catálogo y el inventario: lo que de verdad se compra.

    Un R740 es un chasis; lo que se pide veinte veces es ese chasis **con** doce DIMM, ocho
    discos y una controladora. Lo que se prueba aquí es que eso se declara una vez y sale
    veinte, y las dos decisiones que lo sostienen: que las piezas se **copian** al equipo —y
    desde entonces son suyas— y que la diferencia con la plantilla es un dato, no un error.
    """

    def _plantilla(self, client, nombre='CPD estándar 2024', **extra):
        cuerpo = dict({'name': nombre, 'role': 'server'}, **extra)
        return client.post('/api/v1/dcim/builds', json=cuerpo).get_json()['uid']

    def test_se_escribe_una_y_se_lee_con_sus_cuentas(self, client, fleet):
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'memory', 'model': 'KSM32RD8/32', 'size': '32 GB', 'qty': 12})
        d = client.get('/api/v1/dcim/builds').get_json()
        fila = [b for b in d['builds'] if b['uid'] == uid][0]
        assert fila['parts'] == 1 and fila['items'] == 0
        assert 'server' in d['roles'] and 'memory' in d['part_kinds']

    def test_dos_estandares_con_el_mismo_nombre_no_se_distinguen(self, client, fleet):
        _login(client)
        self._plantilla(client)
        r = client.post('/api/v1/dcim/builds', json={'name': 'CPD estándar 2024'})
        assert r.status_code == 400

    def test_crear_un_equipo_desde_una_plantilla_copia_sus_piezas(self, client, fleet):
        """El punto entero: doce DIMM y ocho discos se declaran UNA vez y salen veinte."""
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'memory', 'model': 'KSM32RD8/32', 'qty': 12})
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'disk', 'model': 'PM9A3', 'qty': 8})
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': fleet['rack'], 'u_start': 20, 'u_height': 1,
                              'label': 'SRV-01', 'build_uid': uid})
        assert r.status_code == 200 and r.get_json()['parts'] == 2
        item = r.get_json()['uid']
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        assert sorted(p['qty'] for p in d['parts']) == [8, 12]

    def test_lo_copiado_no_lleva_el_numero_de_serie_de_nadie(self, client, fleet):
        """Es lo único que tiene esa unidad y ninguna otra: heredarlo sería veinte máquinas con
        el mismo serial, que es peor que ninguno."""
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts', json={'kind': 'disk', 'model': 'X'})
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': uid}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        assert d['parts'][0]['serial'] == ''

    def test_la_altura_y_el_rol_salen_puestos(self, client, fleet):
        _login(client)
        # En décimas, como el catálogo: `20` son dos U.
        uid = self._plantilla(client, u_tenths=20)
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': uid}).get_json()['uid']
        fila = [i for i in client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
                if i['uid'] == item][0]
        assert fila['u_height'] == 2 and fila['role'] == 'server'

    def test_y_si_la_plantilla_no_la_fija_sale_del_modelo_del_catalogo(self, admin, client,
                                                                      fleet):
        """Un R740 mide lo que mide se le ponga lo que se le ponga: la altura está escrita en el
        catálogo, y repetirla en la plantilla sería tenerla en dos sitios."""
        _login(client)
        modelo = admin._dcim_catalog.create(                      # noqa: SLF001
            {'manufacturer': 'Dell', 'model': 'R740', 'u_tenths': 20})
        uid = self._plantilla(client, type_uid=modelo)
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': uid}).get_json()['uid']
        fila = [i for i in client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
                if i['uid'] == item][0]
        assert fila['u_height'] == 2

    def test_lo_que_se_teclea_manda_sobre_la_plantilla(self, client, fleet):
        """El fondo que alguien acaba de medir con un metro vale más que el del estándar de hace
        un año — y una plantilla que pisa lo tecleado deja de servir para lo que casi encaja."""
        _login(client)
        # En décimas, como el catálogo: `20` son dos U.
        uid = self._plantilla(client, u_tenths=20)
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20, 'u_height': 1,
                                 'role': 'switch', 'build_uid': uid}).get_json()['uid']
        fila = [i for i in client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
                if i['uid'] == item][0]
        assert fila['u_height'] == 1 and fila['role'] == 'switch'

    def test_las_piezas_del_equipo_son_suyas_desde_el_momento_en_que_existen(self, client,
                                                                            fleet):
        """Si el equipo las leyera de su plantilla, editar el estándar rescribiría la ficha de
        veinte máquinas que nadie ha tocado."""
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts', json={'kind': 'disk', 'model': 'X'})
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': uid}).get_json()['uid']
        client.post(f'/api/v1/dcim/builds/{uid}/parts', json={'kind': 'gpu', 'model': 'A2'})
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        assert len(d['parts']) == 1, 'la máquina cambió sola'

    def test_el_equipo_recuerda_de_que_plantilla_nacio(self, client, fleet):
        """Sin eso, «cuáles son los veinte del estándar de 2024» no tiene respuesta."""
        _login(client)
        uid = self._plantilla(client)
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': uid}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        assert d['build']['name'] == 'CPD estándar 2024'
        assert client.get('/api/v1/dcim/builds').get_json()['builds'][0]['items'] == 1

    def test_y_lo_que_lleva_de_mas_y_de_menos_se_puede_leer(self, client, fleet):
        """Ninguna de las dos partes es «el error»: que le hayan cambiado los discos es un hecho
        sobre esa máquina, y la diferencia ES el dato."""
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'disk', 'model': 'PM9A3', 'qty': 8})
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': uid}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        assert d['diff'] == [], 'recién creado no puede diferir de su plantilla'
        client.delete(f'/api/v1/dcim/parts/{d["parts"][0]["uid"]}')
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        assert d['diff'][0]['want'] == 8 and d['diff'][0]['have'] == 0

    def test_retirar_la_plantilla_no_toca_los_equipos(self, client, fleet):
        """Nacieron de esto, y eso siguió siendo verdad después de que alguien retirara el
        estándar. Lo que se pierde es poder mirar de qué constaba."""
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts', json={'kind': 'disk', 'model': 'X'})
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': uid}).get_json()['uid']
        r = client.delete(f'/api/v1/dcim/builds/{uid}')
        assert r.status_code == 200 and r.get_json()['items'] == 1
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        assert len(d['parts']) == 1 and 'build' not in d

    def test_la_plantilla_dice_que_maquina_sale_de_ella(self, client, fleet):
        """Quince renglones de piezas no contestan «qué máquina es esta» sin sumarlos a mano — y
        los núcleos de una CPU están en la ficha del catálogo, no en la pieza."""
        _login(client)
        cpu = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'Intel', 'model': 'Xeon 6248',
                                'tree': 'component-types', 'kind': 'cpu',
                                'extra': {'cores': 20, 'threads': 40}}).get_json()['uid']
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'memory', 'model': 'KSM', 'size': '32 GB', 'qty': 12})
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'ssd', 'model': 'PM9A3', 'size': '1.92 TB', 'qty': 8})
        client.post(f'/api/v1/dcim/builds/{uid}/parts', json={'type_uid': cpu, 'qty': 2})
        d = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['summary']
        assert d['memory_gb'] == 384 and d['storage_tb'] == 15.36
        assert d['cpus'] == 2 and d['cores'] == 40 and d['unknown'] == 0

    def test_la_plantilla_ensena_el_ciclo_de_vida_del_chasis(self, client, fleet):
        """Lo que se buscaba al mirar «se compra desde» y no estaba: cuándo salió el equipo y
        cuándo se le acaban los parches. Son del catálogo, no del estándar de compra — dos cosas
        distintas que se confundían porque las dos son fechas y las dos están en esta pantalla."""
        _login(client)
        base = client.post('/api/v1/dcim/catalog',
                           json={'manufacturer': 'HP', 'model': 'EliteDesk 800 G5 Mini',
                                 'u_tenths': 10,
                                 'extra': {'launched': '2019-08-29',
                                           'eol': '2024-08-29'}}).get_json()['uid']
        uid = self._plantilla(client, type_uid=base)
        d = client.get(f'/api/v1/dcim/builds/{uid}').get_json()
        assert d['build']['base']['extra']['eol'] == '2024-08-29'
        assert [c['name'] for c in d['lifecycle']][-1] == 'eol'

    def test_los_puertos_se_guardan_con_su_tipo(self, client, fleet):
        """Un modelo escrito a mano tiene que poder decir de qué clase son sus bocas: sin eso,
        un switch tecleado aquí dice «24 puertos» y no «24 × 1000base-t», que es lo que hace
        falta para saber si el transceptor sirve. Y dos tomas distintas de la misma familia
        —`iec-60320-c14` y `dc-terminal`— son dos renglones del mismo equipo."""
        _login(client)
        uid = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'Genérico', 'model': 'Switch 24',
                                'u_tenths': 10,
                                'ports': {'interfaces': {'1000base-t': 24},
                                          'power-ports': {'iec-60320-c14': 2,
                                                          'dc-terminal': 1}}}).get_json()['uid']
        fila = [r for r in client.get('/api/v1/dcim/catalog').get_json()['types']
                if r['uid'] == uid][0]
        assert fila['ports']['interfaces'] == {'1000base-t': 24}
        assert fila['ports']['power-ports'] == {'iec-60320-c14': 2, 'dc-terminal': 1}

    def test_y_la_familia_que_faltaba_entra(self, client, fleet):
        """`console-server-ports` es la caja a la que se enchufan las consolas de los demás. Sin
        ella no había dónde decir que un equipo tiene dieciséis."""
        _login(client)
        uid = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'Genérico', 'model': 'Consolas',
                                'u_tenths': 10,
                                'ports': {'console-server-ports': {'rj-45': 16}}
                                }).get_json()['uid']
        fila = [r for r in client.get('/api/v1/dcim/catalog').get_json()['types']
                if r['uid'] == uid][0]
        assert fila['ports']['console-server-ports'] == {'rj-45': 16}

    def test_el_resumen_cuenta_lo_que_el_chasis_trae_de_serie(self, client, fleet):
        """Y esta es la que no daba error. `summary()` sabía doblar los puertos del chasis desde
        el primer día; lo que faltaba era que la ruta los PIDIERA — la lista de campos del
        modelo base decía, en un comentario, que los puertos sobraban. Un campo que no se pide
        no falla: sale un cero que parece un dato, y el mini-PC con su puerto en la placa decía
        tener solo la tarjeta que alguien le añadió.
        """
        _login(client)
        base = client.post('/api/v1/dcim/catalog',
                           json={'manufacturer': 'HP', 'model': 'EliteDesk 800 G5 Mini',
                                 'u_tenths': 10, 'power_type': 'external',
                                 'ports': {'interfaces': {'1000base-t': 1},
                                           'power-ports': {'dc-terminal': 1}}}).get_json()['uid']
        uid = self._plantilla(client, type_uid=base)
        d = client.get(f'/api/v1/dcim/builds/{uid}').get_json()
        assert {'speed': '1000base-t', 'ports': 1} in d['summary']['net']
        assert d['summary']['power_type'] == 'external'
        # Y en la ficha del chasis, que es donde la pantalla lo pinta.
        assert d['build']['base']['power_type'] == 'external'

    def test_un_estandar_de_medio_u_se_puede_escribir(self, client, fleet):
        """El bloque de medidas preguntaba «cuántas U» en enteros, así que un patch panel de
        0,5 U no se podía describir — que es justo el caso que hay delante. En décimas, como el
        catálogo: una sola unidad en los dos sitios."""
        _login(client)
        uid = self._plantilla(client, u_tenths=5, u_slots=2, u_split='height')
        b = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert b['u_tenths'] == 5 and b['u_slots'] == 2 and b['u_split'] == 'height'

    def test_y_el_equipo_que_sale_de_ella_lo_hereda(self, client, fleet):
        """De eso sirve escribirlo una vez. El equipo ocupa UN U —uno de 0,5 U ocupa un U y
        comparte sus mitades, que es lo que pasa en el armario— y sabe que lo comparte."""
        _login(client)
        uid = self._plantilla(client, nombre='Panel 0,5U', u_tenths=5, u_slots=2,
                              u_split='height')
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': fleet['rack'], 'u_start': 30, 'build_uid': uid,
                              'label': 'Panel A'})
        assert r.status_code == 200, r.get_json()
        item = [i for i in client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
                if i.get('label') == 'Panel A'][0]
        assert item['u_height'] == 1 and item['u_slots'] == 2
        assert item['u_split'] == 'height'
        # Y por eso cabe el segundo en el mismo U.
        assert client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 30, 'build_uid': uid,
                                 'label': 'Panel B', 'u_slot': 2}).status_code == 200

    def test_elegir_un_modelo_es_traerse_lo_suyo(self, client, fleet):
        """**Se estampa, no se enlaza** — la misma regla que entre una plantilla y un equipo, un
        escalón más arriba. Leerlo en vivo deja la plantilla enseñando huecos el día que alguien
        retira ese modelo o reimporta la biblioteca, que regenera los `uid`."""
        _login(client)
        base = client.post('/api/v1/dcim/catalog',
                           json={'manufacturer': 'HP', 'model': 'EliteDesk 800 G5 Mini',
                                 'u_tenths': 10, 'airflow': 'passive',
                                 'power_type': 'external',
                                 'ports': {'interfaces': {'1000base-t': 1}},
                                 'extra': {'eol': '2024-08-29'}}).get_json()['uid']
        uid = self._plantilla(client, type_uid=base)
        b = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert b['manufacturer'] == 'HP' and b['model'] == 'EliteDesk 800 G5 Mini'
        assert b['u_tenths'] == 10 and b['airflow'] == 'passive'
        assert b['power_type'] == 'external'
        assert b['ports'] == {'interfaces': {'1000base-t': 1}}
        assert b['extra']['eol'] == '2024-08-29'

    def test_y_desde_entonces_el_catalogo_ya_no_manda(self, client, fleet):
        """Retirar el modelo no puede vaciar la plantilla: eso es lo que significa copiar. Y
        corregir la plantilla no toca el catálogo, que sigue diciendo lo que dice."""
        _login(client)
        base = client.post('/api/v1/dcim/catalog',
                           json={'manufacturer': 'HP', 'model': 'Mini', 'u_tenths': 10,
                                 'ports': {'interfaces': {'1000base-t': 1}}}).get_json()['uid']
        uid = self._plantilla(client, type_uid=base)
        client.put(f'/api/v1/dcim/builds/{uid}',
                   json={'name': 'CPD estándar 2024',
                         'ports': {'interfaces': {'2.5gbase-t': 2}}})
        assert client.delete(f'/api/v1/dcim/catalog/{base}').status_code == 200
        b = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert b['model'] == 'Mini', 'la plantilla se quedó sin su chasis'
        assert b['ports'] == {'interfaces': {'2.5gbase-t': 2}}

    def test_guardar_la_ficha_no_deshace_lo_corregido(self, client, fleet):
        """Volver a copiar en cada guardado sería la mitad de para lo que sirve copiar: solo se
        trae al CAMBIAR de modelo."""
        _login(client)
        base = client.post('/api/v1/dcim/catalog',
                           json={'manufacturer': 'HP', 'model': 'Mini',
                                 'u_tenths': 10}).get_json()['uid']
        uid = self._plantilla(client, type_uid=base)
        client.put(f'/api/v1/dcim/builds/{uid}',
                   json={'name': 'CPD estándar 2024', 'type_uid': base, 'model': 'Mini G9'})
        b = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert b['model'] == 'Mini G9'

    def test_pero_cambiar_de_modelo_si_vuelve_a_traerlo_todo(self, client, fleet):
        """Elegir otro chasis y quedarse con los puertos del anterior sería peor que cualquiera
        de las dos cosas."""
        _login(client)
        uno = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'HP', 'model': 'Mini',
                                'u_tenths': 10}).get_json()['uid']
        dos = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'Dell', 'model': 'R740',
                                'u_tenths': 20}).get_json()['uid']
        uid = self._plantilla(client, type_uid=uno)
        client.put(f'/api/v1/dcim/builds/{uid}',
                   json={'name': 'CPD estándar 2024', 'type_uid': dos})
        b = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert b['manufacturer'] == 'Dell' and b['u_tenths'] == 20

    def test_clonar_una_se_lleva_lo_que_llevaba(self, client, fleet):
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts', json={'kind': 'memory', 'qty': 12})
        copia = client.post('/api/v1/dcim/builds', json={'from': uid}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/builds/{copia}').get_json()
        assert len(d['parts']) == 1 and d['parts'][0]['qty'] == 12

    def test_una_plantilla_guarda_lo_que_no_cabe_en_un_renglon(self, client, fleet):
        """Comentarios, vigencia y con qué sale. La descripción es un renglón y lo que hay que
        contar de un estándar no cabe en uno: por qué se eligió ese chasis, qué se probó y no
        valía. Eso hoy vive en un correo, y el correo se pierde antes que el servidor."""
        _login(client)
        plat = client.post('/api/v1/dcim/platforms',
                           json={'name': 'Debian', 'version': '12'}).get_json()['uid']
        uid = self._plantilla(client)
        r = client.put(f'/api/v1/dcim/builds/{uid}',
                       json={'name': 'CPD estándar 2024', 'notes': 'el de 12 discos no cabía',
                             'valid_from': '2024-01-01', 'valid_to': '2024-11-30',
                             'platform_uid': plat})
        assert r.status_code == 200
        b = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert b['notes'] == 'el de 12 discos no cabía'
        assert b['valid_from'] == '2024-01-01' and b['valid_to'] == '2024-11-30'
        assert b['platform_uid'] == plat

    def test_clonarla_se_lleva_los_comentarios_pero_no_la_vigencia(self, client, fleet):
        """Copiar un estándar es copiar por qué es así. Las fechas NO: la copia se hace para el
        año que viene, y heredar «se compró hasta noviembre de 2024» sería nacer caducada."""
        _login(client)
        uid = self._plantilla(client)
        client.put(f'/api/v1/dcim/builds/{uid}',
                   json={'name': 'CPD estándar 2024', 'notes': 'por qué es así',
                         'valid_to': '2024-11-30'})
        copia = client.post('/api/v1/dcim/builds', json={'from': uid}).get_json()['uid']
        b = client.get(f'/api/v1/dcim/builds/{copia}').get_json()['build']
        assert b['notes'] == 'por qué es así' and b['valid_to'] == ''


    def test_escribir_el_estandar_pide_su_propia_bandera(self, admin, client, fleet):
        """Decidir lo que se compra y colocar una caja en un U los hacen personas distintas: con
        una sola bandera, quien monta un rack rescribe lo que compra la empresa."""
        _login(client)
        uid = self._plantilla(client)
        c = _as(admin, 'monta-racks', ['dcim_view', 'dcim_edit'])
        assert c.get('/api/v1/dcim/builds').status_code == 200, 'hay que poder ELEGIR una'
        assert c.post('/api/v1/dcim/builds', json={'name': 'Otra'}).status_code == 403
        assert c.put(f'/api/v1/dcim/builds/{uid}', json={'name': 'X'}).status_code == 403
        assert c.delete(f'/api/v1/dcim/builds/{uid}').status_code == 403
        assert c.post(f'/api/v1/dcim/builds/{uid}/parts',
                      json={'kind': 'disk'}).status_code == 403

    def test_una_pieza_de_una_plantilla_se_puede_corregir(self, client, fleet):
        """Estaba construido y probado desde el principio y en la tabla solo había una papelera:
        una función que solo existe en la API es una función que no existe."""
        _login(client)
        uid = self._plantilla(client)
        pieza = client.post(f'/api/v1/dcim/builds/{uid}/parts',
                            json={'kind': 'memory', 'model': 'KSM', 'slot': 'A1',
                                  'qty': 2}).get_json()['uid']
        assert client.put(f'/api/v1/dcim/build-parts/{pieza}',
                          json={'qty': 4, 'slot': 'A1-A4'}).status_code == 200
        p = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['parts'][0]
        assert p['qty'] == 4 and p['slot'] == 'A1-A4' and p['model'] == 'KSM'

    def test_una_clase_de_pieza_inventada_no_entra_en_una_plantilla(self, client, fleet):
        _login(client)
        uid = self._plantilla(client)
        assert client.post(f'/api/v1/dcim/builds/{uid}/parts',
                           json={'kind': 'reactor'}).status_code == 400

    def test_de_que_nacio_no_se_edita(self, client, fleet):
        """Ya ocurrió. Cambiarlo sería reescribir el origen de una máquina sin tocar ni una de
        sus piezas: una fila que afirma algo que no pasó, y difícil de descubrir."""
        _login(client)
        uid = self._plantilla(client)
        otra = self._plantilla(client, nombre='Otro estándar')
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': uid}).get_json()['uid']
        client.put(f'/api/v1/dcim/items/{item}', json={'build_uid': otra, 'label': 'SRV-9'})
        fila = [i for i in client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
                if i['uid'] == item][0]
        assert fila['build_uid'] == uid and fila['label'] == 'SRV-9'

    def test_una_plantilla_que_no_existe_no_se_apunta(self, client, fleet):
        """Guardar el texto tal cual dejaría una máquina afirmando haber nacido de algo que no
        está — y eso no da ningún error el día que se escribe."""
        _login(client)
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': 'lo que alguien tecleó'}).get_json()['uid']
        fila = [i for i in client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
                if i['uid'] == item][0]
        assert fila['build_uid'] == ''

    def test_la_compra_y_la_garantia_viven_en_el_equipo(self, client, fleet):
        """Ningún modelo ni plantilla puede saberlo: es de ESA caja, y sin ello «qué se queda
        sin garantía este trimestre» no tiene dónde contestarse."""
        _login(client)
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20, 'label': 'SRV',
                                 'purchased_at': '2024-03-01',
                                 'warranty_until': '2027-03-01',
                                 'supplier': 'Distribuidora Norte'}).get_json()['uid']
        fila = [i for i in client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
                if i['uid'] == item][0]
        assert fila['warranty_until'] == '2027-03-01'
        assert fila['supplier'] == 'Distribuidora Norte'

    def test_la_ficha_sirve_lo_que_hay_que_preguntar_de_un_chasis(self, client, fleet):
        """La ventilación y el peso los declara el documento de perfiles, y estaban servidos solo
        en el catálogo: una plantilla los enseñaba y no había forma de corregirlos, aunque desde
        que copia el dato es suyo. Un campo servido en un sitio y no en otro no da ningún error —
        da una casilla que no existe."""
        _login(client)
        uid = self._plantilla(client)
        d = client.get(f'/api/v1/dcim/builds/{uid}').get_json()
        assert [c['name'] for c in d['fields']] == ['airflow', 'weight', 'weight_unit']
        assert 'external' in d['power_types']

    def test_la_ventilacion_y_el_peso_se_corrigen_en_la_plantilla(self, client, fleet):
        _login(client)
        uid = self._plantilla(client)
        r = client.put(f'/api/v1/dcim/builds/{uid}',
                       json={'airflow': 'front-to-rear', 'power_type': 'external',
                             'full_depth': 0, 'extra': {'weight': 1.2, 'weight_unit': 'kg'}})
        assert r.status_code == 200
        fila = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert fila['airflow'] == 'front-to-rear' and fila['power_type'] == 'external'
        assert fila['full_depth'] == 0 and fila['extra']['weight'] == 1.2

    def test_una_plantilla_cambia_su_propia_foto(self, admin, client, fleet):
        """Llegan copiadas del catálogo, y copiadas quiere decir **suyas**: la del catálogo es la
        del chasis desnudo y la de aquí puede ser la del equipo montado. Sin esto la única forma
        de corregir una era corregir el modelo del que salió — de donde cuelgan también las otras
        veinte plantillas."""
        _login(client)
        uid = self._plantilla(client)
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 32
        r = client.post(f'/api/v1/dcim/builds/{uid}/image/front',
                        data={'file': (io.BytesIO(png), 'foto.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 200
        fila = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert fila['front_image'] == r.get_json()['image']

    def test_la_foto_que_sustituye_se_borra_del_disco(self, admin, client, fleet):
        """Sin eso, cada cambio deja un fichero al que no apunta nadie y la carpeta crece durante
        toda la vida de la instalación."""
        _login(client)
        from lib.core.dcim import media
        var = admin._var_dir or ''                             # noqa: SLF001
        uid = self._plantilla(client)
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 32
        for _ in range(2):
            client.post(f'/api/v1/dcim/builds/{uid}/image/front',
                        data={'file': (io.BytesIO(png), 'f.png')},
                        content_type='multipart/form-data')
        fila = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert media.every(var) == [fila['front_image']]
        assert client.delete(f'/api/v1/dcim/builds/{uid}/image/front').status_code == 200
        assert media.every(var) == []

    def test_lo_que_no_es_una_imagen_no_entra_en_una_plantilla(self, client, fleet):
        _login(client)
        uid = self._plantilla(client)
        r = client.post(f'/api/v1/dcim/builds/{uid}/image/front',
                        data={'file': (io.BytesIO(b'no soy una imagen'), 'foto.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 400

    def test_una_cara_que_no_existe_tampoco_en_una_plantilla(self, client, fleet):
        _login(client)
        uid = self._plantilla(client)
        r = client.post(f'/api/v1/dcim/builds/{uid}/image/lateral',
                        data={'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 32),
                                       'f.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 404

    def test_el_historial_dice_que_cambio_y_quien(self, client, fleet):
        """Una plantilla es un dato compartido: de ella salieron veinte máquinas y es el estándar
        con el que se compra. La corrección que rompe algo se descubre cuando alguien dice «esto
        antes llevaba ocho discos» — y sin esto no hay forma de saber si tiene razón."""
        _login(client)
        uid = self._plantilla(client)
        client.put(f'/api/v1/dcim/builds/{uid}', json={'notes': 'no cabía el otro'})
        client.post(f'/api/v1/dcim/builds/{uid}/parts', json={'kind': 'disk', 'qty': 8})
        d = client.get(f'/api/v1/dcim/builds/{uid}/history').get_json()
        assert [h['action'] for h in d['history']] == ['part_add', 'edit', 'create']
        assert d['history'][1]['changes']['notes'][1] == 'no cabía el otro'
        # De qué constaba, que es lo que se le pregunta a esto.
        assert len(d['history'][0]['data']['parts']) == 1

    def test_volver_a_una_version_es_un_cambio_mas(self, client, fleet):
        """No borra lo de en medio: si lo borrara, la respuesta a «quién dejó esto así» sería
        distinta según cuándo se preguntara."""
        _login(client)
        uid = self._plantilla(client)
        client.put(f'/api/v1/dcim/builds/{uid}', json={'notes': 'primera'})
        primera = client.get(f'/api/v1/dcim/builds/{uid}/history').get_json()['history'][0]
        client.put(f'/api/v1/dcim/builds/{uid}', json={'notes': 'segunda'})
        r = client.post(f'/api/v1/dcim/builds/{uid}/restore', json={'rev': primera['uid']})
        assert r.status_code == 200
        fila = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert fila['notes'] == 'primera'
        d = client.get(f'/api/v1/dcim/builds/{uid}/history').get_json()
        assert d['history'][0]['action'] == 'restore'
        assert len(d['history']) == 4          # nada de lo de en medio desapareció

    def test_volver_atras_no_toca_los_componentes(self, client, fleet):
        """La versión los guarda para poder leerlos, pero reescribirlos sería borrar y recrear
        doce filas con `uid` nuevos — y de esas cuelgan las ya estampadas en los equipos."""
        _login(client)
        uid = self._plantilla(client)
        vieja = client.get(f'/api/v1/dcim/builds/{uid}/history').get_json()['history'][0]
        client.post(f'/api/v1/dcim/builds/{uid}/parts', json={'kind': 'disk', 'qty': 8})
        client.post(f'/api/v1/dcim/builds/{uid}/restore', json={'rev': vieja['uid']})
        assert len(client.get(f'/api/v1/dcim/builds/{uid}').get_json()['parts']) == 1

    def test_una_version_de_otra_plantilla_no_vale(self, client, fleet):
        _login(client)
        a = self._plantilla(client, 'A')
        b = self._plantilla(client, 'B')
        suya = client.get(f'/api/v1/dcim/builds/{a}/history').get_json()['history'][0]
        r = client.post(f'/api/v1/dcim/builds/{b}/restore', json={'rev': suya['uid']})
        assert r.status_code == 404

    def test_el_historial_se_lee_con_permiso_de_consultar(self, client, fleet):
        """Mirar lo que decía ayer es leer, y quien no puede editarla sigue necesitando saber si
        cambió bajo sus pies."""
        _login(client)
        uid = self._plantilla(client)
        assert client.get(f'/api/v1/dcim/builds/{uid}/history').status_code == 200

    def test_los_conectores_llegan_tambien_a_la_ficha(self, client, fleet):
        """Esta pantalla se abre sin pasar por el catálogo, y un vocabulario que solo llega por un
        camino es una casilla que sugiere o no según por dónde se haya entrado."""
        _login(client)
        uid = self._plantilla(client)
        d = client.get(f'/api/v1/dcim/builds/{uid}').get_json()
        fams = d['connectors']
        assert 'iec-60320-c14' in [c['id'] for c in fams['power-ports']]
        # Y donde NO va: una C14 es una toma de entrada y nunca una boca de red.
        assert 'iec-60320-c14' not in [c['id'] for c in fams['interfaces']]

    def test_el_catalogo_de_conectores_se_puede_sustituir(self, client, fleet):
        """Como los perfiles y por lo mismo: editar un fichero del disco no vale en un despliegue
        con contenedor web y contenedor de trabajos —comparten la base y no el disco—, ni
        sobrevive a una actualización, ni viaja en la copia de seguridad."""
        _login(client)
        antes = client.get('/api/v1/dcim/connectors').get_json()
        assert antes['packaged'] >= 1 and antes['stored'] == 0
        r = client.put('/api/v1/dcim/connectors',
                       json={'version': antes['packaged'] + 1,
                             'connectors': [{'id': 'el-mio', 'name': 'El de la sala',
                                             'group': 'other', 'families': ['interfaces']}]})
        assert r.status_code == 200
        d = client.get('/api/v1/dcim/connectors').get_json()
        assert d['stored'] == antes['packaged'] + 1
        assert [c['id'] for c in d['connectors']['interfaces']] == ['el-mio']

    def test_lo_que_se_descarta_se_dice(self, client, fleet):
        """Un conector con una familia mal escrita se guardaría igual, no saldría en ninguna
        casilla, y quien lo escribió creería que funcionó."""
        _login(client)
        r = client.put('/api/v1/dcim/connectors',
                       json={'version': 900,
                             'connectors': [{'id': 'a', 'families': ['interfaces']},
                                            {'id': 'b', 'families': ['inventada']}]})
        assert r.status_code == 200
        assert any('b' in x for x in r.get_json()['dropped'])

    def test_sin_version_no_se_guarda_y_lo_dice(self, client, fleet):
        _login(client)
        r = client.put('/api/v1/dcim/connectors',
                       json={'connectors': [{'id': 'a', 'families': ['interfaces']}]})
        assert r.status_code == 400 and r.get_json()['error']

    def test_volver_al_que_viene_con_el_panel(self, client, fleet):
        _login(client)
        client.put('/api/v1/dcim/connectors',
                   json={'version': 900,
                         'connectors': [{'id': 'a', 'families': ['interfaces']}]})
        assert client.delete('/api/v1/dcim/connectors').status_code == 200
        d = client.get('/api/v1/dcim/connectors').get_json()
        assert d['stored'] == 0
        assert 'iec-60320-c19' in [c['id'] for c in d['connectors']['power-outlets']]

    def test_cada_guardado_deja_version_y_no_se_mezcla(self, client, fleet):
        """De aquí sale lo que se ofrece al decir por dónde se enchufa algo: «¿esto quién lo
        cambió?» es la pregunta del mes siguiente. Y es otro documento que el de perfiles."""
        _login(client)
        client.put('/api/v1/dcim/connectors',
                   json={'version': 900, 'connectors': [{'id': 'a',
                                                         'families': ['interfaces']}]})
        h = client.get('/api/v1/dcim/connectors/history').get_json()['history']
        assert len(h) == 1 and h[0]['version'] == 900 and h[0]['count'] == 1
        assert client.get('/api/v1/dcim/profiles/history').get_json()['history'] == []

    def test_el_que_manda_es_el_que_llega_a_las_plantillas(self, client, fleet):
        """Servido por dos caminos —el catálogo y la ficha de una plantilla— y tiene que ser el
        mismo: un vocabulario que dependa de por dónde se entre son dos vocabularios."""
        _login(client)
        client.put('/api/v1/dcim/connectors',
                   json={'version': 900,
                         'connectors': [{'id': 'el-mio', 'families': ['interfaces']}]})
        build = client.post('/api/v1/dcim/builds', json={'name': 'Con conector propio'})
        uid = build.get_json()['uid']
        d = client.get(f'/api/v1/dcim/builds/{uid}').get_json()
        assert [c['id'] for c in d['connectors']['interfaces']] == ['el-mio']

    def test_las_bahias_se_guardan_con_nombre(self, client, fleet):
        """Un puerto se cuenta; una bahía es un SITIO y de un sitio se pregunta cuál. «Dos bahías
        de módulo» no dice en cuál está el DIMM que hay puesto."""
        _login(client)
        uid = self._plantilla(client)
        r = client.put(f'/api/v1/dcim/builds/{uid}',
                       json={'ports': {'module-bays': {'sodimm': 2}},
                             'port_list': {'module-bays': [
                                 {'name': 'SODIMM-1', 'type': 'sodimm'},
                                 {'name': 'SODIMM-2', 'type': 'sodimm'}]}})
        assert r.status_code == 200
        fila = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert [x['name'] for x in fila['port_list']['module-bays']] == ['SODIMM-1', 'SODIMM-2']

    def test_un_componente_dice_en_que_bahia_va(self, client, fleet):
        """Es lo que hace que la lista sirva de algo: sin el hueco, la bahía no sabe qué lleva."""
        _login(client)
        uid = self._plantilla(client)
        client.put(f'/api/v1/dcim/builds/{uid}',
                   json={'port_list': {'module-bays': [{'name': 'SODIMM-1', 'type': 'sodimm'}]}})
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'memory', 'model': 'KSM32', 'slot': 'SODIMM-1'})
        d = client.get(f'/api/v1/dcim/builds/{uid}').get_json()
        assert d['parts'][0]['slot'] == 'SODIMM-1'

    def test_el_hueco_viaja_al_equipo_que_sale_de_la_plantilla(self, client, fleet):
        """Se estampa con lo demás: el día que alguien abra la caja, la ficha del EQUIPO tiene
        que decir en qué ranura está cada módulo, no la de la plantilla."""
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'memory', 'model': 'KSM32', 'slot': 'SODIMM-1'})
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 30, 'label': 'SRV',
                                 'build_uid': uid}).get_json()['uid']
        piezas = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()['parts']
        assert [p['slot'] for p in piezas] == ['SODIMM-1']

    def test_las_bahias_se_copian_al_elegir_el_modelo_del_catalogo(self, admin, client, fleet):
        """Vienen de la biblioteca con nombre, y la plantilla se las trae con lo demás — si no,
        habría que teclear a mano lo que el fichero ya decía."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        modelo = cat.create({'manufacturer': 'HP', 'model': 'Mini',
                             'port_list': {'module-bays': [{'name': 'SODIMM-1',
                                                            'type': 'sodimm'}]}})
        uid = client.post('/api/v1/dcim/builds',
                          json={'name': 'Con bahías', 'type_uid': modelo}).get_json()['uid']
        fila = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['build']
        assert [x['name'] for x in fila['port_list']['module-bays']] == ['SODIMM-1']

    def test_un_kit_puede_decir_las_dos_ranuras_en_las_que_va(self, client, fleet):
        """Un kit de dos módulos se compra junto y se monta en dos ranuras distintas: esa es la
        gracia del kit. Con un solo hueco, la mitad no tenía dónde decir en cuál está."""
        _login(client)
        uid = self._plantilla(client)
        client.put(f'/api/v1/dcim/builds/{uid}',
                   json={'port_list': {'module-bays': [{'name': 'SODIMM-1', 'type': 'sodimm'},
                                                       {'name': 'SODIMM-2', 'type': 'sodimm'}]}})
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'memory', 'model': 'CT2K32G4S266M', 'kit_qty': 2,
                          'slot': 'SODIMM-1, SODIMM-2'})
        pieza = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['parts'][0]
        assert pieza['slot'] == 'SODIMM-1, SODIMM-2' and pieza['kit_qty'] == 2

    def test_las_dos_ranuras_del_kit_viajan_al_equipo(self, client, fleet):
        """Se estampa con lo demás: el día que alguien abra la caja tiene que saber en cuál de
        las dos está cada módulo."""
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'memory', 'model': 'CT2K32G4S266M', 'kit_qty': 2,
                          'slot': 'SODIMM-1, SODIMM-2'})
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 32, 'label': 'SRV2',
                                 'build_uid': uid}).get_json()['uid']
        piezas = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()['parts']
        assert piezas[0]['slot'] == 'SODIMM-1, SODIMM-2'

    def test_lo_que_cuelga_se_distingue_de_lo_que_va_dentro(self, client, fleet):
        """«Cinco componentes» no dice cuántos hay que desmontar para llevarse la caja."""
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'memory', 'model': 'CT2K'})
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'nic', 'model': 'UG-USBC-25052', 'mount': 'external',
                          'slot': 'USB-1'})
        piezas = client.get(f'/api/v1/dcim/builds/{uid}').get_json()['parts']
        fuera = [p for p in piezas if p.get('mount') == 'external']
        assert len(piezas) == 2 and len(fuera) == 1 and fuera[0]['slot'] == 'USB-1'

    def test_una_palabra_inventada_no_llega_a_la_tabla(self, client, fleet):
        """Sin acotarlo, la pieza desaparecería de las dos pestañas: no es de dentro ni de
        fuera, y ninguna la enseña."""
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'nic', 'mount': 'en-la-mesa'})
        assert client.get(f'/api/v1/dcim/builds/{uid}').get_json()['parts'][0]['mount'] == ''

    def test_lo_externo_viaja_al_equipo(self, client, fleet):
        _login(client)
        uid = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{uid}/parts',
                    json={'kind': 'nic', 'model': 'UG-USBC-25052', 'mount': 'external',
                          'slot': 'USB-1'})
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 34, 'label': 'SRV3',
                                 'build_uid': uid}).get_json()['uid']
        piezas = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()['parts']
        assert piezas[0]['mount'] == 'external' and piezas[0]['slot'] == 'USB-1'


class TestLosModelosDeComponente:
    """El cuarto árbol del catálogo, y el único que no viene de ninguna biblioteca.

    Los `module-types` de NetBox son tarjetas de línea y transceptores; la memoria, los discos y
    las CPU no están en ningún repositorio público. Se escriben una vez y se reutilizan siempre.
    """

    def test_un_componente_usa_las_clases_de_una_pieza(self, client):
        _login(client)
        uid = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'Kingston', 'model': 'KSM32RD8/32',
                                'tree': 'component-types', 'kind': 'memory'}).get_json()['uid']
        d = client.get('/api/v1/dcim/catalog?tree=component-types').get_json()
        fila = [x for x in d['types'] if x['uid'] == uid][0]
        assert fila['kind'] == 'memory' and fila['tree'] == 'component-types'

    def test_y_no_las_de_los_que_ocupan_u(self, client):
        """Ofrecer «switch» para un DIMM acabaría ofreciendo el DIMM en un alzado."""
        _login(client)
        uid = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'Kingston', 'model': 'KSM32 DDR4 RDIMM',
                                'tree': 'component-types',
                                'kind': 'switch'}).get_json()['uid']
        d = client.get('/api/v1/dcim/catalog?tree=component-types').get_json()
        fila = [x for x in d['types'] if x['uid'] == uid][0]
        assert fila['kind'] == 'memory', 'la dedujo del nombre en vez de aceptar la de otro árbol'

    def test_corregir_la_clase_sin_mandar_el_arbol_sigue_valiendo(self, client):
        """Se cambia solo la clase, así que el árbol no viene en la petición: el de la fila que
        ya existe es el que decide qué vocabulario se aplica."""
        _login(client)
        uid = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'Samsung', 'model': 'PM9A3',
                                'tree': 'component-types'}).get_json()['uid']
        assert client.put(f'/api/v1/dcim/catalog/{uid}', json={'kind': 'ssd'}).status_code == 200
        d = client.get('/api/v1/dcim/catalog?tree=component-types').get_json()
        assert [x for x in d['types'] if x['uid'] == uid][0]['kind'] == 'ssd'

    def test_el_catalogo_se_puede_mirar_por_forma(self, client):
        """Nadie busca «un armario o un DIMM»: se viene sabiendo cuál de las cuatro cosas se
        quiere."""
        _login(client)
        client.post('/api/v1/dcim/catalog',
                    json={'manufacturer': 'Kingston', 'model': 'DIMM',
                          'tree': 'component-types', 'kind': 'memory'})
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Dell', 'model': 'R740'})
        d = client.get('/api/v1/dcim/catalog?tree=component-types').get_json()
        assert [x['model'] for x in d['types']] == ['DIMM']
        assert d['tree'] == 'component-types'
        assert 'component-types' in d['trees'] and 'component-types' not in d['library_trees']
        assert 'memory' in d['kinds_by_tree']['component-types']
        assert 'memory' not in d['kinds_by_tree']['device-types']
        # Y el catálogo de conectores: `iec-60320-c19` es lo que dice la biblioteca y «IEC C19»
        # es lo que dice alguien en una sala. Vivía en una constante del navegador, que no se
        # puede leer desde aquí.
        c19 = [c for c in d['connectors']['power-outlets'] if c['id'] == 'iec-60320-c19']
        assert c19 and c19[0]['name'] == 'IEC C19'
        assert c19[0]['group'] == 'power-out'
        # Y cuánto hay detrás de cada pestaña, de una sola respuesta: pedirlos al abrir cada
        # una haría que el número apareciera o no según por dónde se hubiera pasado, que es el
        # mismo fallo que tuvo la columna Plataforma de las plantillas. Un número en una
        # pestaña y no en las demás dice menos que ninguno.
        assert set(d['counts']) == {'brands', 'platforms', 'schemas', 'connectors'}
        assert d['counts']['brands'] == 2          # Kingston y Dell, de las dos altas de arriba
        assert d['counts']['connectors'] > 50

    def test_y_las_marcas_obedecen_al_mismo_filtro(self, client):
        """Si no, la rejilla de fabricantes enseñaría los trescientos de la biblioteca mientras
        la tabla enseña los dos que venden memoria."""
        _login(client)
        client.post('/api/v1/dcim/catalog',
                    json={'manufacturer': 'Kingston', 'model': 'DIMM',
                          'tree': 'component-types', 'kind': 'memory'})
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Dell', 'model': 'R740'})
        d = client.get('/api/v1/dcim/catalog?tree=component-types').get_json()
        assert [m[0] for m in d['makers']] == ['Kingston']


class TestLasMarcas:
    """La raíz del catálogo, que hasta ahora era una cadena de texto repetida ocho mil veces.

    Lo que se prueba aquí es lo que aquella columna no podía hacer: que las marcas se den de alta
    solas al importar, que renombrar una no pierda sus modelos, y que retirar su ficha se niegue
    mientras los tenga — no por integridad referencial, sino porque el nombre volvería solo en el
    siguiente arranque y lo único perdido sería lo que escribimos nosotros.
    """

    def test_salen_con_cuantos_modelos_tiene_cada_una(self, client):
        _login(client)
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Dell', 'model': 'R740'})
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Dell', 'model': 'R640'})
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Cisco', 'model': 'C9300'})
        d = client.get('/api/v1/dcim/brands').get_json()
        cuentas = {b['name']: b['models'] for b in d['brands']}
        assert cuentas == {'Cisco': 1, 'Dell': 2}

    def test_dos_formas_del_mismo_nombre_son_una_marca(self, client):
        """`HP`, `H.P.` y `hp` son la misma, y la biblioteca las escribe de las tres formas."""
        _login(client)
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'H.P.', 'model': 'DL380'})
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'hp', 'model': 'DL360'})
        d = client.get('/api/v1/dcim/brands').get_json()
        assert len(d['brands']) == 1 and d['brands'][0]['models'] == 2

    def test_se_escribe_una_para_lo_que_todavia_no_hay(self, client):
        _login(client)
        r = client.post('/api/v1/dcim/brands',
                        json={'name': 'Taller Pérez', 'support_url': 'https://t.example',
                              'account': 'AB-1'})
        assert r.status_code == 200
        fila = client.get('/api/v1/dcim/brands').get_json()['brands'][0]
        assert fila['support_url'] == 'https://t.example' and fila['account'] == 'AB-1'

    def test_dos_que_se_llaman_igual_no_se_distinguen(self, client):
        _login(client)
        client.post('/api/v1/dcim/brands', json={'name': 'Dell'})
        assert client.post('/api/v1/dcim/brands', json={'name': 'dell'}).status_code == 400

    def test_no_se_retira_la_ficha_de_una_que_tiene_modelos(self, client):
        """El nombre sigue escrito en cada fila del catálogo, así que el repaso del arranque la
        daría de alta otra vez: lo único perdido sería la web de soporte y el número de cliente,
        que es justo lo que no se puede volver a descargar."""
        _login(client)
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Dell', 'model': 'R740'})
        uid = client.get('/api/v1/dcim/brands').get_json()['brands'][0]['uid']
        r = client.delete(f'/api/v1/dcim/brands/{uid}')
        assert r.status_code == 400 and r.get_json()['models'] == 1

    def test_y_una_sin_ninguno_si(self, client):
        _login(client)
        uid = client.post('/api/v1/dcim/brands', json={'name': 'Taller'}).get_json()['uid']
        assert client.delete(f'/api/v1/dcim/brands/{uid}').status_code == 200
        assert client.get('/api/v1/dcim/brands').get_json()['brands'] == []

    def test_los_modelos_se_acotan_por_la_marca_como_fila(self, client):
        _login(client)
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Dell', 'model': 'R740'})
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Cisco', 'model': 'C9300'})
        uid = [b for b in client.get('/api/v1/dcim/brands').get_json()['brands']
               if b['name'] == 'Dell'][0]['uid']
        d = client.get(f'/api/v1/dcim/catalog?brand_uid={uid}').get_json()
        assert [x['model'] for x in d['types']] == ['R740']

    def test_renombrarla_no_pierde_sus_modelos(self, client):
        """Que es el punto entero de que sea una fila: acotar por el texto dejaría de encontrar
        nada el día que «HP» pase a ser «Hewlett Packard Enterprise»."""
        _login(client)
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'HP', 'model': 'DL380'})
        uid = client.get('/api/v1/dcim/brands').get_json()['brands'][0]['uid']
        assert client.put(f'/api/v1/dcim/brands/{uid}',
                          json={'name': 'Hewlett Packard Enterprise'}).status_code == 200
        d = client.get(f'/api/v1/dcim/catalog?brand_uid={uid}').get_json()
        assert [x['model'] for x in d['types']] == ['DL380']
        assert client.get('/api/v1/dcim/brands').get_json()['brands'][0]['models'] == 1

    def test_renombrar_una_encima_de_otra_no(self, client):
        _login(client)
        a = client.post('/api/v1/dcim/brands', json={'name': 'Dell'}).get_json()['uid']
        client.post('/api/v1/dcim/brands', json={'name': 'HPE'})
        assert client.put(f'/api/v1/dcim/brands/{a}', json={'name': 'hpe'}).status_code == 400

    def test_leerlas_no_pide_el_permiso_de_importar(self, admin, client):
        """La dirección por la que se abre un ticket es lo que hace falta a las tres de la
        mañana, y esa es la hora a la que nadie tiene el permiso bueno."""
        _login(client)
        client.post('/api/v1/dcim/brands', json={'name': 'Dell'})
        c = _as(admin, 'mira-marcas', ['dcim_view', 'dcim_catalog_view'])
        assert c.get('/api/v1/dcim/brands').status_code == 200
        assert c.post('/api/v1/dcim/brands', json={'name': 'Otra'}).status_code == 403

    def test_el_slug_no_llega_por_la_peticion(self, client):
        """Dejarlo escribir sería dejar que dos marcas se hicieran pasar por la misma."""
        _login(client)
        uid = client.post('/api/v1/dcim/brands',
                          json={'name': 'Dell', 'slug': 'hpe'}).get_json()['uid']
        fila = [b for b in client.get('/api/v1/dcim/brands').get_json()['brands']
                if b['uid'] == uid][0]
        assert fila['slug'] == 'dell'


class TestUnComponenteSaleDelCatalogo:
    """Un SSD no es de esta plantilla ni de esta máquina: es un modelo que va en veinte.

    Escrito a mano en cada sitio son once formas de teclear «Samsung PM9A3» que no se pueden
    contar juntas — y contar juntas es la única pregunta que se le hace a esto: cuántos de estos
    tengo y dónde están. Así que la marca, el nombre y el tamaño los pone **el catálogo**, y los
    resuelve el servidor: si los copiara cada pantalla, dos caminos escribirían dos cosas
    distintas de la misma pieza y el segundo tardaría meses en descubrirse.
    """

    def _modelo(self, client, **extra):
        cuerpo = dict({'manufacturer': 'Samsung', 'model': 'PM9A3',
                       'tree': 'component-types', 'kind': 'ssd', 'size': '1.92 TB'}, **extra)
        return client.post('/api/v1/dcim/catalog', json=cuerpo).get_json()['uid']

    def _plantilla(self, client):
        return client.post('/api/v1/dcim/builds',
                           json={'name': 'CPD estándar'}).get_json()['uid']

    def test_un_modelo_de_componente_tiene_tamano(self, client):
        _login(client)
        uid = self._modelo(client)
        d = client.get('/api/v1/dcim/catalog?tree=component-types').get_json()
        assert [x for x in d['types'] if x['uid'] == uid][0]['size'] == '1.92 TB'

    def test_el_catalogo_dice_cuantos_hay_de_cada_forma(self, client):
        """La tira de formas se dibuja con esas cuentas. Sin ellas habría que pedir el catálogo
        cuatro veces para poder enseñar cuatro números — o no enseñarlos, que es como los
        componentes acabaron siendo una sección a la que había que llegar adivinando."""
        _login(client)
        self._modelo(client)
        client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Dell', 'model': 'R740'})
        d = client.get('/api/v1/dcim/catalog').get_json()
        cuentas = {x['name']: x['count'] for x in d['tree_counts']}
        assert cuentas == {'component-types': 1, 'device-types': 1}
        assert set(d['trees']) == {'device-types', 'module-types', 'rack-types',
                                   'component-types'}

    def test_la_pieza_de_una_plantilla_sale_de_el(self, client, fleet):
        _login(client)
        modelo, plantilla = self._modelo(client), self._plantilla(client)
        r = client.post(f'/api/v1/dcim/builds/{plantilla}/parts',
                        json={'type_uid': modelo, 'slot': 'bahía 1-8', 'qty': 8})
        assert r.status_code == 200
        p = client.get(f'/api/v1/dcim/builds/{plantilla}').get_json()['parts'][0]
        assert p['brand'] == 'Samsung' and p['model'] == 'PM9A3'
        assert p['size'] == '1.92 TB' and p['kind'] == 'ssd' and p['qty'] == 8

    def test_el_catalogo_manda_sobre_lo_que_se_teclee(self, client, fleet):
        """Dejar ganar a la petición sería dejar que la misma pieza se llamara de dos formas
        según por qué pantalla entrara."""
        _login(client)
        modelo, plantilla = self._modelo(client), self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{plantilla}/parts',
                    json={'type_uid': modelo, 'brand': 'Otra', 'model': 'Otro',
                          'size': '999 TB'})
        p = client.get(f'/api/v1/dcim/builds/{plantilla}').get_json()['parts'][0]
        assert (p['brand'], p['model'], p['size']) == ('Samsung', 'PM9A3', '1.92 TB')

    def test_pero_la_bahia_y_la_cantidad_son_de_la_pieza(self, client, fleet):
        _login(client)
        modelo, plantilla = self._modelo(client), self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{plantilla}/parts',
                    json={'type_uid': modelo, 'slot': 'DIMM A1', 'qty': 4})
        p = client.get(f'/api/v1/dcim/builds/{plantilla}').get_json()['parts'][0]
        assert p['slot'] == 'DIMM A1' and p['qty'] == 4

    def test_un_kit_dice_cuantas_piezas_trae(self, client, fleet):
        """Se compra como uno y se monta como dos: la pregunta del inventario quiere la segunda
        cifra y la del pedido quiere la primera."""
        _login(client)
        modelo = client.post('/api/v1/dcim/catalog',
                             json={'manufacturer': 'Kingston', 'model': 'KSM-2x16',
                                   'tree': 'component-types', 'kind': 'memory',
                                   'size': '16 GB', 'kit_qty': 2}).get_json()['uid']
        plantilla = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{plantilla}/parts',
                    json={'type_uid': modelo, 'qty': 3})
        p = client.get(f'/api/v1/dcim/builds/{plantilla}').get_json()['parts'][0]
        # Tres cajas, seis módulos: las dos cifras, cada una en su sitio.
        assert p['qty'] == 3 and p['kit_qty'] == 2

    def test_y_lo_dice_tambien_en_la_maquina(self, client, fleet):
        _login(client)
        modelo = client.post('/api/v1/dcim/catalog',
                             json={'manufacturer': 'Kingston', 'model': 'KSM-2x16',
                                   'tree': 'component-types', 'kind': 'memory',
                                   'kit_qty': 2}).get_json()['uid']
        client.post('/api/v1/dcim/parts',
                    json={'item_uid': fleet['mine'], 'type_uid': modelo, 'qty': 2})
        p = client.get(f'/api/v1/dcim/items/{fleet["mine"]}/parts').get_json()['parts'][0]
        assert p['kit_qty'] == 2

    def test_lo_que_se_compra_suelto_trae_una(self, client, fleet):
        """Es la mayoría, y no tiene por qué declarar un uno."""
        _login(client)
        modelo = client.post('/api/v1/dcim/catalog',
                             json={'manufacturer': 'Samsung', 'model': 'PM9A3',
                                   'tree': 'component-types', 'kind': 'ssd'}).get_json()['uid']
        d = client.get('/api/v1/dcim/catalog?tree=component-types').get_json()
        assert [x for x in d['types'] if x['uid'] == modelo][0]['kit_qty'] == 1

    def test_un_modelo_que_no_existe_no_se_apunta(self, client, fleet):
        """Guardar el identificador dejaría una pieza afirmando venir de algo que no está, y eso
        no da ningún error el día que se escribe."""
        _login(client)
        plantilla = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{plantilla}/parts',
                    json={'type_uid': 'no-existe', 'kind': 'disk', 'model': 'Del cajón'})
        p = client.get(f'/api/v1/dcim/builds/{plantilla}').get_json()['parts'][0]
        assert p['type_uid'] == '' and p['model'] == 'Del cajón'

    def test_lo_mismo_para_la_pieza_de_una_maquina(self, client, fleet):
        """El mismo modelo y el mismo camino: es lo que hace que se puedan contar juntas."""
        _login(client)
        modelo = self._modelo(client)
        client.post('/api/v1/dcim/parts',
                    json={'item_uid': fleet['mine'], 'type_uid': modelo, 'qty': 2})
        p = client.get(f'/api/v1/dcim/items/{fleet["mine"]}/parts').get_json()['parts'][0]
        assert p['brand'] == 'Samsung' and p['size'] == '1.92 TB' and p['kind'] == 'ssd'

    def test_y_llega_al_equipo_al_crearlo_desde_la_plantilla(self, client, fleet):
        _login(client)
        modelo, plantilla = self._modelo(client), self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{plantilla}/parts',
                    json={'type_uid': modelo, 'qty': 8})
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': fleet['rack'], 'u_start': 20,
                                 'build_uid': plantilla}).get_json()['uid']
        p = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()['parts'][0]
        assert p['brand'] == 'Samsung' and p['type_uid'] == modelo and p['qty'] == 8

    def test_a_mano_sigue_valiendo_para_lo_que_no_esta_en_el_catalogo(self, client, fleet):
        """El disco que salió del cajón no está en ningún catálogo y sigue siendo un disco."""
        _login(client)
        plantilla = self._plantilla(client)
        client.post(f'/api/v1/dcim/builds/{plantilla}/parts',
                    json={'kind': 'disk', 'brand': 'Sin marca', 'model': 'El del cajón',
                          'size': '2 TB'})
        p = client.get(f'/api/v1/dcim/builds/{plantilla}').get_json()['parts'][0]
        assert p['brand'] == 'Sin marca' and p['type_uid'] == ''


class TestElHistorialDeUnaFicha:
    """Un modelo del catálogo es un dato compartido: de él cuelgan las plantillas, las piezas
    estampadas en veinte máquinas y la altura con la que se dibuja un alzado.

    La corrección que rompe algo casi nunca se descubre el día que se hace — se descubre semanas
    después, cuando alguien dice «esto antes ponía otra cosa» y no hay forma de saber si tiene
    razón.
    """

    def _modelo(self, client):
        return client.post('/api/v1/dcim/catalog',
                           json={'manufacturer': 'Dell', 'model': 'R740'}).get_json()['uid']

    def test_dice_quien_y_que_cambio(self, client):
        _login(client)
        uid = self._modelo(client)
        client.put(f'/api/v1/dcim/catalog/{uid}', json={'kind': 'server'})
        d = client.get(f'/api/v1/dcim/catalog/{uid}/history').get_json()
        assert len(d['history']) == 2
        assert d['history'][0]['by'] == 'admin'
        assert d['history'][0]['changes']['kind'][1] == 'server'
        assert d['history'][-1]['action'] == 'create'

    def test_la_linea_del_registro_dice_QUE_se_toco(self, client, admin):
        """«Editado» no contesta a nada. Los nombres de los campos y no sus valores: una línea se
        lee de un vistazo entre doscientas, y volcar veinte valores la haría ilegible — los
        valores están en la versión, que es exactamente para eso."""
        _login(client)
        uid = self._modelo(client)
        r = client.put(f'/api/v1/dcim/catalog/{uid}',
                       json={'kind': 'server', 'part_number': 'PN-9'})
        assert sorted(r.get_json()['changed']) == ['kind', 'part_number']

    def test_mirarlo_no_pide_el_permiso_de_importar(self, admin, client):
        """Mirar lo que decía ayer es leer, y quien no puede importar sigue necesitando saber si
        el dato con el que trabaja cambió bajo sus pies."""
        _login(client)
        uid = self._modelo(client)
        c = _as(admin, 'mira-historial', ['dcim_view', 'dcim_catalog_view'])
        assert c.get(f'/api/v1/dcim/catalog/{uid}/history').status_code == 200
        assert c.post(f'/api/v1/dcim/catalog/{uid}/restore',
                      json={'rev': 'x'}).status_code == 403

    def test_volver_a_una_version_escribe_sus_valores(self, client):
        _login(client)
        uid = self._modelo(client)
        primera = client.get(f'/api/v1/dcim/catalog/{uid}/history').get_json()['history'][0]
        client.put(f'/api/v1/dcim/catalog/{uid}', json={'part_number': 'PN-9'})
        r = client.post(f'/api/v1/dcim/catalog/{uid}/restore', json={'rev': primera['uid']})
        assert r.status_code == 200
        d = client.get('/api/v1/dcim/catalog').get_json()
        assert [x for x in d['types'] if x['uid'] == uid][0]['part_number'] == ''

    def test_volver_atras_es_un_cambio_mas_y_no_un_deshacer(self, client):
        """Si borrara lo de en medio, la respuesta a «quién dejó esto así» sería distinta según
        cuándo se preguntara."""
        _login(client)
        uid = self._modelo(client)
        primera = client.get(f'/api/v1/dcim/catalog/{uid}/history').get_json()['history'][0]
        client.put(f'/api/v1/dcim/catalog/{uid}', json={'part_number': 'PN-9'})
        client.post(f'/api/v1/dcim/catalog/{uid}/restore', json={'rev': primera['uid']})
        h = client.get(f'/api/v1/dcim/catalog/{uid}/history').get_json()['history']
        assert len(h) == 3, 'la vuelta atrás también deja constancia'

    def test_una_version_de_otra_ficha_no_vale(self, client):
        _login(client)
        a, b = self._modelo(client), client.post(
            '/api/v1/dcim/catalog',
            json={'manufacturer': 'Cisco', 'model': 'C9300'}).get_json()['uid']
        suya = client.get(f'/api/v1/dcim/catalog/{b}/history').get_json()['history'][0]
        assert client.post(f'/api/v1/dcim/catalog/{a}/restore',
                           json={'rev': suya['uid']}).status_code == 404

    def test_de_una_ficha_que_no_existe_no_hay_historial(self, client):
        _login(client)
        assert client.get('/api/v1/dcim/catalog/no-existe/history').status_code == 404


class TestLosAtributosDeUnComponente:
    """Qué se pregunta de un componente de cada clase, y de dónde sale esa lista.

    Once clases con cuatro atributos escritas en el código son una lista que hay que publicar una
    release para tocar, y quien sabe qué formato tiene la tarjeta nueva casi nunca es quien toca
    el código.
    """

    def test_el_catalogo_dice_que_pedir_de_cada_clase(self, client):
        _login(client)
        d = client.get('/api/v1/dcim/catalog').get_json()
        campos = d['component_fields']
        assert [c['name'] for c in campos['ssd']][:2] == ['form_factor', 'interface']
        # El peso va aparte: lo dicen todas las clases, así que no distingue ninguna y no es un
        # atributo — va con los datos generales, al lado del número de parte.
        assert [c['name'] for c in d['component_common']][:3] == [
            'airflow', 'weight', 'weight_unit']
        # Y las fechas de una vida llegan APARTE de los comunes, porque salen en su propio
        # bloque: mezcladas serían seis casillas de fecha seguidas sin decir de qué van.
        assert [c['name'] for c in d['lifecycle_fields']][0] == 'launched'
        assert [c['name'] for c in d['lifecycle_fields']][-1] == 'eol'
        assert 'weight' not in [c['name'] for c in campos['ssd']]
        # Y el tamaño se llama como toca: de un SSD es su capacidad, de una fuente su potencia.
        assert d['component_size']['ssd']['label'] == 'capacity'
        assert d['component_size']['psu']['label'] == 'power'

    def test_lo_que_se_teclea_se_guarda_y_vuelve(self, client):
        _login(client)
        uid = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'Samsung', 'model': 'MZ-V8P1T0BW',
                                'tree': 'component-types', 'kind': 'ssd', 'size': '1 TB',
                                'extra': {'form_factor': 'M.2 2280', 'interface': 'NVMe'}
                                }).get_json()['uid']
        d = client.get('/api/v1/dcim/catalog?tree=component-types').get_json()
        fila = [x for x in d['types'] if x['uid'] == uid][0]
        assert fila['extra']['interface'] == 'NVMe' and fila['size'] == '1 TB'

    def test_corregir_un_atributo_lo_guarda_de_verdad(self, client):
        """Decía «guardado» y no guardaba: `extra` es JSON y estaba fuera de lo editable, así que
        al volver a abrir la ficha seguía sin poner nada. Un fallo que no da error."""
        _login(client)
        uid = client.post('/api/v1/dcim/catalog',
                          json={'manufacturer': 'Samsung', 'model': 'MZ-V8P1T0BW',
                                'tree': 'component-types', 'kind': 'ssd'}).get_json()['uid']
        assert client.put(f'/api/v1/dcim/catalog/{uid}',
                          json={'extra': {'interface': 'NVMe'}}).status_code == 200
        d = client.get('/api/v1/dcim/catalog?tree=component-types').get_json()
        assert [x for x in d['types'] if x['uid'] == uid][0]['extra'] == {'interface': 'NVMe'}
        h = client.get(f'/api/v1/dcim/catalog/{uid}/history').get_json()['history']
        assert h[0]['changes'] == {'extra.interface': [None, 'NVMe']}

    def test_se_puede_cambiar_sin_publicar_una_version(self, client):
        _login(client)
        base = client.get('/api/v1/dcim/profiles').get_json()['packaged']
        r = client.put('/api/v1/dcim/profiles',
                       json={'version': base + 1,
                             'kinds': {'ssd': [{'name': 'nuevo', 'type': 'text'}]}})
        assert r.status_code == 200 and r.get_json()['version'] == base + 1
        d = client.get('/api/v1/dcim/catalog').get_json()
        assert [c['name'] for c in d['component_fields']['ssd']][0] == 'nuevo'

    def test_lo_que_se_descarta_se_dice(self, client):
        """Un JSON con una clase mal escrita se guardaría igual y dejaría media pantalla sin
        atributos, y quien lo subió no se enteraría hasta que alguien fuera a rellenar una
        ficha."""
        _login(client)
        base = client.get('/api/v1/dcim/profiles').get_json()['packaged']
        r = client.put('/api/v1/dcim/profiles',
                       json={'version': base + 1,
                             'kinds': {'nave': [{'name': 'x', 'type': 'text'}]}})
        assert r.status_code == 200 and r.get_json()['dropped'] == ['kind:nave']

    def test_sin_version_no_entra(self, client):
        """Sería un documento que nunca se usa y que nadie entiende por qué no se usa."""
        _login(client)
        assert client.put('/api/v1/dcim/profiles',
                          json={'kinds': {}}).status_code == 400

    def test_quitarlo_vuelve_al_que_viene_dentro(self, client):
        _login(client)
        base = client.get('/api/v1/dcim/profiles').get_json()['packaged']
        client.put('/api/v1/dcim/profiles',
                   json={'version': base + 1, 'kinds': {'ssd': [{'name': 'x', 'type': 'text'}]}})
        assert client.delete('/api/v1/dcim/profiles').status_code == 200
        d = client.get('/api/v1/dcim/catalog').get_json()
        assert 'form_factor' in [c['name'] for c in d['component_fields']['ssd']]

    def test_el_documento_deja_historial_de_quien_lo_cambio(self, client):
        """De él sale el formulario de todos los componentes: cambiarlo cambia lo que todo el
        mundo puede teclear, y «¿esto quién lo cambió?» es la pregunta del mes siguiente."""
        _login(client)
        base = client.get('/api/v1/dcim/profiles').get_json()['packaged']
        client.put('/api/v1/dcim/profiles',
                   json={'version': base + 1, 'kinds': {'ssd': [{'name': 'x', 'type': 'text'}]}})
        d = client.get('/api/v1/dcim/profiles/history').get_json()
        assert len(d['history']) == 1
        assert d['history'][0]['by'] == 'admin' and d['history'][0]['version'] == base + 1

    def test_y_se_puede_comparar_con_lo_que_hay_ahora(self, client):
        """Por clase y por campo: a dos volcados de JSON uno al lado del otro no se les puede
        preguntar qué se le añadió a los discos."""
        _login(client)
        base = client.get('/api/v1/dcim/profiles').get_json()['packaged']
        client.put('/api/v1/dcim/profiles',
                   json={'version': base + 1, 'kinds': {'ssd': [{'name': 'x', 'type': 'text'}]}})
        vieja = client.get('/api/v1/dcim/profiles/history').get_json()['history'][0]['uid']
        client.put('/api/v1/dcim/profiles',
                   json={'version': base + 2,
                         'kinds': {'ssd': [{'name': 'x', 'type': 'number'}]}})
        d = client.get(f'/api/v1/dcim/profiles/compare?a={vieja}').get_json()
        assert len(d['diff']) == 1
        assert d['diff'][0]['where'] == 'ssd' and d['diff'][0]['after']['type'] == 'number'

    def test_sin_nada_guardado_el_historial_esta_vacio(self, client):
        """El que viene con el panel no tiene historial porque su historial son los commits."""
        _login(client)
        assert client.get('/api/v1/dcim/profiles/history').get_json()['history'] == []

    def test_cambiarlo_pide_el_permiso_de_importar_y_mirarlo_no(self, admin, client):
        c = _as(admin, 'mira-perfiles', ['dcim_view', 'dcim_catalog_view'])
        assert c.get('/api/v1/dcim/profiles').status_code == 200
        assert c.put('/api/v1/dcim/profiles', json={'version': 99}).status_code == 403
        assert c.delete('/api/v1/dcim/profiles').status_code == 403


class TestLosAdjuntosDeUnaFicha:
    """Lo que no es una foto: el manual, la hoja de características, el zip del firmware.

    Hoy eso vive en la carpeta de alguien —o en un correo de hace tres años— y el día que hace
    falta es un martes a las once de la noche con una tarjeta que no arranca.

    **No hay lista blanca de tipos**, y lo que hace que eso sea seguro es cómo salen: siempre
    como descarga, con tipo genérico y sin dejar que el navegador adivine.
    """

    def _modelo(self, client):
        return client.post('/api/v1/dcim/catalog',
                           json={'manufacturer': 'Dell', 'model': 'R740'}).get_json()['uid']

    def _subir(self, client, uid, nombre='manual.pdf', datos=b'%PDF-1.4 hola', clase='manual'):
        return client.post(f'/api/v1/dcim/catalog/{uid}/files',
                           data={'file': (io.BytesIO(datos), nombre), 'kind': clase},
                           content_type='multipart/form-data')

    def test_se_cuelga_un_manual_y_se_lee_la_lista(self, client):
        _login(client)
        uid = self._modelo(client)
        assert self._subir(client, uid).status_code == 200
        d = client.get(f'/api/v1/dcim/catalog/{uid}/files').get_json()
        assert len(d['files']) == 1
        f = d['files'][0]
        assert f['kind'] == 'manual' and f['label'] == 'manual.pdf' and f['size'] > 0

    def test_lo_que_no_es_una_imagen_tambien_entra(self, client):
        """Es el punto entero: aquí va el `.docx` del distribuidor y el zip del firmware."""
        _login(client)
        uid = self._modelo(client)
        assert self._subir(client, uid, 'firmware.zip', b'PK\x03\x04rr',
                           'firmware').status_code == 200

    def test_y_sale_siempre_como_descarga(self, client):
        """Es lo que permite no tener lista blanca: un HTML subido no se ejecuta en este origen
        porque el navegador no llega a renderizarlo."""
        _login(client)
        uid = self._modelo(client)
        self._subir(client, uid, 'trampa.html', b'<script>alert(1)</script>', 'other')
        fuid = client.get(f'/api/v1/dcim/catalog/{uid}/files').get_json()['files'][0]['uid']
        r = client.get(f'/api/v1/dcim/files/{fuid}')
        assert r.status_code == 200
        assert r.headers['Content-Type'].startswith('application/octet-stream')
        assert r.headers['Content-Disposition'].startswith('attachment')
        assert r.headers['X-Content-Type-Options'] == 'nosniff'
        assert r.data == b'<script>alert(1)</script>'

    def test_el_nombre_del_fichero_no_toca_el_disco(self, client, admin):
        """Lo que se guarda lo acuña el panel; lo que llegó es una etiqueta que se enseña."""
        _login(client)
        uid = self._modelo(client)
        from lib.core.dcim import media
        self._subir(client, uid, '../../etc/passwd')
        f = client.get(f'/api/v1/dcim/catalog/{uid}/files').get_json()['files'][0]
        # Lo guardado tiene la forma que acuña el panel —subcarpeta, identificador, `.bin`— y no
        # lleva nada de lo que venía. La subcarpeta dice de dónde salió: `own`, porque lo subió
        # alguien y no una importación, que es lo único que no se puede volver a descargar.
        assert media.is_name(f['stored']) and f['stored'].startswith('own/')
        assert '..' not in f['stored'] and 'passwd' not in f['stored']
        # Y lo que venía se queda como etiqueta, sin la ruta que traía.
        assert '/' not in f['label'] and 'passwd' in f['label']

    def test_ni_la_cabecera_de_la_descarga(self, client):
        """Un nombre con comillas dentro partiría la cabecera en dos."""
        _login(client)
        uid = self._modelo(client)
        self._subir(client, uid, 'ra"ro\nx.pdf')
        fuid = client.get(f'/api/v1/dcim/catalog/{uid}/files').get_json()['files'][0]['uid']
        cabecera = client.get(f'/api/v1/dcim/files/{fuid}').headers['Content-Disposition']
        assert cabecera.count('"') == 2 and '\n' not in cabecera

    def test_quitarlo_borra_el_fichero(self, admin, client):
        _login(client)
        from lib.core.dcim import media
        var = admin._var_dir or ''                             # noqa: SLF001
        uid = self._modelo(client)
        self._subir(client, uid)
        fuid = client.get(f'/api/v1/dcim/catalog/{uid}/files').get_json()['files'][0]['uid']
        assert client.delete(f'/api/v1/dcim/files/{fuid}').status_code == 200
        assert client.get(f'/api/v1/dcim/catalog/{uid}/files').get_json()['files'] == []
        assert media.every(var) == []

    def test_borrar_el_modelo_se_lleva_sus_adjuntos(self, admin, client):
        """Dejarlos sería dejar ficheros en el disco a los que no apunta nadie — el mismo agujero
        que se tapó con las imágenes al reimportar."""
        _login(client)
        from lib.core.dcim import media
        var = admin._var_dir or ''                             # noqa: SLF001
        uid = self._modelo(client)
        self._subir(client, uid)
        assert client.delete(f'/api/v1/dcim/catalog/{uid}').status_code == 200
        assert media.every(var) == []

    def test_una_clase_inventada_es_otro(self, client):
        _login(client)
        uid = self._modelo(client)
        self._subir(client, uid, 'x.pdf', b'x', 'reactor')
        assert client.get(f'/api/v1/dcim/catalog/{uid}/files'
                          ).get_json()['files'][0]['kind'] == 'other'

    def test_un_fichero_vacio_no_es_un_adjunto(self, client):
        _login(client)
        uid = self._modelo(client)
        assert self._subir(client, uid, 'x.pdf', b'').status_code == 400

    def test_leerlos_no_pide_el_permiso_de_importar(self, admin, client):
        """Buscar el manual a las once de la noche no es administrar el catálogo."""
        _login(client)
        uid = self._modelo(client)
        self._subir(client, uid)
        c = _as(admin, 'busca-manual', ['dcim_view', 'dcim_catalog_view'])
        assert c.get(f'/api/v1/dcim/catalog/{uid}/files').status_code == 200
        r = c.post(f'/api/v1/dcim/catalog/{uid}/files', data={},
                   content_type='multipart/form-data')
        assert r.status_code == 403

    def test_clonar_se_lleva_los_adjuntos(self, client):
        """Entraron después de que existiera el clonado y se quedaron fuera: clonar daba una
        ficha sin manual, sin decirlo."""
        _login(client)
        uid = self._modelo(client)
        self._subir(client, uid, 'manual.pdf', b'%PDF-1.4 hola', 'manual')
        copia = client.post('/api/v1/dcim/catalog',
                            json={'from': uid, 'manufacturer': 'Dell',
                                  'model': 'R740 (copia)'}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/catalog/{copia}/files').get_json()
        assert len(d['files']) == 1 and d['files'][0]['label'] == 'manual.pdf'

    def test_y_los_copia_en_vez_de_compartirlos(self, admin, client):
        """Dos fichas apuntando al mismo fichero significa que borrar cualquiera de las dos deja
        a la otra sin manual **sin que nada haya fallado**."""
        _login(client)
        from lib.core.dcim import media
        var = admin._var_dir or ''                             # noqa: SLF001
        uid = self._modelo(client)
        self._subir(client, uid)
        copia = client.post('/api/v1/dcim/catalog',
                            json={'from': uid, 'manufacturer': 'Dell',
                                  'model': 'R740 (copia)'}).get_json()['uid']
        assert len(media.every(var)) == 2, 'un fichero por ficha, no uno compartido'
        # Y borrar el original deja al clon con el suyo.
        client.delete(f'/api/v1/dcim/catalog/{uid}')
        d = client.get(f'/api/v1/dcim/catalog/{copia}/files').get_json()
        assert len(d['files']) == 1
        assert client.get(f'/api/v1/dcim/files/{d["files"][0]["uid"]}').status_code == 200

    def test_de_un_modelo_que_no_existe_no_hay_adjuntos(self, client):
        _login(client)
        assert client.get('/api/v1/dcim/catalog/no-existe/files').status_code == 404

class TestLasPlataformas:
    """Con qué sale un equipo, escrito una vez.

    Una caja de texto por plantilla acaba siendo cuatro formas de escribir «Debian 12», y
    entonces «cuántas máquinas hay que actualizar» no tiene una respuesta. Aquí se da de alta
    una vez y las plantillas apuntan a la fila.
    """

    def test_se_escribe_una_y_sale_en_la_lista(self, client, fleet):
        _login(client)
        r = client.post('/api/v1/dcim/platforms',
                        json={'name': 'Debian', 'version': '12', 'kind': 'os',
                              'extra': {'eol': '2028-06-30'}})
        assert r.status_code == 200
        d = client.get('/api/v1/dcim/platforms').get_json()
        fila = [p for p in d['platforms'] if p['name'] == 'Debian'][0]
        assert fila['version'] == '12' and fila['extra']['eol'] == '2028-06-30'
        # Y las seis fechas llegan con la lista, del mismo documento que las de un modelo.
        assert [c['name'] for c in d['lifecycle']][-1] == 'eol'
        assert 'os' in d['kinds']

    def test_los_basicos_traen_las_que_se_van_a_teclear_igual(self, client, fleet):
        """Un panel recién instalado tiene un armario delante y ninguna plataforma dada de alta,
        y las primeras que alguien escribe son siempre las mismas cinco."""
        from lib.core.dcim import basics
        _login(client)
        r = client.post('/api/v1/dcim/catalog/basics')
        assert r.status_code == 200
        assert r.get_json()['platforms'] == basics.platform_count()
        nombres = [p['name'] for p in
                   client.get('/api/v1/dcim/platforms').get_json()['platforms']]
        # Con su EDICIÓN, que no es un adorno: una `Enterprise LTSC` y una `Pro` no se
        # actualizan igual ni se acaban el mismo día, así que son dos y no una con un matiz.
        assert 'Windows 11 Pro' in nombres and 'Windows 11 Enterprise LTSC' in nombres
        assert 'Windows Server 2022 Datacenter' in nombres
        assert 'Debian 12' in nombres and 'Ubuntu 26.04 LTS' in nombres

    def test_volver_a_traerlos_no_pisa_lo_que_alguien_escribio(self, client, fleet):
        """Los modelos SÍ se reemplazan —son genéricos y vuelven iguales—; una plataforma no: la
        fecha de fin de soporte y las notas de la suya son de esta casa."""
        _login(client)
        client.post('/api/v1/dcim/catalog/basics')
        uid = [p['uid'] for p in client.get('/api/v1/dcim/platforms').get_json()['platforms']
               if p['name'] == 'Debian 12'][0]
        client.put(f'/api/v1/dcim/platforms/{uid}',
                   json={'extra': {'eol': '2028-06-30'},
                         'notes': 'la de los servidores de aquí'})
        client.post('/api/v1/dcim/catalog/basics')
        fila = [p for p in client.get('/api/v1/dcim/platforms').get_json()['platforms']
                if p['uid'] == uid][0]
        assert fila['extra']['eol'] == '2028-06-30'
        assert fila['notes'] == 'la de los servidores de aquí'

    def test_y_la_marca_se_completa_donde_la_hay(self, client, fleet):
        """Quien hace el sistema, que no siempre sale en una factura pero sí agrupa la lista:
        Windows es de Microsoft, RouterOS de MikroTik, DSM de Synology y Debian del proyecto
        Debian. La marca sigue siendo opcional en el modelo — hay firmware que no es de nadie
        con nombre— pero de estos se sabe."""
        _login(client)
        client.post('/api/v1/dcim/catalog/basics')
        por_nombre = {p['name']: p for p in
                      client.get('/api/v1/dcim/platforms').get_json()['platforms']}
        assert por_nombre['Windows 11 Pro']['brand'] == 'Microsoft'
        assert por_nombre['Debian 12']['brand'] == 'Debian'
        assert por_nombre['RouterOS 7']['brand'] == 'MikroTik'

    def test_dos_con_el_mismo_nombre_se_rechaza_con_un_motivo(self, client, fleet):
        _login(client)
        client.post('/api/v1/dcim/platforms', json={'name': 'Debian'})
        r = client.post('/api/v1/dcim/platforms', json={'name': 'debian'})
        assert r.status_code == 400 and r.get_json().get('error')

    def test_la_lista_dice_cuantas_plantillas_la_nombran(self, client, fleet):
        """Es lo que hace que retirarla pueda negarse con un motivo en vez de dejar plantillas
        apuntando a nada."""
        _login(client)
        plat = client.post('/api/v1/dcim/platforms',
                           json={'name': 'RouterOS'}).get_json()['uid']
        client.post('/api/v1/dcim/builds',
                    json={'name': 'Router de sede', 'platform_uid': plat})
        fila = [p for p in client.get('/api/v1/dcim/platforms').get_json()['platforms']
                if p['uid'] == plat][0]
        assert fila['builds'] == 1

    def test_no_se_retira_una_que_alguna_plantilla_nombre(self, client, fleet):
        """Una plantilla que dice «sale con» y no dice con qué es peor que una que no lo dice,
        porque parece que se sabe."""
        _login(client)
        plat = client.post('/api/v1/dcim/platforms',
                           json={'name': 'ESXi'}).get_json()['uid']
        client.post('/api/v1/dcim/builds', json={'name': 'Nodo de virtualización',
                                                 'platform_uid': plat})
        r = client.delete(f'/api/v1/dcim/platforms/{plat}')
        assert r.status_code == 400 and r.get_json().get('builds') == 1
        assert [p for p in client.get('/api/v1/dcim/platforms').get_json()['platforms']
                if p['uid'] == plat], 'se borró de todas formas'

    def test_y_una_que_no_nombra_nadie_si(self, client, fleet):
        _login(client)
        plat = client.post('/api/v1/dcim/platforms',
                           json={'name': 'Windows Server 2022'}).get_json()['uid']
        assert client.delete(f'/api/v1/dcim/platforms/{plat}').status_code == 200
        assert not client.get('/api/v1/dcim/platforms').get_json()['platforms']

    def test_la_familia_viaja_para_poder_leerlas_en_arbol(self, client, fleet):
        """Microsoft → Windows 11 → Pro, Home, Enterprise. Sin ella son veintiséis renglones
        planos, que con cincuenta ya no se leen."""
        _login(client)
        client.post('/api/v1/dcim/platforms',
                    json={'name': 'Windows 11 Pro', 'family': 'Windows 11'})
        fila = client.get('/api/v1/dcim/platforms').get_json()['platforms'][0]
        assert fila['family'] == 'Windows 11'

    def test_una_plataforma_nueva_entra_ENTERA(self, client, fleet):
        """Darla de alta con solo el nombre y completarla después dejaba fuera lo que ya tiene
        valor por defecto —la clase— y por eso Proxmox y ESXi entraban como «sistema operativo».
        Un valor por defecto ES un hueco: es lo que se pone cuando nadie ha dicho nada."""
        _login(client)
        client.post('/api/v1/dcim/catalog/basics')
        por_nombre = {p['name']: p for p in
                      client.get('/api/v1/dcim/platforms').get_json()['platforms']}
        pve = por_nombre['Proxmox VE 9']
        assert pve['kind'] == 'hypervisor' and pve['family'] == 'Proxmox VE'
        assert pve['brand'] == 'Proxmox' and pve['extra']['launched'] == '2025-08-05'
        assert por_nombre['VMware ESXi 8.0']['kind'] == 'hypervisor'
        assert por_nombre['Synology DSM 7.2']['kind'] == 'appliance'
        assert por_nombre['RouterOS 7']['kind'] == 'firmware'

    def test_y_a_una_que_ya_estaba_se_le_corrige_la_clase_por_defecto(self, client, fleet):
        """La que sembró una versión anterior se quedó en `os` sin que nadie lo eligiera. Eso es
        un hueco con otra forma, y dejarla mal para siempre sería peor que rellenarlo."""
        _login(client)
        uid = client.post('/api/v1/dcim/platforms',
                          json={'name': 'Proxmox VE 9'}).get_json()['uid']
        client.post('/api/v1/dcim/catalog/basics')
        fila = [p for p in client.get('/api/v1/dcim/platforms').get_json()['platforms']
                if p['uid'] == uid][0]
        assert fila['kind'] == 'hypervisor'

    def test_pero_una_clase_elegida_a_mano_no_se_toca(self, client, fleet):
        _login(client)
        uid = client.post('/api/v1/dcim/platforms',
                          json={'name': 'Proxmox VE 9',
                                'kind': 'appliance'}).get_json()['uid']
        client.post('/api/v1/dcim/catalog/basics')
        fila = [p for p in client.get('/api/v1/dcim/platforms').get_json()['platforms']
                if p['uid'] == uid][0]
        assert fila['kind'] == 'appliance'

    def test_los_basicos_rellenan_lo_vacio_y_no_pisan_nada(self, client, fleet):
        """Lo que no se puede tocar es un valor que alguien escribió; un hueco no es un valor.
        Escribirlo solo al crear la fila dejaba sin familia a las veintiséis de quien había
        pulsado el botón antes de que esa columna existiera, y el árbol agrupaba cada una
        consigo misma. Y fecha a fecha, no el bloque entero: una corregida a mano no puede
        bloquear las otras cinco para siempre."""
        _login(client)
        client.post('/api/v1/dcim/catalog/basics')
        por_nombre = {p['name']: p for p in
                      client.get('/api/v1/dcim/platforms').get_json()['platforms']}
        w10 = por_nombre['Windows 10 Pro']
        assert w10['extra']['eol'] == '2025-10-14' and w10['family'] == 'Windows 10'
        # Corregida a mano y vaciada la familia: lo primero no se toca, lo segundo se rellena.
        client.put(f'/api/v1/dcim/platforms/{w10["uid"]}',
                   json={'extra': {'eol': '2030-01-01'}, 'family': ''})
        client.post('/api/v1/dcim/catalog/basics')
        de_nuevo = [p for p in client.get('/api/v1/dcim/platforms').get_json()['platforms']
                    if p['uid'] == w10['uid']][0]
        assert de_nuevo['extra']['eol'] == '2030-01-01', 'la importación pisó una corrección'
        assert de_nuevo['family'] == 'Windows 10', 'el hueco se quedó sin rellenar'
        # Y las otras fechas, que la corrección no bloqueó.
        assert de_nuevo['extra']['launched'] == '2015-07-29'

    def test_se_quitan_varias_de_una_vez(self, client, fleet):
        """Traer los básicos da de alta veintiséis, y quien quiere quedarse con cuatro no quiere
        veintidós confirmaciones ni veintidós idas y venidas."""
        _login(client)
        uids = [client.post('/api/v1/dcim/platforms',
                            json={'name': n}).get_json()['uid']
                for n in ('Debian 11', 'Debian 12', 'Ubuntu 24.04 LTS')]
        r = client.post('/api/v1/dcim/platforms/drop', json={'uids': uids})
        assert r.status_code == 200 and r.get_json()['count'] == 3
        assert not client.get('/api/v1/dcim/platforms').get_json()['platforms']

    def test_las_que_alguna_plantilla_nombra_se_quedan_y_se_dice(self, client, fleet):
        """Negar el lote entero por una obligaría a buscar cuál era; borrarla dejaría plantillas
        diciendo «sale con» sin decir con qué, que es peor que no decirlo."""
        _login(client)
        libre = client.post('/api/v1/dcim/platforms',
                            json={'name': 'Debian 11'}).get_json()['uid']
        usada = client.post('/api/v1/dcim/platforms',
                            json={'name': 'Debian 12'}).get_json()['uid']
        client.post('/api/v1/dcim/builds', json={'name': 'Servidor', 'platform_uid': usada})
        d = client.post('/api/v1/dcim/platforms/drop',
                        json={'uids': [libre, usada]}).get_json()
        assert d['count'] == 1 and d['kept'] == 1
        quedan = [p['uid'] for p in
                  client.get('/api/v1/dcim/platforms').get_json()['platforms']]
        assert quedan == [usada]

    def test_quitar_ninguna_se_rechaza_en_vez_de_no_hacer_nada(self, client, fleet):
        _login(client)
        assert client.post('/api/v1/dcim/platforms/drop',
                           json={'uids': []}).status_code == 400

    def test_quitar_varias_pide_el_permiso_de_escribir(self, admin, client, fleet):
        _login(client)
        uid = client.post('/api/v1/dcim/platforms', json={'name': 'X'}).get_json()['uid']
        c = _as(admin, 'monta-racks-2', ['dcim_view', 'dcim_edit'])
        assert c.post('/api/v1/dcim/platforms/drop',
                      json={'uids': [uid]}).status_code == 403

    def test_elegir_una_no_pide_el_permiso_de_escribir_el_catalogo(self, admin, client, fleet):
        """Quien monta un rack tiene que poder ELEGIR con qué sale un equipo, igual que elige un
        modelo de chasis. Escribir la lista es otra cosa."""
        _login(client)
        client.post('/api/v1/dcim/platforms', json={'name': 'Debian'})
        c = _as(admin, 'monta-racks', ['dcim_view', 'dcim_edit'])
        assert c.get('/api/v1/dcim/platforms').status_code == 200
        assert c.post('/api/v1/dcim/platforms', json={'name': 'Otra'}).status_code == 403
class TestDosCosasEnUnMismoU:
    """La rejilla daba por hecho **un elemento por U**, y eso deja fuera media sala: el patch
    panel de 0,5 U, los dos mini PC del kit de 1 U, la bandeja con ocho Raspberry.

    Un solo mecanismo para los tres: un elemento dice en cuántas partes se divide su U y cuál
    toma. Sin enum, porque el número lo decide quien monta y una lista escrita en el código se
    queda corta el primer día.
    """

    def _pon(self, client, fleet, **extra):
        cuerpo = dict({'rack_uid': fleet['rack'], 'u_start': 20, 'u_height': 1,
                       'label': 'algo'}, **extra)
        return client.post('/api/v1/dcim/items', json=cuerpo)

    def test_dos_mitades_caben_en_el_mismo_u(self, client, fleet):
        _login(client)
        assert self._pon(client, fleet, label='Panel A', u_slots=2, u_slot=1,
                         u_split='height').status_code == 200
        assert self._pon(client, fleet, label='Panel B', u_slots=2, u_slot=2,
                         u_split='height').status_code == 200

    def test_pero_dos_veces_la_misma_mitad_no(self, client, fleet):
        """Que es el punto: partir un U no es dejar de comprobar, es comprobar más fino."""
        _login(client)
        self._pon(client, fleet, label='Panel A', u_slots=2, u_slot=1)
        r = self._pon(client, fleet, label='Panel B', u_slots=2, u_slot=1)
        assert r.status_code == 400 and r.get_json()['error']

    def test_ni_una_mitad_debajo_de_algo_que_ocupa_el_u_entero(self, client, fleet):
        _login(client)
        self._pon(client, fleet, label='Servidor')
        assert self._pon(client, fleet, label='Panel', u_slots=2,
                         u_slot=1).status_code == 400

    def test_ocho_raspberry_en_un_u(self, client, fleet):
        """El número lo decide quien monta. Ocho no es un caso raro: es una bandeja."""
        _login(client)
        for n in range(1, 9):
            assert self._pon(client, fleet, label=f'rpi{n}', u_slots=8,
                             u_slot=n).status_code == 200
        assert self._pon(client, fleet, label='una mas', u_slots=8,
                         u_slot=8).status_code == 400

    def test_fracciones_distintas_en_el_mismo_u_se_comparan_bien(self, client, fleet):
        """Un medio y un cuarto no son múltiplos el uno del otro. Con decimales, dos que casi
        encajan pasan; con enteros, no."""
        _login(client)
        self._pon(client, fleet, label='mitad', u_slots=2, u_slot=1)
        # El primer cuarto cae dentro de la primera mitad: no cabe.
        assert self._pon(client, fleet, label='cuarto 1', u_slots=4,
                         u_slot=1).status_code == 400
        # El tercero empieza justo donde acaba la mitad: sí cabe.
        assert self._pon(client, fleet, label='cuarto 3', u_slots=4,
                         u_slot=3).status_code == 200

    def test_un_trozo_que_no_existe_se_rechaza(self, client, fleet):
        _login(client)
        assert self._pon(client, fleet, u_slots=2, u_slot=3).status_code == 400
        assert self._pon(client, fleet, u_slots=4, u_slot=3,
                         u_slot_span=3).status_code == 400
        assert self._pon(client, fleet, u_slots=2, u_slot=1,
                         u_split='diagonal').status_code == 400

    def test_lo_montado_encima_no_ocupa_u(self, client, fleet):
        """El U lo paga la bandeja. Si el montado ocupara también, una bandeja con tres máquinas
        diría que el armario está lleno cuando lo que hay es un U con tres cosas dentro."""
        _login(client)
        bandeja = self._pon(client, fleet, label='Bandeja',
                            role='shelf').get_json()['uid']
        for n in range(3):
            r = client.post('/api/v1/dcim/items',
                            json={'parent_uid': bandeja, 'label': f'mini {n}'})
            assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()
        montados = [i for i in d['items'] if i.get('parent_uid') == bandeja]
        assert len(montados) == 3
        # Y heredan dónde está la bandeja, para que todo lo que ya lee U siga leyendo.
        assert {i['u_start'] for i in montados} == {20}

    def test_no_se_monta_sobre_algo_que_ya_va_montado(self, client, fleet):
        """Una bandeja sobre una bandeja no es una sala: es un árbol que nadie puede dibujar."""
        _login(client)
        bandeja = self._pon(client, fleet, label='Bandeja').get_json()['uid']
        mini = client.post('/api/v1/dcim/items',
                           json={'parent_uid': bandeja, 'label': 'mini'}).get_json()['uid']
        r = client.post('/api/v1/dcim/items',
                        json={'parent_uid': mini, 'label': 'imposible'})
        assert r.status_code == 400

    def test_no_se_retira_lo_que_lleva_algo_encima(self, client, fleet):
        """Quitar la bandeja dejaría tres máquinas colgando de un sitio que ya no está, y
        ninguna ocupa U propio para volver a colocarse sola."""
        _login(client)
        bandeja = self._pon(client, fleet, label='Bandeja').get_json()['uid']
        client.post('/api/v1/dcim/items', json={'parent_uid': bandeja, 'label': 'mini'})
        r = client.delete(f'/api/v1/dcim/items/{bandeja}')
        assert r.status_code == 400 and r.get_json()['mounted'] == 1

    def test_lo_de_siempre_sigue_ocupando_el_u_entero(self, client, fleet):
        """Ninguna fila escrita antes de esto dice nada de trozos, y todas ocupaban su U
        entero: leerlas como «un trozo de uno» tiene que dar exactamente eso."""
        _login(client)
        self._pon(client, fleet, label='Servidor')
        assert self._pon(client, fleet, label='Otro').status_code == 400

class TestLlevarseModelosYPlantillas:
    """El sobre por HTTP: quién puede sacarlo, quién puede meterlo y qué pasa con la mitad que
    no se puede."""

    def _plantilla(self, client, nombre='Servidor web'):
        return client.post('/api/v1/dcim/builds',
                           json={'name': nombre, 'manufacturer': 'HP',
                                 'model': 'Mini'}).get_json()['uid']

    def test_exportar_devuelve_un_fichero_y_no_una_pantalla(self, client):
        _login(client)
        uid = self._plantilla(client)
        r = client.get(f'/api/v1/dcim/export?builds={uid}')
        assert r.status_code == 200
        assert 'attachment' in r.headers.get('Content-Disposition', '')
        doc = r.get_json()
        assert doc['kind'] == 'servicesentry.dcim'
        assert [b['name'] for b in doc['builds']] == ['Servidor web']

    def test_lo_exportado_se_vuelve_a_importar_sin_duplicar(self, client):
        _login(client)
        uid = self._plantilla(client)
        doc = client.get(f'/api/v1/dcim/export?builds={uid}').get_json()
        n = client.post('/api/v1/dcim/import', json=doc).get_json()
        assert n['builds_new'] == 0 and n['builds_skipped'] == 1
        # Y con otro nombre entra, con sus piezas: es el caso de traérsela de otra instalación.
        doc['builds'][0]['name'] = 'Servidor web 2'
        doc['builds'][0]['parts'] = [{'kind': 'memory', 'brand': 'Crucial', 'qty': 2}]
        n = client.post('/api/v1/dcim/import', json=doc).get_json()
        assert n['builds_new'] == 1 and n['parts'] == 1
        filas = client.get('/api/v1/dcim/builds').get_json()['builds']
        assert 'Servidor web 2' in [b['name'] for b in filas]

    def test_un_fichero_de_otra_cosa_se_rechaza_diciendo_por_que(self, client):
        """Tragárselo es escribir filas a partir de lo que alguien tenía en el portapapeles."""
        _login(client)
        r = client.post('/api/v1/dcim/import', json={'builds': [{'name': 'X'}]})
        assert r.status_code == 400
        assert r.get_json()['problems']
        assert 'X' not in [b['name'] for b in
                           client.get('/api/v1/dcim/builds').get_json()['builds']]


class TestLaFotoDeUnConector:
    """Los conectores no son filas: son un DOCUMENTO, y la foto de uno se guarda escribiendo el
    documento entero con una versión más alta. Por eso la sube el servidor en un solo paso.

    En dos —subir el fichero y luego guardar el documento— hay un hueco: quien cierre el cuadro
    después del primero deja un fichero en la carpeta al que no apunta nadie, y nada vuelve a
    mirarlo nunca.
    """

    def _png(self):
        return b'\x89PNG\r\n\x1a\n' + b'0' * 32

    def _un_conector(self, client, cid='regleta'):
        """Uno propio, guardado: la ruta escribe DENTRO del documento en vigor."""
        from lib.core.dcim import connectors as conns
        doc = {'version': conns.next_version(),
               'connectors': [{'id': cid, 'name': 'Regleta del taller',
                               'families': ['power-outlets'], 'group': 'power-out'}]}
        assert client.put('/api/v1/dcim/connectors', json=doc).status_code == 200
        return cid

    def test_subirla_la_guarda_dentro_del_documento(self, admin, client):
        _login(client)
        cid = self._un_conector(client)
        r = client.post(f'/api/v1/dcim/connectors/{cid}/image',
                        data={'file': (io.BytesIO(self._png()), 'foto.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 200, r.get_json()
        nombre = r.get_json()['image']
        d = client.get('/api/v1/dcim/connectors').get_json()
        fila = next(c for c in d['doc']['connectors'] if c['id'] == cid)
        assert fila['image'] == nombre
        # Y llega a la pantalla, que es lo único que hace que se vea.
        pintado = next(c for c in d['connectors']['power-outlets'] if c['id'] == cid)
        assert pintado['image'] == nombre

    def test_la_version_sube_por_encima_de_la_del_panel(self, admin, client):
        """Guardar con una que no gana es guardar algo que no se aplica, y decir que sí."""
        _login(client)
        cid = self._un_conector(client)
        antes = client.get('/api/v1/dcim/connectors').get_json()
        client.post(f'/api/v1/dcim/connectors/{cid}/image',
                    data={'file': (io.BytesIO(self._png()), 'f.png')},
                    content_type='multipart/form-data')
        d = client.get('/api/v1/dcim/connectors').get_json()
        assert d['doc']['version'] > antes['doc']['version']
        assert d['doc']['version'] > d['packaged']

    def test_la_que_sustituye_se_borra_del_disco(self, admin, client):
        """Sin eso, cada cambio deja un fichero al que no apunta nadie y la carpeta crece durante
        toda la vida de la instalación."""
        _login(client)
        from lib.core.dcim import media
        var = admin._var_dir or ''                             # noqa: SLF001
        cid = self._un_conector(client)
        for _ in range(2):
            client.post(f'/api/v1/dcim/connectors/{cid}/image',
                        data={'file': (io.BytesIO(self._png()), 'f.png')},
                        content_type='multipart/form-data')
        d = client.get('/api/v1/dcim/connectors').get_json()
        fila = next(c for c in d['doc']['connectors'] if c['id'] == cid)
        assert media.every(var) == [fila['image']]

    def test_quitarla_la_borra_y_devuelve_el_dibujo(self, admin, client):
        _login(client)
        from lib.core.dcim import media
        var = admin._var_dir or ''                             # noqa: SLF001
        cid = self._un_conector(client)
        client.post(f'/api/v1/dcim/connectors/{cid}/image',
                    data={'file': (io.BytesIO(self._png()), 'f.png')},
                    content_type='multipart/form-data')
        assert client.delete(f'/api/v1/dcim/connectors/{cid}/image').status_code == 200
        d = client.get('/api/v1/dcim/connectors').get_json()
        fila = next(c for c in d['doc']['connectors'] if c['id'] == cid)
        assert 'image' not in fila and media.every(var) == []

    def test_uno_que_no_esta_no_deja_el_fichero_puesto(self, admin, client):
        """Responder 404 y quedarse la foto es la peor mitad de las dos: nada apunta a ella y
        nadie la va a encontrar para borrarla."""
        _login(client)
        from lib.core.dcim import media
        var = admin._var_dir or ''                             # noqa: SLF001
        self._un_conector(client)
        r = client.post('/api/v1/dcim/connectors/no-existe/image',
                        data={'file': (io.BytesIO(self._png()), 'f.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 404
        assert media.every(var) == []

    def test_lo_que_no_es_una_imagen_no_entra(self, admin, client):
        """El tipo lo decide lo que hay DENTRO: una extensión es una afirmación de quien sube."""
        _login(client)
        cid = self._un_conector(client)
        r = client.post(f'/api/v1/dcim/connectors/{cid}/image',
                        data={'file': (io.BytesIO(b'no soy una imagen'), 'foto.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 400


class TestLoQueVaSobreUnaBandeja:
    """Dos mini PC sobre una bandeja se reparten su hueco con **los mismos cuatro campos** que
    dividen un U — `u_slots`, `u_slot`, `u_slot_span`, `u_split`— aplicados al hueco del padre.
    Ya estaban en la ficha y ya se guardaban; lo que no había era quien los mirase.

    Mientras no se dibujaban daba igual que dos dijeran lo mismo. Desde que se dibujan, eso son
    dos cajas superpuestas — y un alzado que miente es peor que uno que no dice nada.
    """

    def _bandeja(self, client, rack):
        return client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': 4, 'label': 'Bandeja',
                                 'role': 'shelf'}).get_json()['uid']

    def _rack(self, client):
        sede = client.post('/api/v1/dcim/sites', json={'name': 'Sede bandeja'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'Sala'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'RK', 'u_height': 10}).get_json()['uid']

    def test_dos_mitades_caben(self, admin, client):
        _login(client)
        rack = self._rack(client)
        padre = self._bandeja(client, rack)
        for cual in (1, 2):
            r = client.post('/api/v1/dcim/items',
                            json={'parent_uid': padre, 'label': f'PC{cual}',
                                  'u_slots': 2, 'u_slot': cual})
            assert r.status_code == 200, (cual, r.get_json())

    def test_dos_veces_la_misma_mitad_no(self, admin, client):
        """Se guardaban las dos sin mirar. Ahora son dos cajas en el mismo sitio del dibujo, y
        eso hay que decirlo cuando se pide, no dejarlo pintado."""
        _login(client)
        rack = self._rack(client)
        padre = self._bandeja(client, rack)
        client.post('/api/v1/dcim/items',
                    json={'parent_uid': padre, 'label': 'PC1', 'u_slots': 2, 'u_slot': 1})
        r = client.post('/api/v1/dcim/items',
                        json={'parent_uid': padre, 'label': 'PC2', 'u_slots': 2, 'u_slot': 1})
        assert r.status_code == 400

    def test_medios_distintos_tambien_se_pisan(self, admin, client):
        """`1 de 2` y `2 de 3` no comparten ningún número y ocupan el mismo trozo de bandeja: en
        fracciones se ve, y contando «cuál de cuántas» no."""
        _login(client)
        rack = self._rack(client)
        padre = self._bandeja(client, rack)
        client.post('/api/v1/dcim/items',
                    json={'parent_uid': padre, 'label': 'PC1', 'u_slots': 2, 'u_slot': 1})
        r = client.post('/api/v1/dcim/items',
                        json={'parent_uid': padre, 'label': 'PC2', 'u_slots': 3, 'u_slot': 1})
        assert r.status_code == 400

    def test_quien_no_dice_nada_no_choca_con_nadie(self, admin, client):
        """No está reclamando media bandeja: está dejando que se reparta."""
        _login(client)
        rack = self._rack(client)
        padre = self._bandeja(client, rack)
        client.post('/api/v1/dcim/items',
                    json={'parent_uid': padre, 'label': 'PC1', 'u_slots': 2, 'u_slot': 1})
        for n in (2, 3):
            r = client.post('/api/v1/dcim/items',
                            json={'parent_uid': padre, 'label': f'PC{n}'})
            assert r.status_code == 200, r.get_json()

    def test_un_trozo_que_no_existe_se_rechaza(self, admin, client):
        _login(client)
        rack = self._rack(client)
        padre = self._bandeja(client, rack)
        r = client.post('/api/v1/dcim/items',
                        json={'parent_uid': padre, 'label': 'PC', 'u_slots': 2, 'u_slot': 3})
        assert r.status_code == 400

    def test_moverlo_no_choca_consigo_mismo(self, admin, client):
        """Editar el que ya está sin cambiarle el hueco es lo más normal del mundo, y contra su
        propia fila daría «ocupado»."""
        _login(client)
        rack = self._rack(client)
        padre = self._bandeja(client, rack)
        uid = client.post('/api/v1/dcim/items',
                          json={'parent_uid': padre, 'label': 'PC1',
                                'u_slots': 2, 'u_slot': 1}).get_json()['uid']
        r = client.put(f'/api/v1/dcim/items/{uid}', json={'label': 'PC1 bis'})
        assert r.status_code == 200, r.get_json()

    def test_y_el_hijo_llega_con_su_foto_al_dibujo(self, admin, client):
        """El alzado lo pinta dentro de la bandeja, y para eso necesita lo mismo que cualquier
        otro equipo: su modelo del catálogo y, con él, su imagen."""
        _login(client)
        rack = self._rack(client)
        padre = self._bandeja(client, rack)
        client.post('/api/v1/dcim/items', json={'parent_uid': padre, 'label': 'PC1'})
        d = client.get(f'/api/v1/dcim/racks/{rack}').get_json()
        hijo = next(i for i in d['items'] if i.get('parent_uid') == padre)
        assert 'images' in hijo, 'un montado llega sin su foto y sale sin dibujo'


class TestElHistorialDeUnArmario:
    """Una foto por cambio contesta las dos preguntas que se le hacen a un armario con un año de
    vida: cómo estaba en marzo, y qué le pasó. De una lista de acontecimientos no se reconstruye
    un estado sin reproducirlos todos, y basta que falte uno para que mienta sin decirlo.

    Por eso lo que se comprueba aquí no es que la ruta conteste: es que **ninguna escritura se
    olvide de dejar su foto**.
    """

    def _rack(self, client, nombre='RK-hist'):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']

    def _hist(self, client, rack):
        return client.get(f'/api/v1/dcim/racks/{rack}/history').get_json()['history']

    def test_colocar_mover_y_retirar_dejan_su_foto(self, admin, client):
        _login(client)
        rack = self._rack(client)
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 3,
                                'label': 'SW01'}).get_json()['uid']
        client.put(f'/api/v1/dcim/items/{uid}', json={'u_start': 2})
        client.delete(f'/api/v1/dcim/items/{uid}')
        acciones = [f['action'] for f in self._hist(client, rack)]
        assert acciones == ['remove', 'move', 'place'], acciones

    def test_y_dice_QUE_paso_en_cada_una(self, admin, client):
        _login(client)
        rack = self._rack(client, 'RK-que')
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 3,
                                'label': 'SW01'}).get_json()['uid']
        client.put(f'/api/v1/dcim/items/{uid}', json={'u_start': 2})
        hist = self._hist(client, rack)
        movido = hist[0]['changed']
        assert len(movido) == 1, movido
        assert movido[0]['field'] == 'u_start' and movido[0]['to'] == 2

    def test_editar_el_armario_tambien(self, admin, client):
        """Renombrarlo mueve de sitio a todo lo que hay dentro: es parte de su historia."""
        _login(client)
        rack = self._rack(client, 'RK-nombre')
        client.post('/api/v1/dcim/items', json={'rack_uid': rack, 'u_start': 1, 'label': 'X'})
        client.put(f'/api/v1/dcim/racks/{rack}', json={'name': 'RK-nuevo'})
        hist = self._hist(client, rack)
        assert hist[0]['action'] == 'rack_edit'
        assert any(c['kind'] == 'rack' and c['field'] == 'name' for c in hist[0]['changed'])

    def test_guardar_sin_cambiar_nada_no_es_una_version(self, admin, client):
        """Un formulario manda la ficha entera cada vez que se pulsa guardar, y doce renglones
        idénticos no dicen qué pasó: dicen que alguien pulsó un botón."""
        _login(client)
        rack = self._rack(client, 'RK-igual')
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 1,
                                'label': 'X'}).get_json()['uid']
        antes = len(self._hist(client, rack))
        for _ in range(3):
            client.put(f'/api/v1/dcim/items/{uid}', json={'label': 'X'})
        assert len(self._hist(client, rack)) == antes

    def test_mudarse_de_armario_deja_foto_en_LOS_DOS(self, admin, client):
        """Para el de origen ese equipo se fue; para el de destino, llegó. Guardar sólo el de
        destino deja al primero enseñando una máquina que ya no está."""
        _login(client)
        a = self._rack(client, 'RK-a')
        b = self._rack(client, 'RK-b')
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': a, 'u_start': 1,
                                'label': 'X'}).get_json()['uid']
        n_a = len(self._hist(client, a))
        client.put(f'/api/v1/dcim/items/{uid}', json={'rack_uid': b, 'u_start': 1})
        assert len(self._hist(client, a)) == n_a + 1, 'el de origen no se enteró'
        assert self._hist(client, b), 'el de destino tampoco'

    def test_la_primera_version_no_inventa_seis_llegadas(self, admin, client):
        """No tiene anterior contra la que compararse. Decir «llegaron seis equipos» sería
        cierto y no sería lo que pasó: lo que pasó es que el armario empezó a guardarse."""
        _login(client)
        rack = self._rack(client, 'RK-primera')
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 1, 'label': 'X'})
        assert self._hist(client, rack)[-1]['changed'] == []

    def test_un_armario_que_no_existe_no_tiene_historial(self, admin, client):
        _login(client)
        assert client.get('/api/v1/dcim/racks/no-existe/history').status_code == 404


class TestColocarAlgoDelCatalogoSinPlantilla:
    """La mitad de lo que se pone en un armario no tiene estándar de compra: una tapa ciega, una
    regleta, una bandeja, un panel de parcheo. Obligar a declarar una plantilla para poder
    colocar una tapa es pedir el estándar de una tapa.

    Con el modelo basta, y de él sale lo único que la biblioteca sabe de verdad: **cuánto mide**
    — el dato del que depende que quepa.
    """

    def _rack(self, client, nombre='RK-cat'):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 20}).get_json()['uid']

    def test_la_altura_sale_del_modelo(self, admin, client):
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        tipo = cat.create({'manufacturer': 'Generico', 'model': 'Bandeja 2U',
                           'u_tenths': 20})
        rack = self._rack(client)
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 1, 'label': 'Bandeja',
                                'type_uid': tipo}).get_json()['uid']
        fila = admin._dcim_store.items.get(uid)                # noqa: SLF001
        assert fila['u_height'] == 2, fila

    def test_media_U_ocupa_UNA(self, admin, client):
        """Un panel de 0,5 U ocupa un U y comparte sus dos mitades. Hacia abajo daría cero, y
        una caja que ocupa cero U es una que el dibujo no pinta."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        tipo = cat.create({'manufacturer': 'Generico', 'model': 'Panel medio',
                           'u_tenths': 5})
        rack = self._rack(client, 'RK-medio')
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 1, 'type_uid': tipo}
                          ).get_json()['uid']
        assert admin._dcim_store.items.get(uid)['u_height'] == 1   # noqa: SLF001

    def test_lo_tecleado_manda_sobre_el_catalogo(self, admin, client):
        """Quien acaba de medir la caja con un metro sabe más que la biblioteca."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        tipo = cat.create({'manufacturer': 'Generico', 'model': 'X', 'u_tenths': 20})
        rack = self._rack(client, 'RK-manda')
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 1, 'u_height': 3,
                                'type_uid': tipo}).get_json()['uid']
        assert admin._dcim_store.items.get(uid)['u_height'] == 3   # noqa: SLF001

    def test_un_modelo_que_no_existe_no_se_guarda(self, admin, client):
        """Guardar el identificador dejaría un equipo afirmando ser algo que no está, y eso no
        da ningún error al escribirlo."""
        _login(client)
        rack = self._rack(client, 'RK-fantasma')
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 1,
                                'type_uid': 'no-existe'}).get_json()['uid']
        assert admin._dcim_store.items.get(uid)['type_uid'] == ''  # noqa: SLF001

    def test_y_el_armario_dice_como_se_llama_ese_modelo(self, admin, client):
        """Sin el nombre, la ficha sólo puede enseñar el identificador — treinta y seis
        caracteres que no dicen nada."""
        _login(client)
        cat = admin._dcim_catalog                              # noqa: SLF001
        tipo = cat.create({'manufacturer': 'Generico', 'model': 'Regleta 8'})
        rack = self._rack(client, 'RK-nombre-tipo')
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 1, 'type_uid': tipo})
        d = client.get(f'/api/v1/dcim/racks/{rack}').get_json()
        assert d['items'][0]['type_name'] == 'Generico Regleta 8'


class TestEnQueTomaEstaEnchufado:
    """La columna `outlet` existía desde el primer commit, la API la aceptaba, la respuesta la
    devolvía y la tabla la pintaba — y ningún camino la escribía nunca. Quinta vez que sale esta
    forma en esta sección: una columna que nadie puede escribir vale siempre su valor por
    defecto, y el código que la respeta parece que funciona.
    """

    def _armario(self, client, nombre):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']
        pdu = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': rack, 'name': 'PDU-A', 'feed': 'a',
                                'outlets': 4}).get_json()['uid']
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': 1,
                                 'label': 'SRV'}).get_json()['uid']
        return rack, pdu, item

    def test_la_toma_se_guarda_y_vuelve(self, admin, client):
        _login(client)
        rack, pdu, item = self._armario(client, 'RK-toma')
        r = client.post('/api/v1/dcim/feeds',
                        json={'item_uid': item, 'pdu_uid': pdu, 'outlet': 3})
        assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert d['items'][0]['feeds'][0]['outlet'] == 3
        assert d['pdus'][0]['outlets_used'] == [3]

    def test_dos_cables_en_la_misma_toma_no(self, admin, client):
        """Es físicamente imposible, y un inventario que lo dice se descubre desenchufando."""
        _login(client)
        rack, pdu, item = self._armario(client, 'RK-toma2')
        otro = client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': 2,
                                 'label': 'SRV2'}).get_json()['uid']
        client.post('/api/v1/dcim/feeds', json={'item_uid': item, 'pdu_uid': pdu, 'outlet': 2})
        r = client.post('/api/v1/dcim/feeds', json={'item_uid': otro, 'pdu_uid': pdu,
                                                    'outlet': 2})
        assert r.status_code == 400, r.get_json()

    def test_una_toma_que_la_regleta_no_tiene_tampoco(self, admin, client):
        _login(client)
        rack, pdu, item = self._armario(client, 'RK-toma3')
        r = client.post('/api/v1/dcim/feeds',
                        json={'item_uid': item, 'pdu_uid': pdu, 'outlet': 9})
        assert r.status_code == 400, r.get_json()

    def test_no_saber_en_cual_sigue_siendo_una_respuesta(self, admin, client):
        """Es lo que alguien sabe mirando la foto de un armario, y obligarle a inventarse un
        número sería peor dato que ninguno."""
        _login(client)
        rack, pdu, item = self._armario(client, 'RK-toma4')
        r = client.post('/api/v1/dcim/feeds', json={'item_uid': item, 'pdu_uid': pdu})
        assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert d['pdus'][0]['outlets_used'] == []
        # Pero la toma sigue ocupada: hay un cable dentro aunque nadie sepa en cuál.
        assert d['pdus'][0]['free'] == 3

    def test_un_cable_se_cambia_de_toma_sin_perder_lo_declarado(self, admin, client):
        """Quitarlo y volverlo a poner se lleva por delante lo que alguien declaró que
        consume."""
        _login(client)
        rack, pdu, item = self._armario(client, 'RK-toma5')
        cable = client.post('/api/v1/dcim/feeds',
                            json={'item_uid': item, 'pdu_uid': pdu, 'outlet': 1,
                                  'watts_said': 250}).get_json()['uid']
        r = client.put(f'/api/v1/dcim/feeds/{cable}', json={'outlet': 4})
        assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert d['items'][0]['feeds'][0]['outlet'] == 4
        assert d['items'][0]['feeds'][0]['watts_said'] == 250

    def test_y_no_se_le_puede_mover_encima_de_otro(self, admin, client):
        _login(client)
        rack, pdu, item = self._armario(client, 'RK-toma6')
        otro = client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': 2,
                                 'label': 'SRV2'}).get_json()['uid']
        cable = client.post('/api/v1/dcim/feeds',
                            json={'item_uid': item, 'pdu_uid': pdu,
                                  'outlet': 1}).get_json()['uid']
        client.post('/api/v1/dcim/feeds', json={'item_uid': otro, 'pdu_uid': pdu, 'outlet': 2})
        r = client.put(f'/api/v1/dcim/feeds/{cable}', json={'outlet': 2})
        assert r.status_code == 400, r.get_json()
        # Y dejarlo donde está no es un choque consigo mismo.
        assert client.put(f'/api/v1/dcim/feeds/{cable}', json={'outlet': 1}).status_code == 200


class TestUnaRegletaColocadaSePuedeDeclarar:
    """Una regleta que ocupa un U es un equipo del armario; una regleta donde se enchufa es una
    fila con ramas y tomas. Son la misma cosa vista desde dos sitios, y hasta que alguien las une
    el panel no ofrece como enchufe la que se acaba de colocar — que es lo que espera quien acaba
    de colocarla.
    """

    def _rack(self, client, nombre='RK-pdu'):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 20}).get_json()['uid']

    def _regleta(self, client, rack, u=5):
        return client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': u, 'label': 'Regleta',
                                 'role': 'pdu'}).get_json()['uid']

    def test_el_armario_dice_que_esta_sin_declarar(self, admin, client):
        _login(client)
        rack = self._rack(client)
        uid = self._regleta(client, rack)
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert [x['uid'] for x in d['undeclared_pdus']] == [uid], d['undeclared_pdus']

    def test_y_deja_de_decirlo_al_declararla(self, admin, client):
        _login(client)
        rack = self._rack(client, 'RK-pdu2')
        uid = self._regleta(client, rack)
        r = client.post('/api/v1/dcim/pdus',
                        json={'rack_uid': rack, 'item_uid': uid, 'name': 'Regleta',
                              'feed': 'a', 'outlets': 8})
        assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert d['undeclared_pdus'] == []
        assert [p['name'] for p in d['pdus']] == ['Regleta']

    def test_el_enlace_vuelve_en_la_respuesta(self, admin, client):
        """Guardado y **devuelto**. La pantalla que ofrece «cuál es la regleta» descarta las que
        ya lo están mirando este campo: sin él ofrece la misma otra vez, y la segunda crea una
        regleta duplicada del mismo cacharro con sus tomas contadas dos veces.

        Un campo que se escribe y no vuelve es la forma de fallo que lleva toda esta sección
        repitiéndose: nada da error, y el que lo lee ve siempre el valor por defecto.
        """
        _login(client)
        rack = self._rack(client, 'RK-pdu-link')
        uid = self._regleta(client, rack)
        client.post('/api/v1/dcim/pdus',
                    json={'rack_uid': rack, 'item_uid': uid, 'name': 'R', 'feed': 'a',
                          'outlets': 8})
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert [p['item_uid'] for p in d['pdus']] == [uid], d['pdus']

    def test_una_regleta_sin_rol_tambien_se_puede_declarar(self, admin, client):
        """Lo que se coloca desde el catálogo nace SIN rol —nadie ha dicho todavía qué es— y por
        eso el aviso de arriba no lo ve. La lista de la que se elige no puede depender de que
        alguien haya contestado antes la pregunta que se está haciendo ahora."""
        _login(client)
        rack = self._rack(client, 'RK-pdu-sinrol')
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 3,
                                'label': 'Regleta'}).get_json()['uid']
        r = client.post('/api/v1/dcim/pdus',
                        json={'rack_uid': rack, 'item_uid': uid, 'name': 'Regleta',
                              'feed': 'a', 'outlets': 8})
        assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert [p['item_uid'] for p in d['pdus']] == [uid]
        # Y deja de contarse entre lo que come, que es lo que hacía por el simple hecho de no
        # tener rol: una regleta pidiéndose un enchufe a sí misma.
        assert uid not in [x['uid'] for x in d['items']]

    def test_una_regleta_declarada_no_es_un_consumidor(self, admin, client):
        """No se enchufa a sí misma, y listarla entre lo que come es pedirle un enchufe a lo que
        da los enchufes."""
        _login(client)
        rack = self._rack(client, 'RK-pdu3')
        uid = self._regleta(client, rack)
        client.post('/api/v1/dcim/pdus',
                    json={'rack_uid': rack, 'item_uid': uid, 'name': 'R', 'feed': 'a',
                          'outlets': 8})
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert uid not in [x['uid'] for x in d['items']]

    def test_una_regleta_que_no_ocupa_U_sigue_pudiendo_existir(self, admin, client):
        """La mayoría van atornilladas al lateral. Por eso `item_uid` puede ir vacío y por eso
        no son la misma tabla."""
        _login(client)
        rack = self._rack(client, 'RK-pdu4')
        r = client.post('/api/v1/dcim/pdus',
                        json={'rack_uid': rack, 'name': 'Vertical', 'feed': 'b', 'outlets': 24})
        assert r.status_code == 200
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert [p['name'] for p in d['pdus']] == ['Vertical']

    def test_y_los_equipos_dicen_de_que_clase_son(self, admin, client):
        """De ahí sale que a una bandeja no se le pida un enchufe."""
        _login(client)
        rack = self._rack(client, 'RK-clase')
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 1, 'label': 'Bandeja',
                          'role': 'shelf'})
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert d['items'][0]['role'] == 'shelf'
        assert 'shelf' in d['quiet_roles']


class TestLosHuecosDeUnPanelSalenDeSuModelo:
    """La pantalla solo sabía mirar la plantilla, y un panel de parcheo no nace de ninguna: no
    tiene estándar de compra ni componentes que estampar, se coloca directamente desde el
    catálogo. Así que en su ficha nunca había lista de huecos y siempre había que teclear el
    nombre — y de ahí salen `hueco 7`, `Hueco-7` y `7` para el mismo sitio.
    """

    def _panel(self, client, nombre='RK-keystone'):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']
        tipo = client.post('/api/v1/dcim/catalog', json={
            'tree': 'device-types', 'manufacturer': 'Generico', 'model': 'KS-24',
            'u': 1, 'ports': {'front-ports': {'8p8c': 24}}}).get_json().get('uid')
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': 1, 'label': 'Panel',
                                 'role': 'patch_panel',
                                 'type_uid': tipo or ''}).get_json()['uid']
        return item, tipo

    def test_el_modelo_viaja_con_las_piezas(self, admin, client):
        _login(client)
        item, tipo = self._panel(client)
        if not tipo:
            pytest.skip('esta instalación no deja escribir en el catálogo')
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        assert (d.get('model') or {}).get('uid') == tipo, d.get('model')
        assert (d['model']['ports'] or {}).get('front-ports'),             'el modelo llega sin sus huecos, así que no hay de dónde elegir'

    def test_y_sin_modelo_no_se_inventa_uno(self, admin, client):
        """Un equipo sin modelo casado no tiene huecos declarados, y decir que tiene cero sería
        distinto de no saberlo."""
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': 'RK-ks2'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'RK-ks2',
                                 'u_height': 10}).get_json()['uid']
        item = client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': 1,
                                 'label': 'X'}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        assert 'model' not in d or d['model'] is None

    def test_un_conector_se_guarda_en_su_hueco(self, admin, client):
        _login(client)
        item, _tipo = self._panel(client, 'RK-ks3')
        r = client.post('/api/v1/dcim/parts',
                        json={'item_uid': item, 'kind': 'jack', 'slot': 'RJ45 7',
                              'brand': 'Digitus', 'model': 'Keystone cat6'})
        assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/items/{item}/parts').get_json()
        puesto = [p for p in d['parts'] if p['kind'] == 'jack']
        assert len(puesto) == 1 and puesto[0]['slot'] == 'RJ45 7'


class TestLasPestanasDicenLoQueTienenSinAbrirlas:
    """Un número que sólo aparece después de entrar no contesta la pregunta para la que está
    —¿hay algo ahí?— y la contesta al revés: una pestaña sin número parece una vacía.
    """

    def test_el_armario_trae_los_recuentos(self, admin, client):
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': 'RK-cnt'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'RK-cnt',
                                 'u_height': 10}).get_json()['uid']
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1, 'label': 'A'}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2, 'label': 'B'}).get_json()['uid']
        pdu = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': rack, 'name': 'P', 'feed': 'a',
                                'outlets': 8}).get_json()['uid']
        client.post('/api/v1/dcim/cables', json={'a_item': a, 'b_item': b})
        client.post('/api/v1/dcim/feeds', json={'item_uid': a, 'pdu_uid': pdu, 'outlet': 1})
        d = client.get(f'/api/v1/dcim/racks/{rack}').get_json()
        c = d.get('counts') or {}
        assert c.get('cables') == 1, c
        assert c.get('power') == 1, c
        # El historial se escribe solo al colocar cosas, así que aquí ya hay varias fotos.
        assert c.get('hist', 0) >= 1, c

    def test_y_la_alimentacion_ya_no_cuenta_las_ramas(self, admin, client):
        """`feeds` en la respuesta eran las tres RAMAS —`a`, `b` y ninguna— y el contador las
        leía como cables: un armario sin un solo cable declarado enseñaba un «3»."""
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': 'RK-cnt2'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'RK-cnt2',
                                 'u_height': 10}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert 'feeds' not in d, 'la clave que el contador confundía sigue ahí'
        assert d.get('feed_kinds'), 'las ramas ya no viajan con su nombre nuevo'
        assert (client.get(f'/api/v1/dcim/racks/{rack}').get_json()
                .get('counts', {}).get('power') == 0)


class TestElCableadoSePideEnDosVeces:
    """Lo declarado se lee de la base y está en milisegundos; el contraste hay que armarlo
    recorriendo la flota entera. Esperarlo para poder pintar la primera fila dejaba la pestaña en
    blanco por un dato que ocupa la última columna.
    """

    def _rack(self, client, nombre):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1, 'label': 'A'}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2, 'label': 'B'}).get_json()['uid']
        client.post('/api/v1/dcim/cables', json={'a_item': a, 'b_item': b, 'label': 'L1'})
        return rack

    def test_la_primera_trae_las_filas_y_ningun_veredicto(self, admin, client):
        _login(client)
        rack = self._rack(client, 'RK-cbl2')
        d = client.get(f'/api/v1/dcim/racks/{rack}/cables').get_json()
        assert d['checked'] is False
        assert [c['label'] for c in d['cables']] == ['L1']
        assert all('seen' not in c for c in d['cables']),             'la lista rápida reparte veredictos sin haber mirado'

    def test_y_la_segunda_los_trae(self, admin, client):
        _login(client)
        rack = self._rack(client, 'RK-cbl3')
        d = client.get(f'/api/v1/dcim/racks/{rack}/cables?check=1').get_json()
        assert d['checked'] is True
        assert d['cables'][0].get('seen')


class TestElPanelPuedeEstarEnOtroArmario:
    """En una sala de verdad los paneles viven en el rack de patcheo y no en el del servidor: sin
    los tramos de más allá, el camino se corta justo donde empieza a hacer falta.
    """

    def test_los_cables_del_panel_vecino_entran_en_la_respuesta(self, admin, client):
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': 'RK-pp'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        r1 = client.post('/api/v1/dcim/racks',
                         json={'room_uid': sala, 'name': 'R1', 'u_height': 10}).get_json()['uid']
        r2 = client.post('/api/v1/dcim/racks',
                         json={'room_uid': sala, 'name': 'R2', 'u_height': 10}).get_json()['uid']
        srv = client.post('/api/v1/dcim/items',
                          json={'rack_uid': r1, 'u_start': 1, 'label': 'SRV',
                                'role': 'server'}).get_json()['uid']
        # El panel y el switch, en el armario de AL LADO.
        pp = client.post('/api/v1/dcim/items',
                         json={'rack_uid': r2, 'u_start': 1, 'label': 'PP',
                               'role': 'patch_panel'}).get_json()['uid']
        sw = client.post('/api/v1/dcim/items',
                         json={'rack_uid': r2, 'u_start': 2, 'label': 'SW',
                               'role': 'switch'}).get_json()['uid']
        client.post('/api/v1/dcim/cables', json={'a_item': srv, 'b_item': pp, 'label': 'L1'})
        client.post('/api/v1/dcim/cables', json={'a_item': pp, 'b_item': sw, 'label': 'L2'})
        # Desde el armario del servidor se ven los DOS tramos: el suyo y el que sale del panel.
        d = client.get(f'/api/v1/dcim/racks/{r1}/cables?check=1').get_json()
        assert sorted(c['label'] for c in d['cables']) == ['L1', 'L2'],             'el tramo de más allá del panel no entra, así que el camino se corta'


class TestMeterUnPanelEnMedioDeUnCable:
    """Los enlaces se apuntan primero de punta a punta —«el servidor va al switch», que es lo que
    uno sabe— y los paneles aparecen después. Sin poder partir el cable, corregirlo es borrarlo y
    escribir tres: se pierden la etiqueta, el color y las dos bocas, así que no se corrige.
    """

    def _sala(self, client, nombre):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']

    def test_se_busca_un_equipo_por_su_etiqueta(self, admin, client):
        _login(client)
        rack = self._sala(client, 'RK-find')
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 1, 'label': 'PP-SALA-A',
                          'role': 'patch_panel'})
        d = client.get('/api/v1/dcim/items?q=pp-sala').get_json()
        assert [i['label'] for i in d['items']] == ['PP-SALA-A']
        # Y dice DÓNDE está: «PP-A» a secas no distingue dos paneles de dos armarios.
        assert d['items'][0]['rack'] == 'RK-find'

    def test_y_no_sale_lo_que_no_se_puede_ver(self, admin, client, fleet):
        """Esto ofrece dónde escribir, y ofrecer algo ajeno es ofrecer escribir en su
        inventario. Ni siquiera opaco: un armario compartido dibuja lo ajeno porque ocupa un U,
        y aquí no se dibuja nada — se elige.
        """
        c = _as(admin, 'busca-b', ['dcim_view', f'org.{fleet["b"]}.view'])
        uids = [i['uid'] for i in c.get('/api/v1/dcim/items').get_json()['items']]
        assert fleet['theirs'] in uids, 'lo suyo tampoco sale'
        assert fleet['mine'] not in uids, 'sale el equipo del vecino'

    def test_el_cable_se_parte_en_dos_tramos(self, admin, client):
        _login(client)
        rack = self._sala(client, 'RK-split')
        srv = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 1, 'label': 'SRV',
                                'role': 'server'}).get_json()['uid']
        sw = client.post('/api/v1/dcim/items',
                         json={'rack_uid': rack, 'u_start': 2, 'label': 'SW',
                               'role': 'switch'}).get_json()['uid']
        pp = client.post('/api/v1/dcim/items',
                         json={'rack_uid': rack, 'u_start': 3, 'label': 'PP',
                               'role': 'patch_panel'}).get_json()['uid']
        cable = client.post('/api/v1/dcim/cables',
                            json={'a_item': srv, 'a_port': 'eno1', 'b_item': sw,
                                  'b_port': 'gi1', 'label': 'L1'}).get_json()['uid']
        # Lo que hace la pantalla: primero el tramo nuevo, después mover el viejo.
        client.post('/api/v1/dcim/cables',
                    json={'a_item': pp, 'a_port': '12', 'b_item': sw, 'b_port': 'gi1'})
        r = client.put(f'/api/v1/dcim/cables/{cable}', json={'b_item': pp, 'b_port': '12'})
        assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/racks/{rack}/cables?check=1').get_json()
        assert len(d['cables']) == 2
        # El de siempre se queda con su etiqueta y su boca: es lo que se perdía al borrarlo.
        viejo = [c for c in d['cables'] if c['uid'] == cable][0]
        assert viejo['label'] == 'L1' and viejo['a_port'] == 'eno1'
        assert viejo['b_item'] == pp


class TestLaBusquedaDeEquiposSabeNombrarlos:
    """La mitad de lo que hay en un armario no está rotulado —una tapa, una bandeja, un panel
    recién puesto— y la búsqueda devolvía sólo la etiqueta: la pantalla caía al identificador,
    que es justo lo que su función de nombrar existe para no enseñar. Sexta vez que sale esta
    forma en esta sección.
    """

    def _rack(self, client, nombre='RK-nom'):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']

    def test_cada_fila_trae_con_que_nombrarse(self, admin, client):
        _login(client)
        rack = self._rack(client)
        tipo = client.post('/api/v1/dcim/catalog', json={
            'tree': 'device-types', 'manufacturer': 'Generico', 'model': 'Regleta 8',
            'u': 1}).get_json().get('uid')
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 7, 'role': 'pdu',
                          'type_uid': tipo or ''})
        fila = [i for i in client.get('/api/v1/dcim/items').get_json()['items']
                if i['rack'] == 'RK-nom'][0]
        assert fila['label'] == '', 'la prueba deja de probar lo que probaba'
        assert fila['type_name'] == 'Generico Regleta 8'
        assert fila['role'] == 'pdu'
        assert 'host_uid' in fila

    def test_y_se_puede_buscar_por_el_modelo(self, admin, client):
        """De lo que no está rotulado, el modelo es lo único que alguien sabe."""
        _login(client)
        rack = self._rack(client, 'RK-nom2')
        tipo = client.post('/api/v1/dcim/catalog', json={
            'tree': 'device-types', 'manufacturer': 'Digitus', 'model': 'DN-91424',
            'u': 1}).get_json().get('uid')
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 2, 'role': 'patch_panel',
                          'type_uid': tipo or ''})
        d = client.get('/api/v1/dcim/items?q=dn-914').get_json()
        assert [i['type_name'] for i in d['items']] == ['Digitus DN-91424']


class TestUnPuenteSeGuarda:
    """La regla «un cable va de un equipo a OTRO» vivía sólo en el navegador, que es lo mismo que
    no vivir en ninguna parte: la escritura entra por la API con o sin pantalla delante.
    """

    def _panel(self, client, nombre='RK-puente'):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']
        return client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'u_start': 1, 'label': 'PP',
                                 'role': 'patch_panel'}).get_json()['uid']

    def test_de_una_boca_a_otra_del_mismo_panel(self, admin, client):
        _login(client)
        pp = self._panel(client)
        r = client.post('/api/v1/dcim/cables',
                        json={'a_item': pp, 'a_port': '25', 'b_item': pp, 'b_port': '17'})
        assert r.status_code == 200, r.get_json()

    def test_pero_no_de_una_boca_a_ella_misma(self, admin, client):
        _login(client)
        pp = self._panel(client, 'RK-puente2')
        r = client.post('/api/v1/dcim/cables',
                        json={'a_item': pp, 'a_port': '25', 'b_item': pp, 'b_port': '25'})
        assert r.status_code == 400, r.get_json()

    def test_ni_sin_decir_por_donde(self, admin, client):
        """«Este equipo se une consigo mismo» no describe nada que se pueda ir a mirar."""
        _login(client)
        pp = self._panel(client, 'RK-puente3')
        r = client.post('/api/v1/dcim/cables', json={'a_item': pp, 'b_item': pp})
        assert r.status_code == 400, r.get_json()


class TestUnCableEsInventario:
    """`length_mm` y `description` existían desde el primer commit y **ningún camino las
    escribía**: valían siempre su valor por defecto. Y de qué categoría es —Cat 6A, OM4— no se
    podía decir en ninguna parte, que es el dato que decide si un enlace de 10 Gb va a funcionar.
    """

    def _dos(self, client, nombre):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1, 'label': 'A'}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2, 'label': 'B'}).get_json()['uid']
        return rack, a, b

    def test_se_guarda_categoria_metros_y_nota(self, admin, client):
        _login(client)
        rack, a, b = self._dos(client, 'RK-inv')
        r = client.post('/api/v1/dcim/cables',
                        json={'a_item': a, 'b_item': b, 'label': 'C-014',
                              'kind': 'copper', 'category': 'cat6a',
                              'length_mm': 3000, 'description': 'por la bandeja de arriba'})
        assert r.status_code == 200, r.get_json()
        c = client.get(f'/api/v1/dcim/racks/{rack}/cables').get_json()['cables'][0]
        assert c['label'] == 'C-014' and c['category'] == 'cat6a'
        assert c['length_mm'] == 3000
        assert c['description'] == 'por la bandeja de arriba'

    def test_y_las_categorias_viajan_con_la_respuesta(self, admin, client):
        """Como los colores de las ramas: una segunda copia en la pantalla es la que se queda sin
        la categoría que se añada mañana."""
        _login(client)
        rack, _a, _b = self._dos(client, 'RK-inv2')
        d = client.get(f'/api/v1/dcim/racks/{rack}/cables').get_json()
        assert 'cat6a' in (d['categories'] or {}).get('copper', [])
        assert 'om4' in (d['categories'] or {}).get('fiber', [])
        assert 'copper' in (d['kinds'] or [])

    def test_cada_parada_del_camino_dice_donde_esta(self, admin, client):
        """«PP-A 25» no dice adónde hay que ir: un camino sale del armario abierto casi
        siempre."""
        _login(client)
        rack, srv, sw = self._dos(client, 'RK-donde')
        pp = client.post('/api/v1/dcim/items',
                         json={'rack_uid': rack, 'u_start': 5, 'label': 'PP',
                               'role': 'patch_panel'}).get_json()['uid']
        client.post('/api/v1/dcim/cables',
                    json={'a_item': srv, 'a_port': 'eno1', 'b_item': pp, 'b_port': '25'})
        client.post('/api/v1/dcim/cables',
                    json={'a_item': pp, 'a_port': '25', 'b_item': sw, 'b_port': 'gi1'})
        d = client.get(f'/api/v1/dcim/racks/{rack}/cables?check=1').get_json()
        # Sin sondas no hay camino confirmado, pero las puntas de cada tramo saben dónde están:
        # es lo mismo que se pinta cuando sí lo hay.
        assert d['checked'] is True
        c = [x for x in d['cables'] if x['b_item'] == pp][0]
        assert c['b_item'] == pp


class TestElInventarioDeLosCables:
    """El número de inventario no es la etiqueta, y un cable de corriente es un cable."""

    def _rack(self, client, nombre):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']

    def test_un_cable_de_datos_tiene_numero_ademas_de_etiqueta(self, admin, client):
        _login(client)
        rack = self._rack(client, 'RK-inv3')
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1, 'label': 'A'}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2, 'label': 'B'}).get_json()['uid']
        client.post('/api/v1/dcim/cables',
                    json={'a_item': a, 'b_item': b, 'label': 'C-014', 'asset': 'INV-2211'})
        c = client.get(f'/api/v1/dcim/racks/{rack}/cables').get_json()['cables'][0]
        # Los dos, y distintos: meterlos en una casilla obliga a elegir cuál se pierde.
        assert c['label'] == 'C-014' and c['asset'] == 'INV-2211'

    def test_y_el_de_corriente_tambien(self, admin, client):
        _login(client)
        rack = self._rack(client, 'RK-inv4')
        it = client.post('/api/v1/dcim/items',
                         json={'rack_uid': rack, 'u_start': 1, 'label': 'A'}).get_json()['uid']
        pdu = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': rack, 'name': 'P', 'feed': 'a',
                                'outlets': 8}).get_json()['uid']
        r = client.post('/api/v1/dcim/feeds',
                        json={'item_uid': it, 'pdu_uid': pdu, 'outlet': 1,
                              'label': 'P-07', 'asset': 'INV-991', 'category': 'c13-c14',
                              'length_mm': 500, 'description': 'por detrás'})
        assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        f = d['items'][0]['feeds'][0]
        assert f['asset'] == 'INV-991' and f['category'] == 'c13-c14'
        assert f['length_mm'] == 500 and f['label'] == 'P-07'

    def test_y_se_puede_corregir_despues(self, admin, client):
        """Un cable se apunta con prisa —se está montando— y se completa después."""
        _login(client)
        rack = self._rack(client, 'RK-inv5')
        it = client.post('/api/v1/dcim/items',
                         json={'rack_uid': rack, 'u_start': 1, 'label': 'A'}).get_json()['uid']
        pdu = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': rack, 'name': 'P', 'feed': 'a',
                                'outlets': 8}).get_json()['uid']
        cable = client.post('/api/v1/dcim/feeds',
                            json={'item_uid': it, 'pdu_uid': pdu,
                                  'outlet': 1}).get_json()['uid']
        r = client.put(f'/api/v1/dcim/feeds/{cable}',
                       json={'asset': 'INV-992', 'length_mm': 250, 'category': 'c19-c20'})
        assert r.status_code == 200, r.get_json()
        f = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()['items'][0]['feeds'][0]
        assert f['asset'] == 'INV-992' and f['length_mm'] == 250
        # Y sin perder dónde está enchufado, que es lo que se perdía borrando y reescribiendo.
        assert f['outlet'] == 1

    def test_las_categorias_de_corriente_viajan_con_la_respuesta(self, admin, client):
        _login(client)
        rack = self._rack(client, 'RK-inv6')
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert 'c13-c14' in (d.get('categories') or [])


class TestElCableadoFueraDeSuArmario:
    """«¿Dónde está el cable C-014?» y «¿cuántos latiguillos de Cat 6A hay puestos?» obligaban a
    saber el armario ANTES de poder buscar, que es lo contrario de buscar.
    """

    def _dos(self, client, nombre, **cable):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1, 'label': 'A'}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2, 'label': 'B'}).get_json()['uid']
        client.post('/api/v1/dcim/cables', json=dict({'a_item': a, 'b_item': b}, **cable))
        return rack

    def test_se_busca_sin_decir_el_armario(self, admin, client):
        _login(client)
        self._dos(client, 'RK-w1', label='C-014', asset='INV-77', category='cat6a',
                  kind='copper')
        d = client.get('/api/v1/dcim/cables?q=c-014').get_json()
        assert [c['label'] for c in d['cables']] == ['C-014']
        # Y dice DÓNDE está, que es la otra mitad de la respuesta.
        assert d['cables'][0]['a_at']['rack'] == 'RK-w1'

    def test_tambien_por_numero_de_inventario(self, admin, client):
        _login(client)
        self._dos(client, 'RK-w2', label='X', asset='INV-4242')
        d = client.get('/api/v1/dcim/cables?q=inv-4242').get_json()
        assert [c['asset'] for c in d['cables']] == ['INV-4242']

    def test_y_se_filtra_por_categoria(self, admin, client):
        """«Cuántos latiguillos de Cat 6A hay puestos» es una pregunta de compras, no de un
        armario."""
        _login(client)
        self._dos(client, 'RK-w3', label='SEIS', category='cat6a')
        self._dos(client, 'RK-w4', label='CINCO', category='cat5e')
        d = client.get('/api/v1/dcim/cables?category=cat6a').get_json()
        etiquetas = [c['label'] for c in d['cables']]
        assert 'SEIS' in etiquetas and 'CINCO' not in etiquetas

    def test_un_cable_entre_dos_ajenos_no_sale(self, admin, client, fleet):
        """Se estrecha como todo lo demás."""
        _login(client)
        client.post('/api/v1/dcim/cables',
                    json={'a_item': fleet['mine'], 'b_item': fleet['theirs'], 'label': 'MIXTO'})
        c = _as(admin, 'wire-b', ['dcim_view', f'org.{fleet["b"]}.view'])
        d = c.get('/api/v1/dcim/cables').get_json()
        # El suyo sale —un extremo es suyo— y del otro extremo no se dice nada.
        fila = [x for x in d['cables'] if x['label'] == 'MIXTO']
        assert len(fila) == 1
        assert fila[0]['a_at']['foreign'] is True and fila[0]['b_at']['foreign'] is False

    def test_y_esta_pantalla_no_contrasta(self, admin, client):
        """Contrastar es una pregunta sobre UN armario: armar el mapa de la flota para listar
        cables de seis salas sería pagarlo seis veces por un dato que no se usa."""
        _login(client)
        self._dos(client, 'RK-w5', label='Z')
        d = client.get('/api/v1/dcim/cables').get_json()
        assert all('seen' not in c for c in d['cables'])


class TestLaListaLlevaLosDosCables:
    """Un cable de red y uno de corriente son la misma pregunta —dónde está, cuántos de esta
    clase hay puestos— y viven en dos tablas por dónde acaban, no por lo que son. Dos listas
    obligarían a buscar dos veces lo mismo y a acordarse de cuál mirar.
    """

    def test_salen_los_de_red_y_los_de_corriente(self, admin, client):
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': 'RK-w9'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'RK-w9',
                                 'u_height': 10}).get_json()['uid']
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1, 'label': 'A'}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2, 'label': 'B'}).get_json()['uid']
        pdu = client.post('/api/v1/dcim/pdus',
                          json={'rack_uid': rack, 'name': 'PDU-A', 'feed': 'a',
                                'outlets': 8}).get_json()['uid']
        client.post('/api/v1/dcim/cables', json={'a_item': a, 'b_item': b, 'label': 'RED-1'})
        client.post('/api/v1/dcim/feeds', json={'item_uid': a, 'pdu_uid': pdu, 'outlet': 3,
                                                'label': 'LUZ-1'})
        d = client.get('/api/v1/dcim/cables').get_json()
        clases = {c['label']: c['wire'] for c in d['cables']}
        assert clases.get('RED-1') == 'data' and clases.get('LUZ-1') == 'power'
        # Y la regleta hace de segunda punta: tiene nombre y está en un armario, que es lo que
        # se necesita de una punta. Su «boca» es el número de toma.
        luz = [c for c in d['cables'] if c['label'] == 'LUZ-1'][0]
        assert luz['b_at']['label'] == 'PDU-A' and luz['b_at']['rack'] == 'RK-w9'
        assert luz['b_port'] == '3'

    def test_y_las_categorias_de_los_dos_viajan_juntas(self, admin, client):
        """La pantalla ofrece las que valen para lo que se está filtrando, y para eso tienen que
        llegar juntas."""
        _login(client)
        d = client.get('/api/v1/dcim/cables').get_json()
        cats = d['categories'] or {}
        assert 'cat6a' in (cats.get('copper') or [])
        assert 'c13-c14' in (cats.get('power') or [])


class TestBuscarPorElNombreDeUnExtremo:
    """Buscar un cable por lo que hay en sus puntas —«el latiguillo de SW01»— es lo normal, y ese
    nombre está en otra tabla: se resuelve antes a identificadores para poder preguntar por
    ellos, en vez de traerse los cables de toda la instalación para mirarles las puntas.
    """

    def _sala(self, client, nombre):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1,
                              'label': 'SW-NUCLEO'}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2,
                              'label': 'SRV-99'}).get_json()['uid']
        client.post('/api/v1/dcim/cables', json={'a_item': a, 'b_item': b, 'label': 'X-1'})
        return rack

    def test_por_el_nombre_del_equipo(self, admin, client):
        _login(client)
        self._sala(client, 'RK-nom-a')
        d = client.get('/api/v1/dcim/cables?q=sw-nucleo').get_json()
        assert [c['label'] for c in d['cables']] == ['X-1']

    def test_y_por_el_nombre_del_armario(self, admin, client):
        _login(client)
        self._sala(client, 'RK-nom-b')
        d = client.get('/api/v1/dcim/cables?q=rk-nom-b').get_json()
        assert [c['label'] for c in d['cables']] == ['X-1']

    def test_lo_que_no_esta_no_sale(self, admin, client):
        """Se buscó algo y no lo tiene nadie: cero filas, no todas."""
        _login(client)
        self._sala(client, 'RK-nom-c')
        assert client.get('/api/v1/dcim/cables?q=zzz-no-existe').get_json()['cables'] == []

    def test_un_guion_bajo_no_es_un_comodin(self, admin, client):
        """Sin escaparlo, `_` encuentra cualquier cosa: un buscador que ignora lo que se le pide
        contesta, que es peor que no encontrar nada."""
        _login(client)
        self._sala(client, 'RK-nom-d')
        assert client.get('/api/v1/dcim/cables?q=x_1').get_json()['cables'] == []

    def test_los_equipos_se_buscan_igual(self, admin, client):
        _login(client)
        self._sala(client, 'RK-nom-e')
        d = client.get('/api/v1/dcim/items?q=srv-9').get_json()
        assert 'SRV-99' in [i['label'] for i in d['items']]
        assert client.get('/api/v1/dcim/items?q=srv_9').get_json()['items'] == []


class TestLosEquiposFueraDeSuArmario:
    """La lista de equipos vive dentro de su rack, así que «qué servidores hay en esta sede» y
    «qué se queda sin garantía este trimestre» obligaban a abrir armario por armario. El dato ya
    estaba: era la pantalla la que faltaba.
    """

    def _sala(self, client, nombre, **item):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 10}).get_json()['uid']
        uid = client.post('/api/v1/dcim/items',
                          json=dict({'rack_uid': rack, 'u_start': 1}, **item)).get_json()['uid']
        return sede, rack, uid

    def test_cada_equipo_dice_donde_esta_del_todo(self, admin, client):
        """Hasta la SEDE: «qué servidores hay en esta sede» sube dos niveles por encima del
        armario, y eso no está en la fila del equipo."""
        _login(client)
        self._sala(client, 'DC-uno', label='SRV-A', role='server')
        fila = [i for i in client.get('/api/v1/dcim/items?limit=200').get_json()['items']
                if i['label'] == 'SRV-A'][0]
        assert fila['rack'] == 'DC-uno' and fila['site'] == 'DC-uno'
        assert fila['role'] == 'server'

    def test_trae_lo_que_solo_tiene_ESA_caja(self, admin, client):
        """El número de serie, el de inventario y la garantía: sin ellos la lista es un
        recuento, y «qué se queda sin cobertura» no tiene dónde contestarse."""
        _login(client)
        self._sala(client, 'DC-dos', label='SRV-B', serial='SN-1', asset='INV-1',
                   warranty_until='2030-01-01', supplier='Casa')
        fila = [i for i in client.get('/api/v1/dcim/items?limit=200').get_json()['items']
                if i['label'] == 'SRV-B'][0]
        assert fila['serial'] == 'SN-1' and fila['asset'] == 'INV-1'
        assert fila['warranty_until'] == '2030-01-01' and fila['supplier'] == 'Casa'

    def test_se_filtra_por_sede(self, admin, client):
        _login(client)
        sede, _r, _u = self._sala(client, 'DC-tres', label='AQUI')
        self._sala(client, 'DC-cuatro', label='ALLI')
        d = client.get(f'/api/v1/dcim/items?limit=200&site={sede}').get_json()
        etiquetas = [i['label'] for i in d['items']]
        assert 'AQUI' in etiquetas and 'ALLI' not in etiquetas

    def test_una_sede_sin_armarios_da_cero_y_no_todos(self, admin, client):
        """Un `IN` vacío es «ninguno». Sin condición saldrían todos, que es la respuesta
        contraria y creíble."""
        _login(client)
        vacia = client.post('/api/v1/dcim/sites', json={'name': 'DC-vacia'}).get_json()['uid']
        self._sala(client, 'DC-cinco', label='ALGO')
        d = client.get(f'/api/v1/dcim/items?limit=200&site={vacia}').get_json()
        assert d['items'] == []

    def test_y_el_tope_no_lo_decide_quien_llama(self, admin, client):
        """`limit` se acota: una URL escrita a mano no puede pedir la instalación entera."""
        _login(client)
        self._sala(client, 'DC-seis', label='UNO')
        d = client.get('/api/v1/dcim/items?limit=99999').get_json()
        assert len(d['items']) <= 200


class TestEstarEnUnArmarioSinOcuparU:
    """Un SAI en el suelo al lado, un cuadro en la pared, una regleta atornillada al lateral:
    ocupan sitio, se alimentan, se cablean y hay que ir a mirarlos, y lo único que no tienen es
    U. **Una sola decisión y no cinco casos particulares.**
    """

    def _rack(self, client, nombre, alto=2):
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': alto}).get_json()['uid']

    def test_cabe_en_un_armario_lleno(self, admin, client):
        """Un SAI en el suelo no deja de caber porque el armario esté lleno: preguntarle si cabe
        sería preguntarle por un sitio que no ocupa."""
        _login(client)
        rack = self._rack(client, 'RK-al-lado', alto=1)
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 1, 'u_height': 1, 'label': 'LLENO'})
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'label': 'SAI', 'role': 'ups',
                              'placement': 'near'})
        assert r.status_code == 200, r.get_json()

    def test_y_no_le_quita_el_sitio_a_nada(self, admin, client):
        _login(client)
        rack = self._rack(client, 'RK-al-lado2', alto=4)
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'label': 'SAI', 'placement': 'near'})
        d = client.get(f'/api/v1/dcim/racks/{rack}').get_json()
        # Las cuatro U siguen libres: lo que no ocupa, no ocupa.
        assert d['free']['count'] == 4

    def test_pero_sigue_estando_EN_el_armario(self, admin, client):
        """Se alimenta, se cablea y hay que ir a mirarlo: lo único que no hace es quitar sitio.
        Sacarlo de la lista lo convertiría en algo que hay que recordar."""
        _login(client)
        rack = self._rack(client, 'RK-al-lado3', alto=4)
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'label': 'SAI',
                                'placement': 'near'}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/racks/{rack}').get_json()
        assert uid in [i['uid'] for i in d['items']]
        assert [i['placement'] for i in d['items'] if i['uid'] == uid] == ['near']

    def test_una_forma_de_estar_puesto_que_no_existe_se_rechaza(self, admin, client):
        _login(client)
        rack = self._rack(client, 'RK-al-lado4')
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'label': 'X', 'placement': 'flotando'})
        assert r.status_code == 400, r.get_json()

    def test_lo_de_siempre_sigue_ocupando(self, admin, client):
        """`u` es el valor por defecto: todo lo escrito antes de esta columna se atornilló a los
        mástiles, que es lo que de verdad hizo."""
        _login(client)
        rack = self._rack(client, 'RK-al-lado5', alto=1)
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 1, 'u_height': 1, 'label': 'A'})
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1, 'u_height': 1, 'label': 'B'})
        assert r.status_code == 400, 'dos cosas en el mismo U dejaron de chocar'

    def test_lo_montado_encima_hereda_como_esta_puesto(self, admin, client):
        """Lo que va sobre una bandeja que está al lado del armario está también al lado: si no
        lo heredara, el alzado dibujaría media bandeja."""
        _login(client)
        rack = self._rack(client, 'RK-al-lado6', alto=4)
        bandeja = client.post('/api/v1/dcim/items',
                              json={'rack_uid': rack, 'label': 'Bandeja', 'role': 'shelf',
                                    'placement': 'near'}).get_json()['uid']
        hijo = client.post('/api/v1/dcim/items',
                           json={'rack_uid': rack, 'label': 'MiniPC',
                                 'parent_uid': bandeja}).get_json()['uid']
        d = client.get(f'/api/v1/dcim/racks/{rack}').get_json()
        assert [i['placement'] for i in d['items'] if i['uid'] == hijo] == ['near']

    def test_y_una_regleta_del_lateral_es_el_MISMO_caso(self, admin, client):
        """Existía como regleta y no como equipo, que es un caso particular con nombre propio.
        Con `side` es un equipo del armario que no ocupa U, y se puede declarar como regleta."""
        _login(client)
        rack = self._rack(client, 'RK-al-lado7', alto=2)
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'label': 'Regleta lateral', 'role': 'pdu',
                                'placement': 'side'}).get_json()['uid']
        r = client.post('/api/v1/dcim/pdus',
                        json={'rack_uid': rack, 'item_uid': uid, 'name': 'Regleta lateral',
                              'feed': 'a', 'outlets': 8})
        assert r.status_code == 200, r.get_json()
        d = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert [p['item_uid'] for p in d['pdus']] == [uid]
        # Y las dos U siguen libres.
        assert client.get(f'/api/v1/dcim/racks/{rack}').get_json()['free']['count'] == 2


class TestMoverAlgoFueraDeLosMastilesLeQuitaLaU:
    """Un equipo que se mueve de los mástiles al suelo conservaba la U que tenía, y una lista que
    lee `u_start` la enseña tan tranquila: «SAI · U1» en un armario donde no está.
    """

    def test_al_moverlo_deja_de_tener_U(self, admin, client):
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': 'RK-mv'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'RK-mv',
                                 'u_height': 4}).get_json()['uid']
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 2, 'u_height': 2,
                                'label': 'SAI'}).get_json()['uid']
        r = client.put(f'/api/v1/dcim/items/{uid}', json={'placement': 'near'})
        assert r.status_code == 200, r.get_json()
        fila = [i for i in client.get(f'/api/v1/dcim/racks/{rack}').get_json()['items']
                if i['uid'] == uid][0]
        assert fila['u_start'] == 0 and fila['u_height'] == 0
        # Y las cuatro U vuelven a estar libres.
        assert client.get(f'/api/v1/dcim/racks/{rack}').get_json()['free']['count'] == 4

    def test_y_al_volver_a_los_mastiles_hay_que_decir_donde(self, admin, client):
        """Cero no es una U: volver a atornillarlo es volver a decir a qué altura."""
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': 'RK-mv2'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'RK-mv2',
                                 'u_height': 4}).get_json()['uid']
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'label': 'SAI',
                                'placement': 'near'}).get_json()['uid']
        # Sin decir la U, no cabe en ninguna: se rechaza en vez de colarlo en la 1.
        assert client.put(f'/api/v1/dcim/items/{uid}',
                          json={'placement': 'u'}).status_code == 400
        assert client.put(f'/api/v1/dcim/items/{uid}',
                          json={'placement': 'u', 'u_start': 3,
                                'u_height': 1}).status_code == 200


class TestElNumeroDeInventarioLoPoneElPanel:
    """Único entre TODO lo inventariado, y el siguiente no se teclea.

    Quien numera un armario entero escribe cuarenta veces un número que ya está decidido, y la
    vez que se equivoca no lo dice nadie: el duplicado aparece meses después, cuando dos fichas
    dicen ser la misma cosa. Por eso lo resuelve el servidor y no la pantalla — dos personas
    numerando a la vez desde dos pantallas verían las dos el mismo «siguiente».
    """

    def _rack(self, client, nombre):
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre,
                                 'u_height': 42}).get_json()['uid']

    def test_el_comodin_se_convierte_en_el_siguiente(self, admin, client):
        rack = self._rack(client, 'INV-a')
        uno = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 1, 'asset': 'INV-?'})
        dos = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 2, 'asset': 'INV-?'})
        assert uno.get_json()['asset'] == 'INV-1'
        assert dos.get_json()['asset'] == 'INV-2'

    def test_y_con_tres_se_rellena_a_tres_cifras(self, admin, client):
        rack = self._rack(client, 'INV-b')
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 1, 'asset': 'INV-45'})
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2, 'asset': 'INV-???'})
        assert r.get_json()['asset'] == 'INV-046'

    def test_lo_que_se_guarda_es_lo_que_se_devuelve(self, admin, client):
        """El panel lo dice en un aviso, y decir uno y guardar otro sería peor que callarse."""
        rack = self._rack(client, 'INV-c')
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 1,
                                'asset': 'INV-?'}).get_json()['uid']
        fila = [i for i in client.get(f'/api/v1/dcim/racks/{rack}').get_json()['items']
                if i['uid'] == uid][0]
        assert fila['asset'] == 'INV-1'

    def test_un_numero_repetido_no_llega_a_escribirse(self, admin, client):
        rack = self._rack(client, 'INV-d')
        client.post('/api/v1/dcim/items',
                    json={'rack_uid': rack, 'u_start': 1, 'asset': 'INV-9'})
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2, 'asset': 'inv-9'})
        assert r.status_code == 400

    def test_ni_aunque_sea_de_otra_clase_de_cosa(self, admin, client):
        """En el albarán hay UNA lista: un latiguillo y un servidor no pueden ser el 45."""
        rack = self._rack(client, 'INV-e')
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1,
                              'asset': 'INV-45'}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2}).get_json()['uid']
        choca = client.post('/api/v1/dcim/cables',
                            json={'a_item': a, 'b_item': b, 'a_port': '1', 'b_port': '2',
                                  'asset': 'INV-45'})
        assert choca.status_code == 400
        sigue = client.post('/api/v1/dcim/cables',
                            json={'a_item': a, 'b_item': b, 'a_port': '3', 'b_port': '4',
                                  'asset': 'INV-?'})
        assert sigue.get_json()['asset'] == 'INV-46'

    def test_el_armario_tambien_lleva_numero(self, admin, client):
        """Lo llevaban el equipo y los dos cables, y el mueble que los sostiene no."""
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': 'INV-f'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        client.post('/api/v1/dcim/racks', json={'room_uid': sala, 'name': 'R1',
                                                'asset': 'RACK-7'})
        r = client.post('/api/v1/dcim/racks', json={'room_uid': sala, 'name': 'R2',
                                                    'asset': 'RACK-?'})
        assert r.status_code == 200
        racks = client.get('/api/v1/dcim/sites').get_json()['sites'][0]['rooms'][0]['rackList']
        assert sorted(x['asset'] for x in racks) == ['RACK-7', 'RACK-8']

    def test_editar_sin_tocar_el_numero_no_choca_consigo_misma(self, admin, client):
        rack = self._rack(client, 'INV-g')
        uid = client.post('/api/v1/dcim/items',
                          json={'rack_uid': rack, 'u_start': 1,
                                'asset': 'INV-3'}).get_json()['uid']
        r = client.put(f'/api/v1/dcim/items/{uid}', json={'asset': 'INV-3', 'label': 'SW'})
        assert r.status_code == 200

    def test_dos_grupos_de_interrogantes_se_rechazan(self, admin, client):
        rack = self._rack(client, 'INV-h')
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1, 'asset': 'INV-?-?'})
        assert r.status_code == 400

    def test_una_peticion_que_acaba_en_403_no_gasta_un_numero(self, admin, client):
        """Gastar uno de la numeración en algo que no se va a escribir deja un hueco en la
        cuenta que nadie sabe explicar — y encima se lo gasta el que no puede escribir."""
        rack = self._rack(client, 'INV-i')
        org = client.post('/api/v1/dcim/orgs', json={'name': 'Ajena'}).get_json()['uid']
        client.post('/api/v1/dcim/owner', json={'scope': 'rack', 'uid': rack, 'org_uid': org})
        otro = _as(admin, 'sinrack', ['dcim_view', 'dcim_edit'])
        assert otro.post('/api/v1/dcim/items',
                         json={'rack_uid': rack, 'u_start': 5,
                               'asset': 'INV-?'}).status_code == 403
        r = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 6, 'asset': 'INV-?'})
        assert r.get_json()['asset'] == 'INV-1'

    def test_tambien_al_corregir_una_ficha_ya_escrita(self, admin, client):
        """Las tres puertas de edición, no sólo las de alta: un número se teclea mal las más de
        las veces corrigiendo, que es cuando ya no se está mirando la lista."""
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': 'INV-j'}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'R1', 'u_height': 42,
                                 'asset': 'INV-1'}).get_json()['uid']
        otro = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'R2'}).get_json()['uid']
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1, 'asset': 'INV-2'}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2}).get_json()['uid']
        cable = client.post('/api/v1/dcim/cables',
                            json={'a_item': a, 'b_item': b, 'a_port': '1',
                                  'b_port': '2'}).get_json()['uid']
        # Un armario, un equipo y un cable, cada uno por su puerta.
        assert client.put(f'/api/v1/dcim/racks/{otro}',
                          json={'asset': 'INV-2'}).status_code == 400
        assert client.put(f'/api/v1/dcim/items/{b}',
                          json={'asset': 'INV-1'}).status_code == 400
        assert client.put(f'/api/v1/dcim/cables/{cable}',
                          json={'asset': 'inv-2'}).status_code == 400
        # Y el comodín también sirve corrigiendo: 1 y 2 puestos, el siguiente es el 3.
        r = client.put(f'/api/v1/dcim/cables/{cable}', json={'asset': 'INV-?'})
        assert r.get_json()['asset'] == 'INV-3'


class TestLaTiradaEnteraDeUnCable:
    """De qué tirada forma parte un cable, preguntado por la ficha desde las dos pantallas."""

    def _sala(self, client, nombre):
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return sede, sala

    def _tirada(self, client, rack, rack2=None):
        """SRV → PP-A · 12 → PP-B · 12 → SW, con los paneles donde se diga."""
        otro = rack2 or rack
        def _pon(rk, u, **mas):
            return client.post('/api/v1/dcim/items',
                               json=dict({'rack_uid': rk, 'u_start': u}, **mas)).get_json()['uid']
        srv = _pon(rack, 1, label='SRV01', role='server')
        ppa = _pon(rack, 2, label='PP-A', role='patch_panel')
        ppb = _pon(otro, 3, label='PP-B', role='patch_panel')
        sw = _pon(otro, 4, label='SW01', role='switch')
        c = []
        for a, ap, b, bp in ((srv, 'eth0', ppa, '12'), (ppb, '12', ppa, '12'),
                             (sw, 'Gi1/0/7', ppb, '12')):
            c.append(client.post('/api/v1/dcim/cables',
                                 json={'a_item': a, 'a_port': ap, 'b_item': b,
                                       'b_port': bp}).get_json()['uid'])
        return {'srv': srv, 'ppa': ppa, 'ppb': ppb, 'sw': sw, 'c': c}

    def test_los_tres_tramos_desde_el_de_en_medio(self, admin, client):
        _, sala = self._sala(client, 'RUN-a')
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'R1'}).get_json()['uid']
        t = self._tirada(client, rack)
        r = client.get(f'/api/v1/dcim/cables/{t["c"][1]}/run')
        assert r.status_code == 200
        legs = r.get_json()['path']['legs']
        # En orden, de punta a punta. Por cuál de las dos puntas empieza es cosa suya —lo que
        # importa y lo mira el test de la unidad es que sea SIEMPRE la misma— y aquí los
        # identificadores los pone la base, así que no se puede predecir cuál gana.
        assert [x['cable'] for x in legs] in (t['c'], list(reversed(t['c'])))
        # Con el nombre de cada parada, que es lo que se lee: sin ellos son identificadores.
        assert {legs[0]['a_label'], legs[-1]['b_label']} == {'SRV01', 'SW01'}

    def test_aunque_los_paneles_esten_en_otro_armario(self, admin, client):
        """En una sala de verdad los paneles viven en el rack de patcheo y no en el del
        servidor: una tirada que se parara en el armario abierto se cortaría justo donde empieza
        a hacer falta."""
        _, sala = self._sala(client, 'RUN-b')
        r1 = client.post('/api/v1/dcim/racks',
                         json={'room_uid': sala, 'name': 'R1'}).get_json()['uid']
        r2 = client.post('/api/v1/dcim/racks',
                         json={'room_uid': sala, 'name': 'R2'}).get_json()['uid']
        t = self._tirada(client, r1, r2)
        legs = client.get(f'/api/v1/dcim/cables/{t["c"][0]}/run').get_json()['path']['legs']
        assert [x['cable'] for x in legs] in (t['c'], list(reversed(t['c'])))
        # Y el ARMARIO de cada parada, que es la otra mitad de la dirección: «PP-B 12» no dice
        # adónde hay que ir.
        assert {x['b_at'].get('rack') for x in legs} == {'R1', 'R2'}

    def test_sin_contraste_ninguno(self, admin, client):
        """Una tirada es un hecho declarado. Antes sólo salía cruzada con lo que los
        dispositivos ven, así que la que nadie confirma —media instalación— no salía."""
        _, sala = self._sala(client, 'RUN-c')
        rack = client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': 'R1'}).get_json()['uid']
        t = self._tirada(client, rack)
        # Nadie ha visto nada por LLDP y la tirada está entera igualmente.
        assert len(client.get(f'/api/v1/dcim/cables/{t["c"][2]}/run')
                   .get_json()['path']['legs']) == 3

    def test_un_cable_que_no_existe(self, admin, client):
        _login(client)
        assert client.get('/api/v1/dcim/cables/no-existe/run').status_code == 404

    def test_y_no_se_cuenta_la_tirada_de_lo_ajeno(self, admin, client, fleet):
        """Un cable se ve si se ven las dos cosas que une: con permiso sobre una sola bastaría
        declarar un cable hacia lo ajeno para que la tirada lo nombrara."""
        cable = client.post('/api/v1/dcim/cables',
                            json={'a_item': fleet['mine'], 'a_port': '1',
                                  'b_item': fleet['theirs'], 'b_port': '2'}).get_json()['uid']
        otro = _as(admin, 'sinfilial', ['dcim_view', 'dcim_org_view'])
        assert otro.get(f'/api/v1/dcim/cables/{cable}/run').status_code == 403


class TestLosColoresQueYaSeUsan:
    """Lo que de verdad se elige al declarar un cable es **el color que ya está puesto**: si el
    azul de esta sala es un azul concreto que llevan cuarenta cables, el cuarenta y uno tiene que
    ser ése. Buscarlo en la rueda a ojo es cómo una instalación acaba con nueve azules que no son
    el mismo azul.

    Los cuenta el servidor sobre la tabla y viajan con las dos listas: una lista escrita en la
    pantalla es la que no sabe qué colores usa esta casa.
    """

    def _rack(self, client, nombre):
        _login(client)
        sede = client.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
        sala = client.post('/api/v1/dcim/rooms',
                           json={'site_uid': sede, 'name': 'S'}).get_json()['uid']
        return client.post('/api/v1/dcim/racks',
                           json={'room_uid': sala, 'name': nombre}).get_json()['uid']

    def test_viajan_con_las_dos_listas_y_del_mas_usado_al_menos(self, admin, client):
        rack = self._rack(client, 'COL-a')
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2}).get_json()['uid']
        for i, color in enumerate(('#1e88e5', '#1e88e5', '#e53935')):
            client.post('/api/v1/dcim/cables',
                        json={'a_item': a, 'b_item': b, 'a_port': f'a{i}', 'b_port': f'b{i}',
                              'color': color})
        # La de la sección de cableado y la de la pestaña de un armario: la ficha es una para las
        # dos, así que las dos tienen que poder ofrecer lo mismo.
        for url in ('/api/v1/dcim/cables', f'/api/v1/dcim/racks/{rack}/cables?check=1'):
            usados = client.get(url).get_json()['colors_used']
            assert usados[:2] == ['#1e88e5', '#e53935'], url

    def test_y_lo_vacio_no_es_un_color(self, admin, client):
        """«Nadie lo ha dicho» le pasa a cuarenta cables y no es un color que ofrecer."""
        rack = self._rack(client, 'COL-b')
        a = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 1}).get_json()['uid']
        b = client.post('/api/v1/dcim/items',
                        json={'rack_uid': rack, 'u_start': 2}).get_json()['uid']
        client.post('/api/v1/dcim/cables',
                    json={'a_item': a, 'b_item': b, 'a_port': '1', 'b_port': '2', 'color': ''})
        assert client.get('/api/v1/dcim/cables').get_json()['colors_used'] == []


class TestUnaEmpresaDiceQueTieneFichado:
    """Desde el árbol se pregunta «¿de quién es este armario?»; desde la pantalla de empresas,
    «¿qué es de esta sociedad?». Sin el recuento, borrar una es pulsar a ciegas: lo que era suyo
    deja de estar fichado y nadie sabía cuánto era.
    """

    def test_cuenta_lo_dicho_y_no_lo_heredado(self, admin, client, fleet):
        """Una sede de la filial B con cuarenta equipos dentro cuenta como UNA sede: los equipos
        no lo dicen, lo heredan, y contarlos sería contar la misma propiedad cuarenta veces."""
        orgs = {o['uid']: o for o in client.get('/api/v1/dcim/orgs').get_json()['orgs']}
        # El departamento de IT tiene dicha la sede; la filial, un equipo dentro del rack.
        assert orgs[fleet['it']]['said'] == {'site': 1}
        assert orgs[fleet['b']]['said'] == {'item': 1}

    def test_y_una_sin_nada_lo_dice_con_un_hueco(self, admin, client):
        _login(client)
        uid = client.post('/api/v1/dcim/orgs', json={'name': 'Recién creada'}).get_json()['uid']
        orgs = {o['uid']: o for o in client.get('/api/v1/dcim/orgs').get_json()['orgs']}
        assert orgs[uid]['said'] == {}

    def test_y_borrarla_deja_lo_suyo_sin_fichar(self, admin, client, fleet):
        """No es un campo que se corrige: es una fila que desaparece con todo lo que la
        nombraba. Se hace, y el recuento de al lado deja de contarlo."""
        assert client.delete(f'/api/v1/dcim/orgs/{fleet["b"]}').status_code == 200
        uids = [o['uid'] for o in client.get('/api/v1/dcim/orgs').get_json()['orgs']]
        assert fleet['b'] not in uids
        # Y el equipo que era suyo sigue estando: lo que se borró es lo DICHO, así que vuelve a
        # heredar de su sede. «Sin dueño» no es lo mismo que «hereda», y aquí lo correcto es lo
        # segundo — la fila que decía «esto es de la filial B» ya no existe.
        fila = [i for i in client.get(f'/api/v1/dcim/racks/{fleet["rack"]}').get_json()['items']
                if i['uid'] == fleet['theirs']][0]
        assert fila.get('org_uid') != fleet['b']
        assert fila.get('org_uid') == fleet['it']
