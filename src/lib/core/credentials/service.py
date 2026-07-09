#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free credential helpers — the pure transformations extracted from
:mod:`lib.core.credentials.routes`.

CRUD, uniqueness and encryption already live in :class:`~lib.core.credentials.store.
CredentialsStore`, so this module only holds the route logic that isn't the store's job:
scanning where a credential is referenced, building a clone payload + candidate names, and
resolving the identity for a test connection.  Pure functions over plain dicts; no Flask.
"""

from __future__ import annotations


def find_credential_usage(uid: str, hosts: list, modules: dict) -> dict:
    """Where credential *uid* is referenced: hosts (ssh profile ``cred_uid``) and module
    checks (inline ``cred_uid``).  Returns ``{'hosts': [...], 'checks': [...]}``."""
    used_hosts = []
    for h in hosts:
        ssh = (h.get('profiles') or {}).get('ssh') or {}
        if ssh.get('cred_uid') == uid:
            used_hosts.append({'uid': h.get('uid'), 'name': h.get('name')})
    checks = []
    for mod_key, mod_cfg in modules.items():
        if not isinstance(mod_cfg, dict):
            continue
        bare = mod_key.split('.')[-1]
        for coll, items in mod_cfg.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            for key, item in items.items():
                if isinstance(item, dict) and item.get('cred_uid') == uid:
                    checks.append({'module': bare, 'key': key,
                                   'label': str(item.get('label') or key)})
    return {'hosts': used_hosts, 'checks': checks}


def clone_payload(src: dict) -> dict:
    """The name-less clone body (ctype/description/data) for duplicating credential *src*;
    the caller supplies a free name from :func:`clone_candidate_names`."""
    return {
        'ctype':       src.get('ctype', 'ssh'),
        'description': src.get('description', ''),
        'data':        src.get('data') or {},
    }


def clone_candidate_names(base: str, suffix: str, limit: int = 100):
    """Yield candidate names for a clone: ``"<base> <suffix>"`` then ``"… <suffix> 2"`` …
    up to *limit*.  The caller tries each until the store accepts a free one."""
    for n in range(1, limit):
        yield f'{base} {suffix}' if n == 1 else f'{base} {suffix} {n}'


def resolve_test_identity(data: dict, stored_data: dict) -> dict:
    """Overlay a stored credential's secrets onto an inline test *data* dict: fill masked or
    empty ``ssh_password``/``ssh_key_string`` from storage, and default the non-secret
    ``ssh_user``/``ssh_auth_method``/``ssh_key`` when absent.  Mutates and returns *data*."""
    for k in ('ssh_password', 'ssh_key_string'):
        if data.get(k) in (None, '') and stored_data.get(k):
            data[k] = stored_data[k]
    for k in ('ssh_user', 'ssh_auth_method', 'ssh_key'):
        data.setdefault(k, stored_data.get(k))
    return data
