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
    {'id': 'ipban',      'label_key': 'cfg_tab_ipban',         'icon': 'bi-slash-circle'},
    {'id': 'interface',  'label_key': 'cfg_tab_interface',     'icon': 'bi-layout-wtf'},
)


# ── Card registry (categories) ──────────────────────────────────────────────
# Each card is METADATA only: its tab, title (title_key or section-label) and
# icon.  A GENERIC card's ``fields`` are DERIVED from the schema — every option
# whose ``Cfg.card`` equals this id, in registry order — so a field's category is
# declared once, on the option itself (spec.py).  A card with ``renderer`` is
# bespoke: the frontend draws it with a named function and owns its own fields.
# Order within a tab = declaration order.
CARDS: tuple[dict, ...] = (
    # ══ General ═════════════════════════════════════════════════════════════
    {'tab': 'general', 'id': 'global',    'section': 'global',    'icon': 'bi-gear'},
    # (web_admin username/password are first-run bootstrap credentials read in main.py,
    #  managed post-setup in the Users UI — not config-UI fields, so no card here.)
    # External Access = server networking (port / reverse-proxy / public URL / HTTPS /
    # cookie-Secure) — a server concern, so it lives in General next to the web panel,
    # not in the Interface (UI presentation) tab.
    {'tab': 'general', 'id': 'proxy',     'title_key': 'proxy_section', 'icon': 'bi-diagram-3'},
    {'tab': 'general', 'id': 'database',  'section': 'database',  'icon': 'bi-database',
     'renderer': 'database'},
    # Platform self-monitoring (core.health): is my own stack alive, are my certs valid.
    # A core/system concern — deliberately NOT under the Monitoring service tab.
    {'tab': 'general', 'id': 'health', 'title_key': 'cfg_card_platform_health',
     'icon': 'bi-heart-pulse'},
    # Destructive data wipes, gathered in ONE place instead of sitting in the toolbar of
    # the section they erase — a monitoring page is left open all day, and "clear all" is
    # not something to keep one stray click away. The card has no fields of its own: each
    # domain contributes its button as a CONFIG_ACTION on section 'maintenance', so
    # nothing here knows about history or syslog specifically.
    {'tab': 'general', 'id': 'maintenance', 'title_key': 'cfg_card_maintenance',
     'icon': 'bi-trash3'},

    # ══ Monitoring ══════════════════════════════════════════════════════════
    {'tab': 'monitoring', 'id': 'monitoring', 'section': 'monitoring', 'icon': 'bi-activity'},
    {'tab': 'monitoring', 'id': 'modules',    'section': 'modules',    'icon': 'bi-grid-3x3-gap-fill'},

    # ══ Notifications (bespoke: Routing / Providers / Templates sub-tabs) ════
    {'tab': 'notifs', 'id': 'notifications', 'renderer': 'notifications'},

    # ══ Syslog ══════════════════════════════════════════════════════════════
    {'tab': 'syslog', 'id': 'syslog_conn',      'title_key': 'syslog_sec_connection', 'icon': 'bi-ethernet'},
    {'tab': 'syslog', 'id': 'syslog_security',  'title_key': 'syslog_sec_security',   'icon': 'bi-shield-lock'},
    {'tab': 'syslog', 'id': 'syslog_retention', 'title_key': 'syslog_sec_retention',  'icon': 'bi-archive'},
    {'tab': 'syslog', 'id': 'syslog_db', 'section': 'syslog_db', 'icon': 'bi-database-gear',
     'renderer': 'syslog_db'},

    # ══ Authentication ══════════════════════════════════════════════════════
    {'tab': 'auth', 'id': 'pw_policy',      'title_key': 'pw_policy_section',      'icon': 'bi-shield-lock'},
    {'tab': 'auth', 'id': 'login_security', 'title_key': 'login_security_section', 'icon': 'bi-shield-exclamation'},
    # Default roles assigned to newly-created users / groups (authorization concern).
    {'tab': 'auth', 'id': 'default_roles', 'title_key': 'default_roles_section', 'icon': 'bi-person-check'},
    {'tab': 'auth', 'id': 'ldap',  'section': 'ldap',  'icon': 'bi-person-badge',       'renderer': 'auth'},
    {'tab': 'auth', 'id': 'oidc',  'section': 'oidc',  'icon': 'bi-box-arrow-in-right', 'renderer': 'auth'},
    {'tab': 'auth', 'id': 'saml2', 'section': 'saml2', 'icon': 'bi-shield-check',       'renderer': 'auth'},
    {'tab': 'auth', 'id': 'scim',  'section': 'scim',  'title_key': 'scim_section',
     'icon': 'bi-arrow-down-up', 'renderer': 'scim'},   # incl. the SCIM limits subsection

    # ══ fail2ban (Config) ═══════════════════════════════════════════════════
    # Configuration lives here: the SETTINGS (thresholds/durations) and the EXPOSED
    # SERVICES card (per-service default block action — a service-config concern, not
    # live operations). The operational surface (banned IPs, watchlist, history,
    # whitelist) lives in the top-level 'fail2ban' section (#tab-ipban / renderFail2ban).
    {'tab': 'ipban', 'id': 'ipban', 'title_key': 'ipban_section', 'icon': 'bi-slash-circle'},
    {'tab': 'ipban', 'id': 'ipban_services', 'title_key': 'ipban_svc_title',
     'icon': 'bi-hdd-network', 'renderer': 'ipban_services'},

    # ══ Interface (UI presentation) ═════════════════════════════════════════
    {'tab': 'interface', 'id': 'pub_status',  'title_key': 'public_status_section', 'icon': 'bi-globe',
     'renderer': 'pub_status'},
    {'tab': 'interface', 'id': 'audit',       'title_key': 'tab_audit',             'icon': 'bi-journal-text',
     'renderer': 'audit'},
    {'tab': 'interface', 'id': 'tables',      'title_key': 'tables_section',        'icon': 'bi-table',
     'renderer': 'tables'},
    {'tab': 'interface', 'id': 'live_update', 'title_key': 'live_update_section',   'icon': 'bi-arrow-repeat',
     'renderer': 'live_update'},   # bespoke: force_reload_secs is conditionally shown
    {'tab': 'interface', 'id': 'advanced',    'title_key': 'cfg_advanced_section',  'icon': 'bi-tools',
     'renderer': 'advanced'},
)


