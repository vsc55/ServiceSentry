#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El número de inventario: único entre todo, y el siguiente lo pone el panel.

Dos reglas, y las dos existen por el mismo motivo: **un número de inventario que se repite no da
ningún error el día que se escribe**. Aparece meses después, cuando dos fichas dicen ser la misma
cosa y ya no hay forma de saber cuál de las dos etiquetas está mal.

* Es único **entre todo lo inventariado**, no dentro de su tabla: en el albarán, en la hoja de la
  aseguradora y en la caja de repuestos hay una lista, no cuatro.
* Nadie debería teclear el siguiente. Quien numera un armario entero escribe cuarenta veces un
  número que ya está decidido, y la vez que se equivoca no lo dice nadie.

Sin app y sin HTTP: la regla es cálculo puro y el almacén es una SQLite en memoria.
"""

from __future__ import annotations

import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim import assets                                    # noqa: E402
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


# ══ La regla, sin base de datos ═════════════════════════════════════════════════════════

class TestQueEsPedirUnNumero:

    def test_lo_normal_es_no_pedirlo(self):
        """Casi todo lo que se teclea aquí es un número ya decidido, y se guarda tal cual."""
        assert assets.asks('INV-045') is None
        assert assets.resolve('INV-045', ['INV-1']) == ('INV-045', '')

    def test_un_interrogante_es_el_siguiente(self):
        assert assets.resolve('INV-?', ['INV-44', 'INV-45']) == ('INV-46', '')

    def test_y_tres_interrogantes_es_el_siguiente_a_tres_cifras(self):
        """El ancho se pide con los propios interrogantes."""
        assert assets.resolve('INV-???', ['INV-45']) == ('INV-046', '')

    def test_el_relleno_no_es_otra_numeracion(self):
        """`INV-045` y `INV-45` son el 45. Contarlos aparte haría que cambiar de ancho un día
        empezara la cuenta otra vez por el uno — dos cosas con el mismo número."""
        assert assets.resolve('INV-?', ['INV-045']) == ('INV-46', '')

    def test_vale_cualquier_principio(self):
        """La regla es del comodín, no de la palabra «INV»."""
        assert assets.resolve('RACK-?', ['RACK-3']) == ('RACK-4', '')
        assert assets.resolve('CBL-??', []) == ('CBL-01', '')

    def test_y_puede_llevar_algo_detras(self):
        assert assets.resolve('INV-?-2026', ['INV-7-2026', 'INV-9-2025']) == ('INV-8-2026', '')

    def test_el_relleno_es_un_minimo_y_no_un_tope(self):
        """Pasar de `INV-99` a `INV-100` con dos interrogantes escribe las tres cifras: la
        alternativa es no poder numerar el ciento uno."""
        assert assets.resolve('INV-??', ['INV-99']) == ('INV-100', '')

    def test_el_primero_es_el_uno(self):
        assert assets.resolve('INV-???', []) == ('INV-001', '')

    def test_el_siguiente_es_el_mayor_mas_uno_y_nunca_un_hueco(self):
        """Si el 20 se dio de baja, el 20 no vuelve: su etiqueta sigue en un cajón y el
        historial sigue nombrándolo. Reciclar un número convierte dos cosas en una a los ojos
        de cualquiera que mire un papel viejo."""
        assert assets.resolve('INV-?', ['INV-1', 'INV-2', 'INV-45']) == ('INV-46', '')

    def test_lo_que_no_es_un_numero_no_cuenta(self):
        """`INV-BIS` no es el número ninguno, y tomarlo por uno daría un salto que nadie
        entiende."""
        assert assets.resolve('INV-?', ['INV-BIS', 'INV-3']) == ('INV-4', '')

    def test_ni_lo_que_solo_se_le_parece(self):
        assert assets.resolve('INV-?', ['INVX-9', 'OTRO-40']) == ('INV-1', '')

    def test_dos_grupos_de_interrogantes_no_son_un_patron(self):
        """`INV-?-?` puede querer decir cualquier cosa, y elegir por quien lo escribió guardaría
        un número que no pidió — que encima parece razonable y no se descubre."""
        valor, err = assets.resolve('INV-?-?', [])
        assert err == 'dcim_asset_ask_many' and valor == 'INV-?-?'

    def test_las_mayusculas_son_el_mismo_numero(self):
        """`inv-45` e `INV-45` son el mismo número para cualquiera que los lea."""
        assert assets.resolve('INV-?', ['inv-45']) == ('INV-46', '')
        assert assets.norm('  INV-45 ') == 'inv-45'


# ══ Y contra lo que ya está escrito ═════════════════════════════════════════════════════

class TestUnicoEntreTodoLoInventariado:

    def _rack(self, store, **extra):
        site = store.sites.create({'name': 'DC'})
        room = store.rooms.create({'site_uid': site, 'name': 'Sala'})
        return store.racks.create(dict({'room_uid': room, 'name': 'R1'}, **extra))

    def test_las_tablas_que_lo_llevan_se_descubren(self, store):
        """Preguntándole a cada tabla si tiene la columna. Una lista escrita a mano hay que
        acordarse de tocarla, y no acordarse no da ningún error: da un número repetido."""
        tablas = {p._TABLE for p in store.asset_parts()}       # noqa: SLF001
        assert {'dc_item', 'dc_cable', 'dc_feed', 'dc_rack'} <= tablas
        # Y no las que no lo llevan: una sala no se compra.
        assert 'dc_room' not in tablas and 'dc_site' not in tablas

    def test_un_equipo_y_un_cable_no_pueden_llevar_el_mismo(self, store):
        """En el albarán hay UNA lista. Comprobarlo por tabla dejaría dos cosas distintas con el
        mismo número y ningún error el día que se escribe."""
        rack = self._rack(store)
        store.items.create({'rack_uid': rack, 'asset': 'INV-45'})
        _, err = store.mint_asset('INV-45')
        assert err == 'dcim_asset_taken'

    def test_ni_escrito_de_otra_manera(self, store):
        rack = self._rack(store)
        store.items.create({'rack_uid': rack, 'asset': 'INV-45'})
        assert store.mint_asset(' inv-45 ')[1] == 'dcim_asset_taken'

    def test_una_ficha_no_choca_consigo_misma(self, store):
        """Guardar un equipo sin tocarle el número no puede fallar."""
        rack = self._rack(store)
        uid = store.items.create({'rack_uid': rack, 'asset': 'INV-45'})
        assert store.mint_asset('INV-45', uid) == ('INV-45', '')

    def test_en_blanco_no_es_un_duplicado(self, store):
        """Un número en blanco es «nadie lo ha dicho», y de eso puede haber cuarenta."""
        rack = self._rack(store)
        store.items.create({'rack_uid': rack, 'asset': ''})
        store.items.create({'rack_uid': rack, 'asset': ''})
        assert store.mint_asset('') == ('', '')

    def test_el_siguiente_cuenta_lo_de_todas_las_tablas(self, store):
        """Si el 45 lo lleva un cable, el siguiente equipo es el 46. Contar sólo los de su
        tabla daría dos cosas con el 45."""
        rack = self._rack(store)
        store.cables.create({'a_item': 'x', 'b_item': 'y', 'asset': 'INV-45'})
        assert store.mint_asset('INV-?') == ('INV-46', '')
        store.items.create({'rack_uid': rack, 'asset': 'INV-46'})
        assert store.mint_asset('INV-?') == ('INV-47', '')

    def test_el_armario_tambien_se_compra(self, store):
        """Lo llevaban el equipo y los dos cables, y el mueble que los sostiene no — que es el
        que sale por más dinero en el albarán."""
        uid = self._rack(store, asset='RACK-1')
        assert (store.racks.get(uid) or {}).get('asset') == 'RACK-1'

    def test_dos_numeraciones_no_se_estorban(self, store):
        """`RACK-?` cuenta racks y `INV-?` cuenta lo demás: el principio del número es lo que
        separa las cuentas, sin ninguna lista que diga cuáles hay."""
        rack = self._rack(store, asset='RACK-9')
        store.items.create({'rack_uid': rack, 'asset': 'INV-3'})
        assert store.mint_asset('RACK-?') == ('RACK-10', '')
        assert store.mint_asset('INV-?') == ('INV-4', '')

    def test_lo_minado_no_puede_salir_repetido(self, store):
        """El hueco entre «resolver» y «comprobar» es por donde entraría justo el caso que esto
        viene a impedir: se pide el siguiente y resulta que alguien lo tiene ya escrito con otro
        relleno."""
        rack = self._rack(store)
        store.items.create({'rack_uid': rack, 'asset': 'INV-7'})
        store.items.create({'rack_uid': rack, 'asset': 'INV-008'})
        assert store.mint_asset('INV-?') == ('INV-9', '')

    def test_un_comodin_del_like_no_cuenta_como_comodin(self, store):
        """`%` y `_` son caracteres que alguien puede teclear.

        Sin escaparlos, pedir `%-?` se lleva de la base la numeración ENTERA de la instalación
        para tirarla luego en Python: el resultado sale bien y lo que se rompe es el trabajo —
        que es la clase de fallo que no se ve hasta que la tabla es grande."""
        rack = self._rack(store)
        store.items.create({'rack_uid': rack, 'asset': 'INV-50'})
        assert store.assets_like('%-', '') == []
        assert store.mint_asset('%-?') == ('%-1', '')
