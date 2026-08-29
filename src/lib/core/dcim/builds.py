#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las plantillas: lo que de verdad se compra, entre el catálogo y el inventario.

El catálogo dice **lo que un fabricante vende** y el inventario dice **qué caja hay en el U 12**.
Entre los dos falta el escalón en el que se trabaja de verdad: un R740 es un chasis, y lo que se
pide veinte veces es ese chasis *con* doce DIMM, ocho SSD y una controladora. Eso no figura en el
catálogo de nadie —no lo vende nadie, lo componemos nosotros— y hoy se teclea veinte veces.

Dos tablas y una regla:

* **``dc_build``** es la plantilla: un nombre nuestro, el modelo de chasis del catálogo, el rol y
  las medidas. Un nombre nuestro y no el del fabricante, porque «Servidor CPD estándar 2024» es
  lo que alguien dice en una reunión y «PowerEdge R740» es lo que dice una factura.
* **``dc_build_part``** es lo que lleva puesto, con **la misma forma que ``dc_part``** — clase,
  bahía, modelo, tamaño, cantidad. La misma forma a propósito: crear un equipo desde una
  plantilla es copiarlas.

**Y se estampa, no se enlaza.** Al crear el equipo las piezas se COPIAN, y desde ese momento son
suyas. Si el equipo las leyera de su plantilla, el día que alguien saca un disco averiado no
habría dónde decirlo —el equipo no tendría piezas propias que corregir— y editar la plantilla
reescribiría la ficha de veinte máquinas que nadie ha tocado. Que una máquina se separe de su
plantilla no es un error que haya que impedir: es un hecho sobre esa máquina, y :func:`compare`
existe para poder leerlo.

