#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""De dónde viene la corriente: acometidas, cuadros, SAI, regletas y cables.

La cadena aguas arriba y lo que cuelga de ella. Aquí vive lo que contesta «¿qué se
apaga si cae esta rama?», que es la pregunta que nadie quiere hacerse en caliente.

Rutas:

    POST    /api/v1/dcim/links
    PUT     /api/v1/dcim/links/<uid>
    DELETE  /api/v1/dcim/links/<uid>
    GET     /api/v1/dcim/racks/<uid>/cables
    GET     /api/v1/dcim/racks/<uid>/power
    GET     /api/v1/dcim/sources
    POST    /api/v1/dcim/sources
    PUT     /api/v1/dcim/sources/<uid>
    DELETE  /api/v1/dcim/sources/<uid>
    POST    /api/v1/dcim/sources/<uid>/clone
"""

from __future__ import annotations

from flask import jsonify, request, session

from lib.core.dcim import owners as dcim_owners
from lib.core.dcim import service as dcim_svc
from lib.core.dcim.store import FEED_COLORS, FEEDS, LINK_KINDS, SOURCE_KINDS
from lib.core.dcim.routes._common import _without


def register(app, wa, C):
    """Las rutas de esta área. *C* es lo que comparten todas: los permisos y los ayudantes."""
    def _rack_writable(uid):
        """Whether this caller may change the RACK a strip or a cable belongs to."""
        store = C.store()
        if not store:
            return None, None
        rack = store.racks.get(str(uid or ''))
        if not rack:
            return store, None
        ok = C.may_write(store, store.owners_map(), C.seen(), 'rack', rack['uid'])
        return store, (rack if ok else False)

    @app.route('/api/v1/dcim/sources', methods=['GET'])
    @C.view_req
    def api_dcim_sources():
        """Lo que hay aguas arriba, con la cadena de cada regleta y lo que no cuadra.

        De una sede si se pide (`?site=`), y si no de todas: un cuadro general alimenta varias
        salas, y la cadena de una regleta puede empezar en un sitio que la sala no conoce.

        **No se estrecha por empresa**: un cuadro eléctrico no es de una sociedad, es del
        edificio, y saber que la corriente pasa por un SAI es lo que evita un susto colectivo.
        Lo que sí se estrecha es de qué REGLETAS se habla — sin ese filtro la cadena delataría
        qué armarios hay en una sede ajena.
        """
        store = C.store()
        if not store:
            return jsonify({'sources': [], 'paths': {}, 'warnings': []})
        site = str(request.args.get('site') or '')
        fuentes = store.sources_of(site)
        said, allowed = store.owners_map(), C.seen()
        reach = dcim_svc.reachable(store, said, allowed)
        pdus = []
        for sitio in store.sites.list():
            if site and sitio['uid'] != site:
                continue
            for sala in store.rooms_of(sitio['uid']):
                for rack in store.racks_of(sala['uid']):
                    visible = dcim_owners.may_see(
                        C.owner_of(store, said, 'rack', rack['uid']), allowed)
                    if visible or dcim_svc.llega(reach, 'rack', rack['uid']):
                        pdus.extend(store.pdus_of(rack['uid']))
        out = dcim_svc.power_path(fuentes, pdus)
        out['sources'] = fuentes
        out['kinds'] = list(SOURCE_KINDS)
        return jsonify(out)

    def _upstream_bad(store, uid, nuevo):
        """Por qué NO puede colgar de *nuevo*, o `''` si puede.

        Tres cosas, y las tres acaban igual: la fila deja de dibujarse. El árbol se pinta desde
        las raíces hacia abajo, así que lo que cuelga de algo que no existe —o de sí mismo, o de
        alguien que a su vez cuelga de ello— no está bajo la raíz ni bajo nadie, y desaparece de
        la pantalla junto con su botón de borrar. Un dato que se puede escribir y no se puede
        corregir es peor que uno que se rechaza.
        """
        nuevo = str(nuevo or '')
        if not nuevo:
            return ''                           # el principio de la cadena, que es lo normal
        if nuevo == str(uid or ''):
            return wa._t('dcim_upstream_self')
        if not store.sources.get(nuevo):
            return wa._t('dcim_not_found')
        # Sin mirar el bypass: un ciclo lo es con el interruptor echado o quitado, y recorrer
        # solo lo que hoy conduce dejaría entrar el que se cierra por el nodo saltado.
        arriba = dcim_svc.chain_up(store.sources.list(), nuevo, honour_bypass=False)
        if any(str(x.get('uid') or '') == str(uid or '') for x in arriba):
            return wa._t('dcim_upstream_loop')
        return ''

    def _source_writable(uid):
        """Una fuente cuelga de una SEDE: quien puede editar esa sede la declara.

        Y una sin sede —una acometida apuntada antes de decidir de qué sede es— la toca quien
        pueda editar el inventario, que es lo único exigible a algo que aún no está en ninguna
        parte.
        """
        store = C.store()
        row = store.sources.get(str(uid or '')) if store else None
        if not row:
            return store, None
        sede = str(row.get('site_uid') or '')
        if not sede:
            return store, row
        ok = C.may_write(store, store.owners_map(), C.seen(), 'site', sede)
        return store, (row if ok else False)

    @app.route('/api/v1/dcim/sources', methods=['POST'])
    @C.edit_req
    def api_dcim_source_new():
        store = C.store()
        data = request.get_json(silent=True) or {}
        if str(data.get('kind') or 'panel') not in SOURCE_KINDS:
            return jsonify({'error': wa._t('dcim_source_kind_unknown')}), 400
        sede = str(data.get('site_uid') or '')
        if sede:
            if not store.sites.get(sede):
                return jsonify({'error': wa._t('dcim_not_found')}), 404
            if not C.may_write(store, store.owners_map(), C.seen(), 'site', sede):
                return jsonify({'error': wa._t('access_denied')}), 403
        # Sin uid todavía: lo único que se puede comprobar es que el padre exista, y con eso
        # basta — una fila que aún no existe no puede estar en el ciclo de nadie.
        malo = _upstream_bad(store, '', data.get('upstream_uid'))
        if malo:
            return jsonify({'error': malo}), 400
        return jsonify({'uid': store.sources.create(data, actor=C.actor())})

    @app.route('/api/v1/dcim/sources/<uid>', methods=['PUT'])
    @C.edit_req
    def api_dcim_source_edit(uid):
        store, row = _source_writable(uid)
        if row is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if row is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        data = _without(request.get_json(silent=True) or {}, ('site_uid',))
        if 'kind' in data and str(data['kind']) not in SOURCE_KINDS:
            return jsonify({'error': wa._t('dcim_source_kind_unknown')}), 400
        if 'upstream_uid' in data:
            malo = _upstream_bad(store, uid, data.get('upstream_uid'))
            if malo:
                return jsonify({'error': malo}), 400
        store.sources.update(uid, data, actor=C.actor())
        # Echar o quitar un bypass no es editar un campo: es una maniobra eléctrica, y quién la
        # hizo y cuándo es lo primero que se pregunta cuando algo se apaga.
        if 'bypass' in data:
            wa._audit('dcim_bypass', detail={'source': uid,
                                             'name': str(row.get('name') or ''),
                                             'on': bool(int(data.get('bypass') or 0))})
        return jsonify({'ok': True})

    #: Cuántas filas como mucho se copian de una vez. Una instalación de verdad no llega; el
    #: tope está para que un dato ya torcido —una cadena que se muerde la cola de antes— no
    #: convierta un clic en cien mil filas.
    _CLONE_MAX = 200

    @app.route('/api/v1/dcim/sources/<uid>/clone', methods=['POST'])
    @C.edit_req
    def api_dcim_source_clone(uid):
        """Copiar una fuente y **todo lo que cuelga de ella**, colgando la copia de donde ella.

        Un cuadro de sala se declara igual en la sala de al lado, con sus dos SAI y sus cuadros
        de salida detrás: escribirlo a mano son quince filas y cuatro sitios donde equivocarse de
        padre. Aquí y no en quince llamadas desde la pantalla — a mitad de la decimoquinta, un
        error de red deja medio árbol escrito y nadie sabe cuál era la mitad.
        """
        store, row = _source_writable(uid)
        if row is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if row is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        hijos: dict = {}
        for f in store.sources.list():
            hijos.setdefault(str(f.get('upstream_uid') or ''), []).append(f)
        sufijo = wa._t('dcim_cat_copy_suffix')
        hechas: list = []
        visto: set = set()

        def copia(fila, padre, raiz):
            viejo = str(fila.get('uid') or '')
            # Un ciclo ya guardado de antes no puede convertir esto en un bucle: se copia lo que
            # se alcanza una vez y se para.
            if viejo in visto or len(hechas) >= _CLONE_MAX:
                return ''
            visto.add(viejo)
            datos = {c: fila.get(c) for c in ('site_uid', 'kind', 'capacity_w', 'autonomy_min',
                                              'description')}
            # El nombre solo lo lleva la de arriba: dentro de un árbol clonado, «SAI 1 (copia)»
            # colgando de «Cuadro sala (copia)» dice dos veces lo mismo, y lo que se busca al
            # mirarlo es el nombre del equipo.
            datos['name'] = (f'{fila.get("name") or ""} {sufijo}'.strip() if viejo == raiz
                             else str(fila.get('name') or ''))
            datos['upstream_uid'] = padre
            nuevo = store.sources.create(datos, actor=C.actor())
            hechas.append(nuevo)
            for h in hijos.get(viejo, ()):
                copia(h, nuevo, raiz)
            return nuevo

        nuevo = copia(row, str(row.get('upstream_uid') or ''), str(uid))
        return jsonify({'uid': nuevo, 'n': len(hechas)})

    @app.route('/api/v1/dcim/sources/<uid>', methods=['DELETE'])
    @C.edit_req
    def api_dcim_source_del(uid):
        store, row = _source_writable(uid)
        if row is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if row is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        # Lo que colgaba de ella queda SIN DECIR de qué cuelga, que es la verdad: ese cuadro ya
        # no está declarado. Dejar el uid apuntando a nada haría que la cadena terminara en un
        # sitio que no existe y nadie sabría por qué.
        for otra in store.sources.list('upstream_uid = ?', (uid,)):
            store.sources.update(otra['uid'], {'upstream_uid': ''}, actor=C.actor())
        for pdu in store.pdus.list('source_uid = ?', (uid,)):
            store.pdus.update(pdu['uid'], {'source_uid': ''}, actor=C.actor())
        store.sources.delete(uid)
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/racks/<uid>/power', methods=['GET'])
    @C.view_req
    def api_dcim_power(uid):
        """How a rack is fed.

        Narrowed with care, because a shared cabinet has a fine edge here. The strips' TOTALS
        are everybody's — how many outlets are left and how much has been declared — because
        that is precisely what planning needs: without it a subsidiary cannot know whether
        another server fits. It is the same fact as "U 12 is taken".

        Whose each cable is, is not. The per-device list narrows like everything else, and a
        foreign device shows as drawing power and nothing more. And a warning about somebody
        else's device is reported to nobody else: "SW-CORE hangs off one branch" is the IT
        department's problem, and the subsidiary can neither fix it nor needs to know it exists.
        """
        store = C.store()
        if not store:
            return jsonify({'pdus': [], 'items': [], 'warnings': []})
        rack = store.racks.get(uid)
        if not rack:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        said, allowed = store.owners_map(), C.seen()
        if not dcim_owners.may_see(C.owner_of(store, said, 'rack', uid), allowed):
            return jsonify({'error': wa._t('access_denied')}), 403
        pdus = store.pdus_of(uid)
        # TODOS los cables para los totales de cada regleta —eso es dato de planificación— y
        # solo los equipos visibles para la lista por equipo y para los avisos.
        feeds = store.feeds_of([p['uid'] for p in pdus])
        # El dueño de cada equipo se resuelve UNA vez y sirve para las dos cosas: decidir si
        # se ve, y sumar el consumo por sociedad. Resolverlo dos veces serían dos copias de la
        # regla de herencia, que es como dos pantallas acaban discrepando sobre de quién es lo
        # mismo.
        duenos = {it['uid']: C.owner_of(store, said, 'item', it['uid'])
                  for it in store.items_of(uid)}
        mios = [it for it in store.items_of(uid)
                if dcim_owners.may_see(duenos.get(it['uid'], ''), allowed)]
        out = dcim_svc.power_of_rack(pdus, feeds, mios, C.states(), duenos)
        out['feeds'] = FEEDS
        # Los colores por defecto viajan con la respuesta: la pantalla no tiene por qué
        # llevar una segunda copia de qué color es la rama A.
        out['feed_colors'] = FEED_COLORS
        return jsonify(out)

    def _power_crud(kind, part, dueno, guard=None):
        """El CRUD de una regleta y el de un cable, que solo se diferencian en de quién cuelgan.

        El permiso se mira siempre en el ARMARIO: ni una regleta ni un cable son de nadie por
        separado, y quien puede ordenar el armario puede enchufar en él.

        *guard* es la bandera que hace falta ADEMÁS. Por defecto la de ordenar el armario, pero
        el cableado tiene la suya: mover un equipo de U y decir por dónde va un cable son dos
        trabajos, muchas veces de dos personas, y el dominio declaró esa bandera precisamente
        para poder separarlas.
        """
        puerta = guard or C.edit_req

        @app.route(f'/api/v1/dcim/{kind}', methods=['POST'],
                   endpoint=f'api_dcim_{kind}_new')
        @puerta
        def _create():
            data = request.get_json(silent=True) or {}
            store, rack = _rack_writable(dueno(C.store(), data))
            if not store or rack is None:
                return jsonify({'error': wa._t('dcim_not_found')}), 404
            if rack is False:
                return jsonify({'error': wa._t('access_denied')}), 403
            if kind == 'pdus' and str(data.get('feed') or 'a') not in FEEDS:
                return jsonify({'error': wa._t('dcim_feed_unknown')}), 400
            return jsonify({'uid': getattr(store, part).create(data, actor=C.actor())})

        @app.route(f'/api/v1/dcim/{kind}/<uid>', methods=['PUT'],
                   endpoint=f'api_dcim_{kind}_edit')
        @puerta
        def _update(uid):
            store = C.store()
            row = getattr(store, part).get(uid) if store else None
            if not row:
                return jsonify({'error': wa._t('dcim_not_found')}), 404
            _, rack = _rack_writable(dueno(store, row))
            if rack is False or rack is None:
                return jsonify({'error': wa._t('access_denied')}), 403
            data = _without(request.get_json(silent=True) or {}, ('rack_uid', 'item_uid',
                                                                 'pdu_uid'))
            if 'feed' in data and str(data['feed']) not in FEEDS:
                return jsonify({'error': wa._t('dcim_feed_unknown')}), 400
            getattr(store, part).update(uid, data, actor=C.actor())
            return jsonify({'ok': True})

        @app.route(f'/api/v1/dcim/{kind}/<uid>', methods=['DELETE'],
                   endpoint=f'api_dcim_{kind}_del')
        @puerta
        def _delete(uid):
            store = C.store()
            row = getattr(store, part).get(uid) if store else None
            if not row:
                return jsonify({'error': wa._t('dcim_not_found')}), 404
            _, rack = _rack_writable(dueno(store, row))
            if rack is False or rack is None:
                return jsonify({'error': wa._t('access_denied')}), 403
            if kind == 'pdus':
                # Quitar la regleta se lleva sus cables. Dejarlos sería una lista de equipos
                # alimentados por algo que ya no existe, y el recuento de tomas de la regleta
                # siguiente saldría mal sin que nadie supiera por qué.
                for cable in store.feeds_of([uid]):
                    store.feeds.delete(cable['uid'])
            getattr(store, part).delete(uid)
            return jsonify({'ok': True})

    # Una regleta cuelga de su armario; un cable, del armario de SU regleta.
    _power_crud('pdus', 'pdus', lambda st, row: (row or {}).get('rack_uid'))
    _power_crud('feeds', 'feeds',
                lambda st, row: ((st.pdus.get(str((row or {}).get('pdu_uid') or '')) or {})
                                 .get('rack_uid')) if st else None)

    # ── Cabling ───────────────────────────────────────────────────────────────
    #
    # This is where the inventory stops being documentation. A declared cable is not worth much
    # on its own; it is worth what it makes possible — having BOTH halves. "The switch sees this
    # server on Gi1/0/7" is an isolated fact; with the label beside it, it becomes "and what was
    # declared says that port goes to panel B, so either the label lies or somebody moved the
    # patch lead".

    @app.route('/api/v1/dcim/racks/<uid>/cables', methods=['GET'])
    @C.view_req
    def api_dcim_cables(uid):
        """What is declared in this rack, against what the devices report seeing.

        Narrowed like everything else: only the devices this reader may see contribute cables
        and only their links are judged. A cable of somebody else's is not theirs to reconcile.

        The topology is the SAME one the infrastructure map is drawn from — asked for through
        one function, so the two screens cannot end up disagreeing about the same fleet.
        """
        store = C.store()
        if not store:
            return jsonify({'cables': [], 'undeclared': [], 'counts': {}})
        rack = store.racks.get(uid)
        if not rack:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        said, allowed = store.owners_map(), C.seen()
        if not dcim_owners.may_see(C.owner_of(store, said, 'rack', uid), allowed):
            return jsonify({'error': wa._t('access_denied')}), 403
        mios = [it for it in store.items_of(uid)
                if dcim_owners.may_see(C.owner_of(store, said, 'item', it['uid']), allowed)]
        cables = store.cables_of([it['uid'] for it in mios])
        # Los items del OTRO extremo también hacen falta para poder nombrarlo: un cable que sale
        # de este armario acaba en otro, y una fila que dice «va a 4f2a-…» no la lee nadie.
        #
        # Pero pasan por la MISMA puerta que todo lo demás. Un equipo ajeno conserva su uid —el
        # dibujo lo necesita para colocar la U ocupada— así que sin esta comprobación bastaba
        # declarar un cable hacia ese uid para que la respuesta devolviera su etiqueta: justo el
        # dato que un armario compartido existe para no dar. Las fugas de esta clase no salen por
        # la pantalla que enseña la cosa, sino por otra que la necesita de paso y no repite la
        # pregunta.
        otros = {c[lado] for c in cables for lado in ('a_item', 'b_item')}
        otros -= {it['uid'] for it in mios}
        vecinos = []
        for u in otros:
            it = store.items.get(u)
            if not it:
                continue
            if dcim_owners.may_see(C.owner_of(store, said, 'item', u), allowed):
                vecinos.append(it)
            else:
                # Existe y ocupa, y nada más — la misma respuesta que da el armario compartido.
                vecinos.append(dcim_owners.opaque(it))
        # El MISMO mapa que dibuja infraestructura, pedido por lo que el panel declara. Sin
        # él se sigue: lo declarado se lee igual, y una pantalla que no abre porque una sonda no
        # ha contestado es peor que una que dice menos.
        edges = []
        armar = getattr(wa, '_infra_topology', None)
        if callable(armar):
            try:
                edges = (armar(session.get('lang') or wa._DEFAULT_LANG).get('edges') or [])
            except Exception:                       # pylint: disable=broad-except
                edges = []
        return jsonify(dcim_svc.cable_check(cables, mios + vecinos, edges))

    _power_crud('cables', 'cables',
                lambda st, row: ((st.items.get(str((row or {}).get('a_item') or '')) or {})
                                 .get('rack_uid')) if st else None,
                guard=C.cable_req)

    # ── Between sites ─────────────────────────────────────────────────────────
    #
    # The same question as power, one level up: if this link drops, which site is on its own?
    # And it breaks just as quietly — two circuits from two carriers that turn out to share a
    # trench, or a branch office with one real path that nobody noticed because the map shows
    # two lines and one of them is a VPN over the other.

    @app.route('/api/v1/dcim/links', methods=['POST'])
    @C.edit_req
    def api_dcim_link_new():
        store = C.store()
        data = request.get_json(silent=True) or {}
        if not store:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if str(data.get('kind') or 'ipsec') not in LINK_KINDS:
            return jsonify({'error': wa._t('dcim_link_kind_unknown')}), 400
        said, allowed = store.owners_map(), C.seen()
        sedes = [str(data.get('a_site') or ''), str(data.get('b_site') or '')]
        if not all(sedes) or sedes[0] == sedes[1]:
            return jsonify({'error': wa._t('dcim_link_two_sites')}), 400
        for sede in sedes:
            if not store.sites.get(sede):
                return jsonify({'error': wa._t('dcim_not_found')}), 404
            # Las DOS sedes: un enlace cambia lo que se ve en las dos puntas, y pedir permiso
            # solo sobre una dejaría dibujar líneas hasta sedes que no se pueden ni abrir.
            if not C.may_write(store, said, allowed, 'site', sede):
                return jsonify({'error': wa._t('access_denied')}), 403
        return jsonify({'uid': store.links.create(data, actor=C.actor())})

    def _link_writable(uid):
        store = C.store()
        row = store.links.get(uid) if store else None
        if not row:
            return None, None
        said, allowed = store.owners_map(), C.seen()
        ok = all(C.may_write(store, said, allowed, 'site', str(row.get(lado) or ''))
                 for lado in ('a_site', 'b_site'))
        return store, (row if ok else False)

    @app.route('/api/v1/dcim/links/<uid>', methods=['PUT'])
    @C.edit_req
    def api_dcim_link_edit(uid):
        store, row = _link_writable(uid)
        if row is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if row is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        data = _without(request.get_json(silent=True) or {}, ('a_site', 'b_site'))
        if 'kind' in data and str(data['kind']) not in LINK_KINDS:
            return jsonify({'error': wa._t('dcim_link_kind_unknown')}), 400
        store.links.update(uid, data, actor=C.actor())
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/links/<uid>', methods=['DELETE'])
    @C.edit_req
    def api_dcim_link_del(uid):
        store, row = _link_writable(uid)
        if row is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if row is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        store.links.delete(uid)
        return jsonify({'ok': True})

    # Referenciadas para que un analizador no las dé por muertas: Flask se las
    # queda por su ruta.
    _ = (api_dcim_sources, api_dcim_source_new, api_dcim_source_edit,)
