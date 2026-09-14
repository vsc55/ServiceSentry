#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Traer los dispositivos de Freshservice: las dos rutas, con la red de mentira.

De mentira **la red y nada más**: la aplicación es la de verdad, el registro de dispositivos es el
de verdad y las fichas que quedan se leen de la base. Lo que se sustituye es el cliente HTTP,
porque una prueba que llama a Freshservice de verdad falla el día que se cae, el día que caduca
una clave y el día que alguien la ejecuta en un tren.

Lo que se comprueba es lo que separa una importación de un desastre, y aquí hay uno que no existía
con las empresas: **de un dispositivo cuelgan sus claves de conexión**. El almacén guarda la ficha
entera en cada escritura, así que una actualización escrita a la ligera —tres campos y a
guardar— le borra los perfiles SSH a cuarenta máquinas sin dar ni un error.

Y lo demás: que mirar y aplicar sean dos cosas, que volver a importar no duplique, que lo que
tecleó una persona se adopte, que lo que ya no está no se borre, que emparejar a mano mande, y que
todo esté detrás de `devices_edit` — que es la bandera que decide qué máquinas hay, y no
`orgs_edit`, que decide de quién son.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys

import pytest
from werkzeug.security import generate_password_hash

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.providers.freshservice import client as fs_client                # noqa: E402
from tests.conftest import _login                                         # noqa: E402


def _node():
    return shutil.which('node')


def _as(admin, username, perms):
    """Una sesión con EXACTAMENTE esos permisos, por un rol propio."""
    role = f'r-{username}'
    admin._custom_roles[role] = {
        'uid': role, 'name': role, 'description': '', 'permissions': list(perms),
        'enabled': True, 'created_at': '2026-09-13T00:00:00Z',
        'updated_at': '2026-09-13T00:00:00Z', 'updated_by': 'test'}
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash('pw-secret')}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': 'pw-secret'},
           follow_redirects=True)
    return c


def _clase(admin, corto):
    """El `uid` de la clase local cuyo nombre corto es *corto*.

    Las pruebas la nombran «server» o «access_point» porque es como se lee; lo que se guarda y lo
    que viaja por la API es su `uid`.
    """
    fila = admin._device_types_store.by_slug(corto)
    assert fila is not None, 'no existe la clase %s' % corto
    return fila['uid']


def _activo(ident, nombre, *, ip='', tipo=7001, **extra):
    campos = {'ip_address_7000999': ip} if ip else {}
    return dict({'id': int(ident) * 100, 'display_id': int(ident), 'name': nombre,
                 'asset_type_id': tipo, 'type_fields': campos}, **extra)


@pytest.fixture()
def fsa(admin, client, monkeypatch):
    """Freshservice configurado y contestando lo que le digamos.

    `set(...)` decide qué contesta la próxima llamada y `calls` cuenta cuántas ha habido — que es
    lo que prueba que aplicar vuelve a preguntar en vez de fiarse de lo que enseñó la pantalla.
    """
    _login(client)
    admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                          'api_key': 'k-secreta'}})
    caja = {'assets': [], 'types': [{'id': 7001, 'name': 'Server'},
                                    {'id': 7002, 'name': 'Network Switch'},
                                    {'id': 7003, 'name': 'Monitor'}],
            'calls': 0, 'raise': None, 'types_raise': None, 'asked': []}

    def _assets(domain, api_key, type_ids=None):
        caja['calls'] += 1
        caja['seen'] = (domain, api_key)
        # Lo que se le PIDIÓ, que no es lo mismo que lo que contesta. Por defecto **ignora el
        # filtro** y devuelve la lista entera, que es lo que hace un origen cuya versión no lo
        # entiende: así lo que se comprueba abajo es que la pantalla no enseñe lo que nadie pidió.
        caja['asked'].append(list(type_ids or []))
        if caja['raise'] is not None:
            raise caja['raise']
        return list(caja['assets'])

    def _types(domain, api_key):
        if caja['types_raise'] is not None:
            raise caja['types_raise']
        return list(caja['types'])

    def _counts(domain, api_key):
        caja['calls'] += 1
        if caja['raise'] is not None:
            raise caja['raise']
        fuera = {}
        for f in caja['assets']:
            k = str(f.get('asset_type_id') or '')
            fuera[k] = fuera.get(k, 0) + 1
        return fuera

    monkeypatch.setattr('lib.providers.freshservice.routes.fs_client.assets', _assets)
    monkeypatch.setattr('lib.providers.freshservice.routes.fs_client.asset_counts', _counts)
    monkeypatch.setattr('lib.providers.freshservice.routes.fs_client.asset_types', _types)
    caja['set'] = lambda filas: caja.__setitem__('assets', filas)
    return caja