Lo único que sobrevive del vínculo es ``dc_item.build_uid``: de qué plantilla **nació**. Sin él,
«cuáles son los veinte del estándar de 2024» no tiene respuesta; con él la tiene aunque a tres
les hayan cambiado los discos.
"""

from __future__ import annotations

import json

from lib.core.dcim.revisions import RevisionStore
from lib.core.dcim.store import (FACES, ITEM_ROLES, PART_KINDS, Rows,
                                 clean_port_list)
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_BUILD = TableSpec(
    name='dc_build',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        # Único: dos plantillas con el mismo nombre son dos estándares que nadie puede
        # distinguir al elegir en un desplegable, que es el único sitio donde se eligen.
        Column('name',        'TEXT', nullable=False, default="''", unique=True),
        # El chasis, en `dc_type`. Opcional: una plantilla de algo que no está en ninguna
        # biblioteca sigue siendo una plantilla, y exigir el modelo obligaría a inventarse una
        # fila de catálogo para poder describir lo que ya se tiene.
        Column('type_uid',    'TEXT', nullable=False, default="''"),
        # Qué CLASE de equipo sale de aquí — uno de `ITEM_ROLES`. Se copia al equipo, que es
        # donde decide si cuenta como «sin vigilar» o no tiene nada que vigilar.
        Column('role',        'TEXT', nullable=False, default="''"),
        # Las medidas, cuando la plantilla las fija. `0` = las del modelo del catálogo, que es
        # lo normal: un R740 mide lo que mide se le ponga lo que se le ponga.
        #
        # En DÉCIMAS de U, como el catálogo (`dc_type.u_tenths`): hay chasis de 0,5 U y en
        # enteros no se pueden escribir. Una sola unidad en los dos sitios — convivir con las
        # dos sería tener dos respuestas a la misma pregunta y verlas discrepar.
        Column('u_tenths',    'INTEGER', nullable=False, default='0'),
        Column('depth_mm',    'INTEGER', nullable=False, default='0'),
        Column('face',        'TEXT', nullable=False, default="'full'"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
        # Las últimas declaradas, para que aparecer sobre una tabla llena sea un `ADD COLUMN`.
        #
        # Lo que no cabe en un renglón: por qué se eligió ese chasis, qué se probó y no valía,
        # con quién se negoció. Hoy eso vive en un correo, y el correo se pierde antes que el
        # servidor.
        Column('notes',       'TEXT', nullable=False, default="''"),
        # Desde cuándo y hasta cuándo se compra así. Un estándar tiene vigencia: sin las dos
        # fechas, «¿esto todavía se pide?» solo lo sabe quien estaba.
        Column('valid_from',  'TEXT', nullable=False, default="''"),
        Column('valid_to',    'TEXT', nullable=False, default="''"),
        # Con qué sistema sale. Forma parte del estándar tanto como los discos, y es lo primero
        # que se pregunta al recibir una máquina nueva. Apunta a `dc_platform` y no es texto:
        # cuatro formas de escribir «Debian 12» son cuatro respuestas a una pregunta que solo
        # tiene una.
        Column('platform_uid', 'TEXT', nullable=False, default="''"),
        # Cómo comparte U esto. Un patch panel de 0,5 U son dos por U; una bandeja de Raspberry
        # las divide en ocho. Es del ESTÁNDAR: lo que no es del estándar es *cuál* de las partes
        # toma cada caja —una va arriba y la otra abajo—, y eso se queda en el equipo.
        Column('u_slots',     'INTEGER', nullable=False, default='1'),
        Column('u_slot_span', 'INTEGER', nullable=False, default='1'),
        Column('u_split',     'TEXT', nullable=False, default="'width'"),
        # ── Lo copiado del catálogo, que desde el momento en que se copia es SUYO ──────
        #
        # Se leía en vivo de `dc_type`, y eso deja la plantilla enseñando huecos el día que
        # alguien retira ese modelo o reimporta la biblioteca —que regenera los `uid`—. Ninguna
        # de las dos es una equivocación: la biblioteca se reimporta cada pocos meses y un
        # modelo se retira porque ya no se compra.
        #
        # Es la misma regla que rige entre una plantilla y un equipo, un escalón más arriba.
        Column('manufacturer', 'TEXT', nullable=False, default="''"),
        Column('model',       'TEXT', nullable=False, default="''"),
        Column('full_depth',  'INTEGER', nullable=False, default='1'),
        Column('airflow',     'TEXT', nullable=False, default="''"),
        Column('power_type',  'TEXT', nullable=False, default="''"),
        # Los puertos y lo que no cabe en columnas —las seis fechas de la vida del equipo, y lo
        # que diga el esquema de su clase—, como JSON igual que en el catálogo.
        Column('ports',       'TEXT', nullable=False, default="'{}'"),
        # Y cómo se llama cada boca, en el orden que las tiene el equipo. Contar contesta «¿es
        # bastante switch?»; nombrar contesta «¿cuál es esta?», que es la que se hace con el
        # latiguillo en la mano.
        Column('port_list',   'TEXT', nullable=False, default="'{}'"),
        Column('extra',       'TEXT', nullable=False, default="'{}'"),
        # Copiadas de verdad y con nombre nuevo: apuntar al fichero del catálogo es una bomba de
        # relojería —borrar cualquiera de los dos se lleva el fichero y el otro enseña un hueco
        # sin que nada haya fallado—. Mismo agujero que ya se tapó al clonar un modelo.
        Column('front_image', 'TEXT', nullable=False, default="''"),
        Column('rear_image',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_build_name', ('name',)),),
    # La caja de texto que fue durante media rama. Nunca salió de aquí, pero sí está en la base
    # de datos de quien la lleva probando, y renombrar conserva lo que hubiera escrito.
    renames={'platform': 'platform_uid'},
)

_BUILD_PART = TableSpec(
    name='dc_build_part',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('build_uid',   'TEXT', nullable=False),
        Column('kind',        'TEXT', nullable=False, default="'other'"),
        Column('slot',        'TEXT', nullable=False, default="''"),
        # El modelo del catálogo, cuando lo hay. Con él la plantilla dice «este DIMM» y no «32
        # GB», que es la diferencia entre poder pedir el recambio y tener que buscarlo.
        Column('type_uid',    'TEXT', nullable=False, default="''"),
        Column('model',       'TEXT', nullable=False, default="''"),
        Column('size',        'TEXT', nullable=False, default="''"),
        Column('qty',         'INTEGER', nullable=False, default='1'),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
        # La marca, por lo mismo que en `dc_part`: la misma forma, porque estampar es copiar.
        Column('brand',       'TEXT', nullable=False, default="''"),
        # Cuántas piezas trae una unidad: un kit de dos módulos son dos zócalos ocupados.
        Column('kit_qty',     'INTEGER', nullable=False, default='1'),
        # Dentro de la caja o colgando de ella. `''` = dentro, que es lo que eran todos los que
        # ya había: una columna nueva no puede inventarse el valor.
        #
        # Aparte de `kind` porque son dos preguntas: `kind` dice QUÉ es —un disco, una fuente,
        # un adaptador— y esto dice DÓNDE está. En un solo campo habría que inventar
        # `nic_externa` el día que alguien enchufe una tarjeta de red por USB, que es el caso
        # que trajo esto.
        Column('mount',       'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_build_part_build', ('build_uid',)),),
)

#: Dónde vive una pieza. `''` es dentro y no está aquí a propósito: lo que no se dice es lo
#: normal, y una lista que incluya el vacío invita a escribirlo.
MOUNTS = ('external',)

SCHEMAS = (_BUILD, _BUILD_PART)

#: Lo que se copia de una pieza de plantilla a una pieza de equipo. El número de serie NO está,
#: y es el punto entero: eso es lo único que tiene esa unidad y ninguna otra.
STAMPED = ('kind', 'slot', 'type_uid', 'brand', 'model', 'size', 'qty', 'kit_qty',
           'description', 'mount')


def _norm(v) -> str:
    return ' '.join(str(v or '').split()).lower()


def _clave(p: dict) -> tuple:
    """Por qué se considera «la misma pieza» al comparar.

    Clase, marca, modelo y tamaño — y no la bahía. Nadie llena las bahías de veinte máquinas en
    el mismo orden, y comparar por bahía convertiría «los mismos ocho discos en otro sitio» en
    dieciséis diferencias. Lo que se pregunta es *qué lleva*, no *dónde*.
    """
    return (str(p.get('kind') or 'other'), _norm(p.get('brand')),
            _norm(p.get('model')), _norm(p.get('size')))


def compare(wanted, have) -> list[dict]:
    """Lo que un equipo lleva contra lo que su plantilla decía. Una lista de diferencias.

    Una sola lista y no dos —«de más» y «de menos»— porque casi siempre son la misma línea vista
    dos veces: cambiar un disco de 4 TB por uno de 8 sale como un renglón que falta y otro que
    sobra, y separarlos en dos tablas obliga a leerlas las dos para entender que fue un cambio.

    Cada fila trae ``want`` y ``have``, y ``diff`` con el signo. Ninguna de las dos partes es «el
    error»: la diferencia ES el dato, igual que en el contraste de cableado y en el de consumo.
    """
    def _sumar(filas):
        out = {}
        for p in filas or ():
            # Piezas y no cajas: dos kits de dos y cuatro módulos sueltos son la misma memoria
            # puesta, y decir que difieren sería contestar la pregunta del pedido a quien está
            # mirando lo que lleva la máquina.
            try:
                n = int(p.get('qty') or 1) * max(1, int(p.get('kit_qty') or 1))
            except (TypeError, ValueError):
                n = 1
            k = _clave(p)
            fila = out.setdefault(k, {'kind': k[0], 'brand': str(p.get('brand') or ''),
                                      'model': str(p.get('model') or ''),
                                      'size': str(p.get('size') or ''), 'qty': 0})
            fila['qty'] += max(0, n)
        return out

    quiere, tiene = _sumar(wanted), _sumar(have)
    salida = []
    for k in sorted(set(quiere) | set(tiene)):
        a, b = quiere.get(k), tiene.get(k)
        n_a, n_b = (a or {}).get('qty', 0), (b or {}).get('qty', 0)
        if n_a == n_b:
            continue
        base = a or b
        salida.append({'kind': base['kind'], 'brand': base['brand'], 'model': base['model'],
                       'size': base['size'], 'want': n_a, 'have': n_b, 'diff': n_b - n_a})
    return salida


#: Cuánto vale cada unidad respecto de la más pequeña de su familia. Dos familias y dos
#: factores porque así se venden y así se leen: la memoria en potencias de dos —un DIMM de 32 GB
#: son 32·2³⁰ bytes— y el almacenamiento en potencias de diez, que es lo que dice la caja de un
#: disco. Elegir uno solo haría que la mitad de los totales no coincidieran con ninguna etiqueta.
_UNIDADES = {
    'memoria': {'MB': 1, 'GB': 1024, 'TB': 1024 * 1024},
    'disco': {'MB': 1, 'GB': 1000, 'TB': 1000 * 1000, 'PB': 1000 * 1000 * 1000},
    'vatios': {'W': 1, 'KW': 1000},
}

#: Qué clase de pieza suma en qué familia.
_FAMILIA = {'memory': 'memoria', 'disk': 'disco', 'ssd': 'disco', 'psu': 'vatios'}


def magnitude(texto: str) -> tuple:
    """«1.92 TB» partido en ``(1.92, 'TB')``. ``(0, '')`` si no se puede leer.

    Se lee y no se exige: el tamaño es texto libre a propósito —«media altura» es un tamaño
    válido para algunas cosas— así que lo que no sea un número con su unidad no se suma, y quien
    llame dirá cuántos se quedaron fuera en vez de fingir que no había ninguno.
    """
    crudo = str(texto or '').strip().replace(',', '.')
    if not crudo:
        return 0.0, ''
    numero, resto = '', ''
    for i, c in enumerate(crudo):
        if c.isdigit() or c == '.':
            numero += c
        else:
            resto = crudo[i:].strip()
            break
    if not numero:
        # Sin número no hay magnitud: «media altura» no es «0 de media altura», y devolver una
        # unidad de nada invita a que alguien la sume.
        return 0.0, ''
    try:
        return float(numero), resto.upper()
    except ValueError:
        return 0.0, ''


def _piezas(p: dict) -> int:
    """Cuántas piezas son de verdad: las cajas por lo que trae cada una."""
    try:
        return max(1, int(p.get('qty') or 1)) * max(1, int(p.get('kit_qty') or 1))
    except (TypeError, ValueError):
        return 1


def summary(parts, models=None, base=None) -> dict:
    """Qué máquina sale de estas piezas. Las cuentas que se hacen a mano al leer la lista.

    *models* es ``{type_uid: fila del catálogo}``: de ahí salen los núcleos de una CPU y los
    puertos de una tarjeta, que están en la ficha del modelo y no en la pieza.

    *base* es el chasis. Sus puertos de red llevan contados en el catálogo desde el primer día y
    nadie los miraba: un mini-PC con dos en la placa decía tener solo la tarjeta que alguien le
    añadió. Y de él sale por dónde come, que no es lo mismo que si come.

    Lo que no se pudo leer va en ``unknown`` con su cuenta. Un total al que le faltan tres discos
    y no lo dice es peor que no dar el total: se cree.
    """
    models = models or {}
    fuera = {'memory_gb': 0.0, 'storage_tb': 0.0, 'cpus': 0, 'cores': 0, 'threads': 0,
             'psu': [], 'net': [], 'unknown': 0, 'power_type': '', 'powered': None}
    vatios, redes = {}, {}
    # Lo que trae el chasis de serie, antes de que nadie le ponga nada.
    if base:
        fuera['power_type'] = str(base.get('power_type') or '')
        fuera['powered'] = str(base.get('is_powered', 1)) not in ('0', 'False', 'false')
        puertos = base.get('ports')
        if isinstance(puertos, str):
            # Estrecho a propósito: un `except Exception` aquí se tragó un `NameError` por un
            # import que faltaba, y el resultado fue que los puertos del chasis no se contaban
            # **sin ningún error en ninguna parte**. Lo que se espera de un JSON mal escrito es
            # esto y nada más.
            try:
                puertos = json.loads(puertos or '{}')
            except (TypeError, ValueError):
                puertos = {}
        for tipo, cuantos in ((puertos or {}).get('interfaces') or {}).items():
            try:
                n = int(cuantos or 0)
            except (TypeError, ValueError):
                continue
            # El tipo de la biblioteca —`1000base-t`— es el nombre estándar del puerto y ya dice
            # su velocidad: traducirlo a «1 Gbps» sería una tabla que se queda corta y que
            # además borra el detalle que distingue un `1000base-t` de un `1000base-x`.
            etiqueta = str(tipo or '').strip() or '?'
            if n:
                redes[etiqueta] = redes.get(etiqueta, 0) + n
    for p in (parts or ()):
        clase = str(p.get('kind') or '')
        n = _piezas(p)
        extra = ((models.get(str(p.get('type_uid') or '')) or {}).get('extra')) or {}
        if clase == 'cpu':
            fuera['cpus'] += n
            for campo in ('cores', 'threads'):
                try:
                    fuera[campo] += int(float(extra.get(campo) or 0)) * n
                except (TypeError, ValueError):
                    pass
            if not extra.get('cores'):
                fuera['unknown'] += n
            continue
        if clase == 'nic':
            try:
                puertos = int(float(extra.get('ports') or 0)) * n
            except (TypeError, ValueError):
                puertos = 0
            velocidad = str(extra.get('link_speed') or '')
            if puertos and velocidad:
                redes[velocidad] = redes.get(velocidad, 0) + puertos
            else:
                fuera['unknown'] += n
            continue
        familia = _FAMILIA.get(clase)
        if not familia:
            continue
        valor, unidad = magnitude(p.get('size'))
        factor = _UNIDADES[familia].get(unidad)
        if not valor or not factor:
            fuera['unknown'] += n
            continue
        if familia == 'memoria':
            fuera['memory_gb'] += valor * factor * n / _UNIDADES['memoria']['GB']
        elif familia == 'disco':
            fuera['storage_tb'] += valor * factor * n / _UNIDADES['disco']['TB']
        else:
            etiqueta = '%g %s' % (valor, unidad)
            vatios[etiqueta] = vatios.get(etiqueta, 0) + n
    fuera['memory_gb'] = round(fuera['memory_gb'], 2)
    fuera['storage_tb'] = round(fuera['storage_tb'], 2)
    fuera['psu'] = [{'size': k, 'qty': v} for k, v in sorted(vatios.items())]
    fuera['net'] = [{'speed': k, 'ports': v} for k, v in sorted(redes.items())]
    return fuera


def _leido(fila):
    """Una plantilla tal y como se lee: con los dos JSON ya abiertos.

    Las columnas guardan texto y quien las lea espera diccionarios. Deserializar aquí —en el
    único sitio por el que salen— es lo que evita que una de las cinco pantallas se olvide y
    reciba una cadena donde busca una clave.
    """
    if not fila:
        return fila
    fuera = dict(fila)
    for campo in ('ports', 'port_list', 'extra'):
        v = fuera.get(campo)
        if isinstance(v, str):
            try:
                fuera[campo] = json.loads(v or '{}') or {}
            except (TypeError, ValueError):
                fuera[campo] = {}
        elif not isinstance(v, dict):
            fuera[campo] = {}
    return fuera


class BuildStore:
    """Las plantillas y lo que llevan puesto.

    Un store sobre dos tablas y no dos stores, por lo mismo que el inventario: la pregunta que se
    hace siempre —«qué es esta plantilla»— cruza las dos, y quien tuviera los dos stores sería
    quien las junta.
    """

    #: De qué clase de cosa son estas versiones, dentro de `dc_rev`. La tabla es compartida con
    #: el catálogo y con el documento de perfiles: una segunda sería un segundo almacén haciendo
    #: estas mismas cuatro cosas.
    SCOPE = 'build'

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self.builds = Rows(db, _BUILD)
        self.parts = Rows(db, _BUILD_PART)
        self.builds.bootstrap()
        self.parts.bootstrap()
        # Qué decía antes, y quién la cambió. Una plantilla es un dato compartido: de ella
        # salieron veinte máquinas, y corregirla es cambiar el estándar con el que se compra.
        self.revs = RevisionStore(db)

    # ── Las plantillas ────────────────────────────────────────────────────────

    def list(self) -> list[dict]:
        """Todas, por nombre. Ordenadas aquí y no en SQL: son decenas, no miles."""
        return sorted((_leido(b) for b in self.builds.list()),
                      key=lambda b: str(b.get('name') or '').lower())

    def get(self, uid: str) -> dict | None:
        return _leido(self.builds.get(uid))

    def by_name(self, name: str) -> dict | None:
        filas = self.builds.list('name = ?', (' '.join(str(name or '').split()),))
        return filas[0] if filas else None

    def create(self, row: dict, *, actor: str = '') -> str:
        """Una plantilla nueva. ``''`` si no tiene nombre o ya hay otra que se llama igual."""
        datos = self._fields(row)
        nombre = datos.get('name') or ''
        if not nombre or self.by_name(nombre):
            return ''
        uid = self.builds.create(datos, actor=actor)
        self._apuntar(uid, 'create', actor)
        return uid

    def update(self, uid: str, row: dict, *, actor: str = '', accion: str = 'edit') -> bool:
        datos = self._fields(row, parcial=True)
        if not datos:
            return True             # una petición que no dice nada no es una que falló
        nombre = datos.get('name')
        if nombre is not None:
            if not nombre:
                return False
            otra = self.by_name(nombre)
            if otra and str(otra.get('uid')) != str(uid):
                return False
        if not self.builds.update(uid, datos, actor=actor):
            return False
        self._apuntar(uid, accion or 'edit', actor)
        return True

    #: Lo que una plantilla se trae de su modelo, y con qué se reconoce que **no** lo tiene.
    #: `full_depth` no está: su columna vale 1 por defecto y 1 es también un fondo completo de
    #: verdad, así que un hueco y un dato son la misma cifra. Se rellena solo cuando la fila
    #: entera está sin estampar, que es lo único que se puede afirmar mirándola.
    _HOLES = (('manufacturer', ''), ('model', ''), ('airflow', ''), ('power_type', ''),
              ('front_image', ''), ('rear_image', ''), ('u_tenths', 0),
              ('ports', {}), ('port_list', {}), ('extra', {}))

    def stamp_missing(self, cat, var_dir: str = '', media_dir: str = '') -> int:
        """Copiar en las plantillas viejas lo que su modelo del catálogo dice. Cuántas tocó.

        Las columnas son nuevas y ``ADD COLUMN`` no puede inventarse el valor, así que las
        plantillas escritas antes las traían vacías: la ficha dejó de enseñar las fotos, las
        medidas y los puertos el día que dejó de leerlos en vivo del catálogo. Un arreglo que
        se lleva por delante lo que ya había escrito es peor que el fallo, y nadie vuelve a
        elegir el modelo de treinta plantillas para recuperar una foto.

        **Solo huecos.** Lo que ya tiene un valor es de la plantilla y puede haberse corregido
        a mano desde entonces; pisarlo sería deshacer esa corrección sin decirlo. Y solo si su
        modelo sigue existiendo: de uno retirado no hay nada que copiar, y la plantilla se
        queda como está, que es justo lo que se buscaba al copiar.

        Una vez: en cuanto no queda ninguna con huecos, no hay nada que recorrer.
        """
        if cat is None:
            return 0
        n = 0
        for fila in self.list():
            tipo = str(fila.get('type_uid') or '')
            if not tipo:
                continue
            faltan = {c for c, vacio in self._HOLES if (fila.get(c) or vacio) == vacio}
            if not faltan:
                continue
            modelo = cat.get(tipo)
            if not modelo:
                continue
            # Y solo lo que el modelo tiene de verdad: copiar su vacío sobre nuestro vacío no
            # es rellenar un hueco, pero SÍ cuenta como escritura — y entonces «una vez» son
            # todas, y la fila se toca en cada arranque para no cambiar nada.
            datos = {c: modelo[c] for c in faltan if modelo.get(c)}
            # Sin fabricante la fila no se estampó nunca, y entonces su fondo tampoco: es la
            # única vez que se puede distinguir «completo» de «nadie lo dijo».
            if not str(fila.get('manufacturer') or '') and 'full_depth' in modelo:
                datos['full_depth'] = modelo['full_depth']
            # Y las imágenes, copiadas de verdad y con nombre nuevo: apuntar al fichero del
            # catálogo deja a los dos borrables y a uno enseñando un hueco.
            if {'front_image', 'rear_image'} & faltan:
                copias = cat.copy_images(modelo, var_dir, media_dir)
                datos.update({c: v for c, v in copias.items() if c in faltan})
            if not datos:
                continue
            self.builds.update(str(fila['uid']), self._fields(datos, parcial=True))
            n += 1
        return n

    def delete(self, uid: str) -> bool:
        """Quitarla, con sus piezas.

        Los equipos que salieron de ella **no** se tocan, y ni siquiera se les quita el
        ``build_uid``: nacieron de esto, y eso siguió siendo verdad después de que alguien
        retirara el estándar. Lo que se pierde es poder mirar de qué constaba, y por eso la
        pantalla dice cuántos hay antes de preguntar.
        """
        if not self.get(uid):
            return False
        self._db.execute(f'DELETE FROM {self.parts._sql_table} WHERE build_uid = ?',
                         (str(uid),))
        self.builds.delete(uid)
        # Y su historial: las versiones de algo que ya no existe no contestan a nada y se
        # quedarían para siempre.
        self.revs.forget(str(uid), scope=self.SCOPE)
        return True

    def clone(self, uid: str, name: str, *, actor: str = '') -> str:
        """Copiar una entera, con sus piezas. ``''`` si no hay original o el nombre está cogido.

        Casi ninguna plantilla se escribe desde cero: la del año que viene es la de este año con
        otros discos, y teclear quince líneas para cambiar una es el trabajo que no se hace — y
        entonces se edita la vieja, que es como se pierde de qué constaban los veinte de antes.
        """
        origen = self.get(uid)
        if not origen:
            return ''
        datos = {k: origen.get(k) for k in
                 ('type_uid', 'role', 'u_tenths', 'depth_mm', 'face', 'description', 'notes',
                  'platform_uid', 'u_slots', 'u_slot_span', 'u_split')}
        datos['name'] = self._free_name(name, origen.get('name') or '')
        nuevo = self.create(datos, actor=actor)
        if not nuevo:
            return ''
        for p in self.parts_of(uid):
            fila = {k: p.get(k) for k in STAMPED}
            fila['build_uid'] = nuevo
            self.parts.create(fila, actor=actor)
        return nuevo

    def _free_name(self, asked: str, base: str) -> str:
        """Un nombre libre para una copia.

        Un nombre que GENERÓ el panel no es un nombre que alguien tecleó: rechazar el segundo
        clon por repetido sería rechazar algo que nadie eligió, y obligar a inventarse un nombre
        antes de poder mirar de qué constaba la copia. Lo tecleado, en cambio, sigue sin poder
        repetirse — eso lo decide `create`, que es donde se comprueba.
        """
        nombre = " ".join(str(asked or "").split())
        if nombre:
            return nombre
        raiz = " ".join(str(base or "").split()) or "?"
        for n in range(2, 100):
            intento = f"{raiz} ({n})"
            if not self.by_name(intento):
                return intento
        return ""

    # ── Lo que llevan puesto ──────────────────────────────────────────────────

    def platform_counts(self) -> dict:
        """Cuántas plantillas apuntan a cada plataforma, por su uid.

        De una consulta: la pantalla las enseña todas con su cuenta, y preguntarlo una a una
        serían treinta consultas para pintar treinta renglones. Y es lo que hace que retirar una
        pueda negarse con un motivo en vez de dejar plantillas apuntando a nada.
        """
        rows = self._db.fetchall(
            f'SELECT platform_uid, COUNT(*) FROM {self.builds._sql_table} '
            "WHERE platform_uid <> '' GROUP BY platform_uid") or ()
        return {str(r[0]): int(r[1]) for r in rows}

    def parts_of(self, build_uid: str) -> list[dict]:
        """Las piezas de una, por clase y bahía — que es como se buscan: «los discos», «la 3»."""
        filas = self.parts.list('build_uid = ?', (str(build_uid or ''),))
        return sorted(filas, key=lambda p: (str(p.get('kind') or ''), str(p.get('slot') or '')))

    def counts(self) -> dict:
        """Cuántas piezas tiene cada plantilla, de una vez.

        La lista las enseña todas con su cuenta, y pedirla plantilla a plantilla serían treinta
        consultas para pintar treinta renglones.
        """
        out = {}
        for p in self.parts.list():
            uid = str(p.get('build_uid') or '')
            out[uid] = out.get(uid, 0) + 1
        return out

    def part_add(self, build_uid: str, row: dict, *, actor: str = '') -> str:
        if not self.get(build_uid):
            return ''
        datos = self._part_fields(row)
        datos['build_uid'] = str(build_uid)
        uid = self.parts.create(datos, actor=actor)
        # Poner un disco a la plantilla es cambiar el estándar tanto como cambiarle el nombre, y
        # es lo que alguien va a querer mirar: «¿desde cuándo lleva ocho?».
        self._apuntar(str(build_uid), 'part_add', actor)
        return uid

    def part_update(self, uid: str, row: dict, *, actor: str = '') -> bool:
        pieza = self.parts.get(uid)
        if not self.parts.update(uid, self._part_fields(row, parcial=True), actor=actor):
            return False
        self._apuntar(str((pieza or {}).get('build_uid') or ''), 'part_edit', actor)
        return True

    def part_delete(self, uid: str, *, actor: str = '') -> bool:
        pieza = self.parts.get(uid)
        if not self.parts.delete(uid):
            return False
        self._apuntar(str((pieza or {}).get('build_uid') or ''), 'part_drop', actor)
        return True

    def _apuntar(self, uid: str, accion: str, actor: str) -> None:
        """Apuntar cómo quedó la plantilla, con sus piezas.

        **Con sus piezas**: media plantilla es media respuesta, y la pregunta que se le hace a un
        historial de estos es casi siempre «¿de qué constaba?». Van en una clave aparte para no
        confundirlas con las columnas al comparar dos versiones — la diferencia habla de campos,
        y una lista no es un campo que cambió: es doce.

        Nada de esto puede tumbar la escritura que lo produjo: guardar la plantilla es lo que
        alguien pidió, y apuntarlo es un favor que se le hace después.
        """
        if not uid:
            return
        fila = self.get(uid)
        if not fila:
            return
        try:
            self.revs.keep(uid, dict(fila, parts=self.parts_of(uid)),
                           action=accion, actor=actor, scope=self.SCOPE)
        except Exception:                       # pylint: disable=broad-except
            pass

    # ── Y lo que sale de ellas ────────────────────────────────────────────────

    def stamp(self, build_uid: str) -> list[dict]:
        """Las piezas que hay que copiar a un equipo recién creado desde esta plantilla.

        Sin ``uid``, sin ``build_uid`` y sin número de serie: lo que se devuelve son piezas de un
        equipo, no piezas de una plantilla, y quien las guarde les pondrá lo suyo.
        """
        return [{k: p.get(k) for k in STAMPED} for p in self.parts_of(build_uid)]

    # ── Lo que una petición puede decir ───────────────────────────────────────

    @staticmethod
    def _fields(row: dict, parcial: bool = False) -> dict:
        """Campo a campo y no en bloque: una petición que trajera ``uid`` o ``created_at``
        escribiría cosas que no son suyas, y una lista de lo aceptado es la única defensa que no
        se olvida de un campo nuevo el día que la tabla crezca."""
        data = row or {}
        fuera = {}
        if 'name' in data or not parcial:
            fuera['name'] = ' '.join(str(data.get('name') or '').split())
        for campo in ('type_uid', 'description', 'notes', 'valid_from', 'valid_to',
                      'platform_uid', 'u_split',
                      # Lo copiado del catálogo, que desde entonces es de la plantilla y se
                      # corrige aquí: el catálogo puede desaparecer entero.
                      'manufacturer', 'model', 'airflow', 'power_type',
                      'front_image', 'rear_image'):
            if campo in data or not parcial:
                fuera[campo] = str(data.get(campo) or '').strip()
        if 'full_depth' in data or not parcial:
            fuera['full_depth'] = 0 if str(data.get('full_depth')) in ('0', 'False',
                                                                      'false') else 1
        # Los dos JSON, serializados en el ÚNICO sitio que escribe: hacerlo en cada llamada
        # sería hacerlo en cinco, y el que se olvide guarda un diccionario donde va texto.
        for campo in ('ports', 'port_list', 'extra'):
            if campo in data or not parcial:
                v = data.get(campo)
                if campo == 'port_list':
                    v = clean_port_list(v)
                fuera[campo] = json.dumps(v if isinstance(v, dict) else {}, sort_keys=True)
        if 'role' in data or not parcial:
            rol = str(data.get('role') or '').strip()
            fuera['role'] = rol if rol in ITEM_ROLES else ''
        if 'face' in data or not parcial:
            cara = str(data.get('face') or '').strip()
            fuera['face'] = cara if cara in FACES else 'full'
        # El suelo no es el mismo para todos: una altura sin poner es `0` y significa «la del
        # modelo», pero un U dividido en cero partes no significa nada — es uno.
        for campo, suelo in (('u_tenths', 0), ('depth_mm', 0),
                             ('u_slots', 1), ('u_slot_span', 1)):
            if campo in data or not parcial:
                try:
                    fuera[campo] = max(suelo, int(float(data.get(campo) or suelo)))
                except (TypeError, ValueError):
                    fuera[campo] = suelo
        return fuera

    @staticmethod
    def _part_fields(row: dict, parcial: bool = False) -> dict:
        data = row or {}
        fuera = {}
        if 'kind' in data or not parcial:
            clase = str(data.get('kind') or '').strip()
            fuera['kind'] = clase if clase in PART_KINDS else 'other'
        for campo in ('slot', 'type_uid', 'brand', 'model', 'size', 'description'):
            if campo in data or not parcial:
                fuera[campo] = str(data.get(campo) or '').strip()
        if 'mount' in data or not parcial:
            m = str(data.get('mount') or '').strip()
            fuera['mount'] = m if m in MOUNTS else ''
        for campo in ('qty', 'kit_qty'):
            if campo in data or not parcial:
                try:
                    fuera[campo] = max(1, int(float(data.get(campo) or 1)))
                except (TypeError, ValueError):
                    fuera[campo] = 1
        return fuera
