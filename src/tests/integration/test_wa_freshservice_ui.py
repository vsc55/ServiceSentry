#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La tabla de la importación, **ejecutada**.

Aquí se escondieron dos fallos que ningún guardián que lea el fuente puede ver, y los dos los
encontró una persona mirando la pantalla:

* una empresa que llevaba meses atada salía con «— crear una nueva —» en su desplegable, porque
  la selección sólo miraba los emparejamientos hechos a mano y no el que el plan ya traía. Lo que
  la fila decía que iba a hacer y lo que iba a hacer eran cosas distintas;
* y la columna de la descripción enseñaba el nombre VIEJO cuando había cambio, así que la fila
  parecía traerse los datos de aquí en lugar de los de Freshservice.

Los dos son de dibujado: la función existe, no revienta, y enseña otra cosa. Sólo se ven llamando
a la función con datos delante, que es lo que hace esto.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='sin node: no hay con qué ejecutar el guion')

#: Dos departamentos y dos empresas de aquí. Uno de los departamentos YA está atado —es el caso
#: que se rompió— y el otro es nuevo; una de las empresas está atada a un tercero, así que no se
#: puede ofrecer para emparejar.
_PRUEBA = r"""
currentUser = {permissions: ['orgs_view', 'orgs_edit']};
showToast = function () {};

const D = {
  total: 2,
  counts: {create: 1, update: 1, adopt: 0, same: 0},
  orphans: [],
  orgs: [
    {uid: 'u-amx', name: 'Amixalan', short: 'AXL',
     source: 'freshservice', external_id: '7'},
    {uid: 'u-libre', name: 'Tecleada aquí', short: 'TA', source: '', external_id: ''},
    {uid: 'u-otro', name: 'De otro departamento', short: 'DOD',
     source: 'freshservice', external_id: '99'}],
  plan: [
    {action: 'update', external_id: '7', uid: 'u-amx', name: 'Amixalan, S.L.',
     short: 'AXL', description: 'Holding del grupo',
     was: {name: 'Amixalan', short: 'AXL', description: 'lo de antes'}},
    {action: 'create', external_id: '8', uid: '', name: 'Alfa Co, S.A.C.',
     short: 'ACSAC', description: '', was: {}}],
};

_fsPlan = D;
_fsPick = new Set(['7', '8']);
_fsLink = {};

__out = {};
__out.html = _fsPlanHtml(D);
// La fila de cada uno, para poder mirarlas por separado.
const trozos = __out.html.split('<tr');
__out.atada = trozos.find(x => x.indexOf('Amixalan, S.L.') >= 0) || '';
__out.nueva = trozos.find(x => x.indexOf('Alfa Co') >= 0) || '';

// Y qué pasa al elegir a mano la que el plan ya traía: no es un emparejamiento, es dejarlo como
// estaba.
_fsSetLink('7', 'u-amx');
__out.linkTrasElegirLaSuya = JSON.stringify(_fsLink);
_fsSetLink('7', 'u-libre');
__out.linkTrasCambiarla = JSON.stringify(_fsLink);
__out.htmlCambiada = _fsPlanHtml(D);
// ── El filtro y el marcado de serie ─────────────────────────────────────────────────────
// Un plan con las cuatro clases de fila, para poder mirar qué se marca solo.
const D2 = {
  total: 4, counts: {create: 1, update: 1, adopt: 1, same: 1}, orphans: [], orgs: [],
  plan: [
    {action: 'update', external_id: '1', uid: 'u1', name: 'Amixalan, S.L.', short: 'AXL',
     description: 'holding', was: {name: 'Amixalan', short: 'AXL', description: ''}},
    {action: 'create', external_id: '2', uid: '', name: 'Alfa Co, S.A.C.', short: 'ACSAC',
     description: 'nueva del todo', was: {}},
    {action: 'adopt', external_id: '3', uid: 'u3', name: 'Behar Consultores', short: 'BC',
     description: '', was: {name: 'Behar Consultores', short: 'BC', description: ''}},
    {action: 'same', external_id: '4', uid: 'u4', name: 'Sin tocar', short: 'ST',
     description: '', was: {name: 'Sin tocar', short: 'ST', description: ''}}],
};

// Lo que `freshserviceImport` marca de serie, sin llamar al servidor.
_fsPlan = D2; _fsLink = {}; _fsQuery = '';
_fsPick = _fsDefaultPick(D2.plan);
__out.marcadasDeSerie = JSON.stringify(Array.from(_fsPick).sort());

// El filtro: por nombre, por abreviatura y por descripción.
const conFiltro = (q) => { _fsQuery = q; return _fsRowsHtml(D2); };
__out.porNombre = conFiltro('amixalan');
__out.porAbreviatura = conFiltro('acsac');
__out.porDescripcion = conFiltro('holding');
__out.sinFiltro = conFiltro('');
__out.grupos = conFiltro('');
__out.gruposSoloNuevas = (function () { _fsQuery = 'alfa'; const h = _fsRowsHtml(D2);
                                        _fsQuery = ''; return h; })();
__out.sinResultados = conFiltro('no existe nada asi');

// Y «todas» con un filtro puesto: sobre lo que se ve, no sobre lo que hay.
_fsQuery = 'alfa';
_fsPick = new Set();
_fsToggleAll(true);
__out.todasConFiltro = JSON.stringify(Array.from(_fsPick).sort());
_fsQuery = '';

"""