class TestElBotonDeImportarViveEnDispositivos:
    """Pedido desde la pantalla, y con la misma forma que el de Empresas: traer los de fuera es
    un acto **sobre esta lista**, y bajar a Configuración para hacerlo es ir a buscar un botón a
    la pantalla de otra cosa.

    Y con la condición que es la mitad del arreglo: **sólo si el conector está puesto**. Un botón
    que promete traer cuatrocientas máquinas y falla en la primera llamada por una clave que nadie
    ha escrito es peor que no tenerlo — el error que da es de autenticación, y eso manda a mirar
    la credencial en vez del campo vacío.
    """

    def test_sin_conector_no_hay_boton(self, client, admin):
        _login(client)
        admin._write_config({'freshservice': {'domain': '', 'api_key': ''}})
        assert client.get('/api/v1/devices').get_json()['actions'] == []

    def test_con_el_conector_puesto_si(self, client, admin):
        _login(client)
        admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                              'api_key': 'k'}})
        [acc] = client.get('/api/v1/devices').get_json()['actions']
        assert acc['fn'] == 'freshserviceImportHosts'
        assert acc['perm'] == 'devices_edit', 'la acción viajaría con el permiso de otra cosa'

    def test_con_el_dominio_pero_sin_la_clave_tampoco(self, client, admin):
        _login(client)
        admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                              'api_key': ''}})
        assert client.get('/api/v1/devices').get_json()['actions'] == []

    def test_y_la_respuesta_no_se_queda_cacheada(self, client, admin):
        """La configuración se edita desde el propio panel. Una respuesta guardada de por vida
        dejaría el botón escondido después de poner la clave, hasta reiniciar."""
        _login(client)
        admin._write_config({'freshservice': {'domain': '', 'api_key': ''}})
        assert client.get('/api/v1/devices').get_json()['actions'] == []
        admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                              'api_key': 'k'}})
        assert len(client.get('/api/v1/devices').get_json()['actions']) == 1

    def test_el_origen_viaja_para_que_la_fila_pueda_decir_de_donde_vino(self, client, admin):
        """La columna guarda `freshservice` y la pantalla enseña un nombre y un icono. Si no
        viajara el descriptor, la fila enseñaría el identificador crudo."""
        _login(client)
        fuentes = client.get('/api/v1/devices').get_json()['sources']
        assert {'id': 'freshservice', 'label_key': 'fs_source',
                'icon': 'bi-life-preserver'} in fuentes

    def test_el_core_no_nombra_a_ningun_proveedor(self):
        """El texto, el icono y la función los pone quien trae los dispositivos. Si el core
        escribiera «Freshservice» en algún sitio, quitar el paquete dejaría un botón que no hace
        nada — y ningún otro proveedor podría ofrecer el suyo."""
        for rel in (os.path.join('lib', 'web_admin', 'templates', 'partials', 'servers',
                                 '_list.html'),
                    os.path.join('lib', 'core', 'devices', 'routes.py'),
                    os.path.join('lib', 'core', 'devices', 'actions.py')):
            texto = io.open(os.path.join(SRC, rel), encoding='utf-8').read()
            # Los comentarios usan el ejemplo real, que es documentación y no código.
            codigo = '\n'.join(l for l in texto.split('\n')
                               if not l.lstrip().startswith(('#', '*', '/*', '//')))
            assert 'freshservice' not in codigo.lower(), rel

    def test_cuelga_del_boton_de_anadir_y_no_al_lado(self, client, admin):
        """Dibujado de verdad en node: que el desplegable esté o no está en el HTML, no en el
        fuente."""
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        from tests.helpers import node_run, panel_bundle            # noqa: PLC0415
        _login(client)
        admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                              'api_key': 'k'}})
        acciones = client.get('/api/v1/devices').get_json()['actions']
        out = node_run(panel_bundle(client), """
            __out = {};
            currentUser = {permissions: ['devices_edit']};
            _hostActions = %s;
            __out.con = _hostsNewHtml();
            _hostActions = [];
            __out.sin = _hostsNewHtml();
            currentUser = {permissions: []};
            _hostActions = %s;
            __out.sinPermiso = _hostsNewHtml();
        """ % (json.dumps(acciones), json.dumps(acciones)))
        assert 'dropdown-toggle-split' in out['con'], 'la pestaña no está'
        assert 'freshserviceImportHosts()' in out['con']
        # Y lo que la pestaña acompaña sigue ahí: es un botón partido, no una pestaña suelta.
        assert 'openNewDeviceModal' in out['con'], 'la pestaña se llevó el botón de añadir'
        # Un desplegable vacío es peor que ninguno: promete algo.
        assert 'dropdown' not in out['sin'], 'la pestaña sale sin nada que colgar'
        assert 'openNewDeviceModal' in out['sin'], 'y el botón de añadir se ha perdido con ella'
        # Sin el permiso del proveedor, la pestaña no sale — pero añadir a mano sí, que es otra
        # bandera y la decide la barra.
        assert 'dropdown' not in out['sinPermiso']


