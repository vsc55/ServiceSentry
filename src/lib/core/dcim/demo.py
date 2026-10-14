#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A complete demonstration site, built through the store: ``main.py dcim demo``.

One site called **Demo** that exercises everything the inventory can hold — three floors with a
background plan and its walls, a stair core, rooms placed on each floor (and loose things in a
floor's general area), rows and aisles, racks of several shapes (standard, network, wall-mounted,
partly empty), items of every placement (bolted, half-width, mounted on a shelf, front/rear,
vertical PDUs one in each rear channel or both in one, horizontal 1U PDUs at the rear or the
front, a UPS on the floor beside a rack), parts, a power chain from the mains to each outlet,
data cabling inside and between racks and floors, room features (CRAC, aisle containment, trays,
columns, doors, a cabinet with its shelves) and two companies. Three small sites —a recovery
centre in Barcelona, an office in Texas and one in Puerto Rico— exist so the WAN links have
somewhere to land: two between Demo and its recovery centre for HA, the IPsec one down.

Every word the demo writes comes from ``data/demo/<lang>.json``, so it is built in the
installation's language. Only the main site's name, «Demo», is the same in all of them.

Written to the store directly and not through the HTTP API: it runs from the command line, with
no panel. Every bolted item is checked with :meth:`DcimStore.fits` before it is written, the
same rule the API applies, so the demo can never hold a placement the panel would refuse.
"""

from __future__ import annotations

import glob
import io
import json
import os

from lib.core.dcim import demo_faces
from lib.core.dcim import media as dcim_media

#: The main site's name, the same in every language.
SITE = 'Demo'
#: The small sites' name keys in the word tables: the demo is found and removed by these names.
BRANCHES = ('site_dr', 'site_tx', 'site_pr', 'site_za', 'site_tw')
#: The keys of `build`'s result that are site uids and not counts.
UID_KEYS = ('site',) + BRANCHES
#: The demo's own catalogue models: their maker, and the origin that marks them as the demo's.
MAKER = 'Demo'
SOURCE = 'demo'
#: The texts, one file per language. `es_ES` is the base a partial translation falls back to.
TEXTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'demo')
_BASE_LANG = 'es_ES'

#: The building: 30 × 20 m, a 300 mm outer wall, interior partitions of 120 mm.
_W, _D = 30000, 20000
_OUTER, _INNER = 300, 120
#: The stair core, at the same point on every floor so it forms one shaft in 3D: at the east
#: end of the corridor, with the floor lobby and the lift in front of it.
_CORE = (27700, 15800)

_WATTS = {'server': 450, 'storage': 900, 'switch': 150, 'router': 120, 'firewall': 200,
          'console': 30, 'kvm': 40, 'other': 60}

#: Which way the air goes through each model. Servers and storage take it in at the front, as
#: the cold aisle expects; the switches are mounted with their ports to the rear and breathe the
#: other way round —which is why a top-of-rack switch the wrong way round is a hot spot—; a patch
#: panel does not breathe.
_AIRFLOW = {'server': 'front-to-rear', 'gpu': 'front-to-rear', 'node': 'front-to-rear',
            'storage': 'front-to-rear', 'tor': 'rear-to-front', 'access': 'rear-to-front',
            'core': 'front-to-rear', 'router': 'front-to-rear', 'cpe': 'passive',
            'firewall': 'front-to-rear', 'patch': 'none', 'fiber': 'none',
            'console': 'passive', 'kvm': 'passive', 'mini': 'side-to-rear'}


#: Where a rack's two PDUs go (`_Builder.pdus`). The usual: a vertical one in each rear channel,
#: said and not left to the automatic alternation, which draws the same but says nothing.
PDU_SPLIT = ({'side_pos': 'rear-left'}, {'side_pos': 'rear-right'})
#: Both in the same rear channel, A against the side panel and B inside it: the other channel is
#: left for the data cables.
PDU_SAME_LEFT = ({'side_pos': 'rear-left', 'side_slot': 0},
                 {'side_pos': 'rear-left', 'side_slot': 1})


class DemoError(Exception):
    """The demo cannot be built as asked (it already exists, a placement does not fit)."""


def _load(path: str) -> dict:
    with io.open(path, encoding='utf-8') as fh:
        return json.load(fh)


def texts(lang: str = '') -> dict:
    """The demo's words in *lang*, completed from the base language where it says nothing."""
    out = _load(os.path.join(TEXTS_DIR, _BASE_LANG + '.json'))
    own = os.path.join(TEXTS_DIR, '%s.json' % os.path.basename(str(lang or '')))
    if lang and lang != _BASE_LANG and os.path.isfile(own):
        out.update(_load(own))
    return out


def _every(key: str) -> set:
    """What *key* is called in every language: the demo is found by name whichever language
    built it, so a panel switched to English can still remove a demo built in Spanish."""
    return {str(_load(p).get(key) or '') for p in glob.glob(os.path.join(TEXTS_DIR, '*.json'))} - {''}


def find(store) -> list[dict]:
    """The demo sites that exist now: by name AND run by the demo's operator company.

    By name alone a real site somebody called «Demo» was the demo, and removing the demo —now a
    button in Maintenance— deleted it with everything in it. The demo writes both sites with its
    own operator, so that is what tells them apart. Every site it writes, the small ones too
    (`BRANCHES`), in every language."""
    names = {SITE}.union(*(_every(k) for k in BRANCHES))
    operadores = {o['uid'] for o in store.orgs.list()
                  if str(o.get('name') or '') in _every('org_operator')}
    return [s for s in store.sites.list() if str(s.get('name') or '') in names
            and str(s.get('operator_uid') or '') in operadores]


# ── Removing ─────────────────────────────────────────────────────────────────────────────────

def remove(store, *, var_dir: str = '', media_dir: str = '') -> int:
    """Delete the demo sites and everything under them. Returns how many sites went.

    Bottom-up, so nothing is ever left pointing at a parent that is gone: cables and feeds, then
    items with their parts, PDUs, racks, features, rows, rooms, walls, floors with their plan
    files, sources, links and finally the sites. The two demo companies stay when anything else
    still names them; otherwise they go too.
    """
    sites = find(store)
    if not sites:
        return 0
    uids = [s['uid'] for s in sites]
    for link in store.links_of(uids):
        store.links.delete(link['uid'])
    for site in sites:
        for room in store.rooms_of(site['uid']):
            _remove_room_items(store, room['uid'])
            for rack in store.racks_of(room['uid']):
                _remove_rack(store, rack)
            for feature in store.features_of(room['uid']):
                store.delete_feature(feature['uid'])
            for row in store.rows_of(room['uid']):
                store.rows.delete(row['uid'])
            _forget_plan(room, var_dir, media_dir)
            store.rooms.delete(room['uid'])
            store.forget_scope('room', room['uid'])
        for floor in store.floors_of(site['uid']):
            store.set_walls(floor['uid'], [])
            _forget_plan(floor, var_dir, media_dir)
            store.floors.delete(floor['uid'])
        for source in store.sources_of(site['uid']):
            store.sources.delete(source['uid'])
        store.sites.delete(site['uid'])
        store.forget_scope('site', site['uid'])
    for name in _every('org_operator') | _every('org_customer'):
        org = _org_named(store, name)
        if org and not _org_in_use(store, org['uid']):
            store.orgs.delete(org['uid'])
    _remove_models(store, var_dir, media_dir)
    return len(sites)


def _catalog(store):
    from lib.core.dcim.catalog import CatalogStore      # noqa: PLC0415
    return CatalogStore(store._db)                     # noqa: SLF001


def _remove_models(store, var_dir: str, media_dir: str) -> None:
    """The demo's catalogue models, with their pictures — except one somebody put to use on an
    item of their own, which is theirs now."""
    cat = _catalog(store)
    for row in cat.list('source = ?', (SOURCE,)):
        if not store.items.list('type_uid = ?', (row['uid'],)) \
                and not store.features.list('type_uid = ?', (row['uid'],)):
            cat.delete(row['uid'], var_dir, media_dir)


def _remove_rack(store, rack: dict) -> None:
    from lib.core.dcim import service as dcim_svc       # noqa: PLC0415
    dcim_svc.empty_rack(store, rack['uid'])
    store.racks.delete(rack['uid'])
    store.forget_scope('rack', rack['uid'])


def _remove_room_items(store, room_uid: str) -> None:
    """What is in the room and not in a rack —the desks' PCs and phones, the outlets, the APs—
    with its cables, its feeds and its parts."""
    items = store.items_in_room(room_uid)
    item_uids = [i['uid'] for i in items]
    for item_uid in item_uids:
        for feed in store.feeds.list('item_uid = ?', (item_uid,)):
            store.feeds.delete(feed['uid'])
    for cable in store.cables_of(item_uids):
        store.cables.delete(cable['uid'])
    for part in store.parts_of(item_uids):
        store.parts.delete(part['uid'])
    for item in items:
        store.items.delete(item['uid'])
        store.forget_scope('item', item['uid'])


def _forget_plan(row: dict, var_dir: str, media_dir: str) -> None:
    name = str(row.get('plan') or '')
    if name and var_dir:
        dcim_media.forget(var_dir, name, media_dir)


def _org_named(store, name: str) -> dict | None:
    return next((o for o in store.orgs.list() if o.get('name') == name), None)


def _org_in_use(store, org_uid: str) -> bool:
    if any(o.get('org_uid') == org_uid for o in store.owners.list()):
        return True
    return any(s.get('operator_uid') == org_uid for s in store.sites.list())


# ── Building ─────────────────────────────────────────────────────────────────────────────────

