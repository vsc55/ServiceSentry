#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El registro de empresas del core: su API, sus permisos y de dónde vino.

La pertenencia es el otro eje de todo lo que el panel guarda. Vivía dentro del inventario
físico, que es donde se hizo la pregunta por primera vez, y era un accidente de calendario: la
misma sociedad que paga el armario tiene usuarios en el directorio y licencias en Microsoft 365.

Lo que se comprueba aquí es lo que ese traslado tiene que seguir cumpliendo:

* que se ficha **cualquier ámbito que alguien declare**, y ninguno más — un armario del
  inventario y una máquina del registro, que son de dos paquetes distintos;
* que leer el registro y decidir de quién es cada cosa son **dos autoridades distintas**, y que
  ninguna de las dos es «ver el inventario»;
* que quien tiene una empresa concedida ve **esa**, y no la lista de sociedades del grupo;
* y que una instalación que venía con las tablas viejas se las encuentra donde ahora se buscan.

Con app y sesión: el estrechamiento lo hace la petición, y probarlo sin HTTP sería probar otra
cosa.
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


def _node():
    """El intérprete con el que se dibuja la pantalla, o None."""
    import shutil, subprocess                                       # noqa: PLC0415
    n = shutil.which('node')
    if not n:
        return None
    try:
        out = subprocess.run([n, '--version'], capture_output=True, text=True, timeout=20)
        return n if int((out.stdout or '').strip().lstrip('v').split('.')[0]) >= 16 else None
    except Exception:                                    # pragma: no cover - sin node
        return None


def _as(admin, username, perms):
    """Una sesión con EXACTAMENTE esos permisos, por un rol propio: los permisos en vigor se
    resuelven del rol, así que pegárselos a la cuenta no le da ninguno."""
    role = f'r-{username}'
    admin._custom_roles[role] = {
        'uid': role, 'name': role, 'description': '', 'permissions': list(perms),
        'enabled': True, 'created_at': '2026-09-05T00:00:00Z',
        'updated_at': '2026-09-05T00:00:00Z', 'updated_by': 'test'}
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash('pw-secret')}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': 'pw-secret'},
           follow_redirects=True)
    return c


@pytest.fixture()
def grupo(client):
    """Dos sociedades, un armario de una y una máquina de la otra — que es el caso entero: dos
    ámbitos, dos paquetes, un registro."""
    _login(client)
    it = client.post('/api/v1/orgs', json={'name': 'IT del grupo', 'short': 'IT'})
    b = client.post('/api/v1/orgs', json={'name': 'Filial B', 'short': 'FB'})
    it, b = it.get_json()['uid'], b.get_json()['uid']
    site = client.post('/api/v1/dcim/sites', json={'name': 'DC Norte'}).get_json()['uid']
    room = client.post('/api/v1/dcim/rooms',
                       json={'site_uid': site, 'name': 'Sala 1'}).get_json()['uid']
    rack = client.post('/api/v1/dcim/racks',
                       json={'room_uid': room, 'name': 'R1', 'u_height': 42}).get_json()['uid']
    host = client.post('/api/v1/hosts', json={'name': 'db03', 'address': '10.0.0.3'})
    host = (host.get_json() or {}).get('uid', '')
    client.post('/api/v1/orgs/owner', json={'scope': 'rack', 'uid': rack, 'org_uid': it})
    if host:
        client.post('/api/v1/orgs/owner', json={'scope': 'host', 'uid': host, 'org_uid': b})
    return {'it': it, 'b': b, 'site': site, 'room': room, 'rack': rack, 'host': host}


