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
import sys

from tests.helpers import _fn, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
DCIM = os.path.join(TPL, 'partials', 'dcim')
BUNDLE = os.path.join(TPL, 'partials', '_js_sections.html')
SHELL = os.path.join(TPL, 'dashboard.html')
CONSTANTS = os.path.join(SRC, 'lib', 'web_admin', 'constants.py')
ROUTES_INDEX = os.path.join(SRC, 'lib', 'web_admin', 'routes', '__init__.py')


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()


def _lang(code):
    """Las palabras de un idioma, **importadas**.

    Leerlas como texto vale para saber si una clave está; para saber qué DICE hace falta el
    diccionario, y estos ficheros son eso: un diccionario y nada más — sin Flask, sin app y sin
    nada que arrancar.
    """
    import importlib                                            # noqa: PLC0415
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    mod = importlib.import_module('lib.i18n.lang.' + code)
    for valor in vars(mod).values():
        if isinstance(valor, dict) and 'dcim_cable_kind' in valor:
            return valor
    raise AssertionError(f'{code}: no trae el diccionario de la sección')


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


def _renglon_fijo(cuerpo: str, clave: str) -> bool:
    """Si ese renglón de una ficha se dibuja SIEMPRE, con valor o sin él.

    Lo que se mira es lo que hay entre el `${` y el `fila(`: un `?` ahí es un renglón que sólo
    existe a veces, que es lo que hacía que un cable sin número de inventario y sin metros
    pareciera un cable del que eso no se puede decir. El VALOR sí puede ser condicional —un «—»
    cuando está vacío—; el renglón, no.

    Y no vale para todo: lo que se pregunta se enseña siempre, pero la evidencia —las bocas que
    los dispositivos dicen ver, cuántos latiguillos hay detrás de una fila— se enseña cuando la
    hay. Un «—» ahí invita a rellenar algo que no se rellena.
    """
    i = cuerpo.index(f"fila(t('{clave}')")
    return '?' not in cuerpo[:i].split('${')[-1]


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
            # Un campo que se PASA a un ayudante de esta misma sección no se está imprimiendo:
            # lo escapa quien lo pinte, y a ese lo comprueba esta misma regla. Lo que hay que
            # perseguir es el que sale directo a la plantilla.
            #
            # `_dc\w+` y no `_dcim\w+`: se escribió cuando los ayudantes de esta sección se
            # llamaban todos `_dcim*`, y el día que uno se llamó `_dcLabel` la guarda señaló el
            # fichero que estaba bien. Lo que la exención dice es «esto se lo pasa a un ayudante
            # de aquí», y ese prefijo lo cumplen los dos.
            if re.match(r'^_dc\w+\([^()]*(?:\([^()]*\)[^()]*)*\)$', expr.strip()):
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

class TestLasEmpresasYaNoVivenAqui:
    """La contención dice **dónde** está algo y la pertenencia **de quién es**: dos árboles, y el
    segundo tuvo su pantalla aquí dos versiones — primero en un botón de la barra del árbol y
    luego como una vista más de la sección.

    Las dos veces por lo mismo: es donde se hizo la pregunta por primera vez. Pero la sociedad
    que paga el armario tiene usuarios en el directorio y licencias en Microsoft 365, y un
    registro que vive dentro de una sección es uno que las demás no pueden usar sin nombrarla.
    Ahora es del core (`lib/core/orgs`), y lo que se vigila aquí es que no vuelva.
    """

    def test_la_seccion_no_dibuja_ninguna_empresa(self):
        """Ni la pantalla ni la variable que decidía si se pintaba: una vista a medio quitar es
        una entrada de menú que lleva a una pantalla en blanco."""
        for fichero in sorted(os.listdir(DCIM)):
            js = _read(os.path.join(DCIM, fichero))
            assert '_dcOrgs' not in js, f'{fichero} sigue dibujando las empresas'
        assert "'slug': 'orgs'" not in _read(CONSTANTS), 'la vista sigue en el registro'

    def test_pero_sigue_sabiendo_de_quien_es_cada_cosa(self):
        """Quitar la pantalla no es quitar la pertenencia: sin las chapas, un armario compartido
        entre sociedades vuelve a ser un armario del que no se sabe nada."""
        arbol = _read(os.path.join(DCIM, '_tree.html'))
        assert '_dcimOwnerAsk(' in arbol, 'no se puede fichar nada desde el árbol'
        assert "'/api/v1/orgs/owner'" in arbol, 'escribe donde ya no hay nadie escuchando'
        assert "_dcimMay('orgs_edit')" in arbol, 'la bandera del core no es la que se mira'

    def test_y_lleva_a_la_seccion_de_verdad_cuando_no_hay_ninguna(self):
        """A quien puede declararlas se le lleva a donde se hace. Navegando y no dibujando: la
        pantalla es de otra sección, y dibujarla aquí la pintaría dentro del inventario."""
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_tree.html')), '_dcimOwnerAsk'))
        assert "_navTab('#tab-orgs')" in cuerpo, 'el aviso no lleva a ninguna parte'


class TestLosTresVerbosSeLeenEnUnSoloSitio:
    """`apiPost` y `apiDelete` devuelven `{status, data}`; `apiPut` devuelve **el cuerpo**, con
    su `ok` y su `error` un nivel más arriba.

    Leerlos todos igual hace que una escritura correcta parezca un fallo, y eso salió a la
    pantalla dos veces seguidas —primero con el POST y luego con el PUT— con el dato ya guardado
    las dos veces. Es la peor forma de equivocarse: la pantalla miente sobre algo que ya ocurrió,
    y solo un F5 la desmiente.

    El normalizador se escribió aquí y ya no es de aquí: en cuanto una segunda pantalla tuvo que
    escribir, una copia habrían sido dos sitios donde arreglar la próxima forma de contestar. Es
    `apiSend`, en `partials/core/_api.html`, y esta sección lo llama por su nombre corto.
    """

    def _js(self):
        return _section()

    def test_hay_un_normalizador_y_esta_en_el_nucleo(self):
        api = _read(os.path.join(TPL, 'partials', 'core', '_api.html'))
        cuerpo = api.split('async function apiSend(')[1].split('\n}')[0]
        assert 'apiPut(' in cuerpo and 'apiPost(' in cuerpo and 'apiDelete(' in cuerpo
        assert 'raw.data !== undefined' in cuerpo, 'no distingue las dos formas'

    def test_y_esta_seccion_lo_llama_en_vez_de_copiarlo(self):
        """Y como función, no como `const`: todo esto acaba en UN script concatenado, así que un
        `const` que se evalúe antes que `_api.html` seria un ReferenceError al cargar."""
        cuerpo = self._js().split('async function _dcimSend(')[1].split('\n}')[0]
        assert 'apiSend(' in cuerpo, 'vuelve a haber una copia del normalizador'
        assert 'raw.data' not in cuerpo, 'la copia sigue ahí'

    def test_y_nadie_llama_a_los_verbos_por_su_cuenta(self):
        """Una llamada suelta es la ocasión de volver a leerla mal."""
        js = self._js()
        fuera = js.split('async function _dcimSend(')[0] +             js.split('async function _dcimSend(')[1].split('\n}', 1)[1]
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
        otra no manda el servidor al otro extremo.

        Las dos lo preguntan por la MISMA pareja de funciones y no cada una por su cuenta: la
        regla dejó de estar copiada el día que la tabla de equipos se puso a ordenar por ella,
        porque una tercera copia son tres que se separan.
        """
        assert '_dcimUFromTop(' in self._fn('_dceY')
        assert '_dcimUAtRow(' in self._fn('_dceUAt')

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


class TestMirarUnaPlataformaNoEsEditarla:
    """La tabla enseña cinco columnas y la ficha tiene quince campos, así que para leer los otros
    diez había que abrir el formulario — y **abrir el formulario para leer es la forma de cambiar
    algo sin querer**: se entra a mirar, se roza una fecha y se guarda.

    Ahora la línea abre una ficha de solo lectura y del mirar se pasa al escribir con un botón,
    que es el orden en el que ocurre de verdad. Lo que se vigila es que siga siendo de solo
    lectura: un campo colado ahí no daría error, daría un formulario que nadie sabe que lo es.
    """

    def _plats(self):
        return _read(os.path.join(DCIM, '_platforms.html'))

    def test_la_linea_entera_abre_la_ficha(self):
        src = self._plats()
        assert 'function _dcPlatInfo(' in src, 'la ficha no está escrita'
        assert 'ss-rowlink' in src and '_dcPlatInfo(' in src, \
            'la fila no se puede pulsar, que es justo lo que se pedía'

    def test_lo_que_dentro_de_la_linea_hace_otra_cosa_no_la_abre(self):
        """Marcar para retirar y borrar ocurren DENTRO de la fila. Sin cortar la propagación, un
        clic en la papelera abre además la ficha de lo que se acaba de mandar borrar — y el modal
        de confirmación queda debajo de una ficha que nadie pidió."""
        # Dentro de la FUNCIÓN que dibuja la tabla: fuera de ella los dos nombres vuelven a
        # aparecer —son sus propias definiciones— y una guarda que mire el fichero entero se
        # daría por satisfecha con el trozo equivocado.
        tabla = _fn(self._plats(), '_dcPlatsTable')
        marca = tabla.split('_dcPlatPick(')[0]
        assert "event.stopPropagation()" in marca[-400:], \
            'marcar una plataforma abre además su ficha'
        borra = tabla.split('_dcPlatDrop(')[0]
        assert "event.stopPropagation()" in borra[-700:], \
            'los botones de la fila abren además su ficha'

    def test_la_ficha_no_puede_escribir(self):
        """De solo lectura de verdad y no por convenio: un `<input>` que se cuele aquí escribe
        en `_dcPlatForm`, que es el borrador del formulario — y lo siguiente que se guarde se
        lleva por delante lo que se tocó mirando."""
        cuerpo = _fn(self._plats(), '_dcPlatInfoHtml')
        malos = [x for x in ('<input', '<select', '<textarea', 'oninput=', 'onchange=',
                             '_dcPlatForm')
                 if x in cuerpo]
        assert not malos, f'la ficha de lectura escribe: {malos}'


class TestUnConectorSePuedeAnadirDesdeDondeSeEchaerdeMenos:
    """La lista de conectores era de solo lectura y remataba diciendo que para añadir uno hay que
    editar `connectors.json`. El editor existía —en la tarjeta de la pantalla de esquemas— y
    quien descubre que le falta el suyo no lo descubre ahí: lo descubre en la lista, buscándolo.

    Y al que se añade no se le parece ningún dibujo: los que trae el panel son uno por FORMA, y
    nadie va a escribir un SVG para la regleta de su rack. Por eso puede llevar una foto.
    """

    def _js(self):
        return _section()

    def test_desde_la_lista_se_llega_al_editor(self):
        js = self._js()
        assert 'function _dcConnEditOpen(' in js, 'el editor no tiene puerta propia'
        # Llamado desde un MANEJADOR y no en cualquier parte: su propia definición satisfaría
        # una comprobación de presencia, que es el error que esta sección ya cometió dos veces.
        manejadores = ' '.join(re.findall(r'on\w+="([^"]*)"', js))
        assert '_dcConnEditOpen(' in manejadores, 'no hay nada que pulsar para llegar'

    def test_la_foto_manda_sobre_el_dibujo(self):
        """Al revés no sirve de nada: el conector que alguien añadió tiene forma `other`, que
        dibuja el enchufe genérico — y el genérico taparía siempre a la foto."""
        cuerpo = _fn(self._js(), '_dcConnIcon')
        i_img, i_forma = cuerpo.find('c.image'), cuerpo.find('c.shape')
        assert 0 <= i_img < i_forma, 'el dibujo genérico tapa la foto que alguien subió'

    def test_las_formas_salen_del_svg_y_no_de_una_lista_copiada(self):
        """Una lista escrita al lado sería una segunda verdad: no ofrecería la forma que alguien
        dibuje mañana, y ofrecería la que se borre — dejando un `<use>` que no da ningún error y
        sí un hueco."""
        cuerpo = _fn(self._js(), '_dcConnShapes')
        assert 'data-ss-conn-shapes' in cuerpo, 'las formas ya no salen del propio SVG'


class TestUnFiltroNoPuedeRenumerarLasFilas:
    """El formulario del documento escribe en `doc.connectors[i]`. Con un filtro puesto, el
    número de la fila que se ve deja de ser ese: renumerar sería editar el conector de al lado
    sin decirlo, en un formulario de ciento y pico filas donde nadie lo notaría.

    Y una fila a medio escribir no se esconde nunca: la que no se ve es la que no se puede
    terminar, y la recién añadida todavía no tiene id por el que encontrarse.
    """

    def _form(self):
        return _fn(_read(os.path.join(DCIM, '_schemas.html')), '_dcConnFormHtml')

    def test_cada_fila_lleva_su_posicion_en_el_documento(self):
        cuerpo = self._form()
        assert 'map((c, i) => ({c: c, i: i}))' in cuerpo, \
            'las filas ya no llevan su índice real'
        assert 'filas.map(({c, i})' in cuerpo, \
            'el índice vuelve a ser el de la lista pintada, no el del documento'

    def test_la_fila_dice_QUE_ES_y_no_lo_dice_todo(self):
        """Diez columnas de formulario no entran en ningún diálogo. Se probó a ensancharlo y lo
        que salió fue una barra de desplazamiento debajo de una fila más ancha que la ventana —
        y ensanchar hasta que quepan es perseguir el ancho de la pantalla de otro.

        La fila contesta **qué es este conector**: cómo se llama, de qué tipo, qué cara tiene y
        en qué casillas se ofrece. La letra pequeña —a cuánto va, qué generaciones caben, qué
        puede llevar, qué es— se pliega, que es donde se lee la letra pequeña. De los ciento
        veintiocho, casi ninguno tiene nada de lo segundo."""
        cuerpo = self._form()
        for fuera in ("'speed'", '_dcConnSigBox', '_dcConnNoteSet'):
            assert fuera not in cuerpo, \
                f'{fuera} vuelve a estar en la fila: la tabla no cabe otra vez'
        assert '_dcConnMoreBtn(' in cuerpo, 'no hay por dónde abrir la letra pequeña'
        detalle = _fn(_read(os.path.join(DCIM, '_schemas.html')), '_dcConnDetailHtml')
        for dentro in ("'speed'", '_dcConnSigBox', '_dcConnNoteSet', '_dcGensHtml'):
            assert dentro in detalle, f'{dentro} no está en ninguno de los dos sitios'

    def test_el_galon_dice_SI_hay_letra_pequena_y_no_cuanta(self):
        """Un galón mudo obliga a abrir los ciento veintiocho para saber cuáles tienen algo
        dentro. Pero **un número tampoco lo dice**: llevaba uno, y un número que suma una
        velocidad, tres generaciones, dos señales y una nota no cuenta nada — «1» no dice cuál de
        las cuatro cosas es, y «6» tampoco. Un recuento significa algo cuando lo que cuenta es de
        una clase.

        Lo único que una fila plegada puede contestar es un bit, y ese sí hace falta."""
        cuerpo = _fn(_read(os.path.join(DCIM, '_schemas.html')), '_dcConnMoreBtn')
        assert 'c.gens' in cuerpo and 'c.signals' in cuerpo, 'el galón no mira nada'
        # Sobre lo que SE PINTA y no sobre cómo se calcula: prohibir un `+` sería fijar la
        # expresión en vez de la regla, y esta sección ya sabe lo que cuesta eso.
        assert 'esc(String(' not in cuerpo, 'el galón vuelve a imprimir un número'
        assert '||' in cuerpo, 'ya no es un bit: alguna de las cuatro dejó de contar'

    def test_lo_que_no_tiene_identificador_no_se_esconde(self):
        cuerpo = self._form()
        assert 'const nuevo = !String(c.id' in cuerpo and 'return nuevo ||' in cuerpo, \
            'un conector a medio escribir puede quedar fuera del filtro'


class TestUnaColumnaQueNadiePuedeEscribir:
    """La forma de fallo que esta sección lleva repetida CUATRO veces.

    `host_uid` existía desde el primer commit, la API la aceptaba y el vuelco de estado la leía —
    y no había campo, así que el rack entero salía gris y el código que la respeta parecía
    funcionar. Luego `asset` y `description`: dos columnas de `dc_item` que se guardan, se
    devuelven y valían siempre su valor por defecto porque ningún formulario las escribía.

    Una columna que nadie puede rellenar no da ningún error. Da un dato que siempre vale lo
    mismo, y eso se lee como «aquí no hay nada que poner».
    """

    #: Lo que NO es de nadie que esté delante de un formulario, y por qué.
    FUERA = {
        'uid',                      # lo acuña el panel
        'rack_uid',                 # dónde se está creando, no un campo
        'type_uid',                 # lo estampa la plantilla o el catálogo
        'created_at', 'updated_at', 'updated_by',   # el registro, no el equipo
    }

    def _columnas(self):
        """Las de `dc_item`, leídas de su propio `TableSpec`."""
        src = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'store.py'))
        i = src.index('_ITEM = TableSpec(')
        return set(re.findall(r"Column\('(\w+)'", src[i:src.index('\n)', i)]))

    def _campos(self):
        js = _read(os.path.join(DCIM, '_form.html'))
        i = js.index("    item: {url: 'items'")
        return set(re.findall(r"name: '(\w+)'", js[i:js.index(']},', i)]))

    def test_todo_lo_que_tiene_un_equipo_se_puede_escribir(self):
        cols, campos = self._columnas(), self._campos()
        assert cols, 'no se encontraron las columnas: la guarda mira donde no es'
        faltan = cols - campos - self.FUERA
        assert not faltan, (
            'columnas de dc_item que se guardan y que ningún campo escribe — valen siempre su '
            f'valor por defecto y nadie se entera: {sorted(faltan)}')

    def test_y_no_se_pide_lo_que_no_es_del_equipo(self):
        """La otra mitad: un campo que escriba `updated_by` deja que alguien firme por otro."""
        sobran = self._campos() & {'uid', 'created_at', 'updated_at', 'updated_by'}
        assert not sobran, f'el formulario escribe el registro: {sorted(sobran)}'


class TestGuardarDicePorQueNoGuarda:
    """Se colocaba un equipo con su número de serie, su plantilla y su fecha de compra, se
    pulsaba Guardar, y **no pasaba nada**: ni error, ni fila, ni pista.

    `if (mode === 'new' && !body[spec.fields[0].name]) return;` — el primer campo del tipo, que
    en un equipo es la etiqueta, y la etiqueta es lo que casi nadie rellena el primer día. La
    guarda era correcta para una sede (una sede sin nombre no es una sede) y estaba escrita sobre
    «el primero de la lista», que es una posición y no una regla.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_form.html'))

    def test_lo_obligatorio_lo_declara_el_campo_y_no_su_posicion(self):
        js = self._js()
        assert 'req: true' in js, 'ya no se declara qué es obligatorio'
        assert 'spec.fields[0]' not in js, \
            'vuelve a ser «el primero de la lista», que es una posición y no una regla'

    def test_y_un_equipo_no_tiene_ninguno(self):
        """Una caja ciega que ocupa un U es un dato de pleno derecho, y no tiene nombre."""
        i = self._js().index("    item: {url: 'items'")
        assert 'req: true' not in self._js()[i:self._js().index(']},', i)], \
            'un equipo vuelve a exigir un campo que casi nadie rellena el primer día'

    def test_negarse_sin_decirlo_ya_no_se_puede(self):
        cuerpo = _fn(self._js(), '_dcimSave')
        assert 'dcim_need_field' in cuerpo, 'guardar vuelve a no hacer nada y no decir nada'


