#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que se lleva de una instalación a otra, y lo que se queda.

Sin base de datos: `portable` es una función sobre diccionarios y dos almacenes que se le pasan,
así que aquí se le pasan dos de mentira. Lo que se comprueba es la forma del sobre y las reglas
—sin uid, nada se pisa, lo saltado se cuenta— que es donde están las decisiones.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.dcim import portable                                   # noqa: E402


class _Cat:
    """Un catálogo de mentira: lo justo que `portable` le pide."""

    def __init__(self, filas=()):
        self.filas = list(filas)
        self.creados = []

    def get(self, uid):
        for f in self.filas:
            if f.get('uid') == uid:
                return f
        return None

    def by_key(self, maker, modelo):
        for f in self.filas:
            if (str(f.get('manufacturer') or '').lower() == str(maker).lower()
                    and str(f.get('model') or '').lower() == str(modelo).lower()):
                return f
        return None

    def create(self, row, source='manual', *, actor=''):
        self.creados.append(dict(row, _source=source))
        return 'nuevo-%d' % len(self.creados)


class _Builds:
    def __init__(self, filas=(), piezas=None, nombres=()):
        self.filas = list(filas)
        self.piezas = piezas or {}
        self.nombres = set(nombres)
        self.creadas = []
        self.puestas = []

    def get(self, uid):
        for f in self.filas:
            if f.get('uid') == uid:
                return f
        return None

    def parts_of(self, uid):
        return self.piezas.get(uid, [])

    def create(self, row, *, actor=''):
        if str(row.get('name') or '') in self.nombres:
            return ''
        self.creadas.append(row)
        return 'b-%d' % len(self.creadas)

    def part_add(self, build_uid, row, *, actor=''):
        self.puestas.append((build_uid, row))
        return 'p-%d' % len(self.puestas)


class _Plats:
    def __init__(self, filas=()):
        self.filas = list(filas)

    def list(self):
        return self.filas


class TestLoQueViaja:
    """Un identificador es de la base de datos que lo acuñó."""

    def test_el_sobre_dice_lo_que_es(self):
        doc = portable.export_doc()
        assert doc['kind'] == portable.KIND
        assert doc['version'] == portable.VERSION
        assert doc['exported_at']

    def test_un_modelo_viaja_sin_uid_y_sin_imagenes(self):
        cat = _Cat([{'uid': 'u1', 'manufacturer': 'HP', 'model': 'DL380', 'u_tenths': 20,
                     'front_image': 'library/x.png', 'source': 'library',
                     'ports': {'interfaces': {'1000base-t': 4}}}])
        fila = portable.export_doc(cat, type_uids=['u1'])['types'][0]
        assert fila['manufacturer'] == 'HP' and fila['ports']
        # El uid no significa nada en la otra casa; la imagen es un fichero de este disco.
        assert 'uid' not in fila and 'front_image' not in fila and 'source' not in fila

    def test_lo_vacio_no_se_escribe(self):
        """Un `"airflow": ""` afirma que ese modelo no tiene ventilación declarada, y lo que
        pasa es que nadie la escribió."""
        cat = _Cat([{'uid': 'u1', 'manufacturer': 'HP', 'model': 'X', 'airflow': '',
                     'extra': {}}])
        fila = portable.export_doc(cat, type_uids=['u1'])['types'][0]
        assert 'airflow' not in fila and 'extra' not in fila

    def test_lo_que_ya_no_esta_se_salta_sin_error(self):
        """Quien pidió veinte modelos y borró uno mientras tanto quiere los diecinueve."""
        cat = _Cat([{'uid': 'u1', 'manufacturer': 'HP', 'model': 'X'}])
        doc = portable.export_doc(cat, type_uids=['u1', 'se-borro'])
        assert len(doc['types']) == 1

    def test_una_plantilla_viaja_con_sus_piezas_y_su_plataforma_por_nombre(self):
        bs = _Builds([{'uid': 'b1', 'name': 'Servidor web', 'manufacturer': 'HP',
                       'model': 'Mini', 'platform_uid': 'p1'}],
                     {'b1': [{'uid': 'x', 'build_uid': 'b1', 'kind': 'memory',
                              'brand': 'Crucial', 'model': 'CT2K', 'qty': 1,
                              'type_uid': 'u9'}]})
        plats = _Plats([{'uid': 'p1', 'name': 'Windows 10 Pro'}])
        fila = portable.export_doc(None, bs, build_uids=['b1'], plats=plats)['builds'][0]
        assert fila['platform'] == 'Windows 10 Pro' and 'platform_uid' not in fila
        # La pieza va con lo copiado y sin el enlace al catálogo de allí.
        assert fila['parts'][0]['brand'] == 'Crucial'
        assert 'type_uid' not in fila['parts'][0] and 'uid' not in fila['parts'][0]