class TestSeFichaLoQueAlguienDeclara:
    """Y sólo eso. La tabla abarca ámbitos que viven en tablas que este paquete no conoce, así
    que lo válido es lo declarado — no una lista escrita en el core, que sería una que hay que
    editar cada vez que un paquete aprende a poseer algo."""

    def test_un_armario_del_inventario_y_una_maquina_del_registro(self, admin, client, grupo):
        """Dos paquetes distintos fichando en el mismo sitio: es la razón de todo el traslado."""
        dicho = admin._orgs_store.said()
        assert dicho[('rack', grupo['rack'])] == grupo['it']
        if grupo['host']:
            assert dicho[('host', grupo['host'])] == grupo['b']

    def test_y_un_ambito_que_nadie_declara_se_rechaza(self, client, grupo):
        """Una errata escribiría una fila que nada podrá volver a leer: no la ve ninguna
        pantalla, no la limpia ningún borrado, y sigue ahí."""
        r = client.post('/api/v1/orgs/owner',
                        json={'scope': 'sala_de_maquinas', 'uid': 'x', 'org_uid': grupo['it']})
        assert r.status_code == 400

    def test_y_una_empresa_que_no_existe_tampoco(self, client, grupo):
        r = client.post('/api/v1/orgs/owner',
                        json={'scope': 'rack', 'uid': grupo['rack'], 'org_uid': 'no-existe'})
        assert r.status_code == 404

    def test_y_dejar_de_decirlo_no_es_decir_que_no_es_de_nadie(self, client, grupo):
        """Vaciarlo devuelve a heredar, que es otro estado y el que alguien quiere cuando un
        armario deja de ser una excepción."""
        client.post('/api/v1/orgs/owner',
                    json={'scope': 'site', 'uid': grupo['site'], 'org_uid': grupo['b']})
        client.post('/api/v1/orgs/owner',
                    json={'scope': 'rack', 'uid': grupo['rack'], 'org_uid': ''})
        fila = client.get('/api/v1/dcim/rooms/%s/racks' % grupo['room']).get_json()
        racks = fila.get('racks') if isinstance(fila, dict) else None
        if racks:
            assert racks[0].get('org_uid') == grupo['b'], 'no ha vuelto a heredar de la sede'


class TestDosSociedadesNoSePuedenLlamarIgual:
    """Y lo que importa no es que no se pueda: es **cómo se dice que no se puede**.

    `org.name` lleva índice único, y un índice no contesta con palabras — contesta con un
    `IntegrityError`, que le llega a una persona como un HTTP 500 con una traza de Werkzeug
    encima de la pantalla. Salió así, tal cual, al teclear dos veces la misma empresa.
    """

    def test_repetir_el_nombre_se_contesta_con_palabras(self, client, grupo):
        r = client.post('/api/v1/orgs', json={'name': 'Filial B', 'short': 'FB2'})
        assert r.status_code == 409, 'un nombre repetido vuelve a reventar'
        assert 'Filial B' in (r.get_json() or {}).get('error', ''), 'no dice cuál'

    def test_y_da_igual_cómo_se_teclee(self, client, grupo):
        """«Filial B» y « filial b » son dos filas y una empresa: la segunda la crea quien la
        teclea otra vez sin mirar, y desde entonces la mitad de los armarios están fichados a un
        nombre que no sale en el desplegable que está mirando."""
        assert client.post('/api/v1/orgs',
                           json={'name': ' filial b ', 'short': 'FB3'}).status_code == 409

    def test_y_la_abreviatura_tambien_es_suya(self, client, grupo):
        """Dos con la misma abreviatura dan una chapa en un alzado que no dice de quién es el
        armario, que es para lo único que sirve una abreviatura."""
        r = client.post('/api/v1/orgs', json={'name': 'Otra distinta', 'short': 'FB'})
        assert r.status_code == 409
        assert 'FB' in (r.get_json() or {}).get('error', '')

    def test_y_sin_abreviatura_no_hay_empresa(self, client, grupo):
        """Es lo que se pinta en una chapa y en un alzado, donde el nombre legal de una sociedad
        no entra. Sin ella, esos sitios enseñan un hueco — y un hueco en el alzado de un armario
        compartido es justo la pregunta que el alzado venía a contestar."""
        assert client.post('/api/v1/orgs',
                           json={'name': 'Sin siglas', 'short': ''}).status_code == 400
        assert client.post('/api/v1/orgs', json={'name': 'Tampoco'}).status_code == 400
        assert client.put(f'/api/v1/orgs/{grupo["b"]}',
                          json={'short': '  '}).status_code == 400

    def test_pero_un_arreglo_de_otra_cosa_no_la_exige(self, client, grupo):
        """Un PUT que corrige la descripción no manda la abreviatura, y exigirla ahí sería pedir
        que se confirme un dato que quien escribe no está mirando."""
        assert client.put(f'/api/v1/orgs/{grupo["b"]}',
                          json={'description': 'La del norte'}).status_code == 200

    def test_y_renombrar_a_una_que_existe_tampoco(self, client, grupo):
        assert client.put(f'/api/v1/orgs/{grupo["it"]}',
                          json={'name': 'Filial B'}).status_code == 409

    def test_pero_guardarse_a_si_misma_no_es_repetirse(self, client, grupo):
        """El caso que rompe una comprobación escrita de prisa: corregir la descripción de una
        empresa manda su nombre otra vez, y el suyo propio lo tiene ella."""
        r = client.put(f'/api/v1/orgs/{grupo["b"]}',
                       json={'name': 'Filial B', 'short': 'FB', 'description': 'La del norte'})
        assert r.status_code == 200

    def test_y_dejarla_sin_nombre_se_dice_tambien(self, client, grupo):
        assert client.put(f'/api/v1/orgs/{grupo["b"]}',
                          json={'name': '   '}).status_code == 400


