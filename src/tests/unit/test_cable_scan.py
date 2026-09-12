#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — alguien movió un latiguillo y nadie se enteró.
#
"""El panel ya sabía que un cable había cambiado de puerto; lo que no hacía era decirlo.

`cable_check` contrasta lo declarado contra lo que los dispositivos ven por LLDP y marca
`other_port` cuando los puertos que nombran no son los escritos. Eso existía. Pero sólo aparecía
si alguien abría la pestaña de cableado y pulsaba Contraste, que para un armario que se toca dos
veces al año es lo mismo que no saberlo.

Lo que estas pruebas sujetan no es la detección —ya estaba probada— sino las tres cosas que
hacen que un aviso automático sirva en vez de estorbar:

* que **no escriba** en el inventario: el descubrimiento propone;
* que **no se repita** más de lo que se le ha pedido, y que lo ya dicho sobreviva a un cambio
  de proceso, porque esto corre en contenedores y el que explora hoy no es el de mañana;
* que **vuelva a avisar** cuando la cosa cambia otra vez, que es lo contrario de callarse.

Sin Flask: la parte que decide qué es un hallazgo es una función pura, y el resto recibe sus
dependencias por parámetro.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.dcim.drift import DriftStore                        # noqa: E402
from lib.core.health.cable_scan import (MAX_PER_SCAN, MOVED,       # noqa: E402
                                        UNDECLARED, CableDriftScanner, findings)
from lib.db import get_connector                                  # noqa: E402


def _check(movidos=(), sin_declarar=(), checked=True):
    """Lo que devolvería `cable_check`, con lo justo para decidir."""
    cables = [{'uid': uid, 'seen': 'other_port', 'a_port': dec[0], 'b_port': dec[1],
               'ports_seen': list(vistos), 'a_label': 'srv1', 'b_label': 'sw1', 'label': uid}
              for uid, dec, vistos in movidos]
    cables.append({'uid': 'ok1', 'seen': 'seen', 'a_port': 'eth0', 'b_port': 'gi1'})
    und = [{'from': a, 'to': b, 'ports': {a: pa, b: pb}, 'a_port': pa, 'b_port': pb,
            'a_item': 'i-' + a, 'b_item': 'i-' + b, 'bundle': 1}
           for a, b, pa, pb in sin_declarar]
    return {'cables': cables, 'undeclared': und, 'checked': checked, 'counts': {}}


class _Estado:
    """Un `DriftStore` de verdad sobre una base en memoria."""

    def __init__(self, path=':memory:'):
        self.store = DriftStore(get_connector(None, default_sqlite_path=path))


def _scanner(check, estado, cfg, dichos):
    return CableDriftScanner(
        check_provider=lambda: check,
        state=estado.store,
        dispatch=lambda kind, **f: dichos.append((kind, f)),
        config_getter=lambda: cfg,
        is_leader=lambda: True,
        text_fn=lambda k, *a: k)


class TestQueEsUnHallazgo:

    def test_un_cable_en_otro_puerto(self):
        h = findings(_check(movidos=[('c1', ('eth0', 'gi9'), ('eth0', 'gi11'))]))
        assert list(h) == ['moved:c1']
        assert h['moved:c1']['kind'] == MOVED
        assert h['moved:c1']['seen'] == ['eth0', 'gi11']

    def test_un_cable_que_coincide_no_es_un_hallazgo(self):
        """La fila `seen` es la mayoría de la tabla. Avisar de ella sería avisar de que todo
        está bien, cada media hora."""
        assert findings(_check()) == {}

    def test_una_adyacencia_sin_declarar(self):
        h = findings(_check(sin_declarar=[('hA', 'hB', 'eth0', 'gi3')]))
        assert list(h) == ['undeclared:hA|hB']
        assert h['undeclared:hA|hB']['kind'] == UNDECLARED

    def test_el_par_va_ordenado(self):
        """Estar enchufados es simétrico. Si el orden de una consulta decidiera quién va
        primero, el mismo hallazgo saldría dos veces con dos claves."""
        uno = findings(_check(sin_declarar=[('hB', 'hA', 'gi3', 'eth0')]))
        otro = findings(_check(sin_declarar=[('hA', 'hB', 'eth0', 'gi3')]))
        assert list(uno) == list(otro) == ['undeclared:hA|hB']

    def test_la_huella_cambia_si_el_puerto_cambia(self):
        """Es lo que distingue «sigue movido» de «lo han vuelto a mover»."""
        a = findings(_check(movidos=[('c1', ('eth0', 'gi9'), ('eth0', 'gi11'))]))
        b = findings(_check(movidos=[('c1', ('eth0', 'gi9'), ('eth0', 'gi12'))]))
        assert a['moved:c1']['fingerprint'] != b['moved:c1']['fingerprint']


class TestAvisarUnaVez:

    def test_la_primera_vuelta_avisa(self):
        dichos = []
        est = _Estado()
        sc = _scanner(_check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))]), est,
                      {'notify_cabling': True}, dichos)
        assert sc.evaluate_once(now=1000.0)
        assert [k for k, _ in dichos] == [MOVED]

    def test_y_la_segunda_no(self):
        dichos = []
        est = _Estado()
        ch = _check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))])
        sc = _scanner(ch, est, {'notify_cabling': True}, dichos)
        sc.evaluate_once(now=1000.0)
        sc.evaluate_once(now=99000.0)
        assert len(dichos) == 1, 'repitió el mismo aviso'

    def test_apagado_no_dice_nada(self):
        dichos = []
        est = _Estado()
        sc = _scanner(_check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))]), est,
                      {'notify_cabling': False}, dichos)
        assert sc.evaluate_once(now=1000.0) == {}
        assert dichos == []

    def test_si_no_es_el_lider_se_calla(self):
        """En un despliegue con varias réplicas, todas ven lo mismo. Sin esto, un hallazgo se
        cuenta tantas veces como contenedores haya."""
        dichos = []
        est = _Estado()
        sc = CableDriftScanner(
            check_provider=lambda: _check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))]),
            state=est.store, dispatch=lambda kind, **f: dichos.append((kind, f)),
            config_getter=lambda: {'notify_cabling': True}, is_leader=lambda: False,
            text_fn=lambda k, *a: k)
        assert sc.evaluate_once(now=1000.0) == {}
        assert dichos == []

    def test_si_no_se_ha_podido_preguntar_no_se_toca_nada(self):
        """`checked` falso es «no se ha podido mirar», no «no hay nada». Confundirlos borraría
        el estado y al volver lo anunciaría todo otra vez como si fuese nuevo."""
        dichos = []
        est = _Estado()
        sc = _scanner(_check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))]), est,
                      {'notify_cabling': True}, dichos)
        sc.evaluate_once(now=1000.0)
        sc._check = lambda: _check(checked=False)
        sc.evaluate_once(now=2000.0)
        assert est.store.known(), 'una sonda muda borró lo que ya se sabía'


class TestVolverAAvisarCuandoCambia:

    def test_movido_a_otra_boca_vuelve_a_avisar(self):
        dichos = []
        est = _Estado()
        sc = _scanner(_check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))]), est,
                      {'notify_cabling': True}, dichos)
        sc.evaluate_once(now=1000.0)
        sc._check = lambda: _check(movidos=[('c1', ('eth0', 'gi9'), ('gi12',))])
        sc.evaluate_once(now=1100.0)
        assert len(dichos) == 2, 'lo movieron otra vez y se calló'

    def test_arreglado_y_vuelto_a_romper_avisa_otra_vez(self):
        """Sin olvidar lo que ya no se ve, el primer aviso sería también el último."""
        dichos = []
        est = _Estado()
        ch = _check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))])
        sc = _scanner(ch, est, {'notify_cabling': True}, dichos)
        sc.evaluate_once(now=1000.0)
        sc._check = lambda: _check()                 # alguien lo corrigió
        sc.evaluate_once(now=2000.0)
        assert est.store.known() == {}, 'no olvidó el hallazgo resuelto'
        sc._check = lambda: ch                       # y volvió a pasar
        sc.evaluate_once(now=3000.0)
        assert len(dichos) == 2


class TestCuantoInsiste:
    """Los dos ajustes tienen que dar los cinco comportamientos que se pueden querer."""

    def _correr(self, cfg, veces=6, paso=3600.0):
        dichos = []
        est = _Estado()
        sc = _scanner(_check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))]), est, cfg, dichos)
        for i in range(veces):
            sc.evaluate_once(now=1000.0 + i * paso)
        return len(dichos)

    def test_no_avisar(self):
        assert self._correr({'notify_cabling': False}) == 0

    def test_una_sola_vez(self):
        assert self._correr({'notify_cabling': True}) == 1
        assert self._correr({'notify_cabling': True, 'cable_repeat_every_secs': 0}) == 1
        assert self._correr({'notify_cabling': True, 'cable_repeat_every_secs': 3600,
                             'cable_repeat_max': 1}) == 1

    def test_repetir_para_siempre(self):
        assert self._correr({'notify_cabling': True, 'cable_repeat_every_secs': 3600,
                             'cable_repeat_max': 0}, veces=6) == 6

    def test_repetir_un_numero_de_veces(self):
        assert self._correr({'notify_cabling': True, 'cable_repeat_every_secs': 3600,
                             'cable_repeat_max': 3}, veces=8) == 3

    def test_el_intervalo_se_respeta(self):
        """Repetir cada hora y mirar cada diez minutos no son seis avisos por hora."""
        assert self._correr({'notify_cabling': True, 'cable_repeat_every_secs': 3600,
                             'cable_repeat_max': 0}, veces=6, paso=600.0) == 1

    def test_un_cambio_manda_sobre_el_tope(self):
        """Gastadas las repeticiones, el mismo latiguillo movido a una tercera boca es un hecho
        nuevo — y el contador vuelve a empezar."""
        dichos = []
        est = _Estado()
        cfg = {'notify_cabling': True, 'cable_repeat_every_secs': 3600, 'cable_repeat_max': 2}
        sc = _scanner(_check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))]), est, cfg, dichos)
        for i in range(5):
            sc.evaluate_once(now=1000.0 + i * 3600)
        assert len(dichos) == 2
        sc._check = lambda: _check(movidos=[('c1', ('eth0', 'gi9'), ('gi12',))])
        sc.evaluate_once(now=90000.0)
        assert len(dichos) == 3
        assert est.store.known()['moved:c1']['times'] == 1, 'el contador no volvió a empezar'


class TestLoQueYaSeDijoSobreviveAlProceso:
    """Esto corre en contenedores: el que explora hoy no es el de mañana. Un diccionario en
    memoria se lleva por delante «ya te lo dije» en cada despliegue."""

    def test_otro_proceso_no_vuelve_a_avisar(self, tmp_path):
        base = str(tmp_path / 'd.db')
        ch = _check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))])
        primeros = []
        uno = _scanner(ch, _Estado(base), {'notify_cabling': True}, primeros)
        uno.evaluate_once(now=1000.0)
        assert len(primeros) == 1
        segundos = []
        otro = _scanner(ch, _Estado(base), {'notify_cabling': True}, segundos)
        otro.evaluate_once(now=2000.0)
        assert segundos == [], 'el pod nuevo volvió a anunciar el atraso entero'

    def test_y_el_contador_de_repeticiones_tambien(self, tmp_path):
        base = str(tmp_path / 'd.db')
        ch = _check(movidos=[('c1', ('eth0', 'gi9'), ('gi11',))])
        cfg = {'notify_cabling': True, 'cable_repeat_every_secs': 3600, 'cable_repeat_max': 2}
        a = []
        _scanner(ch, _Estado(base), cfg, a).evaluate_once(now=1000.0)
        b = []
        _scanner(ch, _Estado(base), cfg, b).evaluate_once(now=5000.0)
        c = []
        _scanner(ch, _Estado(base), cfg, c).evaluate_once(now=9000.0)
        assert (len(a), len(b), len(c)) == (1, 1, 0), 'el tope no cruzó de proceso a proceso'


class TestNoEscribeEnElInventario:

    def test_el_explorador_no_nombra_ninguna_tabla_del_inventario(self):
        """El descubrimiento **propone**. Lo declarado es lo que alguien declaró, y un
        inventario que se corrige solo deja de ser un inventario para ser un informe.

        Por el árbol y no por el texto: el docstring del módulo explica justamente esta regla y
        nombra `dc_cable` al hacerlo. Una guarda que lee la prosa tropieza con el comentario que
        explica lo que está comprobando — que es el motivo de que `_strip_comments` exista para
        los ficheros de pantalla.
        """
        import ast as _ast                                           # noqa: PLC0415
        import io as _io                                             # noqa: PLC0415
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        arbol = _ast.parse(_io.open(os.path.join(src, 'lib', 'core', 'health', 'cable_scan.py'),
                                    encoding='utf-8').read())
        docs = set()
        for n in _ast.walk(arbol):
            if isinstance(n, (_ast.Module, _ast.ClassDef, _ast.FunctionDef,
                              _ast.AsyncFunctionDef)):
                d = _ast.get_docstring(n, clean=False)
                if d:
                    docs.add(d)
        codigo = [n.value for n in _ast.walk(arbol)
                  if isinstance(n, _ast.Constant) and isinstance(n.value, str)
                  and n.value not in docs]
        for texto in codigo:
            for prohibido in ('dc_cable', 'dc_item', 'dc_part', 'INSERT', 'UPDATE', 'DELETE'):
                assert prohibido not in texto, (
                    f'el explorador nombra {prohibido!r} en {texto!r}: propone, no escribe')
        # Y no tiene por dónde: nunca recibe un conector, así que no puede ejecutar nada.
        llamadas = {n.func.attr for n in _ast.walk(arbol)
                    if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)}
        assert not ({'execute', 'executemany', 'commit', 'execute_ddl'} & llamadas), (
            f'el explorador ejecuta SQL: {llamadas}')


class TestUnArmarioEnteroNoSonCienMensajes:

    def test_hay_un_tope_por_vuelta(self):
        dichos = []
        est = _Estado()
        muchos = [(f'c{i}', ('eth0', 'gi1'), ('gi2',)) for i in range(MAX_PER_SCAN + 5)]
        sc = _scanner(_check(movidos=muchos), est, {'notify_cabling': True}, dichos)
        sc.evaluate_once(now=1000.0)
        assert len(dichos) == MAX_PER_SCAN

    def test_y_lo_que_sobra_se_dice_en_la_siguiente(self):
        dichos = []
        est = _Estado()
        muchos = [(f'c{i}', ('eth0', 'gi1'), ('gi2',)) for i in range(MAX_PER_SCAN + 5)]
        sc = _scanner(_check(movidos=muchos), est, {'notify_cabling': True}, dichos)
        sc.evaluate_once(now=1000.0)
        sc.evaluate_once(now=2000.0)
        assert len(dichos) == MAX_PER_SCAN + 5, 'los que sobraron se perdieron'
