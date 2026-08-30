#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El catálogo de modelos: lo que se guarda de cada uno, y lo que deliberadamente no.

Tres decisiones se fijan aquí, y las tres se toman una vez y se pagan durante años:

* **Se guarda un subconjunto**, no el fichero. Guardarlo entero sería guardar el esquema de otro
  proyecto y obligar a cada lector de aquí a conocerlo.
* **Los puertos se cuentan, no se listan.** Un switch de 48 puertos lista 48 interfaces; cinco
  mil modelos así son un millón de filas que ninguna pantalla lee.
* **Casar un modelo es una propuesta**, nunca una respuesta: `sysDescr` es texto libre, y un
  modelo mal casado mete un equipo de 2U en una U que no da.

Y una que es de seguridad: un zip **no se extrae nunca**. Un zip que nombra `../../etc/algo`
escribe fuera del directorio que se le dijo, y la única defensa fiable es no poner su contenido
en ningún disco. Aquí no hace falta.
"""

from __future__ import annotations

import os
import sys
import time
import zipfile

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim import catalog                                   # noqa: E402
from lib.db import get_connector                                    # noqa: E402

pytestmark = pytest.mark.skipif(catalog._yaml is None,              # noqa: SLF001
                                reason='PyYAML no instalado — el importador se autodesactiva')

SWITCH = """
manufacturer: Dell
model: PowerConnect 2848
slug: dell-powerconnect-2848
u_height: 1
is_full_depth: false
part_number: '2848'
interfaces:
  - {name: gi1, type: 1000base-t}
  - {name: gi2, type: 1000base-t}
  - {name: sfp1, type: 10gbase-x-sfpp}
power-ports:
  - {name: PS1, type: iec-60320-c14}
