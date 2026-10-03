#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El widget que este dominio aporta al panel de control: **las sedes en un mapa**.

La pregunta que contesta no la contesta ninguna otra tarjeta del panel. Las demás dicen *qué*
está mal —una lista de máquinas, un recuento de avisos—; esta dice **dónde**, y eso es lo que
decide a quién se llama a las tres de la mañana: no es lo mismo que lo caído esté en la nave de
al lado que en el CPD que está a cuatro horas de coche y al que hay que avisar con antelación
para entrar.

Tres decisiones que no son de dibujo:

* **El estado de una sede es el de lo que hay dentro, contado como lo cuenta la sección.** Se
  pide a `service.board`, que es de donde se dibuja el cuadro del inventario; una segunda idea
  de «peor» aquí sería una pantalla que dice que la sede está bien mientras la otra la pinta en
  rojo, y las dos con razón.
* **Se cuenta lo que este lector puede ver.** Igual que todo lo demás del dominio: en un grupo,
  el panel de control de una filial no puede enseñar los problemas de otra por la puerta de
  atrás. Eso ya lo hace `board`; aquí solo hay que darle con qué.
* **Una sede sin coordenadas no se calla, se cuenta.** No se puede dibujar, y una que
  desaparece del mapa parece una que está bien. Sale en el número que acompaña al dibujo, que
  es lo que hace que alguien vaya a escribir su latitud.
"""

from __future__ import annotations

import lib.maps as maps

from . import service as dcim_svc
from lib.core.orgs import owners as org_owners


#: Cómo se dice aquí lo que la sección llama `warning`. El panel de control tiñe una tarjeta con
#: dos palabras —`error` y `warn`— y son las que entiende `_dwApplyState`; traducirlo aquí, y no
#: en la pantalla, deja el vocabulario de la tarjeta donde se declara la tarjeta.
_TINTE = {'error': 'error', 'warning': 'warn'}

#: Dónde se piden las imágenes de esta sección. La tarjeta del panel de control recibe la
#: dirección hecha y no el nombre del fichero: las rutas de este paquete son suyas, y un widget
#: que las compusiera sería el panel sabiéndose de memoria las direcciones de una sección.
MEDIA = '/api/v1/dcim/media/'


def sites_map(wa) -> dict:
    """Las sedes, cómo están y dónde caen — más con qué dibujar el mapa debajo.

    El servidor de teselas viaja con los datos y no en una petición aparte, como en la sección:
    es configuración del panel y no del navegador, y quien dibuja no tiene por qué preguntarla
    por su cuenta. Que esté vacío es la respuesta normal —el mapa se apaga de fábrica— y no un
    fallo: el dibujo sigue situando las sedes unas respecto a otras.
    """
    store = getattr(wa, '_dcim_store', None)
    # Con qué se dibuja, preguntado al catálogo (`lib.maps`) y no a un atributo suelto: para
    # Google hay que minar una sesión antes, y eso no lo puede hacer un navegador. Es lo mismo
    # que recibe el cuadro de la sección, para que las dos pantallas no dibujen mapas distintos.
    mapa = maps.settings(wa)
    fuera = {'sites': [], 'tiles': mapa['tiles'], 'placed': 0, 'unplaced': 0, 'state': '',
             'attribution': mapa['attribution'],
             'totals': {'sites': 0, 'total': 0, 'bad': 0, 'ok': 0, 'unwatched': 0}}
    if store is None:
        return fuera
    perms = set(wa._get_session_permissions() or [])
    cuadro = dcim_svc.board(store, dcim_svc.states_for(wa, perms), store.owners_map(),
                            org_owners.visible_orgs(perms), store.orgs.list())
    sedes = []
    for s in cuadro.get('sites') or ():
        lat, lon = s.get('lat'), s.get('lon')
        sedes.append({
            'uid': s.get('uid'), 'name': s.get('name'), 'state': s.get('state') or '',
            # Números o nada. Una latitud guardada como texto dibuja igual de mal que una
            # ausente, pero de una forma que parece un dato.
            'lat': float(lat) if isinstance(lat, (int, float)) else None,
            'lon': float(lon) if isinstance(lon, (int, float)) else None,
            'rooms': s.get('rooms') or 0, 'racks': s.get('racks') or 0,
            'total': s.get('total') or 0, 'ok': s.get('ok') or 0,
            'bad': s.get('bad') or 0, 'unwatched': s.get('unwatched') or 0,
            # La ficha que se enseña al pasar por encima. Un punto de color dice que algo va
            # mal; esto dice a quién se llama, dónde está y qué se ve al llegar — que es lo que
            # se pregunta a continuación, y lo único que evita abrir tres pantallas para
            # contestarlo.
            'address': s.get('address') or '', 'contact': s.get('contact') or '',
            'phone': s.get('phone') or '',
            'photo': (MEDIA + s['photo']) if s.get('photo') else '',
            'description': s.get('description') or '', 'operator': s.get('operator') or '',
            'timezone': s.get('timezone') or '',
        })
    # El (0, 0) no cuenta como coordenada: es un punto del golfo de Guinea donde no hay ningún
    # datacenter, y es lo que deja un formulario cuyos dos campos se guardaron vacíos.
    situadas = [s for s in sedes if (s['lat'] or s['lon'])]
    fuera['sites'] = sedes
    # De qué tarjeta son estos puntos: la chincheta lo necesita para saber a qué ficha pertenece
    # y adónde lleva su pulsación.
    fuera['wid'] = 'dcim_sites'
    fuera['placed'] = len(situadas)
    fuera['unplaced'] = len(sedes) - len(situadas)
    fuera['totals'] = dict(cuadro.get('totals') or {})
    fuera['state'] = _TINTE.get(dcim_svc.worst([s['state'] for s in sedes]), '')
    return fuera