class TestLeerYDecidirSonDosAutoridades:

    def test_ver_el_inventario_no_abre_el_registro(self, admin, grupo):
        """Y no es un tecnicismo: el registro dice qué sociedades tiene el grupo, que es una
        lista que no todo el que monta armarios tiene por qué leer."""
        c = _as(admin, 'monta-racks', ['dcim_view', 'dcim_edit', 'orgs_all_view'])
        assert c.get('/api/v1/orgs').status_code == 403

    def test_pero_la_seccion_sigue_pudiendo_pintar_las_chapas(self, admin, grupo):
        """Sin los nombres no hay chapa que pintar ni desplegable con el que fichar un armario,
        así que la lectura corta de la sección va con `dcim_view`."""
        c = _as(admin, 'monta-racks-2', ['dcim_view', 'orgs_all_view'])
        r = c.get('/api/v1/dcim/orgs')
        assert r.status_code == 200
        assert {o['name'] for o in r.get_json()['orgs']} == {'IT del grupo', 'Filial B'}
        # …y nada más que los nombres: lo que cada una tiene fichado es del registro.
        assert 'said' not in r.get_json()['orgs'][0]

    def test_y_leer_no_es_escribir(self, admin, grupo):
        c = _as(admin, 'mirona', ['orgs_view', 'orgs_all_view'])
        assert c.get('/api/v1/orgs').status_code == 200
        assert c.post('/api/v1/orgs', json={'name': 'Nueva'}).status_code == 403
        assert c.put(f'/api/v1/orgs/{grupo["b"]}', json={'name': 'Otro'}).status_code == 403
        assert c.delete(f'/api/v1/orgs/{grupo["b"]}').status_code == 403
        assert c.post('/api/v1/orgs/owner',
                      json={'scope': 'rack', 'uid': grupo['rack'],
                            'org_uid': grupo['b']}).status_code == 403

    def test_y_ni_el_rol_de_editor_la_trae_de_serie(self, admin):
        """En un grupo esto decide qué se le factura a qué sociedad y quién puede ver qué."""
        perms = admin._get_role_permissions('editor')
        assert 'orgs_edit' not in perms
        assert 'orgs_view' in perms and 'orgs_all_view' in perms


class TestQuienTieneUnaEmpresaVeEsaEmpresa:

    def test_y_no_la_lista_de_sociedades_del_grupo(self, admin, grupo):
        """Enumerar las filiales a quien tiene concedida exactamente una es la fuga de siempre
        con otro nombre."""
        c = _as(admin, 'de-la-filial', ['orgs_view', f'org.{grupo["b"]}.view'])
        r = c.get('/api/v1/orgs')
        assert r.status_code == 200
        assert [o['uid'] for o in r.get_json()['orgs']] == [grupo['b']]

    def test_y_quien_no_tiene_ninguna_ve_una_lista_vacia_y_no_un_error(self, admin, grupo):
        """`None` y `set()` son respuestas distintas: a quien se le dio la sección y ninguna
        empresa le toca ver los contenedores con todo opaco, no un 403."""
        c = _as(admin, 'sin-empresa', ['orgs_view'])
        r = c.get('/api/v1/orgs')
        assert r.status_code == 200
        assert r.get_json()['orgs'] == []


