#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Time-series history store for ServiceSentry check results.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default;
PostgreSQL/MySQL supported through the same interface).

Schema
------
Table ``history`` — one row per monitored item per check cycle:

    id        — auto-increment primary key
    ts        — Unix timestamp (float)
    item_uid  — stable UUID for the item (null when not yet assigned)
    status    — 1 = OK, 0 = error
    data      — JSON of the MEASUREMENTS of this reading
    series_id — → history_series.id: which series this is a sample of

Table ``history_series`` — one row per series: the module, the key and the identity, which do
not change between two readings and used to be written out on every one of them.
"""

from __future__ import annotations

import json
import logging
import re
import time

from lib.db import BaseConnector, get_connector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

from .facts import FACT_SCHEMA, FactStore

_log = logging.getLogger(__name__)

_PREFERRED_FIELDS = (
    'temp', 'used', 'count', 'code', 'response_time',
    'latency_ms', 'latency', 'value', 'rate', 'level',
)

# Whitelist for JSON field names used in get_stats (prevents SQL/JSON-path injection).
_FIELD_RE = re.compile(r'^[A-Za-z0-9_]+$')

_SCHEMA = TableSpec(
    name='history',
    columns=(
        Column('id',       'AUTOINCREMENT', primary_key=True),
        Column('ts',       'REAL', nullable=False),
        Column('item_uid', 'TEXT'),
        Column('status',   'INTEGER', nullable=False),
        # `data` ya no está. Las medidas son filas en `history_fact`, una por valor medido: es
        # lo que permite preguntarle a la FLOTA y no sólo a una serie. El porqué, con los
        # números, en `facts.py`.
        #
        # Una base anterior al cambio llega aquí con la columna puesta, y el reconciliador **no
        # la borra** —una columna que dejó de declararse se conserva y se reporta, que es lo
        # correcto: borrar algo que no puso él sería decidir sobre una base que no conoce—. Se
        # queda ahí sin que nadie la lea, que es lo que ya hacía.
        # → history_series.id. Nullable because a sample recorded while the series could not
        # be resolved is still a sample: losing the id costs a join, refusing the row costs
        # the measurement.
        Column('series_id', 'INTEGER'),
    ),
    indexes=(
        # Cómo se lee una serie: por su id y en orden de tiempo. Es lo que sirve a las cuatro
        # lecturas desde el paso 6.
        #
        # ``status`` va dentro no para buscar por él, sino para no salir del índice: contar las
        # muestras de cada serie y cuántas estaban bien es un recorrido agrupado, y con el
        # estado fuera había que visitar la fila entera de cada una. Medido sobre una copia de
        # 30 días de una instalación real (5.266.008 muestras): **108,0 s → 2,4 s**, por 19 MB
        # de índice (877,5 → 896,7 MB).
        # Es lo que hace asumible reparar el resumen después de podar.
        Index('idx_history_series_ts', ('series_id', 'ts', 'status')),
    ),
)

_T = _SCHEMA.name  # table name — single source of truth

# ── The series ────────────────────────────────────────────────────────────────────────
#
# One row per SERIES, not per sample: what does not change between two readings of the same
# thing — the module, the key, and (from step 5) the identity a sample carries around today in
# every ``data`` blob.
#
# The reason is measured, not aesthetic. On a real installation SNMP is 83 % of this table, and
# of the 217 bytes one of its samples occupies, **11 are the measurement**: 54 are the key,
# written out again on every row, and the rest is identity that never changes plus the names of
# the fields, repeated. See ``docs/explica-snmp.md``.
#
# ``(module, key)`` is unique because that is how the rest of the product addresses a series —
# ``query``, ``delete_series`` and the coordinates the metrics payload carries all use that
# pair. ``item_uid`` travels along for the day something starts writing one (nothing does
# today, in any of the 112.000 rows of that installation), and is deliberately NOT the
# identity: a series that changed its uid would become a second series.
_SERIES_SCHEMA = TableSpec(
    name='history_series',
    columns=(
        Column('id',       'AUTOINCREMENT', primary_key=True),
        Column('module',   'TEXT', nullable=False),
        Column('key',      'TEXT', nullable=False),
        Column('item_uid', 'TEXT'),
        # What the thing IS, as last seen. Written in step 5; the migration leaves it empty,
        # because inventing it from a sample would be inventing the date it was true.
        Column('attrs',    'TEXT'),
        Column('first_ts', 'REAL'),
        Column('last_ts',  'REAL'),
        # El resumen de la serie: lo que el catálogo pregunta de ella, contestado por la fila
        # que la representa y no recorriendo sus muestras.
        #
        # No es desnormalización por gusto: es la única forma de que la pregunta no crezca con
        # el histórico. ``get_index`` calculaba esto con una función de ventana y un agregado —
        # dos pasadas sobre la tabla ENTERA para devolver una fila por serie. Medido sobre 30
        # días de una instalación real: **235.674 ms**. Lo mismo leído de aquí: **6,6 ms**.
        #
        # Se mantiene en el mismo UPDATE que ``record`` ya hacía por cada muestra (0,004 ms),
        # y se repara en ``prune``, que es lo único que quita muestras por detrás.
        Column('samples',     'INTEGER'),
        Column('up_samples',  'INTEGER'),
        Column('last_status', 'INTEGER'),
        Column('last_data',   'TEXT'),
    ),
    indexes=(Index('idx_hseries_mk', ('module', 'key'), unique=True),),
)

_TS = _SERIES_SCHEMA.name
_H = FACT_SCHEMA.name


def _split_sample(data: dict | None) -> tuple[dict, dict]:
    """``(medidas, identidad)`` — lo que la muestra MIDE y lo que la serie ES.

    La frontera es la que ya usan los módulos: una clave que empieza por ``_`` habla *del*
    resultado y no es una medida suya.
    """
    medidas: dict = {}
    identidad: dict = {}
    for clave, valor in (data or {}).items():
        (identidad if str(clave).startswith('_') else medidas)[clave] = valor
    return medidas, identidad


class HistoryStore(BaseStore):
    """Backend-agnostic time-series store."""

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        # ``key`` is a reserved word in MySQL — quote it (dialect-aware) in every raw query.
        self._qk = db.quote_ident('key')
        # ``(module, key) -> id``, resolved once per process. A series is created once and
        # read on every sample, so the lookup has to cost nothing; the unique index is what
        # actually guarantees there is one, not this.
        self._series_ids: dict = {}
        # Lo último que se escribió como identidad de cada serie, para no reescribir lo mismo
        # en cada muestra.
        self._series_attrs: dict = {}
        # Las MEDIDAS, una fila por valor medido. Aparte porque es otra pregunta: este almacén
        # va de muestras y de series, aquél va de valores.
        self.facts = FactStore(db)
        self._bootstrap()

    # ── Schema bootstrap ──────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)
        self._db.reconcile_table(_SERIES_SCHEMA)
        self.facts.bootstrap()
        self._fill_summary()

    def _fill_summary(self) -> None:
        """Dar resumen a las series que se grabaron antes de que existiera.

        No es una migración con fecha de caducidad: es la respuesta a «esta serie no sabe
        cuántas muestras tiene». Se hace sola la primera vez y después cuesta una pregunta que
        no devuelve nada — medida en **0,7 ms** sobre 1.465 series.

        El recuento entero cuesta 2,4 s sobre cinco millones de muestras porque el índice cubre
        ``status``; la última muestra de cada serie son 0,29 ms de búsqueda indexada.
        """
        try:
            if not self._db.fetchone(f'SELECT id FROM {_TS} WHERE samples IS NULL LIMIT 1'):
                return
        except Exception:  # pylint: disable=broad-except
            return   # la tabla aún no tiene las columnas; el reconciliador va antes que esto
        try:
            self._resummarise(con_ultima=True)
            self._db.commit()
        except Exception:  # pylint: disable=broad-except
            pass

    def _resummarise(self, *, con_ultima: bool = False) -> None:
        """Recalcular el resumen de cada serie a partir de las muestras que le quedan.

        *con_ultima* pide además la última muestra de cada una. Al rellenar hace falta —no hay
        otro sitio de donde sacarla—; al podar no, porque podar quita las viejas y la última
        sigue siendo la misma. Lo que sí cambia al podar es la serie que se queda **sin
        ninguna**: ahí lo último que dijo ya no existe, y seguir sirviéndolo sería dar por
        presente una medida borrada.

        No hace ``commit``: quien llama decide la transacción, porque ``prune`` borra y repara
        dentro de la misma.
        """
        agg = self._db.fetchall(
            f'SELECT series_id, COUNT(*), SUM(status), MIN(ts), MAX(ts) '
            f'FROM {_T} WHERE series_id IS NOT NULL GROUP BY series_id')
        vivas = set()
        for sid, n, arriba, primera, ultima in agg:
            vivas.add(int(sid))
            if con_ultima:
                fila = self._db.fetchone(
                    f'SELECT ts, status FROM {_T} WHERE series_id = ? '
                    'ORDER BY ts DESC, id DESC LIMIT 1', (sid,))
                medidas = {}
                if fila:
                    medidas = self.facts.by_sample(
                        int(sid), float(fila[0]), float(fila[0])).get(fila[0], {})
                self._db.execute(
                    f'UPDATE {_TS} SET samples = ?, up_samples = ?, first_ts = ?, '
                    'last_ts = ?, last_status = ?, last_data = ? WHERE id = ?',
                    (int(n or 0), int(arriba or 0), primera, ultima,
                     (fila[1] if fila else None),
                     (json.dumps(medidas, ensure_ascii=False) if fila else None), int(sid)))
            else:
                self._db.execute(
                    f'UPDATE {_TS} SET samples = ?, up_samples = ?, first_ts = ?, last_ts = ? '
                    'WHERE id = ?',
                    (int(n or 0), int(arriba or 0), primera, ultima, int(sid)))
        try:
            todas = {int(r[0]) for r in self._db.fetchall(f'SELECT id FROM {_TS}')}
        except Exception:  # pylint: disable=broad-except
            return
        for sid in todas - vivas:
            self._db.execute(
                f'UPDATE {_TS} SET samples = 0, up_samples = 0, first_ts = NULL, '
                'last_ts = NULL, last_status = NULL, last_data = NULL WHERE id = ?', (sid,))

    # ── The series ────────────────────────────────────────────────────────────

    def _touch_series(self, sid: int, ident: tuple, identidad: dict, ts: float,
                      status: bool, medidas: str) -> int | None:
        """Guardar en la serie lo que la fila ES, cuándo se la vio y en qué estado queda.

        La identidad se escribe **sólo cuando cambia**: es lo mismo en muestra tras muestra
        —ese es el motivo de sacarla de la muestra— y volver a escribirla cada vez cambiaría un
        derroche de bytes por un derroche de escrituras.

        El resto va siempre, y es lo que hace que el catálogo no tenga que recorrer el
        histórico para contestar por él: una muestra más, una más buena o no, y lo último que
        dijo. Es la misma actualización por clave primaria que ya se hacía para `last_ts`, con
        cuatro columnas más — **0,004 ms** medidos por muestra.

        El COALESCE no es adorno: una serie creada por `series_id` todavía no tiene contador, y
        sumar uno a NULL da NULL en los tres motores.

        Returns the rows updated — 0 means *sid* is no longer this series (another process
        deleted it, or a restore refilled the table under it) — or ``None`` when the UPDATE
        itself failed. The WHERE carries ``(module, key)`` besides the id so that an id the
        engine handed out again to a different series also reads as 0, not as a hit.
        """
        crudo = json.dumps(identidad, ensure_ascii=False, sort_keys=True) if identidad else ''
        resumen = ('samples = COALESCE(samples, 0) + 1, '
                   'up_samples = COALESCE(up_samples, 0) + ?, '
                   'last_status = ?, last_data = ?, '
                   'last_ts = ?, first_ts = COALESCE(first_ts, ?)')
        datos = (1 if status else 0, 1 if status else 0, medidas, ts, ts)
        donde = f'WHERE id = ? AND module = ? AND {self._qk} = ?'
        clave = (sid, ident[0], ident[1])
        try:
            if self._series_attrs.get(sid) == crudo:
                return self._db.execute(
                    f'UPDATE {_TS} SET {resumen} {donde}', datos + clave)
            n = self._db.execute(
                f'UPDATE {_TS} SET attrs = ?, {resumen} {donde}',
                (crudo or None,) + datos + clave)
            if n:
                self._series_attrs[sid] = crudo
            return n
        except Exception:  # pylint: disable=broad-except
            return None

    def _find_series(self, module: str, key: str, item_uid: str | None = None):
        """El id de una serie **sin crearla**, para quien lee. ``None`` si no existe.

        Leer no crea: una gráfica de algo que nunca se midió tiene que salir vacía, no dejar
        una serie fantasma en el catálogo.
        """
        k = self._qk
        try:
            if item_uid:
                fila = self._db.fetchone(
                    f'SELECT id FROM {_TS} WHERE item_uid = ?', (item_uid,))
                if fila:
                    return int(fila[0])
            fila = self._db.fetchone(
                f'SELECT id FROM {_TS} WHERE module = ? AND {k} = ?',
                (str(module or ''), str(key or '')))
            return int(fila[0]) if fila else None
        except Exception:  # pylint: disable=broad-except
            return None

    def _attrs_map(self) -> dict:
        """``{(module, key): identidad}`` de las series que tienen alguna."""
        k = self._qk
        try:
            filas = self._db.fetchall(
                f'SELECT module, {k}, attrs FROM {_TS} WHERE attrs IS NOT NULL')
        except Exception:  # pylint: disable=broad-except
            return {}
        fuera = {}
        for module, key, crudo in filas:
            datos = _load_json(crudo)
            if datos:
                fuera[(module, key)] = datos
        return fuera

    def _with_attrs(self, datos: dict, identidad: dict) -> dict:
        """La forma de siempre: la identidad de la serie, con la muestra por encima.

        La muestra gana porque una fila anterior a este cambio lleva su propia copia, y esa es
        la que era verdad **ese día**; la de la serie es la última que se vio.
        """
        if not identidad:
            return datos
        return {**identidad, **(datos or {})}

    def series_id(self, module: str, key: str, *, item_uid: str | None = None) -> int | None:
        """The id of one series, creating it if this is the first time it is seen.

        ``None`` when it cannot be resolved — the caller writes the sample anyway. Losing the
        series id costs a join; refusing the sample costs the measurement.
        """
        ident = (str(module or ''), str(key or ''))
        got = self._series_ids.get(ident)
        if got:
            return got
        k = self._qk
        try:
            row = self._db.fetchone(
                f'SELECT id FROM {_TS} WHERE module = ? AND {k} = ?', ident)
            if not row:
                try:
                    # Nace con el resumen a cero, no a NULL. NULL significa «esta serie es
                    # anterior a que el resumen existiera» y dispara el relleno al arrancar; una
                    # serie creada aquí cuya muestra no llegue a escribirse —el INSERT de
                    # `record` puede fallar— dejaría esa marca puesta para siempre, y cada
                    # arranque del panel recalcularía el histórico entero por ella.
                    self._db.execute(
                        f'INSERT INTO {_TS}(module, {k}, item_uid, samples, up_samples) '
                        'VALUES(?, ?, ?, 0, 0)',
                        (ident[0], ident[1], item_uid or None))
                    self._db.commit()
                except Exception:  # pylint: disable=broad-except
                    # Another process got there first. The unique index is the arbiter, so the
                    # answer is to ask again rather than to decide anything here.
                    pass
                row = self._db.fetchone(
                    f'SELECT id FROM {_TS} WHERE module = ? AND {k} = ?', ident)
        except Exception:  # pylint: disable=broad-except
            return None
        if not row or row[0] is None:
            return None
        # A cap, because the key of a series comes from a device and a module that names its
        # rows badly could invent them without end. Twenty thousand is ten times the largest
        # real catalogue measured (1.959 series) and small enough to be nothing in memory.
        if len(self._series_ids) > 20000:
            self._series_ids.clear()
        self._series_ids[ident] = int(row[0])
        return self._series_ids[ident]

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(
        self,
        module: str,
        key: str,
        status: bool,
        data: dict | None = None,
        *,
        item_uid: str | None = None,
    ) -> None:
        """Insert one sample — the MEASUREMENTS of it.

        What the thing IS goes to its series instead of being written out again on every
        reading. The convention already exists and is the recorders' own: a key starting with
        an underscore is *about* the result rather than a measurement of it — ``_attrs`` (the
        identity facts: a disk's model and serial, an interface's MAC), ``_row`` (what the row
        is called), ``_watched`` and ``_role``. None of them is a series; all of them were
        being repeated in every sample.

        Measured on a real installation: of the 217 bytes an SNMP sample occupied, 78 were
        this. See ``docs/explica-snmp.md``.

        Reads put it back (:meth:`_with_attrs`), so nothing above this store can tell — and a
        sample recorded before this change keeps its own copy, which wins over the series'.
        """
        now = time.time()
        medidas, identidad = _split_sample(data)
        sid = self.series_id(module, key, item_uid=item_uid)
        # Lo último que dijo la serie sigue siendo un documento, y ahí sí está bien: es UNA fila
        # por serie —1.465 en una instalación real—, no una por muestra. Lo que no se puede
        # repetir cinco millones de veces se puede guardar mil veces sin pensarlo.
        crudo = json.dumps(medidas, ensure_ascii=False)
        ident = (str(module or ''), str(key or ''))
        try:
            if sid and self._touch_series(sid, ident, identidad, now, status, crudo) == 0:
                # The id this process remembers is not this series any more: the web deleted
                # it (or emptied the history, or a restore refilled the table) and only ITS
                # cache was cleared. Writing on would file every new sample under a series
                # that does not exist — invisible until a restart. So the caches go (field
                # ids too: emptying the history empties the field dictionary with it) and
                # the series is resolved again, which creates it afresh.
                self._forget_series()
                sid = self.series_id(module, key, item_uid=item_uid)
                if sid:
                    self._touch_series(sid, ident, identidad, now, status, crudo)
            self._db.execute(
                f'INSERT INTO {_T}(ts, item_uid, status, series_id) '
                'VALUES(?, ?, ?, ?)',
                (now, item_uid, 1 if status else 0, sid),
            )
            if sid:
                # Las medidas, además, una fila por valor. En la MISMA transacción que la
                # muestra: una muestra sin sus medidas sería un punto en la gráfica sin nada
                # que dibujar, y las dos escrituras tienen que vivir o morir juntas.
                self.facts.write(sid, now, medidas)
            self._db.commit()
        except Exception as exc:  # pylint: disable=broad-except
            import sys  # noqa: PLC0415
            print(
                f'[history] record() FAILED {module}/{key}: '
                f'{type(exc).__name__}: {exc}',
                file=sys.stderr, flush=True,
            )

    def delete_series(
        self, module: str, key: str, *, item_uid: str | None = None
    ) -> int:
        """Delete all records for one series (by UID when available)."""
        sid = self._find_series(module, key, item_uid)
        if sid is None:
            return 0
        try:
            with self._db.transaction():
                self.facts.delete_series(sid)
                deleted = self._db.execute(f'DELETE FROM {_T} WHERE series_id = ?', (sid,))
                # Y la serie con ellas: dejarla sería guardar la identidad de algo de lo que ya
                # no queda ni una muestra, y devolvérsela a la primera muestra nueva que
                # coincidiera de nombre.
                self._db.execute(f'DELETE FROM {_TS} WHERE id = ?', (sid,))
            self._forget_series()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    def delete_all(self) -> int:
        """Delete all rows and reclaim disk space."""
        try:
            with self._db.transaction():
                self.facts.delete_all()
                deleted = self._db.execute(f'DELETE FROM {_T}')
                # Las series también, y las cachés: si no, la primera muestra después de
                # vaciarlo apuntaría con un id de memoria a una fila que ya no está.
                self._db.execute(f'DELETE FROM {_TS}')
            self._forget_series()
            self._db.vacuum()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    def _forget_series(self) -> None:
        """Olvidar lo que este proceso creía saber de las series."""
        self._series_ids.clear()
        self._series_attrs.clear()
        self.facts.forget()

    def prune(self, retention_days: int) -> int:
        """Delete records older than *retention_days* (0 = keep all)."""
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        try:
            # **Todo en una transacción.** El conector va en autocommit, así que sin esto cada
            # sentencia se sincroniza a disco por su cuenta. Medido sobre 3,1 millones de
            # medidas: 427 s sueltas contra 93 dentro de una.
            with self._db.transaction():
                deleted = self._db.execute(f'DELETE FROM {_T} WHERE ts < ?', (cutoff,))
                if deleted:
                    # Y sus medidas, en **un solo** DELETE por tiempo.
                    #
                    # Aquí me equivoqué por escrito antes de medir: parecía evidente que borrar
                    # serie a serie sería mejor, porque `(series_id, ts, field_id)` acota y un
                    # `WHERE ts < ?` a secas recorre la tabla entera. Es al revés. Sobre los
                    # mismos 3,1 millones de medidas: 93 s serie a serie contra **57 s** de una
                    # pasada. El recorrido es barato; lo caro son mil cuatrocientas sentencias,
                    # cada una con su descenso por el árbol y su contabilidad.
                    self._db.execute(f'DELETE FROM {_H} WHERE ts < ?', (cutoff,))
                    # El resumen de cada serie decía cuántas muestras tenía y desde cuándo, y
                    # después de podar deja de ser verdad: son las cuentas de unas filas que ya
                    # no existen. Se recalcula aquí dentro — dejarlo para después sería
                    # publicar un catálogo que cuenta lo que acaba de borrar.
                    #
                    # Una serie de la que no queda nada se queda a cero y no se borra: sigue
                    # siendo la misma serie, y su identidad es lo único que quedaba de ella.
                    self._resummarise()
            self._db.checkpoint()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    # ── Read ──────────────────────────────────────────────────────────────────

    def latest_ts(self) -> float | None:
        """Unix timestamp of the most recent recorded check, or None if empty.

        Used to detect an external monitoring worker: if the web's own scheduler
        is stopped yet checks keep landing here, a separate worker is running."""
        try:
            row = self._db.fetchone(f'SELECT MAX(ts) FROM {_T}')
        except Exception:  # pylint: disable=broad-except
            return None
        return row[0] if row and row[0] is not None else None

    def get_index(self) -> list[dict]:
        """Return metadata for every recorded series.

        Leído de la serie, que es donde vive la respuesta: cuántas muestras, desde cuándo,
        hasta cuándo, cuántas estaban bien y qué dijo la última. **No se toca la tabla de
        muestras.**

        Antes se calculaba: una función de ventana elegía la última fila de cada serie
        mientras un agregado contaba el resto — dos pasadas sobre el histórico ENTERO para
        devolver una fila por serie. Eso es asumible con cuatro mil filas y ruinoso con cinco
        millones: medido sobre una copia de 30 días de una instalación real (5.266.008
        muestras, 1.465 series), **235.674 ms**. Lo mismo desde aquí: **6,6 ms**.

        Una serie sin ninguna muestra no sale, como no salía antes: el agregado no le daba
        grupo. Sigue existiendo en el catálogo de series; lo que no tiene es histórico que
        enseñar.
        """
        k = self._qk
        try:
            rows = self._db.fetchall(f'''
                SELECT module, item_uid, {k}, samples, last_ts, first_ts,
                       up_samples, last_data, last_status
                FROM {_TS}
                WHERE samples > 0
                ORDER BY module, {k}
            ''')
        except Exception:  # pylint: disable=broad-except
            return []
        _mapa = self._attrs_map()
        fuera = []
        for r in rows:
            n = int(r[3] or 0)
            fuera.append({
                'module':      r[0],
                'item_uid':    r[1],
                'key':         r[2],
                'count':       n,
                'last_ts':     r[4],
                'first_ts':    r[5],
                'uptime':      round(int(r[6] or 0) * 100.0 / n, 1),
                'last_data':   self._with_attrs(_load_json(r[7]),
                                                _mapa.get((r[0], r[2]), {})),
                'last_status': None if r[8] is None else bool(r[8]),
            })
        return fuera

    def latest_by_series(self, modules: list | tuple | None = None) -> list[dict]:
        """The LAST sample of each series — and nothing else about it.

        Misma fuente que :meth:`get_index` desde que el resumen vive en la serie; lo que las
        separa ya no es el coste sino cuánto devuelven. Ésta es el respaldo de la ficha del
        dispositivo, que quiere cuatro campos para un chequeo sin estado vivo.

        Existía porque `get_index` costaba ~700 ms de agregado sobre un histórico de 54.000
        filas para leer esos cuatro campos, y eso se pagaba en cada clic de la lista de la
        flota — que es lo que hacía que abrir una máquina tardase segundos con la URL ya
        cambiada. Ese motivo desapareció; la función se queda porque la pregunta es distinta.

        El filtro por módulo se aplica sobre la serie, que es quien lo guarda.
        """
        k = self._qk
        where, args = ' WHERE samples > 0', ()
        mods = [str(m) for m in (modules or ()) if str(m or '').strip()]
        if mods:
            where += f' AND module IN ({",".join("?" * len(mods))})'
            args = tuple(mods)
        try:
            rows = self._db.fetchall(
                f'SELECT module, item_uid, {k}, last_ts, last_status, last_data '
                f'FROM {_TS}{where}', args)
        except Exception:  # pylint: disable=broad-except
            return []
        mapa = self._attrs_map()
        return [
            {
                'module':      r[0],
                'item_uid':    r[1],
                'key':         r[2],
                'last_ts':     r[3],
                'last_status': None if r[4] is None else bool(r[4]),
                'last_data':   self._with_attrs(_load_json(r[5]), mapa.get((r[0], r[2]), {})),
            }
            for r in rows
        ]

    def query(
        self,
        module: str,
        key: str,
        from_ts: float,
        to_ts: float,
        max_points: int = 500,
        *,
        item_uid: str | None = None,
    ) -> list[dict]:
        """Return (possibly time-bucketed) samples ordered by time.

        La muestra —cuándo y si respondió— sale de `history`; sus medidas, de `history_fact`.
        Lo que devuelve es lo de siempre: ``{'ts', 'status', 'data'}`` con `data` otra vez un
        diccionario, porque nadie por encima de este almacén sabe —ni tiene por qué saber— cómo
        está guardado.
        """
        # Por SERIE, que es un entero y un índice. Una serie que no existe no se crea al leerla:
        # la respuesta es que no hay nada que dibujar.
        sid = self._find_series(module, key, item_uid)
        if sid is None:
            return []
        where = 'series_id = ? AND ts >= ? AND ts <= ?'
        w_args: tuple = (sid, from_ts, to_ts)
        try:
            row = self._db.fetchone(
                f'SELECT COUNT(*) FROM {_T} WHERE {where}', w_args
            )
            count = row[0] if row else 0
            if count == 0:
                return []

            bucket = (to_ts - from_ts) / max_points if max_points > 0 else 0
            if count <= max_points or bucket <= 0:
                filas = self._db.fetchall(
                    f'SELECT ts, status FROM {_T} WHERE {where} ORDER BY ts', w_args)
            else:
                # MySQL's CAST target is SIGNED, not INTEGER (SQLite/PostgreSQL accept INTEGER).
                _int = 'SIGNED' if getattr(self._db, 'KIND', 'sqlite') == 'mysql' else 'INTEGER'
                # FLOOR before the cast so the bucket index truncates identically on all
                # engines (PostgreSQL's CAST(double AS int) rounds; SQLite/MySQL truncate) —
                # operand is always >= 0 (ts >= from_ts), so FLOOR == truncate.
                # GROUP BY the OUTPUT COLUMN, not a repeat of the inner expression: MySQL runs
                # with ONLY_FULL_GROUP_BY by default and rejects a select expression it cannot
                # prove is functionally dependent on the grouping one. The result was every
                # history graph coming back EMPTY on MySQL (the query raises, and the caller's
                # except returns []). Grouping by the alias is exact and all three engines
                # accept an output name there.
                #
                # Lo que cambia respecto al documento: antes cada cubo devolvía `MAX(data)`, que
                # es el máximo de una CADENA JSON — es decir, una muestra cualquiera del cubo,
                # elegida por cómo se ordenan sus caracteres. Ahora devuelve **la última** del
                # cubo, que es una regla que se puede decir en voz alta.
                filas = self._db.fetchall(
                    f'''SELECT
                        CAST(FLOOR((ts - ?) / ?) AS {_int}) * ? + ? AS bts,
                        CAST(ROUND(AVG(status)) AS {_int}),
                        MAX(ts)
                    FROM {_T} WHERE {where}
                    GROUP BY bts
                    ORDER BY bts''',
                    (from_ts, bucket, bucket, from_ts) + w_args,
                )
                filas = [(r[2], r[1], r[0]) for r in filas]   # (ts real, status, ts del cubo)

            medidas = self.facts.by_sample(sid, from_ts, to_ts)
            identidad = self._attrs_map().get((module, key), {})
            fuera = []
            for fila in filas:
                ts_real, status = fila[0], fila[1]
                fuera.append({
                    'ts': fila[2] if len(fila) > 2 else ts_real,
                    'status': status,
                    'data': self._with_attrs(medidas.get(ts_real, {}), identidad),
                })
            return fuera
        except Exception:  # pylint: disable=broad-except
            return []

    def get_stats(
        self,
        module: str,
        key: str,
        from_ts: float,
        to_ts: float,
        field: str | None = None,
        *,
        item_uid: str | None = None,
    ) -> dict:
        """Return aggregate statistics for a series in a time range.

        Esto era el único sitio de todo el proyecto donde el SQL tocaba un JSON, y le costaba
        tres ramas por motor —`json_extract` en SQLite, `json_extract` con `AS DOUBLE` en MySQL,
        `jsonb_extract_path_text` en PostgreSQL, que no tiene `json_extract`—, un `try/except`
        propio porque PostgreSQL **lanza** al castear un valor no numérico donde los otros dos
        devuelven NULL, y una lista blanca contra inyección porque el nombre del campo entraba en
        el SQL.

        Con una fila por valor medido no queda nada de eso: el nombre del campo es un parámetro
        que se busca en el diccionario, el número está en su columna, y `AVG` es `AVG`.
        """
        sid = self._find_series(module, key, item_uid)
        if sid is None:
            return {}
        try:
            row = self._db.fetchone(
                f'SELECT COUNT(*), AVG(status), MIN(ts), MAX(ts) FROM {_T} '
                'WHERE series_id = ? AND ts >= ? AND ts <= ?',
                (sid, from_ts, to_ts),
            )
            if not row or not row[0]:
                return {}
            result: dict = {
                'count':    row[0],
                'uptime':   round((row[1] or 0) * 100, 1),
                'first_ts': row[2],
                'last_ts':  row[3],
            }
            if field:
                num = self.facts.stats(sid, str(field), from_ts, to_ts)
                if num:
                    result.update(num)
            return result
        except Exception:  # pylint: disable=broad-except
            return {}

    @staticmethod
    def suggest_field(points: list[dict]) -> str | None:
        """Return the best numeric field name to chart from a sample set."""
        sample: dict = {}
        for p in points[:20]:
            sample.update(p.get('data') or {})
        for f in _PREFERRED_FIELDS:
            if isinstance(sample.get(f), (int, float)):
                return f
        for k, v in sample.items():
            if isinstance(v, (int, float)):
                return k
        return None

    def forget_cache(self) -> None:
        """Forget the series and field ids this process remembers.

        For whoever replaced the tables under it — a backup restore empties and refills
        `history_series` and `history_field` with a plain DELETE/INSERT, and an id remembered
        from before points a new sample at a row that is now another series, or none.
        """
        self._forget_series()


# ── Module-level helpers ──────────────────────────────────────────────────────

def create(
    db_config: dict | None = None,
    *,
    sqlite_path: str,
) -> 'HistoryStore':
    """Build a HistoryStore backed by a connector from *db_config*.

    When *db_config* is None or has no ``driver``, a SQLite connector is used
    at *sqlite_path*.
    """
    connector = get_connector(db_config or None, default_sqlite_path=sqlite_path)
    return HistoryStore(connector)


def _load_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}
