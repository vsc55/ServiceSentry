#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La carpeta de imágenes del inventario: qué entra, con qué nombre, y dónde acaba.

Son ficheros que alguien sube, y eso los pone en la única categoría del panel donde un fallo no
se ve venir: **el nombre lo elige quien sube**. El catálogo de MIB ya trajo una travesía de
rutas exactamente de esta forma, y el arreglo que aguanta no es comprobar mejor el nombre — es
que el nombre no venga nunca de fuera.

Lo que se vigila aquí:

* **el tipo lo decide el contenido**, no la extensión: una extensión es una afirmación de quien
  sube el fichero, y los primeros bytes de un PNG no lo son;
* **el nombre que se guarda lo acuña este módulo**, así que nada de lo que llegue por la red
  llega nunca a un sistema de ficheros;
* **nada se escribe fuera de la carpeta**, ni siquiera con un nombre que apunte hacia arriba;
* **la carpeta configurada manda**, y cuando está vacía se cae al sitio por defecto — que es lo
  que permite que el ajuste siga vacío en toda instalación a la que le dé igual.

Sin app y sin base de datos: el almacén no tiene ni una cosa ni la otra, y eso es justo lo que
deja apuntarlo a un directorio temporal en una línea.
"""

from __future__ import annotations

import io
import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim import media                                     # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 40
JPG = b'\xff\xd8\xff\xe0' + b'0' * 40
GIF = b'GIF89a' + b'0' * 40
WEBP = b'RIFF' + b'\x00\x00\x00\x00' + b'WEBP' + b'0' * 40
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'


@pytest.fixture()
def var(tmp_path):
    return str(tmp_path / 'var')


class TestElTipoLoDiceElContenido:
    """Una extensión es lo que dice quien sube; los primeros bytes, no."""

    @pytest.mark.parametrize('blob, ext', [
        (PNG, '.png'), (JPG, '.jpg'), (GIF, '.gif'), (WEBP, '.webp'), (SVG, '.svg'),
    ])
    def test_cada_formato_se_reconoce_por_sus_bytes(self, blob, ext):
        assert media.kind_of(blob) == ext

    def test_un_script_disfrazado_de_png_no_es_una_imagen(self):
        assert media.kind_of(b'#!/bin/sh\nrm -rf /\n') == ''

    def test_y_no_se_guarda_aunque_lo_llamen_asi(self, var):
        """Este es el caso: se rechaza ANTES de existir, y no queda guardado bajo un nombre
        que lo hace parecer una imagen."""
        name, err = media.save(var, b'#!/bin/sh\n')
        assert name == '' and err == 'dcim_media_not_an_image'
        assert media.every(var) == []

    def test_un_riff_que_no_es_webp_no_cuela(self):
        """`RIFF` lo empiezan también un WAV y un AVI: la marca está en el byte 8."""
        assert media.kind_of(b'RIFF' + b'\x00' * 4 + b'WAVE' + b'0' * 20) == ''

    def test_un_xml_que_no_trae_svg_dentro_tampoco(self):
        assert media.kind_of(b'<?xml version="1.0"?><rss><channel/></rss>') == ''

    def test_un_fichero_vacio_no_es_nada(self):
        assert media.kind_of(b'') == ''


class TestElNombreLoAcunaElPanel:
    """Lo único que nunca puede llegar a un sistema de ficheros es un nombre elegido fuera."""

    def test_lo_guardado_no_se_llama_como_lo_subido(self, var):
        name, err = media.save(var, PNG)
        assert not err
        assert media.is_name(name) and name.endswith('.png')

    def test_dos_subidas_del_mismo_fichero_son_dos_ficheros(self, var):
        """Nombrar por el contenido ahorraría espacio y ataría dos salas al mismo fichero:
        quitar el plano de una dejaría a la otra apuntando a un hueco."""
        a, _ = media.save(var, PNG)
        b, _ = media.save(var, PNG)
        assert a != b
        assert sorted(media.every(var)) == sorted([a, b])

    @pytest.mark.parametrize('nombre', [
        '../../../etc/passwd', '..\\..\\windows\\system32\\x.png', '/etc/shadow',
        'plano.png', 'PLANO.PNG', '', '.', '..',
        'a1b2c3d4-0000-0000-0000-000000000000.exe',
    ])
    def test_ningun_nombre_de_fuera_es_un_nombre_nuestro(self, nombre):
        assert media.is_name(nombre) is False

    def test_y_por_tanto_no_se_lee(self, var):
        media.save(var, PNG)
        blob, err = media.read(var, '../../../etc/passwd')
        assert blob == b'' and err == 'dcim_media_unknown'

    def test_ni_se_borra(self, var):
        assert media.forget(var, '../../../etc/passwd') is False

    def test_el_tipo_servido_sale_del_nombre_guardado(self, var):
        name, _ = media.save(var, GIF)
        assert media.content_type(name) == 'image/gif'

    def test_y_de_un_nombre_desconocido_no_sale_un_tipo_de_imagen(self):
        assert media.content_type('x.exe') == 'application/octet-stream'


class TestNadaSaleDeLaCarpeta:

    def test_un_nombre_hacia_arriba_no_da_ruta(self, tmp_path):
        base = str(tmp_path / 'media')
        os.makedirs(base)
        assert media.confined(base, '../fuera.png') is None

    def test_uno_de_dentro_si(self, tmp_path):
        base = str(tmp_path / 'media')
        os.makedirs(base)
        path = media.confined(base, 'dentro.png')
        assert path and os.path.dirname(path) == os.path.realpath(base)

    def test_sin_base_no_hay_ruta(self):
        assert media.confined('', 'x.png') is None


class TestElTamanoSeCortaAntesDeLeer:
    """«Leerlo y luego decidir» es como una petición llena un disco."""

    def test_una_imagen_enorme_se_rechaza(self, var):
        big = PNG + b'0' * media.MAX_BYTES
        name, err = media.save(var, big)
        assert name == '' and err == 'dcim_media_too_big'
        assert media.every(var) == []

    def test_y_una_vacia_tambien(self, var):
        assert media.save(var, b'') == ('', 'dcim_media_empty')


class TestLaCarpetaConfigurableManda:
    """El ajuste es `web_admin|dcim_media_dir`, y se pasa DESDE FUERA.

    Este módulo no lee configuración ni conoce Flask, que es lo que permite apuntarlo a un
    directorio temporal en una línea — y lo que hace que la ruta lo lea en cada llamada, para
    que mover la carpeta no exija reiniciar el panel.
    """

    def test_vacia_significa_debajo_de_var_dir(self, var):
        assert media.folder(var) == os.path.join(var, media.FOLDER)

    def test_configurada_gana(self, tmp_path, var):
        otra = str(tmp_path / 'planos')
        assert media.folder(var, otra) == otra

    def test_y_el_fichero_acaba_ahi(self, tmp_path, var):
        otra = str(tmp_path / 'planos')
        name, err = media.save(var, PNG, otra)
        assert not err
        assert os.path.isfile(os.path.join(otra, name))
        assert media.every(var, otra) == [name]

    def test_y_no_en_la_de_por_defecto(self, tmp_path, var):
        otra = str(tmp_path / 'planos')
        media.save(var, PNG, otra)
        assert media.every(var) == []

    def test_leer_sin_decir_la_carpeta_no_encuentra_lo_que_hay_en_la_otra(self, tmp_path, var):
        """El fallo que esto vigila no da error: da un 404 en una instalación donde el fichero
        existe. Una ruta que se olvide de pasar el ajuste se ve así y no de otra forma."""
        otra = str(tmp_path / 'planos')
        name, _ = media.save(var, PNG, otra)
        assert media.read(var, name) == (b'', 'dcim_media_unknown')
        assert media.read(var, name, otra)[0] == PNG

    def test_sin_var_dir_y_sin_ajuste_no_hay_donde(self):
        assert media.folder('') == ''
        assert media.save('', PNG) == ('', 'dcim_media_no_dir')

    def test_pero_con_ajuste_y_sin_var_dir_si(self, tmp_path):
        """Un proceso que no tenga var_dir sigue pudiendo guardar si le han dicho dónde."""
        otra = str(tmp_path / 'planos')
        name, err = media.save('', PNG, otra)
        assert not err and os.path.isfile(os.path.join(otra, name))


class TestOlvidarUno:

    def test_borra_el_fichero(self, var):
        name, _ = media.save(var, PNG)
        assert media.forget(var, name) is True
        assert media.every(var) == []

    def test_olvidar_lo_que_ya_no_esta_no_es_un_error(self, var):
        """Es el estado después de restaurar una base de datos sin sus ficheros: un registro
        que apunta a nada. Que eso reviente no ayuda a nadie."""
        name, _ = media.save(var, PNG)
        media.forget(var, name)
        assert media.forget(var, name) is False


class TestLoQueLaCopiaSeLleva:

    def test_la_lista_solo_trae_lo_nuestro(self, var):
        """Lo que haya caído en la carpeta por otra vía no es una imagen del panel, y una copia
        que se lleve lo que encuentre se lleva lo que alguien dejó ahí."""
        name, _ = media.save(var, PNG)
        with io.open(os.path.join(media.folder(var), 'suelto.txt'), 'w') as fh:
            fh.write('esto no lo puso el panel')
        assert media.every(var) == [name]

    def test_y_una_carpeta_que_no_existe_es_una_lista_vacia(self, tmp_path):
        assert media.every(str(tmp_path / 'no-existe'), str(tmp_path / 'tampoco')) == []


class TestLoQueSeVuelveABajarAparteDeLoQueNo:
    """Mil doscientas imágenes de alzado se recuperan con un botón; la foto que alguien hizo con
    el móvil del armario que montó el electricista, no.

    Compartían carpeta, así que mirarla no decía qué se perdería — ni había forma de guardar lo
    propio sin arrastrar ochocientos megas de biblioteca. Es la misma línea que el catálogo traza
    con `source`, aquí trazada en el disco.
    """

    PNG = bytes.fromhex('89504e470d0a1a0a') + b'0' * 32

    def test_cada_cosa_en_su_cesta(self, tmp_path):
        mia, _ = media.save(str(tmp_path), self.PNG)
        suya, _ = media.save(str(tmp_path), self.PNG, '', 'library')
        assert mia.startswith('own/') and suya.startswith('library/')

    def test_se_puede_pedir_solo_lo_propio(self, tmp_path):
        """Lo que hoy no se podía: guardar lo irremplazable sin lo que se vuelve a bajar."""
        media.save(str(tmp_path), self.PNG)
        media.save(str(tmp_path), self.PNG, '', 'library')
        assert len(media.every(str(tmp_path))) == 2
        assert len(media.every(str(tmp_path), '', 'own')) == 1

    def test_una_cesta_inventada_cae_en_la_propia(self, tmp_path):
        """Un nombre que no es una cesta no crea una carpeta: crearía tantas como veces se
        equivoque quien llama."""
        nombre, _ = media.save(str(tmp_path), self.PNG, '', '../fuera')
        assert nombre.startswith('own/')

    def test_lo_de_antes_de_la_separacion_se_sigue_leyendo(self):
        """Nadie tiene que mover nada para recibir esto: los nombres planos siguen valiendo."""
        assert media.is_name('12345678-1234-1234-1234-123456789012.png')
        assert media.is_name('own/12345678-1234-1234-1234-123456789012.png')
        assert media.is_name('library/12345678-1234-1234-1234-123456789012.bin')

    def test_y_una_cesta_que_no_es_una_cesta_no_es_un_nombre(self):
        assert not media.is_name('etc/12345678-1234-1234-1234-123456789012.png')
        assert not media.is_name('own/../12345678-1234-1234-1234-123456789012.png')

    def test_un_adjunto_se_lee_entero(self, tmp_path):
        """El tope de una imagen son dos megas y un manual son treinta: sin decirlo, lo que
        volvería sería un PDF cortado — que se abre y está roto, y nada lo dice."""
        grande = b'%PDF-1.4' + b'x' * (3 * 1024 * 1024)
        nombre, err = media.keep(str(tmp_path), grande, 8 * 1024 * 1024)
        assert not err
        datos, err = media.read(str(tmp_path), nombre, '', 8 * 1024 * 1024)
        assert not err and len(datos) == len(grande)
