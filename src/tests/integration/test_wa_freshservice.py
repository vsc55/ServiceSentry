#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Traer las empresas de Freshservice: las tres rutas, con la red de mentira.

De mentira **la red y nada más**: la aplicación es la de verdad, el almacén es el de verdad y las
filas que quedan se leen de la base. Lo que se sustituye es el cliente HTTP, porque una prueba que
llama a Freshservice de verdad es una que falla el día que se cae, el día que caduca una clave y
el día que alguien la ejecuta en un tren.

Lo que se comprueba es lo que distingue una importación de un desastre:

* que **mirar y aplicar sean dos cosas** — y que aplicar vuelva a pedir la lista, porque entre
  mirar y aceptar pasa un rato;
* que se pueda **volver a importar** sin duplicar nada;
* que lo que **tecleó una persona** se adopte en vez de copiarse;
* que lo que ya no está en el origen **no se borre**;
* que cada fallo de la API se cuente con **su** nombre — la clave, su permiso, el dominio y el
  límite por minuto se arreglan de cuatro maneras distintas;
* y que todo esto esté detrás de `orgs_edit`, que es la bandera que decide de quién es cada cosa.
"""

from __future__ import annotations

import os
import sys

import pytest
from werkzeug.security import generate_password_hash

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.providers.freshservice import client as fs_client                # noqa: E402
from lib.providers.freshservice import plan as fs_plan                    # noqa: E402
from tests.conftest import _login                                         # noqa: E402


def _as(admin, username, perms):
    """Una sesión con EXACTAMENTE esos permisos, por un rol propio."""
    role = f'r-{username}'
    admin._custom_roles[role] = {
        'uid': role, 'name': role, 'description': '', 'permissions': list(perms),
        'enabled': True, 'created_at': '2026-09-06T00:00:00Z',
        'updated_at': '2026-09-06T00:00:00Z', 'updated_by': 'test'}
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash('pw-secret')}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': 'pw-secret'},
           follow_redirects=True)
    return c


@pytest.fixture()
def freshservice(admin, client, monkeypatch):
    """Freshservice configurado y contestando lo que le digamos.

    Devuelve una caja con `set(...)` para decidir qué contesta la próxima llamada, y `calls`
    para contar cuántas ha habido — que es lo que prueba que aplicar vuelve a preguntar.
    """
    _login(client)
    admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                          'api_key': 'k-secreta'}})
    caja = {'deps': [], 'calls': 0, 'raise': None}

    def _departments(domain, api_key):
        caja['calls'] += 1
        caja['seen'] = (domain, api_key)
        if caja['raise'] is not None:
            raise caja['raise']
        return list(caja['deps'])

    def _probe(domain, api_key):
        if caja['raise'] is not None:
            raise caja['raise']
        return {'host': fs_client.host_of(domain), 'rate': caja.get('rate', {})}

    def _status(domain, api_key):
        if caja.get('status_raise') is not None:
            raise caja['status_raise']
        return caja.get('status', {'available': False, 'pages': [], 'incidents': [],
                                   'components': [], 'error_key': ''})

    monkeypatch.setattr(
        'lib.providers.freshservice.routes.fs_client.departments', _departments)
    monkeypatch.setattr('lib.providers.freshservice.routes.fs_client.probe', _probe)
    monkeypatch.setattr(
        'lib.providers.freshservice.routes.fs_client.status_summary', _status)
    caja['set'] = lambda deps: caja.__setitem__('deps', deps)
    return caja


def _dep(i, name, desc=''):
    return {'id': i, 'name': name, 'description': desc}


class TestProbarLaConexionEsUnaPreguntaYNoUnActo:

    def test_contesta_con_el_dominio_al_que_ha_llegado(self, client, freshservice):
        r = client.post('/api/v1/providers/freshservice/test')
        assert r.status_code == 200
        assert r.get_json()['host'] == 'lacasa.freshservice.com'

    def test_y_no_crea_ni_una_empresa(self, admin, client, freshservice):
        """Con un solo botón, quien sólo quería saber si la clave vale se encuentra con cuarenta
        sociedades creadas."""
        freshservice['set']([_dep(1, 'Filial B')])
        client.post('/api/v1/providers/freshservice/test')
        assert admin._orgs_store.orgs.list() == []

    def test_y_sin_dominio_o_sin_clave_lo_dice_en_vez_de_intentarlo(self, admin, client,
                                                                   freshservice):
        admin._write_config({'freshservice': {'domain': '', 'api_key': ''}})
        r = client.post('/api/v1/providers/freshservice/test')
        assert r.status_code == 400


class TestLaPruebaTambienMiraSuPaginaDeEstado:
    """La mitad de las veces que alguien viene a probar la clave es porque algo va raro, y saber
    que esa casa tiene un incidente abierto ahorra la tarde. Es un extra, y por eso va aparte."""

    def test_lo_que_lee_sale_en_la_respuesta(self, client, freshservice):
        freshservice['status'] = {'available': True, 'error_key': '',
                                  'pages': [{'name': 'Estado', 'status': ''}],
                                  'incidents': [{'name': 'Correo caído', 'status': 'investigating'}],
                                  'components': [{'name': 'Portal', 'status': 'operational'}]}
        d = client.post('/api/v1/providers/freshservice/test').get_json()
        assert d['ok'] is True
        assert d['status']['incidents'][0]['name'] == 'Correo caído'
        assert d['status']['components'][0]['status'] == 'operational'

    def test_y_el_cupo_que_queda_tambien(self, client, freshservice):
        """«Te quedan 12 de 200» es media respuesta cuando una importación va a trompicones."""
        freshservice['rate'] = {'total': 200, 'remaining': 12, 'used': 1, 'retry_after': 0}
        d = client.post('/api/v1/providers/freshservice/test').get_json()
        assert d['rate']['remaining'] == 12 and d['rate']['total'] == 200

    def test_pero_que_no_se_pueda_leer_no_estropea_la_prueba(self, client, freshservice):
        """No está en todos los planes y la clave puede no alcanzarla. Una clave perfecta dando
        error por un módulo que esa casa no ha contratado sería mandar a mirar donde no es."""
        freshservice['status'] = {'available': False, 'pages': [], 'incidents': [],
                                  'components': [], 'error_key': 'fs_err_forbidden'}
        r = client.post('/api/v1/providers/freshservice/test')
        assert r.status_code == 200
        d = r.get_json()
        assert d['ok'] is True
        assert d['status']['available'] is False
        # Y lo dice con palabras, no con la clave en crudo.
        assert d['status']['error'] and d['status']['error'] != 'fs_err_forbidden'

    def test_y_si_revienta_del_todo_tampoco(self, client, freshservice):
        """Lo que se estaba probando es la clave, y la clave vale."""
        freshservice['status_raise'] = fs_client.FreshserviceError('fs_err_server', 'boom')
        r = client.post('/api/v1/providers/freshservice/test')
        assert r.status_code == 200, 'un extra ha tumbado la prueba de la clave'
        assert r.get_json()['status']['available'] is False


class TestMirarYAplicarSonDosCosas:

    def test_la_vista_previa_no_escribe_nada(self, admin, client, freshservice):
        """Una importación que crea y corrige en silencio es una que, el día que el filtro esté
        mal, deja media docena de sociedades duplicadas y ninguna forma de saber cuál era la
        buena."""
        freshservice['set']([_dep(1, 'Filial B'), _dep(2, 'Montarto Food')])
        r = client.get('/api/v1/providers/freshservice/preview')
        assert r.status_code == 200
        d = r.get_json()
        assert d['counts'] == {'create': 2, 'update': 0, 'adopt': 0, 'same': 0}
        assert admin._orgs_store.orgs.list() == [], 'mirar ha escrito'

    def test_y_aplicar_escribe_lo_que_se_enseñó(self, admin, client, freshservice):
        freshservice['set']([_dep(1, 'Filial B', 'la del norte')])
        r = client.post('/api/v1/providers/freshservice/import')
        assert r.status_code == 200 and r.get_json()['created'] == 1
        fila = admin._orgs_store.orgs.list()[0]
        assert fila['name'] == 'Filial B' and fila['description'] == 'la del norte'
        assert fila['source'] == fs_plan.SOURCE and fila['external_id'] == '1'
        assert fila['short'], 'sin abreviatura, que aquí es obligatoria'

    def test_y_aplicar_vuelve_a_preguntar(self, client, freshservice):
        """Entre mirar y aceptar pasa un rato, y lo que se escribe tiene que ser lo que hay
        ahora — no lo que había cuando se abrió el cuadro."""
        freshservice['set']([_dep(1, 'Filial B')])
        client.get('/api/v1/providers/freshservice/preview')
        antes = freshservice['calls']
        client.post('/api/v1/providers/freshservice/import')
        assert freshservice['calls'] == antes + 1


class TestVolverAImportarNoDuplica:

    def test_la_segunda_vez_no_hace_nada(self, admin, client, freshservice):
        freshservice['set']([_dep(1, 'Filial B', 'la del norte')])
        client.post('/api/v1/providers/freshservice/import')
        r = client.post('/api/v1/providers/freshservice/import')
        assert r.get_json() == {'created': 0, 'updated': 0, 'adopted': 0,
                                'failed': [], 'orphans': 0}
        assert len(admin._orgs_store.orgs.list()) == 1

    def test_y_renombrarla_alli_la_corrige_aqui_en_vez_de_crear_otra(self, admin, client,
                                                                    freshservice):
        freshservice['set']([_dep(1, 'Filial B')])
        client.post('/api/v1/providers/freshservice/import')
        freshservice['set']([_dep(1, 'Filial B del Norte')])
        r = client.post('/api/v1/providers/freshservice/import')
        assert r.get_json()['updated'] == 1
        filas = admin._orgs_store.orgs.list()
        assert len(filas) == 1 and filas[0]['name'] == 'Filial B del Norte'

    def test_y_la_que_ya_estaba_tecleada_se_adopta(self, admin, client, freshservice):
        """El caso real: la lista se tecleó a mano antes de conectar esto. No se duplica — se
        ata la que ya estaba— y desde ese momento la mantiene el origen, así que sus datos pasan
        a ser los de allí."""
        uid = client.post('/api/v1/orgs',
                          json={'name': 'Filial B', 'short': 'FB',
                                'description': 'escrito aquí'}).get_json()['uid']
        freshservice['set']([_dep(7, 'Filial B', 'lo que dice Freshservice')])
        r = client.post('/api/v1/providers/freshservice/import')
        assert r.get_json()['adopted'] == 1
        filas = admin._orgs_store.orgs.list()
        assert len(filas) == 1 and filas[0]['uid'] == uid, 'ha creado una copia'
        assert filas[0]['external_id'] == '7'
        assert filas[0]['description'] == 'lo que dice Freshservice'


class TestLoQueYaNoEstaNoSeBorra:

    def test_se_cuenta_y_se_queda(self, admin, client, freshservice):
        """De una sociedad cuelgan armarios y máquinas fichados aquí, y un departamento
        desaparece del origen tanto por una reorganización como por un filtro mal puesto."""
        freshservice['set']([_dep(1, 'La que se fue')])
        client.post('/api/v1/providers/freshservice/import')
        freshservice['set']([])
        r = client.post('/api/v1/providers/freshservice/import')
        assert r.get_json()['orphans'] == 1
        assert len(admin._orgs_store.orgs.list()) == 1, 'se ha borrado una empresa'

    def test_y_la_vista_previa_la_nombra(self, client, freshservice):
        """Contar «1» no sirve para decidir: lo que alguien mira es CUÁL."""
        freshservice['set']([_dep(1, 'La que se fue')])
        client.post('/api/v1/providers/freshservice/import')
        freshservice['set']([])
        d = client.get('/api/v1/providers/freshservice/preview').get_json()
        assert [o['name'] for o in d['orphans']] == ['La que se fue']


class TestCadaFalloSeCuentaConSuNombre:
    """La clave, su permiso, el dominio y el límite por minuto se arreglan de cuatro maneras
    distintas, y dichos todos «error» mandan a mirar el que no es."""

    def test_cada_uno_dice_una_cosa_distinta(self, client, freshservice):
        """En palabras y no en claves, y **cuatro** frases distintas: si dos coincidieran, dos
        arreglos distintos se leerían igual. Sin mirar el texto en sí, que depende del idioma de
        quien esté mirando."""
        dichos = {}
        for clave in ('fs_err_auth', 'fs_err_forbidden', 'fs_err_domain', 'fs_err_rate'):
            freshservice['raise'] = fs_client.FreshserviceError(clave, 'detalle')
            r = client.get('/api/v1/providers/freshservice/preview')
            assert r.status_code == 502, clave
            dichos[clave] = r.get_json()['error']
            assert dichos[clave] != clave, 'sale la clave en crudo, sin traducir'
        assert len(set(dichos.values())) == 4, dichos

    def test_y_el_detalle_viaja_aparte_del_aviso(self, client, freshservice):
        """El «HTTP 429» de turno vale para quien mira la consola y estorba en un aviso."""
        freshservice['raise'] = fs_client.FreshserviceError('fs_err_http', 'HTTP 500: boom')
        d = client.get('/api/v1/providers/freshservice/preview').get_json()
        assert d['detail'] == 'HTTP 500: boom'
        assert 'boom' not in d['error']

    def test_y_no_escribe_nada_cuando_la_llamada_falla(self, admin, client, freshservice):
        freshservice['raise'] = fs_client.FreshserviceError('fs_err_rate', '')
        client.post('/api/v1/providers/freshservice/import')
        assert admin._orgs_store.orgs.list() == []


class TestTraerEmpresasEsDecidirDeQuienEsCadaCosa:

    def test_las_tres_rutas_piden_orgs_edit(self, admin, freshservice):
        """Crea sociedades y corrige nombres que salen en las chapas de cuarenta armarios."""
        c = _as(admin, 'mirona-fs', ['orgs_view', 'orgs_all_view', 'config_edit'])
        assert c.post('/api/v1/providers/freshservice/test').status_code == 403
        assert c.get('/api/v1/providers/freshservice/preview').status_code == 403
        assert c.post('/api/v1/providers/freshservice/import').status_code == 403

    def test_y_la_importacion_queda_apuntada(self, client, freshservice):
        """«¿Desde cuándo se llama así?» se pregunta meses después, y la respuesta es que lo
        trajo una importación tal día."""
        freshservice['set']([_dep(1, 'Filial B')])
        client.post('/api/v1/providers/freshservice/import')
        filas = client.get('/api/v1/audit?limit=50').get_json() or []
        if isinstance(filas, dict):
            filas = filas.get('entries') or filas.get('logs') or []
        assert 'freshservice_import' in [str(e.get('event') or e.get('action') or '')
                                         for e in filas]


class TestUnDominioPropioSeExplicaEnVezDeFallar:
    """Su API «works only via Freshservice domains and not via custom CNAMEs», así que el FQDN
    con el que la casa entra a su portal **no vale aquí**. Es un fallo de los que se investigan
    por el lado que no es: el dominio resuelve, contesta, y lo que contesta no es Freshservice."""

    def test_se_dice_antes_de_llamar_a_nadie(self, admin, client, freshservice, monkeypatch):
        """Y sin gastar una llamada: se sabe mirando el nombre."""
        admin._write_config({'freshservice': {'api_key': 'k',
                                              'domain': 'soporte.lacasa.example'}})
        # Con el cliente de verdad, que es quien lo comprueba.
        monkeypatch.undo()
        r = client.post('/api/v1/providers/freshservice/test')
        assert r.status_code == 502
        assert 'freshservice.com' in r.get_json()['error']

    def test_y_el_mensaje_dice_cual_se_tecleó(self, admin, client, freshservice, monkeypatch):
        """El texto lleva un hueco para el dominio, y traducir la clave a secas dejaba un «{}»
        literal en pantalla — que parece un fallo del panel, no una explicación. Reportado desde
        la pantalla."""
        admin._write_config({'freshservice': {'api_key': 'k',
                                              'domain': 'soporte.lacasa.example'}})
        monkeypatch.undo()
        d = client.post('/api/v1/providers/freshservice/test').get_json()
        assert '{}' not in d['error'], 'el hueco del mensaje se ha quedado sin rellenar'
        assert 'soporte.lacasa.example' in d['error']


class TestElDominioSeTecleaDeSeisManeras:
    """Y las seis llevan al mismo sitio: quien lo escribe no tiene por qué saber cuál quiere el
    programa."""

    @pytest.mark.parametrize('escrito', [
        'lacasa.freshservice.com', 'https://lacasa.freshservice.com',
        'https://lacasa.freshservice.com/', 'http://lacasa.freshservice.com',
        ' lacasa.freshservice.com ', 'lacasa',
    ])
    def test_todas_dan_el_mismo_host(self, escrito):
        assert fs_client.host_of(escrito) == 'lacasa.freshservice.com'

    def test_y_sin_nada_no_se_inventa_uno(self):
        assert fs_client.host_of('') == ''


class TestLaHoraDeLaFilaEsLaDeAqui:
    """Su documentación dice que sus marcas de tiempo van en UTC como `YYYY-MM-DDTHH:MM:SSZ`,
    que es la misma forma que escribe este panel: se parecen tanto que copiarlas no daría ningún
    error, sólo una columna «modificado» que unas veces contesta cuándo se tocó aquí y otras
    cuándo se tocó allí."""

    def test_importar_pone_la_hora_de_este_panel(self, admin, client, freshservice):
        freshservice['set']([{'id': 1, 'name': 'Filial B', 'description': '',
                              'created_at': '2016-02-13T23:27:49Z',
                              'updated_at': '2016-02-13T23:27:49Z'}])
        client.post('/api/v1/providers/freshservice/import')
        fila = admin._orgs_store.orgs.list()[0]
        assert not fila['created_at'].startswith('2016'), 'se ha traído la fecha de Freshservice'
        assert fila['updated_at'] and fila['updated_at'].endswith('Z')
        assert fila['updated_by'] == 'admin', 'quien importó no queda apuntado'


class TestSeEligeQueEmpresasSeTraen:
    """Cincuenta y nueve departamentos no son cincuenta y nueve empresas de esta casa."""

    def test_solo_se_crean_las_marcadas(self, admin, client, freshservice):
        freshservice['set']([_dep(1, 'Una'), _dep(2, 'Otra'), _dep(3, 'Tercera')])
        r = client.post('/api/v1/providers/freshservice/import',
                        json={'pick': ['1', '3']})
        assert r.get_json()['created'] == 2
        assert {o['name'] for o in admin._orgs_store.orgs.list()} == {'Una', 'Tercera'}

    def test_y_sin_lista_se_siguen_trayendo_todas(self, admin, client, freshservice):
        """Una llamada que no manda la selección es la de antes de que esto se pudiera elegir."""
        freshservice['set']([_dep(1, 'Una'), _dep(2, 'Otra')])
        client.post('/api/v1/providers/freshservice/import')
        assert len(admin._orgs_store.orgs.list()) == 2

    def test_y_la_vista_previa_manda_las_de_aqui_para_poder_emparejar(self, client,
                                                                     freshservice):
        """Sin ellas no hay con qué emparejar a mano: el desplegable de cada fila sale de aquí."""
        client.post('/api/v1/orgs', json={'name': 'Amixalan', 'short': 'AMX'})
        freshservice['set']([_dep(7, 'Amixalan Energy Supplies, S.L.')])
        d = client.get('/api/v1/providers/freshservice/preview').get_json()
        assert [o['name'] for o in d['orgs']] == ['Amixalan']
        # Sólo lo justo para elegir en un desplegable: el resto de la fila no pinta nada aquí.
        assert set(d['orgs'][0]) == {'uid', 'name', 'short', 'source', 'external_id'}


class TestEmparejarAManoConUnaEmpresaDeAqui:

    def test_ata_la_de_alli_a_la_que_se_diga(self, admin, client, freshservice):
        uid = client.post('/api/v1/orgs',
                          json={'name': 'Amixalan', 'short': 'AMX'}).get_json()['uid']
        freshservice['set']([_dep(7, 'Amixalan Energy Supplies, S.L.')])
        r = client.post('/api/v1/providers/freshservice/import',
                        json={'pick': ['7'], 'link': {'7': uid}})
        assert r.get_json() == {'created': 0, 'updated': 0, 'adopted': 1,
                                'failed': [], 'orphans': 0}
        filas = admin._orgs_store.orgs.list()
        assert len(filas) == 1, 'ha creado una copia en vez de atarla'
        assert filas[0]['uid'] == uid and filas[0]['external_id'] == '7'
        # Y sus datos son los de allí: atarla es decir «estas dos son la misma», y a partir de
        # ahí la mantiene el origen. Respetar el nombre de aquí sólo retrasaría el cambio a la
        # siguiente importación, que es cuando nadie lo está mirando.
        assert filas[0]['name'] == 'Amixalan Energy Supplies, S.L.'
        assert filas[0]['short'], 'se ha quedado sin abreviatura, que aquí es obligatoria'

    def test_y_volver_a_importar_la_reconoce_por_el_atado(self, admin, client, freshservice):
        """Que es para lo que sirve atarla: la segunda vez ya no es una nueva."""
        uid = client.post('/api/v1/orgs',
                          json={'name': 'Amixalan', 'short': 'AMX'}).get_json()['uid']
        freshservice['set']([_dep(7, 'Amixalan Energy Supplies, S.L.')])
        client.post('/api/v1/providers/freshservice/import',
                    json={'pick': ['7'], 'link': {'7': uid}})
        d = client.get('/api/v1/providers/freshservice/preview').get_json()
        assert d['counts']['create'] == 0
        assert len(admin._orgs_store.orgs.list()) == 1

    def test_y_una_ya_atada_a_otro_se_rechaza_con_su_motivo(self, admin, client, freshservice):
        """Dos departamentos no pueden compartir una empresa: la fila iría cambiando de nombre
        sola en cada importación."""
        uid = client.post('/api/v1/orgs',
                          json={'name': 'Amixalan', 'short': 'AMX'}).get_json()['uid']
        freshservice['set']([_dep(7, 'La primera')])
        client.post('/api/v1/providers/freshservice/import',
                    json={'pick': ['7'], 'link': {'7': uid}})
        freshservice['set']([_dep(7, 'La primera'), _dep(8, 'La segunda')])
        r = client.post('/api/v1/providers/freshservice/import',
                        json={'pick': ['8'], 'link': {'8': uid}})
        d = r.get_json()
        assert d['adopted'] == 0 and d['created'] == 0
        assert [f['name'] for f in d['failed']] == ['La segunda']
        # Con palabras, no con la clave en crudo.
        assert d['failed'][0]['error'] and not d['failed'][0]['error'].startswith('fs_')
        assert len(admin._orgs_store.orgs.list()) == 1
