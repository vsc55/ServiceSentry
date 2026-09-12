#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Una marca de tiempo en segundos no es enero de 1970.

`new Date(numero)` cuenta **milisegundos**, y media aplicación guarda **segundos**: el estado de
cada comprobación (`check_state.last_change_ts`) y cada muestra del historial (`history.ts`)
llevan una época en segundos, con decimales. Pasada tal cual al formateador del panel, una fecha
de 2026 salía como **1970-01-21** — en toda la columna «Última actividad» de la ficha de una
máquina, y también en la vista de tarjetas, donde sólo se multiplicaba la del historial.

Un fallo que no rompe nada y que no se puede ver leyendo el fuente: la función existe, no
revienta, y devuelve una fecha perfectamente formateada. Sólo que de hace cincuenta y seis años.
Reportado desde la pantalla.

Así que esto **ejecuta** el formateador con los tres números que le llegan de verdad — segundos,
milisegundos y una fecha ISO — y mira lo que sale.
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

#: Un instante REAL de los que guarda esta aplicación: 2026-09-06, en segundos y con decimales,
#: que es exactamente la forma en la que llega desde la base de datos.
_SEG = 1788720633.4313095
_MS = 1788720633431

_PRUEBA = """
__out = {};
__out.enSegundos   = _fmtDateTime(%(seg)r);
__out.enMilisegundos = _fmtDateTime(%(ms)d);
__out.mismoInstante = _toDate(1788720633).getTime() === _toDate(1788720633000).getTime();
// Una fecha ISO —que es como viaja el resto del panel— no se toca.
__out.iso = _fmtDateTime('2026-09-06T12:00:00Z');
// Y lo que no es una fecha sigue saliendo como estaba: es lo que deja ver que algo va mal.
__out.vacio  = _fmtDateTime('');
__out.basura = _fmtDateTime('no-es-una-fecha');
// El número de una época en milisegundos de verdad, que no se puede multiplicar otra vez.
__out.anioMs = _toDate(%(ms)d).getFullYear();
__out.anioSeg = _toDate(%(seg)r).getFullYear();
""" % {'seg': _SEG, 'ms': _MS}


@pytest.fixture(scope='module')
def fechas():
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


class TestUnaEpocaEnSegundosSeLeeComoSegundos:
    """El año es lo que se comprueba y no la hora: la hora depende del huso de quien mira, y una
    prueba que fije la hora falla en media Europa sin que nada esté mal."""

    def test_no_es_1970(self, fechas):
        assert fechas['enSegundos'].startswith('2026-'), fechas['enSegundos']
        assert fechas['anioSeg'] == 2026

    def test_y_los_milisegundos_siguen_siendo_milisegundos(self, fechas):
        """El corte va en 1e12: en milisegundos eso es septiembre de 2001 y en segundos el año
        33.658. Volver a multiplicar los milisegundos mandaría la fecha al año 58.000."""
        assert fechas['anioMs'] == 2026, fechas['anioMs']

    def test_y_las_dos_formas_dan_el_mismo_instante(self, fechas):
        """Que es lo que quiere decir «se entienden las dos»: no dos fechas parecidas, la
        misma."""
        assert fechas['mismoInstante'] is True

    def test_los_dos_numeros_se_escriben_igual(self, fechas):
        assert fechas['enSegundos'] == fechas['enMilisegundos']


class TestYLoDemasSigueComoEstaba:
    """La otra mitad de arreglar un formateador que usan treinta pantallas."""

    def test_una_fecha_iso_no_se_toca(self, fechas):
        assert fechas['iso'].startswith('2026-09-06'), fechas['iso']

    def test_sin_fecha_sale_la_raya(self, fechas):
        assert fechas['vacio'] == '—'

    def test_y_lo_que_no_es_una_fecha_se_devuelve_tal_cual(self, fechas):
        """Enseñar el texto crudo deja ver que algo va mal; «NaN-NaN-NaN» no dice nada."""
        assert fechas['basura'] == 'no-es-una-fecha'
