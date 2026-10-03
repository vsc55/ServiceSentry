#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El catálogo de modelos: traerlo, escribirlo, corregirlo y llevárselo.

La biblioteca de fuera y lo que alguien escribe a mano, en la misma tabla y con dos
orígenes distintos — que es lo que permite reimportar sin pisar lo escrito. Con los
esquemas de importación, que son la forma en que la biblioteca dice de qué habla.

Rutas:

    GET     /api/v1/dcim/catalog
    POST    /api/v1/dcim/catalog
    PUT     /api/v1/dcim/catalog/<uid>
    DELETE  /api/v1/dcim/catalog/<uid>
    GET     /api/v1/dcim/catalog/<uid>/files
    POST    /api/v1/dcim/catalog/<uid>/files
    GET     /api/v1/dcim/catalog/<uid>/history
    POST    /api/v1/dcim/catalog/<uid>/image/<face>
    DELETE  /api/v1/dcim/catalog/<uid>/image/<face>
    POST    /api/v1/dcim/catalog/<uid>/restore
    POST    /api/v1/dcim/catalog/basics
    GET     /api/v1/dcim/catalog/browse
    POST    /api/v1/dcim/catalog/drop
    GET     /api/v1/dcim/catalog/import
    POST    /api/v1/dcim/catalog/import
    GET     /api/v1/dcim/catalog/import/<job_id>
    GET     /api/v1/dcim/catalog/suggest
    POST    /api/v1/dcim/catalog/upload
    GET     /api/v1/dcim/export
    GET     /api/v1/dcim/files/<uid>
    DELETE  /api/v1/dcim/files/<uid>
    POST    /api/v1/dcim/import
    GET     /api/v1/dcim/schemas
    POST    /api/v1/dcim/schemas
    DELETE  /api/v1/dcim/schemas/<uid>
    POST    /api/v1/dcim/schemas/fetch
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from flask import Response, jsonify, request

from lib.core.dcim import basics as dcim_basics
from lib.core.dcim import catalog as dcim_catalog
from lib.core.dcim import connectors as dcim_connectors
from lib.core.dcim import files as dcim_files
from lib.core.dcim import jobs as dcim_jobs
from lib.core.dcim import media as dcim_media
from lib.core.dcim import portable as dcim_portable
from lib.core.dcim import profiles as dcim_profiles
from lib.core.dcim import revisions as dcim_revs
from lib.core.dcim import schemas as dcim_schemas
from lib.providers import github as _gh
from lib.core.dcim.routes._common import _EXPORT_MAX