class TestBorrarUnaEmpresaDejaLoSuyoSinFichar:

    def test_lo_suyo_sigue_estando_y_deja_de_ser_de_ella(self, admin, client, grupo):
        """Lo que era suyo no se borra: se queda sin fichar, que es donde empieza toda
        instalación. Y las filas que la nombraban se van con ella, o el resolvedor devuelve un
        uid que nada puede volver a buscar."""
        assert client.delete(f'/api/v1/orgs/{grupo["it"]}').status_code == 200
        dicho = admin._orgs_store.said()
        assert ('rack', grupo['rack']) not in dicho
        racks = client.get(f'/api/v1/dcim/rooms/{grupo["room"]}/racks').get_json()
        assert racks is not None, 'el armario se fue con la empresa'

    def test_y_queda_apuntado_en_la_auditoria(self, client, grupo):
        """Deja de estar fichado lo que cuelga de ella, que es un cambio a lo que enseñan doce
        pantallas y que ninguna anuncia."""
        client.delete(f'/api/v1/orgs/{grupo["b"]}')
        eventos = _eventos(client)
        assert 'org_deleted' in eventos

    def test_y_fichar_algo_tambien(self, client, grupo):
        """«¿Desde cuándo eso era nuestro?» es la pregunta que se hace meses después."""
        client.post('/api/v1/orgs/owner',
                    json={'scope': 'site', 'uid': grupo['site'], 'org_uid': grupo['it']})
        eventos = _eventos(client)
        assert 'org_owner_set' in eventos


class TestLoQueVeniaDelInventarioSeAdopta:
    """Una instalación que ya tenía empresas las tiene en `dc_org`/`dc_owner`. Copiadas y no
    renombradas: una copia a una tabla VACÍA es idempotente, vale igual en los tres motores, y
    deja las filas viejas donde están — que es lo que hace esto recuperable."""

    def test_las_filas_viejas_aparecen_en_las_nuevas(self, admin):
        from lib.core.orgs.store import OrgsStore
        db = admin._db_connector
        _tablas_viejas(db)
        db.execute("INSERT INTO dc_org (uid, name, short, description, created_at, "
                   "updated_at, updated_by) VALUES ('o-vieja', 'De antes', 'DA', '', "
                   "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'quien-fuera')")
        db.execute("INSERT INTO dc_owner (scope, uid, org_uid, set_at, set_by) "
                   "VALUES ('rack', 'r-viejo', 'o-vieja', '2026-01-01T00:00:00Z', 'x')")
        db.execute("DELETE FROM org")
        db.execute("DELETE FROM org_owner")
        db.commit()

        store = OrgsStore(db)
        assert [o['name'] for o in store.orgs.list()] == ['De antes']
        assert store.said() == {('rack', 'r-viejo'): 'o-vieja'}

    def test_y_no_pisa_lo_que_ya_hubiera(self, admin, client):
        """Idempotente a propósito: se arranca más de una vez, y un panel que aún no ha
        reiniciado sigue escribiendo en la tabla vieja mientras tanto."""
        from lib.core.orgs.store import OrgsStore
        _login(client)
        _tablas_viejas(admin._db_connector)
        uid = client.post('/api/v1/orgs',
                          json={'name': 'La de ahora', 'short': 'LDA'}).get_json()['uid']
        db = admin._db_connector
        db.execute("INSERT INTO dc_org (uid, name, short, description, created_at, "
                   "updated_at, updated_by) VALUES ('o-vieja2', 'De antes', '', '', '', '', '')")
        db.commit()
        store = OrgsStore(db)
        nombres = {o['name'] for o in store.orgs.list()}
        assert nombres == {'La de ahora'}, 'la adopción ha pisado lo que ya había'
        assert store.orgs.get(uid) is not None


def _eventos(client):
    """Los nombres de lo ultimo apuntado. La ruta contesta una lista pelada, y leerla como si
    fuese un sobre con `entries` dentro es como se escribio esto la primera vez."""
    filas = client.get('/api/v1/audit?limit=50').get_json() or []
    if isinstance(filas, dict):
        filas = filas.get('entries') or filas.get('logs') or []
    return [str(e.get('event') or e.get('action') or '') for e in filas]


