#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 002: add auth_source='local' to users that lack it."""

ID = '002_add_auth_source'


def run(wa):
    dirty = False
    for udata in wa._users.values():
        if 'auth_source' not in udata:
            udata['auth_source'] = 'local'
            dirty = True
    if dirty:
        wa._persist_users()