class _Builder:
    """Holds the store, the words and the running counters while the demo is written."""

    def __init__(self, store, actor: str, var_dir: str, media_dir: str, area_word: str,
                 words: dict):
        self.s = store
        self.actor = actor
        self.var_dir = var_dir
        self.media_dir = media_dir
        self.area_word = area_word
        self.w = words
        self.serial = 0
        self.outlet: dict = {}
        self.models: dict = {}

    # The small writers -------------------------------------------------------------------

    def new(self, table: str, data: dict) -> str:
        return getattr(self.s, table).create(data, actor=self.actor)

    def next_serial(self, prefix: str) -> str:
        self.serial += 1
        return '%s%06d' % (prefix, 100000 + self.serial)

    def org(self, key: str) -> str:
        name = self.w[key]
        found = _org_named(self.s, name)
        if found:
            return found['uid']
        return self.new('orgs', {'name': name, 'short': self.w[key + '_short'],
                                 'description': self.w[key + '_desc']})

    def item(self, rack: str, label: str, role: str, u: int = 0, h: int = 1, **extra) -> str:
        model = self.models.get(extra.pop('model', ''), '')
        data = {'rack_uid': rack, 'label': label, 'role': role, 'u_start': u, 'u_height': h,
                'face': extra.pop('face', 'full'), 'placement': extra.pop('placement', 'u')}
        if model:
            data['type_uid'] = model
        data.update(extra)
        if data['placement'] != 'u':
            data['u_start'], data['u_height'] = 0, 0
        elif not data.get('parent_uid'):
            slot = {k: data[k] for k in ('u_slots', 'u_slot', 'u_slot_span') if k in data}
            if not self.s.fits(rack, u, h, data['face'], slot=slot or None):
                raise DemoError('item %r does not fit at U%d' % (label, u))
        if role not in ('blank', 'patch_panel', 'fiber_panel', 'shelf') \
                and 'serial' not in data:
            data['serial'] = self.next_serial('DM')
        return self.new('items', data)

    def pdus(self, rack: str, name: str, sources: tuple, capacity: int = 7400,
             where: tuple = None) -> tuple:
        """The two PDUs of a rack — the item and the PDU row that says which branch it hangs
        from — and hands back ``(pdu_a, pdu_b)``.

        *where* says where each one goes, A then B (`PDU_SPLIT` by default: a vertical one in
        each rear channel). A vertical one is ``{'side_pos', 'side_slot'}``; a horizontal one
        is ``{'u': n, 'face': 'rear'}`` and takes its U like any item, with the outlets of a 1U
        strip."""
        out = []
        for (feed, src), sitio in zip(zip(('a', 'b'), sources), where or PDU_SPLIT):
            label = 'PDU-%s-%s' % (name, feed.upper())
            sitio = dict(sitio)
            if 'u' in sitio:
                item = self.item(rack, label, 'pdu', sitio.pop('u'), 1,
                                 face=sitio.pop('face', 'rear'), depth_mm=200, **sitio)
                tomas = 12
            else:
                item = self.item(rack, label, 'pdu', placement='side', **sitio)
                tomas = 24
            out.append(self.new('pdus', {'rack_uid': rack,
                                         'name': self.w['pdu_pair'] % (name, feed.upper()),
                                         'feed': feed, 'outlets': tomas, 'capacity_w': capacity,
                                         'source_uid': src, 'item_uid': item}))
        return tuple(out)

    def feed(self, item: str, pdu: str, watts: int, label: str = '') -> None:
        self.outlet[pdu] = self.outlet.get(pdu, 0) + 1
        self.new('feeds', {'item_uid': item, 'pdu_uid': pdu, 'outlet': self.outlet[pdu],
                           'watts_said': watts, 'category': 'c13-c14', 'length_mm': 1500,
                           'label': label})

    def tidy_outlets(self, rack: str) -> None:
        """Each PDU's outlets in the order of the U they feed: on a vertical strip, the cord
        of the item at U1 in an outlet at the bottom and the one at the top in one at the top,
        as somebody plugging them in would. In order of creation, the top item's cord went to
        the bottom of the strip and crossed the whole rack."""
        alto = int((self.s.racks.get(rack) or {}).get('u_height') or 42)
        for pdu in self.s.pdus_of(rack):
            n = int(pdu.get('outlets') or 0)
            feeds = self.s.feeds_of([pdu['uid']])
            if not n or not feeds:
                continue
            u_of = {f['uid']: int((self.s.items.get(f['item_uid']) or {}).get('u_start') or 1)
                    for f in feeds}
            ultima = 0
            for f in sorted(feeds, key=lambda f: (u_of[f['uid']], f['uid'])):
                quiere = 1 + round((u_of[f['uid']] - 1) * (n - 1) / max(1, alto - 1))
                ultima = min(n, max(ultima + 1, quiere))
                self.s.feeds.update(f['uid'], {'outlet': ultima}, actor=self.actor)

    def dual(self, item: str, role: str, pdus: tuple, watts: int = 0) -> None:
        w = watts or _WATTS.get(role, 100)
        for pdu in pdus:
            self.feed(item, pdu, w // len(pdus))

    def cable(self, a: str, a_port: str, b: str, b_port: str, kind: str = 'copper',
              category: str = 'cat6a', color: str = 'blue', length: int = 2000,
              label: str = '') -> str:
        return self.new('cables', {'a_item': a, 'a_port': a_port, 'b_item': b, 'b_port': b_port,
                                   'kind': kind, 'category': category, 'color': color,
                                   'length_mm': length, 'label': label})

    def feature(self, room: str, kind: str, label: str, x: float, y: float,
                w: int = 0, d: int = 0, rot: int = 0, **extra) -> str:
        from lib.core.dcim.store.features import FEATURE_KINDS     # noqa: PLC0415
        std = FEATURE_KINDS[kind]
        data = {'room_uid': room, 'kind': kind, 'label': label, 'pos_x': x, 'pos_y': y,
                'width_mm': w or std['w'], 'depth_mm': d or std['d'], 'rotation': rot}
        data.update(extra)
        return self.new('features', data)

    def door(self, room: str, w: int, d: int, top: bool = False, fire: bool = False) -> None:
        """The room's door, where the floor's walls leave its gap: the middle of the side that
        gives onto the corridor — the bottom one, or the top one for a room against the
        building's back wall (`_door_on_top`). ``fire``: a special-risk room's (CTE DB-SI 1,
        table 2.2), a self-closing fire door, and its label says its class — which is what the
        plan shows and what an inspector looks for."""
        # Una puerta normal, sin rótulo: el suyo sería «Puerta», que ya dice su tipo, y el plano lo
        # toma del catálogo. La cortafuegos lo lleva porque dice algo más: su clase.
        etiqueta = self.w['door_fire'] if fire else ''
        self.feature(room, 'door', etiqueta, w / 2 - 500, 0 if top else d - 120)

    def shelf_items(self, cabinet: str, rows: list) -> None:
        for shelf, label, qty, notes in rows:
            self.new('shelf_items', {'feature_uid': cabinet, 'shelf': shelf, 'label': label,
                                     'qty': qty, 'notes': notes})

    def load_models(self) -> None:
        """The demo's own catalogue models, with their front and rear pictures
        (`data/demo/faces/`, see `demo_faces`): reused if they are there, made if not."""
        cat = _catalog(self.s)
        have = {r['model']: r['uid'] for r in cat.list('source = ?', (SOURCE,))}
        for key, (name, _role, u, full) in demo_faces.MODELS.items():
            if name in have:
                self.models[key] = have[name]
                continue
            cuentas, lista, sitio = demo_faces.ports_of(key)
            row = {'manufacturer': MAKER, 'model': name, 'u_tenths': u * 10,
                   'full_depth': 1 if full else 0, 'ports': cuentas, 'port_list': lista,
                   'airflow': _AIRFLOW.get(key, '')}
            for cara, lado in (('front_image', 'front'), ('rear_image', 'rear')):
                svg = demo_faces.face(key, lado)
                if svg:
                    row[cara] = self.plan(svg)
            self.models[key] = cat.create(row, SOURCE, actor=self.actor)
            # Sus puertos, ya situados: las caras se dibujan aquí, así que se sabe dónde está
            # cada boca, y en el armario cada cable sale de la suya.
            if sitio and self.models[key]:
                cat.set_port_map(self.models[key], sitio, actor=self.actor)

    def load_access_models(self, lang: str = '', images: bool = False) -> None:
        """The access control models: not the demo's own but the GENERAL catalogue's —the
        basics the panel ships (`data/basics.json`), Salto's among them—, brought in if this
        installation has not brought them yet. They are real models and stay when the demo goes."""
        from lib.core.dcim import basics as dcim_basics          # noqa: PLC0415
        cat = _catalog(self.s)
        quiere = {'access_iq': ('Salto', 'IQ 2.0'), 'access_neo': ('Salto', 'Neo Cylinder'),
                  'access_locker': ('Salto', 'XS4 Locker'),
                  'access_reader': ('Salto', 'Design XS Reader')}

        def buscar():
            filas = cat.list('source = ?', (dcim_basics.SOURCE,))
            have = {(r['manufacturer'], r['model']): r['uid'] for r in filas}
            torno = next((r['uid'] for r in filas if r.get('kind') == 'turnstile'
                          and r['manufacturer'] == dcim_basics.MAKER), '')
            return have, torno

        have, torno = buscar()
        if not torno or any(m not in have for m in quiere.values()):
            filas = dcim_basics.rows(lang)
            if images:
                dcim_basics.fetch_images(filas)
            cat.replace(dcim_basics.SOURCE, filas, self.var_dir, self.media_dir)
            have, torno = buscar()
        for key, marca_modelo in quiere.items():
            self.models[key] = have.get(marca_modelo, '')
        self.models['access_turnstile'] = torno

    def plan(self, svg: str) -> str:
        """Store a floor plan picture; empty when there is nowhere to put files."""
        if not self.var_dir and not self.media_dir:
            return ''
        name, err = dcim_media.save(self.var_dir, svg.encode('utf-8'), self.media_dir)
        return '' if err else name


def build(store, *, actor: str = 'demo', var_dir: str = '', media_dir: str = '',
          area_word: str = '', lang: str = '', replace: bool = False,
          images: bool = False) -> dict:
    """Write the demo in *lang*. Refuses when it exists, unless *replace* says to rebuild it.

    Returns ``{'site': uid, 'site_dr': uid, 'site_tx': uid, 'site_pr': uid}`` (`UID_KEYS`)
    plus what was written, counted.
    """
    if find(store):
        if not replace:
            raise DemoError('the demo site already exists')
        remove(store, var_dir=var_dir, media_dir=media_dir)
    w = texts(lang)
    b = _Builder(store, actor, var_dir, media_dir, area_word or 'area', w)
    b.load_models()
    b.load_access_models(lang, images)
    operator = b.org('org_operator')
    customer = b.org('org_customer')

    site = b.new('sites', {
        'name': SITE, 'address': w['site_address'], 'lat': 40.4237, 'lon': -3.6914,
        'timezone': 'Europe/Madrid', 'operator_uid': operator, 'contact': w['site_contact'],
        'phone': '+34 910 000 000', 'description': w['site_desc']})
    site_dr = b.new('sites', {
        'name': w['site_dr'], 'address': w['site_dr_address'], 'lat': 41.3874, 'lon': 2.1686,
        'timezone': 'Europe/Madrid', 'operator_uid': operator, 'description': w['site_dr_desc']})
    site_tx = b.new('sites', {
        'name': w['site_tx'], 'address': w['site_tx_address'], 'lat': 32.7767, 'lon': -96.7970,
        'timezone': 'America/Chicago', 'operator_uid': operator, 'description': w['site_tx_desc']})
    site_pr = b.new('sites', {
        'name': w['site_pr'], 'address': w['site_pr_address'], 'lat': 18.4655, 'lon': -66.1057,
        'timezone': 'America/Puerto_Rico', 'operator_uid': operator,
        'description': w['site_pr_desc']})
    site_za = b.new('sites', {
        'name': w['site_za'], 'address': w['site_za_address'], 'lat': -26.1076, 'lon': 28.0567,
        'timezone': 'Africa/Johannesburg', 'operator_uid': operator,
        'description': w['site_za_desc']})
    site_tw = b.new('sites', {
        'name': w['site_tw'], 'address': w['site_tw_address'], 'lat': 25.0330, 'lon': 121.5654,
        'timezone': 'Asia/Taipei', 'operator_uid': operator, 'description': w['site_tw_desc']})
    sites = [site, site_dr, site_tx, site_pr, site_za, site_tw]

    src = _power_chain(b, site)
    floors = _floors(b, site)
    net = {}
    _basement(b, floors['floor_basement'])
    _ground(b, site, floors['floor_ground'], src, net)
    _first(b, floors['floor_first'], src, net, customer)
    _second(b, site, floors['floor_second'], src, net)
    _third(b, site, floors['floor_third'], src, net)
    _dr(b, site, site_dr, net)
    _americas(b, site, site_tx, site_pr, net)
    _far(b, site, site_tx, site_za, site_tw, net)
    _common(b, floors)
    # El cableado estructurado de toda la oficina: los puestos, sus rosetas, el cable horizontal,
    # las subidas, el anillo de fibra (`demo_cabling`). Antes de ordenar
    # los enchufes de las PDU: los switches de acceso que pone también tiran de ellas.
    from lib.core.dcim import demo_cabling                 # noqa: PLC0415
    # Y las fuentes: las tomas de corriente de los puestos y las salas cuelgan de ellas.
    net['sources'] = src
    demo_cabling.build(b, site, floors, net)
    for room in [r for s in sites for r in store.rooms_of(s)]:
        for rack in store.racks_of(room['uid']):
            b.tidy_outlets(rack['uid'])
    _states(b, site)
    _access(b, floors)
    _safety(b, floors)
    _place_sources(b, site)
    _room_states(b, site)
    return {'site': site, 'site_dr': site_dr, 'site_tx': site_tx, 'site_pr': site_pr,
            'site_za': site_za, 'site_tw': site_tw,
            'sites': len(sites), 'floors': len(floors), **_counts(store, sites)}


def _counts(store, site_uids: list) -> dict:
    rooms = [r for s in site_uids for r in store.rooms_of(s)]
    racks = [k for r in rooms for k in store.racks_of(r['uid'])]
    items = [i for k in racks for i in store.items_of(k['uid'])]         + [i for r in rooms for i in store.items_in_room(r['uid'])]
    pdus = [p for k in racks for p in store.pdus_of(k['uid'])]
    return {'rooms': len(rooms), 'racks': len(racks), 'items': len(items), 'pdus': len(pdus),
            'feeds': len(store.feeds_of([p['uid'] for p in pdus])),
            'cables': len(store.cables_of([i['uid'] for i in items])),
            'features': sum(len(store.features_of(r['uid'])) for r in rooms),
            'walls': sum(len(store.walls_of(f['uid'])) for s in site_uids
                         for f in store.floors_of(s)),
            'sources': sum(len(store.sources_of(s)) for s in site_uids),
            'links': len(store.links_of(site_uids)),
            'parts': len(store.parts_of([i['uid'] for i in items]))}


# ── Power: from the street to the UPS ────────────────────────────────────────────────────────

def _power_chain(b: _Builder, site: str) -> dict:
    w = b.w
    mains = b.new('sources', {'site_uid': site, 'name': w['src_mains'], 'kind': 'mains',
                              'capacity_w': 250000, 'description': w['src_mains_desc']})
    gen = b.new('sources', {'site_uid': site, 'name': w['src_gen'], 'kind': 'generator',
                            'capacity_w': 200000, 'autonomy_min': 480, 'description': w['src_gen_desc']})
    cgbt = b.new('sources', {'site_uid': site, 'name': w['src_cgbt'], 'kind': 'panel',
                             'upstream_uid': mains, 'capacity_w': 250000})
    cpd = b.new('sources', {'site_uid': site, 'name': w['src_cpd'], 'kind': 'panel',
                            'upstream_uid': cgbt, 'capacity_w': 160000})
    ups_a = b.new('sources', {'site_uid': site, 'name': w['src_ups_a'], 'kind': 'ups',
                              'upstream_uid': cpd, 'capacity_w': 80000, 'autonomy_min': 15,
                              'description': w['src_ups_a_desc']})
    ups_b = b.new('sources', {'site_uid': site, 'name': w['src_ups_b'], 'kind': 'ups',
                              'upstream_uid': cpd, 'capacity_w': 80000, 'autonomy_min': 12,
                              'bypass': 1, 'bypass_at': '2026-10-01T08:00:00',
                              'description': w['src_ups_b_desc']})
    p2 = b.new('sources', {'site_uid': site, 'name': w['src_p2'], 'kind': 'panel',
                           'upstream_uid': cgbt, 'capacity_w': 40000})
    p3 = b.new('sources', {'site_uid': site, 'name': w['src_p3'], 'kind': 'panel',
                           'upstream_uid': cgbt, 'capacity_w': 60000})
    return {'mains': mains, 'gen': gen, 'cgbt': cgbt, 'cpd': cpd, 'a': ups_a, 'b': ups_b,
            'p2': p2, 'p3': p3}


# ── Floors, plans and walls ──────────────────────────────────────────────────────────────────

#: The corridor down the middle of every floor: between the centre lines of its two walls. 2 m
#: apart, 1.88 m clear — over the 1.20 m of an accessible route (CTE DB-SUA 9, room for a
#: wheelchair to turn, Ø 1.50 m) and the 1.00 m of an evacuation one (CTE DB-SI 3).
_HALL = (9000, 11000)
#: A room's depth, from the façade to the corridor: every room on a floor reaches both.
_BAND = _HALL[0] - _OUTER
#: The toilets, at the same place on every floor where people work, so their drains go straight
#: down (RD 486/1997, annex V; one of them accessible, CTE DB-SUA 9).
_WC = ('wc', 25700, _OUTER, 4000, _BAND)
#: The second way out of every floor, at the west end of the corridor: the exterior escape stair
#: (the street door on the ground floor). With the stair core at the east end, two exits: the
#: longest route may then be 50 m, and none here passes 40 (CTE DB-SI 3, table 3.1).
_EXIT_W = ('W', _HALL[0] + 500, _HALL[1] - 500)

#: Each floor: its text key, level, rooms ``(key, x, y, w, d)``, windows (x ranges on the north
#: façade, ``(x1, x2, 'S')`` on the south one) and its doors in the façade (``('S', x1, x2)``,
#: ``('N', x1, x2)`` or ``('W', y1, y2)``). A room's name is ``room_<key>``.
#:
#: Laid out as an architect would, to the rules in force in Spain: the rooms on either side of
#: the corridor, wall to wall —a partition is shared, there is no gap between two rooms that
#: could pass for a corridor—, each with its door on the corridor; the stair core, the lift and
#: the floor lobby at the east end (`_CORE`); natural light for whoever works at a desk
#: (RD 486/1997), none for the technical rooms; and one telecommunications room per floor
#: within 90 m of every outlet (UNE-EN 50173-1, UNE-EN 50174-1).
_S = _HALL[1]
_FLOORS = (
    ('floor_ground', 0, (('com', 300, 300, 6000, _BAND),
                         ('lab', 6300, 300, 9000, _BAND),
                         ('exp', 15300, 300, 10400, _BAND),
                         _WC,
                         ('meet0', 300, _S, 7000, _BAND),
                         ('recep', 7300, _S, 4500, _BAND),
                         ('meet0b', 18200, _S, 6300, _BAND)),
     ((8000, 10000), (12000, 14000), (16500, 19500), (26500, 28500),
      (1500, 6000, 'S'), (8300, 10800, 'S'), (19200, 23500, 'S')),
     (('S', 14000, 16000), _EXIT_W, ('N', 21000, 24000))),
    ('floor_first', 1, (('cpd', 300, 300, 16000, _BAND),
                        ('alm', 16300, 300, 5000, _BAND),
                        ('off_ops', 21300, 300, 4400, _BAND),
                        _WC,
                        ('noc', 300, _S, 9000, _BAND),
                        ('stage', 9300, _S, 8000, _BAND),
                        ('meet1', 17300, _S, 7200, _BAND)),
     ((22300, 24700), (26500, 28500),
      (1800, 7800, 'S'), (10500, 16000, 'S'), (18800, 23000, 'S')),
     (_EXIT_W,)),
    ('floor_second', 2, (('open2', 300, 300, 14000, _BAND),
                         ('meet_a', 14300, 300, 4400, _BAND),
                         ('meet_b', 18700, 300, 4000, _BAND),
                         ('idf2', 22700, 300, 3000, _BAND),
                         _WC,
                         ('off_dir', 300, _S, 2800, _BAND),
                         ('off_fin', 3100, _S, 2800, _BAND),
                         ('off_rrhh', 5900, _S, 2800, _BAND),
                         ('off_it', 8700, _S, 2800, _BAND),
                         ('kitchen', 11500, _S, 4200, _BAND),
                         ('train', 15700, _S, 8800, _BAND)),
     ((1000, 5000), (6000, 10000), (11000, 14000), (15000, 18000), (19500, 22000),
      (26500, 28500), (1000, 2400, 'S'), (3800, 5200, 'S'), (6600, 8000, 'S'),
      (9400, 10800, 'S'), (12500, 15000, 'S'), (17000, 23500, 'S')),
     (_EXIT_W,)),
    ('floor_third', 3, (('srv', 300, 300, 7000, _BAND),
                        ('hpc', 7300, 300, 12000, _BAND),
                        ('idf3', 19300, 300, 3000, _BAND),
                        ('off_cto', 22300, 300, 3400, _BAND),
                        _WC,
                        ('open3', 300, _S, 13400, _BAND),
                        ('meet3', 13700, _S, 5400, _BAND),
                        ('kitchen', 19100, _S, 5400, _BAND)),
     ((22800, 25200), (26500, 28500), (1000, 5000, 'S'), (6000, 10000, 'S'),
      (10500, 13200, 'S'), (14500, 18500, 'S'), (20000, 23500, 'S')),
     (_EXIT_W,)),
    ('floor_basement', -1, (('ene', 300, 300, 13400, _BAND),
                            ('gen', 13700, 300, 7000, _BAND),
                            ('bat', 20700, 300, 5000, _BAND),
                            ('pci', 25700, 300, 4000, _BAND)),
     (),
     (_EXIT_W,)),
)


def _walls(rooms: tuple, windows: tuple, doors: tuple) -> list[dict]:
    """The walls of a floor, as the editor stores them: centre lines in millimetres. Two rooms
    side by side share one partition: it is written once."""
    h = _OUTER / 2
    out = [{'kind': 'wall', 'x1': h, 'y1': h, 'x2': _W - h, 'y2': h, 'thick_mm': _OUTER},
           {'kind': 'wall', 'x1': _W - h, 'y1': h, 'x2': _W - h, 'y2': _D - h, 'thick_mm': _OUTER},
           {'kind': 'wall', 'x1': _W - h, 'y1': _D - h, 'x2': h, 'y2': _D - h, 'thick_mm': _OUTER},
           {'kind': 'wall', 'x1': h, 'y1': _D - h, 'x2': h, 'y2': h, 'thick_mm': _OUTER}]
    for win in windows:
        y = _D - h if len(win) > 2 and win[2] == 'S' else h
        out.append({'kind': 'window', 'x1': win[0], 'y1': y, 'x2': win[1], 'y2': y,
                    'thick_mm': _OUTER})
    for side, a, z in doors:
        if side == 'W':
            out.append({'kind': 'door', 'x1': h, 'y1': a, 'x2': h, 'y2': z, 'thick_mm': _OUTER})
        else:
            y = _D - h if side == 'S' else h
            out.append({'kind': 'door', 'x1': a, 'y1': y, 'x2': z, 'y2': y, 'thick_mm': _OUTER})
    edge = _OUTER + 10
    vistos = set()

    def tabique(x1, y1, x2, y2):
        clave = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        if clave not in vistos:
            vistos.add(clave)
            out.append({'kind': 'wall', 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                        'thick_mm': _INNER})

    for _key, x, y, w, d in rooms:
        # Only the sides that are not the building's own wall.
        if x + w < _W - edge:
            tabique(x + w, y, x + w, y + d)
        if x > edge:
            tabique(x, y, x, y + d)
        if y > edge:
            tabique(x, y, x + w, y)
        if y + d < _D - edge:
            tabique(x, y + d, x + w, y + d)
        # The door, on the side that gives onto the corridor.
        mid, ly = x + w / 2, (y if _door_on_top(y, d) else y + d)
        out.append({'kind': 'door', 'x1': mid - 500, 'y1': ly, 'x2': mid + 500, 'y2': ly,
                    'thick_mm': _INNER})
    return out


def _door_on_top(y: float, d: float) -> bool:
    """Whether a room's door is on its top side: it is against the building's back wall, so
    the corridor is above it."""
    return y + d >= _D - _OUTER - 10


def _svg(title: str, rooms: list, walls: list) -> str:
    """The background plan of a floor, drawn from its own walls: 1 px = 10 mm. *rooms* is
    ``[(name, x, y, w, d)]``."""
    k = 10.0
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
             % (_W / k, _D / k, _W / k, _D / k),
             '<rect width="100%" height="100%" fill="#ffffff"/>',
             '<g stroke-linecap="square">']
    line = '<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="%g"/>'
    for wall in walls:
        if wall['kind'] == 'wall':
            parts.append(line % (wall['x1'] / k, wall['y1'] / k, wall['x2'] / k, wall['y2'] / k,
                                 '#1f2937', wall['thick_mm'] / k))
    for wall in walls:
        if wall['kind'] not in ('door', 'window'):
            continue
        # The gap, then what fills it: a door leaf, or a window's thin double line.
        x1, y1, x2, y2 = wall['x1'] / k, wall['y1'] / k, wall['x2'] / k, wall['y2'] / k
        parts.append(line % (x1, y1, x2, y2, '#ffffff', wall['thick_mm'] / k + 1))
        if wall['kind'] == 'window':
            for off in (-0.8, 0.8):
                parts.append(line % (x1, y1 + off, x2, y2 + off, '#60a5fa', 0.6))
        elif x1 == x2:
            # In a side façade: the leaf opens inwards, across the corridor.
            r = abs(y2 - y1)
            parts.append('<path d="M %g %g L %g %g A %g %g 0 0 0 %g %g" fill="none" '
                         'stroke="#9ca3af" stroke-width="0.8"/>'
                         % (x1, y1, x1 + r, y1, r, r, x1, y1 + r))
        else:
            r = abs(x2 - x1)
            parts.append('<path d="M %g %g L %g %g A %g %g 0 0 1 %g %g" fill="none" '
                         'stroke="#9ca3af" stroke-width="0.8"/>'
                         % (x1, y1, x1, y1 + r, r, r, x1 + r, y1))
    parts.append('</g>')
    cx, cy = _CORE[0] / k, _CORE[1] / k
    parts.append('<rect x="%g" y="%g" width="300" height="250" fill="none" stroke="#6b7280" '
                 'stroke-width="2"/>' % (cx - 150, cy - 125))
    for i in range(1, 10):
        parts.append(line % (cx - 150 + i * 30, cy - 125, cx - 150 + i * 30, cy + 125,
                             '#9ca3af', 1))
    text = ('<text x="%g" y="%g" font-family="sans-serif" font-size="%d" fill="%s" '
            'text-anchor="%s"%s>%s</text>')
    for name, x, y, w, d in rooms:
        # Del tamaño que cabe en la sala: a 34 px fijos, el nombre de un despacho de 3,5 m se
        # salía por los dos lados y se mezclaba con el de al lado. Arriba y no en el centro,
        # donde lo tapa lo primero que se pone en la sala.
        talla = max(12, min(34, int((w / k * 0.9) / max(1, len(str(name)) * 0.56))))
        parts.append(text % ((x + w / 2) / k, (y + 200) / k + talla, talla, '#374151', 'middle',
                             '', _xml(name)))
    parts.append('</svg>')
    return ''.join(parts)


