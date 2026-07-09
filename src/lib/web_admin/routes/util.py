#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic utility endpoints: /api/v1/util/*.

Small, feature-agnostic helpers the UI can call — e.g. generating a random
secret/bearer token server-side (single source: :func:`lib.util.generate_token`).

Routes registered by this file:

    GET /api/v1/util/token  a fresh cryptographically-strong random token (hex)
"""

from flask import jsonify, request

from lib.util import generate_token


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/v1/util/token', methods=['GET'])
    @config_edit_req
    def api_util_token():
        """Return a fresh cryptographically-strong random token (hex).  Used by
        the config UI's "generate token" buttons; nothing is stored server-side."""
        try:
            nbytes = int(request.args.get('bytes', 32))
        except (TypeError, ValueError):
            nbytes = 32
        return jsonify({'token': generate_token(nbytes)})
