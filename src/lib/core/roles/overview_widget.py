#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widget the roles domain owns (see lib.core.overview.discovery)."""


def role_meta(wa) -> dict:
    """Shared role metadata (``role_names`` / ``role_keys``) the users/groups/sessions
    by-role badges resolve uids to names with.  Not sensitive (ungated); served in the
    slim overview aggregate so every role badge can render regardless of ``roles_view``."""
    from lib.core.permissions import (BUILTIN_ROLE_PERMISSIONS,  # noqa: PLC0415
                                         BUILTIN_ROLE_UIDS)
    role_names: dict = {}
    role_keys: dict = {}
    for k in BUILTIN_ROLE_PERMISSIONS:
        u = BUILTIN_ROLE_UIDS.get(k, '')
        if not u:
            continue
        ov = wa._builtin_role_overrides.get(u, {})
        role_names[u] = ov.get('name') or wa._builtin_role_names.get(k, k.title())
        role_keys[u] = k
    for u, rd in wa._custom_roles.items():
        if isinstance(rd, dict):
            role_names[u] = rd.get('name', u)
            role_keys[u] = ''
    return {'role_names': role_names, 'role_keys': role_keys}


def roles_stat(wa) -> dict:
    """Stat content for the ``roles`` card: total roles + a custom-roles badge."""
    from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS  # noqa: PLC0415
    custom = len(wa._custom_roles)
    total = len(BUILTIN_ROLE_PERMISSIONS) + custom
    return {'value': total,
            'badges': ([{'plain': True, 'key': 'overview_custom_roles', 'args': [custom]}]
                       if custom else [])}
