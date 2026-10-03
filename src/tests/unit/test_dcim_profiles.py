#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qué se pregunta de un componente de cada clase, y de dónde sale esa lista.

Once clases con cuatro atributos escritas en un `.py` son una lista que hay que publicar una
release para tocar, y quien sabe qué formato tiene la tarjeta nueva casi nunca es quien toca el
código. Así que es un JSON: el que viene con el panel y el que alguien guarde en la base de
datos, mandando **la versión más alta** — que es justo para lo que sirve un número de versión.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim import profiles                                   # noqa: E402
from lib.core.dcim.store import PART_KINDS                           # noqa: E402
from lib.db import get_connector                                     # noqa: E402


@pytest.fixture()
def store():
    db = get_connector({'type': 'sqlite', 'path': ':memory:'})
    yield profiles.ProfileStore(db)
    try:
        db.close()
    except Exception:                           # pylint: disable=broad-except
        pass


# ══ El que viene dentro ═════════════════════════════════════════════════════════════════

class TestElDocumentoQueVieneConElPanel:

    def test_es_un_fichero_y_no_una_tabla_de_python(self):
        """El punto entero: añadir el formato de una tarjeta nueva no tiene por qué ser una
        release, y quien lo sabe casi nunca es quien toca el código."""
        assert os.path.isfile(profiles.FILE)
        with open(profiles.FILE, encoding='utf-8') as fh:
            crudo = json.load(fh)
        assert int(crudo.get('version') or 0) >= 1

    def test_cada_clase_pide_lo_suyo(self):
        """«Samsung PM9A3 · 1.92 TB» alcanza para reconocerlo y no para comprarlo: si es M.2 o
        de 2,5", y si va por NVMe o por SATA."""
        ssd = [f['name'] for f in profiles.fields('ssd')]
        cpu = [f['name'] for f in profiles.fields('cpu')]
        assert 'interface' in ssd and 'cores' not in ssd
        assert 'cores' in cpu and 'rpm' not in cpu

    def test_lo_que_dice_cualquiera_va_al_final(self):
        """Lo primero que alguien quiere teclear de un disco es si es M.2 o de 2,5", no cuánto
        pesa ni cuándo se dejó de vender. Los comunes cierran la lista, y dentro de ellos las
        fechas van las últimas: son las que se rellenan en otro momento, si es que se rellenan."""
        vida = [c['name'] for c in profiles.common() if c.get('group') == 'lifecycle']
        for clase in ('ssd', 'cpu', 'accessory'):
            nombres = [f['name'] for f in profiles.fields(clase)]
            assert nombres[-len(vida):] == vida, 'las fechas cierran la lista'
            assert nombres[-len(vida) - 2:-len(vida)] == ['weight', 'weight_unit']

    def test_la_disipacion_escribe_en_la_columna_que_ya_existe(self):
        """Un componente pasivo y un chasis de flujo frontal-trasero contestan a la misma
        pregunta: guardarla dos veces serían dos respuestas que pueden discrepar."""
        comunes = {c['name']: c for c in profiles.common()}
        assert comunes['airflow']['column'] is True
        assert 'column' not in comunes['weight']

    def test_una_clase_sin_perfil_sigue_teniendo_los_comunes(self):
        assert [f['name'] for f in profiles.fields('accessory')] == [
            'airflow', 'weight', 'weight_unit', 'launched', 'end_of_sale',
            'end_of_maintenance', 'end_of_security', 'last_contract_attach',
            'last_contract_renewal', 'eol']

    def test_las_fechas_de_una_vida_van_en_su_bloque(self):
        """Y no sueltas entre los atributos: seis casillas de fecha seguidas sin decir de qué van
        se leen igual que seis fechas cualesquiera, y lo que hay que ver de un vistazo es cuál ya
        pasó."""
        vida = [c['name'] for c in profiles.common() if c.get('group') == 'lifecycle']
        assert vida == ['launched', 'end_of_sale', 'end_of_maintenance', 'end_of_security',
                        'last_contract_attach', 'last_contract_renewal', 'eol']
        assert 'weight' not in vida

    def test_un_grupo_inventado_no_crea_una_seccion(self):
        """Sería una sección entera que no sale en ninguna pantalla y que nadie echa de menos,
        porque nunca existió."""
        d = profiles.normalise({'version': 1, 'common': [
            {'name': 'x', 'type': 'text', 'group': 'inventado'},
            {'name': 'y', 'type': 'date', 'group': 'lifecycle'}]})
        assert 'group' not in d['common'][0]
        assert d['common'][1]['group'] == 'lifecycle'

    def test_el_tamano_no_es_un_atributo(self):
        """Es la columna `size`: el dato que se lee en cada renglón y el que se copia a la
        pieza. Repetirlo serían dos sitios donde escribir «1.92 TB» y ninguna forma de saber
        cuál manda."""
        for clase in PART_KINDS:
            assert 'size' not in [f['name'] for f in profiles.fields(clase)]

    def test_el_tamano_se_llama_como_toca_en_cada_clase(self):
        """La misma casilla es la capacidad de un disco, los gigas de un DIMM y los vatios de una
        fuente: una palabra que vale para las tres no informa de ninguna."""
        assert profiles.size_of('ssd')['label'] == 'capacity'
        assert profiles.size_of('psu')['label'] == 'power'
        assert profiles.size_of('ssd')['hint'], 'el ejemplo es lo que enseña la unidad'

    def test_y_dice_en_que_unidades_se_escribe(self):
        """Un número y su unidad son UN dato: la pantalla los junta en un control, y de dónde
        salen las opciones es el documento y no el código."""
        assert profiles.size_of('ssd')['units'] == ['MB', 'GB', 'TB', 'PB']
        assert profiles.size_of('psu')['units'] == ['W', 'kW']

    def test_sin_unidades_el_tamano_es_texto_libre(self):
        """Que es lo que hace falta donde el tamaño no es una magnitud: «media altura»."""
        assert profiles.size_of('transceiver')['units'] == []

    def test_la_unidad_del_peso_va_pegada_a_lo_que_mide(self):
        """Sueltas ocupan el doble, se van a la línea de abajo y dejan «Unidad de peso» flotando
        sin nada al lado que diga de qué."""
        comunes = {c['name']: c for c in profiles.common()}
        assert comunes['weight_unit']['unit_of'] == 'weight'
        assert 'unit_of' not in comunes['weight']

    def test_una_clase_donde_no_significa_nada_no_lo_dice(self):
        """De un disco el tamaño es su capacidad y de una fuente sus vatios; de una CPU no es
        nada. «Tamaño» a secas es una casilla que no se sabe rellenar porque no pregunta nada, y
        la pantalla solo la ofrece donde el documento dice QUÉ es."""
        for clase in ('cpu', 'nic', 'hba', 'fan', 'accessory'):
            assert profiles.size_of(clase)['label'] == '', clase
        for clase in ('ssd', 'disk', 'memory', 'psu'):
            assert profiles.size_of(clase)['label'], clase

    def test_una_clase_sin_nada_dicho_usa_la_palabra_generica(self):
        assert profiles.size_of('other') == {'label': '', 'hint': '', 'units': []}

    def test_y_no_se_repite_como_atributo(self):
        """Estaría en dos casillas y ninguna mandaría."""
        for clase in ('battery', 'gpu'):
            nombres = [f['name'] for f in profiles.fields(clase)]
            assert 'capacity_ah' not in nombres and 'memory_gb' not in nombres

    def test_lo_que_es_una_lista_cerrada_se_elige(self):
        """Un zócalo o un cifrado escritos a mano son cuatro formas del mismo dato y ninguna
        forma de preguntar «qué CPU me sirve para esta placa», que es lo único que se le pregunta
        a ese campo."""
        for clase, campo in (('cpu', 'socket'), ('ssd', 'encryption'), ('disk', 'encryption')):
            c = [f for f in profiles.fields(clase) if f['name'] == campo][0]
            assert c['type'] == 'enum' and len(c['enum']) > 5, (clase, campo)

    def test_los_zocalos_llegan_hasta_los_de_ahora(self, ):
        """Desde Socket A: si la lista se queda corta, el campo obliga a elegir algo que no es."""
        zocalos = [f for f in profiles.fields('cpu') if f['name'] == 'socket'][0]['enum']
        assert any('Socket A' in z for z in zocalos)
        assert any('LGA 1851' in z for z in zocalos) and any('SP5' in z for z in zocalos)
        # Con el fabricante delante: cuarenta y seis sueltos no se recorren.
        assert all(z.startswith('Intel ') or z.startswith('AMD ') for z in zocalos)

    def test_una_cpu_dice_lo_que_hace_falta_para_comprarla(self):
        """`cores` a secas dejó de significar algo el día que una CPU trae ocho núcleos grandes y
        dieciséis pequeños — y lo que se mira antes de decir que no vale es la memoria que admite
        y cuánta, no la frecuencia base."""
        cpu = {f['name'] for f in profiles.fields('cpu')}
        assert {'cores_p', 'cores_e', 'turbo_ghz', 'memory_type', 'memory_max_gb',
                'memory_channels', 'ecc'} <= cpu
        assert {'igpu', 'igpu_model', 'management', 'pcie_gen', 'pcie_lanes'} <= cpu
        assert {'lithography', 'cache_l3_mb', 'tdp_max_w', 'segment', 'sockets_max'} <= cpu

    def test_y_no_pierde_la_lista_de_zocalos(self):
        """Rehacerla al ampliar la ficha sería tenerla dos veces y verlas separarse."""
        z = [f for f in profiles.fields('cpu') if f['name'] == 'socket'][0]
        assert z['type'] == 'enum' and len(z['enum']) > 40

    def test_las_dos_fechas_las_tiene_cualquier_componente(self):
        """«¿Esto todavía se compra?» y «¿esto tiene soporte?» se preguntan de un DIMM igual que
        de una CPU: no distinguen una clase de otra, así que no son atributos de ninguna."""
        comunes = {c['name']: c for c in profiles.common()}
        assert comunes['launched']['type'] == 'date'
        assert comunes['eol']['type'] == 'date'
        for clase in ('ssd', 'cpu', 'accessory'):
            assert {'launched', 'eol'} <= {f['name'] for f in profiles.fields(clase)}

    def test_una_fecha_es_un_control_que_la_pantalla_sabe_dibujar(self):
        assert 'date' in profiles.TYPES
        d = profiles.normalise({'version': 2,
                                'kinds': {'ssd': [{'name': 'x', 'type': 'date'}]}})
        assert d['kinds']['ssd'][0]['type'] == 'date'

    def test_los_campos_que_no_se_explican_solos_llevan_ayuda(self):
        """«Litografía», «TDP en turbo», «Resistencia (TBW)» son palabras de una hoja de
        características, y quien rellena la ficha no siempre es quien la leyó. Un campo cuyo
        nombre hay que buscar fuera se deja en blanco — o peor, se rellena con otra cosa."""
        from lib.i18n.lang import es_ES, en_EN                        # noqa: PLC0415
        for idioma in (es_ES.LANG, en_EN.LANG):
            for nombre in ('lithography', 'tdp_max_w', 'endurance_tbw', 'speed_mts',
                           'memory_channels', 'pcie_lanes', 'management', 'ecc', 'eol'):
                assert idioma.get('dcim_attr_%s_tt' % nombre), nombre

    def test_y_la_ayuda_existe_en_los_dos_idiomas_o_en_ninguno(self):
        """Media traducción es una pantalla que cambia de idioma a mitad."""
        from lib.i18n.lang import es_ES, en_EN                        # noqa: PLC0415
        una = {k for k in es_ES.LANG if k.startswith('dcim_attr_')}
        otra = {k for k in en_EN.LANG if k.startswith('dcim_attr_')}
        assert una == otra

    def test_un_modulo_de_memoria_dice_si_sirve_en_esa_placa(self):
        """El formato y el tipo de módulo son dos ejes: `DIMM` dice el tamaño de la pastilla y
        `RDIMM` cómo habla con el controlador. Una placa de servidor exige lo segundo y una de
        sobremesa lo rechaza, así que en la misma casilla hay que elegir qué pregunta se
        contesta."""
        ram = {f['name']: f for f in profiles.fields('memory')}
        assert {'module_type', 'ranks', 'cl', 'timings', 'height'} <= set(ram)
        assert 'RDIMM' in ram['module_type']['enum']
        assert 'RDIMM' not in ram['form_factor']['enum'], 'son dos ejes, no uno'
        # La altura: un módulo normal no entra en un 1U, y eso no se ve en ninguna otra casilla.
        assert any('VLP' in v for v in ram['height']['enum'])

    def test_las_denominaciones_pc_son_las_impresas_y_no_las_calculadas(self):
        """`PC4-21300` parecen los 2666 MT/s por ocho, y calcularlas así produce cuatro que **no
        existen**: la etiqueta dice `PC2-4200` y la multiplicación da 4264.

        Los MT/s ya vienen redondeados —533⅓, 1333⅓, 2133⅓— y el nombre comercial se redondeó por
        su cuenta, unas veces hacia arriba y otras hacia abajo. No hay fórmula que reproduzca el
        conjunto publicado: la fuente de verdad es lo que pone en el módulo.
        """
        opciones = [f for f in profiles.fields('memory')
                    if f['name'] == 'pc_rating'][0]['enum']
        for pc, ddr in (('PC2-4200', 'DDR2-533'), ('PC3-10600', 'DDR3-1333'),
                        ('PC3-17000', 'DDR3-2133'), ('PC4-17000', 'DDR4-2133'),
                        ('PC4-23400', 'DDR4-2933'), ('PC4-21300', 'DDR4-2666'),
                        ('PC5-38400', 'DDR5-4800')):
            assert '%s · %s' % (pc, ddr) in opciones, pc
        # Y ninguna de las que salían de multiplicar y no existen.
        for inventada in ('PC2-4300', 'PC3-10700', 'PC3-17100', 'PC4-17100', 'PC4-23500'):
            assert not any(inventada in o for o in opciones), inventada

    def test_y_cada_una_lleva_las_dos_notaciones(self):
        """Se elige leyendo la etiqueta, diga la que diga — y así las dos casillas no pueden
        acabar diciendo cosas distintas del mismo hecho."""
        opciones = [f for f in profiles.fields('memory')
                    if f['name'] == 'pc_rating'][0]['enum']
        assert len(opciones) == 30
        assert all(o.startswith('PC') and ' · DDR' in o for o in opciones)

    def test_la_velocidad_de_un_enlace_no_se_mide_en_gigabits(self):
        """Un número en gigabits obliga a escribir `0,1` para un puerto de 100 Mbps y `0,01` para
        uno de 10 — que nadie escribe. Y esos puertos existen: un teléfono IP va a 100, y en
        cualquier sala hay algo de hace quince años que va a 10."""
        red = [f for f in profiles.fields('nic') if f['name'] == 'link_speed'][0]
        assert red['type'] == 'enum'
        assert '10 Mbps' in red['enum'] and '100 Mbps' in red['enum']
        assert '1 Gbps' in red['enum'] and '100 Gbps' in red['enum']

    def test_y_no_es_la_misma_lista_para_todo(self):
        """Una tarjeta de red habla Ethernet y una controladora habla SAS o Fibre Channel:
        ofrecer «100 Gbps» para un HBA es ofrecer algo que no existe."""
        red = {v for f in profiles.fields('nic')
               if f['name'] == 'link_speed' for v in f['enum']}
        almacen = {v for f in profiles.fields('hba')
                   if f['name'] == 'link_speed' for v in f['enum']}
        assert red & almacen == set()
        assert any(v.startswith('SAS') for v in almacen)
        assert any(v.startswith('FC') for v in almacen)

    def test_y_el_nombre_viejo_no_se_queda_por_ahi(self):
        """Un campo que ya no usa nadie es uno que alguien mantendrá sin saber por qué."""
        for clase in profiles.packaged()['kinds']:
            assert 'speed_gbps' not in [f['name'] for f in profiles.fields(clase)], clase

    def test_una_tarjeta_de_red_no_siempre_va_dentro(self):
        """Un adaptador USB de red existe y está enchufado ahora mismo en el portátil de alguien:
        es exactamente lo que nadie apunta y luego nadie encuentra."""
        red = [f for f in profiles.fields('nic') if f['name'] == 'interface'][0]['enum']
        assert {'USB-A', 'USB-C', 'Thunderbolt', 'M.2'} <= set(red)
        assert 'PCIe x8' in red, 'y las de dentro siguen estando'

    def test_todas_sus_clases_son_clases_de_pieza(self):
        """Un perfil de una clase que no existe es un formulario que no sale nunca."""
        assert set(profiles.packaged()['kinds']) <= set(PART_KINDS)


