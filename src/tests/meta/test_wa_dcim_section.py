#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inventario físico (/dcim) — el cableado que hace que la sección exista.

Una sección de este panel no es un fichero. Es una entrada en el registro de páginas (que es lo
que le da URL, ruta, puerta de permiso y entrada en la barra), un pane en el shell donde
dibujarse, su JavaScript en el bundle, y una función de render cuyo nombre el registro nombra.
Falta la entrada del registro y no hay URL; falta el pane y la sección se abre sobre nada; falta
el include y la barra ofrece una sección cuya función no está definida.

**Las cuatro fallan en silencio**, y ninguna de una forma que un test de Python notase por su
cuenta: el bundle es una plantilla Jinja, y para Python es texto.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
DCIM = os.path.join(TPL, 'partials', 'dcim')
BUNDLE = os.path.join(TPL, 'partials', '_js_sections.html')
SHELL = os.path.join(TPL, 'dashboard.html')
CONSTANTS = os.path.join(SRC, 'lib', 'web_admin', 'constants.py')
ROUTES_INDEX = os.path.join(SRC, 'lib', 'web_admin', 'routes', '__init__.py')


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()


def _section():
    """Toda la sección, no uno de sus ficheros.

    Se partió en tres —el armazón, el árbol y un rack— porque una `_render.html` que crece es
    una sección escondiendo sub-secciones dentro. Una guarda que apunte a un fichero deja de
    mirar el día que ese fichero se divide, y lo hace **en silencio**: sigue pasando."""
    return '\n'.join(_read(os.path.join(DCIM, f))
                     for f in sorted(os.listdir(DCIM)) if f.endswith('.html'))


class TestLaSeccionEstaCableadaDePuntaAPunta:

    def test_esta_en_el_registro_de_paginas(self):
        """Una entrada es lo que le da a una sección su URL, su ruta, su puerta de permiso y su
        sitio en la barra — ver routes/pages.py, que construye las cuatro con esto."""
        src = _read(CONSTANTS)
        assert "'id': 'dcim'" in src and "'url': '/dcim'" in src
        assert "'perm': 'dcim_view'" in src
        assert "'render': 'renderDcim'" in src
        assert "'pane': 'tab-dcim'" in src

    def test_tiene_pane_donde_dibujarse(self):
        assert 'id="tab-dcim"' in _read(os.path.join(DCIM, '_pane.html'))
        assert 'partials/dcim/_pane.html' in _read(SHELL)

    def test_ningun_parcial_se_queda_sin_incluir(self):
        """Sin esto la barra ofrece una sección cuya función de render no existe, y el clic no
        hace nada — sin error, porque el despacho es por nombre.

        Cada fichero, no el armazón: al partir la sección, un sub-parcial que no se incluya es
        justo eso mismo un nivel más abajo — la sección abre y la mitad de sus botones llaman a
        funciones que no existen.

        En el paquete de JavaScript **o en el pane**: no todo lo que cuelga de esta sección es
        código. Las caras de los conectores son un `<svg>`, y un `<svg>` dentro del `<script>`
        del paquete no dibujaría nada. Lo que se comprueba es que esté enchufado en algún sitio,
        que es lo que de verdad falla cuando falla."""
        enchufado = _read(BUNDLE) + _read(os.path.join(DCIM, '_pane.html'))
        for f in sorted(os.listdir(DCIM)):
            if f.endswith('.html') and f != '_pane.html':
                assert f'partials/dcim/{f}' in enchufado, f

    def test_y_la_funcion_que_el_registro_nombra_existe(self):
        render = re.search(r"'id': 'dcim'[\s\S]{0,400}?'render': '(\w+)'", _read(CONSTANTS))
        assert render, 'el registro no nombra ninguna función'
        assert f'function {render.group(1)}(' in _section()

    def test_y_sus_rutas_estan_registradas(self):
        src = _read(ROUTES_INDEX)
        assert 'lib.core.dcim.routes import register' in src
        assert '_dcim(app, wa)' in src


