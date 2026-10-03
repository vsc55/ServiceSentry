#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dónde está cada cosa: empresas, sedes, salas, racks y lo que hay en el suelo.

La contención —de la calle al armario— y la pertenencia, que es la otra pregunta:
dónde está algo y de quién es no se contestan igual ni las hace la misma persona.

Rutas:

    POST    /api/v1/dcim/features
    PUT     /api/v1/dcim/features/<uid>
    DELETE  /api/v1/dcim/features/<uid>
    POST    /api/v1/dcim/floors
    PUT     /api/v1/dcim/floors/<uid>
    DELETE  /api/v1/dcim/floors/<uid>
    POST    /api/v1/dcim/floors/<uid>/plan
    DELETE  /api/v1/dcim/floors/<uid>/plan
    POST    /api/v1/dcim/floors/<uid>/area
    GET     /api/v1/dcim/media/<path:name>
    GET     /api/v1/dcim/orgs
    GET     /api/v1/dcim/rooms/<uid>/features
    POST    /api/v1/dcim/rooms/<uid>/import
    POST    /api/v1/dcim/rooms/<uid>/plan
    DELETE  /api/v1/dcim/rooms/<uid>/plan
    POST    /api/v1/dcim/sites/<uid>/photo
    DELETE  /api/v1/dcim/sites/<uid>/photo
    GET     /api/v1/dcim/sites/<uid>/floors
    POST    /api/v1/dcim/rows
    PUT     /api/v1/dcim/rows/<uid>
    DELETE  /api/v1/dcim/rows/<uid>
    GET     /api/v1/dcim/sites