class TestUnaListaCerradaSeEligeYNoSeTeclea:
    """Elegir una plantilla dejaba **el uid escrito en la caja**: treinta y seis caracteres que
    no dicen nada, y quien lo veía no podía saber si había elegido bien.

    Era un `<input list=…>`, que está bien para una zona horaria —se teclea, se filtra, y una que
    esta instalación no conozca se puede pegar igual— y no para una plantilla ni para la bandeja
    de al lado. Lo que se ve es el nombre; lo que se guarda sigue siendo el uid.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_form.html'))

    def test_las_cerradas_son_un_desplegable(self):
        js = self._js()
        assert 'pick: true' in js and 'function _dcimPickHtml(' in js
        # Y que se LLAME: escrita y no usada es una función que no existe, y el uid vuelve a la
        # caja sin que nada falle.
        assert '_dcimPickHtml(' in _fn(js, '_dcimFieldHtml'),             'el desplegable está escrito y no se usa: la caja vuelve a enseñar el uid'
        # Y la abierta sigue siéndolo: las zonas horarias son cientos y se pegan de fuera.
        i = js.index("    zones: {")
        assert 'pick' not in js[i:js.index('},', i)], \
            'las zonas horarias dejaron de poder pegarse'

    def test_lo_que_ya_tenia_y_no_esta_en_la_lista_no_se_pierde(self):
        """Un equipo enganchado a una máquina que este rol no puede ver se guardaría
        desenganchado por el solo hecho de abrir su ficha, y sin un error ni una pista."""
        cuerpo = _fn(self._js(), '_dcimPickHtml')
        assert 'conocido' in cuerpo, 'un valor que no está en la lista se pierde al guardar'


class TestElFormularioNoSeIncrustaEntreLasTarjetas:
    """Eran dieciocho cajas en crudo, del ancho que cupiera, diciendo qué eran sólo en su
    `placeholder` — que desaparece en cuanto se escribe. Con cuatro campos pasa; con dieciocho lo
    que se ve es una fila de huecos y hay que contar posiciones.

    Y empujaba hacia abajo lo que se estaba mirando, que es justo lo que se venía a editar."""

    def test_va_en_el_cuadro_compartido(self):
        js = _read(os.path.join(DCIM, '_form.html'))
        assert 'showHtmlModal(' in _fn(js, '_dcimFormDraw'), 'el formulario no abre en un cuadro'

    def test_y_ya_no_se_pinta_dentro_de_ninguna_pantalla(self):
        assert '_dcimFormHtml' not in _section(), \
            'el formulario vuelve a incrustarse entre las tarjetas'

    def test_cada_caja_lleva_su_rotulo(self):
        """El `placeholder` no es un rótulo: se va en cuanto hay algo escrito, que es justo
        cuando hace falta saber qué es esa casilla."""
        cuerpo = _fn(_read(os.path.join(DCIM, '_form.html')), '_dcimFormBody')
        assert '_dcLabel(' in cuerpo, 'las cajas vuelven a no decir qué son'


class TestElArmarioNoSePierdeDeVista:
    """El alzado y sus listas, uno al lado del otro.

    Las cuatro listas de un rack —lo que hay dentro, cómo está cableado, de dónde come, qué lleva
    una de esas cajas— se insertaban **encima** del dibujo y lo empujaban hacia abajo: se pulsaba
    un botón y lo que estabas mirando se movía. Y bajar a la lista dejaba el armario fuera de la
    pantalla, que es justo cuando hace falta, porque un cable va de una U a otra.
    """

    def _rack(self):
        return _read(os.path.join(DCIM, '_rack.html'))

    def test_el_dibujo_y_las_listas_van_en_columnas(self):
        cuerpo = _fn(self._rack(), '_dcimRackHtml')
        assert 'ss-rack-grid' in cuerpo and '_dcRackPanelHtml(' in cuerpo, \
            'las listas vuelven a apilarse debajo del dibujo'

    def test_las_cuatro_listas_son_pestanas_de_la_misma_caja(self):
        cuerpo = _fn(self._rack(), '_dcRackPanelHtml')
        for tab in ("'items'", "'cables'", "'power'", "'parts'"):
            assert tab in cuerpo, f'falta la pestaña {tab}'

    def test_el_alto_del_alzado_sale_del_armario_y_el_ancho_del_hueco(self):
        """Dos mitades de la misma regla.

        El ALTO no puede salir del panel: `.ss-infra-canvas` es `flex: 1 1 auto` —correcto para
        los dos mapas, que ocupan lo que haya— y aquí dejaba un dibujo de ciento cincuenta
        píxeles en medio de medio metro de negro. Se declara la proporción y el navegador saca
        la altura del ancho que le toque.

        Y el ANCHO es todo el que haya: es lo que se viene a mirar, y un U se lee mejor cuanto
        más grande. Pedir los píxeles exactos del dibujo arreglaba la miniatura y dejaba el aire
        al otro lado, que es el mismo hueco desaprovechado en otro sitio."""
        # Sin los comentarios: el que explica el cambio NOMBRA la clase que se dejó de usar, y
        # una guarda que lee la prosa señala justo el texto que cuenta por qué está bien.
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_elevation.html')),
                                     '_dcimElevation'))
        assert 'aspect-ratio' in cuerpo, 'el alto del alzado vuelve a salir del panel'
        assert 'ss-infra-canvas' not in cuerpo, 'vuelve a usar el lienzo que se estira'
        assert 'width:100%' in cuerpo, 'el alzado deja de quedarse con el hueco libre'

    def test_un_dibujo_distinto_no_hereda_la_ventana_del_anterior(self):
        """La ventana de zoom vive en el lienzo compartido y **no se borra sola**: abrir un
        armario de 5 U detrás de uno de 42 le aplicaba al pequeño la ventana del grande, y salía
        diminuto en una esquina. `ssCanvasReset` existe justo para esto —«un redibujado que
        cambia lo que HAY que mirar»— y el alzado era el único de los tres lienzos que no la
        llamaba nunca."""
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_elevation.html')),
                                     '_dcimElevation'))
        assert 'ssCanvasReset(' in cuerpo, 'el zoom del armario anterior se aplica al siguiente'

    def test_y_hay_forma_de_volver_del_zoom(self):
        """Sin el botón de «ver el armario entero», una rueda de más deja el dibujo en una
        esquina y no hay gesto para deshacerlo."""
        js = _read(os.path.join(DCIM, '_elevation.html'))
        assert 'ssCanvasTools(' in _fn(js, '_dceTools'), 'el alzado se queda sin sus botones'
        # En una barra ENCIMA del dibujo. No en la del armario —allí estaban entre los que
        # crean y borran cosas, que es donde nadie los busca— y tampoco flotando sobre el
        # lienzo, donde tapaban parte de lo que manejan y se peleaban con la tarjeta de la lupa
        # por la misma esquina.
        cuerpo = _fn(js, '_dcimElevation')
        assert '_dceTools(' in cuerpo, 'los botones del zoom salen del dibujo sobre el que actúan'
        assert 'ss-toolrow' in cuerpo, 'los botones vuelven a flotar encima del dibujo'

    def test_lo_cargado_es_de_ESE_armario(self):
        """Abrir otro rack con el cableado del anterior puesto enseñaría los cables de uno bajo
        el nombre del otro, y no lo diría: una tabla de cables no lleva escrito de qué rack es."""
        cuerpo = _fn(self._rack(), '_dcimLoadRack')
        for x in ('_dcCables = null', '_dcPower = null', '_dcParts = null'):
            assert x in cuerpo, f'al cambiar de armario se conserva {x.split()[0]}'


class TestElArmarioSeAgrandaCuandoHaceFalta:
    """Un armario de 42 U con las dos caras y las fotos de sus alzados pide todo el ancho que
    haya; uno de 5 no. El reparto de siempre es el bueno para casi todo y no para ese rato.

    Un botón y no una regla automática: quién necesita mirar el armario de cerca lo sabe él, y
    una pantalla que se recoloca sola es una pantalla que se mueve mientras la miras."""

    def test_hay_por_donde_pedirlo(self):
        js = _read(os.path.join(DCIM, '_elevation.html'))
        assert 'function _dceWideToggle(' in js, 'no se puede agrandar el armario'
        assert '_dceWideToggle()' in _fn(js, '_dcimElevation'), 'no hay nada que pulsar'

    def test_y_TAPA_la_tabla_en_vez_de_moverla(self):
        """La diferencia entre apartar algo y taparlo: lo primero obliga a devolverlo a su sitio
        para volver a donde estabas. Se pide sitio para mirar un armario un rato, no una pantalla
        distinta.

        Y el panel deja de desplazarse mientras tanto, que es lo que hace que `inset: 0` sea
        exactamente lo que se ve: sobre un contenedor con desplazamiento sería el alto de TODO su
        contenido, y el dibujo saldría tan alto como la tabla que está tapando."""
        assert '_dceWide' in _fn(_read(os.path.join(DCIM, '_rack.html')), '_dcimRackHtml'), \
            'el botón está y no cambia nada'
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-elev-over' in css, 'la capa que pasa a primer plano no existe'
        bloque = css[css.index('.ss-elev-over {'):css.index('.ss-elev-over {') + 260]
        assert 'position: absolute' in bloque and 'inset: 0' in bloque, \
            'vuelve a empujar la tabla en vez de taparla'
        assert '.ss-rack-pane.ss-rack-over' in css, \
            'el panel sigue desplazándose debajo, así que `inset: 0` no es lo que se ve'

    def test_agrandar_reencuadra(self):
        """La ventana de zoom se calculó para el ancho de antes: dejarla puesta enseña el mismo
        trozo en un hueco del doble, que es no haber agrandado nada."""
        cuerpo = _fn(_read(os.path.join(DCIM, '_elevation.html')), '_dceWideToggle')
        assert 'ssCanvasReset(' in cuerpo, 'se agranda el hueco y el dibujo se queda igual'

class TestUnBotonQueTardaTieneQueDecirloYa:
    """Se pulsaba Cableado y no pasaba nada hasta que contestaba el servidor: `await` primero y
    redibujado después, así que entre el clic y la respuesta la pantalla no cambiaba. Un botón que
    no hace nada es un botón que se vuelve a pulsar — este panel ya lo aprendió con el explorador
    de carpetas de las copias de seguridad.
    """

    def test_el_hueco_se_dibuja_antes_de_pedir_nada(self):
        for rel, fn in (('_cables.html', '_dcCablesOpen'), ('_power.html', '_dcPowerOpen')):
            cuerpo = _fn(_read(os.path.join(DCIM, rel)), fn)
            i_pinta = cuerpo.find('renderDcim()')
            i_pide = cuerpo.find('await apiGet')
            assert 0 <= i_pinta < i_pide, \
                f'{fn} vuelve a esperar al servidor antes de enseñar nada'
            assert 'loading: true' in cuerpo, f'{fn} no marca que está cargando'

    def test_y_lo_que_se_ve_es_la_forma_de_lo_que_viene(self):
        """Una rueda dice «espera»; unas filas grises dicen «aquí van filas», que además es
        cierto y evita el salto de cuando llegan."""
        js = _read(os.path.join(DCIM, '_cables.html'))
        assert 'function _dcRackSkeleton(' in js
        assert 'loading' in _fn(js, '_dcCablesHtml'), 'la pestaña no dibuja el esqueleto'


class TestLaTablaDiceLoQueElDibujoNoPuede:
    """Cuatro columnas —U, cara, nombre y empresa— que son lo mismo que el alzado de al lado con
    menos. Lo que una tabla puede decir y un dibujo no es lo que sólo tiene ESA caja: su número de
    serie, el de inventario y hasta cuándo tiene garantía. Los tres estaban guardados y no se
    veían en ninguna parte."""

    def test_estan_las_columnas_que_solo_tiene_una_caja(self):
        cuerpo = _fn(_read(os.path.join(DCIM, '_rack.html')), '_dcimItemsTable')
        for k in ('dcim_serial', 'dcim_item_asset', 'dcim_item_warranty'):
            assert k in cuerpo, f'la tabla vuelve a callarse {k}'

    def test_y_las_ocho_de_la_propuesta(self):
        """Estuvieron un rato en seis, con la cara y la empresa metidas junto al nombre porque
        no cabían. Una columna dice lo que una insignia pegada a un nombre no: se puede recorrer
        con la vista, que es para lo que se mira una lista de veinte equipos."""
        cuerpo = _fn(_read(os.path.join(DCIM, '_rack.html')), '_dcimItemsTable')
        for k in ('dcim_u', 'dcim_face', 'dcim_what', 'dcim_serial',
                  'dcim_item_asset_col', 'dcim_item_warranty_col', 'dcim_owner'):
            assert k in cuerpo, f'falta la columna {k}'

    def test_un_hueco_se_dice_con_una_raya(self):
        """Tres celdas vacías seguidas en una fila de ocho se leen como una tabla mal
        dibujada. Una raya dice «aquí no hay nada», que es un dato."""
        assert 'function _dcimDash(' in _read(os.path.join(DCIM, '_rack.html'))

    def test_una_garantia_vencida_se_ve(self):
        """Escrita en gris entre otras diez es una fecha que nadie mira."""
        cuerpo = _fn(_read(os.path.join(DCIM, '_rack.html')), '_dcimWarranty')
        assert 'bg-danger' in cuerpo, 'una garantía vencida ya no se distingue'


class TestElDibujoYLaListaSenalanLoMismo:
    """El alzado dice **dónde está** y la tabla **qué es**: son la misma cosa contada dos veces,
    y hasta ahora no se miraban. Señalar un equipo en el dibujo obligaba a buscar su renglón a
    mano, y al revés igual — con veinte equipos eso es contar líneas.

    Las dos direcciones, porque las dos preguntas son reales: «¿dónde está este?» se hace en la
    lista y «¿qué es esto?» en el armario.
    """

    def _elev(self):
        return _read(os.path.join(DCIM, '_elevation.html'))

    def test_del_dibujo_a_la_lista(self):
        cuerpo = _fn(self._elev(), '_dceHover')
        assert "tr[data-dci]" in cuerpo, 'señalar en el dibujo ya no enciende su fila'

    def test_de_la_lista_al_dibujo(self):
        js = self._elev()
        assert 'function _dceHoverFromList(' in js, 'no hay por dónde señalar desde la lista'
        filas = _read(os.path.join(DCIM, '_rack.html'))
        assert 'data-dci=' in filas and '_dceHoverFromList(' in filas, \
            'las filas de la tabla no dicen de qué caja son'

    def test_la_tarjeta_esta_FUERA_del_dibujo(self):
        """Dos intentos de meterla dentro y los dos tapaban una U.

        Primero pegada al borde de abajo, que ocultaba la última; luego saltando al extremo
        contrario, que ocultaba la primera. El error era la premisa: **dentro de un armario
        dibujado no hay sitio libre**, porque el armario ocupa el dibujo entero. Va debajo, con
        su hueco reservado — apareciendo sólo al señalar algo, el dibujo daría un salto cada vez
        que el ratón entra y sale de una caja."""
        js = self._elev()
        cuerpo = _fn(js, '_dcimElevation')
        i_svg = cuerpo.find('</svg>')
        i_caja = cuerpo.find('dcimElevPanel')
        assert 0 <= i_svg < i_caja, 'la tarjeta vuelve a estar encima del dibujo'
        assert 'position-absolute' not in cuerpo[i_caja:i_caja + 120], \
            'la tarjeta vuelve a flotar sobre el armario'
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert 'min-height' in css[css.index('.ss-elev-info'):css.index('.ss-elev-info') + 200], \
            'sin hueco reservado, el dibujo salta cada vez que el ratón entra en una caja'


class TestLoQueVaSobreUnaBandejaSeDibuja:
    """«Bandeja (+2)» era lo que se podía decir sin sitio: un recuento no enseña cuál de los dos
    mini PC está en aviso, que es justo lo que se viene a mirar a un alzado.

    Se dibujan dentro, con los mismos cuatro campos que dividen un U aplicados al hueco del
    padre. Estaban en la ficha y se guardaban desde el primer día; lo que faltaba era leerlos.
    """

    def _elev(self):
        return _read(os.path.join(DCIM, '_elevation.html'))

    def test_se_dibujan_dentro_de_su_bandeja(self):
        js = self._elev()
        assert 'function _dceKids(' in js, 'lo montado vuelve a no dibujarse'
        assert '_dceKids(' in _fn(js, '_dceFace'), 'está escrito y no se llama'

    def test_y_como_HERMANOS_del_que_los_lleva(self):
        """Dentro del `<g>` de la bandeja, salir de un mini PC hacia ella no volvería a
        encenderla —`pointerenter` no burbujea— y la tarjeta se quedaría vacía con el ratón
        todavía encima de algo."""
        cuerpo = _fn(self._elev(), '_dceFace')
        i_padres = cuerpo.find('_dceItem(rack, i, face)')
        i_hijos = cuerpo.find('_dceKids(rack, i, face)')
        assert 0 <= i_padres < i_hijos, 'lo montado se pinta debajo de lo que lo lleva'

    def test_el_rectangulo_se_calcula_UNA_vez(self):
        """Hace falta dos veces —para pintar la caja y para saber dentro de qué hueco van los
        que se montan encima— y dos cuentas serían dos que se separan el día que alguien toque
        el reparto de un U."""
        js = self._elev()
        assert 'function _dceRect(' in js
        for quien in ('_dceItem', '_dceKids'):
            assert '_dceRect(' in _fn(js, quien), f'{quien} calcula el rectángulo por su cuenta'

    def test_la_bandeja_no_se_queda_sin_nombre(self):
        """Los que van encima la taparían entera, y el armario tendría una caja sin rótulo."""
        assert 'function _dceGut(' in self._elev(), 'no se reserva sitio para el nombre'

    def test_y_las_cajas_miden_contra_SU_ancho(self):
        """`_DCE.W` es el ancho de la CARA. Escrito cuando todo ocupaba el U entero, y desde que
        algo puede tomar media U el engranaje y las marcas se dibujaban fuera de su caja —
        encima de la de al lado, que es un botón que abre lo que no parece."""
        js = _strip_comments(self._elev())
        for fn in ('_dcePartsBtn', '_dceMarks', '_dceFoto'):
            assert '_DCE.W' not in _fn(js, fn), f'{fn} vuelve a medir contra la cara entera'


class TestUnErrorNoEsUnaRespuesta:
    """`apiGet` devuelve `null` ante cualquier respuesta que no sea un 200, así que un 403 —el
    usuario no puede ver esa máquina— llegaba al botón del número de serie como un objeto vacío y
    salía por pantalla como «el dispositivo no ha dicho ningún número de serie».

    Un error contado como respuesta es la peor forma de fallar: manda a mirar la configuración
    del equipo cuando el problema estaba en el permiso. Es la misma forma que esta sección lleva
    todo el mes tropezando — una guarda que se niega sin decirlo, un parámetro que nadie pasa,
    un botón que trabaja fuera de la vista.
    """

    def test_una_peticion_que_falla_lo_dice(self):
        cuerpo = _fn(_read(os.path.join(DCIM, '_form.html')), '_dcimSaidAsk')
        assert 'dcim_said_failed' in cuerpo,             'un fallo de la petición vuelve a contarse como «no ha dicho nada»'
        i_null = cuerpo.find('if (!d)')
        # Contra el caso VACÍO y no contra cualquier mensaje: el de «engancha una máquina»
        # va antes a propósito, que es una comprobación que no necesita pedir nada.
        i_vacio = cuerpo.find('dcim_said_but')
        assert 0 <= i_null < i_vacio, 'se mira el contenido antes de si hubo respuesta'

    def test_y_no_haber_dicho_ESO_no_es_no_haber_dicho_NADA(self):
        """Dos causas que se ven igual y se arreglan en sitios distintos: un perfil que ni
        siquiera se enganchó, y uno que sí pero al que le falta esa directiva. La lista de lo que
        el dispositivo SÍ contó separa las dos sin abrir otra pantalla."""
        cuerpo = _fn(_read(os.path.join(DCIM, '_form.html')), '_dcimSaidAsk')
        assert 'dcim_said_but' in cuerpo and 'dcim_said_nothing' in cuerpo,             'las dos causas vuelven a contarse con la misma frase'


class TestElArmarioSeEnteraDeLoQuePasaFuera:
    """El estado de cada equipo —el verde y el ámbar del alzado— viaja con la carga del armario.
    Se recogen datos de una máquina en Infraestructura, se vuelve aquí, y el aviso sigue puesto
    hasta un F5 — y un F5 es lo que hace la gente cuando una pantalla no se entera, que es lo
    mismo que decir que no funciona.
    """

    def test_hay_boton_para_pedirlo(self):
        js = _read(os.path.join(DCIM, '_rack.html'))
        assert 'function _dcimReloadRack(' in js, 'no se puede refrescar el armario'
        assert '_dcimReloadRack()' in _fn(js, '_dcimRackHtml'), 'no hay nada que pulsar'

    def test_y_volver_a_la_seccion_tambien_lo_pide(self):
        """En `shown.bs.tab` y no dentro de `renderDcim`, que se llama en cada redibujado de la
        propia sección: pedir el armario en cada clic de una pestaña interna sería una petición
        por clic. Ahí se sabe que se viene de fuera, que es cuando puede haber cambiado algo."""
        js = _read(os.path.join(DCIM, '_render.html'))
        assert "shown.bs.tab" in js and "'#tab-dcim'" in js,             'volver a la sección ya no vuelve a pedir el armario'


class TestNingunaEscrituraSeOlvidaDeSuFoto:
    """El historial de un armario es una foto por cambio, y su valor entero depende de que no
    falte ninguna: la lista se lee como acontecimientos —la diferencia entre dos fotos— así que
    una escritura sin foto no deja un hueco, **mezcla dos cambios en un renglón** y lo atribuye a
    quien hizo el segundo.

    Y no se nota. Un historial al que le falta un paso sigue leyéndose bien, sólo que cuenta otra
    cosa. Por eso no se deja a la memoria de quien añada la siguiente ruta.
    """

    def _racks(self):
        return _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes', 'racks.py'))

    def test_colocar_mover_y_retirar_dejan_la_suya(self):
        js = self._racks()
        for fn in ('api_dcim_item_create', 'api_dcim_item_update', 'api_dcim_item_delete'):
            i = js.index(f'def {fn}(')
            j = js.find('\n    @app.route', i)
            assert 'C.snap(' in js[i:j if j > 0 else len(js)], \
                f'{fn} escribe y no deja foto: su cambio se contará junto al siguiente'

    def test_editar_el_armario_tambien(self):
        """Renombrarlo o cambiarle la altura mueve de sitio a todo lo que hay dentro."""
        crud = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes', 'places.py'))
        assert "C.snap(uid, 'rack_edit')" in crud, 'editar el armario no deja foto'

    def test_mudarse_deja_foto_en_los_DOS(self):
        """Para el de origen ese equipo se fue; para el de destino, llegó."""
        js = self._racks()
        i = js.index('def api_dcim_item_update(')
        j = js.find('\n    @app.route', i)
        cuerpo = js[i:j if j > 0 else len(js)]
        assert cuerpo.count('C.snap(') >= 2, \
            'mudar un equipo de armario deja al de origen enseñando lo que ya no está'


class TestLaHistoriaSeLeeEnUnaPestana:
    """Dos preguntas y una sola tabla: cada versión es la foto y su diferencia con la anterior es
    el acontecimiento. Guardando sólo lo segundo no se reconstruye lo primero sin reproducirlo
    todo, y basta que falte un renglón para que la reconstrucción mienta sin decirlo."""

    def test_hay_pestana_y_pide_lo_suyo(self):
        rack = _read(os.path.join(DCIM, '_rack.html'))
        assert "'hist'" in _fn(rack, '_dcRackPanelHtml'), 'no hay pestaña de historial'
        assert 'function _dcHistLoad(' in _read(os.path.join(DCIM, '_rackrev.html'))

    def test_el_historial_es_de_ESE_armario(self):
        """Abrir otro con el historial del anterior puesto enseñaría los movimientos de uno bajo
        el nombre del otro — y una lista de versiones no lleva escrito de qué rack es."""
        assert '_dcHist = null' in _fn(_read(os.path.join(DCIM, '_rack.html')),
                                       '_dcimLoadRack'), \
            'al cambiar de armario se conserva el historial del anterior'

    def test_dos_versiones_se_comparan_de_vieja_a_nueva(self):
        """Marcadas en el orden que sea: una diferencia leída al revés dice que se retiró lo que
        se puso."""
        cuerpo = _fn(_read(os.path.join(DCIM, '_rackrev.html')), '_dcHistDiffHtml')
        assert 'sort(' in cuerpo, 'la comparación depende del orden en que se marcaron'


class TestNoTodoLoQueSeColocaTienePlantilla:
    """Una tapa ciega, una regleta, una bandeja y un panel de parcheo no tienen estándar de
    compra ni componentes que estampar. Sólo se podía colocar algo naciendo de una plantilla, y
    declarar una plantilla para poner una tapa es pedir el estándar de una tapa.
    """

    def _form(self):
        return _read(os.path.join(DCIM, '_form.html'))

    def test_se_puede_elegir_un_modelo_del_catalogo(self):
        js = self._form()
        i = js.index("    item: {url: 'items'")
        assert "'type_uid'" in js[i:js.index(']},', i)],             'para colocar una tapa hay que declararle una plantilla otra vez'

    def test_se_BUSCA_y_no_se_ofrece_entero(self):
        """El catálogo son miles de filas. Un desplegable de miles no es un desplegable, y un
        campo de texto con el identificador son treinta y seis caracteres que no dicen nada."""
        js = self._form()
        assert 'function _dcimPickOpen(' in js and "pick: 'type'" in js
        assert 'dcim/catalog?tree=' in _fn(js, '_dcimPickGo'), 'ya no busca en el catálogo'

    def test_la_casilla_enseña_el_nombre_y_guarda_el_uid(self):
        cuerpo = _fn(self._form(), '_dcimPickBox')
        assert "type=\"hidden\"" in cuerpo, 'el identificador ya no viaja como lo espera guardar'
        assert '_dcimPickName(' in cuerpo, 'la casilla vuelve a enseñar el identificador'

    def test_quien_escribe_el_nombre_y_quien_lo_lee_miran_la_misma_clave(self):
        """Este guardián decía `'_name' in cuerpo` y con eso daba por buena la casilla que se
        pasó semanas enseñando el identificador: leía `type_uid_name` —la convención— cuando el
        armario manda `type_name`, y `'_name' in …` es cierto en los dos casos. Comprobar que
        aparece un trozo de nombre de clave no es comprobar que sea LA clave.
        """
        js = self._form()
        assert 'function _dcimPickName(' in js, 'vuelve a haber dos sitios decidiendo dónde'
        # Y quien lo escribe al elegir del catálogo, en la misma: si uno escribe donde el otro
        # no mira, elegir un modelo lo deja elegido y la caja sigue con lo de antes.
        assert 'fld.nameKey' in _fn(js, '_dcimPickTake'),             'al elegir se escribe el nombre donde la casilla no lo busca'

    def test_la_clave_declarada_es_una_que_el_armario_manda(self):
        """`nameKey: 'X'` con una X que nadie manda no da ningún error: da una casilla con el
        identificador dentro, que es justo lo que esta casilla existe para no enseñar."""
        js = self._form()
        claves = re.findall(r"nameKey:\s*'([a-z_]+)'", js)
        assert claves, 'ya no se declara ninguna clave de nombre'
        rutas = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes', 'racks.py'))
        for k in claves:
            assert f"item['{k}']" in rutas, f'nadie manda {k}: la casilla enseñará el uid'

    def test_y_buscar_no_borra_lo_tecleado(self):
        """El buscador y el formulario son el mismo cuadro: enseñar uno borra el marcado del
        otro, y con él las ocho casillas que se llevaban escritas."""
        assert '_dcimFormSnap()' in _fn(self._form(), '_dcimPickOpen'),             'buscar un modelo vacía el formulario'


class TestLaRegletaSeEligeYNoSeAcuna:
    """«+ Regleta» acuñaba `PDU-A` sin preguntar, y ahí estaba la razón de que la regleta que
    alguien acababa de colocar en el armario no apareciera nunca como sitio donde enchufar: la
    regleta que se COLOCA y la regleta que DA TOMAS son dos filas distintas, y no había ni una
    pantalla desde la que juntarlas.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_power.html'))

    def test_el_boton_pregunta_cual(self):
        cuerpo = _fn(self._js(), '_dcPduNew')
        assert 'showHtmlModal(' in cuerpo, 'el botón vuelve a acuñar una regleta sin preguntar'
        assert '_dcPduFromItem(' in cuerpo, 'de la lista no se puede elegir un equipo colocado'

    def test_se_elige_de_lo_colocado_sin_mirar_el_rol(self):
        """El aviso de arriba sí mira el rol, y un rol vacío —que es como nace todo lo que se
        coloca desde el catálogo— lo deja mudo. La lista de la que se elige no puede depender de
        que alguien haya dicho antes lo que se está preguntando ahora."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcPduNew'))
        assert '_dcimRack' in cuerpo and 'items' in cuerpo,             'la lista ya no sale de lo que está colocado en el armario'
        # El TAMIZ, y sólo él: `.sort` puede mirar el rol —poner las regletas declaradas
        # arriba es ordenar, no excluir— y el primer trozo de esta guarda decía `.split(…)[1]`
        # sobre el primer `.filter(` que apareciera, que era otro. Una guarda que recorta por
        # donde no es da por buena cualquier cosa; es la trampa de la ficha de al lado.
        i = cuerpo.index('const libres')
        tamiz = cuerpo[cuerpo.index('.filter(', i):cuerpo.index('.sort(', i)]
        assert 'role' not in tamiz,             'volver a tamizar por rol deja fuera lo que se acaba de colocar, que nace sin él'

    def test_no_se_ofrece_dos_veces_la_misma(self):
        """Sin saber cuáles están ya declaradas, la lista ofrece la misma otra vez y la segunda
        crea una regleta duplicada del mismo cacharro."""
        assert 'item_uid' in _fn(self._js(), '_dcPduNew'),             'la lista no sabe cuáles están ya declaradas'
        svc = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'service.py'))
        assert "'item_uid': str(p.get('item_uid') or '')" in svc,             'la respuesta no dice de qué equipo es cada regleta'

    def test_lo_ajeno_no_se_declara(self):
        """Un armario compartido enseña que el U está ocupado y nada más: declarar como regleta
        propia el equipo del vecino sería escribir sobre su inventario."""
        assert 'foreign' in _fn(self._js(), '_dcPduNew'), 'se ofrece el equipo del vecino'

    def test_queda_la_que_no_ocupa_ningun_U(self):
        """La atornillada al lateral es la mitad de los casos y la única que de verdad no tiene
        ningún equipo al que apuntar."""
        js = self._js()
        assert 'function _dcPduPlain(' in js or 'async function _dcPduPlain(' in js,             'la regleta que no está colocada ya no se puede declarar'
        assert '_dcPduPlain()' in _fn(js, '_dcPduNew'), 'esa opción no está en el cuadro'

    def test_elegir_cierra_el_cuadro(self):
        """El cuadro y el resto de la sección se dibujan en sitios distintos: repintar el fondo
        deja el cuadro delante, y lo elegido pasa a estar hecho detrás de una lista que sigue
        pidiendo que se elija."""
        for fn in ('_dcPduFromItem', '_dcPduPlain'):
            assert 'hideInfoModal()' in _fn(self._js(), fn), f'{fn} deja el cuadro abierto'


class TestNingunDesplegableEnsenaUnIdentificador:
    """Cuarta vez en esta sección que un desplegable acaba enseñando treinta y seis caracteres
    que no dicen nada. La regla es la misma en los cuatro sitios: cómo se lee un item lo dice
    UNA función, y quien la copia se queda fuera el día que esa función mejora.
    """

    #: Dónde se nombra un equipo del armario, y en qué función de cada fichero.
    NOMBRAN = (('_power.html', ('_dcPowerItems', '_dcPowerWarnings', '_dcPduUndeclared',
                                '_dcPduNew')),
               ('_cables.html', ('_dcCableTable',)))

    def test_ninguna_pestana_se_conforma_con_el_rotulo(self):
        """`label` es lo que está rotulado por delante, y está vacío en la mitad de lo que hay
        dentro de un armario: tapas, bandejas, regletas y cualquier cosa colocada el primer día.
        Tres filas seguidas diciendo «Equipo» no distinguen tres equipos, que es exactamente
        para lo que se abre esa tabla — y el navegador tenía el nombre entero delante.
        """
        for fichero, funciones in self.NOMBRAN:
            js = _read(os.path.join(DCIM, fichero))
            for fn in funciones:
                cuerpo = _strip_comments(_fn(js, fn))
                assert '_dcimNameOf(' in cuerpo or '_dcimItemName(' in cuerpo,                     f'{fichero}:{fn} nombra un equipo por su cuenta'

    def test_y_no_queda_ningun_respaldo_a_Equipo(self):
        """El respaldo que tapaba el fallo: «Equipo» parece un nombre, así que la fila no se ve
        rota — se ve repetida."""
        for fichero, _ in self.NOMBRAN:
            js = _strip_comments(_read(os.path.join(DCIM, fichero)))
            assert "label || t('dcim_item')" not in js, f'{fichero} vuelve al respaldo genérico'
            assert "_label || '—'" not in js, f'{fichero} deja un extremo sin nombre'

    def test_el_nombre_sale_de_un_solo_sitio(self):
        """`_dcimNameOf` busca la fila del armario y la nombra con `_dcimItemName`. Dos pasos y
        una función: quien copie sólo el primero se queda con el `label` otra vez."""
        js = _read(os.path.join(DCIM, '_form.html'))
        cuerpo = _fn(js, '_dcimNameOf')
        assert '_dcimItemName(' in cuerpo, 'nombra sin usar la función que nombra'
        assert '_dcimRack' in cuerpo, 'no busca la fila del armario abierto'

    def test_sobre_que_va_montado_se_lee_con_la_funcion_de_siempre(self):
        # Sin la prosa: el comentario que explica la regla nombra justo lo que la guarda
        # prohíbe, y una guarda que lee su propia explicación falla por tenerla.
        js = _strip_comments(_read(os.path.join(DCIM, '_form.html')))
        i = js.index('mounts: {')
        trozo = js[i:js.index('};', i)]
        assert '_dcimItemName(i)' in trozo,             'el desplegable vuelve a enseñar el uid de lo que no está rotulado'
        assert 'i.label || i.uid' not in trozo, 'vuelve a haber una copia de esa regla'


class TestLoQueNoLlevaEnchufeNoPideUno:
    """La bandeja salía en la tabla de alimentación diciendo «No lleva enchufe» y con el botón de
    enchufar al lado: una respuesta y su contraria en la misma fila.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_power.html'))

    def test_no_se_le_ofrece_enchufar(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcPowerItems'))
        i = cuerpo.index('_dcFeedNew(')
        # La condición que decide si se pinta el botón, no una mención cualquiera del rol.
        cond = cuerpo[cuerpo.rindex('${', 0, i):i]
        assert '_dcPowerQuiet(it)' in cond, 'se le sigue ofreciendo un enchufe a una bandeja'

    def test_ni_ocupa_una_fila_para_decir_que_no(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcPowerItems'))
        assert 'const mudos' in cuerpo and 'filas.map(' in cuerpo,             'la tabla vuelve a recorrer todos los equipos'

    def test_pero_no_se_esconde(self):
        """Esconder es lo que hace dudar de una lista: quien cuenta filas se queda preguntando
        si falta algo. Es la misma decisión que el recuento de un armario, que saca los pasivos
        de «sin vigilar» y los cuenta aparte."""
        js = self._js()
        assert 'function _dcPowerQuietNote(' in js, 'lo que no lleva enchufe desaparece sin más'
        assert 'dcim_no_plug_list' in js, 'no se dice cuáles son'

    def test_salvo_que_alguien_le_haya_declarado_un_cable(self):
        """Eso es un hecho escrito, y una fila que no se dibuja es un cable que no se puede ni
        ver ni quitar."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcPowerItems'))
        i = cuerpo.index('const mudos')
        assert 'feeds.length' in cuerpo[i:cuerpo.index('\n', i) + 200],             'una bandeja con un cable declarado se queda sin fila donde quitarlo'


class TestEnQueTomaSeEnchufa:
    """`outlet` existía desde el primer commit, la API la aceptaba y la tabla la pintaba, y
    ningún camino la escribía nunca: valía siempre 0, que es «no sé en cuál».
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_power.html'))

    def test_enchufar_pregunta_la_toma(self):
        js = self._js()
        cuerpo = _strip_comments(_fn(js, '_dcFeedNew'))
        assert '_dcFeedPickDraw()' in cuerpo, 'vuelve a enchufar sin decir dónde'
        assert 'showHtmlModal(' in _fn(js, '_dcFeedPickDraw')

    def test_y_la_manda(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcFeedPut'))
        assert 'outlet' in cuerpo, 'la toma elegida no llega al servidor'

    def test_las_ocupadas_no_se_pueden_pulsar(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcFeedPduHtml'))
        assert 'outlets_used' in cuerpo, 'no se sabe cuáles están ocupadas'
        assert 'disabled' in cuerpo, 'se puede elegir una toma que ya tiene un cable'

    def test_no_saber_en_cual_sigue_siendo_elegible(self):
        """Obligar a inventarse un número es cambiar un hueco por un dato falso."""
        assert 'dcim_outlet_unknown' in _fn(self._js(), '_dcFeedPduHtml'),             'ya no se puede decir «no sé en cuál»'

    def test_el_choque_lo_dice_el_servidor(self):
        """Repetir aquí la comprobación sería una segunda copia de la regla, y un día una de
        las dos dirá otra cosa."""
        rutas = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes', 'power.py'))
        assert 'def _outlet_bad(' in rutas, 'el servidor acepta dos cables en la misma toma'
        for clave in ('dcim_outlet_taken', 'dcim_outlet_out_of_range'):
            assert clave in rutas, f'{clave} no se usa'

    def test_y_se_puede_corregir_despues(self):
        """Sin quitar el cable y volverlo a poner, que se lleva por delante lo declarado."""
        js = self._js()
        assert 'function _dcFeedMove(' in js, 'una toma mal puesta se queda mal puesta'
        assert "'PUT'" in _fn(js, '_dcFeedPut'), 'cambiar de toma vuelve a crear un cable'

    def test_y_desde_la_seccion_de_cableado_tambien(self):
        """**Cuarta pantalla con la misma forma de fallo.** El elector de tomas leía
        `_dcPower.items` —el estado de la pestaña de un armario— y desde la sección de cableado
        vale `null`: «Cambiar de toma» reventaba antes de dibujar nada y no hacía nada. Ni
        ventana, ni aviso. Reportado desde la pantalla.

        Las regletas se piden si no se tienen, y **en su propio estado**: `_dcPower` es de la
        pestaña de un armario, y pisarlo con el de otro dejaría esa pantalla contando las tomas
        de una sala en la que no está.
        """
        js = self._js()
        for fn in ('_dcFeedPickDraw', '_dcFeedPduHtml'):
            assert '_dcPower' not in _strip_comments(_fn(js, fn)), fn
        cuerpo = _strip_comments(_fn(js, '_dcOutletsLoad'))
        assert '/power' in cuerpo, 'no se piden las regletas del armario de la regleta'
        assert 'rack_uid' in cuerpo, 'se piden las del armario del equipo y no las de la regleta'
        assert 'await _dcOutletsLoad(' in _strip_comments(_fn(js, '_dcFeedMove'))

    def test_y_su_ficha_se_lee_como_la_de_datos(self):
        """Son dos pantallas que hacen lo mismo: se parecen o no según quién las tocara la
        última, y la que se queda atrás es la que parece rota."""
        js = self._js()
        ficha = _strip_comments(_fn(js, '_dcFeedInfo'))
        # Un renglón que sólo existe a veces, que es lo que hacía que un cable sin inventario y
        # sin metros pareciera un cable del que eso no se puede decir. El valor sí puede ser
        # condicional —«—» cuando está vacío—; el renglón, no.
        for campo in ('dcim_item_asset', 'dcim_cable_cat', 'dcim_cable_len',
                      'dcim_feed_watts', 'dcim_description'):
            assert _renglon_fijo(ficha, campo), f'{campo}: el renglón vuelve a esconderse'
        forma = _strip_comments(_fn(js, '_dcFeedEditDraw'))
        assert 'ss-fgrid' in forma and 'flex-wrap' not in forma, 'sigue siendo una fila'
        assert forma.count('ss-zone-h') >= 2, 'las casillas van sin rótulos de grupo'
        assert '<textarea' in forma, 'la descripción sigue siendo un renglón'
        assert '<select' in _strip_comments(_fn(js, '_dcFeedCatBox')),             'el par de conectores vuelve a ser una lista que no se ve'
        assert 'max-width' not in _strip_comments(_fn(js, '_dcFeedBox'))


class TestLaFichaNoOfreceLoImposible:
    """Dos casillas seguidas rotuladas «Tipo» —la rama del catálogo y el rol— y la segunda
    ofreciendo «panel de parcheo» aunque la primera dijera «Armario», porque caía al respaldo de
    «todas las clases». Así es como un panel de parcheo acaba escrito como modelo de armario: sin
    salir al buscar un modelo para un rack, y sin dónde declarar sus puertos.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_catalog.html'))

    def test_sin_clases_que_ofrecer_no_hay_casilla(self):
        js = _strip_comments(self._js())
        i = js.index("_dcCatForm.kind=this.value")
        trozo = js[js.rindex('${', 0, i) - 400:i]
        assert 'kinds_by_tree' in trozo and '.length ?' in trozo,             'la casilla del rol se dibuja siempre'

    def test_y_no_cae_al_respaldo_de_todas(self):
        """`d.all_kinds` es la lista entera: cayendo a ella, el árbol deja de decidir nada y la
        casilla vuelve a ofrecer un panel de parcheo para un armario."""
        assert 'all_kinds' not in _strip_comments(self._js()),             'el respaldo que hacía que el árbol no decidiera nada vuelve a estar a mano'

    def test_una_ficha_ya_guardada_en_la_rama_mala_lo_dice(self):
        """Que la casilla ya no exista arregla las de mañana y no las de ayer, y a las de ayer
        no les queda ni la casilla donde se veía el error."""
        js = self._js()
        assert 'function _dcCatTreeMismatch(' in js, 'una ficha mal guardada no dice nada'
        cuerpo = _strip_comments(_fn(js, '_dcCatTreeMismatch'))
        assert "'rack-types'" in cuerpo and 'f.kind' in cuerpo
        assert '_dcCatTreeFix()' in cuerpo, 'lo dice y no deja arreglarlo'

    def test_y_moverla_no_pierde_el_rol(self):
        """Es lo que alguien ya dijo que era, y era lo único de la ficha que estaba bien."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCatTreeFix'))
        assert 'kind' not in cuerpo, 'mover la ficha borra lo único que estaba bien'
        assert "tree = 'device-types'" in cuerpo


class TestNingunDesplegableEnsenaUnIdentificadorDeLaBiblioteca:
    """`4-post-frame` es lo que escribe NetBox: un identificador, no una frase. El panel tiene
    desde hace tiempo un traductor de valores con el crudo como respaldo, y esta lista era la
    única que se saltaba el paso — así que la forma de un armario salía en inglés y con guiones
    en medio de un formulario en castellano.
    """

    def test_la_forma_de_un_armario_se_traduce(self):
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_catalog.html')),
                                     '_dcCatRackFields'))
        assert '_dcEnumName(a)' in cuerpo, 'la forma vuelve a salir como la escribió NetBox'

    def test_y_hay_una_palabra_para_cada_una(self):
        """Un traductor con respaldo no falla: deja pasar el crudo, que es exactamente lo que
        hacía. Lo que se comprueba es que la palabra exista."""
        js = _read(os.path.join(DCIM, '_catalog.html'))
        i = js.index('_dcCatFormExtra.form_factor')
        formas = re.findall(r"'([0-9a-z-]+(?:-frame|-cabinet))'", js[i:i + 700])
        assert formas, 'ya no se ofrecen formas'
        es = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', 'es_ES.py'))
        en = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', 'en_EN.py'))
        for f in formas:
            clave = "'dcim_val_" + f.replace('-', '_') + "'"
            assert clave in es and clave in en, f'{f} sale sin traducir'

    def test_la_casilla_de_la_numeracion_tiene_nombre(self):
        """Salía como `desc_units` —el nombre de la columna— en un formulario donde todo lo
        demás está en castellano."""
        es = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', 'es_ES.py'))
        en = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', 'en_EN.py'))
        for texto in (es, en):
            assert "'dcim_attr_desc_units'" in texto

    def test_las_dos_casillas_seguidas_no_se_llaman_igual(self):
        """La rama del catálogo y el rol estaban las dos rotuladas «Tipo», una al lado de la
        otra. Un rótulo que no distingue es un rótulo que no dice nada."""
        es = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', 'es_ES.py'))
        rama = re.search(r"'dcim_cat_kind':\s*'([^']+)'", es)
        rol = re.search(r"'dcim_role':\s*'([^']+)'", es)
        assert rama and rol and rama.group(1) != rol.group(1),             'las dos casillas del catálogo vuelven a llamarse igual'


class TestCadaHuecoDelPanelLlevaSuConector:
    """Un panel keystone se compra vacío: los huecos son del modelo y lo que se les mete es de
    cada panel. Poder decir qué hay en el hueco 7 es la única pregunta que se le hace a esto.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_parts.html'))

    def test_los_huecos_salen_tambien_del_modelo_del_equipo(self):
        """Miraba solo la plantilla, y un panel de parcheo no nace de ninguna."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCompSlots'))
        assert '_dcParts' in cuerpo and 'model' in cuerpo,             'la ficha de un equipo vuelve a quedarse sin lista de huecos'

    def test_y_si_el_modelo_solo_dijo_cuantos_se_numeran(self):
        """«Tiene veinticuatro y no sé cómo se llaman» no es «no tiene ninguno», y era lo segundo
        lo que pasaba con un panel escrito a mano."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCompSlots'))
        assert '_dcBaySeed(' in cuerpo, 'un modelo que solo dice el número se queda sin lista'

    def test_con_los_mismos_nombres_que_la_plantilla(self):
        """Dos que numeren igual acaban numerando distinto, y entonces el hueco 7 de la
        plantilla y el 7 del equipo dejan de ser el mismo."""
        js = _strip_comments(self._js())
        assert '_dcBaySeed' in js and 'function _dcBaySeed' not in js,             'la pantalla de los componentes numera los huecos por su cuenta'

    def test_un_conector_de_panel_tiene_su_propia_lista_de_sitios(self):
        """No es «lo de dentro» —no es una ranura de la placa— ni «lo que cuelga» —no está
        enchufado por fuera—. Sin una lista propia habría que mentir en `mount`."""
        js = self._js()
        assert '_DC_KIND_FAMS' in js, 'un conector de panel vuelve a no tener dónde ir'
        i = js.index('const _DC_KIND_FAMS')
        assert 'jack' in js[i:i + 200] and 'front-ports' in js[i:i + 200]

    def test_cambiar_la_clase_repinta_el_formulario(self):
        """La clase decide de qué lista salen los huecos, así que cambiarla sin repintar deja la
        mitad derecha del formulario contestando a la clase anterior."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCompFieldsHtml'))
        i = cuerpo.index('_dcCompDraft.kind=this.value')
        assert 'renderDcim()' in cuerpo[i:i + 60],             'cambiar la clase deja los huecos de la clase de antes'

    def test_y_el_hueco_se_llama_hueco(self):
        """Nadie llama «puerto» ni «bahía» a donde entra un keystone."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcSlotWord'))
        assert 'dcim_part_hole' in cuerpo
        assert '_DC_KIND_FAMS' in cuerpo, 'la palabra no sale de la clase'


class TestLaTablaYElDibujoLeenEnElMismoSentido:
    """Un armario puede numerar del suelo al techo —lo normal— o al revés, y eso va serigrafiado
    en el mástil. La tabla ordenaba «de la U más alta a la más baja», que sólo coincide con el
    dibujo en el primer caso: en uno numerado al revés el dibujo bajaba del 1 al 6 y la tabla del
    6 al 1, las dos hablando del mismo armario y ninguna equivocada por su cuenta.
    """

    def test_la_tabla_ordena_por_donde_cae_en_el_dibujo(self):
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_rack.html')),
                                     '_dcimItemsTable'))
        assert '_dcimUFromTop(' in cuerpo,             'la tabla vuelve a ordenar por número de U y no por sitio'
        assert '(b.u_start || 0) - (a.u_start || 0)' not in cuerpo,             'vuelve a haber una copia de la regla de numeración'

    def test_la_regla_de_la_numeracion_esta_en_un_solo_sitio(self):
        """Tres copias son tres que se separan, y separarse aquí es que soltar algo en el 3 lo
        escriba en el 4."""
        js = _strip_comments(_read(os.path.join(DCIM, '_elevation.html')))
        assert 'function _dcimUFromTop(' in js and 'function _dcimUAtRow(' in js
        # El sentido se lee dentro de esas dos y en ninguna otra: fuera de ellas, `desc_units`
        # sólo puede aparecer como el nombre de un campo, nunca decidiendo hacia dónde se cuenta.
        dentro = _fn(js, '_dcimUFromTop') + _fn(js, '_dcimUAtRow')
        assert js.count('desc_units') == dentro.count('desc_units'),             'alguien vuelve a decidir por su cuenta hacia dónde numera un armario'

    def test_y_el_dibujo_la_usa_por_los_dos_lados(self):
        """`_dceY` coloca y `_dceUAt` lee dónde se soltó algo: son la misma regla del derecho y
        del revés, y la que se quede sin tocar es la que descuadra el arrastre."""
        js = _read(os.path.join(DCIM, '_elevation.html'))
        assert '_dcimUFromTop(rack, u)' in _fn(js, '_dceY')
        assert '_dcimUAtRow(rack, fromTop)' in _fn(js, '_dceUAt')


class TestUnaPestanaSinNumeroPareceVacia:
    """Los recuentos salían de los datos de cada pestaña, así que estaban en blanco hasta que
    alguien entraba — y el de alimentación, cuando por fin aparecía, contaba las tres ramas
    porque la respuesta traía una clave `feeds` que no eran cables.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_rack.html'))

    def test_los_numeros_salen_del_armario_hasta_que_la_pestana_los_diga(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcRackPanelHtml'))
        assert 'counts' in cuerpo, 'las pestañas vuelven a estar en blanco hasta abrirlas'
        for clave in ('n.cables', 'n.power', 'n.hist'):
            assert clave in cuerpo, f'{clave} no se usa'

    def test_la_alimentacion_cuenta_cables_y_no_ramas(self):
        js = self._js()
        assert '_dcPower.feeds' not in _strip_comments(js),             'el contador vuelve a leer las ramas como si fueran cables'
        assert 'function _dcPowerN(' in js
        assert 'it.feeds' in _fn(js, '_dcPowerN'), 'no cuenta los cables de cada equipo'

    def test_el_cableado_dice_lo_que_falta_por_apuntar(self):
        """Sin esto, un armario con tres enlaces por apuntar y ninguno apuntado enseña una
        pestaña sin número, que es lo mismo que enseña uno terminado."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcRackPanelHtml'))
        assert 'undeclared' in cuerpo, 'lo que falta por declarar no se ve desde la pestaña'
        assert 'function _dcTabWarn(' in _read(os.path.join(DCIM, '_render.html'))


class TestElDescubrimientoProponeYNoDecide:
    """Lo que manda es lo apuntado. Si el panel escribiera lo que ve, lo visto y lo declarado
    serían la misma cifra y el contraste —la única razón de esa pestaña— no podría decir nunca
    «esto se movió», porque se habría movido también lo declarado.
    """

    def test_hay_un_boton_que_lo_declara(self):
        js = _read(os.path.join(DCIM, '_cables.html'))
        assert 'function _dcCableFromSeen(' in js, 'un enlace visto sólo se puede mirar'
        assert '_dcCableFromSeen(' in _fn(js, '_dcUndeclared'), 'el botón no está en la fila'

    def test_y_entra_por_la_misma_puerta_que_el_formulario(self):
        """Un cable declarado desde ahí y otro escrito a mano tienen que ser la misma fila, o el
        contraste compararía dos cosas distintas."""
        js = _read(os.path.join(DCIM, '_cables.html'))
        assert "'/api/v1/dcim/cables'" in _fn(js, '_dcCableFromSeen')
        assert "'/api/v1/dcim/cables'" in _fn(js, '_dcCableSave')

    def test_pero_nada_lo_escribe_solo(self):
        """Ni un camino que declare lo visto sin que nadie lo pulse."""
        svc = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'service.py'))
        i = svc.index('def cable_check(')
        cuerpo = svc[i:svc.index(chr(10) + 'def ', i + 1)]
        assert '.create(' not in cuerpo and 'store' not in cuerpo,             'el contraste escribe, y entonces deja de ser un contraste'
        # Y la pantalla lo declara sólo con un clic: nada lo llama al pintar.
        js = _read(os.path.join(DCIM, '_cables.html'))
        assert '_dcCableFromSeen(' not in _fn(js, '_dcCablesHtml'),             'la pantalla declara enlaces al dibujarse'


class TestLaFichaDeUnCable:
    """Cuatro columnas contestan «¿cuadra?» y poco más. Un agregado de cuatro puertos salía como
    «Router01 — SW01 · Coincide», sin bocas y sin número, que es justo el que más hay que mirar.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_la_fila_se_pulsa(self):
        js = self._js()
        assert 'function _dcCableInfo(' in js, 'una fila de cable no lleva a ninguna parte'
        cuerpo = _strip_comments(_fn(js, '_dcCableTable'))
        assert '_dcCableInfo(' in cuerpo and 'ss-rowlink' in cuerpo,             'la fila no se puede pulsar, o no lo parece'

    def test_y_el_boton_de_borrar_no_abre_la_ficha(self):
        """Un clic que hace dos cosas hace la que no era."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableTable'))
        i = cuerpo.index('_dcCableDrop(')
        assert 'event.stopPropagation()' in cuerpo[max(0, i - 120):i],             'borrar un cable abre además su ficha'

    def test_la_ficha_enseña_lo_declarado_y_lo_visto(self):
        """Lo declarado es lo que tiene que haber y lo visto es lo que hay ahora: enseñar sólo
        una convertiría esta pantalla en la otra."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableInfo'))
        for clave in ('a_port', 'b_port', 'ports_seen', 'bundle'):
            assert clave in cuerpo, f'la ficha no dice {clave}'

    def test_y_la_fila_avisa_de_que_son_varios(self):
        """Sin abrir nada: un renglón que parece un cable y son cuatro no se distingue de uno
        que es uno."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableTable'))
        assert 'c.bundle' in cuerpo, 'un agregado sigue pareciendo un solo latiguillo'


class TestPorDetrasElOrdenSeInvierte:
    """Un armario visto por la espalda tiene la izquierda donde tenía la derecha. Los dos mini PC
    de una bandeja salían en el mismo orden en las dos caras, y eso no es una preferencia de
    dibujo: quien va con un destornillador a la parte de atrás encuentra el primero a la derecha,
    y un alzado que dice lo contrario le hace desenchufar el que no era.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_elevation.html'))

    def test_hay_una_sola_funcion_que_da_la_vuelta(self):
        """Lo horizontal se reparte en dos sitios —el trozo de U de una caja y el sitio de lo que
        va montado dentro— y el que se quedara sin dar la vuelta dibujaría media bandeja al revés
        que la otra media."""
        assert 'function _dceFlipX(' in self._js()

    def test_y_la_usan_TODOS_los_repartos_horizontales(self):
        """Uno por uno y no «en algún sitio de la función». `_dceKidRect` tiene tres salidas —dos
        reparten a lo ancho y una a lo alto— y comprobar que la vuelta aparece *alguna vez*
        daba por buena la que dibuja los dos mini PC de una bandeja sin darla, que es
        exactamente la que se rompió."""
        js = self._js()
        assert '_dceFlipX(' in _strip_comments(_fn(js, '_dceRect')),             '_dceRect dibuja por detrás en el mismo sitio que por delante'
        cuerpo = _strip_comments(_fn(js, '_dceKidRect'))
        salidas = [x for x in cuerpo.split('return ')[1:]]
        assert len(salidas) == 3, f'cambiaron las salidas de _dceKidRect: {len(salidas)}'
        sin_vuelta = [x for x in salidas if not x.startswith('flip(')]
        assert len(sin_vuelta) == 1, 'una salida horizontal se quedó sin dar la vuelta'
        # Y la única que puede quedarse sin ella es la que reparte a lo ALTO.
        assert 'dentro.h / de' in sin_vuelta[0]

    def test_lo_montado_sabe_por_que_cara_se_mira(self):
        """Sin la cara, la función que da la vuelta no puede darla."""
        js = self._js()
        assert 'function _dceKidRect(caja, item, hermanos, gut, face)' in js
        assert 'gut, face)' in _strip_comments(_fn(js, '_dceKids'))

    def test_pero_en_vertical_no_se_toca(self):
        """La U 5 es la U 5 por delante y por detrás: el número está serigrafiado en los dos
        mástiles. Dar la vuelta a lo vertical movería un equipo de U al rodear el armario."""
        cuerpo = _strip_comments(_fn(self._js(), '_dceFlipX'))
        assert '.y' not in cuerpo and 'h:' not in cuerpo,             'la vuelta toca también lo vertical'
        # Y el reparto a lo alto de una bandeja tampoco: arriba sigue siendo arriba.
        kid = _strip_comments(_fn(self._js(), '_dceKidRect'))
        i = kid.index("'height'")
        # Hasta el final de ESE return y no un trozo a ojo: el siguiente sí lleva la vuelta, y
        # una ventana generosa se la come y da por rota una guarda que estaba bien.
        assert 'flip(' not in kid[i:kid.index('};', i)],             'lo repartido a lo alto se da la vuelta'

    def test_solo_por_detras(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dceFlipX'))
        assert "face !== 'rear'" in cuerpo, 'el frontal también sale al revés'


class TestLasBocasSoloDondeDicenAlgo:
    """En una fila que cuadra, las bocas que dicen los dispositivos son las mismas que ya están
    dos columnas a la izquierda: sólo alargan el renglón, y en un agregado son ocho nombres
    largos que empujan el resto de la tabla.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_apagadas_por_defecto(self):
        js = self._js()
        assert 'let _dcCablePorts = false;' in js, 'vuelven a salir siempre'

    def test_pero_se_pueden_encender(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcCablesHtml'))
        assert '_dcCablePorts=this.checked' in cuerpo, 'no hay forma de verlas'
        assert 'dcim_cable_show_ports' in cuerpo

    def test_y_cuando_NO_cuadran_salen_igual(self):
        """Ahí son la respuesta a «¿entonces dónde está enchufado?», que es la única pregunta
        que esa fila deja abierta."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableTable'))
        i = cuerpo.index('ports_seen')
        assert "other_port" in cuerpo[max(0, i - 160):i + 80],             'apagar el interruptor esconde también las que no cuadran'


class TestElMapaDeLaFlotaSeLeeUnaVez:
    """El comentario de esa función dice que la tabla de estado es una de las dos lecturas caras
    del camino y que por eso se hace para toda la flota de golpe — y se hacía dos veces, con dos
    nombres, a doce líneas de distancia. No da ningún error: da una pantalla que tarda el doble
    de lo que su propio comentario explica.
    """

    def test_la_tabla_de_estado_se_lee_una_sola_vez(self):
        svc = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'service.py'))
        i = svc.index('def topology(')
        # Hasta la siguiente función o hasta el final: `topology` es hoy la última del
        # fichero, y buscar un `def` que no está deja la guarda reventando en vez de
        # comprobando.
        j = svc.find(chr(10) + 'def ', i + 1)
        cuerpo = _strip_comments(svc[i:] if j < 0 else svc[i:j])
        assert cuerpo.count('_read_check_status()') == 1,             'el mapa vuelve a leer la tabla de estado dos veces'


class TestLasCuatroListasDelArmarioSeDibujanIgual:
    """Son cuatro listas del mismo armario, se leen una detrás de otra y se miran juntas: una que
    salga a otro tamaño no parece otra tabla, parece otra pantalla. Y la de equipos iba a
    `ss-fs-3` mientras alimentación y cableado iban al tamaño de fábrica.
    """

    #: Los ficheros que dibujan una tabla del panel de un armario.
    TABLAS = ('_rack.html', '_cables.html', '_power.html')

    def test_hay_una_constante_y_no_seis_copias(self):
        assert 'const _DC_TBL =' in _read(os.path.join(DCIM, '_render.html'))

    def test_y_ninguna_tabla_del_panel_se_dibuja_por_su_cuenta(self):
        for fichero in self.TABLAS:
            js = _strip_comments(_read(os.path.join(DCIM, fichero)))
            for linea in js.split(chr(10)):
                if 'class="table ' not in linea:
                    continue
                # La ficha de un cable vive en un cuadro y no en el panel: ahí manda el cuadro.
                assert 'ss-fs-2' in linea, f'{fichero}: una tabla con clases propias: {linea.strip()[:70]}'

    def test_los_rotulos_de_las_regletas_no_se_parten(self):
        """«Tomas libres» en dos líneas hace que la fila mida dos, y con dos tablas una encima de
        otra eso es lo que hacía que la pestaña pareciera de otra pantalla."""
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_power.html')), '_dcPduTable'))
        assert 'ss-nowrap' in cuerpo


class TestLaPestanaDeCableadoNoPagaElMapaEntero:
    """De todo el mapa, aquí sólo se leen los enlaces `lldp`. Armarlo entero incluye leer enteras
    las cuatro tablas de lo que cada equipo ha visto pasar, la de MAC entre ellas — se leían y se
    tiraban, y eso era la espera de esta pestaña.
    """

    def test_lo_pide_sin_la_evidencia(self):
        rutas = _strip_comments(_read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes',
                                                   'power.py')))
        i = rutas.index('_infra_topology')
        assert 'evidence=False' in rutas[i:i + 400],             'el cableado vuelve a pedir el mapa entero'

    def test_y_el_mapa_las_sigue_leyendo_para_quien_las_usa(self):
        """El mapa de infraestructura coloca una máquina en el puerto de un switch con ellas:
        quitarlas de ahí sería arreglar una pantalla rompiendo otra."""
        rutas = _strip_comments(_read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py')))
        assert 'evidence=True' in rutas, 'el mapa se queda sin la evidencia por defecto'


class TestLaTablaDeCablesSaleAntesQueSuContraste:
    """Esperar al mapa de la flota para poder pintar la primera fila deja la pestaña en blanco por
    un dato que ocupa la última columna.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_se_pide_en_dos_veces(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcCablesOpen'))
        assert cuerpo.count('apiGet(') == 2, 'vuelve a pedirse todo de una vez'
        assert "'?check=1'" in cuerpo or '?check=1' in cuerpo

    def test_y_lo_declarado_se_pinta_en_medio(self):
        """Sin ese redibujado, las dos peticiones se ven como una sola espera más larga."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCablesOpen'))
        i = cuerpo.index('?check=1')
        assert cuerpo[:i].count('renderDcim()') >= 2,             'la tabla no se dibuja hasta que llega el contraste'

    def test_no_se_pega_el_contraste_de_otro_armario(self):
        """Entre las dos peticiones se puede haber cambiado de armario."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCablesOpen'))
        assert 'ahora.uid !== rack.uid' in cuerpo, 'el contraste puede caer sobre otro armario'

    def test_mientras_llega_dice_que_esta_comprobando(self):
        """Y no «no se ve», que es un veredicto sin haber mirado."""
        js = self._js()
        assert 'dcim_cables_checking' in _strip_comments(_fn(js, '_dcCableTable')),             'una fila sin comprobar finge un veredicto'
        assert 'dcim_cables_checking' in _strip_comments(_fn(js, '_dcCablesHtml'))


class TestSeisVecesElMismoAvisoEsUno:
    """Seis equipos colgando de la rama A son seis renglones idénticos salvo el nombre, y lo que
    dicen es UN hecho: de esa rama cuelga todo. Media pantalla para repetir seis veces la misma
    frase, justo encima de la tabla que se venía a mirar — y una lista de avisos que hay que
    saltarse deja de leerse, que es lo contrario de para lo que está.
    """

    def _fn(self):
        return _strip_comments(_fn(_read(os.path.join(DCIM, '_power.html')),
                                   '_dcPowerWarnings'))

    def test_los_de_una_sola_rama_se_agrupan(self):
        cuerpo = self._fn()
        assert 'dcim_warn_single_branch_n' in cuerpo, 'vuelve a haber un renglón por equipo'

    def test_por_rama_y_no_todos_juntos(self):
        """Colgar solo de la A y colgar solo de la B no es el mismo aviso: se apagan con cortes
        distintos, y juntarlos diría que se apagan a la vez."""
        cuerpo = self._fn()
        assert 'solas[rama]' in cuerpo

    def test_uno_solo_sigue_hablando_en_singular(self):
        cuerpo = self._fn()
        assert "quienes.length === 1" in cuerpo,             'un equipo solo sale en plural, o con una lista de uno'

    def test_pero_las_cargas_no_se_agrupan(self):
        """Cada una es una regleta distinta con su porcentaje, y juntar dos cifras que no son la
        misma sólo se puede hacer perdiendo las dos."""
        cuerpo = self._fn()
        assert 'dcim_warn_over_half' in cuerpo and 'otros' in cuerpo

    def test_y_una_lista_larga_no_se_come_la_pantalla(self):
        """Que es de lo que iba todo esto."""
        js = _read(os.path.join(DCIM, '_power.html'))
        assert 'function _dcNames(' in js
        cuerpo = _strip_comments(_fn(js, '_dcNames'))
        assert '_DC_NAMES_MAX' in cuerpo and 'dcim_and_more' in cuerpo,             'una lista de cuarenta nombres vuelve a salir entera'


class TestUnCableSePuedePartir:
    """Los enlaces se apuntan primero de punta a punta y los paneles aparecen después. Sin partir
    el cable, corregirlo es borrarlo y escribir tres: se pierden la etiqueta, el color y las dos
    bocas, así que no se corrige y el inventario se queda diciendo que hay un latiguillo donde
    hay tres.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_se_llega_desde_la_ficha_del_cable(self):
        js = self._js()
        assert 'function _dcCableSplit(' in js
        assert '_dcCableSplit(' in _strip_comments(_fn(js, '_dcCableInfo')),             'partir un cable no se puede pedir desde ninguna parte'

    def test_el_panel_se_busca_en_cualquier_armario(self):
        """Casi nunca está en el armario del servidor: vive en el de patcheo."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcSplitGo'))
        assert '/api/v1/dcim/items?q=' in cuerpo,             'sólo se puede elegir un panel del armario abierto'

    def test_primero_el_tramo_nuevo_y_despues_se_mueve_el_viejo(self):
        """Al revés, un fallo a mitad deja el enlace acabando en el panel y sin salida: un cable
        a ninguna parte que nadie sabría que hay que arreglar."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcSplitSave'))
        assert cuerpo.index("'POST'") < cuerpo.index("'PUT'"),             'se mueve el cable antes de tener dónde seguir'

    def test_y_el_de_siempre_conserva_lo_suyo(self):
        """Repartir la etiqueta entre los dos daría dos cables llamados igual, que en una lista
        de cables es lo mismo que no llamarse. Y lo mismo el inventario, los metros y la
        categoría: mover una punta no cambia qué cable es."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcSplitSave'))
        i = cuerpo.index("'PUT'")
        for campo in ('label', 'asset', 'length_mm', 'category'):
            assert campo not in cuerpo[i:], f'mover el cable le cambia {campo}'

    def test_y_se_dice_por_que_lado_entra_el_panel(self):
        """**El cable que ya existe se quedaba SIEMPRE con el extremo A**, sin decirlo.

        En la mitad de los casos el latiguillo que de verdad sobrevive es el otro —se mete un
        panel de sala entre el servidor y el switch y el cable que uno tiene en la mano es el del
        lado del switch—, y entonces su etiqueta, su número de inventario y sus metros acaban en
        el tramo equivocado. No da ningún error: quedan dos cables bien declarados y uno de los
        dos miente.
        """
        js = self._js()
        assert '_dcSplit.side=this.value' in js, 'no se puede elegir el lado'
        cuerpo = _strip_comments(_fn(js, '_dcSplitSave'))
        assert 'p.side' in cuerpo, 'guardar no mira el lado elegido'
        # Y lo que se mueve es la punta del lado que se SUELTA, no siempre la misma.
        i = cuerpo.index("'PUT'")
        assert 'a_item' in cuerpo[i:] and 'b_item' in cuerpo[i:], 'el lado que se mueve es fijo'

    def test_la_ficha_dice_tambien_lo_que_FALTA(self):
        """Un cable sin número de inventario y sin metros salía con tres renglones y sin una
        pista de que le faltaran: las casillas vacías no se dibujaban, así que la ficha decía
        «esto es lo que hay de este cable» cuando lo que quería decir era «esto es lo único que
        alguien ha escrito». **Un hueco es un dato**, y es justo el que hay que ir a rellenar."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableInfo'))
        for campo in ('dcim_item_asset', 'dcim_cable_len', 'dcim_cable_color',
                      'dcim_description'):
            assert campo in cuerpo, campo
        for campo in ('dcim_item_asset', 'dcim_cable_len', 'dcim_cable_color',
                      'dcim_description'):
            assert _renglon_fijo(cuerpo, campo), f'{campo}: el renglón vuelve a esconderse'

    def test_y_el_formulario_se_reparte_como_la_ficha(self):
        """Eran ocho casillas en una fila que se envuelve, cada una con su ancho puesto a ojo:
        los grupos los hacía el ancho de la ventana. El mismo arreglo que la ficha de un equipo,
        por el mismo motivo — y con la tirada delante, que es cuando hace falta: los metros se
        ponen después de haber visto los tres tramos."""
        js = self._js()
        cuerpo = _strip_comments(_fn(js, '_dcCableEditDraw'))
        assert 'ss-fgrid' in cuerpo and 'flex-wrap' not in cuerpo, 'sigue siendo una fila'
        assert cuerpo.count('ss-zone-h') >= 2, 'las casillas van sin rótulos de grupo'
        assert 'tirada' in cuerpo, 'se corrige sin ver por dónde pasa'
        # Y las casillas sin ancho propio: lo reparte la rejilla.
        assert 'max-width' not in _strip_comments(_fn(js, '_dcEdBox'))

    def test_la_descripcion_es_de_varias_lineas(self):
        """Lo que se escribe ahí es «el latiguillo pasa por detrás del armario y llega justo», no
        una palabra: en un renglón de una línea eso se escribe a ciegas, viendo los últimos
        cuarenta caracteres."""
        js = self._js()
        assert '<textarea' in _strip_comments(_fn(js, '_dcEdArea'))
        assert '_dcEdArea(' in _strip_comments(_fn(js, '_dcCableEditDraw'))

    def test_y_el_color_se_puede_elegir_de_los_que_hay(self):
        """La rueda de dieciséis millones deja la instalación con nueve azules que no son el
        mismo azul. Los corrientes los dice el SERVIDOR, como las categorías: una segunda copia
        aquí es la que se queda sin el color que se añada mañana. Y los dos escriben en la misma
        casilla — dos que guardaran cada uno lo suyo serían dos valores para un campo."""
        js = self._js()
        cuerpo = _strip_comments(_fn(js, '_dcColorBox'))
        assert 'v.colors' in cuerpo, 'la pantalla lleva su propia lista de colores'
        assert 'type="color"' in cuerpo, 'se pierde la rueda para un color que no está'
        assert 'colors' in _strip_comments(_fn(js, '_dcCableVocab'))

    def test_y_primero_los_colores_que_ya_se_usan(self):
        """**Lo que de verdad se elige es lo que ya está puesto.** Si el azul de esta sala es un
        azul concreto que llevan cuarenta cables, el cuarenta y uno tiene que ser ESE — y buscarlo
        en la rueda a ojo es cómo una instalación acaba con nueve azules que no son el mismo.

        Los cuenta el servidor sobre la tabla, del más puesto al menos: una lista escrita a mano
        es la que no sabe qué colores usa esta casa.
        """
        js = self._js()
        cuerpo = _strip_comments(_fn(js, '_dcColorBox'))
        assert 'v.used' in cuerpo, 'no se ofrecen los colores que ya se usan'
        assert cuerpo.index('usados') < cuerpo.index('corrientes'), 'los usados no van primero'
        # Y uno que además sea de los corrientes sale UNA vez, en «usados», que es donde se busca.
        assert 'puestos.has' in cuerpo, 'un color puede salir dos veces en el mismo desplegable'
        assert 'used' in _strip_comments(_fn(js, '_dcCableVocab'))
        rutas = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes', 'power.py'))
        assert 'colors_used(' in rutas, 'el servidor no los cuenta'
        # Y de TODAS las tablas que llevan color: un latiguillo rojo y un cable de corriente rojo
        # son el mismo rojo, y contarlos por separado daría dos colores de veinte en vez de uno
        # de cuarenta.
        assert 'def colors_used(' in _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'store.py'))

    def test_el_tipo_de_un_cable_no_dice_de_que_esta_hecho(self):
        """La columna se llamaba «De qué es» y ponía «cobre» en unas filas y «corriente» en
        otras: **un cable de corriente también es de cobre**, y una consola también. Son dos ejes
        distintos metidos en una palabra, y la palabra elegida era la del eje equivocado — el que
        sólo vale para los de red.

        Lo que la lista contesta es qué clase de cable es, que es lo que hay que pedir para
        sustituirlo. Los de red dicen además de qué, entre paréntesis, porque ahí sí hace falta:
        un latiguillo de cobre y una fibra no se sustituyen el uno por el otro.
        """
        for lang in ('es_ES', 'en_EN'):
            d = _lang(lang)
            assert 'qué es' not in d['dcim_cable_kind'].lower(), lang
            # Y los tres de red lo dicen: sin eso, «cobre» al lado de «corriente» sigue leyéndose
            # como dos respuestas a la misma pregunta.
            de_red = [d['dcim_cable_' + k] for k in ('copper', 'fiber', 'dac')]
            assert all('(' in x for x in de_red), (lang, de_red)
            assert d['dcim_cable_kind_col'] != d['dcim_cable_kind'],                 f'{lang}: la cabecera de columna es el rótulo largo, y parte cada fila en dos'

    def test_y_el_color_se_elige_de_MUESTRAS(self):
        """**Un `<select>` con cada opción pintada de su color es lo que dice el estándar y lo
        que hacen dos navegadores de tres.** El tercero —y es el que se usa aquí— ignora el fondo
        de un `<option>` y deja una lista de `#3b82f6` uno debajo de otro: elegir un color
        leyendo códigos hexadecimales no es elegir un color. Reportado desde la pantalla, con la
        lista de códigos delante.

        Con botones el color se ve en todos, y el código se queda en el `title`. Y **fuera del
        `<label>`**: un botón dentro de la etiqueta de un campo le pasa el clic al campo, así que
        pulsar una muestra abriría la rueda del sistema encima.
        """
        js = self._js()
        cuerpo = _strip_comments(_fn(js, '_dcChipHtml'))
        assert '<button' in cuerpo and 'ss-chip' in cuerpo, 'vuelve a ser una lista de códigos'
        assert 'style="background:${escAttr(hex)}"' in cuerpo, 'la muestra no se pinta'
        assert 'type="button"' in cuerpo, 'una muestra dentro de un formulario lo envía'
        caja = _strip_comments(_fn(js, '_dcColorBox'))
        assert '<select' not in caja, 'vuelve el desplegable que no pinta'
        assert caja.index('</label>') < caja.index('_dcChipsHtml'),             'las muestras vuelven a estar dentro de la etiqueta, y el clic se lo lleva el campo'
        # Y **dentro de un desplegable**: sueltas debajo del campo son dos filas de cuadraditos
        # permanentes en un formulario donde el color es una casilla de nueve — lo que más ocupa
        # es lo que menos se toca.
        assert 'dropdown-menu' in caja and 'data-bs-toggle="dropdown"' in caja

    def test_y_sin_color_es_un_valor_que_se_puede_elegir(self):
        """**Un `<input type="color">` no tiene estado vacío**: siempre vale un color, así que un
        cable sin color declarado salía pintado de azul —el que la rueda trae de fábrica— y no
        había manera de volver a «ninguno». Un campo que no puede estar en blanco convierte
        «nadie lo ha dicho» en una respuesta que nadie dio. Reportado desde la pantalla.

        Lo que se guarda es una casilla escondida: la rueda no puede guardar «sin color» y la
        lista no puede guardar uno que no esté en ella, así que ninguna de las dos es el valor.
        """
        js = self._js()
        caja = _strip_comments(_fn(js, '_dcColorBox'))
        assert 'type="hidden" id="${escAttr(id)}"' in caja, 'vuelve a guardar la rueda'
        assert "_dcChipHtml(id, '', valor)" in caja, 'no se puede elegir «sin color»'
        # Y la rueda, dentro del desplegable: es una opción más —«otro color»— y no el control.
        assert caja.index('dropdown-menu') < caja.index('type="color"')

    def test_y_la_muestra_escribe_sin_redibujar(self):
        """Redibujar el formulario para marcar la elegida tiraría lo tecleado en las otras
        casillas, que es exactamente lo que nadie espera al pulsar un color."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcColorSet'))
        assert "el.value = String(hex || '')" in cuerpo, 'la muestra no llega a lo que se guarda'
        assert 'ss-chip-on' in cuerpo, 'no se marca cuál está puesta'
        assert '_dcColorFaceHtml' in cuerpo, 'el botón no dice qué color quedó puesto'
        assert '_dcCableInfo' not in cuerpo, 'redibuja la ficha y se pierde lo tecleado'
        # Se cierra al elegir una MUESTRA y no arrastrando por la rueda: de ahí llegan diez
        # `input` por segundo, y cerrar en el primero deja el color a medio elegir.
        assert 'boton &&' in cuerpo, 'el desplegable se cierra al primer tirón de la rueda'
        assert 'Dropdown' in cuerpo and 'hide()' in cuerpo, 'el desplegable se queda abierto'

    def test_y_la_lista_se_queda_con_la_respuesta_entera(self):
        """Copiando campo a campo, lo que el servidor añada mañana se tira hoy. Pasó: los colores
        ya usados viajaban en la respuesta y esta carga se quedaba con cuatro claves, así que el
        desplegable salía vacío en la sección de cableado y lleno en la pestaña de un armario —
        el mismo dato, dos comportamientos, y ninguno de los dos daba un error."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcWireLoad'))
        assert 'Object.assign({}, d' in cuerpo, 'la carga vuelve a copiar campo a campo'

    def test_y_un_cable_de_corriente_tambien_tiene_color(self):
        """Es con lo que se encuentra en un mazo de treinta detrás de un armario, y eso no
        depende de por dónde acabe el cable."""
        esquema = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'store.py'))
        feed = esquema.split("name='dc_feed'")[1].split('indexes=')[0]
        assert "Column('color'" in feed, 'la tabla no lo guarda'
        js = _read(os.path.join(DCIM, '_power.html'))
        assert "_dcColorBox('dcf-c'" in _strip_comments(_fn(js, '_dcFeedEditDraw'))
        assert "color: val('dcf-c')" in _strip_comments(_fn(js, '_dcFeedEdSave')),             'se puede elegir y no se guarda'

    def test_y_el_color_de_la_rama_no_se_hace_pasar_por_el_del_cable(self):
        """La lista de cableado pintaba cada cable de corriente con el color de su rama, y lo
        metía en el mismo campo: la ficha lo enseñaba como si fuera el del latiguillo y corregir
        cualquier otra cosa lo guardaba encima. Se pinta el del cable y, si no lo tiene, el de su
        rama — que es lo que hacía falta de aquello."""
        rutas = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes', 'power.py'))
        assert 'branch_color=' in rutas, 'el color de la rama vuelve a pisar el del cable'
        cuerpo = _strip_comments(_fn(self._js(), '_dcwCell'))
        assert 'c.color || c.branch_color' in cuerpo, 'la lista deja de pintar el de la rama'

    def test_el_panel_se_pide_desde_la_punta(self):
        """Es la misma decisión que el desplegable del lado, dicha donde se ve: se pulsa la punta
        por la que ese cable sigue siendo el que se tiene en la mano. Un botón al pie obliga a
        traducir «lado A» a «el extremo del switch» mirando hacia arriba.

        Y sólo en las dos puntas **del cable abierto**: en una tirada de tres tramos, las de los
        otros dos son sus puntas y meterles un panel sería partir otro cable.
        """
        js = self._js()
        assert 'function _dcCableSplitAt(' in js
        parada = _strip_comments(_fn(js, '_dcPathStopHtml'))
        assert '_dcCableSplitAt(' in parada
        assert 'parteDe &&' in parada, 'el botón sale en cualquier parada'
        camino = _strip_comments(_fn(js, '_dcPathHtml'))
        assert 'abierto' in camino and 'mia' in camino, 'el botón sale en paradas que no son suyas'
        # De qué lado es esa punta lo decide la FILA del cable: la tirada se recorre de punta a
        # punta y la mitad de los tramos están guardados al revés.
        assert 'c.a_item' in _strip_comments(_fn(js, '_dcCableSplitAt'))

    def test_y_el_boton_del_pie_solo_queda_donde_no_hay_dibujo(self):
        """Dos formas de hacer lo mismo son dos sitios donde arreglarlo. Se queda como respaldo
        para cuando la tirada no llegó: sin dibujo no hay punta que pulsar."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableInfo'))
        assert '&& !tirada' in cuerpo, 'el botón del pie compite con las puntas'

    def test_y_la_cuenta_se_ensena_hecha(self):
        """Los dos tramos con los nombres puestos y «este» donde va el que ya existe. Una frase
        que describa lo que va a pasar hay que leerla dos veces; dos renglones se miran."""
        js = self._js()
        assert 'function _dcSplitLegsHtml(' in js
        assert '_dcSplitLegsHtml(' in _strip_comments(_fn(js, '_dcSplitDraw'))


class TestLaBusquedaDelPanelNoEnsenaIdentificadores:
    """`r.label || r.uid` deja treinta y seis caracteres donde tenía que ir «Generico Regleta 8»
    o «Bandeja». La misma copia de la regla que ya se quitó del desplegable de «va montado en».
    """

    def test_se_nombra_con_la_funcion_de_siempre(self):
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_cables.html')), '_dcSplitDraw'))
        assert '_dcimItemName(r)' in cuerpo, 'la lista vuelve a enseñar el identificador'
        assert 'r.label || r.uid' not in cuerpo, 'vuelve a haber una copia de esa regla'

    def test_y_el_servidor_manda_los_cuatro_datos_que_hacen_falta(self):
        """Esa función mira etiqueta, máquina, modelo y rol: mandar sólo la etiqueta la deja
        cayendo al identificador igual."""
        rutas = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes', 'racks.py'))
        i = rutas.index('def api_dcim_items_find(')
        cuerpo = rutas[i:rutas.index('@app.route', i)]
        for clave in ("'label'", "'type_name'", "'host_uid'", "'role'"):
            assert clave in cuerpo, f'la búsqueda no manda {clave}'


class TestLaFichaEnsenaPorDondePasa:
    """La fila dice «Por el panel» y ahí se acaba: cuál de los cuatro paneles de la sala, y en
    cuál de sus veinticuatro posiciones, había que reconstruirlo a mano cable a cable.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_la_ficha_pinta_el_camino(self):
        js = self._js()
        assert 'function _dcPathHtml(' in js
        # Por `_dcRunHtml`, que es quien decide si hay tirada que enseñar: con un solo tramo
        # no hay nada que contar —es el propio cable, y sus dos puntas están dos renglones más
        # arriba— y un dibujo de un tramo es ruido con forma de información.
        assert '_dcRunHtml' in _strip_comments(_fn(js, '_dcCableInfo')),             'la ficha no enseña por dónde pasa'
        assert '_dcPathHtml' in _strip_comments(_fn(js, '_dcRunHtml'))

    def test_y_marca_el_tramo_que_se_esta_mirando(self):
        """Un camino de cuatro tramos, sin saber cuál se tiene abierto, obliga a compararlos uno
        a uno."""
        js = self._js()
        assert 'abierto' in _strip_comments(_fn(js, '_dcPathHtml'))
        cuerpo = _strip_comments(_fn(js, '_dcPathLegHtml'))
        assert 'l.cable' in cuerpo and 'ss-path-mine' in cuerpo

    def test_con_los_nombres_que_manda_el_servidor(self):
        """La pantalla sólo tiene los equipos de SU armario, y un camino sale del armario."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcPathHtml'))
        assert 'l.a_label' in cuerpo and 'l.b_label' in cuerpo,             'la traza vuelve a enseñar identificadores fuera del armario abierto'


class TestUnCableSeInventaria:
    """`length_mm` y `description` existían desde el primer commit y ningún camino las escribía.
    Séptima vez que sale esta forma en esta sección: una columna que nadie puede escribir vale
    siempre su valor por defecto, y el código que la respeta parece que funciona.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_el_alta_pregunta_lo_que_hay_que_saber_de_un_cable(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableSave'))
        for campo in ('category', 'length_mm', 'description', 'kind'):
            assert campo in cuerpo, f'{campo} no se manda al guardar'

    def test_los_metros_se_piden_en_metros(self):
        """Nadie mide un latiguillo en milímetros y todo el mundo lo compra en metros. La
        conversión vive en UN sitio: dos copias son dos que se separan, y la que se quede sin el
        cambio guardará metros en una columna de milímetros."""
        js = self._js()
        assert '* 1000' in _strip_comments(_fn(js, '_dcMetresIn'))
        for fn in ('_dcCableSave', '_dcCableEdSave'):
            assert '_dcMetresIn(' in _strip_comments(_fn(js, fn)), fn

    def test_y_se_pueden_escribir_con_coma(self):
        """En un navegador en castellano lo natural es teclear `0,2`, y con `type=number` eso
        llega vacío según el navegador: el cable se guardaba midiendo cero sin decir nada."""
        js = self._js()
        cuerpo = _strip_comments(_fn(js, '_dcMetresIn'))
        assert "replace(',', '.')" in cuerpo, 'la coma vuelve a perder lo tecleado'
        assert 'type="number"' not in _strip_comments(_fn(js, '_dcCableFormHtml')),             'el campo de los metros vuelve a ser numérico, que no acepta coma'

    def test_y_lo_que_no_es_un_numero_se_dice(self):
        """Cero es una longitud y «no se sabe» es otra cosa: guardar 0 en silencio pierde lo
        que alguien acababa de escribir."""
        js = self._js()
        assert ': null' in _strip_comments(_fn(js, '_dcMetresIn'))
        for fn in ('_dcCableSave', '_dcCableEdSave'):
            assert 'dcim_cable_len_bad' in _strip_comments(_fn(js, fn)), fn

    def test_la_categoria_depende_de_de_que_es_el_cable(self):
        """Un Cat 6A no es una categoría de fibra ni un OM4 una de cobre, y ofrecer las diez
        juntas es ofrecer equivocarse."""
        js = self._js()
        cuerpo = _strip_comments(_fn(js, '_dcCatBox'))
        assert 'cats || {})[kind]' in cuerpo, 'la lista deja de depender del tipo'
        # Y las dos pantallas que la usan le pasan el suyo: una caja que se lo mirara ella sola
        # ofrecería categorías de fibra en el alta de un cobre de la otra.
        assert "_dcCatBox('dcc-cat', _dcCableKind" in js
        assert "_dcCatBox('dce-cat', _dcCableEdKind" in js

    def test_la_ficha_no_lee_el_global_de_una_sola_de_sus_dos_listas(self):
        """**La ficha de un cable es UNA para dos pantallas.**

        Su vocabulario —de qué tipos y de qué categorías puede ser— lo leía de `_dcCables`, que
        es el de la pestaña de un armario. Abierta desde la sección de cableado ese global vale
        `null`, así que pulsar «Editar» reventaba con un TypeError antes de dibujar nada: ni
        ventana, ni aviso, ni rastro. Reportado desde la pantalla, con una captura de la ficha
        abierta y el botón sin efecto.

        Lo que se comprueba no es que esté guardado —`(_dcCables || {})` también lo estaría, y
        ofrecería una lista vacía sin decirlo— sino que **pasa por la función que sabe mirar en
        las dos**.
        """
        js = self._js()
        for fn in ('_dcCableEditDraw', '_dcCatBox', '_dcCableFormHtml',
                   # Y el dibujo de la tirada, por lo mismo: sacaba de la lista del armario la
                   # etiqueta, los metros y el color de cada tramo, así que desde la sección de
                   # cableado salía una tirada sin nada que distinga un tramo del de al lado.
                   '_dcPathHtml', '_dcPathLegHtml', '_dcPathTotalHtml',
                   # Y meter un panel en medio, que desde el cableado no guardaba nada: se
                   # quedaba con un cable vacío y `if (!c) return` hacía el resto en silencio.
                   '_dcSplitDraw', '_dcSplitSave'):
            # Sin contar `_dcCablesOpen()`, que es volver a la lista y no leerla: la ficha
            # vuelve a la pantalla de la que se vino, y eso es correcto en las dos.
            cuerpo = _strip_comments(_fn(js, fn)).replace('_dcCablesOpen', '')
            assert '_dcCables' not in cuerpo, (
                f'{fn} lee el global de la pestaña del armario: desde /dcim/wiring es null')
        vocab = _strip_comments(_fn(js, '_dcCableVocab'))
        assert '_dcCables' in vocab and '_dcWire' in vocab, 'el vocabulario mira una sola lista'

    def test_la_tirada_se_pide_por_cable_y_una_vez(self):
        """**Un enlace que atraviesa un panel son tres cables y una tirada**, y la ficha de uno
        de los tres enseñaba ese cable solo: «del panel A boca 12 al panel B boca 12», que no
        dice de dónde viene ni a dónde va.

        Por cable y no con la lista: calcularla para las doscientas filas de una búsqueda sería
        pagar doscientas veces lo que se mira una. Y **una vez por ficha abierta** — pedirla en
        cada redibujado sería una petición por cada tecla del formulario de corrección.
        """
        js = self._js()
        assert "/run" in _strip_comments(_fn(js, '_dcRunLoad')), 'la tirada no se pide'
        abrir = _strip_comments(_fn(js, '_dcCableInfo'))
        assert '_dcRun.uid !== String(uid)' in abrir, 'se vuelve a pedir en cada dibujado'
        # Y no se pega la del cable anterior sobre la ficha de al lado: entre la petición y la
        # respuesta se puede haber abierto otra.
        assert '_dcCableOpen' in _strip_comments(_fn(js, '_dcRunLoad'))

    def test_una_tirada_de_un_solo_tramo_tambien_se_dibuja(self):
        """Se dibujaba sólo con dos o más, porque con uno «sus dos puntas están en los renglones
        de al lado». Y no lo estaban: esos renglones sacaban el nombre de la lista del armario,
        que desde la sección de cableado no existe, así que un cable directo se quedaba con dos
        renglones que ponían «sin decir» y nada más. Reportado desde la pantalla."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcRunHtml'))
        assert 'length < 2' not in cuerpo, 'un cable directo vuelve a quedarse sin sus puntas'
        assert '(p.legs || []).length' in cuerpo, 'se dibuja una tirada vacía'

    def test_y_entonces_las_puntas_no_se_dicen_dos_veces(self):
        """El dibujo ya las da con nombre, boca, armario y U. Dos renglones repitiéndolas peor
        —sin el sitio— son ruido justo encima de lo que hay que leer."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableInfo'))
        i = cuerpo.index('dcim_cable_from')
        assert 'tirada ?' in cuerpo[max(0, i - 200):i], 'las puntas salen dos veces'

    def test_y_el_nombre_de_una_punta_sale_de_donde_lo_haya(self):
        """La lista del armario lo trae en `a_label` y la de cableado en `a_at.label`. Leyendo
        sólo el primero, los dos renglones de la ficha, la nota de partir y el dibujo de cómo
        queda salían con la boca y ni un nombre: cuatro sitios con la misma media lectura, que es
        la señal de que la regla tenía que estar en uno."""
        js = self._js()
        assert "at.label" in _strip_comments(_fn(js, '_dcEndName')),             'la punta vuelve a leer un solo sitio'
        for fn in ('_dcCableInfo', '_dcSplitDraw', '_dcSplitLegsHtml'):
            assert '_dcEndName(' in _strip_comments(_fn(js, fn)), fn

    def test_y_la_ficha_va_a_dos_columnas_solo_cuando_hay_tirada(self):
        """Los datos son renglones cortos y la tirada es alta y estrecha: uno debajo del otro
        dejan media ventana en blanco. Pero una columna vacía al lado no es un diseño, es un
        hueco — sin tirada, una sola."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableInfo'))
        assert "tirada ? 'ss-cable-two' : ''" in cuerpo, 'dos columnas siempre, o ninguna'
        assert "tirada ? 'wide' : 'fit'" in cuerpo, 'la talla no sigue al contenido'

    def test_y_no_promete_un_contraste_donde_no_lo_hay(self):
        """En la sección de cableado no hay contraste a propósito —es una pregunta sobre UN
        armario—, así que «Comprobando…» se quedaba puesto para siempre: un cartel de espera que
        no acaba es peor que decir dónde se mira."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableInfo'))
        assert 'dcim_cable_check_rack' in cuerpo, 'la espera no termina nunca en el cableado'

    def test_y_se_puede_escribir_una_que_no_esté(self):
        """Un fabricante que llame a lo suyo de otra manera no puede quedarse sin apuntarlo: la
        diferencia entre sugerir y obligar.

        Con un desplegable y una última opción que devuelve la casilla de escribir, y no con un
        `<datalist>`: ése no enseña que haya nada que elegir —la casilla se ve igual que una
        vacía—, así que las categorías estaban ahí y nadie las veía; «cat6» acababa escrito a
        mano, con sus erratas y su mayúscula distinta cada vez. Reportado desde la pantalla.
        """
        cuerpo = _strip_comments(_fn(self._js(), '_dcCatBox'))
        assert '<select' in cuerpo, 'la lista vuelve a no verse'
        assert 'dcim_cable_cat_other' in cuerpo, 'la lista pasa a ser obligatoria'
        assert '<input' in cuerpo, 'no queda dónde escribir la que no está'
        # Y una que ya está escrita y no figura en la lista **no se pierde**: la casilla sale
        # suelta, con lo que hay. Sin esto, abrir la ficha de un cable con una categoría rara y
        # guardar sin tocar nada la habría cambiado por la primera del desplegable.
        assert '!lista.includes(valor)' in cuerpo

    def test_y_quien_redibuja_no_lo_decide_la_casilla(self):
        """La misma casilla la usan la ficha de un cable —que se vuelve a abrir— y el alta de la
        pestaña —que se redibuja con ella—. Con la llamada escrita dentro, elegir «Otra…» en el
        alta abría la ficha de un cable."""
        js = self._js()
        assert 'redibuja' in _strip_comments(_fn(js, '_dcCatBox'))
        assert "'renderDcim();'" in js and "'_dcCableInfo(_dcCableOpen,true);'" in js


class TestElCaminoSeDibuja:
    """Una lista de tramos repite cada parada dos veces —final de uno y principio del siguiente—
    y leerla obliga a emparejarlas de cabeza, que es el trabajo que el dibujo existe para
    ahorrar.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_se_dibujan_paradas_y_no_tramos_sueltos(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcPathHtml'))
        assert 'paradas' in cuerpo and '_dcPathStopHtml(' in cuerpo

    def test_cada_parada_dice_donde_esta(self):
        """Con el armario y la U: «PP-A 25» no dice adónde hay que ir."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcPathStopHtml'))
        assert 'x.at.rack' in cuerpo and 'x.at.u' in cuerpo
        svc = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'service.py'))
        assert 'sitio_de' in svc, 'el servidor no manda dónde está cada punta'

    def test_y_de_lo_ajeno_no_se_dice_donde(self):
        """Un equipo ajeno llega opaco a propósito, y decir en qué armario está sería decir qué
        hay en la sala de otro por la puerta de al lado."""
        rutas = _strip_comments(_read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes',
                                                   'power.py')))
        i = rutas.index('nombres_rack')
        assert "foreign" in rutas[i:i + 400], 'el armario de un equipo ajeno se cuenta igual'

    def test_el_tramo_dice_con_que_se_distingue_de_otro_igual(self):
        # Del TRAMO y no buscándolo en una lista: la ficha se abre desde dos pantallas y sólo
        # una tiene lista cargada.
        cuerpo = _strip_comments(_fn(self._js(), '_dcPathLegHtml'))
        assert 'l.label' in cuerpo and 'l.category' in cuerpo and 'l.length_mm' in cuerpo


