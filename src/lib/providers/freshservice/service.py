#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aplicar un plan: la única parte de esto que escribe.

Separada de quien lo decide (:mod:`.plan`) y de quien lo trae (:mod:`.client`) porque son tres
trabajos distintos, y porque el que escribe es el que hay que poder mirar dos veces: crea
sociedades y corrige nombres que después salen en las chapas de cuarenta armarios.

Lo que hace y lo que no:

* **crea** lo que no está, con la abreviatura que el plan sacó del nombre — corregible después,
  que es lo que va a pasar;
* **corrige** nombre y descripción de lo que ya vino de aquí;
* **adopta** —le pone el origen— a la que alguien tecleó con ese mismo nombre;
* **no toca** lo que no cambió, y **no borra nunca**. De una sociedad cuelgan armarios y
  máquinas fichados aquí, y un departamento desaparece del origen tanto por una reorganización
  como por un filtro mal puesto. Lo que ya no está se cuenta y se enseña; borrarlo lo decide una
  persona, en la pantalla de empresas, una por una.
"""

from __future__ import annotations

from lib.providers.freshservice.plan import SOURCE


def apply(store, plan, *, actor: str = '') -> dict:
    """Ejecutar el plan sobre el almacén de empresas. Devuelve cuántas de cada cosa se hicieron.

    Fila a fila y no en una transacción: son unas pocas decenas, cada una es independiente de
    las demás, y una que falle —un nombre que choca con el de una empresa tecleada a mano— no
    tiene por qué llevarse por delante las treinta y nueve que sí valían. Lo que falla se cuenta
    aparte, con su nombre, para que se pueda arreglar a mano.
    """
    hecho = {'created': 0, 'updated': 0, 'adopted': 0, 'failed': []}
    for p in (plan or ()):
        accion = p.get('action')
        if accion == 'same':
            continue
        campos = {'name': p.get('name') or '', 'description': p.get('description') or ''}
        try:
            if accion == 'create':
                store.orgs.create(dict(campos, short=p.get('short') or '',
                                       source=SOURCE, external_id=p.get('external_id') or ''),
                                  actor=actor)
                hecho['created'] += 1
            elif accion == 'update':
                store.orgs.update(p.get('uid') or '', campos, actor=actor)
                hecho['updated'] += 1
            elif accion == 'adopt':
                # El origen **y los datos**. Guardar sólo el atado y respetar lo de aquí era una
                # seguridad de mentira: desde ese momento la fila la mantiene Freshservice, y la
                # siguiente importación le habría pisado el nombre igual. Retrasarlo un ciclo
                # sólo consigue que el cambio llegue el día que nadie lo está mirando.
                #
                # La abreviatura la trae el plan: allí no existe ese campo, así que se rehace del
                # nombre nuevo cuando el nombre cambia, y se queda la de aquí cuando no.
                store.orgs.update(p.get('uid') or '',
                                  dict(campos, short=p.get('short') or '', source=SOURCE,
                                       external_id=p.get('external_id') or ''), actor=actor)
                hecho['adopted'] += 1
        except Exception as exc:                    # pylint: disable=broad-except
            hecho['failed'].append({'name': p.get('name') or '', 'error': str(exc)[:200]})
    return hecho