class TestLaPantallaRespetaLasConvencionesDelPanel:
    """Cuatro reglas que el panel cumple entero, y que se rompen sin que nada falle."""

    def _js(self):
        return _section()

    def test_nada_de_dialogos_del_navegador(self):
        """`confirm()`/`alert()`/`prompt()` no se usan: el panel tiene los suyos."""
        js = self._js()
        for banned in ('confirm(', 'alert(', 'prompt('):
            assert banned not in js.replace('showConfirmModal(', ''), banned

    def test_nada_de_botones_transparentes(self):
        assert 'btn-outline' not in self._js()

    #: Los campos que teclea una persona y acaban en una plantilla.
    ESCRITOS = ('name', 'label', 'serial', 'address', 'short', 'description', 'asset')

    def test_lo_que_teclea_una_persona_sale_escapado(self):
        """Un nombre de sede, una etiqueta de rack, un número de serie: los escribe alguien y de
        ahí salen a HTML.

        Comprobado sobre las INTERPOLACIONES y no sobre el fichero, porque lo que importa no es
        que aparezca `esc(` en alguna parte sino que aparezca en la misma en la que sale el
        campo. `${rows.map(...)}` y `${x.length}` no son texto de nadie y no cuentan.
        """
        js = self._js()
        malas = []
        for expr in re.findall(r'\$\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}', js):
            if not any(re.search(r'\.%s\b' % f, expr) for f in self.ESCRITOS):
                continue
            if 'esc(' in expr or 'escAttr(' in expr or 'jsStr(' in expr:
                continue
            # Un campo que se PASA a un ayudante de este mismo fichero no se está imprimiendo:
            # lo escapa quien lo pinte, y a ese lo comprueba esta misma regla. Lo que hay que
            # perseguir es el que sale directo a la plantilla.
            if re.match(r'^_dcim\w+\([^()]*(?:\([^()]*\)[^()]*)*\)$', expr.strip()):
                continue
            malas.append(expr.strip()[:60])
        assert not malas, f'campos escritos por alguien, sin escapar: {malas}'

    def test_toda_funcion_que_se_llama_esta_escrita(self):
        """Una función borrada no da error de sintaxis: da una pantalla en blanco.

        Pasó dos veces el mismo día. Reescribiendo un bloque me llevé por delante `_dcSchLoad` y
        `_dcSchHtml`, que seguían llamándose desde tres sitios — y el resultado fue la pestaña de
        esquemas vacía **y** el modal de editar un modelo sin abrirse, porque el error corta el
        guion entero y no solo la parte que falta. `node --check` daba el fichero por bueno: le
        sobra razón, es JavaScript perfectamente válido.

        Lo que no ve un comprobador de sintaxis es el conjunto. Esto sí: recoge lo que se llama
        y lo que está escrito **en toda la sección** y compara.
        """
        js = self._js()
        # Declaradas como función y también como flecha en una constante: las dos formas se
        # usan en la sección, y mirar solo una convierte a la otra en un falso positivo.
        escritas = set(re.findall(r'function\s+(_dc\w+)\s*\(', js))
        escritas |= set(re.findall(r'(?:const|let|var)\s+(_dc\w+)\s*=', js))
        llamadas = set(re.findall(r'\b(_dc\w+)\s*\(', js))
        faltan = sorted(llamadas - escritas)
        assert not faltan, (
            'se llaman y no están escritas en ninguna plantilla de la sección: %s' % faltan)

    def test_ningun_async_se_queda_colgando(self):
        """`async` seguido de algo que no es una función es un identificador suelto.

        También válido como sintaxis, y también una pantalla en blanco: al insertar una función
        delante de `async function _dcCatShow` quedó un `async` solo, la inserción se comió el
        `async` de quien lo tenía, y el navegador contestó `async is not defined`. La separación
        automática de sentencias lo hace legal y lo deja roto.
        """
        js = self._js()
        malos = re.findall(r'\basync\b(?!\s*(?:function|\(|[A-Za-z_$]))', js)
        assert not malos, 'hay %d `async` que no encabezan ninguna función' % len(malos)

    def test_y_el_ayudante_al_que_se_lo_pasan_tambien_escapa(self):
        """La excepción de arriba da por hecho que quien recibe un campo lo escapa. Si deja de
        hacerlo, la excepción se convierte en un agujero — así que se comprueba."""
        cuerpo = self._js().split('function _dcimActions(')[1].split('\nfunction ')[0]
        assert 'jsStr(name' in cuerpo, 'el nombre entra crudo en un onclick'
        assert 'jsStr(uid)' in cuerpo, 'el uid entra crudo en un onclick'
        assert 'escAttr(t(key))' in cuerpo

    #: Lo que un item ajeno no trae y esta pantalla no puede inventar.
    AJENO = ('item.label', 'item.serial', 'item.host_uid', 'item.org_uid', 'item.state')

    def _ramas(self, js):
        """Cada `if (item.foreign)` con su bloque, contando llaves.

        TODAS, no la primera: hay una en la fila de la tabla y otra en la tarjeta del alzado, y
        una guarda que mira una de dos deja pasar la otra sin decirlo."""
        out = []
        needle = 'if (item.foreign)'
        i = js.find(needle)
        while i >= 0:
            j = js.index('{', i)
            depth, k = 0, j
            while k < len(js):
                if js[k] == '{':
                    depth += 1
                elif js[k] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            out.append(js[j:k])
            i = js.find(needle, k)
        return out

    def test_y_lo_ajeno_no_se_dibuja_con_nombre(self):
        """El contrato lo aplica la API (`foreign: true`, posición y tamaño y nada más). Lo que
        esta pantalla no puede hacer es inventarle un nombre a lo que llegó sin él."""
        ramas = self._ramas(self._js())
        assert len(ramas) >= 2, 'la pantalla dejó de distinguir lo ajeno en algún sitio'
        for rama in ramas:
            for leak in self.AJENO:
                assert leak not in rama, (leak, rama[:80])

    def test_y_en_el_dibujo_no_tiene_color(self):
        """Sin color a propósito: el color de un item es el de su máquina, y de una máquina
        ajena no se sabe nada. Pintarla de gris no es decoración, es lo único que se puede
        decir — y es un ternario y no un `if`, que es la misma decisión con otra forma."""
        cuerpo = self._js().split('function _dceItem(')[1].split('\nfunction ')[0]
        assert "item.foreign ? 'var(--bs-secondary-bg)'" in cuerpo, \
            'una máquina ajena se pinta con el color de su estado'

    def test_ni_nombre_en_ninguna_de_las_tres_pantallas(self):
        """Cómo se lee un item lo decide UNA función, porque el alzado, la tabla y la tarjeta
        dicen el mismo nombre y tres copias es que una se quede con el uid. Y esa función es
        también donde se niega a nombrar lo ajeno."""
        cuerpo = self._js().split('function _dcimItemName(')[1].split('\nfunction ')[0]
        assert "i.foreign) return t('dcim_foreign')" in cuerpo, \
            'lo ajeno sale con su etiqueta o con su uid'
        # …y la negativa está ANTES de mirar nada suyo: al revés sería correcta por casualidad.
        assert cuerpo.index('foreign') < cuerpo.index('i.label'), \
            'mira la etiqueta de lo ajeno antes de negarse a usarla'