"""

from __future__ import annotations

from flask import jsonify, request

from lib.core.dcim import media as dcim_media
from lib.core.dcim import owners as dcim_owners
from lib.core.dcim import service as dcim_svc
from lib.core.dcim.store import FEATURE_KINDS, FEATURE_LAYERS
from lib.core.dcim.routes._common import _num, _without


def register(app, wa, C):
    """Las rutas de esta área. *C* es lo que comparten todas: los permisos y los ayudantes."""
    @app.route('/api/v1/dcim/orgs', methods=['GET'])
    @C.view_req
    def api_dcim_orgs():
        """The companies, by name, for the screens of this section.

        A READ and nothing else: creating, renaming and removing them is `/api/v1/orgs`, which
        is the core's, because the same company that pays for the cabinet has users in the
        directory and licences in Microsoft 365. What is left here is the half this section
        cannot draw without — the badge on a rack and the dropdown that files one — and it goes
        with `dcim_view`, or opening a room would need a permission about companies.

        Narrowed to what the caller may see: somebody holding one company's scope and not the
        fleet gets that company, not the group's list of subsidiaries.
        """
        store = C.store()
        if store is None:
            return jsonify({'orgs': []})
        allowed = C.seen()
        rows = store.orgs.list()
        if allowed is not None:
            rows = [r for r in rows if r['uid'] in allowed]
        return jsonify({'orgs': [{'uid': r['uid'], 'name': r['name'], 'short': r['short']}
                                 for r in rows]})

    # ── Sites, rooms, racks ───────────────────────────────────────────────────

    @app.route('/api/v1/dcim/sites', methods=['GET'])
    @C.view_req
    def api_dcim_sites():
        store = C.store()
        if store is None:
            return jsonify({'sites': []})
        said, allowed = store.owners_map(), C.seen()
        # A dónde llega este lector, calculado UNA vez: lo que ve, más lo que contiene algo
        # suyo. Las cuatro pantallas que enseñan cajas usan lo mismo.
        reach = dcim_svc.reachable(store, said, allowed)
        roll = dcim_svc.tree_roll(store, C.states(), said, allowed)
        out = []
        for site in C.filtered(store.sites.list(), store, said, allowed, 'site', reach):
            rooms = C.filtered(store.rooms_of(site['uid']), store, said, allowed, 'room', reach)
            for room in rooms:
                # The racks THEMSELVES and not just how many: they are what somebody scanning
                # this page is looking for, and a count turns "which racks are in this room"
                # from an answer into a question. It fits — racks per room are tens at most and
                # a row is four fields. Their ITEMS do not, which is why those are still asked
                # for one rack at a time.
                racks = C.filtered(store.racks_of(room['uid']), store, said, allowed,
                                  'rack', reach)
                for rack in racks:
                    rack['roll'] = roll['rack'].get(rack['uid']) or {}
                    rack['used_u'] = _used_u(store, rack)
                room['rackList'] = racks
                room['racks'] = len(racks)
                room['roll'] = roll['room'].get(room['uid']) or {}
            # Las plantas, de abajo arriba: cuántas, y cuáles —con su plano, que es la miniatura
            # de la tarjeta de la sede y lo que abre cada botón de planta del panel del mapa—.
            plantas = [{'uid': f['uid'], 'name': f['name'], 'level': f['level'],
                        'plan': f['plan']} for f in store.floors_of(site['uid'])]
            out.append(dict(site, rooms=rooms, floors=len(plantas), floor_list=plantas,
                            roll=roll['site'].get(site['uid']) or {}))
        return jsonify({'sites': out})

    def _used_u(store, rack):
        """Cuántos U de un rack están ocupados, por cualquiera de las dos caras.

        Por las dos: un panel de parcheo atornillado solo detrás ocupa ese U igual, y contarlo
        libre sería ofrecer un hueco donde no cabe nada. Lo ajeno cuenta: está ahí, ocupando,
        aunque este lector no pueda saber qué es — que es lo mismo que dibuja el alzado.
        """
        taken = store.occupancy(rack['uid'])
        height = int(taken.get('height') or 0)
        usados = set(taken.get('front') or {}) | set(taken.get('rear') or {})
        return len([u for u in usados if 1 <= int(u) <= height])

    def _room_floor_ok(store, data, room_uid=''):
        """Una sala solo se coloca en una planta de SU sede, o en ninguna.

        Sin esto, una petición podía colgar una sala de la planta de otro edificio: aparecería
        dibujada en un plano que no es el suyo, y quien mirara esa planta vería una sala que no
        está. Vacío es «sin colocar», que siempre vale.
        """
        fid = str(data.get('floor_uid') or '')
        if 'floor_uid' not in data or not fid:
            return True
        floor = store.floors.get(fid)
        site = str(data.get('site_uid') or '')
        if not site and room_uid:
            site = str((store.rooms.get(room_uid) or {}).get('site_uid') or '')
        return bool(floor) and str(floor.get('site_uid') or '') == site

    def _crud(kind, part, scope, required, minted=(), parent=None):
        """The four verbs for one kind of container.

        Written once for sites, rooms and racks because they differ in their columns and not at
        all in what is done to them — and three copies of "check the owner before writing" is
        two places for the check to be forgotten.

        *parent* es ``(ámbito, campo)`` de lo que lo contiene, y decide quién puede CREAR:
        meter una sala en una sede es escribir en esa sede. Sin esto, alguien acotado a su
        sociedad podía crear una sala dentro de una sede que no puede ni listar — y desde ahí un
        rack, y equipos dentro. No daba ningún error: lo creado aparecía en la sede de otro.

        Se declara y no se deduce de *required*: una sede no tiene padre y su `required` es el
        nombre, así que adivinarlo habría funcionado hasta el primer tipo con dos obligatorios.
        """

        @app.route(f'/api/v1/dcim/{kind}', methods=['POST'], endpoint=f'api_dcim_{kind}_new')
        @C.edit_req
        def _create():
            store = C.store()
            data = _without(request.get_json(silent=True) or {}, minted)
            for field in required:
                if not str(data.get(field) or '').strip():
                    return jsonify({'error': wa._t('dcim_name_required')}), 400
            if parent:
                p_scope, p_field = parent
                p_uid = str(data.get(p_field) or '')
                if not getattr(store, p_scope + 's').get(p_uid):
                    return jsonify({'error': wa._t('dcim_not_found')}), 404
                if not C.may_write(store, store.owners_map(), C.seen(), p_scope, p_uid):
                    return jsonify({'error': wa._t('access_denied')}), 403
            # El número de inventario, resuelto y comprobado: `RACK-?` se convierte aquí en el
            # siguiente, y uno repetido no llega a escribirse. Después del permiso a propósito —
            # gastar un número de la numeración en una petición que va a acabar en 403 deja un
            # hueco en la cuenta que nadie sabe explicar.
            err = C.asset(part, data)
            if err:
                return jsonify({'error': wa._t(err)}), 400
            if part == 'rooms' and not _room_floor_ok(store, data):
                return jsonify({'error': wa._t('dcim_floor_other_site')}), 400
            uid = getattr(store, part).create(data, actor=C.actor())
            # Y con qué número se quedó, para lo que lleve número: quien escribe `RACK-?` no
            # puede verlo hasta ir a buscarlo a la lista.
            return jsonify({'uid': uid, 'asset': str(data.get('asset') or '')})

        @app.route(f'/api/v1/dcim/{kind}/<uid>', methods=['PUT'],
                   endpoint=f'api_dcim_{kind}_edit')
        @C.edit_req
        def _update(uid):
            store = C.store()
            if not getattr(store, part).get(uid):
                return jsonify({'error': wa._t('dcim_not_found')}), 404
            if not C.may_write(store, store.owners_map(), C.seen(), scope, uid):
                return jsonify({'error': wa._t('access_denied')}), 403
            data = _without(request.get_json(silent=True) or {}, minted)
            # Con el uid, que es lo que hace que guardar una ficha sin tocarle el número no
            # falle por chocar consigo misma.
            err = C.asset(part, data, uid)
            if err:
                return jsonify({'error': wa._t(err)}), 400
            if part == 'rooms' and not _room_floor_ok(store, data, uid):
                return jsonify({'error': wa._t('dcim_floor_other_site')}), 400
            getattr(store, part).update(uid, data, actor=C.actor())
            # Y su foto, si lo editado ES un armario: renombrarlo o cambiarle la altura mueve de
            # sitio a todo lo que hay dentro, y eso es parte de su historia. Aquí y no en cada
            # llamada porque este CRUD es uno para cuatro cosas — la condición es el precio de
            # que sea uno.
            if scope == 'rack':
                C.snap(uid, 'rack_edit')
            return jsonify({'ok': True})

        @app.route(f'/api/v1/dcim/{kind}/<uid>', methods=['DELETE'],
                   endpoint=f'api_dcim_{kind}_del')
        @C.edit_req
        def _delete(uid):
            store = C.store()
            if not C.may_write(store, store.owners_map(), C.seen(), scope, uid):
                return jsonify({'error': wa._t('access_denied')}), 403
            getattr(store, part).delete(uid)
            store.forget_scope(scope, uid)
            return jsonify({'ok': True})

    _crud('sites', 'sites', 'site', ('name',))
    # `plan` is MINTED by the upload route from what the file turned out to be. Left
    # writable here, a request could point a room at another room's picture without uploading
    # anything — and the check that is written once in the door is the check nobody forgets.
    _crud('rooms', 'rooms', 'room', ('site_uid',), minted=('plan',),
          parent=('site', 'site_uid'))
    _crud('racks', 'racks', 'rack', ('room_uid',), parent=('room', 'room_uid'))

    # ── The pictures ──────────────────────────────────────────────────────────
    #
    # A folder under `var_dir`, the way the MIB library is: these are files somebody uploaded,
    # they are not rows, and a room's plan is a JPEG an architect sent in 2019. The RECORD holds
    # a name this panel minted and never a path — the MIB catalogue shipped a path traversal of
    # exactly this shape, and the fix that holds is the one where a path can only be built in
    # one place, from a name that was minted there.


    @app.route('/api/v1/dcim/sites/<uid>/photo', methods=['POST'])
    @C.edit_req
    def api_dcim_site_photo(uid):
        """Poner una foto en una sede.

        Lo mismo que el plano de una sala y por las mismas razones: **el tipo lo decide lo que
        hay DENTRO del fichero** —una extensión es una afirmación de quien sube, y los primeros
        bytes de un PNG no—, y el nombre con el que llegó no se guarda en ninguna parte, porque
        un nombre elegido por una petición es justo lo que nunca puede llegar a un sistema de
        ficheros.

        Y la que sustituye se borra: sin eso, cada nueva subida deja un fichero al que ya no
        apunta nadie y la carpeta crece durante toda la vida de la instalación.
        """
        store = C.store()
        site = store.sites.get(uid) if store else None
        if not site:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not C.may_write(store, store.owners_map(), C.seen(), 'site', uid):
            return jsonify({'error': wa._t('access_denied')}), 403
        blob = b''
        up = (request.files or {}).get('file')
        if up is not None:
            blob = up.read(dcim_media.MAX_BYTES + 1)
        elif request.data:
            blob = request.data[:dcim_media.MAX_BYTES + 1]
        name, err = dcim_media.save(wa._var_dir or '', blob, C.media_dir())
        if err:
            return jsonify({'error': wa._t(err)}), 400
        old = str(site.get('photo') or '')
        store.sites.update(uid, {'photo': name}, actor=C.actor())
        if old and old != name:
            dcim_media.forget(wa._var_dir or '', old, C.media_dir())
        return jsonify({'photo': name})

    @app.route('/api/v1/dcim/sites/<uid>/photo', methods=['DELETE'])
    @C.edit_req
    def api_dcim_site_photo_delete(uid):
        store = C.store()
        site = store.sites.get(uid) if store else None
        if not site:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not C.may_write(store, store.owners_map(), C.seen(), 'site', uid):
            return jsonify({'error': wa._t('access_denied')}), 403
        name = str(site.get('photo') or '')
        store.sites.update(uid, {'photo': ''}, actor=C.actor())
        if name:
            dcim_media.forget(wa._var_dir or '', name, C.media_dir())
        return jsonify({'ok': True})

    # ── Las plantas de una sede ──────────────────────────────────────────────
    #
    # No son un ámbito de propiedad: una planta es de su sede, y todo lo que se hace con una se
    # permite o no según esa sede. Por eso no pasan por `_crud`, que comprueba el dueño de lo
    # que se toca: aquí lo que se toca no tiene dueño propio.

    def _floor_site(store, floor_uid):
        floor = store.floors.get(floor_uid) if store else None
        return floor, str((floor or {}).get('site_uid') or '')

    def _site_writable(store, site_uid) -> bool:
        return bool(store.sites.get(site_uid)) and C.may_write(
            store, store.owners_map(), C.seen(), 'site', site_uid)

    @app.route('/api/v1/dcim/sites/<uid>/floors', methods=['GET'])
    @C.view_req
    def api_dcim_site_floors(uid):
        """Las plantas de una sede, de abajo arriba, para quien puede ver la sede."""
        store = C.store()
        site = store.sites.get(uid) if store else None
        if not site:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        said, allowed = store.owners_map(), C.seen()
        reach = dcim_svc.reachable(store, said, allowed)
        if not C.filtered([site], store, said, allowed, 'site', reach):
            return jsonify({'error': wa._t('access_denied')}), 403
        # Con los tipos de pieza y sus medidas: la paleta del plano de la sede los necesita
        # aunque la planta no tenga todavía ninguna sala a la que preguntárselos.
        return jsonify({'floors': store.floors_of(uid), 'kinds': FEATURE_KINDS})

    @app.route('/api/v1/dcim/floors', methods=['POST'])
    @C.edit_req
    def api_dcim_floor_new():
        store = C.store()
        # `plan` lo acuña la subida, como el de una sala: escrito aquí, una petición podría
        # apuntar una planta al dibujo de otra sin subir nada.
        data = _without(request.get_json(silent=True) or {}, ('plan', 'area_uid'))
        site = str(data.get('site_uid') or '')
        if not store or not store.sites.get(site):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not _site_writable(store, site):
            return jsonify({'error': wa._t('access_denied')}), 403
        if not str(data.get('name') or '').strip():
            return jsonify({'error': wa._t('dcim_name_required')}), 400
        data['level'] = int(_num(data.get('level')))
        return jsonify({'uid': store.floors.create(data, actor=C.actor())})

    @app.route('/api/v1/dcim/floors/<uid>', methods=['PUT'])
    @C.edit_req
    def api_dcim_floor_edit(uid):
        store = C.store()
        floor, site = _floor_site(store, uid)
        if not floor:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not _site_writable(store, site):
            return jsonify({'error': wa._t('access_denied')}), 403
        # Ni el plano ni la sede: el plano lo acuña la subida, y cambiar de sede una planta
        # dejaría sus salas colgando de un edificio que no es el suyo.
        data = _without(request.get_json(silent=True) or {}, ('plan', 'site_uid', 'area_uid'))
        if 'name' in data and not str(data.get('name') or '').strip():
            return jsonify({'error': wa._t('dcim_name_required')}), 400
        if 'level' in data:
            data['level'] = int(_num(data.get('level')))
        store.floors.update(uid, data, actor=C.actor())
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/floors/<uid>', methods=['DELETE'])
    @C.edit_req
    def api_dcim_floor_del(uid):
        """Quitar una planta. Sus salas NO se borran: se quedan en la sede, sin colocar. Una
        sala es un registro con racks dentro, y quitar el dibujo de una planta no puede llevarse
        el inventario de nadie."""
        store = C.store()
        floor, site = _floor_site(store, uid)
        if not floor:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not _site_writable(store, site):
            return jsonify({'error': wa._t('access_denied')}), 403
        # Su zona general, si está VACÍA, se va con ella: es una sala que existía solo para
        # sostener lo suelto de esta planta, y sin planta ni nada dentro se quedaría en el árbol
        # como una sala «sin colocar» que nadie creó. Con algo dentro se queda, como las demás.
        area = str(floor.get('area_uid') or '')
        if area and store.rooms.get(area) and not store.racks_of(area)                 and not store.features_of(area):
            store.rooms.delete(area)
            store.forget_scope('room', area)
        for room in store.rooms.list('floor_uid = ?', (uid,)):
            store.rooms.update(room['uid'], {'floor_uid': ''}, actor=C.actor())
        store.floors.delete(uid)
        name = str(floor.get('plan') or '')
        if name:
            dcim_media.forget(wa._var_dir or '', name, C.media_dir())
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/floors/<uid>/area', methods=['POST'])
    @C.edit_req
    def api_dcim_floor_area(uid):
        """La zona general de la planta: la que hay, o una nueva la primera vez.

        La llama la pantalla antes de poner algo en la planta fuera de toda sala. Si la que se
        apuntó ya no existe —alguien borró esa sala—, se hace otra: una zona que apunta a una sala
        que no está es un rack que se crea en ninguna parte.
        """
        store = C.store()
        floor, site = _floor_site(store, uid)
        if not floor:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not _site_writable(store, site):
            return jsonify({'error': wa._t('access_denied')}), 403
        area = str(floor.get('area_uid') or '')
        if area and store.rooms.get(area):
            return jsonify({'room_uid': area})
        nombre = '%s · %s' % (str(floor.get('name') or ''), wa._t('dcim_floor_area'))
        area = store.rooms.create({'site_uid': site, 'name': nombre, 'floor_uid': uid,
                                   'pos_x': 0, 'pos_y': 0, 'rotation': 0}, actor=C.actor())
        store.floors.update(uid, {'area_uid': area}, actor=C.actor())
        return jsonify({'room_uid': area})

    @app.route('/api/v1/dcim/floors/<uid>/plan', methods=['POST'])
    @C.edit_req
    def api_dcim_floor_plan(uid):
        """El plano de fondo de una planta, por el mismo camino que el de una sala: el tipo se
        decide por lo que HAY dentro del fichero, y el nombre lo acuña el panel."""
        store = C.store()
        floor, site = _floor_site(store, uid)
        if not floor:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not _site_writable(store, site):
            return jsonify({'error': wa._t('access_denied')}), 403
        blob = b''
        up = (request.files or {}).get('file')
        if up is not None:
            blob = up.read(dcim_media.MAX_BYTES + 1)
        elif request.data:
            blob = request.data[:dcim_media.MAX_BYTES + 1]
        name, err = dcim_media.save(wa._var_dir or '', blob, C.media_dir())
        if err:
            return jsonify({'error': wa._t(err)}), 400
        old = str(floor.get('plan') or '')
        store.floors.update(uid, {'plan': name}, actor=C.actor())
        if old and old != name:
            dcim_media.forget(wa._var_dir or '', old, C.media_dir())
        return jsonify({'plan': name})

    @app.route('/api/v1/dcim/floors/<uid>/plan', methods=['DELETE'])
    @C.edit_req
    def api_dcim_floor_plan_delete(uid):
        store = C.store()
        floor, site = _floor_site(store, uid)
        if not floor:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not _site_writable(store, site):
            return jsonify({'error': wa._t('access_denied')}), 403
        name = str(floor.get('plan') or '')
        store.floors.update(uid, {'plan': ''}, actor=C.actor())
        if name:
            dcim_media.forget(wa._var_dir or '', name, C.media_dir())
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/rooms/<uid>/plan', methods=['POST'])
    @C.edit_req
    def api_dcim_room_plan(uid):
        """Put a floor plan on a room.

        The type is decided by what is INSIDE the file: an extension is a claim by whoever
        uploaded it, and the first bytes of a PNG are not. What the file was CALLED travels into
        the description of nothing — it is not kept, because a name chosen by a request is the
        one thing that must never reach a filesystem.
        """
        store = C.store()
        room = store.rooms.get(uid) if store else None
        if not room:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not C.may_write(store, store.owners_map(), C.seen(), 'room', uid):
            return jsonify({'error': wa._t('access_denied')}), 403
        blob = b''
        up = (request.files or {}).get('file')
        if up is not None:
            blob = up.read(dcim_media.MAX_BYTES + 1)
        elif request.data:
            blob = request.data[:dcim_media.MAX_BYTES + 1]
        name, err = dcim_media.save(wa._var_dir or '', blob, C.media_dir())
        if err:
            return jsonify({'error': wa._t(err)}), 400
        # The one it replaces goes, or every re-upload leaves a file nothing points at and the
        # folder grows for the life of the installation.
        old = str(room.get('plan') or '')
        store.rooms.update(uid, {'plan': name}, actor=C.actor())
        if old and old != name:
            dcim_media.forget(wa._var_dir or '', old, C.media_dir())
        return jsonify({'plan': name})

    @app.route('/api/v1/dcim/rooms/<uid>/plan', methods=['DELETE'])
    @C.edit_req
    def api_dcim_room_plan_delete(uid):
        store = C.store()
        room = store.rooms.get(uid) if store else None
        if not room:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not C.may_write(store, store.owners_map(), C.seen(), 'room', uid):
            return jsonify({'error': wa._t('access_denied')}), 403
        name = str(room.get('plan') or '')
        store.rooms.update(uid, {'plan': ''}, actor=C.actor())
        if name:
            dcim_media.forget(wa._var_dir or '', name, C.media_dir())
        return jsonify({'ok': True})

    # `<path:name>` y no `<name>`: desde que un nombre lleva su subcarpeta —`own/…`,
    # `library/…`— hay una barra dentro, y una regla que no la cruza devolvería 404 sobre una
    # imagen que está perfectamente guardada.
    @app.route('/api/v1/dcim/media/<path:name>', methods=['GET'])
    @C.view_req
    def api_dcim_media(name):
        """One stored picture.

        `dcim_view` and no narrower: a floor plan is the shape of a room, which everybody who
        may open the section is already looking at. Narrowing it per company would mean a room
        whose plan half the readers cannot see, which is a plan that cannot be used to point at
        anything.

        Served from the stored NAME — minted here, its extension decided by the content when it
        arrived — and never from anything the request said about it.
        """
        blob, err = dcim_media.read(wa._var_dir or '', name, C.media_dir())
        if err:
            return jsonify({'error': wa._t(err)}), 404
        resp = app.response_class(blob, mimetype=dcim_media.content_type(name))
        # It cannot change: a new picture is a new name. So it may be cached hard, and an SVG
        # is served as a download rather than a page — an uploaded SVG is a document that can
        # carry script, and this panel is not going to be the origin that runs it.
        resp.headers['Cache-Control'] = 'private, max-age=86400, immutable'
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        if str(name).lower().endswith('.svg'):
            resp.headers['Content-Disposition'] = 'attachment'
        return resp

    # ── What is in a room besides the racks ───────────────────────────────────
    #
    # Columns, doors, partitions, cooling units, panels, trays, aisles. Nothing watches them and
    # they contain nothing — they exist so the plan can be READ and planned on. "Does another
    # row of racks fit?" cannot be answered without knowing where the column is.

    def _room_writable(uid):
        """Whether this caller may change the ROOM this piece belongs to.

        The room and not the piece: a column belongs to nobody — no company in the group bought
        it, it is simply there — so the question that means something is who may touch the room
        it stands in. Asked of the piece, the answer would be "anybody", and anybody could
        rearrange the columns of a room they cannot even open.
        """
        store = C.store()
        if not store:
            return None, None
        room = store.rooms.get(str(uid or ''))
        if not room:
            return store, None
        ok = C.may_write(store, store.owners_map(), C.seen(), 'room', room['uid'])
        return store, (room if ok else False)

    @app.route('/api/v1/dcim/rooms/<uid>/features', methods=['GET'])
    @C.view_req
    def api_dcim_features(uid):
        store = C.store()
        if not store:
            return jsonify({'features': [], 'kinds': {}})
        room = store.rooms.get(uid)
        if not room:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not dcim_owners.may_see(C.owner_of(store, store.owners_map(), 'room', uid), C.seen()):
            return jsonify({'error': wa._t('access_denied')}), 403
        # El catálogo viaja con la lista: es la misma pantalla, y las medidas de fábrica de cada
        # tipo las decide el servidor. Una paleta con sus propias medidas sería una segunda
        # verdad sobre lo que mide una puerta.
        # Las filas van con las piezas: es la misma pantalla y el mismo plano, y pedirlas
        # aparte sería una petición más para dibujar lo que ya se está dibujando.
        filas = dcim_svc.rows_roll(store.rows_of(uid), store.racks_of(uid))
        return jsonify(dict({'features': store.features_of(uid),
                             'kinds': FEATURE_KINDS,
                             'layers': list(FEATURE_LAYERS)}, **filas))

    @app.route('/api/v1/dcim/rows', methods=['POST'])
    @C.edit_req
    def api_dcim_row_new():
        """Declarar una fila.

        Con la misma puerta que las piezas y por la misma razón: una fila no es de nadie —es una
        forma de ordenar la sala— así que quien puede ordenar la sala la declara.
        """
        data = request.get_json(silent=True) or {}
        store, room = _room_writable(data.get('room_uid'))
        if not store or room is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if room is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        return jsonify({'uid': store.rows.create(data, actor=C.actor())})

    @app.route('/api/v1/dcim/rows/<uid>', methods=['PUT'])
    @C.edit_req
    def api_dcim_row_edit(uid):
        store = C.store()
        row = store.rows.get(uid) if store else None
        if not row:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        _, room = _room_writable(row.get('room_uid'))
        if room is False or room is None:
            return jsonify({'error': wa._t('access_denied')}), 403
        store.rows.update(uid, _without(request.get_json(silent=True) or {}, ('room_uid',)),
                          actor=C.actor())
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/rows/<uid>', methods=['DELETE'])
    @C.edit_req
    def api_dcim_row_del(uid):
        store = C.store()
        row = store.rows.get(uid) if store else None
        if not row:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        _, room = _room_writable(row.get('room_uid'))
        if room is False or room is None:
            return jsonify({'error': wa._t('access_denied')}), 403
        # Los racks que estaban en ella se quedan SUELTOS, no se borran. Una fila es una forma
        # de ordenar; deshacerla no deshace los armarios.
        for rack in store.racks_of(str(row.get('room_uid') or '')):
            if str(rack.get('row_uid') or '') == uid:
                store.racks.update(rack['uid'], {'row_uid': ''}, actor=C.actor())
        store.rows.delete(uid)
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/features', methods=['POST'])
    @C.edit_req
    def api_dcim_feature_new():
        data = request.get_json(silent=True) or {}
        kind = str(data.get('kind') or '')
        if kind not in FEATURE_KINDS:
            return jsonify({'error': wa._t('dcim_kind_unknown')}), 400
        store, room = _room_writable(data.get('room_uid'))
        if not store or room is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if room is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        spec = FEATURE_KINDS[kind]
        # Las medidas de fábrica si no vienen dadas: una pieza sin tamaño se dibuja como un punto
        # y hay que estirarla a mano para descubrir que era una mampara.
        body = dict(data)
        body.setdefault('width_mm', spec['w'])
        body.setdefault('depth_mm', spec['d'])
        return jsonify({'uid': store.features.create(body, actor=C.actor())})

    @app.route('/api/v1/dcim/features/<uid>', methods=['PUT'])
    @C.edit_req
    def api_dcim_feature_edit(uid):
        store = C.store()
        row = store.features.get(uid) if store else None
        if not row:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        _, room = _room_writable(row.get('room_uid'))
        if room is False or room is None:
            return jsonify({'error': wa._t('access_denied')}), 403
        data = _without(request.get_json(silent=True) or {}, ('room_uid',))
        if 'kind' in data and str(data['kind']) not in FEATURE_KINDS:
            return jsonify({'error': wa._t('dcim_kind_unknown')}), 400
        store.features.update(uid, data, actor=C.actor())
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/features/<uid>', methods=['DELETE'])
    @C.edit_req
    def api_dcim_feature_del(uid):
        store = C.store()
        row = store.features.get(uid) if store else None
        if not row:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        _, room = _room_writable(row.get('room_uid'))
        if room is False or room is None:
            return jsonify({'error': wa._t('access_denied')}), 403
        store.features.delete(uid)
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/rooms/<uid>/import', methods=['POST'])
    @C.edit_req
    def api_dcim_import(uid):
        """Bring a plan back into this room.

        **Racks are never deleted here.** A rack is a record with equipment inside it: one the
        file does not mention stays exactly where it is. Wiping the room to match a file would
        throw away somebody's inventory because a two-month-old JSON did not name it, and that
        cannot be what a button labelled "import" does.

        They are matched **by name** — which is what people call them by, and what somebody
        typing a plan by hand would write — and only their placement is taken from the file.
        What is inside them is never in the file to begin with.

        The pieces ARE replaced wholesale: they hold nothing, and half an import mixed with what
        was already there leaves a room that is neither the old one nor the file's.

        What happened comes back in the answer, counted. An import that silently did less than
        it looked like is an import somebody trusts wrongly.
        """
        store, room = _room_writable(uid)
        if not store or room is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if room is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get('features'), list) and not isinstance(data.get('racks'), list):
            return jsonify({'error': wa._t('dcim_import_not_a_plan')}), 400

        actor = C.actor()
        # Las medidas de la sala, si el fichero las trae. Un plano sin ellas no se puede usar
        # para lo único que sirve un plano, así que si vienen se aplican.
        medidas = {k: int(data['room'][k]) for k in ('width_mm', 'depth_mm', 'tile_mm')
                   if isinstance(data.get('room'), dict)
                   and str(data['room'].get(k, '')).lstrip('-').isdigit()}
        if medidas:
            store.rooms.update(uid, medidas, actor=actor)

        # Las piezas, enteras.
        piezas, saltadas = 0, 0
        for old in store.features_of(uid):
            store.features.delete(old['uid'])
        for row in (data.get('features') or []):
            kind = str((row or {}).get('kind') or '')
            if kind not in FEATURE_KINDS:
                saltadas += 1                    # un tipo que esta versión no conoce
                continue
            spec = FEATURE_KINDS[kind]
            store.features.create({
                'room_uid': uid, 'kind': kind,
                'label': str(row.get('label') or ''),
                'pos_x': _num(row.get('pos_x')), 'pos_y': _num(row.get('pos_y')),
                'width_mm': int(_num(row.get('width_mm')) or spec['w']),
                'depth_mm': int(_num(row.get('depth_mm')) or spec['d']),
                'rotation': int(_num(row.get('rotation'))) % 360,
                # Vacías si el fichero no las dice: las de su tipo, que es lo que eran.
                'height_mm': (max(1, int(_num(row.get('height_mm'))))
                              if row.get('height_mm') not in (None, '') else None),
                'base_mm': (max(0, int(_num(row.get('base_mm'))))
                            if row.get('base_mm') not in (None, '') else None),
            }, actor=actor)
            piezas += 1

        # Y los racks, por nombre y sin borrar ninguno.
        por_nombre = {str(r.get('name') or ''): r for r in store.racks_of(uid)}
        movidos = creados = 0
        for row in (data.get('racks') or []):
            nombre = str((row or {}).get('name') or '').strip()
            if not nombre:
                continue
            sitio = {'pos_x': _num(row.get('pos_x')), 'pos_y': _num(row.get('pos_y')),
                     'rotation': int(_num(row.get('rotation'))) % 360}
            # A qué altura cuelga es parte de dónde está. Solo si el fichero lo dice: uno
            # exportado antes de que existiera no sabe nada de ello, y leer su silencio como
            # «en el suelo» bajaría al suelo un rack que alguien había colgado.
            if 'base_mm' in row:
                sitio['base_mm'] = max(0, int(_num(row.get('base_mm'))))
            if nombre in por_nombre:
                store.racks.update(por_nombre[nombre]['uid'], sitio, actor=actor)
                movidos += 1
            else:
                store.racks.create(dict(sitio, room_uid=uid, name=nombre,
                                        u_height=int(_num(row.get('u_height')) or 42),
                                        width_mm=int(_num(row.get('width_mm')) or 600),
                                        depth_mm=int(_num(row.get('depth_mm')) or 1000)),
                                   actor=actor)
                creados += 1
        return jsonify({'features': piezas, 'skipped': saltadas,
                        'racks_moved': movidos, 'racks_new': creados,
                        'racks_kept': len([n for n in por_nombre
                                           if n not in {str((r or {}).get('name') or '').strip()
                                                        for r in (data.get('racks') or [])}])})

    # ── Power ─────────────────────────────────────────────────────────────────
    #
    # The question this exists for is not how many watts there are. It is: if branch A drops,
    # what goes dark? A room with two UPS, two strips per cabinet and dual-PSU kit everywhere is
    # fine — until somebody plugs a server's second cable into the strip next door because
    # theirs was full, and for two years nobody knows.

    # Referenciadas para que un analizador no las dé por muertas: Flask se las
    # queda por su ruta.
    _ = (api_dcim_orgs, api_dcim_site_photo, api_dcim_site_photo_delete)
