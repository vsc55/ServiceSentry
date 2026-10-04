#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deshacer y rehacer en los planos, en `node` sobre el guion del panel.

Se pidió desde la pantalla: en el plano todo se guarda al soltar, y mover algo que no se debía
ya estaba en el servidor. Lo que fijan estas pruebas:

- un cambio a algo del plano abierto se apunta con cómo estaba según lo GUARDADO, no según el
  dibujo, que al soltar ya enseña lo nuevo;
- dos cambios seguidos a la misma cosa son uno; lo que no cambia nada no se apunta, y lo que
  no es del plano tampoco;
- deshacer devuelve los valores al dibujo y a lo guardado, y rehacer los vuelve a poner;
- un cambio nuevo olvida lo rehacible, y abrir otro plano empieza de cero;
- los botones dicen qué desharían, y están apagados sin nada que deshacer.

El envío al servidor es asíncrono y el arnés no espera a las promesas: se prueba aquí lo que
hace cada paso, y la guarda de `tests/meta` comprueba que `_dcimSend` los llama.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='sin node: no hay con qué ejecutar el guion')

_PRUEBA = r"""
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
_dcimData = {orgs: [], sites: []};
const U = (tipo, uid) => `/api/v1/dcim/${tipo}/${uid}`;
_dcimPlan = {room: {uid: 'r1', name: 'CPD', width_mm: 6000},
             racks: [{uid: 'k1', name: 'R01', pos_x: 1000, pos_y: 1000, rotation: 0}]};
_dcpFeat = {features: [{uid: 'f1', kind: 'tray', label: 'Bandeja', pos_x: 0}], kinds: {}};
_dcsPlan = null;
__out = {};
_dcUndoPrime();
__out.vacio = _dcUndoButtonsInner().split('disabled').length - 1;

// El dibujo ya dice lo nuevo al soltar; lo de antes sale de lo guardado.
const rack = _dcimPlan.racks[0];
rack.pos_x = 2000;
const antes1 = _dcUndoBefore(U('racks', 'k1'), {pos_x: 2000});
_dcUndoRecord(U('racks', 'k1'), antes1, {pos_x: 2000});
__out.antes = antes1;
// Seguido, a la misma cosa: uno.
rack.pos_x = 2500;
_dcUndoRecord(U('racks', 'k1'), _dcUndoBefore(U('racks', 'k1'), {pos_x: 2500}), {pos_x: 2500});
__out.juntos = _dcUndoStack.map(e => [e.before.pos_x, e.after.pos_x]);
// Lo que no cambia nada, y lo que no es del plano, no se apuntan.
_dcUndoRecord(U('racks', 'k1'), _dcUndoBefore(U('racks', 'k1'), {pos_x: 2500}), {pos_x: 2500});
__out.ajeno = _dcUndoBefore(U('racks', 'otro'), {pos_x: 1});
__out.tras = _dcUndoStack.length;
__out.titulo = _dcUndoButtonsInner().includes(tf('dcim_undo', 'R01'));

// Deshacer: arriba sale la entrada, y al aceptarlo el servidor vuelve el dibujo.
const e = _dcUndoStack.pop();
_dcUndoDone(e, e.before, _dcRedoStack);
__out.deshecho = [rack.pos_x, _dcUndoShadow.get(U('racks', 'k1')).pos_x, _dcRedoStack.length];
// Rehacer.
const r = _dcRedoStack.pop();
_dcUndoDone(r, r.after, _dcUndoStack);
__out.rehecho = [rack.pos_x, _dcUndoStack.length];
// Un cambio nuevo olvida lo rehacible.
_dcRedoStack.push({url: 'x', before: {}, after: {}});
const f = _dcpFeat.features[0];
f.label = 'Mesa';
_dcUndoRecord(U('features', 'f1'), _dcUndoBefore(U('features', 'f1'), {label: 'Mesa'}), {label: 'Mesa'});
__out.sinRehacer = _dcRedoStack.length;
// Otro plano empieza de cero.
_dcimPlan = {room: {uid: 'r2'}, racks: []};
_dcpFeat = {features: [], kinds: {}};
_dcUndoPrime();
__out.otroPlano = [_dcUndoStack.length, _dcRedoStack.length];
// En el plano de una sede: las salas, las plantas y lo de dentro.
_dcimPlan = null;
_dcsPlan = {site: {uid: 's1', rooms: [{uid: 'r9', name: 'Sala 9', pos_x: 0}]},
            floors: [{uid: 'p1', plan_x: 0}], floor: 'p1',
            content: {r9: {racks: [{uid: 'k9', pos_x: 0}], features: []}}};
_dcUndoPrime();
__out.sede = [U('rooms', 'r9'), U('floors', 'p1'), U('racks', 'k9')].every(u => _dcUndoShadow.has(u));
"""


@pytest.fixture(scope='module')
def out():
    """Una sola ejecución de `node` para todo el módulo: arrancarlo cuesta más que mirar."""
    pytest.importorskip('flask')
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


class TestSeApunta:
    def test_lo_de_antes_sale_de_lo_guardado_no_del_dibujo(self, out):
        assert out['antes'] == {'pos_x': 1000}

    def test_dos_cambios_seguidos_son_uno(self, out):
        assert out['juntos'] == [[1000, 2500]]

    def test_lo_que_no_cambia_ni_lo_ajeno_se_apunta(self, out):
        assert out['tras'] == 1
        assert out['ajeno'] is None

    def test_el_boton_dice_que_desharia(self, out):
        assert out['titulo']
        assert out['vacio'] == 2, 'sin nada que deshacer, los dos botones apagados'


class TestDeshacerYRehacer:
    def test_deshacer_devuelve_el_dibujo_y_lo_guardado(self, out):
        assert out['deshecho'] == [1000, 1000, 1]

    def test_rehacer_lo_vuelve_a_poner(self, out):
        assert out['rehecho'] == [2500, 1]

    def test_un_cambio_nuevo_olvida_lo_rehacible(self, out):
        assert out['sinRehacer'] == 0

    def test_otro_plano_empieza_de_cero(self, out):
        assert out['otroPlano'] == [0, 0]

    def test_en_el_plano_de_una_sede_tambien(self, out):
        assert out['sede']
