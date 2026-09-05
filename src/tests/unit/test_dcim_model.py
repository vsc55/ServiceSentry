#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El inventario físico: dónde está cada cosa, de quién es, y quién puede verla.

Tres propiedades sostienen este dominio, y las tres se rompen en silencio:

* **La contención y la pertenencia son dos árboles.** Un holding comparte datacenter, sala y
  rack entre las sociedades del grupo: en el mismo armario hay 2U de una, 4U de otra y un switch
  del propio departamento de IT. Si la empresa fuese la raíz de la contención, ese caso —el
  normal en cuanto hay más de una sociedad— sería inexpresable.
* **Un rack contiene items, y algunos items son hosts**, nunca al revés. Un panel de parcheo
  ocupa 1U y no es un host; un chasis de blades ocupa 7U y contiene ocho cosas que sí lo son.
* **Un rack compartido rompe que ver un sitio sea ver lo que hay dentro.** El de la filial B
  tiene que ver que la U 12 está ocupada —si no, planificar es imposible— y no puede ver de
  quién es. Ahí es donde una fuga se cuela sin que nadie la note, porque el mapa *se ve bien*.

Sin app, sin HTTP: se construye un store sobre una BD SQLite en memoria y se le pregunta.
"""

from __future__ import annotations

import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim import owners                                    # noqa: E402
from lib.core.dcim import service                                   # noqa: E402
from lib.core.dcim.store import DcimStore                           # noqa: E402
from lib.db import get_connector                                    # noqa: E402


@pytest.fixture()
def store():
    db = get_connector({'type': 'sqlite', 'path': ':memory:'})
    yield DcimStore(db)
    try:
        db.close()
    except Exception:                           # pylint: disable=broad-except
        pass


@pytest.fixture()
def fleet(store):
    """Una sede, una sala, un rack, y dos empresas — el caso del holding, en pequeño."""
    it = store.orgs.create({'name': 'IT del grupo', 'short': 'IT'})
    filial = store.orgs.create({'name': 'Filial B', 'short': 'B'})
    site = store.sites.create({'name': 'DC Norte', 'operator_uid': it})
    room = store.rooms.create({'site_uid': site, 'name': 'Sala 1'})
    rack = store.racks.create({'room_uid': room, 'name': 'R3', 'u_height': 42})
    return {'it': it, 'filial': filial, 'site': site, 'room': room, 'rack': rack}


# ══ La contención ═══════════════════════════════════════════════════════════════════════

class TestTodoEstaEnUnSitio:

    def test_la_cadena_sube_hasta_la_sede(self, store, fleet):
        item = store.items.create({'rack_uid': fleet['rack'], 'u_start': 12, 'u_height': 1})
        assert store.chain_of('item', item) == [
            ('item', item), ('rack', fleet['rack']),
            ('room', fleet['room']), ('site', fleet['site'])]

    def test_y_un_huerfano_termina_la_cadena_en_vez_de_reventar(self, store):
        """Un rack cuya sala borraron es un estado real de los datos. La respuesta a «de quién
        es» pasa a ser «nadie lo sabe», que no es lo mismo que un 500."""
        rack = store.racks.create({'room_uid': 'no-existe', 'name': 'suelto'})
        assert store.chain_of('rack', rack) == [('rack', rack), ('room', 'no-existe')]

    def test_los_items_de_un_rack_son_los_suyos(self, store, fleet):
        a = store.items.create({'rack_uid': fleet['rack'], 'u_start': 1})
        otro = store.racks.create({'room_uid': fleet['room'], 'name': 'R4'})
        store.items.create({'rack_uid': otro, 'u_start': 1})
        assert [i['uid'] for i in store.items_of(fleet['rack'])] == [a]


class TestUnRackContieneItemsYAlgunosSonHosts:

    def test_un_item_no_necesita_host(self, store, fleet):
        """Un panel de parcheo ocupa 1U y no contesta a nada."""
        uid = store.items.create({'rack_uid': fleet['rack'], 'u_start': 40,
                                  'label': 'Patch 1-24'})
        assert store.items.get(uid)['host_uid'] == ''

    def test_y_el_que_lo_tiene_se_encuentra_por_el(self, store, fleet):
        uid = store.items.create({'rack_uid': fleet['rack'], 'u_start': 2,
                                  'host_uid': 'h-db03'})
        assert store.item_of_host('h-db03')['uid'] == uid
        assert store.item_of_host('h-que-no') is None


# ══ La U, que es donde el modelo se gana el sueldo ══════════════════════════════════════

class TestLaCaraEsParteDeLaPosicion:

    def test_un_equipo_completo_ocupa_las_dos_caras(self, store, fleet):
        store.items.create({'rack_uid': fleet['rack'], 'u_start': 12, 'u_height': 2,
                            'face': 'full'})
        taken = store.occupancy(fleet['rack'])
        assert sorted(taken['front']) == [12, 13]
        assert sorted(taken['rear']) == [12, 13]

    def test_y_un_panel_trasero_deja_libre_el_frente(self, store, fleet):
        store.items.create({'rack_uid': fleet['rack'], 'u_start': 20, 'face': 'rear'})
        taken = store.occupancy(fleet['rack'])
        assert 20 in taken['rear'] and 20 not in taken['front']
        # …y por eso mismo cabe algo por delante en esa misma U.
        assert store.fits(fleet['rack'], 20, 1, 'front') is True
        assert store.fits(fleet['rack'], 20, 1, 'rear') is False
        assert store.fits(fleet['rack'], 20, 1, 'full') is False


class TestDosCosasNoCabenEnUnaU:
    """No es un error de datos como lo es una columna que falta: es un dibujo de un armario que
    no puede existir, y toda cuenta sacada de él queda mal. El sitio más barato para negarlo es
    antes de escribirlo."""

    def test_lo_que_se_solapa_no_cabe(self, store, fleet):
        store.items.create({'rack_uid': fleet['rack'], 'u_start': 10, 'u_height': 4})
        assert store.fits(fleet['rack'], 13, 1, 'full') is False
        assert store.fits(fleet['rack'], 14, 1, 'full') is True

    def test_lo_que_se_sale_del_rack_tampoco(self, store, fleet):
        assert store.fits(fleet['rack'], 41, 4, 'full') is False   # 42U: 41+4 se pasa
        assert store.fits(fleet['rack'], 0, 1, 'full') is False     # no hay U 0
        assert store.fits(fleet['rack'], 42, 1, 'full') is True

    def test_ni_en_un_rack_que_no_existe(self, store):
        assert store.fits('no-hay-rack', 1, 1, 'full') is False

    def test_una_cara_inventada_no_cabe_en_ninguna_parte(self, store, fleet):
        assert store.fits(fleet['rack'], 1, 1, 'de-lado') is False

    def test_y_moverse_a_donde_ya_esta_uno_mismo_sigue_cabiendo(self, store, fleet):
        """Sin esto, mover un equipo una U choca consigo mismo y no se puede mover nada."""
        uid = store.items.create({'rack_uid': fleet['rack'], 'u_start': 10, 'u_height': 2})
        assert store.fits(fleet['rack'], 10, 2, 'full') is False
        assert store.fits(fleet['rack'], 10, 2, 'full', ignore=uid) is True
        assert store.fits(fleet['rack'], 11, 2, 'full', ignore=uid) is True


# ══ La pertenencia ══════════════════════════════════════════════════════════════════════

class TestDeQuienEsCadaCosa:

    def _owner(self, store, scope, uid):
        return owners.owner_of(store.chain_of(scope, uid), store.owners_map())

    def test_lo_que_nadie_ha_dicho_no_es_de_nadie(self, store, fleet):
        item = store.items.create({'rack_uid': fleet['rack'], 'u_start': 1})
        assert self._owner(store, 'item', item) == ''

    def test_se_hereda_del_contenedor(self, store, fleet):
        store.set_owner('site', fleet['site'], fleet['it'])
        item = store.items.create({'rack_uid': fleet['rack'], 'u_start': 1})
        assert self._owner(store, 'item', item) == fleet['it']
        assert self._owner(store, 'rack', fleet['rack']) == fleet['it']

    def test_y_lo_dicho_en_el_item_manda_sobre_lo_heredado(self, store, fleet):
        """El caso del holding: el rack es del departamento de IT y dentro hay 2U de la
        filial."""
        store.set_owner('site', fleet['site'], fleet['it'])
        mio = store.items.create({'rack_uid': fleet['rack'], 'u_start': 1})
        suyo = store.items.create({'rack_uid': fleet['rack'], 'u_start': 5, 'u_height': 2})
        store.set_owner('item', suyo, fleet['filial'])
        assert self._owner(store, 'item', mio) == fleet['it']
        assert self._owner(store, 'item', suyo) == fleet['filial']

    def test_dejar_de_decirlo_es_volver_a_heredar_y_no_ser_de_nadie(self, store, fleet):
        store.set_owner('site', fleet['site'], fleet['it'])
        item = store.items.create({'rack_uid': fleet['rack'], 'u_start': 1})
        store.set_owner('item', item, fleet['filial'])
        store.set_owner('item', item, '')
        assert self._owner(store, 'item', item) == fleet['it']

    def test_una_cosa_solo_tiene_un_dueno_dicho(self, store, fleet):
        store.set_owner('rack', fleet['rack'], fleet['it'])
        store.set_owner('rack', fleet['rack'], fleet['filial'])
        assert self._owner(store, 'rack', fleet['rack']) == fleet['filial']
        assert len(store.owners.list()) == 1

    def test_un_host_suelto_tambien_es_de_alguien(self, store, fleet):
        """Una VM, un VIP o una máquina encima de una mesa no están en ningún rack."""
        store.set_owner('host', 'h-vip', fleet['filial'])
        assert self._owner(store, 'host', 'h-vip') == fleet['filial']

    def test_un_ambito_inventado_no_se_guarda(self, store, fleet):
        assert store.set_owner('planeta', 'marte', fleet['it']) is False
        assert store.owners.list() == []

    def test_y_borrar_algo_se_lleva_su_pertenencia(self, store, fleet):
        item = store.items.create({'rack_uid': fleet['rack'], 'u_start': 1})
        store.set_owner('item', item, fleet['filial'])
        store.items.delete(item)
        store.forget_scope('item', item)
        assert store.owners_map() == {}


# ══ Y quién puede ver qué, que es donde se cuela una fuga ═══════════════════════════════

class TestElRackCompartidoEsElCasoDuro:
    """Las reglas —quien lo ve todo, quien tiene una empresa concedida, lo que nadie reclama—
    se comprueban donde viven ahora, que es el registro de empresas del core
    (`tests/unit/test_orgs_model.py`). Lo que se queda aquí es lo único que es de un armario:
    que de un equipo ajeno solo sobreviva que existe y que ocupa."""

    def test_un_item_ajeno_ocupa_y_no_dice_nada_mas(self):
        item = {'uid': 'i1', 'rack_uid': 'r1', 'u_start': 12, 'u_height': 2, 'face': 'full',
                'host_uid': 'h-db03', 'label': 'DB03', 'serial': 'ABC123',
                'type_uid': 't-dell-r640', 'description': 'nómina'}
        out = owners.opaque(item)
        assert out == {'uid': 'i1', 'rack_uid': 'r1', 'u_start': 12, 'u_height': 2,
                       'face': 'full', 'foreign': True}

    def test_y_nada_de_lo_que_identifica_sobrevive(self):
        """Escrito como lista de lo que se QUEDA y no de lo que se quita: el día que se añade
        una columna, una lista de exclusiones la deja pasar —que es una fuga— y una de
        inclusiones la omite —que es un hueco en una pantalla. Solo una de las dos es un
        problema de seguridad."""
        item = {'uid': 'i1', 'rack_uid': 'r1', 'u_start': 1, 'u_height': 1, 'face': 'full',
                'host_uid': 'h', 'label': 'x', 'serial': 's', 'asset': 'a', 'type_uid': 't',
                'description': 'd', 'created_at': 'ayer', 'updated_by': 'juan',
                'columna_que_alguien_anada_manana': 'secreto'}
        out = owners.opaque(item)
        assert 'columna_que_alguien_anada_manana' not in out
        for leak in ('host_uid', 'label', 'serial', 'asset', 'type_uid', 'description',
                     'updated_by'):
            assert leak not in out, leak

# ══ Y las banderas, en lista cerrada ════════════════════════════════════════════════════

class TestLasBanderasDelDominio:
    """La lista está cerrada a propósito: una bandera nueva hay que argumentarla aquí, no
    aparecer. Es lo que hizo la de infraestructura tres veces seguidas."""

    def test_son_estas_seis(self):
        """Fueron ocho. Las dos que faltan —ver lo de todas las empresas y decidir de quién es
        cada cosa— no eran de esta sección: la misma sociedad que paga el armario tiene usuarios
        en el directorio, así que viven en `lib.core.orgs` y se llaman `orgs_*`."""
        from lib.core.dcim.manifest import MODULE_PERMISSIONS
        flags = [p['flag'] for p in MODULE_PERMISSIONS['permissions']]
        assert flags == ['dcim_view', 'dcim_edit',
                         'dcim_cable_edit', 'dcim_catalog_view', 'dcim_catalog_manage',
                         'dcim_build_edit']
        assert not any(f.startswith('orgs_') for f in flags), 'una bandera del core aquí'

    def test_y_ninguna_toca_el_registro_de_dispositivos(self):
        """Este dominio guarda lo que la gente sabe. No alcanza a un aparato, no alerta, y no
        abre nada del registro — direcciones y credenciales siguen tras `devices_*`."""
        from lib.core.dcim.manifest import MODULE_PERMISSIONS
        flags = [p['flag'] for p in MODULE_PERMISSIONS['permissions']]
        assert not any(f.startswith('devices_') or f.startswith('infra_') for f in flags)

    def test_decir_de_quien_es_algo_no_se_regala_con_ningun_rol(self):
        """En un grupo esto decide qué se le factura a qué sociedad y quién puede ver qué, que
        no es la misma autoridad que ordenar un armario."""
        from lib.core.dcim.manifest import MODULE_PERMISSIONS
        from lib.core.orgs.manifest import MODULE_PERMISSIONS as ORG_PERMS
        roles = {p['flag']: p['roles'] for p in MODULE_PERMISSIONS['permissions']}
        org_roles = {p['flag']: p['roles'] for p in ORG_PERMS['permissions']}
        assert org_roles['orgs_edit'] == ()
        assert 'viewer' not in roles['dcim_edit']
        # …y lo que es una lectura sí llega a quien solo mira.
        assert 'viewer' in roles['dcim_view'] and 'viewer' in org_roles['orgs_all_view']

    def test_nada_se_declara_para_la_auditoria_sin_que_alguien_lo_escriba(self):
        """La podredumbre que más dura: una declaración de un evento que nadie emite, porque
        nadie busca un nombre que no existe.

        Los cuatro entraron antes que sus emisores y el guardián del panel los echó en el acto;
        volvieron con las rutas que los escriben. Lo que se fija aquí es esa regla, no la lista:
        cada evento declarado tiene que aparecer en el código de este dominio."""
        import os
        from lib.core.dcim.manifest import AUDIT_EVENTS
        pkg = os.path.join(SRC, 'lib', 'core', 'dcim')
        code = ''
        for name in sorted(os.listdir(pkg)):
            if name.endswith('.py'):
                with open(os.path.join(pkg, name), encoding='utf-8') as fh:
                    code += fh.read()
        for entry in AUDIT_EVENTS:
            assert "'%s'" % entry['key'] in code, entry['key']
            assert entry['severity'] in ('muted', 'info', 'warning', 'danger')

# ══ El estado en vivo, volcado sobre el inventario ══════════════════════════════════════

class TestUnItemSinHostNoEstaBien:
    """La trampa de este dominio entero. Un rack lleno de paneles de parcheo **no puede salir
    verde**: no es que esté bien, es que nadie lo mira — y un muro verde es exactamente lo que
    alguien mira de un vistazo desde la puerta.

    El panel ya distingue «sin estado» de «bien» en el color de la flota; aquí importa más,
    porque aquí es donde se decide si hace falta bajar al CPD."""

    def test_sin_host_no_hay_estado(self):
        from lib.core.dcim import service
        assert service.item_state({'uid': 'i1'}, {'h': 'ok'}) == ''

    def test_con_host_pero_sin_checks_tampoco(self):
        """Un servidor apagado que sigue atornillado ocupa su U y no reporta nada."""
        from lib.core.dcim import service
        assert service.item_state({'host_uid': 'h9'}, {'h1': 'ok'}) == ''

    def test_y_con_host_es_el_de_su_maquina(self):
        from lib.core.dcim import service
        assert service.item_state({'host_uid': 'h1'}, {'h1': 'error'}) == 'error'


class TestUnRackEsLoPeorQueTieneDentro:

    def test_lo_peor_manda(self):
        from lib.core.dcim import service
        assert service.worst(['ok', 'warning', 'error']) == 'error'
        assert service.worst(['ok', 'warning']) == 'warning'
        assert service.worst(['ok', '']) == 'ok'
        assert service.worst(['', '']) == ''
        assert service.worst([]) == ''

    def test_y_el_recuento_separa_lo_roto_de_lo_no_vigilado(self):
        """Son dos cosas distintas y se cuentan aparte: cuarenta paneles de parcheo sin vigilar
        no son motivo de nada; cuarenta SERVIDORES sin vigilar son una pregunta."""
        from lib.core.dcim import service
        items = [{'host_uid': 'a'}, {'host_uid': 'b'}, {'host_uid': 'c'}, {'uid': 'panel'}]
        roll = service.rack_roll(items, {'a': 'error', 'b': 'ok', 'c': 'warning'})
        # `passive` se añadió con los roles: lo que no contesta POR NATURALEZA deja de
        # contarse entre los desatendidos. Aquí no hay ninguno, y eso también es un dato.
        assert roll == {'state': 'error', 'total': 4, 'bad': 2, 'unwatched': 1,
                        'passive': 0}

    def test_un_rack_de_paneles_no_sale_verde(self):
        from lib.core.dcim import service
        roll = service.rack_roll([{'uid': 'p1'}, {'uid': 'p2'}], {})
        assert roll['state'] == '' and roll['unwatched'] == 2

    def test_y_lo_ajeno_ocupa_pero_no_cuenta_como_estado(self):
        """Un item ajeno llega sin `host_uid` —eso es lo que significa opaco— así que suma como
        una cosa que ocupa sitio y no aporta ningún estado. Que es exactamente lo que se puede
        decir de él."""
        from lib.core.dcim import owners, service
        ajeno = owners.opaque({'uid': 'x', 'rack_uid': 'r', 'u_start': 1, 'u_height': 1,
                               'face': 'full', 'host_uid': 'h-secreto'})
        roll = service.rack_roll([ajeno, {'host_uid': 'mio'}], {'h-secreto': 'error',
                                                                'mio': 'ok'})
        assert roll['state'] == 'ok', 'el fallo del vecino se coló en mi rack'
        assert roll['total'] == 2 and roll['unwatched'] == 1


class TestLoLibreEsDeTodos:

    def test_cuenta_las_u_libres_por_cara(self):
        from lib.core.dcim import service
        free = service.free_units({'u_height': 10},
                                  {'front': {1: 'a', 2: 'a'}, 'rear': {1: 'a', 2: 'a', 9: 'b'}})
        assert free['front'] == [3, 4, 5, 6, 7, 8, 9, 10]
        assert free['rear'] == [3, 4, 5, 6, 7, 8, 10]
        assert free['count'] == 8 and free['height'] == 10


class TestElVuelcoCuentaSoloLoQueSePuedeVer:
    """Un rack diciendo «3 mal» de los que ninguno es tuyo es una enumeración de la flota ajena
    por la puerta de atrás — la misma forma que la auditoría IDOR de 2026-05."""

    def test_lo_ajeno_no_llega_al_rack_ni_a_la_sala_ni_a_la_sede(self, store, fleet):
        from lib.core.dcim import service
        mio = store.items.create({'rack_uid': fleet['rack'], 'u_start': 1,
                                  'host_uid': 'h-mio'})
        suyo = store.items.create({'rack_uid': fleet['rack'], 'u_start': 5,
                                   'host_uid': 'h-suyo'})
        store.set_owner('item', mio, fleet['filial'])
        store.set_owner('item', suyo, fleet['it'])
        statuses = {'h-mio': 'ok', 'h-suyo': 'error'}
        said = store.owners_map()

        # Quien lo ve todo ve el fallo…
        todo = service.tree_roll(store, statuses, said, None)
        assert todo['rack'][fleet['rack']]['state'] == 'error'
        assert todo['site'][fleet['site']]['state'] == 'error'

        # …y quien solo tiene la filial ve su rack en verde, porque lo suyo está bien.
        solo_b = service.tree_roll(store, statuses, said, {fleet['filial']})
        assert solo_b['rack'][fleet['rack']]['state'] == 'ok'
        assert solo_b['rack'][fleet['rack']]['total'] == 1
        assert solo_b['site'][fleet['site']]['state'] == 'ok', (
            'el fallo del vecino subió hasta la sede')

    def test_y_sin_ninguna_empresa_no_se_ve_ningun_estado(self, store, fleet):
        from lib.core.dcim import service
        store.set_owner('site', fleet['site'], fleet['it'])
        store.items.create({'rack_uid': fleet['rack'], 'u_start': 1, 'host_uid': 'h'})
        roll = service.tree_roll(store, {'h': 'error'}, store.owners_map(), set())
        # Ni siquiera un vuelco vacío: la sede es de una empresa que este lector no tiene, así
        # que no se recorre — la misma regla que hace que no aparezca en el listado. Devolver
        # un rack en blanco sería contar algo que la pantalla del árbol ni siquiera enseña, y
        # dos pantallas discrepando sobre la misma flota es peor que una que no dice nada.
        assert roll['rack'] == {} and roll['room'] == {} and roll['site'] == {}

# ══ Los mástiles, que son lo que decide si algo entra ═══════════════════════════════════

class TestLoQueDecideSiUnServidorEntra:
    """**No es el fondo del armario.** Es la distancia entre mástiles —donde se atornillan los
    raíles— más lo que quede detrás del trasero para los cables. Un armario de 1000 mm con los
    mástiles mal puestos admite menos que uno de 800 bien puestos, y esa es exactamente la
    compra que sale mal."""

    HOLGADO = {'depth_mm': 1000, 'rail_front_mm': 60, 'rail_depth_mm': 720,
               'rail_rear_mm': 200}
    JUSTO = {'depth_mm': 800, 'rail_front_mm': 50, 'rail_depth_mm': 600, 'rail_rear_mm': 90}

    def test_los_tramos_se_leen_por_separado(self):
        from lib.core.dcim import service
        d = service.rack_depths(self.HOLGADO)
        assert (d['front'], d['mount'], d['rear']) == (60, 720, 200)

    def test_el_descuadre_se_dice_y_no_se_corrige(self):
        """Lo que alguien midió con un metro y lo que dice la suma son dos cosas."""
        from lib.core.dcim import service
        assert service.rack_depths(self.HOLGADO)['mismatch'] == 20
        assert service.rack_depths(self.HOLGADO)['total'] == 1000, 'le ha cambiado el fondo'

    def test_y_sin_los_dos_datos_no_hay_descuadre_sino_un_hueco(self):
        """Sin fondo declarado no hay nada con lo que comparar: eso no es una discrepancia, es
        un dato que nadie ha escrito."""
        from lib.core.dcim import service
        assert service.rack_depths({'rail_depth_mm': 700})['mismatch'] == 0
        assert service.rack_depths({'depth_mm': 1000})['mismatch'] == 0

    def test_un_servidor_normal_entra_en_un_rack_holgado(self):
        from lib.core.dcim import service
        out = service.fits_depth(self.HOLGADO, 750)
        assert out['known'] and out['fits'] and out['spare'] == 95

    def test_y_el_mismo_servidor_no_entra_en_el_justo(self):
        """El de 800 mm tiene MENOS sitio útil que el de 1000, que es el caso que hay que poder
        ver antes de comprar."""
        from lib.core.dcim import service
        out = service.fits_depth(self.JUSTO, 750)
        assert out['known'] and not out['fits']

    def test_entrar_no_es_caber(self):
        """Un equipo puede llegar de mástil a fondo y no dejar sitio para los cables. La puerta
        trasera no cierra, y eso se descubre con el equipo ya montado."""
        from lib.core.dcim import service
        out = service.fits_depth(self.HOLGADO, 900)
        assert not out['fits'] and out['why'] == 'dcim_depth_no_cables'
        # …y lo que directamente no llega se dice de otra forma, porque es otro problema.
        assert service.fits_depth(self.HOLGADO, 1200)['why'] == 'dcim_depth_too_deep'

    def test_sin_una_de_las_dos_medidas_no_se_contesta_ni_que_si_ni_que_no(self):
        """Un «cabe» dicho sin saber el fondo del armario es peor que el silencio: alguien
        compra con él."""
        from lib.core.dcim import service
        assert service.fits_depth(self.HOLGADO, 0)['known'] is False
        assert service.fits_depth({'depth_mm': 1000}, 750)['known'] is False

    def test_el_hueco_para_cables_se_puede_discutir(self):
        """No es una norma, es la costumbre — así que se pasa en la llamada en vez de estar
        escrita dentro de la respuesta."""
        from lib.core.dcim import service
        assert service.fits_depth(self.HOLGADO, 900, clearance_mm=0)['fits'] is True


class TestLaNumeracionDelRack:
    """De abajo arriba o al revés. Equivocarse manda a alguien al otro extremo del armario a las
    tres de la mañana, y el dibujo ya lo respetaba… pero no había forma de decirlo."""

    def test_es_una_columna_y_no_una_suposicion(self, store, fleet):
        rack = store.racks.create({'room_uid': fleet['room'], 'name': 'R-invertido',
                                   'u_height': 42, 'desc_units': 1})
        assert store.racks.get(rack)['desc_units'] == 1

    def test_y_por_defecto_la_U1_esta_abajo(self, store, fleet):
        rack = store.racks.create({'room_uid': fleet['room'], 'name': 'R-normal'})
        assert store.racks.get(rack)['desc_units'] == 0

# ══ Por dónde se llega a un rack ════════════════════════════════════════════════════════

class TestElAccesoEsUnHechoDelSitio:
    """No un tipo de armario. Dos racks idénticos, uno en medio de un pasillo y otro colgado en
    la pared, no se manejan igual — y la diferencia es dónde están, no qué son. Las colocaciones
    corrientes son un atajo de la pantalla para rellenar el hecho, no lo que se guarda."""

    def test_lo_no_dicho_es_todo_accesible_y_no_nada(self):
        """Un inventario que se está entrando tiene cientos de racks sin este dato. Tratarlos
        como inaccesibles llenaría la pantalla de avisos sobre algo que nadie ha afirmado: la
        ausencia de dato no es un dato."""
        from lib.core.dcim import service
        assert service.access_of({}) == {'front', 'rear', 'left', 'right'}
        assert service.access_of({'access': ''}) == {'front', 'rear', 'left', 'right'}

    def test_y_lo_dicho_se_respeta(self):
        from lib.core.dcim import service
        assert service.access_of({'access': 'front,left'}) == {'front', 'left'}

    def test_un_lado_inventado_se_ignora_en_vez_de_romper(self):
        from lib.core.dcim import service
        assert service.access_of({'access': 'front,arriba'}) == {'front'}


class TestEquipoAlQueNoSeLlega:
    """La discrepancia que se paga en el pasillo: un armario de pared no tiene trasera, y lo que
    esté montado ahí no se cablea, no se cambia y no se apaga sin descolgarlo.

    Son dos cosas DECLARADAS que se contradicen —por dónde se entra y qué hay dentro— que es
    justo lo que esta sección existe para encontrar."""

    PARED = {'access': 'front'}

    def test_un_equipo_en_la_cara_inalcanzable_se_dice(self):
        from lib.core.dcim import service
        avisos = service.access_warnings(self.PARED, [{'face': 'rear'}])
        assert avisos == [{'kind': 'unreachable_face', 'face': 'rear', 'items': 1}]

    def test_y_uno_de_profundidad_completa_tambien(self):
        """`full` ocupa las dos caras: eso es lo que `full` significa, así que también está en
        la que no se alcanza."""
        from lib.core.dcim import service
        assert service.access_warnings(self.PARED, [{'face': 'full'}])[0]['items'] == 1

    def test_lo_que_si_se_alcanza_no_avisa(self):
        from lib.core.dcim import service
        assert service.access_warnings(self.PARED, [{'face': 'front'}]) == []

    def test_un_rack_normal_no_avisa_de_nada(self):
        from lib.core.dcim import service
        assert service.access_warnings({}, [{'face': 'rear'}, {'face': 'full'}]) == []

    def test_y_un_armario_vacio_tampoco(self):
        """Sin trasera y sin nada montado no hay contradicción: hay un armario de pared."""
        from lib.core.dcim import service
        assert service.access_warnings(self.PARED, []) == []


class TestLaRefrigeracionDeUnaSala:

    def test_sin_decir_no_es_lo_mismo_que_ninguna(self, store, fleet):
        """Un armario de comunicaciones **sin** refrigeración es un hecho que merece constar;
        una sala cuya refrigeración nadie escribió es una pregunta. Guardar las dos igual pierde
        justo la diferencia por la que se mira esto."""
        sin = store.rooms.create({'site_uid': fleet['site'], 'name': 'Sin decir'})
        nada = store.rooms.create({'site_uid': fleet['site'], 'name': 'Sin nada',
                                   'cooling': 'none'})
        assert store.rooms.get(sin)['cooling'] == ''
        assert store.rooms.get(nada)['cooling'] == 'none'

    def test_y_el_vocabulario_cubre_lo_que_hay_en_una_sala_de_verdad(self):
        from lib.core.dcim.store import COOLING
        assert set(COOLING) >= {'', 'none', 'room', 'cold_aisle', 'hot_aisle', 'in_row',
                                'rear_door', 'split'}


# ══ El cuadro de mando ══════════════════════════════════════════════════════════════════

class TestElCuadroDicePorDondeSeLlega:
    """Un panel que dice «tres cosas mal» y no dice cuáles obliga a buscarlas, que es el trabajo
    que venía a ahorrar. Así que lo que se comprueba no es el número: es el camino."""

    def _fleet(self, store, fleet):
        """Dos equipos en el rack: uno de la filial y uno del departamento."""
        suyo = store.items.create({'rack_uid': fleet['rack'], 'u_start': 12, 'u_height': 2,
                                   'label': 'DB03', 'host_uid': 'h-db03'})
        store.set_owner('item', suyo, fleet['filial'])
        nuestro = store.items.create({'rack_uid': fleet['rack'], 'u_start': 1,
                                      'label': 'SW-CORE', 'host_uid': 'h-sw'})
        # Dicho de quién es, y no dejado sin reclamar: lo que nadie reclama lo ve todo el mundo
        # —un rack sin fichar no es un secreto— así que el caso del vecino solo existe cuando
        # alguien ha dicho que es del vecino.
        store.set_owner('item', nuestro, fleet['it'])
        return suyo, nuestro

    def test_cada_fallo_trae_su_camino_entero(self, store, fleet):
        from lib.core.dcim import service
        self._fleet(store, fleet)
        b = service.board(store, {'h-db03': 'error', 'h-sw': 'ok'},
                          store.owners_map(), None, store.orgs.list())
        fila = b['trouble'][0]
        assert (fila['site'], fila['room'], fila['rack']) == ('DC Norte', 'Sala 1', 'R3')
        assert fila['u'] == 12 and fila['name'] == 'DB03'
        # …y con los uid, que es lo que permite llevar a alguien allí de un clic.
        assert fila['rack_uid'] == fleet['rack'] and fila['site_uid'] == fleet['site']

    def test_lo_peor_primero(self, store, fleet):
        from lib.core.dcim import service
        self._fleet(store, fleet)
        b = service.board(store, {'h-db03': 'warning', 'h-sw': 'error'},
                          store.owners_map(), None, store.orgs.list())
        assert [r['state'] for r in b['trouble']] == ['error', 'warning']

    def test_lo_que_nadie_vigila_no_es_un_fallo_pero_se_cuenta(self, store, fleet):
        """Un panel de parcheo sin host no está roto. Cuarenta servidores así son una pregunta,
        y por eso se cuentan aparte en vez de sumarse a los que están bien."""
        from lib.core.dcim import service
        store.items.create({'rack_uid': fleet['rack'], 'u_start': 40, 'label': 'Patch'})
        b = service.board(store, {}, store.owners_map(), None, store.orgs.list())
        sede = b['sites'][0]
        assert b['trouble'] == []
        assert sede['unwatched'] == 1 and sede['ok'] == 0 and sede['total'] == 1

    def test_el_fallo_del_vecino_no_sale_en_el_cuadro_de_la_filial(self, store, fleet):
        """Lo que se rompe sin que nadie lo note: un cuadro es un sitio cómodo para filtrar de
        menos, porque la pantalla se ve perfecta con datos que no debería enseñar."""
        from lib.core.dcim import service
        suyo, _ = self._fleet(store, fleet)
        statuses = {'h-db03': 'ok', 'h-sw': 'error'}     # el roto es el del departamento
        b = service.board(store, statuses, store.owners_map(), {fleet['filial']},
                          store.orgs.list())
        assert b['trouble'] == []
        assert b['sites'][0]['state'] == 'ok'
        assert b['sites'][0]['total'] == 1               # solo cuenta el suyo

    def test_y_el_desglose_por_empresa_tampoco_lo_delata(self, store, fleet):
        from lib.core.dcim import service
        self._fleet(store, fleet)
        b = service.board(store, {'h-db03': 'ok', 'h-sw': 'error'},
                          store.owners_map(), {fleet['filial']}, store.orgs.list())
        assert [o['uid'] for o in b['orgs']] == [fleet['filial']]

    def test_una_lista_recortada_lo_dice(self, store, fleet):
        """Una lista más corta que la realidad parece completa, y quien la lee da por resuelto
        lo que ni siquiera ha visto."""
        from lib.core.dcim import service
        statuses = {}
        for u in range(1, service.BOARD_TROUBLE_CAP + 6):
            store.items.create({'rack_uid': fleet['rack'], 'u_start': u,
                                'label': f'S{u}', 'host_uid': f'h{u}'})
            statuses[f'h{u}'] = 'error'
        b = service.board(store, statuses, store.owners_map(), None, store.orgs.list())
        assert len(b['trouble']) == service.BOARD_TROUBLE_CAP
        assert b['trouble_total'] == service.BOARD_TROUBLE_CAP + 5
        assert b['capped'] is True

    def test_los_totales_suman_lo_de_todas_las_sedes(self, store, fleet):
        from lib.core.dcim import service
        self._fleet(store, fleet)
        otra = store.sites.create({'name': 'DC Sur'})
        sala = store.rooms.create({'site_uid': otra, 'name': 'S1'})
        rack = store.racks.create({'room_uid': sala, 'name': 'R1', 'u_height': 42})
        store.items.create({'rack_uid': rack, 'u_start': 1, 'host_uid': 'h-x'})
        b = service.board(store, {'h-db03': 'ok', 'h-sw': 'ok', 'h-x': 'error'},
                          store.owners_map(), None, store.orgs.list())
        assert b['totals'] == {'total': 3, 'bad': 1, 'unwatched': 0, 'ok': 2,
                               'sites': 2, 'trouble': 1}


# ══ Lo que hay en una sala además de los racks ══════════════════════════════════════════

class TestLaSalaTieneCosasQueNoSonRacks:
    """Un rack es un registro —tiene equipos dentro y estado en vivo— y una columna no.

    Por eso son tablas distintas. Meterlas juntas «total, son cajas» haría que el recuento de
    una sala incluyera extintores, que el vuelco de estado tuviera que aprender a ignorar
    puertas, y que «equipos sin vigilar» devolviera mamparas.
    """

    def test_una_pieza_vive_en_su_sala(self, store, fleet):
        uid = store.features.create({'room_uid': fleet['room'], 'kind': 'column',
                                     'pos_x': 7900, 'pos_y': 4200})
        assert [f['uid'] for f in store.features_of(fleet['room'])] == [uid]
        assert store.features_of('otra-sala') == []

    def test_y_no_cuenta_como_equipo(self, store, fleet):
        """La prueba de que están separadas: poner una columna no cambia el inventario."""
        from lib.core.dcim import service
        store.features.create({'room_uid': fleet['room'], 'kind': 'column'})
        b = service.board(store, {}, store.owners_map(), None, store.orgs.list())
        assert b['totals']['total'] == 0
        assert b['sites'][0]['racks'] == 1

    def test_las_capas_salen_ordenadas_del_modelo(self, store, fleet):
        """Un pasillo confinado va DEBAJO de los racks y una bandeja por el aire. Dibujarlas al
        revés tapa justo lo que se venía a mirar, y dejar el orden a quien pinte significa que
        la próxima pantalla que dibuje una sala lo tenga que volver a acertar."""
        from lib.core.dcim.store import FEATURE_KINDS, FEATURE_LAYERS
        for kind in ('tray', 'column', 'aisle'):
            store.features.create({'room_uid': fleet['room'], 'kind': kind})
        capas = [FEATURE_KINDS[f['kind']]['layer'] for f in store.features_of(fleet['room'])]
        assert capas == ['floor', 'room', 'air']
        assert list(FEATURE_LAYERS) == ['floor', 'room', 'air']

    def test_un_tipo_desconocido_no_desordena_la_lista(self, store, fleet):
        """Los tipos se validan en la ruta, pero una fila vieja de un tipo retirado es un estado
        real de los datos: se dibuja en medio, no revienta el orden."""
        store.features.create({'room_uid': fleet['room'], 'kind': 'lo-que-sea'})
        store.features.create({'room_uid': fleet['room'], 'kind': 'tray'})
        assert len(store.features_of(fleet['room'])) == 2

    def test_el_vocabulario_cubre_una_sala_de_verdad(self, store):
        from lib.core.dcim.store import FEATURE_KINDS
        for kind in ('aisle', 'column', 'door', 'panel', 'ups', 'crac', 'tray', 'extinguisher'):
            assert kind in FEATURE_KINDS, kind
            assert FEATURE_KINDS[kind]['w'] > 0 and FEATURE_KINDS[kind]['d'] > 0

    def test_la_sala_sabe_cuanto_mide_y_cuanto_su_baldosa(self, store, fleet):
        """Sin medidas, un plano se dibuja y no sirve para lo único que sirve un plano: decir si
        cabe otra fila. Y la baldosa es de la sala porque hay suelos de 500 y de 610."""
        room = store.rooms.get(fleet['room'])
        assert room['width_mm'] == 0 and room['depth_mm'] == 0   # nadie lo ha dicho
        assert room['tile_mm'] == 600                            # lo normal, si nadie dice otra
        store.rooms.update(fleet['room'], {'width_mm': 13000, 'tile_mm': 500})
        assert store.rooms.get(fleet['room'])['tile_mm'] == 500


class TestLasTablasDeclaradasSeCrean:
    """La lista de stores a reconciliar se nombraba a mano, y olvidarse no daba ningún error al
    arrancar: daba un «no such table» la primera vez que alguien usara lo nuevo, semanas después
    y en la instalación de otro. Una declaración que hay que repetir en dos sitios es media."""

    def test_todas_las_declaradas_existen_en_la_base(self, store):
        from lib.core.dcim.store import SCHEMAS
        for spec in SCHEMAS:
            filas = store._db.fetchall(f'SELECT COUNT(*) FROM {spec.name}')
            assert filas is not None, spec.name

    def test_y_el_arranque_no_nombra_ninguna(self):
        import inspect
        from lib.core.dcim.store import DcimStore
        cuerpo = inspect.getsource(DcimStore._bootstrap)
        assert 'self.racks' not in cuerpo and 'self.features' not in cuerpo, (
            'volver a nombrarlas es volver a poder olvidarse de una')


# ══ La potencia ═════════════════════════════════════════════════════════════════════════

class TestSiSeCaeUnaRamaQueSeApaga:
    """La pregunta que justifica el módulo de potencia no es cuántos vatios hay.

    Un armario con dos SAI, dos regletas y equipos de dos fuentes está bien — hasta que alguien
    enchufa el segundo cable de un servidor en la regleta de al lado porque la suya estaba llena.
    Ese cable no da ningún error, no sale en ninguna gráfica, y se descubre el día del corte.
    """

    def _rack(self):
        pdus = [{'uid': 'a', 'name': 'PDU-A', 'feed': 'a', 'outlets': 8, 'capacity_w': 3680},
                {'uid': 'b', 'name': 'PDU-B', 'feed': 'b', 'outlets': 8, 'capacity_w': 3680}]
        items = [{'uid': 'i1', 'label': 'DB03', 'u_start': 12},
                 {'uid': 'i2', 'label': 'SW-CORE', 'u_start': 1},
                 {'uid': 'i3', 'label': 'Patch', 'u_start': 42}]
        return pdus, items

    def test_un_equipo_de_dos_ramas_no_es_un_aviso(self, store):
        from lib.core.dcim import service
        pdus, items = self._rack()
        feeds = [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a', 'watts_said': 200},
                 {'uid': 'c2', 'item_uid': 'i1', 'pdu_uid': 'b', 'watts_said': 200}]
        r = service.power_of_rack(pdus, feeds, [items[0]])
        assert r['warnings'] == []
        assert r['items'][0]['branches'] == ['a', 'b']

    def test_pero_uno_con_dos_cables_a_la_MISMA_rama_si(self, store):
        """Este es el fallo entero: dos cables, dos fuentes, y las dos en la rama A. Contando
        cables parecería redundante; contando RAMAS se ve que no lo es."""
        from lib.core.dcim import service
        pdus, items = self._rack()
        pdus.append({'uid': 'a2', 'name': 'PDU-A2', 'feed': 'a', 'outlets': 8})
        feeds = [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a', 'watts_said': 200},
                 {'uid': 'c2', 'item_uid': 'i1', 'pdu_uid': 'a2', 'watts_said': 200}]
        r = service.power_of_rack(pdus, feeds, [items[0]])
        assert [w['kind'] for w in r['warnings']] == ['single_branch']
        assert r['items'][0]['branches'] == ['a']

    def test_y_uno_sin_enchufar_no_es_un_aviso(self, store):
        """Un panel de parcheo no come. Pintarlo como un problema enseña a la gente a ignorar
        esta pantalla, que es la forma más eficaz de que un aviso de verdad no se lea."""
        from lib.core.dcim import service
        pdus, items = self._rack()
        r = service.power_of_rack(pdus, [], [items[2]])
        assert r['warnings'] == []
        assert r['items'][0]['feeds'] == []

    def test_una_regleta_pasada_de_media_carga_avisa(self, store):
        """No se mide contra su capacidad, se mide contra la MITAD: tener dos ramas no sirve de
        nada si una sola no puede con las dos."""
        from lib.core.dcim import service
        pdus, _ = self._rack()
        feeds = [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a', 'watts_said': 1900},
                 {'uid': 'c2', 'item_uid': 'i1', 'pdu_uid': 'b', 'watts_said': 1900}]
        r = service.power_of_rack(pdus, feeds, [{'uid': 'i1', 'label': 'x'}])
        assert {w['kind'] for w in r['warnings']} == {'over_half'}
        assert len([w for w in r['warnings'] if w['kind'] == 'over_half']) == 2

    def test_las_tomas_ocupadas_son_cables_y_no_equipos(self, store):
        """Un equipo con dos cables en la misma regleta ocupa dos tomas. Contar equipos diría
        que queda una de más, y quien vaya con un servidor se encontrará sin sitio."""
        from lib.core.dcim import service
        pdus, _ = self._rack()
        feeds = [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a'},
                 {'uid': 'c2', 'item_uid': 'i1', 'pdu_uid': 'a'}]
        r = service.power_of_rack(pdus, feeds, [{'uid': 'i1'}])
        a = [p for p in r['pdus'] if p['uid'] == 'a'][0]
        assert a['used'] == 2 and a['free'] == 6

    def test_sin_capacidad_declarada_no_se_inventa_una_carga(self, store):
        """`None` y no 0: «no lo sé» y «está al 0 %» son dos cosas distintas, y pintar la
        segunda cuando es la primera es decirle a alguien que hay sitio de sobra."""
        from lib.core.dcim import service
        r = service.power_of_rack([{'uid': 'a', 'name': 'X', 'feed': 'a', 'outlets': 8}],
                                  [], [])
        assert r['pdus'][0]['load'] is None

    def test_el_total_se_reparte_por_ramas(self, store):
        from lib.core.dcim import service
        pdus, _ = self._rack()
        feeds = [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a', 'watts_said': 300},
                 {'uid': 'c2', 'item_uid': 'i2', 'pdu_uid': 'b', 'watts_said': 500}]
        r = service.power_of_rack(pdus, feeds, [{'uid': 'i1'}, {'uid': 'i2'}])
        assert r['by_branch']['a'] == 300 and r['by_branch']['b'] == 500
        assert r['watts_said'] == 800

    def test_cada_regleta_dice_de_que_equipo_es(self, store):
        """Sin ese dato, la pantalla que ofrece «cuál es la regleta» no sabe cuáles están ya
        declaradas: ofrece la misma otra vez y la segunda crea una regleta duplicada del mismo
        cacharro, con sus tomas contadas dos veces."""
        from lib.core.dcim import service
        r = service.power_of_rack([{'uid': 'a', 'name': 'X', 'feed': 'a', 'outlets': 8,
                                    'item_uid': 'i9'},
                                   {'uid': 'b', 'name': 'Y', 'feed': 'b', 'outlets': 8}],
                                  [], [])
        assert r['pdus'][0]['item_uid'] == 'i9'
        # Y la que no es ningún equipo lo dice vacío, no lo omite: una clave que unas veces
        # está y otras no obliga a quien lee a saber cuál de los dos casos tiene delante.
        assert r['pdus'][1]['item_uid'] == ''

    def test_una_regleta_declarada_no_se_pide_a_si_misma_un_enchufe(self, store):
        """Es la que DA los enchufes. Contarla entre lo que come la deja para siempre en la
        lista de «sin enchufar», que es la lista que esta pantalla existe para vaciar."""
        from lib.core.dcim import service
        r = service.power_of_rack([{'uid': 'a', 'name': 'X', 'feed': 'a', 'outlets': 8,
                                    'item_uid': 'i9'}],
                                  [], [{'uid': 'i9', 'label': 'Regleta', 'role': 'pdu'},
                                       {'uid': 'i1', 'label': 'Servidor'}])
        assert [i['uid'] for i in r['items']] == ['i1']
        # Y tampoco figura entre las que faltan por declarar: ya lo está.
        assert r['undeclared_pdus'] == []

    def test_la_regleta_colocada_y_sin_declarar_se_dice(self, store):
        from lib.core.dcim import service
        r = service.power_of_rack([], [], [{'uid': 'i9', 'label': 'Regleta', 'role': 'pdu',
                                            'u_start': 5}])
        assert [x['uid'] for x in r['undeclared_pdus']] == ['i9']
        assert r['undeclared_pdus'][0]['u_start'] == 5

    def test_se_dice_CUALES_tomas_estan_ocupadas(self, store):
        """Y no sólo cuántas. Sin esto, elegir toma es teclear un número a ciegas y descubrir el
        choque —dos cables en la misma toma, que es físicamente imposible— el día que alguien va
        a desenchufar uno y se encuentra dos."""
        from lib.core.dcim import service
        r = service.power_of_rack(
            [{'uid': 'a', 'name': 'A', 'feed': 'a', 'outlets': 8}],
            [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a', 'outlet': 3},
             {'uid': 'c2', 'item_uid': 'i2', 'pdu_uid': 'a', 'outlet': 1},
             # El 0 es «en esa regleta, no sé en cuál»: no ocupa ninguna, y contarlo dejaría la
             # toma 0 pintada como ocupada en una regleta cuya primera toma es la 1.
             {'uid': 'c3', 'item_uid': 'i3', 'pdu_uid': 'a', 'outlet': 0}],
            [{'uid': 'i1'}, {'uid': 'i2'}, {'uid': 'i3'}])
        assert r['pdus'][0]['outlets_used'] == [1, 3]
        # Y las tomas libres se siguen contando por CABLES, no por tomas nombradas: tres cables
        # ocupan tres tomas aunque de uno no se sepa cuál.
        assert r['pdus'][0]['free'] == 5

    def test_el_cable_vuelve_con_su_uid(self, store):
        """Sin él la pantalla puede enseñar de qué come un equipo y no puede desenchufarlo, que
        es la mitad de para lo que se abre."""
        from lib.core.dcim import service
        pdus, _ = self._rack()
        r = service.power_of_rack(pdus, [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a'}],
                                  [{'uid': 'i1'}])
        assert r['items'][0]['feeds'][0]['uid'] == 'c1'


class TestCuantoGastaCadaSociedad:
    """En un holding donde el departamento opera la sala y factura por consumo, esto es una
    línea de una factura."""

    def test_se_suma_por_empresa(self, store):
        from lib.core.dcim import service
        pdus = [{'uid': 'a', 'name': 'A', 'feed': 'a', 'outlets': 8}]
        feeds = [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a', 'watts_said': 300},
                 {'uid': 'c2', 'item_uid': 'i2', 'pdu_uid': 'a', 'watts_said': 500}]
        items = [{'uid': 'i1'}, {'uid': 'i2'}]
        r = service.power_of_rack(pdus, feeds, items, {}, {'i1': 'org-a', 'i2': 'org-b'})
        por = {o['uid']: o for o in r['by_org']}
        assert por['org-b']['watts_said'] == 500 and por['org-a']['watts_said'] == 300
        assert por['org-a']['items'] == 1

    def test_lo_no_reclamado_sale_como_tal(self, store):
        """En el primer día de toda instalación eso es casi todo, y llamarlo «sin empresa» en
        una factura sería inventarse un cliente."""
        from lib.core.dcim import service
        r = service.power_of_rack([{'uid': 'a', 'name': 'A', 'feed': 'a', 'outlets': 8}],
                                  [{'uid': 'c', 'item_uid': 'i1', 'pdu_uid': 'a',
                                    'watts_said': 100}], [{'uid': 'i1'}], {}, {})
        assert r['by_org'] == [{'uid': '', 'watts_said': 100, 'items': 1}]

    def test_el_dueno_llega_RESUELTO_y_no_se_vuelve_a_deducir(self, store, fleet):
        """Un equipo hereda el dueño de su armario. Volver a subir la cadena aquí sería una
        segunda copia de esa regla, que es como dos pantallas acaban discrepando sobre de quién
        es lo mismo — así que se pasa ya resuelto y esto solo suma."""
        import inspect
        from lib.core.dcim import service
        cuerpo = inspect.getsource(service.power_of_rack)
        assert 'chain_of' not in cuerpo and 'owner_of' not in cuerpo


# ══ El cableado, contra lo que se ve ════════════════════════════════════════════════════

class TestLoDeclaradoContraLoQueSeVe:
    """Aquí el inventario deja de ser documentación.

    Un cable declarado no vale por sí solo: vale porque con él hay **dos mitades**. Y el
    resultado no es «bien» o «mal» — son cuatro estados, y confundir dos de ellos convierte la
    pantalla en ruido que nadie vuelve a mirar.
    """

    ITEMS = [{'uid': 'i1', 'host_uid': 'h-sw', 'label': 'SW01'},
             {'uid': 'i2', 'host_uid': 'h-db', 'label': 'DB03'},
             {'uid': 'i3', 'host_uid': '', 'label': 'Panel B'},
             {'uid': 'i4', 'host_uid': 'h-x', 'label': 'SRV9'}]

    def _edges(self):
        return [{'kind': 'lldp', 'from': 'h-sw', 'to': 'h-db',
                 'ports': {'h-sw': ['Gi1/0/7'], 'h-db': ['eth0']}}]

    def test_declarado_y_visto_coincide(self, store):
        from lib.core.dcim import service
        c = [{'uid': 'c1', 'a_item': 'i1', 'a_port': 'Gi1/0/7',
              'b_item': 'i2', 'b_port': 'eth0'}]
        r = service.cable_check(c, self.ITEMS, self._edges())
        assert r['cables'][0]['seen'] == 'seen'

    def test_visto_en_otro_puerto_se_dice(self, store):
        """Es el caso que esta pantalla existe para encontrar: alguien movió el latiguillo y no
        cambió la etiqueta."""
        from lib.core.dcim import service
        c = [{'uid': 'c1', 'a_item': 'i1', 'a_port': 'Gi1/0/3',
              'b_item': 'i2', 'b_port': 'eth9'}]
        r = service.cable_check(c, self.ITEMS, self._edges())
        assert r['cables'][0]['seen'] == 'other_port'
        assert r['cables'][0]['ports_seen'] == ['eth0', 'gi1/0/7']

    def test_un_extremo_pasivo_NO_se_juzga(self, store):
        """Un panel de parcheo es un trozo de metal: nadie puede confirmarlo. Marcarlo como «no
        se ve» llenaría la pantalla de avisos imposibles de resolver, que es la forma más rápida
        de que nadie vuelva a mirarla."""
        from lib.core.dcim import service
        c = [{'uid': 'c1', 'a_item': 'i1', 'a_port': 'Gi1/0/3', 'b_item': 'i3', 'b_port': '3'}]
        r = service.cable_check(c, self.ITEMS, self._edges())
        assert r['cables'][0]['seen'] == 'passive'

    def test_declarado_y_no_visto_es_una_pregunta(self, store):
        from lib.core.dcim import service
        c = [{'uid': 'c1', 'a_item': 'i2', 'b_item': 'i4'}]
        r = service.cable_check(c, self.ITEMS, self._edges())
        assert r['cables'][0]['seen'] == 'unseen'

    def test_lo_visto_y_no_declarado_sale_aparte(self, store):
        """Casi siempre es trabajo pendiente: alguien enchufó y no lo apuntó."""
        from lib.core.dcim import service
        r = service.cable_check([], self.ITEMS, self._edges())
        assert [(u['from'], u['to']) for u in r['undeclared']] == [('h-db', 'h-sw')]

    def test_pero_no_lo_que_va_a_algo_que_no_esta_en_un_armario(self, store):
        """Un enlace al portátil de alguien no es cableado de sala, y llenaría la lista de
        ruido hasta que nadie viera lo que sí importa."""
        from lib.core.dcim import service
        edges = self._edges() + [{'kind': 'lldp', 'from': 'h-sw', 'to': 'h-portatil',
                                  'ports': {}}]
        r = service.cable_check([], self.ITEMS, edges)
        assert all('h-portatil' not in (u['from'], u['to']) for u in r['undeclared'])

    def test_un_enlace_declarado_no_sale_ademas_como_sin_declarar(self, store):
        """Contarlo dos veces haría que arreglar un cable aumentase la lista de pendientes."""
        from lib.core.dcim import service
        c = [{'uid': 'c1', 'a_item': 'i1', 'a_port': 'Gi1/0/7',
              'b_item': 'i2', 'b_port': 'eth0'}]
        r = service.cable_check(c, self.ITEMS, self._edges())
        assert r['undeclared'] == []

    def test_lo_que_no_es_lldp_no_cuenta_como_visto(self, store):
        """El mapa trae aristas de varias clases —una red compartida no es un cable— y solo
        LLDP significa «un aparato ha visto al otro por este puerto»."""
        from lib.core.dcim import service
        edges = [{'kind': 'subnet', 'from': 'h-sw', 'to': 'h-db', 'ports': {}}]
        c = [{'uid': 'c1', 'a_item': 'i1', 'b_item': 'i2'}]
        r = service.cable_check(c, self.ITEMS, edges)
        assert r['cables'][0]['seen'] == 'unseen'
        assert r['undeclared'] == []

    def test_sin_mapa_lo_declarado_se_sigue_leyendo(self, store):
        """Una pantalla que no abre porque una sonda no ha contestado es peor que una que dice
        menos."""
        from lib.core.dcim import service
        c = [{'uid': 'c1', 'a_item': 'i1', 'b_item': 'i2', 'label': 'A-07'}]
        r = service.cable_check(c, self.ITEMS, [])
        assert r['cables'][0]['label'] == 'A-07' and r['cables'][0]['seen'] == 'unseen'

    def test_cada_fila_trae_los_nombres_de_sus_extremos(self, store):
        """Una fila que dice «va a 4f2a-…» no la lee nadie."""
        from lib.core.dcim import service
        c = [{'uid': 'c1', 'a_item': 'i1', 'b_item': 'i3'}]
        r = service.cable_check(c, self.ITEMS, [])
        assert (r['cables'][0]['a_label'], r['cables'][0]['b_label']) == ('SW01', 'Panel B')


# ══ Los enlaces entre sedes ═════════════════════════════════════════════════════════════

class TestQueSedeSeQuedaSola:
    """La misma pregunta que la potencia, un nivel arriba — y se rompe igual de callada."""

    SITES = [{'uid': 's1', 'name': 'DC Norte'}, {'uid': 's2', 'name': 'Sur'},
             {'uid': 's3', 'name': 'Este'}]

    def test_una_sede_con_un_solo_enlace_se_dice(self, store):
        from lib.core.dcim import service
        links = [{'uid': 'l1', 'a_site': 's1', 'b_site': 's3', 'label': 'MPLS-3'},
                 {'uid': 'l2', 'a_site': 's1', 'b_site': 's2'},
                 {'uid': 'l3', 'a_site': 's1', 'b_site': 's2'}]
        r = service.links_roll(links, self.SITES)
        solos = [w for w in r['warnings'] if w['kind'] == 'single_link']
        assert [w['site'] for w in solos] == ['s3']
        assert solos[0]['link'] == 'MPLS-3', 'el aviso dice CUÁL, no solo que hay uno'

    def test_dos_operadores_por_la_misma_zanja_no_son_dos_caminos(self, store):
        """Dos líneas en el mapa y un solo camino en el suelo. Es el hallazgo de esta pantalla:
        redundancia sobre el papel que se descubre el día que pasa una excavadora."""
        from lib.core.dcim import service
        links = [{'uid': 'l1', 'a_site': 's1', 'b_site': 's2', 'provider': 'Telco A',
                  'path': 'Zanja Norte'},
                 {'uid': 'l2', 'a_site': 's1', 'b_site': 's2', 'provider': 'Telco B',
                  'path': 'zanja norte'}]
        r = service.links_roll(links, self.SITES)
        mismo = [w for w in r['warnings'] if w['kind'] == 'same_path']
        assert {w['site'] for w in mismo} == {'s1', 's2'}
        assert mismo[0]['value'] == 'zanja norte', 'se compara sin distinguir mayúsculas'

    def test_y_dos_del_mismo_operador_tampoco(self, store):
        from lib.core.dcim import service
        links = [{'uid': 'l1', 'a_site': 's1', 'b_site': 's2', 'provider': 'Telco A'},
                 {'uid': 'l2', 'a_site': 's1', 'b_site': 's2', 'provider': 'Telco A'}]
        r = service.links_roll(links, self.SITES)
        assert [w['kind'] for w in r['warnings'] if w['kind'] == 'same_provider']

    def test_pero_no_se_avisa_de_lo_que_nadie_escribio(self, store):
        """Un aviso sacado de un campo vacío es un aviso inventado, y esos enseñan a ignorar la
        pantalla — que es como se pierde el aviso de verdad."""
        from lib.core.dcim import service
        links = [{'uid': 'l1', 'a_site': 's1', 'b_site': 's2'},
                 {'uid': 'l2', 'a_site': 's1', 'b_site': 's2'}]
        r = service.links_roll(links, self.SITES)
        assert r['warnings'] == []

    def test_ni_cuando_solo_uno_de_los_dos_comparte_camino(self, store):
        """Con tres enlaces y dos por la misma zanja queda un tercero por otra: la sede NO se
        queda sin camino, así que decir que sí sería mentir."""
        from lib.core.dcim import service
        links = [{'uid': 'l1', 'a_site': 's1', 'b_site': 's2', 'path': 'norte'},
                 {'uid': 'l2', 'a_site': 's1', 'b_site': 's2', 'path': 'norte'},
                 {'uid': 'l3', 'a_site': 's1', 'b_site': 's2', 'path': 'sur'}]
        r = service.links_roll(links, self.SITES)
        assert [w for w in r['warnings'] if w['kind'] == 'same_path'] == []

    def test_el_estado_de_un_enlace_es_el_de_quien_lo_termina(self, store):
        """Un circuito no tiene estado: es un contrato. El router que lo termina sí."""
        from lib.core.dcim import service
        links = [{'uid': 'l1', 'a_site': 's1', 'b_site': 's2', 'a_item': 'i1', 'b_item': 'i2'}]
        r = service.links_roll(links, self.SITES, {'i1': 'ok', 'i2': 'error'})
        assert r['links'][0]['state'] == 'error'

    def test_y_sin_ninguna_punta_enlazada_no_se_opina(self, store):
        """No es que esté bien: es que nadie lo mira, y son cosas distintas."""
        from lib.core.dcim import service
        links = [{'uid': 'l1', 'a_site': 's1', 'b_site': 's2'}]
        r = service.links_roll(links, self.SITES, {'i1': 'ok'})
        assert r['links'][0]['state'] == ''

    def test_cada_enlace_trae_el_nombre_de_sus_dos_sedes(self, store):
        from lib.core.dcim import service
        r = service.links_roll([{'uid': 'l1', 'a_site': 's1', 'b_site': 's3'}], self.SITES)
        assert (r['links'][0]['a_name'], r['links'][0]['b_name']) == ('DC Norte', 'Este')


# ══ Previsión: dónde cabe esto ══════════════════════════════════════════════════════════

class TestDoceULibresNoSonUnHuecoDeDoce:
    """La U es la medida que más engaña.

    Doce U libres repartidas de una en una por todo el armario no admiten nada de 2U, y el
    número «12» parece una respuesta y no lo es: es el que manda a alguien con un servidor en
    las manos hasta un armario donde no entra.
    """

    def test_los_tramos_se_cuentan_seguidos(self, store):
        from lib.core.dcim import service
        assert service.free_runs([1, 2, 3, 7, 8, 20]) == [
            {'start': 1, 'size': 3}, {'start': 7, 'size': 2}, {'start': 20, 'size': 1}]

    def test_y_salen_de_mayor_a_menor(self, store):
        """Quien busca sitio quiere el más grande primero."""
        from lib.core.dcim import service
        assert service.free_runs([5, 10, 11, 12, 13])[0] == {'start': 10, 'size': 4}

    def test_doce_sueltas_no_admiten_un_2u(self, store):
        from lib.core.dcim import service
        libres = list(range(1, 24, 2))                    # 1, 3, 5… doce U y ningún par seguido
        cap = {'uid': 'r', 'name': 'R', 'runs': service.free_runs(libres),
               'free_u': len(libres), 'branches': {'a': {'outlets': 4, 'watts_free': 0,
                                                         'known': False},
                                                   'b': {'outlets': 4, 'watts_free': 0,
                                                         'known': False}}}
        r = service.where_fits([cap], {'u_height': 2})[0]
        assert r['fits'] is False
        assert [x['why'] for x in r['reasons']] == ['no_room']
        assert r['reasons'][0]['best'] == 1, 'dice cuál es el mayor hueco, no solo que no cabe'


class TestPorQueNoCabeEsLaMitadDelValor:
    """Una lista de los armarios que valen deja sin saber si el de al lado está descartado por
    sitio, por corriente o por fondo — y eso decide si hay que mover un equipo, pedir una
    regleta o comprar otro armario. Tres problemas muy distintos con la misma pinta."""

    def _cap(self, **cambios):
        base = {'uid': 'r1', 'name': 'R1', 'runs': [{'start': 1, 'size': 10}], 'free_u': 10,
                'branches': {'a': {'outlets': 4, 'watts_free': 1000, 'known': True},
                             'b': {'outlets': 4, 'watts_free': 1000, 'known': True}}}
        base.update(cambios)
        return base

    def test_lo_que_cabe_dice_desde_que_u(self, store):
        from lib.core.dcim import service
        r = service.where_fits([self._cap()], {'u_height': 2})[0]
        assert r['fits'] and r['at_u'] == 1 and r['run'] == 10

    def test_una_rama_sin_tomas_descarta_aunque_sobre_sitio(self, store):
        """Un armario con veinte U libres y sin toma en la B no admite nada que tenga que comer
        de las dos, y decir «tiene sitio» sería cierto y useless."""
        from lib.core.dcim import service
        cap = self._cap(branches={'a': {'outlets': 4, 'watts_free': 999, 'known': True},
                                  'b': {'outlets': 0, 'watts_free': 999, 'known': True}})
        r = service.where_fits([cap], {'u_height': 1})[0]
        assert [x['why'] for x in r['reasons']] == ['no_outlets']
        assert r['reasons'][0]['have'] == 1 and r['reasons'][0]['need'] == 2

    def test_una_rama_es_una_rama_aunque_tenga_tres_regletas(self, store):
        """Se cuentan RAMAS con toma libre, no regletas: dos llenas en la A y una libre en la A
        siguen siendo una sola rama disponible."""
        from lib.core.dcim import service
        cap = self._cap(branches={'a': {'outlets': 9, 'watts_free': 999, 'known': True}})
        r = service.where_fits([cap], {'u_height': 1})[0]
        assert [x['why'] for x in r['reasons']] == ['no_outlets']

    def test_sin_capacidad_declarada_no_se_descarta_por_vatios(self, store):
        """«No cabe porque no lo sé» es descartar un armario por una casilla vacía."""
        from lib.core.dcim import service
        cap = self._cap(branches={'a': {'outlets': 4, 'watts_free': 0, 'known': False},
                                  'b': {'outlets': 4, 'watts_free': 0, 'known': False}})
        r = service.where_fits([cap], {'u_height': 1, 'watts': 5000})[0]
        assert r['fits'] is True

    def test_pero_con_ella_si_y_dice_en_qué_rama(self, store):
        from lib.core.dcim import service
        cap = self._cap(branches={'a': {'outlets': 4, 'watts_free': 100, 'known': True},
                                  'b': {'outlets': 4, 'watts_free': 9000, 'known': True}})
        r = service.where_fits([cap], {'u_height': 1, 'watts': 500})[0]
        malo = [x for x in r['reasons'] if x['why'] == 'no_watts'][0]
        assert malo['branches'] == ['a']

    def test_el_fondo_descarta_con_su_motivo(self, store):
        from lib.core.dcim import service
        rack = {'uid': 'r1', 'u_height': 42, 'rail_front_mm': 50,
                'rail_depth_mm': 750, 'rail_rear_mm': 20}
        r = service.where_fits([self._cap()], {'u_height': 1, 'depth_mm': 760},
                               {'r1': rack})[0]
        assert 'dcim_depth_no_cables' in [x['why'] for x in r['reasons']]

    def test_se_acumulan_los_motivos(self, store):
        """Arreglar uno y descubrir el siguiente es dos viajes al armario."""
        from lib.core.dcim import service
        cap = self._cap(runs=[{'start': 1, 'size': 1}], free_u=1,
                        branches={'a': {'outlets': 0, 'watts_free': 0, 'known': False}})
        r = service.where_fits([cap], {'u_height': 4})[0]
        assert {x['why'] for x in r['reasons']} == {'no_room', 'no_outlets'}

    def test_entre_los_que_valen_gana_el_hueco_mas_ajustado(self, store):
        """Meter un 1U en el tramo de veinte gasta el único sitio donde luego cabrá un chasis."""
        from lib.core.dcim import service
        ancho = self._cap(uid='grande', name='Grande', runs=[{'start': 1, 'size': 20}])
        justo = self._cap(uid='justo', name='Justo', runs=[{'start': 5, 'size': 2}])
        r = service.where_fits([ancho, justo], {'u_height': 2})
        assert [x['uid'] for x in r] == ['justo', 'grande']

    def test_y_lo_que_no_cabe_va_despues_de_lo_que_si(self, store):
        from lib.core.dcim import service
        no = self._cap(uid='no', runs=[], free_u=0)
        si = self._cap(uid='si')
        assert [x['uid'] for x in service.where_fits([no, si], {'u_height': 1})] == ['si', 'no']


class TestAdondeLlegaUnLector:
    """A una caja se llega **o porque se ve, o porque contiene algo tuyo**.

    Las dos mitades importan y ninguna sola vale. Solo la primera deja al holding sin pantalla:
    el departamento opera la sede, así que la sede es suya, así que la filial que tiene 2U
    dentro no ve ni sede, ni sala, ni rack — y su propio equipo queda inalcanzable salvo que
    alguien le pase una URL. Solo la segunda escondería una sede entera vacía que sí es suya.
    """

    def _monta(self, store, fleet):
        """El caso del holding: sede del departamento, 2U de la filial dentro."""
        store.set_owner('site', fleet['site'], fleet['it'])
        suyo = store.items.create({'rack_uid': fleet['rack'], 'u_start': 12, 'label': 'DB03'})
        store.set_owner('item', suyo, fleet['filial'])
        return suyo

    def test_se_llega_a_la_sede_por_tener_algo_dentro(self, store, fleet):
        from lib.core.dcim import service
        self._monta(store, fleet)
        reach = service.reachable(store, store.owners_map(), {fleet['filial']})
        assert fleet['site'] in reach['site']
        assert fleet['room'] in reach['room']
        assert fleet['rack'] in reach['rack']

    def test_pero_no_a_una_donde_no_se_tiene_nada(self, store, fleet):
        from lib.core.dcim import service
        self._monta(store, fleet)
        otra = store.sites.create({'name': 'DC Ajeno'})
        store.set_owner('site', otra, fleet['it'])
        sala = store.rooms.create({'site_uid': otra})
        store.racks.create({'room_uid': sala, 'name': 'RA'})
        reach = service.reachable(store, store.owners_map(), {fleet['filial']})
        assert otra not in reach['site'] and sala not in reach['room']

    def test_quien_lo_ve_todo_no_necesita_conjuntos(self, store, fleet):
        """`None` es «no hay nada que estrechar», y ahí `may_see` ya dice que sí a todo."""
        from lib.core.dcim import service
        assert service.reachable(store, store.owners_map(), None) is None

    def test_y_ese_None_no_significa_llegar_a_todo(self, store):
        """Dos significados para `None` —«ve todo» y «este llamante no calculó el alcance»—
        hicieron que cualquier filtro que no pasara los conjuntos dejara pasar todo: los
        equipos ajenos de un rack compartido salieron enteros en vez de anónimos."""
        from lib.core.dcim import service
        assert service.llega(None, 'rack', 'lo-que-sea') is False
        assert service.llega({}, 'rack', 'lo-que-sea') is False
        assert service.llega({'rack': {'r1'}}, 'rack', 'r1') is True
        assert service.llega({'rack': {'r1'}}, 'site', 'r1') is False

    def test_el_cuadro_cuenta_solo_lo_suyo_de_esa_sede(self, store, fleet):
        """Llegar a la sede no es ver lo que hay en ella: el equipo del departamento sigue sin
        contar para la filial."""
        from lib.core.dcim import service
        self._monta(store, fleet)
        del_it = store.items.create({'rack_uid': fleet['rack'], 'u_start': 1, 'host_uid': 'h'})
        store.set_owner('item', del_it, fleet['it'])
        b = service.board(store, {'h': 'error'}, store.owners_map(), {fleet['filial']},
                          store.orgs.list())
        assert [s['uid'] for s in b['sites']] == [fleet['site']]
        assert b['sites'][0]['total'] == 1 and b['trouble'] == []


class TestUnaFilaEsAlgoQueSeDeclara:
    """Una fila de racks no se deduce de que caigan alineados: eso falla de las dos formas —dos
    racks alineados por casualidad parecen una fila, y una fila con un hueco deja de parecerlo.

    Y no es una etiqueta. De ella cuelga a qué pasillo da cada cara, y de ahí sale la pregunta
    que un plano no puede contestar mirando cajas: **¿esta fila está respirando lo que expulsa
    la de enfrente?** Las cajas están perfectamente alineadas mientras eso pasa.
    """

    FILAS = [{'uid': 'a', 'name': 'A', 'front_aisle': 'Frío 1', 'rear_aisle': 'Caliente 1'},
             {'uid': 'b', 'name': 'B', 'front_aisle': 'Frío 1', 'rear_aisle': 'Caliente 2'},
             {'uid': 'c', 'name': 'C', 'front_aisle': 'Caliente 1', 'rear_aisle': 'Caliente 3'}]

    def test_una_fila_que_aspira_donde_otra_descarga_se_dice(self, store):
        from lib.core.dcim import service
        r = service.rows_roll(self.FILAS, [])
        malo = [w for w in r['warnings'] if w['kind'] == 'hot_intake']
        assert [(w['label'], w['other']) for w in malo] == [('C', 'A')]

    def test_dos_filas_enfrentadas_compartiendo_frío_no_son_un_aviso(self, store):
        """Es la disposición correcta y la más común: pasillo frío en medio."""
        from lib.core.dcim import service
        r = service.rows_roll(self.FILAS[:2], [])
        assert r['warnings'] == []

    def test_una_fila_sin_pasillos_dichos_no_se_juzga(self, store):
        """No es que esté mal: es que nadie lo ha escrito, y avisar de un campo vacío enseña a
        ignorar la pantalla."""
        from lib.core.dcim import service
        r = service.rows_roll([{'uid': 'x', 'name': 'X'}, {'uid': 'y', 'name': 'Y'}], [])
        assert r['warnings'] == []

    def test_los_racks_sueltos_salen_aparte_y_no_como_error(self, store):
        """El armario de comunicaciones de un rincón no está en ninguna fila y nunca lo estará.
        Meterlo en una inventada haría decir algo falso sobre el aire."""
        from lib.core.dcim import service
        racks = [{'uid': 'r1', 'row_uid': 'a'}, {'uid': 'r2', 'row_uid': ''}]
        r = service.rows_roll(self.FILAS, racks)
        assert [x['uid'] for x in r['loose']] == ['r2']
        assert [f['racks'] for f in r['rows'] if f['uid'] == 'a'] == [1]

    def test_el_nombre_del_pasillo_se_compara_sin_manias(self, store):
        """«Frío 1» y «frio 1» son el mismo pasillo para quien los escribió."""
        from lib.core.dcim import service
        filas = [{'uid': 'a', 'name': 'A', 'rear_aisle': 'CALIENTE 1'},
                 {'uid': 'b', 'name': 'B', 'front_aisle': 'caliente 1  '}]
        assert [w['label'] for w in service.rows_roll(filas, [])['warnings']] == ['B']


# ══ La cadena aguas arriba ══════════════════════════════════════════════════════════════

class TestQuePierdoSiEchanElBypass:
    """Las cuatro instalaciones que hay que poder decir son **tres cadenas y un interruptor**.

    `Cuadro → SAI → Cuadro → PDU` con el bypass echado no es otra instalación: es esa misma con
    el SAI fuera. Modelarlas como dos cadenas obligaría a mantener dos verdades sobre el mismo
    cobre y a acordarse de cambiar las dos.
    """

    def _sala(self, bypass=0):
        return [{'uid': 'red', 'name': 'Acometida', 'kind': 'mains'},
                {'uid': 'cg', 'name': 'CGBT', 'kind': 'panel', 'upstream_uid': 'red'},
                {'uid': 'sai', 'name': 'SAI 1', 'kind': 'ups', 'upstream_uid': 'cg',
                 'bypass': bypass},
                {'uid': 'sal', 'name': 'Cuadro salida', 'kind': 'panel',
                 'upstream_uid': 'sai'}]

    def test_la_cadena_sube_hasta_la_acometida(self, store):
        from lib.core.dcim import service
        cadena = service.chain_up(self._sala(), 'sal')
        assert [n['name'] for n in cadena] == ['Cuadro salida', 'SAI 1', 'CGBT', 'Acometida']

    def test_con_el_bypass_echado_el_sai_no_esta_en_ella(self, store):
        from lib.core.dcim import service
        cadena = service.chain_up(self._sala(bypass=1), 'sal')
        assert [n['name'] for n in cadena] == ['Cuadro salida', 'CGBT', 'Acometida']

    def test_pero_se_puede_preguntar_como_seria_sin_el(self, store):
        """La otra mitad: no «por dónde va ahora» sino «por dónde iría si nadie hubiera tocado
        nada». Es lo que convierte la duda en una frase."""
        from lib.core.dcim import service
        cadena = service.chain_up(self._sala(bypass=1), 'sal', honour_bypass=False)
        assert 'SAI 1' in [n['name'] for n in cadena]

    def test_una_regleta_en_bypass_se_dice_con_el_SAI_que_se_pierde(self, store):
        from lib.core.dcim import service
        pdus = [{'uid': 'p', 'name': 'PDU-A', 'rack_uid': 'r', 'feed': 'a',
                 'source_uid': 'sal'}]
        r = service.power_path(self._sala(bypass=1), pdus)
        malo = [w for w in r['warnings'] if w['kind'] == 'on_bypass'][0]
        assert malo['label'] == 'PDU-A' and malo['ups'] == ['SAI 1']

    def test_y_sin_bypass_no_hay_nada_que_decir(self, store):
        from lib.core.dcim import service
        pdus = [{'uid': 'p', 'name': 'PDU-A', 'rack_uid': 'r', 'feed': 'a',
                 'source_uid': 'sal'}]
        r = service.power_path(self._sala(), pdus)
        assert [w for w in r['warnings'] if w['kind'] == 'on_bypass'] == []

    def test_una_regleta_que_nunca_pasa_por_un_SAI_tampoco_es_un_aviso(self, store):
        """`Cuadro → PDU` es media sala técnica y es correcto. Avisar de eso sería avisar de la
        instalación, no de un problema."""
        from lib.core.dcim import service
        fuentes = [{'uid': 'cg', 'name': 'CGBT', 'kind': 'panel'}]
        pdus = [{'uid': 'p', 'name': 'PDU', 'rack_uid': 'r', 'feed': 'a', 'source_uid': 'cg'}]
        r = service.power_path(fuentes, pdus)
        assert r['warnings'] == []

    def test_las_dos_ramas_del_mismo_SAI_se_dicen(self, store):
        """Dos regletas, dos ramas, dos colores… y un solo punto de fallo tres metros más
        arriba. Es el error que la redundancia dentro del armario esconde."""
        from lib.core.dcim import service
        pdus = [{'uid': 'a', 'name': 'PDU-A', 'rack_uid': 'r', 'feed': 'a', 'source_uid': 'sal'},
                {'uid': 'b', 'name': 'PDU-B', 'rack_uid': 'r', 'feed': 'b', 'source_uid': 'sal'}]
        r = service.power_path(self._sala(), pdus)
        assert [w['kind'] for w in r['warnings'] if w['kind'] == 'same_ups'] == ['same_ups']

    def test_pero_dos_SAI_distintos_no(self, store):
        from lib.core.dcim import service
        fuentes = self._sala() + [
            {'uid': 'sai2', 'name': 'SAI 2', 'kind': 'ups', 'upstream_uid': 'cg'},
            {'uid': 'sal2', 'name': 'Cuadro salida 2', 'kind': 'panel', 'upstream_uid': 'sai2'}]
        pdus = [{'uid': 'a', 'name': 'PDU-A', 'rack_uid': 'r', 'feed': 'a', 'source_uid': 'sal'},
                {'uid': 'b', 'name': 'PDU-B', 'rack_uid': 'r', 'feed': 'b', 'source_uid': 'sal2'}]
        r = service.power_path(fuentes, pdus)
        assert [w for w in r['warnings'] if w['kind'] == 'same_ups'] == []

    def test_una_regleta_sin_origen_dicho_no_se_inventa_uno(self, store):
        """«Nadie lo ha dicho» no es «no tiene»: media sala técnica cuelga de un cuadro que
        nadie documentó, y decir que no tiene sería inventarse un hecho."""
        from lib.core.dcim import service
        r = service.power_path(self._sala(), [{'uid': 'p', 'rack_uid': 'r', 'feed': 'a'}])
        assert r['paths']['p']['known'] is False
        assert r['warnings'] == []

    def test_un_ciclo_declarado_no_cuelga_el_panel(self, store):
        """Alguien dice que A cuelga de B y B de A. Es un dato equivocado, no un estado
        imposible: se dibuja lo que se pueda y ya."""
        from lib.core.dcim import service
        fuentes = [{'uid': 'a', 'name': 'A', 'kind': 'panel', 'upstream_uid': 'b'},
                   {'uid': 'b', 'name': 'B', 'kind': 'panel', 'upstream_uid': 'a'}]
        assert [n['name'] for n in service.chain_up(fuentes, 'a')] == ['A', 'B']


# ══ Qué es cada cosa, y qué lleva dentro ════════════════════════════════════════════════

class TestUnPanelDeParcheoNoEstaSinVigilar:
    """No es un ajuste de números: es la diferencia entre una pantalla que avisa y una que se
    ignora.

    Un armario de cuarenta paneles salía con cuarenta «sin vigilar» y ninguno lo estaba — no es
    que nadie los mire, es que **no hay nada que mirar**. Y cuarenta deberes imposibles enseñan
    a saltarse la lista, con lo que el servidor que sí está sin vigilar se pierde entre ellos.
    """

    def test_lo_que_no_contesta_por_naturaleza_no_cuenta(self, store):
        from lib.core.dcim import service
        items = [{'uid': '1', 'role': 'patch_panel'}, {'uid': '2', 'role': 'fiber_panel'},
                 {'uid': '3', 'role': 'shelf'}, {'uid': '4', 'role': 'blank'},
                 {'uid': '5', 'role': 'server'}]
        r = service.rack_roll(items, {})
        assert r['unwatched'] == 1, 'solo el servidor'
        assert r['passive'] == 4
        assert r['total'] == 5, 'siguen siendo inventario y siguen ocupando U'

    def test_un_servidor_sin_maquina_sigue_siendo_una_pregunta(self, store):
        from lib.core.dcim import service
        r = service.rack_roll([{'uid': '1', 'role': 'server'}], {})
        assert r['unwatched'] == 1 and r['passive'] == 0

    def test_y_uno_sin_rol_dicho_tambien(self, store):
        """Vacío es «nadie lo ha dicho», que es una pregunta. Tratarlo como pasivo sería dejar
        de preguntar por todo lo que aún no se ha clasificado — que el primer día es todo."""
        from lib.core.dcim import service
        r = service.rack_roll([{'uid': '1'}], {})
        assert r['unwatched'] == 1 and r['passive'] == 0

    def test_un_panel_con_maquina_enlazada_no_se_descuenta_dos_veces(self, store):
        """Si alguien enlaza un panel gestionado con una máquina, tiene estado: cuenta como lo
        que es y no como pasivo."""
        from lib.core.dcim import service
        r = service.rack_roll([{'uid': '1', 'role': 'patch_panel', 'host_uid': 'h'}],
                              {'h': 'ok'})
        assert r['passive'] == 0 and r['unwatched'] == 0


class TestElCatalogoSugiereQueEsCadaModelo:
    """La biblioteca no dice el rol en ninguna parte, así que se deduce de los puertos — y una
    deducción escrita en la base de datos como si fuera un hecho es lo que este dominio evita.
    Propone; no escribe."""

    def test_tomas_de_corriente_y_ninguna_interfaz_es_una_regleta(self, store):
        from lib.core.dcim import service
        assert service.role_hint({'ports': {'power-outlets': {'c13': 24}}}) == 'pdu'

    def test_puertos_delante_y_detras_sin_alimentacion_es_un_panel(self, store):
        """No lo alimenta nadie porque no lo necesita: es la señal más fiable de la biblioteca."""
        from lib.core.dcim import service
        assert service.role_hint({'ports': {'front-ports': {'8p8c': 24},
                                            'rear-ports': {'8p8c': 24}},
                                  'is_powered': 0}) == 'patch_panel'

    def test_muchas_interfaces_es_un_conmutador_y_pocas_una_maquina(self, store):
        from lib.core.dcim import service
        assert service.role_hint({'ports': {'interfaces': {'1000base-t': 48}}}) == 'switch'
        assert service.role_hint({'ports': {'interfaces': {'1000base-t': 4}}}) == 'server'

    def test_lo_que_no_encaja_sale_VACIO_y_no_other(self, store):
        """Vacío es «no lo sé»; `other` sería una respuesta, y una respuesta inventada."""
        from lib.core.dcim import service
        assert service.role_hint({'ports': {}}) == ''
        assert service.role_hint(None) == ''

    def test_los_puertos_se_leen_tambien_guardados_como_texto(self, store):
        """En la base de datos viajan como JSON; en memoria, como diccionario. Que solo funcione
        con uno de los dos es un fallo que aparece al pasar de un test a la pantalla."""
        from lib.core.dcim import service
        assert service.role_hint({'ports': '{"power-outlets": {"c13": 8}}'}) == 'pdu'


class TestUnPanelKeystoneSeCompraVacio:
    """Un panel keystone son N huecos y lo que se les mete lo decide quien lo monta: dos paneles
    del mismo modelo llevan cosas distintas. Así que lo que lleva no puede salir del modelo — es
    de cada panel, que es donde ya viven las piezas de un equipo.
    """

    def test_hay_una_clase_para_lo_que_puebla_un_hueco(self):
        """`accessory` valía para guardarlo y no para preguntarle nada: mezclado con los raíles
        y los cargadores, «qué hay puesto en el hueco 7» no tiene a quién preguntárselo."""
        from lib.core.dcim.store import PART_KINDS
        assert 'jack' in PART_KINDS

    def test_y_es_tambien_una_clase_del_catalogo_de_componentes(self):
        """De un modelo de componente sale una pieza: si el catálogo no puede tener modelos de
        conector, cada panel tiene que teclear la marca y el modelo de sus veinticuatro."""
        from lib.core.dcim import catalog
        assert 'jack' in catalog.kinds_for(catalog.COMPONENT_TREE)


class TestUnEnlaceVistoVieneListoParaDeclararlo:
    """El descubrimiento propone; lo que manda es lo apuntado. Pero un enlace que sólo se puede
    mirar obliga a copiarlo a mano de la fila de arriba, que es la forma más segura de que nadie
    lo copie — y de que el que se copie lleve una errata.
    """

    def _edges(self):
        return [{'kind': 'lldp', 'from': 'h1', 'to': 'h2',
                 'ports': {'h1': 'eno1', 'h2': ['gi9']}}]

    def test_trae_los_dos_equipos_y_las_dos_bocas(self):
        from lib.core.dcim import service
        r = service.cable_check([], [{'uid': 'i1', 'host_uid': 'h1'},
                                     {'uid': 'i2', 'host_uid': 'h2'}], self._edges())
        f = r['undeclared'][0]
        assert {f['a_item'], f['b_item']} == {'i1', 'i2'}
        assert {f['a_port'], f['b_port']} == {'eno1', 'gi9'}

    def test_y_no_se_inventa_una_boca_cuando_el_lado_dijo_varias(self):
        """Un agregado de cuatro enlaces dice cuatro nombres por lado, y elegir el primero
        escribiría un cable en una boca que nadie ha dicho que sea ésa."""
        from lib.core.dcim import service
        edges = [{'kind': 'lldp', 'from': 'h1', 'to': 'h2',
                  'ports': {'h1': ['eth1', 'eth2'], 'h2': 'gi9'}}]
        f = service.cable_check([], [{'uid': 'i1', 'host_uid': 'h1'},
                                     {'uid': 'i2', 'host_uid': 'h2'}], edges)['undeclared'][0]
        por_lado = {f['a_item']: f['a_port'], f['b_item']: f['b_port']}
        assert por_lado['i1'] == '' and por_lado['i2'] == 'gi9'

    def test_lo_declarado_deja_de_ser_una_sugerencia(self):
        """Y ésa es la razón de no escribirlo solo: si el panel apuntara lo que ve, lo visto y lo
        declarado serían lo mismo y el contraste no podría decir nunca «esto se movió»."""
        from lib.core.dcim import service
        r = service.cable_check([{'uid': 'c1', 'a_item': 'i1', 'b_item': 'i2',
                                  'a_port': 'eno1', 'b_port': 'gi9'}],
                                [{'uid': 'i1', 'host_uid': 'h1'},
                                 {'uid': 'i2', 'host_uid': 'h2'}], self._edges())
        assert r['undeclared'] == []
        assert r['cables'][0]['seen'] == 'seen'

    def test_y_si_alguien_mueve_el_latiguillo_se_dice(self):
        from lib.core.dcim import service
        r = service.cable_check([{'uid': 'c1', 'a_item': 'i1', 'b_item': 'i2',
                                  'a_port': 'eno1', 'b_port': 'gi9'}],
                                [{'uid': 'i1', 'host_uid': 'h1'},
                                 {'uid': 'i2', 'host_uid': 'h2'}],
                                [{'kind': 'lldp', 'from': 'h1', 'to': 'h2',
                                  'ports': {'h1': 'eno7', 'h2': 'gi22'}}])
        assert r['cables'][0]['seen'] == 'other_port'
        assert r['cables'][0]['ports_seen'] == ['eno7', 'gi22']


class TestUnaFilaQueSonCuatroCablesLoDice:
    """Un agregado de cuatro puertos entre el router y el switch es UN cable declarado y CUATRO
    latiguillos. La fila decía «coincide» sin bocas y sin número: el día que se caiga uno de los
    cuatro, la pantalla que existe para contarlo sigue en verde.
    """

    def _check(self, bundle=4):
        from lib.core.dcim import service
        return service.cable_check(
            [{'uid': 'c1', 'a_item': 'i1', 'b_item': 'i2'}],
            [{'uid': 'i1', 'host_uid': 'h1'}, {'uid': 'i2', 'host_uid': 'h2'}],
            [{'kind': 'lldp', 'from': 'h1', 'to': 'h2', 'bundle': bundle,
              'ports': {'h1': ['gi25', 'gi26'], 'h2': ['ether11', 'ether12']}}])

    def test_cuantos_enlaces_hay_detras(self):
        assert self._check()['cables'][0]['bundle'] == 4

    def test_y_uno_solo_sigue_siendo_uno(self):
        assert self._check(1)['cables'][0]['bundle'] == 1

    def test_las_bocas_vistas_estan_aunque_cuadren(self):
        """Sin ellas, la ficha de un agregado no tiene de dónde sacar de qué cuatro puertos
        habla — y era el caso que más hay que mirar."""
        f = self._check()['cables'][0]
        assert f['seen'] == 'seen'
        assert f['ports_seen'] == ['ether11', 'ether12', 'gi25', 'gi26']


class TestElCableadoNoPagaElMapaEntero:
    """La reconciliación usa **sólo** los enlaces `lldp`. Armar el mapa entero incluye leer las
    cuatro tablas de lo que cada equipo ha visto pasar —la de MAC la primera, sin cota— y se
    leían y se tiraban en cada apertura de la pestaña: una pregunta sobre UN armario pagando el
    inventario de direcciones de la flota.
    """

    def test_solo_mira_los_enlaces_lldp(self):
        from lib.core.dcim import service
        items = [{'uid': 'i1', 'host_uid': 'h1'}, {'uid': 'i2', 'host_uid': 'h2'}]
        # Un enlace deducido de una tabla de puertos NO es un enlace declarable: nadie lo ha
        # visto verse, se ha inferido de por dónde pasó una MAC.
        r = service.cable_check([], items, [{'kind': 'port', 'from': 'h1', 'to': 'h2',
                                             'ports': {'h1': 'gi1'}}])
        assert r['undeclared'] == []

    def test_y_el_mapa_deja_pedirlo_sin_ella(self):
        from lib.core.infra import service as infra_svc
        assert 'fdb' in infra_svc.EVIDENCE_KINDS
        import inspect
        firma = inspect.signature(infra_svc.topology)
        assert 'evidence_kinds' in firma.parameters,             'volver a leer las cuatro tablas es otra vez obligatorio'
        assert firma.parameters['evidence_kinds'].default == infra_svc.EVIDENCE_KINDS,             'el mapa deja de leerlas por defecto, que es lo contrario de lo que hacía falta'


class TestNoPreguntadoNoEsNoSeVe:
    """La lista rápida —la que sale mientras el mapa de la flota se arma— saldría entera diciendo
    «no se ve» si el contraste tratara «sin preguntar» y «preguntado y nada» como lo mismo. Y eso
    es un veredicto, de los peores: manda a buscar un cable que está bien porque todavía nadie ha
    mirado.
    """

    def _cables(self):
        return [{'uid': 'c1', 'a_item': 'i1', 'b_item': 'i2'}]

    def _items(self):
        return [{'uid': 'i1', 'host_uid': 'h1', 'label': 'A'},
                {'uid': 'i2', 'host_uid': 'h2', 'label': 'B'}]

    def test_sin_preguntar_ninguna_fila_lleva_veredicto(self):
        from lib.core.dcim import service
        r = service.cable_check(self._cables(), self._items())
        assert r['checked'] is False
        assert all('seen' not in c for c in r['cables'])
        assert r['counts'] == {} and r['undeclared'] == []

    def test_pero_las_filas_estan_y_con_su_nombre(self):
        """Es lo único que se pide de esa primera vuelta: que la tabla se pueda pintar."""
        from lib.core.dcim import service
        r = service.cable_check(self._cables(), self._items())
        assert [c['a_label'] for c in r['cables']] == ['A']
        assert [c['b_label'] for c in r['cables']] == ['B']

    def test_y_preguntado_sin_ver_nada_si_lleva_veredicto(self):
        from lib.core.dcim import service
        r = service.cable_check(self._cables(), self._items(), [])
        assert r['checked'] is True
        assert r['cables'][0]['seen'] == 'unseen'


class TestUnEnlacePorPanelDeParcheo:
    """Son **tres cables y un camino**: el latiguillo al panel, el enlace fijo entre paneles y el
    latiguillo al switch. Los tres se declaran, ninguno se puede confirmar solo —un panel es un
    trozo de metal— y el enlace que ven los dos extremos salía como «sin declarar» estando
    declarado en tres tramos: la lista de trabajo pendiente incluía trabajo ya hecho.
    """

    def _via(self, rol_medio='patch_panel'):
        return ([{'uid': 'srv', 'host_uid': 'h1', 'role': 'server', 'label': 'SRV'},
                 {'uid': 'pa', 'role': rol_medio, 'label': 'PP-A'},
                 {'uid': 'pb', 'role': rol_medio, 'label': 'PP-B'},
                 {'uid': 'sw', 'host_uid': 'h2', 'role': 'switch', 'label': 'SW'}],
                [{'uid': 'c1', 'a_item': 'srv', 'a_port': 'eno1', 'b_item': 'pa'},
                 {'uid': 'c2', 'a_item': 'pa', 'b_item': 'pb'},
                 {'uid': 'c3', 'a_item': 'pb', 'b_item': 'sw', 'b_port': 'gi1'}],
                [{'kind': 'lldp', 'from': 'h1', 'to': 'h2',
                  'ports': {'h1': 'eno1', 'h2': 'gi1'}}])

    def test_el_camino_explica_el_enlace(self):
        from lib.core.dcim import service
        items, cables, edges = self._via()
        r = service.cable_check(cables, items, edges)
        assert r['undeclared'] == [], 'lo declarado en tres tramos sigue saliendo como pendiente'

    def test_y_los_tres_tramos_quedan_confirmados(self):
        """Ninguno podía confirmarse solo; el camino sí, y entonces se dice."""
        from lib.core.dcim import service
        items, cables, edges = self._via()
        r = service.cable_check(cables, items, edges)
        assert {c['seen'] for c in r['cables']} == {'via'}
        assert r['counts']['via'] == 3

    def test_sin_que_nadie_los_vea_siguen_siendo_pasivos(self):
        """Un panel sin nadie que confirme el camino no es un fallo: es que nadie puede mirarlo.
        Marcarlo en rojo llenaría la pantalla de avisos imposibles de resolver."""
        from lib.core.dcim import service
        items, cables, _edges = self._via()
        r = service.cable_check(cables, items, [])
        assert {c['seen'] for c in r['cables']} == {'passive'}

    def test_no_se_atraviesa_un_switch(self):
        """Dos máquinas enchufadas al mismo switch no están enchufadas entre sí, y decir que sí
        sería inventarse un cable que nadie ha puesto."""
        from lib.core.dcim import service
        items, cables, edges = self._via(rol_medio='switch')
        r = service.cable_check(cables, items, edges)
        assert [x['from'] for x in r['undeclared']],             'el camino atraviesa un switch: se inventa un enlace'

    def test_ni_un_equipo_ajeno(self):
        """No se puede confirmar un camino a través de algo que no se puede ni mirar."""
        from lib.core.dcim import service
        items, cables, edges = self._via()
        items = [dict(i, role='', foreign=True) if i['uid'] == 'pa' else i for i in items]
        r = service.cable_check(cables, items, edges)
        assert r['undeclared'], 'el camino atraviesa un equipo ajeno'

    def test_y_un_ciclo_declarado_por_error_no_lo_cuelga(self):
        from lib.core.dcim import service
        items = [{'uid': 'srv', 'host_uid': 'h1', 'role': 'server'},
                 {'uid': 'pa', 'role': 'patch_panel'}, {'uid': 'pb', 'role': 'patch_panel'}]
        cables = [{'uid': 'c1', 'a_item': 'srv', 'b_item': 'pa'},
                  {'uid': 'c2', 'a_item': 'pa', 'b_item': 'pb'},
                  {'uid': 'c3', 'a_item': 'pb', 'b_item': 'pa'}]
        assert service.cable_check(cables, items, [])['counts']['passive'] == 3


class TestUnPuenteEnElMismoPanel:
    """Un latiguillo corto de la boca 25 a la 17 del mismo panel es lo más normal del mundo, y se
    rechazaba de plano con «un cable va de un equipo a OTRO» — cierto para dos servidores y falso
    para un panel, que es media sala.
    """

    def _items(self):
        return [{'uid': 'srv', 'host_uid': 'h1', 'role': 'server'},
                {'uid': 'pp', 'role': 'patch_panel'},
                {'uid': 'sw', 'host_uid': 'h2', 'role': 'switch'}]

    def _edges(self):
        return [{'kind': 'lldp', 'from': 'h1', 'to': 'h2',
                 'ports': {'h1': 'eno1', 'h2': 'gi1'}}]

    def _cables(self, con_puente=True):
        fuera = [{'uid': 'c1', 'a_item': 'srv', 'a_port': 'eno1',
                  'b_item': 'pp', 'b_port': '25'},
                 {'uid': 'c3', 'a_item': 'pp', 'a_port': '17',
                  'b_item': 'sw', 'b_port': 'gi1'}]
        if con_puente:
            fuera.append({'uid': 'j', 'a_item': 'pp', 'a_port': '25',
                          'b_item': 'pp', 'b_port': '17'})
        return fuera

    def test_el_puente_completa_el_camino(self):
        from lib.core.dcim import service
        r = service.cable_check(self._cables(), self._items(), self._edges())
        assert r['undeclared'] == []
        assert {c['seen'] for c in r['cables']} == {'via'}

    def test_y_sin_el_no_hay_camino(self):
        """Se anda por BOCAS: lo que entra por la 25 sale por la 25, no por la 17. Andar por el
        panel entero daría por explicado cualquier par de cables que lo tocaran, y entonces
        «confirmado» dejaría de querer decir nada."""
        from lib.core.dcim import service
        r = service.cable_check(self._cables(con_puente=False), self._items(), self._edges())
        assert len(r['undeclared']) == 1
        assert {c['seen'] for c in r['cables']} == {'passive'}

    def test_sin_bocas_escritas_se_vuelve_a_lo_de_antes(self):
        """Todas las bocas de un panel son la misma cuando nadie las apuntó: menos preciso, que
        es exactamente lo que se sabe."""
        from lib.core.dcim import service
        cables = [{'uid': 'c1', 'a_item': 'srv', 'a_port': 'eno1', 'b_item': 'pp'},
                  {'uid': 'c3', 'a_item': 'pp', 'b_item': 'sw', 'b_port': 'gi1'}]
        r = service.cable_check(cables, self._items(), self._edges())
        assert r['undeclared'] == []


class TestLaTrazaDelEnlace:
    """«Por el panel» sin decir por CUÁL ni por qué boca obliga a reconstruirlo a mano cable a
    cable, que es tanto trabajo como ir a mirarlo — y es la pregunta que se hace delante del
    armario con el latiguillo en la mano.
    """

    def _todo(self):
        items = [{'uid': 'srv', 'host_uid': 'h1', 'role': 'server', 'label': 'SRV'},
                 {'uid': 'pa', 'role': 'patch_panel', 'label': 'PP-A'},
                 {'uid': 'pb', 'role': 'patch_panel', 'label': 'PP-B'},
                 {'uid': 'sw', 'host_uid': 'h2', 'role': 'switch', 'label': 'SW'}]
        cables = [{'uid': 'c1', 'a_item': 'srv', 'a_port': 'eno1',
                   'b_item': 'pa', 'b_port': '25'},
                  {'uid': 'j', 'a_item': 'pa', 'a_port': '25', 'b_item': 'pa', 'b_port': '17'},
                  # Declarado al revés a propósito: un cable se apunta desde el extremo que se
                  # tenía delante, y la mitad de un camino está escrita en el otro sentido.
                  {'uid': 'c2', 'a_item': 'pb', 'a_port': '3', 'b_item': 'pa', 'b_port': '17'},
                  {'uid': 'c3', 'a_item': 'pb', 'a_port': '3', 'b_item': 'sw', 'b_port': 'gi1'}]
        edges = [{'kind': 'lldp', 'from': 'h1', 'to': 'h2',
                  'ports': {'h1': 'eno1', 'h2': 'gi1'}}]
        from lib.core.dcim import service
        return service.cable_check(cables, items, edges)

    def test_el_camino_viaja_entero_y_en_orden(self):
        r = self._todo()
        assert len(r['paths']) == 1
        pasos = [(l['a_item'], l['a_port'], l['b_item'], l['b_port'])
                 for l in r['paths'][0]['legs']]
        assert pasos == [('srv', 'eno1', 'pa', '25'), ('pa', '25', 'pa', '17'),
                         ('pa', '17', 'pb', '3'), ('pb', '3', 'sw', 'gi1')]

    def test_orientado_hacia_donde_se_recorre(self):
        """`c2` está declarado de PB a PA y en el camino se anda de PA a PB: una traza que va
        «SRV → PP» y luego «SW → PP» no se puede leer."""
        r = self._todo()
        c2 = [l for l in r['paths'][0]['legs'] if l['cable'] == 'c2'][0]
        assert (c2['a_item'], c2['b_item']) == ('pa', 'pb')

    def test_con_el_nombre_de_cada_punta(self):
        """Un camino que pasa por el panel del armario de al lado nombra equipos que la pantalla
        no tiene delante."""
        r = self._todo()
        primero = r['paths'][0]['legs'][0]
        assert primero['a_label'] == 'SRV' and primero['b_label'] == 'PP-A'
        assert primero['b_role'] == 'patch_panel'

    def test_y_cada_tramo_sabe_de_que_camino_es(self):
        r = self._todo()
        assert all(c.get('paths') == [0] for c in r['cables'])


class TestUnCableDeCorrienteEsUnCable:
    """`dc_feed` decía de qué toma cuelga y cuántos vatios se declararon, y nada más — como si el
    latiguillo no existiera. Y existe: se compra, se guarda en una caja, se rompe y hay que
    sustituirlo, y la pregunta de la caja de repuestos es la misma que en datos.
    """

    def test_lo_que_se_guarda_vuelve(self):
        from lib.core.dcim import service
        r = service.power_of_rack(
            [{'uid': 'a', 'name': 'A', 'feed': 'a', 'outlets': 8}],
            [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a', 'outlet': 3,
              'label': 'P-07', 'asset': 'INV-991', 'category': 'c13-c14',
              'length_mm': 500, 'description': 'por detrás', 'watts_said': 250}],
            [{'uid': 'i1', 'label': 'SRV'}])
        f = r['items'][0]['feeds'][0]
        assert f['label'] == 'P-07' and f['asset'] == 'INV-991'
        assert f['category'] == 'c13-c14' and f['length_mm'] == 500
        assert f['description'] == 'por detrás' and f['watts_said'] == 250

    def test_y_lo_que_no_se_dijo_vuelve_vacio_y_no_ausente(self):
        """Una clave que unas veces está y otras no obliga a quien lee a saber cuál de los dos
        casos tiene delante."""
        from lib.core.dcim import service
        r = service.power_of_rack(
            [{'uid': 'a', 'name': 'A', 'feed': 'a', 'outlets': 8}],
            [{'uid': 'c1', 'item_uid': 'i1', 'pdu_uid': 'a'}],
            [{'uid': 'i1'}])
        f = r['items'][0]['feeds'][0]
        for k in ('label', 'asset', 'category', 'description'):
            assert f[k] == '', k
        assert f['length_mm'] == 0

    def test_las_dos_tablas_llaman_igual_a_lo_mismo(self):
        """Dos tablas que guardan lo mismo con nombres distintos son dos pantallas que se
        escriben dos veces."""
        from lib.core.dcim.store import SCHEMAS
        cols = {t.name: {c.name for c in t.columns} for t in SCHEMAS}
        comun = {'asset', 'category', 'length_mm', 'description', 'label'}
        assert comun <= cols['dc_cable'], comun - cols['dc_cable']
        assert comun <= cols['dc_feed'], comun - cols['dc_feed']


class TestBuscarEnLaBaseYNoEnMemoria:
    """Traer la tabla entera para quedarse con treinta filas construye un diccionario por fila de
    toda la instalación y luego lo tira. En una sala pequeña no se nota, que es exactamente lo
    que hace que se escriba así y se descubra tarde.
    """

    def test_el_texto_se_busca_sin_distinguir_mayusculas(self):
        """MySQL no distingue por defecto, SQLite sí y PostgreSQL depende del idioma del
        sistema: un buscador que encuentra «SW01» escribiendo `sw` en una instalación y no en
        otra es el mismo panel comportándose de dos maneras según dónde esté instalado."""
        from lib.core.dcim.store import like_clause
        sql, params = like_clause(('label',), 'SW01')
        assert 'LOWER(label) LIKE ?' in sql
        assert params == ('%sw01%',)

    def test_los_comodines_del_LIKE_se_escapan(self):
        """`_` y `%` son caracteres que alguien puede teclear. Sin escaparlos, teclear `_`
        encuentra cualquier cosa y teclear `%` las encuentra todas — un buscador que ignora lo
        que se le pide es peor que uno que no encuentra nada, porque contesta."""
        from lib.core.dcim.store import like_clause
        _sql, params = like_clause(('label',), 'PP_1%')
        assert params == ('%pp\\_1\\%%',)

    def test_sin_texto_no_hay_condicion(self):
        """Una condición vacía que se cuela en un `WHERE` es un error de sintaxis; una que dice
        `LIKE '%%'` es una tabla entera con otro nombre."""
        from lib.core.dcim.store import like_clause
        assert like_clause(('label',), '   ') == ('', ())
        assert like_clause((), 'x') == ('', ())


class TestRecorrerSinTraerloTodo:
    """Quién puede ver qué sale de una cadena de pertenencia que no está en ninguna columna, así
    que ese filtro no puede ir al `WHERE`. Lo que sí puede es no traerse la tabla entera para
    aplicarlo.
    """

    def _leer(self, total):
        filas = [{'uid': f'i{n}', 'n': n} for n in range(total)]
        return lambda lim, off: filas[off:off + lim]

    def test_devuelve_las_primeras_que_pasan(self):
        from lib.core.dcim.routes._common import scan_pages
        r = scan_pages(self._leer(1000), lambda f: f['n'] % 10 == 0, 5)
        assert [f['n'] for f in r['rows'][:5]] == [0, 10, 20, 30, 40]

    def test_un_trozo_se_termina_siempre(self):
        """Parar a mitad y seguir en el siguiente dejaría fuera para siempre las filas que
        quedaban detrás en ése: el próximo salto empieza donde acabó el trozo."""
        from lib.core.dcim.routes._common import scan_pages, SCAN_CHUNK
        r = scan_pages(self._leer(1000), lambda f: True, 3)
        assert r['next_offset'] == SCAN_CHUNK
        assert len(r['rows']) == SCAN_CHUNK

    def test_y_se_dice_cuando_se_acaba_el_presupuesto(self):
        """«Se acabó el presupuesto» y «hay más» son dos cosas distintas, y sólo una es un
        problema de quien mira."""
        from lib.core.dcim.routes._common import scan_pages
        # Nadie pasa: se recorre el presupuesto entero y se dice que quedó cortado.
        r = scan_pages(self._leer(100000), lambda f: False, 5)
        assert r['rows'] == [] and r['capped'] is True

    def test_una_tabla_que_se_acaba_no_esta_recortada(self):
        from lib.core.dcim.routes._common import scan_pages
        r = scan_pages(self._leer(10), lambda f: True, 100)
        assert len(r['rows']) == 10 and r['capped'] is False


class TestLaTiradaDeUnCable:
    """**Un enlace que atraviesa un panel son tres cables y una tirada.**

    La ficha de uno de los tres enseñaba ese cable solo —«del panel A boca 12 al panel B boca
    12»—, que no dice de dónde viene ni a dónde va. La pregunta que se hace delante del armario
    con el latiguillo en la mano es la otra: de qué tirada forma parte esto y en qué posición.

    Y es un hecho **declarado**: el camino que dibuja la pestaña de un armario sale de cruzar lo
    escrito con lo que los dispositivos ven, así que una tirada que nadie confirma —dos paneles y
    un latiguillo, sin LLDP de por medio— no salía en ninguna parte estando declarada entera.
    """

    ITEMS = [{'uid': 'srv', 'host_uid': 'h-srv', 'role': 'server', 'label': 'SRV01'},
             {'uid': 'ppA', 'role': 'patch_panel', 'label': 'PP-A'},
             {'uid': 'ppB', 'role': 'patch_panel', 'label': 'PP-B'},
             {'uid': 'sw', 'host_uid': 'h-sw', 'role': 'switch', 'label': 'SW01'}]
    CABLES = [{'uid': 'c1', 'a_item': 'srv', 'a_port': 'eth0', 'b_item': 'ppA', 'b_port': '12'},
              {'uid': 'c2', 'a_item': 'ppB', 'a_port': '12', 'b_item': 'ppA', 'b_port': '12'},
              {'uid': 'c3', 'a_item': 'sw', 'a_port': 'Gi1/0/7', 'b_item': 'ppB',
               'b_port': '12'}]

    def _uids(self, r):
        return [t['cable'] for t in (r or {}).get('legs') or ()]

    def test_los_tres_tramos_en_orden(self):
        r = service.run_of('c2', self.CABLES, self.ITEMS)
        assert self._uids(r) == ['c1', 'c2', 'c3']
        assert r['ends'] == ['srv', 'sw']

    def test_desde_cualquiera_de_ellos_es_la_misma(self):
        """Sin esto el sentido lo decidía por cuál se hubiera preguntado: la ficha del latiguillo
        la enseñaba «servidor → switch» y la del troncal al revés. Es la misma tirada, y dos
        dibujos distintos de lo mismo hacen dudar de si son dos."""
        cual = [service.run_of(u, self.CABLES, self.ITEMS) for u in ('c1', 'c2', 'c3')]
        assert [self._uids(r) for r in cual] == [['c1', 'c2', 'c3']] * 3

    def test_orientada_hacia_donde_se_recorre(self):
        """Un cable se declara desde el extremo que se tenía delante, así que la mitad de los
        tramos están escritos al revés: `c2` se guardó de ppB a ppA y la tirada lo recorre al
        contrario."""
        legs = service.run_of('c1', self.CABLES, self.ITEMS)['legs']
        assert [(t['a_item'], t['b_item']) for t in legs] == [
            ('srv', 'ppA'), ('ppA', 'ppB'), ('ppB', 'sw')]

    def test_se_anda_por_bocas_y_no_por_paneles(self):
        """Un panel de veinticuatro posiciones no es un nudo donde todo lo que entra sale por
        cualquier sitio: lo que entra por la 12 sale por la 12. Otro cable en la 13 del mismo
        panel no es la misma tirada."""
        mas = self.CABLES + [{'uid': 'x1', 'a_item': 'ppA', 'a_port': '13',
                              'b_item': 'srv', 'b_port': 'eth1'}]
        assert self._uids(service.run_of('c1', mas, self.ITEMS)) == ['c1', 'c2', 'c3']

    def test_no_se_atraviesa_lo_que_no_es_un_panel(self):
        """Atravesar un switch sería inventarse un cable: dos máquinas enchufadas al mismo switch
        no están enchufadas entre sí."""
        mas = self.CABLES + [{'uid': 'x2', 'a_item': 'sw', 'a_port': 'Gi1/0/7',
                              'b_item': 'srv', 'b_port': 'eth9'}]
        assert self._uids(service.run_of('c1', mas, self.ITEMS)) == ['c1', 'c2', 'c3']

    def test_ni_lo_ajeno(self):
        """Un equipo de otra sociedad llega opaco —existe y ocupa, nada más— y no se puede
        afirmar un camino a través de algo que no se puede ni mirar."""
        items = [dict(i, foreign=True, role='') if i['uid'] == 'ppB' else i for i in self.ITEMS]
        assert self._uids(service.run_of('c1', self.CABLES, items)) == ['c1', 'c2']

    def test_un_cable_suelto_es_su_propia_tirada(self):
        solo = [{'uid': 'z', 'a_item': 'srv', 'a_port': 'eth3', 'b_item': 'sw', 'b_port': 'Gi2'}]
        assert self._uids(service.run_of('z', solo, self.ITEMS)) == ['z']

    def test_un_cable_que_no_esta_no_tiene_tirada(self):
        assert service.run_of('nada', self.CABLES, self.ITEMS) == {}

    def test_una_boca_con_dos_salidas_para_el_paseo(self):
        """Eso no es una tirada, es un dato torcido: de una boca de un panel salen el latiguillo
        y el troncal, no tres cables. Elegir uno de los dos sería dibujar un camino que nadie ha
        declarado."""
        lio = self.CABLES + [{'uid': 'c4', 'a_item': 'ppA', 'a_port': '12',
                              'b_item': 'ppB', 'b_port': '12'}]
        assert self._uids(service.run_of('c1', lio, self.ITEMS)) == ['c1']

    def test_un_bucle_declarado_no_cuelga_el_paseo(self):
        """Un panel puenteado consigo mismo en redondo: sin tope, el paseo no termina."""
        aro = [{'uid': f'a{i}', 'a_item': 'ppA', 'a_port': str(i),
                'b_item': 'ppA', 'b_port': str(i + 1)} for i in range(20)]
        assert len(service.run_of('a0', aro, self.ITEMS)['legs']) <= 8

    def test_cada_tramo_lleva_lo_suyo_del_cable(self):
        """La pantalla lo sacaba de la lista que tenía cargada, y desde la sección de cableado
        esa lista no existe: la tirada salía sin etiquetas, sin metros y sin colores — casi todo
        lo que distingue un tramo del de al lado."""
        cables = [dict(c, label='L-' + c['uid'], length_mm=250, color='#abc', kind='copper')
                  for c in self.CABLES]
        legs = service.with_cable(service.run_of('c1', cables, self.ITEMS)['legs'], cables)
        assert [t['label'] for t in legs] == ['L-c1', 'L-c2', 'L-c3']
        assert all(t['length_mm'] == 250 and t['color'] == '#abc' for t in legs)

    def test_y_el_nombre_y_el_sitio_de_cada_parada(self):
        """Una tirada que pasa por el panel del armario de al lado nombra equipos que la pantalla
        no tiene delante: sin esto sale llena de identificadores."""
        items = [dict(i, rack_name='RK1', rack_uid='r1', u_start=7) for i in self.ITEMS]
        legs = service.label_legs(service.run_of('c1', self.CABLES, items)['legs'], items)
        assert legs[0]['a_label'] == 'SRV01' and legs[0]['b_role'] == 'patch_panel'
        assert legs[0]['b_at'] == {'rack': 'RK1', 'rack_uid': 'r1', 'u': 7}


class TestLoQueYaSeUsa:
    """Ofrecer lo que la casa ya usa, en vez de una lista escrita a mano.

    Los colores de latiguillo de una instalación son cinco, y elegirlos de una rueda de dieciséis
    millones la deja con nueve azules que no son el mismo azul. La lista sale de los datos: es la
    única que no se queda vieja.
    """

    def _cables(self, store, *colores):
        for c in colores:
            store.cables.create({'a_item': 'a', 'b_item': 'b', 'color': c})

    def test_del_mas_usado_al_menos(self, store):
        """Es el orden en que se elige: el color que hay en cuarenta cables es el que va a llevar
        el cuarenta y uno. Alfabéticamente serían códigos hexadecimales ordenados por su primera
        letra, que no significa nada."""
        self._cables(store, '#f00', '#00f', '#00f', '#00f', '#0f0', '#0f0')
        assert store.cables.in_use('color') == ['#00f', '#0f0', '#f00']

    def test_lo_vacio_no_es_un_valor(self, store):
        """«Nadie lo ha dicho» le pasa a cuarenta cables y no es un color que ofrecer."""
        self._cables(store, '', '', '#f00')
        assert store.cables.in_use('color') == ['#f00']

    def test_con_tope(self, store):
        """Una instalación tiene cinco o seis; un desplegable con cuarenta códigos hexadecimales
        no es una ayuda, es otra rueda."""
        self._cables(store, '#1', '#2', '#2', '#3', '#3', '#3')
        assert store.cables.in_use('color', 2) == ['#3', '#2']

    def test_los_colores_se_cuentan_entre_TODAS_las_tablas(self, store):
        """Un latiguillo rojo y un cable de corriente rojo son el mismo rojo. Contándolos por
        separado, el rojo de veinte cables de datos y el de veinte de corriente saldrían como dos
        colores de veinte en vez de uno de cuarenta — y el que la casa más usa no saldría el
        primero, que es lo único que se le pide a esta lista."""
        self._cables(store, '#00f', '#00f', '#f00')
        for _ in range(3):
            store.feeds.create({'item_uid': 'x', 'pdu_uid': 'p', 'color': '#f00'})
        assert store.colors_used() == ['#f00', '#00f']

    def test_y_un_empate_no_baila(self, store):
        """Dos colores empatados a tres cables tienen que salir siempre en el mismo orden, o la
        lista cambia entre dos aperturas sin que nadie haya tocado nada."""
        self._cables(store, '#bbb', '#aaa')
        assert store.colors_used() == ['#aaa', '#bbb']

    def test_y_una_columna_que_esa_tabla_no_tiene_no_es_un_error(self, store):
        """La misma pregunta se le puede hacer a cualquier tabla, y la que no la lleva contesta
        que no tiene ninguno — que es la verdad, no un fallo."""
        assert store.items.in_use('color') == []
