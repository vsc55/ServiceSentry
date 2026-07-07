#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widget the users domain owns (see lib.core.overview.discovery)."""


def users_stat(wa) -> dict:
    """Stat content for the ``users`` card: total + a by-role breakdown (role badges
    resolved client-side via the shared role metadata)."""
    from lib.core.permissions import BUILTIN_ROLE_UIDS  # noqa: PLC0415
    viewer_uid = BUILTIN_ROLE_UIDS.get('viewer', '')
    by_role: dict = {}
    for u in wa._users.values():
        r = u.get('role', '')
        r_uid = (wa._role_name_to_uid(r) if not wa._is_uid(r) else r) or viewer_uid
        by_role[r_uid] = by_role.get(r_uid, 0) + 1
    return {'value': len(wa._users),
            'badges': [{'fn': 'role', 'role': r, 'count': n} for r, n in by_role.items()]}


OVERVIEW_WIDGETS = [
    {'id': 'users', 'icon': 'bi-person', 'label_key': 'overview_users',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 40,
     'perms': {'any': ['users_view']}, 'nav': {'tab': '#tab-access', 'sub': '#subtab-users'},
     'stat': users_stat,
     'view': {'kind': 'stat', 'icon': 'bi-person-fill', 'label_key': 'overview_users',
              'accent': 'orange', 'data_url': '/api/v1/overview/widget/users'}},
]
