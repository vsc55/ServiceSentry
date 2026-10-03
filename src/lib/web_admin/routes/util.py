#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic utility endpoints: /api/v1/util/*.

Small, feature-agnostic helpers the UI can call — e.g. generating a random
secret/bearer token server-side (single source: :func:`lib.util.generate_token`).

Routes registered by this file:

    GET /api/v1/util/token      a fresh cryptographically-strong random token (hex)
    GET /api/v1/util/timezones  the time zone names this installation can interpret
"""

from flask import jsonify, request

from lib.util import generate_token
from lib.util.timezones import available as _timezones


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/v1/util/timezones', methods=['GET'])
    @wa._login_required
    def api_util_timezones():
        """The time zone names this installation can interpret — possibly none.

        A session and no permission: the zones of the world are nobody's secret, and the first
        screen to want them (a site's) is the worst possible reason to put its permission on
        them. A scheduled report and a maintenance window will want the same list.

        The server answers rather than leaving it to the browser, because the server is what has
        to make sense of a stored value: offering names nothing here can resolve produces
        records nobody can use. And when it has none — Windows without `tzdata`, a slimmed
        container — it says so instead of pretending, so a caller can fall back knowingly.
        """
        zones = list(_timezones())
        return jsonify({'zones': zones, 'source': 'server' if zones else ''})

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
