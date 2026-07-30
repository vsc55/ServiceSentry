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
    'HOME_PAGES', 'home_pages', 'page_label', 'home_page_ids',
    'standalone_pages', 'standalone_page',
]

from lib.modules.discovery.pages import module_pages_catalog


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


def _module_home_pages(watchfuls_dir: str | None = None) -> list:
    """The same shape as a ``HOME_PAGES`` entry, for every module claiming a page.

    A module page carries ``label_i18n`` (its own translated ``pretty_name``) where a
    core page carries ``label_key`` (a key in the core catalog) — the core owns no
    string naming a module.  Consumers resolve the label through :func:`page_label`.
    """
    out = []
    for spec in module_pages_catalog(watchfuls_dir):
        out.append({
            # Namespaced on purpose. A module page used to claim a top-level path, which made
            # every future core section a potential collision and left the core policing a
            # blocklist of names it had to remember to grow. Under `/module/` the collision is
            # impossible by construction rather than by vigilance, and the URL says where the
            # page comes from. The id is unchanged, so the landing-page setting — which stores
            # the id, not the path — does not notice.
            'id': spec['id'], 'url': '/module/' + spec['id'], 'label_i18n': spec['label_i18n'],
            'module': spec['module'],
            # `refresh` travels too: it is what tells the core's generic renderer the
            # module can fetch live data, and therefore whether to offer the button. A
            # module shipping its own renderer draws its own; one relying on the generic
            # renderer has no other way to say so.
            'standalone': {'pane': 'tab-' + spec['id'], 'render': spec['render'],
                           'refresh': spec['refresh'],
                           'perm': spec['perm'], 'icon': spec['icon'],
                           # The section's views, when it has more than one. They share
                           # this page's pane and permission and differ only by a
                           # sub-path, so they add no route and no second descriptor.
                           'views': spec['views'],
                           'label_i18n': spec['label_i18n'], 'module': spec['module']},
        })
    return out


def home_pages(watchfuls_dir: str | None = None) -> list:
    """Every landing destination: the core pages plus the module-contributed ones.

    THE accessor — prefer it over the ``HOME_PAGES`` tuple, which is only the core
    half.  Module pages are appended after the core ones (and before ``status``, which
    stays last as the public page) so the sidebar order reads core-first.
    """
    mods = _module_home_pages(watchfuls_dir)
    if not mods:
        return list(HOME_PAGES)
    core = list(HOME_PAGES)
    tail = [p for p in core if p['id'] == 'status']
    head = [p for p in core if p['id'] != 'status']
    return head + mods + tail


def page_label(page: dict, lang: str, default_lang: str = 'en_EN') -> str:
    """A page's display label: a core page translates its ``label_key``; a module page
    carries its own ``label_i18n`` (falling back to the default language, then the id)."""
    key = page.get('label_key')
    if key:
        from lib.i18n import TRANSLATIONS
        return TRANSLATIONS.get(lang, {}).get(key) or TRANSLATIONS.get(default_lang, {}).get(key) or key
    li = page.get('label_i18n') or {}
    return li.get(lang) or li.get(default_lang) or page.get('id', '')


def home_page_ids() -> list:
    """Ordered list of valid landing-page ids (for config options + validation)."""
    return [p['id'] for p in home_pages()]


def standalone_pages() -> list:
    """Pages served as their own URL outside the admin panel (id + standalone spec)."""
    return [p for p in home_pages() if p.get('standalone')]


def standalone_page(page_id: str) -> dict | None:
    """The standalone page with *page_id*, or None."""
    for p in standalone_pages():
        if p['id'] == page_id:
            return p
    return None