# ══ Lo que se acepta ════════════════════════════════════════════════════════════════════

class TestUnDocumentoSeLimpiaAlLeerlo:

    def test_una_clase_que_no_existe_no_entra(self):
        d = profiles.normalise({'version': 2, 'kinds': {'nave': [{'name': 'x', 'type': 'text'}]}})
        assert d['kinds'] == {}

    def test_un_control_que_la_pantalla_no_sabe_dibujar_tampoco(self):
        """Saldría como una caja de texto sin decir que no se entendió, y quien lo escribió
        creería que funcionó."""
        d = profiles.normalise({'version': 2, 'kinds': {'ssd': [{'name': 'x', 'type': 'raro'},
                                                                {'name': 'y', 'type': 'text'}]}})
        assert [f['name'] for f in d['kinds']['ssd']] == ['y']

    def test_un_desplegable_sin_opciones_no_es_un_campo(self):
        d = profiles.normalise({'version': 2,
                                'kinds': {'ssd': [{'name': 'x', 'type': 'enum', 'enum': []}]}})
        assert d['kinds'] == {}

    def test_lo_que_se_tira_se_dice(self):
        """Un JSON con una clase mal escrita se guardaría igual y dejaría media pantalla sin
        atributos, y quien lo subió no se enteraría hasta que alguien fuera a rellenar una
        ficha."""
        malos = profiles.problems({'version': 2, 'kinds': {
            'nave': [{'name': 'x', 'type': 'text'}],
            'ssd': [{'name': 'y', 'type': 'raro'}, {'name': 'z', 'type': 'text'}]}})
        assert sorted(malos) == ['kind:nave', 'ssd.y']

    def test_uno_bueno_no_tiene_nada_que_decir(self):
        assert profiles.problems(profiles.packaged()) == []

    def test_un_documento_que_no_es_un_documento_no_revienta_nada(self):
        assert profiles.normalise(None) == {'version': 0, 'common': [], 'kinds': {},
                                            'size': {}}
        assert profiles.normalise('hola')['kinds'] == {}


