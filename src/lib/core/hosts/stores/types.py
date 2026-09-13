#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La tabla `host_type`: qué clases de dispositivo existen. **Todas en la base de datos.**

La lista vivía escrita aquí al lado: servidor, hipervisor, NAS, conmutador, enrutador,
cortafuegos, SAI, impresora, cámara, puesto y «otro». Once palabras que valían para casi todo y
no para lo siguiente — un punto de acceso, un teléfono IP, una controladora de riego— y que sólo
se podían cambiar con un commit. Ahora son filas: se añaden, se corrigen, se les cambia el icono
y se quitan desde el panel, las once de siempre incluidas.

Del código queda **una sola cosa**, y se usa una sola vez: :data:`SEED` — las once con las que se
siembra la tabla **el día que se crea**. A partir de ahí es un dato como cualquier otro. Si
alguien borra «Cámara» porque aquí no hay ninguna, no vuelve sola en el siguiente arranque: lo
que se sembró se sembró, y volver a ponerlas es un botón que se pulsa a propósito.

**Y siguen traduciéndose.** Una clase sembrada lleva `label_key` —la clave del catálogo de
idiomas— y por eso se dice «Servidor» o «Server» según quién mire. Una que escribe una persona
lleva su nombre tal cual, sin traducir: es un dato de esta casa, como el nombre de una empresa, y
ningún fichero de idiomas puede saberlo. Las dos son filas de la misma tabla y las dos se editan
igual; lo único que cambia es de dónde sale la palabra.

**Se relaciona por `uid`**, como todo lo demás de este esquema: es lo que guarda la columna
`device_type` de cada dispositivo. El nombre corto —`slug`, sacado del nombre y fijo de por vida—
se queda para leer y para atar una clase sembrada con su clave de idioma, pero no apunta a nada.

Una base anterior se migra al arrancar, y **con la flota**: reescribir esta tabla sin reescribir
`hosts.device_type` deja a todos los dispositivos señalando a clases que ya no existen — sin
error, sin aviso, y con el filtro devolviendo cero.

