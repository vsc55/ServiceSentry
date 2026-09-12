#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The measurements, one row per measured value instead of one JSON per sample.

Why
---
A sample's measurements used to be a JSON document in ``history.data``. That is the right shape
for *reading one series* — which is all this panel does today, and it does it in 8 ms — and the
wrong shape for asking anything **across** series. «Which interfaces are degrading», «the ten
hottest disks», an alert on a moving average: none of those can be written today without a
full scan, which is why none of them exists.

Measured by scaling a real installation's history to the 30 days of retention configured
(5,266,008 samples, 1,465 series, 211 distinct field names, 5.24 measurements per sample):

    the ten busiest series by a field, 24 h ....  1,264 ms → 25 ms
    which interfaces reported errors, last hour .. 915 ms →  1 ms
    the fleet's hourly average, 24 h ............. (nobody writes it) → 24 ms

The price is disk: **2,474 MB against 877**. That is the honest trade, and it buys capability
rather than speed — reading one series is 8 ms either way.

Shape
-----
``history_field`` is the dictionary: 211 names written once instead of 27 million times.

``history_fact`` is ``(series_id, ts, field_id, kind, num, txt)``. It carries ``series_id`` and
``ts`` — rather than pointing at ``history.id`` — because that is what the fleet questions filter
on, and a join back to the sample to find its time would undo the whole point.

**And it has no primary key, deliberately.** The natural one would be ``(series_id, ts,
field_id)``, which costs nothing extra… until two samples of the same series land on the same
float timestamp: then the INSERT fails and ``record`` loses the whole measurement. Measured on
the real installation: **zero collisions in 4,026 samples**, every timestamp distinct even across
series — but ``time.time()`` does repeat when called in a tight loop (1,142 distinct values out of
2,000 consecutive calls), so it is possible, just not frequent. A constraint whose violation
costs a measurement is a bad trade when the alternative costs two points drawn as one.