def _xml(value: str) -> str:
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _floors(b: _Builder, site: str) -> dict:
    """The floors with plan, walls, stair core and their rooms. Returns, by the floor's text
    key, ``{'uid', 'name', 'site', 'rooms': {key: uid}, 'size': {key: (w, d, door on top)}}``."""
    out = {}
    for key, level, rooms, windows, doors in _FLOORS:
        name = b.w[key]
        walls = _walls(rooms, windows, doors)
        named = [(b.w['room_' + rk], x, y, w, d) for rk, x, y, w, d in rooms]
        floor = b.new('floors', {'site_uid': site, 'name': name, 'level': level,
                                 'plan': b.plan(_svg('%s · %s' % (SITE, name), named, walls)),
                                 'plan_mm': _W, 'plan_x': 0, 'plan_y': 0, 'north_deg': 0,
                                 'core_kind': 'stairs', 'core_x': _CORE[0], 'core_y': _CORE[1]})
        b.s.set_walls(floor, walls, actor=b.actor)
        uids, size = {}, {}
        for rk, x, y, w, d in rooms:
            uids[rk] = b.new('rooms', {'site_uid': site, 'floor_uid': floor,
                                       'name': b.w['room_' + rk], 'width_mm': w, 'depth_mm': d,
                                       'pos_x': x, 'pos_y': y, 'rotation': 0})
            size[rk] = (w, d, _door_on_top(y, d))
        out[key] = {'uid': floor, 'name': name, 'site': site, 'rooms': uids, 'size': size,
                    'key': key}
    return out


def _area(b: _Builder, floor: dict) -> str:
    """The general area of a floor — the same room the panel makes the first time something is
    put on the floor outside every room."""
    area = b.new('rooms', {'site_uid': floor['site'], 'floor_uid': floor['uid'],
                           'name': '%s · %s' % (floor['name'], b.area_word),
                           'pos_x': 0, 'pos_y': 0, 'rotation': 0})
    b.s.floors.update(floor['uid'], {'area_uid': area}, actor=b.actor)
    return area


# ── Basement: energy ─────────────────────────────────────────────────────────────────────────

