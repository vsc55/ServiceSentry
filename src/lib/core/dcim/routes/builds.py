#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las plantillas: con qué se compra un equipo y de qué consta.

El estándar, no la máquina. Lo que aquí se escribe se **estampa** en cada equipo que
salga de él, así que estas rutas escriben el futuro y no el presente.

Rutas:

    PUT     /api/v1/dcim/build-parts/<uid>
    DELETE  /api/v1/dcim/build-parts/<uid>
    GET     /api/v1/dcim/builds
    POST    /api/v1/dcim/builds
    GET     /api/v1/dcim/builds/<uid>
    PUT     /api/v1/dcim/builds/<uid>
    DELETE  /api/v1/dcim/builds/<uid>
    GET     /api/v1/dcim/builds/<uid>/files
    POST    /api/v1/dcim/builds/<uid>/files
    GET     /api/v1/dcim/builds/<uid>/history
    POST    /api/v1/dcim/builds/<uid>/image/<face>
    DELETE  /api/v1/dcim/builds/<uid>/image/<face>
    POST    /api/v1/dcim/builds/<uid>/parts
    POST    /api/v1/dcim/builds/<uid>/restore
"""

from __future__ import annotations

from flask import jsonify, request

from lib.core.dcim import builds as dcim_builds
from lib.core.dcim import catalog as dcim_catalog
from lib.core.dcim import connectors as dcim_connectors
from lib.core.dcim import files as dcim_files
from lib.core.dcim import media as dcim_media
from lib.core.dcim import profiles as dcim_profiles
from lib.core.dcim import revisions as dcim_revs
from lib.core.dcim.store import FACES, ITEM_ROLES, PART_KINDS
from lib.core.dcim.routes._common import _without


def register(app, wa, C):
    """Las rutas de esta área. *C* es lo que comparten todas: los permisos y los ayudantes."""
    _BASE_FIELDS = ('uid', 'manufacturer', 'model', 'u_tenths', 'full_depth', 'kind',
                    'front_image', 'description', 'airflow', 'power_type', 'ports',
                    'port_list', 'is_powered', 'extra')

    def _type_rows(uids) -> dict:
        """Los modelos del catálogo que estas plantillas usan de base, resumidos.

        Un identificador en pantalla no es un nombre: es una cadena que no dice nada y que encima
        parece un error. Y lo que va con él es lo que evita preguntar dos veces lo mismo — la
        altura de un R740 está escrita en el catálogo, así que el formulario la enseña en vez de
        pedirla.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        fuera = {}
        for uid in {str(u or '') for u in (uids or ()) if str(u or '')}:
            fila = cat.get(uid) if cat else None
            if fila:
                fuera[uid] = {k: fila.get(k) for k in _BASE_FIELDS}
                fuera[uid]['name'] = ' '.join(
                    x for x in (str(fila.get('manufacturer') or ''),
                                str(fila.get('model') or '')) if x)
        return fuera

    #: Lo que una plantilla se trae de su modelo del catálogo. Una tabla y no un puñado de
    #: asignaciones sueltas: es la lista que hay que tocar al añadir un campo, y en un sitio es
    #: la diferencia entre añadirlo y acordarse de añadirlo en tres.
    _STAMP_FROM_TYPE = ('manufacturer', 'model', 'full_depth', 'airflow', 'power_type',
                        'ports', 'port_list', 'extra', 'u_tenths')

    def _stamp_base(data: dict) -> dict:
        """Copiar en *data* lo que dice el modelo del catálogo que ha elegido.

        **Se estampa, no se enlaza** — la misma regla que entre una plantilla y un equipo, un
        escalón más arriba. Se leía en vivo, y eso deja la plantilla enseñando huecos el día que
        alguien retira ese modelo o reimporta la biblioteca, que regenera los `uid`. Ninguna de
        las dos es una equivocación: la biblioteca se reimporta cada pocos meses y un modelo se
        retira porque ya no se compra.

        Ocurre **al elegirlo**, y solo entonces. Elegir un modelo es decir «tráete lo suyo»; a
        partir de ahí lo que hay en la plantilla es suyo y se corrige aquí. Por eso pisa lo que
        hubiera: elegir otro chasis y quedarse con los puertos del anterior sería peor que
        cualquiera de las dos cosas.

        Y lo que la petición traiga **en la misma llamada** manda sobre lo copiado: quien crea
        una plantilla diciendo el modelo y además el rol quiere ese rol.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        modelo = cat.get(str(data.get('type_uid') or '')) if cat else None
        if not modelo:
            return data
        fuera = dict(data)
        for campo in _STAMP_FROM_TYPE:
            if campo not in data and modelo.get(campo) is not None:
                fuera[campo] = modelo[campo]
        # El rol se deduce de la clase del modelo, que es otro vocabulario: `transceiver` está
        # en el del catálogo y no es algo que se coloque en un U.
        if 'role' not in data and str(modelo.get('kind') or '') in ITEM_ROLES:
            fuera['role'] = str(modelo['kind'])
        # Y las imágenes, copiadas de verdad y con nombre nuevo. Apuntar al fichero del catálogo
        # sería una bomba de relojería: borrar cualquiera de los dos se lleva el fichero y el
        # otro se queda enseñando un hueco sin que nada haya fallado.
        if cat is not None:
            fuera.update(cat.copy_images(modelo, wa._var_dir or '', C.media_dir()))
        return fuera

    #: Si ya se ha rellenado en este proceso lo que las plantillas viejas no copiaron. Una
    #: lista para poder tocarla desde dentro de la función.
    _estampado = []

    def _stamp_backfill() -> None:
        """Rellenar **una vez** lo que las plantillas anteriores al copiado no traen.

        Aquí y no al montar los stores porque necesita dos cosas que allí todavía no hay: el
        catálogo y la carpeta donde viven las imágenes. Cuesta una lectura de unas decenas de
        filas la primera vez que alguien abre la pantalla, y nada las siguientes.
        """
        if _estampado:
            return
        _estampado.append(True)
        plantillas = C.builds()
        if plantillas is None:
            return
        try:
            plantillas.stamp_missing(getattr(wa, '_dcim_catalog', None),
                                     wa._var_dir or '', C.media_dir())
        except Exception:                       # pylint: disable=broad-except
            pass                                # un arreglo que rompe la pantalla no arregla



    @app.route('/api/v1/dcim/builds', methods=['GET'])
    @C.view_req
    def api_dcim_builds():
        """Los estándares de compra, con cuántas piezas lleva cada uno y cuántos equipos han
        salido de él.

        Los dos recuentos van en la lista y no en la ficha: sin ellos una plantilla es una nota
        en un documento —que es de donde se viene— y con ellos se sabe a qué afecta tocarla
        antes de abrirla.
        """
        _stamp_backfill()
        plantillas = C.builds()
        store = C.store()
        if plantillas is None:
            return jsonify({'builds': [], 'roles': list(ITEM_ROLES),
                            'part_kinds': list(PART_KINDS), 'faces': list(FACES)})
        cuentas = plantillas.counts()
        # Cuántos equipos por plantilla, de una sola lectura: preguntarlo plantilla a plantilla
        # serían treinta consultas para pintar treinta renglones.
        nacidos = {}
        for item in (store.items.list() if store else ()):
            uid = str(item.get('build_uid') or '')
            if uid:
                nacidos[uid] = nacidos.get(uid, 0) + 1
        todas = plantillas.list()
        bases = _type_rows([b.get('type_uid') for b in todas])
        filas = []
        for b in todas:
            base = bases.get(str(b.get('type_uid') or '')) or {}
            filas.append(dict(b, parts=cuentas.get(str(b['uid']), 0),
                              items=nacidos.get(str(b['uid']), 0),
                              type_name=base.get('name', ''), base=base or None))
        return jsonify({'builds': filas, 'roles': list(ITEM_ROLES),
                        'part_kinds': list(PART_KINDS), 'faces': list(FACES)})

    @app.route('/api/v1/dcim/builds/<uid>', methods=['GET'])
    @C.view_req
    def api_dcim_build(uid):
        _stamp_backfill()
        plantillas = C.builds()
        fila = plantillas.get(uid) if plantillas else None
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        store = C.store()
        base = _type_rows([fila.get('type_uid')]).get(str(fila.get('type_uid') or '')) or {}
        fila = dict(fila, type_name=base.get('name', ''), base=base or None)
        piezas = plantillas.parts_of(uid)
        # Las fichas de catálogo de las piezas: de ahí salen los núcleos de una CPU y los puertos
        # de una tarjeta, que están en el modelo y no en la pieza.
        cat = getattr(wa, '_dcim_catalog', None)
        modelos = {}
        for p in piezas:
            t = str(p.get('type_uid') or '')
            if t and t not in modelos:
                m = cat.get(t) if cat else None
                if m:
                    modelos[t] = m
        return jsonify({'build': fila, 'parts': piezas,
                        # Lo que se pregunta de cualquier chasis —la ventilación, el peso— dicho
                        # por el mismo documento que lo dice en el catálogo. Estaba servido allí
                        # y no aquí, así que una plantilla enseñaba una ventilación que no había
                        # forma de corregir: el dato es suyo desde que se copia.
                        'fields': dcim_profiles.group_fields(C.profiles(), ''),
                        'power_types': list(dcim_catalog.POWER_TYPES),
                        # Los conectores, que aquí se editan igual que en el catálogo. Servidos
                        # también aquí porque esta pantalla se abre sin pasar por aquella, y un
                        # vocabulario que solo llega por un camino es una casilla que sugiere o
                        # no según por dónde se haya entrado.
                        'connectors': dcim_connectors.by_family(wa._lang(), C.conns()),
                        # Con el nombre de cada señal, por lo mismo: un identificador
                        # suelto no se lee.
                        'signals': dcim_connectors.signals(wa._lang(), C.conns()),
                        # Cuántos papeles cuelgan. Aquí y no pidiéndolos al abrir la ficha: el
                        # número de una pestaña está para decir si merece la pena entrar, y uno
                        # que solo aparece después de entrar no contesta esa pregunta.
                        'files': len(C.files().of(uid, 'build') if C.files() else ()),
                        # Las fechas de la vida del CHASIS, que es lo que se busca al abrir una
                        # plantilla y no estaba: cuándo salió, cuándo dejó de venderse, cuándo
                        # se le acaban los parches. La lista, del mismo documento que las demás.
                        'lifecycle': dcim_profiles.group_fields(C.profiles(), 'lifecycle'),
                        # Qué máquina sale de esto: las cuentas que si no se hacen a mano
                        # leyendo quince renglones.
                        # Con el chasis: sus puertos de red están contados en el catálogo
                        # desde el primer día y nadie los miraba, así que un mini-PC con dos de
                        # serie decía tener solo la tarjeta que alguien le añadió.
                        'summary': dcim_builds.summary(piezas, modelos, base),
                        'items': len(store.items_of_build(uid) if store else ()),
                        'part_kinds': list(PART_KINDS)})

    @app.route('/api/v1/dcim/builds', methods=['POST'])
    @C.build_req
    def api_dcim_build_new():
        """Una plantilla nueva, o la copia de otra.

        Clonar porque casi ninguna se escribe desde cero: la del año que viene es la de este año
        con otros discos, y teclear quince líneas para cambiar una es el trabajo que no se hace
        — y entonces se edita la vieja, que es como se pierde de qué constaban los veinte de
        antes.
        """
        plantillas = C.builds()
        if plantillas is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        desde = str(data.get('from') or '').strip()
        # Con modelo base, se trae lo suyo. Clonar no: la copia se lleva lo que tuviera la
        # original, que puede haberse corregido a mano desde que se estampó.
        if not desde and data.get('type_uid'):
            data = _stamp_base(data)
        uid = (plantillas.clone(desde, data.get('name') or '', actor=C.actor()) if desde
               else plantillas.create(data, actor=C.actor()))
        if not uid:
            return jsonify({'error': wa._t('dcim_build_name_taken')}), 400
        wa._audit('dcim_build_save',
                  detail={'action': 'clone' if desde else 'create',
                          'name': str(data.get('name') or ''), 'build': uid})
        return jsonify({'uid': uid})

    @app.route('/api/v1/dcim/builds/<uid>', methods=['PUT'])
    @C.build_req
    def api_dcim_build_edit(uid):
        plantillas = C.builds()
        antes = plantillas.get(uid) if plantillas else None
        if not antes:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        # Cambiar de modelo base es volver a traerse lo suyo. Solo al CAMBIARLO: guardar la
        # ficha con el mismo de siempre no puede deshacer lo que alguien corrigió aquí, que es
        # la mitad de para lo que sirve haberlo copiado.
        if data.get('type_uid') and str(data['type_uid']) != str(antes.get('type_uid') or ''):
            data = _stamp_base(data)
        if not plantillas.update(uid, data, actor=C.actor()):
            return jsonify({'error': wa._t('dcim_build_name_taken')}), 400
        wa._audit('dcim_build_save',
                  detail={'action': 'edit', 'build': uid,
                          'name': str(data.get('name') or antes.get('name') or '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/builds/<uid>', methods=['DELETE'])
    @C.build_req
    def api_dcim_build_drop(uid):
        """Retirarla. Los equipos que salieron de ella **no se tocan**.

        Ni siquiera se les quita el vínculo: nacieron de esto, y eso siguió siendo verdad
        después de que alguien retirara el estándar. Lo que se pierde es poder mirar de qué
        constaba, y por eso la pantalla dice cuántos hay antes de preguntar.
        """
        plantillas = C.builds()
        fila = plantillas.get(uid) if plantillas else None
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        store = C.store()
        nacidos = len(store.items_of_build(uid) if store else ())
        # Y sus papeles: dejarlos sería dejar ficheros en el disco a los que no apunta nadie.
        for f in ((C.files().forget(uid, 'build')) if C.files() else ()):
            dcim_media.forget(wa._var_dir or '', str(f.get('stored') or ''), C.media_dir())
        plantillas.delete(uid)
        wa._audit('dcim_build_drop',
                  detail={'build': uid, 'name': str(fila.get('name') or ''), 'items': nacidos})
        return jsonify({'ok': True, 'items': nacidos})

    @app.route('/api/v1/dcim/builds/<uid>/image/<face>', methods=['POST'])
    @C.build_req
    def api_dcim_build_image(uid, face):
        """Cambiar la foto de una cara de una plantilla.

        Las dos llegan copiadas del catálogo, y copiadas quiere decir **suyas**: la del catálogo
        es la del chasis desnudo y la de aquí puede ser la del equipo montado, con sus tarjetas
        y su etiqueta. Sin esto la única forma de corregir una foto era corregir el modelo del
        que salió, que es de donde cuelgan también las otras veinte plantillas.

        El tipo lo decide lo que hay DENTRO del fichero: una extensión es una afirmación de
        quien sube, y un nombre llegado por la red no toca este disco.
        """
        plantillas = C.builds()
        fila = plantillas.get(uid) if plantillas else None
        if not fila or face not in ('front', 'rear'):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        up = (request.files or {}).get('file')
        blob = up.read(dcim_media.MAX_BYTES + 1) if up is not None             else request.data[:dcim_media.MAX_BYTES + 1]
        nombre, err = dcim_media.save(wa._var_dir or '', blob, C.media_dir())
        if err:
            return jsonify({'error': wa._t(err)}), 400
        vieja = str(fila.get(f'{face}_image') or '')
        plantillas.update(uid, {f'{face}_image': nombre}, actor=C.actor())
        # La que sustituye se va, o cada cambio deja un fichero al que no apunta nadie y la
        # carpeta crece durante toda la vida de la instalación.
        if vieja and vieja != nombre:
            dcim_media.forget(wa._var_dir or '', vieja, C.media_dir())
        wa._audit('dcim_build_save', detail={'action': 'image', 'face': face, 'build': uid,
                                             'name': str(fila.get('name') or '')})
        return jsonify({'image': nombre})

    @app.route('/api/v1/dcim/builds/<uid>/image/<face>', methods=['DELETE'])
    @C.build_req
    def api_dcim_build_image_drop(uid, face):
        plantillas = C.builds()
        fila = plantillas.get(uid) if plantillas else None
        if not fila or face not in ('front', 'rear'):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        vieja = str(fila.get(f'{face}_image') or '')
        plantillas.update(uid, {f'{face}_image': ''}, actor=C.actor())
        if vieja:
            dcim_media.forget(wa._var_dir or '', vieja, C.media_dir())
        wa._audit('dcim_build_save', detail={'action': 'image_drop', 'face': face,
                                             'build': uid,
                                             'name': str(fila.get('name') or '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/builds/<uid>/history', methods=['GET'])
    @C.view_req
    def api_dcim_build_history(uid):
        """Qué decía esta plantilla antes de cada cambio, y quién lo hizo.

        Una plantilla es un dato **compartido**: de ella salieron veinte máquinas y es el
        estándar con el que se compra, así que corregirla no es editar una fila. Y la corrección
        que rompe algo casi nunca se descubre el día que se hace — se descubre cuando alguien
        dice «esto antes llevaba ocho discos» y no hay forma de saber si tiene razón.

        Se lee con el permiso de consultar, como el del catálogo: mirar lo que decía ayer es
        leer, y quien no puede editarla sigue necesitando saber si cambió bajo sus pies.
        """
        plantillas = C.builds()
        if plantillas is None or not plantillas.get(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        return jsonify({'history': plantillas.revs.history(uid, scope=plantillas.SCOPE),
                        'keep': dcim_revs.KEEP})

    @app.route('/api/v1/dcim/builds/<uid>/restore', methods=['POST'])
    @C.build_req
    def api_dcim_build_restore(uid):
        """Volver a una versión. Escribe los valores de aquella y **deja constancia**.

        No borra lo de en medio: volver atrás es un cambio más, no un deshacer que hace
        desaparecer la historia. Si fuera lo segundo, la respuesta a «quién dejó esto así» sería
        distinta según cuándo se preguntara.

        Las **piezas no** se restauran, y la imagen tampoco. La versión guarda la lista de
        componentes para poder leerla —«¿de qué constaba?» es la pregunta que se le hace a esto—
        pero volver a escribirlas sería borrar y recrear doce filas con `uid` nuevos, y de esas
        filas cuelgan las que ya se estamparon en veinte máquinas. Y de la foto lo que se guardó
        es el NOMBRE de un fichero que puede haberse borrado al sustituirlo: escribirlo sería
        cambiar una foto por un hueco.
        """
        plantillas = C.builds()
        actual = plantillas.get(uid) if plantillas else None
        if not actual:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        version = plantillas.revs.get(str(data.get('rev') or ''), scope=plantillas.SCOPE)
        if not version or str(version.get('ref_uid')) != str(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        antes_de = dict(version.get('data') or {})
        for fuera in ('uid', 'parts', 'front_image', 'rear_image',
                      'created_at', 'updated_at', 'updated_by'):
            antes_de.pop(fuera, None)
        if not plantillas.update(uid, antes_de, actor=C.actor(), accion='restore'):
            return jsonify({'error': wa._t('dcim_build_name_taken')}), 400
        cambios = dcim_revs.diff(actual, plantillas.get(uid) or {})
        wa._audit('dcim_build_save',
                  detail={'action': 'restore', 'build': uid,
                          'name': str(actual.get('name') or ''), 'rev': version.get('at'),
                          'changed': sorted(cambios)})
        return jsonify({'ok': True, 'changed': sorted(cambios)})

    @app.route('/api/v1/dcim/builds/<uid>/files', methods=['GET'])
    @C.view_req
    def api_dcim_build_files(uid):
        """Lo que hay colgado de una plantilla: la oferta, el pliego, la foto de cómo queda
        montada. Se lee con `dcim_view`, como la plantilla misma."""
        plantillas = C.builds()
        if plantillas is None or not plantillas.get(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        store = C.files()
        return jsonify({'files': store.of(uid, 'build') if store else [],
                        'kinds': list(dcim_files.KINDS),
                        'max_bytes': dcim_files.MAX_BYTES})

    @app.route('/api/v1/dcim/builds/<uid>/files', methods=['POST'])
    @C.build_req
    def api_dcim_build_file_add(uid):
        """Colgar uno. Mismo camino que los de un modelo —y la misma razón para no tener lista
        blanca de tipos: siempre salen como descarga."""
        plantillas = C.builds()
        fila = plantillas.get(uid) if plantillas else None
        store = C.files()
        if not fila or store is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        up = (request.files or {}).get('file')
        blob = up.read(dcim_files.MAX_BYTES + 1) if up is not None \
            else request.data[:dcim_files.MAX_BYTES + 1]
        nombre, err = dcim_media.keep(wa._var_dir or '', blob, dcim_files.MAX_BYTES,
                                      C.media_dir())
        if err:
            return jsonify({'error': wa._t(err)}), 400
        etiqueta = dcim_files.clean_label(
            (up.filename if up is not None else '') or request.args.get('name') or '')
        nuevo = store.add(uid, nombre, etiqueta, len(blob),
                          kind=str(request.form.get('kind') or ''),
                          actor=C.actor(), scope='build')
        wa._audit('dcim_build_save',
                  detail={'action': 'file', 'build': uid, 'name': str(fila.get('name') or ''),
                          'file': etiqueta})
        return jsonify({'uid': nuevo, 'files': store.of(uid, 'build')})

    @app.route('/api/v1/dcim/builds/<uid>/parts', methods=['POST'])
    @C.build_req
    def api_dcim_build_part_new(uid):
        plantillas = C.builds()
        if plantillas is None or not plantillas.get(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        if str(data.get('kind') or 'other') not in PART_KINDS:
            return jsonify({'error': wa._t('dcim_part_kind_unknown')}), 400
        nuevo = plantillas.part_add(uid, C.from_type(data), actor=C.actor())
        wa._audit('dcim_build_save',
                  detail={'action': 'part', 'build': uid, 'kind': str(data.get('kind') or ''),
                          'model': str(data.get('model') or '')})
        return jsonify({'uid': nuevo})

    @app.route('/api/v1/dcim/build-parts/<uid>', methods=['PUT'])
    @C.build_req
    def api_dcim_build_part_edit(uid):
        plantillas = C.builds()
        fila = plantillas.parts.get(uid) if plantillas else None
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = _without(request.get_json(silent=True) or {}, ('build_uid',))
        if 'kind' in data and str(data['kind']) not in PART_KINDS:
            return jsonify({'error': wa._t('dcim_part_kind_unknown')}), 400
        plantillas.part_update(uid, C.from_type(data), actor=C.actor())
        wa._audit('dcim_build_save',
                  detail={'action': 'part_edit', 'build': str(fila.get('build_uid') or '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/build-parts/<uid>', methods=['DELETE'])
    @C.build_req
    def api_dcim_build_part_drop(uid):
        plantillas = C.builds()
        fila = plantillas.parts.get(uid) if plantillas else None
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        plantillas.part_delete(uid, actor=C.actor())
        wa._audit('dcim_build_save',
                  detail={'action': 'part_drop', 'build': str(fila.get('build_uid') or ''),
                          'kind': str(fila.get('kind') or '')})
        return jsonify({'ok': True})

    # ── The catalogue ─────────────────────────────────────────────────────────

    # Referenciadas para que un analizador no las dé por muertas: Flask se las
    # queda por su ruta.
    _ = (api_dcim_builds, api_dcim_build, api_dcim_build_new,)