# ══ Qué cambió entre dos versiones ══════════════════════════════════════════════════════

class TestElComparador:

    def test_dice_lo_que_se_anadio_y_lo_que_se_fue(self):
        """La pregunta que se hace mirando dos versiones es «¿qué se le añadió a los discos?», y
        a dos volcados de JSON uno al lado del otro no se les puede preguntar eso."""
        a = {'version': 1, 'kinds': {'ssd': [{'name': 'x', 'type': 'text'}]}}
        b = {'version': 2, 'kinds': {'ssd': [{'name': 'y', 'type': 'text'}]}}
        d = profiles.compare(a, b)
        assert {(f['where'], f['name']) for f in d} == {('ssd', 'x'), ('ssd', 'y')}
        assert [f for f in d if f['name'] == 'x'][0]['after'] is None

    def test_y_lo_que_cambio_de_forma(self):
        a = {'version': 1, 'kinds': {'ssd': [{'name': 'x', 'type': 'text'}]}}
        b = {'version': 2, 'kinds': {'ssd': [{'name': 'x', 'type': 'number'}]}}
        d = profiles.compare(a, b)
        assert len(d) == 1 and d[0]['after']['type'] == 'number'

    def test_dos_versiones_iguales_no_tienen_nada_que_decir(self):
        assert profiles.compare(profiles.packaged(), profiles.packaged()) == []

    def test_tambien_compara_el_tamano(self):
        a = {'version': 1, 'size': {'ssd': {'label': 'capacity', 'hint': '1 TB'}}}
        b = {'version': 2, 'size': {'ssd': {'label': 'capacity', 'hint': '2 TB'}}}
        d = profiles.compare(a, b)
        assert len(d) == 1 and d[0]['where'] == 'size' and d[0]['name'] == 'ssd'


