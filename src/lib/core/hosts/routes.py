#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host registry HTTP routes — all under /api/v1/hosts:

* CRUD: GET (list), POST (create), GET /<uid>/status, POST /<uid>/clone, PUT /<uid>, DELETE /<uid>
* test/probe: POST /test_ssh, /test_check, /test (run a check once without saving)
* assisted migration: GET /migrate/preview, POST /migrate/apply

A host carries an address plus per-protocol connection profiles (ssh, snmp, db, http…) that
watchful modules reuse, so a server connection is defined once.  Secret values inside profiles
are masked on read and restored on write.  All non-HTTP logic (check fan-out, per-host status,
probe-prep, clone-record building, migration planning) lives in :mod:`lib.core.hosts.service`
and :mod:`lib.core.hosts.migrate`; these handlers are thin HTTP glue.

Routes registered by this file:

    GET    /api/v1/hosts                      list hosts the user may view (masked)
    GET    /api/v1/hosts/<uid>/status         latest recorded results per bound check
    DELETE /api/v1/hosts/<uid>/source         unlink a device from where it was imported from
    GET    /api/v1/host_types                 every device class, with how many devices wear it
    POST   /api/v1/host_types                 add one
    PUT    /api/v1/host_types/<uid>           rename it / change its icon / describe it
    DELETE /api/v1/host_types/<uid>           remove one nothing is using
    POST   /api/v1/host_types/seed            put back whichever of the basics are missing
    POST   /api/v1/host_types/<uid>/link      link a class to one in an external provider
    DELETE /api/v1/host_types/<uid>/link      unlink it — it becomes this house's again
    POST   /api/v1/hosts                      create a host
    POST   /api/v1/hosts/<uid>/clone          clone a host (profiles + secrets, new uid)
    PUT    /api/v1/hosts/<uid>                update a host (masked secrets restored)
    DELETE /api/v1/hosts/<uid>                delete a host (optionally its checks)
    POST   /api/v1/hosts/test_ssh             probe a host's SSH connection (no save)
    POST   /api/v1/hosts/test_check           run one check once (no save)
    POST   /api/v1/hosts/test                 full host test: SSH + every bound check
    GET    /api/v1/hosts/migrate/preview      inline-connections migration proposal
    POST   /api/v1/hosts/migrate/apply        create hosts + rewrite the checks
