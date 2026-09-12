#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers compartidos por las guardas de estructura (los tests que leen plantillas y JS).

Antes de existir este módulo, cada fichero de guardas llevaba su propia copia de estas tres
funciones: 21 copias byte a byte idénticas de ``_read``, 18 de ``_fn`` y 6 de
``_strip_comments``.  Arreglar una era arreglar una de veinte, en silencio.

No es ``conftest.py`` a propósito: eso es para *fixtures*, y estas son funciones normales que
se importan.  Tampoco se llama ``test_*.py``, así que pytest no lo recoge como suite.
"""

import io
import re


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _fn(src: str, name: str) -> str:
    """El cuerpo de una función JS de primer nivel dentro de ``src``."""
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


def _strip_comments(js: str) -> str:
    """Solo código.  Una guarda que lee también la prosa tropieza con el comentario que
    explica la regla que está comprobando — y todos estos ficheros llevan uno."""
    js = re.sub(r'\{#.*?#\}', '', js, flags=re.S)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


# ── Ejecutar el guion del panel ─────────────────────────────────────────────────────────
#
# Los guardias de arriba LEEN. Esto lo hace correr, que es otra familia de fallos entera: una
# función que existe y revienta antes de dibujar nada, una fila que enseña el dato de al lado, un
# desplegable que sale vacío. Ninguno de esos se ve leyendo el fuente, y todos se ven llamando a
# la función con datos delante.
#
# Vive aquí porque ya había dos copias del mismo arnés —la ficha de un cable y la pantalla de
# empresas— y estaba a punto de haber una tercera. La primera vez que se arregle algo de este
# DOM de mentira, se arregla en las tres.

#: Lo moderno, en su equivalente clásico, por si el `node` de la máquina es viejo.
NODE_VIEJUNO = (('?.(', '('), ('?.[', '['), ('?.', '.'),
                ('??=', '='), ('||=', '='), ('&&=', '='), ('??', '||'))

#: El DOM de mentira. No dibuja: contesta a todo lo que el guion pregunta al cargarse para que
#: llegue entero hasta el final, que es lo único que hace falta para poder llamar a una de sus
#: funciones. Un `null` de más aquí corta la carga a la mitad y deja media docena de `let` sin
#: estrenar — y entonces lo que falla es el arnés, no el panel.

#: Un `localStorage` que guarda. Va dentro del guion del arnés, no en Python: lo usa el DOM de
#: mentira que corre en node.
_ALMACEN_JS = '''
function _almacen() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(String(k)) ? m.get(String(k)) : null),
    setItem: (k, v) => { m.set(String(k), String(v)); },
    removeItem: (k) => { m.delete(String(k)); },
    clear: () => m.clear(),
  };
}
'''

NODE_ARNES = r"""
%(almacen)s
const fs = require('fs'), vm = require('vm');
let js = fs.readFileSync(process.argv[2], 'utf8');
for (const [v, n] of %(viejuno)s) js = js.split(v).join(n);