Aquí está lo que se **lee y se escribe**. Lo que las pantallas y los proveedores preguntan sobre
las clases —«¿cuáles hay?», «¿la lleva alguien puesta?», «créala si no está»— vive en
:mod:`lib.core.hosts.classes`, encima de esto.
"""

from __future__ import annotations

import re
import unicodedata
import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore
from lib.util.entity_audit import utc_now_iso as _now

_TYPE = TableSpec(
    name='host_type',
    columns=(
        # **Por aquí se relaciona.** Un `uid` como el de todo lo demás de este esquema —`org`,
        # `hosts`, `dc_item`—, y es lo que guarda `hosts.device_type`. Antes esa columna llevaba
        # el nombre corto, que funcionaba pero dejaba el esquema con dos maneras de señalar: una
        # por `uid` y otra por una cadena sacada de un nombre.
        Column('uid',        'TEXT', primary_key=True),
        # Cómo se llama. En una clase sembrada es el nombre de reserva —en inglés— y lo que se
        # enseña sale de `label_key`; en una escrita por una persona es lo que se enseña.
        Column('name',       'TEXT', nullable=False, default="''", unique=True),
        # La clave del catálogo de idiomas, cuando la tiene. Es lo que hace que las once de
        # siempre se digan en el idioma de quien mira después de mudarse a una tabla: sin esto,
        # sembrarlas obligaba a elegir un idioma al crear la base y dejarlo así para siempre.
        Column('label_key',  'TEXT', nullable=False, default="''"),
        # Un icono de Bootstrap Icons (`bi-…`). Vacío = el genérico, que es el que lleva un
        # dispositivo sin clasificar y una respuesta perfectamente válida.
        Column('icon',       'TEXT', nullable=False, default="''"),
        # De dónde salió, cuando no la escribió una persona: `seed` las de la siembra, y el
        # identificador del proveedor las que trae una importación. Se guarda para poder
        # contestar «¿y esto quién lo ha metido?», que es lo que se pregunta al ver una clase
        # que nadie recuerda.
        # **Qué sistema de FUERA la mantiene.** Vacío es lo normal y quiere decir «de esta
        # casa» — tanto lo que escribió una persona como lo que puso la siembra, porque la
        # siembra no es un sistema de fuera: es lo que trae cualquier instalación. Marcarla aquí
        # obligaba a excluirla a mano en cada sitio que preguntara «¿esto lo mantiene otro?», y
        # cada uno era una ocasión de olvidarlo. Cuál vino de la siembra lo dice `label_key`,
        # que sólo la llevan ellas.
        Column('source',     'TEXT', nullable=False, default="''"),
        # Y CUÁL de las suyas es, cuando viene de un proveedor. Dos columnas y no una por lo
        # mismo que en `org` y en `hosts`: son dos preguntas. «¿Esto lo mantiene otro?» decide si
        # se puede teclear encima, y «¿cuál de las suyas es?» es lo único que permite volver a
        # importar sin duplicar — por el NOMBRE no se puede, porque renombrar la clase aquí
        # dejaría a la siguiente importación creando una segunda con el nombre de allí.
        #
        # La última, para que una base que ya existe la reciba por ADD COLUMN.
        Column('external_id', 'TEXT', nullable=False, default="''"),
        # En qué orden se ofrecen. Un número y no el alfabeto: la lista va de lo más común a lo
        # menos, y ordenada por nombre «Cámara» sale antes que «Servidor» en un desplegable que
        # se usa cuarenta veces al día para decir «servidor».
        Column('sort',       'INTEGER', nullable=False, default='100'),
        # El nombre corto, sacado del nombre y fijo de por vida. **Ya no relaciona nada** — para
        # eso está `uid`— pero se queda por dos razones: es lo que ata una clase sembrada con su
        # clave de idioma, y es lo que hace legible una fila en una consulta a mano.
        Column('slug',       'TEXT', nullable=False, default="''"),
        # Para qué es esta clase. Un renglón que se escribe una vez y contesta «¿y ésta en qué se
        # diferencia de la de al lado?», que es lo que se pregunta al encontrar dos parecidas
        # meses después.
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_host_type_name', ('name',)),
             Index('idx_host_type_slug', ('slug',))),
)

_T = _TYPE.name

_COLS = ('uid', 'name', 'label_key', 'icon', 'source', 'sort',
         'created_at', 'updated_at', 'updated_by', 'external_id', 'slug', 'description')
_SELECT = ', '.join(_COLS)

#: Lo que cabe en un identificador. Se corta ahí porque lo que hay detrás es una columna y un
#: filtro, no porque un nombre largo moleste: el nombre entero se guarda aparte y es el que se ve.
ID_MAX = 40

#: Y lo que cabe en un nombre. Generoso: lo escribe una persona y lo lee otra.
NAME_MAX = 60

#: Y en la descripción, que es un renglón y no un artículo: lo que se lee al lado del nombre para
#: saber en qué se diferencia de la de al lado.
DESC_MAX = 200

#: **Las once de siempre, y lo único que queda de ellas en el código.** Se usan el día que se
#: crea la tabla y cuando alguien pulsa «añadir las básicas»; a partir de ahí la tabla manda.
#:
#: `label_key` es lo que las mantiene traducidas, y `name` el nombre de reserva por si un día no
#: existiera esa clave — una fila sin ninguna de las dos es una entrada en blanco en un
#: desplegable.
SEED: tuple[dict, ...] = (
    {'id': 'server',      'icon': 'bi-hdd-rack',          'name': 'Server'},
    {'id': 'workstation', 'icon': 'bi-pc-display',        'name': 'Workstation'},
    {'id': 'nas',         'icon': 'bi-hdd-stack',         'name': 'NAS / Storage'},
    {'id': 'hypervisor',  'icon': 'bi-boxes',             'name': 'Hypervisor'},
    {'id': 'switch',      'icon': 'bi-ethernet',          'name': 'Switch'},
    {'id': 'router',      'icon': 'bi-router',            'name': 'Router'},
    {'id': 'firewall',    'icon': 'bi-shield-lock',       'name': 'Firewall'},
    {'id': 'ups',         'icon': 'bi-battery-charging',  'name': 'UPS'},
    {'id': 'printer',     'icon': 'bi-printer',           'name': 'Printer'},
    {'id': 'camera',      'icon': 'bi-camera-video',      'name': 'Camera'},
    {'id': 'other',       'icon': 'bi-hdd-network',       'name': 'Other'},
)

#: El icono que lleva un dispositivo sin clasificar. No es una clase — es la respuesta cuando no
#: hay ninguna — así que no está en la tabla y no se puede borrar.
FALLBACK_ICON = 'bi-hdd-network'

_NO_PALABRA = re.compile(r'[^0-9a-z]+')


def slug(name: str) -> str:
    """El identificador de una clase, sacado de su nombre.

    Sin acentos, en minúsculas y con guiones bajos: «Punto de acceso» → `punto_de_acceso`. Va a
    una columna de texto que se compara y se filtra, y las tres cosas que se quitan aquí son las
    tres que hacen que dos escrituras del mismo nombre no casen.

    Devuelve ``''`` cuando no queda nada — un nombre de sólo signos no es un nombre.
    """
    plano = unicodedata.normalize('NFKD', str(name or '').strip().lower())
    plano = ''.join(c for c in plano if not unicodedata.combining(c))
    return _NO_PALABRA.sub('_', plano).strip('_')[:ID_MAX]


class HostTypesStore(BaseStore):
    """Las clases de dispositivo. Todas: las de la siembra y las que añada esta casa."""

    _TABLE = _T

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        # **Sembrar SÓLO al crear la tabla**, y por eso se pregunta antes de tocarla. Hacerlo
        # «cuando esté vacía» tiene otro significado, y es el que no se quiere: quien borre las
        # once porque en su casa no hay ninguna se las encontraría de vuelta en el siguiente
        # arranque, sin que nada lo explicara. Lo que se sembró, sembrado está; volver a ponerlas
        # es un botón que se pulsa a propósito.
        #
        # Y «nueva» es que no haya NADA de donde venir, ni la tabla ni la que una migración a
        # medias dejó apartada. Mirando sólo la primera, una base que se quedó a medio rehacer
        # —la vieja a un lado, la nueva sin crear— se sembraría encima: once clases de fábrica
        # donde había las de esa casa, y la flota señalando a ninguna de ellas.
        nueva = not self._existe() and not self._hay_apartada()
        # La forma vieja —clave primaria `id` con el nombre corto dentro— hay que rehacerla antes
        # de reconciliar: cambiar una clave primaria no es añadir una columna, y `reconcile_table`
        # no lo intenta. Con esto delante, una base de esos días entra en la forma nueva sola.
        if not nueva:
            self._migrar_a_uid()
        self._db.reconcile_table(_TYPE)
        from lib.core.constants import SYSTEM_USER                # noqa: PLC0415
        if nueva:
            self.seed_missing(actor=SYSTEM_USER)
        else:
            self._limpiar_siembra(SYSTEM_USER)
            self._reparar_vinculos()

    def _migrar_a_uid(self) -> None:
        """Pasar la tabla de relacionar por el nombre corto a relacionar por `uid`.

        Y **con la flota**: `hosts.device_type` guardaba ese nombre corto, así que rehacer la
        tabla sin reescribirlo deja a todos los dispositivos señalando a clases que ya no existen
        —sin error, con el filtro de clase en cero y con la columna en blanco—.

        Tres cosas que costaron una base de verdad cada una:

        **Se reconoce por la columna vieja, no por la forma entera.** La primera versión pedía
        «con `id` y sin `uid`», y eso la desactiva para siempre en cuanto algo añada las columnas
        antes: `reconcile_table` sabe añadirlas —no sabe cambiar una clave primaria—, así que una
        base que arrancó con el esquema a medio escribir se quedó con `uid`, `slug` y
        `description` puestas y a NULL, y con `id` todavía de clave. Mientras `id` esté ahí hay
        trabajo que hacer, y el `uid` que ya tenga una fila se respeta.

        **El DDL no entra en la transacción.** El conector lo manda por su propia conexión, así
        que un fallo a mitad no deshace el renombrado: lo que queda es la tabla vieja apartada y
        la nueva vacía, y al siguiente arranque no hay ningún `id` que mirar — las once clases
        desaparecidas y la flota sin clasificar. Por eso la tabla apartada **es** el otro sitio
        donde se busca trabajo: encontrarla es una vuelta que se quedó a medias, y se termina.

        **Los índices siguen a la tabla renombrada.** `idx_host_type_name` se va con ella, y
        entonces crear la tabla nueva falla por un nombre ocupado por una tabla que está a punto
        de desaparecer. Se quitan antes de pedirla.
        """
        viejo = f'{_T}_old'
        try:
            cols = set(self._db.list_columns(_T))
            if 'id' in cols:
                origen = _T
            elif self._db.table_exists(viejo):
                origen = viejo          # una vuelta anterior se quedó a medias
            else:
                return
        except Exception:  # pylint: disable=broad-except
            return
        import uuid as _uuid                                       # noqa: PLC0415
        try:
            # De las columnas que puede que no estén —una tabla de la forma original no tiene
            # `uid` ni `slug`— se lee lo que haya, y de lo que no hay se pone el hueco.
            hay = set(self._db.list_columns(origen))
            campos = ['id', 'name', 'label_key', 'icon', 'source', 'sort', 'created_at',
                      'updated_at', 'updated_by', 'external_id']
            campos.append('uid' if 'uid' in hay else "'' AS uid")
            campos.append('slug' if 'slug' in hay else "'' AS slug")
            campos.append('description' if 'description' in hay else "'' AS description")
            filas, nuevos = [], {}
            for r in self._db.fetchall(f'SELECT {", ".join(campos)} FROM {origen}') or []:
                corto = str(r[0] or '')
                ident = str(r[10] or '') or str(_uuid.uuid4())
                if corto:
                    nuevos[corto] = ident
                filas.append((ident, r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                              str(r[11] or '') or corto, r[12] or ''))
            if origen == _T:
                self._db.execute_ddl(f'ALTER TABLE {_T} RENAME TO {viejo}')
            # Los índices se quitan SIEMPRE, y no sólo al apartar la tabla: siguen a la
            # renombrada, así que `idx_host_type_name` se queda colgando de la apartada y el
            # nombre sigue ocupado. Al retomar una vuelta a medias eso es lo único que hay
            # delante, y hacía fallar la reconciliación **al arrancar el panel** — que es un
            # panel que no abre. Se vuelven a crear en la reconciliación de aquí abajo.
            for idx in _TYPE.indexes:
                try:
                    self._db.execute_ddl(f'DROP INDEX IF EXISTS {idx.name}')
                except Exception:  # pylint: disable=broad-except
                    pass
            self._db.reconcile_table(_TYPE)
            # Los datos sí van juntos: las clases y la flota que las lleva puesta, o ninguna de
            # las dos cosas. Media migración es una flota apuntando a la nada.
            # Puede no haber flota que reescribir: una base donde las clases existen y los
            # dispositivos todavía no. Preguntarlo es lo que distingue «no hay nada que hacer» de
            # «ha fallado» — sin esto, el `UPDATE` contra una tabla que no está tira la
            # transacción entera y lo que queda es la tabla nueva VACÍA: las once clases
            # desaparecidas por no tener dispositivos a los que avisar.
            try:
                hay_flota = bool(self._db.table_exists('hosts'))
            except Exception:  # pylint: disable=broad-except
                hay_flota = False
            with self._db.transaction():
                for fila in filas:
                    self._db.execute(
                        f'INSERT INTO {_T} ({_SELECT}) '
                        f'VALUES ({", ".join("?" * len(_COLS))})', fila)
                for corto, nuevo in (nuevos.items() if hay_flota else ()):
                    self._db.execute(
                        'UPDATE hosts SET device_type = ? WHERE device_type = ?',
                        (nuevo, corto))
            self._db.execute_ddl(f'DROP TABLE {viejo}')
        except Exception:  # pylint: disable=broad-except
            # Lo que quede apartado se retoma al siguiente arranque, que es para lo que se mira
            # la tabla vieja arriba. Lo que no puede pasar es que el panel no abra por esto.
            pass

    def _limpiar_siembra(self, system_user: str) -> None:
        """Quitarle el origen falso a lo que se sembró antes de que esto se decidiera.

        Durante un rato la siembra se marcó con `source='seed'` y `updated_by='seed'`. Lo primero
        es mentira —`source` dice qué sistema de FUERA mantiene la fila, y la siembra no es uno— y
        lo segundo es un usuario que no existe en ninguna otra tabla de este panel.

        Se arregla aquí y no con un aviso porque lo que deja es una chapa «seed» en cada fila y una
        entrada «seed» en el filtro de orígenes, para siempre, en toda instalación que se creara
        esos días.

        **Son dos correcciones y no una.** Escritas como una sola —`SET source='', updated_by=?
        WHERE source='seed' OR updated_by='seed'`— cada fila que cumpliera media condición perdía
        las dos columnas: una clase de la siembra que Freshservice hubiera **adoptado** lleva su
        origen puesto y conserva el `updated_by='seed'` de cuando se sembró, y salía de aquí con el
        origen en blanco y el `external_id` a solas — vinculada a nada, y sin manera de saber a qué
        lo estaba. Visto en una base de verdad. Cada columna mira su propio valor.
        """
        try:
            with self._db.transaction():
                self._db.execute(
                    f"UPDATE {_T} SET source = '' WHERE source = 'seed'")
                self._db.execute(
                    f"UPDATE {_T} SET updated_by = ? WHERE updated_by = 'seed'",
                    (system_user,))
        except Exception:  # pylint: disable=broad-except
            # Una base a la que no se puede escribir no puede impedir abrir el panel: lo que
            # queda es la chapa de más, que es feo y no rompe nada.
            pass

    def _reparar_vinculos(self) -> None:
        """Devolverle el origen a las filas que se quedaron con el `external_id` a solas.

        Un vínculo son **dos datos** —de qué sistema y cuál de los suyos— y :meth:`link` escribe
        siempre los dos. Media fila no la escribe nada: es lo que dejó la limpieza de la siembra
        cuando reseteaba la fila entera por cumplir media condición. Y no se nota mirando: la
        clase sigue ahí, con su nombre y su icono, sólo que ya no la mantiene nadie — la siguiente
        importación crea una segunda al lado, y ésa se lleva los dispositivos nuevos.

        **Sólo cuando no hay que adivinar**, que es cuando hay un único proveedor de dispositivos
        declarado: entonces ese `external_id` no puede ser de otro. Con dos o más se deja como
        está y se vuelve a vincular desde la pantalla, que es una decisión de quien mira y no una
        que se pueda tomar por probabilidad.
        """
        try:
            filas = self._db.fetchall(
                f"SELECT uid FROM {_T} WHERE external_id <> '' AND source = ''") or []
            if not filas:
                return
            from lib.core.hosts import actions as host_actions     # noqa: PLC0415
            fuentes = sorted(host_actions.sources().keys())
            if len(fuentes) != 1:
                return
            with self._db.transaction():
                self._db.execute(
                    f"UPDATE {_T} SET source = ? WHERE external_id <> '' AND source = ''",
                    (fuentes[0],))
        except Exception:  # pylint: disable=broad-except
            # Como la limpieza de al lado: una base que no se deja escribir no puede impedir que
            # el panel abra. Lo que queda es una clase que hay que volver a vincular a mano.
            pass

    def _hay_apartada(self) -> bool:
        """Si una migración a medias dejó la tabla vieja a un lado. Es de donde se retoma."""
        try:
            return bool(self._db.table_exists(f'{_T}_old'))
        except Exception:  # pylint: disable=broad-except
            return False

    def _existe(self) -> bool:
        try:
            return bool(self._db.table_exists(_T))
        except Exception:  # pylint: disable=broad-except
            # Un conector que no sepa contestar no puede hacer que se siembre encima de lo que ya
            # hay: se trata como «ya existía», que es lo que no escribe nada.
            return True

    # ── Leer ────────────────────────────────────────────────────────────────
    def _fila(self, r) -> dict:
        return {'uid': r[0], 'name': r[1] or '', 'label_key': r[2] or '', 'icon': r[3] or '',
                'source': r[4] or '', 'sort': int(r[5] or 0),
                'created_at': r[6] or '', 'updated_at': r[7] or '', 'updated_by': r[8] or '',
                'external_id': r[9] or '', 'slug': r[10] or '', 'description': r[11] or ''}

    def list(self) -> list[dict]:
        """Todas, en el orden en que se ofrecen: por `sort` y, a igualdad, por nombre."""
        return [self._fila(r) for r in self._db.fetchall(
            f'SELECT {_SELECT} FROM {_T} ORDER BY sort, name')]

    def get(self, type_id: str) -> dict | None:
        """Una, por su `uid`.

        Una consulta y no un recorrido de :meth:`list`: esto lo llama el almacén de dispositivos
        en CADA guardado para decidir si la clase existe, y una importación de cuatrocientas
        máquinas serían cuatrocientos recorridos de la tabla entera para mirar una fila.
        """
        ident = str(type_id or '')
        if not ident:
            return None
        fila = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE uid = ?', (ident,))
        return self._fila(fila) if fila else None

    def by_name(self, name: str) -> dict | None:
        """Por su nombre, sin distinguir mayúsculas ni acentos.

        Comparando por el identificador y no por el texto: «Punto de Acceso» y «punto de acceso»
        son la misma clase, y dos filas para eso son dos entradas en el desplegable que hacen
        dudar a quien elige.
        """
        buscado = slug(name)
        if not buscado:
            return None
        fila = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE slug = ?', (buscado,))
        if fila:
            return self._fila(fila)
        # Y por el nombre aplanado, que no es lo mismo: una clase sembrada se llama «NAS /
        # Storage» y su `slug` es `nas`, así que quien teclee ese nombre no choca por slug.
        for otra in self.list():
            if slug(otra['name']) == buscado:
                return otra
        return None

    # ── Escribir ────────────────────────────────────────────────────────────
    def by_slug(self, slug_id: str) -> dict | None:
        """Una, por su nombre corto. Para quien sólo tiene eso: la tabla de pistas del importador
        contesta `switch` o `ups`, que son los de la semilla y lo único de ellas escrito en el
        código."""
        corto = str(slug_id or '').strip()
        if not corto:
            return None
        fila = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE slug = ?', (corto,))
        return self._fila(fila) if fila else None

    def by_external(self, source: str, external_id: str) -> dict | None:
        """La clase atada a ESA de fuera, si alguna lo está.

        Es lo que se mira antes del nombre al importar: renombrar la clase aquí —que es algo que
        se puede hacer y que la pantalla invita a hacer— dejaría a la siguiente importación
        creando una segunda con el nombre de allí, y la mitad de los dispositivos nuevos irían a
        una y la mitad a la otra.
        """
        src, ext = str(source or '').strip(), str(external_id or '').strip()
        if not src or not ext:
            return None
        fila = self._db.fetchone(
            f'SELECT {_SELECT} FROM {_T} WHERE source = ? AND external_id = ?', (src, ext))
        return self._fila(fila) if fila else None

    def link(self, type_id: str, source: str, external_id: str, *, actor: str = '') -> bool:
        """Atar una clase de aquí a una de fuera — o soltarla, con las dos vacías.

        Lo que esto cambia es de quién se entiende que es la clase, no lo que dice: el nombre y
        el icono se quedan como están. Atar una que ya se escribió a mano es exactamente lo que
        evita el duplicado la próxima vez que alguien importe.
        """
        ident = str(type_id or '')
        if self.get(ident) is None:
            return False
        src, ext = str(source or '').strip(), str(external_id or '').strip()
        otra = self.by_external(src, ext)
        if otra is not None and otra['uid'] != ident:
            return False          # esa de fuera ya es de otra de aquí
        try:
            with self._db.transaction():
                self._db.execute(
                    f'UPDATE {_T} SET source=?, external_id=?, updated_at=?, updated_by=? '
                    'WHERE uid=?', (src, ext, _now(), actor or '', ident))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def create(self, name: str, icon: str = '', *, source: str = '', label_key: str = '',
               sort: int = 100, slug_id: str = '', external_id: str = '',
               description: str = '', uid: str = '', actor: str = '') -> str | None:
        """Crear una clase. Devuelve su identificador, o ``None`` si el nombre no vale o ya está.

        ``None`` y no una excepción porque quien llama son tres: una pantalla, que enseña el
        motivo; una importación, que sigue con las otras treinta y nueve; y la siembra, que pasa
        de largo por lo que ya esté.

        *slug_id* sólo lo usa la siembra, para que las once conserven el nombre corto con el que
        se las nombra en el catálogo de idiomas. No es por donde se relaciona nada: eso es *uid*.
        """
        nombre = str(name or '').strip()[:NAME_MAX]
        corto = str(slug_id or '').strip() or slug(nombre)
        if not nombre or not corto:
            return None
        if self.by_name(nombre) is not None:
            return None
        ident = str(uid or '') or str(uuid.uuid4())
        ahora = _now()
        try:
            with self._db.transaction():
                self._db.execute(
                    f'INSERT INTO {_T} ({_SELECT}) VALUES ({", ".join("?" * len(_COLS))})',
                    (ident, nombre, str(label_key or ''), str(icon or ''), str(source or ''),
                     int(sort or 100), ahora, ahora, actor or '',
                     str(external_id or ''), corto, str(description or '')[:DESC_MAX]))
            return ident
        except Exception:  # pylint: disable=broad-except
            return None

    def update(self, type_id: str, name: str, icon: str = '', *, keep_label: bool = False,
               description: str | None = None, actor: str = '') -> bool:
        """Renombrarla o cambiarle el icono. **El identificador no se toca.**

        Es lo que guarda cada dispositivo de esa clase: cambiarlo los dejaría a todos apuntando a
        una clase que ya no existe, sin error y con el filtro devolviendo cero.

        Y renombrar una clase sembrada **le quita la clave de idioma**, que es lo correcto: desde
        el momento en que alguien la llama «Servidor de producción», eso es lo que quiere leer —
        no lo que diga un catálogo de traducciones sobre una palabra que ya no usa.

        *keep_label* es para cuando el nombre NO cambia: cambiarle el icono a «Servidor» no es
        renombrarlo, y quitarle la clave ahí lo dejaría en inglés para quien mira en castellano
        por haber elegido otro dibujo.
        """
        ident = str(type_id or '')
        nombre = str(name or '').strip()[:NAME_MAX]
        ya = self.get(ident) if ident else None
        if not nombre or ya is None:
            return False
        choca = self.by_name(nombre)
        if choca is not None and choca['uid'] != ident:
            return False
        desc = ya['description'] if description is None else str(description or '')[:DESC_MAX]
        try:
            with self._db.transaction():
                self._db.execute(
                    f'UPDATE {_T} SET name=?, label_key=?, icon=?, description=?, '
                    'updated_at=?, updated_by=? WHERE uid=?',
                    (nombre, ya['label_key'] if keep_label else '', str(icon or ''), desc,
                     _now(), actor or '', ident))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, type_id: str) -> bool:
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (str(type_id or ''),))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def seed_missing(self, *, actor: str = '') -> list:
        """Poner las básicas que falten. Devuelve **los nombres cortos** que ha añadido.

        Los cortos y no los `uid`: esto va a un aviso en pantalla y a una línea de auditoría, y
        las dos cosas las lee una persona. «camera, printer» dice lo que ha pasado; dos uuids
        dicen que han pasado dos cosas.

        Las que YA están no se tocan — ni el nombre, ni el icono, ni el orden: alguien las habrá
        corregido, y una «siembra» que pisa lo corregido es una que deshace trabajo cada vez que
        se pulsa. Las que se borraron a propósito vuelven, que es exactamente para lo que existe
        el botón.

        *actor* es quien queda escrito en la fila. Al crear la tabla es `system`, que es el
        usuario que este panel tiene para lo que hace él solo; desde el botón, quien lo pulsó.
        """
        puestas = []
        for orden, spec in enumerate(SEED, start=1):
            # **Sin `source`.** Lo que se siembra es de esta casa desde el primer día: se puede
            # renombrar, se le puede cambiar el icono y se puede quitar, que es justo lo que un
            # origen impide.
            ident = self.create(spec['name'], spec['icon'],
                                label_key=f"host_type_{spec['id']}", sort=orden * 10,
                                slug_id=spec['id'], actor=actor)
            if ident:
                puestas.append(spec['id'])
        return puestas
