#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La sección de empresas: su cableado, y que su lista sea **la tabla del panel**.

Una sección de este panel no es un fichero: es una entrada en un registro (que le da URL, ruta,
puerta de permiso y sitio en la barra), un panel donde dibujarse, su JavaScript en el guion, y una
función de dibujado cuyo nombre el registro nombra. Falta la entrada y no hay URL; falta el panel
y la sección se abre sobre nada; falta el guion y la barra ofrece una sección cuya función no está
definida. Las cuatro fallan en silencio.

Y la otra mitad, que es la de esta pantalla en concreto: **la lista es la del panel**. Empezó
siendo tres disposiciones escritas a mano, con su propio cambiador, su edición dentro de la fila y
su propio marcado de lo obligatorio. Funcionaba, y estaba mal: `createListTable` ya trae el
esqueleto, la cabecera, el filtro, la paginación, las columnas ordenables, elegibles y
recordadas por usuario, y la columna de acciones. Una lista que se lo salta se ve distinta de las
otras diez y no aprende nada de lo que se arregle en ellas.

Lo que se dibuja de verdad se comprueba **ejecutándolo**, en
`tests/integration/test_wa_orgs_page.py`. Esto es lo otro: que esté declarado y enchufado.
"""

from __future__ import annotations

import io
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
PKG = os.path.join(SRC, 'lib', 'core', 'orgs')
UI = os.path.join(PKG, 'web', '_ui.html')
MODAL = os.path.join(PKG, 'web', '_modals.html')
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()


def _vistas() -> str:
    """El registro de vistas, sin las líneas comentadas.

    Comentar una vista deja su texto escrito en el fichero, así que una guarda que busque la
    cadena la da por viva y la vista desaparece de la pantalla sin que nadie lo diga. Salió al
    comprobar esta guarda por mutación.
    """
    js = _read(UI)
    bloque = js.split('const ORG_VIEWS = [')[1].split('];')[0]
    return chr(10).join(l for l in bloque.splitlines()
                        if not l.strip().startswith('//'))


def _spec() -> str:
    """La declaración que se le pasa a la tabla compartida, del `(` al `});` que la cierra."""
    js = _read(UI)
    i = js.index('createListTable({')
    return js[i:js.index('\n});', i)]


class TestLaSeccionExiste:

    def test_la_declara_su_propio_paquete(self):
        """Y no `constants.py`: una página del core se declara sola (`PAGE` en su manifiesto),
        que es lo que permite que este paquete se lleve su pantalla consigo."""
        m = _read(os.path.join(PKG, 'manifest.py'))
        assert "'id': 'orgs'" in m and "'render': 'renderOrgsPage'" in m
        assert "'perm': 'orgs_view'" in m, 'la sección no está tras su permiso'
        assert "'i18n': 'orgs_page'" in m, 'el título no sale del catálogo del core'

    def test_y_su_guion_dibuja_lo_que_el_registro_nombra(self):
        assert 'function renderOrgsPage(' in _read(UI)

    def test_y_pinta_dentro_del_panel_que_le_dan(self):
        """El contenedor lo pone el armazón a partir del `id` de la sección; escribir `#orgs` a
        mano aquí sería una sección que dibuja en un sitio que el registro puede mover."""
        js = _read(UI)
        cuerpo = js.split('async function renderOrgsPage(')[1].split('\n}')[0]
        assert "'-container'" in cuerpo and 'SS_STANDALONE_PAGES' in cuerpo


class TestLaListaEsLaDelPanel:

    def test_se_arma_con_la_tabla_compartida(self):
        js = _read(UI)
        assert 'createListTable({' in js, 'vuelve a tener una tabla escrita a mano'
        assert '<table' not in js, 'dibuja una tabla por su cuenta'
        assert '<thead' not in js

    def test_y_declara_lo_que_una_tabla_declara(self):
        spec = _spec()
        for campo in ('key:', 'containerId:', 'columns:', 'rows:', 'cell:', 'actions:',
                      'sortValue:', 'state:', 'globalPrefix:'):
            assert campo in spec, campo

    def test_y_trae_las_columnas_de_siempre(self):
        """`uid`, creado, modificado y por quién: las mismas cuatro que toda lista de entidades,
        tomadas del sitio donde están escritas una vez."""
        js = _read(UI)
        assert '_META_COL.uid' in js and '..._META_TAIL' in js

    def test_y_se_recuerda_por_usuario(self):
        """Qué columnas, en qué orden y de qué ancho es una preferencia de lectura, y el panel ya
        sabe guardarla: una lista que no la guarda es la única que se recoloca sola cada mañana."""
        spec = _spec()
        assert 'persist: true' in spec
        assert 'clearLabelKey:' in spec, 'la lista no se puede nombrar en Personalización'

    def test_y_el_cambiador_de_vista_es_el_del_panel(self):
        """Tres vistas —tabla, tarjetas y ficha—, con el mismo control que usan grupos, sesiones
        y el cableado."""
        js = _read(UI)
        assert 'createViewState(' in js
        assert "_orgView.switcher('setOrgsView')" in js
        spec = _spec()
        assert 'bodyMode:' in spec and 'cardsBody:' in spec
        vistas = _vistas()
        for vista in ("id: 'table'", "id: 'card'", "id: 'record'"):
            assert vista in vistas, vista

    def test_y_el_cuerpo_de_cada_vista_lo_despacha_el_registro(self):
        """Y no una llamada fija a las tarjetas: son tres, y dos de ellas no son tarjetas — con
        `cardsBody` llamando siempre a lo mismo, la ficha existe y no se dibuja nunca. La caza
        esta guarda porque las que ejecutan la ficha la llaman por su nombre, y esa la dibuja
        igual. Encontrado comprobándolo por mutación."""
        assert '_orgView.body(' in _spec(), 'la vista abierta no decide qué se pinta'

    def test_y_la_que_declara_un_dibujado_lo_tiene_escrito(self):
        """El registro despacha POR NOMBRE, así que un nombre mal escrito es una vista que se
        elige y deja la lista en blanco, sin ningún error."""
        js = _read(UI)
        # Sólo el registro de vistas: el `render` de `globalPrefix` es el nombre con el que la
        # tabla compartida PUBLICA el suyo, y ese no está escrito aquí — mirarlo también haría
        # fallar esta guarda por algo que está bien.
        import re as _re                                            # noqa: PLC0415
        nombres = _re.findall(r"render: '([^']+)'", _vistas())
        assert nombres, 'ninguna vista declara con qué se dibuja'
        for nombre in nombres:
            assert f'function {nombre}(' in js, nombre

    def test_y_lo_que_se_filtra_se_filtra_donde_toca(self):
        """En el navegador: son las sociedades de un grupo, media docena, no un catálogo de
        miles — un viaje al servidor por cada letra tecleada es una lista a tirones."""
        spec = _spec()
        assert 'filters:' in spec and 'match:' in spec
        assert '/api/v1/orgs?' not in _read(UI), 'pide al servidor por cada letra'


class TestCorregirVaEnUnCuadro:
    """Como un grupo, un rol o una credencial. Una fila convertida en cajas de texto tiene el
    ancho de su columna, y aquí hay una descripción que no cabe en ninguna."""

    def test_el_paquete_trae_su_cuadro(self):
        assert os.path.isfile(MODAL), 'la pantalla edita sin tener dónde'
        html = _read(MODAL)
        assert 'id="orgModal"' in html and 'id="btnOrgModalOk"' in html

    def test_y_pide_las_dos_cosas_sin_las_que_no_hay_empresa(self):
        """Declaradas `required`, que es lo que mira el marcador del panel. Pintarlas en rojo no
        es cosa de esta pantalla: una regla escrita dos veces son dos reglas."""
        html = _read(MODAL)
        for campo in ('id="omName"', 'id="omShort"'):
            etiqueta = html[html.rindex('<', 0, html.index(campo)):
                            html.index('>', html.index(campo)) + 1]
            assert 'required' in etiqueta, campo
        # …y la descripción no: se rellena un mes después, si es que se rellena.
        desc = html[html.rindex('<', 0, html.index('id="omDescription"')):
                    html.index('>', html.index('id="omDescription"')) + 1]
        assert 'required' not in desc

    def test_y_no_toca_la_lista_hasta_que_el_servidor_contesta(self):
        """Cerrar con la cruz tiene que dejarla como estaba, y con la fila editada en vivo no
        habría a qué volver."""
        js = _read(UI)
        cuerpo = js.split('async function _orgModalSave(')[1].split('\n}\n')[0]
        assert 'apiSend(' in cuerpo
        assert '_orgsReload()' in cuerpo, 'guarda y no vuelve a mirar lo que quedó'

    def test_y_un_nombre_repetido_se_contesta_dentro_del_cuadro(self):
        """El servidor contesta 409 con palabras. Cerrarlo y soltar un aviso encima de una lista
        que no ha cambiado es contarlo donde ya no se puede corregir."""
        js = _read(UI)
        cuerpo = js.split('async function _orgModalSave(')[1].split('\n}\n')[0]
        assert 'orgModalError' in cuerpo


class TestLoQueSeEscribeSeEscribeConPermiso:

    def test_los_botones_de_escribir_van_tras_su_bandera(self):
        js = _read(UI)
        assert "_orgsMay('orgs_edit')" in js
        spec = _spec()
        assert 'actionsVisible:' in spec, 'la columna de acciones se enseña siempre'
        assert 'ctx.puede' in spec

    def test_y_leerla_no_pide_la_de_escribir(self):
        """El registro lo lee cualquiera que tenga la sección: una entrada de menú que lleva a un
        403 es peor que no estar. Lo que se estrecha es escribir, así que **las filas no miran la
        bandera**: si la mirasen, quien sólo puede leer vería una lista vacía."""
        spec = _spec()
        filas = spec.split('rows:')[1].split('actions:')[0]
        assert 'orgs_edit' not in filas, 'las filas se esconden a quien no puede escribir'
        assert "_orgsMay('orgs_edit')" in spec.split('prepare:')[1].split('rows:')[0], \
            'nadie resuelve el permiso una vez por dibujado'
