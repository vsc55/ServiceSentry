#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La pantalla de empresas, **ejecutada**.

Un guardián que lee el fuente dice que la función está escrita. No dice que dibuje: la sección de
cableado se comió tres botones muertos el mismo día, y los tres reventaban con un `TypeError`
antes de pintar nada — ni ventana, ni aviso. Así que esto carga el guion del panel en `node` con
un DOM de mentira y llama a lo que la pantalla pone de su parte.

Y pone poco a propósito: la tabla es la del panel (`createListTable`), que ya trae el esqueleto,
la cabecera, el filtro, la paginación y las columnas elegibles. Lo suyo son las tarjetas, las
chapas de lo fichado, los botones de una fila y qué se manda al guardar — que es lo que se ejecuta
aquí. Que la tabla esté bien enchufada se comprueba leyendo, en `tests/meta/test_wa_orgs_page.py`:
eso es una declaración, no un dibujo.

**No se comprueba el aspecto** —para eso hace falta un navegador, y para eso están los `e2e`—
sino lo que se puede afirmar sin pintar.
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

#: Lo moderno, en su equivalente clásico, por si el `node` de la máquina es viejo.
_VIEJUNO = (('?.(', '('), ('?.[', '['), ('?.', '.'),
            ('??=', '='), ('||=', '='), ('&&=', '='), ('??', '||'))

_ARNES = r"""
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
  const n = {id: '', value: '', innerHTML: '', checked: false, disabled: false,
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

#: Lo que habría traído el servidor. A mano porque lo que se prueba es el DIBUJADO — y con un
#: nombre con `<` dentro, que es lo que separa escapar de decir que se escapa.
_PRUEBA = r"""
currentUser = {permissions: ['orgs_view', 'orgs_edit', 'orgs_all_view']};
SS_STANDALONE_PAGES = [{id: 'orgs', url: '/orgs', pane: 'tab-orgs',
                        render: 'renderOrgsPage', views: []}];
showToast = function () {};
showConfirmModal = function () {};
_orgsData = {
  orgs: [
    {uid: 'o1', name: 'Sociedad A', short: 'SA', description: 'La matriz', said: {site: 3, rack: 2}},
    {uid: 'o2', name: 'Sociedad B', short: 'SB', description: '', said: {}},
    {uid: 'o3', name: '<script>ojo', short: 'S&C', description: 'con & y <', said: {host: 1}}],
  scopes: [{scope: 'site', label_key: 'orgs_scope_site'},
           {scope: 'rack', label_key: 'orgs_scope_rack'},
           {scope: 'host', label_key: 'orgs_scope_host'}],
  loaded: true};

__out = {chips: {}, acciones: {}, cambios: {}, marca: {}};
__out.tarjetas = _orgsCardsBody(_orgsData.orgs, {puede: true});
__out.tarjetasSinTocar = _orgsCardsBody(_orgsData.orgs, {puede: false});
// La ficha: abre la que se le diga, y la primera si la que había ya no está.
_orgsPick = 'o2';
__out.ficha = _orgsRecordBody(_orgsData.orgs, {puede: true});
_orgsPick = 'ya-no-existe';
__out.fichaHuerfana = _orgsRecordBody(_orgsData.orgs, {puede: true});
__out.fichaVacia = _orgsRecordBody([], {puede: true});
__out.chips.conAlgo = _orgsChipsHtml(_orgsData.orgs[0]);
__out.chips.sinNada = _orgsChipsHtml(_orgsData.orgs[1]);
__out.acciones.puede = _orgsRowActions(_orgsData.orgs[0], {puede: true});
__out.acciones.noPuede = _orgsRowActions(_orgsData.orgs[0], {puede: false});

// Lo que se manda al guardar, que es lo único que no se ve en pantalla.
var _a = _orgsData.orgs[0];
__out.cambios.igual = _orgChange({uid: 'o1', name: 'Sociedad A', short: 'SA',
                                  description: 'La matriz'}, _a);
__out.cambios.cambiada = _orgChange({uid: 'o1', name: 'Sociedad A', short: 'SA',
                                     description: 'Otra cosa'}, _a);
__out.cambios.nueva = _orgChange({uid: '', name: '  Recién puesta ', short: 'RP',
                                  description: ''}, null);
__out.cambios.sinNombre = _orgChange({uid: '', name: '   ', short: 'RP'}, null);
__out.cambios.sinSiglas = _orgChange({uid: '', name: 'Sin siglas', short: '  '}, null);

