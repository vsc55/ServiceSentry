#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — una fila por valor medido, no un documento por muestra.
#
"""Las medidas dejan de ser un JSON por muestra y pasan a ser filas.

El motivo no es velocidad: leer **una** serie cuesta 8 ms de las dos formas, y eso es todo lo
que el panel hace hoy. El motivo es lo que no se puede escribir con un documento —«qué
interfaces se están degradando», «los diez discos más calientes», una alerta sobre una media
móvil— porque cada una de esas preguntas es hoy un recorrido de un segundo. Medido sobre 30 días
de una instalación real: 1.264 ms → 25 ms, y 915 ms → 1 ms.

Lo que estas pruebas sujetan no es eso, que es fácil de medir y difícil de romper. Es que **la
medida que sale sea la que entró**, porque ahí el fallo no se ve: una gráfica creíble y
equivocada.

Sin Flask: un conector SQLite en memoria, un almacén y filas.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.history.facts import FACT_SCHEMA, FIELD_SCHEMA      # noqa: E402
from lib.core.history.store import HistoryStore                   # noqa: E402
from lib.db import get_connector                                  # noqa: E402


def _store():
    return HistoryStore(get_connector(None, default_sqlite_path=':memory:'))


def _hechos(st, series_id=None):
    """``[(serie, ts, nombre, kind, num, txt)]`` — lo que hay escrito de verdad."""
    donde = '' if series_id is None else ' WHERE h.series_id = %d' % series_id
    return st._db.fetchall(
        'SELECT h.series_id, h.ts, f.name, h.kind, h.num, h.txt '
        'FROM history_fact h JOIN history_field f ON f.id = h.field_id' + donde
        + ' ORDER BY h.ts, f.name')


def _medidas(st, sid, ts):
    """Las medidas de una muestra, recompuestas desde los hechos."""
    return st.facts.by_sample(sid, ts - 0.001, ts + 0.001).get(ts, {})


class TestLoQueEntraEsLoQueSale:

    def test_una_muestra_se_recompone_entera(self):
        st = _store()
        medidas = {'used': 42, 'temp': 36.5, 'name': 'sda', 'ok': True,
                   'falta': None, 'ips': ['10.0.0.1']}
        st.record('snmp', 'host.h1/sda', status=True, data=dict(medidas))
        sid = st.series_id('snmp', 'host.h1/sda')
        ts = st._db.fetchone('SELECT ts FROM history')[0]
        assert _medidas(st, sid, ts) == medidas

    def test_los_tipos_sobreviven_al_viaje(self):
        """Un booleano que vuelve como 1 y un entero que vuelve con coma no dan ningún error:
        dan una ficha que enseña algo distinto de lo que se midió."""
        st = _store()
        st.record('proxmox', 'cl1', status=True,
                  data={'quorate': True, 'nodes_online': 3, 'load': 0.5, 'note': None})
        sid = st.series_id('proxmox', 'cl1')
        ts = st._db.fetchone('SELECT ts FROM history')[0]
        salida = _medidas(st, sid, ts)
        assert salida['quorate'] is True
        assert isinstance(salida['nodes_online'], int)
        assert isinstance(salida['load'], float)
        assert salida['note'] is None

    def test_lo_que_devuelve_query_es_lo_que_se_grabo(self):
        """La invariante del cambio entero, por el camino que usa el panel: lo que sale de
        `query` tiene que ser lo que entró en `record`, campo a campo y tipo a tipo."""
        st = _store()
        casos = [
            ('cpu', 'srv1', {'used': 12, 'alert': False}),
            ('snmp', 'host.h1/eth0', {'if_in': 10, 'if_oper': 1, 'if_name': 'eth0'}),
            ('ping', 'gw', {'latency_ms': 1.25}),
            ('web', 'portal', {'code': 200, 'detail': ''}),
            ('ups', 'u1', {'on_battery': False, 'runtime': None}),
        ]
        for mod, key, medidas in casos:
            st.record(mod, key, status=True, data=dict(medidas))
        for mod, key, medidas in casos:
            puntos = st.query(mod, key, 0, 9e12)
            assert len(puntos) == 1, f'{mod}/{key}: {puntos}'
            assert puntos[0]['data'] == medidas, f'{mod}/{key} no cuadra'
            for campo, valor in medidas.items():
                assert type(puntos[0]['data'][campo]) is type(valor), campo


class TestElDiccionarioDeCampos:
    """211 nombres en una instalación real, escritos una vez en vez de veintisiete millones."""

    def test_un_nombre_se_escribe_una_sola_vez(self):
        st = _store()
        for _ in range(5):
            st.record('cpu', 'srv1', status=True, data={'used': 1, 'alert': False})
        nombres = st._db.fetchall('SELECT name FROM history_field ORDER BY name')
        assert [n[0] for n in nombres] == ['alert', 'used']
        assert st._db.fetchone('SELECT COUNT(*) FROM history_fact')[0] == 10

    def test_dos_series_comparten_el_nombre_del_campo(self):
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'used': 1})
        st.record('cpu', 'srv2', status=True, data={'used': 2})
        assert st._db.fetchone('SELECT COUNT(*) FROM history_field')[0] == 1

    def test_el_id_sobrevive_a_otro_proceso_sobre_la_misma_base(self, tmp_path):
        """Dos procesos pueden ver un campo nuevo por primera vez a la vez. Quien pierde la
        carrera tiene que encontrarse la fila del otro, no crear una segunda."""
        base = str(tmp_path / 'h.db')
        uno = HistoryStore(get_connector(None, default_sqlite_path=base))
        uno.record('cpu', 'srv1', status=True, data={'used': 1})
        otro = HistoryStore(get_connector(None, default_sqlite_path=base))
        otro.record('cpu', 'srv2', status=True, data={'used': 2})
        filas = otro._db.fetchall('SELECT id, name FROM history_field')
        assert len(filas) == 1, 'se creó un segundo campo con el mismo nombre'
        assert {int(r[1]) for r in otro._db.fetchall(
            'SELECT ts, field_id FROM history_fact')} == {int(filas[0][0])}

    def test_pedir_muchos_nombres_cuesta_un_viaje(self):
        """Una muestra SNMP trae catorce campos. Resolverlos de uno en uno son catorce viajes a
        la base por muestra, que es lo que convierte escribir en un problema."""
        st = _store()
        st.facts.forget()
        viajes = []
        original = st._db.fetchall
        st._db.fetchall = lambda sql, args=(): (viajes.append(sql), original(sql, args))[1]
        st.facts.field_ids([f'c{i}' for i in range(14)])
        st._db.fetchall = original
        assert len(viajes) <= 2, f'{len(viajes)} viajes para catorce nombres: {viajes}'


class TestUnaMuestraPuedeNoMedirNada:

    def test_no_deja_ningun_hecho_y_eso_esta_bien(self):
        """325 de las 4.026 muestras reales no miden nada: sólo dicen si la cosa respondió."""
        st = _store()
        st.record('ping', 'gw', status=False)
        assert st._db.fetchone('SELECT COUNT(*) FROM history')[0] == 1
        assert st._db.fetchone('SELECT COUNT(*) FROM history_fact')[0] == 0

    def test_y_la_muestra_se_sigue_pudiendo_leer(self):
        st = _store()
        st.record('ping', 'gw', status=False)
        assert st.get_index()[0]['count'] == 1
        assert st.get_index()[0]['last_status'] is False


class TestLaIdentidadNoEsUnaMedida:

    def test_lo_que_empieza_por_guion_bajo_no_llega_a_los_hechos(self):
        """`_attrs`, `_row`, `_watched`, `_role` hablan *del* resultado, no lo miden. Van a la
        serie, que es donde no se repiten — ese es el motivo entero del paso anterior."""
        st = _store()
        st.record('snmp', 'host.h1/eth0', status=True,
                  data={'if_in': 7, '_attrs': {'p': {'mac': 'aa:bb'}}, '_row': 'eth0'})
        nombres = {r[0] for r in st._db.fetchall('SELECT name FROM history_field')}
        assert nombres == {'if_in'}, f'la identidad se coló en los hechos: {nombres}'


class TestOlvidar:

    def test_borrar_una_serie_se_lleva_sus_medidas(self):
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'used': 1})
        st.record('cpu', 'srv2', status=True, data={'used': 2})
        sid = st.series_id('cpu', 'srv1')
        assert st.delete_series('cpu', 'srv1') == 1
        assert _hechos(st, sid) == []
        assert len(_hechos(st)) == 1, 'se llevó por delante las medidas de la otra serie'

    def test_vaciarlo_entero_se_lleva_tambien_el_diccionario(self, tmp_path):
        """Si los nombres se quedaran, la primera muestra nueva apuntaría con un id a una fila
        que sí está — pero la caché del proceso apuntaría a una que no."""
        base = str(tmp_path / 'h.db')
        st = HistoryStore(get_connector(None, default_sqlite_path=base))
        st.record('cpu', 'srv1', status=True, data={'used': 1})
        st.delete_all()
        assert st._db.fetchone('SELECT COUNT(*) FROM history_fact')[0] == 0
        assert st._db.fetchone('SELECT COUNT(*) FROM history_field')[0] == 0
        st.record('cpu', 'srv1', status=True, data={'used': 9})
        sid = st.series_id('cpu', 'srv1')
        ts = st._db.fetchone('SELECT ts FROM history')[0]
        assert _medidas(st, sid, ts) == {'used': 9}


class TestLaForma:

    def test_la_tabla_de_hechos_no_tiene_clave_primaria(self):
        """A propósito, y medido: la clave natural `(serie, ts, campo)` no cuesta nada de más
        —el índice ya hace falta— hasta que dos muestras de la misma serie caen en el mismo `ts`
        exacto. Entonces el INSERT falla y `record` pierde la medida entera.

        Cero choques en 4.026 muestras reales, con las 4.026 marcas de tiempo distintas incluso
        entre series. Pero `time.time()` sí se repite en bucle apretado (1.142 valores distintos
        de 2.000 seguidos), así que es posible. Una restricción cuya violación cuesta una medida
        es mal negocio cuando la alternativa cuesta dos puntos dibujados como uno.
        """
        assert FACT_SCHEMA.pk_columns == (), (
            'la tabla de hechos tiene clave primaria: un choque de `ts` dejaría de juntar dos '
            'puntos y pasaría a perder una muestra')

    def test_el_nombre_del_campo_es_unico(self):
        """Aquí sí: dos filas con el mismo nombre son dos ids para el mismo campo, y entonces
        «los diez que más» se contesta con la mitad de las series."""
        unicos = [i for i in FIELD_SCHEMA.indexes if i.unique]
        assert [i.columns for i in unicos] == [('name',)]

    def test_los_dos_indices_estan_y_sirven_a_las_dos_preguntas(self):
        porcol = {i.columns: i for i in FACT_SCHEMA.indexes}
        assert ('series_id', 'ts', 'field_id') in porcol, 'falta cómo se lee una serie'
        assert ('field_id', 'ts', 'series_id', 'num') in porcol, (
            'falta el índice que contesta a la flota — y `num` va dentro para que el promedio '
            'no tenga que visitar la fila')


def _vieja(base, filas):
    """Una base con la forma ANTERIOR: `history.data` con su documento y ningún hecho.

    Es la única forma honrada de probar el paso — fabricar lo que escribía la versión de antes
    y abrir un almacén encima, que es exactamente lo que le pasa a una instalación al
    actualizarse.
    """
    import json                                                       # noqa: PLC0415
    db = get_connector(None, default_sqlite_path=base)
    db.execute_ddl('CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,'
                   ' item_uid TEXT, status INTEGER NOT NULL, data TEXT, series_id INTEGER)')
    db.execute_ddl('CREATE TABLE history_series (id INTEGER PRIMARY KEY AUTOINCREMENT,'
                   ' module TEXT NOT NULL, key TEXT NOT NULL, item_uid TEXT, attrs TEXT,'
                   ' first_ts REAL, last_ts REAL)')
    db.execute_ddl('CREATE UNIQUE INDEX idx_hseries_mk ON history_series (module, key)')
    series, ts = {}, 1000.0
    for module, key, status, medidas in filas:
        if (module, key) not in series:
            db.execute('INSERT INTO history_series(module, key) VALUES(?, ?)', (module, key))
            db.commit()
            series[(module, key)] = db.last_insert_id()
        db.execute('INSERT INTO history(ts, item_uid, status, data, series_id) '
                   'VALUES(?, ?, ?, ?, ?)',
                   (ts, None, 1 if status else 0, json.dumps(medidas),
                    series[(module, key)]))
        ts += 1.0
    db.commit()
    db.close()
    return series


class TestPodarSeLlevaLasMedidas:

    def test_la_poda_no_deja_medidas_huerfanas(self):
        """Borrar la muestra y dejar sus medidas es peor que no borrar nada: la tabla que más
        crece deja de podarse, y nadie lo ve hasta que el disco se llena."""
        import time                                                   # noqa: PLC0415
        st = _store()
        sid = st.series_id('cpu', 'srv1')
        viejo = time.time() - 40 * 86400
        st._db.execute('INSERT INTO history(ts, item_uid, status, series_id) VALUES(?, ?, ?, ?)',
                       (viejo, None, 1, sid))
        st.facts.write(sid, viejo, {'used': 1})
        st._db.commit()
        st.record('cpu', 'srv1', status=True, data={'used': 2})
        assert st._db.fetchone('SELECT COUNT(*) FROM history_fact')[0] == 2
        assert st.prune(30) == 1
        assert st._db.fetchone('SELECT COUNT(*) FROM history_fact')[0] == 1, (
            'se fue la muestra y se quedaron sus medidas')
        assert st._db.fetchone('SELECT num FROM history_fact')[0] == 2.0, 'borró la que no era'

    def test_y_el_diccionario_de_campos_no_se_poda(self):
        """Un nombre no es una medida: cuesta una fila, lo comparten todas las series y
        borrarlo obligaría a volver a crearlo con otro id en la siguiente muestra."""
        import time                                                   # noqa: PLC0415
        st = _store()
        sid = st.series_id('cpu', 'srv1')
        st.facts.write(sid, time.time() - 40 * 86400, {'used': 1})
        st._db.execute('INSERT INTO history(ts, item_uid, status, series_id) VALUES(?, ?, ?, ?)',
                       (time.time() - 40 * 86400, None, 1, sid))
        st._db.commit()
        st.prune(30)
        assert st._db.fetchone('SELECT COUNT(*) FROM history_field')[0] == 1


class TestLeerNoCrea:
    """La misma regla que ya cumplen las series: preguntar por algo que nunca se midió sale
    vacío, no deja un nombre fantasma en el catálogo de lo que se puede preguntar."""

    def test_preguntar_por_un_campo_que_no_existe_no_lo_inventa(self):
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'used': 1})
        antes = st._db.fetchone('SELECT COUNT(*) FROM history_field')[0]
        assert st.facts.top('jamas_medido', 0, 9e12) == []
        assert st.facts.series_where('jamas_medido', 0, 9e12) == []
        assert st.facts.over_time('jamas_medido', 0, 9e12) == []
        assert st.facts.stats(1, 'jamas_medido', 0, 9e12) == {}
        assert st.get_stats('cpu', 'srv1', 0, 9e12, field='jamas_medido').get('avg') is None
        assert st._db.fetchone('SELECT COUNT(*) FROM history_field')[0] == antes, (
            'leer creó un campo')
        assert st.facts.field_id_of('jamas_medido') is None

    def test_pero_escribirlo_si_lo_crea(self):
        st = _store()
        st.record('cpu', 'srv1', status=True, data={'recien_medido': 1})
        assert st.facts.field_id_of('recien_medido')


class TestPreguntarleALaFlota:
    """Para esto existe la tabla. No acelera nada de lo que el panel ya hacía: hace posible lo
    que no hacía."""

    def _flota(self):
        st = _store()
        for serie, temp, err in (('d1', 60, 0), ('d2', 75, 3), ('d3', 41, 0)):
            for i in range(3):
                st.record('snmp', f'host.{serie}', status=True,
                          data={'temp': temp + i, 'errors': err})
        return st

    def test_los_que_mas(self):
        st = self._flota()
        top = st.facts.top('temp', 0, 9e12, limit=2)
        assert len(top) == 2
        assert top[0]['value'] > top[1]['value']
        assert top[0]['samples'] == 3

    def test_y_los_que_menos(self):
        st = self._flota()
        assert st.facts.top('temp', 0, 9e12, limit=1, desc=False)[0]['value'] == 42.0

    def test_cuales_cumplen_una_condicion(self):
        st = self._flota()
        sids = st.facts.series_where('errors', 0, 9e12, op='>', value=0)
        assert len(sids) == 1
        assert st._db.fetchone(
            'SELECT %s FROM history_series WHERE id = ?' % st._qk, (sids[0],))[0] == 'host.d2'

    def test_agregada_por_tramos(self):
        st = self._flota()
        tramos = st.facts.over_time('temp', 0, 9e12, bucket=9e12)
        assert len(tramos) == 1
        assert tramos[0]['samples'] == 9
        assert tramos[0]['min'] == 41.0 and tramos[0]['max'] == 77.0

    def test_un_operador_inventado_no_llega_al_sql(self):
        """El operador entra en el SQL como texto, así que es lo único de estas consultas que
        no puede ser un parámetro — y por eso es lista blanca y no escapado."""
        st = self._flota()
        assert st.facts.series_where('temp', 0, 9e12, op='> 0 OR 1=1 --') == []
        assert st.facts.top('temp', 0, 9e12, agg='avg); DROP TABLE history_fact; --') == []
        assert st._db.fetchone('SELECT COUNT(*) FROM history_fact')[0] == 18


class TestLoQueSaleSePuedeSerializar:
    """PostgreSQL devuelve `Decimal` donde SQLite y MySQL devuelven `float`. `Decimal` no es
    serializable a JSON, así que una respuesta que funciona en dos motores es un 500 en el
    tercero — y nada en el camino parece específico de ningún motor."""

    def test_todo_numero_que_sale_es_un_float(self):
        import json                                                   # noqa: PLC0415
        st = _store()
        for i in range(4):
            st.record('snmp', f'host.d{i}', status=True, data={'temp': 40 + i})
        salidas = [st.facts.top('temp', 0, 9e12),
                   st.facts.over_time('temp', 0, 9e12, bucket=9e12),
                   [st.facts.stats(st.series_id('snmp', 'host.d0'), 'temp', 0, 9e12)],
                   [st.get_stats('snmp', 'host.d0', 0, 9e12, field='temp')]]
        for filas in salidas:
            json.dumps(filas)          # lo que haría una ruta: si no serializa, revienta aquí
            for fila in filas:
                for clave, valor in fila.items():
                    if valor is None:
                        continue
                    # Un entero puede salir entero —`count`, `samples`— y está bien. Lo que no
                    # puede salir es un `Decimal`, ni nada que no sea un número de Python.
                    assert isinstance(valor, (int, float)) and not isinstance(valor, bool), (
                        f'{clave} sale como {type(valor).__name__}')
                    assert type(valor).__module__ == 'builtins', (
                        f'{clave} sale como {type(valor).__module__}.{type(valor).__name__}, '
                        'que es del motor y no de Python')
