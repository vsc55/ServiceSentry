#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the clusters domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_clusters',
    'order': 170,
    'permissions': (
        {'flag': 'clusters_view',   'roles': ('editor', 'viewer')},  # view Clusters sub-tab
        {'flag': 'clusters_add',    'roles': ()},                    # create clusters
        {'flag': 'clusters_edit',   'roles': ('editor',)},           # edit/toggle clusters
        {'flag': 'clusters_delete', 'roles': ()},                    # delete clusters
    ),
}
