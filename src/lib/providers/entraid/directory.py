#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — directory reads (groups).  Pure Graph calls that take an
app-only access token; raise ``RuntimeError`` (Graph message) on an API error."""

from __future__ import annotations

import requests as _req

from lib.providers.entraid.client import GRAPH_BASE, graph_error


def fetch_groups(access_token: str, limit: int = 5000) -> list[dict]:
    """Return ``[{id, name}]`` for every directory group (paged, sorted by name)."""
    groups: list[dict] = []
    url = f'{GRAPH_BASE}/groups?$select=id,displayName&$top=999'
    hdrs = {'Authorization': f'Bearer {access_token}'}
    while url and len(groups) < limit:
        r = _req.get(url, headers=hdrs, timeout=15)
        if not r.ok:
            raise RuntimeError(graph_error(r))
        body = r.json()
        for g in body.get('value', []):
            groups.append({'id': g['id'], 'name': g.get('displayName') or g['id']})
        url = body.get('@odata.nextLink')
    groups.sort(key=lambda g: g['name'].lower())
    return groups


def lookup_group(access_token: str, group_id: str):
    """Return a group's display name, ``None`` if it doesn't exist (404).
    Raises ``RuntimeError`` on other API errors."""
    r = _req.get(f'{GRAPH_BASE}/groups/{group_id}?$select=id,displayName',
                 headers={'Authorization': f'Bearer {access_token}'}, timeout=15)
    if r.status_code == 404:
        return None
    if not r.ok:
        raise RuntimeError(graph_error(r))
    return r.json().get('displayName') or group_id
