#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que un paquete puede ofrecer EN la pantalla de Dispositivos.

Dar de alta un dispositivo a mano es lo que esa pantalla sabe hacer sola. Traerlo de donde ya
está escrito —el sistema de tickets, el inventario de otro— es **otra manera de que aparezca un
dispositivo**, no otra cosa; por eso su botón cuelga del de añadir y no vive en la tarjeta de
configuración de quien lo trae, que es donde acabaría estando si nadie lo decidiera. Bajar a
Configuración para importar es ir a buscar un botón a la pantalla de otra cosa.

Se declara en el `manifest.py` de quien lo ofrece, como todo lo demás aquí (ver
`docs/explica-discovery.md`); el ejemplo está debajo, en el comentario de :func:`actions`.

Este módulo no nombra a ningún proveedor, y no puede: el texto, el icono y la función los pone
quien trae los dispositivos, y quitar su carpeta quita el botón. Hay una guarda que lo comprueba,
y por eso el ejemplo va en un comentario y no aquí.
"""

from __future__ import annotations


# El descriptor, con el ejemplo real::
#
#     DEVICE_ACTIONS = [{'id': 'import', 'label_key': 'fs_import_hosts',
#                      'icon': 'bi-cloud-download', 'variant': 'primary',
#                      'perm': 'devices_edit', 'fn': 'freshserviceImportHosts',
#                      'ready': is_configured}]
#
# `ready` es lo que hace que el botón no aparezca hasta que su conector está puesto, y es una
# función **del proveedor**: qué necesita para funcionar lo sabe él. Sin `ready`, siempre.

def actions(wa) -> list:
    """Las acciones que los paquetes ofrecen aquí, ya filtradas por lo que está configurado.

    El filtrado es el de :func:`lib.discovery.ready_actions` —el mismo que aplica la pantalla de
    Empresas con `ORG_ACTIONS`— y está escrito una vez a propósito: son la misma regla, y dos
    copias son dos sitios donde arreglar el mismo fallo.
    """
    from lib.discovery import ready_actions       # noqa: PLC0415
    return ready_actions('DEVICE_ACTIONS', wa)


# El descriptor de la pantalla de CLASES, con el ejemplo real::
#
#     DEVICE_TYPE_ACTIONS = [{'id': 'import', 'label_key': 'fs_import_types',
#                           'icon': 'bi-cloud-download', 'perm': 'devices_edit',
#                           'fn': 'freshserviceImportTypes', 'ready': is_configured}]
#
# La misma forma y las mismas reglas que las de la lista de dispositivos: sin `fn` no se dibuja,
# `ready` decide si aparece, y quien lo declara pone el texto, el icono y la función. Un registro
# aparte y no el mismo porque son dos pantallas: traer los dispositivos de un sitio y traer sus
# clases son dos actos, y un proveedor puede ofrecer uno sin el otro.

def type_actions(wa) -> list:
    """Lo que los paquetes ofrecen en la pantalla de clases, ya filtrado."""
    from lib.discovery import ready_actions       # noqa: PLC0415
    return ready_actions('DEVICE_TYPE_ACTIONS', wa)


# ── De dónde vino un dispositivo ────────────────────────────────────────────────────────
#
# La columna `source` de un dispositivo guarda un identificador (`freshservice`), y la pantalla
# tiene que poder enseñar un nombre y un icono sin que el core escriba ninguno: **ningún texto
# del core nombra a un proveedor**. Lo declara quien los trae, en su `manifest.py`::
#
#     DEVICE_SOURCES = [{'id': 'freshservice', 'label_key': 'fs_source',
#                      'icon': 'bi-life-preserver'}]
#
# Y un origen que ya no declara nadie —el proveedor se quitó— no deja la fila muda: la pantalla
# enseña el identificador tal cual, que sigue diciendo de dónde vino.
#
# Aparte de `ORG_SOURCES` porque son dos preguntas distintas: un proveedor puede traer las
# empresas y no los dispositivos, y con una sola lista el segundo botón aparecería por tener
# puesto el primero.

_FUENTES: dict | None = None


def sources() -> dict:
    """``{id: descriptor}`` de todo origen de dispositivos que algún paquete declare."""
    global _FUENTES                              # pylint: disable=global-statement
    if _FUENTES is None:
        from lib.discovery import declared_by_id  # noqa: PLC0415
        _FUENTES = declared_by_id('DEVICE_SOURCES')
    return _FUENTES


def forget_sources() -> None:
    """Dropar la caché. Para las pruebas que instalan un paquete a media ejecución."""
    global _FUENTES                              # pylint: disable=global-statement
    _FUENTES = None
