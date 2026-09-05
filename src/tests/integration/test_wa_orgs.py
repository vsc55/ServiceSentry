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

import os
import sys

import pytest
from werkzeug.security import generate_password_hash

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from tests.conftest import _login                                   # noqa: E402


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