def _basement(b: _Builder, floor: dict) -> None:
    w = b.w
    ene, gen = floor['rooms']['ene'], floor['rooms']['gen']
    b.s.rooms.update(ene, {'cooling': 'room', 'description': w['room_ene_desc']}, actor=b.actor)
    b.s.rooms.update(gen, {'cooling': 'none'}, actor=b.actor)
    # La acometida: el cuadro de la compañía, a la izquierda del general (se lleva a la pared).
    b.feature(ene, 'panel', w['src_mains'], 300, 2600, 900, 400)
    b.feature(ene, 'panel', w['src_cgbt'], 600, 400, 2400, 600)
    b.feature(ene, 'panel', w['src_cpd'], 3400, 400, 1600, 600)
    b.feature(ene, 'ups', w['src_ups_a'], 6000, 300, rot=180)
    b.feature(ene, 'ups', w['src_ups_b'], 7600, 300, rot=180)
    b.feature(ene, 'zone', w['ene_batteries'], 8000, 5200, 3000, 2000)
    b.feature(ene, 'crac', w['ene_crac'], 11200, 3000, rot=270)
    b.feature(ene, 'extinguisher', w['extinguisher_co2'], 300, 7300)
    b.feature(ene, 'label', w['ene_sign'], 1000, 5500)
    b.door(ene, *floor['size']['ene'][:2], fire=True)
    b.feature(gen, 'zone', w['src_gen'], 1000, 3800, 4000, 1800)
    b.feature(gen, 'extinguisher', w['extinguisher_powder'], 6400, 300)
    b.door(gen, *floor['size']['gen'][:2], fire=True)
    bat = floor['rooms']['bat']
    b.s.rooms.update(bat, {'cooling': 'room', 'description': w['room_bat_desc']}, actor=b.actor)
    for i in range(3):
        b.feature(bat, 'cabinet', '%s %d' % (w['bat_racks'], i + 1), 600 + i * 1300, 600,
                  1100, 700, rot=180, shelves=4)
    b.feature(bat, 'crac', w['bat_fan'], 4300, 2200, 600, 400, rot=270, base_mm=2300, height_mm=400)
    b.feature(bat, 'extinguisher', w['extinguisher_co2'], 300, 4300)
    b.door(bat, *floor['size']['bat'][:2], fire=True)
    # Lo que alimenta las BIE de todo el edificio: un aljibe y su grupo de presión (RIPCI, RD
    # 513/2017; UNE 23500), en su propio local.
    pci = floor['rooms']['pci']
    b.s.rooms.update(pci, {'cooling': 'none', 'description': w['room_pci_desc']}, actor=b.actor)
    b.feature(pci, 'zone', w['pci_tank'], 300, 300, 3400, 4200)
    b.feature(pci, 'zone', w['pci_pumps'], 300, 5000, 2400, 1600)
    b.feature(pci, 'panel', w['pci_panel'], 3000, 5000, 600, 300)
    b.door(pci, *floor['size']['pci'][:2], fire=True)


# ── Ground floor: communications, lab, dispatch, a rack in the corridor ──────────────────────

def _ground(b: _Builder, site: str, floor: dict, src: dict, net: dict) -> None:
    w = b.w
    com, lab, exp = floor['rooms']['com'], floor['rooms']['lab'], floor['rooms']['exp']
    b.s.rooms.update(com, {'cooling': 'split', 'description': w['room_com_desc']}, actor=b.actor)
    b.s.rooms.update(lab, {'cooling': 'split'}, actor=b.actor)
    b.s.rooms.update(exp, {'cooling': 'none'}, actor=b.actor)

    # Communications room: the operators' rack, with a UPS on the floor beside it.
    rack = b.new('racks', {'room_uid': com, 'name': 'COM-01', 'u_height': 42, 'width_mm': 800,
                           'depth_mm': 1000, 'pos_x': 800, 'pos_y': 800, 'rotation': 180,
                           'access': 'front,rear,right', 'description': w['rack_com_desc']})
    ups_item = b.item(rack, w['ups_com_item'], 'ups', placement='near')
    ups = b.new('sources', {'site_uid': site, 'name': w['src_ups_com'], 'kind': 'ups',
                            'upstream_uid': src['cgbt'], 'capacity_w': 2700, 'autonomy_min': 25,
                            'item_uid': ups_item})
    pdu = b.new('pdus', {'rack_uid': rack, 'name': w['pdu_com'], 'feed': 'a', 'outlets': 12,
                         'capacity_w': 2700, 'source_uid': ups,
                         'item_uid': b.item(rack, 'PDU-COM', 'pdu', placement='side')})
    b.item(rack, w['fiber_operators'], 'fiber_panel', 42, face='front', model='fiber')
    fibra_plantas = b.item(rack, w['fiber_floors'], 'fiber_panel', 41, face='front', model='fiber')
    # El repartidor de la planta baja y del sótano: sus paneles y switches de acceso los pone el
    # cableado estructurado (`demo_cabling`) según los puestos que tenga que servir.
    net.setdefault('dists', {})['com'] = {'kind': 'com', 'tag': 'P0', 'rack': rack, 'power': pdu,
                                          'fiber': fibra_plantas, 'floor': 'floor_ground',
                                          'pairs': []}
    ont = b.item(rack, w['ont'], 'router', 38, u_slots=2, u_slot=1, model='cpe')
    cpe = b.item(rack, w['cpe'], 'router', 38, u_slots=2, u_slot=2, model='cpe')
    sw = b.item(rack, 'SW-COM', 'switch', 36, model='access')
    b.item(rack, w['blank'], 'blank', 37, face='front')
    for it, role in ((ont, 'router'), (cpe, 'router'), (sw, 'switch')):
        b.feed(it, pdu, _WATTS[role])
    b.cable(ont, 'Gi0/1', sw, 'Gi1/0/1', color='yellow', length=1000)
    b.cable(cpe, 'Gi0/1', sw, 'Gi1/0/2', color='yellow', length=1000)
    net['com_sw'], net['ont'], net['cpe'] = sw, ont, cpe
    b.feature(com, 'crac', w['split'], 5000, 3500, 800, 300, base_mm=2200, height_mm=300)
    b.feature(com, 'extinguisher', w['extinguisher_co2'], 300, 4400)
    b.door(com, *floor['size']['com'][:2])

    # Lab: a wall-mounted cabinet and a small rack.
    wall = b.new('racks', {'room_uid': lab, 'name': 'LAB-W1', 'u_height': 12, 'width_mm': 600,
                           'depth_mm': 450, 'pos_x': 300, 'pos_y': _FACE, 'rotation': 180,
                           'base_mm': 1200, 'access': 'front', 'description': w['rack_wall_desc']})
    b.item(wall, w['patch'] % 'LAB', 'patch_panel', 12, face='front', model='patch')
    lab_sw = b.item(wall, 'SW-LAB', 'switch', 11, model='access')
    b.item(wall, w['wall_strip'], 'pdu', 1)
    lab_rack = b.new('racks', {'room_uid': lab, 'name': 'LAB-01', 'u_height': 24,
                               'width_mm': 600, 'depth_mm': 800, 'pos_x': 2000, 'pos_y': 600,
                               'rotation': 180})
    pdus = b.pdus(lab_rack, 'LAB-01', (src['a'], src['b']), capacity=3700)
    lab_tor = b.item(lab_rack, 'SW-LAB-01', 'switch', 24, model='tor')
    b.dual(lab_tor, 'switch', pdus)
    shelf = b.item(lab_rack, w['shelf'], 'shelf', 20)
    for slot in (1, 2):
        mini = b.item(lab_rack, w['mini_pc'] % slot, 'server', 20, 1, parent_uid=shelf,
                      u_slots=2, u_slot=slot, model='mini', depth_mm=180)
        b.feed(mini, pdus[slot - 1], 65)
        b.cable(mini, 'eth0', lab_tor, 'Gi1/0/%d' % slot, length=1000)
    for i, u in enumerate((1, 3, 5)):
        srv = b.item(lab_rack, 'lab-srv-%02d' % (i + 1), 'server', u, 2, depth_mm=700, model='server')
        b.dual(srv, 'server', pdus)
        b.cable(srv, 'eth0', lab_tor, 'Gi1/0/%d' % (i + 3), length=1500)
    b.cable(lab_tor, 'Gi1/0/48', lab_sw, 'Gi1/0/1', color='green', length=4000)
    b.feature(lab, 'bench', w['lab_bench_test'], 4000, 4500, 2400, 900)
    b.feature(lab, 'bench', w['lab_bench_solder'], 6800, 4500)
    b.feature(lab, 'cabinet', w['lab_cabinet'], 7800, 100, rot=180, shelves=3)
    b.door(lab, *floor['size']['lab'][:2])

    # Dispatch: the loading bay, at its door in the façade, and the packing material.
    b.feature(exp, 'zone', w['exp_dock'], 5700, 300, 3000, 2500)
    b.feature(exp, 'bench', w['exp_bench'], 1500, 1500, 2400, 900)
    cab = b.feature(exp, 'cabinet', w['exp_cabinet'], 600, 4000, shelves=2)
    b.shelf_items(cab, [(1, w['exp_boxes'], 30, ''), (2, w['exp_film'], 6, '')])
    b.door(exp, *floor['size']['exp'][:2])

    # The floor's general area: a wall rack in the corridor and the floor's electrical panel.
    # Hung on the corridor face of the meeting room's wall, near its corner: clear of its door
    # (the wall's middle) and of the extinguisher and call point (its start). A rack standing
    # loose in the middle of the hall is not where anyone puts one. And above 2.20 m: lower, its
    # 450 mm would stick out into an evacuation route where someone walks into it (CTE DB-SUA 2,
    # 1.1 — nothing may project more than 150 mm between 0.15 and 2.20 m).
    area = _area(b, floor)
    mx, my, mw, _md = next(g[1:] for g in _FLOORS[0][2] if g[0] == 'meet0')
    hall = b.new('racks', {'room_uid': area, 'name': w['rack_hall'], 'u_height': 12,
                           'width_mm': 600, 'depth_mm': 450,
                           'pos_x': mx + mw - 1100, 'pos_y': my - _INNER / 2 - 450,
                           'rotation': 0, 'base_mm': 2250, 'access': 'front'})
    hall_pdu = b.new('pdus', {'rack_uid': hall, 'name': w['pdu_hall'], 'feed': 'a', 'outlets': 8,
                              'capacity_w': 3600, 'source_uid': src['cgbt'],
                              # Its only door is the front, so its strip is plugged from there.
                              'item_uid': b.item(hall, 'PDU-P0', 'pdu', 1, face='front',
                                                 depth_mm=200)})
    b.item(hall, w['patch'] % 'P0', 'patch_panel', 12, face='front', model='patch')
    hall_sw = b.item(hall, 'SW-P0', 'switch', 11, model='access')
    b.feed(hall_sw, hall_pdu, 150)
    b.cable(hall_sw, 'Gi1/0/23', lab_sw, 'Gi1/0/2', color='green', length=12000)
    b.cable(hall_sw, 'Te1/1/1', sw, 'Gi1/0/24', kind='fiber', category='om4', color='cyan',
            length=15000)
    net['hall_sw'] = hall_sw
    x, y, rot = _on_wall(_W - _OUTER, _D - _OUTER, 'right', 12500, 900, 400, _OUTER, _OUTER)
    b.feature(area, 'panel', w['floor_panel'], x, y, 900, 400, rot=rot)
    x, y, rot = _on_wall(_W - _OUTER, _D - _OUTER, 'bottom', 13000, 300, 300, _OUTER, _OUTER)
    b.feature(area, 'extinguisher', w['extinguisher_floor'], x, y, rot=rot, base_mm=0)
    b.feature(area, 'label', w['entrance'], 14200, 18000)

    # Reception, by the entrance, and the big meeting room.
    recep, meet0 = floor['rooms']['recep'], floor['rooms']['meet0']
    b.s.rooms.update(recep, {'cooling': 'split'}, actor=b.actor)
    b.s.rooms.update(meet0, {'cooling': 'split'}, actor=b.actor)
    b.feature(recep, 'bench', w['recep_counter'], 600, 2600, 3200, 800, rot=180)
    b.feature(recep, 'zone', w['recep_wait'], 600, 4400, 3000, 1600)
    b.feature(recep, 'cabinet', w['recep_lockers'], 3300, 7600, 1000, 500, shelves=3)
    b.feature(recep, 'label', w['room_recep'], 2000, 1300)
    b.door(recep, *floor['size']['recep'][:2], top=True)
    b.feature(meet0, 'bench', w['table'] % 12, 1700, 2200, 4000, 1400)
    b.feature(meet0, 'label', w['screen'], 2900, 5200, 1600, 400)
    # Girado sobre su centro: para que quede pegado a la pared derecha, el centro va a 125 mm de
    # ella —la mitad de su fondo—, y la caja sin girar empieza 450 mm a su izquierda.
    b.feature(meet0, 'crac', w['split_n'] % 1, floor['size']['meet0'][0] - 125 - 450, 2500,
              900, 250, rot=90, base_mm=2200, height_mm=300)
    b.door(meet0, *floor['size']['meet0'][:2], top=True)
    _meeting(b, floor, 'meet0b', 8, (1300, 3000, 3600, 1200))
    # Beside the turnstiles, a gate a wheelchair goes through (CTE DB-SUA 9: an accessible way
    # in where the others are turnstiles).
    b.feature(area, 'door', w['gate_accessible'], 16400, 15800, rot=180)


# ── First floor: the data centre, the technical store and the NOC ────────────────────────────

