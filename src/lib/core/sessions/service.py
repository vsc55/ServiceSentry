#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free session helpers — the read view-model and uid/owner lookups extracted from
:mod:`lib.core.sessions.routes`.

Pure functions over plain dicts; no Flask.  The requester-context guards (admin-only,
self-vs-other ownership) and the actual revocation stay in the route — they need the
session and mutate ``wa`` state.
"""

from __future__ import annotations


def build_sessions_view(sessions: dict, users: dict, current_token) -> dict:
    """Project active *sessions* to the API view-model keyed by session uid (token never
    exposed), resolving each session's owner username and flagging the current one."""
    uid_to_name = {d.get('uid', ''): u for u, d in users.items()}
    result: dict = {}
    for token, entry in sessions.items():
        uid      = entry.get('uid') or token[:16]
        user_uid = entry.get('user_uid', '')
        result[uid] = {
            'username':   uid_to_name.get(user_uid, user_uid),
            'user_uid':   user_uid,
            'ip':         entry.get('ip', ''),
            'user_agent': entry.get('user_agent', ''),
            'created':    entry.get('created', ''),
            'last_seen':  entry.get('last_seen', ''),
            'is_current': token == current_token,
        }
    return result


def find_token_by_uid(sessions: dict, uid: str):
    """The session token whose entry has this ``uid`` (``None`` if absent)."""
    return next((t for t, e in sessions.items() if e.get('uid') == uid), None)


def owner_username(users: dict, user_uid: str) -> str:
    """The username owning *user_uid* (empty string if unknown) — for the audit trail."""
    return next((u for u, d in users.items() if d.get('uid') == user_uid), '')
