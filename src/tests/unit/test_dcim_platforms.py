#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las plataformas: con qué sale un equipo, escrito una vez.

Antes de esto, «sale con» era una caja de texto dentro de cada plantilla. Veinte plantillas con
una caja de texto son «Debian 12», «debian 12», «Debian GNU/Linux 12» y «deb12» — y entonces
«cuántas máquinas hay que actualizar» no tiene una respuesta: tiene cuatro, y ninguna está
entera.

Lo que se fija aquí es lo mismo que en las marcas y por el mismo motivo: **el slug es la
identidad y el nombre es lo que se lee**. Renombrarla es editar una fila; lo que apuntaba a ella
sigue apuntando.
"""

from __future__ import annotations

import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim.platforms import KINDS, PlatformStore                # noqa: E402
from lib.db import get_connector                                        # noqa: E402


@pytest.fixture()
def store():
    db = get_connector({'type': 'sqlite', 'path': ':memory:'})
    yield PlatformStore(db)
    try:
        db.close()
    except Exception:                           # pylint: disable=broad-except
        pass


class TestElSlugEsLaIdentidad:

    def test_se_escribe_una_y_se_lee(self, store):
        uid = store.create({'name': 'Debian', 'version': '12', 'kind': 'os'})
        assert uid
        fila = store.get(uid)
        assert fila['name'] == 'Debian' and fila['version'] == '12'
        assert fila['slug'] == 'debian'

    def test_dos_con_el_mismo_nombre_no_son_dos(self, store):
        assert store.create({'name': 'Debian'})
        assert store.create({'name': 'debian'}) == '', 'se coló la misma escrita distinto'
        assert store.create({'name': 'Debian.'}) == ''

    def test_sin_nombre_no_hay_plataforma(self, store):
        assert store.create({'version': '12'}) == ''
        assert store.create({'name': '   '}) == ''

    def test_renombrarla_no_la_convierte_en_otra(self, store):
        """Que es el punto entero de la tabla: lo que apuntaba a ella sigue apuntando."""
        uid = store.create({'name': 'Debian', 'version': '12'})
        assert store.update(uid, {'name': 'Debian 12 (bookworm)'})
        assert store.get(uid)['uid'] == uid
        assert store.get(uid)['slug'] == 'debian12bookworm'

    def test_no_se_puede_renombrar_encima_de_otra(self, store):
        store.create({'name': 'Debian'})
        otra = store.create({'name': 'Ubuntu'})
        assert store.update(otra, {'name': 'debian'}) is False
        assert store.get(otra)['name'] == 'Ubuntu'

    def test_el_slug_no_llega_de_fuera(self, store):
        """Dejarlo llegar sería dejar que dos plataformas se hicieran pasar por la misma."""
        uid = store.create({'name': 'Debian', 'slug': 'ubuntu'})
        assert store.get(uid)['slug'] == 'debian'


class TestLoQueSeGuardaDeUna:

    def test_una_clase_inventada_no_entra(self, store):
        """Una clase que no existe es un filtro que nunca devuelve nada y una fila que no sale
        en ninguna pantalla."""
        uid = store.create({'name': 'X', 'kind': 'vaporware'})
        assert store.get(uid)['kind'] == 'os'
        assert 'os' in KINDS

    def test_el_fabricante_es_opcional(self, store):
        """RouterOS es de MikroTik; Debian no es de nadie que salga en una factura, y obligar a
        rellenarlo sería obligar a inventárselo."""
        uid = store.create({'name': 'Debian'})
        assert store.get(uid)['brand_uid'] == ''

    def test_la_version_va_aparte_del_nombre(self, store):
        """Para poder preguntar «cuántas Debian hay» y «cuántas van por la 12» sin partir
        cadenas."""
        store.create({'name': 'Debian 12'})
        store.create({'name': 'Debian 11'})
        assert len(store.list()) == 2, 'dos nombres distintos, dos filas'

    def test_las_fechas_de_su_vida_son_las_mismas_seis(self, store):
        """Un sistema operativo deja de recibir parches igual que un servidor deja de venderse, y
        la lista sale del mismo sitio. En `extra` y no en columnas: añadir la séptima es editar
        un JSON, no una migración."""
        uid = store.create({'name': 'Windows 10 Pro',
                            'extra': {'eol': '2025-10-14', 'end_of_security': '2025-10-14'}})
        fila = store.get(uid)
        assert fila['extra']['eol'] == '2025-10-14'
        assert fila['extra']['end_of_security'] == '2025-10-14'

    def test_un_extra_que_no_es_un_diccionario_no_entra(self, store):
        """Guardar una lista donde se espera un objeto es dejar que la pantalla reviente al
        leerlo, semanas después y en otra sesión."""
        uid = store.create({'name': 'X', 'extra': ['no', 'soy', 'un', 'objeto']})
        assert store.get(uid)['extra'] == {}

    def test_lo_que_no_se_dice_no_se_borra(self, store):
        """Una edición parcial toca lo que nombra y nada más."""
        uid = store.create({'name': 'Debian', 'version': '12', 'notes': 'la de siempre'})
        store.update(uid, {'version': '13'})
        fila = store.get(uid)
        assert fila['version'] == '13' and fila['notes'] == 'la de siempre'


class TestLaListaSeLeeComoSeEscribe:

    def test_por_nombre_y_sin_que_las_mayusculas_manden(self, store):
        """`pfSense` detrás de la Z es lo que pasa cuando se ordena por el valor del carácter."""
        for n in ('Ubuntu', 'pfSense', 'Debian'):
            store.create({'name': n})
        assert [p['name'] for p in store.list()] == ['Debian', 'pfSense', 'Ubuntu']

    def test_ensure_devuelve_la_que_ya_esta(self, store):
        """Existe para lo que llega escrito: una plantilla que traía «Debian 12» en una caja de
        texto tiene que poder seguir diciendo lo mismo sin dar de alta nada primero."""
        uid = store.create({'name': 'Debian 12'})
        assert store.ensure('debian  12') == uid
        assert store.ensure('') == ''
        assert len(store.list()) == 1

    def test_retirarla_la_quita(self, store):
        uid = store.create({'name': 'Debian'})
        assert store.delete(uid) is True
        assert store.get(uid) is None
        assert store.delete(uid) is False