class TestElCaminoDiceCuantoMide:
    """Es la cifra que se busca al mirar un camino: si el enlace entero pasa de los cien metros
    de cobre, da igual lo bien declarado que esté — y eso no se ve mirando tres tramos por
    separado.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_se_suman_los_tramos(self):
        js = self._js()
        assert 'function _dcPathTotalHtml(' in js
        assert '_dcPathTotalHtml(' in _strip_comments(_fn(js, '_dcPathHtml'))

    def test_y_se_dice_cuantos_faltan_por_medir(self):
        """Sumar sólo los medidos y enseñarlo como el total es la peor forma de contestar: un
        camino de cuatro tramos con uno medido diría «0,25 m» y quien lo lea se lo cree."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcPathTotalHtml'))
        assert 'faltan' in cuerpo
        assert 'dcim_cable_path_at_least' in cuerpo and 'dcim_cable_path_total' in cuerpo


class TestUnCableSeCorrige:
    """Un cable se podía dar de alta y borrar, y nada más: la categoría, los metros y la nota se
    preguntaban una vez y ahí se acababa. Pero un cable se apunta con prisa —se está montando— y
    sus datos se completan después, con el metro en la mano.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_la_ficha_se_puede_editar(self):
        js = self._js()
        assert 'function _dcCableEditDraw(' in js
        assert '_dcCableInfo(' in _strip_comments(_fn(js, '_dcCableInfo')),             'no hay por dónde entrar a corregir un cable'

    def test_y_el_modo_es_de_esa_apertura_y_no_del_panel(self):
        """Era una variable que se encendía al pulsar «Editar» y sólo se apagaba al guardar:
        cerrando el cuadro sin guardar se quedaba encendida, y la siguiente fila que alguien
        pulsara abría el formulario de otro cable en vez de su ficha. Ni un error ni una pantalla
        en blanco — la ventana equivocada, que además parece la buena."""
        for fichero, fn in (('_cables.html', '_dcCableInfo'), ('_power.html', '_dcFeedInfo')):
            cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, fichero)), fn))
            # `_fn` corta DESPUÉS del paréntesis de apertura, así que la firma no está en el
            # cuerpo: se busca en el fichero. Recortar por donde no es da por buena cualquier
            # cosa — es la trampa de la ficha de `'_name' in cuerpo`.
            js = _read(os.path.join(DCIM, fichero))
            assert f'function {fn}(uid, editar)' in js, f'{fn} no recibe el modo'
            assert 'if (editar)' in cuerpo, f'{fn} decide el modo por una variable de fuera'

    def test_y_guarda_lo_que_se_corrige(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableEdSave'))
        for campo in ('label', 'category', 'length_mm', 'description', 'a_port', 'b_port'):
            assert campo in cuerpo, f'{campo} no se guarda al corregir'

    def test_pero_no_deja_mover_las_puntas(self):
        """Mover una punta es otra operación —«meter un panel en medio»— y ofrecerla mezclada con
        la etiqueta y los metros invita a rehacer el cableado creyendo que se corrige una
        errata."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableEdSave'))
        assert 'a_item' not in cuerpo and 'b_item' not in cuerpo


