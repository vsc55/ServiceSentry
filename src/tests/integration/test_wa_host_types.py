#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las clases de dispositivo por HTTP, y la pantalla que las maneja.

Once vienen de serie y no se tocan; las demás las añade quien monta la instalación. Lo que se
comprueba aquí es lo que separa «una clase más» de una pantalla que miente:

* que **su identificador no se mueva** al renombrarla — es lo que guarda cada dispositivo de esa
  clase, y moverlo los deja a todos señalando a una que ya no existe, con el filtro en cero;
* que no se pueda **quitar una que lleva puesta alguien**;
* que una de serie **no se pueda cambiar** aunque exista;
* que escribir esté detrás de `devices_edit` y leer no, o el desplegable saldría vacío para quien
  sólo mira;
* y que la pantalla se ponga al día **sin recargar**: la clase que se acaba de crear tiene que
  estar en el desplegable de al lado, que es desde donde se ha creado.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

import pytest
from werkzeug.security import generate_password_hash

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from tests.conftest import _login                                         # noqa: E402


def _node():
    return shutil.which('node')


def _as(admin, username, perms):
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


def _uid(admin, corto):
    """El `uid` de la clase sembrada cuyo nombre corto es *corto*.

    Las pruebas la nombran «server» o «nas» porque es como se lee; lo que viaja por la API es su
    `uid`, que se genera al sembrar y por tanto no se puede escribir aquí.
    """
    fila = next((f for f in admin._host_types_store.list() if f['slug'] == corto), None)
    assert fila is not None, 'no existe la clase %s' % corto
    return fila['uid']


class TestElCatalogo:
    """Todas son filas de la misma tabla. Lo que cambia entre una sembrada y una escrita aquí no
    es lo que se puede hacer con ella, sino de dónde sale su palabra."""


    def test_lleva_las_de_serie_y_las_de_aqui(self, client, admin):
        _login(client)
        admin._host_types_store.create('Punto de acceso', 'bi-wifi')
        tipos = client.get('/api/v1/host_types').get_json()['types']
        cortos = [t['slug'] for t in tipos]
        assert 'server' in cortos and 'punto_de_acceso' in cortos
        assert cortos.index('server') < cortos.index('camera'), 'ha perdido el orden declarado'
        # Y cada una con su `uid`, que es con lo que la pantalla vuelve a hablar de ella.
        assert all(t['uid'] for t in tipos)

    def test_las_de_serie_traen_su_clave_y_las_de_aqui_su_texto(self, client, admin):
        """Una clase de casa no es traducible porque nadie más sabe que existe; una de serie con
        el texto metido dentro saldría en castellano para quien mira en inglés."""
        _login(client)
        admin._host_types_store.create('Punto de acceso')
        tipos = {t['slug']: t for t in client.get('/api/v1/host_types').get_json()['types']}
        assert tipos['server']['label_key'] == 'host_type_server'
        assert 'label' not in tipos['server']
        assert tipos['punto_de_acceso']['label'] == 'Punto de acceso'
        assert 'label_key' not in tipos['punto_de_acceso']

    def test_y_cuantos_dispositivos_lleva_cada_una(self, client, admin):
        """Va con la lista porque es la mitad de la pregunta: «¿esta la usa alguien?» decide si
        se puede quitar, y sin el número la única forma de saberlo era intentar borrarla y leer
        el error."""
        _login(client)
        server = _uid(admin, 'server')
        admin._hosts_store.create({'name': 'srv-1', 'device_type': server})
        admin._hosts_store.create({'name': 'srv-2', 'device_type': server})
        assert client.get('/api/v1/host_types').get_json()['usage'] == {server: 2}

    def test_leerlo_no_pide_poder_editar(self, admin):
        """O el desplegable de la ficha saldría vacío para quien sólo mira, y sus dispositivos
        parecerían todos sin clasificar."""
        c = _as(admin, 'miron-tipos', ['devices_view'])
        assert c.get('/api/v1/host_types').status_code == 200