class TestLoQueSePuedeTraer:
    """Se mira lo que el fichero dice ser: un JSON con una lista dentro no es un export."""

    def test_un_fichero_de_otra_cosa_no_entra(self):
        assert portable.problems({'builds': []})
        assert portable.problems('vaya')
        assert portable.problems({'kind': portable.KIND, 'version': 99})
        assert portable.problems({'kind': portable.KIND, 'version': 1, 'types': {}})

    def test_el_sobre_propio_se_puede_volver_a_leer(self):
        assert portable.problems(portable.export_doc()) == []

    def test_lo_que_no_se_puede_leer_no_escribe_nada(self):
        cat = _Cat()
        portable.import_doc({'builds': [{'name': 'X'}]}, cat, _Builds())
        assert not cat.creados


class TestNadaSePisa:
    """Importar es traer lo que falta, no sustituir lo que hay."""

    def _sobre(self, **extra):
        doc = {'kind': portable.KIND, 'version': portable.VERSION}
        doc.update(extra)
        return doc

    def test_un_modelo_que_ya_esta_se_salta_y_se_cuenta(self):
        cat = _Cat([{'uid': 'u1', 'manufacturer': 'HP', 'model': 'DL380'}])
        n = portable.import_doc(self._sobre(types=[
            {'manufacturer': 'HP', 'model': 'DL380'},
            {'manufacturer': 'Dell', 'model': 'R740'}]), cat, _Builds())
        assert n['types_new'] == 1 and n['types_skipped'] == 1
        assert [c['model'] for c in cat.creados] == ['R740']

    def test_una_plantilla_con_el_mismo_nombre_se_salta(self):
        bs = _Builds(nombres=['Servidor web'])
        n = portable.import_doc(self._sobre(builds=[{'name': 'Servidor web'},
                                                    {'name': 'Otra'}]), _Cat(), bs)
        assert n['builds_new'] == 1 and n['builds_skipped'] == 1

    def test_las_piezas_entran_con_su_plantilla(self):
        bs = _Builds()
        n = portable.import_doc(self._sobre(builds=[
            {'name': 'X', 'parts': [{'kind': 'memory', 'brand': 'Crucial'},
                                    {'kind': 'ssd', 'brand': 'Samsung'}]}]), _Cat(), bs)
        assert n['parts'] == 2 and len(bs.puestas) == 2

    def test_una_plataforma_que_no_existe_se_dice_y_no_se_inventa(self):
        """Darla de alta es escribir en otro sitio a espaldas de quien pidió importar; callarlo
        deja la plantilla sin ella y nadie lo nota hasta abrirla."""
        bs = _Builds()
        n = portable.import_doc(self._sobre(builds=[{'name': 'X', 'platform': 'Debian 13'}]),
                                _Cat(), bs, plats=_Plats())
        assert n['platforms_missing'] == ['Debian 13']
        assert 'platform_uid' not in bs.creadas[0]

    def test_una_plataforma_que_si_existe_se_engancha_por_su_nombre(self):
        bs = _Builds()
        portable.import_doc(self._sobre(builds=[{'name': 'X', 'platform': 'windows 10 pro'}]),
                            _Cat(), bs, plats=_Plats([{'uid': 'p1', 'name': 'Windows 10 Pro'}]))
        assert bs.creadas[0]['platform_uid'] == 'p1'

    def test_una_ida_y_vuelta_no_duplica_nada(self):
        """Reimportar lo que uno mismo exportó es lo que hace cualquiera para comprobar que el
        fichero está bien, y tiene que ser inofensivo."""
        cat = _Cat([{'uid': 'u1', 'manufacturer': 'HP', 'model': 'DL380'}])
        doc = portable.export_doc(cat, type_uids=['u1'])
        n = portable.import_doc(doc, cat, _Builds())
        assert n['types_new'] == 0 and n['types_skipped'] == 1
        assert not cat.creados