def _first(b: _Builder, floor: dict, src: dict, net: dict, customer: str) -> None:
    w = b.w
    cpd, alm, noc = floor['rooms']['cpd'], floor['rooms']['alm'], floor['rooms']['noc']
    b.s.rooms.update(cpd, {'cooling': 'cold_aisle', 'tile_mm': 600,
                           'description': w['room_cpd_desc']}, actor=b.actor)
    b.s.rooms.update(alm, {'cooling': 'none'}, actor=b.actor)
    b.s.rooms.update(noc, {'cooling': 'split'}, actor=b.actor)

    row_a = b.new('rows', {'room_uid': cpd, 'name': w['row'] % 'A',
                           'front_aisle': w['aisle_cold'] % 1, 'rear_aisle': w['aisle_hot'] % 'A'})
    row_b = b.new('rows', {'room_uid': cpd, 'name': w['row'] % 'B',
                           'front_aisle': w['aisle_cold'] % 1, 'rear_aisle': w['aisle_hot'] % 'B'})
    row_n = b.new('rows', {'room_uid': cpd, 'name': w['row'] % 'N',
                           'front_aisle': w['aisle_cold'] % 2, 'rear_aisle': w['aisle_hot'] % 'B',
                           'description': w['row_n_desc']})

    # The network row first: every rack's top-of-rack switch goes to both cores.
    cores = []
    for n in (1, 2):
        name = 'N0%d' % n
        rack = b.new('racks', {'room_uid': cpd, 'name': name, 'u_height': 42,
                               'width_mm': 800, 'depth_mm': 1000, 'pos_x': 1500 + (n - 1) * 800,
                               'pos_y': 7000, 'rotation': 0, 'row_uid': row_n,
                               'rail_front_mm': 100, 'rail_depth_mm': 740, 'rail_rear_mm': 160})
        # The network row keeps both strips on the left: its right channel is where the
        # patching runs.
        pdus = b.pdus(rack, name, (src['a'], src['b']), where=PDU_SAME_LEFT)
        net.setdefault('cpd_fiber', []).append(
            b.item(rack, w['fiber_trunk'], 'fiber_panel', 42, face='front', model='fiber'))
        net.setdefault('cpd_patch', []).append(
            b.item(rack, w['patch'] % name, 'patch_panel', 41, face='front', model='patch'))
        if n == 1:
            # Y el repartidor de la primera planta —el NOC, el almacén—, en la fila de red.
            net['cpd_rack'] = rack
            net.setdefault('dists', {})['cpd'] = {'kind': 'cpd', 'tag': 'P1', 'rack': rack,
                                                  'power': pdus, 'fiber': None,
                                                  'floor': 'floor_first', 'pairs': []}
        core = b.item(rack, 'CORE-%d' % n, 'switch', 38, 2, depth_mm=500, model='core')
        rtr = b.item(rack, 'RTR-%d' % n, 'router', 36, model='router')
        fw = b.item(rack, 'FW-%d' % n, 'firewall', 34, model='firewall')
        net.setdefault('rtrs', []).append(rtr)
        net.setdefault('fws', []).append(fw)
        kvm = b.item(rack, w['kvm'] % name, 'kvm', 32, face='front', model='kvm')
        b.item(rack, w['console_server'], 'console', 32, face='rear', model='console')
        for it, role in ((core, 'switch'), (rtr, 'router'), (fw, 'firewall'), (kvm, 'kvm')):
            b.dual(it, role, pdus)
        b.cable(rtr, 'Gi0/1', fw, 'port1', color='red', length=1000)
        b.cable(fw, 'port2', core, 'Gi1/0/1', color='red', length=1000)
        b.new('parts', {'item_uid': core, 'kind': 'psu', 'model': 'PWR-C1-715WAC', 'qty': 2})
        b.new('parts', {'item_uid': core, 'kind': 'transceiver', 'model': 'SFP-10G-SR',
                        'qty': 16, 'description': w['core_uplinks']})
        cores.append((core, rtr))
    b.cable(cores[0][0], 'Te1/0/47', cores[1][0], 'Te1/0/47', kind='dac', category='dac-passive',
            color='black', length=1000, label='STACK')
    # Up to the operators on the ground floor, by fibre between floors.
    b.cable(cores[0][1], 'Te0/0/0', net['ont'], 'Te0/0/0', kind='fiber', category='os2',
            color='yellow', length=25000, label='P1-P0-01')
    b.cable(cores[1][1], 'Te0/0/0', net['cpe'], 'Te0/0/0', kind='fiber', category='os2',
            color='yellow', length=25000, label='P1-P0-02')
    b.cable(cores[0][0], 'Te1/0/48', net['com_sw'], 'Te1/1/1', kind='fiber', category='os2',
            color='yellow', length=25000, label='P1-P0-03')
    net['rtr'] = cores[0][1]
    net['cores'] = [c for c, _r in cores]

    # Rows A and B, facing each other across the confined cold aisle.
    servers = (6, 9, 4, 12, 3, 8, 10, 0)
    for letter, y, rot, row in (('A', 1500, 180, row_a), ('B', 3900, 0, row_b)):
        for i, many in enumerate(servers):
            name = '%s0%d' % (letter, i + 1)
            rack = b.new('racks', {'room_uid': cpd, 'name': name, 'u_height': 42,
                                   'width_mm': 600, 'depth_mm': 1200,
                                   'pos_x': 1500 + i * 600, 'pos_y': y, 'rotation': rot,
                                   'row_uid': row, 'access': 'front,rear'})
            if letter == 'B' and i >= 6:
                b.s.set_owner('rack', rack, customer, actor=b.actor)
            hot = letter == 'A' and i == 3           # a GPU rack, past the safe load
            pdus = b.pdus(rack, name, (src['a'], src['b']), capacity=3700 if hot else 7400)
            _compute_rack(b, rack, name, many, pdus, [c for c, _r in cores], hot,
                          storage=i == 2, halves=i == 4, single=letter == 'A' and i == 1,
                          console=letter == 'B', parts=letter == 'A' and i == 0)

    b.feature(cpd, 'aisle', w['cpd_aisle'], 1500, 2700, 4800, 1200)
    b.feature(cpd, 'tray', w['cpd_tray_a'], 1500, 1500, 4800, 300)
    b.feature(cpd, 'tray', w['cpd_tray_b'], 1500, 4800, 4800, 300)
    b.feature(cpd, 'crac', 'CRAC-1', 7000, 1600, rot=270)
    b.feature(cpd, 'crac', 'CRAC-2', 7000, 4000, rot=270)
    b.feature(cpd, 'column', w['column'], 9000, 7000)
    b.feature(cpd, 'column', w['column'], 13000, 7000)
    b.feature(cpd, 'zone', w['cpd_reserve'], 9500, 1000, 5000, 3500)
    b.feature(cpd, 'panel', w['cpd_panel'], 300, 7900)
    b.feature(cpd, 'extinguisher', w['extinguisher_co2'], 15300, 7900)
    b.feature(cpd, 'label', w['room_cpd'], 10000, 5600)
    b.door(cpd, *floor['size']['cpd'][:2], fire=True)

    # The technical store: spares and tools on shelves.
    b.shelf_items(b.feature(alm, 'cabinet', w['alm_spares'], 300, 100, rot=180, shelves=5),
                  w['spares'])
    b.shelf_items(b.feature(alm, 'cabinet', w['alm_tools'], 1500, 100, rot=180, shelves=3),
                  w['tools'])
    b.feature(alm, 'bench', w['alm_bench'], 3000, 3800)
    b.door(alm, *floor['size']['alm'][:2])

    # The NOC.
    for i in range(3):
        b.feature(noc, 'bench', w['noc_desk'] % (i + 1), 500 + i * 1900, 5200)
    b.feature(noc, 'label', w['noc_sign'], 2400, 7600)
    b.door(noc, *floor['size']['noc'][:2], top=True)

    # The operations manager's office, the staging room where servers are unpacked and tested
    # before they go into the data centre, and a meeting room.
    _private_office(b, floor, 'off_ops')
    stage = floor['rooms']['stage']
    b.s.rooms.update(stage, {'cooling': 'split', 'description': w['room_stage_desc']},
                     actor=b.actor)
    for n, (x, y) in enumerate(((800, 2200), (4400, 2200), (800, 5200), (4400, 5200))):
        b.feature(stage, 'bench', w['stage_bench'] % (n + 1), x, y, 2400, 900)
    b.feature(stage, 'cabinet', w['alm_spares'], 6800, 7900, 1000, 500, shelves=4)
    b.door(stage, *floor['size']['stage'][:2], top=True)
    _meeting(b, floor, 'meet1', 10, (1800, 3000, 3600, 1200))


def _compute_rack(b: _Builder, rack: str, name: str, many: int, pdus: tuple, cores: list,
                  hot: bool, *, storage: bool, halves: bool, single: bool, console: bool,
                  parts: bool) -> None:
    """A row rack: patch panel and top-of-rack switch at the top, servers from the bottom."""
    w = b.w
    b.item(rack, w['patch'] % name, 'patch_panel', 42, face='front', model='patch')
    tor = b.item(rack, 'SW-%s' % name, 'switch', 41, model='tor')
    b.dual(tor, 'switch', pdus)
    b.item(rack, w['cable_manager'], 'blank', 40, face='front')
    for n, core in enumerate(cores):
        # A la boca de este armario en cada núcleo: la A01 a la 1, la B08 a la 16.
        boca = 'AB'.index(name[0]) * 8 + int(name[1:]) if name[0] in 'AB' else 40
        b.cable(tor, 'Te1/1/%d' % (n + 1), core, 'Te1/0/%d' % boca, kind='fiber',
                category='om4', color='cyan', length=12000)
    if console:
        b.item(rack, w['blank'], 'blank', 39, face='front')
        b.item(rack, w['serial_console'] % name, 'console', 39, face='rear', model='console')
    port = 0
    for k in range(many):
        label = '%s-%s-%02d' % ('gpu' if hot else 'srv', name.lower(), k + 1)
        srv = b.item(rack, label, 'server', 1 + 2 * k, 2, depth_mm=750,
                     supplier=w['supplier'], purchased_at='2025-03-15',
                     warranty_until='2030-03-15', model='gpu' if hot else 'server')
        if single and k == 0:
            # One server with both cords on branch A: the power view flags it.
            b.feed(srv, pdus[0], 225)
            b.feed(srv, pdus[0], 225)
        else:
            b.dual(srv, 'server', pdus, watts=1200 if hot else 0)
        port += 1
        b.cable(srv, 'eth0', tor, 'Gi1/0/%d' % port, color='blue', length=2000)
        if parts and k < 3:
            b.new('parts', {'item_uid': srv, 'kind': 'memory', 'size': '32 GB', 'qty': 8,
                            'brand': 'Demo', 'model': 'DDR5-4800 RDIMM'})
            b.new('parts', {'item_uid': srv, 'kind': 'ssd', 'size': '1.92 TB', 'qty': 4,
                            'model': 'NVMe U.2'})
            b.new('parts', {'item_uid': srv, 'kind': 'psu', 'size': '800 W', 'qty': 2})
    if storage:
        st = b.item(rack, w['storage'], 'storage', 30, 4, depth_mm=900, model='storage')
        b.dual(st, 'storage', pdus)
        b.cable(st, 'ctrlA-0', tor, 'Te1/1/3', kind='dac', category='dac-passive',
                color='black', length=2000)
        b.cable(st, 'ctrlB-0', tor, 'Te1/1/4', kind='dac', category='dac-passive',
                color='black', length=2000)
    if halves:
        for slot in (1, 2):
            node = b.item(rack, w['node'] % slot, 'server', 36, 1, u_slots=2, u_slot=slot, model='node')
            b.dual(node, 'server', pdus, watts=300)
            port += 1
            b.cable(node, 'eth0', tor, 'Gi1/0/%d' % port, length=1500)


# ── Offices: desks, private offices, meeting rooms ───────────────────────────────────────────

def _desks(b: _Builder, room: str, islands: list, floor_no: int, first: int = 1,
           width: int = 1600) -> int:
    """Islands of six desks back to back, three a side: ``islands`` are their top-left corners.
    Each desk is called by its floor and number, «P2.07», which is what the outlet under it says
    —short, so it fits on the desk in the plan—. Returns the next number."""
    n = first
    for ox, oy in islands:
        for fila, rot in ((0, 0), (1, 180)):
            for c in range(3):
                b.feature(room, 'bench', b.w['desk'] % ('%d.%02d' % (floor_no, n)),
                          ox + c * width, oy + fila * 800, width, 800, rot=rot)
                n += 1
    return n


def _private_office(b: _Builder, floor: dict, key: str, extra: str = '') -> None:
    """A private office: a desk, a cabinet and, for some, a round table or a test bench."""
    w = b.w
    room = floor['rooms'][key]
    ancho, fondo, arriba = floor['size'][key]
    b.s.rooms.update(room, {'cooling': 'split', 'description': w['room_office_desc']}, actor=b.actor)
    b.feature(room, 'bench', w['desk_named'] % w['room_' + key], 600, 1500, 1800, 800)
    # Against the façade, its front into the office: up from the bottom wall, down from the top.
    b.feature(room, 'cabinet', w['floor_cabinet'], 300, 100 if not arriba else fondo - 600,
              1000, 500, rot=0 if arriba else 180, shelves=2)
    if extra == 'round':
        # Debajo del puesto y a un lado de la puerta: encima, se pisaban.
        b.feature(room, 'zone', w['round_table'], ancho - 1400, fondo - 1500, 1200, 1200)
    elif extra == 'bench':
        b.feature(room, 'bench', w['test_bench'], 600, 2900, 1800, 700)
    b.door(room, ancho, fondo, top=arriba)


def _meeting(b: _Builder, floor: dict, key: str, people: int, table: tuple) -> None:
    w = b.w
    room = floor['rooms'][key]
    ancho, fondo, arriba = floor['size'][key]
    b.s.rooms.update(room, {'cooling': 'split'}, actor=b.actor)
    x, y, tw, td = table
    b.feature(room, 'bench', w['table'] % people, x, y, tw, td)
    b.feature(room, 'label', w['screen'], (ancho - 1600) / 2, 300 if not arriba else fondo - 700)
    b.door(room, ancho, fondo, top=arriba)


def _kitchen(b: _Builder, floor: dict) -> None:
    """The floor's kitchen: the counter against the façade, the tables between it and the door."""
    w = b.w
    kitchen = floor['rooms']['kitchen']
    ancho, fondo, arriba = floor['size']['kitchen']
    b.s.rooms.update(kitchen, {'cooling': 'none'}, actor=b.actor)
    b.feature(kitchen, 'bench', w['kitchen_counter'], 300, fondo - 700 if arriba else 100,
              ancho - 600, 600, rot=0 if arriba else 180)
    b.feature(kitchen, 'zone', w['kitchen_tables'], 600, 3000, ancho - 1200, 2400)
    b.door(kitchen, ancho, fondo, top=arriba)