@pytest.fixture(scope='module')
def tabla():
    """La tabla del plan, dibujada de verdad."""
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
    return node_run(panel_bundle(c), _PRUEBA)


class TestLaFilaYaAtadaDiceAQuien:
    """Salía con «— crear una nueva —» en su desplegable. Lo que la fila decía que iba a hacer y
    lo que iba a hacer eran cosas distintas — y la que se lee es la que decía."""

    def test_su_empresa_sale_elegida(self, tabla):
        fila = tabla['atada']
        assert 'u-amx' in fila, 'su empresa ni siquiera se ofrece'
        # La opción de SU empresa es la marcada.
        trozo = fila.split('value="u-amx"')[1][:20]
        assert 'selected' in trozo, 'sale sin elegir, como si fuera nueva'

    def test_y_no_se_le_ofrece_crear_otra(self, tabla):
        """Una fila que ya es una empresa de aquí no puede «crear una nueva»: sería duplicarla
        y dejar la vieja huérfana.

        Por la opción vacía y no por su texto, que depende del idioma de quien mire: buscar la
        frase en castellano en una sesión en inglés es una comprobación que pasa siempre."""
        assert '<option value=""' not in tabla['atada']

    def test_pero_a_una_nueva_si(self, tabla):
        assert '<option value=""' in tabla['nueva']

    def test_y_se_puede_cambiar_a_otra_de_aqui(self, tabla):
        """Corregir un emparejamiento equivocado tiene que poder hacerse desde la misma
        pantalla."""
        assert 'u-libre' in tabla['atada']

    def test_pero_no_a_una_que_ya_es_de_otro_departamento(self, tabla):
        """Una empresa compartida por dos departamentos cambia de nombre sola en cada
        importación."""
        assert 'u-otro' not in tabla['atada']
        assert 'u-otro' not in tabla['nueva']


class TestLaFilaEnseñaLoQueSeVaATraer:
    """La columna de la descripción enseñaba el nombre viejo cuando había cambio, así que la
    fila parecía traerse los datos de aquí en lugar de los de Freshservice."""

    def test_la_descripcion_es_la_del_origen(self, tabla):
        assert 'Holding del grupo' in tabla['atada']

    def test_y_lo_que_se_pierde_se_enseña_tachado_y_en_su_columna(self, tabla):
        """Antes → ahora, cada cosa en su sitio: el nombre viejo bajo el nombre, no metido en la
        descripción."""
        fila = tabla['atada']
        assert 'text-decoration-line-through' in fila
        nombre = fila.split('Amixalan, S.L.')[1].split('</td>')[0]
        assert 'Amixalan<' in nombre or '>Amixalan' in nombre, 'el nombre viejo no está donde va'
        desc = fila.split('Holding del grupo')[1].split('</td>')[0]
        assert 'lo de antes' in desc

    def test_y_lo_que_no_cambia_no_se_tacha(self, tabla):
        """La abreviatura es la misma: tacharla diría que se va a perder algo que se queda."""
        fila = tabla['atada']
        corta = fila.split('AXL')[1].split('</td>')[0]
        assert 'line-through' not in corta