// Y el marcado de lo obligatorio, que es del panel y no de esta pantalla.
var _c = document.createElement('input');
_c.value = '';
ssReqMark(_c);
__out.marca.vacia = _c.classList.contains('is-invalid');
_c.value = 'algo';
ssReqMark(_c);
__out.marca.llena = _c.classList.contains('is-invalid');
"""


def _bundle(client) -> str:
    """El `<script>` más grande de `/admin`: el paquete de todas las secciones."""
    html = client.get('/admin').get_data(as_text=True)
    trozos = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    assert trozos, '/admin no sirvió ningún guion'
    return max(trozos, key=len)


@pytest.fixture(scope='module')
def pantalla():
    """La pantalla ejecutada, una vez para todo el fichero.

    Por módulo porque cuesta unos segundos: levantar el panel, servir `/admin`, arrancar `node`.
    Lo que devuelve es texto, así que no hay estado que se pueda contaminar entre pruebas.
    """
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var,
                  pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    js = _bundle(c)

    tmp = tempfile.mkdtemp(prefix='ss-orgs-js-')
    p_js = os.path.join(tmp, 'panel.js')
    p_pr = os.path.join(tmp, 'prueba.js')
    p_ar = os.path.join(tmp, 'arnes.js')
    io.open(p_js, 'w', encoding='utf-8').write(js)
    io.open(p_pr, 'w', encoding='utf-8').write(_PRUEBA)
    io.open(p_ar, 'w', encoding='utf-8').write(
        _ARNES % {'viejuno': json.dumps([list(x) for x in _VIEJUNO])})
    r = subprocess.run(['node', p_ar, p_js, p_pr], capture_output=True, text=True,
                       encoding='utf-8', timeout=120)
    assert r.returncode == 0, (r.stderr or '')[-2000:]
    out = json.loads([l for l in r.stdout.splitlines() if l.startswith('{')][-1])
    # `load` NO se exige vacío, y la razón es del arnés y no del panel: traducir `?.` a `.` para
    # un `node` viejo se lleva por delante la seguridad ante nulos, así que la última línea del
    # guion —la que sincroniza la barra lateral— revienta contra un DOM de mentira. Las funciones
    # ya están todas definidas para entonces (se izan), y lo que importa es lo de abajo: que
    # dibujar no reviente y que salga algo.
    assert not out['error'], f'dibujar reventó: {out["error"]}'
    out['fuente'] = js
    return out


class TestLasTarjetasDibujan:
    """La otra forma de mirar la misma lista, que en este panel es una decisión del lector: la
    misma tabla, las mismas acciones, otra colocación."""

    def test_pinta_y_lleva_las_empresas(self, pantalla):
        html = pantalla['tarjetas']
        assert len(html) > 400, 'ha dibujado algo, pero prácticamente nada'
        assert 'Sociedad A' in html and 'Sociedad B' in html

    def test_y_lleva_la_descripcion_y_las_siglas(self, pantalla):
        """El campo estaba en la tabla desde el primer día y no había forma de teclearlo. Un campo
        que se guarda y no se puede escribir es una columna muerta."""
        assert 'La matriz' in pantalla['tarjetas']
        assert 'SA' in pantalla['tarjetas']

    def test_y_no_pinta_lo_tecleado_en_crudo(self, pantalla):
        """Un nombre de empresa es texto que alguien escribió, y sale en cuatro pantallas."""
        html = pantalla['tarjetas']
        assert '<script>ojo' not in html
        assert '&lt;script&gt;ojo' in html

    def test_y_usa_la_tarjeta_del_panel(self, pantalla):
        """No una suya: una lista que se dibuja distinta de las otras diez no aprende nada de lo
        que se arregle en ellas."""
        cuerpo = pantalla['fuente'].split('function _orgsCardsBody(')[1][:700]
        assert '_entityCard(' in cuerpo and '_cardGrid(' in cuerpo


class TestLaFichaEsLaTerceraVista:
    """La lista a un lado y una sociedad al otro: es la que da sitio a lo largo —una descripción
    de tres renglones no cabe en una celda ni en una tarjeta— y la que aguanta que mañana una
    empresa tenga un CIF, un contacto y un centro de coste.

    Y es una vista del registro, no una pantalla aparte: el mismo cambiador, las mismas acciones y
    el mismo cuadro para corregir. Un formulario que sólo existiera aquí sería uno que se arregla
    en un sitio y se queda viejo en los otros dos."""

    def test_dibuja_la_lista_y_la_abierta(self, pantalla):
        html = pantalla['ficha']
        assert 'list-group-item' in html, 'no hay lista de la que elegir'
        # Todas en la lista, y la abierta con sus datos al lado.
        assert 'Sociedad A' in html and 'Sociedad B' in html
        assert '_orgsOpen(' in html, 'no se puede abrir otra'

    def test_y_da_sitio_a_la_descripcion(self, pantalla):
        """Que es su razón de ser: tres renglones no caben en una celda ni en una tarjeta. La de
        la ABIERTA — en la lista de la izquierda sólo van el nombre y las siglas."""
        abierta = pantalla['fichaHuerfana']              # cae en la primera, que sí la tiene
        assert 'La matriz' in abierta
        assert 'orgs_desc' not in abierta, 'el rótulo sale en crudo, sin traducir'

    def test_y_trae_los_mismos_botones_que_una_fila(self, pantalla):
        """Corregir desde aquí abre el mismo cuadro: uno por vista serían tres formularios."""
        assert '_orgModalOpen(' in pantalla['ficha'] and '_orgsDrop(' in pantalla['ficha']

    def test_y_si_la_abierta_ya_no_esta_abre_la_primera(self, pantalla):
        """Se borró, o el filtro la dejó fuera. Una ficha en blanco sobre una lista con seis
        empresas se lee como que la pantalla no ha cargado."""
        html = pantalla['fichaHuerfana']
        assert 'Sociedad A' in html
        assert 'active' in html, 'ninguna sale marcada como abierta'

    def test_y_sin_ninguna_no_dibuja_una_ficha_vacia(self, pantalla):
        """El hueco lo pone la tabla compartida, que ya sabe decir «no hay nada»."""
        assert pantalla['fichaVacia'] == ''


class TestLoFichadoSeCuentaPorAmbito:
    """«3 sedes» y no «5 cosas»: lo que se puede cambiar es la decisión, y las decisiones son por
    ámbito. Los ámbitos salen de lo que declara cada paquete, así que el día que un módulo fiche
    buzones esto los cuenta sin que nadie toque la pantalla."""

    def test_una_chapa_por_ambito_con_algo(self, pantalla):
        chips = pantalla['chips']['conAlgo']
        assert '3 ' in chips and '2 ' in chips
        assert chips.count('badge') == 2, 'cuenta ámbitos que no tiene'

    def test_y_la_que_no_tiene_nada_no_inventa_ninguna(self, pantalla):
        assert pantalla['chips']['sinNada'] == ''
        # …y quien la pinta pone el hueco, que es lo que distingue «no tiene» de «no se sabe».
        assert 'orgs_owns_none' in pantalla['fuente']


class TestCadaFilaTraeSusDosBotones:
    """Corregir y quitar, en la fila, como en el resto de las listas del panel."""

    def test_el_lapiz_abre_el_cuadro_y_la_papelera_pregunta(self, pantalla):
        html = pantalla['acciones']['puede']
        assert '_orgModalOpen(' in html, 'no hay por dónde corregir esta'
        assert '_orgsDrop(' in html, 'no hay por dónde quitarla'

    def test_y_quien_no_puede_escribir_no_los_ve(self, pantalla):
        """Un botón que lleva a un 403 es peor que no estar."""
        assert pantalla['acciones']['noPuede'] == ''
        assert '_orgsDrop(' not in pantalla['tarjetasSinTocar']


class TestLoQueNadieTocoNoViaja:
    """Guardar algo que no cambió escribe una línea de auditoría que no dice nada, y el día que
    alguien busque quién renombró una sociedad no la va a encontrar entre el ruido."""

    def test_lo_igual_no_manda_nada(self, pantalla):
        assert pantalla['cambios']['igual'] is None

    def test_lo_cambiado_va_con_put(self, pantalla):
        paso = pantalla['cambios']['cambiada']
        assert paso['metodo'] == 'PUT' and paso['uid'] == 'o1'
        assert paso['cuerpo']['description'] == 'Otra cosa'

    def test_y_lo_nuevo_con_post_y_sin_espacios_de_sobra(self, pantalla):
        paso = pantalla['cambios']['nueva']
        assert paso['metodo'] == 'POST' and paso['uid'] == ''
        assert paso['cuerpo']['name'] == 'Recién puesta'

    def test_y_sin_nombre_o_sin_siglas_no_se_guarda(self, pantalla):
        """Las dos son obligatorias: la abreviatura es lo que cabe en una chapa y en un alzado,
        donde el nombre legal de una sociedad no entra."""
        assert pantalla['cambios']['sinNombre'] is None
        assert pantalla['cambios']['sinSiglas'] is None


class TestLoObligatorioLoMarcaElPanel:
    """Esta pantalla tuvo su propia versión del marcado durante una tarde. Lo que le toca a una
    pantalla es declarar `required`; pintarlo es del panel, y una regla escrita dos veces son dos
    reglas."""

    def test_una_caja_vacia_se_marca_y_una_llena_no(self, pantalla):
        assert pantalla['marca']['vacia'] is True
        assert pantalla['marca']['llena'] is False

    def test_y_el_cuadro_se_abre_marcando_lo_que_falta(self, pantalla):
        """Un alta nace con las dos cajas vacías: decirlo al abrir es decirlo cuando sirve."""
        cuadro = pantalla['fuente'].split('function _orgModalOpen(')[1].split('\n}')[0]
        assert 'ssMarkRequired' in cuadro