class TestUnCableDeCorrienteSeInventaria:
    """Corregirlo, cambiarlo de toma y desenchufarlo eran tres cosas escondidas en la misma chapa
    o en ninguna parte.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_power.html'))

    def test_la_chapa_abre_su_ficha(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcPowerItems'))
        assert '_dcFeedInfo(' in cuerpo, 'un cable de corriente no lleva a ninguna parte'

    def test_la_ficha_dice_lo_que_hace_falta_para_sustituirlo(self):
        cuerpo = _strip_comments(_fn(self._js(), '_dcFeedInfo'))
        for clave in ('f.asset', 'f.category', 'f.length_mm', 'f.description'):
            assert clave in cuerpo, f'la ficha no dice {clave}'

    def test_y_se_puede_corregir(self):
        js = self._js()
        assert 'function _dcFeedEditDraw(' in js
        cuerpo = _strip_comments(_fn(js, '_dcFeedEdSave'))
        for campo in ('asset', 'category', 'length_mm', 'watts_said', 'description'):
            assert campo in cuerpo, f'{campo} no se guarda'

    def test_los_metros_por_el_mismo_camino_que_los_de_datos(self):
        """Dos conversiones son dos que se separan, y la que se quede sin el cambio guardará
        metros en una columna de milímetros."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcFeedEdSave'))
        assert '_dcMetresIn(' in cuerpo and 'dcim_cable_len_bad' in cuerpo


