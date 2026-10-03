#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config routes: /api/v1/config (GET, PUT) with per-field version tracking, plus the
read-only UI-metadata endpoints /api/v1/config/layout and /api/v1/config/schema.

All non-HTTP logic lives in the Flask-free :mod:`lib.core.config.service` — save planning
(format/versions/merge), locked-field enforcement, validation, and the frontend UI-schema
assembly.  This module owns only the HTTP surface: request parsing, the requester-context
guards (admin-only / ipban), persistence, the runtime side-effects (``setattr`` on ``wa``,
ProxyFix, service pokes) and audit.

Routes registered by this file:

    GET    /api/v1/config               effective config + per-field versions
    GET    /api/v1/config/versions      per-field version tokens only (poll)
    GET    /api/v1/config/layout        config UI layout (sub-tabs -> cards)
    GET    /api/v1/config/schema        field-level UI metadata (min/max/opts)
    PUT    /api/v1/config               partial versioned save of edited fields
    GET    /api/v1/config/db/targets/<op>  what a run will walk (tables, or nothing when
                                        the engine cannot split the operation)
    POST   /api/v1/config/db/<op>       database maintenance: optimize | compact
    GET    /api/v1/config/db/orphans    readings stored under a key nothing owns any more
    DELETE /api/v1/config/db/orphans    …and the sweep that removes them
    GET    /api/v1/config/map/preview/<int:z>/<int:x>/<int:y>   una tesela del mapa
                                     que se está probando, servida por el panel (la
                                     política de contenido sólo abre el GUARDADO)
    POST   /api/v1/config/map/test     probar el mapa: proveedor, sesión, una tesela y el
                                     origen que la política de contenido abre