class TestElegirLaQueYaEstabaNoEsEmparejar:

    def test_no_se_guarda_como_hecho_a_mano(self, tabla):
        """Guardarlo haría que la fila dijera «se adopta» cuando no cambia de empresa — y que se
        marcara sola una que no tenía nada que hacer."""
        assert tabla['linkTrasElegirLaSuya'] == '{}'

    def test_pero_cambiarla_a_otra_si(self, tabla):
        assert '"7":"u-libre"' in tabla['linkTrasCambiarla'].replace(' ', '')

    def test_y_entonces_la_fila_pasa_a_decir_que_se_adopta(self, tabla):
        assert 'fs_act_adopt' in tabla['htmlCambiada'] or 'Se adopta' in tabla['htmlCambiada'] \
            or 'Adopted' in tabla['htmlCambiada']

class TestSeMarcaDeSerieLoQueYaSeMantieneAqui:
    """Cincuenta y nueve departamentos no son cincuenta y nueve sociedades de las que aquí se
    quiera saber nada. Refrescar lo que ya se mantiene aquí es rutina; traer una nueva es una
    decisión — y marcarlas de serie hacía que la rutina creara cincuenta y seis filas que nadie
    pidió, salvo que alguien se acordara de desmarcarlas."""

    def test_solo_las_que_ya_estan_atadas_y_han_cambiado(self, tabla):
        assert tabla['marcadasDeSerie'] == '["1"]'

    def test_lo_que_dice_es_que_una_nueva_se_elige_a_mano(self, tabla):
        """`create` y `adopt` no se marcan: la primera no está aquí, y la segunda es un
        emparejamiento que alguien tiene que querer."""
        marcadas = tabla['marcadasDeSerie']
        assert '"2"' not in marcadas and '"3"' not in marcadas

    def test_ni_las_que_no_tienen_nada_que_hacer(self, tabla):
        assert '"4"' not in tabla['marcadasDeSerie']


class TestElBuscadorMiraLasTresCosas:
    """Quien busca «amixalan» no sabe si lo que recuerda era el nombre, la chapa o la
    descripción."""

    def test_por_nombre(self, tabla):
        assert 'Amixalan, S.L.' in tabla['porNombre']
        assert 'Alfa Co' not in tabla['porNombre']

    def test_por_abreviatura(self, tabla):
        assert 'Alfa Co' in tabla['porAbreviatura']
        assert 'Amixalan, S.L.' not in tabla['porAbreviatura']

    def test_y_por_descripcion(self, tabla):
        assert 'Amixalan, S.L.' in tabla['porDescripcion']
        assert 'Behar' not in tabla['porDescripcion']

    def test_y_sin_nada_escrito_salen_todas(self, tabla):
        for nombre in ('Amixalan, S.L.', 'Alfa Co', 'Behar Consultores', 'Sin tocar'):
            assert nombre in tabla['sinFiltro'], nombre

    def test_y_lo_que_no_está_no_sale(self, tabla):
        assert tabla['sinResultados'].strip() == ''


class TestTodasEsLoQueSeVe:
    """Con un filtro puesto, «todas» son las que se están mirando: marcar también las que el
    filtro esconde es marcar a ciegas, que es justo lo que el filtro estaba evitando."""

    def test_marca_solo_lo_filtrado(self, tabla):
        assert tabla['todasConFiltro'] == '["2"]'


class TestPrimeroLoQueYaEstaVinculado:
    """Con cincuenta y nueve departamentos, los tres que ya se mantienen aquí —que son los que
    se vienen a mirar— salían repartidos por orden alfabético entre cincuenta y seis que no. Son
    dos preguntas distintas: «¿qué le pasa a lo mío?» y «¿qué más hay?»."""

    def test_las_vinculadas_van_delante(self, tabla):
        html = tabla['grupos']
        assert html.index('Amixalan, S.L.') < html.index('Alfa Co'), 'no van primero'

    def test_y_cada_grupo_dice_cuantos_tiene(self, tabla):
        """«(3)» y «(56)» es la mitad de la respuesta: cuánto de esto es mío y cuánto no."""
        assert '(3)' in tabla['grupos'] and '(1)' in tabla['grupos']

    def test_pero_sin_los_dos_grupos_no_hay_separador(self, tabla):
        """Un título sobre una lista entera no separa nada."""
        assert 'table-active' not in tabla['gruposSoloNuevas']
        assert 'Alfa Co' in tabla['gruposSoloNuevas']
