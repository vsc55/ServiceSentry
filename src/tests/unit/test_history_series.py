#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — una fila por serie, no por muestra.
#
"""Lo que no cambia entre dos lecturas de la misma cosa deja de escribirse en cada una.

Medido sobre una instalación real: SNMP es el **83 %** de las filas del histórico, y de los 217
bytes que ocupa una de sus muestras, **11 son la medida**. Cincuenta y cuatro son la clave
—`host.<uuid>/<fila>`, reescrita entera cada vez— y el resto es identidad que no cambia nunca
más los nombres de los campos, repetidos. El plan entero está en `docs/explica-snmp.md`.

La migración que llevó una base de datos de la forma vieja a ésta ya no está en el código: se
ejecutó, y un camino que sólo puede correr una vez y ya corrió es código muerto que hay que
seguir manteniendo. Lo que queda aquí es la forma de ahora — cómo se crea una serie, cómo se
escribe una muestra y cómo se lee — que es lo que sí se puede romper mañana.

Sin Flask, ni directa ni transitivamente: un conector, un store y filas.
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.db import get_connector                      # noqa: E402
from lib.core.history.store import HistoryStore       # noqa: E402


def _store():
    return HistoryStore(get_connector(None, default_sqlite_path=':memory:'))


def _fuente(nombre):
    """El cuerpo de un método del store, tal cual está escrito."""
    src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
    cuerpo = io.open(os.path.join(src, 'lib', 'core', 'history', 'store.py'),
                     encoding='utf-8').read()
    return cuerpo.split('def ' + nombre)[1].split(chr(10) + '    def ')[0]


def _resumen(st):
    """``{(module, key): (samples, up_samples, last_status, last_data)}``."""
    filas = st._db.fetchall(
        'SELECT module, %s, samples, up_samples, last_status, last_data '
        'FROM history_series' % st._qk)
    return {(r[0], r[1]): (r[2], r[3], r[4], r[5]) for r in filas}


def _con_documento(st, module, key, medidas):
    """Fabricar una muestra **de antes del cambio**: con su documento y sin hechos.

    Es la única forma honrada de probar el paso: volver a poner la columna que se retiró y
    escribir en ella lo que escribía la versión anterior.
    """
    import json as _json                                              # noqa: PLC0415
    import time as _time                                              # noqa: PLC0415
    sid = st.series_id(module, key)
    if 'data' not in st._db.list_columns('history'):
        st._db.execute_ddl('ALTER TABLE history ADD COLUMN data TEXT')
    st._db.execute(
        'INSERT INTO history(ts, item_uid, status, series_id, data) VALUES(?, ?, ?, ?, ?)',
        (_time.time(), None, 1, sid, _json.dumps(medidas)))
    st._db.commit()
    return sid


def _series(st):
    """``{(module, key): (id, first_ts, last_ts)}`` leído de la tabla."""
    filas = st._db.fetchall(
        'SELECT id, module, %s, first_ts, last_ts FROM history_series' % st._qk)
    return {(r[1], r[2]): (r[0], r[3], r[4]) for r in filas}


class TestPedirElIdDeUnaSerie:

    def test_la_crea_la_primera_vez_y_luego_la_encuentra(self):
        st = _store()
        primero = st.series_id('cpu', 'srv1')
        assert primero
        assert st.series_id('cpu', 'srv1') == primero
        assert len(_series(st)) == 1

    def test_dos_series_no_comparten_id(self):
        st = _store()
        assert st.series_id('cpu', 'srv1') != st.series_id('cpu', 'srv2')

    def test_y_el_id_sobrevive_a_otro_store_sobre_la_misma_base(self):
        """Que es el caso de verdad: el panel y el monitor son dos procesos, y la caché de cada
        uno no puede decidir qué serie es cuál. Lo decide el índice único."""
        st = _store()
        esperado = st.series_id('snmp', 'host.h1/eth0')
        otro = HistoryStore(st._db)
        assert otro.series_id('snmp', 'host.h1/eth0') == esperado

    def test_una_serie_que_ya_existe_no_se_duplica_aunque_la_cache_este_vacia(self):
        st = _store()
        esperado = st.series_id('cpu', 'srv1')
        st._series_ids.clear()
        assert st.series_id('cpu', 'srv1') == esperado
        assert len(_series(st)) == 1


    def test_dos_filas_de_la_misma_serie_son_imposibles(self):
        """Y lo impide la BASE, no el código: el panel y el monitor son dos procesos que pueden
        ver la misma serie por primera vez a la vez, y el que pierda la carrera tiene que
        encontrarse la fila del otro, no crear una segunda. Sin el índice único no falla nada —
        aparecen dos series de lo mismo y las gráficas se parten en dos, cada una con la mitad
        de las muestras."""
        import pytest                                                # noqa: PLC0415
        st = _store()
        st.series_id('cpu', 'srv1')
        with pytest.raises(Exception):
            st._db.execute(
                f'INSERT INTO history_series(module, {st._qk}) VALUES(?, ?)', ('cpu', 'srv1'))

    def test_y_no_se_vuelve_a_preguntar_por_una_que_ya_se_resolvio(self):
        """Una serie se crea una vez y se lee en cada muestra: con noventa mil muestras al día,
        una consulta por muestra para traducir la misma pareja es la mitad del coste de escribir
        el histórico."""
        st = _store()
        esperado = st.series_id('cpu', 'srv1')

        def _prohibido(*_a, **_k):
            raise AssertionError('volvió a preguntarle a la base por una serie ya resuelta')

        st._db.fetchone = _prohibido
        assert st.series_id('cpu', 'srv1') == esperado


class TestCadaMuestraApuntaASuSerie:
    """Paso 4. La columna es anulable a propósito: una muestra grabada cuando la serie no se
    pudo resolver **sigue siendo una muestra**. Perder el id cuesta un `join`; rechazar la fila
    cuesta la medida."""

    def test_una_muestra_nueva_nace_apuntando(self):
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'v': 1})
        fila = st._db.fetchone('SELECT series_id FROM history')
        assert fila[0] == st.series_id('cpu', 'srv1')

class TestLaMuestraLlevaMedidasYLaSerieLlevaIdentidad:
    """Paso 5. De los 217 bytes que ocupaba una muestra SNMP, **78 eran esto**: la MAC, el
    alias y el nombre de la fila, reescritos en cada lectura de la misma interfaz.

    La frontera no se inventa aquí — es la que ya usan los módulos: una clave que empieza por
    `_` habla *del* resultado y no es una medida suya."""

    _MUESTRA = {'if_in': 5, '_attrs': {'p1': {'mac': 'aa:bb'}}, '_row': 'eth0',
                '_watched': True}

    def test_lo_que_se_escribe_es_solo_la_medida(self):
        """La muestra ya no guarda un documento: guarda una fila por valor medido. La
        frontera es la misma y el sitio donde se comprueba, otro."""
        st = _store()
        st.record('snmp', 'host.h1/eth0', status=True, data=dict(self._MUESTRA))
        medidas = st._db.fetchall(
            'SELECT f.name, h.num FROM history_fact h JOIN history_field f ON f.id = h.field_id')
        assert [(r[0], r[1]) for r in medidas] == [('if_in', 5.0)], medidas

    def test_y_la_identidad_vive_en_la_serie(self):
        st = _store()
        st.record('snmp', 'host.h1/eth0', status=True, data=dict(self._MUESTRA))
        attrs = st._db.fetchone('SELECT attrs FROM history_series')[0]
        assert '"mac": "aa:bb"' in attrs and '"_row": "eth0"' in attrs

    def test_pero_quien_lee_sigue_viendo_lo_de_siempre(self):
        """Que es lo que permite hacer esto sin tocar ninguna pantalla. Y no es cosmética: la
        ficha de identidad de un dispositivo se dibuja de `_attrs`, y para una máquina en
        mantenimiento —a la que le podaron el estado vivo— **sale del historial**."""
        st = _store()
        st.record('snmp', 'host.h1/eth0', status=True, data=dict(self._MUESTRA))
        for datos in (st.latest_by_series()[0]['last_data'],
                      st.get_index()[0]['last_data'],
                      st.query('snmp', 'host.h1/eth0', 0, 9e12)[0]['data']):
            assert datos['if_in'] == 5
            assert datos['_attrs'] == {'p1': {'mac': 'aa:bb'}}
            assert datos['_row'] == 'eth0' and datos['_watched'] is True

    def test_la_identidad_se_reescribe_solo_cuando_cambia(self):
        """Es lo mismo en muestra tras muestra —ese es el motivo de sacarla de la muestra— y
        volver a escribirla cada vez cambiaría un derroche de bytes por uno de escrituras."""
        st = _store()
        st.record('snmp', 'host.h1/eth0', status=True, data=dict(self._MUESTRA))
        escrituras = []
        original = st._db.execute

        def _contando(sql, params=()):
            if 'UPDATE history_series' in sql and 'attrs' in sql:
                escrituras.append(sql)
            return original(sql, params)

        st._db.execute = _contando
        st.record('snmp', 'host.h1/eth0', status=True, data=dict(self._MUESTRA))
        assert not escrituras, escrituras
        st.record('snmp', 'host.h1/eth0', status=True,
                  data={'if_in': 6, '_attrs': {'p1': {'mac': 'cc:dd'}}})
        assert escrituras, 'una MAC nueva no llegó a la serie'
        st._db.execute = original
        assert '"mac": "cc:dd"' in st._db.fetchone('SELECT attrs FROM history_series')[0]

    def test_y_la_serie_sabe_cuando_informo_por_ultima_vez(self):
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'v': 1})
        primero, ultimo = st._db.fetchone('SELECT first_ts, last_ts FROM history_series')
        assert primero and ultimo and primero == ultimo
        st.record('cpu', 'srv1', status=True, data={'v': 2})
        segundo, ultimo2 = st._db.fetchone('SELECT first_ts, last_ts FROM history_series')
        assert segundo == primero, 'la primera vez no se mueve'
        assert ultimo2 > ultimo

    def test_una_muestra_sin_identidad_no_escribe_nada_en_la_serie(self):
        """La inmensa mayoría de los módulos no llevan ninguna: no hay que hacerles pagar una
        actualización de más."""
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'v': 1})
        assert st._db.fetchone('SELECT attrs FROM history_series')[0] is None

class TestSeLeePorSerie:
    """Paso 6. Cuatro lecturas que acotaban con `module = ? AND key = ?` —dos cadenas repetidas
    en cada una de las cien mil filas— pasan a acotar con un entero.

    Y `get_index` deja de agrupar por `COALESCE(item_uid, module||':'||key)`, una expresión que
    ningún índice puede servir y que obligaba a sus dos pasadas a ordenar la tabla entera en un
    árbol temporal. Medido sobre la instalación real: **1.783 ms → 976 ms**."""

    def test_una_grafica_sigue_saliendo_igual(self):
        st = _store()
        for i in range(3):
            st.record('cpu', 'srv1', status=True, data={'v': i})
        st.record('cpu', 'otra', status=True, data={'v': 99})
        puntos = st.query('cpu', 'srv1', 0, 9e12)
        assert [p['data']['v'] for p in puntos] == [0, 1, 2], puntos

    def test_y_las_estadisticas_tambien(self):
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'v': 1})
        st.record('cpu', 'srv1', status=False, data={'v': 3})
        st.record('cpu', 'otra', status=False, data={'v': 0})
        stats = st.get_stats('cpu', 'srv1', 0, 9e12, field='v')
        assert stats['count'] == 2 and stats['uptime'] == 50.0

    def test_leer_una_serie_que_no_existe_no_la_crea(self):
        """Una gráfica de algo que nunca se midió sale vacía; lo que no puede es dejar una
        serie fantasma en el catálogo, que luego sale en la lista de lo que hay medido."""
        st = _store()
        # Cada una por separado: al final valdría igual con una que crea la serie y otra que
        # la borra, y las dos estarían mal.
        assert st.query('cpu', 'jamas', 0, 9e12) == []
        assert _series(st) == {}, 'leer una gráfica creó la serie'
        assert st.get_stats('cpu', 'jamas', 0, 9e12) == {}
        assert _series(st) == {}, 'pedir estadísticas creó la serie'
        assert st.delete_series('cpu', 'jamas') == 0
        assert _series(st) == {}

    def test_el_filtro_por_modulo_pasa_por_la_serie(self):
        """Funcionaría hoy leyendo la columna de la muestra y dejaría de funcionar en el paso
        que la quita — devolviendo menos, que es la forma silenciosa de romperse."""
        st = _store()
        st.record('cpu', 'srv1', status=True)
        st.record('web', 'portal', status=True)
        assert {r['module'] for r in st.latest_by_series(['cpu'])} == {'cpu'}
        assert len(st.latest_by_series()) == 2
        # Y por el fuente, porque ejecutar no distingue: `history.module` sigue ahí, y leerlo
        # daría hoy la misma respuesta. Desde que el resumen vive en la serie, esta función no
        # tiene ningún motivo para nombrar la tabla de muestras — ni para el filtro ni para
        # nada. Que no la nombre es más fuerte que comprobar la forma de una subconsulta.
        sql = _fuente('latest_by_series')
        assert '{_TS}' in sql, 'no lee de la tabla de series'
        assert '{_T}' not in sql, (
            'latest_by_series vuelve a tocar la tabla de muestras: era el recorrido que '
            'costaba 69 s sobre cinco millones de filas')


class TestBorrarUnaSerieSeLaLlevaEntera:

    def test_se_van_las_muestras_y_tambien_la_serie(self):
        """Dejarla sería guardar la identidad de algo de lo que no queda ni una muestra — y
        devolvérsela a la primera medida nueva que coincidiera de nombre."""
        st = _store()
        st.record('snmp', 'host.h1/eth0', status=True,
                  data={'if_in': 1, '_attrs': {'p': {'mac': 'aa:bb'}}})
        st.record('cpu', 'srv1', status=True)
        assert st.delete_series('snmp', 'host.h1/eth0') == 1
        assert set(_series(st)) == {('cpu', 'srv1')}

    def test_y_lo_que_este_proceso_creia_saber_se_olvida(self):
        """La caché de ids vive en memoria. Sin limpiarla, la siguiente muestra apuntaría con
        un id a una fila que ya no está: una medida archivada en ninguna parte."""
        st = _store()
        viejo = st.series_id('cpu', 'srv1')
        st.record('cpu', 'srv1', status=True)
        st.delete_series('cpu', 'srv1')
        st.record('cpu', 'srv1', status=True)
        nuevo = st._db.fetchone('SELECT series_id FROM history')[0]
        assert nuevo != viejo
        assert nuevo == st.series_id('cpu', 'srv1')

    def test_y_vaciarlo_todo_vacia_las_dos_tablas(self, tmp_path):
        # En fichero y no en memoria: `delete_all` termina con un VACUUM, y el conector suelta
        # la conexión después —el fichero se reconstruye en su sitio y algunos sqlite3 se
        # quedan con una caché vieja—. Contra `:memory:` soltar la conexión es tirar la base
        # entera, así que la prueba no llegaría a mirar nada.
        st = HistoryStore(get_connector(None, default_sqlite_path=str(tmp_path / 'h.db')))
        st.record('cpu', 'srv1', status=True)
        st.record('web', 'portal', status=True)
        st.delete_all()
        assert _series(st) == {}
        assert st._db.fetchone('SELECT COUNT(*) FROM history')[0] == 0
        st.record('cpu', 'srv1', status=True)
        assert st._db.fetchone('SELECT series_id FROM history')[0] == st.series_id('cpu', 'srv1')


class TestLosIndicesDicenComoSeLee:
    """Paso 7."""

    def _indices(self, st):
        return {getattr(i, 'name', '') for i in st._db.list_indexes('history')}

    def test_esta_el_de_la_serie(self):
        assert 'idx_history_series_ts' in self._indices(_store())

    def test_y_no_esta_el_que_indexaba_una_columna_vacia(self):
        """`idx_history_uid_ts(item_uid, ts)` indexaba una columna que es NULL en todas las
        filas de todas las instalaciones: ningún registrador ha escrito nunca una. Era espacio
        y una escritura por muestra a cambio de nada.

        Lo retiró la migración de su día, que ya no está en el código; lo que se comprueba
        ahora es que no vuelva — declararlo otra vez sería recuperar el coste sin recuperar
        ninguna razón."""
        assert 'idx_history_uid_ts' not in self._indices(_store())

    def test_podar_deja_la_serie_diciendo_la_verdad(self):
        """`first_ts` decía cuándo empezó una serie. Después de podar es la fecha de una muestra
        que ya no existe — y una fecha inventada en una tabla que existe para no tener que mirar
        el histórico es peor que no tenerla."""
        import time                                                  # noqa: PLC0415
        st = _store()
        st.record('cpu', 'srv1', status=True)
        st._db.execute('UPDATE history SET ts = ?', (time.time() - 40 * 86400,))
        st._db.execute('UPDATE history_series SET first_ts = ?', (time.time() - 40 * 86400,))
        st._db.commit()
        st.record('cpu', 'srv1', status=True)
        assert st.prune(30) == 1
        primero = st._db.fetchone('SELECT first_ts FROM history_series')[0]
        quedan = st._db.fetchone('SELECT MIN(ts) FROM history')[0]
        assert primero == quedan


class TestElResumenViveEnLaSerie:
    """Cuántas muestras, cuántas buenas y qué dijo la última: contestado por la fila que
    representa a la serie, no recorriendo sus muestras.

    Medido sobre una copia de 30 días de una instalación real (5.266.008 muestras, 1.465
    series): `get_index` pasó de **235.674 ms** a **6,6 ms**. Lo que estas pruebas sujetan no
    es la velocidad, es que el resumen diga la verdad — porque un número que se mantiene aparte
    se equivoca en silencio, y la página lo enseña igual de convencida.
    """

    def test_cada_muestra_suma_una(self):
        st = _store()
        for _ in range(3):
            st.record('cpu', 'srv1', status=True, data={'used': 10})
        st.record('cpu', 'srv1', status=False, data={'used': 99})
        assert _resumen(st)[('cpu', 'srv1')][:3] == (4, 3, 0)

    def test_y_el_catalogo_cuenta_lo_mismo_que_hay(self):
        """Lo que enseña la página contra lo que hay en la tabla: si el resumen se desviara,
        aquí es donde se ve."""
        st = _store()
        for i in range(5):
            st.record('cpu', 'srv1', status=(i != 2), data={'used': i})
        st.record('web', 'portal', status=True)
        fila = [r for r in st.get_index() if r['key'] == 'srv1'][0]
        real = st._db.fetchone(
            'SELECT COUNT(*), SUM(status) FROM history h JOIN history_series s '
            'ON s.id = h.series_id WHERE s.%s = ?' % st._qk, ('srv1',))
        assert fila['count'] == real[0] == 5
        assert fila['uptime'] == round(real[1] * 100.0 / real[0], 1) == 80.0

    def test_la_ultima_muestra_es_la_ultima(self):
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'used': 1})
        st.record('cpu', 'srv1', status=False, data={'used': 2})
        fila = st.get_index()[0]
        assert fila['last_status'] is False
        assert fila['last_data'] == {'used': 2}
        assert st.latest_by_series()[0]['last_data'] == {'used': 2}

    def test_la_identidad_de_la_serie_sigue_volviendo_con_la_ultima(self):
        """El resumen guarda la MEDIDA, como la muestra. Lo que la serie ES se le pone encima
        al leer, igual que en `query` — si no, la ficha perdería el modelo y el número de serie
        justo en la vista que los enseña."""
        st = _store()
        st.record('snmp', 'host.h1/eth0', status=True,
                  data={'if_in': 7, '_attrs': {'p': {'mac': 'aa:bb'}}})
        assert _resumen(st)[('snmp', 'host.h1/eth0')][3] == '{"if_in": 7}'
        for fila in (st.get_index()[0], st.latest_by_series()[0]):
            assert fila['last_data'] == {'if_in': 7, '_attrs': {'p': {'mac': 'aa:bb'}}}

    def test_una_serie_sin_muestras_no_sale_en_el_catalogo(self):
        """`series_id` crea la serie antes de que exista ninguna medida suya. Enseñarla sería
        una fila en la página de histórico que no tiene nada que dibujar."""
        st = _store()
        st.series_id('cpu', 'jamas')
        assert _series(st)
        assert st.get_index() == []
        assert st.latest_by_series() == []

    def test_el_catalogo_no_recorre_las_muestras(self):
        """El motivo entero del cambio. Ejecutar no lo distingue —con diez filas las dos
        formas contestan igual—; lo distingue el fuente."""
        sql = _fuente('get_index')
        assert '{_TS}' in sql, 'no lee de la tabla de series'
        assert '{_T}' not in sql, (
            'get_index vuelve a recorrer el histórico: eran 235.674 ms sobre 30 días '
            'de una instalación real')


class TestPodarRepara:
    """Podar quita muestras por detrás, y el resumen las sigue contando. Es el único camino
    que puede dejarlo mintiendo."""

    def _viejas(self, st, sid, cuantas, desde):
        """Muestras antiguas metidas a mano: `record` siempre escribe con la hora de ahora."""
        for i in range(cuantas):
            st._db.execute(
                'INSERT INTO history(ts, item_uid, status, series_id) '
                'VALUES(?, ?, ?, ?)', (desde + i, None, 1, sid))
            st.facts.write(sid, desde + i, {'used': 1})
        st._db.commit()

    def test_despues_de_podar_el_resumen_cuenta_lo_que_queda(self):
        import time                                                   # noqa: PLC0415
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'used': 5})
        sid = st.series_id('cpu', 'srv1')
        self._viejas(st, sid, 4, time.time() - 40 * 86400)
        st._resummarise(con_ultima=True)
        st._db.commit()
        assert _resumen(st)[('cpu', 'srv1')][0] == 5
        assert st.prune(30) == 4
        assert _resumen(st)[('cpu', 'srv1')][0] == 1, 'el resumen sigue contando lo que borró'
        assert st.get_index()[0]['count'] == 1

    def test_la_serie_que_se_queda_sin_nada_deja_de_decir_lo_que_dijo(self):
        """Servir su última medida sería dar por presente algo que se borró — que es
        exactamente el fallo del respaldo que servía una serie muerta como estado de ahora."""
        import time                                                   # noqa: PLC0415
        st = _store()
        sid = st.series_id('cpu', 'srv1')
        self._viejas(st, sid, 3, time.time() - 40 * 86400)
        st._resummarise(con_ultima=True)
        st._db.commit()
        assert st.get_index()[0]['count'] == 3
        assert st.prune(30) == 3
        assert _resumen(st)[('cpu', 'srv1')] == (0, 0, None, None)
        assert st.get_index() == [], 'una serie sin muestras sigue en el catálogo'
        assert _series(st), 'la serie se borró: su identidad era lo único que quedaba de ella'


class TestRellenarLoQueSeGraboAntes:
    """Una instalación con histórico anterior a estas columnas. No es una migración con fecha:
    es la respuesta a «esta serie no sabe cuántas muestras tiene»."""

    def test_el_arranque_rellena_lo_que_estaba_vacio(self, tmp_path):
        base = str(tmp_path / 'h.db')
        st = HistoryStore(get_connector(None, default_sqlite_path=base))
        st.record('cpu', 'srv1', status=True, data={'used': 1})
        st.record('cpu', 'srv1', status=False, data={'used': 2})
        st.record('web', 'portal', status=True)
        # Lo que había antes de que existiera el resumen.
        st._db.execute('UPDATE history_series SET samples = NULL, up_samples = NULL, '
                       'last_status = NULL, last_data = NULL')
        st._db.commit()
        otro = HistoryStore(get_connector(None, default_sqlite_path=base))
        assert _resumen(otro)[('cpu', 'srv1')] == (2, 1, 0, '{"used": 2}')
        assert _resumen(otro)[('web', 'portal')][:2] == (1, 1)
        assert [r['count'] for r in otro.get_index() if r['key'] == 'srv1'] == [2]

    def test_una_serie_recien_creada_no_dispara_el_relleno(self):
        """Nace a cero, no a NULL. Si naciera a NULL, una serie creada cuya muestra no llegue
        a escribirse dejaría esa marca puesta para siempre — y cada arranque del panel
        recalcularía el histórico entero por ella."""
        st = _store()
        st.series_id('cpu', 'sin_muestras')
        assert _resumen(st)[('cpu', 'sin_muestras')][:2] == (0, 0)
        llamadas = []
        original = st._resummarise
        st._resummarise = lambda **kw: llamadas.append(kw)             # noqa: ARG005
        st._fill_summary()
        st._resummarise = original
        assert llamadas == [], 'una serie sin muestras dispara el recuento entero'

    def test_y_despues_no_vuelve_a_recorrer_nada(self):
        """El sondeo es una pregunta que no devuelve nada. Si se rellenara en cada arranque,
        cada proceso del panel pagaría el recuento entero al abrir."""
        st = _store()
        st.record('cpu', 'srv1', status=True)
        llamadas = []
        original = st._resummarise
        st._resummarise = lambda **kw: llamadas.append(kw)             # noqa: ARG005
        st._fill_summary()
        st._resummarise = original
        assert llamadas == [], 'volvió a recalcular con el resumen ya puesto'
