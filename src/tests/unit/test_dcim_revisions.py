#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qué decía una ficha del catálogo antes, y quién la cambió.

Un modelo del catálogo es un dato **compartido**: de él cuelgan las plantillas, las piezas
estampadas en veinte máquinas y la altura con la que se dibuja un alzado. La corrección que rompe
algo casi nunca se descubre el día que se hace — se descubre semanas después, cuando alguien dice
«esto antes ponía otra cosa» y no hay forma de saber si tiene razón.
"""

from __future__ import annotations

import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim import revisions                                  # noqa: E402
from lib.core.dcim.catalog import CatalogStore                       # noqa: E402
from lib.db import get_connector                                     # noqa: E402


@pytest.fixture()
def db():
    conn = get_connector({'type': 'sqlite', 'path': ':memory:'})
    yield conn
    try:
        conn.close()
    except Exception:                           # pylint: disable=broad-except
        pass


@pytest.fixture()
def revs(db):
    return revisions.RevisionStore(db)


@pytest.fixture()
def cat(db):
    return CatalogStore(db)


# ══ La diferencia ═══════════════════════════════════════════════════════════════════════

class TestQueCambio:

    def test_dice_las_dos_caras_de_cada_campo(self):
        d = revisions.diff({'model': 'A', 'size': '1 TB'}, {'model': 'A', 'size': '2 TB'})
        assert d == {'size': ['1 TB', '2 TB']}

    def test_un_numero_escrito_de_dos_formas_no_es_un_cambio(self):
        """Uno viene de la base de datos y otro de un formulario. Decir que cambió sería llenar
        el historial de cambios que nadie hizo."""
        assert revisions.diff({'u_tenths': 10}, {'u_tenths': '10'}) == {}

    def test_lo_que_se_escribe_en_cada_guardado_no_cuenta(self):
        """Enseñarlos convertiría cada renglón en una lista de tres cosas que cambian siempre y
        una que importa."""
        assert revisions.diff({'imported_at': 'ayer'}, {'imported_at': 'hoy'}) == {}
        assert revisions.diff({'match_key': 'a'}, {'match_key': 'b'}) == {}

    def test_una_columna_de_json_se_abre_por_dentro(self):
        """Sin esto, cambiar la interfaz de un disco sale como dos volcados de `extra` uno al
        lado del otro y hay que compararlos a ojo — que es lo que este historial existe para no
        tener que hacer."""
        d = revisions.diff({'extra': {'interface': 'SATA'}},
                           {'extra': {'interface': 'NVMe', 'rpm': 7200}})
        assert d == {'extra.interface': ['SATA', 'NVMe'], 'extra.rpm': [None, 7200]}

    def test_y_si_no_cambia_nada_dentro_no_dice_nada(self):
        assert revisions.diff({'extra': {'a': 1}}, {'extra': {'a': 1}}) == {}

    def test_un_campo_que_aparece_o_desaparece_es_un_cambio(self):
        assert revisions.diff({}, {'size': '2 TB'}) == {'size': [None, '2 TB']}

    def test_lo_que_no_es_texto_se_compara_entero(self):
        assert revisions.diff({'ports': {'a': 1}}, {'ports': {'a': 1}}) == {}
        assert revisions.diff({'ports': {'a': 1}}, {'ports': {'a': 2}})


# ══ El historial ════════════════════════════════════════════════════════════════════════

class TestElHistorial:

    def test_de_la_mas_nueva_a_la_mas_vieja(self, revs):
        for n in ('A', 'B', 'C'):
            revs.keep('x', {'model': n}, actor='ana')
        assert [h['data']['model'] for h in revs.history('x')] == ['C', 'B', 'A']

    def test_el_orden_no_depende_del_reloj(self, revs):
        """Este proyecto guarda segundos: tres cambios seguidos caen en el mismo, y ordenarlos
        por la fecha los devolvería al azar — que es como una versión aparece antes que la que la
        produjo y la diferencia sale del revés."""
        for n in range(10):
            revs.keep('x', {'model': str(n)})
        h = revs.history('x')
        assert [f['data']['model'] for f in h] == [str(n) for n in range(9, -1, -1)]
        assert len({f['at'] for f in h}) <= 2, 'el caso que se quiere probar es el mismo segundo'

    def test_cada_renglon_trae_lo_que_ese_cambio_hizo(self, revs):
        revs.keep('x', {'model': 'A', 'size': '1 TB'}, action='create')
        revs.keep('x', {'model': 'A', 'size': '2 TB'})
        h = revs.history('x')
        assert h[0]['changes'] == {'size': ['1 TB', '2 TB']}

    def test_la_primera_no_compara_contra_nada(self, revs):
        revs.keep('x', {'model': 'A'}, action='create')
        assert revs.history('x')[0]['changes'] == {}

    def test_quien_lo_hizo_va_en_la_version(self, revs):
        revs.keep('x', {'model': 'A'}, actor='ana')
        assert revs.history('x')[0]['by'] == 'ana'

    def test_se_poda_a_las_ultimas(self, revs):
        """Sin tope, esta tabla crece durante toda la vida de la instalación por una función que
        casi nadie mira."""
        for n in range(revisions.KEEP + 5):
            revs.keep('x', {'model': str(n)})
        h = revs.history('x')
        assert len(h) == revisions.KEEP
        assert h[0]['data']['model'] == str(revisions.KEEP + 4), 'se van las viejas, no las nuevas'

    def test_cada_ficha_tiene_la_suya(self, revs):
        revs.keep('x', {'model': 'A'})
        revs.keep('y', {'model': 'B'})
        assert len(revs.history('x')) == 1 and len(revs.history('y')) == 1

    def test_olvidar_se_lleva_las_de_una_sola(self, revs):
        revs.keep('x', {'model': 'A'})
        revs.keep('y', {'model': 'B'})
        assert revs.forget('x') == 1
        assert revs.history('x') == [] and len(revs.history('y')) == 1


# ══ Y el catálogo lo escribe solo ═══════════════════════════════════════════════════════

class TestElCatalogoDejaConstancia:

    def test_crear_deja_la_primera_version(self, cat):
        uid = cat.create({'manufacturer': 'Dell', 'model': 'R740'}, actor='ana')
        h = cat.revs.history(uid)
        assert len(h) == 1 and h[0]['action'] == 'create' and h[0]['by'] == 'ana'

    def test_corregir_deja_la_suya_con_lo_que_cambio(self, cat):
        uid = cat.create({'manufacturer': 'Dell', 'model': 'R740'}, actor='ana')
        cat.update(uid, {'kind': 'server'}, actor='luis')
        h = cat.revs.history(uid)
        assert len(h) == 2 and h[0]['by'] == 'luis'
        # `other` porque al crearla se dedujo: nadie dijo la clase y eso es una respuesta.
        assert h[0]['changes'].get('kind') == ['other', 'server']

    def test_poner_una_imagen_se_apunta_aunque_no_cambie_ningun_campo(self, cat):
        """Sin la acción sería un renglón vacío: la comparación no ve el nombre de un fichero
        que este historial no compara."""
        uid = cat.create({'manufacturer': 'Dell', 'model': 'R740'})
        cat.set_image(uid, 'front', 'foto.png', actor='ana')
        assert cat.revs.history(uid)[0]['action'] == 'image'
        cat.set_image(uid, 'front', '', actor='ana')
        assert cat.revs.history(uid)[0]['action'] == 'image_drop'

    def test_importar_no_deja_versiones(self, cat):
        """Reemplaza el origen entero —miles de filas, con uid nuevos— así que un historial por
        uid no sobreviviría de todas formas, y guardarlo haría crecer la tabla en ocho mil
        renglones cada vez que alguien actualiza la biblioteca."""
        cat.replace('library', [{'manufacturer': 'Dell', 'model': 'R740', 'u_tenths': 20},
                                {'manufacturer': 'Cisco', 'model': 'C9300', 'u_tenths': 10}])
        for fila in cat.list():
            assert cat.revs.history(fila['uid']) == []

    def test_borrar_una_ficha_se_lleva_su_historial(self, cat):
        """Las versiones de algo que ya no existe no contestan a nada y se quedarían para
        siempre."""
        uid = cat.create({'manufacturer': 'Dell', 'model': 'R740'})
        cat.update(uid, {'kind': 'server'})
        cat.delete(uid)
        assert cat.revs.history(uid) == []

    def test_los_atributos_se_pueden_corregir(self, cat):
        """`extra` y `ports` son JSON y estaban fuera de la lista de lo editable, así que
        corregir las medidas de un armario o la interfaz de un disco decía «guardado» y no
        guardaba nada. Un fallo que no da error: la pantalla afirma que escribió."""
        uid = cat.create({'manufacturer': 'Samsung', 'model': 'MZ',
                          'tree': 'component-types', 'kind': 'ssd'})
        assert cat.update(uid, {'extra': {'interface': 'NVMe'}}) is True
        assert cat.get(uid)['extra'] == {'interface': 'NVMe'}
        assert cat.revs.history(uid)[0]['changes'] == {'extra.interface': [None, 'NVMe']}

    def test_la_version_guarda_la_ficha_entera(self, cat):
        """Volver atrás es escribir esto, y una diferencia no se puede escribir sin la fila que
        la precede — que es justo la que puede haberse podado."""
        uid = cat.create({'manufacturer': 'Dell', 'model': 'R740', 'part_number': 'PN-1'})
        datos = cat.revs.history(uid)[0]['data']
        assert datos['manufacturer'] == 'Dell' and datos['part_number'] == 'PN-1'
