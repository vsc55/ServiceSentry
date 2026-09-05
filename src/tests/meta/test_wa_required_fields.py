#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo obligatorio se ve, y se ve **antes** de pulsar guardar.

El panel siempre supo qué campos no se pueden dejar en blanco: cada formulario lo comprueba al
guardar y suelta un aviso. Pero eso lo dice **después de pulsar**, cuando el renglón ya se dio por
terminado, y sin señalar en cuál de las ocho cajas falta — que es la mitad de la pregunta.

La regla es una y está escrita una vez (`ssReqMark`, en `partials/core/_utils.html`): una caja
declarada `required` se marca en rojo mientras esté vacía, al dibujarse y mientras se teclea. Lo
que cada pantalla pone de su parte es **declararlo**, con el atributo de HTML de toda la vida.

Dos cosas se vigilan aquí, y son distintas:

* que el mecanismo siga siendo **uno** y siga siendo genérico — el día que una pantalla se escriba
  su propia versión, hay dos reglas y una se quedará vieja;
* que las cajas que el panel YA se niega a guardar vacías sigan declarándose. Es una lista, y una
  lista es una deuda; la alternativa —deducir de un `if (!name)` cuál era la caja— es adivinar
  desde el otro extremo del fichero, y adivinar mal aquí no da ningún error: da una caja que no
  avisa, indistinguible de una que no es obligatoria.