What a value IS — number, integer, boolean, absent, nested — is in :mod:`lib.core.history.values`.
"""

from __future__ import annotations

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

from . import values as V

#: El diccionario de nombres. 211 en una instalación real, escritos una vez.
#:
#: Los nombres los inventan los perfiles SNMP y los módulos, así que la tabla crece sola y no
#: hay ninguna lista fija que mantener — que es justo lo que hacía imposible «una columna por
#: dato»: 211 columnas casi todas nulas, y una más cada vez que alguien carga una MIB.
FIELD_SCHEMA = TableSpec(
    name='history_field',
    columns=(
        Column('id',   'AUTOINCREMENT', primary_key=True),
        Column('name', 'TEXT', nullable=False),
    ),
    indexes=(Index('idx_hfield_name', ('name',), unique=True),),
)

FACT_SCHEMA = TableSpec(
    name='history_fact',
    columns=(
        Column('series_id', 'INTEGER', nullable=False),
        Column('ts',        'REAL', nullable=False),
        Column('field_id',  'INTEGER', nullable=False),
        # Qué es el valor. Una letra, porque va en cada una de las veintisiete millones de
        # filas; el porqué de que sean ocho está en `values.py`.
        Column('kind',      'TEXT', nullable=False, default="'t'"),
        Column('num',       'REAL'),
        Column('txt',       'TEXT'),
    ),
    indexes=(
        # Cómo se lee UNA serie: sus medidas en un rango de tiempo. Es lo que sirve a `query`.
        Index('idx_hfact_serie', ('series_id', 'ts', 'field_id')),
        # Cómo se pregunta a la FLOTA: un campo, un rango, y el número ya dentro del índice
        # para que el promedio no tenga que visitar la fila. Es el índice que convierte
        # «los diez que más» de 1.264 ms en 25.
        Index('idx_hfact_campo', ('field_id', 'ts', 'series_id', 'num')),
    ),
)

_F = FIELD_SCHEMA.name
_H = FACT_SCHEMA.name


def _num(v):
    """Un número que sea de verdad un número, venga del motor que venga.

    PostgreSQL devuelve `Decimal` donde SQLite y MySQL devuelven `float`: un `AVG` sobre una
    columna de doble precisión, o un entero multiplicado por un doble —que es lo que hace el
    índice de cubo de `over_time`—. `Decimal` **no es serializable a JSON**, así que la misma
    llamada funciona en dos motores y devuelve un 500 en el tercero, sin que nada en el camino
    parezca específico de ninguno.
    """
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class FactStore:
    """Las medidas de las muestras: escribirlas, leerlas y olvidarlas.

    Vive aparte de :class:`~lib.core.history.store.HistoryStore` porque es otra pregunta —el
    almacén va de muestras y series, esto va de valores— y porque así el diccionario de campos
    tiene un sitio donde cachearse sin ensuciar el otro.
    """

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        # ``nombre -> id``, resuelto una vez por proceso. Un campo se crea una vez y se escribe
        # en cada muestra, así que la búsqueda tiene que costar cero; quien garantiza que hay
        # uno solo es el índice único, no esta caché.
        self._field_ids: dict = {}
        # El diccionario al revés, ``id -> nombre``, que es como se vuelve a componer una
        # medida. Se cachea porque leerlo son 211 filas y recomponer el resumen lo pide una vez
        # por serie: medido, 0,57 s de 1,05 en releer mil cuatrocientas veces la misma tabla.
        self._field_names: dict = {}

    # ── Arranque ──────────────────────────────────────────────────────────────

    def bootstrap(self) -> None:
        self._db.reconcile_table(FIELD_SCHEMA)
        self._db.reconcile_table(FACT_SCHEMA)

    def forget(self) -> None:
        """Olvidar lo que este proceso creía saber. Después de vaciar las tablas, la caché
        apuntaría con ids a filas que ya no están."""
        self._field_ids.clear()
        self._field_names.clear()

    # ── El diccionario de campos ──────────────────────────────────────────────

    def field_ids(self, nombres) -> dict:
        """``{nombre: id}``, creando los que se vean por primera vez.

        En bloque y no uno a uno: una muestra SNMP trae catorce campos, y catorce viajes a la
        base por muestra es lo que convierte una escritura en un problema.
        """
        pedidos = [str(n) for n in nombres]
        faltan = [n for n in pedidos if n not in self._field_ids]
        if faltan:
            self._resolve(sorted(set(faltan)))
        return {n: self._field_ids[n] for n in pedidos if n in self._field_ids}

    def _resolve(self, faltan: list) -> None:
        marcas = ','.join('?' * len(faltan))
        try:
            for fid, nombre in self._db.fetchall(
                    f'SELECT id, name FROM {_F} WHERE name IN ({marcas})', tuple(faltan)) or ():
                self._field_ids[str(nombre)] = int(fid)
            nuevos = [n for n in faltan if n not in self._field_ids]
            for nombre in nuevos:
                try:
                    self._db.execute(f'INSERT INTO {_F}(name) VALUES(?)', (nombre,))
                except Exception:  # pylint: disable=broad-except
                    # Otro proceso llegó antes. El índice único es el árbitro; la respuesta es
                    # volver a preguntar, no decidir nada aquí.
                    pass
            if nuevos:
                # **Sin `commit`.** Dentro de la misma conexión un INSERT sin confirmar ya se
                # ve, así que volver a preguntar funciona igual — y confirmar aquí cerraría la
                # transacción de quien llamó. Es lo que pasaba al migrar: el primer lote creaba
                # los 211 campos, el `commit` cerraba el lote, y las veintiséis mil filas
                # siguientes volvían a escribirse una a una en autocommit.
                self._field_names.clear()
                marcas = ','.join('?' * len(nuevos))
                for fid, nombre in self._db.fetchall(
                        f'SELECT id, name FROM {_F} WHERE name IN ({marcas})',
                        tuple(nuevos)) or ():
                    self._field_ids[str(nombre)] = int(fid)
        except Exception:  # pylint: disable=broad-except
            pass
        # Un tope, porque los nombres los inventan los perfiles y un perfil que los generase sin
        # fin llenaría esto. Cincuenta mil es doscientas veces el catálogo real medido (211).
        if len(self._field_ids) > 50000:
            self._field_ids.clear()

    def field_id_of(self, nombre: str):
        """El id de un campo **sin crearlo**, para quien lee. ``None`` si no existe.

        Leer no crea: preguntar por «los diez más calientes» de un campo que nadie ha medido
        nunca tiene que salir vacío, no dejar un nombre fantasma en el diccionario — que es la
        misma regla que ya cumple `_find_series` con las series.
        """
        got = self._field_ids.get(str(nombre))
        if got:
            return got
        try:
            fila = self._db.fetchone(f'SELECT id FROM {_F} WHERE name = ?', (str(nombre),))
        except Exception:  # pylint: disable=broad-except
            return None
        if not fila:
            return None
        self._field_ids[str(nombre)] = int(fila[0])
        return self._field_ids[str(nombre)]

    def field_names(self) -> dict:
        """``{id: nombre}`` — el diccionario entero, para volver a componer las medidas.

        Cacheado, y **sólo crece**: un id nunca cambia de nombre, así que lo que ya está no
        caduca. Se vuelve a pedir cuando aparece un nombre que este proceso no tenía, que es
        cuando alguien carga una MIB nueva o un módulo empieza a medir algo más.
        """
        if self._field_names:
            return self._field_names
        try:
            self._field_names = {int(r[0]): str(r[1]) for r in
                                 self._db.fetchall(f'SELECT id, name FROM {_F}') or ()}
        except Exception:  # pylint: disable=broad-except
            return {}
        return self._field_names

    # ── Escribir ──────────────────────────────────────────────────────────────

    def write(self, series_id: int, ts: float, medidas: dict | None) -> int:
        """Las medidas de una muestra. Devuelve cuántos hechos escribió.

        Una muestra sin ninguna medida no escribe nada y **eso está bien**: 325 de las 4.026
        muestras reales sólo dicen si la cosa respondió. La fila de la muestra existe por sí
        misma en `history`; aquí no hace falta una fila vacía que lo represente.
        """
        hechos = V.encode_sample(medidas)
        if not hechos or not series_id:
            return 0
        ids = self.field_ids([h[0] for h in hechos])
        filas = [(int(series_id), float(ts), ids[campo], kind, num, txt)
                 for campo, kind, num, txt in hechos if campo in ids]
        if not filas:
            return 0
        try:
            self._db.executemany(
                f'INSERT INTO {_H}(series_id, ts, field_id, kind, num, txt) '
                'VALUES(?, ?, ?, ?, ?, ?)', filas)
        except Exception:  # pylint: disable=broad-except
            return 0
        return len(filas)

    def write_many(self, muestras) -> int:
        """Las medidas de MUCHAS muestras: ``[(series_id, ts, medidas), …]``.

        Un viaje para todos los nombres y un ``executemany`` para todas las filas, en vez de un
        par por muestra. No es una micro-optimización: migrar una instalación llama a esto una
        vez por lote de cinco mil, y haciéndolo muestra a muestra el paso de cinco millones de
        documentos tardaba **2,4 horas** — un arranque que nadie va a esperar, y que se
        interrumpiría a la mitad una y otra vez.
        """
        preparadas = [(int(sid), float(ts), V.encode_sample(medidas))
                      for sid, ts, medidas in muestras if sid]
        nombres = {h[0] for _sid, _ts, hechos in preparadas for h in hechos}
        if not nombres:
            return 0
        ids = self.field_ids(sorted(nombres))
        filas = [(sid, ts, ids[campo], kind, num, txt)
                 for sid, ts, hechos in preparadas
                 for campo, kind, num, txt in hechos if campo in ids]
        if not filas:
            return 0
        try:
            self._db.executemany(
                f'INSERT INTO {_H}(series_id, ts, field_id, kind, num, txt) '
                'VALUES(?, ?, ?, ?, ?, ?)', filas)
        except Exception:  # pylint: disable=broad-except
            return 0
        return len(filas)

    # ── Leer ──────────────────────────────────────────────────────────────────

    def by_sample(self, series_id: int, from_ts: float, to_ts: float) -> dict:
        """``{ts: {campo: valor}}`` de una serie en un rango.

        Sale del índice `(series_id, ts, field_id)` en orden de tiempo, que es como se dibuja.
        """
        nombres = self.field_names()
        fuera: dict = {}
        try:
            filas = self._db.fetchall(
                f'SELECT ts, field_id, kind, num, txt FROM {_H} '
                'WHERE series_id = ? AND ts >= ? AND ts <= ? ORDER BY ts',
                (int(series_id), float(from_ts), float(to_ts))) or ()
        except Exception:  # pylint: disable=broad-except
            return {}
        for ts, fid, kind, num, txt in filas:
            campo = nombres.get(int(fid))
            if campo is not None:
                fuera.setdefault(ts, {})[campo] = V.decode(kind, num, txt)
        return fuera

    def stats(self, series_id: int, field: str, from_ts: float, to_ts: float) -> dict:
        """``{'min', 'max', 'avg'}`` de un campo de una serie, o ``{}``.

        Sin una sola rama por motor y sin lista blanca: el nombre del campo es un parámetro que
        se busca en el diccionario, el número vive en su columna, y ``AVG`` es ``AVG``. Lo que
        había antes —tres formas de sacar un número de un JSON, una por motor, más un
        ``try/except`` porque PostgreSQL lanza donde los otros dan NULL— era todo consecuencia
        de guardar el documento.
        """
        fid = self.field_id_of(field)
        if not fid:
            return {}
        marcas = ','.join('?' * len(V.NUMERIC_KINDS))
        try:
            fila = self._db.fetchone(
                f'SELECT MIN(num), MAX(num), AVG(num) FROM {_H} '
                f'WHERE series_id = ? AND field_id = ? AND ts >= ? AND ts <= ? '
                f'AND kind IN ({marcas}) AND num IS NOT NULL',
                (int(series_id), int(fid), float(from_ts), float(to_ts)) + V.NUMERIC_KINDS)
        except Exception:  # pylint: disable=broad-except
            return {}
        if not fila or fila[0] is None:
            return {}
        return {'min': _num(fila[0]), 'max': _num(fila[1]), 'avg': _num(fila[2])}

    # ── Preguntarle a la FLOTA ────────────────────────────────────────────────
    #
    # Esto es para lo que existe esta tabla. No acelera nada de lo que el panel ya hacía —leer
    # una serie cuesta 8 ms de las dos formas—: hace posible lo que no hacía, y por eso la
    # capacidad vive aquí, en métodos, y no en «escríbete el SQL». Una capacidad que hay que
    # redactar a mano cada vez no está habilitada, está sólo permitida.
    #
    # Las tres salen del índice `(field_id, ts, series_id, num)`, con el número dentro para que
    # el promedio no tenga que visitar la fila. Medido sobre 30 días de una instalación real
    # (27.588.336 hechos): 25 ms, 1 ms y 24 ms.

    def fields(self) -> list[str]:
        """Qué se puede preguntar: todos los nombres de campo que existen, ordenados."""
        try:
            return sorted(str(r[0]) for r in
                          self._db.fetchall(f'SELECT name FROM {_F}') or ())
        except Exception:  # pylint: disable=broad-except
            return []

    def top(self, field: str, from_ts: float, to_ts: float, *,
            limit: int = 10, agg: str = 'avg', desc: bool = True) -> list[dict]:
        """Las series con mayor (o menor) *agg* de un campo en un rango.

        «Los diez discos más calientes», «las interfaces que más tráfico llevan». Medido: 25 ms
        sobre treinta días; con el documento eran 1.264 ms, que es por lo que nadie lo escribió.
        """
        fid = self.field_id_of(field)
        funcion = {'avg': 'AVG', 'max': 'MAX', 'min': 'MIN', 'sum': 'SUM'}.get(str(agg).lower())
        if not fid or not funcion:
            return []
        marcas = ','.join('?' * len(V.NUMERIC_KINDS))
        try:
            filas = self._db.fetchall(
                f'SELECT series_id, {funcion}(num), COUNT(*) FROM {_H} '
                f'WHERE field_id = ? AND ts >= ? AND ts <= ? AND kind IN ({marcas}) '
                'AND num IS NOT NULL '
                f'GROUP BY series_id ORDER BY 2 {"DESC" if desc else "ASC"} LIMIT ?',
                (int(fid), float(from_ts), float(to_ts)) + V.NUMERIC_KINDS
                + (max(1, int(limit)),)) or ()
        except Exception:  # pylint: disable=broad-except
            return []
        return [{'series_id': int(r[0]), 'value': _num(r[1]), 'samples': int(r[2])}
                for r in filas]

    def series_where(self, field: str, from_ts: float, to_ts: float, *,
                     op: str = '>', value: float = 0) -> list[int]:
        """Qué series cumplieron una condición sobre un campo en un rango.

        «Qué interfaces dieron errores en la última hora». Medido: 1 ms sobre treinta días,
        contra 915 ms recorriendo documentos.
        """
        fid = self.field_id_of(field)
        if not fid or str(op) not in ('>', '>=', '<', '<=', '=', '!='):
            return []
        marcas = ','.join('?' * len(V.NUMERIC_KINDS))
        try:
            filas = self._db.fetchall(
                f'SELECT DISTINCT series_id FROM {_H} '
                f'WHERE field_id = ? AND ts >= ? AND ts <= ? AND kind IN ({marcas}) '
                f'AND num IS NOT NULL AND num {op} ?',
                (int(fid), float(from_ts), float(to_ts)) + V.NUMERIC_KINDS
                + (float(value),)) or ()
        except Exception:  # pylint: disable=broad-except
            return []
        return [int(r[0]) for r in filas]

    def over_time(self, field: str, from_ts: float, to_ts: float, *,
                  bucket: float = 3600.0, series_ids=None) -> list[dict]:
        """El campo agregado por tramos de tiempo sobre TODAS las series (o las que se digan).

        «La media de la flota por hora». La base de una alerta sobre una media móvil, que hoy
        no se puede escribir. Medido: 24 ms sobre treinta días.
        """
        fid = self.field_id_of(field)
        if not fid or bucket <= 0:
            return []
        _int = 'SIGNED' if getattr(self._db, 'KIND', 'sqlite') == 'mysql' else 'INTEGER'
        marcas = ','.join('?' * len(V.NUMERIC_KINDS))
        where, extra = '', ()
        sids = [int(x) for x in (series_ids or ())]
        if sids:
            where = f' AND series_id IN ({",".join("?" * len(sids))})'
            extra = tuple(sids)
        try:
            filas = self._db.fetchall(
                f'''SELECT CAST(FLOOR((ts - ?) / ?) AS {_int}) * ? + ? AS bts,
                           AVG(num), MIN(num), MAX(num), COUNT(*)
                    FROM {_H}
                    WHERE field_id = ? AND ts >= ? AND ts <= ? AND kind IN ({marcas})
                      AND num IS NOT NULL{where}
                    GROUP BY bts ORDER BY bts''',
                (float(from_ts), float(bucket), float(bucket), float(from_ts),
                 int(fid), float(from_ts), float(to_ts)) + V.NUMERIC_KINDS + extra) or ()
        except Exception:  # pylint: disable=broad-except
            return []
        return [{'ts': _num(r[0]), 'avg': _num(r[1]), 'min': _num(r[2]), 'max': _num(r[3]),
                 'samples': int(r[4])} for r in filas]

    # ── Olvidar ───────────────────────────────────────────────────────────────

    def delete_series(self, series_id: int) -> int:
        try:
            return self._db.execute(f'DELETE FROM {_H} WHERE series_id = ?', (int(series_id),))
        except Exception:  # pylint: disable=broad-except
            return 0

    def delete_all(self) -> int:
        try:
            borradas = self._db.execute(f'DELETE FROM {_H}')
            self._db.execute(f'DELETE FROM {_F}')
            self.forget()
            return borradas
        except Exception:  # pylint: disable=broad-except
            return 0