class TestAnadirCorregirYQuitar:

    def test_se_anade_y_aparece(self, client, admin):
        _login(client)
        r = client.post('/api/v1/host_types', json={'name': 'Punto de acceso',
                                                    'icon': 'bi-wifi',
                                                    'description': 'Los del techo'})
        ident = r.get_json()['uid']
        fila = admin._host_types_store.get(ident)
        assert (fila['icon'], fila['slug']) == ('bi-wifi', 'punto_de_acceso')
        assert fila['description'] == 'Los del techo'

    def test_y_la_descripcion_se_corrige_despues(self, client, admin):
        """Es lo único que se puede escribir sobre una clase que mantiene un origen: de allí no
        viene, así que ninguna importación la va a pisar."""
        _login(client)
        ident = client.post('/api/v1/host_types',
                            json={'name': 'Punto de acceso'}).get_json()['uid']
        assert client.put(f'/api/v1/host_types/{ident}',
                          json={'name': 'Punto de acceso',
                                'description': 'Los del techo'}).status_code == 200
        assert admin._host_types_store.get(ident)['description'] == 'Los del techo'

    def test_y_guardar_sin_mandarla_no_la_borra(self, client, admin):
        """Que no venga es «déjala como está». Tratarlo como «vacíala» haría que cambiar el icono
        borrara lo que escribió alguien, sin decirlo."""
        _login(client)
        ident = client.post('/api/v1/host_types',
                            json={'name': 'Punto de acceso',
                                  'description': 'Los del techo'}).get_json()['uid']
        client.put(f'/api/v1/host_types/{ident}',
                   json={'name': 'Punto de acceso', 'icon': 'bi-broadcast'})
        assert admin._host_types_store.get(ident)['description'] == 'Los del techo'

    def test_sin_nombre_no(self, client, admin):
        _login(client)
        assert client.post('/api/v1/host_types', json={'name': '  '}).status_code == 400

    def test_el_mismo_nombre_otra_vez_se_rechaza_y_lo_dice(self, client, admin):
        _login(client)
        client.post('/api/v1/host_types', json={'name': 'Punto de acceso'})
        r = client.post('/api/v1/host_types', json={'name': 'PUNTO DE ACCESO'})
        assert r.status_code == 409
        assert 'Punto' in r.get_json()['error'] or 'PUNTO' in r.get_json()['error']

    def test_renombrarla_no_mueve_su_uid(self, client, admin):
        """**La regla entera**, comprobada con un dispositivo puesto: es lo que él tiene guardado,
        y si cambiara se quedaría señalando a una clase que ya no existe."""
        _login(client)
        ident = client.post('/api/v1/host_types',
                            json={'name': 'Punto de acceso'}).get_json()['uid']
        uid = admin._hosts_store.create({'name': 'ap-1', 'device_type': ident})
        assert client.put(f'/api/v1/host_types/{ident}',
                          json={'name': 'AP Wi-Fi 6', 'icon': 'bi-broadcast'}).status_code == 200
        fila = admin._host_types_store.get(ident)
        assert (fila['name'], fila['slug']) == ('AP Wi-Fi 6', 'punto_de_acceso')
        assert admin._hosts_store.get(uid)['device_type'] == ident

    def test_una_sembrada_se_cambia_como_cualquier_otra(self, admin, client):
        """Nada es intocable: era el punto de sacar la lista del código. Y al renombrarla deja de
        traducirse — desde que alguien la llama «Cabina de discos», eso es lo que quiere leer, y
        no lo que diga un catálogo sobre una palabra que ya no usa."""
        _login(client)
        nas = _uid(admin, 'nas')
        assert client.put(f'/api/v1/host_types/{nas}',
                          json={'name': 'Cabina de discos'}).status_code == 200
        fila = admin._host_types_store.get(nas)
        assert (fila['name'], fila['label_key']) == ('Cabina de discos', '')
        assert client.delete(f"/api/v1/host_types/{_uid(admin, 'camera')}").status_code == 200

    def test_una_que_no_existe_sigue_siendo_404(self, client, admin):
        _login(client)
        assert client.put('/api/v1/host_types/fantasma',
                          json={'name': 'X'}).status_code == 404
        assert client.delete('/api/v1/host_types/fantasma').status_code == 404

    def test_volver_a_poner_las_basicas(self, client, admin):
        """La siembra sólo ocurre al crear la tabla, así que quien se pase borrando necesita una
        manera de deshacerlo que no sea teclear once nombres."""
        _login(client)
        client.delete(f"/api/v1/host_types/{_uid(admin, 'camera')}")
        client.delete(f"/api/v1/host_types/{_uid(admin, 'printer')}")
        r = client.post('/api/v1/host_types/seed', json={})
        # Por su nombre corto: esto se lee en un aviso y en una línea de auditoría, y dos uuids
        # dicen que han pasado dos cosas pero no cuáles.
        assert sorted(r.get_json()['added']) == ['camera', 'printer']

    def test_que_no_pisa_lo_corregido(self, client, admin):
        """Un botón que rescribe lo editado es uno que deshace trabajo cada vez que se pulsa."""
        _login(client)
        server = _uid(admin, 'server')
        client.put(f'/api/v1/host_types/{server}', json={'name': 'Servidor de producción',
                                                         'icon': 'bi-cpu'})
        assert client.post('/api/v1/host_types/seed', json={}).get_json()['added'] == []
        assert admin._host_types_store.get(server)['name'] == 'Servidor de producción'

    def test_sembrar_pide_devices_edit(self, admin):
        c = _as(admin, 'miron-semilla', ['devices_view'])
        assert c.post('/api/v1/host_types/seed', json={}).status_code == 403

    def test_una_que_no_lleva_nadie_se_quita(self, client, admin):
        _login(client)
        ident = client.post('/api/v1/host_types',
                            json={'name': 'Punto de acceso'}).get_json()['uid']
        assert client.delete(f'/api/v1/host_types/{ident}').status_code == 200
        assert admin._host_types_store.get(ident) is None

    def test_una_que_lleva_alguien_no_se_quita_y_dice_cuantos(self, client, admin):
        """Borrarla deja a esos dispositivos con una palabra que ya no significa nada: no se
        traduce, no se filtra y no dibuja su icono. Y no se arregla volviéndola a crear."""
        _login(client)
        ident = client.post('/api/v1/host_types',
                            json={'name': 'Punto de acceso'}).get_json()['uid']
        admin._hosts_store.create({'name': 'ap-1', 'device_type': ident})
        admin._hosts_store.create({'name': 'ap-2', 'device_type': ident})
        r = client.delete(f'/api/v1/host_types/{ident}')
        assert r.status_code == 409
        assert '2' in r.get_json()['error'], 'no dice cuántos hay que arreglar'
        assert admin._host_types_store.get(ident) is not None

    def test_escribir_pide_devices_edit(self, admin):
        c = _as(admin, 'miron-tipos-2', ['devices_view'])
        assert c.post('/api/v1/host_types', json={'name': 'X'}).status_code == 403
        assert c.put('/api/v1/host_types/x', json={'name': 'Y'}).status_code == 403
        assert c.delete('/api/v1/host_types/x').status_code == 403