class TestElNumeroDeInventarioNoEsLaEtiqueta:
    """`label` es lo rotulado en el cable —se repite, se borra, se equivoca— y el de inventario lo
    pone la casa y es único. Meter los dos en una casilla obliga a elegir cuál se pierde.
    """

    def test_son_dos_campos_en_el_alta(self):
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_cables.html')), '_dcCableSave'))
        assert "label: val('dcc-l')" in cuerpo and "asset: val('dcc-as')" in cuerpo

    def test_y_dos_en_la_correccion(self):
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_cables.html')),
                                     '_dcCableEdSave'))
        assert "label: val('dce-l')" in cuerpo and "asset: val('dce-as')" in cuerpo


class TestElArmarioSePuedeVerSinRotulos:
    """Con diez cajas y sus nombres encima, lo que se pierde es el dibujo: dónde quedan los
    huecos, qué ocupa media U, qué hay montado sobre qué. Y una foto para una presentación no
    lleva los nombres de la casa.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_elevation.html'))

    def test_hay_un_interruptor_y_viene_encendido(self):
        """Un armario sin rótulos no dice qué hay dentro: lo normal es verlos."""
        js = self._js()
        assert 'let _dceNames = true;' in js
        assert '_dceNamesToggle()' in _strip_comments(_fn(js, '_dceTools'))

    def test_lo_apaga_en_las_cajas_y_en_lo_montado(self):
        """Media bandeja con nombres y media sin no es ninguna de las dos vistas."""
        js = self._js()
        for fn in ('_dceItem', '_dceKids'):
            assert '_dceNames ?' in _strip_comments(_fn(js, fn)), fn

    def test_y_no_mueve_el_encuadre(self):
        """El dibujo mide lo mismo con letras y sin ellas: devolver el zoom a su sitio movería
        lo que se está mirando por quitar unas letras."""
        cuerpo = _strip_comments(_fn(self._js(), '_dceNamesToggle'))
        assert 'ssCanvasReset' not in cuerpo
        assert 'renderDcim()' in cuerpo, 'el botón no se repinta y se queda del color de antes'


class TestElCableadoTieneSuPantalla:
    """Dentro de un rack se contesta «qué sale de aquí». Las otras dos —dónde está este cable, y
    cuántos de esta categoría hay puestos— obligaban a saber el armario antes de buscar.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_cables.html'))

    def test_es_una_vista_de_la_seccion_con_su_direccion(self):
        """Una tira de pastillas dentro del panel no es una dirección: `/dcim/wiring` se pega en
        un chat, se marca y se puede elegir como pantalla de entrada."""
        cons = _read(os.path.join(SRC, 'lib', 'web_admin', 'constants.py'))
        assert "'slug': 'wiring'" in cons
        render = _strip_comments(_read(os.path.join(DCIM, '_render.html')))
        assert "_dcWire ? _dcWireHtml()" in render, 'la vista no se dibuja'
        assert "donde === 'wiring'" in render, 'no se puede ir a ella'
        assert "_dcWire = null;" in _fn(render, '_dcimGo'), 'salir de ella no la cierra'

    def test_la_ficha_es_la_MISMA_que_la_del_armario(self):
        """Dos fichas del mismo cable serían dos formas de escribir lo mismo, y la segunda
        tardaría meses en descubrirse."""
        js = self._js()
        assert '_dcCableInfo(' in _strip_comments(_fn(js, '_dcWireInfo'))
        assert 'function _dcCableOf(' in js, 'la ficha sólo sabe buscar en una de las listas'
        assert '_dcWire' in _strip_comments(_fn(js, '_dcCableOf'))

    def test_y_guardar_vuelve_a_la_lista_de_la_que_se_vino(self):
        """Recargar la otra deja lo corregido fuera de la vista, y una corrección que no se ve
        parece una que no se ha guardado."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcCableEdSave'))
        assert '_dcCableFrom' in cuerpo and '_dcWireReload()' in cuerpo

    def test_se_dice_cuando_la_lista_esta_recortada(self):
        """Una lista más corta que la realidad parece completa. En la cabecera de la tabla, que
        es donde van las condiciones de lo que se está mirando."""
        assert 'dcim_wire_capped' in _strip_comments(self._js())

    def test_y_usa_la_tabla_compartida_del_panel(self):
        """Una lista con su propio buscador y su propia paginación se comporta distinto que las
        otras diez sin ninguna razón: filtros, orden, columnas y paginación son los mismos que en
        Usuarios o Grupos."""
        js = self._js()
        assert 'createListTable({' in js, 'la lista se dibuja a mano'
        assert "key: 'dcwire'" in js
        # Y el hueco se rellena cuando ya está en el documento, no al componer el HTML.
        render = _strip_comments(_read(os.path.join(DCIM, '_render.html')))
        assert 'renderDcWire()' in render

    def test_estan_los_de_red_y_los_de_corriente(self):
        """Son la misma pregunta —dónde está este cable— y viven en dos tablas por dónde acaban,
        no por lo que son. Dos listas obligarían a buscar dos veces lo mismo."""
        rutas = _strip_comments(_read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes',
                                                   'power.py')))
        i = rutas.index('def api_dcim_cables_all(')
        cuerpo = rutas[i:rutas.index('@app.route', i)]
        assert 'store.feeds.list(' in cuerpo, 'los cables de corriente no salen en la lista'
        assert "wire='power'" in cuerpo and "wire='data'" in cuerpo
        # Y la ficha que se abre es la que toca: uno acaba en otro equipo y el otro en una toma.
        assert '_dcFeedInfo(' in _strip_comments(_fn(self._js(), '_dcWireInfo'))

    def test_y_cada_punta_dice_donde_esta(self):
        """Es la otra mitad de «dónde está este cable»."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcWireEnd'))
        assert 'a.rack' in cuerpo and 'a.u' in cuerpo
        assert 'dcim_foreign' in cuerpo, 'de una punta ajena se dice más de lo que se puede'
