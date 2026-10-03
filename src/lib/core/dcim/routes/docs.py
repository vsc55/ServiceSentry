#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Los dos documentos del catálogo: qué se pregunta de un componente y por dónde se
enchufa.

Se editan como documento y no como filas —viene uno con el panel y otro puede estar
guardado— así que sus rutas son las de un documento: leerlo, sustituirlo, su historial
y volver al de dentro.

Rutas:

    GET     /api/v1/dcim/connectors
    PUT     /api/v1/dcim/connectors
    DELETE  /api/v1/dcim/connectors
    POST    /api/v1/dcim/connectors/<cid>/image
    DELETE  /api/v1/dcim/connectors/<cid>/image
    GET     /api/v1/dcim/connectors/history
    GET     /api/v1/dcim/profiles
    PUT     /api/v1/dcim/profiles
    DELETE  /api/v1/dcim/profiles
    GET     /api/v1/dcim/profiles/compare
    GET     /api/v1/dcim/profiles/history
"""

from __future__ import annotations

from flask import jsonify, request

from lib.core.dcim import connectors as dcim_connectors
from lib.core.dcim import media as dcim_media
from lib.core.dcim import profiles as dcim_profiles


def register(app, wa, C):
    """Las rutas de esta área. *C* es lo que comparten todas: los permisos y los ayudantes."""
    @app.route('/api/v1/dcim/profiles', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_profiles():
        """El documento en vigor, con las dos versiones que compiten por serlo."""
        guardado = C.profiles().get() if C.profiles() else None
        return jsonify({'doc': dcim_profiles.effective(C.profiles()),
                        'packaged': int(dcim_profiles.packaged().get('version') or 0),
                        'stored': int((guardado or {}).get('version') or 0),
                        'stored_at': str((guardado or {}).get('updated_at') or ''),
                        'stored_by': str((guardado or {}).get('updated_by') or '')})

    @app.route('/api/v1/dcim/profiles/history', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_profiles_history():
        """Las versiones guardadas del documento: quién lo cambió y cuándo.

        Solo las guardadas aquí: la que viene con el panel no tiene historial porque su historial
        son los commits. Vacío significa que nadie lo ha tocado, que es lo normal.
        """
        store = C.profiles()
        if store is None:
            return jsonify({'history': []})
        filas = store.revs.history(dcim_profiles.NAME, scope=dcim_profiles.SCOPE)
        # Sin el documento entero: son cuarenta campos por versión y la lista solo enseña
        # quién y cuándo. El que se quiera comparar se pide por su uid.
        return jsonify({'history': [
            {'uid': f['uid'], 'at': f['at'], 'by': f['by'],
             'version': int((f.get('data') or {}).get('version') or 0)} for f in filas]})

    @app.route('/api/v1/dcim/profiles/compare', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_profiles_compare():
        """Qué cambia entre dos versiones. Sin `b`, contra el documento en vigor.

        Por clase y por campo, y no como dos volcados de JSON uno al lado del otro: la pregunta
        que se hace mirando dos versiones es «¿qué se le añadió a los discos?», y a dos bloques de
        texto no se les puede preguntar eso.
        """
        store = C.profiles()
        if store is None:
            return jsonify({'diff': []})
        def _doc(uid):
            if not uid:
                # Lo **guardado**, no lo efectivo. El historial es de documentos guardados, y
                # comparar uno contra la vista mezclada —que suma los comunes del panel— saca
                # diez «añadidos» que nadie añadió: son los que siempre estuvieron, vistos
                # desde el otro lado. Sin nada guardado, contra el que viene con el panel, que
                # es lo que de verdad hay.
                guardado = store.get()
                return (guardado or {}).get('body') or dcim_profiles.packaged()
            fila = store.revs.get(str(uid), scope=dcim_profiles.SCOPE)
            return (fila or {}).get('data') or {}
        a = _doc(request.args.get('a') or '')
        b = _doc(request.args.get('b') or '')
        return jsonify({'diff': dcim_profiles.compare(a, b)})

    @app.route('/api/v1/dcim/profiles', methods=['PUT'])
    @C.catalog_manage_req
    def api_dcim_profiles_save():
        """Guardar un documento más nuevo, sin publicar una versión del panel.

        Manda la versión **más alta** entre este y el que viene dentro: una actualización que
        publique la 3 supera a un parche local que iba por la 2, y un parche que va por la 4
        sigue en pie hasta que se publique la 5.

        Lo que se descarta se **dice**. Un JSON con una clase mal escrita se guardaría igual y
        dejaría media pantalla sin atributos, y quien lo subió no se enteraría hasta que alguien
        fuera a rellenar una ficha.
        """
        store = C.profiles()
        if store is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        doc = request.get_json(silent=True) or {}
        tirado = dcim_profiles.problems(doc)
        version = store.save(doc, actor=C.actor())
        if not version:
            return jsonify({'error': wa._t('dcim_profiles_no_version'),
                            'dropped': tirado}), 400
        wa._audit('dcim_profiles_save',
                  detail={'action': 'save', 'version': version, 'dropped': tirado})
        return jsonify({'ok': True, 'version': version, 'dropped': tirado})

    @app.route('/api/v1/dcim/profiles', methods=['DELETE'])
    @C.catalog_manage_req
    def api_dcim_profiles_drop():
        """Quitar el guardado y volver al que viene con el panel."""
        store = C.profiles()
        if store is None or not store.delete():
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        wa._audit('dcim_profiles_save', detail={'action': 'drop'})
        return jsonify({'ok': True,
                        'version': int(dcim_profiles.packaged().get('version') or 0)})

    # ── Los conectores: por dónde se enchufa cada cosa ───────────────────


    @app.route('/api/v1/dcim/connectors', methods=['GET'])
    @C.view_req
    def api_dcim_connectors():
        """El catálogo en vigor, con las dos versiones que compiten por serlo.

        Se lee con el permiso de consultar, no con el de gestionar el catálogo: quien está
        cableando a las tres de la mañana necesita saber si el latiguillo es un C13 o un C19, y
        esa es justo la hora a la que nadie tiene el permiso bueno.
        """
        guardado = C.conns().get(dcim_connectors.NAME) if C.conns() else None
        return jsonify({'connectors': dcim_connectors.by_family(wa._lang(), C.conns()),
                        # Y cómo se llama cada señal. Viaja con ellos y no aparte: una
                        # señal marcada en un puerto es un identificador, y sin la lista
                        # que le pone nombre la pantalla enseña `power-out` a quien
                        # quiere leer «alimenta».
                        'signals': dcim_connectors.signals(wa._lang(), C.conns()),
                        'doc': dcim_connectors.effective(C.conns()),
                        'groups': list(dcim_connectors.GROUPS),
                        'families': list(dcim_connectors.FAMILIES),
                        'packaged': int(dcim_connectors.packaged().get('version') or 0),
                        'stored': int((guardado or {}).get('version') or 0),
                        'stored_at': str((guardado or {}).get('updated_at') or ''),
                        'stored_by': str((guardado or {}).get('updated_by') or '')})

    @app.route('/api/v1/dcim/connectors', methods=['PUT'])
    @C.catalog_manage_req
    def api_dcim_connectors_save():
        """Guardar un catálogo más nuevo, sin publicar una versión del panel.

        Manda la versión **más alta** entre este y el que viene dentro, igual que con los
        perfiles: una actualización que publique la 2 supera a un parche local que iba por la 1,
        y un parche que va por la 3 sigue en pie hasta que se publique la 4.

        Lo que se descarta se **dice**. Un conector con una familia mal escrita se guardaría
        igual, no saldría en ninguna casilla, y quien lo escribió creería que funcionó.
        """
        store = C.conns()
        if store is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        doc = request.get_json(silent=True) or {}
        tirado = dcim_connectors.problems(doc)
        version = store.save(doc, name=dcim_connectors.NAME, actor=C.actor())
        if not version:
            return jsonify({'error': wa._t('dcim_profiles_no_version'),
                            'dropped': tirado}), 400
        wa._audit('dcim_profiles_save',
                  detail={'action': 'save', 'doc': 'connectors', 'version': version,
                          'dropped': tirado})
        return jsonify({'ok': True, 'version': version, 'dropped': tirado})

    @app.route('/api/v1/dcim/connectors', methods=['DELETE'])
    @C.catalog_manage_req
    def api_dcim_connectors_drop():
        """Quitar el guardado y volver al que viene con el panel."""
        store = C.conns()
        if store is None or not store.delete(dcim_connectors.NAME):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        wa._audit('dcim_profiles_save', detail={'action': 'drop', 'doc': 'connectors'})
        return jsonify({'ok': True,
                        'version': int(dcim_connectors.packaged().get('version') or 0)})

    @app.route('/api/v1/dcim/connectors/<cid>/image', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_connector_image(cid):
        """Ponerle una foto a un conector.

        Los que vienen con el panel llevan dibujo —uno por FORMA, en `_conn_shapes.html`— y el
        que alguien añada no lleva ninguno: nadie va a escribir un SVG para la regleta que tiene
        en su rack, y sin nada al lado del nombre esa fila se lee como incompleta justo entre
        ciento y pico que sí lo tienen.

        Aquí y no en dos pasos —subir el fichero y luego guardar el documento— porque entre los
        dos hay un hueco: quien cierre el cuadro después del primero deja un fichero en la
        carpeta al que no apunta nadie, y nada vuelve a mirarlo nunca.

        El tipo lo decide lo que hay DENTRO del fichero y el nombre lo acuña el almacén de
        medios, igual que la imagen de un modelo: una extensión es una afirmación de quien sube,
        y un nombre llegado por la red no toca este disco.
        """
        store = C.conns()
        if store is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        up = (request.files or {}).get('file')
        blob = up.read(dcim_media.MAX_BYTES + 1) if up is not None \
            else request.data[:dcim_media.MAX_BYTES + 1]
        nombre, err = dcim_media.save(wa._var_dir or '', blob, C.media_dir())
        if err:
            return jsonify({'error': wa._t(err)}), 400
        doc, vieja = dcim_connectors.with_image(
            dcim_connectors.effective(store), cid, nombre)
        if doc is None:
            # El conector no está en el documento: guardar la foto de algo que no existe deja
            # un fichero huérfano y una respuesta que dice que fue bien.
            dcim_media.forget(wa._var_dir or '', nombre, C.media_dir())
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        doc['version'] = dcim_connectors.next_version(store)
        version = store.save(doc, name=dcim_connectors.NAME, actor=C.actor())
        # La que sustituye se va, o cada cambio deja un fichero al que no apunta nadie y la
        # carpeta crece durante toda la vida de la instalación.
        if vieja and vieja != nombre:
            dcim_media.forget(wa._var_dir or '', vieja, C.media_dir())
        wa._audit('dcim_profiles_save',
                  detail={'action': 'image', 'doc': 'connectors', 'connector': cid,
                          'version': version})
        return jsonify({'image': nombre, 'version': version})

    @app.route('/api/v1/dcim/connectors/<cid>/image', methods=['DELETE'])
    @C.catalog_manage_req
    def api_dcim_connector_image_drop(cid):
        """Quitársela y volver al dibujo de su forma."""
        store = C.conns()
        if store is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        doc, vieja = dcim_connectors.with_image(
            dcim_connectors.effective(store), cid, '')
        if doc is None or not vieja:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        doc['version'] = dcim_connectors.next_version(store)
        version = store.save(doc, name=dcim_connectors.NAME, actor=C.actor())
        dcim_media.forget(wa._var_dir or '', vieja, C.media_dir())
        wa._audit('dcim_profiles_save',
                  detail={'action': 'image_drop', 'doc': 'connectors', 'connector': cid,
                          'version': version})
        return jsonify({'ok': True, 'version': version})

    @app.route('/api/v1/dcim/connectors/history', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_connectors_history():
        """Las versiones guardadas: quién lo cambió y cuándo.

        Solo las guardadas aquí: la que viene con el panel no tiene historial porque su historial
        son los commits. Vacío significa que nadie lo ha tocado, que es lo normal.
        """
        store = C.conns()
        if store is None:
            return jsonify({'history': []})
        filas = store.revs.history(dcim_connectors.NAME, scope=dcim_connectors.SCOPE)
        # Sin el documento entero: son ciento y pico conectores por versión y la lista solo
        # enseña quién y cuándo.
        return jsonify({'history': [
            {'uid': f['uid'], 'at': f['at'], 'by': f['by'],
             'version': int((f.get('data') or {}).get('version') or 0),
             'count': len((f.get('data') or {}).get('connectors') or ())} for f in filas]})

    # ── Las plataformas: con qué sale un equipo ──────────────────────────

    # Referenciadas para que un analizador no las dé por muertas: Flask se las
    # queda por su ruta.
    _ = (api_dcim_profiles, api_dcim_profiles_history, api_dcim_profiles_compare,)
