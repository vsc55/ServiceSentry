#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las tablas de este dominio, una por archivo.

Son dos y responden a dos preguntas distintas:

* :mod:`~lib.core.hosts.stores.hosts` — ``hosts``: qué máquinas hay, cómo se llega a cada una y
  con qué credenciales (cifradas).
* :mod:`~lib.core.hosts.stores.types` — ``host_type``: qué **clases** de dispositivo existen, que
  es un dato de esta casa y no una lista en el código.

**Una tabla por archivo y el nombre del archivo es el de la tabla**, que es lo que hace que
buscar `host_type` en el repositorio lleve a un sitio y no a tres. La misma forma que
:mod:`lib.core.dcim.store`, donde son doce.

Lo que se **lee y se escribe** vive aquí; lo que las pantallas y los proveedores preguntan sobre
las clases —«¿cuáles hay?», «¿la lleva alguien puesta?», «créala si no está»— vive en
:mod:`lib.core.hosts.classes`, que es la capa de encima. Las dos cosas juntas eran un archivo de
setecientas líneas donde para leer el catálogo había que importar el módulo que define la tabla.

Reexportado aquí para que quien sólo quiere un almacén no tenga que saber en qué archivo cayó:
``from lib.core.hosts.stores import HostsStore, HostTypesStore``.
"""

from lib.core.hosts.stores.hosts import HostsStore
from lib.core.hosts.stores.types import HostTypesStore

__all__ = ['HostsStore', 'HostTypesStore']