"""

BLADE = """
manufacturer: HPE
model: BladeSystem c7000
slug: hpe-c7000
u_height: 10
is_full_depth: true
subdevice_role: parent
"""

HALF = """
manufacturer: Ubiquiti
model: EdgeRouter X
slug: ubiquiti-er-x
u_height: 0.5
is_full_depth: false
"""


@pytest.fixture()
def store():
    db = get_connector({'type': 'sqlite', 'path': ':memory:'})
    yield catalog.CatalogStore(db)
    try:
        db.close()
    except Exception:                           # pylint: disable=broad-except
        pass


# ══ Lo que se lee de un fichero ═════════════════════════════════════════════════════════

class TestLoQueSeGuardaDeUnModelo:

    def test_los_cinco_campos_que_hacen_posible_un_alzado(self):
        row = catalog.parse(SWITCH)
        assert row['manufacturer'] == 'Dell'
        assert row['model'] == 'PowerConnect 2848'
        assert row['slug'] == 'dell-powerconnect-2848'
        assert row['u_tenths'] == 10
        assert row['full_depth'] == 0

    def test_media_u_no_se_redondea_sobre_la_de_al_lado(self):
        """Hay un puñado de modelos de 0,5U. Una columna de enteros los apilaría unos sobre
        otros, y el alzado dibujaría dos equipos en el mismo sitio."""
        assert catalog.parse(HALF)['u_tenths'] == 5

    def test_un_chasis_dice_que_es_un_chasis(self):
        """Un alzado que dibuja un c7000 como ocho servidores de 1U se equivoca sobre el
        rack."""
        assert catalog.parse(BLADE)['subdevice'] == 'parent'

    def test_los_puertos_se_cuentan_por_tipo(self):
        assert catalog.parse(SWITCH)['ports'] == {
            'interfaces': {'1000base-t': 2, '10gbase-x-sfpp': 1},
            'power-ports': {'iec-60320-c14': 1}}

    def test_un_puerto_sin_tipo_se_cuenta_igual(self):
        """«Este modelo tiene cuatro algos» vale más para una cuenta de capacidad que el
        silencio, y lo contrario esconde el hueco que tienen los datos de origen."""
        row = catalog.parse('manufacturer: X\nmodel: Y\nu_height: 1\n'
                            'interfaces:\n  - {name: a}\n  - {name: b}\n')
        assert row['ports'] == {'interfaces': {'': 2}}

    def test_lo_que_no_es_un_tipo_de_dispositivo_se_salta(self):
        """La biblioteca también trae tipos de módulo y otras formas. Una fila sin altura es
        una fila que un alzado no puede dibujar y que una búsqueda sí devuelve."""
        assert catalog.parse('manufacturer: X\n') is None          # sin modelo
        assert catalog.parse('model: Y\n') is None                 # sin fabricante
        assert catalog.parse('manufacturer: X\nmodel: Y\nu_height: alto\n') is None
        assert catalog.parse('- una lista\n') is None

    def test_un_fichero_roto_es_un_fichero_y_no_una_importacion_fallida(self):
        assert catalog.parse('esto: [no cierra\n') is None


# ══ Casar lo que dijo el aparato ════════════════════════════════════════════════════════

class TestCasarUnModeloEsUnaPropuesta:

    def test_la_clave_ignora_lo_que_solo_cambia_la_puntuacion(self):
        assert catalog.key('Dell', 'PowerConnect 2848') == \
               catalog.key('dell', 'power-connect  2848')
        assert catalog.key('Dell', 'PowerConnect 2848') != catalog.key('Dell', 'PC 2848')

    def test_lo_que_el_aparato_dijo_encuentra_su_modelo(self, store):
        store.replace('library', [catalog.parse(SWITCH)])
        hit = store.suggest('DELL', 'powerconnect 2848')
        assert hit and hit['model'] == 'PowerConnect 2848'

    def test_y_lo_que_no_esta_no_se_inventa(self, store):
        store.replace('library', [catalog.parse(SWITCH)])
        assert store.suggest('Dell', 'PowerConnect 5548') is None
        assert store.suggest('', '') is None


# ══ La importación ══════════════════════════════════════════════════════════════════════

class TestImportar:

    def test_un_directorio_entra_entero(self, store, tmp_path):
        (tmp_path / 'dell').mkdir()
        (tmp_path / 'dell' / 'sw.yaml').write_text(SWITCH, encoding='utf-8')
        (tmp_path / 'hpe.yml').write_text(BLADE, encoding='utf-8')
        (tmp_path / 'leeme.txt').write_text('no soy un modelo', encoding='utf-8')
        assert store.replace('library', catalog.read_dir(str(tmp_path))) == 2
        assert [m for m, _ in store.makers()] == ['Dell', 'HPE']

    def test_un_zip_tambien_y_sin_extraerlo(self, store, tmp_path):
        """Un zip que nombra `../../etc/algo` escribe fuera del directorio que se le dijo. La
        única defensa fiable es no poner su contenido en ningún disco."""
        path = tmp_path / 'lib.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('device-types/dell/sw.yaml', SWITCH)
            zf.writestr('device-types/hpe/c7000.yaml', BLADE)
            zf.writestr('../../fuera.yaml', HALF)     # …se lee por nombre, no se escribe
            zf.writestr('README.md', '# nada')
        rows = list(catalog.read_zip(str(path)))
        # Dos y no tres: este archivo TIENE la forma de la biblioteca, así que lo que cuelga de
        # `..` no está en ninguno de sus tres árboles y no es un modelo. Que además no se
        # escriba en ningún sitio sigue siendo lo que se vigila aquí.
        assert len(rows) == 2
        assert not (tmp_path.parent.parent / 'fuera.yaml').exists()

    def test_una_entrada_absurdamente_grande_no_es_un_modelo(self, store, tmp_path):
        """El mayor de verdad son unos pocos kilobytes; lo que ocupa medio mega comprimiéndose
        a nada es una bomba, no un tipo de dispositivo."""
        path = tmp_path / 'bomba.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('grande.yaml', 'manufacturer: X\nmodel: Y\nu_height: 1\n'
                                       + '#' * (600 * 1024))
        assert list(catalog.read_zip(str(path))) == []

    def test_reimportar_reemplaza_lo_suyo_y_respeta_lo_tecleado(self, store):
        """Un panel puede tener la biblioteca *y* cuatro modelos que alguien tecleó para equipo
        que nadie ha publicado. Vaciar la tabla se llevaría justo los que no se pueden volver a
        bajar."""
        store.replace('library', [catalog.parse(SWITCH), catalog.parse(BLADE)])
        store.replace('a_mano', [catalog.parse(HALF)])
        store.replace('library', [catalog.parse(SWITCH)])
        assert sorted(r['model'] for r in store.list()) == ['EdgeRouter X',
                                                            'PowerConnect 2848']

    def test_los_puertos_vuelven_como_cuentas_y_no_como_texto(self, store):
        store.replace('library', [catalog.parse(SWITCH)])
        assert store.list()[0]['ports']['interfaces']['1000base-t'] == 2


# ══ Y el trabajo de fondo ═══════════════════════════════════════════════════════════════

class _StoreDeMentira:
    """Lo único que el trabajo le pide a un store: que se trague una lista y diga cuántas."""

    def __init__(self):
        self.calls = []

    def replace(self, source, rows, var_dir='', media_dir='', partial=False):
        rows = list(rows)
        # Dónde guardar las imágenes viaja hasta aquí: el trabajo tiene que pasarlo, y una
        # firma que no lo acepte esconde que se le olvide. Y hasta dónde llega el reemplazo,
        # por lo mismo: es el trabajo quien sabe si se pidieron unos fabricantes o todos.
        self.calls.append((source, len(rows), var_dir, media_dir, partial))
        return len(rows)


class TestElTrabajoDeFondo:
    """Hilo, estado y «solo uno a la vez». El SQL es de `catalog.py` y tiene sus propios tests;
    juntarlos aquí obligaría además a que la BD fuese compartible entre hilos, y una SQLite
    `:memory:` es por conexión — el hilo abriría una base vacía y el test fallaría por algo que
    no ocurre en producción."""

    def _wait(self, jobs, job_id, tries=300):
        for _ in range(tries):
            if (jobs.job_status(job_id) or {}).get('done'):
                return jobs.job_status(job_id)
            time.sleep(0.01)
        return jobs.job_status(job_id)

    def test_importar_es_un_trabajo_que_se_puede_mirar(self, tmp_path):
        from lib.core.dcim import jobs
        (tmp_path / 'sw.yaml').write_text(SWITCH, encoding='utf-8')
        (tmp_path / 'no.txt').write_text('nada', encoding='utf-8')
        store = _StoreDeMentira()
        job_id, err = jobs.start_import(store, 'library', 'dir', str(tmp_path))
        assert err == '' and job_id
        job = self._wait(jobs, job_id)
        assert job['done'] is True and job['error'] == '' and job['count'] == 1
        assert [c[:2] for c in store.calls] == [('library', 1)]

    def test_elegir_fabricantes_hace_la_importacion_parcial(self, tmp_path, monkeypatch):
        """Y no elegirlos, no. Es aquí donde se decidía —sin decirlo— que traerse Dell borraba
        HP: el trabajo llamaba a reemplazar la fuente entera para las dos cosas."""
        from lib.core.dcim import catalog as cat
        from lib.core.dcim import jobs
        monkeypatch.setattr(cat, 'read_remote',
                            lambda *a, **k: [{'manufacturer': 'Dell', 'model': 'R740'}])
        for vendors, parcial in ((['Dell'], True), ([], False)):
            store = _StoreDeMentira()
            job_id, err = jobs.start_import(store, 'library', 'github', 'http://x',
                                            vendors=vendors, paths=[])
            assert err == ''
            self._wait(jobs, job_id)
            assert [c[4] for c in store.calls] == [parcial]

    def test_un_zip_llega_por_el_mismo_camino(self, tmp_path):
        from lib.core.dcim import jobs
        path = tmp_path / 'lib.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('d/sw.yaml', SWITCH)
            zf.writestr('d/c7000.yaml', BLADE)
        store = _StoreDeMentira()
        job_id, err = jobs.start_import(store, 'library', 'zip', str(path))
        assert err == ''
        assert self._wait(jobs, job_id)['count'] == 2

    def test_solo_uno_a_la_vez(self, tmp_path):
        """Dos importaciones a la vez son dos escritores reemplazando las filas del mismo
        origen, y el trabajo del perdedor se pierde en silencio. No hay cola: al segundo se le
        dice que hay una en marcha, que es la verdad y es lo que querría saber."""
        from lib.core.dcim import jobs
        (tmp_path / 'sw.yaml').write_text(SWITCH, encoding='utf-8')

        lento = _StoreDeMentira()
        original = lento.replace

        def _replace(source, rows):
            time.sleep(0.25)                    # …el tiempo de que llegue el segundo
            return original(source, rows)

        lento.replace = _replace
        primero, err = jobs.start_import(lento, 'library', 'dir', str(tmp_path))
        assert err == ''
        segundo, err2 = jobs.start_import(_StoreDeMentira(), 'library', 'dir', str(tmp_path))
        assert segundo == '' and err2 == 'dcim_catalog_busy'
        assert self._wait(jobs, primero)['done'] is True

    def test_y_sale_en_la_pantalla_de_trabajos(self, tmp_path):
        from lib.core.dcim import jobs
        (tmp_path / 'sw.yaml').write_text(SWITCH, encoding='utf-8')
        job_id, _ = jobs.start_import(_StoreDeMentira(), 'library', 'dir', str(tmp_path))
        self._wait(jobs, job_id)
        row = [r for r in jobs.live(None) if r['id'] == job_id][0]
        assert row['kind'] == 'dcim_catalog' and row['state'] == 'done'
        # Sin denominador a propósito: cuántos modelos trae un archivo no se sabe hasta
        # haberlo leído, y una barra que se inventa el total miente sobre lo que falta.
        assert row['total'] == 0

    def test_un_error_de_lectura_termina_el_trabajo_diciendolo(self, tmp_path):
        from lib.core.dcim import jobs
        job_id, err = jobs.start_import(_StoreDeMentira(), 'library', 'zip',
                                        str(tmp_path / 'no-existe.zip'))
        assert err == ''
        assert self._wait(jobs, job_id)['error'] != ''

    def test_lo_privado_del_trabajo_no_sale(self, tmp_path):
        from lib.core.dcim import jobs
        (tmp_path / 'sw.yaml').write_text(SWITCH, encoding='utf-8')
        job_id, _ = jobs.start_import(_StoreDeMentira(), 'library', 'dir', str(tmp_path),
                                      actor='juan')
        self._wait(jobs, job_id)
        assert not any(k.startswith('_') for k in jobs.job_status(job_id))

    def test_un_trabajo_que_no_existe_no_es_un_trabajo_vacio(self):
        from lib.core.dcim import jobs
        assert jobs.job_status('no-existe') is None


class TestLasImagenesVienenConLaBiblioteca:
    """`front_image: true` en el YAML no es una imagen: es la **afirmación de que existe una** —
    y existe, en el mismo repositorio, en `elevation-images/<fabricante>/<slug>.front.png`.

    Estaba delante todo el tiempo: se leía que existía y se tiraba.
    """

    YAML = ('manufacturer: Dell\n'
            'model: PowerConnect 2848\n'
            'slug: dell-powerconnect-2848\n'
            'u_height: 1\n'
            'is_full_depth: true\n'
            'front_image: true\n')

    PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 60

    def _biblioteca(self, tmp_path, con_imagen=True):
        import os
        raiz = tmp_path / 'lib'
        (raiz / 'Dell').mkdir(parents=True)
        (raiz / 'Dell' / 'switch.yaml').write_text(self.YAML, encoding='utf-8')
        if con_imagen:
            img = raiz / 'elevation-images' / 'Dell'
            img.mkdir(parents=True)
            (img / 'dell-powerconnect-2848.front.png').write_bytes(self.PNG)
        return str(raiz)

    def test_se_lee_la_imagen_que_hay_al_lado(self, tmp_path):
        from lib.core.dcim import catalog
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        filas = list(catalog.read_dir(self._biblioteca(tmp_path)))
        assert filas and filas[0]['_images']['front'] == self.PNG

    def test_y_sin_ella_el_modelo_entra_igual(self, tmp_path):
        """Un modelo cuya imagen no se encuentre se queda sin ella, que es como estaba antes.
        Fallar la importación entera por una foto sería cambiar mil modelos por una imagen."""
        from lib.core.dcim import catalog
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        filas = list(catalog.read_dir(self._biblioteca(tmp_path, con_imagen=False)))
        assert filas and filas[0]['_images'] == {}

    def test_no_se_busca_la_que_el_yaml_dice_que_no_hay(self, tmp_path):
        """Probar seis nombres por cara para cada uno de los mil modelos son doce mil
        comprobaciones que casi siempre dicen que no. El YAML ya lo sabe."""
        from lib.core.dcim import catalog
        assert catalog._wants({'front_image': 'true'}, 'front') is True
        assert catalog._wants({'front_image': 'false'}, 'front') is False
        assert catalog._wants({}, 'front') is False

    def test_lo_guardado_es_el_NOMBRE_y_no_la_afirmacion(self, tmp_path, store):
        """Un `true` en la columna no se puede dibujar. Lo que queda es el nombre que acuñó el
        almacén de medios."""
        from lib.core.dcim import catalog, media
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        var = str(tmp_path / 'var')
        filas = list(catalog.read_dir(self._biblioteca(tmp_path)))
        store.replace('library', filas, var)
        guardado = store.list()[0]
        assert media.is_name(guardado['front_image'])
        assert media.read(var, guardado['front_image'])[0] == self.PNG

    def test_reimportar_no_deja_la_carpeta_creciendo(self, tmp_path, store):
        """Cada pocos meses se reimporta la biblioteca. Sin borrar las viejas, la carpeta crece
        durante toda la vida de la instalación con ficheros a los que no apunta nadie."""
        from lib.core.dcim import catalog, media
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        var = str(tmp_path / 'var')
        raiz = self._biblioteca(tmp_path)
        store.replace('library', list(catalog.read_dir(raiz)), var)
        primera = store.list()[0]['front_image']
        store.replace('library', list(catalog.read_dir(raiz)), var)
        segunda = store.list()[0]['front_image']
        assert primera != segunda
        assert media.every(var) == [segunda], 'la de la importación anterior se quedó'


# ══ De GitHub, sin bajarse GitHub ═══════════════════════════════════════════════════════
#
# El primer intento se traía el repositorio entero como un zip, que es lo que hacen las MIB.
# Funciona mientras un repositorio sean treinta megas; este pesa ochocientos cincuenta porque
# lleva una imagen de alzado por aparato, y pulsar «ver qué hay» arrancaba una descarga de casi
# un giga que el tope cortaba — y lo único que llegaba a la pantalla era «Error».
#
# Lo que se prueba aquí es lo que lo sustituye: el índice contesta la pregunta sin descargar
# nada, y al importar se piden solo los ficheros elegidos.


class TestTresCosasYNoUna:
    """El repositorio trae aparatos, módulos y armarios, y son la misma forma con tres sentidos.

    Sin distinguirlos, un transceptor ocupa U en un alzado y un armario de 42U figura como un
    equipo de 42U. Y las imágenes de módulo viven en `module-images/` y se nombran por el modelo,
    no en `elevation-images/` por el slug: buscarlas donde no están es no encontrar ninguna.
    """

    RACK = ('manufacturer: APC\nmodel: AR3100\nslug: apc-ar3100\nu_height: 42\n'
            'form_factor: 4-post-cabinet\nouter_width: 600\nouter_depth: 1070\n'
            'outer_unit: mm\nmax_weight: 1020\nweight_unit: kg\n')
    MODULO = 'manufacturer: Cisco\nmodel: A9K-2X100GE\npart_number: A9K-2X100GE\n'

    def _zip(self, tmp_path):
        import zipfile
        ruta = str(tmp_path / 'biblioteca.zip')
        png = b'\x89PNG\r\n\x1a\n'
        with zipfile.ZipFile(ruta, 'w') as zf:
            zf.writestr('lib-master/', '')                     # la entrada del envoltorio
            zf.writestr('lib-master/device-types/HP/DL380.yaml',
                        'manufacturer: HP\nmodel: DL380\nslug: dl380\nu_height: 2\n'
                        'front_image: true\n')
            zf.writestr('lib-master/rack-types/APC/AR3100.yaml', self.RACK)
            zf.writestr('lib-master/module-types/Cisco/A9K.yaml', self.MODULO)
            zf.writestr('lib-master/elevation-images/HP/dl380.front.png', png)
            zf.writestr('lib-master/module-images/Cisco/A9K-2X100GE.front.png', png)
            zf.writestr('lib-master/tests/algo.yaml', 'manufacturer: X\nmodel: Y\n')
            zf.writestr('lib-master/README.md', '# nada')
        return ruta

    def test_cada_uno_entra_como_lo_que_es(self, tmp_path):
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        filas = {f['model']: f for f in catalog.read_zip(self._zip(tmp_path))}
        assert filas['DL380']['_tree'] == 'device-types'
        assert filas['AR3100']['_tree'] == 'rack-types'
        assert filas['A9K-2X100GE']['_tree'] == 'module-types'

    def test_lo_que_no_esta_en_ninguno_de_los_tres_no_es_un_modelo(self, tmp_path):
        """Los tests del propio repositorio son YAML con `manufacturer` y `model`, y entraban
        como aparatos: filas que nadie puso ahí y nadie sabe qué son."""
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        assert 'Y' not in {f['model'] for f in catalog.read_zip(self._zip(tmp_path))}

    def test_la_imagen_de_un_modulo_esta_en_OTRA_carpeta_y_con_OTRO_nombre(self, tmp_path):
        """`module-images/<Fabricante>/<modelo>.front.png`. Y el YAML de un módulo no dice que
        tenga imagen —no trae ese campo— así que preguntárselo es no buscarla nunca."""
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        filas = {f['model']: f for f in catalog.read_zip(self._zip(tmp_path))}
        assert filas['A9K-2X100GE']['_images'].get('front')
        assert filas['DL380']['_images'].get('front'), 'y la del aparato sigue en la suya'

    def test_la_imagen_se_llama_como_el_FICHERO_y_no_como_el_modelo(self, tmp_path):
        """`Check Point / CPAC-2-100/25F` es un modelo con una barra dentro, y una barra en un
        nombre de fichero es una carpeta: el repositorio la cambia por un guion. Deducir el
        nombre del fichero desde el modelo obliga a copiar esa regla ajena aquí y a acertar
        también la siguiente — y el nombre del fichero ya se sabe, es el que se acaba de leer.
        """
        import zipfile
        ruta = str(tmp_path / 'barras.zip')
        png = b'\x89PNG\r\n\x1a\n'
        with zipfile.ZipFile(ruta, 'w') as zf:
            zf.writestr('module-types/CP/CPAC-2-100-25F.yaml',
                        'manufacturer: CP\nmodel: CPAC-2-100/25F\n')
            zf.writestr('module-images/CP/CPAC-2-100-25F.front.png', png)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        fila = list(catalog.read_zip(ruta))[0]
        assert fila['_images'].get('front') == png

    def test_de_un_armario_se_guarda_lo_que_solo_tiene_un_armario(self, tmp_path):
        """Sus medidas contestan si cabe donde se quiere poner, y el peso máximo si aguanta lo
        que se le va a meter: dos preguntas que se hacen antes de comprar."""
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        rack = [f for f in catalog.read_zip(self._zip(tmp_path))
                if f['_tree'] == 'rack-types'][0]
        assert rack['u_tenths'] == 420
        assert rack['extra']['outer_depth'] == 1070
        assert rack['extra']['max_weight'] == 1020

    def test_y_eso_sobrevive_a_guardarlo_y_leerlo(self, tmp_path, store):
        """La columna guarda texto. Serializado en un sitio y leído en otro sin deshacer, lo que
        sale es una cadena con llaves que ninguna pantalla puede pintar."""
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        store.replace('library', catalog.read_zip(self._zip(tmp_path)))
        rack = [r for r in store.list() if r['tree'] == 'rack-types'][0]
        assert rack['extra']['outer_width'] == 600

    def test_un_zip_SIN_la_forma_de_la_biblioteca_sigue_entrando_entero(self, tmp_path):
        """La otra puerta que esto atiende: el zip que alguien prepara a mano, que es una carpeta
        plana de YAML porque nadie se inventa `device-types/<Fabricante>/` para catorce ficheros
        propios. Exigirle la forma de la biblioteca lo dejaría fuera."""
        import zipfile
        ruta = str(tmp_path / 'mio.zip')
        with zipfile.ZipFile(ruta, 'w') as zf:
            zf.writestr('sw.yaml', SWITCH)
            zf.writestr('c7000.yaml', BLADE)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        filas = list(catalog.read_zip(ruta))
        assert len(filas) == 2
        assert {f['_tree'] for f in filas} == {'device-types'}


class TestLosBasicosVienenDentro:
    """Un catálogo mínimo dentro del panel, para la primera tarde y para la sala sin internet."""

    def test_traen_de_las_tres_cosas(self):
        import collections
        from lib.core.dcim import basics
        c = collections.Counter(r['_tree'] for r in basics.rows())
        assert c['rack-types'] and c['device-types'] and c['module-types']

    def test_salen_de_un_json_y_no_del_codigo(self):
        """Son datos: los tamaños de armario que se fabrican, las formas que se repiten en
        cualquier sala, las plataformas que todo el mundo teclea. Añadir «Ubuntu 28.04 LTS» o el
        armario de 45U no puede ser publicar una versión, y quien sabe qué falta casi nunca es
        quien toca el código."""
        import json
        from lib.core.dcim import basics
        with open(basics.FILE, encoding='utf-8') as fh:
            doc = json.load(fh)
        assert doc['version'] and doc['racks'] and doc['devices'] and doc['platforms']
        assert len(basics.rows()) == (len(doc['racks']) + len(doc['devices'])
                                      + len(doc['modules']))

    def test_un_fichero_roto_deja_la_seccion_en_pie(self, monkeypatch):
        """Con el catálogo entero detrás, romper la lista de genéricos no puede impedir mirar un
        modelo: salen cero y el botón no trae nada."""
        from lib.core.dcim import basics
        monkeypatch.setattr(basics, '_CACHE', None)
        monkeypatch.setattr(basics, 'FILE', 'no/existe.json')
        assert basics.rows() == [] and basics.platforms() == []
        monkeypatch.setattr(basics, '_CACHE', None)      # y el siguiente lo vuelve a leer bien

    def test_las_ediciones_de_windows_son_plataformas_distintas(self):
        """Una `Enterprise LTSC` y una `Pro` no se actualizan igual ni se acaban el mismo día:
        son dos plataformas y no una con un matiz."""
        from lib.core.dcim import basics
        nombres = [p['name'] for p in basics.platforms()]
        assert 'Windows 11 Pro' in nombres and 'Windows 11 Enterprise LTSC' in nombres
        assert 'Windows Server 2016 Standard' in nombres
        assert 'Windows Server 2025 Datacenter' in nombres
        assert 'Ubuntu 26.04 LTS' in nombres

    def test_las_plataformas_traen_las_fechas_publicadas(self):
        """Las que el fabricante publica, que son la mitad del valor de tenerlas dadas de alta:
        un Windows 10 sin parches desde octubre de 2025 tiene que salir en rojo el día que se
        mira, no el día que alguien se acuerde de escribirlo."""
        from lib.core.dcim import basics
        por_nombre = {p['name']: p for p in basics.platforms()}
        assert por_nombre['Windows 10 Pro']['extra']['eol'] == '2025-10-14'
        assert por_nombre['Windows Server 2019 Standard']['extra']['launched']
        assert por_nombre['Debian 12']['extra']['end_of_security']

    def test_y_donde_no_hay_UNA_fecha_no_se_inventa_ninguna(self):
        """El canal anual de Windows 11 marca una por versión —23H2, 24H2…— y poner la de una
        como si fuera la del producto es exactamente la fecha que alguien se cree. Se deja vacía
        y se dice por qué, que es lo único honesto que se puede hacer ahí."""
        from lib.core.dcim import basics
        por_nombre = {p['name']: p for p in basics.platforms()}
        w11 = por_nombre['Windows 11 Pro']
        assert not w11['extra'].get('eol') and w11['notes']
        # Y la LTSC, que sí tiene una sola, la trae.
        assert por_nombre['Windows 11 Enterprise LTSC']['extra']['eol']

    def test_cada_una_dice_de_qué_familia_es(self):
        """Es lo que agrupa la lista: Microsoft → Windows 11 → Pro, Home, Enterprise. Veintiséis
        renglones planos son veintiséis renglones planos."""
        from lib.core.dcim import basics
        por_nombre = {p['name']: p for p in basics.platforms()}
        assert por_nombre['Windows 11 Pro']['family'] == 'Windows 11'
        assert por_nombre['Windows Server 2022 Standard']['family'] == 'Windows Server 2022'
        assert por_nombre['Debian 12']['family'] == 'Debian'
        assert all(p.get('family') for p in basics.platforms())

    def test_lo_que_se_acaba_en_dos_pasos_lleva_las_dos_fechas(self):
        """Casi todo se acaba dos veces: primero deja de recibir lo que no es seguridad y
        después deja de recibir nada. Con una sola fecha hay que elegir cuál se apunta, y quien
        la lea seis meses después no sabrá cuál se eligió."""
        from lib.core.dcim import basics
        por_nombre = {p['name']: p for p in basics.platforms()}
        srv = por_nombre['Windows Server 2019 Standard']['extra']
        assert srv['end_of_maintenance'] == '2024-01-09' and srv['eol'] == '2029-01-09'
        esxi = por_nombre['VMware ESXi 7.0']['extra']
        assert esxi['end_of_maintenance'] < esxi['eol'], 'el soporte general acaba antes'
        ub = por_nombre['Ubuntu 22.04 LTS']['extra']
        assert ub['end_of_security'] < ub['eol'], 'ESM va después del mantenimiento'

    def test_la_mayoria_trae_su_fin_de_soporte(self):
        """Es la mitad del valor de tenerlas dadas de alta: un ESXi 6.7 sin guía técnica desde
        2023 tiene que salir en rojo el día que se mira."""
        from lib.core.dcim import basics
        con = [p for p in basics.platforms() if (p.get('extra') or {}).get('eol')]
        assert len(con) > len(basics.platforms()) * 2 / 3

    def test_y_lo_que_no_tiene_una_fecha_lo_dice(self):
        """DSM la marca por modelo y no por versión, y el canal anual de Windows 11 por versión
        y no por producto. Ahí no hay una fecha que poner, y poner la de un caso como si fuera
        la del producto es exactamente la que alguien se cree."""
        from lib.core.dcim import basics
        for p in basics.platforms():
            if not (p.get('extra') or {}).get('eol'):
                assert p.get('notes'), f"{p['name']} no dice por qué no tiene fecha"

    def test_no_todo_lo_que_corre_en_una_caja_es_un_sistema_de_servidor(self):
        """Un router corre firmware, un nodo de virtualización un hipervisor y un NAS lo suyo.
        Meterlos todos en «sistema operativo» sería no poder preguntar qué hay de cada cosa."""
        from lib.core.dcim import basics
        por_nombre = {p['name']: p for p in basics.platforms()}
        assert por_nombre['RouterOS 7']['kind'] == 'firmware'
        assert por_nombre['Proxmox VE 8']['kind'] == 'hypervisor'
        assert por_nombre['VMware ESXi 8.0']['kind'] == 'hypervisor'
        assert por_nombre['Synology DSM 7.2']['kind'] == 'appliance'

    def test_los_textos_hablan_los_dos_idiomas(self):
        """Lo que sale de aquí se COPIA a una fila y se queda: un nombre en castellano en un
        panel en inglés no se arregla cambiando de idioma después, hay que volver a sembrar."""
        from lib.core.dcim import basics
        es = {r['slug']: r['model'] for r in basics.rows('es_ES')}
        en = {r['slug']: r['model'] for r in basics.rows('en_EN')}
        assert es['generic-1u-cantilever-shelf'] == 'Bandeja voladiza 1U'
        assert en['generic-1u-cantilever-shelf'] == '1U cantilever shelf'
        nota = [p for p in basics.platforms('es_ES') if p['name'] == 'Debian 12'][0]['notes']
        assert 'Debian LTS' in nota and 'equipo de seguridad' in nota

    def test_el_slug_no_cambia_con_el_idioma(self):
        """Es la identidad de la fila. Uno que cambiara con el idioma de quien pulsó el botón
        haría que sembrar dos veces en dos idiomas creara dos catálogos."""
        from lib.core.dcim import basics
        assert {r['slug'] for r in basics.rows('es_ES')} ==                {r['slug'] for r in basics.rows('en_EN')}

    def test_un_texto_sin_ese_idioma_sale_en_otro_y_no_en_blanco(self):
        """Un texto es peor en otro idioma y mucho peor si no está."""
        from lib.core.dcim import basics
        assert basics._text({'en_EN': 'only English'}, 'es_ES') == 'only English'
        assert basics._text({'zz': 'suelto'}, 'es_ES') == 'suelto'
        assert basics._text('una cadena de siempre', 'es_ES') == 'una cadena de siempre'
        assert basics._text(None, 'es_ES') == ''

    def test_el_fichero_se_relee_cuando_cambia(self, tmp_path, monkeypatch):
        """Se edita para añadir una plataforma, que es para lo que se sacó del código. Guardarlo
        para siempre en memoria convertiría «editar un JSON» en «editar un JSON y reiniciar el
        panel», con la trampa de que lo segundo no está escrito en ninguna parte."""
        import json
        from lib.core.dcim import basics
        ruta = tmp_path / 'basics.json'
        ruta.write_text(json.dumps({'version': 1, 'platforms': [{'name': 'Una'}]}),
                        encoding='utf-8')
        monkeypatch.setattr(basics, 'FILE', str(ruta))
        monkeypatch.setattr(basics, '_CACHE', None)
        monkeypatch.setattr(basics, '_SEEN', ())
        assert [p['name'] for p in basics.platforms()] == ['Una']
        ruta.write_text(json.dumps({'version': 2,
                                    'platforms': [{'name': 'Una'}, {'name': 'Otra'}]}),
                        encoding='utf-8')
        # `mtime` tiene la resolución que tenga; el tamaño ha cambiado, que es la otra mitad
        # de la firma y por lo que son dos y no una.
        assert [p['name'] for p in basics.platforms()] == ['Una', 'Otra']

    def test_cada_llamada_devuelve_los_suyos(self):
        """`replace` escribe sobre lo que le pasan —le añade `uid`, origen y fecha— así que
        devolver siempre la misma lista dejaría que la primera importación ensuciara la
        segunda."""
        from lib.core.dcim import basics
        a, b = basics.rows(), basics.rows()
        a[0]['model'] = 'tocado'
        assert b[0]['model'] != 'tocado'

    def test_las_bandejas_no_son_todas_la_misma(self, store):
        """Una **voladiza** se atornilla solo por delante y no llega al fondo; una **fija de
        cuatro puntos** va de delante atrás. No es un nombre: `full_depth` decide si el dibujo la
        pinta ocupando el fondo y si lo que va detrás cabe."""
        from lib.core.dcim import basics
        # Por SLUG y no por nombre: el nombre se traduce y el slug es la identidad. Una prueba
        # que busca «Bandeja voladiza 1U» deja de encontrar nada en un panel en inglés.
        por_slug = {r['slug']: r for r in basics.rows()}
        assert por_slug['generic-1u-cantilever-shelf']['full_depth'] == 0
        assert por_slug['generic-1u-fixed-shelf-4-post'].get('full_depth', 1) == 1

    def test_hay_un_SAI_de_cada_altura_que_se_monta(self, store):
        """El de 1U es el que se pone cuando lo que hay que proteger es un switch y no una
        sala."""
        from lib.core.dcim import basics
        sais = [r for r in basics.rows() if r.get('kind') == 'ups']
        assert sorted(r['u_tenths'] for r in sais) == [10, 20, 30]

    def test_el_papel_de_cada_uno_se_deduce_de_sus_puertos(self):
        """El catálogo no guarda el rol —lo decide quien coloca— pero SÍ lo sugiere, y un
        genérico sin puertos saldría sin sugerencia y habría que elegírselo a mano cada vez."""
        from lib.core.dcim import basics
        por_slug = {r['slug']: r for r in basics.rows()}
        regleta = por_slug['generic-8-outlet-power-strip']
        panel = por_slug['generic-24-port-patch-panel']
        assert regleta['ports']['power-outlets'] and not regleta['ports'].get('interfaces')
        assert panel['is_powered'] == 0 and panel['ports']['front-ports']

    def test_entran_con_su_propia_etiqueta(self, store):
        """Con la de la biblioteca, reimportar una se llevaría la otra por delante."""
        from lib.core.dcim import basics
        store.replace('library', [{'manufacturer': 'HP', 'model': 'DL380'}])
        store.replace(basics.SOURCE, basics.rows())
        assert store.count('source = ?', ('library',)) == 1
        assert store.count('source = ?', (basics.SOURCE,)) == basics.count()


class TestQueEsCadaModelo:
    """La columna «Tipo» salía vacía en media tabla.

    Y con razón: la deducción solo miraba puertos de red y tomas de corriente, así que una fuente
    de alimentación —un módulo con `power-ports: 1` y nada más— no encajaba en ninguna regla y
    salía sin nada. Ni siquiera «módulo», que es lo que es y se sabía desde que se importó.
    """

    def test_una_fuente_es_una_fuente_y_no_un_hueco(self):
        """`FS-600-PSU-1200`, del catálogo de Fortinet, y las cuatro que salían en blanco."""
        for modelo in ('FS-600-PSU-1200', 'FS-PSU-300', 'SP-FG1240B-PS', 'SP-FG300E-PS'):
            fila = {'_tree': 'module-types', 'model': modelo,
                    'ports': {'power-ports': {'': 1}}}
            assert catalog.kind_of(fila) == 'psu', modelo

    def test_un_transceptor_se_reconoce_por_como_se_llama(self):
        """Un módulo no declara puertos —una óptica no tiene puertos que contar— así que la
        única señal que queda es su nombre. Es una heurística y solo se usa donde la alternativa
        es no decir nada en absoluto."""
        assert catalog.kind_of({'_tree': 'module-types', 'model': 'SFP-10G-LR'}) == 'transceiver'
        assert catalog.kind_of({'_tree': 'module-types', 'model': 'QSFP28-100G'}) == 'transceiver'

    def test_lo_que_no_se_reconoce_es_un_modulo_y_no_un_hueco(self):
        assert catalog.kind_of({'_tree': 'module-types', 'model': 'ABC-123'}) == 'module'

    def test_un_armario_lo_dice_el_arbol_del_que_vino(self):
        """Sin adivinar nada: el repositorio ya lo separó."""
        assert catalog.kind_of({'_tree': 'rack-types', 'model': 'AR3100'}) == 'rack'

    def test_las_señales_de_un_aparato_son_las_de_siempre(self):
        assert catalog.kind_of({'ports': {'power-outlets': {'c13': 8}}}) == 'pdu'
        assert catalog.kind_of({'ports': {'front-ports': {'8p8c': 24},
                                          'rear-ports': {'8p8c': 24}},
                                'is_powered': 0}) == 'patch_panel'
        assert catalog.kind_of({'ports': {'interfaces': {'1g': 48}}}) == 'switch'
        assert catalog.kind_of({'ports': {'interfaces': {'1g': 2}}}) == 'server'
        assert catalog.kind_of({'ports': {'device-bays': {'': 8}}}) == 'server'

    def test_un_SAI_no_es_una_regleta(self):
        """Las dos reparten corriente con las mismas señales: tomas y ninguna interfaz. Lo único
        que las separa es el nombre — y `ups` era una opción del filtro que no encontraba nunca
        nada. No se sustituyen igual: cuando un SAI se apaga, lo que cuelga de él sigue con luz.
        """
        tomas = {'power-outlets': {'c13': 8}}
        assert catalog.kind_of({'model': 'Smart-UPS 1500', 'ports': tomas}) == 'ups'
        assert catalog.kind_of({'model': 'SAI 2U', 'ports': tomas}) == 'ups'
        assert catalog.kind_of({'model': 'Rack PDU 2G', 'ports': tomas}) == 'pdu'

    def test_y_la_regla_del_nombre_es_estrecha_a_proposito(self):
        """Solo donde ya se había decidido «regleta», y solo con la palabra suelta. Una lista de
        palabras acierta más casos y falla de formas que nadie prevé — y lo que sale de aquí se
        enseña como si se supiera."""
        # `upstream` lleva «ups» dentro y no es un SAI.
        assert catalog.kind_of({'model': 'Upstream 24',
                                'ports': {'power-outlets': {'c13': 8}}}) == 'pdu'
        # Y con interfaces no es ninguna de las dos, se llame como se llame.
        assert catalog.kind_of({'model': 'UPS Manager',
                                'ports': {'interfaces': {'1g': 24}}}) == 'switch'

    def test_lo_que_la_fila_DICE_que_es_manda_sobre_la_deduccion(self, store):
        """Deducir es lo que se hace cuando nadie lo ha dicho. Cuando alguien lo dice —un
        genérico del panel, una fila escrita a mano— deducir es contradecirle."""
        store.replace('core', [{'manufacturer': 'Genérico', 'model': 'SAI 2U',
                                'ports': {'power-outlets': {'c13': 8}}, 'kind': 'ups'}])
        fila = store.list()[0]
        assert fila['kind'] == 'ups' and fila['kind_set'] == 1

    def test_pero_una_clase_inventada_no_se_cuela(self, store):
        """El vocabulario es cerrado: una clase que solo existe en una fila sale en un filtro
        que nadie puede volver a elegir."""
        store.replace('core', [{'manufacturer': 'X', 'model': 'Y',
                                'ports': {'interfaces': {'1g': 48}}, 'kind': 'inventada'}])
        assert store.list()[0]['kind'] == 'switch'

    def test_una_caja_sin_puertos_y_sin_alimentar_es_una_bandeja(self):
        assert catalog.kind_of({'ports': {}, 'is_powered': 0}) == 'shelf'

    def test_los_puertos_valen_igual_venga_como_texto_o_como_diccionario(self):
        """De la base de datos salen como JSON. Fiarse de que siempre llegue deshecho es la
        forma de que una de las dos llamadas devuelva `other` sin decir por qué."""
        assert catalog.kind_of({'ports': '{"interfaces": {"1g": 48}}'}) == 'switch'

    def test_se_guarda_al_importar_y_se_puede_contar(self, store):
        """Calculado al leer serían ocho mil quinientas veces por página, y el filtro no podría
        preguntárselo a la base de datos."""
        store.replace('library', [
            {'manufacturer': 'X', 'model': 'SW', 'ports': {'interfaces': {'1g': 48}}},
            {'manufacturer': 'X', 'model': 'PDU', 'ports': {'power-outlets': {'c13': 8}}},
            {'manufacturer': 'X', 'model': 'SFP+', '_tree': 'module-types'},
        ])
        assert dict(store.kinds()) == {'switch': 1, 'pdu': 1, 'transceiver': 1}
        assert [r['model'] for r in store.list('kind = ?', ('pdu',))] == ['PDU']

    def test_la_rejilla_de_marcas_obedece_al_filtro_que_ensena(self, store):
        """Una lista de fabricantes con el tipo puesto en «switch» que siguiera contando sus
        impresoras diría una cosa y enseñaría otra — y las marcas sin ningún switch sobrarían
        enteras."""
        store.replace('library', [
            {'manufacturer': 'A', 'model': 'SW', 'ports': {'interfaces': {'1g': 48}}},
            {'manufacturer': 'A', 'model': 'PDU', 'ports': {'power-outlets': {'c13': 8}}},
            {'manufacturer': 'B', 'model': 'PDU2', 'ports': {'power-outlets': {'c13': 8}}},
        ])
        assert dict(store.makers()) == {'A': 2, 'B': 1}
        assert dict(store.makers('kind = ?', ('switch',))) == {'A': 1}

    def test_lo_importado_ANTES_de_que_existiera_la_columna_se_clasifica_solo(self, store):
        """`ADD COLUMN` no puede inventarse el valor, así que quien ya tenía el catálogo vería
        «Sin clasificar» en las ocho mil quinientas filas y un filtro que no filtra. Y nadie
        vuelve a descargar ochocientos cincuenta megas para que salga una palabra."""
        store.replace('library', [
            {'manufacturer': 'X', 'model': 'SW', 'ports': {'interfaces': {'1g': 48}}}])
        store._db.execute("UPDATE dc_type SET kind = ''")
        store._db.commit()
        assert store.backfill_kinds() == 1
        assert store.list()[0]['kind'] == 'switch'

    def test_y_no_hace_nada_cuando_no_queda_ninguna(self, store):
        """Una vez, no en cada arranque: la pregunta previa es un `COUNT` que contesta cero."""
        store.replace('library', [{'manufacturer': 'X', 'model': 'SW'}])
        assert store.backfill_kinds() == 0


class TestCorregirLoQueLaReglaNoAcierta:
    """`N9K-PAC-650W-B` es una fuente y sale como «Otro».

    La regla mira los puertos, y una fuente declara un `power-ports` y nada más — lo mismo que
    media docena de cosas distintas. No hay regla que acierte ocho mil quinientos casos, y quien
    mira la fila lo sabe en un segundo. Lo que faltaba era poder decirlo… y que lo dicho no se
    perdiera en la siguiente importación, que es donde esto se convierte en una función que
    engaña en vez de una que sirve.
    """

    def _una(self, store, kind_esperado='other'):
        store.replace('library', [{'manufacturer': 'Cisco', 'model': 'N9K-PAC-650W-B',
                                   'ports': {'power-ports': {'': 1}}}])
        fila = store.list()[0]
        assert fila['kind'] == kind_esperado
        return fila

    def test_se_puede_decir_lo_que_es(self, store):
        fila = self._una(store)
        assert store.update(fila['uid'], {'kind': 'psu'})
        assert store.list()[0]['kind'] == 'psu'

    def test_y_queda_marcado_como_decidido_por_alguien(self, store):
        """Sin la marca no hay forma de distinguir lo deducido de lo corregido, y reimportar
        obligaría a elegir entre perder todas las correcciones o no actualizar nunca."""
        fila = self._una(store)
        store.update(fila['uid'], {'kind': 'psu'})
        assert store.list()[0]['kind_set'] == 1

    def test_LA_CORRECCION_SOBREVIVE_A_REIMPORTAR(self, store):
        """La trampa entera de esta función: `replace` borra las filas del origen y mete las
        nuevas, así que actualizar la biblioteca se llevaría por delante cuarenta correcciones
        hechas en marzo — en silencio y meses después, cuando nadie se acuerda de que corrigió.
        """
        fila = self._una(store)
        store.update(fila['uid'], {'kind': 'psu'})
        # La misma biblioteca, otra vez, con la fila tal como viene del repositorio.
        store.replace('library', [{'manufacturer': 'Cisco', 'model': 'N9K-PAC-650W-B',
                                   'ports': {'power-ports': {'': 1}}}])
        assert store.list()[0]['kind'] == 'psu', 'la corrección se perdió al reimportar'
        assert store.list()[0]['kind_set'] == 1

    def test_pero_lo_DEDUCIDO_sigue_actualizandose(self, store):
        """Se rescata lo que decidió una persona, no la fila entera: el resto es del
        repositorio, y congelarlo sería no volver a recibir una corrección suya nunca."""
        store.replace('library', [{'manufacturer': 'X', 'model': 'SW',
                                   'ports': {'interfaces': {'1g': 2}}}])
        assert store.list()[0]['kind'] == 'server'
        store.replace('library', [{'manufacturer': 'X', 'model': 'SW',
                                   'ports': {'interfaces': {'1g': 48}}}])
        assert store.list()[0]['kind'] == 'switch'

    def test_una_correccion_de_OTRO_origen_no_se_cruza(self, store):
        """Cada origen rescata lo suyo. Cruzarlos haría que corregir en la biblioteca cambiara
        un modelo escrito a mano que se llama igual."""
        store.replace('library', [{'manufacturer': 'X', 'model': 'A',
                                   'ports': {'power-ports': {'': 1}}}])
        store.update(store.list()[0]['uid'], {'kind': 'psu'})
        store.replace('core', [{'manufacturer': 'X', 'model': 'A',
                                'ports': {'power-ports': {'': 1}}}])
        mio = [r for r in store.list() if r['source'] == 'core'][0]
        assert mio['kind'] == 'other', 'se cruzó la corrección de otro origen'


class TestEscribirUnModeloAMano:
    """Para lo que no está en ninguna biblioteca."""

    def test_se_crea_con_su_propio_origen(self, store):
        """Ninguna importación lo toca: lo que alguien escribió porque no existe en ningún
        repositorio no puede desaparecer al actualizar el repositorio."""
        uid = store.create({'manufacturer': 'Taller', 'model': 'Armario a medida',
                            'tree': 'rack-types', 'u_tenths': 300})
        assert uid
        fila = store.get(uid)
        assert fila['source'] == 'manual' and fila['tree'] == 'rack-types'
        store.replace('library', [{'manufacturer': 'X', 'model': 'Y'}])
        assert store.get(uid), 'una importación se llevó lo escrito a mano'

    def test_se_guarda_todo_lo_que_el_formulario_puede_decir(self, store):
        """Los esquemas de la biblioteca dicen qué tiene un modelo, y el formulario los sigue:
        un armario sin sus medidas no contesta si cabe donde se quiere poner, y un switch sin
        puertos no sirve para una cuenta de capacidad."""
        uid = store.create({
            'manufacturer': 'Taller', 'model': 'AR a medida', 'tree': 'rack-types',
            'kind': 'rack', 'u_tenths': 420, 'description': 'El del pasillo, 42U',
            'ports': {'power-outlets': {'': 8}},
            'extra': {'form_factor': '4-post-cabinet', 'outer_depth': 1000, 'max_weight': 800},
        })
        fila = store.get(uid)
        assert fila['description'] == 'El del pasillo, 42U'
        assert fila['extra']['outer_depth'] == 1000 and fila['extra']['max_weight'] == 800
        assert fila['ports']['power-outlets'][''] == 8

    def test_la_descripcion_llega_de_la_biblioteca(self):
        """«APC NetShelter SX, 42U, 1991H x 600W x 1070D mm»: es donde está el «42U» que alguien
        escribe en el buscador de un armario que se llama `AR1300`."""
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        fila = catalog.parse('manufacturer: APC\nmodel: AR1300\nu_height: 42\n'
                             'description: APC NetShelter SX, 42U\n')
        assert fila['description'] == 'APC NetShelter SX, 42U'

    def test_sin_fabricante_o_sin_modelo_no_hay_fila(self, store):
        """Una fila sin nombre no se puede buscar ni elegir: es una que estorba y no sirve."""
        assert store.create({'manufacturer': '', 'model': 'X'}) == ''
        assert store.create({'manufacturer': 'X', 'model': '   '}) == ''

    def test_lo_escrito_a_mano_nace_decidido(self, store):
        """Si alguien lo escribió, lo escribió a propósito: la clase no es una deducción."""
        uid = store.create({'manufacturer': 'Taller', 'model': 'Cacharro', 'kind': 'shelf'})
        assert store.get(uid)['kind'] == 'shelf'
        assert store.get(uid)['kind_set'] == 1

    def test_corregir_el_nombre_rehace_la_clave_de_correspondencia(self, store):
        """`match_key` es lo que casa un aparato con su modelo. Dejarlo viejo rompe esa
        correspondencia sin decir nada."""
        uid = store.create({'manufacturer': 'A', 'model': 'Uno'})
        store.update(uid, {'model': 'Dos'})
        assert store.get(uid)['match_key'] == catalog.key('A', 'Dos')

    def test_una_peticion_no_puede_reescribir_de_donde_vino_algo(self, store):
        """`source`, `uid` y la fecha son del almacén. Aceptarlos de fuera sería dejar que una
        petición dijera que un modelo suyo vino de la biblioteca."""
        uid = store.create({'manufacturer': 'A', 'model': 'B'})
        store.update(uid, {'source': 'library', 'uid': 'otro'})
        assert store.get(uid)['source'] == 'manual'


class TestElOrdenAlfabeticoLoEsDeVerdad:
    """`ghipsystems` salía detrás de `Zyxel`.

    `ORDER BY manufacturer` ordena por el valor del carácter: la `Z` es el 90 y la `a` el 97, así
    que todo lo que empieza en minúscula cae detrás de la Z entera — al final de trescientos
    treinta y seis nombres, que es donde nadie lo busca. Y no falla nada: la lista está ordenada,
    solo que por un criterio que no es el que se lee.
    """

    def _lleno(self, store):
        store.replace('library', [
            {'manufacturer': 'Zyxel', 'model': 'A'},
            {'manufacturer': 'ghipsystems', 'model': 'B'},
            {'manufacturer': 'Arista', 'model': 'C'},
            {'manufacturer': 'i-PRO', 'model': 'D'},
        ])

    def test_las_minusculas_no_van_detras_de_la_zeta(self, store):
        self._lleno(store)
        assert [m[0] for m in store.makers()] == ['Arista', 'ghipsystems', 'i-PRO', 'Zyxel']

    def test_y_el_listado_sigue_el_mismo_orden(self, store):
        """Dos ordenaciones distintas para la misma tabla son dos listas que no se parecen."""
        self._lleno(store)
        assert [r['manufacturer'] for r in store.list()] ==             ['Arista', 'ghipsystems', 'i-PRO', 'Zyxel']


class TestElIndiceContestaSinDescargar:
    """Cuántos modelos hay por fabricante lo dicen los NOMBRES de los ficheros."""

    RUTAS = [
        'README.md',
        'schema/devicetype.json',
        'device-types/HP/DL380-Gen10.yaml',
        'device-types/HP/DL360-Gen10.yml',
        'device-types/Eaton/5PX1500iRT.yaml',
        'module-types/HP/562SFP.yaml',
        'device-types/README.md',                    # no es un modelo
        'device-types/suelto.yaml',                  # sin fabricante: tampoco
        'elevation-images/HP/dl380-gen10.front.png',
    ]

    def _falso(self, monkeypatch, rutas=None, err=''):
        from lib.core.dcim import catalog
        datos = self.RUTAS if rutas is None else rutas
        monkeypatch.setattr(catalog.gh, 'list_tree', lambda url, token='': (datos, err))
        return catalog

    def test_los_fabricantes_salen_del_indice(self, monkeypatch):
        catalog = self._falso(monkeypatch)
        d = catalog.browse()
        assert d['error'] == ''
        assert [v['name'] for v in d['vendors']] == ['Eaton', 'HP']

    def test_se_cuentan_aparatos_y_modulos_por_separado(self, monkeypatch):
        """Un transceptor y un servidor son la misma forma con dos significados. Sumarlos haría
        que el fabricante pareciera traer tres aparatos cuando trae dos y una tarjeta."""
        catalog = self._falso(monkeypatch)
        hp = [v for v in catalog.browse()['vendors'] if v['name'] == 'HP'][0]
        assert (hp['device_types'], hp['module_types']) == (2, 1)

    def test_lo_que_no_es_un_modelo_no_cuenta(self, monkeypatch):
        """El README, el esquema y la imagen están en el mismo índice. Contarlos inventaría
        fabricantes que no existen."""
        catalog = self._falso(monkeypatch)
        nombres = [v['name'] for v in catalog.browse()['vendors']]
        assert 'schema' not in nombres and 'elevation-images' not in nombres

    def test_el_indice_viaja_para_que_nadie_lo_pida_dos_veces(self, monkeypatch):
        """Mirar y luego importar son la misma pregunta. La segunda gasta de las sesenta
        peticiones por hora que hay sin credencial."""
        catalog = self._falso(monkeypatch)
        assert catalog.browse()['paths'] == self.RUTAS

    def test_un_fallo_sale_tal_cual_y_no_como_una_lista_vacia(self, monkeypatch):
        """«No hay fabricantes» y «no se pudo preguntar» son dos cosas, y la pantalla las dice
        distinto: una es un repositorio raro, la otra una rama mal escrita."""
        catalog = self._falso(monkeypatch, rutas=[], err='not_found')
        d = catalog.browse()
        assert d['error'] == 'not_found' and d['vendors'] == []


class TestSoloSeTraeLoElegido:
    """Traer un fabricante son sus modelos. Traerlos todos son ochocientos cincuenta megas."""

    YAML = ('manufacturer: HP\nmodel: DL380 Gen10\nslug: dl380-gen10\nu_height: 2\n'
            'front_image: true\n')

    def _falso(self, monkeypatch, rutas, ficheros):
        from lib.core.dcim import catalog

        def _many(url, paths, max_bytes=0, timeout=30):
            for p in paths:
                yield p, ficheros.get(p), ('' if p in ficheros else 'not_found')

        monkeypatch.setattr(catalog.gh, 'fetch_many', _many)
        monkeypatch.setattr(catalog.gh, 'list_tree', lambda url, token='': (rutas, ''))
        return catalog

    def _biblioteca(self):
        return {'device-types/HP/DL380-Gen10.yaml': self.YAML.encode('utf-8'),
                'device-types/Eaton/5PX.yaml': b'manufacturer: Eaton\nmodel: 5PX\n',
                'elevation-images/HP/dl380-gen10.front.png': b'\x89PNG\r\n\x1a\n'}

    def test_un_fabricante_no_arrastra_a_los_otros(self, monkeypatch):
        ficheros = self._biblioteca()
        catalog = self._falso(monkeypatch, list(ficheros), ficheros)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        filas = list(catalog.read_remote(vendors=['HP'], paths=list(ficheros)))
        assert [f['manufacturer'] for f in filas] == ['HP']

    def test_la_imagen_llega_con_el_modelo(self, monkeypatch):
        """El YAML dice `front_image: true`, que no se puede dibujar. Lo que hay que traer es el
        fichero que está en otra carpeta, y su nombre se deduce del `slug`."""
        ficheros = self._biblioteca()
        catalog = self._falso(monkeypatch, list(ficheros), ficheros)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        fila = list(catalog.read_remote(vendors=['HP'], paths=list(ficheros)))[0]
        assert fila['_images']['front'].startswith(b'\x89PNG')

    def test_sin_fabricantes_se_traen_todos(self, monkeypatch):
        """La pantalla obliga a elegir; esto no, porque una importación programada no tiene a
        quién preguntar."""
        ficheros = self._biblioteca()
        catalog = self._falso(monkeypatch, list(ficheros), ficheros)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        filas = list(catalog.read_remote(paths=list(ficheros)))
        assert sorted(f['manufacturer'] for f in filas) == ['Eaton', 'HP']

    def test_demasiados_ficheros_se_para_antes_de_empezar(self, monkeypatch):
        """Cada fichero es una petición. Seis mil seguidas son media hora y una forma muy
        educada de que a uno lo bloqueen."""
        from lib.core.dcim import catalog as _c
        rutas = ['device-types/HP/m%d.yaml' % i for i in range(_c.MAX_FILES + 1)]
        catalog = self._falso(monkeypatch, rutas, {})
        with pytest.raises(RuntimeError, match='too_many'):
            list(catalog.read_remote(paths=rutas))

    def test_un_modelo_roto_no_se_lleva_por_delante_la_importacion(self, monkeypatch):
        """Son miles de ficheros de un repositorio ajeno. Uno que no baja no puede costar los
        otros cinco mil novecientos noventa y nueve."""
        ficheros = self._biblioteca()
        rutas = list(ficheros) + ['device-types/HP/no-esta.yaml']
        catalog = self._falso(monkeypatch, rutas, ficheros)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        filas = list(catalog.read_remote(vendors=['HP'], paths=rutas))
        assert [f['model'] for f in filas] == ['DL380 Gen10']

    def test_va_diciendo_por_donde_va_mientras_lo_hace(self, monkeypatch):
        """La pantalla decía «0 modelos leídos» durante todo el trabajo.

        Y era verdad: las filas no salen de aquí hasta el final —hay una segunda pasada de por
        medio— así que quien contara lo entregado contaba cero justo mientras duraba todo. El
        aviso va por FICHERO PEDIDO, que es lo que está pasando, y lleva la fase: bajar los
        modelos y bajar sus imágenes son dos trabajos seguidos de duración muy distinta, y una
        sola barra para los dos se queda parada a la mitad sin explicar por qué.
        """
        ficheros = self._biblioteca()
        catalog = self._falso(monkeypatch, list(ficheros), ficheros)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        visto = []
        list(catalog.read_remote(vendors=['HP'], paths=list(ficheros),
                                 on_progress=lambda h, t, f: visto.append((f, h, t))))
        # Lo PRIMERO que pasa es pedir el índice, y tarda: sin decirlo, ese rato se ve como un
        # cero que parece colgado — que es exactamente lo que se venía a arreglar.
        assert visto[0] == ('index', 0, 0), 'pedir el índice no se contaba y es lo primero'
        assert ('models', 1, 1) in visto, 'y luego cada modelo, mientras se pide'
        assert ('images', 1, 1) in visto, 'las imágenes tienen su propia fase y su propio total'

    def test_se_distingue_un_aparato_de_un_modulo(self, monkeypatch):
        """Sin `_tree`, un transceptor entraría como algo que ocupa U en un alzado."""
        ficheros = {'module-types/HP/562SFP.yaml': b'manufacturer: HP\nmodel: 562SFP\n'}
        catalog = self._falso(monkeypatch, list(ficheros), ficheros)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        fila = list(catalog.read_remote(paths=list(ficheros)))[0]
        assert fila['_tree'] == 'module-types'


class TestTraerloTodoEsOtroCamino:
    """Diez mil ochocientos ficheros de uno en uno son tres cuartos de hora.

    El mismo contenido en un zip baja en poco más de un minuto, así que para «todos» el archivo
    entero es lo barato — y para tres fabricantes es exactamente al revés. Las dos existen porque
    elegir una sola para los dos casos es bajar un giga para importar un fabricante, o pasar tres
    cuartos de hora pidiendo ficheros para importarlos todos.
    """

    def _zip(self, tmp_path):
        import zipfile
        ruta = str(tmp_path / 'biblioteca.zip')
        with zipfile.ZipFile(ruta, 'w') as zf:
            zf.writestr('devicetype-library-master/device-types/HP/DL380.yaml',
                        'manufacturer: HP\nmodel: DL380\nslug: dl380\nu_height: 2\n')
            zf.writestr('devicetype-library-master/device-types/Eaton/5PX.yaml',
                        'manufacturer: Eaton\nmodel: 5PX\n')
        return ruta

    def _falso(self, monkeypatch, ruta, err=''):
        """`download` devuelve ese archivo, sin salir a internet. Anota si lo borraron."""
        from lib.core.dcim import catalog
        borrados = []
        monkeypatch.setattr(catalog.gh, 'download',
                            lambda url, mx, prog=None, cache='', fresh=False:
                            ((None, err, False) if err else (ruta, '', False)))
        monkeypatch.setattr(catalog.gh, '_rm_quiet', borrados.append)
        return catalog, borrados

    def test_salen_todos_los_modelos_del_archivo(self, tmp_path, monkeypatch):
        catalog, _ = self._falso(monkeypatch, self._zip(tmp_path))
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        filas = list(catalog.read_whole())
        assert sorted(f['manufacturer'] for f in filas) == ['Eaton', 'HP']

    def test_el_archivo_se_borra_al_acabar(self, tmp_path, monkeypatch):
        """Ochocientos cincuenta megas no son una caché que ahorre una descarga dentro de seis
        meses: son un disco lleno esperando a que nadie se acuerde. Ya pasó con las MIB."""
        ruta = self._zip(tmp_path)
        catalog, borrados = self._falso(monkeypatch, ruta)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        list(catalog.read_whole())
        assert borrados == [ruta]

    def test_y_tambien_si_la_lectura_revienta(self, tmp_path, monkeypatch):
        """El borrado va en un `finally` por esto: un archivo corrupto que no se borra deja el
        giga puesto justo en el caso en que alguien va a volver a intentarlo."""
        ruta = str(tmp_path / 'roto.zip')
        with open(ruta, 'wb') as fh:
            fh.write(b'esto no es un zip')
        catalog, borrados = self._falso(monkeypatch, ruta)
        with pytest.raises(Exception):
            list(catalog.read_whole())
        assert borrados == [ruta]

    def test_una_descarga_fallida_se_dice_y_no_se_lee_nada(self, tmp_path, monkeypatch):
        catalog, borrados = self._falso(monkeypatch, '', err='rate_limited')
        with pytest.raises(RuntimeError, match='rate_limited'):
            list(catalog.read_whole())
        assert borrados == [], 'no había nada que borrar'

    def test_una_url_que_no_es_un_repositorio_se_para_antes_de_bajar(self, monkeypatch):
        from lib.core.dcim import catalog
        with pytest.raises(RuntimeError, match='bad_url'):
            list(catalog.read_whole('https://example.com/x'))

    def test_las_imagenes_sobreviven_al_envoltorio_de_github(self, tmp_path, monkeypatch):
        """8361 modelos importados y ninguno con imagen, sin un solo error.

        GitHub envuelve el repositorio en una carpeta con su nombre y su rama, y una imagen se
        busca por `elevation-images/<Fabricante>/…`. Con el envoltorio puesto los dos nombres son
        correctos y distintos, y buscar en un diccionario devuelve `None` sin decir por qué.
        """
        import zipfile
        ruta = str(tmp_path / 'con-envoltorio.zip')
        png = b'\x89PNG\r\n\x1a\n'
        with zipfile.ZipFile(ruta, 'w') as zf:
            zf.writestr('devicetype-library-master/device-types/HP/DL380.yaml',
                        'manufacturer: HP\nmodel: DL380\nslug: dl380\nfront_image: true\n')
            zf.writestr('devicetype-library-master/elevation-images/HP/dl380.front.png', png)
        catalog, _ = self._falso(monkeypatch, ruta)
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        fila = list(catalog.read_whole())[0]
        assert fila['_images'].get('front') == png, 'el envoltorio se comió la imagen'

    def test_va_diciendo_que_esta_descargando(self, tmp_path, monkeypatch):
        """Ochocientos cincuenta megas son minutos. Sin decir nada, son minutos de pantalla
        quieta — que es lo que hace pensar que se ha colgado."""
        catalog, _ = self._falso(monkeypatch, self._zip(tmp_path))
        if catalog._yaml is None:
            pytest.skip('sin PyYAML')
        visto = []
        list(catalog.read_whole(on_progress=lambda h, t, f: visto.append(f)))
        assert visto[0] == 'download' and 'models' in visto
# ══ Y hasta dónde llega ═════════════════════════════════════════════════════════════════

class TestImportarUnaMarcaNoBorraLasDemas:
    """Una importación reemplaza lo que cubría, y nada más.

    Bajarse la biblioteca entera SÍ borra lo que ya no está arriba: eso es lo que significa
    «entera». Marcar tres fabricantes en la pantalla no dice nada de los otros trescientos, y
    borrarlos era leer un silencio como una afirmación — el catálogo se quedaba con la última
    marca que alguien pidió y las anteriores desaparecían sin que nada lo contara.
    """

    PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 60

    def _tres(self, store):
        store.replace('library', [
            {'manufacturer': 'Dell', 'model': 'R740', 'u_tenths': 20},
            {'manufacturer': 'HP', 'model': 'DL380', 'u_tenths': 20},
            {'manufacturer': 'Cisco', 'model': 'C9300', 'u_tenths': 10},
        ])

    def _marcas(self, store):
        return sorted(m for m, _ in store.makers())

    def test_traerse_una_deja_las_otras_donde_estaban(self, store):
        self._tres(store)
        store.replace('library', [{'manufacturer': 'Dell', 'model': 'R750', 'u_tenths': 20}],
                      partial=True)
        assert self._marcas(store) == ['Cisco', 'Dell', 'HP']

    def test_y_la_suya_si_se_reemplaza(self, store):
        """Reemplazar es reemplazar: el modelo viejo de esa marca se va, y no se queda al lado
        del nuevo. Sumar sin borrar dejaría un catálogo que solo crece."""
        self._tres(store)
        store.replace('library', [{'manufacturer': 'Dell', 'model': 'R750', 'u_tenths': 20}],
                      partial=True)
        dell = [r['model'] for r in store.list() if r['manufacturer'] == 'Dell']
        assert dell == ['R750']

    def test_dos_veces_lo_mismo_no_lo_duplica(self, store):
        self._tres(store)
        for _ in range(2):
            store.replace('library', [{'manufacturer': 'Dell', 'model': 'R750',
                                       'u_tenths': 20}], partial=True)
        assert len([r for r in store.list() if r['manufacturer'] == 'Dell']) == 1

    def test_el_nombre_se_reconoce_aunque_se_escriba_distinto(self, store):
        """`HP`, `H.P.` y `hp` son la misma casa escrita por tres personas: si el alcance no lo
        supiera, pedir `hp` metería un segundo HP al lado del primero."""
        self._tres(store)
        store.replace('library', [{'manufacturer': 'H.P.', 'model': 'DL360', 'u_tenths': 10}],
                      partial=True)
        assert [r['model'] for r in store.list() if r['manufacturer'] == 'H.P.'] == ['DL360']
        assert not [r for r in store.list() if r['model'] == 'DL380']

    def test_una_descarga_que_no_trae_nada_no_vacia_el_catalogo(self, store):
        """Pedir Dell y que no baje ni un fichero es una descarga fallida, no un fabricante que
        ha dejado de publicar. Borrar ahí sería castigar un corte de red."""
        self._tres(store)
        store.replace('library', [], partial=True)
        assert self._marcas(store) == ['Cisco', 'Dell', 'HP']

    def test_la_marca_que_llego_es_la_que_manda(self, store):
        """El fabricante de la CARPETA y el del YAML no siempre coinciden — se marca `Dell` y
        baja una fila que se declara `HP`. Manda lo que dice la fila: si entra, lo que había de
        esa marca es lo viejo, o quedarían las dos versiones del mismo modelo."""
        self._tres(store)
        store.replace('library', [{'manufacturer': 'HP', 'model': 'DL560', 'u_tenths': 40}],
                      partial=True)
        assert [r['model'] for r in store.list() if r['manufacturer'] == 'HP'] == ['DL560']
        assert [r['model'] for r in store.list() if r['manufacturer'] == 'Dell'] == ['R740']

    def test_bajarse_la_biblioteca_entera_si_borra_lo_que_ya_no_esta(self, store):
        """La otra mitad de la regla, y la que se rompería sola: sin `only`, un modelo retirado
        arriba tiene que irse de aquí."""
        self._tres(store)
        store.replace('library', [{'manufacturer': 'Dell', 'model': 'R750', 'u_tenths': 20}])
        assert self._marcas(store) == ['Dell']

    def test_lo_tecleado_a_mano_no_lo_toca_ninguna_de_las_dos(self, store):
        self._tres(store)
        store.create({'manufacturer': 'Acme', 'model': 'Caja', 'u_tenths': 10})
        store.replace('library', [{'manufacturer': 'Dell', 'model': 'R750', 'u_tenths': 20}],
                      partial=True)
        store.replace('library', [{'manufacturer': 'Dell', 'model': 'R750', 'u_tenths': 20}])
        assert [r['model'] for r in store.list() if r['manufacturer'] == 'Acme'] == ['Caja']

    def test_no_se_lleva_por_delante_las_imagenes_de_las_que_no_toca(self, tmp_path, store):
        """Y esta es la que no da error: la fila sobrevive, el fichero no, y el alzado queda en
        blanco meses después sin que nada lo relacione con aquella importación."""
        from lib.core.dcim import media
        var = str(tmp_path)
        store.replace('library', [
            {'manufacturer': 'Dell', 'model': 'R740', 'u_tenths': 20,
             '_images': {'front': self.PNG}},
            {'manufacturer': 'HP', 'model': 'DL380', 'u_tenths': 20,
             '_images': {'front': self.PNG}},
        ], var)
        de_hp = [r['front_image'] for r in store.list() if r['manufacturer'] == 'HP'][0]
        assert de_hp, 'no se guardó la imagen, así que el test no prueba nada'
        store.replace('library', [{'manufacturer': 'Dell', 'model': 'R750', 'u_tenths': 20}],
                      var, partial=True)
        datos, err = media.read(var, de_hp)
        assert not err and datos == self.PNG
# ══ Por dónde come ══════════════════════════════════════════════════════════════════════

class TestPorDondeComeSeDeduce:
    """La biblioteca no trae «alimentación» con ese nombre, pero trae la respuesta.

    Una toma `dc-terminal` es la entrada de un ladrón que va fuera de la caja: hay que
    llevárselo al mudar el equipo y no está atornillado a nada. Una `iec-60320-c14` es corriente
    de pared, y eso solo entra en un equipo que lleva la fuente dentro. Y un `poe_mode: pd` sin
    ninguna toma es un equipo que come por el cable de red — ese no gasta enchufe en la regleta,
    lo gasta el switch.
    """

    #: El mini-PC que lo destapó: dice su puerto de red y dice su alimentador, y el panel no
    #: enseñaba ninguna de las dos cosas.
    MINI = ('manufacturer: HP\n'
            'model: EliteDesk 800 G5 Mini\n'
            'u_height: 1\n'
            'interfaces:\n'
            '  - name: ethernet-1/1\n'
            '    type: 1000base-t\n'
            'power-ports:\n'
            '  - name: External Power Supply\n'
            '    type: dc-terminal\n')

    def test_una_toma_de_continua_es_un_ladron_fuera_de_la_caja(self):
        assert catalog.parse(self.MINI)['power_type'] == 'external'

    def test_y_su_puerto_de_red_se_cuenta(self):
        """El otro medio agujero: el YAML lo decía y el resumen enseñaba solo la tarjeta que
        alguien le añadió."""
        assert catalog.parse(self.MINI)['ports']['interfaces'] == {'1000base-t': 1}

    def test_una_toma_de_pared_es_una_fuente_dentro(self):
        doc = ('manufacturer: Dell\nmodel: R740\nu_height: 2\n'
               'power-ports:\n  - name: PSU1\n    type: iec-60320-c14\n'
               '  - name: PSU2\n    type: iec-60320-c14\n')
        assert catalog.parse(doc)['power_type'] == 'internal'

    def test_comer_por_el_cable_de_red_no_gasta_enchufe(self):
        doc = ('manufacturer: Cisco\nmodel: 8841\nu_height: 1\n'
               'interfaces:\n  - name: eth0\n    type: 100base-tx\n    poe_mode: pd\n')
        assert catalog.parse(doc)['power_type'] == 'poe'

    def test_el_que_da_corriente_por_el_cable_no_es_el_que_la_recibe(self):
        """`pse` es el switch que alimenta, y ese sí gasta enchufe. Confundirlos contaría un
        armario entero de menos."""
        doc = ('manufacturer: Cisco\nmodel: C9300\nu_height: 1\n'
               'interfaces:\n  - name: gi1/0/1\n    type: 1000base-t\n    poe_mode: pse\n')
        assert catalog.parse(doc)['power_type'] == ''

    def test_no_decir_nada_no_es_decir_que_no_se_alimenta(self):
        """Vacío es «quien subió el fichero no rellenó esa parte». Que no se alimente lo dice
        `is_powered`, que es otra pregunta y tiene otra respuesta."""
        fila = catalog.parse('manufacturer: X\nmodel: Y\nu_height: 1\n')
        assert fila['power_type'] == '' and fila['is_powered'] == 1

    def test_lo_ya_importado_se_deduce_de_lo_que_quedo_contado(self, store):
        """Ocho mil modelos entraron antes de que existiera la columna. Volver a bajarse la
        biblioteca para rellenarla serían ochocientos cincuenta megas por un dato que ya está
        guardado: las claves de `ports` SON los tipos de toma."""
        store.replace('library', [catalog.parse(self.MINI)])
        uid = store.list()[0]['uid']
        store._db.execute(f"UPDATE {store._sql_table} SET power_type = '' WHERE uid = ?",
                          (uid,))
        store._db.commit()
        assert store.backfill_power() == 1
        assert store.get(uid)['power_type'] == 'external'
        assert store.backfill_power() == 0, 'se hace una vez, no en cada arranque'


class TestLosPuertosSeCuentanYSeNombran:
    """Dos preguntas y dos respuestas.

    Contar es lo que se mira para decidir si el switch sirve, y por eso un modelo guarda un
    recuento y no cuarenta y ocho filas. Nombrar es lo que se mira con el latiguillo en la mano:
    `gi1` es lo que sale en la configuración del equipo y lo que va en la etiqueta. La biblioteca
    trae las dos y se estaba tirando la segunda.
    """

    def test_los_nombres_salen_del_documento(self):
        doc = {'interfaces': [{'name': 'gi1', 'type': '1000base-t'},
                              {'name': 'gi2', 'type': '1000base-t'},
                              {'name': 'te1', 'type': '1000base-x-sfp'}]}
        lista = catalog._port_list(doc)                          # noqa: SLF001
        assert [p['name'] for p in lista['interfaces']] == ['gi1', 'gi2', 'te1']
        assert lista['interfaces'][2]['type'] == '1000base-x-sfp'

    def test_en_su_orden_y_no_ordenados(self):
        """`gi10` va después de `gi9` en el panel y antes en el alfabeto, y una lista que no sale
        en el orden del frontal no sirve para encontrar la boca que se está mirando."""
        doc = {'interfaces': [{'name': f'gi{i}'} for i in (9, 10, 11)]}
        lista = catalog._port_list(doc)                          # noqa: SLF001
        assert [p['name'] for p in lista['interfaces']] == ['gi9', 'gi10', 'gi11']

    def test_sin_nombre_no_hay_entrada(self):
        """Lo que se guarda aquí es el nombre: una lista de guiones no dice nada que el recuento
        no diga mejor."""
        doc = {'interfaces': [{'type': '1000base-t'}, {'name': 'gi1'}]}
        assert len(catalog._port_list(doc)['interfaces']) == 1   # noqa: SLF001

    def test_el_recuento_no_se_toca(self):
        """Sigue contando lo que no nombra: un documento sin nombres tiene que seguir diciendo
        cuántas bocas hay."""
        doc = {'interfaces': [{'type': '1000base-t'} for _ in range(48)]}
        assert catalog._ports(doc)['interfaces']['1000base-t'] == 48   # noqa: SLF001
        assert catalog._port_list(doc) == {}                     # noqa: SLF001

    def test_hay_un_tope_y_el_recuento_no_lo_tiene(self):
        """El tope está para que un documento raro no meta cien mil entradas en una columna. Lo
        que se pierde entonces es el detalle, nunca el recuento."""
        doc = {'interfaces': [{'name': f'gi{i}', 'type': '1000base-t'}
                              for i in range(catalog.PORT_LIST_MAX + 50)]}
        assert len(catalog._port_list(doc)['interfaces']) == catalog.PORT_LIST_MAX  # noqa: SLF001
        assert (catalog._ports(doc)['interfaces']['1000base-t']                     # noqa: SLF001
                == catalog.PORT_LIST_MAX + 50)

    def test_se_guarda_y_se_lee_como_diccionario(self, store):
        """La columna guarda texto y quien la lea espera una lista: deshacerlo en el único sitio
        por el que sale una fila es lo que evita que una pantalla reciba una cadena."""
        uid = store.create({'manufacturer': 'Linksys', 'model': 'LGS528',
                            'port_list': {'interfaces': [{'name': 'gi1',
                                                          'type': '1000base-t'}]}})
        assert store.get(uid)['port_list']['interfaces'][0]['name'] == 'gi1'


class TestUnArmarioNoEsUnPanelDeParcheo:
    """Las clases de `KINDS` son las de las cosas que van DENTRO de un armario. Ofrecérselas a un
    armario deja escribir «armario que es un panel de parcheo», que no es un dato raro sino uno
    imposible — y quien lo escribe no está describiendo su armario: se ha equivocado de rama, y
    esa casilla era lo único que se lo podía decir.
    """

    def test_la_rama_de_los_armarios_no_ofrece_ninguna(self):
        from lib.core.dcim import catalog
        assert catalog.kinds_for('rack-types') == ()

    def test_pero_las_demas_siguen_teniendo_la_suya(self):
        from lib.core.dcim import catalog
        from lib.core.dcim.store import PART_KINDS
        assert catalog.kinds_for('device-types') == catalog.KINDS
        assert catalog.kinds_for('module-types') == catalog.KINDS
        assert catalog.kinds_for(catalog.COMPONENT_TREE) == PART_KINDS

    def test_un_armario_ya_dice_su_forma_por_otro_sitio(self):
        """`form_factor` es lo que aquí sería la clase, y está donde debe."""
        from lib.core.dcim import catalog
        assert 'form_factor' in catalog._RACK_FIELDS