class TestLosEquiposTienenSuPantalla:
    """La misma forma que el cableado, a propósito: dos listas de la misma sección que se
    comportan distinto son dos cosas que aprender por la cara.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_devices.html'))

    def test_es_una_vista_de_la_seccion(self):
        cons = _read(os.path.join(SRC, 'lib', 'web_admin', 'constants.py'))
        assert "'slug': 'devices'" in cons
        render = _strip_comments(_read(os.path.join(DCIM, '_render.html')))
        assert '_dcDev ? _dcDevHtml()' in render
        assert "donde === 'devices'" in render
        assert '_dcDev = null;' in _fn(render, '_dcimGo')

    def test_usa_la_tabla_compartida_y_los_carriles(self):
        js = self._js()
        assert 'createListTable({' in js and "key: 'dcdev'" in js
        assert 'createViewState(' in js and 'DCDEV_VIEWS' in js

    def test_en_que_monton_cae_algo_lo_dice_UNA_funcion(self):
        """Las dos maquetas que agrupan miran la misma lista: lo único que tienen en común es en
        qué montón está cada cosa, y dos copias serían dos que se separan justo en eso."""
        js = _read(os.path.join(DCIM, '_devices.html'))
        assert 'function _dcDevGroupOf(' in js
        assert 'groupOf: (i) =>' in js, 'la tabla agrupada no sabe agrupar'
        assert '_dcDevGroupOf' in _strip_comments(_fn(js, '_dcDevTilesHtml')),             'los recuentos cuentan por su cuenta'

    def test_y_ninguna_pantalla_dibuja_carriles(self):
        """Se probaron cuatro maquetas y se eligieron tres. Lo que no se eligió se quita: código
        que no se dibuja es código que nadie mantiene y que el día que se toque no falla."""
        render = _read(os.path.join(DCIM, '_render.html'))
        assert '_ssLanes' not in render and '_ssBands' not in render
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-lane' not in css and '.ss-band' not in css

    def test_pulsar_lleva_al_equipo_a_su_armario(self):
        """Una ficha aquí sería una tercera forma de mirar lo mismo: lo que se quiere al pulsar
        es verlo en su sitio, que es donde está todo lo demás."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcDevGo'))
        assert '_dcimLoadRack(' in cuerpo and 'rack_uid' in cuerpo

    def test_la_garantia_se_puede_preguntar_a_la_lista_entera(self):
        """Es la pregunta que ya tenía dónde contestarse y no se contestaba."""
        js = self._js()
        assert 'function _dcDevWarrantyIs(' in js
        cuerpo = _strip_comments(_fn(js, '_dcDevWarrantyIs'))
        for cual in ("'none'", "'expired'"):
            assert cual in cuerpo, cual

    def test_y_sin_fecha_es_un_grupo_y_no_un_hueco(self):
        """Un equipo sin garantía apuntada es exactamente lo que hay que mirar antes de
        contestar, y esconderlo deja la respuesta corta y creíble."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcDevWarrantyIs'))
        i = cuerpo.index("'none'")
        assert 'return !s' in cuerpo[i:i + 60]


class TestActualizarNoRedibujaLaSeccion:
    """`renderDcim` reescribe el panel entero: tira el contenedor de la tabla, la barra de
    filtros y todo lo demás. Eso hace falta al ENTRAR en la vista y es exactamente lo que no hace
    falta al pulsar «Actualizar» — la pantalla ya está montada y lo único que cambia son las
    filas. El parpadeo era eso, y con él se perdía el foco de la barra de filtros: actualizar con
    algo escrito era perder dónde se estaba escribiendo.
    """

    #: Las dos listas de la sección que se piden al servidor y se actualizan.
    LISTAS = (('_cables.html', '_dcWireReload', 'renderDcWire'),
              ('_devices.html', '_dcDevReload', 'renderDcDev'))

    def test_actualizar_repinta_solo_su_tabla(self):
        for fichero, fn, pintar in self.LISTAS:
            js = _read(os.path.join(DCIM, fichero))
            cuerpo = _strip_comments(_fn(js, fn))
            assert f'{pintar}()' in cuerpo, f'{fn} no repinta la tabla'
            assert 'renderDcim()' not in cuerpo, f'{fn} vuelve a redibujar la sección entera'

    def test_y_el_boton_llama_a_eso(self):
        for fichero, fn, _p in self.LISTAS:
            js = _strip_comments(_read(os.path.join(DCIM, fichero)))
            i = js.index('refreshButton:')
            assert f'{fn}()' in js[i:i + 300], fichero

    def test_pero_ENTRAR_en_la_vista_si_la_dibuja(self):
        """El hueco de la tabla tiene que existir antes de que la tabla pueda escribir en él."""
        for fichero, fn, _p in self.LISTAS:
            abrir = fn.replace('Reload', 'Open')
            cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, fichero)), abrir))
            assert 'renderDcim()' in cuerpo, abrir


class TestLosEquiposPorEstado:
    """La pregunta que hace que esta lista sirva para algo más que contar: qué de lo que tengo
    está mal. Y las dos distinciones que la hacen útil — «sin vigilar» no es «bien», y lo que no
    contesta por naturaleza no está desatendido.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_devices.html'))

    def test_el_estado_es_un_criterio_de_agrupacion(self):
        js = self._js()
        assert "'state'" in js and 'DCDEV_GROUPS' in js
        assert 'function _dcDevState(' in js

    def test_lo_peor_va_primero(self):
        """Agrupado por estado, el carril gordo es el de lo que está bien: ordenarlos por tamaño
        deja lo que está mal al final de la fila."""
        js = self._js()
        i = js.index('_DCD_STATE_ORDER = [')
        orden = js[i:js.index(']', i)]
        assert orden.index('error') < orden.index('warning') < orden.index('ok')
        assert '_DCD_STATE_ORDER' in _strip_comments(_fn(js, '_dcDevGroupRank')),             'los montones de estado se ordenan por tamaño o por nombre'
        # Y el mismo orden en las cuatro: cambiar de maqueta no puede cambiar qué va primero.
        assert '_dcDevGroupRank' in _strip_comments(_fn(js, '_dcDevGroupOrder'))
        assert 'groupRank: (k) => _dcDevGroupRank(k)' in js

    def test_sin_vigilar_no_es_bien(self):
        """Un equipo sin máquina enganchada no está correcto, está sin mirar, y esa distinción
        es la mitad de para lo que sirve la pantalla."""
        js = self._js()
        i = js.index('_DCD_STATE_ORDER = [')
        orden = js[i:js.index(']', i)]
        assert "''" in orden and "'ok'" in orden, 'sin estado deja de ser un carril propio'

    def test_y_lo_que_no_contesta_por_naturaleza_va_aparte(self):
        """Un panel de parcheo no contesta porque no hay nada que preguntarle: meterlo entre los
        desatendidos llena la pantalla de deberes imposibles, que es la forma más rápida de que
        nadie vuelva a mirarla."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcDevState'))
        assert '_DC_QUIET_ROLES' in cuerpo and "'mudo'" in cuerpo

    def test_esa_lista_no_se_separa_de_la_del_nucleo(self):
        """Está copiada en la pantalla porque ésta no pide un armario; copiada y comprobada, que
        es distinto de copiada y olvidada."""
        js = self._js()
        i = js.index('_DC_QUIET_ROLES = [')
        en_pantalla = set(re.findall(r"'([a-z_]+)'", js[i:js.index(']', i)]))
        store = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'store.py'))
        j = store.index('ROLES_MUDOS = (')
        en_nucleo = set(re.findall(r"'([a-z_]+)'", store[j:store.index(')', j)]))
        assert en_pantalla == en_nucleo, (en_pantalla, en_nucleo)

    def test_y_la_columna_se_ordena_por_gravedad(self):
        """Alfabéticamente, «error, ok, sin vigilar, warning» pone lo que está mal en medio de
        lo que está bien."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcdSortValue'))
        assert '_DCD_STATE_ORDER.indexOf' in cuerpo