def register(app, wa, C):
    """Las rutas de esta área. *C* es lo que comparten todas: los permisos y los ayudantes."""
    @app.route('/api/v1/dcim/catalog', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_catalog():
        cat = getattr(wa, '_dcim_catalog', None)
        # La dirección de la biblioteca va en la respuesta aunque no haya catálogo: la pantalla
        # la enseña ANTES de traer nada, y quien la haya cambiado en la configuración tiene que
        # ver la suya y no la de NetBox en el hueco donde va a pulsar.
        if cat is None:
            return jsonify({'types': [], 'makers': [], 'library_url': _library_url()})
        q = str(request.args.get('q') or '').strip().lower()
        maker = str(request.args.get('maker') or '').strip()
        kind = str(request.args.get('kind') or '').strip()
        # Una página y no todo: seis mil filas en una tabla no las lee nadie, y mandarlas
        # cuesta lo mismo que si alguien fuera a leerlas.
        try:
            offset = max(0, int(request.args.get('offset') or 0))
        except (TypeError, ValueError):
            offset = 0
        donde, params = [], []
        if q:
            # También en la descripción: un armario se llama `AR3100` y lo que alguien
            # escribe en el buscador es «42U», que solo está ahí.
            donde.append('(LOWER(manufacturer) LIKE ? OR LOWER(model) LIKE ? '
                         'OR LOWER(description) LIKE ?)')
            params += [f'%{q}%', f'%{q}%', f'%{q}%']
        if maker:
            donde.append('manufacturer = ?')
            params.append(maker)
        # Y por el fabricante como FILA, que es lo que sigue siendo cierto después de
        # renombrarlo: acotar por el texto dejaría de encontrar sus modelos el día que «HP» pase
        # a ser «Hewlett Packard Enterprise».
        brand_uid = str(request.args.get('brand_uid') or '').strip()
        if brand_uid:
            donde.append('brand_uid = ?')
            params.append(brand_uid)
        if kind:
            donde.append('kind = ?')
            params.append(kind)
        # De qué FORMA: dispositivo, módulo, armario o componente. Es el filtro de primer nivel,
        # porque nadie busca «un armario o un DIMM»: se viene sabiendo cuál de las cuatro cosas
        # se quiere, y sin él los componentes comparten tabla con ocho mil dispositivos.
        arbol = str(request.args.get('tree') or '').strip()
        if arbol in dcim_catalog.TREES:
            donde.append('tree = ?')
            params.append(arbol)
        where = ' AND '.join(donde)
        # La rejilla de marcas obedece al TIPO y a nada más: el fabricante no se filtra a sí
        # mismo, y lo que se escribe en el buscador acota modelos en una vista y nombres de
        # marca en la otra — que la rejilla filtra por su cuenta, sin ir al servidor.
        donde_marcas, params_marcas = [], []
        if kind:
            donde_marcas.append('kind = ?')
            params_marcas.append(kind)
        if arbol in dcim_catalog.TREES:
            donde_marcas.append('tree = ?')
            params_marcas.append(arbol)
        donde_marcas = ' AND '.join(donde_marcas)
        params_marcas = tuple(params_marcas)
        rows = cat.list(where, tuple(params), limit=PAGE, offset=offset)
        # El total ANTES de recortar: es la diferencia entre «hay doscientos» y «se están
        # enseñando doscientos de seis mil», y solo la segunda es cierta.
        esquemas = getattr(wa, '_dcim_schemas', None)
        return jsonify({'types': rows, 'makers': cat.makers(donde_marcas, params_marcas),
                        'total': cat.count(where, tuple(params)),
                        'offset': offset, 'limit': PAGE,
                        # Qué orígenes hay, para poder vaciar uno sin teclear su nombre:
                        # equivocarse en una letra vacía cero modelos y no lo dice nadie.
                        'sources': [{'name': n, 'count': c} for n, c in cat.sources()],
                        # Las clases del catálogo ENTERO, no las de la página: un filtro que
                        # cambia de opciones al pasar de página es un filtro del que nadie se
                        # fía.
                        'kinds': [{'name': n, 'count': c} for n, c in cat.kinds()],
                        # El vocabulario COMPLETO, que no es el mismo que las clases que hay:
                        # para corregir una fila hace falta poder elegir una que todavía no
                        # usa nadie, y escribir la lista en la pantalla sería tenerla dos veces.
                        'all_kinds': list(dcim_catalog.KINDS),
                        # Y el vocabulario de CADA árbol, porque no es el mismo: un DIMM no es
                        # «switch, servidor u otro». Servido desde aquí y no escrito en la
                        # pantalla, que es como una lista acaba estando en dos sitios y
                        # discrepando.
                        'kinds_by_tree': {a: list(dcim_catalog.kinds_for(a))
                                          for a in dcim_catalog.TREES},
                        # Qué se pregunta de un componente de cada clase. Servido y no escrito
                        # en la pantalla: once clases con cuatro atributos puestas a mano en una
                        # plantilla son la lista que nadie actualiza el día que entra la doceava.
                        'component_fields': C.component_fields(),
                        # Lo que dice todo componente —el peso—, y cómo se llama su casilla de
                        # tamaño en cada clase: la misma casilla es la capacidad de un disco y
                        # los vatios de una fuente.
                        'component_common': dcim_profiles.common(
                            dcim_profiles.effective(C.profiles())),
                        # Las fechas de la vida de un modelo, que no son de los componentes:
                        # un servidor deja de venderse y deja de recibir parches igual que un
                        # disco. Aparte de los comunes porque van en su propio bloque.
                        'lifecycle_fields': dcim_profiles.group_fields(C.profiles(),
                                                                      'lifecycle'),
                        'component_size': (dcim_profiles.effective(C.profiles()).get('size')
                                           or {}),
                        'tree_counts': [{'name': n, 'count': c} for n, c in cat.trees()],
                        # Cuánto hay detrás de cada pestaña. Servidos aquí y no pedidos al abrir
                        # cada una: un número que solo aparece después de entrar no contesta la
                        # pregunta que hace un número en una pestaña, y uno que aparece o no
                        # según por dónde se haya pasado es peor — es el mismo fallo que la
                        # columna Plataforma de las plantillas.
                        'counts': {
                            'brands': len(cat.brands.list()),
                            'platforms': len(C.platforms().list()) if C.platforms() else 0,
                            'schemas': len(esquemas.list()) if esquemas else 0,
                            'connectors': dcim_connectors.count(C.conns()),
                        },
                        'tree': arbol,
                        'trees': list(dcim_catalog.TREES),
                        'power_types': list(dcim_catalog.POWER_TYPES),
                        # Por dónde se enchufa cada cosa, con un nombre que alguien reconoce:
                        # `iec-60320-c19` y `c20` se distinguen en un carácter y son dos cosas
                        # distintas. Del documento y no de una lista en el navegador, que es el
                        # peor sitio: no se lee desde el servidor y nadie que sepa qué falta la
                        # encuentra.
                        'connectors': dcim_connectors.by_family(wa._lang(), C.conns()),
                        # Con el nombre de cada señal, por lo mismo: un identificador
                        # suelto no se lee.
                        'signals': dcim_connectors.signals(wa._lang(), C.conns()),
                        'library_trees': list(dcim_catalog.LIBRARY_TREES),
                        'library_url': _library_url()})

    @app.route('/api/v1/dcim/catalog/suggest', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_catalog_suggest():
        """What a device's own words point at — a PROPOSAL, never a decision.

        Nothing here writes. `sysDescr` is free text and a wrongly matched model puts a 2U
        device in a U that has not got the room; the panel offers, a person agrees.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None:
            return jsonify({'match': None})
        hit = cat.suggest(request.args.get('maker') or '', request.args.get('model') or '')
        return jsonify({'match': hit})

    #: Lo que el proveedor contesta cuando algo sale mal, y qué frase le corresponde. Cada una
    #: dice qué hacer: una rama que no existe se arregla escribiendo la buena, y un límite
    #: agotado se arregla esperando — y son dos cosas que «no se pudo» no distingue.
    _BROWSE_ERRORS = {
        'bad_url': 'dcim_catalog_bad_url',
        'not_found': 'dcim_catalog_not_found',
        'rate_limited': 'dcim_catalog_rate_limited',
        'truncated': 'dcim_catalog_truncated',
        'too_large': 'dcim_catalog_too_large',
        'bad_json': 'dcim_catalog_bad_json',
    }

    def _browse_reason(err: str) -> str:
        """La clave de la frase que explica *err*, o la genérica si es una que no se conocía."""
        return _BROWSE_ERRORS.get(str(err or ''), 'dcim_catalog_download_failed')

    def _library_url() -> str:
        """De dónde se trae el catálogo: lo configurado, y si no, la de NetBox.

        Se lee en cada llamada y no se guarda: cambiar la dirección no debe pedir un reinicio,
        y quien la cambie a mediodía esperaría que la siguiente importación fuera ya de la
        nueva —no de la que había cuando arrancó el proceso—.
        """
        return str(getattr(wa, '_DCIM_CATALOG_URL', '') or dcim_catalog.LIBRARY_URL)

    @app.route('/api/v1/dcim/catalog/browse', methods=['GET'])
    # Mirar cuesta una descarga de treinta megas en el servidor: es un acto y no una vista,
    # así que lo pide el mismo permiso que importar y no el de leer el catálogo.
    @C.catalog_manage_req
    def api_dcim_catalog_browse():
        """Qué fabricantes trae la biblioteca, antes de importar nada.

        Dos peticiones y no una, a propósito. Traerlo todo son más de cuatro mil modelos de
        doscientos fabricantes, y una instalación con equipos de cinco convive con el ruido para
        siempre: el buscador deja de servir el día que se importa.

        La descarga se reutiliza en la importación posterior — el proveedor la guarda con su
        ETag, y la segunda vez cuesta una petición y ningún megabyte.
        """
        url = str(request.args.get('url') or '').strip() or _library_url()
        d = dcim_catalog.browse(url)
        fallo = str(d.get('error') or '')
        # Queda registrado mire quien mire, salga como salga. Es una petición a una máquina
        # ajena hecha desde este servidor: si acaba en «se acabaron las peticiones de la hora»
        # o en «esa rama no existe», eso tiene que poder leerse después sin estar delante.
        wa._audit('dcim_catalog_browse',
                  detail={'url': url,
                          'ok': not fallo,
                          'vendors': len(d.get('vendors') or []),
                          'error': fallo})
        if fallo:
            # Con 200 y no con 400, a propósito: el envoltorio de GET del panel devuelve `null`
            # ante cualquier respuesta que no sea 2xx, y el cuerpo —donde va el motivo— se
            # pierde antes de que nadie lo lea. Un 400 aquí es exactamente el «Error» sin
            # explicación que provocó esto. La petición se atendió; lo que falló es lo de
            # fuera, y eso se cuenta en el cuerpo.
            return jsonify({'error': wa._t(_browse_reason(fallo)),
                            'detail': fallo, 'url': url, 'vendors': []})
        # El índice completo NO sale de aquí: son once mil rutas y tres megas que el navegador
        # no usa para nada. La importación lo vuelve a pedir — una petición más de las sesenta
        # que hay por hora, contra tres megas por cada persona que abra la pantalla.
        return jsonify({'vendors': d.get('vendors') or [],
                        'url': url,
                        'trees': list(dcim_catalog.LIBRARY_TREES)})

    #: Cuántos modelos se enseñan de una vez. Un catálogo entero son seis mil filas que nadie
    #: lee y que cuestan lo mismo que si alguien fuera a leerlas; lo que hace falta es poder
    #: llegar a todas, y para eso está el desplazamiento y el buscador.
    PAGE = 200

    #: Lo que puede pesar un zip subido por el navegador. El tope general del panel son ocho
    #: megas —pensado para un JSON— y una biblioteca de modelos con sus imágenes los pasa sin
    #: esfuerzo. Sesenta y cuatro es lo que cabe subir por un formulario sin que la espera se
    #: vuelva absurda; para más está la otra puerta, que es apuntar a una carpeta del servidor.
    MAX_UPLOAD = 64 * 1024 * 1024

    def _rm_quiet(path: str) -> None:
        """Borrar sin que el fallo al borrar sea el error que se cuenta."""
        try:
            os.remove(path)
        except OSError:
            pass

    @app.route('/api/v1/dcim/catalog/upload', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_catalog_upload():
        """Importar un zip que llega en la petición, sin pedirle a nadie una ruta del servidor.

        Escribir la ruta de un fichero del disco del servidor supone tener acceso a ese disco.
        Quien administra el panel desde un navegador normalmente no lo tiene — y decirle «deja
        el zip en una carpeta mía» es pedirle que haga primero la parte que no puede hacer.

        El fichero se deja en un temporal y se borra en cuanto la importación acaba: lo que
        interesa está en la base de datos a partir de ese momento, y guardar el archivo sería
        guardar una copia de algo que ya se leyó.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        # El tope general del panel son ocho megas, que es lo que debe pesar un JSON. Se sube
        # para ESTA petición y no en la configuración de la aplicación: subirlo en general
        # dejaría que cualquier otra ruta aceptara sesenta y cuatro megas de cuerpo.
        try:
            request.max_content_length = MAX_UPLOAD
        except (AttributeError, TypeError):     # pragma: no cover  (Flask < 3.1)
            pass
        up = (request.files or {}).get('file')
        blob = up.read(MAX_UPLOAD + 1) if up is not None else request.data[:MAX_UPLOAD + 1]
        if not blob:
            return jsonify({'error': wa._t('dcim_catalog_path_required')}), 400
        if len(blob) > MAX_UPLOAD:
            return jsonify({'error': wa._t('dcim_catalog_upload_big')}), 400
        # Que sea un zip lo dicen sus primeros bytes y no su nombre: la extensión es una
        # afirmación de quien lo sube, y aquí lo que se va a abrir es el contenido.
        if not blob.startswith(b'PK'):
            return jsonify({'error': wa._t('dcim_catalog_not_zip')}), 400
        import tempfile                                     # noqa: PLC0415
        fd, tmp = tempfile.mkstemp(prefix='ss-dcim-catalog-', suffix='.zip')
        try:
            with os.fdopen(fd, 'wb') as fh:
                fh.write(blob)
        except OSError as exc:
            return jsonify({'error': str(exc)}), 500
        job_id, err = dcim_jobs.start_import(
            cat, str(request.form.get('source') or 'library'), 'zip', tmp,
            actor=C.actor(), var_dir=wa._var_dir or '', media_dir=C.media_dir(),
            cleanup=tmp)
        if err:
            _rm_quiet(tmp)
            return jsonify({'error': wa._t(err)}), 409 if err == 'dcim_catalog_busy' else 400
        wa._audit('dcim_catalog_import',
                  detail={'source': str(request.form.get('source') or 'library'),
                          'kind': 'upload', 'bytes': len(blob)})
        return jsonify({'job': job_id})

    @app.route('/api/v1/dcim/catalog/import', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_catalog_import():
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        # De dónde viene, PRIMERO. Cada procedencia tiene su requisito y ninguno vale para las
        # otras: exigir una ruta antes de mirar si lo que se pide es un repositorio es lo que
        # hacía que importar de GitHub contestara «falta la ruta o el archivo zip».
        github = str(data.get('github') or '').strip()
        # `all` es traerse el repositorio entero de una vez, que para «todos» es lo barato: diez
        # mil ochocientos ficheros de uno en uno son tres cuartos de hora y el mismo contenido en
        # un zip baja en poco más de un minuto. Para tres fabricantes es al revés.
        todo = bool(data.get('all'))
        if github or todo or data.get('vendors') is not None:
            elegidos = [] if todo else [str(v) for v in (data.get('vendors') or [])]
            job_id, err = dcim_jobs.start_import(
                cat, str(data.get('source') or 'library'),
                'github_all' if todo else 'github',
                github or _library_url(), actor=C.actor(),
                var_dir=wa._var_dir or '', media_dir=C.media_dir(),
                vendors=elegidos)
            if err:
                return jsonify({'error': wa._t(err)}), \
                    409 if err == 'dcim_catalog_busy' else 400
            wa._audit('dcim_catalog_import',
                      detail={'source': str(data.get('source') or 'library'),
                              'kind': 'github_all' if todo else 'github',
                              'url': github or _library_url(),
                              # Los nombres y no cuántos: dentro de un año la pregunta será
                              # «¿de dónde salió este modelo?», y un número no la contesta.
                              'vendors': ', '.join(elegidos[:20]) or '*'})
            return jsonify({'job': job_id})
        path = str(data.get('path') or '').strip()
        if not path:
            return jsonify({'error': wa._t('dcim_catalog_path_required')}), 400
        # Resolved and checked HERE, once, because this is where a request's word becomes a
        # filesystem path — and the job module deliberately does not check it a second time,
        # which is how two checks come to disagree.
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(path):
            return jsonify({'error': wa._t('dcim_catalog_path_missing')}), 400
        kind = 'zip' if os.path.isfile(path) else 'dir'
        if kind == 'zip' and not path.lower().endswith('.zip'):
            return jsonify({'error': wa._t('dcim_catalog_path_missing')}), 400
        job_id, err = dcim_jobs.start_import(
            cat, str(data.get('source') or 'library'), kind, path,
            actor=C.actor(),
            # Dónde guardar las imágenes de elevación que la biblioteca trae al lado de cada
            # modelo: hasta ahora se leía que existían y se tiraba la imagen.
            var_dir=wa._var_dir or '', media_dir=C.media_dir())
        if err:
            return jsonify({'error': wa._t(err)}), 409 if err == 'dcim_catalog_busy' else 400
        wa._audit('dcim_catalog_import', detail={'source': str(data.get('source')
                                                                or 'library'),
                                                 'kind': kind})
        return jsonify({'job': job_id})

    @app.route('/api/v1/dcim/catalog/import/<job_id>', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_catalog_import_status(job_id):
        job = dcim_jobs.job_status(job_id)
        if job is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        return jsonify(job)

    #: De dónde son los modelos escritos a mano. Su propio origen, así que ninguna
    #: importación los toca: lo que alguien escribió porque no existe en ningún repositorio no
    #: puede desaparecer al actualizar el repositorio.
    MANUAL_SOURCE = 'manual'

    # ── Los esquemas: qué campos tiene un modelo ──────────────────────────────

    @app.route('/api/v1/dcim/schemas', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_schemas():
        """Los esquemas guardados, con sus campos.

        Los lee quien va a escribir un modelo, así que basta el permiso de mirar el catálogo:
        traerlos o cambiarlos es otra cosa y pide el de importar.
        """
        st = getattr(wa, '_dcim_schemas', None)
        if st is None:
            return jsonify({'schemas': []})
        return jsonify({'schemas': st.list(),
                        # Dónde acaba cada campo, para que la pantalla lo enseñe sin tener que
                        # saberlo por su cuenta: la correspondencia se decide en un sitio.
                        'columns': sorted(dcim_schemas.FIELD_COLUMN),
                        'ports': list(dcim_schemas.PORT_FIELDS),
                        'trees': list(dcim_catalog.LIBRARY_TREES)})

    @app.route('/api/v1/dcim/schemas/fetch', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_schemas_fetch():
        """Traer los tres de la biblioteca configurada.

        Cuatro ficheros pequeños y ningún modelo: los tres esquemas y las definiciones que
        comparten. Reemplaza los que se trajeron antes —por nombre— y no toca los propios.
        """
        st = getattr(wa, '_dcim_schemas', None)
        if st is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        url = str(data.get('url') or '').strip() or _library_url()
        traidos, err = dcim_schemas.fetch(url, _gh)
        if err:
            return jsonify({'error': wa._t(err), 'detail': err}), 200
        for e in traidos:
            st.save(e['name'], e['tree'], e['fields'], source='library')
        wa._audit('dcim_schema_save',
                  detail={'action': 'fetch', 'url': url, 'count': len(traidos)})
        return jsonify({'count': len(traidos)})

    @app.route('/api/v1/dcim/schemas', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_schema_save():
        """Escribir un esquema, o clonar uno.

        Clonar es lo que hace esto útil: una sala tiene un cuadro eléctrico, una caja de fibra,
        un armario ignífugo de cintas — cosas que no están en ningún repositorio. Partir del que
        más se le parezca y quitarle y ponerle campos es más corto que escribirlos todos, y
        mucho más corto que meterlas como «otro» y apuntar el resto en la descripción.
        """
        st = getattr(wa, '_dcim_schemas', None)
        if st is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        nombre = str(data.get('name') or '').strip()
        if not nombre:
            return jsonify({'error': wa._t('dcim_schema_need_name')}), 400
        base = st.get(str(data.get('from') or '')) if data.get('from') else None
        if base and st.by_name(nombre) and nombre == base['name']:
            # Clonar sobre el mismo nombre no es clonar, es perder el original sin decirlo.
            return jsonify({'error': wa._t('dcim_schema_dup')}), 400
        campos = data.get('fields')
        if not isinstance(campos, list):
            campos = list(base['fields']) if base else []
        uid = st.save(nombre, str(data.get('tree') or (base or {}).get('tree') or ''),
                      _clean_fields(campos), source='manual',
                      based_on=(base or {}).get('name', ''))
        if not uid:
            return jsonify({'error': wa._t('dcim_schema_need_name')}), 400
        wa._audit('dcim_schema_save',
                  detail={'action': 'clone' if base else 'write', 'name': nombre,
                          'fields': len(campos)})
        return jsonify({'uid': uid})

    @app.route('/api/v1/dcim/schemas/<uid>', methods=['DELETE'])
    @C.catalog_manage_req
    def api_dcim_schema_drop(uid):
        st = getattr(wa, '_dcim_schemas', None)
        if st is None or not st.get(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        nombre = st.get(uid)['name']
        st.delete(uid)
        wa._audit('dcim_schema_save', detail={'action': 'drop', 'name': nombre})
        return jsonify({'ok': True})

    def _clean_fields(campos) -> list:
        """Los campos que llegan en una petición, en la forma que el almacén guarda.

        Campo a campo y con el destino decidido AQUÍ: si una petición pudiera elegir a qué
        columna va un campo, un esquema podría escribir en `source` o en `uid` — y el destino
        no es una opinión, es dónde este panel sabe guardar cada cosa.
        """
        fuera = []
        for c in (campos or []):
            if not isinstance(c, dict):
                continue
            nombre = str(c.get('name') or '').strip()
            if not nombre or nombre in dcim_schemas.SKIP_FIELDS:
                continue
            if nombre in dcim_schemas.PORT_FIELDS:
                destino, tipo = 'ports', 'count'
            elif nombre in dcim_schemas.FIELD_COLUMN:
                destino, tipo = 'column', str(c.get('type') or 'string')
            else:
                destino, tipo = 'extra', str(c.get('type') or 'string')
            fuera.append({'name': nombre, 'type': tipo, 'target': destino,
                          'enum': [str(v) for v in (c.get('enum') or [])],
                          'required': bool(c.get('required'))})
        return fuera

    @app.route('/api/v1/dcim/catalog', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_catalog_new():
        """Un modelo escrito a mano.

        Para lo que no está en ninguna biblioteca: el armario que montó el electricista, la
        bandeja con el mini-PC y su cargador, el dispositivo de un fabricante que no publica nada.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        fila = _catalog_fields(data)
        # Clonar: casi ningún modelo se escribe desde cero. Lo que hay en una sala es «como el
        # R640 pero con la otra fuente», y teclear veinte campos para cambiar uno es el trabajo
        # que nadie hace — se deja sin registrar.
        origen = cat.get(str(data.get('from') or '')) if data.get('from') else None
        if origen:
            # Las imágenes se COPIAN, no se comparten: dos filas apuntando al mismo fichero
            # significan que borrar cualquiera de las dos deja a la otra enseñando un hueco.
            fila.update(cat.copy_images(origen, wa._var_dir or '', C.media_dir()))
            for campo in ('ports', 'extra'):
                fila.setdefault(campo, origen.get(campo) or {})
        uid = cat.create(fila, MANUAL_SOURCE, actor=C.actor())
        if not uid:
            return jsonify({'error': wa._t('dcim_catalog_need_name')}), 400
        # Y los adjuntos, también copiados: entraron después de que existiera el clonado y se
        # quedaron fuera, así que clonar daba una ficha sin manual y sin decirlo.
        if origen and C.files():
            C.files().copy(origen['uid'], uid, wa._var_dir or '', C.media_dir(), actor=C.actor())
        wa._audit('dcim_catalog_edit',
                  detail={'action': 'clone' if origen else 'create',
                          'maker': fila.get('manufacturer'),
                          'model': fila.get('model'), 'kind': fila.get('kind'),
                          'from': (origen or {}).get('model', '')})
        return jsonify({'uid': uid})

    @app.route('/api/v1/dcim/catalog/<uid>', methods=['PUT'])
    @C.catalog_manage_req
    def api_dcim_catalog_edit(uid):
        """Corregir un modelo — sobre todo, la clase que se dedujo.

        La deducción mira los puertos, y una fuente de alimentación declara un `power-ports` y
        nada más, igual que media docena de cosas distintas. Nadie va a escribir una regla que
        acierte los ocho mil quinientos casos; quien mira la fila sabe lo que es en un segundo.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        antes = cat.get(uid)
        if not antes:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        if not cat.update(uid, _catalog_fields(data, parcial=True,
                                              tree_actual=str(antes.get('tree') or '')),
                          actor=C.actor()):
            return jsonify({'error': wa._t('dcim_catalog_need_name')}), 400
        # QUÉ cambió, no solo que se editó. Los nombres de los campos y no sus valores: una
        # línea del registro se lee de un vistazo entre doscientas, y volcar veinte valores la
        # haría ilegible — los valores están en la versión, que es exactamente para eso.
        cambios = dcim_revs.diff(antes, cat.get(uid) or {})
        wa._audit('dcim_catalog_edit',
                  detail={'action': 'edit', 'maker': antes.get('manufacturer'),
                          'model': antes.get('model'),
                          'kind': str(data.get('kind') or antes.get('kind') or ''),
                          'changed': sorted(cambios)})
        return jsonify({'ok': True, 'changed': sorted(cambios)})

    def _catalog_fields(data: dict, parcial: bool = False, tree_actual: str = '') -> dict:
        """Lo que una petición puede decir de un modelo, y en la forma que la tabla espera.

        Se copia campo a campo y no en bloque: una petición que trajera `source` o `uid`
        reescribiría de dónde vino algo, y la lista de lo que se acepta es la única defensa que
        no se olvida de un campo nuevo el día que la tabla crezca.

        *parcial* es la diferencia entre crear y corregir: al crear, lo que no venga toma su
        valor por defecto; al corregir, lo que no venga **no se toca**, que es lo que permite
        cambiar solo la clase sin mandar el modelo entero de vuelta.
        """
        fuera = {}
        arbol = str(data.get('tree') or '').strip()
        if arbol in dcim_catalog.TREES:
            fuera['tree'] = arbol
        elif not parcial:
            fuera['tree'] = 'device-types'
        # Contra el vocabulario del árbol y no contra el de los dispositivos. Al corregir una
        # fila el árbol puede no venir en la petición —se cambia solo la clase— así que el de la
        # fila que ya existe es el que decide; sin eso, `memory` se leía como una clase que no
        # existe y se descartaba en silencio.
        efectivo = fuera.get('tree') or arbol or tree_actual or 'device-types'
        clase = str(data.get('kind') or '').strip()
        if clase in dcim_catalog.kinds_for(efectivo):
            fuera['kind'] = clase
        for campo in ('manufacturer', 'model', 'slug', 'part_number', 'airflow',
                      'subdevice', 'description', 'size', 'url'):
            if campo in data:
                fuera[campo] = str(data.get(campo) or '').strip()
        poder = str(data.get('power_type') or '').strip()
        if poder in dcim_catalog.POWER_TYPES:
            fuera['power_type'] = poder
        elif 'power_type' in data:
            fuera['power_type'] = ''
        if 'kit_qty' in data:
            try:
                fuera['kit_qty'] = max(1, int(float(data.get('kit_qty') or 1)))
            except (TypeError, ValueError):
                fuera['kit_qty'] = 1
        elif not parcial:
            fuera['kit_qty'] = 1
        if 'u_height' in data or 'u_tenths' in data:
            try:
                fuera['u_tenths'] = max(0, int(round(float(
                    data.get('u_tenths', float(data.get('u_height') or 0) * 10)))))
            except (TypeError, ValueError):
                pass
        elif not parcial:
            fuera['u_tenths'] = 10
        for campo, clave in (('full_depth', 'full_depth'), ('is_powered', 'is_powered')):
            if clave in data:
                fuera[campo] = 0 if str(data.get(clave)).lower() in ('0', 'false', 'no') else 1
        if not parcial:
            fuera.setdefault('full_depth', 1)
            fuera.setdefault('is_powered', 1)
        if isinstance(data.get('ports'), dict):
            fuera['ports'] = data['ports']
        if isinstance(data.get('extra'), dict):
            fuera['extra'] = data['extra']
        return fuera

    @app.route('/api/v1/dcim/catalog/<uid>/image/<face>', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_catalog_image(uid, face):
        """Poner la imagen de una cara de un modelo.

        La biblioteca trae las de mil doscientos modelos y ninguna de los demás — y ninguna, por
        definición, de lo que alguien escriba a mano. Un alzado sin imagen es una caja gris con
        un nombre dentro: se entiende y no se reconoce de un vistazo, que es para lo que sirve.

        El tipo lo decide lo que hay DENTRO del fichero y el nombre lo acuña el almacén de
        medios. Una extensión es una afirmación de quien sube, y un nombre llegado por la red no
        toca este disco.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        fila = cat.get(uid) if cat else None
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if face not in ('front', 'rear'):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        up = (request.files or {}).get('file')
        blob = up.read(dcim_media.MAX_BYTES + 1) if up is not None \
            else request.data[:dcim_media.MAX_BYTES + 1]
        nombre, err = dcim_media.save(wa._var_dir or '', blob, C.media_dir())
        if err:
            return jsonify({'error': wa._t(err)}), 400
        vieja = str(fila.get(f'{face}_image') or '')
        cat.set_image(uid, face, nombre, actor=C.actor())
        # La que sustituye se va, o cada cambio deja un fichero al que no apunta nadie y la
        # carpeta crece durante toda la vida de la instalación.
        if vieja and vieja != nombre:
            dcim_media.forget(wa._var_dir or '', vieja, C.media_dir())
        wa._audit('dcim_catalog_edit',
                  detail={'action': 'image', 'face': face,
                          'maker': fila.get('manufacturer'), 'model': fila.get('model')})
        return jsonify({'image': nombre})

    @app.route('/api/v1/dcim/catalog/<uid>/image/<face>', methods=['DELETE'])
    @C.catalog_manage_req
    def api_dcim_catalog_image_drop(uid, face):
        cat = getattr(wa, '_dcim_catalog', None)
        fila = cat.get(uid) if cat else None
        if not fila or face not in ('front', 'rear'):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        vieja = str(fila.get(f'{face}_image') or '')
        cat.set_image(uid, face, '', actor=C.actor())
        if vieja:
            dcim_media.forget(wa._var_dir or '', vieja, C.media_dir())
        wa._audit('dcim_catalog_edit',
                  detail={'action': 'image_drop', 'face': face,
                          'maker': fila.get('manufacturer'), 'model': fila.get('model')})
        return jsonify({'ok': True})

    # ── Lo que no es una foto: manuales, hojas, firmware ──────────────────────


    @app.route('/api/v1/dcim/catalog/<uid>/files', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_catalog_files(uid):
        """Lo que hay colgado de un modelo. Se lee con el permiso de consultar: buscar el manual
        a las once de la noche no es administrar el catálogo."""
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None or not cat.get(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        store = C.files()
        return jsonify({'files': store.of(uid) if store else [],
                        'kinds': list(dcim_files.KINDS),
                        'max_bytes': dcim_files.MAX_BYTES})

    @app.route('/api/v1/dcim/catalog/<uid>/files', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_catalog_file_add(uid):
        """Colgar uno. Multipart, campo `file`; `kind` dice de qué es.

        **Sin lista blanca de tipos**, y es una decisión: lo útil aquí es abierto —un PDF, el
        `.docx` del distribuidor, el zip del firmware— y una lista se queda corta cada semana, con
        lo que quien la sufre acaba renombrando ficheros para colarlos. Lo que hace que sea seguro
        es que **siempre sale como descarga**: este panel no renderiza nunca un fichero subido.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        fila = cat.get(uid) if cat else None
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
                          kind=str(request.form.get('kind') or request.args.get('kind') or ''),
                          actor=C.actor())
        wa._audit('dcim_catalog_edit',
                  detail={'action': 'file', 'maker': fila.get('manufacturer'),
                          'model': fila.get('model'), 'file': etiqueta})
        return jsonify({'uid': nuevo, 'files': store.of(uid)})

    @app.route('/api/v1/dcim/files/<uid>', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_file_get(uid):
        """Bajarse uno. **Siempre como descarga y con tipo genérico.**

        Es lo que permite no tener lista blanca: un HTML o un SVG subidos no se ejecutan en este
        origen porque el navegador no llega a renderizarlos. `nosniff` cierra la otra mitad —
        adivinar el tipo por el contenido es exactamente lo que aquí no debe pasar.
        """
        store = C.files()
        fila = store.get(uid) if store else None
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        blob, err = dcim_media.read(wa._var_dir or '', str(fila.get('stored') or ''),
                                    C.media_dir(), dcim_files.MAX_BYTES)
        if err:
            return jsonify({'error': wa._t(err)}), 404
        resp = app.response_class(blob, mimetype='application/octet-stream')
        # El nombre que se ofrece es la etiqueta, saneada y en ASCII: lo que llegó por la red no
        # decide cómo se escribe una cabecera.
        seguro = ''.join(c for c in str(fila.get('label') or 'adjunto')
                         if 32 <= ord(c) < 127 and c not in '"\\') or 'adjunto'
        resp.headers['Content-Disposition'] = f'attachment; filename="{seguro}"'
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['Cache-Control'] = 'private, max-age=86400, immutable'
        return resp

    @app.route('/api/v1/dcim/files/<uid>', methods=['DELETE'])
    @C.catalog_manage_req
    def api_dcim_file_drop(uid):
        store = C.files()
        fila = store.delete(uid) if store else None
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        dcim_media.forget(wa._var_dir or '', str(fila.get('stored') or ''), C.media_dir())
        wa._audit('dcim_catalog_edit',
                  detail={'action': 'file_drop', 'file': str(fila.get('label') or '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/catalog/<uid>/history', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_catalog_history(uid):
        """Qué decía esta ficha antes, y quién la cambió.

        Un modelo del catálogo es un dato compartido: de él cuelgan las plantillas, las piezas
        estampadas en veinte máquinas y la altura con la que se dibuja un alzado. La corrección
        que rompe algo casi nunca se descubre el día que se hace — se descubre semanas después,
        cuando alguien dice «esto antes ponía otra cosa» y no hay forma de saber si tiene razón.

        Se lee con el permiso de consultar: mirar lo que decía ayer es leer, y quien no puede
        importar sigue necesitando saber si el dato con el que trabaja cambió bajo sus pies.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None or not cat.get(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        return jsonify({'history': cat.revs.history(uid), 'keep': dcim_revs.KEEP})

    @app.route('/api/v1/dcim/catalog/<uid>/restore', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_catalog_restore(uid):
        """Volver a una versión. Escribe los valores de aquella y **deja constancia**.

        No borra lo de en medio: volver atrás es un cambio más, no un deshacer que hace
        desaparecer la historia. Si fuera lo segundo, la respuesta a «quién dejó esto así» sería
        distinta según cuándo se preguntara.

        La imagen no se restaura: lo que aquella versión guardaba era el NOMBRE de un fichero, y
        ese fichero puede haberse borrado al sustituirlo. Escribir el nombre de algo que no está
        sería cambiar una foto por un hueco.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        actual = cat.get(uid) if cat else None
        if not actual:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        version = cat.revs.get(str(data.get('rev') or ''))
        if not version or str(version.get('ref_uid')) != str(uid):
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        antes_de = version.get('data') or {}
        campos = {c: antes_de[c] for c in cat._EDITABLE if c in antes_de}   # noqa: SLF001
        if not cat.update(uid, campos, actor=C.actor()):
            return jsonify({'error': wa._t('dcim_catalog_need_name')}), 400
        cambios = dcim_revs.diff(actual, cat.get(uid) or {})
        wa._audit('dcim_catalog_edit',
                  detail={'action': 'restore', 'maker': actual.get('manufacturer'),
                          'model': actual.get('model'), 'rev': version.get('at'),
                          'changed': sorted(cambios)})
        return jsonify({'ok': True, 'changed': sorted(cambios)})

    @app.route('/api/v1/dcim/catalog/<uid>', methods=['DELETE'])
    @C.catalog_manage_req
    def api_dcim_catalog_delete(uid):
        """Quitar un modelo suelto.

        Con el permiso de importar y no con uno propio: quien puede reemplazar el catálogo
        entero puede quitarle una fila, y un permiso más fino aquí sería un permiso que nadie
        sabría cuándo dar.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        fila = cat.get(uid)
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        # Los adjuntos se van con él: dejarlos sería dejar ficheros en el disco a los que no
        # apunta nadie, el mismo agujero que se tapó con las imágenes al reimportar.
        for f in ((C.files().forget(uid)) if C.files() else ()):
            dcim_media.forget(wa._var_dir or '', str(f.get('stored') or ''), C.media_dir())
        cat.delete(uid, wa._var_dir or '', C.media_dir())
        wa._audit('dcim_catalog_drop',
                  detail={'maker': str(fila.get('manufacturer') or ''),
                          'model': str(fila.get('model') or ''),
                          'source': str(fila.get('source') or '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/catalog/basics', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_catalog_basics():
        """Meter los genéricos que vienen con el panel.

        Sin trabajo de fondo y sin descargar nada: son treinta filas escritas en el código, así
        que la respuesta llega antes de que a nadie le dé tiempo a mirar una barra. Un trabajo
        con su hilo y su seguimiento para esto sería andamiaje para tres décimas de segundo.

        Con su propia etiqueta —`core`— para que reimportar la biblioteca no se los lleve por
        delante ni al revés: son dos orígenes, y `replace` trabaja por origen.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        n = cat.replace(dcim_basics.SOURCE, dcim_basics.rows(wa._lang()),
                        wa._var_dir or '', C.media_dir())
        # Y las plataformas que se van a teclear igual. **Se añaden, no se reemplazan**: volver
        # a pulsar el botón no puede pisar la fecha de fin de soporte ni las notas que alguien
        # escribió sobre la suya, y `ensure` devuelve la que ya está sin tocarla.
        plats, marcas = C.platforms(), C.brands()
        p = 0
        for fila in (dcim_basics.platforms(wa._lang()) if plats is not None else ()):
            nombre = str(fila.get('name') or '')
            ya = plats.find(nombre)
            marca = (marcas.ensure(str(fila['brand']), actor=C.actor())
                     if fila.get('brand') and marcas is not None else '')
            if ya is None:
                # Nueva: entra entera. Darla de alta con solo el nombre y completarla después
                # dejaba fuera lo que ya tiene valor por defecto —la clase— y por eso Proxmox
                # y ESXi entraban como «sistema operativo».
                datos = {k: fila.get(k) or '' for k in ('name', 'family', 'kind', 'notes')}
                datos['extra'] = dict(fila.get('extra') or {})
                datos['brand_uid'] = marca
                p += 1 if plats.create(datos, actor=C.actor()) else 0
                continue
            p += 1
            # Ya estaba: **se rellena lo vacío y no se pisa nada.** Lo que no se puede tocar es
            # un valor que alguien escribió, y un hueco no es un valor — ni la cadena vacía ni
            # el valor por defecto, que es lo que se pone cuando nadie ha dicho nada.
            campos = {}
            for k in ('family', 'notes'):
                if fila.get(k) and not str(ya.get(k) or '').strip():
                    campos[k] = str(fila[k])
            if fila.get('kind') and str(ya.get('kind') or 'os') == 'os' \
                    and str(fila['kind']) != 'os':
                campos['kind'] = str(fila['kind'])
            # Fecha a fecha, no el bloque entero: la que alguien corrigió se queda y la que
            # falta se completa. Todo o nada haría que una sola fecha escrita a mano bloqueara
            # las otras cinco para siempre.
            tiene = dict(ya.get('extra') or {})
            nuevas = {k: v for k, v in (fila.get('extra') or {}).items()
                      if not str(tiene.get(k) or '').strip()}
            if nuevas:
                campos['extra'] = dict(tiene, **nuevas)
            if not str(ya.get('brand_uid') or '') and marca:
                campos['brand_uid'] = marca
            if campos:
                plats.update(str(ya['uid']), campos, actor=C.actor())
        wa._audit('dcim_catalog_import',
                  detail={'source': dcim_basics.SOURCE, 'kind': 'basics', 'count': n,
                          'platforms': p})
        return jsonify({'ok': True, 'count': n, 'platforms': p})

    @app.route('/api/v1/dcim/catalog/drop', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_catalog_drop():
        """Quitar varios modelos: los marcados, o un origen entero.

        Una petición y no cuatrocientas: quien marca cuatrocientas filas no quiere cuatrocientas
        confirmaciones ni cuatrocientas idas y venidas, y un borrado a medias por una conexión
        que se cayó a la mitad deja un catálogo que nadie sabe en qué estado quedó.

        `source` vacía un origen entero, que es la unidad en la que ENTRARON. Sin él, deshacer
        una importación equivocada era reimportar las otras para que `replace` se la llevara por
        delante — rehacer lo bueno para deshacer lo malo.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        if cat is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        origen = str(data.get('source') or '').strip()
        if origen:
            n = cat.drop_source(origen, wa._var_dir or '', C.media_dir())
            wa._audit('dcim_catalog_drop', detail={'source': origen, 'count': n})
            return jsonify({'ok': True, 'count': n})
        uids = [str(u) for u in (data.get('uids') or []) if str(u or '').strip()]
        if not uids:
            return jsonify({'error': wa._t('dcim_catalog_pick_none')}), 400
        n = cat.drop_many(uids, wa._var_dir or '', C.media_dir())
        wa._audit('dcim_catalog_drop', detail={'count': n, 'asked': len(uids)})
        return jsonify({'ok': True, 'count': n})

    @app.route('/api/v1/dcim/export', methods=['GET'])
    @C.view_req
    def api_dcim_export():
        """Un fichero con los modelos y las plantillas que se pidan.

        `?types=` y `?builds=` con los identificadores separados por comas. Cada mitad exige su
        permiso de LECTURA y se calla si no lo hay, en vez de negar el fichero entero: quien
        puede ver plantillas y no el catálogo se lleva sus plantillas, que son suyas igual.
        """
        cat = getattr(wa, '_dcim_catalog', None)
        bs = getattr(wa, '_dcim_builds', None)

        def _uids(clave):
            crudo = str(request.args.get(clave) or '')
            return [x.strip() for x in crudo.split(',') if x.strip()][:_EXPORT_MAX]

        tipos = _uids('types') if 'dcim_catalog_view' in C.perms() else []
        plantillas = _uids('builds')
        doc = dcim_portable.export_doc(cat, bs, type_uids=tipos, build_uids=plantillas,
                                       plats=getattr(wa, '_dcim_platforms', None))
        wa._audit('dcim_export', detail={'types': len(doc.get('types') or ()),
                                         'builds': len(doc.get('builds') or ())})
        # Como fichero y no como respuesta que se mira: lo que se ha pedido es llevárselo.
        cuerpo = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)
        sello = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')
        return Response(cuerpo, mimetype='application/json', headers={
            'Content-Disposition': f'attachment; filename="dcim-{sello}.json"'})

    @app.route('/api/v1/dcim/import', methods=['POST'])
    @C.view_req
    def api_dcim_import_doc():
        """Traer lo que falte de un sobre. Cuántos entraron y cuántos ya estaban.

        Cada mitad con **su** permiso: sin el del catálogo llegan las plantillas y los modelos
        no, y se dice — un import que se traga la mitad en silencio deja a alguien creyendo que
        tiene un catálogo que no tiene.
        """
        doc = request.get_json(silent=True) or {}
        malo = dcim_portable.problems(doc)
        if malo:
            return jsonify({'error': wa._t('dcim_port_bad'), 'problems': malo}), 400
        permisos = C.perms()
        puede_cat = 'dcim_catalog_manage' in permisos
        puede_bld = 'dcim_build_edit' in permisos
        if not puede_cat and not puede_bld:
            return jsonify({'error': wa._t('access_denied')}), 403
        recorte = dict(doc)
        if not puede_cat:
            recorte['types'] = []
        if not puede_bld:
            recorte['builds'] = []
        fuera = dcim_portable.import_doc(
            recorte, getattr(wa, '_dcim_catalog', None), getattr(wa, '_dcim_builds', None),
            plats=getattr(wa, '_dcim_platforms', None), actor=C.actor())
        fuera['types_denied'] = len(doc.get('types') or ()) if not puede_cat else 0
        fuera['builds_denied'] = len(doc.get('builds') or ()) if not puede_bld else 0
        wa._audit('dcim_import', detail={k: v for k, v in fuera.items()
                                         if k != 'platforms_missing'})
        return jsonify(fuera)

    @app.route('/api/v1/dcim/catalog/import', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_catalog_running():
        """Is one running — the SERVER's answer, for a browser that has just been reloaded."""
        return jsonify({'job': dcim_jobs.running_job()})

    # Referenciadas para que un analizador no las dé por muertas: Flask se las
    # queda por su ruta.
    _ = (api_dcim_catalog, api_dcim_catalog_suggest, api_dcim_catalog_browse,)
