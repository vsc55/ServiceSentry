#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Llevarse modelos y plantillas de una instalación a otra: un fichero y las dos puertas.

Lo que se escribe a mano en el catálogo —el armario que montó el electricista, el mini-PC que no
publica nadie— y sobre todo **las plantillas**, que son horas de decisiones, no salían de aquí. La
biblioteca se reimporta en un minuto; un estándar de compra escrito por alguien, no: se vuelve a
teclear, y quien lo teclea otra vez lo teclea distinto.

**Un solo sobre para las dos cosas**, y no un fichero por tabla, porque cuando alguien se lleva
una plantilla se quiere llevar los modelos que la explican — y dos ficheros que hay que importar
en el orden correcto son un orden que alguien va a equivocar.

**Sin `uid` ninguno.** Un identificador es de la base de datos que lo acuñó y en la de al lado no
significa nada: lo que viaja es lo que una persona reconoce —fabricante y modelo, el nombre de la
plantilla— y con eso se busca al llegar. Es la misma razón por la que una plantilla lleva sus
medidas copiadas y no un enlace al catálogo: lo que se copia sobrevive al viaje.

**Nada se pisa.** Un modelo que ya está se salta, y una plantilla cuyo nombre ya existe también.
Importar es traer lo que falta, no sustituir lo que hay — y lo saltado se **cuenta y se dice**,
que es la diferencia entre «no ha hecho nada» y «ya lo tenías».
"""

from __future__ import annotations

from datetime import datetime, timezone

#: Qué es este fichero. Va dentro y no en el nombre: un `.json` renombrado sigue siendo lo que
#: sea que fuera, y lo que decide si esto se puede importar es lo que dice, no cómo se llama.
KIND = 'servicesentry.dcim'

#: La versión del **formato**, no la del panel. Sube cuando cambie lo que significa una clave, no
#: cuando se añada una: quien lea la 1 tiene que poder leer un fichero con campos de más.
VERSION = 1

#: Lo que viaja de un modelo del catálogo. Las imágenes no: son ficheros de este disco, pesan más
#: que todo lo demás junto, y un modelo sin su foto sigue siendo el modelo. Tampoco `source` ni
#: `imported_at` —de dónde salió allí no dice de dónde sale aquí— ni el `kind_set`, que es una
#: corrección de alguien sobre su propio catálogo.
TYPE_FIELDS = ('manufacturer', 'model', 'tree', 'kind', 'u_tenths', 'full_depth', 'part_number',
               'airflow', 'subdevice', 'is_powered', 'description', 'size', 'url', 'kit_qty',
               'power_type', 'ports', 'port_list', 'extra')

#: Y de una plantilla. Con lo estampado del catálogo dentro —fabricante, modelo, medidas— porque
#: es lo que la hace independiente: al llegar puede no haber ningún modelo que se le parezca y la
#: plantilla sigue diciendo de qué chasis es.
BUILD_FIELDS = ('name', 'role', 'face', 'u_tenths', 'depth_mm', 'u_slots', 'u_slot_span',
                'u_split', 'manufacturer', 'model', 'airflow', 'power_type', 'full_depth',
                'description', 'notes', 'valid_from', 'valid_to', 'ports', 'port_list', 'extra')

#: Lo que lleva puesto. Sin `type_uid`: apunta a una fila del catálogo de allí, y aquí es un
#: identificador que no existe. La marca y el modelo van copiados, que es lo que se lee.
PART_FIELDS = ('kind', 'slot', 'mount', 'brand', 'model', 'size', 'qty', 'kit_qty',
               'description')


def _pick(fila, campos) -> dict:
    """Los campos que viajan, sin los vacíos.

    Sin los vacíos porque un fichero que dice `"airflow": ""` afirma que ese modelo no tiene
    ventilación declarada, y lo que pasa es que nadie la escribió. Al importar, un campo ausente
    y uno vacío acaban igual; en el fichero, uno se lee y el otro no.
    """
    fuera = {}
    for c in campos:
        v = (fila or {}).get(c)
        if v in (None, '', {}, []):
            continue
        fuera[c] = v
    return fuera


def export_doc(cat=None, builds=None, *, type_uids=(), build_uids=(), plats=None) -> dict:
    """El sobre con lo que se pida. Lo que no exista se salta sin decir nada: quien pidió veinte
    modelos y borró uno mientras tanto quiere los diecinueve, no un error.
    """
    doc = {'kind': KIND, 'version': VERSION,
           'exported_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'types': [], 'builds': []}
    for uid in (type_uids or ()):
        fila = cat.get(str(uid)) if cat else None
        if fila:
            doc['types'].append(_pick(fila, TYPE_FIELDS))
    nombres = {}
    for p in (plats.list() if plats else ()):
        nombres[str(p.get('uid') or '')] = str(p.get('name') or '')
    for uid in (build_uids or ()):
        fila = builds.get(str(uid)) if builds else None
        if not fila:
            continue
        uno = _pick(fila, BUILD_FIELDS)
        # La plataforma **por su nombre**: «Windows 10 Pro» significa lo mismo en las dos casas y
        # su uid no significa nada en ninguna de las dos salvo la suya.
        plat = nombres.get(str(fila.get('platform_uid') or ''), '')
        if plat:
            uno['platform'] = plat
        piezas = [_pick(p, PART_FIELDS) for p in (builds.parts_of(str(uid)) or ())]
        if piezas:
            uno['parts'] = piezas
        doc['builds'].append(uno)
    return doc


def problems(doc) -> list:
    """Por qué este fichero no se puede importar. Vacío si se puede.

    Se mira **lo que dice ser**: un JSON cualquiera con una lista `builds` dentro no es un export
    de este panel, y tragárselo es escribir filas a partir de lo que alguien tenía en el
    portapapeles.
    """
    if not isinstance(doc, dict):
        return ['not an object']
    fuera = []
    if str(doc.get('kind') or '') != KIND:
        fuera.append(f'not a {KIND} file')
    try:
        v = int(doc.get('version') or 0)
    except (TypeError, ValueError):
        v = 0
    if v < 1 or v > VERSION:
        fuera.append(f'unsupported format version: {doc.get("version")!r}')
    for clave in ('types', 'builds'):
        if clave in doc and not isinstance(doc[clave], list):
            fuera.append(f'{clave}: not a list')
    return fuera


def import_doc(doc, cat=None, builds=None, *, plats=None, actor: str = '',
               source: str = 'import') -> dict:
    """Traer lo que falte. Cuántos entraron, cuántos ya estaban y qué no se pudo resolver.

    El orden importa y por eso está aquí y no en quien llama: **primero los modelos**, para que
    una plantilla que llegue detrás encuentre en casa el chasis del que habla.
    """
    cuenta = {'types_new': 0, 'types_skipped': 0, 'builds_new': 0, 'builds_skipped': 0,
              'parts': 0, 'platforms_missing': []}
    if problems(doc):
        return cuenta
    for fila in (doc.get('types') or ()):
        if not isinstance(fila, dict):
            continue
        maker = str(fila.get('manufacturer') or '').strip()
        modelo = str(fila.get('model') or '').strip()
        if not maker or not modelo:
            continue
        # Ya estaba: se salta y se cuenta. Pisarlo sería deshacer una corrección que alguien hizo
        # aquí sobre su propio catálogo, y eso no se puede decir que fuera «importar».
        if cat and cat.by_key(maker, modelo):
            cuenta['types_skipped'] += 1
            continue
        if cat and cat.create(_pick(fila, TYPE_FIELDS), source=source, actor=actor):
            cuenta['types_new'] += 1
    por_nombre = {}
    for p in (plats.list() if plats else ()):
        por_nombre[str(p.get('name') or '').strip().lower()] = str(p.get('uid') or '')
    for fila in (doc.get('builds') or ()):
        if not isinstance(fila, dict):
            continue
        datos = _pick(fila, BUILD_FIELDS)
        if not str(datos.get('name') or '').strip():
            continue
        plat = str(fila.get('platform') or '').strip()
        if plat:
            uid_plat = por_nombre.get(plat.lower(), '')
            if uid_plat:
                datos['platform_uid'] = uid_plat
            # No se inventa: dar de alta una plataforma es escribir en otro sitio a espaldas de
            # quien pidió importar. Se dice cuál falta, que es lo que deja arreglarlo en un clic.
            elif plat not in cuenta['platforms_missing']:
                cuenta['platforms_missing'].append(plat)
        uid = builds.create(datos, actor=actor) if builds else ''
        if not uid:
            cuenta['builds_skipped'] += 1
            continue
        cuenta['builds_new'] += 1
        for pieza in (fila.get('parts') or ()):
            if isinstance(pieza, dict) and builds.part_add(uid, _pick(pieza, PART_FIELDS),
                                                           actor=actor):
                cuenta['parts'] += 1
    return cuenta