def _toilets(b: _Builder, floor: dict) -> None:
    """The floor's toilets: women's, men's and an accessible one with the turning circle of a
    wheelchair inside (Ø 1.50 m, CTE DB-SUA 9, annex A), the washbasins by the door and the
    cleaning cupboard. Mechanical extraction, no air conditioning."""
    w = b.w
    room = floor['rooms']['wc']
    ancho, fondo, arriba = floor['size']['wc']
    b.s.rooms.update(room, {'cooling': 'none', 'description': w['room_wc_desc']}, actor=b.actor)
    b.feature(room, 'zone', w['wc_women'], 150, 150, 1800, 3000)
    b.feature(room, 'zone', w['wc_men'], 2050, 150, 1800, 3000)
    b.feature(room, 'zone', w['wc_accessible'], 150, 3400, 2200, 2400)
    b.feature(room, 'zone', w['wc_cleaning'], 2550, 3400, 1300, 1400)
    b.feature(room, 'zone', w['wc_basins'], 2550, 5100, 1300, 700)
    b.door(room, ancho, fondo, top=arriba)


def _common(b: _Builder, floors: dict) -> None:
    """What every floor has outside its rooms, in its general area: the lobby with the lift in
    front of the stair core (an accessible lift, CTE DB-SUA 9, as there is more than one floor
    above the entrance), the second way out at the west end of the corridor, and the two trays
    along the corridor's ceiling — data and power apart, as UNE-EN 50174-2 asks of a horizontal
    run beside power. The basement's south half is the car park, with an accessible space by
    the lift (CTE DB-SUA 9). And the toilets of every floor where people work."""
    w = b.w
    for fkey, floor in floors.items():
        area = b.s.floors.get(floor['uid']).get('area_uid') or _area(b, floor)
        b.feature(area, 'zone', w['lift'], _CORE[0] - 3100, _CORE[1] - 1500, 1600, 1800)
        b.feature(area, 'label', w['lobby'], _CORE[0] - 1500, _HALL[1] + 600)
        salida = w['exit_street'] if fkey == 'floor_ground' else w['exit_stair']
        b.feature(area, 'label', salida, _OUTER + 300, _HALL[0] + 150)
        b.feature(area, 'tray', w['tray_data'], _OUTER, _HALL[0] + 150, _CORE[0] - 3500 - _OUTER,
                  300)
        b.feature(area, 'tray', w['tray_power'], _OUTER, _HALL[1] - 450, _CORE[0] - 3500 - _OUTER,
                  300)
        if 'wc' in floor['rooms']:
            _toilets(b, floor)
        if fkey == 'floor_basement':
            for n in range(6):
                b.feature(area, 'zone', w['parking'] % (n + 1), 1000 + n * 2600, _S + 3200,
                          2400, 5000)
            b.feature(area, 'zone', w['parking_accessible'], 1000 + 6 * 2600, _S + 3200, 3600, 5000)


def _idf(b: _Builder, site: str, floor: dict, key: str, tag: str, panel: str, desks: int,
         cores: list, core_port: int, net: dict) -> None:
    """A floor's communications room: one rack with the fibre up to the core, a patch panel
    per 24 desks and an access switch behind each, a UPS on the floor beside it, and a wall
    split. Each panel's ports are cabled to its switch, port for port."""
    w = b.w
    room = floor['rooms'][key]
    ancho, fondo, arriba = floor['size'][key]
    b.s.rooms.update(room, {'cooling': 'split', 'description': w['room_idf_desc']}, actor=b.actor)
    rack = b.new('racks', {'room_uid': room, 'name': 'IDF-%s' % tag, 'u_height': 42,
                           'width_mm': 800, 'depth_mm': 1000, 'pos_x': 500, 'pos_y': 1200,
                           'rotation': 0, 'access': 'front,rear,left',
                           'description': w['rack_idf_desc']})
    ups_item = b.item(rack, w['ups_rack'] % tag, 'ups', placement='near')
    ups = b.new('sources', {'site_uid': site, 'name': w['src_ups_idf'] % tag, 'kind': 'ups',
                            'upstream_uid': panel, 'capacity_w': 1350, 'autonomy_min': 30,
                            'item_uid': ups_item})
    pdu = b.new('pdus', {'rack_uid': rack, 'name': w['pdu_single'] % tag, 'feed': 'a',
                         'outlets': 12, 'capacity_w': 1350, 'source_uid': ups,
                         'item_uid': b.item(rack, 'PDU-%s' % tag, 'pdu', placement='side')})
    fibra = b.item(rack, w['fiber_trunk'], 'fiber_panel', 42, face='front', model='fiber')
    # Los paneles de los puestos y sus switches de acceso, y sus subidas al núcleo por la fibra,
    # los pone el cableado estructurado (`demo_cabling`), 24 puertos cada vez según los puestos
    # que haya en la planta. `desks`, `cores` y `core_port` quedan de cuando se ponían aquí.
    _ = (desks, cores, core_port)
    net.setdefault('dists', {})[tag] = {'kind': 'idf', 'tag': tag, 'rack': rack, 'power': pdu,
                                        'fiber': fibra, 'floor': floor['key'], 'pairs': []}
    b.feature(room, 'crac', w['split_n'] % 1, ancho - 1300, 150 if not arriba else fondo - 400,
              800, 250, base_mm=2200, height_mm=300)
    b.feature(room, 'extinguisher', w['extinguisher_co2'], ancho - 500, fondo - 600)
    b.door(room, ancho, fondo, top=arriba)


def _second(b: _Builder, site: str, floor: dict, src: dict, net: dict) -> None:
    """The office floor: an open office of 24 desks, four private offices, two meeting rooms,
    a training room, the kitchen and the floor's communications room."""
    w = b.w
    open2 = floor['rooms']['open2']
    b.s.rooms.update(open2, {'cooling': 'split', 'description': w['room_office_desc']},
                     actor=b.actor)
    _desks(b, open2, [(1000, 1500), (7000, 1500), (1000, 5000), (7000, 5000)], 2)
    b.feature(open2, 'zone', w['printer'], 12500, 6800, 1200, 1000)
    b.feature(open2, 'cabinet', w['floor_cabinet'], 12600, 100, 1000, 500, rot=180, shelves=4)
    b.feature(open2, 'column', w['column'], 6200, 4300)
    b.feature(open2, 'extinguisher', w['extinguisher_co2'], 300, 8400)
    b.door(open2, *floor['size']['open2'][:2])
    _meeting(b, floor, 'meet_a', 10, (400, 1900, 3600, 1200))
    _meeting(b, floor, 'meet_b', 4, (800, 2000, 2400, 1000))
    _private_office(b, floor, 'off_dir', 'round')
    _private_office(b, floor, 'off_fin')
    _private_office(b, floor, 'off_rrhh')
    _private_office(b, floor, 'off_it', 'bench')
    _kitchen(b, floor)
    train = floor['rooms']['train']
    b.s.rooms.update(train, {'cooling': 'split'}, actor=b.actor)
    for r in range(3):
        for c in range(4):
            b.feature(train, 'bench', w['desk'] % ('F.%02d' % (r * 4 + c + 1)),
                      700 + c * 1950, 1300 + r * 1100, 1600, 700)
    b.feature(train, 'bench', w['trainer'], 3700, 4600, 1600, 700, rot=180)
    b.feature(train, 'label', w['whiteboard'], 3700, 5300)
    b.door(train, *floor['size']['train'][:2], top=True)
    _idf(b, site, floor, 'idf2', 'P2', src['p2'], 36, net['cores'], 33, net)


def _third(b: _Builder, site: str, floor: dict, src: dict, net: dict) -> None:
    """The technical floor: a server room cooled by wall splits, an HPC room with a contained
    hot aisle and in-row coolers, the floor's communications room, and offices."""
    w = b.w
    cores = net['cores']

    # The server room: splits on the wall, no containment. The racks face the splits.
    srv = floor['rooms']['srv']
    b.s.rooms.update(srv, {'cooling': 'split', 'description': w['room_srv_desc']}, actor=b.actor)
    b.feature(srv, 'crac', w['split_n'] % 1, 1300, 150, 900, 250, base_mm=2200, height_mm=300)
    b.feature(srv, 'crac', w['split_n'] % 2, 2800, 150, 900, 250, base_mm=2200, height_mm=300)
    racks = []
    for i in range(4):
        racks.append(b.new('racks', {'room_uid': srv, 'name': 'S0%d' % (i + 1), 'u_height': 42,
                                     'width_mm': 600, 'depth_mm': 1000, 'pos_x': 1200 + i * 700,
                                     'pos_y': 1300, 'rotation': 0, 'access': 'front,rear',
                                     'description': w['rack_srv_desc']}))
    ups_item = b.item(racks[3], w['ups_rack'] % 'SRV', 'ups', placement='near')
    ups = b.new('sources', {'site_uid': site, 'name': w['src_ups_srv'], 'kind': 'ups',
                            'upstream_uid': src['p3'], 'capacity_w': 6000, 'autonomy_min': 15,
                            'item_uid': ups_item})
    pdus = [b.pdus(r, 'S0%d' % (i + 1), (ups, src['p3']), capacity=3700) for i, r in enumerate(racks)]
    b.item(racks[0], w['patch'] % 'S01', 'patch_panel', 42, face='front', model='patch')
    tor = b.item(racks[0], 'SW-S01', 'switch', 41, model='tor')
    fw = b.item(racks[0], 'FW-S01', 'firewall', 39, model='firewall')
    for it, role in ((tor, 'switch'), (fw, 'firewall')):
        b.dual(it, role, pdus[0])
    b.cable(fw, 'port1', tor, 'Gi1/0/48', color='red', length=1000)
    for n, core in enumerate(cores):
        b.cable(tor, 'Te1/1/%d' % (n + 1), core, 'Te1/0/%d' % 36, kind='fiber', category='os2',
                color='yellow', length=30000, label='SRV-CORE%d' % (n + 1))
    port = 0
    for r in (1, 2):
        for k in range(6):
            srv_it = b.item(racks[r], 'srv-s0%d-%02d' % (r + 1, k + 1), 'server', 1 + 2 * k, 2,
                            depth_mm=750, model='server')
            b.dual(srv_it, 'server', pdus[r])
            port += 1
            b.cable(srv_it, 'eth0', tor, 'Gi1/0/%d' % port, color='blue', length=3000)
    st = b.item(racks[3], w['storage'], 'storage', 1, 4, depth_mm=900, model='storage')
    b.dual(st, 'storage', pdus[3])
    b.cable(st, 'ctrlA-0', tor, 'Te1/1/3', kind='fiber', category='om4', color='cyan', length=4000)
    b.cable(st, 'ctrlB-0', tor, 'Te1/1/4', kind='fiber', category='om4', color='cyan', length=4000)
    b.feature(srv, 'label', w['srv_sign'], 2000, 4300, 3000, 400)
    b.feature(srv, 'extinguisher', w['extinguisher_co2'], 6400, 5400)
    b.door(srv, *floor['size']['srv'][:2], fire=True)

    # The HPC room: two rows back to back on a contained hot aisle, in-row coolers between racks.
    hpc = floor['rooms']['hpc']
    b.s.rooms.update(hpc, {'cooling': 'hot_aisle', 'tile_mm': 600,
                           'description': w['room_hpc_desc']}, actor=b.actor)
    filas = []
    for n in (1, 2):
        filas.append(b.new('rows', {'room_uid': hpc, 'name': w['row_hpc'] % n,
                                    'front_aisle': w['aisle_hpc_cold'],
                                    'rear_aisle': w['aisle_hpc_hot']}))
    huecos = ['R', 'R', 'C', 'R', 'R', 'C', 'R', 'R']
    numero, clima = 0, 0
    for fila, (y, rot) in enumerate(((1500, 0), (3900, 180))):
        x = 1500
        for hueco in huecos:
            if hueco == 'C':
                clima += 1
                b.feature(hpc, 'crac', 'IR-%02d' % clima, x, y, 300, 1200, rot=rot,
                          height_mm=2000)
                x += 300
                continue
            numero += 1
            name = 'H%02d' % numero
            rack = b.new('racks', {'room_uid': hpc, 'name': name, 'u_height': 42,
                                   'width_mm': 600, 'depth_mm': 1200, 'pos_x': x, 'pos_y': y,
                                   'rotation': rot, 'row_uid': filas[fila], 'access': 'front,rear',
                                   'description': w['rack_hpc_desc']})
            pd = b.pdus(rack, name, (src['a'], src['b']), capacity=22000)
            b.item(rack, w['patch'] % name, 'patch_panel', 42, face='front', model='patch')
            sw = b.item(rack, 'SW-%s' % name, 'switch', 41, model='tor')
            b.dual(sw, 'switch', pd)
            b.item(rack, w['cable_manager'], 'blank', 40, face='front')
            for n, core in enumerate(cores):
                b.cable(sw, 'Te1/1/%d' % (n + 1), core, 'Te1/0/%d' % (16 + numero), kind='fiber',
                        category='om4', color='cyan', length=20000)
            for k in range(8):
                gpu = b.item(rack, 'gpu-%s-%02d' % (name.lower(), k + 1), 'server', 1 + 2 * k, 2,
                             depth_mm=800, model='gpu')
                b.dual(gpu, 'server', pd, watts=1400)
                b.cable(gpu, 'eth0', sw, 'Gi1/0/%d' % (k + 1), color='blue', length=1500)
            x += 600
    b.feature(hpc, 'aisle', w['hpc_aisle'], 1500, 2700, 4800, 1200)
    for xd in (940, 5860):
        b.feature(hpc, 'door', w['hpc_door'], xd, 3240, rot=90)
    b.feature(hpc, 'tray', w['cpd_tray_a'], 1500, 1500, 4800, 300)
    b.feature(hpc, 'tray', w['cpd_tray_b'], 1500, 4800, 4800, 300)
    b.feature(hpc, 'zone', w['hpc_reserve'], 7200, 1500, 4300, 3600)
    b.feature(hpc, 'column', w['column'], 6600, 6300)
    b.feature(hpc, 'panel', w['cpd_panel'], 300, 6800)
    b.feature(hpc, 'extinguisher', w['extinguisher_co2'], 11300, 7300)
    b.door(hpc, *floor['size']['hpc'][:2], fire=True)

    _idf(b, site, floor, 'idf3', 'P3', src['p3'], 20, cores, 37, net)
    _meeting(b, floor, 'meet3', 8, (1100, 1500, 3200, 1200))
    open3 = floor['rooms']['open3']
    b.s.rooms.update(open3, {'cooling': 'split', 'description': w['room_office_desc']},
                     actor=b.actor)
    # The door is on top (the corridor): the islands start 1.8 m below it.
    _desks(b, open3, [(300, 1800), (4700, 1800), (9100, 1800), (300, 5200), (4700, 5200)], 3,
           width=1400)
    b.feature(open3, 'zone', w['printer'], 10000, 5600, 1200, 1000)
    b.door(open3, *floor['size']['open3'][:2], top=True)
    _private_office(b, floor, 'off_cto', 'round')
    _kitchen(b, floor)


