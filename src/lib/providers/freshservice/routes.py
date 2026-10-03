#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freshservice sobre HTTP — todo bajo ``/api/v1/providers/freshservice``:

    POST   /api/v1/providers/freshservice/test      ¿conecta esta clave con este dominio?
    GET    /api/v1/providers/freshservice/preview   qué se crearía, qué se corregiría, qué no
    POST   /api/v1/providers/freshservice/import    hacerlo

…y lo mismo para los **activos**, que aquí son los dispositivos, con una más delante::

    GET    /api/v1/providers/freshservice/assets/types     qué clases de activo hay allí
    POST   /api/v1/providers/freshservice/assets/types     crear aquí las que falten
    GET    /api/v1/providers/freshservice/assets/counts    cuántos hay de cada (se paga aparte)
    GET    /api/v1/providers/freshservice/assets/preview   qué se crearía, qué se corregiría
    POST   /api/v1/providers/freshservice/assets/import    hacerlo

La de los tipos va **antes** y es una sola llamada: el catálogo de tipos es un recurso aparte del
de los activos, así que se puede preguntar «¿qué quieres, conmutadores o portátiles?» sin haber
traído todavía ni un activo — y traer después sólo eso. Un inventario de cuatro mil activos son
cuarenta viajes a su API; tres tipos suelen ser tres.

Dos pares y no uno con un parámetro: las empresas y los dispositivos no se traen en el mismo
momento, no los mira la misma persona y **no los autoriza la misma bandera** — `orgs_edit`
decide de quién es la propiedad y `devices_edit` decide qué máquinas hay. Una ruta con un
interruptor sería una que se autoriza con la de una cosa y escribe en la otra.

Tres y no una porque son tres momentos: se comprueba la conexión mientras se teclea la clave, se
mira el plan cuando ya conecta, y se aplica cuando el plan dice lo que se esperaba. Una sola ruta
que importase de golpe sería una que, el día que el dominio esté mal escrito, contesta «0
empresas» sin decir si es que no hay o es que no ha entrado.

