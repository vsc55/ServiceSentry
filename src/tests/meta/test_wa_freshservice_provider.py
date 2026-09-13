#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El proveedor de Freshservice: que todo lo que dice esté en los ficheros de idioma.

Un proveedor habla en dos momentos, y los dos son sitios donde una frase se escribe a mano sin
que nada falle: cuando algo va mal —la clave, el permiso de esa clave, el dominio, el límite por
minuto— y cuando la pantalla enseña el plan antes de aplicarlo.

Una frase escrita en el código no se puede traducir, no sale en ninguna revisión de traducciones,
y el día que alguien cambie la palabra en `es_ES.py` la pantalla seguirá diciendo la vieja sin que
nada lo diga. La guarda general (`test_i18n_no_text_in_code.py`) caza el castellano por sus
acentos; el inglés no se distingue de un identificador, así que **aquí se comprueba al revés**:
que cada clave que este paquete nombra exista de verdad en los dos idiomas, y que ningún error se
construya con una frase dentro.

La diferencia entre las dos mitades de un error importa:

* la **clave** es lo que se le enseña a una persona, y por eso se traduce;
* el **detalle** es lo que dijo el otro extremo —un código HTTP, el mensaje de una librería, el
  cuerpo del proxy que contestó en su lugar— y por eso NO se traduce: no es de este panel, y
  traducir lo que dijo otro es cambiárselo.