class TestLasPalabrasExisten:

    def test_cada_clave_que_la_pantalla_nombra_esta_en_los_dos_idiomas(self):
        js = _section()
        keys = set(re.findall(r"\bt\('([a-z0-9_]+)'\)", js))
        keys |= set(re.findall(r"\btf\('([a-z0-9_]+)'", js))
        # Una clave dentro de un ternario —`t(a ? 'x' : 'y')`— y otra puesta como `label:` de
        # la tabla de campos entraron sin existir en ningún idioma, y esto dijo que bien: solo
        # miraba la forma literal. Un guardián que aprueba lo que no mira da por revisado lo que
        # nadie ha revisado, así que mira las tres formas en las que la pantalla nombra algo.
        for call in re.findall(r"\bt\(([^()]*\?[^()]*)\)", js):
            # Solo las ramas: lo que hay antes del `?` es la condicion, y ahi `mode === 'new'`
            # es una comparacion y no una palabra que nadie vaya a leer.
            keys |= set(re.findall(r"'([a-z0-9_]+)'", call.split('?', 1)[1]))
        keys |= set(re.findall(r"\b(?:label|title)_?k?e?y?: *'([a-z0-9_]+)'", js))
        assert keys, 'la pantalla no nombra ninguna palabra, que sería más raro todavía'
        for lang in ('es_ES', 'en_EN'):
            words = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            missing = sorted(k for k in keys if f"'{k}'" not in words)
            assert not missing, (lang, missing)