# ── States: some items in warning and in error ───────────────────────────────────────────────

#: The rooms whose active items get a demo state; the lab, the dispatch rack and the recovery
#: site stay without one, so «sin vigilar» shows too.
_WATCHED_ROOMS = ('room_cpd', 'room_hpc', 'room_srv', 'room_idf2', 'room_idf3', 'room_com')
#: Which items are in trouble, by label: a little of everything, spread over rooms and rows so
#: the room, the floor, the building and the overview each have something to show.
_TROUBLE = {
    'srv-a01-03': 'error', 'gpu-h05-02': 'error', 'SW-B04': 'error', 'srv-s02-04': 'error',
    'srv-a02-01': 'warning', 'srv-b06-05': 'warning', 'gpu-h09-07': 'warning',
    'gpu-h02-08': 'warning', 'SW-P2-2': 'warning', 'FW-S01': 'warning', 'CORE-2': 'warning',
    'NVR-01': 'warning',
}
#: And why: what the check that put it there would have said. Clicking an item in trouble
#: shows it, as a real device shows its failing checks.
_WHY = {
    'srv-a01-03': 'why_ping', 'gpu-h05-02': 'why_gpu_xid', 'SW-B04': 'why_psu_both',
    'srv-s02-04': 'why_raid_failed', 'srv-a02-01': 'why_disk_smart', 'srv-b06-05': 'why_psu_one',
    'gpu-h09-07': 'why_gpu_temp', 'gpu-h02-08': 'why_ecc', 'SW-P2-2': 'why_port_errors',
    'FW-S01': 'why_ha_sync', 'CORE-2': 'why_uplink_down', 'NVR-01': 'why_nvr_disk',
}
#: What does not answer by nature: no state, it is not watched for a reason.
_MUTE = ('patch_panel', 'fiber_panel', 'shelf', 'blank', 'pdu', 'ups')


def _states(b: _Builder, site: str) -> None:
    """A demo state for the active items of the watched rooms: most of them ok, a few in warning
    and in error (`_TROUBLE`). Written to `dc_item.demo_state`, which only the demo writes and
    only counts for an item with no device: no device, no check, nothing for the monitor to
    probe and no alert for a machine that does not exist. Each such item says so in its
    description."""
    w = b.w
    salas = {w[k] for k in _WATCHED_ROOMS}
    for room in b.s.rooms_of(site):
        if room['name'] not in salas:
            continue
        for rack in b.s.racks_of(room['uid']):
            for it in b.s.items_of(rack['uid']):
                if str(it.get('role') or '') in _MUTE:
                    continue
                nombre = str(it.get('label') or '')
                estado = _TROUBLE.get(nombre, 'ok')
                b.s.items.update(it['uid'], {'demo_state': estado,
                                             'demo_reason': w[_WHY[nombre]] if nombre in _WHY else '',
                                             'description': w['demo_state_desc'] % w['state_' + estado]},
                                 actor=b.actor)


#: The room items in trouble, and why: what their device would say.
_ROOM_TROUBLE = {'IMP-P2': ('warning', 'why_toner'), 'AP-P2-OPEN2': ('warning', 'why_ap_clients'),
                 'CAM-P0-2': ('error', 'why_cam_signal')}


def _room_states(b: _Builder, site: str) -> None:
    """A demo state for what is in the rooms —the PCs, the phones, the APs—: ok, but for a
    printer low on toner, an access point with clients on a weak signal and a camera with no
    picture. The outlets and the power sockets have none: a wall socket does not answer."""
    w = b.w
    for room in b.s.rooms_of(site):
        for it in b.s.items_in_room(room['uid']):
            if it['role'] in ('outlet', 'power_outlet'):
                continue
            estado, por = _ROOM_TROUBLE.get(str(it.get('label') or ''), ('ok', ''))
            b.s.items.update(it['uid'], {'demo_state': estado, 'demo_reason': w[por] if por else '',
                                         'description': w['demo_state_desc'] % w['state_' + estado]},
                             actor=b.actor)


def _place_sources(b: _Builder, site: str) -> None:
    """Each source of the power chain IS a piece of the plan: the mains, the panels and the
    room UPSs in the energy room, the generator's zone, each floor's panel in its corridor. Linked
    (`dc_source.feature_uid`), the 3D draws the source at its piece instead of in a row beside the
    building. By name, as the chain and the pieces are written with the same words; a floor's
    panel is «Floor panel P2» on the plan and «Floor 2 panel» in the chain."""
    from lib.core.dcim.store import SOURCE_PIECE_KINDS        # noqa: PLC0415
    w = b.w
    piezas = {}
    for room in b.s.rooms_of(site):
        for f in b.s.features_of(room['uid']):
            if f['kind'] in SOURCE_PIECE_KINDS and f.get('label'):
                piezas.setdefault(f['label'], f['uid'])
    alias = {w['src_p2']: w['floor_panel_n'] % _IQ_TAG['floor_second'],
             w['src_p3']: w['floor_panel_n'] % _IQ_TAG['floor_third']}
    for s in b.s.sources_of(site):
        if s.get('item_uid'):
            continue                                   # a UPS in a rack is drawn in its rack
        pieza = piezas.get(alias.get(s['name'], s['name']))
        if pieza:
            b.s.sources.update(s['uid'], {'feature_uid': pieza}, actor=b.actor)


# ── Access control: a gateway per floor, cylinders, lockers, turnstiles ──────────────────────

#: Where each floor's gateway hangs: the room, and a free spot on its wall.
_IQ = {'floor_basement': ('ene', 11500, 6500), 'floor_ground': ('com', 300, 2500),
       'floor_first': ('noc', 6000, 3000), 'floor_second': ('idf2', 2600, 1800),
       'floor_third': ('idf3', 2600, 1800)}
_IQ_TAG = {'floor_basement': 'S', 'floor_ground': 'P0', 'floor_first': 'P1',
           'floor_second': 'P2', 'floor_third': 'P3'}
#: The rooms whose door has an electronic cylinder: the technical ones and the private offices.
_LOCKED = ('cpd', 'hpc', 'srv', 'idf2', 'idf3', 'com', 'noc', 'alm', 'ene', 'bat', 'gen',
           'pci', 'off_dir', 'off_fin', 'off_rrhh', 'off_it', 'off_cto', 'off_ops')
#: The cabinets with a locker lock.
_LOCKERS = ('recep_lockers', 'floor_cabinet')
#: What is in trouble, and why: the battery of a cylinder, a turnstile that lost its gateway,
#: a locker that reports tampering.
_ACCESS_TROUBLE = {('door', 'hpc'): ('warning', 'reason_battery'),
                   ('turnstile', 2): ('error', 'reason_offline'),
                   ('cabinet', 'recep'): ('warning', 'reason_tamper')}


def _access(b: _Builder, floors: dict) -> None:
    """Salto-style access control on the demo building. A gateway (IQ) per floor on a wall, the
    doors of the technical rooms and the private offices with an electronic cylinder (Neo), the
    reception lockers and the floor cabinets with a locker lock (XS4 Locker), and two turnstiles
    at the entrance with their reader — each one connected to its floor's gateway, and with a
    demo state: most ok, a few in trouble, saying why."""
    w = b.w
    serie = [0]

    def numero(prefix):
        serie[0] += 1
        return '%s-%06d' % (prefix, 410000 + serie[0])

    def estado(kind, where, extra):
        st, razon = _ACCESS_TROUBLE.get((kind, where), ('ok', ''))
        nombre = w['state_' + st] + (', ' + w[razon] if razon else '')
        return dict(extra, demo_state=st, demo_reason=w[razon] if razon else '',
                    description=w['demo_state_desc'] % nombre)

    for fkey, floor in floors.items():
        sala, x, y = _IQ[fkey]
        tag = _IQ_TAG[fkey]
        iq = b.feature(floor['rooms'][sala], 'reader', w['iq'] % tag, x, y,
                       lock='', model='Salto IQ 2.0', serial=numero('IQ'),
                       type_uid=b.models['access_iq'])
        b.s.features.update(iq, estado('reader', tag, {}), actor=b.actor)
        for key, room in floor['rooms'].items():
            for f in b.s.features_of(room):
                # La puerta de la sala, no las del confinamiento de un pasillo.
                if f['kind'] == 'door' and key in _LOCKED and f['label'] in ('', w['door_fire']):
                    b.s.features.update(f['uid'], estado('door', key, {
                        'lock': 'cylinder', 'model': 'Salto Neo Cylinder',
                        'type_uid': b.models['access_neo'],
                        'serial': numero('NEO'), 'hub_uid': iq}), actor=b.actor)
                elif f['kind'] == 'cabinet' and f['label'] in [w[k] for k in _LOCKERS]:
                    b.s.features.update(f['uid'], estado('cabinet', key, {
                        'lock': 'locker', 'model': 'Salto XS4 Locker',
                        'type_uid': b.models['access_locker'],
                        'serial': numero('XS4'), 'hub_uid': iq}), actor=b.actor)
        if fkey == 'floor_ground':
            area = b.s.floors.get(floor['uid'])['area_uid']
            for n, x in ((1, 13900), (2, 15100)):
                t_uid = b.feature(area, 'turnstile', w['turnstile_n'] % n, x, 15800, rot=180)
                b.s.features.update(t_uid, estado('turnstile', n, {
                    'lock': 'reader', 'model': w['turnstile_model'],
                    'type_uid': b.models['access_turnstile'],
                    'serial': numero('TT'), 'hub_uid': iq}), actor=b.actor)


# ── Safety and what hangs on a wall: the whole building on the map ──────────────────────────

def _on_wall(W, D, side, along, w, d, x0=0.0, y0=0.0):
    """Where a piece of ``w × d`` goes so that it hangs on a wall of the box ``(x0, y0)–(W, D)``
    with its front —the ``pos_y`` side, as on a rack— facing into the room: ``(pos_x, pos_y,
    rotation)``. ``along`` is where along that wall, from its start. The turn is about the piece's
    centre, so a piece on a side wall does not start where its corner would."""
    if side == 'top':
        return x0 + along, y0, 180
    if side == 'bottom':
        return x0 + along, D - d, 0
    cx = x0 + d / 2 if side == 'left' else W - d / 2
    cy = y0 + along + w / 2
    return cx - w / 2, cy - d / 2, 90 if side == 'left' else 270


#: What hangs on a wall, and is moved onto the nearest one if it was put loose in the room.
_WALL_KINDS = ('reader', 'extinguisher', 'panel', 'hose_reel', 'fire_alarm', 'emergency_light',
               'first_aid', 'aed')


#: A room's edge is the centre line of its wall: what hangs inside goes on the wall's inner
#: face, half a partition in.
_FACE = _INNER / 2


def _snap(b: _Builder, f: dict, W: float, D: float) -> None:
    """Put a piece on the wall nearest to it, on the wall's inner face and facing into the room.
    Its height stays if it said one (a wall split at 2.2 m); if not, its kind's."""
    from lib.core.dcim.store.features import FEATURE_KINDS     # noqa: PLC0415
    w, d = float(f['width_mm']), float(f['depth_mm'])
    cx, cy = float(f['pos_x']) + w / 2, float(f['pos_y']) + d / 2
    lados = {'top': cy, 'bottom': D - cy, 'left': cx, 'right': W - cx}
    side = min(lados, key=lados.get)
    largo = (W if side in ('top', 'bottom') else D) - 2 * _FACE
    centro = cx if side in ('top', 'bottom') else cy
    along = min(max(0.0, centro - _FACE - w / 2), largo - w)
    x, y, rot = _on_wall(W - _FACE, D - _FACE, side, along, w, d, _FACE, _FACE)
    altura = f.get('base_mm')
    if altura in (None, ''):
        altura = FEATURE_KINDS[f['kind']].get('base', 0)
    b.s.features.update(f['uid'], {'pos_x': x, 'pos_y': y, 'rotation': rot,
                                   'base_mm': altura}, actor=b.actor)