class TestElegirLasClasesAntesDeTraerNada:
    """El catálogo de tipos es un recurso aparte y una sola llamada, así que se puede preguntar
    qué hace falta **antes** de traer: un inventario de cuatro mil activos son cuarenta viajes a
    su API para acabar mirando los doce conmutadores. Pedido desde la pantalla.
    """

    def test_el_catalogo_de_clases_se_pide_solo(self, client, fsa):
        d = client.get('/api/v1/providers/freshservice/assets/types').get_json()
        assert [x['name'] for x in d['types']] == ['Monitor', 'Network Switch', 'Server']
        assert fsa['calls'] == 0, 'ha traído activos para enseñar una lista de clases'

    def test_y_cada_clase_dice_en_qué_se_convertiría(self, client, admin, fsa):
        """Una lista de nombres ajenos no se puede contestar de un vistazo; con la clase de aquí
        al lado, sí — y es lo que separa «Network Switch» de «Monitor».

        Dicha por `uid`, que es lo que la pantalla sabe traducir: su catálogo va por uid, y con el
        nombre corto la columna enseñaba «switch» a secas donde el resto dice «Conmutador»."""
        d = client.get('/api/v1/providers/freshservice/assets/types').get_json()
        clases = {x['name']: x['device_type'] for x in d['types']}
        assert clases['Network Switch'] == _clase(admin, 'switch')
        assert clases['Monitor'] == '', 'un monitor no es un dispositivo que se pueda vigilar'

    def test_lo_elegido_se_le_pide_al_origen(self, client, fsa):
        """Para no traer de más. Es el ahorro entero: el filtro va en la consulta, no sólo en la
        pantalla."""
        fsa['set']([])
        client.get('/api/v1/providers/freshservice/assets/preview?type=7002')
        assert fsa['asked'] == [['7002']]

    def test_y_lo_que_llegue_se_filtra_igualmente(self, client, fsa):
        """**La mitad que importa.** La forma de ese filtro no es la misma en todos los planes, y
        un origen que no lo entienda contesta la lista entera — y la pantalla enseñaría cuatro mil
        activos cuando se pidieron los conmutadores, sin que nada fallara. El del arnés la ignora
        a propósito."""
        fsa['set']([_activo(1, 'SRV-01', tipo=7001), _activo(2, 'SW-01', tipo=7002)])
        d = client.get(
            '/api/v1/providers/freshservice/assets/preview?type=7002').get_json()
        assert [p['name'] for p in d['plan']] == ['SW-01']

    def test_sin_elegir_ninguna_se_traen_todas(self, client, fsa):
        """Que es lo que significa no haber elegido. Un filtro vacío que no devolviera nada sería
        una pantalla en blanco por no pulsar."""
        fsa['set']([_activo(1, 'SRV-01', tipo=7001), _activo(2, 'SW-01', tipo=7002)])
        d = client.get('/api/v1/providers/freshservice/assets/preview').get_json()
        assert len(d['plan']) == 2
        assert fsa['asked'] == [[]]

    def test_aplicar_pide_las_mismas_clases_con_las_que_se_miró(self, client, admin, fsa):
        """Sin esto, aceptar volvería a pedir el inventario entero: lo elegido saldría igual —va
        por identificador— pero a costa de las cuarenta páginas que la vista previa acababa de
        ahorrar. Y lo de OTRA clase que se hubiera colado no se tocaría igualmente."""
        fsa['set']([_activo(1, 'SRV-01', tipo=7001), _activo(2, 'SW-01', tipo=7002)])
        client.get('/api/v1/providers/freshservice/assets/preview?type=7002')
        client.post('/api/v1/providers/freshservice/assets/import',
                    json={'pick': ['2'], 'types': ['7002']})
        assert fsa['asked'] == [['7002'], ['7002']]
        assert [h['name'] for h in admin._devices_store.list()] == ['SW-01']

    def test_los_huérfanos_se_cuentan_sobre_lo_que_se_pidió(self, client, admin, fsa):
        """Con un filtro puesto, «ya no está en Freshservice» sólo puede decirse de lo que se
        preguntó. Un dispositivo importado de otra clase saldría como desaparecido por no haberlo
        pedido — y lo que eso invita a hacer es borrarlo."""
        admin._devices_store.create({'name': 'SRV-01', 'source': 'freshservice',
                                   'external_id': '1'})
        fsa['set']([_activo(1, 'SRV-01', tipo=7001), _activo(2, 'SW-01', tipo=7002)])
        d = client.get(
            '/api/v1/providers/freshservice/assets/preview?type=7002').get_json()
        assert d['orphans'] == []

    def test_la_pantalla_de_clases_pone_delante_las_que_se_parecen_a_algo(self, client, fsa):
        """Dibujada de verdad en node. Un inventario tiene «Monitor», «Silla» y «Licencia» entre
        los conmutadores, y lo que se viene a buscar es lo que se puede vigilar: por orden
        alfabético, «Monitor» sale antes que «Network Switch» y «Server».

        Y el atajo de «las que parecen dispositivos» marca **sólo ésas**. Marcarlas todas
        —que es lo que pasa si se deja de mirar `device_type`— convierte el atajo en el botón de
        al lado, en silencio: el recuento diría 3 de 3 y nadie se fijaría.
        """
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        from tests.helpers import node_run, panel_bundle            # noqa: PLC0415
        tipos = client.get(
            '/api/v1/providers/freshservice/assets/types').get_json()['types']
        # El DOM de mentira devuelve un nodo NUEVO en cada `getElementById`, así que lo que se
        # escribe no se puede volver a leer. Se le pone uno estable por id, que es lo que permite
        # mirar lo que la función ha pintado de verdad.
        out = node_run(panel_bundle(client), """
            __out = {};
            const _nodos = {};
            document.getElementById = (id) => (_nodos[id] = _nodos[id]
                || {innerHTML: '', textContent: '', disabled: false});
            _fsaTypes = %s;
            _fsaTypePick = new Set();
            _fsaTypesDraw();
            __out.html = _nodos['fsAssetsBody'].innerHTML;
            _fsaTypesLikely();
            __out.likely = Array.from(_fsaTypePick).sort().join(',');
            _fsaTypesAll(true);
            __out.todas = Array.from(_fsaTypePick).sort().join(',');
        """ % json.dumps(tipos))
        orden = [n for n in ('Network Switch', 'Server', 'Monitor')
                 if n in out['html']]
        assert out['html'].index('Network Switch') < out['html'].index('Monitor')
        assert orden and 'Monitor' in out['html'], 'ha escondido una clase en vez de bajarla'
        # 7001 servidor y 7002 conmutador; 7003 es un monitor y no se vigila.
        assert out['likely'] == '7001,7002'
        assert out['todas'] == '7001,7002,7003'

    def test_el_recuento_se_pide_aparte_y_no_al_abrir(self, client, fsa):
        """Su catálogo no trae el número, así que contarlos es recorrer los activos — el viaje
        que este paso ahorra. Hacerlo al abrir sería pagarlo siempre para que a veces sirviera."""
        fsa['set']([_activo(1, 'SRV-01', tipo=7001), _activo(2, 'SW-01', tipo=7002),
                    _activo(3, 'SW-02', tipo=7002)])
        client.get('/api/v1/providers/freshservice/assets/types')
        assert fsa['calls'] == 0
        d = client.get('/api/v1/providers/freshservice/assets/counts').get_json()
        assert d['counts'] == {'7001': 1, '7002': 2}

    def test_las_clases_vacías_se_apartan_y_no_se_pueden_marcar(self, client, fsa):
        """Dibujado de verdad en node. Y **sin contar no hay ceros**: `null` y `0` son dos cosas
        distintas, y con la diferencia borrada la lista sin contar saldría entera apagada y no
        habría dónde elegir nada."""
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        from tests.helpers import node_run, panel_bundle            # noqa: PLC0415
        tipos = client.get(
            '/api/v1/providers/freshservice/assets/types').get_json()['types']
        out = node_run(panel_bundle(client), """
            __out = {};
            const _nodos = {};
            document.getElementById = (id) => (_nodos[id] = _nodos[id]
                || {innerHTML: '', textContent: '', disabled: false});
            _fsaTypes = %s;
            _fsaTypePick = new Set();
            _fsaCounts = null;
            _fsaShowEmpty = false;
            _fsaTypesDraw();
            __out.sinContar = _nodos['fsAssetsBody'].innerHTML;
            _fsaCounts = {'7001': 4, '7002': 0, '7003': 0};
            _fsaTypesDraw();
            __out.contado = _nodos['fsAssetsBody'].innerHTML;
            _fsaTypesAll(true);
            __out.todas = Array.from(_fsaTypePick).sort().join(',');
            _fsaToggleEmpty();
            __out.conVacias = _nodos['fsAssetsBody'].innerHTML;
        """ % json.dumps(tipos))
        assert 'disabled' not in out['sinContar'], 'sin contar ha apagado las casillas'
        assert 'Monitor' in out['sinContar']
        # Contado: sólo queda la que tiene algo, y las otras dos se apartan tras un botón.
        assert 'Server' in out['contado']
        assert 'Monitor' not in out['contado'], 'una clase vacía sigue ocupando sitio'
        assert 'Monitor' in out['conVacias'], 'no hay forma de volver a verlas'
        assert 'disabled' in out['conVacias'], 'una clase vacía se puede marcar'
        # Y «todas» no marca lo que no puede traer nada: el botón prometería un número que no es.
        assert out['todas'] == '7001'

    def test_el_catalogo_tambien_está_detrás_de_devices_edit(self, admin, fsa):
        c = _as(admin, 'solo-empresas-2', ['devices_view', 'orgs_edit'])
        assert c.get('/api/v1/providers/freshservice/assets/types').status_code == 403
        assert c.get('/api/v1/providers/freshservice/assets/counts').status_code == 403


