#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qué se hace con los activos de Freshservice, sin red y sin base de datos.

Lo único de esta importación que puede EQUIVOCARSE está en `lib/providers/freshservice/assets.py`:
qué es nuevo, qué es el mismo con otro nombre, qué no hay que tocar y de dónde sale la dirección
de una máquina. Todo eso se prueba con dos listas y ningún servidor, que es exactamente por lo que
decidir y hacer están en ficheros distintos.

Lo que se vigila aquí, y por qué cada cosa:

* **dónde vive la dirección de un activo** — Freshservice la mete en `type_fields` con el número
  del tipo pegado detrás, y leerla «por su nombre» devuelve un hueco en TODAS las instalaciones;
* que se empareje **por el identificador de allí** y no por el nombre;
* que lo que **tecleó una persona** se adopte en vez de duplicarse;
* que un emparejamiento **a mano** mande sobre lo deducido, y que uno imposible se rechace con
  su motivo en vez de hacerse a medias;
* y que lo que ya no está en el origen se **cuente** y no se borre.
"""

from __future__ import annotations

import io
import os
import sys

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.providers.freshservice import assets as fa                       # noqa: E402


def _activo(ident, nombre, *, tipo='7001', campos=None, **extra):
    """Un activo como los devuelve Freshservice: la ficha desnuda y sus `type_fields`."""
    return dict({'id': int(ident) * 100, 'display_id': int(ident), 'name': nombre,
                 'asset_type_id': int(tipo), 'type_fields': dict(campos or {})}, **extra)


TIPOS = [{'id': 7001, 'name': 'Server'}, {'id': 7002, 'name': 'Network Switch'}]


class TestDondeViveLaDireccionDeUnActivo:
    """**El fallo que no da ningún error.** Freshservice no devuelve `ip_address`: devuelve
    `ip_address_7000123456`, con el identificador del tipo de activo pegado detrás — y ese
    número es distinto en cada casa, así que no se puede escribir en ningún sitio.

    Un lector que pidiera el campo por su nombre encontraría un hueco SIEMPRE, en todas las
    instalaciones, y lo que se vería es una lista de dispositivos sin dirección: nada falla, nada
    avisa, y se investiga por el lado de la red.
    """

    def test_la_saca_de_type_fields_con_el_sufijo_del_tipo(self):
        a = _activo(1, 'SRV-01', campos={'ip_address_7000123456': '10.0.0.5'})
        assert fa.field(a, 'ip_address') == '10.0.0.5'

    def test_y_el_sufijo_no_es_el_del_propio_tipo_del_activo(self):
        """El número que llevan pegado es el del tipo que DEFINE el campo, que en su modelo es
        el padre — no el del activo. Buscar por `f'ip_address_{asset_type_id}'` acierta en la
        casa donde se probó y falla en la siguiente."""
        a = _activo(1, 'SRV-01', tipo='7099', campos={'ip_address_7001': '10.0.0.5'})
        assert fa.field(a, 'ip_address') == '10.0.0.5'

    def test_prueba_los_campos_en_orden_y_se_queda_con_el_primero_que_traiga_algo(self):
        a = _activo(1, 'SRV-01', campos={'ip_address_70': '', 'hostname_70': 'srv01.casa'})
        assert fa.field(a, *fa.ADDRESS_FIELDS) == 'srv01.casa'

    def test_el_nombre_del_activo_no_vale_como_direccion(self):
        """Se parece a un nombre de máquina lo bastante para tentar, y «Portátil de Juan» como
        dirección es un dispositivo en rojo para siempre. Sin dirección es una respuesta."""
        a = _activo(1, 'Portátil de Juan')
        assert fa.field(a, *fa.ADDRESS_FIELDS) == ''
        assert 'name' not in fa.ADDRESS_FIELDS

    def test_un_type_fields_que_no_es_un_diccionario_no_revienta(self):
        """Lo manda otro sistema. Un campo que llega como lista es una pantalla en blanco si
        esto levanta, y un hueco si no."""
        a = _activo(1, 'SRV-01')
        a['type_fields'] = ['vaya']
        assert fa.field(a, 'ip_address') == ''

    def test_tambien_mira_la_ficha_desnuda(self):
        """`name` y `asset_tag` viven fuera de `type_fields`, y el día que alguien tenga un
        Freshservice que devuelva `ip_address` arriba tiene que valer igual."""
        a = _activo(1, 'SRV-01', ip_address='192.168.1.1')
        assert fa.field(a, 'ip_address') == '192.168.1.1'


class TestQueClaseDeDispositivoEs:
    """Adivinada del nombre del tipo de activo, que lo escribe quien montó ese Freshservice —
    en su idioma. Por palabras y no por identificador: el número de un tipo es distinto en cada
    casa."""

    def test_lo_especifico_gana_a_lo_general(self):
        """«Servidor de virtualización» lleva dentro la palabra «servidor», y la lista se
        recorre en orden justamente por eso."""
        assert fa.device_type_for('Servidor de virtualización') == 'hypervisor'
        assert fa.device_type_for('Servidor de correo') == 'server'

    def test_en_los_dos_idiomas(self):
        assert fa.device_type_for('Network Switch') == 'switch'
        assert fa.device_type_for('Conmutador de planta') == 'switch'

    def test_los_acentos_no_deciden_nada(self):
        """Dos Freshservice de dos casas escriben «Cámara IP» y «Camara IP», y son la misma casa
        diciendo lo mismo. Comparando con acentos casaría uno de los dos y el otro no — en
        silencio, dejando la mitad de los dispositivos sin clase y sin nada que lo dijera."""
        assert fa.device_type_for('Cámara IP') == 'camera'
        assert fa.device_type_for('Camara IP') == 'camera'
        assert fa.device_type_for('Portátil de dirección') == 'workstation'

    def test_lo_que_no_se_parece_a_nada_se_queda_sin_clase(self):
        """«No lo sé» es una respuesta, y la pantalla sabe enseñar un dispositivo sin
        clasificar. Ponerle una etiqueta inventada es trabajo para quien la tenga que quitar."""
        assert fa.device_type_for('Silla de oficina') == ''
        assert fa.device_type_for('') == ''

    def test_las_clases_adivinadas_existen_de_verdad(self):
        """Adivinar hacia una clase que no existe se guarda como vacío —`_norm_device_type` la
        tira— así que apuntar a «nas» cuando ninguna instalación tiene «nas» sería adivinar para
        nada, en silencio.

        Contra la SEMILLA y no contra la tabla: es lo que tiene cualquier instalación recién
        creada, y es de lo único que se puede afirmar algo sin mirar una base de datos concreta.
        Quien borre «nas» a mano se queda sin esa adivinanza, que es su decisión."""
        from lib.core.devices.stores.types import SEED                   # noqa: PLC0415
        validos = {t['id'] for t in SEED}
        for nuestro, _palabras in fa.TYPE_HINTS:
            assert nuestro in validos, nuestro


class TestElegirQueClasesSeTraen:
    """Un inventario tiene «Monitor», «Silla» y «Licencia» entre los conmutadores, y traerlo
    entero para mirar doce son cuarenta viajes a su API. El catálogo de tipos es un recurso
    aparte y una sola llamada, así que se puede elegir ANTES de traer.

    Pero el filtro se le pide al origen y **no se depende de él**: la forma de ese filtro no es
    la misma en todos los planes, y uno que no lo entienda contesta la lista entera. Filtrar
    también lo que llega es lo que hace que las dos rutas enseñen lo mismo.
    """

    ASSETS = [_activo(1, 'SRV-01', tipo='7001'), _activo(2, 'SW-01', tipo='7002'),
              _activo(3, 'MON-01', tipo='7003')]

    def test_se_queda_con_los_de_esas_clases(self):
        fuera = fa.only_types(self.ASSETS, ['7002'])
        assert [f['name'] for f in fuera] == ['SW-01']

    def test_varias_clases_a_la_vez(self):
        fuera = fa.only_types(self.ASSETS, ['7001', '7002'])
        assert [f['name'] for f in fuera] == ['SRV-01', 'SW-01']

    def test_sin_elegir_ninguna_estan_todas(self):
        """Que es lo que significa no haber elegido, y lo que esto hacía antes de tener el paso.
        Un filtro vacío que no devolviera nada sería una pantalla en blanco por no pulsar."""
        assert len(fa.only_types(self.ASSETS, [])) == 3
        assert len(fa.only_types(self.ASSETS, None)) == 3

    def test_los_numeros_y_las_cadenas_son_lo_mismo(self):
        """El identificador viaja por una URL —así que llega como texto— y en la ficha del activo
        es un número. Comparándolos sin igualar, el filtro no casa NUNCA y la pantalla sale
        vacía: nada falla, y parece que no hay activos de ese tipo."""
        assert len(fa.only_types([{'asset_type_id': 7001}], ['7001'])) == 1
        assert len(fa.only_types([{'asset_type_id': '7001'}], [7001])) == 1


class TestElPlan:
    """Qué se haría con cada activo. Cuatro respuestas, y las cuatro se enseñan antes de nada."""

    def test_uno_que_no_esta_se_crea(self):
        [p] = fa.build([_activo(1, 'SRV-01', campos={'ip_address_70': '10.0.0.5'})], [], TIPOS)
        assert (p['action'], p['external_id'], p['address']) == ('create', '1', '10.0.0.5')
        assert p['device_type'] == 'server', 'la clase adivinada no viaja con el plan'

    def test_uno_que_ya_vino_de_aqui_y_no_cambio_no_viaja(self):
        """Una importación que reescribe cuatrocientas fichas idénticas llena el registro de
        auditoría de cambios que no cambian nada."""
        devices = [{'uid': 'u1', 'name': 'SRV-01', 'address': '10.0.0.5', 'description': '',
                  'source': 'freshservice', 'external_id': '1'}]
        [p] = fa.build([_activo(1, 'SRV-01', campos={'ip_address_70': '10.0.0.5'})],
                       devices, TIPOS)
        assert p['action'] == 'same'

    def test_uno_que_cambio_de_direccion_se_corrige_y_dice_de_que_a_que(self):
        devices = [{'uid': 'u1', 'name': 'SRV-01', 'address': '10.0.0.5', 'description': '',
                  'source': 'freshservice', 'external_id': '1'}]
        [p] = fa.build([_activo(1, 'SRV-01', campos={'ip_address_70': '10.0.0.9'})],
                       devices, TIPOS)
        assert p['action'] == 'update'
        assert p['was']['address'] == '10.0.0.5', 'sin el «antes» no se puede mirar el cambio'

    def test_se_empareja_por_el_identificador_y_no_por_el_nombre(self):
        """Renombrar un activo en Freshservice crearía aquí un segundo y dejaría el primero
        huérfano, sin que nada lo dijera."""
        devices = [{'uid': 'u1', 'name': 'SRV-01', 'address': '', 'description': '',
                  'source': 'freshservice', 'external_id': '1'}]
        [p] = fa.build([_activo(1, 'SRV-NUEVO')], devices, TIPOS)
        assert (p['action'], p['uid']) == ('update', 'u1')

    def test_lo_que_tecleo_una_persona_se_adopta_en_vez_de_duplicarse(self):
        """El caso real: la lista se tecleó a mano antes de conectar esto."""
        devices = [{'uid': 'u9', 'name': 'srv-01', 'address': '', 'description': '',
                  'source': '', 'external_id': ''}]
        [p] = fa.build([_activo(1, 'SRV-01')], devices, TIPOS)
        assert (p['action'], p['uid']) == ('adopt', 'u9')

    def test_uno_que_ya_mantiene_OTRO_origen_no_se_adopta(self):
        """Adoptar por el nombre sólo vale para lo que no es de nadie. Uno que mantiene otro
        sistema es uno que ese sistema va a volver a escribir."""
        devices = [{'uid': 'u9', 'name': 'SRV-01', 'address': '', 'description': '',
                  'source': 'otro', 'external_id': 'x'}]
        [p] = fa.build([_activo(1, 'SRV-01')], devices, TIPOS)
        assert p['action'] == 'create'

    def test_sin_nombre_o_sin_identidad_no_es_un_dispositivo(self):
        assert fa.build([_activo(1, '   '), {'name': 'x'}], [], TIPOS) == []

    def test_sin_los_tipos_sigue_habiendo_plan(self):
        """El catálogo de tipos es un extra: una clave sin permiso para leerlo no puede impedir
        traer cuatrocientas máquinas por no poder decir cuáles son conmutadores."""
        [p] = fa.build([_activo(1, 'SRV-01')], [], None)
        assert (p['action'], p['type_name'], p['device_type']) == ('create', '', '')

    def test_los_recuentos_cuadran(self):
        plan = fa.build([_activo(1, 'A'), _activo(2, 'B')], [], TIPOS)
        assert fa.counts(plan) == {'create': 2, 'update': 0, 'adopt': 0, 'same': 0}


class TestLoQueDeVerdadSeAplica:
    """Lo elegido, con los emparejamientos a mano puestos — y lo que no se puede hacer,
    contado."""

    DEVICES = [{'uid': 'u1', 'name': 'srv-barcelona', 'address': '', 'description': '',
              'source': '', 'external_id': ''},
             {'uid': 'u2', 'name': 'otro', 'address': '', 'description': '',
              'source': 'freshservice', 'external_id': '99'}]

    def test_lo_no_elegido_no_viaja(self):
        plan = fa.build([_activo(1, 'A'), _activo(2, 'B')], [], TIPOS)
        fuera, rechazos = fa.select(plan, pick=['1'], devices=[])
        assert [p['external_id'] for p in fuera] == ['1']
        assert rechazos == []

    def test_un_emparejamiento_a_mano_convierte_la_fila_en_una_adopcion(self):
        """Es la mitad de para lo que sirve la pantalla: que «SRV-BCN-01» de allí y
        «srv-barcelona» de aquí son la misma máquina lo sabe quien lo mira, y ningún parecido de
        nombres lo va a decir nunca."""
        plan = fa.build([_activo(1, 'SRV-BCN-01')], self.DEVICES, TIPOS)
        fuera, rechazos = fa.select(plan, pick=['1'], link={'1': 'u1'}, devices=self.DEVICES)
        assert (fuera[0]['action'], fuera[0]['uid']) == ('adopt', 'u1')
        assert rechazos == []

    def test_emparejar_con_uno_ya_atado_a_otro_activo_se_rechaza_con_su_motivo(self):
        """Dos no pueden compartir uno: el segundo le pisaría el nombre al primero en cada
        importación, y la ficha iría cambiando de nombre sola."""
        plan = fa.build([_activo(1, 'A')], self.DEVICES, TIPOS)
        fuera, rechazos = fa.select(plan, pick=['1'], link={'1': 'u2'}, devices=self.DEVICES)
        assert fuera == []
        assert rechazos == [{'name': 'A', 'reason': 'fs_devices_link_taken'}]

    def test_emparejar_con_uno_que_ya_no_existe_se_rechaza_con_su_motivo(self):
        """Se borró entre mirar y aceptar. Es un rechazo y no un silencio: se pidió y no salió."""
        plan = fa.build([_activo(1, 'A')], self.DEVICES, TIPOS)
        fuera, rechazos = fa.select(plan, pick=['1'], link={'1': 'fantasma'}, devices=self.DEVICES)
        assert (fuera, [r['reason'] for r in rechazos]) == ([], ['fs_devices_link_gone'])

    def test_uno_elegido_al_que_no_hay_nada_que_hacerle_no_es_un_rechazo(self):
        """No se eligió mal: es que ya estaba bien. Contarlo como fallo diría que algo salió mal
        cuando no había nada que hacer."""
        devices = [{'uid': 'u1', 'name': 'A', 'address': '', 'description': '',
                  'source': 'freshservice', 'external_id': '1'}]
        plan = fa.build([_activo(1, 'A')], devices, TIPOS)
        fuera, rechazos = fa.select(plan, pick=['1'], devices=devices)
        assert (fuera, rechazos) == ([], [])


class TestLoQueYaNoEstaEnElOrigen:
    """No se borra. De un dispositivo cuelgan sus perfiles de conexión, sus módulos y meses de
    historial, y un activo desaparece del origen tanto por una baja real como por un filtro mal
    puesto."""

    def test_se_cuenta_el_que_vino_de_aqui_y_ya_no_esta(self):
        devices = [{'uid': 'u1', 'name': 'viejo', 'source': 'freshservice', 'external_id': '7'}]
        assert [h['uid'] for h in fa.orphans([_activo(1, 'A')], devices)] == ['u1']

    def test_y_no_se_cuenta_el_que_nunca_vino_de_aqui(self):
        """Un dispositivo tecleado en esta casa no es un huérfano de Freshservice, y decir que
        lo es invita a borrarlo."""
        devices = [{'uid': 'u1', 'name': 'de aqui', 'source': '', 'external_id': ''}]
        assert fa.orphans([], devices) == []

    def test_se_reconoce_por_el_mismo_identificador_con_el_que_se_importo(self):
        """`display_id` al traer y `display_id` al comparar. Con `id` en un sitio y `display_id`
        en el otro, TODOS los importados saldrían como huérfanos en cada vista previa."""
        devices = [{'uid': 'u1', 'name': 'A', 'source': 'freshservice', 'external_id': '1'}]
        assert fa.orphans([_activo(1, 'A')], devices) == []


class TestLaListaDeCamposMantenidosEsUnaSola:
    """`MANAGED` decide dos cosas a la vez: qué compara el plan para decir «ha cambiado» y qué se
    niega a que se teclee la ruta de guardar. Dos copias serían un campo que la pantalla deja
    escribir y la importación revierte sin decirlo — o al revés, uno bloqueado que nadie
    actualiza nunca."""

    def test_la_ruta_de_guardar_protege_exactamente_esos_campos(self):
        ruta = io.open(os.path.join(SRC, 'lib', 'core', 'devices', 'routes.py'),
                       encoding='utf-8').read()
        trozo = ruta.split('_ORIGIN_FIELDS = (', 1)[1].split(')\n', 1)[0]
        for campo in fa.MANAGED:
            assert f"'{campo}'" in trozo, f'{campo} se importa y se puede teclear encima'