"""

import uuid

import time

from flask import jsonify, request, session

from lib.debug import DebugLevel
from lib.config.spec import CFG_BY_PATH, admin_only_fields
from lib.config.layout import config_layout
from lib.core.config import service as config_svc
from lib.core.config import orphans
from lib.core.config.service import AdminOpError
from lib.security import secret_manager
from lib.util import fmt_bytes


def register(app, wa):
    # Per-field version tokens: {path_str: uuid} updated each time a field is saved.
    if not hasattr(wa, '_field_versions'):
        wa._field_versions = {}
    if not hasattr(wa, '_CONFIG_POLL_SECS'):
        wa._CONFIG_POLL_SECS = CFG_BY_PATH['web_admin|config_poll_secs'].default
    if not hasattr(wa, '_CONFIG_UPDATE_BANNER_SECS'):
        wa._CONFIG_UPDATE_BANNER_SECS = CFG_BY_PATH['web_admin|config_update_banner_secs'].default

    config_view_req = wa._perm_required('config_view', 'config_edit')
    config_edit_req = wa._perm_required('config_edit')

    #: Con qué plantilla dibuja el mapa de prueba de cada persona, y hasta cuándo vale. En
    #: memoria y por usuario: es lo que acaba de teclear ESA persona en un formulario sin
    #: guardar, no un ajuste de la casa. Se caduca sola porque nadie va a venir a borrarla.
    if not hasattr(wa, '_map_preview'):
        wa._map_preview = {}

    #: Cuánto vale. Lo que dura mirar un cuadro de diagnóstico y volver a pulsar un par de veces.
    _PREVIEW_TTL = 600

    def _map_needs_reload(antes: dict, ahora: dict) -> bool:
        """Si el mapa recién guardado NO cabe en la política que lleva la página abierta.

        De dónde puede el navegador traerse imágenes se decide al abrir la página, y viaja en su
        cabecera: la que está delante de quien guarda se sirvió con la configuración de ANTES.
        Si el origen que hace falta ahora ya estaba en aquella lista, no hay nada que hacer —y
        ese es el caso corriente desde que una instalación con mapa abre todos los del catálogo,
        así que cambiar de proveedor ya no pide nada—. Si no estaba, el navegador va a bloquear
        cada tesela **sin decir una palabra**, y entonces sí hay que pedir la página otra vez.

        Los dos casos que quedan: encender el mapa por primera vez —antes no había ningún
        origen abierto— y escribir una plantilla propia que apunta a un servidor nuevo.
        """
        from lib.maps import catalog as cat                           # noqa: PLC0415
        abiertos = cat.origins_for((antes or {}).get('web_admin') or {})
        hace_falta = cat.origin_of(cat.resolve((ahora or {}).get('web_admin') or {})['tiles'])
        return bool(hace_falta) and hace_falta not in abiertos

    @app.route('/api/v1/config/map/preview/<int:z>/<int:x>/<int:y>', methods=['GET'])
    @config_edit_req
    def api_config_map_preview(z, x, y):
        """Una tesela del mapa que se está probando, **servida por el panel**.

        Y no directamente desde el proveedor, que es lo que hace un mapa de verdad. La razón es
        la política de contenido: `img-src` se abre para el origen que sale de la configuración
        **guardada**, así que un proveedor recién elegido en el formulario tiene su origen
        cerrado — el navegador bloquea cada tesela sin decir una palabra y sólo queda la
        chincheta sobre un rectángulo vacío. Que es exactamente lo que se veía, y lo que hacía
        falta guardar y recargar para que dejara de pasar.

        Aquí no hay que abrir nada: las imágenes vienen del propio panel.

        **No es un proxy abierto.** La dirección no viene en la petición: viene de lo que esta
        misma persona acaba de probar, guardado en memoria y con caducidad, y sólo llegan aquí
        quienes pueden editar la configuración — que son los que ya podían apuntar el mapa a
        donde quisieran. Lo único que se puede pedir es la tesela z/x/y de ESE mapa.
        """
        guardado = (wa._map_preview or {}).get(session.get('username', '') or '')
        if not guardado or guardado[1] < time.time():
            return jsonify({'error': wa._t('map_err_off')}), 404
        from lib import maps                                          # noqa: PLC0415
        datos, tipo = maps.fetch_tile(guardado[0], z, x, y)
        if not datos:
            # 404 y no 500: no hay tesela ahí. Lo que ha fallado ya lo cuenta el informe, y un
            # error de servidor por una imagen que no está llenaría el registro de ruido.
            return jsonify({'error': wa._t('map_err_tile')}), 404
        return app.response_class(datos, mimetype=tipo or 'image/png',
                                  # Un cuadro de diagnóstico no quiere una imagen de hace un
                                  # rato: se pulsa precisamente porque algo ha cambiado.
                                  headers={'Cache-Control': 'no-store'})

    @app.route('/api/v1/config/map/test', methods=['POST'])
    @config_edit_req
    def api_config_map_test():
        """Probar el mapa: **pedir una tesela de verdad** y contar qué pasó.

        Un mapa que no sale no dice nada por su cuenta: el navegador se traga una imagen que no
        carga, la política de contenido bloquea en silencio y una clave sin permiso contesta un
        403 que nadie ve. Todo el rato es el mismo cuadro vacío, y no hay por dónde empezar.

        Así que esto recorre la cadena entera y devuelve **cada paso por separado**:

        1. qué proveedor sale de la configuración y con qué dirección;
        2. para Google, si dan una sesión — y si no, **lo que contestaron ellos**, que es donde
           está la respuesta (una clave sin la Map Tiles API activada, un proyecto sin
           facturación, una restricción por referente que a una llamada de servidor le falta);
        3. si desde ESTE servidor se puede traer una tesela, que separa «no hay salida a
           internet» de «la clave no vale»;
        4. y qué origen tiene que abrir la política de contenido, que es la mitad que falla sin
           dejar rastro en la página.

        La sesión se pide NUEVA a propósito: probar contra la que está guardada contestaría que
        todo va bien con una clave que se acaba de cambiar.
        """
        from lib import maps                                          # noqa: PLC0415
        from lib.maps import catalog as cat                           # noqa: PLC0415
        from lib.maps import google as gmaps                          # noqa: PLC0415
        # Lo que hay EN PANTALLA, no lo que está guardado. Un botón de probar que sólo mira lo
        # guardado contesta siempre lo mismo mientras alguien cambia de proveedor y vuelve a
        # pulsar — y lo que se quiere saber antes de guardar es precisamente si lo nuevo va a
        # funcionar. Reportado desde la pantalla.
        #
        # Lo posteado manda SALVO donde no venga: la clave sale enmascarada a la pantalla, así
        # que si nadie la ha tocado no viaja de vuelta, y ahí lo que vale es la guardada. Es la
        # misma regla que hace que guardar la configuración no borre un secreto que no se editó.
        cfg = dict(wa._config_section('web_admin') or {})
        dado = (request.get_json(silent=True) or {}).get('web_admin') or {}
        for campo in ('dcim_map_provider', 'dcim_map_tiles', 'dcim_map_attribution',
                      'dcim_map_google_key', 'dcim_map_google_type', 'dcim_map_max_zoom'):
            if isinstance(dado.get(campo), (str, int)) and dado.get(campo) != '':
                cfg[campo] = dado[campo]
            elif dado.get(campo) == '' and campo != 'dcim_map_google_key':
                # Vaciar una casilla es una decisión: «sin plantilla propia», «sin tope». La
                # clave es la excepción, porque vacía es como llega cuando no se ha tocado.
                cfg[campo] = ''
        elegido = cat.resolve(cfg)
        # Lo que hay guardado, que puede no ser lo que se está probando: los mapas de las
        # demás pantallas siguen con ese hasta que alguien guarde, y su política de contenido
        # hasta que además recargue. Decirlo evita el «pues aquí funciona y allí no».
        guardado_cfg = cat.resolve(wa._config_section('web_admin') or {})
        out = {'provider': elegido['provider'], 'zmax': elegido.get('zmax') or 0,
               'saved_provider': guardado_cfg['provider'], 'preview': '',
               # Cómo se llama cada uno, dicho por el catálogo. Componer la clave con el
               # identificador ya salió a la pantalla: el del IGN se llama `ign_pnoa` y su
               # rótulo es `…_ign`, así que se leyó la clave en crudo dentro de una frase.
               'saved_label_key': cat.label_key(guardado_cfg['provider']),
               'label_key': cat.label_key(elegido['provider']),
               'attribution': elegido.get('attribution') or '',
               'origin': cat.origin_of(elegido['tiles']), 'session': False,
               # La dirección LISTA —con la sesión y la clave de Google ya puestas—, para que el
               # cuadro pueda dibujar un trozo de mapa de verdad. Es la mitad que este servidor
               # no puede comprobar: él se trae la tesela por su cuenta, y quien tiene que poder
               # traerla es el navegador. Si el informe dice que llegó y el dibujo sale en
               # blanco, es la política de contenido — y así se ve de un vistazo en vez de
               # deducirse.
               'tiles': '', 'tile': {}, 'error': '', 'detail': ''}
        if not elegido['provider']:
            out['error'] = 'map_err_off'
            return jsonify(out)
        url = elegido['tiles']
        if elegido['provider'] == cat.GOOGLE:
            gmaps.forget()          # la de ahora, no la de antes de cambiar la clave
            lang, region = gmaps.lang_of(getattr(wa, '_DEFAULT_LANG', '') or '')
            try:
                url = gmaps.tiles(url, str(cfg.get('dcim_map_google_key') or ''),
                                  lang=lang, region=region,
                                  map_type=str(cfg.get('dcim_map_google_type') or ''))
                out['session'] = True
            except gmaps.MapKeyError as exc:
                out['error'], out['detail'] = exc.key, exc.detail
                return jsonify(out)
            except Exception as exc:                 # pylint: disable=broad-except
                out['error'], out['detail'] = 'gmaps_err_session', str(exc)
                return jsonify(out)
        if not url:
            out['error'] = 'map_err_no_tiles'
            return jsonify(out)
        out['tiles'] = url
        # Con qué dibuja el cuadro: por el panel, no directo. Ver `api_config_map_preview`.
        wa._map_preview[session.get('username', '') or ''] = (url, time.time() + _PREVIEW_TTL)
        # Con una marca distinta en cada prueba. **La dirección del cuadro es la misma para
        # todos los proveedores** —la sirve el panel—, así que sin esto la tesela z/x/y que el
        # navegador ya se trajo probando el satélite del IGN se reutiliza al probar
        # OpenStreetMap: sale un mapa a trozos, mitad callejero y mitad foto aérea, según cuáles
        # estuvieran ya en la caché. Reportado desde la pantalla, y no lo arregla `no-store`:
        # con la misma URL, un `<image>` puede salir de la caché de memoria de la propia página.
        out['preview'] = (f'/api/v1/config/map/preview/{{z}}/{{x}}/{{y}}'
                          f'?v={int(time.time() * 1000)}')
        out['tile'] = maps.probe_tile(url)
        if not out['tile'].get('ok'):
            out['error'] = 'map_err_tile'
            out['detail'] = str(out['tile'].get('detail') or '')
        return jsonify(out)


    # Sections that contain external-service credentials (LDAP bind password,
    # OIDC client secret, SMTP password, etc.).  Only admins may modify them.
    _ADMIN_ONLY_SECTIONS = frozenset({'ldap', 'oidc', 'saml2', 'email', 'telegram', 'msteams'})

    # Individual security-relevant web_admin fields that, like the sensitive
    # sections above, must be admin-only — they govern account lockout, cookie
    # security, password policy, trusted-proxy handling and public exposure.
    # A non-admin with config_edit must not be able to weaken these.
    # Derived from the central registry (fields flagged admin_only=True).
    _ADMIN_ONLY_FIELDS = frozenset(admin_only_fields())

    # --- API: config.json -----------------------------------------

    @app.route('/api/v1/config', methods=['GET'])
    @config_view_req
    def api_get_config():
        """Return the effective config and per-field version tokens."""
        raw = wa._read_config_file(wa._CONFIG_FILE) or {}
        # Overlay env var values so the UI always shows what is actually in effect.
        for path, value in wa._env_override_values.items():
            section, field = path.split('|')
            raw.setdefault(section, {})[field] = value
        # Webhooks live in their own store; bundle the list (read-only) so the
        # Notifications tab can render it.  Editing still goes through /api/v1/notify/webhooks.
        from lib.core.notify.webhook import channel as _wh_channel  # noqa: PLC0415
        from lib.core.notify.msteams import channel as _ms_channel  # noqa: PLC0415
        raw['webhooks'] = _wh_channel.load(wa._notify)
        # Teams channel destinations live in their own store too — bundle read-only.
        raw['msteams_channels'] = _ms_channel.load(wa._notify)
        resp = jsonify({
            'config': secret_manager.mask_sensitive(raw, wa._secret_keys),
            'versions': dict(wa._field_versions),
        })
        resp.headers['ETag'] = f'"{wa._config_version}"'
        return resp

    @app.route('/api/v1/config/versions', methods=['GET'])
    @config_view_req
    def api_get_config_versions():
        """Lightweight poll endpoint — returns only per-field version tokens."""
        return jsonify({'versions': dict(wa._field_versions)})

    # --- API: read-only UI metadata (layout + field schema) -------

    @app.route('/api/v1/config/layout', methods=['GET'])
    @config_view_req
    def api_get_config_layout():
        """The config UI layout (sub-tabs → cards) from the central registry
        (``lib.config.layout``) — so the web admin renders the config screen from
        this single source of truth instead of hardcoding the structure."""
        return jsonify(config_layout())

    @app.route('/api/v1/config/schema', methods=['GET'])
    @config_view_req
    def api_get_config_schema():
        """Field-level UI metadata (min, max, default, option lists, …) — assembled by
        the Flask-free :func:`config_svc.build_config_schema` from the central registry."""
        return jsonify(config_svc.build_config_schema())

    @app.route('/api/v1/config', methods=['PUT'])
    @config_edit_req
    def api_save_config():
        """Partial versioned save: only write fields that were actually edited.

        Request body: ``{"fields": {"section|field": {"value": ..., "version": "uuid"}}}``

        Each field is checked against its stored version token. If the token
        matches (or the field has no stored version yet), the field is saved.
        Mismatches are returned as conflicts with the server's current value.

        Also accepts the legacy flat format ``{"section": {"field": value}}``
        for backwards compatibility with older API clients.
        """
        data, err = wa._require_json()
        if err:
            return err

        # Sensitive-section / sensitive-field guard: only admins may modify
        # external-service credentials or security-relevant web_admin fields.
        _incoming_sections, _incoming_fields = config_svc.incoming_paths(data)
        _touches_admin_only = (
            bool(_incoming_sections & _ADMIN_ONLY_SECTIONS)
            or bool(_incoming_fields & _ADMIN_ONLY_FIELDS)
        )
        wa._dbg(f"> Config PUT >> received {len(_incoming_fields)} field(s) in "
                f"{sorted(_incoming_sections)}; admin_only={_touches_admin_only}", DebugLevel.debug)
        if _touches_admin_only and not wa._is_admin_requester():
            wa._dbg("> Config PUT >> rejected: non-admin touched admin-only field", DebugLevel.warning)
            return jsonify({'error': wa._t('insufficient_permissions')}), 403

        # fail2ban settings (web_admin|ipban_*) are security-sensitive: editing them
        # needs the dedicated ipban_config_edit permission on top of config access.
        if (any(f.startswith('web_admin|ipban_') for f in _incoming_fields)
                and not wa._is_admin_requester()
                and 'ipban_config_edit' not in wa._get_session_permissions()):
            wa._dbg("> Config PUT >> rejected: no ipban_config_edit for fail2ban settings",
                    DebugLevel.warning)
            return jsonify({'error': wa._t('insufficient_permissions')}), 403

        old_data = wa._read_config_file(wa._CONFIG_FILE) or {}

        # Flatten to {path: value}, resolving per-field version conflicts.
        to_apply, conflicts, legacy_mode = config_svc.plan_save(
            data, wa._field_versions, old_data)
        wa._dbg(f"> Config PUT >> mode={'legacy' if legacy_mode else 'versioned'}; "
                f"{len(to_apply)} to apply, {len(conflicts)} conflict(s)"
                + (f" {sorted(conflicts)}" if conflicts else ""), DebugLevel.debug)
        if not legacy_mode and not to_apply:
            # All fields conflicted — nothing to write.
            wa._dbg("> Config PUT >> all fields conflicted; nothing written", DebugLevel.warning)
            return jsonify({'ok': False, 'saved': [], 'conflicts': conflicts, 'versions': {}})

        # Build merged config: current saved + fields to apply.
        new_data = config_svc.merge_config(old_data, to_apply)
        wa._dbg(f"> Config PUT >> merged config: applying {sorted(to_apply.keys())}", DebugLevel.debug)

        # Locked fields must not be persisted — restore original effective values.
        # Env vars and ``config.json`` overrides are both read-only layers.
        _locked = set(wa._env_locked) | set(getattr(wa, '_file_locked', frozenset()))
        config_svc.enforce_locked(new_data, old_data, _locked)
        if _locked:
            wa._dbg(f"> Config PUT >> locked enforced (env+file): {sorted(_locked)}", DebugLevel.debug)

        wa._dbg("> Config PUT >> validating fields", DebugLevel.debug)
        try:
            config_svc.validate_config(new_data)
        except AdminOpError as e:
            wa._dbg(f"> Config PUT >> reject: {e.key} {e.args}", DebugLevel.warning)
            return jsonify({'error': wa._t(e.key, *e.args)}), 400

        wa._dbg("> Config PUT >> validation passed; restoring masked secrets, "
                "encrypting + writing editable layer to DB", DebugLevel.debug)
        secret_manager.restore_sensitive(new_data, old_data, keys=wa._secret_keys)

        if wa._write_config(new_data, actor=session.get('username', '')):
            wa._dbg(f"> Config >> saved {len(to_apply)} field(s): "
                    f"{sorted(to_apply.keys())}", DebugLevel.info)
            wa._dbg("> Config PUT >> file written; applying runtime values", DebugLevel.debug)
            # Apply the saved config to the running instance: runtime attributes (shared
            # with boot) + save-only side-effects (log level, cache, service pokes, restart
            # flags on port/proxy/syslog_db change, ProxyFix rebuild). Flask-/wa-coupled, so
            # it lives on WebAdmin, not in the Flask-free config service.
            wa._apply_config_on_save(old_data, new_data, to_apply)
            changes = wa._diff_dicts(old_data, new_data, sensitive=wa._sensitive_fields)
            # Only audit a save that actually changed something — a no-op save (e.g.
            # the SCIM wizard re-saving an unchanged token) would otherwise clutter the
            # log with blank-detail entries.
            if changes:
                wa._audit('config_saved', detail=changes)
            wa._config_version = str(uuid.uuid4())
            if wa._restart_pending:
                wa._dbg("> Config PUT >> restart_pending set (port/proxy changed)", DebugLevel.debug)

            # Update per-field version tokens for every saved field.
            new_token = str(uuid.uuid4())
            for path in to_apply:
                wa._field_versions[path] = new_token
            saved_versions = {p: new_token for p in to_apply}

            wa._dbg(f"> Config PUT >> done: {len(to_apply)} saved, {len(conflicts)} conflict(s), "
                    f"config_version={wa._config_version[:8]}", DebugLevel.debug)
            resp = jsonify({
                'ok': len(conflicts) == 0,
                'saved': list(to_apply.keys()),
                'conflicts': conflicts,
                'versions': saved_versions,
                # Si la página que acaba de guardar puede cargar el mapa nuevo, o hay que
                # pedirla otra vez. Lo contesta el SERVIDOR porque es quien sabe con qué
                # política se sirvió esa página: la de la configuración vieja, que es la que
                # tenía delante quien pulsó guardar. La pantalla no puede saberlo — no puede
                # leer su propia cabecera— y una regla escrita allí sería una copia de esta que
                # se desviaría el día que cambie.
                'reload_required': _map_needs_reload(old_data, new_data),
            })
            resp.headers['ETag'] = f'"{wa._config_version}"'
            return resp

        wa._dbg("> Config PUT >> save_file_error: write failed", DebugLevel.error)
        return jsonify({'error': wa._t('save_file_error')}), 500

    # --- API: database maintenance --------------------------------

    # The two halves of maintenance, kept apart because they cost wildly different things:
    # `optimize` refreshes the statistics the query planner reads and touches no storage;
    # `compact` rewrites it to hand free space back to the filesystem and can hold the
    # database for as long as that takes. Offering only the combined operation would mean the
    # cheap, safe one could never be run on its own — which is the one worth running often.
    _DB_OPS = {
        'optimize': ('optimize', 'db_optimized'),
        'compact':  ('compact',  'db_compacted'),
    }

    def _orphan_inputs():
        """What still exists, from the two places that know.

        The configuration for what a module still claims, the registry for what a device
        still is. Read once per request and handed to the sweep, which is arithmetic on two
        lists and stays testable that way.
        """
        saved = wa._load_modules() or {}
        items: dict = {}
        present = set()
        for mod_key, cfg in saved.items():
            bare = orphans._bare(mod_key)
            present.add(bare)
            keys = items.setdefault(bare, set())
            if not isinstance(cfg, dict):
                continue
            for coll, entries in cfg.items():
                if str(coll).startswith('__') or not isinstance(entries, dict):
                    continue
                keys.update(str(k) for k in entries)
        store = getattr(wa, '_devices_store', None)
        devices = set()
        if store is not None:
            try:
                devices = {str(h.get('uid') or '') for h in (store.list(decrypt=False) or ())}
            except Exception:  # pylint: disable=broad-except
                devices = set()
        return items, devices, present

    def _orphan_series():
        """Every stored series, per table, with what it would cost to keep."""
        out = {}
        hist = getattr(wa, '_history', None)
        if hist is not None:
            try:
                out['history'] = [{'module': s.get('module'), 'key': s.get('key'),
                                   'count': int(s.get('count') or 0)}
                                  for s in hist.get_index()]
            except Exception:  # pylint: disable=broad-except
                out['history'] = []
        state = getattr(wa, '_check_state_store', None)
        if state is not None:
            try:
                # One entry per KEY and not per stored row: a key is what the sweep deletes,
                # and a device profile files hundreds of metrics under one of them. The count
                # is the rows that would go with it, so the screen says what it will cost.
                seen: dict = {}
                for (mod, key, _metric), _rec in (state.get_all() or {}).items():
                    e = seen.setdefault((mod, key), 0)
                    seen[(mod, key)] = e + 1
                out['check_state'] = [{'module': m, 'key': k, 'count': n}
                                      for (m, k), n in seen.items()]
            except Exception:  # pylint: disable=broad-except
                out['check_state'] = []
        return out

    @app.route('/api/v1/config/db/orphans', methods=['GET'])
    @wa._perm_required('db_maintenance')
    def api_db_orphans():
        """Readings stored under a key nothing owns any more.

        Reported and never swept on its own: "the item is gone" and "the data is worthless"
        are different statements, and the second is the operator's to make. So this answers
        what there is and what it would cost, and the sweep is a separate press.
        """
        items, devices, present = _orphan_inputs()
        out = {}
        for table, rows in _orphan_series().items():
            found = orphans.scan(rows, items, devices, modules=present)
            out[table] = {**orphans.summary(found), 'rows': found}
        return jsonify(out)

    @app.route('/api/v1/config/db/orphans', methods=['DELETE'])
    @wa._perm_required('db_maintenance')
    def api_db_orphans_purge():
        """Delete them. Found again HERE rather than trusting the list the browser was shown.

        That list was true when it was drawn; a cycle since may have recorded a reading under
        a key it now owns, and deleting what a screen remembers is how a sweep removes
        something that stopped being an orphan while somebody read the dialog.
        """
        items, devices, present = _orphan_inputs()
        hist = getattr(wa, '_history', None)
        state = getattr(wa, '_check_state_store', None)
        deleted = {'history': 0, 'check_state': 0}
        series = 0
        for table, rows in _orphan_series().items():
            for row in orphans.scan(rows, items, devices, modules=present):
                series += 1
                try:
                    if table == 'history' and hist is not None:
                        deleted['history'] += int(
                            hist.delete_series(row['module'], row['key']) or 0)
                    elif table == 'check_state' and state is not None:
                        if state.delete(row['module'], row['key']):
                            deleted['check_state'] += int(row.get('count') or 0)
                except Exception:  # pylint: disable=broad-except
                    continue        # one series that will not go is not the sweep failing
        wa._audit('db_orphans_purged', detail={'series': series, **deleted})
        return jsonify({'ok': True, 'series': series, **deleted})

    @app.route('/api/v1/config/db/targets/<op>', methods=['GET'])
    @wa._perm_required('db_maintenance')
    def api_db_targets(op):
        """What the run will walk, in the order it will walk it.

        The ENGINE decides the shape: a table per row where the statement works per table,
        and nothing at all where it does not — SQLite's VACUUM is one indivisible rewrite of
        the file, and reporting it as thirty-three tables would invent a granularity the
        engine does not have, making every tick a claim about work that had not finished.
        `divisible: false` is how the client knows to show a single row for the database
        itself instead of a list.

        Asked from the catalog rather than from the TableSpec declarations: what matters is
        what the database actually contains — a module table created at runtime is as real as
        a declared one, and a list that omitted it would tick to the end with work left.
        """
        if op not in _DB_OPS:
            return jsonify({'error': wa._t('db_maintenance_unknown_op')}), 400
        conn = getattr(wa, '_db_connector', None)
        if conn is None:
            return jsonify({'error': wa._t('db_not_available')}), 503
        targets = conn.maintenance_targets(op)
        return jsonify({'op': op, 'targets': targets, 'divisible': bool(targets)})

    @app.route('/api/v1/config/db/<op>', methods=['POST'])
    @wa._perm_required('db_maintenance')
    def api_db_maintenance(op):
        """Run one maintenance operation against the main database.

        The operation is looked up in a fixed table rather than called by name off the
        connector: `op` arrives from the URL, and `getattr(connector, op)` would turn this
        endpoint into a way to invoke any method the connector has.
        """
        entry = _DB_OPS.get(op)
        if not entry:
            return jsonify({'error': wa._t('db_maintenance_unknown_op')}), 400
        method, event = entry
        conn = getattr(wa, '_db_connector', None)
        if conn is None:
            return jsonify({'error': wa._t('db_not_available')}), 503

        # One table at a time, so the UI can show a tick that means THAT table finished
        # rather than a bar that means time passed. Only `optimize` takes it: analyzing one
        # table is cheap and independent, while a compaction is one rewrite of the whole
        # store on two of the three engines.
        body = request.get_json(silent=True) or {}
        table = str(body.get('table') or '').strip()
        if table:
            # Checked against what THIS operation can actually be split into, never trusted.
            # The name is interpolated into SQL (an identifier cannot be a bound parameter),
            # so accepting whatever arrived would be an injection point — quoting is not an
            # argument for skipping the check, it is the reason the check has to decide.
            # Asking `maintenance_targets` rather than `list_tables` also refuses a per-table
            # request for an operation the engine cannot divide: on SQLite a per-table
            # "compact" would silently rewrite the WHOLE database once per table.
            if table not in conn.maintenance_targets(op):
                return jsonify({'error': wa._t('db_table_unknown')}), 400

        size_before = None if table else config_svc.database_size(conn)
        try:
            getattr(conn, method)(table) if table else getattr(conn, method)()
        except Exception as exc:  # pylint: disable=broad-except
            wa._dbg(f'> DB >> {op} failed: {type(exc).__name__}: {exc}', DebugLevel.error)
            wa._audit(event, detail={'ok': False, 'table': table, 'error': str(exc)[:500]})
            return jsonify({'error': f'{wa._t("db_maintenance_failed")}: {exc}'}), 500
        # A per-table step reports no sizes and writes no audit entry of its own: the run is
        # ONE operator action, and one row per table would bury the record it belongs to.
        # The client closes the run with a final call carrying no table.
        if table:
            return jsonify({'ok': True, 'operation': op, 'table': table})
        size_after = config_svc.database_size(conn)

        # Audited like any other operator action, and with the numbers: "compacted" without
        # a before and after is a claim nobody can check, and the whole reason to run it is
        # to find out whether there was anything to reclaim.
        detail = {'ok': True, 'operation': op}
        freed = None
        if size_before is not None and size_after is not None:
            freed = max(0, size_before - size_after)
            detail.update({'bytes_before': size_before, 'bytes_after': size_after,
                           'bytes_freed': freed})
        # What each table reported. The per-table steps deliberately write no entry each, so
        # without this the record of a thirty-three table run is the word "ok" — true, and
        # useless to anyone asking WHICH table failed.
        #
        # It comes from the client because only the client watched the whole run; the server
        # answers one table per request and keeps nothing between them. So it is treated as a
        # claim and checked into shape: table names must be ones this operation could actually
        # have walked, and the errors are truncated. What it cannot be is a way to write
        # arbitrary text into the audit log.
        detail.update(config_svc.summarize_run(
            body.get('results'), conn.maintenance_targets(op),
            getattr(wa, '_AUDIT_DETAIL_MAX_ITEMS',
                    CFG_BY_PATH['web_admin|audit_detail_max_items'].default)))
        wa._audit(event, detail=detail)
        # Formatted HERE, by the formatter the rest of the panel already uses. The browser
        # would need its own to render this, and a second implementation of "bytes as a
        # human reads them" is a second answer to the same question: fmt_bytes scales in
        # 1024s, so a JS version counting in 1000s would print a different size for the same
        # number depending on which side of the wire formatted it.
        return jsonify({'ok': True, 'operation': op,
                        'bytes_before': size_before, 'bytes_after': size_after,
                        'bytes_freed': freed,
                        'freed_human': fmt_bytes(freed) if freed is not None else None})
