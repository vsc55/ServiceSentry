#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The plan catalogue's API: what a screen can put on its plan, and the objects created from it.

    GET    /api/v1/plan2d/<screen>/kinds          its objects: base, its own, and created ones
    POST   /api/v1/plan2d/<screen>/kinds          create one
    PUT    /api/v1/plan2d/<screen>/kinds/<uid>    change one
    DELETE /api/v1/plan2d/<screen>/kinds/<uid>    delete one nothing uses

Each screen says with which permission it is read and with which its objects are managed
(:func:`lib.core.plan2d.kinds.register_screen`): the inventory's, with `dcim_view` and
`dcim_catalog_manage`. A screen nobody registered does not exist here (404).
"""

from __future__ import annotations

from flask import jsonify, request, session

from lib.core.plan2d import kinds as p2k


def register(app, wa):

    def _store():
        return getattr(wa, '_plan2d_kinds', None)

    def _may(perm):
        return perm in set(wa._get_session_permissions() or ())

    def _screen_or_error(name, perm_key):
        s = p2k.screen(name)
        if not s:
            return None, (jsonify({'error': wa._t('plan2d_screen_unknown')}), 404)
        if not _may(s[perm_key]):
            return None, (jsonify({'error': wa._t('access_denied')}), 403)
        return s, None

    @app.route('/api/v1/plan2d/<screen>/kinds', methods=['GET'])
    @wa._login_required
    def api_plan2d_kinds(screen):
        s, err = _screen_or_error(screen, 'view_perm')
        if err:
            return err
        st = _store()
        filas = st.of_screen(screen) if st else []
        return jsonify({'kinds': p2k.kinds(screen, filas), 'groups': p2k.groups(),
                        'icons': list(p2k.ICONS),
                        'layers': list(p2k.LAYERS), 'mounts': list(p2k.MOUNTS),
                        'devices': bool(s['devices']), 'manage': _may(s['manage_perm'])})

    @app.route('/api/v1/plan2d/<screen>/kinds', methods=['POST'])
    @wa._login_required
    def api_plan2d_kind_new(screen):
        s, err = _screen_or_error(screen, 'manage_perm')
        if err:
            return err
        st = _store()
        if not st:
            return jsonify({'error': wa._t('plan2d_screen_unknown')}), 404
        datos = p2k.custom_clean(request.get_json(silent=True) or {})
        malo = p2k.custom_bad(datos, devices=s['devices'])
        if malo:
            return jsonify({'error': wa._t(malo)}), 400
        nuevo = st.create(screen, datos, actor=session.get('username', ''))
        wa._audit('plan2d_kind_created', detail={'screen': screen, 'key': nuevo['key'],
                                                 'name': datos['name']})
        return jsonify(nuevo)

    def _own(screen, uid):
        """The object *uid*, if it is one of *screen*'s: one of another screen is not found."""
        st = _store()
        fila = st.get(uid) if st else None
        return fila if fila and fila.get('screen') == screen else None

    @app.route('/api/v1/plan2d/<screen>/kinds/<uid>', methods=['PUT'])
    @wa._login_required
    def api_plan2d_kind_edit(screen, uid):
        s, err = _screen_or_error(screen, 'manage_perm')
        if err:
            return err
        fila = _own(screen, uid)
        if not fila:
            return jsonify({'error': wa._t('plan2d_kind_not_found')}), 404
        datos = p2k.custom_clean(request.get_json(silent=True) or {}, current=fila)
        malo = p2k.custom_bad(datos, devices=s['devices'])
        if malo:
            return jsonify({'error': wa._t(malo)}), 400
        # Equipment or not is what decides where the screen keeps what is placed: changing it
        # under things already placed would leave them in the wrong table.
        if int(datos['device']) != int(fila.get('device') or 0) and _in_use(s, fila['key']):
            return jsonify({'error': wa._t('plan2d_kind_in_use')}), 409
        _store().update(uid, datos, actor=session.get('username', ''))
        return jsonify({'ok': True})

    def _in_use(s, key):
        fn = s.get('in_use')
        try:
            return int(fn(wa, key)) if fn else 0
        except Exception:                                   # noqa: BLE001 — refuse rather than guess
            return 1

    @app.route('/api/v1/plan2d/<screen>/kinds/<uid>', methods=['DELETE'])
    @wa._login_required
    def api_plan2d_kind_del(screen, uid):
        s, err = _screen_or_error(screen, 'manage_perm')
        if err:
            return err
        fila = _own(screen, uid)
        if not fila:
            return jsonify({'error': wa._t('plan2d_kind_not_found')}), 404
        usados = _in_use(s, fila['key'])
        if usados:
            return jsonify({'error': wa._t('plan2d_kind_in_use'), 'used': usados}), 409
        _store().delete(uid)
        wa._audit('plan2d_kind_deleted', detail={'screen': screen, 'key': fila['key'],
                                                 'name': fila.get('name') or ''})
        return jsonify({'ok': True})
