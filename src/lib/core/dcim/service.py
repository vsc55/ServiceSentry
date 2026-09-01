#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the inventory looks like when the fleet's live state is laid over it.

The inventory says a device is in rack R3 at U 12. Infrastructure says that device has not
answered since Thursday. **Neither is useful alone**: the first is a map with nothing on it, the
second is a list with no idea where to walk. This module is the join, and it is the whole reason
for putting the two in one panel.

Three rules decide everything here, and each of them is a way of being wrong that looks right:

* **An item with no host has no state — and no state is not "fine".** A rack full of patch
  panels must not come out green, because nothing is watching a patch panel; it comes out with
  no colour, which is the truth. The panel already draws that distinction elsewhere
  (``HOST_STATE_COLORS['']``) and it matters more here, where a wall of green is the thing
  somebody glances at from the door.
* **A count follows visibility.** A rack reporting "3 down" of which none are yours is an
  enumeration of somebody else's fleet through the back door — the same shape as the IDOR audit
  of 2026-05. What is counted is what the caller may see.
* **Free space is everybody's.** How many U are free reveals nothing about anybody, and it is
  half the reason a shared cabinet is worth drawing at all.

The roll-up is computed in ONE pass over the containment and handed down, never asked per node:
a room of forty racks asking per rack is forty reads of the same status file.
"""

from __future__ import annotations

from . import owners as dcim_owners
from .store import FEED_COLORS, ITEM_ROLES, ROLES_MUDOS, SIDES

#: Worst first. A rack is the worst thing in it, and this is what "worst" means — the same
#: order the fleet list sorts by, so a rack and the list cannot disagree about which of two
#: machines is in more trouble.
_RANK = {'error': 3, 'warning': 2, 'ok': 1, '': 0}


#: Cuántas filas de «esto está mal» se devuelven. Una flota con doscientas cosas caídas
#: necesita las primeras veinte y un número, no doscientas filas que nadie va a leer. Se dice
#: en la respuesta que se ha recortado: una lista más corta que la realidad parece completa.
BOARD_TROUBLE_CAP = 20


def worst(states) -> str:
    """The worst of several states, or ``''`` when nothing has one."""
    out = ''
    for st in states or ():
        if _RANK.get(str(st or ''), 0) > _RANK.get(out, 0):
            out = str(st or '')
    return out


def item_state(item, statuses) -> str:
    """One item's state: its host's, or ``''`` if it has no host or nothing watches it.

    Deliberately not "ok" for the second case. Most of what fills a rack answers to nothing —
    a patch panel, a blanking plate, a switched-off server still bolted in — and painting those
    green would make the one thing this drawing is for, a glance from the door, a lie.
    """
    uid = str((item or {}).get('host_uid') or '')
    if not uid:
        return ''
    return str((statuses or {}).get(uid) or '')


def rack_roll(items, statuses) -> dict:
    """``{state, total, bad, unwatched}`` for the items **as given**.

    As given: the caller has already dropped or blanked what this reader may not see, so the
    counts follow visibility without this function knowing anything about permissions. A
    foreign item carries no `host_uid`, so it counts as one more thing occupying space and
    contributes no state — which is exactly what may be said about it.
    """
    states = [item_state(i, statuses) for i in items or ()]
    # Lo que no contesta POR NATURALEZA no cuenta como desatendido. Un armario de cuarenta
    # paneles de parcheo salía con cuarenta «sin vigilar» y ninguno lo estaba: no es que nadie
    # los mire, es que no hay nada que mirar. Y cuarenta deberes imposibles enseñan a saltarse
    # la lista, con lo que el servidor que SÍ está sin vigilar se pierde entre ellos.
    mudos = [i for i in (items or ())
             if str(i.get('role') or '') in ROLES_MUDOS and not item_state(i, statuses)]
    return {
        'state': worst(states),
        'total': len(states),
        'bad': len([s for s in states if s in ('error', 'warning')]),
        # Sin estado y sin razón para no tenerlo. Un rack de cuarenta SERVIDORES así es una
        # pregunta; uno de cuarenta paneles no lo es y ya no lo dice.
        'unwatched': len([s for s in states if not s]) - len(mudos),
        # Dicho aparte, no escondido: son inventario y salen en los pedidos.
        'passive': len(mudos),
    }


def free_units(rack, taken) -> dict:
    """Which U are free, per face — and how many, which is what a summary shows.

    Both faces, because "is U 12 free" has no answer without one: a 1U device fills U 12 front
    and rear, a patch panel may fill only the rear, and two half-depth devices share a U from
    opposite sides.
    """
    height = int((rack or {}).get('u_height') or 0)
    out = {}
    for face in ('front', 'rear'):
        free = [u for u in range(1, height + 1) if u not in (taken or {}).get(face, {})]
        out[face] = free
    out['count'] = len(out['front'])
    out['height'] = height
    return out


#: Lo que hace falta detrás del mástil trasero para que los cables no queden aplastados. No
#: es una norma, es la costumbre — y por eso se puede cambiar en la llamada en vez de estar
#: escrito en la respuesta.
CABLE_CLEARANCE_MM = 75


def rack_depths(rack) -> dict:
    """Los tramos de un rack en profundidad, y si cuadran con su fondo.

    ``{total, front, mount, rear, sum, mismatch}``. `mount` es lo que decide si un servidor
    entra: es donde se atornillan sus raíles. `mismatch` es la diferencia entre la suma de los
    tres tramos y el fondo declarado — **no se corrige**: lo que alguien midió con un metro y lo
    que dice la suma son dos cosas, y quedarse con la segunda pierde la primera. Que no cuadren
    es un dato sobre el rack, no un error del panel.
    """
    r = rack or {}
    total = int(r.get('depth_mm') or 0)
    front = int(r.get('rail_front_mm') or 0)
    mount = int(r.get('rail_depth_mm') or 0)
    rear = int(r.get('rail_rear_mm') or 0)
    parts = front + mount + rear
    return {'total': total, 'front': front, 'mount': mount, 'rear': rear, 'sum': parts,
            # Solo cuando hay las dos cosas que comparar: sin fondo o sin tramos no hay
            # discrepancia, hay un dato que nadie ha escrito.
            'mismatch': (total - parts) if (total and parts) else 0}


def fits_depth(rack, depth_mm, clearance_mm=CABLE_CLEARANCE_MM) -> dict:
    """Si un equipo de *depth_mm* de fondo entra en este rack, y por qué no.

    ``{'known': bool, 'fits': bool, 'why': str, 'spare': int}``. `known` es falso cuando falta
    alguno de los dos números — y entonces no se contesta que sí ni que no. Un «cabe» dicho sin
    saber el fondo del armario es peor que no decir nada: alguien compra con él.
    """
    d = rack_depths(rack)
    depth = int(depth_mm or 0)
    if not depth or not d['mount']:
        return {'known': False, 'fits': False, 'why': 'dcim_depth_unknown', 'spare': 0}
    # Lo aprovechable es de mástil delantero hacia atrás: el equipo va atornillado ahí y su
    # cuerpo sobresale hacia el fondo, no hacia la puerta.
    usable = d['mount'] + d['rear']
    spare = usable - depth - int(clearance_mm or 0)
    if depth > usable:
        return {'known': True, 'fits': False, 'why': 'dcim_depth_too_deep', 'spare': spare}
    if spare < 0:
        return {'known': True, 'fits': False, 'why': 'dcim_depth_no_cables', 'spare': spare}
    return {'known': True, 'fits': True, 'why': '', 'spare': spare}


def access_of(rack) -> set:
    """Los lados de un rack a los que se llega.

    Lo no dicho es TODO accesible, no nada: un inventario que se está entrando por primera vez
    tiene cientos de racks sin esta columna, y tratarlos como inaccesibles llenaría la pantalla
    de avisos sobre algo que nadie ha afirmado. La ausencia de dato no es un dato.
    """
    raw = str((rack or {}).get('access') or '').strip()
    if not raw:
        return set(SIDES)
    return {p.strip() for p in raw.split(',') if p.strip() in SIDES}


def access_warnings(rack, items) -> list:
    """Lo que no cuadra entre por dónde se llega a un rack y lo que hay montado en él.

    Hoy una sola cosa, y es la que se paga en el pasillo: **equipo en una cara a la que no se
    llega**. Un armario colgado en la pared no tiene trasera; lo que esté montado ahí no se
    cablea, no se cambia y no se apaga sin descolgar el armario.

    Es una discrepancia entre dos cosas DECLARADAS —por dónde se entra y qué hay dentro— que es
    justo el tipo de contradicción que esta sección existe para encontrar. No se corrige nada:
    se dice, porque cuál de las dos está mal lo sabe quien esté delante.
    """
    sides = access_of(rack)
    out = []
    for face in ('front', 'rear'):
        if face in sides:
            continue
        stuck = [i for i in (items or [])
                 if str(i.get('face') or 'full') in (face, 'full')]
        if stuck:
            out.append({'kind': 'unreachable_face', 'face': face, 'items': len(stuck)})
    return out


def tree_roll(store, statuses, said, allowed) -> dict:
    """The state of every rack, room and site, in one pass.

    ``{'rack': {uid: roll}, 'room': {…}, 'site': {…}}``. One pass because the alternative —
    asking per node while drawing — is a read of the status file per rack, and the screen this
    feeds is the one somebody opens with forty of them.

    Visibility is applied HERE, at the leaves, and rolls up on its own: a machine the caller
    may not see contributes no state to its rack, so it cannot contribute one to the room or
    the site either. That is the property worth having — the alternative is remembering to
    filter at three levels and forgetting at one.
    """
    racks, rooms, sites = {}, {}, {}
    for site, rooms_seen in walk(store, said, allowed):
        s_states = []
        for room, racks_seen in rooms_seen:
            r_states = []
            for rack, mine in racks_seen:
                roll = rack_roll(mine, statuses)
                racks[rack['uid']] = roll
                r_states.append(roll['state'])
            rooms[room['uid']] = {'state': worst(r_states), 'racks': len(r_states)}
            s_states.append(rooms[room['uid']]['state'])
        sites[site['uid']] = {'state': worst(s_states), 'rooms': len(s_states)}
    return {'rack': racks, 'room': rooms, 'site': sites}


def reachable(store, said, allowed) -> dict | None:
    """A qué sedes, salas y racks llega este lector: ``{'site': set, 'room': set, 'rack': set}``.

    ``None`` cuando lo ve todo — y `None` no es lo mismo que tres conjuntos vacíos, igual que en
    `visible_orgs`: el primero es «no hay nada que estrechar» y el segundo «no llega a nada».

    Lo que devuelve NO es lo que puede ver: es lo que **contiene algo suyo**. Se une con lo
    visible en cada sitio que lo use, porque las dos mitades son razones distintas para llegar a
    la misma caja y ninguna sola basta:

    * solo lo visible deja al holding sin pantalla — la sede es del departamento, y la filial
      que tiene 2U dentro no ve ni el camino hasta ellas;
    * solo lo que contiene algo suyo escondería una sede entera vacía que sí es suya.
    """
    if allowed is None:
        return None
    sitios, salas, racks = set(), set(), set()
    for site in store.sites.list():
        for room in store.rooms_of(site['uid']):
            for rack in store.racks_of(room['uid']):
                if any(dcim_owners.may_see(
                        dcim_owners.owner_of(store.chain_of('item', it['uid']), said), allowed)
                        for it in store.items_of(rack['uid'])):
                    racks.add(rack['uid'])
                    salas.add(room['uid'])
                    sitios.add(site['uid'])
    return {'site': sitios, 'room': salas, 'rack': racks}


def llega(reach, scope, uid) -> bool:
    """Si esta caja CONTIENE algo de quien mira. Solo eso, y nunca «lo ve».

    Falso cuando no hay conjuntos, y eso incluye el caso de quien lo ve todo: ahí `may_see` ya
    dice que sí, y hacer que esto también lo dijera daría **dos significados a `None`** —«ve
    todo» y «este llamante no calculó el alcance»—. Con el segundo, cualquier filtro que no
    pasara los conjuntos dejaba pasar todo, que es exactamente lo que hizo la primera versión:
    los equipos ajenos de un rack compartido dejaron de salir anónimos y salieron enteros.
    """
    return bool(reach) and str(uid or '') in reach.get(scope, ())


def walk(store, said, allowed):
    """The whole tree, once, with the items this reader may see and nothing else.

    ``[(site, [(room, [(rack, [item, …]), …]), …]), …]``.

    Its own function because two screens need the same walk with the same visibility rule —
    the tree's badges and the board — and two copies of "may this reader see this item" are two
    places for that rule to drift. The day they drifted, the two screens would disagree about
    the same fleet and both would look right.

    A site, a room or a rack this reader may not see is simply NOT WALKED — the same rule the
    listing applies, because a board that counted a site the tree does not show would be two
    screens disagreeing about the same fleet.

    Visibility is applied at the LEAVES and rolls up on its own: an item the caller may not see
    contributes nothing to its rack, so it can contribute nothing to the room or the site.
    """
    reach = reachable(store, said, allowed)

    def mio(scope, uid):
        # O lo ve, o contiene algo suyo. Las dos mitades: sin la segunda, el cuadro de una
        # filial del holding sale vacío aunque tenga equipos en la sala de al lado.
        return dcim_owners.may_see(
            dcim_owners.owner_of(store.chain_of(scope, uid), said), allowed)             or llega(reach, scope, uid)

    out = []
    for site in store.sites.list():
        if not mio('site', site['uid']):
            continue
        rooms = []
        for room in store.rooms_of(site['uid']):
            if not mio('room', room['uid']):
                continue
            racks = []
            for rack in store.racks_of(room['uid']):
                if not mio('rack', rack['uid']):
                    continue
                mine = [item for item in store.items_of(rack['uid'])
                        if mio('item', item['uid'])]
                racks.append((rack, mine))
            rooms.append((room, racks))
        out.append((site, rooms))
    return out


def board(store, statuses, said, allowed, orgs=None) -> dict:
    """What is wrong, and **how to get to it**.

    ``{'sites': [...], 'orgs': [...], 'trouble': [...], 'totals': {...}}``.

    A panel that says "three things are wrong" without saying which forces somebody to go and
    find them, and finding them is the work this was supposed to save. So `trouble` is not a
    count: it is the path — site › room › rack › U — to each thing that is wrong, which is what
    one person reads down the phone while the other walks towards the cabinet.

    Worst first, and capped: a fleet where two hundred things are down needs the first twenty
    and a number, not two hundred rows nobody will read. The cap is SAID in the answer rather
    than left as a shorter list that looks complete.

    The per-company breakdown counts what the reader may see, like everything else here — in a
    shared rack, a company sees its own rows and the count of the others' occupied units, never
    what is in them.
    """
    names = {o['uid']: o.get('name') or o['uid'] for o in (orgs or ())}
    sites, trouble, per_org = [], [], {}

    for site, rooms in walk(store, said, allowed):
        s_states, s_roll = [], {'total': 0, 'bad': 0, 'unwatched': 0}
        n_rooms = n_racks = 0
        for room, racks in rooms:
            n_rooms += 1
            for rack, mine in racks:
                n_racks += 1
                roll = rack_roll(mine, statuses)
                s_states.append(roll['state'])
                for k in ('total', 'bad', 'unwatched'):
                    s_roll[k] += roll[k]
                for item in mine:
                    state = item_state(item, statuses)
                    org = dcim_owners.owner_of(store.chain_of('item', item['uid']), said)
                    tally = per_org.setdefault(
                        org or '', {'uid': org or '', 'name': names.get(org, ''),
                                    'total': 0, 'bad': 0, 'unwatched': 0})
                    tally['total'] += 1
                    if state in ('error', 'warning'):
                        tally['bad'] += 1
                    elif not state:
                        tally['unwatched'] += 1
                    if state not in ('error', 'warning'):
                        continue
                    trouble.append({
                        'state': state,
                        'site': site.get('name') or site['uid'], 'site_uid': site['uid'],
                        'room': room.get('name') or room['uid'], 'room_uid': room['uid'],
                        'rack': rack.get('name') or rack['uid'], 'rack_uid': rack['uid'],
                        'u': item.get('u_start'), 'face': item.get('face') or 'full',
                        'name': item.get('label') or '', 'host_uid': item.get('host_uid') or '',
                        'item_uid': item['uid'],
                    })
        sites.append({
            'uid': site['uid'], 'name': site.get('name') or site['uid'],
            'state': worst(s_states), 'rooms': n_rooms, 'racks': n_racks,
            'pos_x': site.get('pos_x'), 'pos_y': site.get('pos_y'),
            'lat': site.get('lat'), 'lon': site.get('lon'),
            # La zona horaria viaja con la sede: la hora local se pinta en el navegador —que
            # sabe convertirla y no necesita preguntar— y sin el nombre no hay nada que
            # convertir. «Son las 4 de la mañana allí» es lo que decide si se llama ahora.
            'timezone': str(site.get('timezone') or ''),
            'total': s_roll['total'], 'bad': s_roll['bad'],
            'unwatched': s_roll['unwatched'],
            'ok': s_roll['total'] - s_roll['bad'] - s_roll['unwatched'],
        })

    # Lo peor primero, con el MISMO orden que usa `worst`: dos ideas de «peor» en el mismo
    # dominio acaban en dos pantallas que discrepan sobre cuál de dos máquinas está peor.
    trouble.sort(key=lambda r: (-_RANK.get(r['state'], 0), r['site'], r['rack'], r['u'] or 0))
    totals = {k: sum(x[k] for x in sites) for k in ('total', 'bad', 'unwatched', 'ok')}
    totals['sites'] = len(sites)
    totals['trouble'] = len(trouble)
    return {'sites': sites,
            'orgs': sorted(per_org.values(), key=lambda o: (-o['bad'], o['name'], o['uid'])),
            # Dicho, no recortado en silencio: una lista más corta que lo que hay parece
            # completa, y quien la lee da por resuelto lo que ni siquiera ha visto.
            'trouble': trouble[:BOARD_TROUBLE_CAP], 'trouble_total': len(trouble),
            'capped': len(trouble) > BOARD_TROUBLE_CAP,
            'totals': totals}


# ══ La potencia ═════════════════════════════════════════════════════════════════════════
#
# La pregunta que justifica todo esto no es cuántos vatios hay. Es: **si se cae la rama A, ¿qué
# se apaga?** Una sala con dos SAI, dos regletas por armario y todo el equipo con dos fuentes
# está bien — hasta que alguien enchufa el segundo cable de un servidor en la regleta de al lado
# porque la suya estaba llena, y durante dos años nadie lo sabe.

#: Por encima de esto, una regleta está demasiado cargada para que se caiga su pareja: si la
#: rama B se lleva lo de las dos, pasa del 100 %. No es una norma eléctrica, es la aritmética de
#: la redundancia — y por eso está aquí y no escondida en una comparación.
PDU_SAFE_LOAD = 0.45


def power_of_rack(pdus, feeds, items, statuses=None, owners=None) -> dict:
    """Cómo está alimentado un armario: por regleta, por equipo, y qué falta.

    ``{'pdus': [...], 'items': [...], 'warnings': [...], 'by_org': {...}}``.

    Las tres cosas que contesta, en orden de para qué se abre esta pantalla:

    1. **Qué se apaga si se cae una rama.** Un equipo alimentado por una sola rama es un equipo
       que se apaga, y da igual que tenga dos fuentes: lo que cuenta es de dónde comen.
    2. **Cuántas tomas quedan**, que es lo que se pregunta delante del armario con un equipo
       nuevo en las manos.
    3. **Cuánto se ha declarado frente a lo que aguanta** — y, cuando la regleta es un host que
       contesta, frente a lo que está dando de verdad.

    Lo declarado y lo medido no se corrigen el uno al otro. La placa de un servidor dice el
    máximo que puede pedir y una regleta dice lo que está pasando ahora: los dos son ciertos y
    su desacuerdo es el dato.
    """
    # `owners` es {uid de equipo → empresa}, YA RESUELTO por quien lo llama. Resuelto y no
    # crudo porque un equipo hereda el dueño de su armario, y volver a subir la cadena aquí
    # sería una segunda copia de esa regla — que es como dos pantallas acaban discrepando sobre
    # de quién es lo mismo.
    owners = owners or {}
    porcalle = {}
    for f in (feeds or ()):
        porcalle.setdefault(str(f.get('pdu_uid') or ''), []).append(f)
    por_item = {}
    for f in (feeds or ()):
        por_item.setdefault(str(f.get('item_uid') or ''), []).append(f)

    rama_de = {str(p['uid']): str(p.get('feed') or 'none') for p in (pdus or ())}
    nombre_de = {str(p['uid']): str(p.get('name') or p['uid']) for p in (pdus or ())}

    filas = []
    for p in (pdus or ()):
        mios = porcalle.get(str(p['uid']), [])
        declarado = sum(int(f.get('watts_said') or 0) for f in mios)
        cap = int(p.get('capacity_w') or 0)
        filas.append({
            'uid': p['uid'], 'name': nombre_de[str(p['uid'])],
            # De qué equipo del armario es, cuando lo es. Va en la respuesta porque la pantalla
            # tiene que saber cuáles de los equipos colocados están YA declarados para no
            # ofrecerlos otra vez: sin esto, la lista de «cuál es la regleta» ofrece la misma
            # dos veces y la segunda crea una regleta duplicada del mismo cacharro.
            'item_uid': str(p.get('item_uid') or ''),
            'feed': str(p.get('feed') or 'none'),
            'outlets': int(p.get('outlets') or 0),
            # Las tomas OCUPADAS son los cables, no los equipos: un equipo con dos cables en la
            # misma regleta ocupa dos tomas, y contar equipos diría que queda una de más.
            'used': len(mios),
            # CUÁLES están ocupadas, y no sólo cuántas. Sin esto, elegir toma es teclear un
            # número a ciegas y descubrir el choque —dos cables en la misma toma, que es
            # físicamente imposible— el día que alguien va a desenchufar uno y encuentra dos.
            # El 0 no cuenta: es «en esa regleta, no sé en cuál», y no ocupa ninguna.
            'outlets_used': sorted({int(f.get('outlet') or 0) for f in mios
                                    if int(f.get('outlet') or 0) > 0}),
            'free': max(0, int(p.get('outlets') or 0) - len(mios)),
            'watts_said': declarado,
            'capacity_w': cap,
            'load': round(declarado / cap, 3) if cap else None,
            'host_uid': str(p.get('host_uid') or ''),
            # Resuelto aquí y no en la pantalla: dos sitios decidiendo de qué color va una rama
            # acaban pintándola de dos colores distintos en dos vistas de lo mismo.
            'color': str(p.get('color') or '').strip()
                     or FEED_COLORS.get(str(p.get('feed') or 'none'), FEED_COLORS['none']),
            'state': item_state({'host_uid': p.get('host_uid')}, statuses or {}),
        })

    # Las regletas que YA están declaradas como tales: su equipo no es un consumidor. Una
    # regleta no se enchufa a sí misma, y listarla entre lo que come es pedirle un enchufe a lo
    # que da los enchufes.
    es_regleta = {str(p.get('item_uid') or '') for p in (pdus or ()) if p.get('item_uid')}

    # Y por equipo: de qué ramas come. Aquí es donde sale el hallazgo.
    por_equipo, avisos = [], []
    for it in (items or ()):
        if str(it.get('uid') or '') in es_regleta:
            continue
        uid = str(it.get('uid') or '')
        cables = por_item.get(uid, [])
        ramas = sorted({rama_de.get(str(c.get('pdu_uid') or ''), 'none') for c in cables})
        fila = {
            'uid': uid, 'label': it.get('label') or '',
            'u_start': it.get('u_start'), 'host_uid': str(it.get('host_uid') or ''),
            # Con el uid del CABLE: sin él, la pantalla puede enseñar de qué come un equipo
            # y no puede desenchufarlo, que es la mitad de para lo que se abre.
            # Con lo que hace de un cable de corriente una cosa inventariada, no sólo un
            # vínculo: su etiqueta, su número, de qué par de conectores es, cuánto mide y qué
            # haya que decir de él. Se guardaba y no volvía, que es la misma forma de fallo
            # que llevamos toda la semana persiguiendo — un dato que no viaja vale su valor
            # por defecto en la pantalla, y el respaldo parece que funciona.
            'feeds': [{'uid': str(c.get('uid') or ''),
                       'pdu': nombre_de.get(str(c.get('pdu_uid') or ''), ''),
                       'pdu_uid': str(c.get('pdu_uid') or ''),
                       'branch': rama_de.get(str(c.get('pdu_uid') or ''), 'none'),
                       'outlet': int(c.get('outlet') or 0),
                       'label': str(c.get('label') or ''),
                       'asset': str(c.get('asset') or ''),
                       'category': str(c.get('category') or ''),
                       'length_mm': int(c.get('length_mm') or 0),
                       'description': str(c.get('description') or ''),
                       'watts_said': int(c.get('watts_said') or 0)} for c in cables],
            'branches': [b for b in ramas if b != 'none'],
            'watts_said': sum(int(c.get('watts_said') or 0) for c in cables),
            'role': str(it.get('role') or ''),
        }
        por_equipo.append(fila)
        if not cables:
            # No es un fallo: un panel de parcheo no come. Es una pregunta, y por eso se dice
            # aparte de los avisos de verdad.
            continue
        if len(fila['branches']) < 2:
            avisos.append({'kind': 'single_branch', 'item': uid,
                           'label': fila['label'], 'branch': (fila['branches'] or [''])[0]})

    # Una regleta tan cargada que su pareja no podría con las dos. Es la aritmética de la
    # redundancia: tener dos ramas no sirve de nada si una sola no aguanta el total.
    for fila in filas:
        if fila['load'] is not None and fila['load'] > PDU_SAFE_LOAD:
            avisos.append({'kind': 'over_half', 'pdu': fila['uid'], 'label': fila['name'],
                           'load': fila['load']})

    # Las regletas que están COLOCADAS y no declaradas. Una regleta que ocupa un U es un equipo
    # del armario; una regleta donde se enchufa es una fila con ramas y tomas. Son la misma cosa
    # vista desde dos sitios, y hasta que alguien las une el panel no puede ofrecer como enchufe
    # la que se acaba de colocar — que es exactamente lo que espera quien acaba de colocarla.
    #
    # No se unen solas: declarar una regleta es decir de qué rama cuelga y cuántas tomas tiene, y
    # eso no está en el catálogo ni lo puede adivinar nadie. Lo que sí se puede es no dejar que
    # pase desapercibido.
    sin_declarar = [{'uid': str(it.get('uid') or ''),
                     'label': str(it.get('label') or ''),
                     'u_start': it.get('u_start')}
                    for it in (items or ())
                    if str(it.get('role') or '') == 'pdu' and str(it.get('uid') or '') not in es_regleta]

    # Y por sociedad, que en un holding es una línea de factura: el departamento opera la sala
    # y cobra por consumo. Solo cuenta lo que quien mira puede ver —los equipos ya vienen
    # filtrados— así que la filial ve su propia línea y nada más, que es lo que puede comprobar.
    por_org = {}
    for fila in por_equipo:
        org = str(owners.get(fila['uid'], '') or '')
        tally = por_org.setdefault(org, {'uid': org, 'watts_said': 0, 'items': 0})
        tally['watts_said'] += fila['watts_said']
        tally['items'] += 1

    return {'pdus': filas, 'items': por_equipo, 'warnings': avisos,
            'undeclared_pdus': sin_declarar,
            'watts_said': sum(f['watts_said'] for f in filas),
            'by_branch': {b: sum(f['watts_said'] for f in filas if f['feed'] == b)
                          for b in ('a', 'b', 'none')},
            'by_org': sorted(por_org.values(),
                             key=lambda o: (-o['watts_said'], o['uid']))}


# ══ El cableado, contra lo que se ve ════════════════════════════════════════════════════
#
# Aquí es donde el inventario deja de ser documentación. Un cable declarado no vale por sí solo:
# vale porque con él tenemos las DOS mitades. «El switch ve a este servidor por la Gi1/0/7» es un
# hecho aislado; con la etiqueta al lado es «y lo declarado dice que ese puerto va al panel B, así
# que o la etiqueta miente o alguien movió el latiguillo».
#
# Las tres cosas que pueden pasar, y ninguna de ellas es un error del panel:
#
# * **coincide** — declarado y visto, en los mismos puertos;
# * **no se ve** — declarado y LLDP no lo confirma. NO es necesariamente un fallo: entre los dos
#   extremos puede haber un panel de parcheo, que es pasivo y no aparece en ningún LLDP. Es una
#   pregunta, y se dice como pregunta;
# * **sin declarar** — LLDP ve un enlace entre dos máquinas que están en armarios y ningún cable
#   lo dice. Eso sí suele ser trabajo pendiente: alguien enchufó y no lo apuntó.


#: Cuántos tramos como mucho tiene una tirada. Ocho son un latiguillo, dos troncales de sala,
#: dos paneles de armario y sitio de sobra: más que eso no es una instalación, es un bucle
#: declarado por error, y un paseo sin tope sobre un bucle no termina.
_RUN_MAX = 8


def _port_map(cables) -> dict:
    """``{(equipo, boca): [(cable, desde, hacia), …]}`` — qué cables tocan cada boca.

    **Por BOCAS y no por equipos.** Un panel de veinticuatro posiciones no es un nudo donde todo
    lo que entra sale por cualquier sitio: lo que entra por la 12 sale por la 12, que es la misma
    posición vista por el otro lado. Andar por el panel entero daría por explicado cualquier par
    de cables que lo tocaran.

    Sin bocas escritas, todas las de un equipo son la misma —``('panel', '')``— y lo que sale es
    menos preciso, que es exactamente lo que se sabe cuando nadie las apuntó.

    En un sitio porque lo andan dos: el que confirma un enlace a través de un panel y el que
    contesta «¿de qué tirada es este cable?». Dos copias del mismo índice serían dos ideas de por
    dónde se puede pasar, y la segunda se separaría en el primer arreglo.
    """
    out: dict = {}
    for c in (cables or ()):
        a = (str(c.get('a_item') or ''), str(c.get('a_port') or '').strip())
        b = (str(c.get('b_item') or ''), str(c.get('b_port') or '').strip())
        if not a[0] or not b[0]:
            continue
        uid = str(c.get('uid') or '')
        out.setdefault(a, []).append((uid, a, b))
        out.setdefault(b, []).append((uid, b, a))
    return out


def _passable(items) -> dict:
    """``{equipo: si se puede atravesar}``.

    Atravesar un switch sería inventarse un cable: dos máquinas enchufadas al mismo switch no
    están enchufadas entre sí. Y un equipo del que nadie ha dicho el rol —o uno ajeno, que llega
    sin él— tampoco se atraviesa: no se puede afirmar un camino a través de algo que no se puede
    ni mirar.
    """
    return {str(i.get('uid') or ''): (str(i.get('role') or '') in ROLES_MUDOS
                                      and not i.get('foreign'))
            for i in (items or ())}


def _leg(uid, desde, hacia) -> dict:
    """Un tramo **en el sentido en que se recorre**, del origen al destino.

    En ese sentido y no en el que se guardó: un cable se declara desde el extremo que se tenía
    delante, así que la mitad de los tramos de una tirada están escritos al revés — y una traza
    que va «SRV → PP» y luego «SW → PP» no se puede leer.
    """
    return {'cable': uid, 'a_item': desde[0], 'a_port': desde[1],
            'b_item': hacia[0], 'b_port': hacia[1]}


#: Lo que un tramo lleva DEL CABLE que es. La pantalla lo sacaba de la lista que tenía cargada
#: —la de la pestaña del armario— y desde la sección de cableado esa lista no existe: la tirada
#: salía sin etiquetas, sin metros y sin colores, que es casi todo lo que distingue un tramo del
#: de al lado. Viaja con el tramo y se acabó la búsqueda.
_LEG_FIELDS = ('label', 'asset', 'kind', 'category', 'length_mm', 'color')


def with_cable(legs, cables) -> list:
    """Los tramos con lo que hay que saber del cable de cada uno pegado."""
    de = {str(c.get('uid') or ''): c for c in (cables or ())}
    return [dict(t, **{k: (de.get(t['cable'], {}) or {}).get(k) for k in _LEG_FIELDS})
            for t in (legs or ())]


def label_legs(legs, items) -> list:
    """Los tramos con el NOMBRE, el ROL y el SITIO de cada punta pegados.

    Una tirada que pasa por el panel del armario de al lado nombra equipos que la pantalla no
    tiene delante —sólo tiene los de su lista—, así que sin esto sale llena de identificadores,
    que es lo que ya se arregló en cuatro sitios de esta sección. Con el rol además del rótulo:
    la mitad de los paneles no está rotulada, y «Panel de parcheo» dice más que ocho letras de un
    uid. Y con el armario y la U, que es la dirección con la que alguien camina hasta allí.
    """
    # **Cómo se llama**, en el mismo orden que en todas las listas: lo rotulado, si no la
    # máquina, si no el modelo. Con la etiqueta sola, las dos puntas de una tirada salían con la
    # boca y nada más —«gigabitethernet11»— porque lo normal es no rotular un servidor que ya
    # tiene nombre de máquina. Quien llama pone `host_name` si puede resolverlo; donde no, la
    # pantalla lo completa con lo que tiene cargado.
    nombre = {str(i.get('uid') or ''): (i.get('label') or i.get('host_name')
                                        or i.get('type_name') or '')
              for i in (items or ())}
    rol = {str(i.get('uid') or ''): str(i.get('role') or '') for i in (items or ())}
    sitio = {str(i.get('uid') or ''): {'rack': str(i.get('rack_name') or ''),
                                       'rack_uid': str(i.get('rack_uid') or ''),
                                       'u': i.get('u_start')}
             for i in (items or ())}
    return [dict(t,
                 a_label=nombre.get(t['a_item'], ''), a_role=rol.get(t['a_item'], ''),
                 a_at=sitio.get(t['a_item'], {}),
                 b_label=nombre.get(t['b_item'], ''), b_role=rol.get(t['b_item'], ''),
                 b_at=sitio.get(t['b_item'], {}))
            for t in (legs or ())]


def run_of(cable_uid, cables, items) -> dict:
    """``{'ends': [equipo, equipo], 'legs': [tramo, …]}`` — **la tirada de este cable**.

    Un enlace que atraviesa un panel son tres cables y una tirada, y la ficha de uno de los tres
    enseñaba ese cable solo: «del panel A boca 12 al panel B boca 12», que no dice de dónde viene
    ni a dónde va. La pregunta que se hace delante del armario con el latiguillo en la mano es la
    otra — de qué tirada forma parte esto y en qué posición está—, y para contestarla había que
    ir cable a cable reconstruyéndola de cabeza.

    **Es un hecho DECLARADO, no una confirmación.** El camino que dibuja la pestaña de un armario
    sale de cruzar lo declarado con lo que los dispositivos ven, así que una tirada que nadie
    confirma —dos paneles y un latiguillo, sin LLDP de por medio— no salía en ninguna parte
    aunque estuviera escrita entera. Esto se lee sólo de lo declarado: contesta también donde no
    hay nada que confirmar, que es media instalación.

    Se anda hacia los dos lados desde el cable, y **se para en lo que no es un panel**: un equipo
    de verdad termina la tirada, y también la termina una boca donde no sigue nada. Si de una
    boca salen dos cables además del que llega, se para ahí: eso no es una tirada, es un dato
    torcido, y elegir uno de los dos sería dibujar un camino que nadie ha declarado.
    """
    uid = str(cable_uid or '')
    cual = next((c for c in (cables or ()) if str(c.get('uid') or '') == uid), None)
    if not cual:
        return {}
    en_boca, pasa = _port_map(cables), _passable(items)
    a = (str(cual.get('a_item') or ''), str(cual.get('a_port') or '').strip())
    b = (str(cual.get('b_item') or ''), str(cual.get('b_port') or '').strip())
    if not a[0] or not b[0]:
        return {}
    legs = [_leg(uid, a, b)]

    def _sigue(boca, usados):
        """El único cable que continúa por esa boca, o `None`."""
        if not pasa.get(boca[0]):
            return None
        otros = [x for x in en_boca.get(boca, ()) if x[0] not in usados]
        return otros[0] if len(otros) == 1 else None

    # Hacia delante, y luego hacia atrás dándole la vuelta a cada tramo: una tirada se lee de
    # punta a punta, y una lista que empieza por el medio obliga a ordenarla de cabeza.
    for adelante in (True, False):
        # Con tope: una tirada de más de esto no es una instalación, es un bucle declarado por
        # error — y un paseo sin tope sobre un bucle no termina.
        while len(legs) < _RUN_MAX:
            punta = (legs[-1]['b_item'], legs[-1]['b_port']) if adelante \
                else (legs[0]['a_item'], legs[0]['a_port'])
            paso = _sigue(punta, {t['cable'] for t in legs})
            if not paso:
                break
            otro_uid, desde, hacia = paso
            if adelante:
                legs.append(_leg(otro_uid, desde, hacia))
            else:
                legs.insert(0, _leg(otro_uid, hacia, desde))
    # **La misma tirada se lee igual desde cualquiera de sus tramos.** Sin esto, el sentido lo
    # decidía por qué cable se hubiera preguntado: la ficha del latiguillo la enseñaba
    # «servidor → switch» y la del troncal «switch → servidor». Es la misma tirada, y dos
    # dibujos distintos de lo mismo hacen dudar de si son dos.
    #
    # Primero el extremo que ES una máquina cuando sólo uno lo es —una tirada se lee desde donde
    # hay algo que mirar— y, cuando eso no decide, por identificador: hace falta una regla
    # estable, y cualquiera vale mientras sea siempre la misma.
    host_de = {str(i.get('uid') or ''): str(i.get('host_uid') or '') for i in (items or ())}
    ini, fin = legs[0]['a_item'], legs[-1]['b_item']
    mio, suyo = bool(host_de.get(ini)), bool(host_de.get(fin))
    if (suyo and not mio) or (mio == suyo and fin < ini):
        legs = [{'cable': t['cable'], 'a_item': t['b_item'], 'a_port': t['b_port'],
                 'b_item': t['a_item'], 'b_port': t['a_port']} for t in reversed(legs)]
    return {'ends': [legs[0]['a_item'], legs[-1]['b_item']], 'legs': legs}


def _through_passive(cables, items) -> dict:
    """``{(máquina, máquina): [tramo, …]}`` — caminos que pasan SÓLO por equipos pasivos.

    Cada tramo es ``{'cable', 'a_item', 'a_port', 'b_item', 'b_port'}`` **en el sentido en que se
    recorre**, del origen al destino. En ese sentido y no en el que se guardó: un cable se
    declara desde el extremo que se tenía delante, así que la mitad de los tramos de un camino
    están escritos al revés — y una traza que va «SRV → PP» y luego «SW → PP» no se puede leer.

    Un enlace que atraviesa un panel de parcheo son **tres cables y un camino**: el latiguillo
    del servidor al panel, el enlace fijo entre los dos paneles, y el latiguillo del otro panel
    al switch. Los tres se declaran por separado, porque los tres son cables que alguien puede
    desenchufar — y ninguno de los tres se puede confirmar solo, porque un panel es un trozo de
    metal que no habla.

    Lo que sí se puede confirmar es el CAMINO. El servidor y el switch se ven por LLDP a través
    del panel, y sin esto ese enlace salía como «sin declarar» estando declarado en tres tramos:
    la lista de trabajo pendiente incluía trabajo ya hecho, que es la forma más rápida de que
    nadie vuelva a mirarla.

    **Se anda por BOCAS y no por equipos.** Un panel de veinticuatro posiciones no es un nudo
    donde todo lo que entra sale por cualquier sitio: lo que entra por la 12 sale por la 12, que
    es la misma posición vista por el otro lado. Andar por el panel entero daría por explicado
    cualquier par de cables que lo tocaran, y entonces «confirmado» dejaría de querer decir nada.

    Y por eso un **puente** —un latiguillo de la boca 25 a la 17 del mismo panel— encaja sin
    ninguna regla nueva: es un cable como los demás, y andando por bocas lleva de una posición a
    la otra igual que cualquier otro tramo.

    Sin bocas escritas, todas las de un panel son la misma —`('panel', '')`— y el camino vuelve
    a ser el de antes: menos preciso, que es exactamente lo que se sabe cuando nadie las apuntó.

    **Sólo a través de pasivos.** Atravesar un switch sería inventarse un cable: dos máquinas
    enchufadas al mismo switch no están enchufadas entre sí. Y un equipo del que nadie ha dicho
    el rol —o uno ajeno, que llega sin él— tampoco se atraviesa: no se puede confirmar un camino
    a través de algo que no se puede ni mirar.
    """
    host_de = {str(i.get('uid') or ''): str(i.get('host_uid') or '') for i in (items or ())}
    pasa = _passable(items)
    en_boca = _port_map(cables)
    out: dict = {}
    for origen, ha in host_de.items():
        if not ha:
            continue
        # En anchura desde todas las bocas de la máquina, con el camino RECORRIDO a cuestas: lo
        # que se marca al final son los tramos, porque es cada uno el que queda confirmado por
        # formar parte de un camino que alguien ve entero.
        cola = [(hacia, [_leg(uid, desde, hacia)], 0)
                for boca, salidas in en_boca.items() if boca[0] == origen
                for uid, desde, hacia in salidas]
        visitado = set()
        while cola:
            boca, camino, saltos = cola.pop(0)
            if boca in visitado:
                continue
            visitado.add(boca)
            hb = host_de.get(boca[0], '')
            if hb:
                # Un cable directo entre dos máquinas ya lo casa la comprobación de siempre; lo
                # que aquí interesa es lo que pasa POR algo.
                if saltos and ha != hb:
                    out.setdefault(tuple(sorted((ha, hb))), list(camino))
                continue
            if not pasa.get(boca[0]):
                continue                       # ni un switch ni algo sin rol: no se atraviesa
            usados = {t['cable'] for t in camino}
            for uid, desde, hacia in en_boca.get(boca, ()):
                if uid not in usados:
                    cola.append((hacia, camino + [_leg(uid, desde, hacia)], saltos + 1))
    return out


def cable_check(cables, items, edges=None) -> dict:
    """Lo declarado contra lo que los dispositivos dicen ver.

    ``{'cables': [...], 'undeclared': [...], 'counts': {...}}``.

    *edges* son las aristas del mapa de infraestructura —las de `kind == 'lldp'`, que son las que
    un dispositivo ha visto de verdad— y *items* los equipos que dan sentido a un uid: de ellos sale
    a qué máquina corresponde cada extremo.

    **Un cable cuyos extremos no son máquinas no se juzga.** Un latiguillo de un servidor a un
    panel de parcheo no puede confirmarlo nadie: el panel es un trozo de metal. Marcarlo como «no
    se ve» sería llenar la pantalla de avisos imposibles de resolver, que es la forma más rápida
    de que nadie vuelva a mirarla.
    """
    host_de = {str(i.get('uid') or ''): str(i.get('host_uid') or '') for i in (items or ())}
    nombre_de = {str(i.get('uid') or ''): (i.get('label') or '') for i in (items or ())}
    rol_de = {str(i.get('uid') or ''): str(i.get('role') or '') for i in (items or ())}
    # Dónde está cada punta. Un camino sale del armario abierto —el panel vive en el de
    # patcheo— así que «PP-A 25» no dice dónde hay que ir: hacen falta el armario y la U, que
    # es la dirección con la que alguien camina hasta allí.
    sitio_de = {str(i.get('uid') or ''): {'rack': str(i.get('rack_name') or ''),
                                          'rack_uid': str(i.get('rack_uid') or ''),
                                          'u': i.get('u_start')}
                for i in (items or ())}
    etiqueta = [dict(c,
                     a_label=nombre_de.get(str(c.get('a_item') or ''), ''),
                     b_label=nombre_de.get(str(c.get('b_item') or ''), ''))
                for c in (cables or ())]
    # `None` es **no se ha preguntado**; `[]` es «se ha preguntado y no se ve nada». No es una
    # sutileza: sin esa diferencia, la lista rápida —la que sale mientras el mapa de la flota se
    # arma— saldría entera diciendo «no se ve», que es un veredicto, y de los peores: manda a
    # buscar un cable que está bien porque todavía nadie ha mirado. Es la misma forma de fallo
    # que un 403 contado como «el dispositivo no ha dicho nada».
    if edges is None:
        return {'cables': etiqueta, 'undeclared': [], 'counts': {}, 'checked': False}
    # Lo que se ve, indexado por el par de máquinas. El par va ordenado porque estar enchufados
    # es simétrico: quién es «el primero» no es un hecho del cable.
    visto = {}
    for e in (edges or ()):
        if str(e.get('kind') or '') != 'lldp':
            continue
        par = tuple(sorted((str(e.get('from') or ''), str(e.get('to') or ''))))
        visto[par] = e

    # Los caminos que pasan por un panel, ANTES de juzgar nada. Un enlace explicado por tres
    # tramos declarados no está sin declarar, y cada uno de esos tramos queda confirmado por el
    # camino aunque él solo no pudiera confirmarse nunca.
    caminos = _through_passive(cables, items)
    filas, casados = [], set()
    # Casados por el camino: el par se ve y hay tramos declarados que lo explican. Y el camino
    # entero viaja con la respuesta: «pasa por un panel» sin decir por CUÁL ni por qué boca
    # obliga a reconstruirlo a mano cable a cable, que es la pregunta que se hace delante del
    # armario con el latiguillo en la mano.
    por_camino: dict = {}
    trazas = []
    for par, tramos in sorted(caminos.items()):
        if par not in visto:
            continue
        casados.add(par)
        i = len(trazas)
        # Con el NOMBRE de cada punta pegado al tramo. Un camino que pasa por el panel del
        # armario de al lado nombra equipos que la pantalla no tiene delante —sólo tiene los de
        # su armario— así que sin esto la traza sale llena de identificadores, que es lo que se
        # arregló ya en cuatro sitios de esta misma sección. Con el rol además del rótulo: la
        # mitad de los paneles no está rotulada, y «Panel de parcheo» dice más que ocho letras
        # de un uid.
        trazas.append({'ends': list(par),
                       'legs': with_cable(label_legs(tramos, items), cables)})
        for t in tramos:
            por_camino.setdefault(t['cable'], []).append(i)
    for c in (cables or ()):
        a, b = str(c.get('a_item') or ''), str(c.get('b_item') or '')
        ha, hb = host_de.get(a, ''), host_de.get(b, '')
        fila = dict(c)
        fila['a_label'] = nombre_de.get(a, '')
        fila['b_label'] = nombre_de.get(b, '')
        if not ha or not hb:
            # Un extremo pasivo. Él solo no lo puede confirmar nadie —un panel es un trozo de
            # metal— pero el CAMINO del que forma parte sí, y entonces se dice: es la diferencia
            # entre «esto no se puede comprobar» y «esto está comprobado».
            suyos = por_camino.get(str(c.get('uid') or ''), ())
            fila['seen'] = 'via' if suyos else 'passive'
            if suyos:
                fila['via'] = len(suyos)
                # De qué caminos forma parte, para poder enseñarlos enteros desde su ficha.
                fila['paths'] = list(suyos)
            filas.append(fila)
            continue
        par = tuple(sorted((ha, hb)))
        arista = visto.get(par)
        if not arista:
            fila['seen'] = 'unseen'
        else:
            casados.add(par)
            fila['seen'] = 'seen'
            # De cuántos enlaces habla esta fila. Un agregado de cuatro puertos entre el router y
            # el switch es UN cable declarado y CUATRO latiguillos, y la fila decía «coincide» sin
            # dar ninguna pista de eso: el día que se caiga uno de los cuatro, la pantalla que
            # existe para contarlo sigue en verde.
            fila['bundle'] = int(arista.get('bundle') or 1)
            # Y si los puertos que dijo el dispositivo no incluyen los declarados, se dice: es el
            # caso de «alguien movió el latiguillo y no cambió la etiqueta», que es exactamente
            # lo que esta pantalla existe para encontrar.
            dichos = {str(p or '').lower()
                      for lado in (arista.get('ports') or {}).values()
                      for p in (lado if isinstance(lado, (list, tuple)) else [lado])}
            declarados = {str(c.get('a_port') or '').lower(),
                          str(c.get('b_port') or '').lower()} - {''}
            # Las bocas que los dispositivos nombran, **siempre** y no sólo cuando no cuadran:
            # es lo único que puede decir de qué cuatro puertos habla un agregado, y la ficha del
            # cable no tiene otro sitio de donde sacarlo. La tabla las enseña sólo cuando
            # contradicen a lo declarado, que es cuando significan algo de un vistazo.
            fila['ports_seen'] = sorted(dichos)
            if declarados and dichos and not (declarados & dichos):
                fila['seen'] = 'other_port'
        filas.append(fila)

    # Y al revés: lo que se ve y nadie declaró. Solo entre máquinas que están en un armario —un
    # enlace a un portátil de alguien no es cableado de sala y llenaría la lista de ruido.
    en_rack = {h for h in host_de.values() if h}
    # De vuelta: de qué EQUIPO es cada máquina. Sin esto, un enlace descubierto sólo se puede
    # mirar — un cable se declara entre dos equipos del armario, no entre dos máquinas, y
    # traducir uno en otro en la pantalla sería una segunda copia de este mismo diccionario.
    #
    # El primero que aparezca: una máquina puede estar enganchada a dos equipos si alguien se
    # equivocó, y elegir el primero es tan bueno como cualquiera cuando ya hay un error escrito.
    item_de: dict = {}
    for uid_item, host in host_de.items():
        if host:
            item_de.setdefault(host, uid_item)
    sin_declarar = []
    for par, arista in visto.items():
        if par in casados or not (par[0] in en_rack and par[1] in en_rack):
            continue
        puertos = arista.get('ports') or {}

        def _boca(host, _p=puertos):
            """El nombre de puerto que ese lado dijo, si dijo uno solo que valga."""
            v = _p.get(host)
            if isinstance(v, (list, tuple)):
                v = v[0] if len(v) == 1 else ''
            return str(v or '')

        sin_declarar.append({'from': par[0], 'to': par[1],
                             'ports': puertos,
                             # Listo para declararlo de un clic. **Una propuesta**: lo que manda
                             # es lo que alguien apunta, y el descubrimiento sirve para no
                             # teclearlo y para avisar cuando deja de coincidir. Rellenar la
                             # ficha a mano copiando de la fila de arriba es la forma más
                             # segura de que nadie la rellene.
                             'a_item': item_de.get(par[0], ''),
                             'b_item': item_de.get(par[1], ''),
                             'a_port': _boca(par[0]),
                             'b_port': _boca(par[1]),
                             'bundle': arista.get('bundle') or 1})

    cuenta = {estado: len([f for f in filas if f['seen'] == estado])
              for estado in ('seen', 'unseen', 'other_port', 'passive', 'via')}
    cuenta['undeclared'] = len(sin_declarar)
    return {'cables': filas, 'undeclared': sin_declarar, 'counts': cuenta, 'checked': True,
            'paths': trazas}


# ══ Los enlaces entre sedes ═════════════════════════════════════════════════════════════
#
# La misma pregunta que en la potencia, un nivel más arriba: **si se cae este enlace, ¿qué sede
# se queda sola?** Y se rompe igual de silenciosamente — dos circuitos contratados a dos
# operadores que resultan ir por la misma zanja, o una delegación con un solo camino real que
# nadie notó porque en el mapa hay dos líneas y una de ellas es una VPN sobre la otra.


def links_roll(links, sites, item_state_by_uid=None) -> dict:
    """Los enlaces con su estado, y las sedes que dependen de uno solo.

    ``{'links': [...], 'warnings': [...]}``.

    **El estado de un enlace es el de los equipos que lo terminan.** Un circuito no tiene estado
    —es un contrato— y el router que lo termina sí. Sin ningún extremo enlazado a un equipo, el
    enlace no sale ni bien ni mal: sale sin vigilar, que es lo que es.

    Dos hallazgos, y los dos son de los que no dan ningún error:

    * **una sede con un solo enlace** — se queda incomunicada cuando ese caiga, y en el mapa se
      ve perfectamente porque una línea es una línea;
    * **dos enlaces por el mismo camino o el mismo operador** — que es redundancia sobre el
      papel y ninguna el día que una excavadora pasa por la zanja. Se dice solo cuando alguien
      escribió el camino o el operador: adivinarlo sería inventarse un aviso.
    """
    estados = item_state_by_uid or {}
    nombre = {str(s.get('uid') or ''): (s.get('name') or s.get('uid') or '')
              for s in (sites or ())}

    filas, por_sede = [], {}
    for l in (links or ()):
        a, b = str(l.get('a_site') or ''), str(l.get('b_site') or '')
        puntas = [estados.get(str(l.get(lado) or ''), None)
                  for lado in ('a_item', 'b_item') if l.get(lado)]
        fila = dict(l)
        fila['a_name'] = nombre.get(a, a)
        fila['b_name'] = nombre.get(b, b)
        # Sin ninguna punta enlazada no se opina: no es que esté bien, es que nadie lo mira.
        fila['state'] = worst([e for e in puntas if e]) if puntas else ''
        filas.append(fila)
        for sede in (a, b):
            if sede:
                por_sede.setdefault(sede, []).append(fila)

    avisos = []
    for sede, suyos in sorted(por_sede.items()):
        if len(suyos) == 1:
            avisos.append({'kind': 'single_link', 'site': sede,
                           'label': nombre.get(sede, sede),
                           'link': suyos[0].get('label') or suyos[0].get('circuit_id') or ''})
            continue
        # Dos o más: ¿son caminos de verdad? Solo se juzga lo que alguien escribió — un aviso
        # sacado de un campo vacío es un aviso inventado, y esos enseñan a ignorar la pantalla.
        for campo, clase in (('path', 'same_path'), ('provider', 'same_provider')):
            visto = {}
            for x in suyos:
                valor = str(x.get(campo) or '').strip().lower()
                if valor:
                    visto.setdefault(valor, []).append(x)
            for valor, grupo in visto.items():
                if len(grupo) == len(suyos) and len(grupo) > 1:
                    avisos.append({'kind': clase, 'site': sede,
                                   'label': nombre.get(sede, sede), 'value': valor,
                                   'count': len(grupo)})
    return {'links': filas, 'warnings': avisos}


# ══ Previsión: dónde cabe esto ══════════════════════════════════════════════════════════
#
# Es lo que todo lo anterior hace posible. Un armario tiene U libres, tomas libres, vatios de
# margen y fondo — y decir que algo cabe exige las cuatro, porque falla la que falta. La U es la
# que más engaña: **doce U libres no son un hueco de doce**. Doce U sueltas por todo el armario
# no admiten un servidor de 2U, y el número «12» parece una respuesta y no lo es.


def role_hint(tipo) -> str:
    """Qué clase de dispositivo **parece** un modelo del catálogo, a partir de lo que trae.

    Propone; no escribe. Es la misma regla que el resto del catálogo en este panel: la
    biblioteca no dice el rol en ninguna parte, así que esto lo deduce de los puertos —y una
    deducción escrita en la base de datos como si fuera un hecho es exactamente lo que este
    dominio evita.

    Las señales son fuertes y pocas a propósito. Un dispositivo con tomas de corriente y sin
    interfaces reparte corriente; uno con puertos por delante y por detrás y sin alimentación es
    un panel de parcheo (no lo alimenta nadie porque no lo necesita); uno con bahías de
    dispositivo es un chasis. Lo que no encaja en ninguna sale vacío, que es «no lo sé» y no
    `other`, que sería una respuesta.
    """
    if not tipo:
        return ''
    # La deducción vive en el catálogo, que es quien la guarda al importar. Aquí se traduce a
    # lo que un ITEM puede ser: un armario no se mete dentro de un armario, y un módulo no
    # ocupa U, así que ninguno de los dos es una sugerencia válida para colocar.
    guardado = str(tipo.get('kind') or '')
    if guardado:
        return guardado if guardado in ITEM_ROLES else ''
    puertos = tipo.get('ports') if isinstance(tipo.get('ports'), dict) else {}
    if isinstance(tipo.get('ports'), str):
        try:
            import json as _json                                 # noqa: PLC0415
            puertos = _json.loads(tipo['ports']) or {}
        except Exception:                       # pylint: disable=broad-except
            puertos = {}
    tiene = lambda k: bool(puertos.get(k))      # noqa: E731
    alimentado = str(tipo.get('is_powered', 1)) not in ('0', 'False', 'false')

    if tiene('power-outlets') and not tiene('interfaces'):
        return 'pdu'
    if (tiene('front-ports') or tiene('rear-ports')) and not tiene('interfaces')             and not alimentado:
        return 'patch_panel'
    if tiene('device-bays'):
        return 'server'                         # un chasis: lo que lleva dentro son servidores
    if tiene('interfaces'):
        # Muchas interfaces y consola: un conmutador. Pocas: una máquina con tarjetas de red.
        cuantas = sum(int(v or 0) for v in (puertos.get('interfaces') or {}).values())
        return 'switch' if cuantas >= 8 else 'server'
    return ''


def free_runs(libres) -> list:
    """Los TRAMOS seguidos de U libres, de mayor a menor.

    No un recuento. Un armario con doce U libres repartidas de una en una no admite nada de 2U,
    y «12 libres» es la respuesta que hace ir a alguien con un servidor en las manos hasta un
    armario donde no entra. Un tramo sí es una respuesta: dice cuánto cabe y desde qué U.
    """
    seguidas, tramos = sorted(int(u) for u in (libres or ())), []
    for u in seguidas:
        if tramos and u == tramos[-1]['start'] + tramos[-1]['size']:
            tramos[-1]['size'] += 1
        else:
            tramos.append({'start': u, 'size': 1})
    return sorted(tramos, key=lambda t: (-t['size'], t['start']))


def rack_capacity(rack, taken, pdus, feeds, statuses=None) -> dict:
    """Lo que le queda a un armario: hueco, tomas, vatios y fondo.

    Las cuatro juntas porque las cuatro tienen que dar que sí. Un armario con veinte U libres y
    sin una toma en la rama B no admite nada que tenga que estar alimentado por las dos, y decir
    «tiene sitio» sería cierto y useless.
    """
    libres = free_units(rack, taken)
    poder = power_of_rack(pdus, feeds, [], statuses)
    por_rama = {}
    for p in poder['pdus']:
        r = por_rama.setdefault(p['feed'], {'outlets': 0, 'watts_free': 0, 'known': False})
        r['outlets'] += p['free']
        if p['capacity_w']:
            r['known'] = True
            # El margen se mide contra la MITAD, como en toda esta sección: lo que se puede
            # añadir sin que la pareja deje de poder con las dos si esta se cae.
            r['watts_free'] += max(0, int(p['capacity_w'] * PDU_SAFE_LOAD) - p['watts_said'])
    return {
        'uid': (rack or {}).get('uid', ''), 'name': (rack or {}).get('name', ''),
        'runs': free_runs(libres['front']),
        'free_u': libres['count'], 'height': libres['height'],
        'branches': por_rama,
        'depths': rack_depths(rack),
    }


def where_fits(capacities, need, racks_by_uid=None) -> list:
    """Qué armarios admiten esto, y **por qué no** los que no.

    El «por qué no» es la mitad del valor. Una lista de los que sí valen deja a quien la lee sin
    saber si el armario de al lado está descartado por falta de sitio, de corriente o de fondo —
    y eso es lo que decide si la solución es mover un equipo, pedir una regleta o comprar otro
    armario. Tres problemas muy distintos con la misma pinta en una lista filtrada.

    *need* es ``{u_height, depth_mm, watts, branches}``: cuánto ocupa, cuánto mide de fondo,
    cuánto pide y de cuántas ramas tiene que comer. `branches` por defecto 2, porque lo normal
    es lo redundante — y porque un armario que no puede darle dos ramas a un servidor de dos
    fuentes no es un armario donde ese servidor deba ir.
    """
    alto = max(1, int((need or {}).get('u_height') or 1))
    fondo = int((need or {}).get('depth_mm') or 0)
    vatios = int((need or {}).get('watts') or 0)
    ramas = int((need or {}).get('branches') if (need or {}).get('branches') is not None else 2)

    out = []
    for cap in (capacities or ()):
        porques, hueco = [], None
        for tramo in cap['runs']:
            if tramo['size'] >= alto:
                hueco = tramo
                break
        if not hueco:
            porques.append({'why': 'no_room', 'free_u': cap['free_u'],
                            'best': cap['runs'][0]['size'] if cap['runs'] else 0})
        # Las ramas: se cuentan las que tienen alguna toma libre, no las regletas. Una rama con
        # dos regletas llenas y otra con una libre es UNA rama disponible, no tres.
        con_toma = [r for r, d in cap['branches'].items() if r != 'none' and d['outlets'] > 0]
        if len(con_toma) < ramas:
            porques.append({'why': 'no_outlets', 'need': ramas, 'have': len(con_toma)})
        if vatios:
            # Solo se descarta por vatios cuando alguien declaró la capacidad. Sin ella no se
            # sabe, y «no cabe porque no lo sé» es descartar un armario por una casilla vacía.
            escasas = [r for r in con_toma
                       if cap['branches'][r]['known']
                       and cap['branches'][r]['watts_free'] < vatios]
            if escasas:
                porques.append({'why': 'no_watts', 'need': vatios,
                                'branches': sorted(escasas)})
        if fondo:
            rack = (racks_by_uid or {}).get(cap['uid']) or {}
            prof = fits_depth(rack, fondo)
            if prof['known'] and not prof['fits']:
                porques.append({'why': prof['why'], 'spare': prof['spare']})
        out.append({'uid': cap['uid'], 'name': cap['name'], 'fits': not porques,
                    'at_u': (hueco or {}).get('start'), 'run': (hueco or {}).get('size'),
                    'free_u': cap['free_u'], 'reasons': porques})
    # Los que valen primero, y entre ellos el que deja el hueco más ajustado: meter un 1U en el
    # tramo de veinte es gastar el único sitio donde luego cabrá un chasis.
    out.sort(key=lambda r: (not r['fits'], r['run'] or 999, -(r['free_u'] or 0)))
    return out


# ══ Las filas, y por dónde va el aire ═══════════════════════════════════════════════════
#
# Una fila declarada no es una etiqueta: de ella cuelga a qué pasillo da cada cara, y de ahí sale
# la pregunta que un plano no puede contestar mirando cajas — **¿el aire caliente de una fila
# entra en la aspiración de la de enfrente?**
#
# Eso no se deduce de la orientación de los racks. Dos filas enfrentadas comparten pasillo frío
# porque alguien lo diseñó así, y dos filas mirando al mismo sitio pueden ser correctas o ser el
# error que hace que la segunda respire lo que expulsó la primera. Es una decisión, y por eso se
# declara.


def rows_roll(rows, racks) -> dict:
    """Las filas de una sala, con lo que tienen dentro y lo que no cuadra.

    ``{'rows': [...], 'loose': [...], 'warnings': [...]}``.

    *loose* son los racks que no están en ninguna fila. **No es un error**: el armario de
    comunicaciones de un rincón no está en ninguna fila y nunca lo estará. Sale aparte porque un
    plano que los mete en una fila inventada dice algo falso sobre el aire.
    """
    por_fila = {}
    for rack in (racks or ()):
        por_fila.setdefault(str(rack.get('row_uid') or ''), []).append(rack)

    filas = []
    for row in (rows or ()):
        uid = str(row.get('uid') or '')
        suyos = por_fila.get(uid, [])
        filas.append(dict(row, racks=len(suyos),
                          rack_uids=[r['uid'] for r in suyos]))

    avisos = []
    # Lo que respira una fila es lo que expulsa otra: el pasillo del que aspira una es el de
    # descarga de la otra. Es EL error de una sala mal ordenada y no se ve mirando el plano,
    # porque las cajas están perfectamente alineadas.
    for una in filas:
        aspira = str(una.get('front_aisle') or '').strip().lower()
        if not aspira:
            continue
        for otra in filas:
            if otra is una:
                continue
            if str(otra.get('rear_aisle') or '').strip().lower() == aspira:
                avisos.append({'kind': 'hot_intake', 'row': una['uid'],
                               'label': una.get('name') or '',
                               'other': otra.get('name') or '', 'aisle': una['front_aisle']})
    # Y una fila sin pasillos dichos no se juzga: no es que esté mal, es que nadie lo ha escrito.
    return {'rows': filas, 'loose': por_fila.get('', []), 'warnings': avisos}


# ══ La cadena aguas arriba ══════════════════════════════════════════════════════════════
#
# Las cuatro instalaciones que hay que poder decir son en realidad tres cadenas y un interruptor:
#
#     Cuadro → PDU
#     Cuadro → SAI → PDU
#     Cuadro → SAI → Cuadro → PDU        …y esa misma con el bypass echado: Cuadro → PDU
#
# La última no es una instalación distinta: es la anterior con el SAI fuera. Por eso el bypass no
# es otra cadena sino una marca en el nodo que se salta — y por eso se puede recorrer la misma
# cadena **dos veces**, con el bypass y sin él, que es lo que contesta «¿qué pierdo si lo echan?»
# antes de que lo echen.


def chain_up(sources, source_uid, *, honour_bypass=True) -> list:
    """La cadena desde una fuente hacia arriba, hasta la acometida.

    *honour_bypass* falso recorre la instalación **como si ningún bypass estuviera echado**, que
    es la otra mitad de la pregunta: no «por dónde va la corriente ahora» sino «por dónde iría si
    nadie hubiera tocado nada».

    Un ciclo —alguien declaró que A cuelga de B y B de A— termina la cadena en vez de colgar el
    panel. Es un dato equivocado, no un estado imposible: se dibuja lo que se pueda y ya.
    """
    por_uid = {str(s.get('uid') or ''): s for s in (sources or ())}
    salida, visto = [], set()
    uid = str(source_uid or '')
    while uid and uid in por_uid and uid not in visto:
        visto.add(uid)
        nodo = por_uid[uid]
        saltado = honour_bypass and bool(int(nodo.get('bypass') or 0))
        if not saltado:
            salida.append(nodo)
        uid = str(nodo.get('upstream_uid') or '')
    return salida


def power_path(sources, pdus) -> dict:
    """De qué cuelga cada regleta, ahora y con los bypass quitados.

    ``{'paths': {pdu_uid: {...}}, 'warnings': [...]}``.

    Dos hallazgos, y los dos son de los que no dan ningún error:

    * **una regleta que ahora mismo no pasa por ningún SAI**. Puede ser correcto —hay racks que
      no lo necesitan— o puede ser un bypass que alguien echó hace tres meses para una
      maniobra y nadie volvió a quitar. Lo que el panel puede decir con verdad es lo segundo:
      *sin el bypass sí pasaría por uno*, y eso convierte la duda en una frase;
    * **las dos ramas colgando del mismo SAI**. Dos regletas, dos ramas, dos colores… y un solo
      punto de fallo tres metros más arriba. Es exactamente el error que la redundancia dentro
      del armario esconde.
    """
    caminos, avisos = {}, []
    for pdu in (pdus or ()):
        uid = str(pdu.get('uid') or '')
        origen = str(pdu.get('source_uid') or '')
        if not origen:
            # Nadie lo ha dicho. Distinto de «no tiene»: media sala técnica cuelga de un cuadro
            # que nadie documentó, y decir que no tiene sería inventarse un hecho.
            caminos[uid] = {'known': False, 'now': [], 'clean': [], 'ups': []}
            continue
        ahora = chain_up(sources, origen)
        limpio = chain_up(sources, origen, honour_bypass=False)
        sais = [n['uid'] for n in ahora if str(n.get('kind')) == 'ups']
        caminos[uid] = {
            'known': True,
            'now': [{'uid': n['uid'], 'name': n.get('name') or '', 'kind': n.get('kind'),
                     'bypass': bool(int(n.get('bypass') or 0))} for n in ahora],
            'clean': [n['uid'] for n in limpio],
            'ups': sais,
        }
        if not sais and any(str(n.get('kind')) == 'ups' for n in limpio):
            avisos.append({'kind': 'on_bypass', 'pdu': uid,
                           'label': pdu.get('name') or '',
                           'ups': [n.get('name') or '' for n in limpio
                                   if str(n.get('kind')) == 'ups']})

    # Y las dos ramas de un mismo armario colgando del mismo SAI: dentro del rack se ve
    # perfectamente redundante, y el punto de fallo está tres metros más arriba.
    por_rack = {}
    for pdu in (pdus or ()):
        por_rack.setdefault(str(pdu.get('rack_uid') or ''), []).append(pdu)
    for rack, suyas in por_rack.items():
        ramas = {str(p.get('feed') or 'none') for p in suyas} - {'none'}
        if len(ramas) < 2:
            continue
        sais = [set(caminos.get(str(p.get('uid')), {}).get('ups') or ()) for p in suyas]
        comunes = set.intersection(*sais) if all(sais) else set()
        if comunes:
            avisos.append({'kind': 'same_ups', 'rack': rack,
                           'ups': sorted(comunes),
                           'labels': sorted(p.get('name') or '' for p in suyas)})
    return {'paths': caminos, 'warnings': avisos}