"""

from __future__ import annotations

import ast
import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
PKG = os.path.join(SRC, 'lib', 'providers', 'freshservice')


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()


def _lang(code):
    """Las palabras de un idioma, importadas: para saber si una clave EXISTE hace falta el
    diccionario, no el texto del fichero."""
    import importlib                                                # noqa: PLC0415
    import sys                                                      # noqa: PLC0415
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    # El diccionario se llama `LANG` y se busca por lo que TIENE, no por su nombre: el nombre es
    # un detalle del fichero y esta guarda no tiene por qué saberlo.
    mod = importlib.import_module('lib.i18n.lang.' + code)
    for valor in vars(mod).values():
        if isinstance(valor, dict) and 'save' in valor:
            return valor
    raise AssertionError(f'{code}: no trae el diccionario de idioma')


def _py(nombre):
    return os.path.join(PKG, nombre)


class TestNadaDeLoQueDiceEstaEscritoAqui:

    def test_cada_error_nombra_una_clave_que_existe(self):
        """Una clave que no está en el catálogo sale en pantalla tal cual: `fs_err_body`, con
        guion bajo y todo, encima de un aviso rojo."""
        usadas = set()
        for f in sorted(os.listdir(PKG)):
            if not f.endswith('.py'):
                continue
            usadas |= set(re.findall(r"FreshserviceError\('([a-z_]+)'", _read(_py(f))))
        assert usadas, 'ningún error con nombre: ¿se ha dejado de usar la clase?'
        for code in ('es_ES', 'en_EN'):
            idioma = _lang(code)
            faltan = sorted(k for k in usadas if k not in idioma)
            assert not faltan, (code, faltan)

    def test_y_ningun_error_lleva_una_frase_dentro(self):
        """El detalle es lo que dijo el otro extremo: `str(exc)` o el código que contestó. Una
        cadena escrita aquí es una frase que no se puede traducir — y la tentación es grande,
        porque en el momento de escribirla se sabe muy bien lo que se quiere decir."""
        malos = []
        for f in sorted(os.listdir(PKG)):
            if not f.endswith('.py'):
                continue
            arbol = ast.parse(_read(_py(f)))
            for nodo in ast.walk(arbol):
                if not (isinstance(nodo, ast.Call) and getattr(nodo.func, 'id', '')
                        == 'FreshserviceError'):
                    continue
                if len(nodo.args) < 2:
                    continue                    # sólo la clave: lo correcto
                detalle = nodo.args[1]
                # Vale `str(exc)`, vale una f-string con el código, y no vale una frase.
                if isinstance(detalle, ast.Constant) and isinstance(detalle.value, str):
                    malos.append(f'{f}:{nodo.lineno}: {detalle.value[:50]!r}')
        assert not malos, 'frases escritas a mano en un error:\n' + '\n'.join(malos)

    def test_y_la_pantalla_pide_sus_palabras_al_catalogo(self):
        """Todo lo que se pinta pasa por `t()` o `tf()`, y cada clave tiene que existir.

        **Todas sus pantallas, no una.** Esto miraba `web/_ui.html` a secas, y el día que el
        paquete creció con un segundo cuadro —el de los dispositivos— la guarda habría seguido
        en verde sin mirarlo: una guarda apuntada a un nombre de fichero deja de guardar en
        cuanto hay un fichero más, y nadie se entera porque no falla.
        """
        web = os.path.join(PKG, 'web')
        js = '\n'.join(_read(os.path.join(web, f)) for f in sorted(os.listdir(web))
                       if f.endswith('.html'))
        claves = set(re.findall(r"\bt f?\(?'([a-z_0-9]+)'\)", js)) \
            | set(re.findall(r"\bt\('([a-z_0-9]+)'\)", js)) \
            | set(re.findall(r"\btf\('([a-z_0-9]+)'", js))
        assert claves, 'la pantalla no pide ni una palabra al catálogo'
        for code in ('es_ES', 'en_EN'):
            idioma = _lang(code)
            faltan = sorted(k for k in claves
                            if k not in idioma and not k.startswith('fs_act_'))
            assert not faltan, (code, faltan)
        # Las de las acciones se componen (`'fs_act_' + p.action`), así que se miran una a una:
        # una clave compuesta que no exista sale en crudo dentro de una insignia. `create_m` es
        # la misma acción en masculino — un activo es «Nuevo» y una empresa es «Nueva».
        for code in ('es_ES', 'en_EN'):
            idioma = _lang(code)
            for accion in ('create', 'update', 'adopt', 'same', 'create_m'):
                assert f'fs_act_{accion}' in idioma, (code, accion)

    def test_y_los_botones_tambien(self):
        """Los declara el manifiesto y los dibuja el panel: una clave que no exista deja un botón
        con el nombre de la clave escrito encima.

        Los tres sitios donde este paquete pone uno —su tarjeta de configuración, la pantalla de
        Empresas y la de Dispositivos— más el origen que firma las filas que trae. Se recorren
        por el NOMBRE del descriptor y no de uno en uno, para que el quinto entre solo.
        """
        import importlib                                            # noqa: PLC0415
        import sys                                                  # noqa: PLC0415
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        man = importlib.import_module('lib.providers.freshservice.manifest')
        claves = set()
        declarados = [n for n in dir(man) if n.endswith('_ACTIONS') or n.endswith('_SOURCES')]
        assert len(declarados) >= 4, f'¿se ha dejado de declarar algo? {declarados}'
        for nombre in declarados:
            for a in getattr(man, nombre):
                claves |= {a.get('label_key', ''), a.get('tooltip_key', ''),
                           a.get('group_label_key', '')}
        claves.discard('')
        for code in ('es_ES', 'en_EN'):
            idioma = _lang(code)
            faltan = sorted(k for k in claves if k not in idioma)
            assert not faltan, (code, faltan)

    def test_y_sus_dos_campos_de_configuracion(self):
        """Un campo sin rótulo sale con su `seccion|campo` de nombre, que es lo que se lee cuando
        alguien abre la tarjeta por primera vez."""
        for code in ('es_ES', 'en_EN'):
            idioma = _lang(code)
            for campo in ('freshservice|domain', 'freshservice|api_key'):
                assert campo in (idioma.get('labels') or {}), (code, campo)
                assert campo in (idioma.get('hints') or {}), (code, campo)
            assert 'cfg_card_freshservice' in idioma, code

    def test_y_lo_que_escribe_en_la_auditoria(self):
        """La línea de auditoría se lee meses después, cuando alguien pregunta desde cuándo una
        sociedad se llama así."""
        import importlib                                            # noqa: PLC0415
        man = importlib.import_module('lib.providers.freshservice.manifest')
        for code in ('es_ES', 'en_EN'):
            eventos = _lang(code).get('audit_events') or {}
            for e in man.AUDIT_EVENTS:
                assert e['key'] in eventos, (code, e['key'])


class TestElCuadroSeAbreAlPulsar:
    """Y espera DENTRO. Al revés —pedir, y abrir cuando conteste— el botón se pulsa y no pasa
    nada durante unos segundos, que es exactamente lo que hace que alguien lo pulse otra vez.

    Es la misma regla que ya sigue la comprobación de permisos del panel: «el cuadro se abre
    INMEDIATAMENTE con una fila girando por cada permiso». Reportado desde la pantalla.
    """

    def _js(self):
        return _read(os.path.join(PKG, 'web', '_ui.html'))

    def _cuerpo(self, nombre):
        return self._js().split(f'async function {nombre}(')[1].split(chr(10) + '}')[0]

    def test_los_dos_botones_abren_antes_de_preguntar(self):
        for fn, pedir in (('freshserviceTest', 'apiSend('),
                          ('freshserviceImport', 'apiGet(')):
            cuerpo = self._cuerpo(fn)
            assert '_fsOpen(' in cuerpo, fn
            assert cuerpo.index('_fsOpen(') < cuerpo.index(pedir),                 f'{fn}: pide primero y abre después'

    def test_y_lo_que_se_enseña_mientras_dice_que_esta_haciendo(self):
        """Una rueda sola es «algo pasa»; con la frase es «se está preguntando a Freshservice»,
        que es lo que quita las ganas de volver a pulsar."""
        cuerpo = self._js().split('function _fsOpen(')[1].split(chr(10) + '}')[0]
        assert 'spinner-border' in cuerpo
        assert "t('fs_working')" in cuerpo

    def test_y_un_fallo_se_cuenta_dentro_del_cuadro_abierto(self):
        """El cuadro ya está abierto: un aviso pasando por detrás de un cuadro vacío es la peor
        forma de decir que algo falló."""
        assert '_fsFalloHtml(' in self._cuerpo('freshserviceTest')
        assert '_fsFalloHtml(' in self._cuerpo('freshserviceImport')

    def test_y_mientras_escribe_el_boton_no_se_deja_pulsar_dos_veces(self):
        """Son sesenta filas: un segundo clic las escribiría dos veces."""
        cuerpo = self._cuerpo('freshserviceApply')
        assert 'btn.disabled = true' in cuerpo
        assert "t('fs_working')" in cuerpo
        assert 'btn.disabled = false' in cuerpo, 'el botón se queda muerto si algo falla'