Todas piden ``orgs_edit``: esto crea sociedades y corrige nombres que salen en las chapas de
cuarenta armarios, que es exactamente la autoridad que esa bandera nombra.
"""

from __future__ import annotations

from flask import jsonify, request, session

from lib.providers.freshservice import assets as fs_assets
from lib.providers.freshservice import client as fs_client
from lib.providers.freshservice import plan as fs_plan
from lib.providers.freshservice import service as fs_service


def register(app, wa):
    edit_req = wa._perm_required('orgs_edit')
    # Traer dispositivos crea fichas en el registro de máquinas, que es exactamente la autoridad
    # que nombra esta otra bandera. Quien lleva las sociedades no tiene por qué poder dar de alta
    # cuarenta servidores, y al revés tampoco.
    dev_req = wa._perm_required('devices_edit')

    def _cfg():
        """El dominio y la clave guardados. La clave sale del almacén y no de la pantalla: la
        pantalla la enseña enmascarada, que es lo que hace que no viaje de vuelta."""
        sec = wa._config_section('freshservice') or {}
        return (str(sec.get('domain') or '').strip(), str(sec.get('api_key') or '').strip())

    def _store():
        return getattr(wa, '_orgs_store', None)

    def _fallo(exc):
        """Un error con nombre, contado en el idioma de quien mira. Detrás de cada clave hay una
        cosa distinta que arreglar —la clave, su permiso, el dominio, el límite por minuto— y
        decirlas todas «error» manda a mirar la que no es."""
        detalle = getattr(exc, 'detail', '')[:200]
        # El detalle va TAMBIÉN como argumento del texto: algunos mensajes llevan un hueco —el
        # dominio que se tecleó, sin ir más lejos— y traducir la clave a secas dejaba un «{}»
        # literal en pantalla, que es peor que no decir nada porque parece un fallo del panel.
        # `_t` ignora los argumentos que le sobran, así que los que no tienen hueco no cambian.
        return jsonify({'error': wa._t(getattr(exc, 'key', 'fs_err_net'), detalle),
                        'detail': detalle}), 502

    @app.route('/api/v1/providers/freshservice/test', methods=['POST'])
    @edit_req
    def api_fs_test():
        """¿Vale esta clave, y qué se ve con ella?

        Lo primero se contesta con una página de un departamento: barato, y es lo que de verdad
        se está preguntando. Lo segundo es su **página de estado** —qué publican, qué incidentes
        hay abiertos y qué componentes— porque la mitad de las veces que alguien viene a probar
        la clave es porque algo va raro, y saber que esa casa tiene un incidente abierto ahorra
        la tarde.

        Lo de la página de estado es **opcional y va aparte**: no está en todos los planes y la
        clave puede no alcanzarla. Si falla, la prueba sigue saliendo bien y lo dice — al revés,
        una clave perfecta daría error por un módulo que esa casa no ha contratado.
        """
        domain, key = _cfg()
        if not domain or not key:
            return jsonify({'error': wa._t('fs_err_unset')}), 400
        try:
            out = fs_client.probe(domain, key)
        except fs_client.FreshserviceError as exc:
            return _fallo(exc)
        try:
            estado = fs_client.status_summary(domain, key)
        except Exception as exc:                # pylint: disable=broad-except
            # Ancho a propósito, y es el sitio donde la promesa se cumple: lo que se estaba
            # probando es la CLAVE, y la clave vale. `status_summary` ya recoge los fallos con
            # nombre uno a uno; esto recoge el resto —lo que no se previó— para que un extra no
            # pueda tumbar la respuesta principal. Sin esto, un fallo raro leyendo su página de
            # estado contesta un 500 a quien acaba de teclear una clave correcta.
            estado = {'available': False, 'pages': [], 'incidents': [], 'components': [],
                      'error_key': getattr(exc, 'key', 'fs_err_net')}
        if estado.get('error_key'):
            # La clave del fallo se traduce aquí: la pantalla enseña una frase, no `fs_err_403`.
            estado['error'] = wa._t(estado['error_key'], estado.get('detail', ''))
        wa._audit('freshservice_test', detail={'host': out.get('host', ''),
                                               'status_page': bool(estado.get('available'))})
        return jsonify({'ok': True, 'host': out.get('host', ''),
                        'rate': out.get('rate', {}), 'status': estado})

    def _preview():
        """Lo que llega, emparejado con lo que hay. Compartido por mirar y por aplicar: si el
        plan se calculara de dos maneras, lo aplicado no sería lo que se enseñó."""
        domain, key = _cfg()
        if not domain or not key:
            return None, (jsonify({'error': wa._t('fs_err_unset')}), 400)
        store = _store()
        if store is None:
            return None, (jsonify({'error': wa._t('orgs_not_found')}), 500)
        try:
            deps = fs_client.departments(domain, key)
        except fs_client.FreshserviceError as exc:
            return None, _fallo(exc)
        orgs = store.orgs.list()
        # Una lista cortada en el tope de páginas no es la lista entera: se dice, y no se
        # cuentan huérfanos sobre ella — todo lo que no llegó saldría como «ya no está allí».
        cortada = bool(getattr(deps, 'truncated', False))
        return {'orgs': orgs,
                'plan': fs_plan.build(deps, orgs),
                'orphans': [] if cortada else [
                    {'uid': o['uid'], 'name': o['name'], 'short': o.get('short') or ''}
                    for o in fs_plan.orphans(deps, orgs)],
                'truncated': cortada,
                'total': len(deps)}, None

    @app.route('/api/v1/providers/freshservice/preview', methods=['GET'])
    @edit_req
    def api_fs_preview():
        """Qué pasaría. **Antes** de que pase: una importación que crea y corrige en silencio es
        una que, el día que el filtro esté mal, deja media docena de sociedades duplicadas y
        ninguna forma de saber cuál era la buena."""
        out, err = _preview()
        if err is not None:
            return err
        # Las de aquí van con la lista para poder emparejar a mano: qué empresa local es la misma
        # que un departamento de allí lo sabe quien mira, no un parecido de nombres. Sólo lo
        # justo para elegir en un desplegable — el resto de la fila no pinta nada en este cuadro.
        locales = [{'uid': o['uid'], 'name': o['name'], 'short': o.get('short') or '',
                    'source': o.get('source') or '',
                    'external_id': o.get('external_id') or ''} for o in out.pop('orgs', [])]
        return jsonify(dict(out, counts=fs_plan.counts(out['plan']), orgs=locales))

    @app.route('/api/v1/providers/freshservice/import', methods=['POST'])
    @edit_req
    def api_fs_import():
        """Aplicarlo. Se vuelve a pedir la lista en vez de fiarse de lo que enseñó la pantalla:
        entre mirar y aceptar pasa un rato, y lo que se escribe tiene que ser lo que hay ahora."""
        datos = request.get_json(silent=True) or {}
        out, err = _preview()
        if err is not None:
            return err
        # Lo elegido y lo emparejado llegan de la pantalla; el PLAN se vuelve a calcular aquí
        # sobre lo que hay ahora. Aplicar lo que mandó el navegador sería escribir lo que se vio
        # hace un rato, y entre mirar y aceptar pasa el tiempo suficiente para que otro haya
        # tocado una fila.
        pick = datos.get('pick')
        pick = None if pick is None else [str(x) for x in (pick or [])]
        plan, rechazos = fs_plan.select(out['plan'], pick=pick,
                                        link=datos.get('link') or {}, orgs=out.get('orgs') or [])
        hecho = fs_service.apply(_store(), plan, actor=session.get('username', ''))
        # Un emparejamiento que no se pudo hacer se cuenta como lo que es: algo que se pidió y no
        # salió, con su motivo, y no como una fila que nadie eligió.
        hecho['failed'] = list(hecho['failed']) + [
            {'name': r['name'], 'error': wa._t(r['reason'])} for r in rechazos]
        wa._audit('freshservice_import',
                  detail={'created': hecho['created'], 'updated': hecho['updated'],
                          'adopted': hecho['adopted'], 'failed': len(hecho['failed']),
                          'picked': len(plan), 'orphans': len(out['orphans'])})
        return jsonify(dict(hecho, orphans=len(out['orphans'])))

    # ── Los activos, que aquí son los dispositivos ───────────────────────────────────────

    def _devices_store():
        return getattr(wa, '_devices_store', None)

    @app.route('/api/v1/providers/freshservice/assets/types', methods=['GET'])
    @dev_req
    def api_fs_asset_types():
        """Las clases de activo que hay allí, y nada más.

        Una llamada y barata, y por eso va sola: es lo que permite elegir **antes** de traer. Sin
        esto, saber que sólo hacen falta los conmutadores costaba traerse el inventario entero
        para descartarlo en la pantalla.
        """
        domain, key = _cfg()
        if not domain or not key:
            return jsonify({'error': wa._t('fs_err_unset')}), 400
        try:
            filas = fs_client.asset_types(domain, key)
        except fs_client.FreshserviceError as exc:
            return _fallo(exc)
        # Con lo que hace falta para decidir, que son **dos preguntas distintas** y no una:
        #
        #   `here`   — aquí ya hay una clase que se llama así. Es lo que mira el cuadro de
        #              IMPORTAR: traerla no crearía nada, sólo la adoptaría.
        #   `linked` — aquí ya hay una clase ATADA a ésta. Es lo que mira el de atar: dos
        #              locales sobre la misma de fuera es repartir la flota en dos montones.
        #
        # Estaban juntas en un solo campo, y el cuadro de atar apagaba lo que coincidía por el
        # nombre — que es justo la fila que se quiere pulsar, porque la clase que se llama igual
        # suele ser la que se está intentando atar. Reportado desde la pantalla.
        from lib.core.devices import classes as device_types          # noqa: PLC0415
        almacen = getattr(wa, '_device_types_store', None)
        fuera = []
        for t in (filas or []):
            if not t.get('id'):
                continue
            nombre = str(t.get('name') or '')
            ext = str(t.get('id') or '')
            ya = atada = None
            if almacen is not None:
                try:
                    atada = almacen.by_external(fs_plan.SOURCE, ext)
                    if device_types.slug(nombre):
                        ya = almacen.by_name(nombre)
                except Exception:      # pylint: disable=broad-except
                    ya = atada = None
            fuera.append({'id': ext, 'name': nombre,
                          # Dicha por `uid`, que es como la nombra todo lo demás: la pantalla la
                          # traduce con el catálogo del navegador, y ése va por uid.
                          'device_type': device_types.uid_for(
                              wa, fs_assets.device_type_for(nombre)),
                          'here': str((ya or {}).get('uid') or ''),
                          'here_name': str((ya or {}).get('name') or ''),
                          'linked': str((atada or {}).get('uid') or ''),
                          'linked_name': str((atada or {}).get('name') or '')})
        return jsonify({'types': sorted(fuera, key=lambda t: t['name'].casefold())})

    @app.route('/api/v1/providers/freshservice/assets/counts', methods=['GET'])
    @dev_req
    def api_fs_asset_counts():
        """Cuántos activos hay de cada clase.

        **Aparte, y se pide a mano.** Su catálogo de tipos no trae ese número, así que la única
        forma de saberlo es recorrer los activos — que es exactamente el viaje que el paso de
        elegir clases existe para ahorrar. Hacerlo al abrir el cuadro habría sido pagarlo siempre
        para que a veces sirviera; así se paga una vez, cuando alguien decide que le compensa, y
        a partir de ahí se elige sabiendo dónde hay algo.
        """
        domain, key = _cfg()
        if not domain or not key:
            return jsonify({'error': wa._t('fs_err_unset')}), 400
        try:
            return jsonify({'counts': fs_client.asset_counts(domain, key)})
        except fs_client.FreshserviceError as exc:
            return _fallo(exc)

    @app.route('/api/v1/providers/freshservice/assets/types', methods=['POST'])
    @dev_req
    def api_fs_import_types():
        """Crear aquí las clases de dispositivo que allí ya existen, y **sin traer un activo**.

        Una casa que ya usa Freshservice tiene escritas las clases que usa; teclearlas otra vez
        aquí es tener dos listas, y dos listas son una que se queda vieja sin avisar.

        **Se eligen antes**, como en las otras dos importaciones de este paquete: `pick` son los
        identificadores marcados en la pantalla. `null` —o que no venga— es «todas», que es lo
        que esto hacía cuando no se podía elegir.

        Lo que ya está no se toca —ni el nombre ni el icono— y lo que se crea se cuenta con su
        nombre: crear quince clases en silencio es la manera de acabar con quince que nadie
        recuerda haber pedido. Un tipo que se parece a una clase que ya hay no crea una copia,
        que es lo que hace :func:`lib.core.devices.classes.ensure`.
        """
        datos = request.get_json(silent=True) or {}
        pick = datos.get('pick')
        elegidos = None if pick is None else {str(x) for x in (pick or [])}
        domain, key = _cfg()
        if not domain or not key:
            return jsonify({'error': wa._t('fs_err_unset')}), 400
        try:
            filas = fs_client.asset_types(domain, key)
        except fs_client.FreshserviceError as exc:
            return _fallo(exc)
        from lib.core.devices import classes as device_types          # noqa: PLC0415
        antes = {c['uid'] for c in device_types.catalog(wa)}
        puestas = []
        for t in (filas or []):
            nombre = str((t or {}).get('name') or '').strip()
            if not nombre:
                continue
            # Lo que se vuelve a pedir aquí es la LISTA; lo elegido llega de la pantalla, y se
            # compara por el identificador de allí — el nombre puede haber cambiado entre mirar
            # y aceptar, y entonces lo que se traería no sería lo que se marcó.
            if elegidos is not None and str((t or {}).get('id') or '') not in elegidos:
                continue
            ident = device_types.ensure(wa, nombre, source=fs_plan.SOURCE,
                                      external_id=str((t or {}).get('id') or ''),
                                      actor=session.get('username', ''))
            if ident and ident not in antes:
                antes.add(ident)
                puestas.append({'uid': ident, 'name': nombre})
        if puestas:
            wa._audit('device_type_created',
                      detail={'source': fs_plan.SOURCE,
                              'added': [p['uid'] for p in puestas]})
        return jsonify({'added': puestas, 'total': len(filas or [])})

    def _assets_preview(type_ids=None):
        """Lo que llega, emparejado con lo que hay. Compartido por mirar y por aplicar: si el
        plan se calculara de dos maneras, lo aplicado no sería lo que se enseñó.

        *type_ids* se le pide al origen para no traer de más, y **se vuelve a aplicar aquí** a lo
        que conteste: un origen que no entienda el filtro devuelve la lista entera, y la pantalla
        enseñaría lo que nadie pidió.
        """
        domain, key = _cfg()
        if not domain or not key:
            return None, (jsonify({'error': wa._t('fs_err_unset')}), 400)
        store = _devices_store()
        if store is None:
            return None, (jsonify({'error': wa._t('device_not_found')}), 500)
        try:
            filas = fs_assets.only_types(fs_client.assets(domain, key, type_ids), type_ids)
            # Los tipos son un extra que mejora la respuesta y no puede estropearla: sin ellos
            # cada dispositivo llega sin clase adivinada, que es lo mismo que pasa hoy con uno
            # dado de alta a mano. Que una clave sin permiso para leer el catálogo de tipos
            # tumbara la importación entera sería negarse a traer cuarenta máquinas por no poder
            # decir cuáles son conmutadores.
            try:
                tipos = fs_client.asset_types(domain, key)
            except fs_client.FreshserviceError:
                tipos = []
        except fs_client.FreshserviceError as exc:
            return None, _fallo(exc)
        devices = store.list(decrypt=False)
        # **Los huérfanos sólo se pueden contar sin filtro.** «Ya no está en Freshservice» es una
        # afirmación sobre TODO lo que hay allí, y con unas clases elegidas lo que se ha visto es
        # un trozo: un dispositivo importado de otra clase saldría como desaparecido por no
        # haberlo preguntado — y lo que eso invita a hacer es borrarlo. Callar es la respuesta
        # honesta; para verlos se mira sin filtro, que es una opción de la pantalla.
        desaparecidos = [] if type_ids else fs_assets.orphans(filas, devices)
        # La clase adivinada sale de una tabla de pistas y viene dicha con el nombre corto de una
        # sembrada; de aquí en adelante viaja por `uid`, que es lo que la pantalla sabe traducir
        # y lo que la columna acepta. Traducirla aquí es traducirla una vez: mirar y aplicar usan
        # este mismo plan, que es lo que hace que lo aplicado sea lo que se enseñó.
        from lib.core.devices import classes as device_types          # noqa: PLC0415
        plan = fs_assets.build(filas, devices, tipos)
        for p in plan:
            if p.get('device_type'):
                p['device_type'] = device_types.uid_for(wa, p['device_type'])
        return {'devices': devices,
                'plan': plan,
                'orphans': [{'uid': h['uid'], 'name': h['name']} for h in desaparecidos],
                'total': len(filas)}, None

    @app.route('/api/v1/providers/freshservice/assets/preview', methods=['GET'])
    @dev_req
    def api_fs_assets_preview():
        """Qué pasaría. **Antes** de que pase — la misma razón que en las empresas, y aquí pesa
        más: un dispositivo creado por error se queda en la lista de todo el mundo, y uno
        emparejado con el que no es se lleva su nombre y su dirección."""
        out, err = _assets_preview(request.args.getlist('type'))
        if err is not None:
            return err
        # Los de aquí van con la lista para poder emparejar a mano: qué dispositivo local es el
        # mismo que un activo de allí lo sabe quien mira, no un parecido de nombres. Sólo lo
        # justo para elegir en un desplegable — los perfiles de conexión no pintan nada en este
        # cuadro, y menos en una respuesta HTTP.
        locales = [{'uid': h['uid'], 'name': h['name'], 'address': h.get('address') or '',
                    'source': h.get('source') or '',
                    'external_id': h.get('external_id') or ''} for h in out.pop('devices', [])]
        return jsonify(dict(out, counts=fs_assets.counts(out['plan']), devices=locales))

    @app.route('/api/v1/providers/freshservice/assets/import', methods=['POST'])
    @dev_req
    def api_fs_assets_import():
        """Aplicarlo. Se vuelve a pedir la lista en vez de fiarse de lo que enseñó la pantalla:
        entre mirar y aceptar pasa un rato, y lo que se escribe tiene que ser lo que hay ahora."""
        datos = request.get_json(silent=True) or {}
        # Los mismos tipos con los que se miró. Sin ellos, aplicar volvería a preguntar por el
        # inventario entero: lo elegido saldría igual —va por identificador— pero a costa de las
        # cuarenta páginas que la vista previa acababa de evitar.
        out, err = _assets_preview(datos.get('types') or [])
        if err is not None:
            return err
        pick = datos.get('pick')
        pick = None if pick is None else [str(x) for x in (pick or [])]
        plan, rechazos = fs_assets.select(out['plan'], pick=pick,
                                          link=datos.get('link') or {},
                                          devices=out.get('devices') or [])
        hecho = fs_service.apply_devices(_devices_store(), plan,
                                       actor=session.get('username', ''), wa=wa)
        # Lo que no se pudo hacer se cuenta como lo que es: algo que se pidió y no salió, con su
        # motivo y en el idioma de quien mira.
        fallos = [{'name': f.get('name') or '',
                   'error': wa._t(f['error_key']) if f.get('error_key') else f.get('error', '')}
                  for f in hecho['failed']]
        hecho['failed'] = fallos + [{'name': r['name'], 'error': wa._t(r['reason'])}
                                    for r in rechazos]
        wa._audit('freshservice_import_devices',
                  detail={'created': hecho['created'], 'updated': hecho['updated'],
                          'adopted': hecho['adopted'], 'failed': len(hecho['failed']),
                          'picked': len(plan), 'orphans': len(out['orphans'])})
        return jsonify(dict(hecho, orphans=len(out['orphans'])))

    _ = (api_fs_test, api_fs_preview, api_fs_import,
         api_fs_asset_types, api_fs_asset_counts, api_fs_import_types,
         api_fs_assets_preview, api_fs_assets_import)
