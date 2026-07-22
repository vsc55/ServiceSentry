#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web-specific constants for the administration server.

The RBAC model (roles / permissions / built-in role UIDs and grants + the
per-instance permission-key validators) lives in :mod:`lib.core.permissions`, and
the i18n surface (``DEFAULT_LANG`` / ``SUPPORTED_LANGS`` / ``TRANSLATIONS`` /
``coerce_lang``) in :mod:`lib.i18n` — both foundational layers imported directly by
their consumers (web_admin, core domains, providers), so nothing reaches *up* into
web_admin for them.  Only genuinely web-facing constants remain here.
"""

__all__ = [
    'HOME_PAGES', 'home_page_ids', 'standalone_pages', 'standalone_page',
]


# ── Landing pages (post-login URL destinations) ─────────────────────────────
# Registry of the pages a user can be sent to after login, for the "default
# landing page" feature (global config + per-user/per-group override). Each is a
# whole URL destination, NOT a dashboard tab: 'admin' is the admin panel (/),
# 'status' is the public status page (/status). A future module that exposes its
# own top-level page appends an entry here with its URL. The effective landing
# (precedence user → group → global) is resolved server-side at login and the
# browser is redirected to its `url`. Served to the frontend only to build the
# selects (id + label).
#
# A page with a ``standalone`` descriptor is ALSO served as its own page out of the
# admin panel (like Overview): it has no tab in ``#mainTabs``, only the ``pane`` that
# the page renders on its own, the JS ``render`` entry point the wiring calls, the
# ``perm`` gating both the route and its navbar button, and the navbar ``icon``/label.
# One generic route serves them all — adding a page here is enough.
HOME_PAGES = (
    {'id': 'admin',    'url': '/admin',    'label_key': 'landing_admin'},
    {'id': 'overview', 'url': '/overview', 'label_key': 'landing_overview',
     'standalone': {'pane': 'tab-overview', 'render': 'renderOverview',
                    'perm': 'overview_view', 'icon': 'bi-speedometer2',
                    'nav_label_key': 'tab_overview'}},
    {'id': 'history',  'url': '/history',  'label_key': 'landing_history',
     'standalone': {'pane': 'tab-history', 'render': 'renderHistory',
                    'perm': 'history_view', 'icon': 'bi-graph-up',
                    'nav_label_key': 'tab_history'}},
    {'id': 'syslog',   'url': '/syslog',   'label_key': 'landing_syslog',
     'standalone': {'pane': 'tab-syslog', 'render': 'renderSyslog',
                    'perm': 'syslog_view', 'icon': 'bi-hdd-stack',
                    'nav_label_key': 'tab_syslog'}},
    {'id': 'status',   'url': '/status',   'label_key': 'landing_status'},
)


def home_page_ids() -> list:
    """Ordered list of valid landing-page ids (for config options + validation)."""
    return [p['id'] for p in HOME_PAGES]


def standalone_pages() -> list:
    """Pages served as their own URL outside the admin panel (id + standalone spec)."""
    return [p for p in HOME_PAGES if p.get('standalone')]


def standalone_page(page_id: str) -> dict | None:
    """The standalone page with *page_id*, or None."""
    for p in standalone_pages():
        if p['id'] == page_id:
            return p
    return None