class TestGuardarloDejaVersion:

    def test_cada_guardado_deja_constancia(self, store):
        """De este documento sale el formulario de todos los componentes: cambiarlo cambia lo
        que todo el mundo puede teclear, y «¿esto quién lo cambió?» es la pregunta del mes
        siguiente."""
        store.save({'version': 90, 'kinds': {}}, actor='ana')
        store.save({'version': 91, 'kinds': {}}, actor='luis')
        h = store.revs.history(profiles.NAME, scope=profiles.SCOPE)
        assert [f['by'] for f in h] == ['luis', 'ana']
        assert h[0]['data']['version'] == 91

    def test_y_vive_aparte_de_las_fichas_del_catalogo(self, store):
        """Un modelo y la lista de qué preguntar de los modelos son dos cosas."""
        store.save({'version': 90, 'kinds': {}})
        assert store.revs.history(profiles.NAME, scope='type') == []


# ══ Cuál manda ══════════════════════════════════════════════════════════════════════════

class TestMandaLaVersionMasAlta:

    def test_sin_nada_guardado_manda_el_del_panel(self, store):
        assert profiles.effective(store) == profiles.packaged()

    def test_uno_mas_nuevo_gana(self, store):
        base = int(profiles.packaged()['version'])
        assert store.save({'version': base + 1,
                           'kinds': {'ssd': [{'name': 'nuevo', 'type': 'text'}]}}) == base + 1
        # Los atributos de la clase son los suyos y solo los suyos: quitar uno de ahí es una
        # decisión. Los comunes se suman aparte, que es la otra mitad de la regla.
        d = profiles.effective(store)
        assert [f['name'] for f in (d.get('kinds') or {}).get('ssd', [])] == ['nuevo']

    def test_pero_no_se_lleva_por_delante_lo_que_el_panel_anada_despues(self, store):
        """`common` es donde el panel añade lo que pregunta de cualquier cosa —las seis fechas
        del ciclo de vida entraron por ahí—, y quien hubiera guardado un documento con un número
        más alto antes de que existieran se quedaría sin ellas: sin error, sin aviso, y sin nada
        que relacione el hueco con aquella edición."""
        base = int(profiles.packaged()['version'])
        store.save({'version': base + 1, 'common': [{'name': 'mio', 'type': 'text'}],
                    'kinds': {'ssd': [{'name': 'nuevo', 'type': 'text'}]}})
        nombres = [c['name'] for c in (profiles.effective(store).get('common') or ())]
        assert 'eol' in nombres and 'airflow' in nombres, 'el panel perdió los suyos'
        assert 'mio' in nombres, 'y el guardado perdió el suyo'

    def test_y_el_guardado_sigue_mandando_campo_a_campo(self, store):
        """Quien haya redefinido el peso se queda con el suyo. Sumar no es ignorar."""
        base = int(profiles.packaged()['version'])
        store.save({'version': base + 1,
                    'common': [{'name': 'weight', 'type': 'text'}]})
        peso = [c for c in profiles.effective(store)['common'] if c['name'] == 'weight'][0]
        assert peso['type'] == 'text', 'el del panel pisó al guardado'

    def test_uno_mas_viejo_no(self, store):
        """Una actualización del panel supera a un parche local: si no, una mejora publicada no
        llegaría nunca a quien tocó algo una vez."""
        store.save({'version': 1, 'kinds': {'ssd': [{'name': 'viejo', 'type': 'text'}]}})
        # A igualdad manda también el que viene dentro: para desbancarlo hay que ser MAS nuevo.
        assert 'viejo' not in [f['name'] for f in profiles.fields('ssd',
                                                                  profiles.effective(store))]

    def test_sin_version_no_se_guarda(self, store):
        """Sería un documento que nunca se usa y que nadie entiende por qué no se usa."""
        assert store.save({'kinds': {'ssd': [{'name': 'x', 'type': 'text'}]}}) == 0
        assert store.get() is None

    def test_guardarlo_dos_veces_lo_reemplaza(self, store):
        base = int(profiles.packaged()['version'])
        store.save({'version': base + 1, 'kinds': {}})
        store.save({'version': base + 2, 'kinds': {}})
        assert store.get()['version'] == base + 2

    def test_quitarlo_vuelve_al_que_viene_dentro(self, store):
        store.save({'version': 99, 'kinds': {'ssd': [{'name': 'x', 'type': 'text'}]}})
        assert store.delete() is True
        assert profiles.effective(store) == profiles.packaged()
        assert store.delete() is False

    def test_lo_guardado_se_limpia_igual_que_lo_que_viene(self, store):
        """Una comprobación que solo corre en la puerta de entrada no protege del fichero que
        llega por la otra."""
        store.save({'version': 99, 'kinds': {'nave': [{'name': 'x', 'type': 'text'}],
                                             'ssd': [{'name': 'y', 'type': 'text'}]}})
        assert set(store.get()['body']['kinds']) == {'ssd'}