class TestTresMaquetasYLasMismasEnLasDosListas:
    """Se probaron cuatro y se eligieron tres: tabla, tabla agrupada y recuentos. Las mismas en
    Equipos y en Cableado — dos listas de la misma sección que se comportan distinto son dos
    cosas que aprender por la cara.
    """

    LISTAS = (('_devices.html', 'DCDEV_VIEWS'), ('_cables.html', 'DCWIRE_VIEWS'))

    def test_son_las_tres_en_las_dos(self):
        for fichero, const in self.LISTAS:
            js = _read(os.path.join(DCIM, fichero))
            i = js.index('const ' + const)
            bloque = js[i:js.index('];', i)]
            ids = set(re.findall(r"id: '([a-z]+)'", bloque))
            assert ids == {'table', 'grouped', 'tiles'}, (fichero, ids)

    def test_agrupar_y_dibujar_son_dos_preguntas(self):
        """Mezclarlas daría nueve vistas para contestar tres cosas."""
        for fichero, _c in self.LISTAS:
            js = _strip_comments(_read(os.path.join(DCIM, fichero)))
            assert 'GROUPS = [' in js, fichero
            assert 'BySwitcher()' in js, fichero

    def test_y_las_tres_son_la_misma_tabla(self):
        """Lo que cambia es si se agrupa y si lleva recuentos encima: no hay un segundo cuerpo
        que dibujar, así que no hay `cardsBody`."""
        for fichero, _c in self.LISTAS:
            js = _strip_comments(_read(os.path.join(DCIM, fichero)))
            assert 'cardsBody' not in js, fichero
            assert 'beforeBody:' in js and 'groupOf:' in js, fichero


