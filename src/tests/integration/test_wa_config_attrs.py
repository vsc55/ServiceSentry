#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Un ajuste que dice reflejarse en un atributo, se refleja.

El registro (`lib/config/spec.py`) permite que un campo declare `attr=`: «el valor de esto vive
además en ese atributo del panel», que es de donde lo leen las veinte pantallas que no van a
abrir la configuración en cada petición.

Los enteros y los interruptores tenían su pasada genérica. **Las cadenas no**: cada una había
que escribirla a mano en `_apply_config_attrs`, y las que nadie escribió no llegaban a ninguna
parte. Eso no da ningún error en ningún sitio:

* la pantalla acepta el valor y lo guarda;
* al volver a abrirla, ahí está, escrito;
* y quien lo lee —`getattr(wa, '_LO_QUE_SEA', '')`— recibe una cadena vacía **para siempre**,
  ni siquiera reiniciando, porque ese atributo solo lo ponía el camino de las variables de
  entorno.

Así estaban cinco: el servidor de teselas del mapa y su atribución, la dirección del catálogo de
modelos, la carpeta de imágenes y la de copias de seguridad. Se descubrió porque alguien
configuró el mapa con la plantilla de OpenStreetMap y el mapa siguió saliendo vacío —que es la
única forma que tiene de avisar un fallo que no falla.

Esta prueba recorre **el registro**, no una lista escrita a mano: el día que se añada la sexta
cadena con atributo, o la primera de un tipo nuevo, el guardián ya está puesto.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

#: Lo que se le pone a cada campo que no admite cualquier cosa. Un idioma tiene que ser uno de
#: los que hay —a un valor inventado se le hace caso omiso, y con razón—, y la URL pública se
#: normaliza al guardarla. Los demás se conforman con una marca.
_VALORES = {
    'web_admin|default_lang': 'en_EN',
    'web_admin|status_lang': 'es_ES',
    'web_admin|public_url': 'panel.example.org',
}

_SIN_TOCAR = '\x00sin-tocar\x00'


def _campos():
    from lib.core.config.service import STR_RULES                   # noqa: PLC0415
    return sorted((p, a) for p, a in STR_RULES.items() if a)


class TestLoQueSeGuardaLlegaADondeSeLee:

    def test_cada_cadena_del_registro_alcanza_su_atributo(self, admin):
        """La prueba entera: se pone una marca en el atributo, se aplica una configuración con
        el campo escrito, y el atributo tiene que haber cambiado. Da igual en qué se convierta
        —un idioma se valida, una URL se normaliza—; lo que no puede es no llegar."""
        mudos = []
        for path, attr in _campos():
            seccion, campo = path.split('|')
            previo = getattr(admin, attr, None)
            setattr(admin, attr, _SIN_TOCAR)
            try:
                admin._apply_config_attrs({seccion: {campo: _VALORES.get(path, f'probe-{campo}')}})
                if getattr(admin, attr, None) == _SIN_TOCAR:
                    mudos.append(f'{path} -> {attr}')
            finally:
                setattr(admin, attr, previo)
        assert not mudos, ('ajustes que se guardan y no los lee nadie:\n  '
                           + '\n  '.join(mudos))

    def test_y_hay_alguna(self, admin):
        """Si el registro dejara de declarar cadenas con atributo, la prueba de arriba pasaría
        sin mirar nada — verde y ciega, que es lo peor de los dos mundos."""
        assert len(_campos()) >= 5

    def test_el_servidor_de_teselas_es_una_de_ellas(self, admin):
        """Por su nombre, porque es la que se rompió y la que se mira al leer esto."""
        assert 'web_admin|dcim_map_tiles' in dict(_campos())

    def test_ningun_tipo_se_queda_sin_pasada(self):
        """Un campo con `attr` de un tipo que ninguna de las tres pasadas mira es exactamente el
        agujero de las cadenas otra vez, con otro tipo."""
        from lib.config.spec import CONFIG_FIELDS                   # noqa: PLC0415
        huerfanos = sorted(f.path for f in CONFIG_FIELDS
                           if f.attr and f.type not in (str, int, bool) and not f.no_rule)
        assert not huerfanos, huerfanos


class TestYLlegaHastaLaPantallaQueLoUsa:
    """De extremo a extremo con el mapa, que es donde se vio: guardar por la ruta de verdad,
    y que el widget del panel de control reciba lo guardado."""

    _TESELAS = 'https://tile.example.org/{z}/{x}/{y}.png'

    def _guarda(self, client):
        from tests.conftest import _login                           # noqa: PLC0415
        _login(client)
        r = client.put('/api/v1/config',
                       json={'web_admin': {'dcim_map_tiles': self._TESELAS}})
        assert r.status_code == 200, r.get_json()
        return client

    def test_el_widget_lo_recibe_sin_reiniciar(self, client):
        """Sin reiniciar, que es lo que hace que un ajuste sea un ajuste y no un fichero de
        arranque."""
        c = self._guarda(client)
        datos = c.get('/api/v1/overview/widget/dcim_sites').get_json()['content']
        assert datos['tiles'] == self._TESELAS

    def test_y_el_cuadro_del_inventario_tambien(self, client):
        c = self._guarda(client)
        assert c.get('/api/v1/dcim/board').get_json()['map']['tiles'] == self._TESELAS

    def test_y_la_politica_de_contenido_deja_pedir_esas_imagenes(self, client):
        """La mitad silenciosa: sin esto el navegador bloquea cada tesela y **no dice nada** en
        la página — el mapa sale vacío exactamente igual que si no estuviera configurado."""
        c = self._guarda(client)
        csp = c.get('/admin').headers.get('Content-Security-Policy', '')
        assert 'https://tile.example.org' in csp
        # El ORIGEN, no la URL: una tesela es una de un millón de rutas debajo.
        assert '{z}' not in csp
        # Y solo las imágenes: el guion de un tercero se queda fuera, que es la diferencia
        # entre decirle dónde están tus sedes y darle la página entera.
        assert 'https://tile.example.org' not in csp.split('img-src')[0]
        assert 'tile.example.org' not in csp.split('script-src')[1].split(';')[0]

    def test_sin_configurar_la_politica_queda_como_estaba(self, client):
        """Una instalación sin mapa no abre nada."""
        from tests.conftest import _login                           # noqa: PLC0415
        _login(client)
        csp = client.get('/admin').headers.get('Content-Security-Policy', '')
        assert "img-src 'self' data:;" in csp