class TestUnaClaseQueMantieneUnOrigen:
    """Atada a una de fuera, su nombre lo lleva allí: aquí se mira y no se teclea, porque la
    siguiente importación lo pisaría. Y hay por dónde salir, o quitar el proveedor dejaría clases
    que nadie mantiene y nadie puede corregir."""

    def _atada(self, client, admin):
        _login(client)
        ident = admin._host_types_store.create('Punto de acceso')
        client.post(f'/api/v1/host_types/{ident}/link',
                    json={'source': 'freshservice', 'external_id': '7009'})
        return ident

    def test_se_ata_y_lo_dice(self, client, admin):
        ident = self._atada(client, admin)
        fila = admin._host_types_store.get(ident)
        assert (fila['source'], fila['external_id']) == ('freshservice', '7009')
        tipos = {t['uid']: t for t in client.get('/api/v1/host_types').get_json()['types']}
        assert tipos[ident]['external_id'] == '7009', 'la pantalla no puede saberlo'

    def test_y_entonces_su_nombre_no_se_teclea(self, client, admin):
        ident = self._atada(client, admin)
        r = client.put(f'/api/v1/host_types/{ident}', json={'name': 'Otro nombre'})
        assert r.status_code == 409
        assert 'freshservice' in r.get_json()['error'].lower()
        assert admin._host_types_store.get(ident)['name'] == 'Punto de acceso'

    def test_pero_su_icono_si(self, client, admin):
        """Lo que mantiene el origen es el nombre y sólo él: allí no hay iconos. Negarse a
        guardarlo era negarse por algo que el origen nunca va a tocar — y la importación ya lo
        respetaba, que es lo que hacía la negativa doblemente falsa. Reportado desde la
        pantalla."""
        ident = self._atada(client, admin)
        r = client.put(f'/api/v1/host_types/{ident}',
                       json={'name': 'Punto de acceso', 'icon': 'bi-broadcast'})
        assert r.status_code == 200
        fila = admin._host_types_store.get(ident)
        assert fila['icon'] == 'bi-broadcast'
        assert (fila['source'], fila['external_id']) == ('freshservice', '7009')

    def test_y_cambiarle_el_icono_a_una_sembrada_no_la_deja_sin_traducir(self, client, admin):
        """Renombrarla sí le quita la clave de idioma —desde ese momento se lee lo que alguien
        escribió— pero elegir otro dibujo no es renombrarla. Sin esta distinción, cambiarle el
        icono a «Servidor» lo dejaba en inglés para quien mira en castellano."""
        _login(client)
        server = _uid(admin, 'server')
        assert admin._host_types_store.get(server)['label_key'] == 'host_type_server'
        r = client.put(f'/api/v1/host_types/{server}',
                       json={'name': 'Server', 'icon': 'bi-cpu'})
        assert r.status_code == 200
        fila = admin._host_types_store.get(server)
        assert (fila['icon'], fila['label_key']) == ('bi-cpu', 'host_type_server')

    def test_pero_una_sembrada_si_se_teclea(self, client, admin):
        """`source` a solas no ata: lo lleva también la siembra, y eso no lo mantiene nadie.
        Confundirlas dejaría las once de serie en sólo lectura."""
        _login(client)
        assert client.put(f"/api/v1/host_types/{_uid(admin, 'nas')}",
                          json={'name': 'Cabina'}).status_code == 200

    def test_soltarla_la_devuelve_a_poder_escribirse(self, client, admin):
        ident = self._atada(client, admin)
        assert client.delete(f'/api/v1/host_types/{ident}/link').status_code == 200
        assert client.put(f'/api/v1/host_types/{ident}',
                          json={'name': 'Otro nombre'}).status_code == 200

    def test_y_no_borra_ni_la_clase_ni_lo_que_la_lleva(self, client, admin):
        ident = self._atada(client, admin)
        admin._hosts_store.create({'name': 'ap-1', 'device_type': ident})
        client.delete(f'/api/v1/host_types/{ident}/link')
        assert admin._host_types_store.get(ident) is not None
        assert admin._hosts_store.get_by_name('ap-1')['device_type'] == ident

    def test_dos_de_aqui_no_comparten_una_de_fuera(self, client, admin):
        ident = self._atada(client, admin)
        otra = admin._host_types_store.create('Antena')
        r = client.post(f'/api/v1/host_types/{otra}/link',
                        json={'source': 'freshservice', 'external_id': '7009'})
        assert r.status_code == 409
        assert 'Punto de acceso' in r.get_json()['error'], 'no dice con cuál choca'
        assert admin._host_types_store.get(ident)['external_id'] == '7009'

    def test_atar_sin_decir_a_que_no_vale(self, client, admin):
        _login(client)
        ident = admin._host_types_store.create('Punto de acceso')
        assert client.post(f'/api/v1/host_types/{ident}/link',
                           json={'source': 'freshservice'}).status_code == 400

    def test_atar_y_soltar_piden_devices_edit(self, admin):
        ident = admin._host_types_store.create('Punto de acceso')
        c = _as(admin, 'miron-atar', ['devices_view'])
        assert c.post(f'/api/v1/host_types/{ident}/link',
                      json={'source': 'x', 'external_id': '1'}).status_code == 403
        assert c.delete(f'/api/v1/host_types/{ident}/link').status_code == 403