def _safety(b: _Builder, floors: dict) -> None:
    """The building's safety and everything that hangs on a wall, on the map. In every room:
    what was put loose on a wall goes onto the nearest one; smoke detectors on the ceiling, one
    every 6 m; an emergency light over the door and an extinguisher beside it. In every
    corridor, on the walls that give onto it: an emergency light over each door, and taking turns
    an extinguisher with a fire alarm call point, or a fire hose reel (BIE). Each floor's panel on
    the façade, and a first aid kit and a defibrillator at the reception."""
    from lib.core.dcim.store.features import FEATURE_KINDS     # noqa: PLC0415
    w = b.w
    base = {k: v.get('base', 0) for k, v in FEATURE_KINDS.items()}

    def pieza(room, kind, label, W, D, side, along, x0=_FACE, y0=_FACE, **extra):
        spec = FEATURE_KINDS[kind]
        x, y, rot = _on_wall(W - x0, D - y0, side, along - x0, spec['w'], spec['d'], x0, y0)
        return b.feature(room, kind, label, x, y, rot=rot, base_mm=base[kind], **extra)

    for fkey, floor in floors.items():
        geometria = {rk: (x, y, ww, dd) for k, _lvl, rooms, _wi, _en in _FLOORS if k == fkey
                     for rk, x, y, ww, dd in rooms}
        # Inside each room.
        for rk, room in floor['rooms'].items():
            W, D, arriba = floor['size'][rk]
            piezas = b.s.features_of(room)
            for f in piezas:
                # Y los splits de pared —un climatizador colgado, con altura—, que también
                # quedaban sueltos en mitad de la sala.
                if f['kind'] in _WALL_KINDS or (f['kind'] == 'crac' and f.get('base_mm')):
                    _snap(b, f, W, D)
            lado = 'top' if arriba else 'bottom'
            # Sin rótulo: va justo encima de la puerta, y el suyo tapaba el de la puerta. Lo
            # que es lo dice su tipo, en su icono y en el inspector.
            pieza(room, 'emergency_light', '', W, D, lado, W / 2 - 175)
            # (Ni en los aseos: les sirve el del pasillo, a menos de 15 m — DB-SI 4.)
            if rk != 'wc' and not any(f['kind'] == 'extinguisher' for f in piezas):
                pieza(room, 'extinguisher', w['extinguisher_co2'], W, D, lado, W / 2 + 700)
            nx, ny = max(1, -(-int(W) // 6000)), max(1, -(-int(D) // 6000))
            for i in range(nx):
                for j in range(ny):
                    b.feature(room, 'smoke_detector', '',
                              W * (i + 0.5) / nx - 60, D * (j + 0.5) / ny - 60,
                              base_mm=base['smoke_detector'])
        # The corridors: the floor's general area, on the walls of the rooms that give onto them.
        area = b.s.floors.get(floor['uid']).get('area_uid') or _area(b, floor)
        grueso = _INNER / 2
        for i, (rk, (x, y, ww, dd)) in enumerate(sorted(geometria.items(), key=lambda kv: kv[1][:2])):
            arriba = floor['size'][rk][2]
            # The corridor is above the room's top wall, or below its bottom one; the piece's
            # back goes against the wall's corridor face.
            if arriba:
                lado, yy = 'bottom', y - grueso                  # above the wall, front up
                caja = (0.0, 0.0, _W, yy)
            else:
                lado, yy = 'top', y + dd + grueso                # below the wall, front down
                caja = (0.0, yy, _W, _D)

            def junto(kind, label, at, **extra):
                spec = FEATURE_KINDS[kind]
                px, py, rot = _on_wall(caja[2], caja[3], lado, at, spec['w'], spec['d'],
                                       caja[0], caja[1])
                return b.feature(area, kind, label, px, py, rot=rot, base_mm=base[kind], **extra)

            junto('emergency_light', '', x + ww / 2 - 175)
            # A un lado de la puerta y nunca en su hueco (la mitad de la sala ± 500 mm).
            if ww < 3500:
                # Delante de una sala estrecha —un despacho de 2,8 m— solo cabe una pieza junto a
                # su puerta: un extintor o un pulsador, por turnos.
                if i % 2 == 0:
                    junto('extinguisher', w['extinguisher_n'] % _IQ_TAG[fkey], x + 150)
                else:
                    junto('fire_alarm', w['pushbutton'], x + 300)
            elif i % 2 == 0:
                junto('extinguisher', w['extinguisher_n'] % _IQ_TAG[fkey], x + 400)
                junto('fire_alarm', w['pushbutton'], x + 800)
            else:
                junto('hose_reel', w['bie'], x + ww / 2 + 600)
                junto('fire_alarm', w['pushbutton'], x + 400)
        # The floor's panel, on the façade, where the corridor reaches it.
        if fkey != 'floor_ground':
            pieza(area, 'panel', w['floor_panel_n'] % _IQ_TAG[fkey], _W, _D,
                  'right', 12500, _OUTER, _OUTER)
        if fkey == 'floor_ground':
            recep = floor['rooms']['recep']
            W, D, _a = floor['size']['recep']
            pieza(recep, 'first_aid', '', W, D, 'left', 1200)       # «Botiquín»: su tipo
            pieza(recep, 'aed', w['aed'], W, D, 'left', 2000)


# ── The small sites and the WAN links ──────────────────────────────────────────────────────

def _branch(b: _Builder, site: str, tag: str, ups_name: str,
            trouble: dict | None = None) -> dict:
    """A small site: the mains and a UPS, one technical room with one rack —a router, a
    firewall, a switch and two servers—, cabled and fed from both sides of the UPS. Each active
    item gets a demo state: ok, but for those *trouble* names (``{label: (state, why_key)}``).
    Hands back ``{'rtr', 'fw', 'sw'}``, where the WAN links end."""
    w = b.w
    mains = b.new('sources', {'site_uid': site, 'name': w['src_dr_mains'], 'kind': 'mains'})
    ups = b.new('sources', {'site_uid': site, 'name': ups_name, 'kind': 'ups',
                            'upstream_uid': mains, 'capacity_w': 10000, 'autonomy_min': 20})
    room = b.new('rooms', {'site_uid': site, 'name': w['room_dr'], 'width_mm': 5000,
                           'depth_mm': 4000, 'cooling': 'split'})
    # Its door: a technical room is a special-risk one, so a fire door, as in the main CPD.
    # Without one the room was a closed box, in the plan and in the 3D walk.
    b.door(room, 5000, 4000, fire=True)
    rack = b.new('racks', {'room_uid': room, 'name': 'R-01', 'u_height': 42, 'width_mm': 600,
                           'depth_mm': 1000, 'pos_x': 1000, 'pos_y': 800, 'rotation': 180})
    # Small sites: 1U strips bolted at the rear, under the network gear and over the servers. The
    # recovery centre mixes the two kinds: a 1U strip and a vertical one in the right channel.
    pdus = b.pdus(rack, 'R-01', (ups, ups),
                  where=(({'u': 5, 'face': 'rear'}, {'side_pos': 'rear-right'}) if tag == 'DR'
                         else ({'u': 5, 'face': 'rear'}, {'u': 6, 'face': 'rear'})))
    # With their depth, as the rest of the demo: without one the 3D drew them nearly as deep as
    # the rack and the cables behind them had nowhere to be seen.
    rtr = b.item(rack, 'RTR-' + tag, 'router', 40, model='router', depth_mm=450)
    fw = b.item(rack, 'FW-' + tag, 'firewall', 38, model='firewall', depth_mm=450)
    sw = b.item(rack, 'SW-' + tag, 'switch', 36, model='tor', depth_mm=450)
    activos = [(rtr, 'router'), (fw, 'firewall'), (sw, 'switch')]
    for it, role in activos:
        b.dual(it, role, pdus)
    b.cable(rtr, 'Gi0/1', fw, 'port1', color='red', length=1000)
    b.cable(fw, 'port2', sw, 'Gi1/0/1', color='red', length=1000)
    for k in range(2):
        srv = b.item(rack, 'srv-%s-%02d' % (tag.lower(), k + 1), 'server', 1 + 2 * k, 2,
                     model='server', depth_mm=750)
        b.dual(srv, 'server', pdus)
        b.cable(srv, 'eth0', sw, 'Gi1/0/%d' % (k + 2), length=2000)
        activos.append((srv, 'server'))
    for it, _role in activos:
        label = str((b.s.items.get(it) or {}).get('label') or '')
        estado, por = (trouble or {}).get(label, ('ok', ''))
        b.s.items.update(it, {'demo_state': estado, 'demo_reason': w[por] if por else '',
                              'description': w['demo_state_desc'] % w['state_' + estado]},
                         actor=b.actor)
    return {'rtr': rtr, 'fw': fw, 'sw': sw}


def _dr(b: _Builder, demo: str, site: str, net: dict) -> None:
    """The recovery centre, joined to Demo by TWO links for HA: the MPLS between the routers,
    up, and the IPsec tunnel between the firewalls, down —FW-DR in error says why—, so the map
    shows a link in error beside one that is fine."""
    w = b.w
    dr = _branch(b, site, 'DR', w['src_dr_ups'],
                 trouble={'FW-DR': ('error', 'why_ipsec_down')})
    b.new('links', {'a_site': demo, 'b_site': site, 'a_item': net['rtr'], 'b_item': dr['rtr'],
                    'kind': 'mpls', 'provider': w['link_mpls_provider'],
                    'circuit_id': 'MPLS-DEMO-0001', 'bandwidth_mbps': 1000,
                    'label': w['link_mpls']})
    b.new('links', {'a_site': demo, 'b_site': site, 'a_item': net['fws'][-1],
                    'b_item': dr['fw'], 'kind': 'ipsec', 'provider': 'Internet',
                    'bandwidth_mbps': 300, 'path': 'internet', 'label': w['link_ipsec'],
                    'description': w['link_ipsec_desc']})


def _far(b: _Builder, demo: str, texas: str, south_africa: str, taiwan: str,
         net: dict) -> None:
    """South Africa and Taiwan, the two ends of the map.

    South Africa is **entirely offline**: every active item in error with the same reason, and
    its only link —one MPLS to Madrid— down with them, so the map shows a whole site lost and
    the board warns that it hung from a single link. Taiwan is fine and has two paths: an
    international MPLS to Madrid and an SD-WAN to Texas."""
    w = b.w
    caido = ('error', 'why_site_offline')
    za = _branch(b, south_africa, 'ZA', w['src_za_ups'],
                 trouble={k: caido for k in ('RTR-ZA', 'FW-ZA', 'SW-ZA',
                                             'srv-za-01', 'srv-za-02')})
    tw = _branch(b, taiwan, 'TW', w['src_tw_ups'])
    b.new('links', {'a_site': demo, 'b_site': south_africa, 'a_item': net['rtrs'][0],
                    'b_item': za['rtr'], 'kind': 'mpls', 'provider': w['link_intl_provider'],
                    'circuit_id': 'MPLS-DEMO-0003', 'bandwidth_mbps': 200,
                    'label': w['link_za'], 'description': w['link_za_desc']})
    b.new('links', {'a_site': demo, 'b_site': taiwan, 'a_item': net['rtrs'][0],
                    'b_item': tw['rtr'], 'kind': 'mpls', 'provider': w['link_intl_provider'],
                    'circuit_id': 'MPLS-DEMO-0004', 'bandwidth_mbps': 500,
                    'label': w['link_tw'], 'description': w['link_tw_desc']})
    b.new('links', {'a_site': texas, 'b_site': taiwan,
                    'a_item': _site_router(b, texas), 'b_item': tw['rtr'], 'kind': 'sdwan',
                    'provider': 'Internet', 'bandwidth_mbps': 200, 'path': 'internet',
                    'label': w['link_tx_tw'], 'description': w['link_tx_tw_desc']})


def _site_router(b: _Builder, site: str) -> str:
    """The router of a small site (`_branch`), found by its label: the WAN links end there."""
    for room in b.s.rooms_of(site):
        for rack in b.s.racks_of(room['uid']):
            for it in b.s.items_of(rack['uid']):
                if str(it.get('label') or '').startswith('RTR-'):
                    return it['uid']
    return ''


def _americas(b: _Builder, demo: str, texas: str, puerto_rico: str, net: dict) -> None:
    """Texas and Puerto Rico, so the map holds a small WAN across the ocean: Demo - Texas by
    international MPLS between routers (up), Texas - Puerto Rico by SD-WAN (in warning: RTR-PR
    reports the latency)."""
    w = b.w
    tx = _branch(b, texas, 'TX', w['src_tx_ups'])
    pr = _branch(b, puerto_rico, 'PR', w['src_pr_ups'],
                 trouble={'RTR-PR': ('warning', 'why_sdwan_latency')})
    b.new('links', {'a_site': demo, 'b_site': texas, 'a_item': net['rtrs'][-1],
                    'b_item': tx['rtr'], 'kind': 'mpls', 'provider': w['link_intl_provider'],
                    'circuit_id': 'MPLS-DEMO-0002', 'bandwidth_mbps': 500,
                    'label': w['link_tx'], 'description': w['link_tx_desc']})
    b.new('links', {'a_site': texas, 'b_site': puerto_rico, 'a_item': tx['rtr'],
                    'b_item': pr['rtr'], 'kind': 'sdwan', 'provider': 'Internet',
                    'bandwidth_mbps': 200, 'path': 'internet', 'label': w['link_tx_pr'],
                    'description': w['link_tx_pr_desc']})
