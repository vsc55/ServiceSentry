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


# Wiping the audit log lives in Config → General → Maintenance, not in the Audit toolbar:
# that page stays open all day, one stray click from erasing the trail. Mirrors what the
# history and syslog domains contribute; the fn ships with the audit UI.
CONFIG_ACTIONS = [
    {'section': 'maintenance', 'id': 'audit_clear_all',
     'label_key': 'audit_clear_all', 'tooltip_key': 'audit_clear_all_tt',
     'icon': 'bi-trash3', 'variant': 'danger', 'order': 30,
     'button_key': 'act_wipe', 'group_label_key': 'cfg_actions_group_wipe', 'desc_key': 'audit_clear_all_desc',
     'perm': 'audit_delete', 'fn': 'confirmClearAudit'},
]


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


# What this package writes to the audit log, and how loud each one is. Declared
# rather than guessed from the event name: the badge is the only thing a glance
# down two hundred rows gives you, and deriving it from a noun made the colour
# depend on what somebody called the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    # The audit domain's own two.
    {'key': 'audit_cleared', 'severity': 'danger'},
    {'key': 'audit_entry_deleted', 'severity': 'danger'},

    # And the web layer's, which has no manifest of its own: `lib.web_admin` is not one of
    # the discovery roots (they are the domains, services and providers), and the events are
    # written by the request lifecycle rather than by any one domain — a login, a rejected
    # CSRF token, a crash inside a handler. They live with the audit domain because "what an
    # audit event means" is what this package is for. Everything else that used to sit here
    # went home: notify, permissions, scim, oidc and saml each declare their own now.
    {'key': 'login_ok', 'severity': 'success'},
    {'key': 'login_failed', 'severity': 'danger'},
    {'key': 'login_throttled', 'severity': 'warning'},
    {'key': 'logout', 'severity': 'warning'},
    {'key': 'csrf_failed', 'severity': 'danger'},
    {'key': 'internal_error', 'severity': 'danger'},
    {'key': 'language_changed', 'severity': 'muted'},
    # Written by the config panel when it rotates the Entra secret from the web UI; the
    # provider declares the rest of its events itself.
    # Raised from lib/util when any store fails to persist — no package owns it.
    {'key': 'file_write_error', 'severity': 'danger'},
    # A background service coming up, reported from lib/services/__init__.py.
]
