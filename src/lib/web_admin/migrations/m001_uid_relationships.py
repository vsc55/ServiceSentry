#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 001: translate name-based relationships to UIDs.

Converts:
  - group['roles']   : role names  → role UIDs
  - user['role']     : role name   → role UID
  - user['groups']   : group names → group UIDs
"""

ID = '001_uid_relationships'


def run(wa):
    groups_dirty = False
    users_dirty = False

    for gdata in wa._groups.values():
        old_roles = gdata.get('roles', [])
        if not old_roles:
            continue
        new_roles = []
        changed = False
        for r in old_roles:
            if not wa._is_uid(r):
                uid = wa._role_name_to_uid(r)
                if uid:
                    new_roles.append(uid)
                    changed = True
                # unknown role names are silently dropped
            else:
                new_roles.append(r)
        if changed:
            gdata['roles'] = new_roles
            groups_dirty = True

    for udata in wa._users.values():
        role_val = udata.get('role', '')
        if role_val and not wa._is_uid(role_val):
            uid = wa._role_name_to_uid(role_val)
            if uid:
                udata['role'] = uid
                users_dirty = True

        old_groups = udata.get('groups', [])
        if old_groups:
            new_groups = []
            changed = False
            for g in old_groups:
                if not wa._is_uid(g):
                    uid = wa._group_name_to_uid(g)
                    if uid:
                        new_groups.append(uid)
                        changed = True
                    # unknown group names are silently dropped
                else:
                    new_groups.append(g)
            if changed:
                udata['groups'] = new_groups
                users_dirty = True

    if groups_dirty:
        wa._persist_groups()
    if users_dirty:
        wa._persist_users()
