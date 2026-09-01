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
    'landing_pages', 'landing_options', 'standalone_pages', 'standalone_page',
    'PANEL_TABS', 'tab_sort_key',
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
    {'id': 'infra',    'url': '/infra',    'label_key': 'landing_infra',
     'standalone': {'pane': 'tab-infra', 'render': 'renderInfra',
                    'perm': 'infra_view', 'icon': 'bi-hdd-network',
                    'nav_label_key': 'tab_infra'}},
    # Where the equipment IS, beside what it is DOING. Its own section rather than a tab of
    # Infrastructure: that one answers "is this all right" and this one answers "where do I
    # walk", and they are opened by different people at different moments.
    {'id': 'dcim',     'url': '/dcim',     'label_key': 'landing_dcim',
     'standalone': {'pane': 'tab-dcim', 'render': 'renderDcim',
                    'perm': 'dcim_view', 'icon': 'bi-building',
                    'nav_label_key': 'tab_dcim',
                    # Four screens under one section, and the sidebar unfolds them. They were
                    # buttons in the tree's toolbar — which is where ACTS on what is on screen
                    # belong, not places you go — and worse, that toolbar is the tree's, so
                    # they vanished the moment somebody opened a rack.
                    #
                    # `views` is the panel's own mechanism for exactly this and it was already
                    # there for module sections. Using it rather than a row of pills inside the
                    # pane is what makes `/dcim/catalog` an address: shareable, bookmarkable,
                    # and choosable as a landing page.
                    #
                    # `kind`/`action` stay empty on purpose: they describe how the GENERIC
                    # renderer draws a module's view, and this section ships its own renderer.
                    'views': (
                        {'slug': 'inventory', 'icon': 'bi-diagram-3', 'kind': '', 'action': '',
                         'label_i18n': {'es_ES': 'Inventario', 'en_EN': 'Inventory'}},
                        {'slug': 'board', 'icon': 'bi-speedometer2', 'kind': '', 'action': '',
                         'label_i18n': {'es_ES': 'Cuadro de mando', 'en_EN': 'Dashboard'}},
                        {'slug': 'catalog', 'icon': 'bi-journal-text', 'kind': '', 'action': '',
                         'label_i18n': {'es_ES': 'Catálogo', 'en_EN': 'Catalogue'}},
                        # Entre el catálogo y el inventario: lo que de verdad se compra. Al
                        # lado del catálogo y no del inventario a propósito — se abre cuando se
                        # decide qué se compra, no cuando se monta un armario.
                        {'slug': 'builds', 'icon': 'bi-boxes', 'kind': '', 'action': '',
                         'label_i18n': {'es_ES': 'Plantillas', 'en_EN': 'Templates'}},
                        # El cableado, fuera de su armario. Dentro de un rack se contesta
                        # «qué sale de aquí»; aquí se contesta «dónde está el cable C-014» y
                        # «cuántos latiguillos de Cat 6A hay puestos», que obligaban a saber el
                        # armario ANTES de poder buscar — lo contrario de buscar.
                        # Los equipos, fuera de su armario. La misma idea que el cableado
                        # un nivel más abajo: «qué servidores hay en esta sede» y «qué se queda
                        # sin garantía este trimestre» obligaban a abrir armario por armario.
                        {'slug': 'devices', 'icon': 'bi-hdd-stack', 'kind': '', 'action': '',
                         'label_i18n': {'es_ES': 'Equipos', 'en_EN': 'Devices'}},
                        {'slug': 'wiring', 'icon': 'bi-ethernet', 'kind': '', 'action': '',
                         'label_i18n': {'es_ES': 'Cableado', 'en_EN': 'Cabling'}},
                        {'slug': 'sources', 'icon': 'bi-lightning-charge', 'kind': '',
                         'action': '',
                         'label_i18n': {'es_ES': 'Fuentes', 'en_EN': 'Sources'}},
                    )}},
    {'id': 'history',  'url': '/history',  'label_key': 'landing_history',
     'standalone': {'pane': 'tab-history', 'render': 'renderHistory',
                    'perm': 'history_view', 'icon': 'bi-graph-up',
                    'nav_label_key': 'tab_history'}},
    {'id': 'syslog',   'url': '/syslog',   'label_key': 'landing_syslog',
     'standalone': {'pane': 'tab-syslog', 'render': 'renderSyslog',
                    'perm': 'syslog_view', 'icon': 'bi-hdd-stack',
                    'nav_label_key': 'tab_syslog'}},
    {'id': 'status',   'url': '/status',   'label_key': 'landing_status'},
    # What the panel is DOING, as opposed to what it found. Placed in the System panel
    # rather than beside the monitoring sections: it is about this process — its threads,
    # its progress — and not about the fleet. Same `placement` a module section uses, so it
    # sorts into that menu alphabetically with everything else there.
    {'id': 'jobs',     'url': '/jobs',     'label_key': 'landing_jobs',
     'standalone': {'pane': 'tab-jobs', 'render': 'renderJobs',
                    'perm': 'jobs_view', 'icon': 'bi-hourglass-split',
                    'placement': 'system', 'nav_label_key': 'tab_jobs'}},
)


