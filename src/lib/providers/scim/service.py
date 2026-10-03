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

from lib.core.constants import (BUILTIN_GROUP_UID_SET, BUILTIN_ROLE_UIDS,
                                SYSTEM_USER, is_reserved_username)
from lib.core.uids import new_uid

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


# Who PROVISIONED an account is a different fact from how it last signed in. ``auth_source``
# answers the second — every SSO sign-in rewrites it — so SCIM ownership kept there was lost
# the first time a provisioned user signed in through OIDC/SAML/LDAP, and from then on the IdP
# could no longer deactivate or delete them: the deprovisioning push answered 403 and the
# account (with its API tokens and remember-me sessions) stayed alive. These two fields live
# in the users store's ``extra`` JSON and no sign-in path writes them.
PROVISIONED_BY = 'provisioned_by'
SCIM_EXTERNAL_ID = 'scim_external_id'


def remember_provisioning(user: dict) -> None:
    """Pin a SCIM-provisioned account's ownership before a sign-in re-links it.

    Called by every SSO ``sync_user`` right before it overwrites ``auth_source`` /
    ``auth_source_id``. Accounts created by SCIM already carry the marker; this covers the
    ones provisioned before it existed, while ``auth_source`` still says ``scim``.
    """
    if not isinstance(user, dict) or user.get(PROVISIONED_BY):
        return
    if str(user.get('auth_source') or '') == 'scim':
        user[PROVISIONED_BY] = 'scim'
        user.setdefault(SCIM_EXTERNAL_ID, user.get('auth_source_id', '') or '')


def is_scim_managed(user: dict) -> bool:
    """True when SCIM owns this account's lifecycle: provisioned by SCIM (whatever it signs
    in with now) or still marked ``scim``. An account an administrator explicitly turned
    back into a LOCAL one is not — that is a decision to take it out of the IdP's hands."""
    u = user or {}
    src = str(u.get('auth_source') or 'local')
    if src == 'scim':
        return True
    return u.get(PROVISIONED_BY) == 'scim' and src not in ('', 'local')


def scim_user_fields(body: dict):
    """Extract ``(email, display_name, active)`` from a SCIM User payload."""
    emails = body.get('emails') or []
    email = ''
    if isinstance(emails, list) and emails:
        email = (next((e for e in emails if isinstance(e, dict) and e.get('primary')), emails[0])
                 or {}).get('value', '') if isinstance(emails[0], dict) else ''
    name = body.get('displayName') or (body.get('name') or {}).get('formatted') or ''
    return email, name, bool(body.get('active', True))


