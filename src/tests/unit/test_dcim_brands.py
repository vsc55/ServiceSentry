#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las marcas: la raíz del catálogo, que hasta ahora era una cadena de texto.

Lo que se prueba aquí es lo que una columna de texto repetida ocho mil quinientas veces no podía
hacer: que `HP`, `H.P.` y `hp` sean **una** marca y no tres, que reimportar la biblioteca no cree
trescientas más, que renombrar una sea un `UPDATE` y no ocho mil, y que lo que escribimos
nosotros —la web de soporte, el número de contrato— sobreviva a todo eso, porque es lo único de
aquí que no se puede volver a descargar.
"""

from __future__ import annotations

import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim import brands                                     # noqa: E402
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
def store(db):
    return brands.BrandStore(db)


@pytest.fixture()
def cat(db):
    return CatalogStore(db)


# ══ La identidad ════════════════════════════════════════════════════════════════════════

class TestElSlugEsLaIdentidad:

    def test_las_formas_de_escribir_un_nombre_se_juntan(self):
        """La biblioteca los escribe de tres formas según quién subiera el fichero."""
        assert brands.slug_of('HP') == brands.slug_of('H.P.') == brands.slug_of('hp')
        assert brands.slug_of('Hewlett-Packard') == brands.slug_of('hewlett packard')

    def test_dos_nombres_distintos_siguen_siendo_dos(self):
        assert brands.slug_of('Dell') != brands.slug_of('Delta')

    def test_un_nombre_que_no_deja_nada_no_es_un_nombre(self):
        assert brands.slug_of('  ...  ') == ''

    def test_alta_por_slug_y_no_por_texto(self, store):
        """Sin esto, reimportar crea una marca nueva cada vez que alguien mueve un punto."""
        uno = store.ensure('H.P.')
        assert store.ensure('hp') == uno and store.ensure('HP') == uno
        assert len(store.list()) == 1

    def test_y_no_pisa_lo_que_alguien_escribio(self, store):
        """La web de soporte es de esta casa: una importación no tiene por qué saber nada de
        ella, y desde luego no tiene por qué borrarla."""
        uid = store.ensure('Dell')
        store.update(uid, {'support_url': 'https://soporte.example/dell', 'account': 'C-42'})
        assert store.ensure('DELL') == uid
        assert store.get(uid)['support_url'] == 'https://soporte.example/dell'
        assert store.get(uid)['account'] == 'C-42'

    def test_sin_nombre_no_se_da_de_alta_nada(self, store):
        assert store.ensure('   ') == '' and store.list() == []


# ══ Escribirlas a mano ══════════════════════════════════════════════════════════════════

class TestLaFichaDeUnaMarca:

    def test_se_escribe_una_para_lo_que_todavia_no_hay(self, store):
        uid = store.create({'name': 'Taller Pérez', 'support_url': 'https://t.example',
                            'account': 'AB-1'})
        assert uid and store.get(uid)['account'] == 'AB-1'

    def test_dos_que_se_llaman_igual_no_se_distinguen(self, store):
        store.create({'name': 'Dell'})
        assert store.create({'name': 'dell'}) == '', 'la puntuación no las hace distintas'

    def test_ni_renombrando_una_encima_de_otra(self, store):
        a = store.create({'name': 'Dell'})
        store.create({'name': 'HPE'})
        assert store.update(a, {'name': 'hpe'}) is False
        assert store.get(a)['name'] == 'Dell'

    def test_el_slug_no_se_escribe_desde_fuera(self, store):
        """Dejar que llegue en la petición sería dejar que dos marcas se hicieran pasar por la
        misma —o que una se escondiera de la que ya está—."""
        uid = store.create({'name': 'Dell', 'slug': 'hpe'})
        assert store.get(uid)['slug'] == 'dell'

    def test_renombrarla_es_una_fila_y_no_ocho_mil(self, store, cat):
        uid = cat.brands.ensure('HP')
        cat.create({'manufacturer': 'HP', 'model': 'DL380'})
        cat.brands.update(uid, {'name': 'Hewlett Packard Enterprise'})
        assert cat.brands.get(uid)['name'] == 'Hewlett Packard Enterprise'
        # El modelo sigue diciendo lo que decía su fichero de origen, y sigue siendo suyo.
        fila = cat.list('manufacturer = ?', ('HP',))[0]
        assert fila['brand_uid'] == uid

    def test_por_nombre_sin_mirar_mayusculas(self, store):
        for n in ('zyxel', 'APC', 'i-PRO'):
            store.create({'name': n})
        assert [b['name'] for b in store.list()] == ['APC', 'i-PRO', 'zyxel']


# ══ Y el catálogo colgando de ellas ═════════════════════════════════════════════════════

class TestElCatalogoCuelgaDeLaMarca:

    def test_un_modelo_escrito_a_mano_da_de_alta_su_marca(self, cat):
        uid = cat.create({'manufacturer': 'Taller Pérez', 'model': 'Armario a medida'})
        assert cat.get(uid)['brand_uid']
        assert [b['name'] for b in cat.brands.list()] == ['Taller Pérez']

    def test_dos_formas_del_mismo_nombre_son_una_marca(self, cat):
        a = cat.create({'manufacturer': 'H.P.', 'model': 'DL380'})
        b = cat.create({'manufacturer': 'hp', 'model': 'DL360'})
        assert cat.get(a)['brand_uid'] == cat.get(b)['brand_uid']
        assert len(cat.brands.list()) == 1

    def test_importar_da_de_alta_las_que_traiga(self, cat):
        cat.replace('library', [
            {'manufacturer': 'Dell', 'model': 'R740', 'u_tenths': 20},
            {'manufacturer': 'Dell', 'model': 'R640', 'u_tenths': 10},
            {'manufacturer': 'Cisco', 'model': 'C9300', 'u_tenths': 10},
        ])
        assert sorted(b['name'] for b in cat.brands.list()) == ['Cisco', 'Dell']
        assert sorted(cat.brand_counts().values()) == [1, 2]

    def test_reimportar_no_las_duplica(self, cat):
        filas = [{'manufacturer': 'Dell', 'model': 'R740', 'u_tenths': 20}]
        cat.replace('library', filas)
        antes = cat.brands.list()[0]['uid']
        cat.replace('library', list(filas))
        assert [b['uid'] for b in cat.brands.list()] == [antes]

    def test_lo_ya_importado_recibe_su_marca_sin_volver_a_descargar_nada(self, cat, db):
        """`ADD COLUMN` no puede inventarse el valor: sin este repaso, quien ya tenía las ocho
        mil quinientas filas vería la pantalla de marcas vacía. Nadie reinstala para recibir un
        arreglo, y menos aún vuelve a bajarse ochocientos cincuenta megas."""
        cat.replace('library', [{'manufacturer': 'Dell', 'model': 'R740', 'u_tenths': 20},
                                {'manufacturer': 'Cisco', 'model': 'C9300', 'u_tenths': 10}])
        # Volvemos al estado de antes de que existiera la columna.
        db.execute(f"UPDATE {cat._sql_table} SET brand_uid = ''")   # noqa: SLF001
        db.execute('DELETE FROM dc_brand')
        db.commit()
        assert cat.backfill_brands() == 2
        assert sorted(b['name'] for b in cat.brands.list()) == ['Cisco', 'Dell']
        assert all(f['brand_uid'] for f in cat.list())

    def test_y_el_repaso_se_hace_una_vez(self, cat):
        cat.replace('library', [{'manufacturer': 'Dell', 'model': 'R740', 'u_tenths': 20}])
        assert cat.backfill_brands() == 0, 'no quedaba ninguna sin marca'

    def test_la_cuenta_sale_de_una_sola_consulta(self, cat):
        cat.replace('library', [{'manufacturer': 'Dell', 'model': 'R740', 'u_tenths': 20},
                                {'manufacturer': 'Dell', 'model': 'R640', 'u_tenths': 10}])
        uid = cat.brands.list()[0]['uid']
        assert cat.brand_counts() == {uid: 2}
