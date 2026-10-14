#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demonstration data, from Configuration → Maintenance: ``/api/v1/dcim/demo``

    GET    /api/v1/dcim/demo    whether it is installed, and which sites it is
    POST   /api/v1/dcim/demo    install it; ``{"replace": true}`` rebuilds one already there
    DELETE /api/v1/dcim/demo    remove it

The same as ``main.py dcim demo`` (and ``--replace``, ``--remove``), for whoever runs the panel
and not a shell. Asked for: an option in Maintenance to add or delete the demo data.

Behind ``db_maintenance``, the flag of the section it sits in, and not ``dcim_edit``: it writes
and deletes whole sites in one go, which is a maintenance act and not tidying a rack. Only the
sites :mod:`lib.core.dcim.demo` names are ever touched — removing it cannot reach anything a
person entered. Both are audited.
"""

from __future__ import annotations

from flask import jsonify, request

from lib.core.dcim import demo as dcim_demo


def register(app, wa, C):
    maintenance_req = wa._perm_required('db_maintenance')

    def _dirs() -> dict:
        return {'var_dir': wa._var_dir or '', 'media_dir': C.media_dir()}

    @app.route('/api/v1/dcim/demo', methods=['GET'])
    @maintenance_req
    def api_dcim_demo():
        store = C.store()
        sites = dcim_demo.find(store) if store else []
        return jsonify({'installed': bool(sites), 'sites': [str(s.get('name') or '') for s in sites]})

    @app.route('/api/v1/dcim/demo', methods=['POST'])
    @maintenance_req
    def api_dcim_demo_install():
        store = C.store()
        if not store:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        replace = bool((request.get_json(silent=True) or {}).get('replace'))
        try:
            made = dcim_demo.build(store, actor=C.actor(), area_word=wa._t('dcim_floor_area'),
                                   lang=wa._lang(), images=True, replace=replace, **_dirs())
        except dcim_demo.DemoError:
            return jsonify({'error': wa._t('dcim_demo_exists')}), 409
        counts = {k: v for k, v in made.items() if k not in dcim_demo.UID_KEYS}
        wa._audit('dcim_demo_installed', detail={'replace': replace, 'counts': counts})
        return jsonify({'ok': True, 'counts': counts})

    @app.route('/api/v1/dcim/demo', methods=['DELETE'])
    @maintenance_req
    def api_dcim_demo_remove():
        store = C.store()
        if not store:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        gone = dcim_demo.remove(store, **_dirs())
        if gone:
            wa._audit('dcim_demo_removed', detail={'sites': gone})
        return jsonify({'ok': True, 'removed': gone})

    _ = (api_dcim_demo, api_dcim_demo_install, api_dcim_demo_remove)