def _tablas_viejas(db):
    """Las dos tablas que este panel ya no declara, puestas a mano.

    Es lo que hace honesta la prueba: si las siguiese creando alguien, lo que se estaria
    comprobando es que dos tablas vivas se copian entre si, no que una instalacion vieja se
    encuentra sus empresas donde ahora se buscan.
    """
    db.execute("CREATE TABLE IF NOT EXISTS dc_org (uid TEXT PRIMARY KEY, name TEXT, "
               "short TEXT, description TEXT, created_at TEXT, updated_at TEXT, "
               "updated_by TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS dc_owner (scope TEXT, uid TEXT, org_uid TEXT, "
               "set_at TEXT, set_by TEXT)")
    db.commit()

class TestLaListaDiceDeDondePuedeVenirUna:
    """La columna guarda `freshservice` y la pantalla enseña un nombre. Ese nombre lo declara
    quien trae las empresas: **ningún texto del core nombra a un proveedor**."""

    def test_los_origenes_declarados_viajan_con_la_lista(self, client, grupo):
        d = client.get('/api/v1/orgs').get_json()
        ids = [f['id'] for f in d.get('sources', [])]
        assert 'freshservice' in ids, 'la pantalla no tiene con qué poner un nombre'
        fs = [f for f in d['sources'] if f['id'] == 'freshservice'][0]
        assert fs['label_key'] and fs['icon']

    def test_y_lo_declara_el_paquete_que_las_trae(self):
        """Aquí se comprueba de dónde sale: si esto se escribiera en el core, quitar el
        proveedor dejaría un nombre suyo escrito en una pantalla que ya no lo usa."""
        from lib.core.orgs import scopes as org_scopes
        assert org_scopes.sources()['freshservice']['package'] == 'freshservice'


class TestLoQueMantieneUnOrigenNoSeCorrigeAqui:
    """La siguiente importación lo pisaría, y un campo que se puede escribir y se revierte solo
    es peor que uno que no se puede: el trabajo se pierde sin que nada lo diga, y al día
    siguiente. La pantalla lo enseña en solo lectura; esto es la guarda, porque una pantalla no
    lo es."""

    def _importada(self, admin, client):
        """Una empresa como la deja una importación: con su origen puesto."""
        uid = client.post('/api/v1/orgs',
                          json={'name': 'Traída', 'short': 'TR'}).get_json()['uid']
        admin._orgs_store.orgs.update(uid, {'source': 'freshservice', 'external_id': '7'})
        return uid

    def test_no_se_le_cambia_el_nombre(self, admin, client, grupo):
        uid = self._importada(admin, client)
        r = client.put(f'/api/v1/orgs/{uid}', json={'name': 'A mano'})
        assert r.status_code == 409
        assert admin._orgs_store.orgs.get(uid)['name'] == 'Traída'

    def test_ni_la_abreviatura_ni_la_descripcion(self, admin, client, grupo):
        uid = self._importada(admin, client)
        assert client.put(f'/api/v1/orgs/{uid}', json={'short': 'XX'}).status_code == 409
        assert client.put(f'/api/v1/orgs/{uid}',
                          json={'description': 'mía'}).status_code == 409

    def test_y_el_aviso_dice_quien_la_mantiene(self, admin, client, grupo):
        """Una negativa que no dice de quién es la fila manda a mirar dónde no es."""
        uid = self._importada(admin, client)
        d = client.put(f'/api/v1/orgs/{uid}', json={'name': 'A mano'}).get_json()
        assert 'freshservice' in d['error']

    def test_pero_una_de_esta_casa_se_corrige_como_siempre(self, admin, client, grupo):
        """La guarda es para lo que mantiene otro, no para todo."""
        assert client.put(f'/api/v1/orgs/{grupo["b"]}',
                          json={'description': 'mía'}).status_code == 200