class TestTraerLasClasesSinTraerNingunActivo:
    """Una casa que ya usa Freshservice tiene ahí escritas las clases que usa —«Access Point»,
    «IP Phone»— y teclearlas otra vez aquí es tener dos listas, que es una que se queda vieja sin
    avisar. Su catálogo de tipos es un recurso aparte y una sola llamada, así que esto es
    barato."""

    def test_las_crea_y_las_cuenta_con_su_nombre(self, client, admin, fsa):
        """Crear quince clases en silencio es la manera de acabar con quince que nadie recuerda
        haber pedido."""
        fsa['types'] = [{'id': 7009, 'name': 'Access Point'},
                        {'id': 7010, 'name': 'IP Phone'}]
        d = client.post('/api/v1/providers/freshservice/assets/types',
                        json={}).get_json()
        # Contadas **con su nombre**, que es lo que se lee en el aviso: el `uid` viene al lado
        # para que la pantalla pueda ir a ellas, pero no dice nada a quien mira.
        assert sorted(x['name'] for x in d['added']) == ['Access Point', 'IP Phone']
        assert all(x['uid'] for x in d['added'])
        assert admin._device_types_store.by_slug('access_point')['source'] == 'freshservice'
        assert fsa['calls'] == 0, 'ha traído activos para crear unas clases'

    def test_lo_que_ya_hay_no_se_toca_ni_se_duplica(self, client, admin, fsa):
        """Un tipo que se parece a una clase que ya está no crea una copia: dos «Router» en el
        desplegable son dos sitios donde repartir la misma flota."""
        fsa['types'] = [{'id': 7001, 'name': 'Router'}]
        antes = len(admin._device_types_store.list())
        d = client.post('/api/v1/providers/freshservice/assets/types',
                        json={}).get_json()
        assert d['added'] == []
        assert len(admin._device_types_store.list()) == antes

    def test_dos_veces_seguidas_no_crean_dos(self, client, admin, fsa):
        fsa['types'] = [{'id': 7009, 'name': 'Access Point'}]
        client.post('/api/v1/providers/freshservice/assets/types', json={})
        d = client.post('/api/v1/providers/freshservice/assets/types',
                        json={}).get_json()
        assert d['added'] == []

    def test_un_tipo_sin_nombre_no_crea_una_clase_en_blanco(self, client, admin, fsa):
        """Una fila sin nombre es una entrada vacía en el desplegable de todo el mundo."""
        fsa['types'] = [{'id': 7009, 'name': '  '}, {'id': 7010, 'name': 'Access Point'}]
        d = client.post('/api/v1/providers/freshservice/assets/types',
                        json={}).get_json()
        assert [x['name'] for x in d['added']] == ['Access Point']

    def test_se_pregunta_cuales_antes_de_traerlas(self, client, admin, fsa):
        """Las otras dos importaciones de este paquete enseñan el plan antes de tocar nada; ésta
        se lanzaba a ciegas. La lista de tipos de una casa lleva «Monitor», «Silla» y «Licencia»
        entre los conmutadores."""
        fsa['types'] = [{'id': 7009, 'name': 'Access Point'},
                        {'id': 7010, 'name': 'IP Phone'}]
        client.post('/api/v1/providers/freshservice/assets/types',
                    json={'pick': ['7009']})
        assert admin._device_types_store.by_slug('access_point') is not None
        assert admin._device_types_store.by_slug('ip_phone') is None

    def test_y_el_catalogo_dice_cual_de_ellas_ya_tiene_equivalente(self, client, admin, fsa):
        """Elegir qué traer sin saber qué haría cada una es elegir a ciegas entre lo que crea
        algo y lo que no hace nada."""
        fsa['types'] = [{'id': 7001, 'name': 'Server'}, {'id': 7009, 'name': 'Access Point'}]
        tipos = {t['name']: t for t in client.get(
            '/api/v1/providers/freshservice/assets/types').get_json()['types']}
        assert tipos['Server']['here'] == _clase(admin, 'server'), \
            'no ve que ya hay una que vale'
        assert tipos['Access Point']['here'] == ''

    def test_llamarse_igual_y_estar_vinculada_son_dos_cosas(self, client, admin, fsa):
        """**El fallo que se vio en la pantalla.** El catálogo decía sólo «aquí ya hay una que se
        llama así», y con eso el cuadro de ATAR apagaba «Server» al ir a atarle la clase local
        «Servidor» —que se llama «Server» en el catálogo de idiomas— es decir, apagaba justo la
        fila que se quería pulsar.

        Son dos preguntas: una la contesta el cuadro de importar (traerla no crearía nada) y la
        otra el de atar (dos locales sobre la misma de fuera es repartir la flota en dos montones
        que nadie decidió).
        """
        _login(client)
        # `server` se llama «Server» y no está atada a nada.
        fsa['types'] = [{'id': 7001, 'name': 'Server'}]
        [t1] = client.get(
            '/api/v1/providers/freshservice/assets/types').get_json()['types']
        server = _clase(admin, 'server')
        assert t1['here'] == server, 'ya no coincide por el nombre: el caso se ha perdido'
        assert t1['linked'] == '', 'coincidir por el nombre no es estar vinculada'

        # Y cuando SÍ lo está, lo dice — con cuál.
        client.post(f'/api/v1/device_types/{server}/link',
                    json={'source': 'freshservice', 'external_id': '7001'})
        [t2] = client.get(
            '/api/v1/providers/freshservice/assets/types').get_json()['types']
        assert t2['linked'] == server
        assert t2['linked_name'] == 'Server'

    def test_sin_elegir_ninguna_se_traen_todas(self, client, admin, fsa):
        """Que es lo que hacía cuando no se podía elegir, y lo que significa no haber elegido."""
        fsa['types'] = [{'id': 7009, 'name': 'Access Point'},
                        {'id': 7010, 'name': 'IP Phone'}]
        d = client.post('/api/v1/providers/freshservice/assets/types',
                        json={}).get_json()
        assert len(d['added']) == 2

    def test_una_lista_vacia_no_trae_nada(self, client, admin, fsa):
        """`[]` es «ninguna» y `null` es «todas» — borrar esa diferencia hace que desmarcarlo
        todo y aceptar traiga el catálogo entero."""
        fsa['types'] = [{'id': 7009, 'name': 'Access Point'}]
        d = client.post('/api/v1/providers/freshservice/assets/types',
                        json={'pick': []}).get_json()
        assert d['added'] == []

    def test_lo_que_crea_queda_atado_a_la_de_alli(self, client, admin, fsa):
        """Y no sólo marcado con el origen: por el nombre, renombrarla aquí dejaría a la
        siguiente importación creando una segunda."""
        fsa['types'] = [{'id': 7009, 'name': 'Access Point'}]
        client.post('/api/v1/providers/freshservice/assets/types', json={})
        fila = admin._device_types_store.by_slug('access_point')
        assert (fila['source'], fila['external_id']) == ('freshservice', '7009')
        admin._device_types_store.update(fila['uid'], 'Punto de acceso')
        antes = len(admin._device_types_store.list())
        client.post('/api/v1/providers/freshservice/assets/types', json={})
        assert len(admin._device_types_store.list()) == antes, 'ha creado una segunda'

    def test_y_esta_detras_de_devices_edit(self, admin, fsa):
        c = _as(admin, 'solo-empresas-3', ['devices_view', 'orgs_edit'])
        assert c.post('/api/v1/providers/freshservice/assets/types',
                      json={}).status_code == 403

    def test_el_boton_solo_sale_con_el_conector_puesto(self, client, admin):
        """Declarado como todo lo demás, y filtrado por el propio proveedor: la pantalla de
        clases no sabe que Freshservice existe."""
        _login(client)
        admin._write_config({'freshservice': {'domain': '', 'api_key': ''}})
        assert client.get('/api/v1/device_types').get_json()['actions'] == []
        admin._write_config({'freshservice': {'domain': 'lacasa.freshservice.com',
                                              'api_key': 'k'}})
        acciones = client.get('/api/v1/device_types').get_json()['actions']
        porfn = {a['fn']: a for a in acciones}
        # Dos: traer el catálogo entero, que va en la barra, y atar UNA clase a una de allí, que
        # va dentro de su ficha. Son dos actos y por eso `link` los separa.
        assert porfn['freshserviceImportTypes']['perm'] == 'devices_edit'
        assert porfn['freshserviceImportTypes']['link'] is False
        assert porfn['freshserviceLinkType']['link'] is True