def _fields_for_card(card_id: str) -> list[str]:
    """The option paths assigned to *card_id* (``Cfg.card``), in registry order."""
    from lib.config.spec import CONFIG_FIELDS  # local import: keep module import-light
    return [f.path for f in CONFIG_FIELDS if f.card == card_id]


def config_layout() -> dict:
    """The config UI layout (tabs + cards) as plain data for the web admin.

    Pure structure — the browser resolves ``label_key`` / ``title_key`` /
    ``section`` labels via i18n and each field's control via the schema
    (``cfg_meta``).  A generic card gets its ``fields`` DERIVED from the schema
    (options with a matching ``Cfg.card``); a ``renderer`` card is drawn by a
    named frontend function.  Single source of truth: the UI can never drift."""
    from lib.config.config_actions import discover_config_actions  # noqa: PLC0415
    from lib.config.group_sources import discover_group_sources  # noqa: PLC0415
    by_section: dict[str, list] = {}
    for a in discover_config_actions():
        by_section.setdefault(a['section'], []).append(a)
    sources = {s['section']: s for s in discover_group_sources()}
    cards = []
    for c in CARDS:
        d = dict(c)
        if 'renderer' not in d:
            d['fields'] = _fields_for_card(d['id'])
        # Buttons a package contributes to this card's section (self-describing; the
        # panel renders them generically and the package ships the JS they name).
        acts = by_section.get(d.get('section') or d['id'])
        if acts:
            d['actions'] = acts
        # Directory group source backing this section, if a provider declares one — the
        # group→role widget renders its fetch button / picker / name lookup from it.
        src = sources.get(d.get('section') or d['id'])
        if src:
            d['group_source'] = src
        cards.append(d)
    return {'tabs': [dict(t) for t in TABS], 'cards': cards}