class TestLaFuenteQueVaFuera:
    """ATX, SFX, CRPS y Flex ATX son las formas de una fuente que se atornilla DENTRO.

    El alimentador de un mini-PC no es ninguna de las cuatro —es un ladrillo con dos cables— así
    que el campo se quedaba en «Sin decir», que es lo mismo que no haber preguntado.
    """

    def _campo(self, nombre):
        for c in profiles.packaged()['kinds']['psu']:
            if c['name'] == nombre:
                return c
        raise AssertionError(f'la fuente no declara {nombre}')

    def test_hay_formato_para_lo_que_va_fuera(self):
        formas = self._campo('form_factor')['enum']
        assert 'external-desktop' in formas
        assert 'external-wall' in formas

    def test_los_de_dentro_siguen_estando(self):
        """Añadir los de fuera no puede llevarse los que ya usaba alguien: un `ATX` guardado
        dejaría de salir en su desplegable y parecería que se borró."""
        formas = self._campo('form_factor')['enum']
        for viejo in ('ATX', 'SFX', 'CRPS', 'Flex ATX'):
            assert viejo in formas, viejo

    def test_la_eficiencia_admite_la_norma_de_los_externos(self):
        """80 PLUS es de las fuentes de ordenador; un adaptador externo lleva impreso DoE o CoC,
        y preguntar por una etiqueta que no puede tener es preguntar para que se quede vacío."""
        assert 'DoE VI' in self._campo('efficiency')['enum']

    def test_los_identificadores_nuevos_se_traducen(self):
        """Se guarda `external-desktop` y no «Adaptador externo»: el documento es uno y la
        pantalla habla dos idiomas."""
        from lib.i18n.lang import en_EN, es_ES              # noqa: PLC0415
        for ident in ('external_desktop', 'external_wall', 'din_rail', 'open_frame',
                      'poe_injector'):
            assert es_ES.LANG.get('dcim_val_' + ident), ident
            assert en_EN.LANG.get('dcim_val_' + ident), ident
