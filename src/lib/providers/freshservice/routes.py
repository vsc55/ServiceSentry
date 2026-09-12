#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freshservice sobre HTTP — todo bajo ``/api/v1/providers/freshservice``:

    POST   /api/v1/providers/freshservice/test      ¿conecta esta clave con este dominio?
    GET    /api/v1/providers/freshservice/preview   qué se crearía, qué se corregiría, qué no
    POST   /api/v1/providers/freshservice/import    hacerlo

Tres y no una porque son tres momentos: se comprueba la conexión mientras se teclea la clave, se
mira el plan cuando ya conecta, y se aplica cuando el plan dice lo que se esperaba. Una sola ruta
que importase de golpe sería una que, el día que el dominio esté mal escrito, contesta «0
empresas» sin decir si es que no hay o es que no ha entrado.

Todas piden ``orgs_edit``: esto crea sociedades y corrige nombres que salen en las chapas de
cuarenta armarios, que es exactamente la autoridad que esa bandera nombra.
"""

from __future__ import annotations

from flask import jsonify, request, session

from lib.providers.freshservice import client as fs_client
from lib.providers.freshservice import plan as fs_plan
from lib.providers.freshservice import service as fs_service


def register(app, wa):
    edit_req = wa._perm_required('orgs_edit')

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
        return {'orgs': orgs,
                'plan': fs_plan.build(deps, orgs),
                'orphans': [{'uid': o['uid'], 'name': o['name'], 'short': o.get('short') or ''}
                            for o in fs_plan.orphans(deps, orgs)],
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

    _ = (api_fs_test, api_fs_preview, api_fs_import)