class TestMirarAntesDeAplicar:
    """Una importación que crea en silencio es una que, el día que el filtro esté mal, deja
    cuatrocientas fichas y ninguna forma de saber cuál era la buena."""

    def test_la_vista_previa_no_escribe_nada(self, client, admin, fsa):
        fsa['set']([_activo(1, 'SRV-01', ip='10.0.0.5')])
        d = client.get('/api/v1/providers/freshservice/assets/preview').get_json()
        assert d['counts'] == {'create': 1, 'update': 0, 'adopt': 0, 'same': 0}
        assert admin._devices_store.list() == []

    def test_lleva_los_de_aqui_para_poder_emparejar_a_mano(self, client, admin, fsa):
        """Qué dispositivo local es el mismo que un activo de allí lo sabe quien mira, no un
        parecido de nombres."""
        admin._devices_store.create({'name': 'srv-barcelona', 'address': '10.0.0.5'})
        fsa['set']([_activo(1, 'SRV-BCN-01')])
        d = client.get('/api/v1/providers/freshservice/assets/preview').get_json()
        assert [h['name'] for h in d['devices']] == ['srv-barcelona']

    def test_y_no_lleva_los_perfiles_de_conexion(self, client, admin, fsa):
        """En ese cuadro se elige un nombre de un desplegable. Mandar las claves de SSH de la
        flota entera en una respuesta HTTP para dibujar un `<select>` es regalar lo único que de
        verdad hay que guardar."""
        admin._devices_store.create({'name': 'srv-1', 'address': '10.0.0.5',
                                   'profiles': {'ssh': {'ssh_password': 'p@ss'}}})
        fsa['set']([])
        crudo = client.get('/api/v1/providers/freshservice/assets/preview').get_data(
            as_text=True)
        assert 'p@ss' not in crudo and 'profiles' not in crudo

    def test_aplicar_vuelve_a_pedir_la_lista(self, client, admin, fsa):
        """Entre mirar y aceptar pasa un rato, y lo que se escribe tiene que ser lo que hay
        ahora — no lo que enseñó la pantalla."""
        fsa['set']([_activo(1, 'SRV-01')])
        client.get('/api/v1/providers/freshservice/assets/preview')
        assert fsa['calls'] == 1
        client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert fsa['calls'] == 2