class TestNingunaClasePropiaSeQuedaSinRegla:
    """Un `<span class="ss-dot">` sin regla no falla: es un hueco de cero píxeles con un color de
    fondo que nadie ve. Pasó — al quitar los carriles se fue por delante la regla del punto de
    estado, y el marcado seguía pintándolo perfectamente en ninguna parte.

    Es la misma forma de siempre en otro idioma: lo que se escribe y no se lleva vale su valor
    por defecto, y el valor por defecto de una clase que no existe es «nada».
    """

    def test_todas_las_clases_ss_de_la_seccion_estan_definidas(self):
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        usadas = set()
        for f in sorted(os.listdir(DCIM)):
            js = _read(os.path.join(DCIM, f))
            for attr in re.findall(r'class="([^"]*)"', js):
                for tok in attr.split():
                    # Lo que sale de una expresión de plantilla no es una clase: es el trozo de
                    # una. Se descarta, o la guarda perseguiría comillas.
                    tok = tok.strip(chr(39) + chr(34) + '{}%')
                    if tok.startswith('ss-') and '$' not in tok and '{' not in tok:
                        usadas.add(tok)
        assert usadas, 'la sección dejó de usar clases propias: la guarda no comprueba nada'
        sin_regla = sorted(c for c in usadas if ('.' + c) not in css)
        assert not sin_regla, f'clases sin ninguna regla: {sin_regla}'


class TestLoQueNoOcupaUSeDiceIgual:
    """Un SAI en el suelo no tiene U donde dibujarse. Ponerlo en la U 1 por no dejarlo fuera
    sería dibujar un armario que no existe; sacarlo del alzado sin más lo convertiría en algo que
    hay que recordar. Ni una cosa ni la otra: fuera del dibujo y **dicho debajo**.
    """

    def test_el_alzado_no_lo_dibuja(self):
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_elevation.html')), '_dceFace'))
        assert 'placement' in cuerpo, 'el alzado dibuja en la U 1 lo que no tiene U'

    def test_pero_lo_nombra_debajo(self):
        """Esconder es lo que hace dudar de un dibujo: quien cuenta cajas se queda preguntando
        si falta algo."""
        js = _read(os.path.join(DCIM, '_elevation.html'))
        assert 'function _dceBesideHtml(' in js
        assert '_dceBesideHtml(items)' in _strip_comments(_fn(js, '_dcimElevation'))

    def test_la_ficha_lo_pregunta_antes_que_los_U(self):
        """Es lo que decide si los U significan algo."""
        js = _strip_comments(_read(os.path.join(DCIM, '_form.html')))
        i = js.index("{name: 'placement'")
        j = js.index("{name: 'u_start'")
        assert i < j, 'los U se preguntan antes de saber si hacen falta'

    def test_y_es_UNA_decision_y_no_cinco_casos(self):
        """La regleta del lateral ya existía como caso particular con nombre propio; en cuanto
        hay un segundo, la pregunta de verdad se ve — y se contesta una vez."""
        store = _read(os.path.join(SRC, 'lib', 'core', 'dcim', 'store.py'))
        assert 'PLACEMENTS = ' in store
        i = store.index('PLACEMENTS = (')
        vals = set(re.findall(r"'([a-z]+)'", store[i:store.index(')', i)]))
        assert vals == {'u', 'side', 'near'}, vals
        # Y una sola comprobación decide: ni la ocupación ni el alzado saben de casos.
        assert store.count("placement') or 'u') != 'u'") == 1


class TestUnCampoQueNoSignificaNadaNoSePregunta:
    """Un SAI en el suelo al lado del armario seguía teniendo que decir en qué U está, y la
    respuesta era 1 porque la casilla venía con un 1 puesto. Un dato que se pide sin sentido no
    sale vacío: sale con su valor por defecto, y ése es una mentira con formato de dato.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_form.html'))

    def test_hay_un_mecanismo_y_no_diez_condiciones(self):
        """Quién pregunta qué es una sola regla; repartida sería la casilla que alguien se deja
        puesta."""
        js = self._js()
        assert 'function _dcimAsks(' in js
        cuerpo = _strip_comments(_fn(js, '_dcimFormBody'))
        assert '_dcimAsks(' in cuerpo, 'la ficha vuelve a dibujarlo todo siempre'

    def test_los_U_solo_de_lo_que_ocupa_un_U(self):
        js = _strip_comments(self._js())
        for campo in ("'u_start'", "'face'"):
            i = js.index('{name: ' + campo)
            assert 'when:' in js[i:js.index('},', i)], campo
        assert 'function _dcimTakesU(' in js
        cuerpo = _strip_comments(_fn(self._js(), '_dcimTakesU'))
        assert 'placement' in cuerpo and 'parent_uid' in cuerpo

    def test_ni_se_pide_lo_que_ya_dijo_la_plantilla_o_el_catalogo(self):
        """Volver a preguntar el alto es pedir que alguien confirme un número que no ha mirado —
        o que lo contradiga sin enterarse."""
        # Dentro del bloque del EQUIPO: un armario también tiene `u_height` —lo que mide— y
        # buscar el primero del fichero encuentra el del armario, que no es éste.
        js = _strip_comments(self._js())
        eq = js[js.index("item: {url: 'items'"):]
        i = eq.index("{name: 'u_height'")
        trozo = eq[i:eq.index('},', i)]
        assert 'build_uid' in trozo and 'type_uid' in trozo

    def test_y_cambiar_la_respuesta_redibuja_la_ficha(self):
        """Sin esto, elegir «al lado del armario» dejaba las casillas de U en pantalla: la ficha
        seguía preguntando por un sitio que la respuesta anterior acababa de dejar sin sentido."""
        js = _strip_comments(self._js())
        assert '_DCIM_DRIVE' in js
        for campo in ("'placement'", "'parent_uid'", "'build_uid'"):
            i = js.index('{name: ' + campo)
            assert 'drives: true' in js[i:js.index('},', i)], campo

    def test_lo_que_no_se_dibuja_no_se_manda(self):
        """La columna se queda con lo que tenía; lo que deja de tener sentido lo pone a cero el
        servidor, que es quien decide qué ocupa."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcimSave'))
        assert 'if (!el) return;' in cuerpo

    def test_y_la_lista_no_se_inventa_una_U(self):
        """Una fila que dice un número que nadie ha escrito es peor que una que no dice nada:
        alguien va a la U 1 a buscarlo."""
        cuerpo = _strip_comments(_fn(_read(os.path.join(DCIM, '_rack.html')), '_dcimItemRow'))
        assert 'dcim_place_col_' in cuerpo
        rutas = _strip_comments(_read(os.path.join(SRC, 'lib', 'core', 'dcim', 'routes',
                                                   'racks.py')))
        i = rutas.index("if puesto != 'u':")
        assert "data['u_start'] = 0" in rutas[i:i + 900],             'un equipo movido al suelo conserva la U que tenía'


class TestLoQueNoOcupaUVaDespuesDeLasU:
    """Ordenado con lo demás, un SAI del suelo caía entre la U 1 y la U 2. Eso no es una lista
    mal ordenada: es una lista que dice que el SAI está ahí. La columna dice «Al lado», sí, pero
    **el orden se lee antes que la columna**.
    """

    def _js(self):
        return _strip_comments(_fn(_read(os.path.join(DCIM, '_rack.html')),
                                   '_dcimItemsTable'))

    def test_van_en_su_zona_y_no_entre_las_U(self):
        cuerpo = self._js()
        assert 'const enU' in cuerpo and 'const fuera' in cuerpo,             'lo que no ocupa U vuelve a ordenarse entre lo que sí'
        assert 'rowsFuera' in cuerpo

    def test_con_su_cabecera_y_su_recuento(self):
        """Una zona sin rótulo son filas sueltas al final: parece que la tabla se ha estropeado
        en vez de que ahí empieza otra cosa."""
        cuerpo = self._js()
        assert 'ss-lt-group' in cuerpo and 'dcim_elev_beside' in cuerpo

    def test_pero_dentro_de_la_tabla(self):
        """Son equipos del armario, se alimentan y se cablean: sacarlos sería la misma
        equivocación por el otro lado."""
        cuerpo = self._js()
        i = cuerpo.index('<tbody>')
        assert 'rowsFuera.map(' in cuerpo[i:], 'se dibujan fuera de la tabla'

    def test_y_se_ordenan_por_nombre_entre_ellos(self):
        """No tienen altura por la que ordenarse, y el azar del identificador cambiaría el orden
        entre dos recargas de lo mismo."""
        cuerpo = self._js()
        i = cuerpo.index('const fuera')
        assert '_dcimItemName' in cuerpo[i:i + 260]

    def test_y_lo_montado_encima_sigue_a_lo_suyo(self):
        """Una máquina sobre una bandeja que está al lado del armario está al lado del armario:
        separarla de su bandeja la dejaría en la zona de las U."""
        cuerpo = self._js()
        # Las dos listas pasan por la misma función que cuelga los hijos de su padre: dos
        # copias serían dos que se separan, y lo que se separaría es de quién cuelga qué.
        assert 'conHijos(enU' in cuerpo and 'conHijos(fuera' in cuerpo


class TestLaFichaDeUnEquipoVaPorZonas:
    """Las casillas iban en una sola fila que se envuelve, así que los grupos los hacía el ancho
    de la ventana: «Máquina» acababa al lado de «Fondo del equipo» porque ahí cupo, y con la
    ventana medio palmo más estrecha eran otros dos. Un grupo que cambia de miembros al estirar
    el cuadro no es un grupo.
    """

    def _js(self):
        return _read(os.path.join(DCIM, '_form.html'))

    def _zonas(self):
        js = _strip_comments(self._js())
        i = js.index('const _DCIM_ZONES')
        return js[i:js.index(chr(10) + '};', i)]

    def _equipo(self):
        js = _strip_comments(self._js())
        eq = js[js.index("item: {url: 'items'"):]
        return eq[:eq.index(chr(10) + '    ]},')]

    def test_hay_zonas_declaradas(self):
        js = self._js()
        assert 'const _DCIM_ZONES' in js and 'function _dcimZoneHtml(' in js

    def test_solo_las_declara_el_equipo(self):
        """Una sede tiene cuatro casillas, y cinco rótulos para ordenar cuatro cosas es peor que
        ninguno."""
        bloque = self._zonas()
        assert bloque.count(': [') == 1 and 'item: [' in bloque

    def test_todas_las_casillas_del_equipo_tienen_zona(self):
        """Una casilla sin zona cae en la primera por descarte, y por descarte no es un sitio."""
        eq = self._equipo()
        campos = re.findall(r"name: '([a-z_]+)'", eq)
        sin = [c for c in campos if not re.search(
            r"name: '%s'[^}]*zone:" % c, eq, flags=re.S)]
        assert not sin, f'campos sin zona: {sin}'

    def test_y_todas_tienen_ayuda(self):
        """De diecisiete campos, uno la tenía. Un campo que no dice para qué es sólo lo rellena
        quien escribió el modelo."""
        eq = self._equipo()
        campos = re.findall(r"name: '([a-z_]+)'", eq)
        sin = [c for c in campos if not re.search(
            r"name: '%s'[^}]*tt:" % c, eq, flags=re.S)]
        assert not sin, f'campos sin ayuda: {sin}'

    def test_una_zona_sin_casillas_no_se_dibuja(self):
        """En un SAI que está en el suelo no hay ningún U que partir, y un título sobre un hueco
        vacío deja a quien lo lee buscando el campo que no está."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcimZoneHtml'))
        assert 'if (!dentro.length) return' in cuerpo

    def test_lo_raro_va_plegado(self):
        assert self._zonas().count('fold:') == 2, 'cambiaron los pliegues sin decirlo'

    def test_pero_lo_que_ya_esta_relleno_se_despliega_solo(self):
        """Esconder un dato escrito es peor que enseñar uno vacío: el que está escrito no se
        puede ni corregir ni descubrir."""
        assert self._zonas().count('open:') == 2,             'un pliegue esconde lo que alguien ya escribió'
        assert 'z.open(' in _strip_comments(_fn(self._js(), '_dcimZoneOn'))

    def test_y_la_zona_por_defecto_no_es_una_posicion(self):
        """Leerla del primer campo de la lista sería una posición haciendo de regla — el mismo
        fallo que ya tuvo «lo obligatorio es lo primero»."""
        cuerpo = _strip_comments(_fn(self._js(), '_dcimZoneHtml'))
        assert 'spec.fields[0]' not in cuerpo
        assert 'primera' in cuerpo
