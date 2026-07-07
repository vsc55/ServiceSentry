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
    'HOME_PAGES', 'home_page_ids',
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
HOME_PAGES = (
    {'id': 'admin',  'url': '/admin',  'label_key': 'landing_admin'},
    {'id': 'status', 'url': '/status', 'label_key': 'landing_status'},
)


def home_page_ids() -> list:
    """Ordered list of valid landing-page ids (for config options + validation)."""
    return [p['id'] for p in HOME_PAGES]
