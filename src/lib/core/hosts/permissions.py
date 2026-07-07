#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the servers domain owns (the host registry — see
:mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_servers',
    'order': 160,
    'permissions': (
        {'flag': 'servers_view',   'roles': ('editor', 'viewer')},  # view the servers tab
        {'flag': 'servers_add',    'roles': ()},                    # add modules/checks to a server
        {'flag': 'servers_edit',   'roles': ('editor',)},           # edit servers / host-bound checks
        {'flag': 'servers_delete', 'roles': ()},                    # delete servers
    ),
}
