#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A section can declare which sidebar group it belongs in, and the shell obeys.

A module contributes a section by declaring ``__page__``. Until now every one of them landed
in the same place — a top-level entry of its own, beside Overview and Infrastructure — which
is right for something an operator WATCHES and wrong for something an operator ADMINISTERS.
The MIB library is administered: it belongs beside Services, Modules and Credentials, and
that is what the SNMP module declared (``"placement": "system"``).

Then the groups became two: the organisation's registers — companies, devices, credentials and
the MIB library — moved to a **Catalogue** of their own (``"placement": "catalog"``), and
**System** kept the platform: services, modules, access, backups. Who files the company that owns
a rack is not who manages the backups.

Four things have to agree for that to work, and they live in four files — the descriptor, the
sidebar, the pane and the wiring. Any one of them can be right on its own while the section
stays unreachable, and none of that is visible to a test which reads only Python. This one
renders the real page and looks.
"""

import pytest

from tests.conftest import _login


def _entry(html, li_id):
    """The opening ``<li …>`` tag of one sidebar entry.

    Scoped on purpose: an attribute asserted against the whole page is an attribute that can
    belong to anything on it, and this file exists to check THIS entry."""
    i = html.index(f'id="{li_id}"')
    start = html.rindex('<li', 0, i)
    return html[start:html.index('>', i) + 1]


def test_a_declared_page_can_live_in_a_group(client):
    """The SNMP MIB manager, end to end: the entry inside the Catalogue, the pane it opens
    and the markup it clones — with the modal it replaced gone."""
    _login(client)
    html = client.get('/admin').data.decode('utf-8', 'replace')

    # The entry, and the attribute that decides whether it is ever shown — read off the
    # ELEMENT and not off the page. Asserted as `in html` these passed while the entry
    # carried neither: `data-nav-module="snmp"` and `data-nav-perm="modules_view"` both
    # appear elsewhere on the page, so the guard was satisfied by somebody else's markup
    # while the section itself shipped hidden and nothing ever revealed it.
    assert 'id="tab-snmp-li"' in html, 'no entry for the SNMP section in the panel'
    assert 'data-bs-target="#tab-snmp"' in html
    entry = _entry(html, 'tab-snmp-li')
    # SNMP is declared by a CORE package now, so there is no module behind it and the
    # permission is the whole rule. `applyRoleRestrictions` reveals by permission and treats
    # "no module" as active; `syncModuleSections` only handles the ones that HAVE a module.
    # An entry with neither attribute is an entry nobody shows.
    assert 'data-nav-perm="snmp_view"' in entry, entry
    assert 'data-nav-module=' not in entry, 'the section belongs to a module again'

    # The pane it opens, and the container the module renders into.
    assert 'id="tab-snmp"' in html and 'id="snmp-container"' in html

    # …and the markup, inert until the render clones it.
    assert 'id="snmpMibsPageTpl"' in html
    assert 'id="mibManagerModal"' not in html, 'the modal it replaced is still shipped'

    # INSIDE the Catalogue and not among the top-level sections nor in System, which is the
    # whole difference between this placement and the others.
    assert html.index('id="ss-sb-catalog"') < html.index('id="tab-snmp-li"') \
        < html.index('id="ss-sb-settings"')


def test_a_section_placed_page_still_lands_at_the_top(client):
    """The other placement, unchanged: the guard is that `placement` moved something, not
    that it moved everything."""
    _login(client)
    html = client.get('/admin').data.decode('utf-8', 'replace')
    if 'id="nav-page-m365-li"' not in html:
        pytest.skip('m365 is not shipped in this build')
    assert html.index('id="nav-page-m365-li"') < html.index('id="ss-sb-catalog"')


def _panel_entries(html, group='ss-sb-settings'):
    """(id, label) for every entry of one sidebar group, in the order rendered."""
    import re
    acc = html.index('id="%s"' % group)
    # Up to where the next group starts: its entries are not this one's.
    fin =html.index('id="ss-sb-settings-group"', acc) if group == 'ss-sb-catalog' else len(html)
    out = []
    for m in re.finditer(r'id="tab-([a-z0-9_-]+)-li"', html[acc:fin]):
        chunk = html[acc + m.start():acc + m.start() + 1200]
        lbl = re.search(r'<span class="ss-sb-label">([^<]+)</span>', chunk)
        out.append((m.group(1), (lbl.group(1) if lbl else '').strip()))
    return out


def test_the_panel_entries_are_in_the_readers_alphabetical_order(client):
    """Thirteen entries in a hand-picked order is thirteen positions to learn; in alphabetical
    order there is nothing to learn. It has to be the TRANSLATED label — the order is
    different in every language, which is why the list stopped being a literal in the
    template and became a registry the renderer sorts."""
    _login(client)
    html = client.get('/admin').data.decode('utf-8', 'replace')
    for grupo, minimo in (('ss-sb-settings', 10), ('ss-sb-catalog', 4)):
        entries = _panel_entries(html, grupo)
        assert len(entries) >= minimo, f'{grupo} lost its entries'
        labels = [lbl for _id, lbl in entries]
        assert labels == sorted(labels, key=_key), f'{grupo} out of order: {labels}'


def test_a_module_tab_is_sorted_among_the_core_ones(client):
    """Merged before the sort, not appended after it: a module section pinned to the end
    reads as an afterthought, and where an entry came from is not what somebody scanning a
    menu is looking for. Stated language-independently — its position among the labels is the
    position the sort gives it, wherever that falls in Spanish or English."""
    _login(client)
    entries = _panel_entries(client.get('/admin').data.decode('utf-8', 'replace'),
                             'ss-sb-catalog')
    assert 'snmp' in [i for i, _l in entries], 'the SNMP section is not in the Catalogue'
    labels = [lbl for _id, lbl in entries]
    mine = dict(entries)['snmp']
    assert labels.index(mine) == sorted(labels, key=_key).index(mine)


def test_a_section_in_the_panel_lists_its_views(client):
    """`__page__.views` gave a top-level section a flyout and left a System-panel one
    without: same declaration, same mechanism, a different branch of the sidebar — so a
    section that moved into the panel silently lost its views. They are a property of the
    SECTION; where the sidebar draws it is not a property of anything.

    Keyed like every other sub-item (`data-subtab="#view-<id>-<slug>"`), because the single
    highlight and the breadcrumb already read that, and a second mechanism for one job is
    how two of them end up disagreeing."""
    _login(client)
    html = client.get('/admin').data.decode('utf-8', 'replace')
    acc = html.index('id="ss-sb-catalog"')
    entry = html.index('id="tab-snmp-li"', acc)
    chunk = html[entry:entry + 2500]
    assert 'ss-sb-flyout' in chunk, 'the section in the panel has no flyout'
    for slug in ('library', 'import'):
        assert 'data-subtab="#view-snmp-%s"' % slug in chunk
        assert "_navPageView('snmp', '%s')" % slug in chunk
    # …and the section keeps its own URL, so a copied link says /module/snmp/<view> and not
    # /admin?tab=snmp, which names no view at all.
    assert 'data-nav-url="/module/snmp"' in chunk


def test_a_section_with_its_own_renderer_draws_its_own_views(client):
    """Changing view called the core's generic renderer — which paints the core's layout
    from `page_data`, over a page that had already declared it draws itself. The core owns
    the pane, the URL and which view the URL names; what goes in it was never its half."""
    _login(client)
    html = client.get('/admin').data.decode('utf-8', 'replace')
    i = html.index('function renderModulePageView(')
    body = html[i:html.index('function ', i + 10)]
    assert 'spec.render' in body, 'a module renderer is ignored when the view changes'
    assert 'renderModulePage(spec)' in body, 'the generic renderer is no longer the fallback'


def _key(label):
    """The same folding the renderer uses: accents and case are not sort order."""
    from lib.web_admin.constants import tab_sort_key
    return tab_sort_key(label)


def test_the_catalogue_holds_the_organisations_registers(client):
    """Companies, devices, credentials and the MIB library in the Catalogue; the platform's own
    settings in System. Read off the rendered page: the declarations are four files and the
    group is drawn by a fifth, and any one of them can disagree."""
    _login(client)
    html = client.get('/admin').data.decode('utf-8', 'replace')
    catalogo = {i for i, _l in _panel_entries(html, 'ss-sb-catalog')}
    sistema = {i for i, _l in _panel_entries(html, 'ss-sb-settings')}
    # Devices' classes and clusters as entries of their own: the registry's list went to
    # Infrastructure, where each device is also watched, located and configured.
    registros = {'orgs', 'devtypes', 'clusters', 'credentials', 'snmp'}
    assert registros <= catalogo, catalogo
    assert not (registros & sistema), sistema
    assert 'servers' not in catalogo | sistema, 'the registry still has a tab of its own'
    assert {'services', 'modules', 'config', 'access', 'backup', 'audit'} <= sistema, sistema


def test_the_catalogue_is_a_group_like_system(client):
    """Same drawing, its own remembered open/closed state, and above System."""
    _login(client)
    html = client.get('/admin').data.decode('utf-8', 'replace')
    assert 'id="ss-sb-catalog-group"' in html
    assert 'data-sb-store="ss_sidebar_catalog_open"' in html
    assert 'data-sb-store="ss_sidebar_settings_open"' in html
    assert html.index('id="ss-sb-catalog-group"') < html.index('id="ss-sb-settings-group"')


def test_an_unknown_placement_still_lands_at_the_top(client):
    """A typo in a declaration must not make a section vanish: it goes where a section with no
    placement goes."""
    from lib.modules.discovery.pages import _page_spec                # noqa: PLC0415
    assert _page_spec('x', {'id': 'xmod', 'placement': 'catalogue'})['placement'] == 'section'
    assert _page_spec('x', {'id': 'xmod', 'placement': 'catalog'})['placement'] == 'catalog'
