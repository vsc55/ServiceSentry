#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La ficha de un cable, **ejecutada**.

Nada más de la suite ejecuta el guion del panel. Los guardianes leen el fuente —que toda función
llamada esté escrita, que lo tecleado salga escapado, que ningún global de una pantalla se lea
desde la otra— y ninguno de ellos corre una línea. Eso deja fuera una familia entera de fallos,
y la sección de cableado se comió tres el mismo día:

* «Editar» reventaba con un `TypeError` antes de dibujar nada, porque la ficha leía `_dcCables`
  —el estado de la pestaña de un armario— y desde `/dcim/wiring` vale `null`. Ni ventana, ni
  aviso: un botón muerto.
* «Meter un panel en medio» hacía lo mismo un poco más abajo: se quedaba con un cable vacío y
  `if (!c) return` se ocupaba del resto, en silencio.
* Un cable directo se quedaba sin dibujo de su tirada y con dos renglones que ponían «sin decir»,
  porque el nombre de cada punta también salía de esa lista.

Los tres se encontraron cargando el guion en `node` con un DOM de mentira, que es lo que hace
esto. **No se comprueba el aspecto** —para eso hace falta un navegador de verdad, y para eso
están los `e2e`— sino lo que se puede afirmar sin pintar: que abrir no lanza una excepción, que
lo que se dibuja lleva lo que tiene que llevar, y que las acciones salen donde corresponden.

El guion se saca de la página igual que en ``test_wa_bundle_syntax.py``, y se traducen antes las
dos formas modernas por si el `node` de la máquina es viejo.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from tests.conftest import _login                                   # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='sin node: no hay con qué ejecutar el guion')

#: Lo moderno, en su equivalente clásico. La misma lista que el analizador de sintaxis.
_VIEJUNO = (('?.(', '('), ('?.[', '['), ('?.', '.'),
            ('??=', '='), ('||=', '='), ('&&=', '='), ('??', '||'))

#: El DOM de mentira. No dibuja nada: contesta a todo lo que el guion pregunta al cargarse para
#: que llegue entero hasta el final, que es lo único que hace falta para poder llamar a una de
#: sus funciones. Un `null` de más aquí corta la carga a la mitad y deja media docena de `let`
#: sin estrenar — y entonces lo que falla es el arnés, no el panel.
_ARNES = r"""
const fs = require('fs'), vm = require('vm');
let js = fs.readFileSync(process.argv[2], 'utf8');
for (const [v, n] of %(viejuno)s) js = js.split(v).join(n);

// `esc()` escapa creando un <div>, poniéndole `textContent` y leyendo su `innerHTML`. Con un
// `innerHTML` fijo a '' el arnés devolvía cadena vacía para TODO lo escapado, y las pruebas
// pasaban sin poder mirar ni un nombre. Aquí se escapa de verdad, que es lo que hace un DOM.
function escapa(v) {
  return String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function nodo() {
  const n = {value: '', innerHTML: '', checked: false, disabled: false,
    style: {}, dataset: {}, children: [], childNodes: [],
    classList: {add() {}, remove() {}, toggle() {}, contains: () => false},
    addEventListener() {}, removeEventListener() {}, appendChild() {}, removeChild() {},
    setAttribute() {}, getAttribute: () => '', removeAttribute() {}, focus() {}, blur() {},
    click() {}, closest: () => null, querySelector: () => nodo(), querySelectorAll: () => [],
    insertAdjacentHTML() {}, scrollIntoView() {}, remove() {}, contains: () => false,
    getBoundingClientRect: () => ({top: 0, left: 0, width: 0, height: 0}),
    cloneNode: () => nodo(), parentNode: null};
  Object.defineProperty(n, 'textContent', {
    get() { return n.__t || ''; },
    set(v) { n.__t = String(v); n.innerHTML = escapa(v); },
  });
  return n;
}
const doc = {getElementById: () => nodo(), querySelector: () => nodo(), querySelectorAll: () => [],
  createElement: () => nodo(), createTextNode: () => nodo(),
  addEventListener() {}, removeEventListener() {},
  body: nodo(), head: nodo(), documentElement: nodo(), cookie: '', readyState: 'complete'};
const caja = {console, document: doc, navigator: {language: 'es', userAgent: 'node'},
  location: {href: '', hash: '', search: '', pathname: '/admin', origin: 'http://x'},
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
  sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}},
  setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  requestAnimationFrame: () => 0,
  fetch: () => Promise.resolve({ok: true, status: 200, headers: {get: () => 'application/json'},
                                json: async () => ({}), text: async () => ''}),
  bootstrap: {Modal: function () { return {show() {}, hide() {}}; }, Tooltip: function () {},
              Offcanvas: function () { return {show() {}, hide() {}}; }},
  Chart: function () { return {destroy() {}, update() {}}; }, URLSearchParams, URL,
  addEventListener() {}, removeEventListener() {},
  matchMedia: () => ({matches: false, addEventListener() {}, addListener() {}}),
  getComputedStyle: () => ({getPropertyValue: () => ''}),
  Image: function () {}, WebSocket: function () {}, EventSource: function () {},
  performance: {now: () => 0}, crypto: {getRandomValues: (a) => a},
  MutationObserver: function () { return {observe() {}, disconnect() {}}; },
  ResizeObserver: function () { return {observe() {}, disconnect() {}}; },
  IntersectionObserver: function () { return {observe() {}, disconnect() {}}; }};
caja.window = caja; caja.globalThis = caja;
vm.createContext(caja);
const salida = {load: '', error: '', modals: []};
try { vm.runInContext(js, caja, {filename: 'panel.js'}); }
catch (e) { salida.load = String(e && e.message || e); }
// Las funciones del panel se declaran con `function`, así que son propiedades del global y se
// pueden sustituir; los `let` no, y por eso lo que hay que tocar se toca DENTRO del contexto.
try {
  vm.runInContext(`
    showHtmlModal = function (titulo, cuerpo, tono, pie, ancho) {
      globalThis.__modales.push({body: String(cuerpo || ''), foot: String(pie || ''),
                                 size: String(ancho || '')});
    };
    showToast = function () {};
    _dcimMay = function () { return true; };
    __modales = [];
  ` + fs.readFileSync(process.argv[3], 'utf8'), caja, {filename: 'prueba.js'});
} catch (e) { salida.error = String(e && e.constructor && e.constructor.name || '') +
                             ': ' + String(e && e.message || e); }
salida.modals = caja.__modales || [];
console.log(JSON.stringify(salida));
"""


