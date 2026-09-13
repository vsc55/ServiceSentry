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


def _clase(wa, p, actor: str) -> str:
    """La clase que se le pone a un dispositivo nuevo, creándola si hace falta.

    Primero la adivinada, que es una de las de serie y siempre vale. Si no se parecía a ninguna,
    se crea una con el nombre del tipo de allí: un punto de acceso no era ninguna de las once y
    caía en «sin clasificar», junto con los teléfonos IP y todo lo que no estuviera en una lista
    escrita hace dos años.

    **Y se devuelve su `uid`**, que es lo que la columna guarda. La pista viene dicha con el
    nombre corto —`switch`, `ups`, que es lo único de las sembradas escrito en el código—, y
    escribir eso en la columna es que el almacén lo tire: la máquina se trae igual y se queda sin
    clasificar, sin un solo error.

    Sin panel —o si crearla falla— se devuelve vacío, que es «sin clasificar»: mucho mejor que
    negarse a traer el dispositivo por no poder ponerle una etiqueta.
    """
    if wa is None:
        return ''
    from lib.core.hosts import classes as host_types        # noqa: PLC0415
    try:
        adivinada = host_types.uid_for(wa, str(p.get('device_type') or ''))
    except Exception:  # pylint: disable=broad-except
        adivinada = ''
    if adivinada:
        return adivinada
    nombre = str(p.get('new_type') or '').strip()
    if not nombre:
        return ''
    try:
        return host_types.ensure(wa, nombre, source=SOURCE,
                                 external_id=str(p.get('new_type_id') or ''), actor=actor)
    except Exception:  # pylint: disable=broad-except
        return ''


def is_configured(wa) -> bool:
    """¿Hay a quién llamar y con qué?

    Lo decide este paquete y no la pantalla de Empresas, que es la regla de siempre aquí: el
    core no sabe qué necesita un proveedor para funcionar, y el día que a éste le haga falta un
    tercer campo, la respuesta cambia en un sitio.

    Dominio **y** clave. Con el dominio sólo, el botón invita a una importación que va a fallar
    en la primera llamada — y falla con un error de autenticación, que es el peor sitio para
    enterarse de que faltaba un campo de configuración.
    """
    try:
        sec = wa._config_section('freshservice') or {}       # noqa: SLF001
    except Exception:      # pylint: disable=broad-except
        return False
    return bool(str(sec.get('domain') or '').strip()
                and str(sec.get('api_key') or '').strip())


# ── Los dispositivos ────────────────────────────────────────────────────────────────────
#
# El mismo trabajo que con las empresas y con una diferencia que es toda la diferencia: de un
# dispositivo de aquí cuelgan cosas que Freshservice no sabe que existen —los perfiles de
# conexión con sus claves, los módulos que lo vigilan, las filas marcadas, meses de historial— y
# el almacén de dispositivos guarda la ficha ENTERA en cada escritura.
#
# Así que una actualización se hace sobre la ficha que hay, no sobre un puñado de campos: se lee,
# se le cambia lo que mantiene el origen y se vuelve a guardar. Escribir sólo los tres campos
# sería, palabra por palabra, borrarle las claves de conexión a cuarenta máquinas.

def apply_hosts(store, plan, *, actor: str = '', wa=None) -> dict:
    """Ejecutar el plan sobre el registro de dispositivos. Devuelve cuántos de cada cosa.

    Fila a fila y no en una transacción, por lo mismo que las empresas: son unas decenas, cada
    una es independiente, y una que falle —un nombre que choca con el de un dispositivo dado de
    alta a mano— no tiene por qué llevarse por delante las treinta y nueve que sí valían.
    """
    hecho = {'created': 0, 'updated': 0, 'adopted': 0, 'failed': []}
    # Lo que falla trae `error_key` —una clave del catálogo de idiomas— y no una frase: aquí no
    # se sabe en qué idioma mira quien pulsó, y una frase escrita en este fichero es una que no
    # se puede traducir. Lo que viene de una excepción trae `error` y no se traduce, porque no
    # es de este panel.
    for p in (plan or ()):
        accion = p.get('action')
        if accion == 'same':
            continue
        campos = {'name': p.get('name') or '', 'address': p.get('address') or '',
                  'description': p.get('description') or ''}
        try:
            if accion == 'create':
                # `kind` no se dice y es correcto que no se diga: el almacén lo deja en `none`,
                # que es «este panel no ejecuta nada en él» — la respuesta honesta para un
                # conmutador, un SAI o una impresora que llegan de un inventario. Ponerle
                # `local` haría que un check suyo midiera esta máquina y lo archivara con su
                # nombre.
                uid = store.create(dict(campos, device_type=_clase(wa, p, actor),
                                        source=SOURCE,
                                        external_id=p.get('external_id') or ''), actor=actor)
                if not uid:
                    # El almacén contesta `None` cuando el nombre ya está cogido, que es el caso
                    # real: alguien lo dio de alta a mano con otro nombre… o con ÉSTE, y
                    # entonces lo que se quería era emparejarlos. Se cuenta con su nombre para
                    # que se pueda hacer a mano.
                    hecho['failed'].append({'name': campos['name'],
                                            'error_key': 'fs_host_name_taken'})
                    continue
                hecho['created'] += 1
            elif accion in ('update', 'adopt'):
                # La ficha entera, con lo del origen encima. Sin el `dict(actual, …)` esto
                # guardaría un dispositivo sin perfiles, sin módulos y sin nada vigilado.
                actual = store.get(p.get('uid') or '', decrypt=True)
                if actual is None:
                    hecho['failed'].append({'name': campos['name'],
                                            'error_key': 'fs_hosts_link_gone'})
                    continue
                ficha = dict(actual, **campos)
                if accion == 'adopt':
                    # La clase de dispositivo NO se toca al adoptar: el de aquí ya la tiene
                    # puesta, probablemente por una persona, y lo de allí es una adivinanza
                    # sacada del nombre de un tipo de activo.
                    ficha['source'] = SOURCE
                    ficha['external_id'] = p.get('external_id') or ''
                store.update(p.get('uid') or '', ficha, actor=actor)
                hecho['updated' if accion == 'update' else 'adopted'] += 1
        except Exception as exc:                    # pylint: disable=broad-except
            hecho['failed'].append({'name': p.get('name') or '', 'error': str(exc)[:200]})
    return hecho
