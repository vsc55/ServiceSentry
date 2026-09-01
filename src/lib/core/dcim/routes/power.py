#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""De dónde viene la corriente: acometidas, cuadros, SAI, regletas y cables.

La cadena aguas arriba y lo que cuelga de ella. Aquí vive lo que contesta «¿qué se
apaga si cae esta rama?», que es la pregunta que nadie quiere hacerse en caliente.

Rutas:

    POST    /api/v1/dcim/links
    PUT     /api/v1/dcim/links/<uid>
    DELETE  /api/v1/dcim/links/<uid>
    GET     /api/v1/dcim/cables
    GET     /api/v1/dcim/cables/<uid>/run
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
from lib.core.dcim.store import (CABLE_CATEGORIES, CABLE_COLORS, CABLE_KINDS,
                                 FEED_CATEGORIES, FEED_COLORS,
                                 FEEDS, LINK_KINDS, ROLES_MUDOS, SOURCE_KINDS)
from lib.core.dcim import store as dcim_store
from lib.core.dcim.routes._common import _without, scan_pages


#: Cuántos colores ya usados se ofrecen. Una instalación tiene cinco o seis; un desplegable con
#: cuarenta entradas de código hexadecimal no es una ayuda, es otra rueda.
_COLORS_USED_MAX = 24

