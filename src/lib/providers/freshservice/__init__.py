#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freshservice: de dónde salen las empresas cuando ya están escritas en otro sitio.

En Freshservice, «departamento» y «empresa» son la misma cosa —lo dice su propia
documentación— y en una casa que ya lo usa esa lista existe, está mantenida y es la buena: la
que aparece en los tickets, la que factura y la que alguien actualiza cuando el grupo compra
una sociedad. Teclearla aquí otra vez es tener dos listas, y dos listas son una que se queda
vieja sin avisar.

Así que esto la TRAE, y trae poco: nombre, descripción y su identificador allí. Lo demás —de
quién es cada armario, cada máquina, cada buzón— se sigue diciendo aquí, porque eso Freshservice
no lo sabe.

**En un solo sentido.** Nada de lo de aquí sube. Un proveedor que escribe en el sistema de
tickets de otro es un proveedor que puede romperle el suyo, y lo que se ha pedido es leer.

Las piezas, y por qué están separadas:

* :mod:`.client` — hablar con la API (páginas, reintentos, qué significa cada código);
* :mod:`.plan` — QUÉ hacer con lo que llegue, sin red y sin base de datos: qué se crea, qué se
  corrige y qué se deja en paz. Es lo único que tiene decisiones dentro, así que es lo único
  que hace falta poder probar a solas;
* :mod:`.routes` — probar la conexión, ver el plan antes de aplicarlo, y aplicarlo.

**Se mira antes de aplicar.** Una importación que crea y corrige en silencio es una que, el día
que el filtro esté mal, deja media docena de sociedades duplicadas y ninguna forma de saber cuál
era la buena.
"""