def _external_id(u: dict) -> str:
    """The IdP's externalId for a user — kept apart from ``auth_source_id`` once SCIM
    provisioned it, since an SSO sign-in overwrites the latter with its own subject."""
    u = u or {}
    if SCIM_EXTERNAL_ID in u:
        return u.get(SCIM_EXTERNAL_ID) or ''
    return u.get('auth_source_id', '') or ''


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
        """True when SCIM is enabled and *auth_header* carries the configured bearer
        token (constant-time compare, weak-token floor). Used by the route auth gate."""
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
        """Build a SCIM Error ``(body, status)`` with *detail* and an optional
        ``scimType`` (e.g. ``uniqueness``, ``mutability``, ``invalidValue``)."""
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
        if gid in BUILTIN_GROUP_UID_SET:
            return self.err(403, 'Built-in groups cannot be modified via SCIM', 'mutability')
        if (g or {}).get('source') != 'scim':
            return self.err(403, 'Only SCIM-managed groups can be modified via SCIM', 'mutability')
        return None

    def deny_user_write(self, u):
        """SCIM may only mutate the users it provisioned — never local/LDAP/OIDC/SAML2
        accounts (e.g. the local Administrator). "Provisioned" is the ``provisioned_by``
        marker, not ``auth_source``, which each SSO sign-in rewrites (see
        :func:`is_scim_managed`)."""
        if not is_scim_managed(u):
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
        """Serialize an internal user dict to a SCIM User resource (id, userName,
        externalId, name, emails, active, meta.location)."""
        name = u.get('display_name', '') or ''
        return {
            'schemas':    [USER_SCHEMA],
            'id':         u.get('uid', ''),
            'userName':   username,
            'externalId': _external_id(u),
            'name':       {'formatted': name},
            'displayName': name,
            'emails':     ([{'value': u['email'], 'primary': True}] if u.get('email') else []),
            'active':     bool(u.get('enabled', True)),
            'meta':       {'resourceType': 'User', 'location': f"{self.base}/Users/{u.get('uid','')}"},
        }

    def group_to_scim(self, uid, g):
        """Serialize an internal group dict to a SCIM Group resource, expanding its
        members from the users that reference *uid* (id, displayName, members,
        meta.location, and externalId when present)."""
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
                'external_id': _external_id(u)}

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
        """Return the SCIM ``ServiceProviderConfig`` document advertising supported
        capabilities (patch + filter on, bulk/sort/etag/changePassword off) and the
        OAuth bearer auth scheme."""
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
        """Return the SCIM ``ResourceTypes`` ListResponse (the User and Group types
        with their endpoints and schema URNs)."""
        return self._list([
            {'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ResourceType'],
             'id': 'User', 'name': 'User', 'endpoint': '/Users', 'schema': USER_SCHEMA,
             'meta': {'resourceType': 'ResourceType', 'location': f'{self.base}/ResourceTypes/User'}},
            {'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ResourceType'],
             'id': 'Group', 'name': 'Group', 'endpoint': '/Groups', 'schema': GROUP_SCHEMA,
             'meta': {'resourceType': 'ResourceType', 'location': f'{self.base}/ResourceTypes/Group'}},
        ])

    def schemas_doc(self):
        """Return the SCIM ``Schemas`` ListResponse (the supported User and Group
        schema URNs)."""
        return self._list([{'id': USER_SCHEMA, 'name': 'User'},
                           {'id': GROUP_SCHEMA, 'name': 'Group'}])

    # ── Users ─────────────────────────────────────────────────────────────────
    def list_users(self, filter_str, start, count):
        """List users as a SCIM ListResponse. A ``userName eq "…"`` filter returns
        the single matching user; otherwise pages the full set (1-based *start*,
        *count* capped at 200)."""
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
        """Return the SCIM User with internal id *uid*, or a 404 error tuple."""
        username, u = self._user_by_id(uid)
        if not u:
            return self.err(404, f'User {uid} not found')
        return self.user_to_scim(username, u), 200

    def create_user(self, body):
        """Provision a new SCIM user from *body*.

        Requires ``userName`` (409 on collision); assigns the SCIM default role
        (never admin — see :meth:`_default_role_uid`), persists the users store and
        audits the creation. Returns the created User with 201, or an error tuple.
        """
        username = (body.get('userName') or '').strip()
        if not username:
            return self.err(400, 'userName is required', 'invalidValue')
        # A provisioned `system` or `anonymous` would own audit entries that read as the
        # panel's own, or as an unauthenticated caller's. Refused as an invalid value rather
        # than as a conflict: the name is not taken, it is not available at all.
        if is_reserved_username(username):
            return self.err(400, f'userName {username} is reserved', 'invalidValue')
        if username in self.wa._users:
            return self.err(409, f'User {username} already exists', 'uniqueness')
        email, name, active = scim_user_fields(body)
        user = {
            'uid':            new_uid(),
            'auth_source':    'scim',
            'auth_source_id': body.get('externalId', '') or '',
            PROVISIONED_BY:   'scim',
            SCIM_EXTERNAL_ID: body.get('externalId', '') or '',
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
        """Replace (PUT) a SCIM-provisioned user's attributes from *body* (display
        name, email, active, externalId). 404 if unknown, 403 for a non-SCIM account.
        Persists and audits only the fields that actually changed; returns the User."""
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
        ext = body.get('externalId', _external_id(u))
        u[SCIM_EXTERNAL_ID] = ext
        if u.get('auth_source') == 'scim':
            # Only while SCIM is also how it signs in: after an SSO sign-in this is the
            # IdP's subject/DN, and overwriting it would unlink the account from its IdP.
            u['auth_source_id'] = ext
        self.wa._persist_users()
        after = self._user_snap(u)
        if after != before:
            self._audit_change('scim_user_updated', {'username': username}, before, after)
        return self.user_to_scim(username, u), 200

    def patch_user(self, uid, body):
        """Apply a SCIM PatchOp to a SCIM-provisioned user (up to 100 ops): active
        (enable/disable), displayName/name.formatted and emails. Tolerates Entra's
        value-object form. 404 if unknown, 403 for a non-SCIM account; persists and
        audits only real changes; returns the User."""
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
        """Delete a SCIM-provisioned user (hard delete). 404 if unknown, 403 for a
        non-SCIM account. Persists, audits, and returns ``('', 204)``."""
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
        """List groups as a SCIM ListResponse, optionally narrowed by a
        ``displayName eq "…"`` filter."""
        want = parse_filter_eq(filter_str, 'displayName')
        res = [self.group_to_scim(gid, g) for gid, g in self.wa._groups.items()
               if want is None or g.get('name') == want]
        return self._list(res)

    def get_group(self, gid):
        """Return the SCIM Group with uid *gid*, or a 404 error tuple."""
        g = self.wa._groups.get(gid)
        if not g:
            return self.err(404, f'Group {gid} not found')
        return self.group_to_scim(gid, g), 200

    def create_group(self, body):
        """Provision a SCIM group from *body* (``displayName`` required).

        If a SCIM group with the same ``externalId`` already exists (typically one
        soft-deleted on de-assignment) it is REACTIVATED and its membership replaced
        with the new set — preserving its role mapping — instead of creating a
        duplicate. Members are capped at ``_SCIM_MAX_MEMBERS``. Persists users +
        groups, audits, and returns the Group with 201.
        """
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

        gid = new_uid()
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
        """Apply a SCIM PatchOp to a SCIM-owned group (up to 100 ops): membership
        add/remove/replace (capped at ``_SCIM_MAX_MEMBERS``) and displayName. 404 if
        unknown, 403 for a built-in or non-SCIM group. Persists, audits real changes,
        returns the Group."""
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
        """Replace (PUT) a SCIM-owned group: set displayName and reset membership to
        the ``members`` in *body* (capped at ``_SCIM_MAX_MEMBERS``). 404 if unknown,
        403 for a built-in or non-SCIM group. Persists, audits real changes, returns
        the Group."""
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
        """SOFT-delete a SCIM-owned group: disable it (a disabled group grants none of
        its roles) while preserving its role mapping and membership, so a later
        re-assignment with the same externalId can restore it. 404 if unknown, 403 for
        a built-in or non-SCIM group. Persists, audits, returns ``('', 204)``."""
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
