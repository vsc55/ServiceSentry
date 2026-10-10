#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Brand routes: the pictures an installation shows, and changing them.

Routes registered by this file:

    GET    /brand/<slot>             A brand picture (public: the sign-in page shows them);
                                     ``?download=1`` hands it over as a file
    GET    /api/v1/brand             The name and what each slot holds
    POST   /api/v1/brand/<slot>      Upload a slot's picture (multipart ``file`` or raw body)
    DELETE /api/v1/brand/<slot>      Back to the shipped picture
    POST   /api/v1/brand/<slot>/stock  Copy the shipped picture in as the installation's own

The name itself is a config field (``brand|name``) and is saved with the rest of the
configuration; ``GET /api/v1/brand`` only reports it, and whether ``SS_BRAND_NAME`` locks it.
"""

from __future__ import annotations

from flask import Response, jsonify, request, send_file, session

from lib.core.brand import service as brand_svc


def register(app, wa):
    view_req = wa._perm_required('config_view')
    edit_req = wa._perm_required('config_edit')

    def _store():
        return getattr(wa, '_brand_store', None)

    @app.route('/brand/<slot>', methods=['GET'])
    def brand_picture(slot):
        """A slot's picture: the installation's own, or the shipped file.

        Public, like ``/favicon.ico``: the sign-in page shows the logo before anybody has a
        session. Nothing here is secret — it is what the login screen shows to anyone.

        Versioned URLs (``?v=`` matching the current one) are kept for a year; anything else
        for five minutes, so a bookmark or a stale page still catches a change. An SVG goes out
        with a content policy that runs nothing, as the second lock after the upload check.
        """
        if slot not in brand_svc.SLOTS:
            return Response(status=404)
        store = _store()
        own = store.meta().get(slot) if store is not None else None
        got = store.get(slot) if own else None
        if got:
            resp = Response(got[0], mimetype=got[1])
            version = own['sha'][:16]
        else:
            resp = send_file(brand_svc.default_file(slot),
                             mimetype=brand_svc.MIME.get(brand_svc.default_kind(slot)))
            version = None
        pedida = request.args.get('v', '')
        fija = bool(pedida) and (version is None and pedida.startswith('d') or pedida == version)
        resp.headers['Cache-Control'] = ('public, max-age=31536000, immutable' if fija
                                         else 'public, max-age=300')
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        if (got and got[1] == brand_svc.MIME['svg']) or (not got and slot != 'email'
                                                         and brand_svc.default_kind(slot) == 'svg'):
            resp.headers['Content-Security-Policy'] = (
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox")
        if request.args.get('download'):
            # As a file, to keep: the stored picture is the ADJUSTED one — cropped and resized
            # in the dialog — and nothing else holds a copy of it. Named after the slot, with
            # the extension its bytes say. Asked from the screen.
            mime = got[1] if got else brand_svc.MIME.get(brand_svc.default_kind(slot), '')
            ext = {v: k for k, v in brand_svc.MIME.items()}.get(mime, 'bin')
            resp.headers['Content-Disposition'] = f'attachment; filename="brand-{slot}.{ext}"'
            resp.headers['Cache-Control'] = 'no-store'
        return resp

    @app.route('/api/v1/brand', methods=['GET'])
    @view_req
    def api_brand():
        meta = _store().meta() if _store() is not None else {}
        slots = {}
        for slot, spec in brand_svc.SLOTS.items():
            own = meta.get(slot)
            # What is shown now measures: the own picture's stored size, or the stock file's.
            if own:
                actual = (own.get('width', 0), own.get('height', 0))
            else:
                try:
                    with open(brand_svc.default_file(slot), 'rb') as fh:
                        actual = brand_svc.image_size(fh.read(65536)) or (0, 0)
                except OSError:
                    actual = (0, 0)
            slots[slot] = {
                'own': bool(own),
                'src': wa._brand_src(slot),
                'mime': wa._brand_mime(slot),
                'size': (own or {}).get('size', 0),
                'width': (own or {}).get('width', 0),
                'height': (own or {}).get('height', 0),
                'kinds': list(spec['kinds']),
                'max': spec['max'],
                'shape': spec['shape'], 'min_px': spec['min'], 'max_px': spec['top'],
                'rec': list(spec['rec']), 'now': list(actual),
            }
        return jsonify({'name': wa._brand_name(),
                        'name_locked': 'brand|name' in (getattr(wa, '_env_locked', None) or ()),
                        'slots': slots})

    @app.route('/api/v1/brand/<slot>', methods=['POST'])
    @edit_req
    def api_brand_upload(slot):
        store = _store()
        if store is None or slot not in brand_svc.SLOTS:
            return jsonify({'error': wa._t('brand_bad_slot')}), 404
        limite = brand_svc.SLOTS[slot]['max']
        up = (request.files or {}).get('file')
        data = up.read(limite + 1) if up is not None else (request.get_data() or b'')[:limite + 1]
        kind, err = brand_svc.check(slot, data)
        if err:
            return jsonify({'error': wa._t(err)}), 400
        err, args = brand_svc.check_size(slot, data)
        if err:
            texto = wa._t(err)
            for a in args:
                texto = texto.replace('{}', str(a), 1)
            return jsonify({'error': texto}), 400
        w, h = brand_svc.image_size(data) or (0, 0)
        sha = store.put(slot, data, brand_svc.MIME[kind], width=w, height=h,
                        actor=session.get('username', ''))
        wa._audit('brand_asset_set', detail={'slot': slot, 'kind': kind, 'size': len(data),
                                             'sha': sha[:16]})
        return jsonify({'ok': True, 'src': wa._brand_src(slot)})

    @app.route('/api/v1/brand/<slot>/stock', methods=['POST'])
    @edit_req
    def api_brand_from_stock(slot):
        """The shipped picture, copied in as if it had been uploaded: a starting point that is
        the installation's own — it stays when the product's pictures change, and it can be
        adjusted and reset like any other. Through the same checks as an upload."""
        store = _store()
        if store is None or slot not in brand_svc.SLOTS:
            return jsonify({'error': wa._t('brand_bad_slot')}), 404
        try:
            with open(brand_svc.default_file(slot), 'rb') as fh:
                data = fh.read()
        except OSError:
            return jsonify({'error': wa._t('brand_empty')}), 404
        kind, err = brand_svc.check(slot, data)
        if err:
            return jsonify({'error': wa._t(err)}), 400
        w, h = brand_svc.image_size(data) or (0, 0)
        sha = store.put(slot, data, brand_svc.MIME[kind], width=w, height=h,
                        actor=session.get('username', ''))
        wa._audit('brand_asset_set', detail={'slot': slot, 'kind': kind, 'size': len(data),
                                             'sha': sha[:16], 'from': 'stock'})
        return jsonify({'ok': True, 'src': wa._brand_src(slot)})

    @app.route('/api/v1/brand/<slot>', methods=['DELETE'])
    @edit_req
    def api_brand_reset(slot):
        store = _store()
        if store is None or slot not in brand_svc.SLOTS:
            return jsonify({'error': wa._t('brand_bad_slot')}), 404
        if store.delete(slot):
            wa._audit('brand_asset_reset', detail={'slot': slot})
        return jsonify({'ok': True, 'src': wa._brand_src(slot)})