class TestLaClaseLlegaAlDispositivo:

    def test_se_puede_guardar_un_dispositivo_con_ella(self, client, admin):
        """El fallo que no da ningún error: la pantalla la ofrece, el almacén la tira por no
        estar en la lista de once, y el dispositivo se guarda sin nada."""
        _login(client)
        ident = client.post('/api/v1/host_types',
                            json={'name': 'Punto de acceso'}).get_json()['uid']
        r = client.post('/api/v1/hosts', json={'name': 'ap-1', 'address': '10.0.0.3',
                                               'device_type': ident})
        assert r.status_code in (200, 201)
        assert admin._hosts_store.get_by_name('ap-1')['device_type'] == ident

    def test_y_la_pagina_la_sirve_sin_reiniciar(self, client, admin):
        """`HOST_TYPES` lo trae la página al cargar. Si saliera de la constante del código en vez
        del panel, una clase creada aquí no existiría para ningún desplegable ni para ningún
        icono hasta reiniciar el proceso."""
        _login(client)
        client.post('/api/v1/host_types', json={'name': 'Punto de acceso'})
        html = client.get('/admin').get_data(as_text=True)
        # Del LITERAL que se inyecta, no del texto de la página. Buscar el identificador a secas
        # daba verde con la lista del código puesta a mano: la palabra estaba, pero en un
        # comentario del propio fichero que la usa de ejemplo. Encontrado mutándolo.
        crudo = html.split('const HOST_TYPES = ', 1)[1].split(';\n', 1)[0]
        tipos = json.loads(crudo)
        porcorto = {t['slug']: t for t in tipos}
        assert porcorto['punto_de_acceso']['label'] == 'Punto de acceso'
        assert porcorto['server']['label_key'] == 'host_type_server', 'faltan las de serie'
        # Con su `uid`, que es lo que guarda cada dispositivo: sin él la página no puede
        # traducir la clase de una fila ni marcarla en el desplegable de la ficha.
        assert all(t['uid'] for t in tipos)