class TestLoQueEscribe:
    """Y sobre todo, lo que NO escribe."""

    def test_crea_el_dispositivo_con_lo_que_sabe_el_origen(self, client, admin, fsa):
        fsa['set']([_activo(1, 'SRV-01', ip='10.0.0.5', description='el de la sala')])
        r = client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert r.get_json()['created'] == 1
        [h] = admin._devices_store.list()
        assert (h['name'], h['address'], h['description']) == ('SRV-01', '10.0.0.5',
                                                               'el de la sala')
        assert (h['source'], h['external_id']) == ('freshservice', '1')

    def test_nace_sin_ejecutar_nada_en_el(self, client, admin, fsa):
        """`kind` = `none`. Un conmutador o un SAI que llegan de un inventario no tienen dónde
        ejecutar una orden, y `local` haría que un check suyo midiera ESTA máquina y archivara
        el resultado con el nombre del conmutador."""
        fsa['set']([_activo(1, 'SW-01')])
        client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert admin._devices_store.get_by_name('SW-01')['kind'] == 'none'

    def test_la_clase_se_adivina_del_tipo_de_activo(self, client, admin, fsa):
        """Y se guarda por `uid`. La tabla de pistas contesta con el nombre corto —`server`,
        `switch`—, que es lo único de las sembradas escrito en el código; escribir eso en la
        columna es que el almacén lo tire, y entonces la máquina se trae igual y se queda sin
        clasificar, sin un solo error."""
        fsa['set']([_activo(1, 'SRV-01')])
        client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert admin._devices_store.get_by_name('SRV-01')['device_type'] == _clase(admin,
                                                                                'server')

    def test_la_clase_que_no_existe_aqui_se_crea(self, client, admin, fsa):
        """Un punto de acceso no era ninguna de las once clases de serie, así que caía en «sin
        clasificar» — junto con los teléfonos IP, las controladoras y todo lo que no estuviera en
        una lista escrita hace dos años. Ahora se crea con el nombre que trae el origen."""
        fsa['types'] = [{'id': 7009, 'name': 'Access Point'}]
        fsa['set']([_activo(1, 'AP-01', tipo=7009)])
        client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        clase = admin._device_types_store.by_slug('access_point')
        assert admin._devices_store.get_by_name('AP-01')['device_type'] == clase['uid']
        assert (clase['name'], clase['source']) == ('Access Point', 'freshservice')

    def test_y_no_se_crea_dos_veces(self, client, admin, fsa):
        """Buscar antes de crear no es una optimización: dos importaciones seguidas dejarían dos
        clases iguales, y la segunda se llevaría los dispositivos nuevos."""
        fsa['types'] = [{'id': 7009, 'name': 'Access Point'}]
        fsa['set']([_activo(1, 'AP-01', tipo=7009), _activo(2, 'AP-02', tipo=7009)])
        antes = len(admin._device_types_store.list())
        client.post('/api/v1/providers/freshservice/assets/import',
                    json={'pick': ['1', '2']})
        assert len(admin._device_types_store.list()) == antes + 1

    def test_pero_la_que_SÍ_se_parece_a_una_de_serie_no_crea_ninguna(self, client, admin, fsa):
        """La lista de casa no crece con una copia de algo que ya existe sólo porque el origen lo
        escriba con otras palabras."""
        fsa['set']([_activo(1, 'SRV-01', tipo=7001)])     # «Server» → `server`, ya sembrada
        antes = len(admin._device_types_store.list())
        client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert len(admin._device_types_store.list()) == antes, 'ha creado una copia'
        assert admin._devices_store.get_by_name('SRV-01')['device_type'] == _clase(admin,
                                                                                'server')

    def test_la_vista_previa_dice_que_va_a_crearla_antes_de_aceptar(self, client, fsa):
        """Crear clases en silencio es la manera de acabar con quince que nadie recuerda haber
        pedido."""
        fsa['types'] = [{'id': 7009, 'name': 'Access Point'}]
        fsa['set']([_activo(1, 'AP-01', tipo=7009)])
        [p] = client.get(
            '/api/v1/providers/freshservice/assets/preview').get_json()['plan']
        assert (p['device_type'], p['new_type']) == ('', 'Access Point')

    def test_y_no_lo_dice_cuando_ya_hay_una_que_vale(self, client, admin, fsa):
        """Un aviso de «se creará una clase» sobre una importación que no va a crear ninguna es
        una alarma que enseña a ignorar las alarmas.

        Y la clase viaja por `uid` ya en el plan: es lo que la pantalla sabe traducir —su catálogo
        va por uid— y lo que la columna acepta al aplicarlo. Con el nombre corto, la vista previa
        enseñaba «server» a secas donde el resto del panel dice «Servidor»."""
        fsa['set']([_activo(1, 'SRV-01', tipo=7001)])
        [p] = client.get(
            '/api/v1/providers/freshservice/assets/preview').get_json()['plan']
        assert (p['device_type'], p['new_type']) == (_clase(admin, 'server'), '')

    def test_una_actualizacion_no_se_lleva_por_delante_los_perfiles(self, client, admin, fsa):
        """**El fallo caro.** El almacén guarda la ficha ENTERA en cada escritura, así que una
        actualización escrita como «tres campos y a guardar» le borra a cuarenta máquinas las
        claves de conexión, los módulos que las vigilan y las filas marcadas. Y no da ningún
        error: los checks simplemente empiezan a fallar por credenciales.
        """
        uid = admin._devices_store.create({
            'name': 'SRV-01', 'address': '10.0.0.5', 'source': 'freshservice',
            'external_id': '1', 'profiles': {'ssh': {'ssh_user': 'root',
                                                     'ssh_password': 'p@ss'}},
            'modules': ['ping'], 'tags': ['prod'],
            'device_type': _clase(admin, 'server')})
        fsa['set']([_activo(1, 'SRV-01', ip='10.0.0.9')])
        r = client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert r.get_json()['updated'] == 1
        h = admin._devices_store.get(uid, decrypt=True)
        assert h['address'] == '10.0.0.9', 'no ha traído lo que venía a traer'
        assert h['profiles']['ssh']['ssh_password'] == 'p@ss'
        assert (h['modules'], h['tags']) == (['ping'], ['prod'])

    def test_volver_a_importar_no_duplica_nada(self, client, admin, fsa):
        fsa['set']([_activo(1, 'SRV-01', ip='10.0.0.5')])
        client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        r = client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert r.get_json()['created'] == 0
        assert len(admin._devices_store.list()) == 1

    def test_lo_que_tecleo_una_persona_se_adopta(self, client, admin, fsa):
        """El caso real: la flota se tecleó a mano antes de conectar esto. Y adoptar conserva lo
        de aquí que el origen no sabe — que es casi todo."""
        uid = admin._devices_store.create({'name': 'SRV-01', 'address': '10.0.0.1',
                                         'modules': ['ping']})
        fsa['set']([_activo(1, 'SRV-01', ip='10.0.0.5')])
        r = client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert r.get_json()['adopted'] == 1
        h = admin._devices_store.get(uid)
        assert (h['source'], h['external_id'], h['address']) == ('freshservice', '1',
                                                                 '10.0.0.5')
        assert h['modules'] == ['ping']
        assert len(admin._devices_store.list()) == 1

    def test_emparejar_a_mano_ata_los_dos_que_no_se_parecen(self, client, admin, fsa):
        uid = admin._devices_store.create({'name': 'srv-barcelona'})
        fsa['set']([_activo(1, 'SRV-BCN-01', ip='10.0.0.5')])
        r = client.post('/api/v1/providers/freshservice/assets/import',
                        json={'pick': ['1'], 'link': {'1': uid}})
        assert r.get_json()['adopted'] == 1
        h = admin._devices_store.get(uid)
        assert (h['name'], h['external_id']) == ('SRV-BCN-01', '1')

    def test_un_nombre_que_ya_esta_cogido_se_cuenta_y_no_tumba_a_los_demas(
            self, client, admin, fsa):
        """Son decenas y cada una es independiente. Y lo que falla se cuenta **con su nombre**,
        para que se pueda emparejar a mano — que es lo que se quería hacer."""
        admin._devices_store.create({'name': 'SRV-01', 'source': 'otro', 'external_id': 'x'})
        fsa['set']([_activo(1, 'SRV-01'), _activo(2, 'SRV-02')])
        d = client.post('/api/v1/providers/freshservice/assets/import',
                        json={'pick': ['1', '2']}).get_json()
        assert d['created'] == 1
        assert [f['name'] for f in d['failed']] == ['SRV-01']
        assert 'fs_host_name_taken' not in d['failed'][0]['error'], 'la clave sin traducir'

    def test_lo_que_ya_no_esta_en_el_origen_se_cuenta_y_no_se_borra(self, client, admin, fsa):
        """De un dispositivo cuelgan sus perfiles, sus módulos y meses de historial, y un activo
        desaparece del origen tanto por una baja real como por un filtro mal puesto."""
        admin._devices_store.create({'name': 'viejo', 'source': 'freshservice',
                                   'external_id': '7'})
        fsa['set']([])
        d = client.get('/api/v1/providers/freshservice/assets/preview').get_json()
        assert [h['name'] for h in d['orphans']] == ['viejo']
        client.post('/api/v1/providers/freshservice/assets/import', json={'pick': []})
        assert admin._devices_store.get_by_name('viejo') is not None

    def test_un_catalogo_de_tipos_inalcanzable_no_impide_traer_nada(self, client, admin, fsa):
        """Que una clave no alcance el catálogo de tipos no puede convertirse en negarse a traer
        cuatrocientas máquinas por no poder decir cuáles son conmutadores."""
        fsa['types_raise'] = fs_client.FreshserviceError('fs_err_forbidden')
        fsa['set']([_activo(1, 'SRV-01')])
        r = client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert r.get_json()['created'] == 1
        assert admin._devices_store.get_by_name('SRV-01')['device_type'] == ''


