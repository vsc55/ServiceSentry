#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qué hacer con lo que llega de Freshservice, sin red y sin base de datos.

Todo lo que decide vive aquí, y por eso aquí no hay ni una petición ni una consulta: lo que se
puede equivocar es el emparejamiento —qué es nuevo, qué es lo mismo con otro nombre, qué no hay
que tocar— y eso se prueba con dos listas y ningún servidor.

Tres reglas, y las tres tienen una razón de haber salido mal en otros sitios:

1. **Se empareja por el identificador de allí, no por el nombre.** Renombrar una sociedad en
   Freshservice crearía aquí una segunda y dejaría la primera huérfana, sin que nada lo dijera.
2. **Lo que alguien tecleó aquí no se pisa.** Una empresa sin origen es una que escribió una
   persona; que una importación le cambie el nombre porque coincide con un departamento es
   perder un dato para ganar otro. Se ADOPTA sólo si el nombre coincide exactamente y todavía no
   es de nadie — que es el caso real: la lista se tecleó a mano antes de conectar esto.
3. **Lo que no cambió no viaja.** Una importación que reescribe cuarenta filas idénticas llena
   el registro de auditoría de cambios que no cambian nada.
"""

from __future__ import annotations

import re
import unicodedata

#: Cómo se llama este origen en la columna `source` de una empresa. Una constante y no una
#: cadena suelta: la escriben el plan, la ruta y la consulta que busca lo ya importado.
SOURCE = 'freshservice'

#: Lo que cabe en una chapa. El límite es de la columna, no del gusto de nadie.
SHORT_MAX = 12

_NO_PALABRA = re.compile(r'[^0-9A-Za-z]+')


def ascii_fold(texto: str) -> str:
    """Sin acentos y sin eñes.

    Lo pide una abreviatura —es para una chapa y para un alzado— y lo pide también comparar con
    lo que escribe otro: un Freshservice que llame «Cámara IP» a un tipo de activo y otro que lo
    llame «Camara IP» son la misma casa diciendo lo mismo, y sólo casan los dos si se comparan
    planos. Público porque lo usan los dos planes de este paquete.
    """
    plano = unicodedata.normalize('NFKD', str(texto or ''))
    return ''.join(c for c in plano if not unicodedata.combining(c))


def short_for(name: str, taken) -> str:
    """Una abreviatura para una empresa que llega sin ella, sin repetir ninguna de *taken*.

    Freshservice no tiene ese campo, y aquí es obligatorio: es lo que cabe en la chapa de un
    alzado, donde el nombre legal de una sociedad no entra. Así que se saca del nombre y se
    deja corregir después — que es lo que va a pasar, porque una abreviatura la elige quien la
    va a leer en una chapa a dos metros.

    Las iniciales de las palabras cuando hay varias («Montarto Food» → `MF`), y las primeras
    letras cuando es una sola («Amixalan» → `AMIXALAN`). Si eso ya está cogido, se le pone un
    número: dos chapas iguales en un armario compartido no dicen de quién es.
    """
    palabras = [p for p in _NO_PALABRA.split(ascii_fold(name)) if p]
    if not palabras:
        base = 'ORG'
    elif len(palabras) > 1:
        base = ''.join(p[0] for p in palabras).upper()[:SHORT_MAX]
    else:
        base = palabras[0].upper()[:SHORT_MAX]
    usadas = {str(x or '').strip().casefold() for x in (taken or ())}
    if base.casefold() not in usadas:
        return base
    for n in range(2, 100):
        cola = str(n)
        cand = base[:SHORT_MAX - len(cola)] + cola
        if cand.casefold() not in usadas:
            return cand
    return base[:SHORT_MAX]                 # cien iguales: que lo arregle una persona


def _dept(fila) -> dict:
    """Un departamento de Freshservice, con lo poco que de él se guarda aquí.

    **Tres campos, y sus fechas no son ninguno de ellos.** Freshservice manda `created_at` y
    `updated_at` —en UTC y con la forma `YYYY-MM-DDTHH:MM:SSZ`, que da la casualidad de que es
    la misma que escribe este panel—, y precisamente por parecerse tanto es por lo que no se
    copian: esas columnas de aquí dicen **cuándo lo cambió este panel**, y meterles la hora en
    que lo cambió otro las convierte en una columna que significa dos cosas según la fila. Quien
    mire «modificado» para saber si alguien ha tocado algo aquí se llevaría la respuesta de otra
    casa.

    Traerlas algún día es posible, y sería en columnas propias (`source_updated_at`), no en
    éstas. No haría falta convertir nada: las dos puntas hablan el mismo ISO 8601 en UTC.

    Que se queden fuera está vigilado, porque el día que alguien escriba `dict(fila)` en vez de
    estos tres campos las fechas entran solas y no falla nada.
    """
    return {'external_id': str((fila or {}).get('id') or ''),
            'name': str((fila or {}).get('name') or '').strip(),
            'description': str((fila or {}).get('description') or '').strip()}


def build(departments, orgs) -> list:
    """El plan: una entrada por departamento, diciendo qué se haría con él.

    *departments* es lo que contestó Freshservice y *orgs* las empresas de aquí (tal cual salen
    del almacén). Devuelve una lista de ``{'action', 'external_id', 'name', 'description',
    'uid', 'short', 'was'}`` con *action* en:

    * ``create`` — no está;
    * ``update`` — está y algo cambió (y *was* dice qué había);
    * ``adopt``  — hay una tecleada aquí con ese mismo nombre y sin origen: se le pone el
      origen en vez de crear una copia;
    * ``same``   — está y no cambió nada. Se devuelve igualmente: «no había nada que hacer» es
      una respuesta, y no verla deja a quien mira preguntándose si se importó.
    * ``conflict`` — se adoptaría una empresa que OTRO departamento de la misma lista ya va a
      adoptar (dos departamentos que se llaman igual). No se aplica: el segundo le pisaría el
      `external_id` al primero, y en cada importación la empresa cambiaría de dueño. Queda en el
      plan para que se vea, y se resuelve emparejándolo a mano con otra.

    Nada de esto escribe: quien lo aplica recorre esta lista. Que decidir y hacer estén
    separados es lo que permite enseñar el plan antes de aplicarlo.
    """
    por_ext, por_nombre = {}, {}
    for o in (orgs or ()):
        if str(o.get('source') or '') == SOURCE and str(o.get('external_id') or ''):
            por_ext[str(o['external_id'])] = o
        if not str(o.get('source') or ''):
            por_nombre.setdefault(str(o.get('name') or '').strip().casefold(), o)

    cogidas = {str(o.get('short') or '').strip() for o in (orgs or ())}
    adoptadas: dict = {}                    # uid local → external_id que ya la adopta
    plan = []
    for fila in (departments or ()):
        d = _dept(fila)
        if not d['external_id'] or not d['name']:
            continue                        # sin identidad o sin nombre no es un departamento
        ya = por_ext.get(d['external_id'])
        if ya is None:
            suya = por_nombre.get(d['name'].casefold())
            if suya is not None:
                uid_suya = str(suya.get('uid') or '')
                if adoptadas.get(uid_suya, d['external_id']) != d['external_id']:
                    plan.append(dict(d, action='conflict', uid='', short='',
                                     was={'name': str(suya.get('name') or '')}))
                    continue
                adoptadas[uid_suya] = d['external_id']
                plan.append(dict(d, action='adopt', uid=str(suya.get('uid') or ''),
                                 short=str(suya.get('short') or ''),
                                 was={'name': str(suya.get('name') or ''),
                                      'short': str(suya.get('short') or ''),
                                      'description': str(suya.get('description') or '')}))
                continue
            corta = short_for(d['name'], cogidas)
            cogidas.add(corta)
            plan.append(dict(d, action='create', uid='', short=corta, was={}))
            continue
        cambio = (str(ya.get('name') or '') != d['name']
                  or str(ya.get('description') or '') != d['description'])
        plan.append(dict(d, action='update' if cambio else 'same',
                         uid=str(ya.get('uid') or ''), short=str(ya.get('short') or ''),
                         was={'name': str(ya.get('name') or ''),
                              'description': str(ya.get('description') or '')}))
    return plan


def select(plan, pick=None, link=None, orgs=None):
    """El plan que de verdad se va a aplicar: lo ELEGIDO, con los emparejamientos a mano puestos.

    Devuelve ``(plan, rechazos)``. Dos cosas y no una porque una fila que no se puede hacer no es
    una fila que no se eligió: la primera hay que contarla con su motivo, y la segunda no existe.

    * *pick* — los `external_id` que se han marcado. `None` es «todo», que es lo que esto hacía
      antes de que se pudiera elegir.
    * *link* — ``{external_id: uid}``, los emparejamientos que ha hecho una persona. Es la
      diferencia entre lo que el panel puede deducir y lo que sólo sabe quien lo mira: «Amixalan
      Energy Supplies, S.L.» de allí y «Amixalan» de aquí pueden ser la misma casa, y ningún
      emparejamiento automático por nombre lo va a decir nunca.

    Un emparejamiento a mano **manda sobre lo que se hubiera deducido**: si alguien dice que esas
    dos son la misma, es que lo son.

    Lo que se rechaza, y por qué:

    * la empresa elegida ya no existe — se borró entre mirar y aceptar;
    * ya está atada a OTRO departamento. Dos no pueden compartir una: el segundo le pisaría el
      nombre al primero en cada importación, y la fila iría cambiando de nombre sola. Eso vale
      también DENTRO de esta misma importación: dos emparejamientos a mano con la misma
      empresa, o uno a mano con la que otro departamento adopta solo. Gana el primero y el
      segundo se cuenta como rechazo;
    * un ``conflict`` del plan que nadie emparejó a mano — ver :func:`build`.
    """
    por_uid = {str(o.get('uid') or ''): o for o in (orgs or ())}
    cogidas = {str(o.get('short') or '').strip() for o in (orgs or ()) if o.get('short')}
    elegidos = None if pick is None else {str(x) for x in pick}
    enlaces = {str(k): str(v) for k, v in (link or {}).items() if str(v or '')}
    fuera, rechazos = [], []
    reclamadas: dict = {}                   # uid local → external_id al que se ata aquí

    def _reclamar(uid, ext) -> bool:
        if reclamadas.get(uid, ext) != ext:
            return False
        reclamadas[uid] = ext
        return True

    for p in (plan or ()):
        ext = str(p.get('external_id') or '')
        if elegidos is not None and ext not in elegidos:
            continue
        uid = enlaces.get(ext, '')
        if not uid:
            if p.get('action') == 'same':
                continue                    # elegida y sin nada que hacerle: no es un rechazo
            if p.get('action') == 'conflict':
                rechazos.append({'name': p.get('name') or '', 'reason': 'fs_link_taken'})
                continue
            if p.get('action') in ('adopt', 'update') and not _reclamar(str(p.get('uid') or ''), ext):
                rechazos.append({'name': p.get('name') or '', 'reason': 'fs_link_taken'})
                continue
            fuera.append(p)
            continue
        suya = por_uid.get(uid)
        if suya is None:
            rechazos.append({'name': p.get('name') or '', 'reason': 'fs_link_gone'})
            continue
        otro = str(suya.get('external_id') or '')
        if str(suya.get('source') or '') == SOURCE and otro and otro != ext:
            rechazos.append({'name': p.get('name') or '', 'reason': 'fs_link_taken'})
            continue
        if not _reclamar(uid, ext):
            rechazos.append({'name': p.get('name') or '', 'reason': 'fs_link_taken'})
            continue
        # La abreviatura: Freshservice no tiene ese campo, así que no hay nada que «descargar».
        # Se rehace del nombre nuevo **sólo si el nombre cambia** — una abreviatura es las
        # iniciales de un nombre, y dejar «AMX» sobre «Amixalan Energy Supplies, S.L.» es una
        # chapa que ya no dice lo que pone la fila. Si el nombre no cambia, la de aquí se queda:
        # la eligió una persona para leerla en un armario a dos metros.
        corta = str(suya.get('short') or '')
        if str(suya.get('name') or '') != p.get('name') or not corta:
            corta = short_for(p.get('name') or '', cogidas - {corta})
        fuera.append(dict(p, action='adopt', uid=uid, short=corta,
                          was={'name': str(suya.get('name') or ''),
                               'short': str(suya.get('short') or ''),
                               'description': str(suya.get('description') or '')}))
    return fuera, rechazos


def orphans(departments, orgs) -> list:
    """Lo que se importó un día y ya no está en Freshservice.

    **No se borra**, y por eso esto sólo lo cuenta: de esa sociedad cuelgan armarios y máquinas
    fichados aquí, y un departamento puede desaparecer del origen por una reorganización, por un
    filtro mal puesto o porque alguien se equivocó. Borrar lo que cuelga por una lista que llegó
    corta es perder trabajo de meses; enseñarlo y que decida una persona, no.
    """
    vivos = {str((f or {}).get('id') or '') for f in (departments or ())}
    return [o for o in (orgs or ())
            if str(o.get('source') or '') == SOURCE
            and str(o.get('external_id') or '') not in vivos]


def counts(plan) -> dict:
    """Cuántos de cada, para decirlo en una línea antes de aplicar nada."""
    out = {'create': 0, 'update': 0, 'adopt': 0, 'same': 0}
    for p in (plan or ()):
        out[p['action']] = out.get(p['action'], 0) + 1
    return out