class TestLaPantallaSePoneAlDia:
    """Sin recargar. La clase que se acaba de crear tiene que estar en el desplegable de al lado,
    que es desde donde se ha creado — pedirle a alguien que recargue para ver lo que acaba de
    escribir es lo contrario de todo lo demás del panel."""

    def test_el_catalogo_del_navegador_se_rehace_con_lo_que_contesta_el_servidor(
            self, client, admin):
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        from tests.helpers import node_run, panel_bundle            # noqa: PLC0415
        _login(client)
        client.post('/api/v1/host_types', json={'name': 'Punto de acceso',
                                                'icon': 'bi-wifi'})
        tipos = client.get('/api/v1/host_types').get_json()['types']
        nueva = next(t for t in tipos if t['slug'] == 'punto_de_acceso')['uid']
        server = _uid(admin, 'server')
        out = node_run(panel_bundle(client), """
            __out = {};
            const NUEVA = %s, SERVER = %s;
            // Antes: sólo las de serie, que es como estaba la página antes de crearla. El
            // paquete se ha generado DESPUÉS de crearla, así que el catálogo ya la trae — hay
            // que quitarla a mano para poder mirar el estado anterior.
            HOST_TYPES.length = 0;
            Object.keys(HOST_TYPE_LABELS).forEach(k => delete HOST_TYPE_LABELS[k]);
            Object.keys(HOST_TYPE_KEYS).forEach(k => delete HOST_TYPE_KEYS[k]);
            Object.keys(HOST_TYPE_SLUGS).forEach(k => delete HOST_TYPE_SLUGS[k]);
            [{uid: SERVER, slug: 'server', icon: 'bi-hdd-rack', label_key: 'host_type_server'}]
                .forEach(x => { HOST_TYPES.push(x); HOST_TYPE_ICONS[x.uid] = x.icon;
                                HOST_TYPE_KEYS[x.uid] = x.label_key;
                                HOST_TYPE_SLUGS[x.uid] = x.slug; });
            __out.antes = hostTypeLabel(NUEVA);
            _htData = %s;
            // Lo que hace `_htRefresh` tras guardar, sin la parte que pide por red.
            HOST_TYPES.length = 0;
            (_htData || []).forEach(x => {
                HOST_TYPES.push(x);
                HOST_TYPE_ICONS[x.uid] = x.icon || 'bi-hdd-network';
                HOST_TYPE_SLUGS[x.uid] = x.slug || '';
                if (x.label) HOST_TYPE_LABELS[x.uid] = x.label;
                else delete HOST_TYPE_LABELS[x.uid];
                if (x.label_key) HOST_TYPE_KEYS[x.uid] = x.label_key;
            });
            __out.despues = hostTypeLabel(NUEVA);
            __out.icono = hostTypeIcon(NUEVA);
            __out.deSerie = hostTypeLabel(SERVER);
        """ % (json.dumps(nueva), json.dumps(server), json.dumps(tipos)))
        # Sin ella, lo que se vería en el desplegable es el `uid` a pelo — treinta y seis dígitos
        # entre diez palabras de verdad.
        assert out['antes'] == nueva
        assert out['despues'] == 'Punto de acceso'
        assert out['icono'] == 'bi-wifi'
        # Y una de serie sigue diciéndose por su catálogo, no por un texto guardado.
        assert out['deSerie'] and out['deSerie'] != 'host_type_server'


