#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SCIM 2.0 provisioning endpoints: /scim/v2/*.

Thin HTTP layer: it owns the bearer-auth gate + per-IP rate limiting and delegates
every operation to :class:`lib.providers.scim.ScimService` (the Flask-independent
provisioning logic).  An IdP (Microsoft Entra ID, Okta…) uses these routes to
PROACTIVELY create/update/deactivate users and groups; authenticated by the
``scim|token`` bearer, independent of the web session.

⚠️  DO NOT rename these paths.  Unlike the rest of the app (``/api/v1/*``, our own
internal API), the ``/scim/v2/*`` URL scheme is MANDATED by the SCIM 2.0 standard
(IETF RFC 7643/7644).  External identity providers are configured with only the base
URL and expect exactly these standard resource paths (``ServiceProviderConfig``,
``Users``, ``Groups``, …).  Changing them — e.g. moving under ``/api/v1/`` — would
break provisioning from every IdP.  These are endpoints we expose FOR OTHERS to call,
so they intentionally live outside our internal API namespace.

Routes registered by this file:

    GET    /scim/v2/ServiceProviderConfig  provider capability document
    GET    /scim/v2/ResourceTypes          supported resource types
    GET    /scim/v2/Schemas                supported schemas document
    GET    /scim/v2/Users                  list/filter users (paginated)
    GET    /scim/v2/Users/<uid>            get a single user
    POST   /scim/v2/Users                  create a user
    PUT    /scim/v2/Users/<uid>            replace a user
    PATCH  /scim/v2/Users/<uid>            patch a user
    DELETE /scim/v2/Users/<uid>            delete a user
    GET    /scim/v2/Groups                 list/filter groups
    GET    /scim/v2/Groups/<gid>           get a single group
    POST   /scim/v2/Groups                 create a group
    PATCH  /scim/v2/Groups/<gid>           patch a group (membership/attrs)
    PUT    /scim/v2/Groups/<gid>           replace a group
    DELETE /scim/v2/Groups/<gid>           delete a group
"""

from flask import jsonify, request

from lib.providers.scim import ScimService, ERR_SCHEMA
from lib.security.ratelimit import RateLimiter


def register(app, wa):
    if not hasattr(wa, '_scim_ratelimit'):
        wa._scim_ratelimit = RateLimiter()

    def _svc():
        """A per-request service bound to this request's public base URL."""
        return ScimService(wa, request.host_url.rstrip('/') + '/scim/v2')

    def _finish(result):
        """Turn a service ``(body, status)`` into a Flask response."""
        body, status = result
        return ('', status) if body == '' else (jsonify(body), status)

    # ── auth gate (bearer token + brute-force throttle) ─────────────────────────
    @app.before_request
    def _scim_gate():
        if not request.path.startswith('/scim/'):
            return None
        if _svc().bearer_ok(request.headers.get('Authorization', '')):
            return None
        # Failed auth: throttle per IP and audit (SCIM has no per-account lockout, so
        # this is the only brute-force signal/limit on the bearer token).
        ip = request.remote_addr or '?'
        allowed, retry = wa._scim_ratelimit.hit(
            ip, max_hits=wa._SCIM_RL_MAX, window_secs=wa._SCIM_RL_WINDOW)
        wa._audit('scim_auth_failed', username='', ip=ip,
                  detail={'path': request.path, 'blocked': not allowed})
        # Feed the internal fail2ban (explicit → also counts the 429 throttle case,
        # and suppresses the generic 401 capture so the ban reason is 'scim_auth_failed').
        wa._ipban_offense('scim_auth_failed')
        if not allowed:
            resp = jsonify({'schemas': [ERR_SCHEMA], 'status': '429',
                            'detail': 'Too many failed SCIM authentication attempts'})
            resp.headers['Retry-After'] = str(retry)
            return resp, 429
        return _finish(ScimService.err(401, 'Unauthorized (SCIM disabled or invalid bearer token)'))

    def _json():
        return request.get_json(silent=True, force=True) or {}

    # ── Discovery / capability documents ────────────────────────────────────────
    @app.route('/scim/v2/ServiceProviderConfig', methods=['GET'])
    def scim_spconfig():
        return _finish(_svc().service_provider_config())

    @app.route('/scim/v2/ResourceTypes', methods=['GET'])
    def scim_resourcetypes():
        return _finish(_svc().resource_types())

    @app.route('/scim/v2/Schemas', methods=['GET'])
    def scim_schemas():
        return _finish(_svc().schemas_doc())

    # ── Users ───────────────────────────────────────────────────────────────────
    @app.route('/scim/v2/Users', methods=['GET'])
    def scim_users_list():
        try:
            start = int(request.args.get('startIndex', 1))
            count = int(request.args.get('count', 100))
        except ValueError:
            start, count = 1, 100
        return _finish(_svc().list_users(request.args.get('filter', ''), start, count))

    @app.route('/scim/v2/Users/<uid>', methods=['GET'])
    def scim_user_get(uid):
        return _finish(_svc().get_user(uid))

    @app.route('/scim/v2/Users', methods=['POST'])
    def scim_user_create():
        return _finish(_svc().create_user(_json()))

    @app.route('/scim/v2/Users/<uid>', methods=['PUT'])
    def scim_user_replace(uid):
        return _finish(_svc().replace_user(uid, _json()))

    @app.route('/scim/v2/Users/<uid>', methods=['PATCH'])
    def scim_user_patch(uid):
        return _finish(_svc().patch_user(uid, _json()))

    @app.route('/scim/v2/Users/<uid>', methods=['DELETE'])
    def scim_user_delete(uid):
        return _finish(_svc().delete_user(uid))

    # ── Groups ──────────────────────────────────────────────────────────────────
    @app.route('/scim/v2/Groups', methods=['GET'])
    def scim_groups_list():
        return _finish(_svc().list_groups(request.args.get('filter', '')))

    @app.route('/scim/v2/Groups/<gid>', methods=['GET'])
    def scim_group_get(gid):
        return _finish(_svc().get_group(gid))

    @app.route('/scim/v2/Groups', methods=['POST'])
    def scim_group_create():
        return _finish(_svc().create_group(_json()))

    @app.route('/scim/v2/Groups/<gid>', methods=['PATCH'])
    def scim_group_patch(gid):
        return _finish(_svc().patch_group(gid, _json()))

    @app.route('/scim/v2/Groups/<gid>', methods=['PUT'])
    def scim_group_replace(gid):
        return _finish(_svc().replace_group(gid, _json()))

    @app.route('/scim/v2/Groups/<gid>', methods=['DELETE'])
    def scim_group_delete(gid):
        return _finish(_svc().delete_group(gid))
