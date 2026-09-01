#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dónde está cada cosa: empresas, sedes, salas, racks y lo que hay en el suelo.

La contención —de la calle al armario— y la pertenencia, que es la otra pregunta:
dónde está algo y de quién es no se contestan igual ni las hace la misma persona.

Rutas:

    POST    /api/v1/dcim/features
    PUT     /api/v1/dcim/features/<uid>
    DELETE  /api/v1/dcim/features/<uid>
    GET     /api/v1/dcim/media/<path:name>
    GET     /api/v1/dcim/orgs
    POST    /api/v1/dcim/orgs
    PUT     /api/v1/dcim/orgs/<uid>
    DELETE  /api/v1/dcim/orgs/<uid>
    POST    /api/v1/dcim/owner
    GET     /api/v1/dcim/rooms/<uid>/features
    POST    /api/v1/dcim/rooms/<uid>/import
    POST    /api/v1/dcim/rooms/<uid>/plan
    DELETE  /api/v1/dcim/rooms/<uid>/plan
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
from lib.core.dcim.store import FEATURE_KINDS, FEATURE_LAYERS, OWNER_SCOPES
from lib.core.dcim.routes._common import _num, _without


def register(app, wa, C):
    """Las rutas de esta área. *C* es lo que comparten todas: los permisos y los ayudantes."""
    @app.route('/api/v1/dcim/orgs', methods=['GET'])
    @C.view_req
    def api_dcim_orgs():
        store = C.store()
        if store is None:
            return jsonify({'orgs': []})
        allowed = C.seen()
        rows = store.orgs.list()
        if allowed is not None:
            rows = [r for r in rows if r['uid'] in allowed]
        return jsonify({'orgs': rows})

    @app.route('/api/v1/dcim/orgs', methods=['POST'])
    @C.org_edit_req
    def api_dcim_org_create():
        store = C.store()
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': wa._t('dcim_name_required')}), 400
        uid = store.orgs.create({'name': name, 'short': str(data.get('short') or '').strip(),
                                 'description': str(data.get('description') or '')},
                                actor=C.actor())
        return jsonify({'uid': uid})

    @app.route('/api/v1/dcim/orgs/<uid>', methods=['PUT'])
    @C.org_edit_req
    def api_dcim_org_update(uid):
        store = C.store()
        if not store.orgs.get(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        store.orgs.update(uid, request.get_json(silent=True) or {}, actor=C.actor())
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/orgs/<uid>', methods=['DELETE'])
    @C.org_edit_req
    def api_dcim_org_delete(uid):
        store = C.store()
        # …and every ownership that named it, or the rows outlive the company and the resolver
        # returns a uid nothing can be looked up by.
        for (scope, thing), org in list(store.owners_map().items()):
            if org == uid:
                store.set_owner(scope, thing, '')
        store.orgs.delete(uid)
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/owner', methods=['POST'])
    @C.org_edit_req
    def api_dcim_set_owner():
        """Say whose something is. An empty ``org_uid`` stops saying, which is back to
        inheriting — a different state from "owned by nobody"."""
        store = C.store()
        data = request.get_json(silent=True) or {}
        scope = str(data.get('scope') or '')
        uid = str(data.get('uid') or '')
        if scope not in OWNER_SCOPES or not uid:
            return jsonify({'error': wa._t('dcim_bad_scope')}), 400
        org = str(data.get('org_uid') or '')
        if org and not store.orgs.get(org):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        store.set_owner(scope, uid, org, actor=C.actor())
        wa._audit('dcim_owner_set', detail={'scope': scope, 'uid': uid,
                                            'org': org, 'cleared': not org})
        return jsonify({'ok': True})

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
                room['rackList'] = racks
                room['racks'] = len(racks)
                room['roll'] = roll['room'].get(room['uid']) or {}
            out.append(dict(site, rooms=rooms,
                            roll=roll['site'].get(site['uid']) or {}))
        return jsonify({'sites': out})

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
    _ = (api_dcim_orgs, api_dcim_org_create, api_dcim_org_update,)
