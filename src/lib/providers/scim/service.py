#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SCIM 2.0 provisioning service — Flask-independent domain logic.

Every operation returns a ``(body, status)`` tuple where ``body`` is a plain dict
(a SCIM resource, ListResponse, or Error) or ``''`` (204 No Content); the web layer
turns it into an HTTP response.  The service reads/writes the host WebAdmin's user
and group stores via the ``wa`` handle, so it carries no request state beyond the
public base URL used to build ``meta.location``.
"""

from __future__ import annotations

import hmac
import uuid

from lib.web_admin.constants import BUILTIN_ROLE_UIDS, SYSTEM_USER, _BUILTIN_GROUPS

USER_SCHEMA  = 'urn:ietf:params:scim:schemas:core:2.0:User'
GROUP_SCHEMA = 'urn:ietf:params:scim:schemas:core:2.0:Group'
LIST_SCHEMA  = 'urn:ietf:params:scim:api:messages:2.0:ListResponse'
ERR_SCHEMA   = 'urn:ietf:params:scim:api:messages:2.0:Error'
PATCH_SCHEMA = 'urn:ietf:params:scim:api:messages:2.0:PatchOp'


# ── stateless helpers (no wa/request needed) ────────────────────────────────────
def bearer_token_ok(auth_header: str, token: str, min_len: int) -> bool:
    """Constant-time check of a ``Bearer <token>`` header against the configured
    token.  Rejects an unset/too-short token (weak-token floor)."""
    token = str(token or '')
    if len(token) < min_len:
        return False
    if not auth_header.startswith('Bearer '):
        return False
    return hmac.compare_digest(auth_header[7:], token)


def parse_filter_eq(filter_str: str, attr: str):
    """Parse a simple ``attr eq "value"`` SCIM filter; return the value or None."""
    f = (filter_str or '').strip()
    pre = f'{attr.lower()} eq '
    if f.lower().startswith(pre):
        v = f[len(pre):].strip()
        return v[1:-1] if len(v) >= 2 and v[0] in '"\'' else v
    return None


def scim_user_fields(body: dict):
    """Extract ``(email, display_name, active)`` from a SCIM User payload."""
    emails = body.get('emails') or []
    email = ''
    if isinstance(emails, list) and emails:
        email = (next((e for e in emails if isinstance(e, dict) and e.get('primary')), emails[0])
                 or {}).get('value', '') if isinstance(emails[0], dict) else ''
    name = body.get('displayName') or (body.get('name') or {}).get('formatted') or ''
    return email, name, bool(body.get('active', True))


class ScimService:
    """SCIM provisioning operations over a WebAdmin instance."""

    def __init__(self, wa, base: str):
        self.wa = wa
        self.base = base            # e.g. https://host/scim/v2 — for meta.location

    # ── config / auth ──────────────────────────────────────────────────────────
    def _cfg(self) -> dict:
        return self.wa._config_section('scim') or {}

    def _auto_disable(self) -> bool:
        return bool(self._cfg().get('auto_disable', True))

    def bearer_ok(self, auth_header: str) -> bool:
        cfg = self._cfg()
        if not cfg.get('enabled'):
            return False
        return bearer_token_ok(auth_header, cfg.get('token'), self.wa._SCIM_MIN_TOKEN_LEN)

    def _default_role_uid(self):
        dr = str(self._cfg().get('default_role') or '')
        uid = dr if self.wa._is_uid(dr) else (
            self.wa._role_name_to_uid(dr or 'none') or self.wa._role_name_to_uid('none'))
        # Never let the IdP mass-provision admins: a misconfigured scim|default_role
        # pointing at the built-in admin role is downgraded to none.
        if uid and uid == BUILTIN_ROLE_UIDS.get('admin'):
            return self.wa._role_name_to_uid('none')
        return uid

    # ── error / list envelopes ─────────────────────────────────────────────────
    @staticmethod
    def err(status, detail, scim_type=None):
        body = {'schemas': [ERR_SCHEMA], 'status': str(status), 'detail': detail}
        if scim_type:
            body['scimType'] = scim_type
        return body, status

    @staticmethod
    def _list(resources, total=None, start=1):
        return {
            'schemas':      [LIST_SCHEMA],
            'totalResults': total if total is not None else len(resources),
            'startIndex':   start,
            'itemsPerPage': len(resources),
            'Resources':    resources,
        }, 200

    # ── guards ──────────────────────────────────────────────────────────────────
    def deny_group_write(self, gid, g):
        """SCIM may only mutate groups it owns. Reject built-in groups (would let a
        token add admins / delete the Administrators group) and any non-SCIM group."""
        if gid in _BUILTIN_GROUPS:
            return self.err(403, 'Built-in groups cannot be modified via SCIM', 'mutability')
        if (g or {}).get('source') != 'scim':
            return self.err(403, 'Only SCIM-managed groups can be modified via SCIM', 'mutability')
        return None

    def deny_user_write(self, u):
        """SCIM may only mutate the users it provisioned — never local/LDAP/OIDC/SAML2
        accounts (e.g. the local Administrator)."""
        if (u or {}).get('auth_source') != 'scim':
            return self.err(403, 'Only SCIM-provisioned users can be modified via SCIM', 'mutability')
        return None

    # ── lookups ──────────────────────────────────────────────────────────────────
    def _user_by_id(self, uid):
        for username, u in self.wa._users.items():
            if u.get('uid') == uid:
                return username, u
        return None, None

    def _group_member_ids(self, group_uid):
        return [u['uid'] for u in self.wa._users.values()
                if group_uid in (u.get('groups') or []) and u.get('uid')]

    def _group_by_external_id(self, ext_id):
        if not ext_id:
            return None, None
        for egid, eg in self.wa._groups.items():
            if eg.get('source') == 'scim' and eg.get('external_id') == ext_id:
                return egid, eg
        return None, None

    def _set_member(self, user_uid, group_uid, add):
        for u in self.wa._users.values():
            if u.get('uid') == user_uid:
                gl = list(u.get('groups') or [])
                if add and group_uid not in gl:
                    gl.append(group_uid)
                elif not add and group_uid in gl:
                    gl.remove(group_uid)
                u['groups'] = gl
                return True
        return False

    # ── serialization ─────────────────────────────────────────────────────────
    def user_to_scim(self, username, u):
        name = u.get('display_name', '') or ''
        return {
            'schemas':    [USER_SCHEMA],
            'id':         u.get('uid', ''),
            'userName':   username,
            'externalId': u.get('auth_source_id', '') or '',
            'name':       {'formatted': name},
            'displayName': name,
            'emails':     ([{'value': u['email'], 'primary': True}] if u.get('email') else []),
            'active':     bool(u.get('enabled', True)),
            'meta':       {'resourceType': 'User', 'location': f"{self.base}/Users/{u.get('uid','')}"},
        }

    def group_to_scim(self, uid, g):
        d = {
            'schemas':     [GROUP_SCHEMA],
            'id':          uid,
            'displayName': g.get('name', uid),
            'members':     [{'value': mid} for mid in self._group_member_ids(uid)],
            'meta':        {'resourceType': 'Group', 'location': f"{self.base}/Groups/{uid}"},
        }
        if g.get('external_id'):
            d['externalId'] = g['external_id']
        return d

    # ── audit snapshots (before/after) ──────────────────────────────────────────
    @staticmethod
    def _user_snap(u):
        return {'display_name': u.get('display_name', ''), 'email': u.get('email', ''),
                'enabled': bool(u.get('enabled', True)), 'role': u.get('role', ''),
                'groups': sorted(u.get('groups') or []),
                'external_id': u.get('auth_source_id', '')}

    def _group_snap(self, gid, g):
        return {'name': g.get('name', ''), 'source': g.get('source', 'local'),
                'enabled': bool(g.get('enabled', True)),
                'members': sorted(self._group_member_ids(gid))}

    def _audit_change(self, event, ident, before=None, after=None):
        """Record a SCIM mutation. On an update (both snapshots) keep ONLY the fields
        that changed; create/delete keep the full snapshot. Actor = system (automated
        IdP push); the IdP's source IP is captured by wa._audit()."""
        detail = dict(ident)
        if before is not None and after is not None:
            keys = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
            detail['before'] = {k: before.get(k) for k in keys}
            detail['after']  = {k: after.get(k) for k in keys}
        elif before is not None:
            detail['before'] = before
        elif after is not None:
            detail['after'] = after
        self.wa._audit(event, username=SYSTEM_USER, detail=detail)

    # ── discovery / capability documents ────────────────────────────────────────
    def service_provider_config(self):
        return {
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig'],
            'patch':          {'supported': True},
            'bulk':           {'supported': False, 'maxOperations': 0, 'maxPayloadSize': 0},
            'filter':         {'supported': True, 'maxResults': 200},
            'changePassword': {'supported': False},
            'sort':           {'supported': False},
            'etag':           {'supported': False},
            'authenticationSchemes': [{
                'type': 'oauthbearertoken', 'name': 'OAuth Bearer Token',
                'description': 'Authentication via the SCIM bearer token.',
            }],
        }, 200

    def resource_types(self):
        return self._list([
            {'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ResourceType'],
             'id': 'User', 'name': 'User', 'endpoint': '/Users', 'schema': USER_SCHEMA,
             'meta': {'resourceType': 'ResourceType', 'location': f'{self.base}/ResourceTypes/User'}},
            {'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ResourceType'],
             'id': 'Group', 'name': 'Group', 'endpoint': '/Groups', 'schema': GROUP_SCHEMA,
             'meta': {'resourceType': 'ResourceType', 'location': f'{self.base}/ResourceTypes/Group'}},
        ])

    def schemas_doc(self):
        return self._list([{'id': USER_SCHEMA, 'name': 'User'},
                           {'id': GROUP_SCHEMA, 'name': 'Group'}])

    # ── Users ─────────────────────────────────────────────────────────────────
    def list_users(self, filter_str, start, count):
        want = parse_filter_eq(filter_str, 'userName')
        if want is not None:
            u = self.wa._users.get(want)
            return self._list([self.user_to_scim(want, u)] if u else [], total=1 if u else 0)
        start = max(1, start)
        count = min(max(0, count), 200)          # cap = maxResults
        items = list(self.wa._users.items())
        page = items[start - 1: start - 1 + count]
        return self._list([self.user_to_scim(n, u) for n, u in page],
                          total=len(items), start=start)

    def get_user(self, uid):
        username, u = self._user_by_id(uid)
        if not u:
            return self.err(404, f'User {uid} not found')
        return self.user_to_scim(username, u), 200

    def create_user(self, body):
        username = (body.get('userName') or '').strip()
        if not username:
            return self.err(400, 'userName is required', 'invalidValue')
        if username in self.wa._users:
            return self.err(409, f'User {username} already exists', 'uniqueness')
        email, name, active = scim_user_fields(body)
        user = {
            'uid':            str(uuid.uuid4()),
            'auth_source':    'scim',
            'auth_source_id': body.get('externalId', '') or '',
            'display_name':   name,
            'email':          email,
            'role':           self._default_role_uid(),
            'groups':         [],
            'enabled':        active,
            'lang':           '',
        }
        self.wa._users[username] = user
        self.wa._persist_users()
        self._audit_change('scim_user_created', {'username': username}, after=self._user_snap(user))
        return self.user_to_scim(username, user), 201

    def replace_user(self, uid, body):
        username, u = self._user_by_id(uid)
        if not u:
            return self.err(404, f'User {uid} not found')
        deny = self.deny_user_write(u)
        if deny:
            return deny
        before = self._user_snap(u)
        email, name, active = scim_user_fields(body)
        u['display_name']   = name
        u['email']          = email
        u['enabled']        = active if self._auto_disable() or active else u.get('enabled', True)
        u['auth_source_id'] = body.get('externalId', u.get('auth_source_id', ''))
        self.wa._persist_users()
        after = self._user_snap(u)
        if after != before:
            self._audit_change('scim_user_updated', {'username': username}, before, after)
        return self.user_to_scim(username, u), 200

    def patch_user(self, uid, body):
        username, u = self._user_by_id(uid)
        if not u:
            return self.err(404, f'User {uid} not found')
        deny = self.deny_user_write(u)
        if deny:
            return deny
        before = self._user_snap(u)
        for op in (body.get('Operations') or [])[:100]:   # cap ops (parity w/ group PATCH)
            path = (op.get('path') or '').lower()
            val = op.get('value')
            # Entra sends {"op":"replace","value":{"active":false}} or with path "active".
            if isinstance(val, dict) and 'active' in val:
                val, path = val.get('active'), 'active'
            if path == 'active':
                new_active = str(val).lower() not in ('false', '0', 'none', '')
                if new_active or self._auto_disable():
                    u['enabled'] = new_active
            elif path in ('displayname', 'name.formatted'):
                u['display_name'] = str(val or '')
            elif path.startswith('emails'):
                if isinstance(val, list) and val:
                    u['email'] = (val[0] or {}).get('value', '') if isinstance(val[0], dict) else str(val[0])
                elif val:
                    u['email'] = str(val)
        self.wa._persist_users()
        after = self._user_snap(u)
        if after != before:
            self._audit_change('scim_user_updated', {'username': username}, before, after)
        return self.user_to_scim(username, u), 200

    def delete_user(self, uid):
        username, u = self._user_by_id(uid)
        if not u:
            return self.err(404, f'User {uid} not found')
        deny = self.deny_user_write(u)
        if deny:
            return deny
        before = self._user_snap(u)
        self.wa._users.pop(username, None)
        self.wa._persist_users()
        self._audit_change('scim_user_deleted', {'username': username}, before=before)
        return '', 204

    # ── Groups ────────────────────────────────────────────────────────────────
    def list_groups(self, filter_str):
        want = parse_filter_eq(filter_str, 'displayName')
        res = [self.group_to_scim(gid, g) for gid, g in self.wa._groups.items()
               if want is None or g.get('name') == want]
        return self._list(res)

    def get_group(self, gid):
        g = self.wa._groups.get(gid)
        if not g:
            return self.err(404, f'Group {gid} not found')
        return self.group_to_scim(gid, g), 200

    def create_group(self, body):
        name = (body.get('displayName') or '').strip()
        if not name:
            return self.err(400, 'displayName is required', 'invalidValue')
        ext_id = (body.get('externalId') or '').strip()
        members = [m['value'] for m in (body.get('members') or [])[:self.wa._SCIM_MAX_MEMBERS]
                   if isinstance(m, dict) and m.get('value')]

        # Re-provision: if a SCIM group with this externalId already exists (typically
        # one we soft-deleted on de-assignment), REACTIVATE it instead of creating a
        # duplicate — its role→role mapping is preserved. Members sync to the new set.
        egid, eg = self._group_by_external_id(ext_id)
        if eg is not None:
            before = self._group_snap(egid, eg)
            eg['enabled'] = True
            eg['name'] = name
            for muid in self._group_member_ids(egid):     # replace membership with the new set
                self._set_member(muid, egid, False)
            for mid in members:
                self._set_member(mid, egid, True)
            self.wa._persist_groups()
            self.wa._persist_users()
            after = self._group_snap(egid, eg)
            if after != before:
                self._audit_change('scim_group_updated', {'name': name}, before, after)
            return self.group_to_scim(egid, eg), 201

        gid = str(uuid.uuid4())
        self.wa._groups[gid] = {'uid': gid, 'name': name, 'description': 'SCIM', 'enabled': True,
                                'source': 'scim', 'external_id': ext_id, 'roles': []}
        self.wa._persist_groups()
        for mid in members:
            self._set_member(mid, gid, True)
        self.wa._persist_users()
        self._audit_change('scim_group_created', {'name': name},
                           after=self._group_snap(gid, self.wa._groups[gid]))
        return self.group_to_scim(gid, self.wa._groups[gid]), 201

    def patch_group(self, gid, body):
        g = self.wa._groups.get(gid)
        if not g:
            return self.err(404, f'Group {gid} not found')
        deny = self.deny_group_write(gid, g)
        if deny:
            return deny
        before = self._group_snap(gid, g)
        changed = False
        for op in (body.get('Operations') or [])[:100]:
            action = (op.get('op') or '').lower()
            path = (op.get('path') or '').lower()
            val = op.get('value')
            if path == 'members' or path.startswith('members'):
                members = (val if isinstance(val, list) else ([val] if val else []))[:self.wa._SCIM_MAX_MEMBERS]
                if action == 'replace':
                    for muid in self._group_member_ids(gid):
                        self._set_member(muid, gid, False)
                for m in members:
                    mid = m.get('value') if isinstance(m, dict) else m
                    if mid:
                        self._set_member(mid, gid, action != 'remove')
                changed = True
            elif path == 'displayname' and isinstance(val, str):
                g['name'] = val
                self.wa._persist_groups()
            elif isinstance(val, dict) and 'displayName' in val:
                g['name'] = val['displayName']
                self.wa._persist_groups()
        if changed:
            self.wa._persist_users()
        after = self._group_snap(gid, g)
        if after != before:
            self._audit_change('scim_group_updated', {'name': g.get('name', gid)}, before, after)
        return self.group_to_scim(gid, g), 200

    def replace_group(self, gid, body):
        g = self.wa._groups.get(gid)
        if not g:
            return self.err(404, f'Group {gid} not found')
        deny = self.deny_group_write(gid, g)
        if deny:
            return deny
        before = self._group_snap(gid, g)
        if body.get('displayName'):
            g['name'] = body['displayName']
            self.wa._persist_groups()
        for muid in self._group_member_ids(gid):
            self._set_member(muid, gid, False)
        for m in (body.get('members') or [])[:self.wa._SCIM_MAX_MEMBERS]:
            mid = m.get('value') if isinstance(m, dict) else m
            if mid:
                self._set_member(mid, gid, True)
        self.wa._persist_users()
        after = self._group_snap(gid, g)
        if after != before:
            self._audit_change('scim_group_updated', {'name': g.get('name', gid)}, before, after)
        return self.group_to_scim(gid, g), 200

    def delete_group(self, gid):
        g = self.wa._groups.get(gid)
        if not g:
            return self.err(404, f'Group {gid} not found')
        deny = self.deny_group_write(gid, g)
        if deny:
            return deny
        before = self._group_snap(gid, g)
        # SOFT delete: Entra deprovisions a group with DELETE (SCIM groups have no
        # `active`). Disable it instead of removing it — a disabled group grants none of
        # its roles (permissions honour `enabled`), yet its role→role mapping and
        # membership are preserved, so a later re-assignment (POST with the same
        # externalId) restores everything. The admin can still hard-delete it via the UI.
        g['enabled'] = False
        self.wa._persist_groups()
        after = self._group_snap(gid, g)
        self._audit_change('scim_group_deleted', {'name': g.get('name', gid)}, before, after)
        return '', 204
