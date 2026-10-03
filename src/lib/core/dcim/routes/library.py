#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Marcas y plataformas: los dos vocabularios cortos del catálogo.

Ninguno es una tabla de propósito general: una marca es la raíz de un modelo y una
plataforma es con lo que sale un equipo. Se leen mucho y se escriben poco.

Rutas:

    GET     /api/v1/dcim/brands
    POST    /api/v1/dcim/brands
    PUT     /api/v1/dcim/brands/<uid>
    DELETE  /api/v1/dcim/brands/<uid>
    GET     /api/v1/dcim/platforms
    POST    /api/v1/dcim/platforms
    PUT     /api/v1/dcim/platforms/<uid>
    DELETE  /api/v1/dcim/platforms/<uid>
    POST    /api/v1/dcim/platforms/drop
"""

from __future__ import annotations

from flask import jsonify, request

from lib.core.dcim import platforms as dcim_platforms
from lib.core.dcim import profiles as dcim_profiles


def register(app, wa, C):
    """Las rutas de esta área. *C* es lo que comparten todas: los permisos y los ayudantes."""
    @app.route('/api/v1/dcim/platforms', methods=['GET'])
    @C.view_req
    def api_dcim_platforms():
        """Las plataformas, con cuántas plantillas apuntan a cada una.

        Se lee con `dcim_view` y no con el permiso del catálogo: quien monta un rack tiene que
        poder ELEGIR una, igual que elige un modelo base. Escribirlas es otra cosa.
        """
        store = C.platforms()
        if store is None:
            return jsonify({'platforms': [], 'kinds': list(dcim_platforms.KINDS),
                            'lifecycle': []})
        plantillas = C.builds()
        usos = plantillas.platform_counts() if plantillas else {}
        marcas = {str(m['uid']): str(m.get('name') or '')
                  for m in (C.brands().list() if C.brands() else ())}
        return jsonify({'platforms': [
            dict(p, builds=usos.get(str(p['uid']), 0),
                 brand=marcas.get(str(p.get('brand_uid') or ''), ''))
            for p in store.list()],
            'kinds': list(dcim_platforms.KINDS),
            # Las mismas seis fechas que las de un modelo del catálogo, del mismo sitio: un
            # sistema operativo deja de recibir parches igual que un servidor deja de venderse,
            # y dos listas serían dos que se separan.
            'lifecycle': dcim_profiles.group_fields(C.profiles(), 'lifecycle')})

    @app.route('/api/v1/dcim/platforms', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_platform_new():
        store = C.platforms()
        if store is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        uid = store.create(data, actor=C.actor())
        if not uid:
            return jsonify({'error': wa._t('dcim_platform_name_taken')}), 400
        wa._audit('dcim_platform_save',
                  detail={'action': 'create', 'name': str(data.get('name') or '')})
        return jsonify({'uid': uid})

    @app.route('/api/v1/dcim/platforms/drop', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_platforms_drop():
        """Retirar varias de una vez. Devuelve cuántas se fueron y cuántas se quedaron.

        Una petición y no veintidós: traer los básicos da de alta veintiséis, y quien quiere
        quedarse con cuatro no quiere veintidós confirmaciones ni veintidós idas y venidas.

        **Las que alguna plantilla nombre no se van**, y eso no es un error de la petición: es lo
        que pasó con esas. Se cuentan aparte para poder decirlo — negar el lote entero por una
        obligaría a buscar cuál era, y borrarla dejaría plantillas diciendo «sale con» sin decir
        con qué.
        """
        store = C.platforms()
        if store is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        uids = [str(u) for u in ((request.get_json(silent=True) or {}).get('uids') or [])
                if str(u or '').strip()]
        if not uids:
            return jsonify({'error': wa._t('dcim_catalog_pick_none')}), 400
        plantillas = C.builds()
        usos = plantillas.platform_counts() if plantillas else {}
        idas, quedan = 0, 0
        for uid in uids:
            if usos.get(uid):
                quedan += 1
                continue
            idas += 1 if store.delete(uid) else 0
        wa._audit('dcim_platform_save',
                  detail={'action': 'drop_many', 'count': idas, 'kept': quedan,
                          'asked': len(uids)})
        return jsonify({'ok': True, 'count': idas, 'kept': quedan})

    @app.route('/api/v1/dcim/platforms/<uid>', methods=['PUT'])
    @C.catalog_manage_req
    def api_dcim_platform_edit(uid):
        store = C.platforms()
        antes = store.get(uid) if store else None
        if not antes:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        if not store.update(uid, data, actor=C.actor()):
            return jsonify({'error': wa._t('dcim_platform_name_taken')}), 400
        wa._audit('dcim_platform_save',
                  detail={'action': 'edit', 'platform': uid,
                          'name': str(data.get('name') or antes.get('name') or '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/platforms/<uid>', methods=['DELETE'])
    @C.catalog_manage_req
    def api_dcim_platform_drop(uid):
        """Retirarla. **No mientras haya plantillas que la nombren.**

        Se dice cuántas en vez de borrar y dejarlas apuntando a nada: una plantilla que dice
        «sale con» y no dice con qué es peor que una que no lo dice, porque parece que se sabe.
        """
        store = C.platforms()
        fila = store.get(uid) if store else None
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        plantillas = C.builds()
        cuantas = (plantillas.platform_counts() if plantillas else {}).get(str(uid), 0)
        if cuantas:
            return jsonify({'error': wa._t('dcim_platform_in_use'),
                            'builds': cuantas}), 400
        store.delete(uid)
        wa._audit('dcim_platform_save',
                  detail={'action': 'drop', 'platform': uid,
                          'name': str(fila.get('name') or '')})
        return jsonify({'ok': True})

    # ── Las marcas: la raíz del catálogo ─────────────────────────────────


    @app.route('/api/v1/dcim/brands', methods=['GET'])
    @C.catalog_view_req
    def api_dcim_brands():
        """Los fabricantes, con cuántos modelos tiene cada uno.

        La cuenta va en la lista y no en la ficha: es lo que dice de un vistazo a quién se le
        compra de verdad y quién entró de rebote con la biblioteca. Y es lo que hace que borrar
        uno pueda negarse con un motivo en vez de dejar cuatrocientos modelos huérfanos.
        """
        brands = C.brands()
        cat = getattr(wa, '_dcim_catalog', None)
        if brands is None:
            return jsonify({'brands': []})
        cuentas = cat.brand_counts() if cat else {}
        return jsonify({'brands': [dict(m, models=cuentas.get(str(m['uid']), 0))
                                   for m in brands.list()]})

    @app.route('/api/v1/dcim/brands', methods=['POST'])
    @C.catalog_manage_req
    def api_dcim_brand_new():
        """Uno escrito a mano, para el fabricante del que todavía no hay ningún modelo.

        Los trescientos de la biblioteca se crean solos al importar — nadie los va a teclear— así
        que esto es para el otro caso: el taller que montó el armario, el distribuidor con el que
        hay contrato y del que aún no se ha metido nada.
        """
        brands = C.brands()
        if brands is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        uid = brands.create(data, actor=C.actor())
        if not uid:
            return jsonify({'error': wa._t('dcim_brand_name_taken')}), 400
        wa._audit('dcim_brand_save',
                  detail={'action': 'create', 'name': str(data.get('name') or '')})
        return jsonify({'uid': uid})

    @app.route('/api/v1/dcim/brands/<uid>', methods=['PUT'])
    @C.catalog_manage_req
    def api_dcim_brand_edit(uid):
        brands = C.brands()
        antes = brands.get(uid) if brands else None
        if not antes:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        data = request.get_json(silent=True) or {}
        if not brands.update(uid, data, actor=C.actor()):
            return jsonify({'error': wa._t('dcim_brand_name_taken')}), 400
        wa._audit('dcim_brand_save',
                  detail={'action': 'edit', 'brand': uid,
                          'name': str(data.get('name') or antes.get('name') or '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/brands/<uid>', methods=['DELETE'])
    @C.catalog_manage_req
    def api_dcim_brand_drop(uid):
        """Retirar la ficha de un fabricante. **No mientras haya modelos suyos.**

        No por integridad referencial: porque volvería. El catálogo guarda el nombre en cada
        fila, y el repaso del arranque vuelve a dar de alta a todo fabricante que aparezca en
        alguna — así que borrarlo con cuatrocientos modelos detrás sería tirar la web de soporte
        y el número de cliente para que el nombre reapareciera solo al siguiente reinicio. Eso no
        es un borrado: es perder lo único que no se puede volver a descargar.
        """
        brands = C.brands()
        fila = brands.get(uid) if brands else None
        if not fila:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        cat = getattr(wa, '_dcim_catalog', None)
        cuantos = (cat.brand_counts() if cat else {}).get(str(uid), 0)
        if cuantos:
            return jsonify({'error': wa._t('dcim_brand_in_use'), 'models': cuantos}), 400
        brands.delete(uid)
        wa._audit('dcim_brand_save',
                  detail={'action': 'drop', 'brand': uid, 'name': str(fila.get('name') or '')})
        return jsonify({'ok': True})

    # ── Las plantillas: lo que de verdad se compra ────────────────────────────

    # Referenciadas para que un analizador no las dé por muertas: Flask se las
    # queda por su ruta.
    _ = (api_dcim_platforms, api_dcim_platform_new, api_dcim_platforms_drop,)