class TestSoltarUnaEmpresaDeSuOrigen:
    """Hace falta una salida: sin ella, quitar el proveedor deja filas que nadie mantiene y que
    nadie puede corregir — sólo se podrían borrar, y de una sociedad cuelgan armarios."""

    def test_vuelve_a_ser_de_esta_casa(self, admin, client, grupo):
        uid = client.post('/api/v1/orgs',
                          json={'name': 'Traída', 'short': 'TR'}).get_json()['uid']
        admin._orgs_store.orgs.update(uid, {'source': 'freshservice', 'external_id': '7'})
        assert client.delete(f'/api/v1/orgs/{uid}/source').status_code == 200
        fila = admin._orgs_store.orgs.get(uid)
        assert fila['source'] == '' and fila['external_id'] == ''
        # Y se vuelve a poder escribir, que es para lo que se suelta.
        assert client.put(f'/api/v1/orgs/{uid}', json={'name': 'A mano'}).status_code == 200

    def test_y_no_se_lleva_por_delante_lo_que_tiene_fichado(self, admin, client, grupo):
        """Soltarla del origen no es borrarla: los armarios que son suyos siguen siendo suyos."""
        admin._orgs_store.orgs.update(grupo['it'], {'source': 'freshservice',
                                                    'external_id': '9'})
        client.delete(f'/api/v1/orgs/{grupo["it"]}/source')
        assert admin._orgs_store.said().get(('rack', grupo['rack'])) == grupo['it']

    def test_y_queda_apuntado(self, admin, client, grupo):
        """«¿Por qué esta ya no se actualiza?» se pregunta semanas después."""
        admin._orgs_store.orgs.update(grupo['b'], {'source': 'freshservice',
                                                   'external_id': '9'})
        client.delete(f'/api/v1/orgs/{grupo["b"]}/source')
        assert 'org_unlinked' in _eventos(client)

    def test_y_hace_falta_poder_escribir_para_soltarla(self, admin, grupo):
        c = _as(admin, 'mirona-suelta', ['orgs_view', 'orgs_all_view'])
        assert c.delete(f'/api/v1/orgs/{grupo["b"]}/source').status_code == 403