def _bundle(client) -> str:
    """El `<script>` más grande de `/admin`: el paquete de todas las secciones."""
    html = client.get('/admin').get_data(as_text=True)
    trozos = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    assert trozos, '/admin no sirvió ningún guion'
    return max(trozos, key=len)


def _correr(client, guion: str) -> dict:
    """Carga el panel en `node`, ejecuta *guion* dentro y devuelve lo que salió."""
    tmp = tempfile.mkdtemp(prefix='ss-panel-')
    js = os.path.join(tmp, 'panel.js')
    io.open(js, 'w', encoding='utf-8').write(_bundle(client))
    prueba = os.path.join(tmp, 'prueba.js')
    io.open(prueba, 'w', encoding='utf-8').write(guion)
    arnes = os.path.join(tmp, 'arnes.js')
    io.open(arnes, 'w', encoding='utf-8').write(_ARNES % {'viejuno': json.dumps(_VIEJUNO)})
    r = subprocess.run(['node', arnes, js, prueba], capture_output=True, text=True, timeout=120)
    ultima = [l for l in (r.stdout or '').splitlines() if l.startswith('{')]
    assert ultima, f'node no contestó: {r.stdout[-500:]}\n{r.stderr[-500:]}'
    out = json.loads(ultima[-1])
    # Que el ARNÉS esté bien es parte de la prueba: si la carga se corta, lo que viene detrás
    # falla por el motivo equivocado y el test acusa al panel de algo que no ha hecho.
    assert 'function _dcCableInfo' in _bundle(client)
    return out


#: Un cable de la SECCIÓN de cableado: `_dcCables` vale `null` porque allí no se ha abierto
#: ningún armario, que es exactamente el caso en que se rompía todo.
_DESDE_CABLEADO = """
_dcCables = null;
_dcWire = {rows: [{uid: 'c1', label: '', kind: 'copper', category: 'cat6', length_mm: 500,
                   a_item: 'i1', b_item: 'i2', a_port: '2', b_port: '1',
                   color: '#ffffff', description: '', asset: '',
                   a_at: {label: 'SW01', role: 'switch', rack: 'R1', u: 3},
                   b_at: {label: 'PVE02', role: 'server', rack: 'R1', u: 5}}]};
"""

#: Y su tirada, tal como la contesta `/cables/<uid>/run`.
_TIRADA = """
_dcRun = {uid: 'c1', path: {ends: ['i1', 'i2'], legs: [
  {cable: 'z0', a_item: 'i1', a_port: '2', b_item: 'pp', b_port: '12',
   a_label: 'SW01', b_label: 'PP-A', a_role: 'switch', b_role: 'patch_panel',
   a_at: {rack: 'R1', u: 3}, b_at: {rack: 'R1', u: 20},
   label: 'L1', category: 'cat6', length_mm: 500, color: '#00f', kind: 'copper'},
  {cable: 'c1', a_item: 'pp', a_port: '12', b_item: 'i2', b_port: '1',
   a_label: 'PP-A', b_label: 'PVE02', a_role: 'patch_panel', b_role: 'server',
   a_at: {rack: 'R1', u: 20}, b_at: {rack: 'R1', u: 5},
   label: 'L2', category: 'cat6', length_mm: 1200, color: '#0f0', kind: 'copper'}]}};
"""


