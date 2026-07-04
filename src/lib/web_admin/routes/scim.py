#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SCIM 2.0 provisioning endpoints: /scim/v2/*.

Lets an IdP (Microsoft Entra ID, Okta…) PROACTIVELY create/update/deactivate users
and groups in ServiceSentry — unlike JIT provisioning, users appear before their
first login and are disabled when their assignment is removed.

Authenticated by a bearer token (``scim|token``, the secret the IdP is configured
with), independent of the web session.  Users are stored with ``auth_source: 'scim'``;
SCIM groups map to ServiceSentry groups (the admin assigns roles to those groups, and
members inherit them via the normal group→role mechanism).
"""

import hmac
import uuid

from flask import jsonify, request

_USER_SCHEMA  = 'urn:ietf:params:scim:schemas:core:2.0:User'
_GROUP_SCHEMA = 'urn:ietf:params:scim:schemas:core:2.0:Group'
_LIST_SCHEMA  = 'urn:ietf:params:scim:api:messages:2.0:ListResponse'
_ERR_SCHEMA   = 'urn:ietf:params:scim:api:messages:2.0:Error'
_PATCH_SCHEMA = 'urn:ietf:params:scim:api:messages:2.0:PatchOp'


def register(app, wa):

    # ── helpers ───────────────────────────────────────────────────────────────
    def _cfg():
        return wa._config_section('scim') or {}

    def _base():
        return request.host_url.rstrip('/') + '/scim/v2'

    def _err(status, detail, scim_type=None):
        body = {'schemas': [_ERR_SCHEMA], 'status': str(status), 'detail': detail}
        if scim_type:
            body['scimType'] = scim_type
        return jsonify(body), status

    def _authed():
        cfg = _cfg()
        if not cfg.get('enabled'):
            return False
        token = str(cfg.get('token') or '')
        if not token:
            return False
        hdr = request.headers.get('Authorization', '')
        if not hdr.startswith('Bearer '):
            return False
        return hmac.compare_digest(hdr[7:], token)

    def _default_role_uid():
        dr = str(_cfg().get('default_role') or '')
        if wa._is_uid(dr):
            return dr
        return wa._role_name_to_uid(dr or 'none') or wa._role_name_to_uid('none')

    def _user_by_id(uid):
        """Find a user (keyed by username) by its stable SCIM id (= user uid)."""
        for username, u in wa._users.items():
            if u.get('uid') == uid:
                return username, u
        return None, None

    def _group_member_ids(group_uid):
        return [u['uid'] for u in wa._users.values()
                if group_uid in (u.get('groups') or []) and u.get('uid')]

    def _user_to_scim(username, u):
        name = u.get('display_name', '') or ''
        return {
            'schemas':    [_USER_SCHEMA],
            'id':         u.get('uid', ''),
            'userName':   username,
            'externalId': u.get('auth_source_id', '') or '',
            'name':       {'formatted': name},
            'displayName': name,
            'emails':     ([{'value': u['email'], 'primary': True}] if u.get('email') else []),
            'active':     bool(u.get('enabled', True)),
            'meta':       {'resourceType': 'User', 'location': f"{_base()}/Users/{u.get('uid','')}"},
        }

    def _group_to_scim(uid, g):
        return {
            'schemas':     [_GROUP_SCHEMA],
            'id':          uid,
            'displayName': g.get('name', uid),
            'members':     [{'value': mid} for mid in _group_member_ids(uid)],
            'meta':        {'resourceType': 'Group', 'location': f"{_base()}/Groups/{uid}"},
        }

    def _list(resources, total=None, start=1):
        return jsonify({
            'schemas':      [_LIST_SCHEMA],
            'totalResults': total if total is not None else len(resources),
            'startIndex':   start,
            'itemsPerPage': len(resources),
            'Resources':    resources,
        })

    def _scim_user_fields(body):
        """Extract (email, display_name, active) from a SCIM User payload."""
        emails = body.get('emails') or []
        email = ''
        if isinstance(emails, list) and emails:
            email = (next((e for e in emails if isinstance(e, dict) and e.get('primary')), emails[0])
                     or {}).get('value', '') if isinstance(emails[0], dict) else ''
        name = body.get('displayName') or (body.get('name') or {}).get('formatted') or ''
        active = body.get('active', True)
        return email, name, bool(active)

    def _filter_eq(attr):
        """Parse a simple `attr eq "value"` filter; return the value or None."""
        f = (request.args.get('filter') or '').strip()
        low = f.lower()
        pre = f'{attr.lower()} eq '
        if low.startswith(pre):
            v = f[len(pre):].strip()
            return v[1:-1] if len(v) >= 2 and v[0] in '"\'' else v
        return None

    # ── SCIM auth gate for every /scim route ────────────────────────────────────
    @app.before_request
    def _scim_gate():
        if request.path.startswith('/scim/') and not _authed():
            return _err(401, 'Unauthorized (SCIM disabled or invalid bearer token)')
        return None

    # ── Discovery / capability documents ────────────────────────────────────────
    @app.route('/scim/v2/ServiceProviderConfig', methods=['GET'])
    def scim_spconfig():
        return jsonify({
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig'],
            'patch':         {'supported': True},
            'bulk':          {'supported': False, 'maxOperations': 0, 'maxPayloadSize': 0},
            'filter':        {'supported': True, 'maxResults': 200},
            'changePassword': {'supported': False},
            'sort':          {'supported': False},
            'etag':          {'supported': False},
            'authenticationSchemes': [{
                'type': 'oauthbearertoken', 'name': 'OAuth Bearer Token',
                'description': 'Authentication via the SCIM bearer token.',
            }],
        })

    @app.route('/scim/v2/ResourceTypes', methods=['GET'])
    def scim_resourcetypes():
        return _list([
            {'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ResourceType'],
             'id': 'User', 'name': 'User', 'endpoint': '/Users', 'schema': _USER_SCHEMA,
             'meta': {'resourceType': 'ResourceType', 'location': f'{_base()}/ResourceTypes/User'}},
            {'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ResourceType'],
             'id': 'Group', 'name': 'Group', 'endpoint': '/Groups', 'schema': _GROUP_SCHEMA,
             'meta': {'resourceType': 'ResourceType', 'location': f'{_base()}/ResourceTypes/Group'}},
        ])

    @app.route('/scim/v2/Schemas', methods=['GET'])
    def scim_schemas():
        return _list([{'id': _USER_SCHEMA, 'name': 'User'},
                      {'id': _GROUP_SCHEMA, 'name': 'Group'}])

    # ── Users ───────────────────────────────────────────────────────────────────
    @app.route('/scim/v2/Users', methods=['GET'])
    def scim_users_list():
        want = _filter_eq('userName')
        if want is not None:
            u = wa._users.get(want)
            return _list([_user_to_scim(want, u)] if u else [], total=1 if u else 0)
        try:
            start = max(1, int(request.args.get('startIndex', 1)))
            count = max(0, int(request.args.get('count', 100)))
        except ValueError:
            start, count = 1, 100
        items = [(n, u) for n, u in wa._users.items()]
        page = items[start - 1: start - 1 + count]
        return _list([_user_to_scim(n, u) for n, u in page], total=len(items), start=start)

    @app.route('/scim/v2/Users/<uid>', methods=['GET'])
    def scim_user_get(uid):
        username, u = _user_by_id(uid)
        if not u:
            return _err(404, f'User {uid} not found')
        return jsonify(_user_to_scim(username, u))

    @app.route('/scim/v2/Users', methods=['POST'])
    def scim_user_create():
        body = request.get_json(silent=True, force=True) or {}
        username = (body.get('userName') or '').strip()
        if not username:
            return _err(400, 'userName is required', 'invalidValue')
        if username in wa._users:
            return _err(409, f'User {username} already exists', 'uniqueness')
        email, name, active = _scim_user_fields(body)
        user = {
            'uid':            str(uuid.uuid4()),
            'auth_source':    'scim',
            'auth_source_id': body.get('externalId', '') or '',
            'display_name':   name,
            'email':          email,
            'role':           _default_role_uid(),
            'groups':         [],
            'enabled':        active,
            'lang':           '',
        }
        wa._users[username] = user
        wa._persist_users()
        wa._audit('scim_user_created', detail={'username': username})
        return jsonify(_user_to_scim(username, user)), 201

    @app.route('/scim/v2/Users/<uid>', methods=['PUT'])
    def scim_user_replace(uid):
        username, u = _user_by_id(uid)
        if not u:
            return _err(404, f'User {uid} not found')
        body = request.get_json(silent=True, force=True) or {}
        email, name, active = _scim_user_fields(body)
        u['display_name']   = name
        u['email']          = email
        u['enabled']        = active if _cfg().get('auto_disable', True) or active else u.get('enabled', True)
        u['auth_source_id'] = body.get('externalId', u.get('auth_source_id', ''))
        wa._persist_users()
        wa._audit('scim_user_updated', detail={'username': username})
        return jsonify(_user_to_scim(username, u))

    @app.route('/scim/v2/Users/<uid>', methods=['PATCH'])
    def scim_user_patch(uid):
        username, u = _user_by_id(uid)
        if not u:
            return _err(404, f'User {uid} not found')
        body = request.get_json(silent=True, force=True) or {}
        for op in (body.get('Operations') or []):
            path = (op.get('path') or '').lower()
            val = op.get('value')
            # Entra sends {"op":"replace","value":{"active":false}} or with path "active".
            if isinstance(val, dict) and 'active' in val:
                val, path = val.get('active'), 'active'
            if path == 'active':
                new_active = str(val).lower() not in ('false', '0', 'none', '')
                if new_active or _cfg().get('auto_disable', True):
                    u['enabled'] = new_active
            elif path in ('displayname', 'name.formatted'):
                u['display_name'] = str(val or '')
            elif path.startswith('emails'):
                if isinstance(val, list) and val:
                    u['email'] = (val[0] or {}).get('value', '') if isinstance(val[0], dict) else str(val[0])
                elif val:
                    u['email'] = str(val)
        wa._persist_users()
        wa._audit('scim_user_updated', detail={'username': username})
        return jsonify(_user_to_scim(username, u))

    @app.route('/scim/v2/Users/<uid>', methods=['DELETE'])
    def scim_user_delete(uid):
        username, u = _user_by_id(uid)
        if not u:
            return _err(404, f'User {uid} not found')
        wa._users.pop(username, None)
        wa._persist_users()
        wa._audit('scim_user_deleted', detail={'username': username})
        return '', 204

    # ── Groups ──────────────────────────────────────────────────────────────────
    def _set_member(user_uid, group_uid, add):
        for u in wa._users.values():
            if u.get('uid') == user_uid:
                gl = list(u.get('groups') or [])
                if add and group_uid not in gl:
                    gl.append(group_uid)
                elif not add and group_uid in gl:
                    gl.remove(group_uid)
                u['groups'] = gl
                return True
        return False

    @app.route('/scim/v2/Groups', methods=['GET'])
    def scim_groups_list():
        want = _filter_eq('displayName')
        res = []
        for gid, g in wa._groups.items():
            if want is not None and g.get('name') != want:
                continue
            res.append(_group_to_scim(gid, g))
        return _list(res)

    @app.route('/scim/v2/Groups/<gid>', methods=['GET'])
    def scim_group_get(gid):
        g = wa._groups.get(gid)
        if not g:
            return _err(404, f'Group {gid} not found')
        return jsonify(_group_to_scim(gid, g))

    @app.route('/scim/v2/Groups', methods=['POST'])
    def scim_group_create():
        body = request.get_json(silent=True, force=True) or {}
        name = (body.get('displayName') or '').strip()
        if not name:
            return _err(400, 'displayName is required', 'invalidValue')
        gid = str(uuid.uuid4())
        wa._groups[gid] = {'uid': gid, 'name': name, 'description': 'SCIM', 'enabled': True,
                           'source': 'scim', 'roles': []}
        wa._persist_groups()
        for m in (body.get('members') or []):
            if isinstance(m, dict) and m.get('value'):
                _set_member(m['value'], gid, True)
        wa._persist_users()
        wa._audit('scim_group_created', detail={'name': name})
        return jsonify(_group_to_scim(gid, wa._groups[gid])), 201

    @app.route('/scim/v2/Groups/<gid>', methods=['PATCH'])
    def scim_group_patch(gid):
        g = wa._groups.get(gid)
        if not g:
            return _err(404, f'Group {gid} not found')
        body = request.get_json(silent=True, force=True) or {}
        changed = False
        for op in (body.get('Operations') or []):
            action = (op.get('op') or '').lower()
            path = (op.get('path') or '').lower()
            val = op.get('value')
            if path == 'members' or path.startswith('members'):
                members = val if isinstance(val, list) else ([val] if val else [])
                if action == 'replace':
                    for uid in _group_member_ids(gid):
                        _set_member(uid, gid, False)
                for m in members:
                    mid = m.get('value') if isinstance(m, dict) else m
                    if mid:
                        _set_member(mid, gid, action != 'remove')
                changed = True
            elif path == 'displayname' and isinstance(val, str):
                g['name'] = val
                wa._persist_groups()
            elif isinstance(val, dict) and 'displayName' in val:
                g['name'] = val['displayName']
                wa._persist_groups()
        if changed:
            wa._persist_users()
        wa._audit('scim_group_updated', detail={'name': g.get('name', gid)})
        return jsonify(_group_to_scim(gid, g))

    @app.route('/scim/v2/Groups/<gid>', methods=['PUT'])
    def scim_group_replace(gid):
        g = wa._groups.get(gid)
        if not g:
            return _err(404, f'Group {gid} not found')
        body = request.get_json(silent=True, force=True) or {}
        if body.get('displayName'):
            g['name'] = body['displayName']
            wa._persist_groups()
        for uid in _group_member_ids(gid):
            _set_member(uid, gid, False)
        for m in (body.get('members') or []):
            mid = m.get('value') if isinstance(m, dict) else m
            if mid:
                _set_member(mid, gid, True)
        wa._persist_users()
        wa._audit('scim_group_updated', detail={'name': g.get('name', gid)})
        return jsonify(_group_to_scim(gid, g))

    @app.route('/scim/v2/Groups/<gid>', methods=['DELETE'])
    def scim_group_delete(gid):
        g = wa._groups.get(gid)
        if not g:
            return _err(404, f'Group {gid} not found')
        for uid in _group_member_ids(gid):
            _set_member(uid, gid, False)
        wa._groups.pop(gid, None)
        wa._persist_groups()
        wa._persist_users()
        wa._audit('scim_group_deleted', detail={'name': g.get('name', gid)})
        return '', 204
