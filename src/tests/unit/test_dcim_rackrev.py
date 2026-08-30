#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cómo estaba un armario, y qué le pasó.

Sin base de datos: `rackrev` es una función sobre diccionarios. Lo que se comprueba es lo que
decide — qué entra en la foto, qué cuenta como un cambio, y sobre todo qué NO cuenta como dos.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.dcim import rackrev                                   # noqa: E402


def _it(uid, **kw):
    fila = {'uid': uid, 'label': uid.upper(), 'u_start': 1, 'u_height': 1, 'face': 'full'}
    fila.update(kw)
    return fila


class TestLaFoto:

    def test_sale_igual_aunque_la_base_los_devuelva_al_reves(self):
        """Dos fotos del mismo armario tienen que salir iguales cuando nada ha cambiado. Con el
        orden que dé la consulta, reordenarla se leería como que alguien movió tres equipos."""
        rack = {'name': 'RK', 'u_height': 10}
        a = rackrev.snapshot(rack, [_it('x', u_start=1), _it('y', u_start=4)])
        b = rackrev.snapshot(rack, [_it('y', u_start=4), _it('x', u_start=1)])
        assert a == b
        assert rackrev.same(a, b)

    def test_lleva_lo_que_se_le_pregunta_a_un_armario_de_hace_medio_ano(self):
        foto = rackrev.snapshot({'name': 'RK', 'u_height': 42},
                                [_it('x', serial='SN1', asset='INV-1')])
        assert foto['name'] == 'RK' and foto['u_height'] == 42
        assert foto['items'][0]['serial'] == 'SN1'
        assert foto['items'][0]['asset'] == 'INV-1'


class TestQueCuentaComoUnCambio:

    def _foto(self, *items, **rack):
        base = {'name': 'RK', 'u_height': 10}
        base.update(rack)
        return rackrev.snapshot(base, list(items))

    def test_mover_algo_es_UN_cambio_y_no_dos(self):
        """Un equipo que se mueve no es uno que se va y otro que llega: es el mismo. Contarlo
        como dos convierte «moví el switch una U» en dos líneas que no se entienden juntas."""
        antes = self._foto(_it('sw', u_start=3))
        ahora = self._foto(_it('sw', u_start=2))
        cambios = rackrev.compare(antes, ahora)
        assert len(cambios) == 1
        assert cambios[0]['kind'] == 'edit' and cambios[0]['field'] == 'u_start'
        assert cambios[0]['from'] == 3 and cambios[0]['to'] == 2

    def test_lo_que_llega_y_lo_que_se_va(self):
        cambios = rackrev.compare(self._foto(_it('a')), self._foto(_it('b')))
        clases = sorted(c['kind'] for c in cambios)
        assert clases == ['add', 'drop']

    def test_el_armario_tambien_cambia(self):
        """Renombrarlo o crecerlo mueve de sitio a todo lo que hay dentro."""
        cambios = rackrev.compare(self._foto(name='RK'), self._foto(name='RK-01'))
        assert [c['kind'] for c in cambios] == ['rack']
        assert cambios[0]['field'] == 'name'

    def test_lo_que_no_cambio_no_sale(self):
        assert rackrev.compare(self._foto(_it('a')), self._foto(_it('a'))) == []

    def test_donde_esta_se_dice_como_se_lee(self):
        """`U4` y `U4–U6`, no un número suelto: lo que ocupa un equipo de tres U es tres U."""
        # El que LLEGÓ, no el primero de la lista: contra una foto vacía cambian también los
        # campos del armario, y salen antes.
        cambios = rackrev.compare({}, self._foto(_it('a', u_start=4, u_height=3)))
        llego = next(c for c in cambios if c['kind'] == 'add')
        assert llego['to'] == 'U4–U6'

    def test_y_lo_montado_no_dice_una_U_que_no_ocupa(self):
        """Un mini PC sobre una bandeja no ocupa U: el suyo lo paga la bandeja, y decir «U4»
        de él sería decir que ocupa el mismo sitio dos veces."""
        cambios = rackrev.compare({}, self._foto(_it('pc', parent_uid='bandeja', u_start=4)))
        llego = next(c for c in cambios if c['kind'] == 'add')
        assert llego['to'] == 'mounted'