"""

from __future__ import annotations

import io
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
UTILS = os.path.join(TPL, 'partials', 'core', '_utils.html')
BUNDLE = os.path.join(TPL, 'partials', '_js_sections.html')

#: Dónde se exige un campo, y el trozo de la caja que tiene que declararlo. Cada par es una
#: pantalla que YA contesta «hace falta un nombre» al guardar: lo que se comprueba es que además
#: lo diga antes. Añadir una pantalla que valide al guardar y no aparezca aquí no rompe nada —por
#: eso está escrito en el docstring de arriba— pero quitarle el `required` a una de estas, sí.
_DECLARADAS = (
    ('partials/modals/_user.html', 'id="umUsername"'),
    ('partials/modals/_access.html', 'id="gmLabel"'),
    ('partials/modals/_access.html', 'id="rmLabel"'),
    ('partials/servers/_modal.html', 'id="hmName"'),
    ('partials/events/_modal.html', 'id="evm-name"'),
    ('partials/cfg/notify/_webhooks.html', 'id="whUrl"'),
    ('partials/cfg/notify/_msteams.html', 'id="mstUrl"'),
    ('partials/apitokens/_list.html', 'id="accTokName"'),
    ('partials/account/_tokens.html', 'id="accTokName"'),
    ('partials/ipban/_whitelist.html', 'id="ipbanWlValue"'),
    ('partials/credentials/_modal.html', "_setCredField('name'"),
    # Y el cuadro de una empresa, que es de un paquete del core y no de las
    # plantillas del panel: el marcador es el mismo, y la declaración también.
    ('../../core/orgs/web/_modals.html', 'id="omName"'),
    ('../../core/orgs/web/_modals.html', 'id="omShort"'),
)


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()


def _tag(texto: str, ancla: str) -> str:
    """La etiqueta que contiene *ancla*, del `<` anterior al `>` siguiente.

    Buscar `required` en todo el fichero diría que sí en cuanto CUALQUIER caja lo lleve, que es
    exactamente la forma de que esta comprobación pase sin comprobar nada.
    """
    i = texto.index(ancla)
    return texto[texto.rindex('<', 0, i):texto.index('>', i) + 1]


class TestElMarcadorEsUnoYEsDelPanel:

    def test_existe_y_marca_por_estar_vacia(self):
        js = _read(UTILS)
        assert 'function ssReqMark(' in js, 'no hay marcador'
        cuerpo = js.split('function ssReqMark(')[1].split('\n}')[0]
        assert 'is-invalid' in cuerpo and 'toggle' in cuerpo
        # Quitar y poner: una marca que no se va deja de significar algo.
        assert '.trim()' in cuerpo, 'una caja con espacios contaría como llena'
        # Una casilla no se marca: su vacío es un estado legítimo, y pintarlo en rojo diría que
        # hay que marcarla, que es otra cosa.
        assert 'checkbox' in cuerpo

    def test_y_se_entera_de_lo_que_se_teclea_sin_que_nadie_lo_llame(self):
        """Un `oninput` por caja serían trescientos sitios donde acordarse, y el que se olvide no
        da ningún error: da una caja que no avisa."""
        js = _read(UTILS)
        for evento in ("document.addEventListener('input'",
                       "document.addEventListener('change'"):
            trozo = js[js.index(evento):]
            trozo = trozo[:trozo.index('});') + 3]      # sólo ESTA escucha, no la de al lado
            assert "hasAttribute('required')" in trozo, evento
            assert 'ssReqMark' in trozo, evento

    def test_y_de_lo_que_se_dibuja(self):
        """Casi todo en este panel se pinta metiendo HTML en un contenedor, y no hay un solo sitio
        por el que pase todo: lo que se busca es lo que ENTRA en el documento."""
        js = _read(UTILS)
        # La condición ENTERA: `if (false && typeof MutationObserver === 'function')` deja el
        # nombre escrito y el observador sin arrancar, y una guarda que sólo busca el nombre lo
        # da por bueno. Pasó al comprobarlo por mutación.
        assert "if (typeof MutationObserver === 'function') {" in js, 'no se arranca'
        trozo = js[js.index("if (typeof MutationObserver === 'function') {"):]
        assert '.observe(' in trozo, 'se construye y no se observa nada'
        assert 'addedNodes' in trozo, 'recorre el documento entero en vez de lo añadido'
        assert 'ssMarkRequired' in trozo

    def test_y_escucha_en_burbuja_para_no_perder_la_marca(self):
        """Media docena de cajas llevan un `oninput="this.classList.remove('is-invalid')"` de
        cuando la marca sólo señalaba un guardado rechazado. Capturando, esto pintaría primero y
        esa línea lo borraría después: la marca no saldría, y no habría nada que mirar."""
        js = _read(UTILS)
        for evento in ("document.addEventListener('input'",
                       "document.addEventListener('change'"):
            trozo = js[js.index(evento):]
            trozo = trozo[:trozo.index('});') + 3]
            assert not trozo.rstrip().endswith('}, true);'), f'{evento} captura'

    def test_y_va_en_el_guion_que_se_sirve(self):
        assert 'partials/core/_utils.html' in _read(BUNDLE)

    def test_y_nadie_se_escribe_el_suyo(self):
        """El día que una pantalla se haga su propia versión hay dos reglas, y una se quedará
        vieja. `add`/`remove` sueltos siguen valiendo: son de señalar un guardado rechazado, que
        es otra cosa y llega en otro momento."""
        malos = []
        for aqui, _dirs, ficheros in os.walk(os.path.join(SRC, 'lib')):
            for f in sorted(ficheros):
                if not f.endswith('.html'):
                    continue
                ruta = os.path.join(aqui, f)
                if os.path.abspath(ruta) == os.path.abspath(UTILS):
                    continue
                js = _read(ruta)
                if "toggle('is-invalid'" in js or 'toggle("is-invalid"' in js:
                    malos.append(os.path.relpath(ruta, SRC).replace(os.sep, '/'))
        assert not malos, 'segunda implementación del marcado: ' + ', '.join(malos)


class TestLoQueSeExigeAlGuardarSeDiceAntes:

    def test_cada_caja_de_la_lista_se_declara_obligatoria(self):
        faltan = []
        for rel, ancla in _DECLARADAS:
            texto = _read(os.path.join(TPL, *rel.split('/')))
            if ancla not in texto:
                faltan.append(f'{rel}: ya no existe {ancla}')
                continue
            if 'required' not in _tag(texto, ancla):
                faltan.append(f'{rel}: {ancla} no se declara obligatoria')
        assert not faltan, '\n'.join(faltan)

    def test_y_el_inventario_lo_saca_de_su_registro(self):
        """Las de DCIM no se declaran una a una: sus campos ya dicen `req: true` en el registro,
        así que lo que hay que vigilar es que quien los dibuja lo mire — una caja y un desplegable,
        que son las dos formas que tiene un campo de esa sección."""
        js = _read(os.path.join(TPL, 'partials', 'dcim', '_form.html'))
        cuerpo = js.split('function _dcimFieldHtml(')[1].split('\n}')[0]
        assert cuerpo.count('fld.req') >= 2, 'el registro declara lo obligatorio y nadie lo mira'
        assert 'required' in cuerpo

    def test_y_las_empresas_tambien_lo_declaran(self):
        """Esta pantalla tuvo su propia versión del marcado durante una tarde. Lo que queda es la
        declaración, que es lo único que le toca a una pantalla."""
        js = _read(os.path.join(SRC, 'lib', 'core', 'orgs', 'web', '_ui.html'))
        assert "_ORGS_REQ = ['name', 'short']" in js
        assert 'is-invalid' not in js, 'vuelve a pintar la marca por su cuenta'
        # Y su cuadro llama al marcador del panel al abrirse: un alta nace con las dos cajas
        # vacías, y decirlo al abrir es decirlo cuando sirve.
        assert 'ssMarkRequired' in js