// `esc()` escapa creando un <div>, poniéndole `textContent` y leyendo su `innerHTML`. Un
// `innerHTML` fijo a '' devolvería cadena vacía para TODO lo escapado, y las pruebas pasarían
// sin poder mirar ni un nombre — ciegas y en verde, que es lo peor de los dos mundos.
function escapa(v) {
  return String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function nodo() {
  const n = {id: '', value: '', innerHTML: '', checked: false, disabled: false, readOnly: false,
    style: {}, dataset: {}, children: [], childNodes: [],
    addEventListener() {}, removeEventListener() {}, appendChild() {}, removeChild() {},
    setAttribute() {}, getAttribute: () => '', removeAttribute() {}, focus() {}, blur() {},
    click() {}, closest: () => null, querySelector: () => nodo(), querySelectorAll: () => [],
    insertAdjacentHTML() {}, scrollIntoView() {}, remove() {}, contains: () => false,
    getBoundingClientRect: () => ({top: 0, left: 0, width: 0, height: 0}),
    cloneNode: () => nodo(), parentNode: null};
  // Un `classList` que se ACUERDA: con uno que no hace nada, comprobar que algo se marca pasa
  // siempre — que es la prueba ciega de siempre.
  n.classList = {_s: [],
    add(c) { if (this._s.indexOf(c) < 0) this._s.push(c); },
    remove(c) { const k = this._s.indexOf(c); if (k >= 0) this._s.splice(k, 1); },
    toggle(c, on) { if (on === undefined) on = this._s.indexOf(c) < 0;
                    return on ? this.add(c) : this.remove(c); },
    contains(c) { return this._s.indexOf(c) >= 0; }};
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
  // Almacenamiento de VERDAD, en memoria. Un doble que descarta lo que se le escribe deja
  // hueca cualquier prueba sobre estado recordado —«la pestaña sobrevive a un F5»— porque el
  // `getItem` siguiente devuelve null y la prueba comprueba el valor por defecto creyendo que
  // comprueba el guardado.
  localStorage: _almacen(),
  sessionStorage: _almacen(),
  setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  requestAnimationFrame: () => 0,
  fetch: () => Promise.resolve({ok: true, status: 200, headers: {get: () => 'application/json'},
                                json: async () => ({}), text: async () => ''}),
  bootstrap: {Modal: {getOrCreateInstance: () => ({show() {}, hide() {}})},
              Tab: {getOrCreateInstance: () => ({show() {}})},
              Tooltip: function () {},
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
const salida = {load: '', error: ''};
try { vm.runInContext(js, caja, {filename: 'panel.js'}); }
catch (e) { salida.load = String(e && e.message || e); }
try {
  vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), caja, {filename: 'prueba.js'});
} catch (e) { salida.error = String(e && e.constructor && e.constructor.name || '') +
                             ': ' + String(e && e.message || e); }
Object.assign(salida, caja.__out || {});
console.log(JSON.stringify(salida));
"""


def node_run(bundle_js: str, probe_js: str) -> dict:
    """Cargar el guion del panel en `node` y ejecutar *probe_js* encima. Devuelve su `__out`.

    `load` NO se exige vacío, y la razón es del arnés y no del panel: traducir `?.` a `.` para un
    `node` viejo se lleva por delante la seguridad ante nulos, así que la última línea del guion
    —la que sincroniza la barra lateral— revienta contra un DOM de mentira. Las funciones ya
    están todas definidas para entonces (se izan), y lo que importa es que la prueba corra.
    """
    import json                                                      # noqa: PLC0415
    import os                                                        # noqa: PLC0415
    import subprocess                                                # noqa: PLC0415
    import tempfile                                                  # noqa: PLC0415
    tmp = tempfile.mkdtemp(prefix='ss-node-')
    rutas = {}
    for nombre, texto in (('panel.js', bundle_js), ('prueba.js', probe_js),
                          ('arnes.js', NODE_ARNES % {
                              'almacen': _ALMACEN_JS,
                              'viejuno': json.dumps([list(x) for x in NODE_VIEJUNO])})):
        rutas[nombre] = os.path.join(tmp, nombre)
        io.open(rutas[nombre], 'w', encoding='utf-8').write(texto)
    r = subprocess.run(['node', rutas['arnes.js'], rutas['panel.js'], rutas['prueba.js']],
                       capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert r.returncode == 0, (r.stderr or '')[-2000:]
    out = json.loads([l for l in r.stdout.splitlines() if l.startswith('{')][-1])
    assert not out['error'], f'la prueba reventó: {out["error"]}'
    return out


def panel_bundle(client) -> str:
    """El `<script>` más grande de `/admin`: el paquete de todas las secciones."""
    import re as _re                                                 # noqa: PLC0415
    html = client.get('/admin').get_data(as_text=True)
    trozos = _re.findall(r'<script[^>]*>(.*?)</script>', html, _re.S)
    assert trozos, '/admin no sirvió ningún guion'
    return max(trozos, key=len)
