#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Central *presentation* layout for the configuration UI.

:mod:`lib.config.spec` is the single source of truth for each option's *data*
(type / default / range / env / admin_only / validation).  This module adds the
single source of truth for its *presentation*: which sub-tab and card an option
lives in, in what order, with which icon — so the web admin renders the config
screen from data instead of hardcoding the structure in JavaScript.

Shape
-----
``TABS``  — ordered list of the config sub-tabs::

    {'id', 'label_key', 'icon'}

``CARDS`` — ordered list of the collapsible cards, each pinned to a tab::

    {'tab', 'id', 'icon',
     'title_key'  : i18n key for the card title (split cards), OR
     'section'    : config section whose i18n label titles the card,
     'fields'     : ['section|field', …]  — scalar fields rendered generically,
     'renderer'   : 'database' | 'auth' | 'audit' | …  — a bespoke card the
                    frontend renders with a named function (no generic fields)}

A card is EITHER generic (has ``fields``) or bespoke (has ``renderer``).  The
frontend maps ``renderer`` to the matching JS function; everything else it draws
generically from the field list + the per-field schema (``cfg_meta``).

``config_layout()`` returns ``{'tabs': TABS, 'cards': [...]}`` — served to the
browser so ``renderConfig`` consumes it (see routes/config/schema.py).
"""

from __future__ import annotations


# ── Sub-tabs (order = display order) ─────────────────────────────────────────
TABS: tuple[dict, ...] = (
    {'id': 'general',    'label_key': 'cfg_tab_general',       'icon': 'bi-sliders'},
    {'id': 'monitoring', 'label_key': 'cfg_tab_monitoring',    'icon': 'bi-activity'},
    {'id': 'notifs',     'label_key': 'cfg_tab_notifications', 'icon': 'bi-bell'},
    {'id': 'syslog',     'label_key': 'cfg_tab_syslog',        'icon': 'bi-hdd-stack'},
    {'id': 'auth',       'label_key': 'cfg_tab_auth',          'icon': 'bi-person-lock'},
    {'id': 'interface',  'label_key': 'cfg_tab_interface',     'icon': 'bi-layout-wtf'},
)


# ── Cards (order within a tab = declaration order) ───────────────────────────
# 'fields' → generic (rendered from the schema); 'renderer' → a bespoke card.
CARDS: tuple[dict, ...] = (
    # ══ General ═════════════════════════════════════════════════════════════
    {'tab': 'general', 'id': 'global', 'section': 'global', 'icon': 'bi-gear',
     'fields': ['global|log_level']},
    # web_admin "Web Panel": the core web_admin fields NOT split into the other
    # cards below (rendered exclude-based, so username/password/host are included
    # exactly as before) — a bespoke card.
    {'tab': 'general', 'id': 'web_admin', 'section': 'web_admin', 'icon': 'bi-gear',
     'renderer': 'web_panel'},
    {'tab': 'general', 'id': 'database', 'section': 'database', 'icon': 'bi-database',
     'renderer': 'database'},
    {'tab': 'general', 'id': 'users', 'section': 'users', 'icon': 'bi-gear',
     'fields': ['users|default_role']},
    {'tab': 'general', 'id': 'groups', 'section': 'groups', 'icon': 'bi-gear',
     'fields': ['groups|default_role']},

    # ══ Monitoring ══════════════════════════════════════════════════════════
    {'tab': 'monitoring', 'id': 'monitoring', 'section': 'monitoring', 'icon': 'bi-activity',
     'fields': ['monitoring|enabled', 'monitoring|autostart', 'monitoring|timer_check']},
    {'tab': 'monitoring', 'id': 'modules', 'section': 'modules', 'icon': 'bi-grid-3x3-gap-fill',
     'fields': ['modules|threads', 'modules|timeout']},

    # ══ Notifications (bespoke: Routing / Providers / Templates sub-tabs) ════
    {'tab': 'notifs', 'id': 'notifications', 'renderer': 'notifications'},

    # ══ Syslog ══════════════════════════════════════════════════════════════
    {'tab': 'syslog', 'id': 'syslog_conn', 'title_key': 'syslog_sec_connection', 'icon': 'bi-ethernet',
     'fields': ['syslog|enabled', 'syslog|autostart', 'syslog|bind_host',
                'syslog|udp_port', 'syslog|tcp_port', 'syslog|tls_port']},
    {'tab': 'syslog', 'id': 'syslog_security', 'title_key': 'syslog_sec_security', 'icon': 'bi-shield-lock',
     'fields': ['syslog|tls_cert', 'syslog|tls_key', 'syslog|allowed_sources']},
    {'tab': 'syslog', 'id': 'syslog_retention', 'title_key': 'syslog_sec_retention', 'icon': 'bi-archive',
     'fields': ['syslog|retention_days', 'syslog|max_rows']},
    {'tab': 'syslog', 'id': 'syslog_db', 'section': 'syslog_db', 'icon': 'bi-database-gear',
     'renderer': 'syslog_db'},

    # ══ Authentication ══════════════════════════════════════════════════════
    {'tab': 'auth', 'id': 'pw_policy', 'title_key': 'pw_policy_section', 'icon': 'bi-shield-lock',
     'fields': ['web_admin|pw_min_len', 'web_admin|pw_max_len', 'web_admin|pw_require_upper',
                'web_admin|pw_require_digit', 'web_admin|pw_require_symbol']},
    {'tab': 'auth', 'id': 'login_security', 'title_key': 'login_security_section', 'icon': 'bi-shield-exclamation',
     'fields': ['web_admin|lockout_max_attempts', 'web_admin|lockout_duration_secs']},
    {'tab': 'auth', 'id': 'ldap', 'section': 'ldap', 'icon': 'bi-person-badge', 'renderer': 'auth'},
    {'tab': 'auth', 'id': 'oidc', 'section': 'oidc', 'icon': 'bi-box-arrow-in-right', 'renderer': 'auth'},
    {'tab': 'auth', 'id': 'saml2', 'section': 'saml2', 'icon': 'bi-shield-check', 'renderer': 'auth'},

    # ══ Interface & web deployment ══════════════════════════════════════════
    {'tab': 'interface', 'id': 'proxy', 'title_key': 'proxy_section', 'icon': 'bi-diagram-3',
     'fields': ['web_admin|port', 'web_admin|proxy_count', 'web_admin|public_url',
                'web_admin|force_https', 'web_admin|force_fqdn']},
    {'tab': 'interface', 'id': 'pub_status', 'title_key': 'public_status_section', 'icon': 'bi-globe',
     'renderer': 'pub_status'},
    {'tab': 'interface', 'id': 'audit', 'title_key': 'tab_audit', 'icon': 'bi-journal-text',
     'renderer': 'audit'},
    {'tab': 'interface', 'id': 'tables', 'title_key': 'tables_section', 'icon': 'bi-table',
     'renderer': 'tables'},
    {'tab': 'interface', 'id': 'live_update', 'title_key': 'live_update_section', 'icon': 'bi-arrow-repeat',
     'renderer': 'live_update'},
    {'tab': 'interface', 'id': 'advanced', 'title_key': 'cfg_advanced_section', 'icon': 'bi-tools',
     'renderer': 'advanced'},
)


def config_layout() -> dict:
    """The config UI layout (tabs + cards) as plain data for the web admin.

    Pure structure — the browser resolves ``label_key`` / ``title_key`` /
    ``section`` labels via i18n and each field's control via the schema
    (``cfg_meta``).  Returned verbatim from the registry so the UI can never
    drift from this single source of truth."""
    return {
        'tabs': [dict(t) for t in TABS],
        'cards': [dict(c) for c in CARDS],
    }
