#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the audit domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_audit',   # i18n key for the role-editor group heading
    'order': 140,                  # core domains ordered after the services (10–40)
    'permissions': (
        {'flag': 'audit_view',   'roles': ('editor', 'viewer')},  # read audit log
        {'flag': 'audit_delete', 'roles': ()},                    # delete audit entries
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import activity_rows, failed_login_rows  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'failed_logins', 'icon': 'bi-shield-lock', 'label_key': 'overview_failed_logins',
     'cols': 4, 'h': 140, 'has_h': True, 'order': 150,
     'perms': {'any': ['audit_view']}, 'nav': {'tab': '#tab-audit'},
     'rows': failed_login_rows,
     'view': {'kind': 'table', 'icon': 'bi-shield-lock', 'title_key': 'overview_failed_logins',
              'accent': 'rose', 'data_url': '/api/v1/overview/widget/failed_logins',
              'empty_key': 'status_empty', 'columns': [
                  {'key': 'ts',     'label_key': 'col_time',   'sortable': True, 'cell': 'date'},
                  {'key': 'user',   'label_key': 'col_user',   'sortable': True, 'cell': 'code'},
                  {'key': 'ip',     'label_key': 'col_ip',     'sortable': True, 'cell': 'code'},
                  {'key': 'detail', 'label_key': 'col_detail', 'sortable': True, 'cell': 'login_detail'},
              ]}},
    {'id': 'activity', 'icon': 'bi-clock-history', 'label_key': 'overview_recent_activity',
     'cols': 4, 'h': 340, 'has_h': True, 'order': 180,
     'perms': {'any': ['audit_view']}, 'nav': {'tab': '#tab-audit'},
     'rows': activity_rows,
     'view': {'kind': 'table', 'icon': 'bi-clock-history', 'title_key': 'overview_recent_activity',
              'accent': 'slate', 'data_url': '/api/v1/overview/widget/activity',
              'empty_key': 'status_empty', 'columns': [
                  {'key': 'ts',    'label_key': 'col_time',  'sortable': True, 'cell': 'date'},
                  {'key': 'event', 'label_key': 'col_event', 'sortable': True, 'cell': 'event_badge'},
                  {'key': 'user',  'label_key': 'col_user',  'sortable': True, 'cell': 'code'},
              ]}},
]