class TestLosTresVerbosSeLeenEnUnSoloSitio:
    """`apiPost` y `apiDelete` devuelven `{status, data}`; `apiPut` devuelve **el cuerpo**, con
    su `ok` y su `error` un nivel más arriba.

    Leerlos todos igual hace que una escritura correcta parezca un fallo, y eso salió a la
    pantalla dos veces seguidas —primero con el POST y luego con el PUT— con el dato ya guardado
    las dos veces. Es la peor forma de equivocarse: la pantalla miente sobre algo que ya ocurrió,
    y solo un F5 la desmiente.

    El núcleo no se toca —el contrato de `apiPut` lo leen decenas de sitios— así que se
    normaliza una vez aquí, y esto vigila que siga siendo una.
    """

    def _js(self):
        return _section()

    def test_hay_un_normalizador(self):
        body = self._js().split('async function _dcimSend(')[1].split('\n}')[0]
        assert 'apiPut(' in body and 'apiPost(' in body and 'apiDelete(' in body
        assert 'raw.data !== undefined' in body, 'no distingue las dos formas'

    def test_y_nadie_llama_a_los_verbos_por_su_cuenta(self):
        """Una llamada suelta es la ocasión de volver a leerla mal."""
        js = self._js()
        fuera = js.split('async function _dcimSend(')[0] + \
            js.split('async function _dcimSend(')[1].split('\n}', 1)[1]
        for verbo in ('apiPost(', 'apiPut(', 'apiDelete('):
            assert verbo not in fuera, f'{verbo} se llama fuera del normalizador'

    def test_y_lo_que_devuelve_se_lee_por_ok_y_por_error(self):
        js = self._js()
        assert 'if (r.ok) {' in js, 'algo sigue leyendo el estado a mano'
        assert 'r.status === 200' not in js

class TestDondeEstaUnRackNoEsLaVistaDeNadie:
    """En los dos mapas, dónde alguien arrastró una caja es **su** lectura de un diagrama: vive
    en su navegador y en su cuenta, y está bien que así sea, porque dos personas pueden querer
    leer la misma red de forma distinta.

    Un rack no es un diagrama. Son trescientos kilos de acero en un sitio, **el mismo para
    todos**, y el siguiente que abra el plano tiene que verlo donde está. Guardarlo como la
    disposición de un mapa sería que cada uno lo viera donde él lo dejó — y el que baja al CPD
    se lo encuentra en otra parte.
    """

    def _js(self):
        return _section()

    def test_soltar_un_rack_escribe_en_el_servidor(self):
        cuerpo = self._js().split('async function _dcpUp(')[1].split('\n}')[0]
        assert "_dcimSend('PUT'" in cuerpo, 'la posición se queda en el navegador'
        assert 'pos_x' in cuerpo and 'pos_y' in cuerpo

    def test_y_no_por_la_disposicion_guardada_del_lienzo(self):
        """`ssCanvasMoved` y compañía son la vista de una persona sobre un dibujo. Este plano
        usa el lienzo para mirar —desplazar, acercar, encuadrar, exportar— y no para recordar
        dónde está nada."""
        plano = self._js().split('const _DCP_SVG')[1]
        for guardado in ('ssCanvasMoved', 'ssCanvasDragStart', 'ssCanvasKeep'):
            assert guardado not in plano, guardado

    def test_y_si_el_servidor_lo_rechaza_el_rack_vuelve_a_donde_estaba(self):
        """Dejarlo donde lo soltó la mano cuando el servidor dijo que no es una pantalla que
        enseña algo que no ocurrió — el mismo error que ya salió dos veces con el guardado."""
        cuerpo = self._js().split('async function _dcpUp(')[1].split('\n}')[0]
        assert '_dcimOpenPlan' in cuerpo, 'una escritura rechazada deja el rack movido'

    def test_el_plano_se_mide_en_milimetros_y_se_dibuja_a_escala(self):
        """La posición se GUARDA en las unidades en que se mide una sala. Guardar píxeles haría
        el plano ilegible el día que cambie la escala, y la escala es una decisión sobre el
        dibujo, no sobre la sala."""
        cuerpo = self._js().split('function _dcpMove(')[1].split('\n}')[0]
        assert '/ _DCP_SCALE' in cuerpo, 'la posición se guarda en píxeles'


