#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las plantillas: lo que de verdad se compra, entre el catálogo y el inventario.

Lo que se prueba aquí es el escalón que faltaba y las dos decisiones que lo sostienen: que una
plantilla **se estampa y no se enlaza** —lo que sale de ella son piezas de un equipo, sin su
número de serie— y que la diferencia entre lo que una máquina lleva y lo que su plantilla decía
**es un dato y no un error**.

Y el cuarto árbol del catálogo, que es lo que hace posible lo anterior: los modelos de
componente, con **su propio vocabulario de clases**. Un DIMM no es «switch, servidor u otro».
"""

from __future__ import annotations

import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim import builds                                     # noqa: E402
from lib.core.dcim import catalog                                    # noqa: E402
from lib.core.dcim.store import (ITEM_ROLES, PART_KINDS, PORT_LIST_MAX,  # noqa: E402
                                 PORT_SIGNALS_MAX, clean_port_list)
from lib.db import get_connector                                     # noqa: E402


@pytest.fixture()
def store():
    db = get_connector({'type': 'sqlite', 'path': ':memory:'})
    yield builds.BuildStore(db)
    try:
        db.close()
    except Exception:                           # pylint: disable=broad-except
        pass


# ══ El cuarto árbol ═════════════════════════════════════════════════════════════════════

class TestElVocabularioLoDecideElArbol:

    def test_un_componente_no_usa_las_clases_de_los_que_ocupan_u(self):
        """Ofrecer «switch» para un DIMM acabaría ofreciendo el DIMM en un alzado."""
        assert catalog.kinds_for('component-types') == PART_KINDS
        assert catalog.kinds_for('device-types') == catalog.KINDS
        assert 'memory' in catalog.kinds_for('component-types')
        assert 'memory' not in catalog.kinds_for('device-types')

    def test_el_arbol_de_componentes_no_se_descarga_de_ninguna_parte(self):
        """Dos listas y no una: qué se puede IMPORTAR y qué puede SER una fila. Mezcladas, el
        importador saldría a buscar una carpeta que no existe en ningún repositorio."""
        assert catalog.COMPONENT_TREE in catalog.TREES
        assert catalog.COMPONENT_TREE not in catalog.LIBRARY_TREES

    def test_lo_que_la_fila_dice_manda_sobre_el_nombre(self):
        fila = {'tree': 'component-types', 'model': 'PERC H740P', 'kind': 'hba'}
        assert catalog.kind_of(fila) == 'hba'

    def test_y_si_no_dice_nada_lo_dice_el_nombre(self):
        """Un componente no declara puertos —una memoria no tiene ninguno— así que el nombre es
        la única señal que queda."""
        assert catalog.kind_of({'tree': 'component-types',
                                'model': 'KSM32RD8/32 DDR4 RDIMM'}) == 'memory'
        assert catalog.kind_of({'tree': 'component-types',
                                'model': 'PM9A3 1.92TB NVMe'}) == 'ssd'
        assert catalog.kind_of({'tree': 'component-types',
                                'model': 'Xeon Gold 6248R'}) == 'cpu'

    def test_y_si_el_nombre_tampoco_other_que_es_una_respuesta(self):
        assert catalog.kind_of({'tree': 'component-types', 'model': 'Cosa rara'}) == 'other'


# ══ Lo que se copia ═════════════════════════════════════════════════════════════════════

class TestSeEstampaNoSeEnlaza:

    def test_lo_que_sale_de_una_plantilla_no_lleva_numero_de_serie(self, store):
        """Es el punto entero: el serial es lo único que tiene esa unidad y ninguna otra."""
        uid = store.create({'name': 'CPD estándar'})
        store.part_add(uid, {'kind': 'memory', 'model': 'KSM32RD8/32', 'qty': 12})
        copia = store.stamp(uid)
        assert len(copia) == 1
        assert 'serial' not in copia[0]
        assert copia[0]['qty'] == 12

    def test_ni_el_identificador_de_la_plantilla_ni_el_suyo(self, store):
        """Lo que se devuelve son piezas de un EQUIPO, no piezas de una plantilla."""
        uid = store.create({'name': 'CPD estándar'})
        store.part_add(uid, {'kind': 'disk', 'model': 'X', 'qty': 8})
        pieza = store.stamp(uid)[0]
        assert 'uid' not in pieza and 'build_uid' not in pieza
        assert set(pieza) == set(builds.STAMPED)

    def test_lo_que_se_copia_incluye_el_modelo_del_catalogo(self, store):
        """Con él la pieza dice «este DIMM» y no «32 GB»: la diferencia entre poder pedir el
        recambio y tener que buscarlo."""
        assert 'type_uid' in builds.STAMPED


# ══ La diferencia es el dato ════════════════════════════════════════════════════════════

class TestContraSuPlantilla:

    def test_lo_mismo_no_es_ninguna_diferencia(self):
        piezas = [{'kind': 'memory', 'model': 'KSM32', 'size': '32 GB', 'qty': 12}]
        assert builds.compare(piezas, list(piezas)) == []

    def test_lo_que_falta_se_dice_con_su_cuenta(self):
        quiere = [{'kind': 'disk', 'model': 'PM9A3', 'size': '1.92 TB', 'qty': 8}]
        tiene = [{'kind': 'disk', 'model': 'PM9A3', 'size': '1.92 TB', 'qty': 6}]
        d = builds.compare(quiere, tiene)
        assert len(d) == 1 and d[0]['want'] == 8 and d[0]['have'] == 6 and d[0]['diff'] == -2

    def test_y_lo_que_sobra_tambien_no_solo_lo_que_falta(self):
        d = builds.compare([], [{'kind': 'gpu', 'model': 'A2', 'qty': 1}])
        assert len(d) == 1 and d[0]['want'] == 0 and d[0]['diff'] == 1

    def test_un_cambio_son_dos_renglones_de_la_misma_tabla(self):
        """Cambiar un disco de 4 TB por uno de 8 sale como uno que falta y otro que sobra —y en
        UNA tabla, porque separarlos obliga a leer las dos para entender que fue un cambio."""
        d = builds.compare([{'kind': 'disk', 'model': 'A', 'size': '4 TB', 'qty': 1}],
                           [{'kind': 'disk', 'model': 'A', 'size': '8 TB', 'qty': 1}])
        assert len(d) == 2
        assert sorted(f['diff'] for f in d) == [-1, 1]

    def test_la_marca_forma_parte_de_lo_que_se_compara(self):
        """Dos discos de 4 TB de dos fabricantes no son el mismo disco, y sustituir uno por otro
        es exactamente el cambio que hay que poder ver."""
        d = builds.compare([{'kind': 'disk', 'brand': 'Seagate', 'model': 'X', 'qty': 1}],
                           [{'kind': 'disk', 'brand': 'WD', 'model': 'X', 'qty': 1}])
        assert len(d) == 2 and sorted(f['diff'] for f in d) == [-1, 1]

    def test_y_sale_en_la_diferencia_para_poder_leerla(self):
        d = builds.compare([{'kind': 'ssd', 'brand': 'Samsung', 'model': 'PM9A3', 'qty': 8}], [])
        assert d[0]['brand'] == 'Samsung'

    def test_la_marca_se_estampa_con_lo_demas(self, store):
        """El serial no se copia y la marca sí: uno es de esa unidad, la otra es del modelo."""
        assert 'brand' in builds.STAMPED and 'serial' not in builds.STAMPED
        uid = store.create({'name': 'X'})
        store.part_add(uid, {'kind': 'ssd', 'brand': 'Samsung', 'model': 'PM9A3'})
        assert store.stamp(uid)[0]['brand'] == 'Samsung'

    def test_un_kit_de_dos_cuenta_como_dos(self):
        """Un kit se compra como uno y se monta como dos. Lo que se compara es lo que lleva la
        máquina, así que dos kits de dos y cuatro módulos sueltos son la misma memoria puesta."""
        assert builds.compare(
            [{'kind': 'memory', 'model': 'KSM', 'qty': 2, 'kit_qty': 2}],
            [{'kind': 'memory', 'model': 'KSM', 'qty': 4}]) == []

    def test_y_la_diferencia_se_dice_en_piezas(self):
        d = builds.compare(
            [{'kind': 'memory', 'model': 'KSM', 'qty': 2, 'kit_qty': 2}],
            [{'kind': 'memory', 'model': 'KSM', 'qty': 3}])
        assert d[0]['want'] == 4 and d[0]['have'] == 3

    def test_sin_decir_nada_una_unidad_es_una_pieza(self):
        """Lo que se compra suelto es la mayoría, y no tiene por qué declarar un uno."""
        assert builds.compare([{'kind': 'disk', 'model': 'X', 'qty': 2}],
                              [{'kind': 'disk', 'model': 'X', 'qty': 2, 'kit_qty': 1}]) == []

    def test_el_kit_se_estampa_con_lo_demas(self, store):
        """Una máquina que dice llevar dos kits sigue diciendo cuántos módulos son aunque alguien
        borre el modelo del catálogo."""
        assert 'kit_qty' in builds.STAMPED
        uid = store.create({'name': 'X'})
        store.part_add(uid, {'kind': 'memory', 'model': 'KSM', 'qty': 2, 'kit_qty': 2})
        assert store.stamp(uid)[0]['kit_qty'] == 2

    def test_una_caja_de_cero_piezas_no_es_una_caja(self, store):
        uid = store.create({'name': 'X'})
        store.part_add(uid, {'kind': 'memory', 'kit_qty': 0})
        assert store.parts_of(uid)[0]['kit_qty'] == 1

    def test_la_bahia_no_cuenta_como_diferencia(self):
        """Nadie llena las bahías de veinte máquinas en el mismo orden, y comparar por bahía
        convertiría «los mismos ocho discos en otro sitio» en dieciséis diferencias."""
        assert builds.compare(
            [{'kind': 'disk', 'model': 'A', 'slot': 'bahía 1', 'qty': 1}],
            [{'kind': 'disk', 'model': 'A', 'slot': 'bahía 7', 'qty': 1}]) == []

    def test_ni_las_mayusculas_ni_los_espacios_de_sobra(self):
        assert builds.compare([{'kind': 'memory', 'model': 'KSM32  RD8', 'qty': 2}],
                              [{'kind': 'memory', 'model': 'ksm32 rd8', 'qty': 2}]) == []

    def test_dos_filas_de_lo_mismo_se_suman_antes_de_comparar(self):
        """Seis discos apuntados en dos renglones son seis discos."""
        assert builds.compare(
            [{'kind': 'disk', 'model': 'A', 'qty': 6}],
            [{'kind': 'disk', 'model': 'A', 'qty': 4},
             {'kind': 'disk', 'model': 'A', 'qty': 2}]) == []


# ══ Qué máquina sale de aquí ════════════════════════════════════════════════════════════

class TestElResumenDeUnaPlantilla:
    """Quince renglones de piezas no contestan «qué máquina es esta» sin sumarlos a mano."""

    MODELOS = {'c1': {'extra': {'cores': 20, 'threads': 40}},
               'n1': {'extra': {'ports': 4, 'link_speed': '10 Gbps'}}}

    def test_suma_la_memoria_contando_las_piezas(self):
        d = builds.summary([{'kind': 'memory', 'size': '32 GB', 'qty': 12}])
        assert d['memory_gb'] == 384
        # Y un kit de dos cuenta como dos, igual que en todo lo demás.
        d = builds.summary([{'kind': 'memory', 'size': '32 GB', 'qty': 6, 'kit_qty': 2}])
        assert d['memory_gb'] == 384

    def test_y_el_almacenamiento_en_bruto(self):
        d = builds.summary([{'kind': 'ssd', 'size': '1.92 TB', 'qty': 8}])
        assert d['storage_tb'] == 15.36

    def test_cada_familia_con_su_factor(self):
        """La memoria se vende en potencias de dos y los discos en potencias de diez: un factor
        para las dos haría que la mitad de los totales no coincidieran con ninguna etiqueta."""
        assert builds.summary([{'kind': 'memory', 'size': '1024 MB'}])['memory_gb'] == 1
        assert builds.summary([{'kind': 'disk', 'size': '1000 GB'}])['storage_tb'] == 1

    def test_los_nucleos_salen_del_modelo_y_no_de_la_pieza(self):
        """Están en la ficha del catálogo: la pieza guarda marca, modelo y tamaño."""
        d = builds.summary([{'kind': 'cpu', 'qty': 2, 'type_uid': 'c1'}], self.MODELOS)
        assert d['cpus'] == 2 and d['cores'] == 40 and d['threads'] == 80

    def test_los_puertos_de_red_tambien(self):
        d = builds.summary([{'kind': 'nic', 'qty': 1, 'type_uid': 'n1'}], self.MODELOS)
        assert d['net'] == [{'speed': '10 Gbps', 'ports': 4}]

    def test_las_fuentes_se_cuentan_por_su_potencia(self):
        d = builds.summary([{'kind': 'psu', 'size': '800 W', 'qty': 2}])
        assert d['psu'] == [{'size': '800 W', 'qty': 2}]

    def test_los_puertos_del_chasis_tambien_cuentan(self):
        """Un mini-PC trae una tarjeta en la placa y no lleva ninguna puesta: el resumen decía
        solo la que alguien añadió, y el catálogo las tenía contadas desde el primer día."""
        base = {'ports': {'interfaces': {'1000base-t': 2}}}
        d = builds.summary([{'kind': 'nic', 'qty': 1, 'type_uid': 'n1'}], self.MODELOS, base)
        assert {'speed': '1000base-t', 'ports': 2} in d['net']
        assert {'speed': '10 Gbps', 'ports': 4} in d['net']

    def test_y_llegan_aunque_vengan_como_texto(self):
        """La columna es JSON: quien la lea de la base de datos recibe una cadena."""
        base = {'ports': '{"interfaces": {"1000base-t": 2}}'}
        assert builds.summary([], {}, base)['net'] == [{'speed': '1000base-t', 'ports': 2}]

    def test_por_donde_come_es_del_chasis(self):
        """`is_powered` dice SI come y no dice cómo, y la diferencia entre una fuente dentro y un
        ladrón externo decide si hace falta una toma en la regleta o un enchufe en la pared."""
        d = builds.summary([], {}, {'power_type': 'external', 'is_powered': 1})
        assert d['power_type'] == 'external' and d['powered'] is True
        d = builds.summary([], {}, {'is_powered': 0})
        assert d['powered'] is False and d['power_type'] == ''

    def test_sin_chasis_el_resumen_sigue_saliendo(self):
        """Una plantilla sin modelo base es una plantilla igual."""
        d = builds.summary([{'kind': 'memory', 'size': '16 GB', 'qty': 2}])
        assert d['memory_gb'] == 32 and d['powered'] is None

    def test_lo_que_no_se_puede_contar_se_dice(self):
        """Un total al que le faltan tres discos y no lo dice es peor que no dar el total:
        se cree."""
        d = builds.summary([{'kind': 'ssd', 'size': 'media altura', 'qty': 3},
                            {'kind': 'ssd', 'size': '1 TB', 'qty': 1}])
        assert d['storage_tb'] == 1 and d['unknown'] == 3

    def test_una_cpu_sin_ficha_no_inventa_nucleos(self):
        d = builds.summary([{'kind': 'cpu', 'qty': 2}])
        assert d['cpus'] == 2 and d['cores'] == 0 and d['unknown'] == 2

    def test_lo_que_no_suma_en_nada_no_estorba(self):
        """Una bandeja o un cable no entran en ninguna cuenta, y no por eso faltan datos."""
        d = builds.summary([{'kind': 'accessory', 'size': '', 'qty': 3}])
        assert d['unknown'] == 0 and d['memory_gb'] == 0

    def test_una_magnitud_se_lee_o_no_se_lee(self):
        assert builds.magnitude('1.92 TB') == (1.92, 'TB')
        assert builds.magnitude('750W') == (750.0, 'W')
        assert builds.magnitude('1,5 GB') == (1.5, 'GB')
        assert builds.magnitude('media altura') == (0.0, '')
        assert builds.magnitude('') == (0.0, '')


# ══ El almacén ══════════════════════════════════════════════════════════════════════════

class TestLasPlantillas:

    def test_sin_nombre_no_hay_plantilla(self, store):
        """El nombre es lo único con lo que se elige una: sin él, en el desplegable hay un
        hueco."""
        assert store.create({'name': '   '}) == ''

    def test_dos_con_el_mismo_nombre_serian_dos_estandares_indistinguibles(self, store):
        assert store.create({'name': 'CPD estándar'})
        assert store.create({'name': 'CPD estándar'}) == ''

    def test_ni_renombrando_una_encima_de_otra(self, store):
        a = store.create({'name': 'A'})
        store.create({'name': 'B'})
        assert store.update(a, {'name': 'B'}) is False
        assert store.get(a)['name'] == 'A'

    def test_una_clase_de_equipo_que_no_existe_no_se_guarda(self, store):
        uid = store.create({'name': 'X', 'role': 'nave-espacial'})
        assert store.get(uid)['role'] == ''
        assert store.create({'name': 'Y', 'role': 'server'})

    def test_y_una_clase_de_pieza_que_no_existe_es_other(self, store):
        uid = store.create({'name': 'X'})
        p = store.part_add(uid, {'kind': 'antimateria', 'model': 'X'})
        assert store.parts_of(uid)[0]['kind'] == 'other'
        assert p

    def test_la_altura_en_cero_significa_la_del_modelo(self, store):
        """Un R740 mide lo que mide se le ponga lo que se le ponga: la plantilla no tiene por
        qué repetirlo, y un 1 por defecto sería una mentira sobre el noventa por ciento."""
        uid = store.create({'name': 'X'})
        assert store.get(uid)['u_tenths'] == 0

    def test_la_altura_va_en_decimas_como_en_el_catalogo(self, store):
        """Hay chasis de 0,5 U. En unidades enteras no se pueden escribir, y una plantilla que
        no puede decir lo que mide su chasis no es una plantilla de ese chasis."""
        uid = store.create({'name': 'Panel', 'u_tenths': 5})
        assert store.get(uid)['u_tenths'] == 5

    def test_y_dice_como_comparte_el_u(self, store):
        """Dos por U para un patch panel de medio U, ocho para una bandeja de Raspberry. Es del
        estándar; *cuál* de las partes toma cada caja se dice al colocarla."""
        uid = store.create({'name': 'Panel', 'u_tenths': 5, 'u_slots': 2,
                            'u_split': 'height'})
        fila = store.get(uid)
        assert fila['u_slots'] == 2 and fila['u_slot_span'] == 1
        assert fila['u_split'] == 'height'

    def test_clonar_se_lleva_las_piezas(self, store):
        a = store.create({'name': 'CPD 2024', 'role': 'server'})
        store.part_add(a, {'kind': 'memory', 'model': 'KSM32', 'qty': 12})
        store.part_add(a, {'kind': 'disk', 'model': 'PM9A3', 'qty': 8})
        b = store.clone(a, 'CPD 2025')
        assert b and b != a
        assert len(store.parts_of(b)) == 2
        assert store.get(b)['role'] == 'server'

    def test_clonar_sin_nombre_se_inventa_uno_libre(self, store):
        """Un nombre que generó el panel no es un nombre que alguien tecleó: rechazar el segundo
        clon por repetido sería rechazar algo que nadie eligió."""
        a = store.create({'name': 'CPD'})
        uno, dos = store.clone(a, ''), store.clone(a, '')
        assert uno and dos and uno != dos
        assert store.get(uno)['name'] != store.get(dos)['name']

    def test_las_piezas_del_clon_son_suyas(self, store):
        """Si se compartieran, cambiar los discos de la copia cambiaría los del original — que
        es exactamente lo que se clona para no hacer."""
        a = store.create({'name': 'A'})
        store.part_add(a, {'kind': 'disk', 'model': 'X', 'qty': 4})
        b = store.clone(a, 'B')
        store.part_delete(store.parts_of(b)[0]['uid'])
        assert len(store.parts_of(a)) == 1 and store.parts_of(b) == []

    def test_borrarla_se_lleva_sus_piezas_y_nada_mas(self, store):
        uid = store.create({'name': 'A'})
        store.part_add(uid, {'kind': 'disk', 'model': 'X'})
        assert store.delete(uid) is True
        assert store.parts_of(uid) == [] and store.get(uid) is None

    def test_una_pieza_de_una_plantilla_que_no_existe_no_se_guarda(self, store):
        assert store.part_add('no-existe', {'kind': 'disk'}) == ''

    def test_las_cuentas_salen_de_una_sola_lectura(self, store):
        a, b = store.create({'name': 'A'}), store.create({'name': 'B'})
        store.part_add(a, {'kind': 'disk'})
        store.part_add(a, {'kind': 'memory'})
        store.part_add(b, {'kind': 'cpu'})
        assert store.counts() == {a: 2, b: 1}

    def test_por_nombre_y_sin_distinguir_mayusculas(self, store):
        for n in ('zeta', 'Alfa', 'beta'):
            store.create({'name': n})
        assert [b['name'] for b in store.list()] == ['Alfa', 'beta', 'zeta']

    def test_una_peticion_no_escribe_columnas_que_no_son_suyas(self, store):
        """Campo a campo y no en bloque: la lista de lo aceptado es la única defensa que no se
        olvida de un campo nuevo el día que la tabla crezca."""
        campos = builds.BuildStore._fields({'uid': 'robado', 'created_at': 'ayer',   # noqa: SLF001
                                            'name': 'X'})
        assert 'uid' not in campos and 'created_at' not in campos

    def test_la_cantidad_nunca_baja_de_uno(self, store):
        uid = store.create({'name': 'X'})
        store.part_add(uid, {'kind': 'disk', 'qty': 0})
        assert store.parts_of(uid)[0]['qty'] == 1

    def test_el_rol_de_una_plantilla_es_uno_de_los_del_inventario(self):
        """Se copia al equipo tal cual: si fuesen dos vocabularios, la mitad de los equipos
        creados desde una plantilla saldrían con un rol que ninguna pantalla sabe pintar."""
        assert set(ITEM_ROLES) >= {'server', 'switch', 'blank'}
        for rol in ITEM_ROLES:
            assert builds.BuildStore._fields({'role': rol})['role'] == rol   # noqa: SLF001


class TestLasViejasTambienCopian:
    """Rellenar en las plantillas anteriores lo que su modelo del catálogo dice.

    Las columnas son nuevas y ``ADD COLUMN`` no puede inventarse el valor, así que las
    plantillas escritas antes las traían vacías: la ficha dejó de enseñar las fotos, las medidas
    y los puertos el día que dejó de leerlas en vivo del catálogo. Un fallo que no da ningún
    error — solo huecos donde había datos.
    """

    @pytest.fixture()
    def cat(self):
        db = get_connector({'type': 'sqlite', 'path': ':memory:'})
        yield catalog.CatalogStore(db)
        try:
            db.close()
        except Exception:                       # pylint: disable=broad-except
            pass

    def test_rellena_los_huecos_de_su_modelo(self, store, cat):
        modelo = cat.create({'tree': 'device-types', 'manufacturer': 'HP', 'model': 'Mini',
                             'kind': 'server', 'u_tenths': 10, 'full_depth': 0,
                             'airflow': 'passive', 'power_type': 'external',
                             'ports': {'interfaces': {'1000base-t': 1}}})
        uid = store.create({'name': 'Vieja', 'type_uid': modelo})
        assert store.get(uid)['manufacturer'] == ''      # así estaba antes del copiado
        assert store.stamp_missing(cat) == 1
        fila = store.get(uid)
        assert fila['manufacturer'] == 'HP' and fila['model'] == 'Mini'
        assert fila['u_tenths'] == 10 and fila['power_type'] == 'external'
        assert fila['ports'] == {'interfaces': {'1000base-t': 1}}
        # El fondo solo se puede deducir cuando la fila entera estaba sin estampar: su columna
        # vale 1 por defecto y 1 es también un fondo completo de verdad.
        assert fila['full_depth'] == 0

    def test_no_pisa_lo_que_ya_estaba_escrito(self, store, cat):
        """Lo que tiene valor es de la plantilla y puede haberse corregido a mano. Pisarlo sería
        deshacer esa corrección sin decirlo — y un arreglo que borra datos es peor que el fallo.
        """
        modelo = cat.create({'tree': 'device-types', 'manufacturer': 'HP', 'model': 'Mini',
                             'kind': 'server', 'u_tenths': 10})
        uid = store.create({'name': 'Corregida', 'type_uid': modelo,
                            'manufacturer': 'HPE', 'u_tenths': 5})
        store.stamp_missing(cat)
        fila = store.get(uid)
        assert fila['manufacturer'] == 'HPE' and fila['u_tenths'] == 5
        assert fila['model'] == 'Mini'          # el hueco sí se rellena

    def test_un_modelo_retirado_no_borra_nada(self, store, cat):
        """De uno que ya no está no hay nada que copiar, y la plantilla se queda como está — que
        es justo lo que se buscaba al copiar en vez de enlazar."""
        uid = store.create({'name': 'Huérfana', 'type_uid': 'ya-no-existe',
                            'manufacturer': 'HP'})
        assert store.stamp_missing(cat) == 0
        assert store.get(uid)['manufacturer'] == 'HP'

    def test_sin_modelo_base_no_se_toca(self, store, cat):
        uid = store.create({'name': 'A mano', 'u_tenths': 20})
        assert store.stamp_missing(cat) == 0
        assert store.get(uid)['u_tenths'] == 20

    def test_una_vez(self, store, cat):
        """En cuanto no queda ninguna con huecos, no hay nada que recorrer: la segunda pasada
        contesta cero sin escribir."""
        modelo = cat.create({'tree': 'device-types', 'manufacturer': 'HP', 'model': 'Mini',
                             'kind': 'server', 'u_tenths': 10, 'airflow': 'passive',
                             'power_type': 'external', 'ports': {'interfaces': {'': 1}},
                             'extra': {'launched': '2019-08-29'}})
        store.create({'name': 'Vieja', 'type_uid': modelo})
        assert store.stamp_missing(cat) == 1
        assert store.stamp_missing(cat) == 0

    def test_sin_catalogo_no_falla(self, store):
        """Un panel sin catálogo montado no puede copiar, y eso no es un error: es que no hay
        de dónde."""
        store.create({'name': 'X', 'type_uid': 't1'})
        assert store.stamp_missing(None) == 0


class TestQueDeciaAntes:
    """El historial de una plantilla, en la misma tabla que el del catálogo.

    Una plantilla es un dato **compartido**: de ella salieron veinte máquinas y es el estándar
    con el que se compra, así que corregirla no es editar una fila. Y la corrección que rompe
    algo no se descubre el día que se hace — se descubre cuando alguien dice «esto antes llevaba
    ocho discos» y no hay forma de saber si tiene razón.
    """

    def test_crear_y_corregir_dejan_version(self, store):
        uid = store.create({'name': 'CPD 2024'}, actor='ana')
        store.update(uid, {'notes': 'porque el otro no cabía'}, actor='luis')
        hist = store.revs.history(uid, scope=store.SCOPE)
        assert [h['action'] for h in hist] == ['edit', 'create']
        assert hist[0]['by'] == 'luis' and hist[1]['by'] == 'ana'
        assert hist[0]['changes']['notes'][1] == 'porque el otro no cabía'

    def test_poner_un_componente_es_un_cambio_de_la_plantilla(self, store):
        """«¿Desde cuándo lleva ocho discos?» es la pregunta que se le hace a esto, y sin
        apuntarlo no hay dónde contestarla."""
        uid = store.create({'name': 'CPD 2024'})
        store.part_add(uid, {'kind': 'disk', 'model': 'PM9A3', 'qty': 8}, actor='ana')
        hist = store.revs.history(uid, scope=store.SCOPE)
        assert hist[0]['action'] == 'part_add' and hist[0]['by'] == 'ana'

    def test_la_version_guarda_de_que_constaba(self, store):
        """Media plantilla es media respuesta: lo que se pregunta de un historial de estos es
        casi siempre de qué constaba."""
        uid = store.create({'name': 'CPD 2024'})
        store.part_add(uid, {'kind': 'disk', 'model': 'PM9A3', 'qty': 8})
        piezas = store.revs.history(uid, scope=store.SCOPE)[0]['data']['parts']
        assert [p['model'] for p in piezas] == ['PM9A3']

    def test_la_lista_de_piezas_no_sale_como_un_campo_que_cambio(self, store):
        """Compararla como texto pondría dos volcados de doce componentes uno al lado del otro
        para decir que se añadió un disco. Lo que hizo ese cambio lo dice la acción."""
        uid = store.create({'name': 'CPD 2024'})
        store.part_add(uid, {'kind': 'disk', 'model': 'PM9A3'})
        store.part_add(uid, {'kind': 'memory', 'model': 'KSM32'})
        assert 'parts' not in store.revs.history(uid, scope=store.SCOPE)[0]['changes']

    def test_quitar_una_pieza_tambien_queda(self, store):
        uid = store.create({'name': 'CPD 2024'})
        pieza = store.part_add(uid, {'kind': 'disk'})
        store.part_delete(pieza, actor='ana')
        assert store.revs.history(uid, scope=store.SCOPE)[0]['action'] == 'part_drop'

    def test_retirarla_se_lleva_su_historial(self, store):
        """Las versiones de algo que ya no existe no contestan a nada y se quedarían para
        siempre."""
        uid = store.create({'name': 'CPD 2024'})
        store.update(uid, {'notes': 'x'})
        store.delete(uid)
        assert store.revs.history(uid, scope=store.SCOPE) == []

    def test_el_historial_del_catalogo_y_el_de_una_plantilla_no_se_mezclan(self, store):
        """Misma tabla y `scope` distinto: sin eso, un `uid` que coincidiera enseñaría las
        versiones de otra cosa."""
        uid = store.create({'name': 'CPD 2024'})
        assert store.revs.history(uid) == []            # el scope por omisión es el catálogo
        assert store.revs.history(uid, scope=store.SCOPE)


class TestDentroDeLaCajaOColgandoDeElla:
    """Un DIMM va en una ranura de la placa; el adaptador USB-C a red va enchufado a un puerto.

    Contarlos juntos deja «cinco componentes» sin decir cuántos hay que desmontar para llevarse
    la caja, y esa es la pregunta del día de la mudanza.
    """

    def test_por_omision_va_dentro(self, store):
        """Una columna nueva no puede inventarse el valor, y lo que había escrito hasta hoy son
        piezas de dentro."""
        uid = store.create({'name': 'X'})
        pieza = store.part_add(uid, {'kind': 'memory'})
        assert store.parts.get(pieza)['mount'] == ''

    def test_se_puede_decir_que_cuelga(self, store):
        uid = store.create({'name': 'X'})
        pieza = store.part_add(uid, {'kind': 'nic', 'mount': 'external'})
        assert store.parts.get(pieza)['mount'] == 'external'

    def test_una_palabra_inventada_no_entra(self, store):
        """`Rows` escribe cualquier columna de la tabla: sin acotarlo, una petición dejaría ahí
        algo que ninguna pestaña sabe leer — y la pieza desaparecería de las dos."""
        uid = store.create({'name': 'X'})
        pieza = store.part_add(uid, {'kind': 'nic', 'mount': 'en-la-mesa'})
        assert store.parts.get(pieza)['mount'] == ''

    def test_viaja_al_equipo_con_lo_demas(self, store):
        """El adaptador que el estándar dice que lleva sigue siendo externo en la máquina que
        sale de él: el día de la mudanza eso es lo que hay que acordarse de meter en la caja."""
        uid = store.create({'name': 'X'})
        store.part_add(uid, {'kind': 'nic', 'mount': 'external', 'slot': 'USB-1'})
        copia = store.stamp(uid)[0]
        assert copia['mount'] == 'external' and copia['slot'] == 'USB-1'


class TestLaListaConNombreSeLimpiaEnLaPuerta:
    """Entraba tal y como la mandaba el navegador: un JSON que se serializa y se guarda.

    Con dos campos era feo; con la generación y las señales dentro es una columna donde cabe
    cualquier cosa que alguien mande, y lo que se guarda sin mirar es lo que después se lee sin
    poder creerlo.
    """

    def test_se_queda_lo_que_esta_pantalla_sabe_leer(self):
        limpio = clean_port_list({'rear-ports': [
            {'name': ' USB 1 ', 'type': 'usb-c', 'gen': 'usb3.2g2',
             'signals': ['data', 'dp', 'data', ''], 'inventado': 'x'}]})
        assert limpio == {'rear-ports': [
            {'name': 'USB 1', 'type': 'usb-c', 'gen': 'usb3.2g2', 'signals': ['data', 'dp']}]}

    def test_una_familia_que_ninguna_pantalla_dibuja_no_entra(self):
        assert clean_port_list({'inventada': [{'name': 'x'}]}) == {}

    def test_sin_nombre_no_hay_entrada(self):
        """El nombre es lo que cruza con el componente que va en ese hueco."""
        assert clean_port_list({'rear-ports': [{'name': '  ', 'type': 'usb-c'}]}) == {}

    def test_los_campos_vacios_no_se_escriben(self):
        """Un `gen: ''` es una generación que alguien tendría que interpretar."""
        uno = clean_port_list({'rear-ports': [{'name': 'a', 'gen': '', 'signals': []}]})
        assert uno['rear-ports'][0] == {'name': 'a', 'type': ''}

    def test_hay_tope_de_bocas_y_de_senales(self):
        muchas = [{'name': f'p{i}'} for i in range(PORT_LIST_MAX + 30)]
        assert len(clean_port_list({'interfaces': muchas})['interfaces']) == PORT_LIST_MAX
        sen = clean_port_list({'rear-ports': [
            {'name': 'a', 'signals': [f's{i}' for i in range(PORT_SIGNALS_MAX + 5)]}]})
        assert len(sen['rear-ports'][0]['signals']) == PORT_SIGNALS_MAX

    def test_el_voltaje_es_texto_y_los_vatios_un_numero(self):
        """Lo que pone en la etiqueta de una fuente es `100-240 V`, un rango: convertirlo en una
        cifra sería inventarse cuál de las dos. Los vatios sí son uno, y son los que se suman."""
        uno = clean_port_list({'power-ports': [
            {'name': 'IN', 'type': 'iec-60320-c14', 'volts': ' 100-240 ', 'watts': '750'}]})
        assert uno['power-ports'][0]['volts'] == '100-240'
        assert uno['power-ports'][0]['watts'] == 750

    def test_unos_vatios_que_no_son_un_numero_no_entran(self):
        """Un cero, un negativo o «noventa» son tres formas de no decirlo, y las tres se suman
        igual de mal."""
        for malo in ('no', -3, 0, None, 10 ** 9):
            fila = clean_port_list({'power-ports': [{'name': 'IN', 'watts': malo}]})
            assert 'watts' not in fila['power-ports'][0], malo

    def test_lo_que_no_es_un_diccionario_no_tumba_nada(self):
        assert clean_port_list('vaya') == {}
        assert clean_port_list({'rear-ports': ['x', {'name': 'a'}]})['rear-ports'] == [
            {'name': 'a', 'type': ''}]