class TestElBotonDeImportarViveEnEmpresas:
    """Estaba en la tarjeta de Freshservice, en Configuración → Fuentes externas. Pedido desde
    la pantalla: traer las empresas es un acto **sobre la lista de empresas**, y bajar a
    Configuración para hacerlo es ir a buscar un botón a la pantalla de otra cosa.

    Y con una condición que es la mitad del arreglo: **sólo si el conector está puesto**. Un
    botón que promete traer cuarenta empresas y falla en la primera llamada por una clave que
    nadie ha escrito es peor que no tenerlo — el error que da es de autenticación, y eso manda a
    mirar la credencial en vez del campo vacío.
    """

    def test_sin_conector_no_hay_boton(self, client, admin):
        _login(client)
        admin._write_config({'freshservice': {'domain': '', 'api_key': ''}})
        assert client.get('/api/v1/orgs').get_json()['actions'] == []

    def test_con_el_conector_puesto_si(self, client, admin):
        _login(client)
        admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                              'api_key': 'k'}})
        [acc] = client.get('/api/v1/orgs').get_json()['actions']
        assert acc['fn'] == 'freshserviceImport'
        assert acc['perm'] == 'orgs_edit', 'la acción viajaría sin su permiso'

    def test_con_el_dominio_pero_sin_la_clave_tampoco(self, client, admin):
        """Medio configurado no es configurado: con el dominio solo, la importación llega a la
        primera llamada y muere con un error de autenticación."""
        _login(client)
        admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                              'api_key': ''}})
        assert client.get('/api/v1/orgs').get_json()['actions'] == []

    def test_y_la_respuesta_no_se_queda_cacheada(self, client, admin):
        """La configuración se edita desde el propio panel. Una respuesta guardada de por vida
        dejaría el botón escondido después de poner la clave, hasta reiniciar."""
        _login(client)
        admin._write_config({'freshservice': {'domain': '', 'api_key': ''}})
        assert client.get('/api/v1/orgs').get_json()['actions'] == []
        admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                              'api_key': 'k'}})
        assert len(client.get('/api/v1/orgs').get_json()['actions']) == 1

    def test_cuelga_del_boton_de_anadir_y_no_al_lado(self, client, admin):
        """Propuesto desde la pantalla, y es mejor: traer de fuera es otra manera de que
        aparezca una empresa, no una cosa distinta. Con la pestaña, el día que haya tres
        fuentes la barra sigue teniendo dos botones en vez de cinco.

        Dibujado de verdad en node: que el desplegable esté o no está en el HTML, no en el
        fuente.
        """
        import json as _json                                        # noqa: PLC0415
        from tests.helpers import node_run, panel_bundle            # noqa: PLC0415
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        _login(client)
        admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                              'api_key': 'k'}})
        acciones = client.get('/api/v1/orgs').get_json()['actions']
        out = node_run(panel_bundle(client), """
            __out = {};
            currentUser = {permissions: ['orgs_edit']};
            _orgsData = {orgs: [], scopes: [], sources: [], actions: %s, loaded: true};
            __out.con = _orgsNewHtml(true);
            _orgsData.actions = [];
            __out.sin = _orgsNewHtml(true);
            __out.sinPermiso = _orgsNewHtml(false);
        """ % _json.dumps(acciones))
        assert 'dropdown-toggle-split' in out['con'], 'la pestaña no está'
        assert 'freshserviceImport()' in out['con']
        # Y lo que la pestaña acompaña sigue ahí: es un botón partido, no una pestaña suelta.
        # Sin esto, quitar `${nuevo}` del grupo dejaba la prueba en verde y la pantalla sin
        # forma de añadir una empresa a mano — se vio mutándolo.
        assert 'orgModalOpen' in out['con'], 'la pestaña se llevó el botón de añadir'
        # Un desplegable vacío es peor que ninguno.
        assert 'dropdown' not in out['sin'], 'la pestaña sale sin nada que colgar'
        assert 'orgModalOpen' in out['sin'], 'y el botón de añadir se ha perdido con ella'
        assert out['sinPermiso'] == ''

    def test_el_core_no_nombra_a_ningun_proveedor(self, client, admin):
        """La misma regla que siguen los ámbitos y los orígenes: el texto, el icono y la función
        los pone quien trae las empresas. Si el core escribiera «Freshservice» en algún sitio,
        quitar el paquete dejaría un botón que no hace nada."""
        raiz = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        for rel in (os.path.join('lib', 'core', 'orgs', 'web', '_ui.html'),
                    os.path.join('lib', 'core', 'orgs', 'routes.py'),
                    os.path.join('lib', 'core', 'orgs', 'scopes.py')):
            texto = io.open(os.path.join(raiz, rel), encoding='utf-8').read()
            # El comentario de `scopes.py` usa el ejemplo real, que es documentación y no código.
            codigo = '\n'.join(l for l in texto.split('\n')
                               if not l.lstrip().startswith(('#', '*', '/*', '//')))
            assert 'freshservice' not in codigo.lower(), rel

    def test_una_accion_sin_funcion_no_llega_a_la_pantalla(self, client, admin, monkeypatch):
        """Un descriptor a medio escribir dibujaría un botón cuyo `onclick` es `()`: un error
        de JavaScript al pulsarlo, que es peor que no ofrecerlo."""
        from lib.core.orgs import scopes as org_scopes              # noqa: PLC0415

        def _falso(_clave, **_kw):
            return [('malo', [{'id': 'sin-fn', 'label_key': 'x'},
                              {'id': 'buena', 'fn': 'algo'}])]

        monkeypatch.setattr('lib.discovery.scan', _falso)
        assert [a['id'] for a in org_scopes.actions(admin)] == ['buena']

    def test_una_accion_cuyo_ready_revienta_no_tumba_la_pantalla(self, client, admin,
                                                                monkeypatch):
        """Es la pantalla de Empresas: un fallo en una línea de un proveedor no puede dejarla
        sin cargar."""
        from lib.core.orgs import scopes as org_scopes              # noqa: PLC0415

        def _explota(_wa):
            raise RuntimeError('boom')

        def _falso(_clave, **_kw):
            return [('malo', [{'id': 'x', 'fn': 'nada', 'ready': _explota}])]

        monkeypatch.setattr('lib.discovery.scan', _falso)
        _login(client)
        assert org_scopes.actions(admin) == []