class TestLasCoordenadasNiSeRedondeanNiSeTecleanEnDosVeces:
    """Un mapa da las dos coordenadas juntas y con diecisiete dígitos.

    Las dos formas de perder eso no dan error, que es lo que las hace peligrosas:

    * un `<input type=number>` **descarta** un texto con coma —`value` sale vacío— así que un
      pegado de «41.53, 0.42» se pierde entero y la caja se queda en blanco;
    * `toFixed(4)` pinta once metros y lo presenta como el dato guardado, cuando lo guardado
      tiene los diecisiete dígitos. Un número redondeado al pintarlo y enseñado como el dato es
      una mentira que nadie comprueba, porque no hay nada que ver.
    """

    def test_no_son_campos_numericos(self):
        js = _section()
        campos = js.split("site: {url: 'sites'")[1].split(']}')[0]
        for name in ('lat', 'lon'):
            fila = [l for l in campos.splitlines() if f"name: '{name}'" in l][0]
            assert "type: 'coord'" in fila, fila
            assert "type: 'number'" not in fila, fila

    def test_y_cada_una_sabe_cual_es_la_otra(self):
        js = _section()
        campos = js.split("site: {url: 'sites'")[1].split(']}')[0]
        assert "pairs: 'lon'" in campos and "pairs: 'lat'" in campos

    def test_el_par_se_reparte_al_escribir_y_al_guardar(self):
        """Solo al guardar dejaría la caja de la latitud enseñando las dos: la pantalla diría
        algo distinto de lo que se va a guardar."""
        js = _section()
        assert '_dcimSplitCoords(this,' in js, 'no se reparte mientras se escribe'
        assert '_dcimCoordPair(raw)' in js, 'no se reparte al guardar'

    def test_un_texto_que_no_es_un_par_se_deja_en_paz(self):
        """Adivinar de más es peor que no adivinar: exige DOS números y nada más."""
        cuerpo = _section().split('function _dcimCoordPair(')[1]
        cuerpo = cuerpo.split(chr(10) + chr(125))[0]
        assert 'length !== 2' in cuerpo
        assert 'isFinite' in cuerpo

    def test_la_insignia_no_redondea_a_cuatro_decimales(self):
        js = _section()
        assert 'toFixed(4)' not in js, 'cuatro decimales son once metros: toda la sede'


class TestElMarcoNoMezclaUnidades:
    """Un marco tiene que estar en las mismas unidades que lo que enmarca.

    El plano se dibuja en unidades de dibujo —milímetros por la escala— y el margen está escrito
    en milímetros, como todo lo que aquí se mide. Mezclarlos daba una ventana perfectamente
    válida, `-400 -400 96 72`, mirando a un sitio donde no había nada: el dibujo salía entero y
    en su sitio, y la pantalla salía **en blanco, sin un solo error en la consola**.

    Por eso se vigila, y por eso se vigila así: no hay forma de notar esto leyendo el código
    —los dos números parecen números— y la única señal es una pantalla vacía que parece un
    problema de datos.
    """

    def _extent(self):
        js = _read(os.path.join(DCIM, '_plan.html'))
        return js.split('function _dcpExtent(')[1].split(chr(10) + chr(125))[0]

    def test_el_origen_esta_en_unidades_de_dibujo(self):
        cuerpo = self._extent()
        assert 'x: -_DCP.PAD,' not in cuerpo, (
            'el origen en milímetros y el tamaño en unidades de dibujo: la ventana acaba '
            'mirando a donde no hay nada')
        assert '_DCP.PAD * _DCP_SCALE' in cuerpo, 'el margen tiene que escalarse como el resto'

    def test_y_el_marco_cuenta_todo_lo_que_se_dibuja(self):
        """Un marco que no cuenta una de sus cajas deja esa caja donde ya no se puede agarrar.
        Este panel lo ha pisado tres veces: los dos mapas de infraestructura y este plano."""
        cuerpo = self._extent()
        for lo_que_hay in ('racks', '_dcpFeatures', 'width_mm', 'plan_mm'):
            assert lo_que_hay in cuerpo, lo_que_hay