class TestQuienPuedeHacerlo:
    """`devices_edit`, que es la bandera que decide qué máquinas hay. Quien lleva las sociedades
    no tiene por qué poder dar de alta cuarenta servidores, y al revés tampoco."""

    def test_con_orgs_edit_no_basta(self, admin, fsa):
        c = _as(admin, 'solo-empresas', ['devices_view', 'orgs_edit'])
        assert c.get('/api/v1/providers/freshservice/assets/preview').status_code == 403
        assert c.post('/api/v1/providers/freshservice/assets/import',
                      json={}).status_code == 403

    def test_con_devices_edit_si(self, admin, fsa):
        c = _as(admin, 'con-dispositivos', ['devices_view', 'devices_edit'])
        assert c.get('/api/v1/providers/freshservice/assets/preview').status_code == 200


class TestUnDispositivoAtadoNoSeTecleaEncima:
    """Los tres campos que rescribe cada importación no se corrigen a mano: el cambio duraría
    hasta la siguiente, y un campo que se puede escribir y se revierte solo es peor que uno que
    no se puede. La salida es soltarlo de su origen."""

    def test_cambiarle_el_nombre_se_rechaza_y_dice_por_que(self, client, admin, fsa):
        uid = admin._devices_store.create({'name': 'SRV-01', 'source': 'freshservice',
                                         'external_id': '1'})
        r = client.put(f'/api/v1/devices/{uid}', json={'name': 'otro'})
        assert r.status_code == 409
        error = r.get_json()['error']
        assert 'Freshservice' in error, 'enseña el identificador crudo del origen'
        assert 'name' not in error, 'enseña el nombre de la columna de la base de datos'
        assert admin._devices_store.get(uid)['name'] == 'SRV-01'

    def test_pero_todo_lo_demas_se_sigue_editando(self, client, admin, fsa):
        """Freshservice no sabe nada de los perfiles de conexión, de los módulos ni de las
        etiquetas: este panel es el único sitio donde viven. Un dispositivo importado que no se
        puede tocar de ninguna manera es un dispositivo que no se puede vigilar."""
        uid = admin._devices_store.create({'name': 'SRV-01', 'address': '10.0.0.5',
                                         'source': 'freshservice', 'external_id': '1'})
        r = client.put(f'/api/v1/devices/{uid}',
                       json={'name': 'SRV-01', 'address': '10.0.0.5', 'tags': ['prod'],
                             'profiles': {'ssh': {'ssh_user': 'root'}}})
        assert r.status_code == 200
        h = admin._devices_store.get(uid)
        assert h['tags'] == ['prod']
        # **Y sigue atado.** Un guardado que no menciona el origen no lo borra: este cuadro manda
        # la ficha y no sabe de esto, así que sin conservarlo, editar un perfil de conexión
        # soltaría el dispositivo en silencio — y la siguiente importación lo crearía otra vez,
        # duplicado, con el mismo nombre y sin nada de lo que se le había puesto.
        assert (h['source'], h['external_id']) == ('freshservice', '1')

    def test_guardar_la_ficha_entera_sin_tocar_nada_no_se_rechaza(self, client, admin, fsa):
        """El cuadro manda todos los campos siempre. Mirar si la clave VIENE —en vez de si el
        valor cambia— dejaría un dispositivo importado bloqueado del todo."""
        uid = admin._devices_store.create({'name': 'SRV-01', 'address': '10.0.0.5',
                                         'description': 'x', 'source': 'freshservice',
                                         'external_id': '1'})
        h = admin._devices_store.get(uid)
        assert client.put(f'/api/v1/devices/{uid}', json=h).status_code == 200

    def test_editar_uno_de_esta_casa_no_toca_nada_de_esto(self, client, admin, fsa):
        uid = admin._devices_store.create({'name': 'de-aqui'})
        assert client.put(f'/api/v1/devices/{uid}',
                          json={'name': 'renombrado'}).status_code == 200