class TestLaFichaDeUnCableSeAbreDeVerdad:
    """Abierta **desde la sección de cableado**, que es donde se rompía: allí no hay armario
    abierto y todo lo que leyera el estado de esa pestaña encontraba un `null`."""

    def test_la_ficha_abre(self, admin, client):
        _login(client)
        r = _correr(client, _DESDE_CABLEADO + "_dcCableInfo('c1');")
        assert not r['error'], r['error']
        assert len(r['modals']) == 1

    def test_y_editar_tambien(self, admin, client):
        """Reventaba con un `TypeError` antes de dibujar nada, y la excepción moría en el
        `onclick`: ni ventana, ni aviso, ni rastro. Un botón muerto."""
        _login(client)
        r = _correr(client, _DESDE_CABLEADO + "_dcCableInfo('c1'); _dcCableInfo('c1', true);")
        assert not r['error'], r['error']
        assert len(r['modals']) == 2
        assert 'dce-as' in r['modals'][1]['body'], 'el formulario no trae sus casillas'

    def test_y_meter_un_panel_en_medio(self, admin, client):
        """Se quedaba con un cable vacío y `if (!c) return` hacía el resto en silencio."""
        _login(client)
        r = _correr(client, _DESDE_CABLEADO + """
            _dcCableSplit('c1');
            _dcSplit.pick = {uid: 'pp', label: 'PP-A'};
            _dcSplit.port = '12';
            _dcSplitDraw();
        """)
        assert not r['error'], r['error']
        cuerpo = r['modals'][-1]['body']
        # Los dos tramos que van a quedar, con los nombres puestos.
        assert cuerpo.count('ss-path-stop') == 2, 'no se enseña cómo queda la cosa'
        assert 'SW01' in cuerpo and 'PVE02' in cuerpo, 'la nota sale sin nombres'


class TestLaTiradaSeDibuja:

    def test_un_cable_directo_tambien_tiene_dos_puntas(self, admin, client):
        """Se dibujaba sólo con dos tramos o más, porque «con uno las puntas están en los
        renglones de al lado». Y esos renglones salían vacíos desde esta pantalla."""
        _login(client)
        r = _correr(client, _DESDE_CABLEADO + """
            _dcRun = {uid: 'c1', path: {ends: ['i1', 'i2'], legs: [
              {cable: 'c1', a_item: 'i1', a_port: '2', b_item: 'i2', b_port: '1',
               a_label: 'SW01', b_label: 'PVE02', a_role: 'switch', b_role: 'server',
               a_at: {rack: 'R1', u: 3}, b_at: {rack: 'R1', u: 5},
               label: '', category: 'cat6', length_mm: 500, color: '#00f', kind: 'copper'}]}};
            _dcCableInfo('c1');
        """)
        assert not r['error'], r['error']
        cuerpo = r['modals'][-1]['body']
        assert cuerpo.count('ss-path-stop') == 2, 'un cable directo se queda sin sus dos puntas'
        assert 'SW01' in cuerpo and 'PVE02' in cuerpo

    def test_y_marca_el_tramo_que_se_esta_mirando(self, admin, client):
        """Una tirada de tres tramos, sin saber cuál se tiene abierto, obliga a compararlos uno
        a uno."""
        _login(client)
        r = _correr(client, _DESDE_CABLEADO + _TIRADA + "_dcCableInfo('c1');")
        assert not r['error'], r['error']
        cuerpo = r['modals'][-1]['body']
        assert cuerpo.count('ss-path-mine') == 1, 'no se marca, o se marcan varios'
        assert 'ss-cable-two' in cuerpo, 'la ficha con tirada no va a dos columnas'
        assert r['modals'][-1]['size'] == 'wide'

    def test_y_el_panel_solo_se_puede_meter_por_las_puntas_de_este_cable(self, admin, client):
        """En una tirada de tres tramos, las paradas de los otros dos son sus puntas: meterles
        un panel sería partir otro cable."""
        _login(client)
        r = _correr(client, _DESDE_CABLEADO + _TIRADA + "_dcCableInfo('c1');")
        assert not r['error'], r['error']
        cuerpo = r['modals'][-1]['body']
        assert cuerpo.count('_dcCableSplitAt(') == 2, 'el botón sale en paradas que no son suyas'
        # Y el del pie no está: dos formas de hacer lo mismo son dos sitios donde arreglarlo.
        assert '_dcCableSplit(' not in r['modals'][-1]['foot']

    def test_y_la_punta_que_se_pulsa_decide_el_lado(self, admin, client):
        """Es la misma decisión que el desplegable «el cable de ahora se queda con», dicha donde
        se ve. Qué punta es «la A» lo dice la fila del cable y no el dibujo: la tirada se recorre
        de punta a punta y la mitad de los tramos están guardados al revés."""
        _login(client)
        r = _correr(client, _DESDE_CABLEADO + """
            _dcCableSplitAt('c1', 'i1'); globalThis.__uno = _dcSplit.side;
            _dcCableSplitAt('c1', 'i2'); globalThis.__dos = _dcSplit.side;
            showHtmlModal('', globalThis.__uno + globalThis.__dos, '', '', '');
        """)
        assert not r['error'], r['error']
        assert r['modals'][-1]['body'].endswith('ab')