class TestElListadoParaAtar:
    """Dibujado en node. Lo que apaga una fila es estar **atada a otra** clase de aquí, no
    llamarse igual que una — que es lo que apagaba justo la que se quería pulsar."""

    def _lista(self, client, admin, para, tipos):
        from tests.helpers import node_run, panel_bundle            # noqa: PLC0415
        return node_run(panel_bundle(client), """
            __out = {};
            _fsLinkFor = %s;
            _fsLinkQuery = '';
            _fsTypes = %s;
            __out.html = _fsLinkRowsHtml();
        """ % (json.dumps(para), json.dumps(tipos)))

    def test_una_que_se_llama_igual_pero_no_esta_atada_se_puede_pulsar(self, client, admin):
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        _login(client)
        out = self._lista(client, admin, 'server', [
            {'id': '7001', 'name': 'Server', 'here': 'server', 'here_name': 'Server',
             'linked': '', 'linked_name': '', 'device_type': 'server'}])
        assert 'disabled' not in out['html'], 'apaga la fila que se quiere pulsar'
        assert 'hostTypeLinkTo' in out['html']

    def test_una_atada_a_OTRA_no(self, client, admin):
        """Dos locales sobre la misma de fuera es repartir la flota en dos montones que nadie
        decidió — y el servidor se niega igualmente, pero enterarse al pulsar es tarde."""
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        _login(client)
        out = self._lista(client, admin, 'server', [
            {'id': '7001', 'name': 'Server', 'here': '', 'here_name': '',
             'linked': 'otra', 'linked_name': 'Otra clase', 'device_type': ''}])
        assert 'disabled' in out['html']
        assert 'Otra clase' in out['html'], 'no dice con cuál choca'

    def test_y_la_que_ya_tiene_puesta_sale_marcada(self, client, admin):
        """Pulsarla no cambia nada, pero verla marcada es lo que dice cuál es la suya."""
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        _login(client)
        out = self._lista(client, admin, 'server', [
            {'id': '7001', 'name': 'Server', 'here': '', 'here_name': '',
             'linked': 'server', 'linked_name': 'Server', 'device_type': ''}])
        assert 'disabled' not in out['html'], 'apaga la que ya tiene puesta'
        assert 'bi-check2' in out['html'], 'no dice cuál es la suya'

    def test_al_vincular_se_cierran_los_DOS_cuadros(self, client, admin):
        """Se cerraba sólo el de la clase, así que quedaba el selector del proveedor encima: se
        leía «Guardado» y la pantalla no se movía — parecía que no había pasado nada. Reportado
        desde ella."""
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        from tests.helpers import node_run, panel_bundle            # noqa: PLC0415
        _login(client)
        out = node_run(panel_bundle(client), """
            __out = {};
            const _cerrados = [];
            // Un nodo que se ACUERDA de su id, que es lo que hay que poder mirar: sin eso sólo
            // se puede contar cuántas veces se pidió cerrar, y no cuáles.
            document.getElementById = (id) => ({
                _id: id,
                classList: {contains: c => c === 'show', add() {}, remove() {}, toggle() {}}});
            bootstrap.Modal.getOrCreateInstance = (el) => ({
                show() {}, hide() { _cerrados.push(el._id); }});
            _htCloseStack();
            __out.cerrados = _cerrados.sort().join(',');
        """)
        assert out['cerrados'] == 'fsTypesModal,hostTypeEditModal', out['cerrados']


