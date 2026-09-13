#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qué hacer con los activos que llegan de Freshservice, sin red y sin base de datos.

El hermano de :mod:`.plan`, para dispositivos en vez de empresas, y con las mismas tres reglas
—emparejar por el identificador de allí, no pisar lo que tecleó una persona, no viajar lo que no
cambió— porque los fallos que evitan son los mismos.

**Lo que un dispositivo importado tiene de allí es poco, y a propósito.** Nombre, dirección y
descripción: eso es lo que Freshservice sabe. Los perfiles de conexión, los módulos que lo
vigilan, lo que está marcado como enlace de salida y todo lo demás se dice **aquí**, porque
Freshservice no tiene dónde guardarlo — y por eso una importación que los rescribiera estaría
borrando el único sitio donde viven.

**La clase de dispositivo se adivina UNA vez.** El tipo de activo de allí («Server», «Network
Device») se parece a lo de aquí lo justo para acertar de salida, y no lo bastante para insistir:
en cuanto alguien lo corrige en este panel, la corrección es lo que sabe esta casa y ninguna
importación posterior la deshace. Se adivina al crear, se enseña en la vista previa antes de
aceptar, y ahí se acaba.

**Y la que no se parece a ninguna se crea.** Un punto de acceso no era ninguna de las once clases
de serie, así que caía en «sin clasificar» — junto con los teléfonos IP, las controladoras y todo
lo que no estaba en una lista escrita hace dos años. Ahora la importación añade la clase con el
nombre que trae el origen (`lib/core/hosts/classes.py::ensure`), y el plan lo **dice antes**:
crear clases en silencio es la manera de acabar con quince que nadie recuerda haber pedido.
"""

from __future__ import annotations

from lib.providers.freshservice.plan import SOURCE, ascii_fold

#: Dónde vive la dirección de un activo, por orden de preferencia. Se prueban en este orden
#: porque una dirección IP es a lo que se conecta un check y un nombre puede no resolver desde
#: este servidor — pero un nombre es mucho mejor que nada.
#:
#: El nombre del activo NO está en la lista, y estuvo: se parece a un nombre de máquina lo
#: bastante para tentar, y «Portátil de Juan» como dirección de un check es un dispositivo que
#: sale en rojo para siempre sin que nadie entienda por qué. Sin dirección es una respuesta.
ADDRESS_FIELDS = ('ip_address', 'hostname', 'host_name', 'fqdn')

#: El número de serie, que es lo que se lee en una pegatina y lo que pide un soporte.
SERIAL_FIELDS = ('serial_number', 'serial_no', 'serial')

#: Qué clase de dispositivo de los de aquí (`lib/core/hosts/manifest.py::HOST_TYPES`) se parece
#: a un tipo de activo de allí. **Por palabras y no por identificador**: el número de un tipo de
#: activo es distinto en cada casa, y su nombre lo escribe quien montó ese Freshservice — en su
#: idioma, y a veces en dos.
#:
#: Se recorre en orden y gana la primera que aparezca en el nombre, así que lo específico va
#: antes que lo general: «servidor de virtualización» es un hipervisor y no un servidor.
#:
#: **Sin acentos, y el nombre de allí se aplana antes de comparar.** Dos Freshservice de dos casas
#: escriben «Cámara IP» y «Camara IP», y con las palabras acentuadas sólo casaría uno de los dos —
#: en silencio, dejando la mitad de los dispositivos sin clase y sin nada que lo dijera.
TYPE_HINTS = (
    ('hypervisor', ('hypervisor', 'vmware', 'esxi', 'proxmox', 'virtualiz')),
    ('nas',        ('nas', 'storage', 'almacenamiento', 'cabina')),
    ('switch',     ('switch', 'conmutador')),
    ('router',     ('router', 'enrutador', 'gateway')),
    ('firewall',   ('firewall', 'cortafuegos', 'utm')),
    ('ups',        ('ups', 'sai', 'battery')),
    ('printer',    ('printer', 'impresora', 'mfp')),
    ('camera',     ('camera', 'camara', 'cctv')),
    ('workstation', ('workstation', 'desktop', 'laptop', 'notebook', 'portatil',
                     'sobremesa', 'puesto', 'pc', 'computer', 'ordenador')),
    ('server',     ('server', 'servidor', 'host')),
)


def field(asset, *names) -> str:
    """El primero de esos campos que traiga algo, buscado donde de verdad está.

    **Los campos de un activo no se llaman como se llaman.** Freshservice los devuelve dentro de
    ``type_fields`` con el identificador de su tipo pegado detrás — ``ip_address_7000123456`` —
    y ese número es distinto en cada casa y hasta entre dos tipos de la misma. Un lector que
    pidiera ``ip_address`` a secas encontraría un hueco **siempre**, en todas las instalaciones,
    y lo que se vería en pantalla es una lista de dispositivos sin dirección: un fallo que no da
    ningún error y que se investiga por el lado que no es.

    Se mira también en la ficha desnuda, que es donde viven `name` y `asset_tag`.
    """
    campos = (asset or {}).get('type_fields') or {}
    if not isinstance(campos, dict):
        campos = {}
    for nombre in names:
        directo = str((asset or {}).get(nombre) or '').strip()
        if directo:
            return directo
        for clave, valor in campos.items():
            if clave == nombre or str(clave).startswith(f'{nombre}_'):
                texto = str(valor or '').strip()
                if texto:
                    return texto
    return ''


def device_type_for(type_name: str) -> str:
    """La clase de dispositivo de aquí que se parece a ese tipo de activo de allí, o ``''``.

    ``''`` es una respuesta y no un fallo: «no lo sé» es mejor que ponerle una etiqueta que
    alguien tendría que quitar, y la pantalla ya sabe enseñar un dispositivo sin clasificar.
    """
    texto = ascii_fold(str(type_name or '')).strip().lower()
    if not texto:
        return ''
    for nuestro, palabras in TYPE_HINTS:
        if any(p in texto for p in palabras):
            return nuestro
    return ''


def only_types(assets, type_ids) -> list:
    """Los activos de esos tipos. Sin tipos, todos — que es lo que significa no haber elegido.

    Aquí y no sólo en la consulta al origen: al origen se le PIDE el filtro para no traer cuatro
    mil activos cuando hacen falta cuarenta, pero si no lo entiende contesta la lista entera, y
    entonces la pantalla enseñaría lo que nadie pidió. Filtrar lo que ha llegado es lo que hace
    que las dos rutas den el mismo resultado.
    """
    quiero = {str(t).strip() for t in (type_ids or ()) if str(t).strip()}
    if not quiero:
        return list(assets or ())
    return [f for f in (assets or ())
            if str((f or {}).get('asset_type_id') or '') in quiero]


def type_names(types) -> dict:
    """``{id: nombre}`` de los tipos de activo, para poder decir «Servidor» y no `7000123456`."""
    fuera = {}
    for t in (types or ()):
        ident = str((t or {}).get('id') or '').strip()
        nombre = str((t or {}).get('name') or '').strip()
        if ident and nombre:
            fuera[ident] = nombre
    return fuera


def _asset(fila, tipos) -> dict:
    """Un activo de Freshservice, con lo poco que de él se guarda aquí.

    Las fechas de allí no son ninguno de estos campos, por lo mismo que en :mod:`.plan`: las
    columnas `created_at` y `updated_at` de aquí dicen cuándo lo cambió **este** panel, y
    meterles la hora en que lo cambió otro las convierte en una columna que significa dos cosas
    según la fila.
    """
    tipo = str(tipos.get(str((fila or {}).get('asset_type_id') or '')) or '')
    return {'external_id': str((fila or {}).get('display_id')
                               or (fila or {}).get('id') or ''),
            # El nombre del tipo de allí, que es del que saldría una clase nueva si no se
            # pareciera a ninguna de aquí. Viaja con el plan para que la pantalla pueda decirlo.
            'new_type': '' if device_type_for(tipo) else tipo,
            # Y CUÁL es allí, para poder atar la clase que se cree: por el nombre no vale —
            # renombrarla aquí dejaría a la siguiente importación creando una segunda.
            'new_type_id': ('' if device_type_for(tipo)
                            else str((fila or {}).get('asset_type_id') or '')),
            'name': str((fila or {}).get('name') or '').strip(),
            'address': field(fila, *ADDRESS_FIELDS),
            'serial': field(fila, *SERIAL_FIELDS),
            'asset_tag': str((fila or {}).get('asset_tag') or '').strip(),
            'description': str((fila or {}).get('description') or '').strip(),
            'type_name': tipo,
            'device_type': device_type_for(tipo)}


#: Lo que una importación mantiene de un dispositivo atado. Nombrado y en un solo sitio porque es
#: la MISMA lista que la ruta de guardar usa para negarse a que se teclee encima: dos copias
#: serían un campo que la pantalla deja escribir y la importación revierte sin decirlo.
MANAGED = ('name', 'address', 'description')


def build(assets, hosts, types=None) -> list:
    """El plan: una entrada por activo, diciendo qué se haría con él.

    *assets* es lo que contestó Freshservice, *hosts* los dispositivos de aquí y *types* sus
    tipos de activo. Devuelve ``{'action', 'external_id', 'name', 'address', 'description',
    'serial', 'asset_tag', 'type_name', 'device_type', 'uid', 'was'}`` con *action* en:

    * ``create`` — no está;
    * ``update`` — está, lo mantiene este origen y algo cambió (y *was* dice qué había);
    * ``adopt``  — hay uno dado de alta aquí con ese mismo nombre y sin origen: se le pone el
      origen en vez de crear un duplicado;
    * ``same``   — está y no cambió nada. Se devuelve igualmente: «no había nada que hacer» es
      una respuesta, y no verla deja a quien mira preguntándose si se importó.
    """
    tipos = type_names(types)
    por_ext, por_nombre = {}, {}
    for h in (hosts or ()):
        if str(h.get('source') or '') == SOURCE and str(h.get('external_id') or ''):
            por_ext[str(h['external_id'])] = h
        if not str(h.get('source') or ''):
            por_nombre.setdefault(str(h.get('name') or '').strip().casefold(), h)

    plan = []
    for fila in (assets or ()):
        a = _asset(fila, tipos)
        if not a['external_id'] or not a['name']:
            continue                    # sin identidad o sin nombre no es un dispositivo
        ya = por_ext.get(a['external_id'])
        if ya is None:
            suyo = por_nombre.get(a['name'].casefold())
            if suyo is not None:
                plan.append(dict(a, action='adopt', uid=str(suyo.get('uid') or ''),
                                 was=_was(suyo)))
                continue
            plan.append(dict(a, action='create', uid='', was={}))
            continue
        cambio = any(str(ya.get(c) or '') != str(a.get(c) or '') for c in MANAGED)
        plan.append(dict(a, action='update' if cambio else 'same',
                         uid=str(ya.get('uid') or ''), was=_was(ya)))
    return plan


def _was(host) -> dict:
    """Lo que hay aquí AHORA de los campos que la importación mantiene. Es lo que convierte «12
    se corrigen» en «éste va a cambiar de nombre», que es lo que alguien mira antes de aceptar."""
    return {c: str((host or {}).get(c) or '') for c in MANAGED}


def select(plan, pick=None, link=None, hosts=None):
    """El plan que de verdad se va a aplicar: lo ELEGIDO, con los emparejamientos a mano puestos.

    Devuelve ``(plan, rechazos)``. Dos cosas y no una porque una fila que no se puede hacer no es
    una fila que no se eligió: la primera hay que contarla con su motivo, y la segunda no existe.

    *link* —``{external_id: uid}``— es la mitad de para lo que sirve esta pantalla: que
    «SRV-BCN-01» de allí y «srv-barcelona» de aquí son la misma máquina lo sabe quien lo mira, y
    ningún parecido de nombres lo va a decir nunca. Un emparejamiento a mano **manda sobre lo que
    se hubiera deducido**.

    Lo que se rechaza, y por qué:

    * el dispositivo elegido ya no existe — se borró entre mirar y aceptar;
    * ya está atado a OTRO activo. Dos no pueden compartir uno: el segundo le pisaría el nombre
      al primero en cada importación, y la ficha iría cambiando de nombre sola.
    """
    por_uid = {str(h.get('uid') or ''): h for h in (hosts or ())}
    elegidos = None if pick is None else {str(x) for x in pick}
    enlaces = {str(k): str(v) for k, v in (link or {}).items() if str(v or '')}
    fuera, rechazos = [], []
    for p in (plan or ()):
        ext = str(p.get('external_id') or '')
        if elegidos is not None and ext not in elegidos:
            continue
        uid = enlaces.get(ext, '')
        if not uid:
            if p.get('action') == 'same':
                continue                # elegido y sin nada que hacerle: no es un rechazo
            fuera.append(p)
            continue
        suyo = por_uid.get(uid)
        if suyo is None:
            rechazos.append({'name': p.get('name') or '', 'reason': 'fs_hosts_link_gone'})
            continue
        otro = str(suyo.get('external_id') or '')
        if str(suyo.get('source') or '') == SOURCE and otro and otro != ext:
            rechazos.append({'name': p.get('name') or '', 'reason': 'fs_hosts_link_taken'})
            continue
        fuera.append(dict(p, action='adopt', uid=uid, was=_was(suyo)))
    return fuera, rechazos


def orphans(assets, hosts) -> list:
    """Lo que se importó un día y ya no está en Freshservice.

    **No se borra**, y por eso esto sólo lo cuenta: de ese dispositivo cuelgan perfiles de
    conexión, módulos vigilándolo y meses de historial, y un activo desaparece del origen tanto
    por una baja real como por un filtro mal puesto. Borrar por una lista que llegó corta es
    perder trabajo de meses; enseñarlo y que decida una persona, no.
    """
    vivos = {str((f or {}).get('display_id') or (f or {}).get('id') or '')
             for f in (assets or ())}
    return [h for h in (hosts or ())
            if str(h.get('source') or '') == SOURCE
            and str(h.get('external_id') or '') not in vivos]


def counts(plan) -> dict:
    """Cuántos de cada, para decirlo en una línea antes de aplicar nada."""
    out = {'create': 0, 'update': 0, 'adopt': 0, 'same': 0}
    for p in (plan or ()):
        out[p['action']] = out.get(p['action'], 0) + 1
    return out