class TestSoltarloDeSuOrigen:
    """Hace falta una salida. Sin ella, quitar el proveedor deja fichas que nadie mantiene y que
    nadie puede corregir: sólo se podrían borrar."""

    def test_lo_suelta_y_vuelve_a_poder_escribirse(self, client, admin, fsa):
        uid = admin._devices_store.create({'name': 'SRV-01', 'source': 'freshservice',
                                         'external_id': '1'})
        assert client.delete(f'/api/v1/devices/{uid}/source').status_code == 200
        assert admin._devices_store.get(uid)['source'] == ''
        assert client.put(f'/api/v1/devices/{uid}', json={'name': 'otro'}).status_code == 200

    def test_no_borra_nada_suyo(self, client, admin, fsa):
        """Ni sus perfiles, ni sus módulos, ni su dirección. Soltarlo es dejar de refrescarlo,
        no deshacer lo que se sabe de él."""
        uid = admin._devices_store.create({
            'name': 'SRV-01', 'address': '10.0.0.5', 'modules': ['ping'],
            'profiles': {'ssh': {'ssh_password': 'p@ss'}},
            'source': 'freshservice', 'external_id': '1'})
        client.delete(f'/api/v1/devices/{uid}/source')
        h = admin._devices_store.get(uid, decrypt=True)
        assert (h['address'], h['modules']) == ('10.0.0.5', ['ping'])
        assert h['profiles']['ssh']['ssh_password'] == 'p@ss'

    def test_y_despues_una_importacion_lo_vuelve_a_adoptar_en_vez_de_duplicarlo(
            self, client, admin, fsa):
        """Soltarlo no lo esconde del origen: sigue llamándose igual, así que la siguiente
        importación lo encuentra por el nombre y lo adopta. Lo que se ha ganado es el rato de
        poder corregirlo a mano."""
        uid = admin._devices_store.create({'name': 'SRV-01', 'source': 'freshservice',
                                         'external_id': '1'})
        client.delete(f'/api/v1/devices/{uid}/source')
        fsa['set']([_activo(1, 'SRV-01')])
        r = client.post('/api/v1/providers/freshservice/assets/import', json={'pick': ['1']})
        assert r.get_json()['adopted'] == 1
        assert len(admin._devices_store.list()) == 1

    def test_quien_no_puede_editar_ese_dispositivo_no_lo_suelta(self, admin, fsa):
        uid = admin._devices_store.create({'name': 'SRV-01', 'source': 'freshservice',
                                         'external_id': '1'})
        c = _as(admin, 'mirón', ['devices_view'])
        assert c.delete(f'/api/v1/devices/{uid}/source').status_code == 403
        assert admin._devices_store.get(uid)['source'] == 'freshservice'

    def test_uno_que_no_existe_es_un_404_y_no_un_500(self, client, admin, fsa):
        assert client.delete('/api/v1/devices/fantasma/source').status_code == 404