class TestElCatalogoDeIconos:
    """Los dos mil que trae la fuente, para cuando ninguno de los veinte vale.

    Sacados de la **propia hoja de estilos** y no de una lista escrita a mano: una lista se queda
    vieja en cuanto se actualiza el paquete, y lo que da un nombre que la fuente no tiene no es un
    error — es una clase que no aplica nada, así que el botón sale con un hueco y el cuadro
    parece terminado.
    """

    def test_los_enumera(self, client, admin):
        _login(client)
        d = client.get('/api/v1/ui/icons').get_json()
        assert len(d['icons']) > 1000, len(d['icons'])
        assert all(i.startswith('bi-') for i in d['icons'])

    def test_y_estan_los_de_la_lista_corta(self, client, admin):
        """Los veinte que el cuadro ofrece de entrada salen de la misma fuente: uno que no
        estuviera sería un botón con un hueco dentro."""
        _login(client)
        from tests.helpers import _read                              # noqa: PLC0415
        js = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers',
                                '_types.html'))
        crudo = js.split('const HT_ICONS = [', 1)[1].split(']', 1)[0]
        cortos = [x.strip().strip("'\"") for x in crudo.split(',') if x.strip()]
        todos = set(client.get('/api/v1/ui/icons').get_json()['icons'])
        faltan = [i for i in cortos if i not in todos]
        assert not faltan, faltan

    def test_pide_estar_dentro(self, admin):
        """No es un secreto, pero tampoco es del público: todo lo que hay bajo `/api/v1` de este
        panel pide sesión, y una excepción sin motivo es una puerta que alguien tiene que
        justificar luego."""
        c = admin.app.test_client()
        assert c.get('/api/v1/ui/icons').status_code in (302, 401, 403)


