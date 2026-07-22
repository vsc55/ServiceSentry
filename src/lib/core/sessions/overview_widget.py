#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the sessions domain owns (see lib.core.overview.discovery)."""


def session_stat(wa) -> dict:
    """Stat content for the ``sessions`` card: active count + a by-role breakdown (role
    badges resolved client-side via the shared role metadata)."""
    from lib.core.permissions import BUILTIN_ROLE_UIDS  # noqa: PLC0415
    uid_to_name = {d.get('uid', ''): u for u, d in wa._users.items()}
    by_role: dict = {}
    for s in wa._sessions.values():
        if not isinstance(s, dict):
            continue
        uname = uid_to_name.get(s.get('user_uid', ''), s.get('user_uid', ''))
        u = wa._users.get(uname) if uname else None
        if isinstance(u, dict):
            r = u.get('role', '')
            r_uid = (wa._role_name_to_uid(r) if not wa._is_uid(r) else r) \
                or BUILTIN_ROLE_UIDS.get('viewer', '')
            if r_uid:
                by_role[r_uid] = by_role.get(r_uid, 0) + 1
    return {'value': len(wa._sessions),
            'badges': [{'fn': 'role', 'role': r, 'count': n} for r, n in by_role.items()]}


def session_rows(wa, f: str = '') -> list:
    """Active-session rows for the sessions_list table (user/ip/agent/last_seen),
    newest first — fetched over AJAX by the generic table renderer."""
    uid_to_name = {d.get('uid', ''): u for u, d in wa._users.items()}
    rows = []
    for s in wa._sessions.values():
        if not isinstance(s, dict):
            continue
        uname = uid_to_name.get(s.get('user_uid', ''), s.get('user_uid', ''))
        rows.append({'user': uname, 'ip': s.get('ip', ''), 'agent': s.get('user_agent', ''),
                     'created': s.get('created', ''), 'last_seen': s.get('last_seen', '')})
    rows.sort(key=lambda x: str(x.get('last_seen') or ''), reverse=True)
    return rows