# ── The System panel's tabs ───────────────────────────────────────────────────────────
# The admin panel's own sections, as data. They were a literal in the sidebar template, which
# was fine while the order was hand-picked — and stopped being fine the moment the order had
# to be ALPHABETICAL, because alphabetical is a property of the translated label and a
# template cannot sort by a string it is about to look up.
#
# Ordering is not declared here for the same reason: whoever renders knows the language.
PANEL_TABS = (
    {'id': 'services',    'icon': 'bi-hdd-rack',         'label_key': 'tab_services'},
    {'id': 'modules',     'icon': 'bi-puzzle',           'label_key': 'tab_modules'},
    {'id': 'servers',     'icon': 'bi-hdd-network',      'label_key': 'tab_infrastructure'},
    {'id': 'credentials', 'icon': 'bi-key',              'label_key': 'tab_credentials'},
    {'id': 'status',      'icon': 'bi-activity',         'label_key': 'tab_status'},
    {'id': 'events',      'icon': 'bi-bell',             'label_key': 'tab_events'},
    {'id': 'ipban',       'icon': 'bi-slash-circle',     'label_key': 'tab_ipban'},
    {'id': 'config',      'icon': 'bi-gear',             'label_key': 'tab_config'},
    {'id': 'access',      'icon': 'bi-person-lock',      'label_key': 'tab_access'},
    {'id': 'audit',       'icon': 'bi-journal-text',     'label_key': 'tab_audit'},
    {'id': 'backup',      'icon': 'bi-archive',          'label_key': 'tab_backup'},
    {'id': 'diagnostic',  'icon': 'bi-clipboard-pulse',  'label_key': 'tab_diagnostic'},
)


def tab_sort_key(label: str) -> str:
    """How the panel's entries are ordered: by the WORD the reader sees.

    Accents folded away, because a Spanish reader looking for "Índice" looks under I and not
    after Z — which is where the raw code point puts it. Case folded for the same reason:
    `fail2ban` is a name and not a section that sorts before every capital letter.
    """
    import unicodedata                                        # noqa: PLC0415
    n = unicodedata.normalize('NFKD', str(label or ''))
    return ''.join(c for c in n if not unicodedata.combining(c)).casefold()


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
                           # Its pane is GENERATED by dashboard.html, unlike the core
                           # sections (Overview, Infra, History, Syslog) which predate this
                           # and ship bespoke markup. The flag says which, because "has a
                           # module" stopped answering it: a core PACKAGE can claim a section
                           # now, and its pane has to be generated exactly like a module's.
                           'generated': True,
                           'refresh': spec['refresh'],
                           'perm': spec['perm'], 'icon': spec['icon'],
                           # Where the sidebar puts it: a section of its own, or an entry in
                           # the System panel beside Services and Credentials.
                           'placement': spec['placement'],
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


def _page_label_i18n(page: dict) -> dict:
    """A page's name per language, however it happens to name itself.

    Two conventions meet here: a core page points at a key in the core catalog, a module page
    carries its own translations because no core string may name a module. Flattening both to
    the same map is what lets a caller compose a label —  "section · view" — without knowing
    which kind of page it has.
    """
    if page.get('label_i18n'):
        return dict(page['label_i18n'])
    key = page.get('label_key')
    if not key:
        return {}
    from lib.i18n import TRANSLATIONS  # noqa: PLC0415
    return {lang: (data or {}).get(key) for lang, data in TRANSLATIONS.items()
            if (data or {}).get(key)}


def landing_pages(watchfuls_dir: str | None = None) -> list:
    """The landing destinations a human can CHOOSE, which is not the same list as the pages.

    A section with several views is several destinations: "m365" is not a place, it is
    whichever of its views happens to be first, and offering it beside "Storage" asks the
    reader to know that. Each view becomes its own option and the bare section drops out of
    the list — a menu with a parent and its children in it makes the parent mean "the first
    child", silently.

    The bare id stays VALID (see :func:`home_page_ids`): it is a working URL and it is what
    every landing saved before views existed says.
    """
    out = []
    for p in home_pages(watchfuls_dir):
        views = (p.get('standalone') or {}).get('views') or []
        if not views:
            out.append(p)
            continue
        page_li = _page_label_i18n(p)
        for v in views:
            # The section names the place, the view names which of it — and for a module both
            # come from the MODULE's lang file, so the core invents a name for neither.
            view_li = v.get('label_i18n') or {}
            label_i18n = {
                lang: '{} · {}'.format(page_li.get(lang) or p['id'],
                                       view_li.get(lang) or v['slug'])
                for lang in set(page_li) | set(view_li)
            }
            out.append({'id': '{}/{}'.format(p['id'], v['slug']),
                        'url': '{}/{}'.format(p['url'], v['slug']),
                        'label_i18n': label_i18n, 'module': p.get('module')})
    return out


def landing_options(lang: str, default_lang: str = 'en_EN') -> list:
    """:func:`landing_pages` with each label already resolved for *lang*.

    The selects that offer these live in three places (config, user, group) and a module
    page's name is in the module's own lang file, not in the core catalog — resolving it
    here once is what keeps those three from each growing their own half of the rule.
    """
    return [{'id': p['id'], 'url': p['url'], 'label': page_label(p, lang, default_lang)}
            for p in landing_pages()]


def home_page_ids() -> list:
    """Every landing id that RESOLVES — the choosable ones plus the bare section ids.

    Validation is not the same question as the menu: a landing saved as "m365" before that
    section grew a second view still points somewhere real, and rejecting it on the next save
    of an unrelated field would be this list calling a working setting invalid.
    """
    ids = [p['id'] for p in landing_pages()]
    ids += [p['id'] for p in home_pages() if p['id'] not in ids]
    return ids


def standalone_pages() -> list:
    """Pages served as their own URL outside the admin panel (id + standalone spec)."""
    return [p for p in home_pages() if p.get('standalone')]


def standalone_page(page_id: str) -> dict | None:
    """The standalone page with *page_id*, or None."""
    for p in standalone_pages():
        if p['id'] == page_id:
            return p
    return None