#: Cuántos paneles seguidos se atraviesan buscando el otro extremo de un camino. Tres son un
#: panel de sala, uno de rack y el latiguillo — más que eso no es una instalación, es un dato
#: torcido, y un recorrido sin tope convierte un ciclo declarado por error en una consulta que no
#: termina.
_PATH_HOPS = 3


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

    def _loop_bad(a_item, b_item, a_port, b_port):
        """Por qué ese cable NO puede ir de un equipo a sí mismo, o `''` si puede.

        Un **puente** es un cable de verdad: un latiguillo corto de la boca 25 a la 17 del mismo
        panel de parcheo es lo más normal del mundo, y se rechazaba de plano con «un cable va de
        un equipo a OTRO» — cierto para dos servidores y falso para un panel, que es media sala.

        Lo que no puede ser es un cable de una boca a ella misma, ni uno que dice unir un equipo
        consigo mismo sin decir por dónde: eso no describe nada que se pueda ir a mirar.
        """
        a, b = str(a_item or ''), str(b_item or '')
        if not a or a != b:
            return ''
        pa, pb = str(a_port or '').strip(), str(b_port or '').strip()
        if not pa or not pb or pa == pb:
            return wa._t('dcim_cable_same_item')
        return ''

    def _outlet_bad(pdu_uid, outlet, mine=''):
        """Por qué ese cable NO puede ir en esa toma, o `''` si puede.

        Dos cosas, y las dos son imposibles delante del armario: una toma que la regleta no
        tiene, y una toma con otro cable ya dentro. Guardarlas deja un inventario que dice algo
        que no se puede ver, y lo peor de un dato así es que se descubre desenchufando.

        El **0 pasa siempre**: es «en esa regleta, no sé en cuál», que es lo que alguien sabe
        mirando una foto, y obligarle a inventarse un número sería peor dato que ninguno.
        """
        store = C.store()
        n = int(outlet or 0)
        if n <= 0 or not store:
            return ''
        pdu = store.pdus.get(str(pdu_uid or '')) or {}
        tomas = int(pdu.get('outlets') or 0)
        # Sin tomas declaradas no se juzga: nadie ha dicho cuántas tiene, así que ningún número
        # se sale de una cuenta que no existe.
        if tomas and n > tomas:
            return wa._t('dcim_outlet_out_of_range')
        for cable in store.feeds_of([str(pdu_uid or '')]):
            if int(cable.get('outlet') or 0) == n and str(cable.get('uid') or '') != str(mine):
                return wa._t('dcim_outlet_taken')
        return ''

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
        # Las ramas que existen, con su nombre de siempre. Se llamaba `feeds`, que es también
        # como se llaman los CABLES de esta pantalla, y el contador de la pestaña lo leía como
        # tal: decía «3» —las tres ramas, `a`, `b` y ninguna— en un armario sin un solo cable
        # declarado. Un número que sale de una lista de otra cosa no da ningún error: da una
        # cifra creíble, y ésa es la peor.
        out['feed_kinds'] = list(FEEDS)
        # Los colores por defecto viajan con la respuesta: la pantalla no tiene por qué
        # llevar una segunda copia de qué color es la rama A.
        out['feed_colors'] = FEED_COLORS
        # Los que no llevan enchufe, dichos por el servidor y no copiados en la pantalla: la
        # misma razón que los colores de las ramas, y la misma lista que ya decide quién no
        # figura entre los «sin vigilar».
        out['quiet_roles'] = list(ROLES_MUDOS)
        # Y de qué par de conectores puede ser un cable de corriente, por lo mismo que los
        # colores: la pantalla no lleva una segunda copia de qué es un C13 a C14.
        out['categories'] = list(FEED_CATEGORIES)
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
            # Y un cable de un equipo a sí mismo sólo vale como PUENTE: de una boca a otra. La
            # regla vivía sólo en el navegador, que es lo mismo que no vivir en ninguna parte —
            # la escritura entra por la API con o sin pantalla delante.
            if kind == 'cables':
                malo = _loop_bad(data.get('a_item'), data.get('b_item'),
                                 data.get('a_port'), data.get('b_port'))
                if malo:
                    return jsonify({'error': malo}), 400
            if kind == 'feeds':
                malo = _outlet_bad(data.get('pdu_uid'), data.get('outlet'))
                if malo:
                    return jsonify({'error': malo}), 400
            err = C.asset(part, data)
            if err:
                return jsonify({'error': wa._t(err)}), 400
            return jsonify({'uid': getattr(store, part).create(data, actor=C.actor()),
                            'asset': str(data.get('asset') or '')})

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
            # Con la regleta de la FILA y no la del cuerpo: `pdu_uid` no se puede cambiar por
            # aquí —está en la lista de lo que se quita—, así que comprobar la del cuerpo sería
            # comprobar una toma de una regleta a la que el cable no se va a mover.
            if kind == 'feeds' and 'outlet' in data:
                malo = _outlet_bad(row.get('pdu_uid'), data.get('outlet'), uid)
                if malo:
                    return jsonify({'error': malo}), 400
            err = C.asset(part, data, uid)
            if err:
                return jsonify({'error': wa._t(err)}), 400
            getattr(store, part).update(uid, data, actor=C.actor())
            return jsonify({'ok': True, 'asset': str(data.get('asset') or '')})

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

    #: Cuántos cables devuelve una búsqueda. Doscientos no se leen; lo que se hace con una
    #: lista de doscientos es afinar la búsqueda, y para eso hay que saber que está recortada.
    _WIRE_MAX = 200

    #: Cuántos identificadores entran en un `IN` al buscar por el nombre de un extremo. Con más
    #: de quinientos coincidiendo, lo que hay que afinar es la búsqueda: un `IN` de ocho mil no
    #: es una consulta, es otro problema.
    _NAMES_MAX = 500

    def _items_matching(q: str) -> list:
        """Los equipos cuya etiqueta —o el nombre de cuyo armario— contiene *q*.

        Buscar un cable por el nombre de lo que hay en sus puntas es lo normal —«el latiguillo de
        SW01»— y ese nombre está en otra tabla. Se resuelve antes a identificadores para poder
        preguntar por ellos: dejarlo para después obligaría a traerse los cables de toda la
        instalación sólo para mirarles el nombre a las puntas.
        """
        store = C.store()
        if not q or not store:
            return []
        sql, params = dcim_store.like_clause(('label',), q)
        uids = [r['uid'] for r in store.items.list(sql, params, limit=_NAMES_MAX)]
        # Y por el nombre del ARMARIO, que es como se busca «los cables del RK-04». Los armarios
        # son pocos: se resuelven a una lista y se pregunta por sus equipos.
        rsql, rparams = dcim_store.like_clause(('name',), q)
        racks = [r['uid'] for r in store.racks.list(rsql, rparams, limit=_NAMES_MAX)]
        if racks and len(uids) < _NAMES_MAX:
            marcas = ', '.join('?' for _ in racks)
            uids += [r['uid'] for r in store.items.list(
                f'rack_uid IN ({marcas})', tuple(racks), limit=_NAMES_MAX - len(uids))]
        return list(dict.fromkeys(uids))[:_NAMES_MAX]

    def _pdus_matching(q: str) -> list:
        """Las regletas cuyo nombre —o el de cuyo armario— contiene *q*. La otra punta de un
        cable de corriente es una regleta, no un equipo."""
        store = C.store()
        if not q or not store:
            return []
        sql, params = dcim_store.like_clause(('name',), q)
        uids = [r['uid'] for r in store.pdus.list(sql, params, limit=_NAMES_MAX)]
        rsql, rparams = dcim_store.like_clause(('name',), q)
        racks = [r['uid'] for r in store.racks.list(rsql, rparams, limit=_NAMES_MAX)]
        if racks and len(uids) < _NAMES_MAX:
            marcas = ', '.join('?' for _ in racks)
            uids += [r['uid'] for r in store.pdus.list(
                f'rack_uid IN ({marcas})', tuple(racks), limit=_NAMES_MAX - len(uids))]
        return list(dict.fromkeys(uids))[:_NAMES_MAX]

    @app.route('/api/v1/dcim/cables', methods=['GET'])
    @C.view_req
    def api_dcim_cables_all():
        """Todos los cables que este lector puede ver, para buscarlos.

        **Sin pasar por un armario.** El cableado se veía dentro de un rack, así que «¿dónde está
        el cable C-014?» y «¿cuántos latiguillos de Cat 6A hay puestos?» no tenían dónde
        preguntarse: había que saber el armario ANTES de poder buscar, que es lo contrario de
        buscar.

        Aquí no hay contraste con lo que ven los dispositivos, y no por ahorrar: contrastar es
        una pregunta sobre un armario —qué se ve DESDE aquí— y armar el mapa de la flota para
        listar cables de seis salas sería pagar el mapa seis veces por un dato que esta pantalla
        no usa. El contraste sigue estando donde significa algo, que es dentro del rack.

        **Los dos: los de red y los de corriente.** Son la misma pregunta —dónde está este
        cable, cuántos de esta clase hay puestos— y viven en dos tablas por dónde acaban, no por
        lo que son. Dos listas obligarían a buscar dos veces lo mismo y a acordarse de cuál de
        las dos mirar, que es de lo que se venía huyendo.

        Se busca por lo que alguien lee: etiqueta, número de inventario, boca y el nombre de los
        dos extremos. Y se estrecha como todo lo demás — un cable entre dos equipos ajenos no es
        de este lector, y de uno con un extremo ajeno se dice lo que del extremo se puede decir.
        """
        store = C.store()
        if not store:
            return jsonify({'cables': []})
        q = str(request.args.get('q') or '').strip().lower()
        kind = str(request.args.get('kind') or '').strip()
        cat = str(request.args.get('category') or '').strip()
        said, allowed = store.owners_map(), C.seen()
        # Los equipos una vez, y de ahí sale todo: quién ve qué, cómo se llama cada extremo y en
        # qué armario está. Preguntar por cable serían dos lecturas por fila.
        items = {it['uid']: it for it in store.items.list()}
        racks = {r['uid']: r for s in store.sites.list()
                 for sala in store.rooms_of(s['uid'])
                 for r in store.racks_of(sala['uid'])}
        visible: dict = {}

        def _puedo(uid):
            uid = str(uid or '')
            if uid not in visible:
                visible[uid] = bool(items.get(uid)) and dcim_owners.may_see(
                    C.owner_of(store, said, 'item', uid), allowed)
            return visible[uid]

        def _punta(uid):
            """Cómo se llama y dónde está una punta — o nada, si es de otro."""
            it = items.get(str(uid or '')) or {}
            if not _puedo(uid):
                return {'label': '', 'role': '', 'rack': '', 'foreign': True}
            r = racks.get(str(it.get('rack_uid') or '')) or {}
            return {'label': str(it.get('label') or ''), 'role': str(it.get('role') or ''),
                    'rack': str(r.get('name') or ''), 'rack_uid': str(it.get('rack_uid') or ''),
                    'u': it.get('u_start'), 'foreign': False}

        # ── Lo que la BASE puede filtrar, filtrado en la base ────────────────────────
        #
        # Esto recorría las dos tablas enteras y construía un diccionario por cable de toda la
        # instalación para quedarse con doscientos. En una sala pequeña no se nota, que es
        # exactamente lo que hace que se escriba así y se descubra tarde.
        #
        # Buscar por el NOMBRE de un extremo también va a la base: el nombre está en otra tabla,
        # así que se resuelve antes a una lista de identificadores y se pregunta por ellos —el
        # mismo camino que la búsqueda de equipos por modelo—. Dejarlo para después obligaría a
        # traerse los cables de toda la instalación para mirarles el nombre a las puntas, que es
        # justo de lo que se venía huyendo.
        tocan = _items_matching(q)
        regletas = _pdus_matching(q)

        def _o_extremos(sql_q, p_q, cols):
            """El `OR` de los extremos, si hay a quién nombrar. Uno para las dos tablas: sólo
            cambia cómo se llaman sus columnas de extremo."""
            trozos, params = [sql_q] if sql_q else [], list(p_q)
            for col, uids in cols:
                if not uids:
                    continue
                trozos.append(f'{col} IN (' + ', '.join('?' for _ in uids) + ')')
                params.extend(uids)
            if not trozos:
                return '', ()
            return '(' + ' OR '.join(trozos) + ')', tuple(params)

        def _donde(sobre_cable: bool):
            """`(where, params)` para una de las dos tablas, o `(None, ())` si no aplica."""
            cond, params = [], []
            if kind:
                if sobre_cable:
                    cond.append('kind = ?')
                    params.append(kind)
                elif kind != 'power':
                    return None, ()          # un cable de corriente sólo es de esa clase
            if cat:
                cond.append('category = ?')
                params.append(cat)
            if q:
                cols = ('label', 'asset', 'a_port', 'b_port') if sobre_cable \
                    else ('label', 'asset')
                sql_q, p_q = dcim_store.like_clause(cols, q)
                extremos = ([('a_item', tocan), ('b_item', tocan)] if sobre_cable
                            else [('item_uid', tocan), ('pdu_uid', regletas)])
                sql_q, p_q = _o_extremos(sql_q, p_q, extremos)
                if not sql_q:
                    return None, ()          # se buscó algo y no lo tiene nadie
                cond.append(sql_q)
                params.extend(p_q)
            return ' AND '.join(cond), tuple(params)

        # Lo único que la base NO puede: quién puede ver qué sale de una cadena de pertenencia
        # que no está en ninguna columna, y escribirla en SQL sería tener la regla en dos sitios.
        fuera, recortado = [], False
        w_c, p_c = _donde(True)
        if w_c is not None:
            pag = scan_pages(
                lambda lim, off: store.cables.list(w_c, p_c, limit=lim, offset=off),
                lambda c: (_puedo(str(c.get('a_item') or ''))
                           or _puedo(str(c.get('b_item') or ''))),
                _WIRE_MAX, 0)
            recortado = pag['capped']
            for c in pag['rows']:
                fuera.append(dict(c, wire='data',
                                  a_at=_punta(str(c.get('a_item') or '')),
                                  b_at=_punta(str(c.get('b_item') or ''))))

        # Y los de CORRIENTE. Acaban en una regleta y no en otro equipo, así que viven en otra
        # tabla; pero la pregunta es la misma, y dos listas obligarían a buscar dos veces.
        #
        # La regleta hace de segunda punta: tiene nombre y está en un armario, que es lo que se
        # necesita de una punta. Su «boca» es el número de toma.
        w_f, p_f = _donde(False)
        if w_f is not None and len(fuera) < _WIRE_MAX:
            pdus = {p['uid']: p for p in store.pdus.list()}
            pag = scan_pages(
                lambda lim, off: store.feeds.list(w_f, p_f, limit=lim, offset=off),
                lambda f: _puedo(str(f.get('item_uid') or '')),
                _WIRE_MAX - len(fuera), 0)
            recortado = recortado or pag['capped']
            for f in pag['rows']:
                pdu = pdus.get(str(f.get('pdu_uid') or '')) or {}
                rack = racks.get(str(pdu.get('rack_uid') or '')) or {}
                fuera.append(dict(f, wire='power', kind='power',
                                  a_port=str(f.get('a_port') or ''),
                                  b_port=(str(f.get('outlet') or '')
                                          if int(f.get('outlet') or 0) else ''),
                                  # El color del CABLE es suyo, y el de la rama es de la
                                  # regleta: pisar el primero con el segundo dejaba la ficha
                                  # enseñando el color de la rama como si fuera el del
                                  # latiguillo — y guardándolo encima al corregir cualquier
                                  # otra cosa. La lista pinta el del cable y, si no lo tiene,
                                  # el de su rama.
                                  branch_color=str(pdu.get('color') or ''),
                                  a_at=_punta(str(f.get('item_uid') or '')),
                                  b_at={'label': str(pdu.get('name') or ''), 'role': 'pdu',
                                        'rack': str(rack.get('name') or ''),
                                        'rack_uid': str(pdu.get('rack_uid') or ''),
                                        'foreign': False}))

        # Las categorías de las dos, en el mismo diccionario: la pantalla ofrece las que valen
        # para lo que se está filtrando, y para eso tienen que llegar juntas.
        cats = dict(CABLE_CATEGORIES, power=list(FEED_CATEGORIES))
        return jsonify({'cables': fuera[:_WIRE_MAX], 'capped': recortado,
                        'colors': [list(x) for x in CABLE_COLORS],
                        'colors_used': store.colors_used(_COLORS_USED_MAX),
                        # `power` ya está en la lista: un cable de corriente entre dos
                        # equipos se puede declarar como cable de datos de clase `power`,
                        # y añadirlo otra vez daría dos opciones iguales en el filtro.
                        'kinds': list(CABLE_KINDS), 'categories': cats})

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
        #
        # Y **se sigue por los paneles**, aunque estén en otro armario, que es donde suelen
        # estar: en una sala de verdad los paneles viven en el rack de patcheo y no en el del
        # servidor. Un enlace que atraviesa un panel son tres cables declarados y un camino, y
        # sin los tramos de más allá el camino se corta justo donde empieza a hacer falta.
        #
        # Sólo por lo PASIVO y sólo por lo que este lector ve: atravesar un switch sería
        # inventarse un cable, y atravesar algo ajeno sería confirmar un camino a través de algo
        # que no se puede ni mirar. Un equipo ajeno llega sin rol —`opaque` no lo trae— así que
        # el recorrido se para en él por sí solo.
        vistos = {it['uid'] for it in mios}
        vecinos, frontera, vueltas = [], True, 0
        while frontera and vueltas < _PATH_HOPS:
            vueltas += 1
            frontera = []
            otros = {c[lado] for c in cables for lado in ('a_item', 'b_item')} - vistos
            for u in otros:
                vistos.add(u)
                it = store.items.get(u)
                if not it:
                    continue
                if dcim_owners.may_see(C.owner_of(store, said, 'item', u), allowed):
                    vecinos.append(it)
                    # Un panel no termina un camino: lo continúa. Se le piden sus cables para
                    # poder llegar al otro lado.
                    if str(it.get('role') or '') in ROLES_MUDOS:
                        frontera.append(it['uid'])
                else:
                    # Existe y ocupa, y nada más — la misma respuesta que da el armario
                    # compartido. Y no se atraviesa.
                    vecinos.append(dcim_owners.opaque(it))
            if frontera:
                ya = {str(c.get('uid') or '') for c in cables}
                cables += [c for c in store.cables_of(frontera)
                           if str(c.get('uid') or '') not in ya]
        # El MISMO mapa que dibuja infraestructura, pedido por lo que el panel declara. Sin
        # él se sigue: lo declarado se lee igual, y una pantalla que no abre porque una sonda no
        # ha contestado es peor que una que dice menos.
        #
        # **Sin la evidencia**: de todo el mapa aquí sólo se leen los enlaces `lldp` —lo que dos
        # dispositivos dicen verse el uno al otro— y armarlo entero incluye leer enteras las
        # cuatro tablas de lo que cada equipo ha visto pasar, la de MAC entre ellas. Se leían y
        # se tiraban, y eso era la espera de esta pestaña: una pregunta sobre UN armario pagando
        # el inventario de direcciones de la flota.
        # **Y sólo si se pide.** Lo declarado se lee de la base y está en milisegundos; el
        # contraste hay que armarlo recorriendo la flota entera, y esperarlo para poder pintar la
        # primera fila deja la pestaña en blanco un rato largo por un dato que ocupa la última
        # columna. Se piden en dos veces, y mientras tanto la pantalla dice que está comprobando
        # en vez de decir que no se ve nada.
        # Las categorías viajan con la respuesta, como los colores de las ramas: la pantalla no
        # tiene por qué llevar una segunda copia de qué es una Cat 6A.
        # Y el nombre del armario de cada punta, que es la mitad de una dirección: «PP-A 25»
        # no dice dónde hay que ir, y un camino sale del armario abierto casi siempre.
        #
        # Sólo de lo que este lector ve. Un equipo ajeno llega opaco a propósito —existe y
        # ocupa, nada más— y decir en qué armario está sería decir qué hay en la sala de otro
        # por la puerta de al lado, que es la forma en que se escapan estas cosas.
        nombres_rack = {}
        for it in mios + vecinos:
            if it.get('foreign'):
                continue
            ru = str(it.get('rack_uid') or '')
            if ru and ru not in nombres_rack:
                nombres_rack[ru] = str((store.racks.get(ru) or {}).get('name') or '')
            it['rack_name'] = nombres_rack.get(ru, '')
        # Y de qué puede ser un cable, por lo mismo: la pantalla lleva una lista corta de
        # respaldo para no dibujar un desplegable vacío, pero la que manda es ésta.
        cats = {'categories': CABLE_CATEGORIES, 'kinds': list(CABLE_KINDS),
                # Los colores con los que se compra un latiguillo, dichos por el servidor: la
                # pantalla no lleva una segunda copia, igual que con las categorías.
                'colors': [list(x) for x in CABLE_COLORS],
                # Y los que **ya están puestos** en esta instalación, del más usado al menos. Es
                # la lista que de verdad se elige: el azul que hay en cuarenta cables es el que
                # va a llevar el cuarenta y uno, y buscarlo en la rueda a ojo deja nueve azules
                # que no son el mismo azul.
                'colors_used': store.colors_used(_COLORS_USED_MAX)}
        if not request.args.get('check'):
            return jsonify(dict(dcim_svc.cable_check(cables, mios + vecinos), **cats))
        edges = []
        armar = getattr(wa, '_infra_topology', None)
        if callable(armar):
            try:
                edges = (armar(session.get('lang') or wa._DEFAULT_LANG,
                               evidence=False).get('edges') or [])
            except Exception:                       # pylint: disable=broad-except
                edges = []
        return jsonify(dict(dcim_svc.cable_check(cables, mios + vecinos, edges), **cats))

    @app.route('/api/v1/dcim/cables/<uid>/run', methods=['GET'])
    @C.view_req
    def api_dcim_cable_run(uid):
        """De qué **tirada** forma parte este cable: sus tramos en orden, de punta a punta.

        Un enlace que atraviesa un panel son tres cables y una tirada, y la ficha de uno de los
        tres enseñaba ese cable solo —«del panel A boca 12 al panel B boca 12»—, que no dice de
        dónde viene ni a dónde va. La pregunta que se hace delante del armario con el latiguillo
        en la mano es la otra.

        **Por cable y no con la lista**, que es lo que la hace barata: la pestaña de un armario
        trae los caminos de todos porque ya ha reunido la instalación entera para contrastar; una
        búsqueda de cables no reúne nada, y calcularle la tirada a doscientas filas para enseñar
        una sería pagar doscientas veces lo que se mira una.

        Y **de lo declarado**, sin contraste: una tirada es un hecho escrito, y el camino que
        dibuja la otra pestaña sale de cruzarlo con lo que los dispositivos ven — así que una
        tirada que nadie confirma, que es media instalación, no salía en ninguna parte estando
        declarada entera.
        """
        store = C.store()
        cable = store.cables.get(str(uid or '')) if store else None
        if not cable:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        said, allowed = store.owners_map(), C.seen()

        def _visible(item_uid):
            return dcim_owners.may_see(C.owner_of(store, said, 'item', str(item_uid or '')),
                                       allowed)

        # Se pide permiso sobre los DOS extremos: un cable se ve si se ven las dos cosas que une,
        # y con uno solo bastaría declarar un cable hacia lo ajeno para que la tirada lo nombrara.
        if not (_visible(cable.get('a_item')) and _visible(cable.get('b_item'))):
            return jsonify({'error': wa._t('access_denied')}), 403
        # Se reúne SÓLO el vecindario: los dos extremos, y de ahí hacia fuera atravesando lo
        # pasivo. Un panel no termina una tirada, la continúa — pero se para en lo que no se
        # puede mirar, igual que el recorrido de la pestaña del armario.
        cables, items, vistos = list(store.cables_of([str(cable.get('a_item') or ''),
                                                      str(cable.get('b_item') or '')])), [], set()
        frontera = [str(cable.get('a_item') or ''), str(cable.get('b_item') or '')]
        vueltas = 0
        while frontera and vueltas <= _PATH_HOPS:
            vueltas += 1
            siguiente = []
            for u in frontera:
                if not u or u in vistos:
                    continue
                vistos.add(u)
                it = store.items.get(u)
                if not it:
                    continue
                if not _visible(u):
                    items.append(dcim_owners.opaque(it))   # existe y ocupa, y nada más
                    continue
                items.append(it)
                if str(it.get('role') or '') in ROLES_MUDOS:
                    # Los cables de este panel, y **las dos puntas de todos ellos**: lo que hace
                    # falta seguir no son los cables nuevos sino los equipos nuevos. Empujando
                    # sólo las puntas de los que se acababan de añadir, preguntar por el tramo
                    # de en medio no llegaba nunca al servidor ni al switch —sus cables ya
                    # estaban en la lista desde el principio— y la tirada salía con las dos
                    # puntas sin nombre.
                    suyos = store.cables_of([u])
                    ya = {str(x.get('uid') or '') for x in cables}
                    cables += [c for c in suyos if str(c.get('uid') or '') not in ya]
                    siguiente += [str(c.get(lado) or '')
                                  for c in suyos for lado in ('a_item', 'b_item')]
            frontera = [u for u in siguiente if u not in vistos]
        # El nombre del armario de cada punta, que es la mitad de una dirección: «PP-A 25» no
        # dice dónde hay que ir. De lo ajeno no: decir en qué armario está sería contar qué hay
        # en la sala de otro por la puerta de al lado.
        nombres = {}
        for it in items:
            if it.get('foreign'):
                continue
            ru = str(it.get('rack_uid') or '')
            if ru and ru not in nombres:
                nombres[ru] = str((store.racks.get(ru) or {}).get('name') or '')
            it['rack_name'] = nombres.get(ru, '')
        # Y cómo se llama la máquina de cada punta, cuando la punta no está rotulada — que es lo
        # normal: nadie rotula un servidor que ya tiene nombre. Sin esto las dos puntas de la
        # tirada salían con su boca y nada más. Con la regla del REGISTRO, que es de quien es el
        # dato: quien no puede ver una máquina tampoco ve su nombre por esta puerta.
        hosts = getattr(wa, '_hosts_store', None)
        if hosts is not None:
            perms = C.perms()
            de_maquina = {}
            for h in hosts.list(decrypt=False) or ():
                hu = str(h.get('uid') or '')
                if 'devices_view' in perms or f'server.{hu}.view' in perms:
                    de_maquina[hu] = str(h.get('name') or '')
            for it in items:
                if not it.get('foreign') and it.get('host_uid'):
                    it['host_name'] = de_maquina.get(str(it.get('host_uid')), '')
        tirada = dcim_svc.run_of(uid, cables, items)
        if tirada:
            tirada['legs'] = dcim_svc.with_cable(
                dcim_svc.label_legs(tirada.get('legs'), items), cables)
        return jsonify({'path': tirada})

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