"""

from flask import jsonify, request, session

from lib.security import secret_manager
from lib.core.constants import SYSTEM_USER
from lib.core.hosts import actions as host_actions
from lib.core.hosts import service as hosts_svc
from lib.core.hosts import classes as host_types
from lib.core.hosts import ssh_client
from lib.core.hosts import probe as host_probe
from lib.modules import check_runner
from lib.core.hosts.migrate import apply_to_modules, build_migration_plan
from lib.core.hosts.service import (
    _MOD_RE, _bare, _probe_host_record, _restore_check_secrets,
    _apply_check_cred, _checks_for_host, _create_unique_host,
)


def register(app, wa):
    login_required = wa._login_required

    def _store():
        return getattr(wa, '_hosts_store', None)

    # ── host registry CRUD ───────────────────────────────────────────────────────

    @app.route('/api/v1/hosts', methods=['GET'])
    @login_required
    def api_get_hosts():
        """List hosts the current user may view (secrets masked).

        Users with the global ``devices_view`` see every host; otherwise only
        hosts for which they hold a ``server.{uid}.view`` per-server permission.
        """
        perms = wa._get_session_permissions()
        has_global_view = 'devices_view' in perms
        has_any_view = has_global_view or any(
            p.startswith('server.') and p.endswith('.view') for p in perms)
        if not has_any_view:
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        # Lo que algún paquete ofrece hacer en esta pantalla, y de dónde puede venir un
        # dispositivo. Viajan con la lista y no en una ruta aparte: los dibuja la misma barra que
        # la lista, y una segunda petición para pintar un botón es un botón que aparece tarde.
        extra = {'actions': host_actions.actions(wa),
                 'sources': [{'id': i, 'label_key': str(d.get('label_key') or ''),
                              'icon': str(d.get('icon') or '')}
                             for i, d in sorted(host_actions.sources().items())]}
        if store is None:
            return jsonify(dict(extra, hosts=[]))
        hosts = secret_manager.mask_sensitive(store.list(decrypt=True), wa._secret_keys)
        if not has_global_view:
            hosts = [h for h in hosts if f"server.{h.get('uid')}.view" in perms]
        hosts_svc.enrich_hosts(hosts, hosts_svc._host_statuses(wa),
                               hosts_svc._host_bound_modules(wa))
        return jsonify(dict(extra, hosts=hosts))

    @app.route('/api/v1/hosts/<uid>/status', methods=['GET'])
    @login_required
    def api_host_status(uid):
        """Latest recorded results (from the daemon's status.json) for every
        check bound to this host — shown in the server modal's "Latest data" tab.

        Each entry: ``{module, key, name, ok, message, data, ts}``.  Derived keys
        (e.g. ram_swap ``<uid>_ram``) are matched to their base bound item.
        """
        if not wa._has_server_permission(uid, 'view'):
            return jsonify({'error': wa._t('access_denied')}), 403
        # Bound items per bare module: {bare: {item_key: label}}.
        bound: dict = {}
        for (bare, _coll), items in _checks_for_host(wa, uid).items():
            for k, item in items.items():
                bound.setdefault(bare, {})[k] = str((item or {}).get('label') or '').strip()
        # Current live state (from the check_state DB table).
        status_raw = wa._read_check_status()
        # Index the history once, grouped by bare module, for the fallback when a
        # check has no live status (e.g. the host is in maintenance, so its live
        # records were purged).
        hist_by_mod: dict = {}
        hist_store = getattr(wa, '_history', None)
        if hist_store is not None:
            try:
                for s in hist_store.get_index():
                    hist_by_mod.setdefault(s.get('module'), []).append(s)
            except Exception:  # pylint: disable=broad-except
                pass
        return jsonify({'results': hosts_svc.build_host_status(bound, status_raw, hist_by_mod)})

    @app.route('/api/v1/hosts', methods=['POST'])
    @login_required
    def api_create_host():
        """Create a host."""
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        data, err = wa._require_json()
        if err:
            return err
        if not str(data.get('name') or '').strip():
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        uid = store.create(data, actor=session.get('username', SYSTEM_USER))
        if not uid:
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        wa._audit('host_created', detail={
            'uid': uid, 'name': data.get('name'),
            'address': data.get('address', ''),
            'kind': data.get('kind', 'local'),
            'os': data.get('os', 'auto'),
            'maintenance': bool(data.get('maintenance')),
            'virtual': bool(data.get('virtual')),
            'device_type': data.get('device_type', ''),
            'profiles': sorted((data.get('profiles') or {}).keys()),
        })
        return jsonify({'ok': True, 'uid': uid})

    @app.route('/api/v1/hosts/<uid>/clone', methods=['POST'])
    @login_required
    def api_clone_host(uid):
        """Clone a host: duplicate the stored host (all profiles + secrets) under a
        NEW uid, overriding name/address from the request.  The source is read
        DECRYPTED and re-created, so inline profile secrets (ssh_password,
        ssh_key_string…) are preserved (and re-encrypted) instead of being lost as
        they would in a client-side copy of the masked data."""
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        src = store.get(uid, decrypt=True)
        if src is None:
            return jsonify({'error': wa._t('host_not_found')}), 404
        body, err = wa._require_json()
        if err:
            return err
        # Build the clone record (deep-copy + name/address override + os=auto + strip
        # per-node cluster identity). Member fields are discovered, not hardcoded.
        from lib.core.hosts.profiles import module_member_fields  # noqa: PLC0415
        data = hosts_svc.build_clone_record(
            src, body, module_member_fields(wa._modules_dir).values())
        if not data['name']:
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        new_uid = store.create(data, actor=session.get('username', SYSTEM_USER))
        if not new_uid:
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        # Duplicate the source host's module checks onto the clone.  When the
        # client sends a ``checks`` list, only those item keys are cloned (the
        # user picked them in the modal); absent → clone all.
        _sel = (body or {}).get('checks')
        only_keys = set(str(k) for k in _sel) if isinstance(_sel, list) else None
        checks_cloned = hosts_svc._clone_host_checks(wa, uid, new_uid, label=data['name'],
                                                     only_keys=only_keys)
        wa._audit('host_cloned', detail={
            'uid': new_uid, 'source_uid': uid, 'name': data['name'],
            'address': data.get('address', ''), 'checks_cloned': checks_cloned,
        })
        return jsonify({'ok': True, 'uid': new_uid, 'checks_cloned': checks_cloned})

    @app.route('/api/v1/hosts/<uid>', methods=['PUT'])
    @login_required
    def api_update_host(uid):
        """Update a host.  Masked (null/'') secrets are restored from the
        stored value so the client never has to resend them."""
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        old = store.get(uid, decrypt=True)
        if old is None:
            return jsonify({'error': wa._t('host_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        # Restore secrets the client masked out (profiles only carry secrets).
        # Done before authorization so an unchanged profile isn't seen as edited.
        if isinstance(data.get('profiles'), dict):
            secret_manager.restore_sensitive(
                data['profiles'], old.get('profiles') or {}, keys=wa._secret_keys)
        # Full edit, or — for an 'add'-only user — a change limited to registering
        # additional monitored modules (the host's ``modules`` hint list), which
        # is how adding a check to a server touches the host record.
        if not wa._has_server_permission(uid, 'edit'):
            if not (wa._has_server_permission(uid, 'add')
                    and hosts_svc._only_modules_growth(old, data)):
                return jsonify({'error': wa._t('access_denied')}), 403
        # Lo que mantiene un origen no se corrige aquí: la siguiente importación lo pisaría, y un
        # campo que se puede escribir y se revierte solo es peor que uno que no se puede. La
        # salida es desatarlo (`DELETE /<uid>/source`), no pelearse con la importación.
        #
        # **Sólo esos tres campos, y comparando VALORES y no claves.** Freshservice no sabe nada
        # de los perfiles de conexión, de los módulos ni de lo vigilado, así que todo eso se
        # sigue editando; y este cuadro manda la ficha entera en cada guardado, así que mirar si
        # la clave viene daría un dispositivo importado que no se puede tocar de ninguna manera.
        gestionado = _managed_fields(old, data)
        if gestionado:
            return jsonify({'error': wa._t('host_managed', _source_name(old.get('source')),
                                            ', '.join(gestionado))}), 409
        if not store.update(uid, data, actor=session.get('username', SYSTEM_USER)):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        # Field-level diff (secrets masked) — same convention as config/modules.
        _diffable = ('name', 'address', 'kind', 'os', 'maintenance', 'virtual',
                     'device_type', 'tags',
                     'description', 'profiles', 'modules')
        changes = wa._diff_dicts(
            {k: old.get(k) for k in _diffable},
            {k: data.get(k) for k in _diffable},
            sensitive=wa._secret_keys,
        )
        wa._audit('host_updated', detail={
            'uid': uid, 'name': data.get('name'), 'changes': changes,
        })
        return jsonify({'ok': True})

    #: Lo que Freshservice —o quien lo traiga— rescribe en cada importación. Aquí y no dentro
    #: de la ruta porque es la lista que decide qué se puede teclear en un dispositivo atado, y
    #: una lista escondida en un `if` es una que crece sin que nadie la lea.
    #: …y cómo se llama cada uno EN PANTALLA. Con su clave de idioma y no con el nombre de la
    #: columna: decirle a alguien que «description» no se puede cambiar es enseñarle el interior
    #: de la base de datos y dejarle buscando un campo que en su pantalla se llama otra cosa.
    _ORIGIN_FIELDS = (('name', 'col_host_name'), ('address', 'col_host_address'),
                      ('description', 'host_description'))

    def _source_name(source) -> str:
        """Cómo se llama ese origen en pantalla.

        Se cae al identificador tal cual cuando ya no lo declara nadie, que es lo que pasa
        cuando se quita el proveedor: sigue diciendo de dónde vino, que es más de lo que dice un
        hueco.
        """
        ident = str(source or '')
        clave = str((host_actions.sources().get(ident) or {}).get('label_key') or '')
        return wa._t(clave) if clave else ident

    def _managed_fields(old, data) -> list:
        """Los campos de un dispositivo atado que este guardado intenta CAMBIAR.

        Vacío cuando no está atado, y vacío cuando la ficha llega igual que estaba — que es lo
        normal: el cuadro manda todos los campos siempre, y quien acaba de editar un perfil de
        conexión no ha tocado el nombre.
        """
        if not str((old or {}).get('source') or ''):
            return []
        return [wa._t(etiqueta) for c, etiqueta in _ORIGIN_FIELDS
                if c in (data or {}) and str(data.get(c) or '') != str((old or {}).get(c) or '')]

    @app.route('/api/v1/hosts/<uid>/source', methods=['DELETE'])
    @login_required
    def api_host_unlink(uid):
        """Desatar un dispositivo de donde se importó: vuelve a ser de esta casa y a poder
        escribirse.

        Hace falta una salida. Sin ella, quitar el proveedor —o dejar de usarlo— deja fichas que
        nadie mantiene y que nadie puede corregir: sólo se podrían borrar, y de un dispositivo
        cuelgan sus perfiles de conexión, sus módulos y su historial. Lo que NO hace es borrar
        nada ni tocar nada más de la ficha.
        """
        if not wa._has_server_permission(uid, 'edit'):
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        row = (store.get(uid) if store is not None else None) or {}
        if not row:
            return jsonify({'error': wa._t('host_not_found')}), 404
        store.update(uid, dict(row, source='', external_id=''),
                     actor=session.get('username', SYSTEM_USER))
        wa._audit('host_unlinked', detail={'uid': uid, 'name': str(row.get('name') or ''),
                                           'was': str(row.get('source') or '')})
        return jsonify({'ok': True})

    # ── Las clases de dispositivo ────────────────────────────────────────────────────────
    #
    # **Todas son filas y todas se editan igual**, las once de la siembra incluidas: lo que
    # cambia entre una y otra no es lo que se puede hacer con ella, sino de dónde sale su
    # palabra — una sembrada lleva la clave del catálogo de idiomas y se dice en el idioma de
    # quien mira; una escrita aquí lleva su nombre tal cual, porque es un dato de esta casa y
    # ningún fichero de idiomas puede saberlo.
    #
    # `devices_edit` para escribir, porque decidir qué clases existen es decidir cómo se
    # clasifica la flota entera; leerlas basta con poder ver dispositivos, o el desplegable
    # saldría vacío para quien sólo mira.

    def _types_store():
        return getattr(wa, '_host_types_store', None)

    @app.route('/api/v1/host_types', methods=['GET'])
    @login_required
    def api_host_types():
        """Las clases y **cuántos dispositivos lleva cada una**.

        El recuento va con la lista porque es la mitad de la pregunta: «¿esta la usa alguien?» es
        lo que decide si se puede quitar, y sin él la única forma de saberlo era intentar borrarla
        y leer el error.
        """
        return jsonify({'types': host_types.catalog(wa), 'usage': host_types.usage(wa),
                        # Y lo que algún paquete ofrece hacer aquí: traerlas de donde ya están
                        # escritas. Filtradas ya, así que esta pantalla no sabe de proveedores.
                        'actions': host_actions.type_actions(wa),
                        # Y cómo se llama cada origen. La columna guarda `freshservice` y la
                        # pantalla tiene que poder enseñar un nombre: **ningún texto del core
                        # nombra a un proveedor**, así que lo declara quien las trae — el mismo
                        # registro que usa la lista de dispositivos.
                        'sources': [{'id': i, 'label_key': str(d.get('label_key') or ''),
                                     'icon': str(d.get('icon') or '')}
                                    for i, d in sorted(host_actions.sources().items())]})

    @app.route('/api/v1/host_types', methods=['POST'])
    @login_required
    def api_host_type_create():
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        data, err = wa._require_json()
        if err:
            return err
        store = _types_store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        nombre = str(data.get('name') or '').strip()
        if not nombre:
            return jsonify({'error': wa._t('host_type_name_required')}), 400
        ident = store.create(nombre, str(data.get('icon') or ''),
                             description=str(data.get('description') or ''),
                             actor=session.get('username', SYSTEM_USER))
        if not ident:
            # Una de las dos: el nombre ya está cogido —por otra añadida o por una de serie— o
            # no queda nada de él al quitarle los signos. Las dos se arreglan escribiendo otro.
            return jsonify({'error': wa._t('host_type_name_taken', nombre)}), 409
        wa._audit('host_type_created', detail={'uid': ident, 'name': nombre})
        return jsonify({'uid': ident})

    @app.route('/api/v1/host_types/<uid>', methods=['PUT'])
    @login_required
    def api_host_type_update(uid):
        """Renombrarla, describirla o cambiarle el icono, sea de la siembra o no: nada es
        intocable, que era el punto de sacar la lista del código. **Su `uid` no se toca nunca**,
        eso sí: es lo que guarda cada dispositivo de esa clase, y cambiarlo los dejaría a todos
        apuntando a una que ya no existe — sin error, y con el filtro devolviendo cero."""
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        data, err = wa._require_json()
        if err:
            return err
        store = _types_store()
        if store is None or store.get(uid) is None:
            return jsonify({'error': wa._t('host_type_not_found')}), 404
        nombre = str(data.get('name') or '').strip()
        if not nombre:
            return jsonify({'error': wa._t('host_type_name_required')}), 400
        # Lo que mantiene un origen es el **nombre**, y sólo él: la siguiente importación lo
        # pisaría, y un campo que se puede escribir y se revierte solo es peor que uno que no se
        # puede. La salida es desvincularla (`DELETE /<uid>/link`).
        #
        # **El icono no.** Allí no existe —Freshservice no tiene iconos—, así que el dibujo con
        # el que se distingue una clase entre cuarenta filas es un dato de esta casa. Negarse a
        # guardarlo era negarse por algo que el origen nunca va a tocar; la importación ya lo
        # respetaba, que es lo que hacía la negativa doblemente falsa.
        fila = store.get(uid) or {}
        vinculada = bool(str(fila.get('source') or '') and str(fila.get('external_id') or ''))
        if vinculada and nombre != str(fila.get('name') or ''):
            return jsonify({'error': wa._t('host_type_managed',
                                            _source_name(fila.get('source')))}), 409
        if not store.update(uid, nombre, str(data.get('icon') or ''),
                            # La descripción es de esta casa aunque el nombre no lo sea: el
                            # origen no la trae, así que es lo único que se puede escribir sobre
                            # una clase que mantiene un proveedor. Y que NO venga es «déjala
                            # como está», que no es lo mismo que venir vacía: un cliente que
                            # manda sólo el icono no borra lo que escribió alguien.
                            description=(str(data.get('description') or '')
                                         if 'description' in data else None),
                            # Renombrar una clase sembrada le quita la clave de idioma: desde ese
                            # momento se lee lo que alguien escribió. Cambiarle sólo el icono no
                            # es renombrarla, y perderla ahí dejaría «Servidor» en inglés por
                            # haber elegido otro dibujo.
                            keep_label=(nombre == str(fila.get('name') or '')),
                            actor=session.get('username', SYSTEM_USER)):
            return jsonify({'error': wa._t('host_type_name_taken', nombre)}), 409
        wa._audit('host_type_updated', detail={'uid': uid, 'name': nombre})
        return jsonify({'ok': True})

    @app.route('/api/v1/host_types/<uid>', methods=['DELETE'])
    @login_required
    def api_host_type_delete(uid):
        """Quitar una clase **que no lleve puesta nadie**.

        Borrar una que llevan cuarenta máquinas las deja con una palabra que ya no significa
        nada: no se traduce, no se filtra y no dibuja su icono. Y no se arregla volviendo a
        crearla con el mismo nombre, porque lo que se perdió fue saber que había que hacerlo.
        """
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _types_store()
        fila = store.get(uid) if store is not None else None
        if fila is None:
            return jsonify({'error': wa._t('host_type_not_found')}), 404
        usados = host_types.in_use(wa, uid)
        if usados:
            return jsonify({'error': wa._t('host_type_in_use', fila['name'],
                                            str(usados))}), 409
        store.delete(uid)
        wa._audit('host_type_deleted', detail={'uid': uid, 'name': fila['name']})
        return jsonify({'ok': True})

    @app.route('/api/v1/host_types/seed', methods=['POST'])
    @login_required
    def api_host_types_seed():
        """Volver a poner las básicas que falten.

        Existe porque la siembra sólo ocurre el día que se crea la tabla: quien borre «Cámara»
        porque en su casa no hay ninguna no se la encuentra de vuelta en el siguiente arranque, y
        quien se pase borrando necesita una manera de deshacerlo que no sea teclear once nombres.

        Lo que YA está no se toca — ni el nombre, ni el icono: alguien lo habrá corregido, y un
        botón que pisa lo corregido es uno que deshace trabajo cada vez que se pulsa.
        """
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _types_store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        puestas = store.seed_missing(actor=session.get('username', SYSTEM_USER))
        if puestas:
            wa._audit('host_type_created', detail={'seeded': puestas})
        return jsonify({'added': puestas})

    @app.route('/api/v1/host_types/<uid>/link', methods=['POST'])
    @login_required
    def api_host_type_link(uid):
        """Vincular una clase de aquí con una de un proveedor.

        Es lo que evita el duplicado: una clase escrita a mano que se llama distinto que la de
        allí se crearía otra vez en la primera importación. Vinculándolas, la importación la
        reconoce — y desde ese momento su nombre lo mantiene el origen, que es lo que hace que
        esta pantalla la enseñe en sólo lectura.

        No se comprueba que esa de fuera exista: quién sabe qué clases tiene un proveedor es el
        proveedor, y el core no puede preguntárselo sin nombrarlo. Lo que sí se comprueba es que
        no esté ya vinculada con otra de aquí — dos clases locales sobre la misma de fuera es un
        reparto de la flota en dos montones que nadie decidió.
        """
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        data, err = wa._require_json()
        if err:
            return err
        store = _types_store()
        if store is None or store.get(uid) is None:
            return jsonify({'error': wa._t('host_type_not_found')}), 404
        source = str(data.get('source') or '').strip()
        external_id = str(data.get('external_id') or '').strip()
        if not source or not external_id:
            return jsonify({'error': wa._t('host_type_link_required')}), 400
        if not store.link(uid, source, external_id,
                          actor=session.get('username', SYSTEM_USER)):
            otra = store.by_external(source, external_id) or {}
            return jsonify({'error': wa._t('host_type_link_taken',
                                            otra.get('name') or '')}), 409
        wa._audit('host_type_updated', detail={'uid': uid, 'linked': source,
                                               'external_id': external_id})
        return jsonify({'ok': True})

    @app.route('/api/v1/host_types/<uid>/link', methods=['DELETE'])
    @login_required
    def api_host_type_unlink(uid):
        """Desvincularla: vuelve a ser de esta casa y a poder escribirse.

        Hace falta una salida. Sin ella, quitar el proveedor —o dejar de usarlo— deja clases que
        nadie mantiene y que nadie puede corregir. Lo que NO hace es borrar nada: ni la clase, ni
        los dispositivos que la llevan puesta.
        """
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _types_store()
        fila = store.get(uid) if store is not None else None
        if fila is None:
            return jsonify({'error': wa._t('host_type_not_found')}), 404
        store.link(uid, '', '', actor=session.get('username', SYSTEM_USER))
        wa._audit('host_type_updated', detail={'uid': uid,
                                               'unlinked': fila.get('source') or ''})
        return jsonify({'ok': True})

    @app.route('/api/v1/hosts/<uid>', methods=['DELETE'])
    @login_required
    def api_delete_host(uid):
        """Delete a host."""
        if not wa._has_server_permission(uid, 'delete'):
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('host_not_found')}), 404
        old = store.get(uid, decrypt=False)
        if old is None or not store.delete(uid):
            return jsonify({'error': wa._t('host_not_found')}), 404
        # Optionally also delete the module checks bound to this host (the client
        # asks the user). Otherwise they are left (and read as inline).
        checks_deleted = 0
        if str(request.args.get('with_checks') or '').lower() in ('1', 'true', 'yes'):
            checks_deleted = hosts_svc._delete_host_checks(wa, uid)
        wa._audit('host_deleted', detail={
            'uid': uid, 'name': old.get('name', ''), 'address': old.get('address', ''),
            'checks_deleted': checks_deleted,
        })
        # The roles that scoped a permission to THIS host keep a key naming something that
        # no longer exists — dead weight nobody can see, and counted as a grant.
        wa._purge_scoped_permissions('server', [uid])
        return jsonify({'ok': True, 'checks_deleted': checks_deleted})

    # ── test / probe endpoints (run a check once without saving) ─────────────────

    def _can_edit_body_host():
        """Edit gate for the test endpoints — allow the global ``devices_edit``
        or a per-server ``server.{uid}.edit`` when the body targets an existing
        host (a new draft has no uid, so it needs the global permission)."""
        uid = str((request.get_json(silent=True) or {}).get('uid') or '').strip()
        return wa._has_server_permission(uid, 'edit')

    @app.route('/api/v1/hosts/test_ssh', methods=['POST'])
    @login_required
    def api_test_host_ssh():
        """Probe the SSH connection for a (remote) host without saving it.

        Body: ``{address, profiles:{ssh:{...}}, uid?}``.  When a secret field is
        masked (null/'') and ``uid`` is given, it is restored from the stored
        host so the user need not re-enter the password/key to test.

        SECURITY (accepted risk, 2026-07): a ``devices_edit`` holder can point the test at
        an arbitrary ``address`` using a referenced ``cred_uid`` whose secret they cannot
        see — so in theory a stored SSH secret could be exfiltrated to an attacker-controlled
        host (or used for SSRF).  Binding the address to a registered host would break the
        legitimate "test a shared credential against a new host before saving" flow (editors
        hold ``devices_edit`` but not ``credentials_*``), so the risk is accepted for this
        semi-trusted role; every attempt is audited below (``host_ssh_tested`` with uid +
        address).  See memory ``project_bug_audit_2026_07``.
        """
        if not _can_edit_body_host():
            return jsonify({'error': wa._t('access_denied')}), 403
        if not ssh_client.HAS_PARAMIKO:
            return jsonify({'ok': False,
                            'message': wa._t('paramiko_missing')})
        data, err = wa._require_json()
        if err:
            return err
        ssh = dict((data.get('profiles') or {}).get('ssh') or {})
        uid = str(data.get('uid') or '').strip()
        cred_uid = str(ssh.get('cred_uid') or '').strip()
        if cred_uid:
            # A reusable credential supplies the identity: drop any inline
            # user/auth/secret (so a stale value can't win) and overlay the
            # credential — exactly what resolve_host does at runtime.  The
            # stored host's inline secret must NOT be restored here, or a wrong
            # credential would be tested with the host's old correct password.
            from lib.core.credentials.store import apply_credential, SSH_CRED_FIELDS  # noqa: PLC0415
            cstore = getattr(wa, '_credentials_store', None)
            cred = cstore.get(cred_uid) if cstore is not None else None
            ssh = apply_credential({k: v for k, v in ssh.items() if k not in SSH_CRED_FIELDS}, cred)
        else:
            # Inline edit flow: restore masked secrets from the stored host so
            # the user need not re-type the password/key just to test.
            store = _store()
            if store is not None and uid:
                stored = store.get(uid, decrypt=True) or {}
                stored_ssh = (stored.get('profiles') or {}).get('ssh') or {}
                for k in ('ssh_password', 'ssh_key_string'):
                    if ssh.get(k) in (None, '') and stored_ssh.get(k):
                        ssh[k] = stored_ssh[k]
        ok, msg, os_found = ssh_client.test_connection(
            address=data.get('address', ''),
            port=ssh.get('ssh_port') or 22,
            user=ssh.get('ssh_user', ''),
            password=ssh.get('ssh_password', ''),
            key_path=ssh.get('ssh_key', ''),
            key_string=ssh.get('ssh_key_string', ''),
            verify_host=bool(ssh.get('ssh_verify_host', False)),
            detect=True,
        )
        wa._audit('host_ssh_tested', detail={
            'uid': uid, 'address': data.get('address', ''), 'ok': ok, 'os': os_found,
        })
        return jsonify({'ok': ok, 'message': msg, 'os': os_found})

    def _item_name(items, key):
        """Friendly label for a result key: the item's ``label``, falling back to
        the base item for derived keys (e.g. ram_swap ``<uid>_ram``)."""
        for cand in (key, key.rsplit('_', 1)[0]):
            it = items.get(cand)
            if isinstance(it, dict) and str(it.get('label') or '').strip():
                return str(it['label']).strip()
        return ''

    def _run_checks(record, grouped):
        """Run each grouped check once on the host; return a flat result list."""
        store = host_probe.ProbeHostsStore(record, _store())
        db = getattr(wa, '_db_connector', None)
        # Global config → the probe resolves check messages in the configured
        # notification language (with admin text overrides) instead of raw i18n keys.
        notify_cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        # Saved module-level settings (e.g. ssl_cert warning_days, timeout) so the
        # module's get_conf() resolves them in the probe — an item that inherits a
        # module-level value (blank/0) would otherwise fall back to the hardcoded
        # default instead of the configured value.
        saved_mods = wa._load_modules() or {}
        out = []
        for (bare, coll), items in grouped.items():
            _mod_scalars = {k: v for k, v in (saved_mods.get(bare) or {}).items()
                            if not k.startswith('__') and not isinstance(v, dict)}
            cfg = {f'watchfuls.{bare}': {**_mod_scalars, coll: items}}
            try:
                results = check_runner.run_module_check(
                    bare, cfg, hosts_store=store, db=db, modules_dir=wa._modules_dir,
                    notify_cfg=notify_cfg)
            except Exception as exc:  # pylint: disable=broad-except
                out.append({'module': bare, 'key': '', 'name': '', 'ok': False,
                            'message': str(exc)})
                continue
            for r in results:
                out.append({'module': bare, 'key': r['key'],
                            'name': _item_name(items, r['key']),
                            'ok': r['status'], 'message': r['message']})
        return out

    def _ssh_test(record):
        ssh = (record.get('profiles') or {}).get('ssh') or {}
        if not ssh_client.HAS_PARAMIKO:
            return {'ok': False, 'message': wa._t('paramiko_missing')}
        ok, msg, _os = ssh_client.test_connection(
            address=record.get('address', ''), port=ssh.get('ssh_port') or 22,
            user=ssh.get('ssh_user', ''), password=ssh.get('ssh_password', ''),
            key_path=ssh.get('ssh_key', ''), key_string=ssh.get('ssh_key_string', ''),
            verify_host=bool(ssh.get('ssh_verify_host', False)), detect=True)
        return {'ok': ok, 'message': msg}

    @app.route('/api/v1/hosts/test_check', methods=['POST'])
    @login_required
    def api_test_host_check():
        """Run ONE check once on the host and return its result(s)."""
        if not _can_edit_body_host():
            return jsonify({'error': wa._t('access_denied')}), 403
        body, err = wa._require_json()
        if err:
            return err
        module = _bare(str(body.get('module') or ''))
        if not _MOD_RE.match(module):
            return jsonify({'ok': False, 'message': wa._t('invalid_module_name')}), 400
        coll = str(body.get('collection') or 'list')
        key = str(body.get('key') or 'check')
        record = _probe_host_record(wa, body)
        fields = dict(body.get('fields') or {})
        # The modal sends cred_uid at the body level (the check's binding lives
        # outside its fields); fold it in so the credential is actually applied.
        if body.get('cred_uid') and not fields.get('cred_uid'):
            fields['cred_uid'] = body.get('cred_uid')
        _restore_check_secrets(wa, module, coll, key, fields)
        fields = _apply_check_cred(wa, fields)
        item = {**fields, 'host_uid': record['uid'], 'enabled': True}
        results = _run_checks(record, {(module, coll): {key: item}})
        ok = bool(results) and all(r['ok'] for r in results)
        wa._audit('host_test_check', detail={
            'uid': record['uid'], 'name': record.get('name', ''),
            'module': module, 'key': key, 'ok': ok,
            'results': [{'key': r['key'], 'ok': r['ok'], 'message': r['message']}
                        for r in results],
        })
        return jsonify({'ok': ok, 'results': results})

    @app.route('/api/v1/hosts/test', methods=['POST'])
    @login_required
    def api_test_host():
        """Full host test: SSH connection (if remote) + every bound check once."""
        if not _can_edit_body_host():
            return jsonify({'error': wa._t('access_denied')}), 403
        body, err = wa._require_json()
        if err:
            return err
        record = _probe_host_record(wa, body)
        out = {'ssh': None, 'results': []}
        # A module-scoped test (no_ssh) skips the SSH connection check.
        if str(record.get('kind') or '').lower() == 'remote' and not body.get('no_ssh'):
            out['ssh'] = _ssh_test(record)

        # Checks: explicit list from the modal, else everything bound in the module configuration.
        grouped = {}
        checks = body.get('checks')
        if isinstance(checks, list):
            for c in checks:
                bare = _bare(str(c.get('module') or ''))
                if not _MOD_RE.match(bare):
                    continue
                coll = str(c.get('collection') or 'list')
                key = str(c.get('key') or '') or f'check{len(grouped)}'
                fields = dict(c.get('fields') or {})
                if c.get('cred_uid') and not fields.get('cred_uid'):
                    fields['cred_uid'] = c.get('cred_uid')
                _restore_check_secrets(wa, bare, coll, key, fields)
                fields = _apply_check_cred(wa, fields)
                grouped.setdefault((bare, coll), {})[key] = {
                    **fields, 'host_uid': record['uid'], 'enabled': True}
        else:
            grouped = _checks_for_host(wa, record['uid'])
            for _items in grouped.values():
                for _k in list(_items):
                    _items[_k] = _apply_check_cred(wa, _items[_k])

        out['results'] = _run_checks(record, grouped)
        out['ok'] = ((out['ssh'] is None or out['ssh']['ok'])
                     and all(r['ok'] for r in out['results']))
        passed = sum(1 for r in out['results'] if r['ok'])
        failed = [r for r in out['results'] if not r['ok']]
        wa._audit('host_tested', detail={
            'uid': record['uid'], 'name': record.get('name', ''),
            'ok': out['ok'],
            'ssh': (out['ssh'] or {}).get('ok'),
            'total': len(out['results']), 'passed': passed, 'failed': len(failed),
            # Per-check outcome so the audit shows exactly which check failed.
            'results': [{'module': r['module'], 'key': r['key'], 'ok': r['ok'],
                         'message': r['message']} for r in out['results']],
        })
        return jsonify(out)

    # ── assisted migration (inline connections → shared hosts) ───────────────────

    @app.route('/api/v1/hosts/migrate/preview', methods=['GET'])
    @login_required
    def api_migrate_preview():
        """Return the migration proposal (candidate hosts; secrets masked)."""
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        modules = wa._load_modules()
        plan = build_migration_plan(modules, wa._modules_dir)
        return jsonify(secret_manager.mask_sensitive(plan, wa._secret_keys))

    @app.route('/api/v1/hosts/migrate/apply', methods=['POST'])
    @login_required
    def api_migrate_apply():
        """Create hosts for the accepted candidates and rewrite the checks.

        Body: ``{"accept": [{"id": <candidate id>, "name": <optional>}]}``.
        The plan is rebuilt server-side from the (decrypted) module configuration, so the
        client never supplies credentials — only which candidates to accept.
        """
        if 'devices_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        body, err = wa._require_json()
        if err:
            return err
        accept = body.get('accept') or []
        modules = wa._load_modules()
        plan = build_migration_plan(modules, wa._modules_dir)
        by_id = {c['id']: c for c in plan['candidates']}
        actor = session.get('username', SYSTEM_USER)

        applied, created = [], []
        for acc in accept:
            cand = by_id.get(acc.get('id'))
            if not cand:
                continue
            uid = _create_unique_host(store, acc.get('name'), cand, actor)
            if not uid:
                continue
            applied.append({'uid': uid, 'members': cand['members']})
            created.append({
                'uid': uid,
                'name': (acc.get('name') or cand.get('suggested_name') or '').strip(),
                'address': cand.get('address', ''),
                'members': len(cand['members']),
                'checks': [f"{m['module'].split('.')[-1]}/{m['key']}" for m in cand['members']],
            })

        if applied:
            apply_to_modules(modules, applied, wa._modules_dir)
            if not wa._save_modules(modules):
                return jsonify({'error': wa._t('save_file_error')}), 500
            wa._audit('hosts_migrated', detail={
                'hosts': len(created),
                'checks': sum(c['members'] for c in created),
                'created': [{k: c[k] for k in ('uid', 'name', 'address', 'checks')}
                            for c in created],
            })
        return jsonify({'ok': True, 'created': len(created),
                        'checks': sum(c['members'] for c in created)})
