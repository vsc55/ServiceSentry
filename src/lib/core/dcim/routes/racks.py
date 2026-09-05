#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Un armario por dentro: lo que ocupa cada U, lo que se le pone y dónde cabe.

El alzado, el cuadro de mando y las dos escrituras que mueven cosas de sitio. Colocar
una caja es lo que más se hace en esta sección, y por eso está solo.

Rutas:

    GET     /api/v1/dcim/board
    GET     /api/v1/dcim/fits
    GET     /api/v1/dcim/hosts
    POST    /api/v1/dcim/items
    PUT     /api/v1/dcim/items/<uid>
    DELETE  /api/v1/dcim/items/<uid>
    GET     /api/v1/dcim/items
    GET     /api/v1/dcim/items/<uid>/parts
    GET     /api/v1/dcim/media-dir
    GET     /api/v1/dcim/racks/<uid>/history
    GET     /api/v1/dcim/said
    POST    /api/v1/dcim/parts
    PUT     /api/v1/dcim/parts/<uid>
    DELETE  /api/v1/dcim/parts/<uid>
    GET     /api/v1/dcim/racks
    GET     /api/v1/dcim/racks/<uid>
"""

from __future__ import annotations

from flask import jsonify, request

from lib.core.dcim import builds as dcim_builds
from lib.core.dcim import catalog as dcim_catalog
from lib.core.dcim import media as dcim_media
from lib.core.dcim import owners as dcim_owners
from lib.core.dcim import rackrev as dcim_rackrev
from lib.core.dcim import service as dcim_svc
from lib.core.dcim import store as dcim_store
from lib.core.dcim.store import FACES, ITEM_ROLES, LINK_KINDS, PART_KINDS, PLACEMENTS
from lib.core.dcim.routes._common import _num, _without, scan_pages


def register(app, wa, C):
    """Las rutas de esta área. *C* es lo que comparten todas: los permisos y los ayudantes."""
    @app.route('/api/v1/dcim/fits', methods=['GET'])
    @C.view_req
    def api_dcim_fits():
        """Dónde cabe un equipo, y **por qué no** donde no cabe.

        El «por qué no» es la mitad del valor: una lista filtrada de los que valen deja a quien
        la lee sin saber si el armario de al lado está descartado por falta de sitio, de
        corriente o de fondo — y eso decide si la solución es mover un equipo, pedir una regleta
        o comprar otro armario. Tres problemas muy distintos con la misma pinta.

        Se recorren solo los armarios que este lector puede ver, y **la ocupación cuenta lo de
        todos**: la U 12 está ocupada aunque lo que la ocupe sea de otra sociedad, y decir que
        está libre mandaría a alguien con un servidor a un sitio donde no entra.
        """
        store = C.store()
        if not store:
            return jsonify({'racks': []})
        need = {
            'u_height': _num(request.args.get('u') or 1),
            'depth_mm': _num(request.args.get('depth') or 0),
            'watts': _num(request.args.get('watts') or 0),
            'branches': _num(request.args.get('branches')
                             if request.args.get('branches') is not None else 2),
        }
        said, allowed = store.owners_map(), C.seen()
        caps, por_uid = [], {}
        for site in store.sites.list():
            if not dcim_owners.may_see(C.owner_of(store, said, 'site', site['uid']), allowed):
                continue
            for room in store.rooms_of(site['uid']):
                if not dcim_owners.may_see(C.owner_of(store, said, 'room', room['uid']),
                                           allowed):
                    continue
                for rack in store.racks_of(room['uid']):
                    if not dcim_owners.may_see(C.owner_of(store, said, 'rack', rack['uid']),
                                               allowed):
                        continue
                    pdus = store.pdus_of(rack['uid'])
                    cap = dcim_svc.rack_capacity(rack, store.occupancy(rack['uid']), pdus,
                                                 store.feeds_of([p['uid'] for p in pdus]),
                                                 C.states())
                    cap['site'] = site.get('name') or site['uid']
                    cap['room'] = room.get('name') or room['uid']
                    caps.append(cap)
                    por_uid[rack['uid']] = rack
        filas = dcim_svc.where_fits(caps, need, por_uid)
        # De dónde es cada uno, para poder ir: un armario que vale y no se sabe en qué sala está
        # obliga a buscarlo, que es el trabajo que esto venía a ahorrar.
        donde = {c['uid']: (c['site'], c['room']) for c in caps}
        for fila in filas:
            fila['site'], fila['room'] = donde.get(fila['uid'], ('', ''))
        return jsonify({'racks': filas, 'need': need})

    @app.route('/api/v1/dcim/board', methods=['GET'])
    @C.view_req
    def api_dcim_board():
        """The board: what is wrong, and the path to each of them.

        Narrowed like every other read here — the counts, the per-company breakdown and the
        list of what is wrong all count what THIS reader may see. In a shared rack that means a
        subsidiary's board never says the department has a problem, which is right: it is not
        their problem and they cannot go and look at it.
        """
        store = C.store()
        if not store:
            return jsonify({'sites': [], 'orgs': [], 'trouble': [], 'totals': {}})
        out = dcim_svc.board(
            store, C.states(), store.owners_map(), C.seen(), store.orgs.list())
        # Con qué se dibuja el mapa. Viaja con el cuadro y no en una ruta aparte: es la misma
        # pantalla, y una petición más para dos cadenas es una petición más en cada apertura.
        # Y los enlaces entre sedes, con su estado y lo que se les ve mal. Viajan con el
        # cuadro porque se dibujan en el MISMO mapa: pedirlos aparte sería una petición más
        # para dibujar las líneas que unen las cajas que ya están puestas.
        visibles = {s['uid'] for s in out['sites']}
        enlaces = [l for l in store.links_of()
                   if str(l.get('a_site') or '') in visibles
                   and str(l.get('b_site') or '') in visibles]
        # El estado de un enlace es el de los equipos que lo terminan, y de esos solo se opina
        # sobre los que este lector puede ver: un router ajeno no le dice a nadie cómo está.
        por_item = {}
        for sitio in out['sites']:
            for sala in store.rooms_of(sitio['uid']):
                for rack in store.racks_of(sala['uid']):
                    for it in store.items_of(rack['uid']):
                        if dcim_owners.may_see(
                                C.owner_of(store, store.owners_map(), 'item', it['uid']),
                                C.seen()):
                            por_item[it['uid']] = dcim_svc.item_state(it, C.states())
        out.update(dcim_svc.links_roll(enlaces, out['sites'], por_item))
        out['link_kinds'] = list(LINK_KINDS)
        out['map'] = {
            'tiles': str(getattr(wa, '_DCIM_MAP_TILES', '') or ''),
            'attribution': str(getattr(wa, '_DCIM_MAP_ATTRIBUTION', '') or ''),
        }
        return jsonify(out)

    @app.route('/api/v1/dcim/media-dir', methods=['GET'])
    @wa._perm_required('config_edit')
    def api_dcim_media_dir():
        """Which folder the pictures actually go to.

        For the empty box in Configuration, which otherwise says "empty means the default" and
        leaves the operator to guess WHICH default: it depends on where the panel was installed,
        so the registry cannot hold it. Same answer the backup folder gives, for the same reason.

        `config_edit`, because it is a path on the server's disk and the only screen that needs
        it is the one that sets it — and answering it does not CREATE the folder: a GET that
        paints a screen has no business leaving a directory behind.
        """
        configured = dcim_media.where(wa._var_dir or '', C.media_dir())
        return jsonify({'configured': configured})

    # ── What is inside a device ───────────────────────────────────────────────
    #
    # Six disks, the memory, the two power supplies — and the mini-PC's charger, which is not an
    # elegant component and is exactly what has to be replaced when it goes missing. A row per
    # component and not a text field, because the question is "how many 4 TB disks do I have and
    # in which machines", and a description cannot be asked that.

    def _item_writable(uid):
        store = C.store()
        item = store.items.get(str(uid or '')) if store else None
        if not item:
            return store, None
        ok = C.may_write(store, store.owners_map(), C.seen(), 'item', item['uid'])
        return store, (item if ok else False)

    @app.route('/api/v1/dcim/items/<uid>/parts', methods=['GET'])
    @C.view_req
    def api_dcim_parts(uid):
        """Lo que hay dentro de un equipo.

        Solo de uno que este lector pueda ver **entero**. A diferencia de un equipo —que sale
        ocupando U aunque sea ajeno, porque si no la sala no se puede planificar— un disco no
        ocupa nada que nadie más necesite saber: de un equipo ajeno no se lista ni uno.
        """
        store = C.store()
        if not store:
            return jsonify({'parts': [], 'kinds': []})
        item = store.items.get(uid)
        if not item:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not dcim_owners.may_see(C.owner_of(store, store.owners_map(), 'item', uid), C.seen()):
            return jsonify({'error': wa._t('access_denied')}), 403
        salida = {'parts': store.parts_of([uid]), 'kinds': list(PART_KINDS),
                  'component_tree': dcim_catalog.COMPONENT_TREE}
        # Los huecos que declara su MODELO. Son lo que hace que «en cuál va» se pueda ELEGIR en
        # vez de teclear, y sin ellos el mismo hueco acaba escrito de tres maneras —`hueco 7`,
        # `Hueco-7`, `7`— y entonces «qué hay en el 7» no tiene respuesta.
        #
        # Hacía falta aquí porque la pantalla solo sabía mirar la plantilla, y un panel de
        # parcheo no nace de ninguna: no tiene estándar de compra que estampar, se coloca
        # directamente desde el catálogo. Se manda con la forma de una plantilla —`ports` y
        # `port_list`— para que lo lea el mismo código: dos lectores de lo mismo se separan.
        modelo = str(item.get('type_uid') or '')
        cat = getattr(wa, '_dcim_catalog', None)
        fila = (cat.get(modelo) if (modelo and cat and hasattr(cat, 'get')) else None) or None
        if fila:
            salida['model'] = {'uid': str(fila.get('uid') or modelo),
                               'ports': fila.get('ports') or {},
                               'port_list': fila.get('port_list') or {}}
        # Y lo que su plantilla decía, si nació de una. Ninguna de las dos partes es «el error»:
        # que una máquina se separe de su estándar es un hecho sobre esa máquina —le cambiaron
        # los discos— y la diferencia ES el dato, igual que en el contraste de cableado.
        plantillas = C.builds()
        plantilla = plantillas.get(str(item.get('build_uid') or '')) if plantillas else None
        if plantilla:
            salida['build'] = {'uid': plantilla['uid'], 'name': plantilla.get('name') or ''}
            salida['diff'] = dcim_builds.compare(plantillas.parts_of(plantilla['uid']),
                                                 salida['parts'])
        return jsonify(salida)

    @app.route('/api/v1/dcim/parts', methods=['POST'])
    @C.edit_req
    def api_dcim_part_new():
        data = request.get_json(silent=True) or {}
        if str(data.get('kind') or 'other') not in PART_KINDS:
            return jsonify({'error': wa._t('dcim_part_kind_unknown')}), 400
        store, item = _item_writable(data.get('item_uid'))
        if not store or item is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if item is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        return jsonify({'uid': store.parts.create(C.from_type(data), actor=C.actor())})

    @app.route('/api/v1/dcim/parts/<uid>', methods=['PUT'])
    @C.edit_req
    def api_dcim_part_edit(uid):
        store = C.store()
        row = store.parts.get(uid) if store else None
        if not row:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        _, item = _item_writable(row.get('item_uid'))
        if item is False or item is None:
            return jsonify({'error': wa._t('access_denied')}), 403
        data = _without(request.get_json(silent=True) or {}, ('item_uid',))
        if 'kind' in data and str(data['kind']) not in PART_KINDS:
            return jsonify({'error': wa._t('dcim_part_kind_unknown')}), 400
        store.parts.update(uid, C.from_type(data), actor=C.actor())
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/parts/<uid>', methods=['DELETE'])
    @C.edit_req
    def api_dcim_part_del(uid):
        store = C.store()
        row = store.parts.get(uid) if store else None
        if not row:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        _, item = _item_writable(row.get('item_uid'))
        if item is False or item is None:
            return jsonify({'error': wa._t('access_denied')}), 403
        store.parts.delete(uid)
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/hosts', methods=['GET'])
    @C.view_req
    def api_dcim_hosts():
        """The machines this caller may link an item to: uid, name, address, and what the
        device said it IS.

        Its own route rather than reusing Infrastructure's fleet listing, for two reasons that
        pull the same way. That one is behind `infra_view`, and somebody who arranges cabinets
        need not hold it — making the inventory unusable without a permission it has nothing to
        do with. And it returns the whole shape of a machine, of which this needs four fields:
        a picker that ships the fleet's status, tags and module counts is a picker that costs
        what the fleet screen costs.

        Narrowed by the registry's own rule (`devices_view` / `server.<uid>.view`), because what
        is being offered here is the registry's records.
        """
        store = getattr(wa, '_hosts_store', None)
        if store is None:
            return jsonify({'hosts': []})
        perms = C.perms()
        rows = []
        for h in store.list(decrypt=False) or ():
            uid = str(h.get('uid') or '')
            if 'devices_view' not in perms and f'server.{uid}.view' not in perms:
                continue
            rows.append({'uid': uid, 'name': str(h.get('name') or ''),
                         'address': str(h.get('address') or ''),
                         'device_type': str(h.get('device_type') or '')})
        rows.sort(key=lambda r: r['name'].lower())
        return jsonify({'hosts': rows})

    @app.route('/api/v1/dcim/racks', methods=['GET'])
    @C.view_req
    def api_dcim_racks():
        """The racks of one room.

        Not folded into the site tree: that answer carries a COUNT per room, because a fleet of
        forty rooms would otherwise ship every rack of every one of them to draw a number.
        """
        store = C.store()
        room = str(request.args.get('room') or '')
        if store is None or not room:
            return jsonify({'racks': []})
        said, allowed = store.owners_map(), C.seen()
        racks = C.filtered(store.racks_of(room), store, said, allowed, 'rack',
                          dcim_svc.reachable(store, said, allowed))
        # …con cómo está cada uno, que es de lo que se colorea el plano. Un vuelco entero para
        # una sala es más de lo que hace falta, pero es UNA pasada y el alternativo —preguntar
        # por rack— son cuarenta lecturas del mismo fichero de estado.
        roll = dcim_svc.tree_roll(store, C.states(), said, allowed)
        for rack in racks:
            rack['roll'] = roll['rack'].get(rack['uid']) or {}
        return jsonify({'racks': racks})

    @app.route('/api/v1/dcim/racks/<uid>', methods=['GET'])
    @C.view_req
    def api_dcim_rack(uid):
        """One rack: what is in it, and what is free.

        Free space is returned whatever the caller owns. It reveals nothing about anybody and
        it is half the reason this exists — "6U free" is the answer somebody needs before
        buying, and refusing it to the person who cannot see the neighbours' names would make
        a shared cabinet unplannable.
        """
        store = C.store()
        rack = store.racks.get(uid) if store else None
        if not rack:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        said, allowed = store.owners_map(), C.seen()
        # **O lo ves, o tienes algo dentro.** Las dos mitades importan y ninguna sola vale.
        #
        # Solo «lo ves» rompe el caso del holding, que es la razón de ser de esto: el
        # departamento opera la sede, así que la sede es suya y la filial no ve ni sede, ni
        # sala, ni rack — y sin abrir el rack no puede saber que la U 12 está ocupada, que es
        # justo lo que necesita para planificar. Un armario improvisable.
        #
        # Solo «tienes algo dentro» tampoco: sin ninguna regla, cualquiera con permiso de mirar
        # abría CUALQUIER armario escribiendo su uid —nombre, sociedad, U libres, cuánto hay
        # dentro— sin tener nada que ver con él. Y el listado sí lo escondía: dos pantallas
        # discrepando y la permisiva alcanzable a mano.
        if not dcim_owners.may_see(C.owner_of(store, said, 'rack', uid), allowed)                 and not dcim_svc.llega(dcim_svc.reachable(store, said, allowed), 'rack', uid):
            return jsonify({'error': wa._t('access_denied')}), 403
        items = C.filtered(store.items_of(uid), store, said, allowed, 'item')
        statuses = C.states()
        # …and what each of them is DOING, which is the join this section exists for. A
        # foreign item carries no host, so it contributes no state and gets none — occupied,
        # and nothing else said about it.
        for item in items:
            item['state'] = dcim_svc.item_state(item, statuses)
        # …and how deep it is, per section. What decides whether a server fits is not the
        # cabinet's depth but the distance between the posts, and that is a number nobody can
        # look up — so the rack publishes what it has, and each item that knows its own depth
        # gets an answer.
        # La imagen del modelo, si el catálogo la trajo. Se resuelve aquí y no en el navegador
        # porque el alzado ya recibe los items: pedir el catálogo aparte para pintar cuarenta
        # cajas sería una petición para saber si hay una foto.
        cat = getattr(wa, '_dcim_catalog', None)
        fotos, nombres = {}, {}
        for item in items:
            tipo = str(item.get('type_uid') or '')
            if tipo and cat and tipo not in fotos:
                fila = cat.get(tipo) if hasattr(cat, 'get') else None
                fotos[tipo] = {'front': str((fila or {}).get('front_image') or ''),
                               'rear': str((fila or {}).get('rear_image') or '')}
                nombres[tipo] = ' '.join(
                    x for x in (str((fila or {}).get('manufacturer') or ''),
                                str((fila or {}).get('model') or '')) if x)
        for item in items:
            if not item.get('foreign'):
                item['depth'] = dcim_svc.fits_depth(rack, item.get('depth_mm'))
                # …y de un equipo ajeno tampoco sale su foto: la foto dice el modelo, y el
                # modelo es de las cosas que un armario compartido no cuenta.
                item['images'] = fotos.get(str(item.get('type_uid') or '')) or {}
                # Y cómo se LLAMA ese modelo. La ficha lo tiene que enseñar, y sin el nombre
                # sólo puede enseñar el identificador — treinta y seis caracteres que no dicen
                # nada, que es lo que ya pasaba con las plantillas.
                item['type_name'] = nombres.get(str(item.get('type_uid') or ''), '')
                # Y qué CREE el catálogo que es, cuando nadie lo ha dicho. Propone, no
                # escribe: la biblioteca no trae el rol y esto se deduce de los puertos.
                if not str(item.get('role') or '') and cat:
                    tipo = cat.get(str(item.get('type_uid') or '')) if item.get('type_uid') \
                        else None
                    item['role_hint'] = dcim_svc.role_hint(tipo)
        # Cuántas filas hay detrás de cada pestaña. **Aquí y no al abrir cada una**: un número
        # que sólo aparece después de entrar no contesta la pregunta para la que está —¿hay algo
        # ahí?— y la contesta al revés, porque una pestaña sin número parece una pestaña vacía.
        # Es la misma decisión que los recuentos de las pestañas del catálogo.
        #
        # Contando lo que este lector VE, como todo lo demás: los cables de sus equipos y las
        # regletas de este armario.
        mios = [it['uid'] for it in items if not it.get('foreign')]
        return jsonify({'rack': dict(rack, org_uid=C.owner_of(store, said, 'rack', uid)),
                        'counts': {
                            'cables': len(store.cables_of(mios) or ()),
                            'power': len(store.feeds_of(
                                [p['uid'] for p in store.pdus_of(uid)]) or ()),
                            'hist': len(store.revs.history(
                                uid, scope=dcim_rackrev.SCOPE) or ()),
                        },
                        'items': items,
                        'depths': dcim_svc.rack_depths(rack),
                        # Lo que no cuadra entre por dónde se entra y lo que hay montado. Se
                        # calcula sobre los items que este lector VE: avisar de algo ajeno que
                        # no puede ni mirar es contarle lo que hay en el rack del vecino.
                        'access': dcim_svc.access_warnings(rack, items),
                        'free': dcim_svc.free_units(rack, store.occupancy(uid)),
                        'roll': dcim_svc.rack_roll(items, statuses)})

    # ── What is in a rack ─────────────────────────────────────────────────────

    def _slot_ok(data) -> str:
        """Que el trozo pedido exista dentro de su reparto. Vacío si está bien.

        Aparte porque lo preguntan los dos caminos —lo que se atornilla al armario y lo que se
        monta sobre una bandeja— y son la misma regla sobre el mismo campo: `3 de 2` no es un
        sitio ni en un U ni en una bandeja.
        """
        try:
            de = max(1, int(data.get('u_slots') or 1))
            cual = int(data.get('u_slot') or 1)
            cuantos = max(1, int(data.get('u_slot_span') or 1))
        except (TypeError, ValueError):
            return 'dcim_bad_unit'
        if cual < 1 or cual > de or cual - 1 + cuantos > de:
            return 'dcim_bad_slot'
        if str(data.get('u_split') or 'width') not in ('width', 'height'):
            return 'dcim_bad_slot'
        return ''

    def _span(fila) -> tuple:
        """El trozo que toma una fila, **como fracción**: ``(desde, hasta)`` entre 0 y 1.

        En fracciones y no en «cuál de cuántas» porque los hermanos no tienen por qué contar
        igual: uno puede repartir la bandeja en dos y el siguiente en tres, y `1 de 2` y `2 de 3`
        se pisan aunque no compartan ningún número. Comparadas en la misma escala, se ve.
        """
        de = max(1, int(fila.get('u_slots') or 1))
        cual = min(de, max(1, int(fila.get('u_slot') or 1)))
        cuantos = max(1, min(de - cual + 1, int(fila.get('u_slot_span') or 1)))
        return ((cual - 1) / de, (cual - 1 + cuantos) / de)

    def _mount_busy(store, padre_uid, data, ignore) -> bool:
        """Si el trozo de bandeja que se pide ya lo tiene otro.

        Solo entre los que lo DICEN. Quien no dice nada no está reclamando media bandeja: está
        dejando que se reparta, y el dibujo los reparte a partes iguales — o lo dicen todos, o
        lo reparte el dibujo. Una fila que no lo dice no puede chocar con nada.
        """
        if int(data.get('u_slots') or 1) <= 1:
            return False
        desde, hasta = _span(data)
        for otro in (store.children_of(padre_uid) or ()):
            if str(otro.get('uid')) == str(ignore or ''):
                continue
            if int(otro.get('u_slots') or 1) <= 1:
                continue
            a, b = _span(otro)
            if desde < b and a < hasta:
                return True
        return False

    def _place(store, data, *, ignore='') -> tuple:
        """Validate a placement. Returns ``(rack_uid, error_key)``.

        **Montado en otro no se coloca: se cuelga.** Un mini PC sobre una bandeja no ocupa un U
        —lo paga la bandeja— así que hereda su sitio y no se le comprueba hueco. Lo que sí se
        comprueba es que quien lo lleva exista, esté en el mismo rack y no vaya montado él
        mismo: dos niveles serían una bandeja sobre una bandeja, que no es una sala, es un
        árbol que nadie puede dibujar.
        """
        padre_uid = str(data.get('parent_uid') or '')
        if padre_uid:
            padre = store.items.get(padre_uid)
            if not padre:
                return '', 'dcim_not_found'
            if str(padre.get('parent_uid') or ''):
                return '', 'dcim_mount_nested'
            if str(padre['uid']) == str(ignore or ''):
                return '', 'dcim_mount_self'
            # Hereda dónde está. Así el alzado, los listados y los recuentos siguen leyendo lo
            # mismo que siempre sin saber que esto va montado.
            # Y cómo está puesto: lo que va encima de una bandeja que está en el suelo al
            # lado del armario está también al lado del armario. Heredarlo es lo que hace que
            # el alzado no dibuje media bandeja.
            for campo in ('rack_uid', 'u_start', 'u_height', 'face', 'placement'):
                data[campo] = padre.get(campo)
            # **Y qué trozo de la bandeja toma.** Los mismos cuatro campos que dividen un U,
            # aplicados al hueco del padre: ya estaban en la ficha y ya se guardaban, y hasta
            # aquí se guardaban SIN MIRARLOS — dos mini PC podían decir los dos «1 de 2» y nadie
            # se quejaba. Mientras no se dibujaban daba igual; desde que se dibujan, eso son dos
            # cajas superpuestas, y un alzado que miente es peor que uno que no dice nada.
            err = _slot_ok(data)
            if err:
                return '', err
            if _mount_busy(store, padre_uid, data, ignore):
                return '', 'dcim_no_room'
            return str(padre.get('rack_uid') or ''), ''
        rack_uid = str(data.get('rack_uid') or '')
        if not store.racks.get(rack_uid):
            return '', 'dcim_not_found'
        # **Y cómo está puesto.** Casi todo se atornilla a los mástiles; lo que no —un SAI en el
        # suelo al lado, un cuadro en la pared, la regleta del lateral— está en el armario para
        # todo lo demás y no tiene U que comprobar. Preguntarle si cabe sería preguntarle por un
        # sitio que no ocupa, y la respuesta sería «no» en un armario lleno: un SAI en el suelo
        # no deja de caber porque el armario esté lleno.
        puesto = str(data.get('placement') or 'u')
        if puesto not in PLACEMENTS:
            return '', 'dcim_placement_unknown'
        face = str(data.get('face') or 'full')
        if face not in FACES:
            return '', 'dcim_bad_face'
        if str(data.get('role') or '') and str(data['role']) not in ITEM_ROLES:
            return '', 'dcim_role_unknown'
        if puesto != 'u':
            # **Y sin U guardada.** La ficha ya no la pregunta, pero un equipo que se mueve de
            # los mástiles al suelo conserva la que tenía, y una lista que lee `u_start` la
            # enseña tan tranquila: «SAI · U1» en un armario donde no está. Un valor que dejó de
            # significar algo y se queda escrito es peor que uno que falta, porque se lee.
            #
            # Aquí y no en la pantalla: quien decide qué ocupa es quien tiene que dejarlo dicho.
            data['u_start'] = 0
            data['u_height'] = 0
            return rack_uid, ''
        # El rol se comprueba arriba, antes de decidir si esto ocupa U: uno inventado es una
        # caja que ninguna pantalla sabe contar, y de él cuelga que algo deje de figurar como
        # «sin vigilar» — valga donde valga.
        try:
            u_start = int(data.get('u_start') or 0)
            u_height = int(data.get('u_height') or 1)
            # En cuántas partes se divide el U y cuál se toma. `1/1` es el U entero, que es lo
            # que dice una petición que no hable de esto — y lo que ocupaba todo hasta ahora.
            de = max(1, int(data.get('u_slots') or 1))
            cual = int(data.get('u_slot') or 1)
            cuantos = max(1, int(data.get('u_slot_span') or 1))
        except (TypeError, ValueError):
            return '', 'dcim_bad_unit'
        err = _slot_ok(data)
        if err:
            return '', err
        if not store.fits(rack_uid, u_start, u_height, face, ignore=ignore,
                          slot={'u_slots': de, 'u_slot': cual, 'u_slot_span': cuantos}):
            return '', 'dcim_no_room'
        return rack_uid, ''

    @app.route('/api/v1/dcim/said', methods=['GET'])
    @C.edit_req
    def api_dcim_said():
        """Lo que un dispositivo ha DICHO de sí mismo, para ofrecerlo en la ficha de un equipo.

        Hoy sólo el número de serie, que es lo que a nadie le apetece copiar de una pegatina
        detrás de un rack. Sale de `reported_facts`, que es el canal por el que la pantalla de
        infraestructura ya lee «quién lo hizo» y «qué modelo es»: un rol, un valor y quién lo
        dijo — y descartando lo que viene con `_row`, para que el número de serie de un disco de
        un Synology no se confunda con el de la caja.

        **Nada aquí escribe.** El panel ofrece y una persona acepta, igual que con el modelo que
        sugiere el catálogo: un número de serie puesto solo es un número que nadie ha comprobado
        y que a partir de ese momento parece comprobado.

        Varios valores no es un error: un switch apilado tiene varios chasis y por tanto varios
        números, y la respuesta los lleva todos para que se elija — quedarse con el primero sería
        decidir por su cuenta cuál de los tres armarios es «el» equipo.

        **Y viaja TODO lo que el dispositivo contó, no sólo lo que se pregunta.** «No ha dicho
        número de serie» tiene dos causas que se ven igual y se arreglan en sitios distintos: un
        perfil que ni siquiera se enganchó —no ha dicho nada de nada— y uno que sí, pero al que
        le falta esa directiva `extend`. La lista de lo que sí dijo separa las dos sin tener que
        abrir otra pantalla, que es lo que costó la primera vez que pasó.
        """
        from lib.core.hosts.resolve import reported_facts        # noqa: PLC0415
        uid = str(request.args.get('host') or '').strip()
        if not uid:
            return jsonify({'said': {}})
        store = getattr(wa, '_hosts_store', None)
        if store is None or not store.get(uid, decrypt=False):
            return jsonify({'error': wa._t('host_not_found')}), 404
        # Con el permiso de la MÁQUINA además del del inventario: lo que se devuelve es lo que
        # un dispositivo contó de sí mismo, y quien no puede abrir su ficha tampoco puede
        # sacárselo por aquí. La misma regla que el listado del registro, dicha igual.
        perms = set(wa._get_session_permissions() or [])
        if 'devices_view' not in perms and f'server.{uid}.view' not in perms:
            return jsonify({'error': wa._t('access_denied')}), 403
        hechos = reported_facts(wa._read_check_status(), uid)
        return jsonify({'said': hechos})

    @app.route('/api/v1/dcim/racks/<uid>/history', methods=['GET'])
    @C.view_req
    def api_dcim_rack_history(uid):
        """Cómo estaba este armario y qué le pasó.

        Las dos preguntas de una tabla: cada versión es la foto —«cómo estaba en marzo»— y su
        diferencia con la anterior es el acontecimiento —«quién movió el switch»—. Calculada
        aquí y no en la pantalla porque es la misma cuenta que hace la comparación de dos
        versiones cualesquiera, y dos implementaciones de «qué cambió» serían libres de no estar
        de acuerdo sobre si mover un equipo es un cambio o dos.

        La foto entera viaja con cada renglón: son catorce campos por equipo y treinta versiones
        como mucho, y es lo que permite comparar dos cualesquiera sin una segunda petición por
        cada par que a alguien se le ocurra mirar.
        """
        store = C.store()
        rack = store.racks.get(uid) if store else None
        if not rack:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not dcim_owners.may_see(C.owner_of(store, store.owners_map(), 'rack', uid),
                                   C.seen()):
            return jsonify({'error': wa._t('access_denied')}), 403
        filas = store.revs.history(uid, scope=dcim_rackrev.SCOPE)
        fuera = []
        for i, f in enumerate(filas):
            # Contra la SIGUIENTE de la lista, que es la anterior en el tiempo: `history`
            # devuelve de la más nueva a la más vieja.
            #
            # Y la más vieja **no se compara contra nada**: la diferencia contra el vacío diría
            # que llegaron seis equipos y que el armario se llamó, que es cierto y no es lo que
            # pasó — lo que pasó es que aquí empezó a guardarse. Un historial que se inventa un
            # primer día enseña un acontecimiento que nadie vivió.
            ultima = i + 1 >= len(filas)
            previa = {} if ultima else (filas[i + 1].get('data') or {})
            fuera.append({'uid': f['uid'], 'at': f['at'], 'by': f['by'],
                          'action': f.get('action') or '',
                          'items': len((f.get('data') or {}).get('items') or ()),
                          'changed': [] if ultima
                                     else dcim_rackrev.compare(previa, f.get('data') or {}),
                          'data': f.get('data') or {}})
        return jsonify({'history': fuera})

    #: Cuántos equipos devuelve una búsqueda cuando nadie dice cuántos. Treinta es una lista
    #: que se lee; doscientas es un desplegable disfrazado, y quien busca «PP» en una sala
    #: grande no quiere doscientas.
    _FIND_MAX = 30

    #: Y el tope de verdad, para la pantalla que los lista todos. Doscientas filas se miran; con
    #: más, lo que se hace no es leerlas sino afinar la búsqueda — y para eso hay que saber que
    #: está recortada, que es lo que dice `capped`.
    _FIND_TOP = 200

    def _types_matching(q: str) -> list:
        """Los modelos del catálogo cuyo nombre contiene *q*, para poder buscar equipos por él.

        La mitad de lo que hay en un armario no está rotulado y de eso lo único que se sabe es de
        qué modelo es. El modelo vive en otra tabla, así que se resuelve antes a una lista de
        identificadores: un `JOIN` diría lo mismo, pero el catálogo es su propio almacén y
        atravesarlo desde aquí sería que esta ruta supiera cómo está guardado.

        Acotada: un `IN` de ocho mil identificadores no es una consulta, es otro problema.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        if not q or cat is None or not hasattr(cat, 'list'):
            return []
        sql, params = dcim_store.like_clause(('manufacturer', 'model'), q)
        if not sql:
            return []
        try:
            return [r['uid'] for r in cat.list(sql, params, limit=_TYPES_MAX)]
        except Exception:                       # pylint: disable=broad-except
            return []                           # buscar por etiqueta sigue funcionando

    #: Cuántos modelos como mucho entran en la búsqueda por nombre de modelo. Con más de
    #: doscientos coincidiendo, lo que hay que afinar es la búsqueda.
    _TYPES_MAX = 200

    @app.route('/api/v1/dcim/items', methods=['GET'])
    @C.view_req
    def api_dcim_items_find():
        """Buscar un equipo por su nombre, en cualquier armario que este lector pueda ver.

        Hace falta para meter un panel en medio de un cable que ya está declarado: **el panel
        casi nunca está en el armario del servidor** —vive en el de patcheo— así que una lista
        acotada al armario abierto deja fuera justo el caso normal.

        Se busca por lo que alguien lee: la etiqueta **y el modelo**. La mitad de lo que hay en
        un armario no está rotulado —una tapa, una bandeja, un panel recién puesto— y de eso lo
        único que se sabe es de qué modelo es. El identificador no se teclea, y buscar por él
        sería ofrecer buscar por lo que nadie sabe de memoria.

        Y **cada fila vuelve con lo que hace falta para nombrarla**: la etiqueta, la máquina, el
        modelo y el rol. La pantalla nombra un equipo con una sola función, y esa función necesita
        los cuatro; mandar sólo la etiqueta la deja cayendo al identificador, que es exactamente
        lo que esa función existe para no enseñar. Sexta vez que sale esta forma en esta sección:
        un dato que no viaja vale su valor por defecto, y el respaldo parece que funciona.

        Narrowed like everything else: un equipo que este lector no puede ver no sale, ni
        siquiera opaco — esto no dibuja un armario compartido, ofrece dónde escribir, y ofrecer
        algo ajeno como sitio donde escribir es ofrecer escribir en su inventario.
        """
        store = C.store()
        if not store:
            return jsonify({'items': []})
        q = str(request.args.get('q') or '').strip().lower()
        rol = str(request.args.get('role') or '').strip()
        sede = str(request.args.get('site') or '').strip()
        empresa = str(request.args.get('org') or '').strip()
        cuantos = max(1, min(_FIND_TOP, int(_num(request.args.get('limit') or _FIND_MAX))))
        said, allowed = store.owners_map(), C.seen()
        # Dónde está cada uno, entero: «PP-A» a secas no distingue el panel de la sala del panel
        # del rack de al lado, y «qué servidores hay en esta sede» necesita subir hasta la sede.
        # Se arma una vez y de ahí salen las tres respuestas — armario, sala y sede.
        racks, sede_de = {}, {}
        for sitio in store.sites.list():
            for sala in store.rooms_of(sitio['uid']):
                for r in store.racks_of(sala['uid']):
                    racks[r['uid']] = dict(r, room_name=str(sala.get('name') or ''),
                                           site_uid=sitio['uid'],
                                           site_name=str(sitio.get('name') or ''))
                    sede_de[r['uid']] = sitio['uid']
        # ── Lo que la BASE puede filtrar, filtrado en la base ─────────────────────────
        #
        # Esto recorría la tabla entera y construía un diccionario por equipo de toda la
        # instalación para quedarse con treinta. En una sala pequeña no se nota, que es
        # exactamente lo que hace que se escriba así y se descubra tarde.
        #
        # El texto se busca en la etiqueta **y en el modelo**, y el modelo está en otra tabla:
        # se resuelve antes a una lista de identificadores y se pregunta por ellos. Acotada, que
        # un `IN` de ocho mil no es una consulta sino un problema distinto.
        cond, params = [], []
        if rol:
            cond.append('role = ?')
            params.append(rol)
        if sede:
            # Los armarios de esa sede, resueltos antes: la sede de un equipo es la de su
            # armario y eso no está en su fila. Un `IN` vacío es «ninguno», que es la respuesta
            # correcta a una sede sin armarios — y no «todos», que es lo que saldría de no
            # poner condición.
            de_esa = [u for u, s_uid in sede_de.items() if s_uid == sede]
            marcas = ', '.join('?' for _ in de_esa) or 'NULL'
            cond.append(f'rack_uid IN ({marcas})')
            params.extend(de_esa)
        if q:
            sql_q, p_q = dcim_store.like_clause(('label',), q)
            tipos = _types_matching(q)
            if tipos:
                marcas = ', '.join('?' for _ in tipos)
                sql_q = f'({sql_q} OR type_uid IN ({marcas}))'
                p_q = tuple(p_q) + tuple(tipos)
            cond.append(sql_q)
            params.extend(p_q)
        where = ' AND '.join(cond)
        cat = getattr(wa, '_dcim_catalog', None)
        nombres: dict = {}

        def _modelo(tipo):
            """Cómo se llama ese modelo del catálogo. Cacheado: veinte equipos del mismo
            modelo son una lectura, no veinte."""
            tipo = str(tipo or '')
            if not tipo or not cat or not hasattr(cat, 'get'):
                return ''
            if tipo not in nombres:
                fila = cat.get(tipo) or {}
                nombres[tipo] = ' '.join(x for x in (str(fila.get('manufacturer') or ''),
                                                     str(fila.get('model') or '')) if x)
            return nombres[tipo]

        # Lo único que la base NO puede: quién puede ver qué sale de una cadena de
        # pertenencia que no está en ninguna columna, y escribirla en SQL sería tener la regla
        # en dos sitios. Por eso se recorre a trozos en vez de traerlo todo.
        pag = scan_pages(
            lambda lim, off: store.items.list(where, tuple(params), limit=lim, offset=off),
            lambda f: dcim_owners.may_see(C.owner_of(store, said, 'item', f['uid']), allowed),
            cuantos, int(_num(request.args.get('offset') or 0)))
        estados = C.states()
        fuera = []
        for fila in pag['rows'][:cuantos]:
            rack = racks.get(str(fila.get('rack_uid') or '')) or {}
            dueno = C.owner_of(store, said, 'item', fila['uid'])
            # La empresa se filtra AQUÍ y no en el `WHERE`: un equipo hereda la de su armario
            # cuando no dice la suya, y esa herencia no está en ninguna columna. Escribirla en
            # SQL sería tener la regla en dos sitios, que es como dos pantallas acaban
            # discrepando sobre de quién es lo mismo.
            if empresa and str(dueno or '') != empresa:
                continue
            fuera.append({'uid': fila['uid'], 'label': str(fila.get('label') or ''),
                          'type_name': _modelo(fila.get('type_uid')),
                          'host_uid': str(fila.get('host_uid') or ''),
                          'role': str(fila.get('role') or ''),
                          'u_start': fila.get('u_start'),
                          'u_height': fila.get('u_height'),
                          'serial': str(fila.get('serial') or ''),
                          'asset': str(fila.get('asset') or ''),
                          'purchased_at': str(fila.get('purchased_at') or ''),
                          'warranty_until': str(fila.get('warranty_until') or ''),
                          'supplier': str(fila.get('supplier') or ''),
                          'org_uid': str(dueno or ''),
                          # Su estado, que es lo que hace que esta lista sirva para algo más que
                          # contar: sin él es un inventario, y con él es «qué de lo que tengo
                          # está mal». Vacío cuando no hay máquina enganchada, que NO es «bien».
                          'state': dcim_svc.item_state(fila, estados),
                          'rack_uid': str(fila.get('rack_uid') or ''),
                          'rack': str(rack.get('name') or ''),
                          'room': str(rack.get('room_name') or ''),
                          'site_uid': str(rack.get('site_uid') or ''),
                          'site': str(rack.get('site_name') or '')})
        return jsonify({'items': fuera, 'capped': pag['capped'],
                        'next_offset': pag['next_offset'],
                        'roles': list(ITEM_ROLES),
                        'sites': [{'uid': x['uid'], 'name': str(x.get('name') or '')}
                                  for x in store.sites.list()]})

    @app.route('/api/v1/dcim/items', methods=['POST'])
    @C.edit_req
    def api_dcim_item_create():
        store = C.store()
        data = request.get_json(silent=True) or {}
        # Desde una plantilla: la altura, el fondo, la cara, el rol y el modelo salen puestos, y
        # lo que queda por teclear es solo lo que tiene ESA caja y ninguna otra. Antes de
        # `_place` a propósito: la altura decide si cabe donde se pidió, y aplicarla después
        # sería validar un hueco para un equipo de otro tamaño.
        plantilla = C.build_wanted(data)
        if plantilla:
            data = C.from_build(plantilla, data)
        elif data.get('build_uid'):
            # Una plantilla que no existe no es una plantilla: guardar el texto tal cual dejaría
            # una máquina afirmando haber nacido de algo que no está, y eso no da ningún error
            # el día que se escribe — solo una ficha que no cuadra meses después.
            data = _without(data, ('build_uid',))
        # Y del catálogo, DESPUÉS de la plantilla: una plantilla ya dice de qué modelo sale, así
        # que lo que queda por resolver aquí es el caso en que se eligió un modelo a pelo — una
        # tapa, una regleta, una bandeja. Cosas que no tienen estándar de compra y que hasta
        # ahora obligaban a inventarse una plantilla para poder colocarlas.
        data = C.from_type_item(data)
        rack_uid, err = _place(store, data)
        if err:
            return jsonify({'error': wa._t(err)}), 400 if err != 'dcim_not_found' else 404
        if not C.may_write(store, store.owners_map(), C.seen(), 'rack', rack_uid):
            return jsonify({'error': wa._t('access_denied')}), 403
        err = C.asset('items', data)
        if err:
            return jsonify({'error': wa._t(err)}), 400
        uid = store.items.create(data, actor=C.actor())
        # Las piezas se COPIAN, no se leen de la plantilla. Desde este momento son suyas: el día
        # que alguien saca un disco averiado hay dónde decirlo, y editar la plantilla no
        # rescribe la ficha de veinte máquinas que nadie ha tocado.
        piezas = 0
        if plantilla:
            for pieza in (C.builds().stamp(plantilla['uid']) if C.builds() else ()):
                store.parts.create(dict(pieza, item_uid=uid), actor=C.actor())
                piezas += 1
        wa._audit('dcim_placed', detail={'item': uid, 'rack': rack_uid,
                                         'label': str(data.get('label') or ''),
                                         'u': data.get('u_start'),
                                         'build': (plantilla or {}).get('name', ''),
                                         'parts': piezas})
        C.snap(rack_uid, 'place')
        return jsonify({'uid': uid, 'parts': piezas,
                        'asset': str(data.get('asset') or '')})

    @app.route('/api/v1/dcim/items/<uid>', methods=['PUT'])
    @C.edit_req
    def api_dcim_item_update(uid):
        store = C.store()
        item = store.items.get(uid)
        if not item:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        # …against the owner of what is being MOVED. Moving somebody else's server one U is
        # still touching somebody else's server.
        if not C.may_write(store, store.owners_map(), C.seen(), 'item', uid):
            return jsonify({'error': wa._t('access_denied')}), 403
        # `build_uid` no se edita: dice de qué plantilla NACIÓ, y eso ya ocurrió. Cambiarlo
        # sería reescribir el origen de una máquina sin tocar ni una de sus piezas — una fila
        # que afirma algo que no pasó, y encima difícil de descubrir.
        data = _without(request.get_json(silent=True) or {}, ('build_uid',))
        # Cambiar CÓMO está puesto es moverlo: pasar de los mástiles al suelo es dejar de
        # ocupar una U, y sin contarlo entre lo que mueve, la comprobación no corría y el equipo
        # se quedaba con la U que tenía — un SAI al lado del armario listado en la U 1.
        moving = {'rack_uid', 'u_start', 'u_height', 'face', 'u_slots', 'u_slot',
                  'u_slot_span', 'u_split', 'parent_uid', 'placement'} & set(data)
        if moving:
            # Lo que lleva algo encima no puede pasar a ir montado: sería una bandeja sobre una
            # bandeja, y lo que hay encima de ella se quedaría colgando de un nivel que no
            # existe.
            if str(data.get('parent_uid') or '') and store.children_of(uid):
                return jsonify({'error': wa._t('dcim_mount_nested')}), 400
            merged = dict(item, **data)
            _, err = _place(store, merged, ignore=uid)
            if err:
                return jsonify({'error': wa._t(err)}), 400
            # Colgarlo o descolgarlo arrastra su sitio, que `_place` ya ha resuelto.
            for campo in ('rack_uid', 'u_start', 'u_height', 'face'):
                if campo in merged:
                    data[campo] = merged[campo]
        err = C.asset('items', data, uid)
        if err:
            return jsonify({'error': wa._t(err)}), 400
        store.items.update(uid, data, actor=C.actor())
        # De los DOS armarios cuando cambia de uno a otro: para el de origen, ese equipo se fue;
        # para el de destino, llegó. Guardar sólo el de destino dejaría el primero enseñando una
        # máquina que ya no está, que es exactamente lo que un historial no puede hacer.
        antes = str(item.get('rack_uid') or '')
        ahora = str((store.items.get(uid) or {}).get('rack_uid') or '')
        C.snap(antes, 'move' if moving else 'edit')
        if ahora and ahora != antes:
            C.snap(ahora, 'move')
        return jsonify({'ok': True, 'asset': str(data.get('asset') or '')})

    @app.route('/api/v1/dcim/items/<uid>', methods=['DELETE'])
    @C.edit_req
    def api_dcim_item_delete(uid):
        store = C.store()
        if not store.items.get(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not C.may_write(store, store.owners_map(), C.seen(), 'item', uid):
            return jsonify({'error': wa._t('access_denied')}), 403
        # Lo que lleva algo encima **no se retira**: quitar la bandeja dejaría tres máquinas
        # colgando de un sitio que ya no está, y ninguna de ellas ocupa U propio para volver a
        # colocarse sola. Se dice cuántas son, que es lo que hace falta para decidir.
        encima = store.children_of(uid)
        if encima:
            return jsonify({'error': wa._t('dcim_mount_in_use'),
                            'mounted': len(encima)}), 400
        # De qué armario era, ANTES de borrarlo: después ya no hay a quién preguntárselo.
        era = str((store.items.get(uid) or {}).get('rack_uid') or '')
        store.items.delete(uid)
        store.forget_scope('item', uid)
        wa._audit('dcim_removed', detail={'item': uid})
        C.snap(era, 'remove')
        return jsonify({'ok': True})

    # Referenciadas para que un analizador no las dé por muertas: Flask se las
    # queda por su ruta.
    _ = (api_dcim_fits, api_dcim_board, api_dcim_media_dir,)