class TestElVisor3dNoPideNadaAFuera:
    """El prototipo del que sale el visor cargaba three.js de un CDN. Aquí eso no es una
    preferencia: la política de contenido de este panel no ejecuta script de terceros, y se
    despliega en sitios sin salida a internet donde un `<script src>` a un CDN es una pantalla
    que no carga y no dice por qué.

    Se vigila desde fuera porque la tentación vuelve cada vez que alguien quiere una sombra.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_room3d.html'))

    def test_no_carga_ninguna_libreria(self):
        js = self._js()
        for fuera in ('cdnjs', 'unpkg', 'jsdelivr', 'three.min.js', '<script src'):
            assert fuera not in js, fuera

    def test_dibuja_con_webgl_del_propio_navegador(self):
        js = self._js()
        assert "getContext('webgl'" in js
        assert 'createShader' in js and 'drawElements' in js

    def test_y_dice_algo_cuando_no_hay_webgl(self):
        """Una pantalla negra sin explicación es peor que una frase: el plano en planta sigue
        funcionando y quien mira tiene que saberlo."""
        assert 'dcim_3d_no_webgl' in self._js()

    def test_suelta_el_contexto_al_cerrar(self):
        """Un navegador aguanta unos pocos contextos WebGL y va tirando los viejos. Abrir y
        cerrar el visor diez veces sin soltarlos deja el undécimo en negro, sin ningún error."""
        js = self._js()
        assert 'WEBGL_lose_context' in js and 'cancelAnimationFrame' in js


class TestUnPlanoSeLlevaYSeTrae:

    def test_el_fichero_se_entrega_por_el_ayudante_compartido(self):
        """Seis líneas que entregan un fichero y revocan su URL son seis líneas que un día se
        copian cinco de seis y dejan una fuga."""
        js = _read(os.path.join(DCIM, '_pieces.html'))
        assert 'ssDownloadBlob(' in js
        assert 'URL.createObjectURL' not in js

    def test_lo_exportado_no_lleva_lo_que_hay_dentro_de_un_rack(self):
        """Un plano describe una sala. El inventario de un armario es otra cosa y viaja en la
        copia de seguridad."""
        js = _read(os.path.join(DCIM, '_pieces.html'))
        cuerpo = js.split('function _dcpExportJson(')[1].split(chr(10) + chr(125))[0]
        for dentro in ('items', 'host_uid', 'serial'):
            assert dentro not in cuerpo, dentro

    def test_importar_avisa_de_lo_que_reemplaza(self):
        """Un botón que borra tiene que decir qué borra ANTES, no después."""
        js = _read(os.path.join(DCIM, '_pieces.html'))
        assert 'dcim_import_q' in js and 'showConfirmModal' in js


class TestLaInversaDeLaAlturaEsExacta:
    """`_dceUAt` convierte una altura del dibujo en una U, y `_dceY` hace lo contrario.

    Si no son exactamente inversas, arrastrar un servidor lo deja una U más arriba de donde se
    soltó —y en el otro extremo del armario si además se equivoca el sentido de la numeración—.
    No hay ningún error que ver: solo un armario mal dibujado que alguien se va a creer, y un
    servidor que aparece en la U de al lado en la documentación.

    Pasó: escrito con `round`, el centro de una fila cae en `.5` y se iba a la fila siguiente.
    Las 42 U, en los dos sentidos.
    """

    def _fn(self, nombre):
        js = _read(os.path.join(DCIM, '_elevation.html'))
        return js.split('function ' + nombre + '(')[1].split(chr(10) + chr(125))[0]

    def test_se_redondea_hacia_la_fila_y_no_a_la_de_al_lado(self):
        cuerpo = self._fn('_dceUAt')
        assert 'Math.floor' in cuerpo, (
            '`_dceY` devuelve el borde superior de la fila, así que el centro de una U cae en '
            '`.5`: con `round` todo lo arrastrado cae una U por encima')
        assert 'Math.round' not in cuerpo

    def test_y_pregunta_lo_mismo_que_la_ida_sobre_la_numeracion(self):
        """Un armario numerado de arriba abajo cuenta al revés. Que una de las dos lo mire y la
        otra no manda el servidor al otro extremo."""
        for nombre in ('_dceY', '_dceUAt'):
            assert 'desc_units' in self._fn(nombre), nombre

    def test_lo_de_fuera_del_armario_se_recorta(self):
        """Soltar por encima del armario tiene que dar la U 1 o la última, no una que no
        existe: una U 0 se guarda igual de bien y no se puede dibujar."""
        cuerpo = self._fn('_dceUAt')
        assert 'Math.max(1' in cuerpo and 'Math.min(h' in cuerpo


class TestLoAjenoNoSeArrastra:

    def test_un_equipo_de_otro_no_se_coge(self):
        """Se dibuja ocupando y anónimo. Poder moverlo sería poder reorganizar el armario de
        otra sociedad sin verlo."""
        cuerpo = _read(os.path.join(DCIM, '_elevation.html'))
        cuerpo = cuerpo.split('function _dceDown(')[1].split(chr(10) + chr(125))[0]
        assert 'item.foreign' in cuerpo and "_dcimMay('dcim_edit')" in cuerpo


class TestElAlzadoDiceQueSaleDeCadaEquipo:
    """Una tabla de cables contesta «qué hay declarado»; el alzado contesta «qué sale de ESTE
    equipo», que es la pregunta que se hace con la mano en el armario.

    Marcas y no cables: cuarenta equipos con sus latiguillos dibujados son una maraña que tapa
    justo lo que se venía a mirar.
    """

    def _marks(self):
        js = _read(os.path.join(DCIM, '_elevation.html'))
        return js.split('function _dceMarks(')[1].split(chr(10) + chr(125))[0]

    def test_las_marcas_salen_de_lo_ya_cargado(self):
        """De `_dcCables` y `_dcPower`, que ya están en memoria cuando su pestaña está abierta.
        Una petición por equipo dibujado sería una petición por fila del armario."""
        cuerpo = self._marks()
        assert '_dcCables' in cuerpo and '_dcPower' in cuerpo
        assert 'apiGet' not in cuerpo and 'fetch(' not in cuerpo

    def test_estan_acotadas(self):
        """Un equipo con veinte cables declarados no puede pintar veinte puntos en una U: se
        salen de la caja y tapan el nombre, que es lo que de verdad se lee."""
        cuerpo = self._marks()
        assert '.slice(0,' in cuerpo.replace(' ', '')

    def test_lo_ajeno_no_lleva_marcas(self):
        """De un equipo de otra sociedad no sale ni un dato, y de qué color es su latiguillo lo
        es: dos armarios con el mismo color de cable dicen quién los parcheó."""
        js = _read(os.path.join(DCIM, '_elevation.html'))
        item = js.split('function _dceItem(')[1].split(chr(10) + chr(125))[0]
        assert 'item.foreign ?' in item and '_dceMarks(' in item
        # …y en la rama de lo ajeno no se llama a las marcas.
        ajeno = item.split('item.foreign ?')[1].split(': _dceMarks')[0]
        assert '_dceMarks' not in ajeno


class TestTodoLoQueSeEscribeTieneDondeEscribirse:
    """Una ruta que solo existe en la API es una función que no existe.

    Pasó, y se descubrió preguntando: el catálogo entero —importador, buscador y sugerencia—
    estaba construido y probado, y no había **ningún botón** para lanzarlo. Igual los cuadros y
    los SAI, y crear filas. El modelo, las rutas y los tests en verde, y nada de eso alcanzable.

    Los tests no lo ven porque prueban la API, que es justo la mitad que sí estaba. Así que se
    vigila desde fuera: cada verbo de escritura de esta sección tiene que aparecer en alguna
    plantilla, o no está terminado.
    """

    def _escrituras(self):
        """Las URL que esta sección escribe, sacadas de sus propias rutas."""
        # El paquete entero: las rutas se repartieron por áreas —salas, corriente, catálogo…—
        # y leer solo un fichero dejaría fuera cinco sextos de la sección sin que nada fallara.
        carpeta = os.path.join(SRC, 'lib', 'core', 'dcim', 'routes')
        src = ''.join(_read(os.path.join(carpeta, f))
                      for f in sorted(os.listdir(carpeta)) if f.endswith('.py'))
        urls = set()
        for m in re.finditer(r"@app\.route\(f?'(/api/v1/dcim/[^']+)'[^)]*methods=\[([^\]]+)\]",
                             src):
            verbos = m.group(2)
            if 'POST' in verbos or 'PUT' in verbos or 'DELETE' in verbos:
                # El prefijo estable: lo que va después de `/dcim/` hasta el primer `<` o `/`
                # con parámetro. Es lo que una plantilla escribe literalmente.
                trozo = m.group(1).split('/api/v1/dcim/')[1]
                trozo = trozo.split('/<')[0].split('<')[0].strip('/')
                if trozo and '{' not in trozo:
                    urls.add(trozo)
        return urls

    def test_cada_cosa_que_se_escribe_se_puede_escribir_desde_la_pantalla(self):
        js = _section()
        # El CRUD genérico se monta con `f'/api/v1/dcim/{kind}'`, así que sus tres nombres
        # aparecen como literales en la llamada al factory y no en la ruta.
        genericas = {'sites', 'rooms', 'racks', 'pdus', 'feeds', 'cables'}
        faltan = []
        for url in sorted(self._escrituras() | genericas):
            if f'/api/v1/dcim/{url}' not in js:
                faltan.append(url)
        assert not faltan, (
            'estas se pueden escribir por la API y no desde ninguna pantalla, que es lo mismo '
            f'que no poder escribirlas: {faltan}')

    def test_y_a_cada_pantalla_se_llega_pulsando_algo(self):
        """La que faltaba y dio origen a esta guarda: el importador existía y no había botón.

        Se busca la llamada dentro de un MANEJADOR y no en cualquier parte, porque la primera
        versión de esto comprobaba que `_dcCatOpen` existiera — y su propia definición la
        satisfacía. Un guardián que aprueba lo que no mira da por revisado lo que nadie ha
        revisado, y esta sección ya lo ha aprendido dos veces.
        """
        ficheros = {f: _read(os.path.join(DCIM, f))
                    for f in sorted(os.listdir(DCIM)) if f.endswith('.html')}

        def pulsable(src):
            return ' '.join(re.findall(r'on\w+="([^"]*)"', src)
                            + re.findall(r'btn\(\s*`([^`]*)`', src))

        # Una VISTA —de las que `renderDcim` conmuta— solo es alcanzable si la abre alguien de
        # FUERA: sus propios botones de buscar y recargar no cuentan, porque para pulsarlos ya
        # hay que estar dentro. Ese fue el cuarto intento fallido de esta guarda.
        #
        # Y hay DOS formas de llegar de fuera, no una: un botón en otra pantalla de la sección,
        # o el menú de la izquierda, que despliega las vistas que el registro declara. La
        # segunda se comprueba entera —la vista declarada Y `_dcimGo` sabiendo abrirla— porque
        # declarar una vista que nadie abre es este mismo agujero con otra forma.
        registro = _read(os.path.join(SRC, 'lib', 'web_admin', 'constants.py'))
        dcim = registro[registro.index("'id': 'dcim'"):]
        dcim = dcim[:dcim.index("'id': 'history'")]
        declaradas = set(re.findall(r"'slug': '(\w+)'", dcim))
        ir = _read(os.path.join(DCIM, '_render.html'))
        cuerpo_ir = ir[ir.index('function _dcimGo('):]

        def por_el_menu(abre):
            """Si el menú lleva a esta pantalla: alguna vista declarada la abre."""
            for slug in declaradas:
                trozo = cuerpo_ir.split(f"'{slug}'")
                if len(trozo) > 1 and abre in trozo[1][:120]:
                    return True
            return False

        faltan = []
        for abre in ('_dcCatOpen', '_dcSrcOpen', '_dcimOpenBoard', '_dcPartsOpen'):
            dueno = [f for f, src in ficheros.items() if f'function {abre}(' in src]
            desde_fuera = [f for f, src in ficheros.items()
                           if f not in dueno and abre in pulsable(src)]
            if not desde_fuera and not por_el_menu(abre):
                faltan.append(abre)
        # Y una acción EN SITIO basta con que tenga su botón donde ocurre: para decir de quién es
        # un rack ya se está mirando el rack.
        aqui = pulsable(_section())
        faltan += [abre for abre in ('_dcimOwnerAsk', '_dcimLinkNew', '_dcpRowNew')
                   if abre not in aqui]
        assert not faltan, f'no hay nada que pulsar para llegar a estas: {faltan}'
