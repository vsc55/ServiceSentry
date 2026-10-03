#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — un valor, repartido en columnas, tiene que volver siendo el mismo.
#
"""Lo que un JSON lleva escrito dentro y una columna no.

`true` no es `1`, `10` no es `10.0`, `[]` no es `"[]"` y un campo presente y vacío no es un campo
ausente. Cuando la medida deja de ser un documento y pasa a ser una fila, todo eso hay que
decirlo aparte — y si se dice mal no falla nada: el panel enseña algo parecido a lo que se midió.

Las proporciones que aparecen aquí están medidas sobre una instalación real (21.092 valores):
15.102 enteros, 4.668 decimales, 811 textos, 285 booleanos, 203 nulos y 23 anidados. Los 21.092
se pasaron uno a uno por `encode`/`decode` y **volvieron idénticos, con su tipo**. Esto sujeta
esa propiedad sin necesitar la base.

Sin Flask ni base de datos: son funciones puras sobre valores.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.history import values as V                  # noqa: E402


def _ida_y_vuelta(v):
    kind, num, txt = V.encode(v)
    assert kind in V.KINDS, f'marca desconocida: {kind!r}'
    return V.decode(kind, num, txt)


class TestUnValorVuelveSiendoElMismo:

    def test_los_tipos_que_manda_un_modulo_de_verdad(self):
        """Uno de cada clase que aparece en la instalación real, con su tipo."""
        for v in (0, 1, -7, 42, 3.5, -0.25, 0.0, '', 'ok', 'host.lan',
                  True, False, None, [], {}, [1, 2], {'a': 1}):
            vuelta = _ida_y_vuelta(v)
            assert vuelta == v, f'{v!r} volvió {vuelta!r}'
            assert type(vuelta) is type(v), (
                f'{v!r} ({type(v).__name__}) volvió como {type(vuelta).__name__}')

    def test_un_booleano_no_vuelve_como_un_uno(self):
        """En Python `True` ES un entero, así que preguntar por `int` antes que por `bool` lo
        convierte en 1 — y `holds_vip` deja de ser sí/no para ser un número."""
        assert _ida_y_vuelta(True) is True
        assert _ida_y_vuelta(False) is False
        assert V.encode(True)[0] == V.BOOL
        assert V.encode(1)[0] == V.INT

    def test_un_entero_no_vuelve_con_coma_ni_al_reves(self):
        """`10` y `10.0` son el mismo número y la misma gráfica, pero no el mismo texto — y la
        ficha de un dispositivo enseña texto."""
        assert _ida_y_vuelta(10) == 10 and isinstance(_ida_y_vuelta(10), int)
        assert isinstance(_ida_y_vuelta(10.0), float)
        assert V.encode(10)[0] == V.INT and V.encode(10.0)[0] == V.FLOAT

    def test_un_campo_vacio_no_es_un_campo_ausente(self):
        """`{'temp': None}` dice «lo medí y no había»; no decir nada dice «no lo medí»."""
        assert V.encode(None)[0] == V.NULL
        assert _ida_y_vuelta(None) is None
        assert V.decode_sample([('temp', *V.encode(None))]) == {'temp': None}

    def test_lo_anidado_sigue_siendo_json(self):
        """23 de 21.092 valores reales son listas o diccionarios — `node_ips` de Proxmox, listas
        de puertos. Esta forma no los sabe partir en columnas, así que no lo intenta."""
        for v in ([], [1, 'a'], {'x': [1, 2]}, [{'p': 1}]):
            assert _ida_y_vuelta(v) == v
            assert V.encode(v)[0] == V.JSON_


class TestLosNumerosQueNoCabenEnUnReal:
    """SNMP manda contadores de 64 bits. Un REAL guarda enteros exactos hasta 2⁵³."""

    def test_por_debajo_del_limite_es_exacto_y_cuenta_en_los_promedios(self):
        v = V.EXACT_INT - 1
        kind, num, txt = V.encode(v)
        assert kind == V.INT and kind in V.NUMERIC_KINDS
        assert num == float(v) and txt is None
        assert V.decode(kind, num, txt) == v

    def test_por_encima_no_pierde_un_digito(self):
        """`float(v)` redondearía y devolvería otro número sin avisar de nada."""
        v = V.EXACT_INT * 4 + 12345          # ni de lejos representable en un REAL
        assert int(float(v)) != v, 'el caso de prueba no prueba nada: este entero sí cabe'
        kind, num, txt = V.encode(v)
        assert kind == V.BIGINT
        assert V.decode(kind, num, txt) == v, 'se perdieron dígitos'

    def test_y_aun_asi_sigue_contando_en_un_promedio(self):
        """El número aproximado se guarda igualmente en `num`: si no, una pregunta de flota
        —«los diez que más tráfico llevan»— se saltaría justo a los más grandes."""
        kind, num, txt = V.encode(V.EXACT_INT * 4)
        assert kind in V.NUMERIC_KINDS
        assert num is not None and num > 0

    def test_nan_e_infinito_vuelven_como_estaban(self):
        """Hoy pasan por JSON y vuelven; una columna REAL no los devuelve igual en los tres
        motores. Perderlos sería cambiar un valor imposible por un nulo creíble."""
        for v in (float('inf'), float('-inf')):
            assert _ida_y_vuelta(v) == v
        assert math.isnan(_ida_y_vuelta(float('nan')))
        assert V.encode(float('nan'))[0] == V.SPECIAL


class TestUnaMuestraEntera:

    def test_se_parte_y_se_junta(self):
        medidas = {'used': 42, 'temp': 36.5, 'name': 'sda', 'ok': True,
                   'falta': None, 'ips': ['10.0.0.1']}
        hechos = V.encode_sample(medidas)
        assert len(hechos) == len(medidas)
        assert V.decode_sample(hechos) == medidas

    def test_el_orden_es_estable(self):
        """Dos muestras iguales tienen que producir las mismas filas en el mismo orden, o
        comparar dos migraciones sería comparar dos barajas."""
        medidas = {'b': 1, 'a': 2, 'c': 3}
        assert [h[0] for h in V.encode_sample(medidas)] == ['a', 'b', 'c']
        assert V.encode_sample(medidas) == V.encode_sample(dict(reversed(list(medidas.items()))))

    def test_una_muestra_sin_ningun_campo_no_da_ningun_hecho(self):
        """325 de 4.026 muestras reales no miden nada: sólo dicen si la cosa respondió. La fila
        de la muestra tiene que poder existir sin un solo hecho detrás."""
        assert V.encode_sample({}) == []
        assert V.encode_sample(None) == []
        assert V.decode_sample([]) == {}


class TestLasMarcas:

    def test_ninguna_se_diferencia_solo_por_la_caja(self):
        """La intercalación por defecto de MySQL no distingue mayúsculas: `'n'` y `'N'` serían
        la misma marca ahí y dos distintas en SQLite — dos motores leyendo cosas distintas de
        la misma fila."""
        assert len({k.lower() for k in V.KINDS}) == len(V.KINDS)
        assert all(k == k.lower() for k in V.KINDS)

    def test_todas_caben_en_un_caracter(self):
        assert all(len(k) == 1 for k in V.KINDS)

    def test_las_numericas_son_las_que_guardan_numero(self):
        """`NUMERIC_KINDS` es lo que puede entrar en un AVG. Si una marca entrara ahí sin tener
        número, el promedio de la flota saldría contando nulos."""
        for kind in V.NUMERIC_KINDS:
            assert kind in V.KINDS
        for v, kind in ((1, V.INT), (1.5, V.FLOAT), (V.EXACT_INT * 4, V.BIGINT)):
            marca, num, _txt = V.encode(v)
            assert marca == kind and num is not None
        for v in ('texto', None, [1], float('nan')):
            marca, num, _txt = V.encode(v)
            assert marca not in V.NUMERIC_KINDS
            assert num is None, f'{v!r} guarda número sin ser numérica'
