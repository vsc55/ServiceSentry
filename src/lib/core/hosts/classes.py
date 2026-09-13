#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que el panel pregunta sobre las clases de dispositivo.

Esto es la capa de encima de :mod:`lib.core.hosts.stores.types`, y son preguntas, no filas:
«¿cuáles hay y cómo se dicen?» (:func:`catalog`), «¿esa palabra señala a alguna?»
(:func:`known`, :func:`uid_for`), «¿la lleva alguien puesta?» (:func:`in_use`, :func:`usage`) y
«créala si no está» (:func:`ensure`), que es lo que usa cada importación.

**Separado del almacén a propósito.** Quien las dibuja o las trae de fuera —las rutas, el
proveedor de Freshservice, la página— no tiene nada que decirle a la tabla: le hace una pregunta
al panel. Estaban en el mismo archivo, y leer el catálogo obligaba a importar el módulo que
define columnas e índices.

Todas toman *wa* —el panel— y no un almacén: el almacén cuelga de él (`_host_types_store`) y
puede no estar, que es un panel a medio montar. Ninguna revienta por eso; contestan lo que se
puede contestar sin tabla, que casi siempre es «nada» y nunca es un error.
"""

from lib.core.hosts.stores.types import (           # noqa: F401  (parte de esta API)
    DESC_MAX, FALLBACK_ICON, ID_MAX, NAME_MAX, SEED, HostTypesStore, slug,
)


def _store(wa):
    return getattr(wa, '_host_types_store', None)


def catalog(wa) -> list:
    """Todas las clases que este panel conoce, en el orden en que se ofrecen.

    Cada una trae **o** `label_key` **o** `label`, nunca las dos: la sembrada la dice el catálogo
    de idiomas —se lee «Servidor» o «Server» según quién mire— y la escrita aquí lleva su texto
    tal cual. Quien la dibuja no tiene que saber de cuál de las dos se trata; sólo mirar cuál de
    los dos campos viene.
    """
    almacen = _store(wa)
    if almacen is None:
        return []
    try:
        filas = almacen.list()
    except Exception:  # pylint: disable=broad-except
        # La pantalla de dispositivos no se queda sin cargar porque una tabla no esté: lo que se
        # pierde es el desplegable de clases, y lo que queda es «sin clasificar», que es una
        # respuesta válida para todo.
        return []
    fuera = []
    for f in filas:
        una = {'uid': f['uid'], 'slug': f['slug'], 'icon': f['icon'] or FALLBACK_ICON,
               'source': f['source'], 'external_id': f['external_id'],
               'description': f['description'],
               'created_at': f['created_at'], 'updated_at': f['updated_at'],
               'updated_by': f['updated_by']}
        if f['label_key']:
            una['label_key'] = f['label_key']
            # Y de dónde sale su descripción, por lo mismo que el nombre: escrita en la columna
            # se congelaría en el idioma de quien creó la base. La columna se queda vacía —nadie
            # de esta casa ha escrito nada— y quien dibuja mira primero la columna y luego ésta.
            una['desc_key'] = f['label_key'] + '_desc'
        else:
            una['label'] = f['name']
        fuera.append(una)
    return fuera


def uid_for(wa, ident: str) -> str:
    """El `uid` de una clase, venga dicho como venga: por `uid` o por su nombre corto.

    **Un solo sitio.** Lo que entra por aquí es lo que sale de la tabla de pistas del importador
    —`switch`, `ups`— y lo que ya viene resuelto de una vuelta anterior; los dos tienen que acabar
    en la columna escritos igual, porque lo que el almacén de dispositivos acepta es el `uid` y
    nada más. Vacío cuando no hay tal clase, que es «sin clasificar»: una palabra que no señala a
    ninguna fila no se puede guardar, y la pantalla ya sabe enseñar un dispositivo sin clase.
    """
    almacen = _store(wa)
    texto = str(ident or '').strip()
    if almacen is None or not texto:
        return ''
    try:
        if almacen.get(texto) is not None:
            return texto
        fila = almacen.by_slug(texto)
    except Exception:  # pylint: disable=broad-except
        return ''
    return str((fila or {}).get('uid') or '')


def known(wa, type_id: str) -> bool:
    """Si algo declara esa clase. Lo que mantiene fuera de la columna una palabra inventada."""
    almacen = _store(wa)
    if almacen is None or not str(type_id or ''):
        return False
    return almacen.get(str(type_id)) is not None


def ensure(wa, name: str, *, icon: str = '', source: str = '', external_id: str = '',
           actor: str = '') -> str:
    """El identificador de la clase que corresponde a esa de fuera, creándola si no existe.

    Lo usa la importación: un tipo de activo de allí que no se parece a ninguna clase de aquí
    **se crea**, con el nombre que trae el origen, en vez de dejar el dispositivo sin clasificar.

    **Se busca por el identificador de allí antes que por el nombre**, y en ese orden por una
    razón que se ve sola: renombrar una clase aquí es algo que la pantalla invita a hacer, y
    buscando sólo por el nombre la siguiente importación crearía una segunda con el nombre de
    allí — con la mitad de los dispositivos nuevos yendo a una y la mitad a la otra.

    Buscar antes de crear tampoco es una optimización: sin ello, dos importaciones seguidas
    dejarían dos clases iguales.
    """
    almacen = _store(wa)
    if almacen is None:
        return ''
    atada = almacen.by_external(source, external_id)
    if atada is not None:
        # **Y se refresca desde allí.** Es la otra mitad de que su nombre no se pueda teclear
        # aquí: una clase que nadie puede corregir y que tampoco se actualiza sola es un nombre
        # congelado sin dueño. Sólo si cambió — una escritura por cada importación llenaría el
        # registro de cambios que no cambian nada.
        nombre = str(name or '').strip()[:NAME_MAX]
        if nombre and nombre != atada['name']:
            almacen.update(atada['uid'], nombre, atada['icon'], actor=actor)
        return atada['uid']
    if not slug(name):
        return ''
    ya = almacen.by_name(name)
    if ya is not None:
        # Se escribió a mano y se llama igual: se **adopta** en vez de crear una copia, que es lo
        # mismo que hacen las empresas y los dispositivos. Desde ahora la mantiene ese origen, y
        # renombrarla ya no la duplica.
        if external_id and not str(ya.get('external_id') or ''):
            almacen.link(ya['uid'], source, external_id, actor=actor)
        return ya['uid']
    return almacen.create(name, icon, source=source, external_id=external_id,
                          actor=actor) or ''


def in_use(wa, type_id: str) -> int:
    """Cuántos dispositivos llevan puesta esa clase.

    Se pregunta antes de borrarla: quitar una clase que llevan cuarenta máquinas las deja con una
    palabra que ya no significa nada —ni se traduce, ni se filtra, ni se dibuja con su icono— y
    eso no se puede deshacer volviendo a crearla con el mismo nombre, porque lo que se perdió fue
    saber que había que hacerlo.

    **Una consulta, no la flota entera.** Esto lo preguntaba recorriendo todos los dispositivos en
    Python, y con tres mil máquinas eran ciento diez milisegundos — por clase. Quitar doce eran
    doce lecturas completas de la flota, y lo que se veía era una pantalla que tardaba.
    """
    almacen = getattr(wa, '_hosts_store', None)
    if almacen is None:
        return 0
    try:
        return almacen.count_with_device_type(str(type_id or ''))
    except Exception:  # pylint: disable=broad-except
        return 0


def usage(wa) -> dict:
    """``{clase: cuántos}`` de una consulta agrupada.

    La pantalla de clases enseña cuántos lleva cada una — es lo que contesta «¿esta la usa
    alguien?» sin tener que ir a probar a borrarla.
    """
    almacen = getattr(wa, '_hosts_store', None)
    if almacen is None:
        return {}
    try:
        return almacen.count_by_device_type()
    except Exception:  # pylint: disable=broad-except
        return {}