class TestElCuadroDeIconos:
    """Dibujado en node, porque lo que falla aquí no da ningún error: una lista con de más se ve,
    no se cae."""

    def _cuadro(self, client, icono):
        from tests.helpers import node_run, panel_bundle            # noqa: PLC0415
        return node_run(panel_bundle(client), """
            __out = {};
            _htDraft = {uid: 'u-1', slug: 'server', name: 'Server', description: '',
                        icon: %s, source: '', external_id: '', ro: false};
            _htIconsOpen = true;
            // Lo que contesta /api/v1/ui/icons: la fuente entera, los veinte de arriba dentro.
            _htAllIcons = HT_ICONS.concat(['bi-alarm', 'bi-bell', 'bi-box', 'bi-wifi-off']);
            __out.corta = _htIconsShort();
            __out.larga = _htIconsExtra();
            __out.html = _htAllIconsHtml();
        """ % json.dumps(icono))

    def test_los_de_arriba_no_se_repiten_abajo(self, client, admin):
        """Salían **dos veces** en el mismo cuadro, el marcado con ellos — que es lo que hace
        dudar de si son el mismo icono. Reportado desde la pantalla."""
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        _login(client)
        out = self._cuadro(client, 'bi-boxes')
        repetidos = [i for i in out['corta'] if i in out['larga']]
        assert not repetidos, repetidos
        assert 'bi-alarm' in out['larga'], 'la lista larga se ha quedado sin los suyos'

    def test_ni_el_que_lleva_la_clase_cuando_no_es_de_los_veinte(self, client, admin):
        """El caso que se escapa restando sólo `HT_ICONS`: la rejilla corta pone delante el icono
        que lleva la clase cuando no es de los veinte, así que el repetido sería justo ése — el
        único que quien abre el cuadro está mirando."""
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        _login(client)
        out = self._cuadro(client, 'bi-bell')
        assert 'bi-bell' in out['corta'], 'el suyo no sale arriba'
        assert 'bi-bell' not in out['larga'], 'y sale otra vez abajo'

    def test_y_el_buscador_dice_entre_cuantos_busca_de_verdad(self, client, admin):
        """El número del recuadro salía de la lista entera mientras la rejilla enseñaba otra:
        decía «busca entre 2050» sobre una lista de 2030."""
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        _login(client)
        out = self._cuadro(client, 'bi-boxes')
        assert str(len(out['larga'])) in out['html']


class TestLaDescripcionDeLasDeSerie:
    """Para qué es cada una de las once viaja por el catálogo de idiomas, como su nombre: escrita
    en la columna se congelaría en el idioma de quien creó la base."""

    def test_el_catalogo_dice_de_donde_sale(self, client, admin):
        _login(client)
        tipos = {t['slug']: t for t in client.get('/api/v1/host_types').get_json()['types']}
        assert tipos['nas']['desc_key'] == 'host_type_nas_desc'
        assert tipos['nas']['description'] == '', 'se ha escrito en la columna'

    def test_describirla_a_mano_no_la_renombra_ni_le_quita_la_clave(self, client, admin):
        """Describir no es renombrar. Sin esa distinción, escribir un renglón sobre «Servidor» lo
        dejaría en inglés para quien mira en castellano — que es el mismo fallo que ya tuvo el
        icono, y por el mismo sitio."""
        _login(client)
        nas = _uid(admin, 'nas')
        r = client.put(f'/api/v1/host_types/{nas}',
                       json={'name': 'NAS / Storage', 'description': 'Las dos cabinas del CPD'})
        assert r.status_code == 200
        fila = admin._host_types_store.get(nas)
        assert fila['description'] == 'Las dos cabinas del CPD'
        assert fila['label_key'] == 'host_type_nas', 'la ha dejado sin traducir'

    def test_y_la_pantalla_prefiere_la_escrita_aqui(self, client, admin):
        """Dibujado en node, que es donde se decide: desde que alguien la describe con sus
        palabras, eso es lo que quiere leer. Y una clase de serie sin traducir no puede enseñar
        `host_type_nas_desc` en la columna donde se espera una frase — `t()` devuelve la clave que
        se le dio cuando no la encuentra."""
        if not _node():
            pytest.skip('no node >= 16 on PATH')
        from tests.helpers import node_run, panel_bundle            # noqa: PLC0415
        _login(client)
        out = node_run(panel_bundle(client), """
            __out = {};
            __out.deSerie = _htDesc({desc_key: 'host_type_nas_desc', description: ''});
            __out.propia  = _htDesc({desc_key: 'host_type_nas_desc',
                                     description: 'Las dos cabinas del CPD'});
            __out.sinClave = _htDesc({description: ''});
            __out.claveQueNoExiste = _htDesc({desc_key: 'host_type_inventada_desc'});
        """)
        assert out['deSerie'] and out['deSerie'] != 'host_type_nas_desc'
        assert out['propia'] == 'Las dos cabinas del CPD'
        assert out['sinClave'] == ''
        assert out['claveQueNoExiste'] == '', 'enseñaría la clave en la columna de la frase'
