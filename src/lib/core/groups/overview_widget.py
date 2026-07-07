#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widget the groups domain owns (see lib.core.overview.discovery)."""


def groups_stat(wa) -> dict:
    """Stat content for the ``groups`` card: total + a by-role breakdown (a group counts
    toward each role it carries), falling back to a member count."""
    by_role: dict = {}
    for g in wa._groups.values():
        if not isinstance(g, dict):
            continue
        for r in g.get('roles', []) or []:
            r_uid = (wa._role_name_to_uid(r) if not wa._is_uid(r) else r) or r
            if r_uid:
                by_role[r_uid] = by_role.get(r_uid, 0) + 1
    members = sum(len(g.get('members', [])) for g in wa._groups.values() if isinstance(g, dict))
    badges = [{'fn': 'role', 'role': r, 'count': n} for r, n in by_role.items()]
    if not badges and members:
        badges = [{'plain': True, 'key': 'overview_members', 'args': [members]}]
    return {'value': len(wa._groups), 'badges': badges}


OVERVIEW_WIDGETS = [
    {'id': 'groups', 'icon': 'bi-people', 'label_key': 'overview_groups',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 50,
     'perms': {'any': ['groups_view']}, 'nav': {'tab': '#tab-access', 'sub': '#subtab-groups'},
     'stat': groups_stat,
     'view': {'kind': 'stat', 'icon': 'bi-people-fill', 'label_key': 'overview_groups',
              'accent': 'emerald', 'data_url': '/api/v1/overview/widget/groups'}},
]
