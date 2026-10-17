#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The two network maps of Infrastructure, laid out so that they still read at a thousand
machines — run in `node` against the panel's own script.

They were drawn as one long picture of the whole fleet: the address map came out as a single
horizontal line with a fan of curves, the cable map as a strip one box wide and three hundred
tall. With the demo's 356 devices neither showed anything. Now (`infra/_netgraph.html`) both are
drawn as SITES — frames with their machines in bands, foldable into one box with the worst state
on it, the lines to a folded site added up into one with the number on it — and the sites are
placed in two dimensions.

What is pinned here, each on the real functions and none on their source text:

* grouping by the inventory's site, with the device's own location as the fallback;
* folding: what a folded site stands for, the lines added up, what is inside counted;
* the layout: nothing on top of anything, the same picture twice, every machine accounted for;
* the list's filters narrow the picture;
* the states: a dead cable is drawn as one, a folded site wears its worst machine;
* and a thousand machines with fifteen hundred cables laid out and drawn inside a time budget.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

from tests.conftest import _login
from tests.helpers import node_run, panel_bundle

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = [
    pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed'),
    pytest.mark.skipif(shutil.which(os.environ.get('SS_NODE') or 'node') is None,
                       reason='no node: nothing to run the script with'),
]

#: The panel's script, built once per worker: it is the same for every probe here.
_BUNDLE: dict = {}


@pytest.fixture()
def run(client):
    if 'js' not in _BUNDLE:
        _login(client)
        _BUNDLE['js'] = panel_bundle(client)

    def _run(probe):
        return node_run(_BUNDLE['js'], FLEET_JS + probe)
    return _run


#: A synthetic fleet: *sites* sites, each with a router, a firewall, two core switches, access
#: switches cabled to both cores, and servers and cameras under each access switch — half the
#: servers cabled to two switches. Every machine has an address on its access network and points
#: at that network's `.1`, which nobody registered, so the address map has its routers to draw.
FLEET_JS = r"""
const T = s => Object.keys(DEVICE_TYPE_SLUGS).find(u => DEVICE_TYPE_SLUGS[u] === s) || '';
function fleet(sites, perSite, opts) {
  const o = opts || {};
  const nodes = [], edges = [], siteRows = [], nets = new Map();
  let k = 0;
  const add = (s, slug, net, status) => {
    const uid = 'u' + String(k).padStart(4, '0'); k++;
    const cidr = `10.${s}.${net}.0/24`;
    const addr = `10.${s}.${net}.${(k % 250) + 2}`;
    const n = {uid, name: `${slug}-${s}-${k}`, kind: T(slug),
               status: status || (k % 97 === 0 ? 'error' : k % 41 === 0 ? 'warning' : 'ok'),
               addresses: [addr + '/24'], networks: [cidr], gateway: `10.${s}.${net}.1`,
               wan: '', site: o.noSites ? '' : 's' + s, location: ''};
    nodes.push(n);
    if (!nets.has(cidr)) nets.set(cidr, {net: cidr, members: [], claims: {}});
    nets.get(cidr).members.push(uid);
    nets.get(cidr).claims[uid] = addr;
    edges.push({from: uid, to: '', kind: 'exit', address: `10.${s}.${net}.1`, said: false});
    return uid;
  };
  const cable = (a, b, state) => edges.push({from: a, to: b, kind: state === 'down' ? 'down' : 'lldp',
      confirmed: true, by: [a, b], ports: {[a]: ['p'], [b]: ['p']}, bundle: 1, state: state || ''});
  for (let s = 0; s < sites; s++) {
    siteRows.push({uid: 's' + s, name: 'Site ' + String(s).padStart(2, '0')});
    const r = add(s, 'router', 0), f = add(s, 'firewall', 0);
    const c1 = add(s, 'switch', 0), c2 = add(s, 'switch', 0);
    cable(r, c1); cable(f, c2); cable(c1, c2);
    let left = perSite - 4, acc = [];
    while (left > 0) {
      const a = add(s, 'switch', 1 + (acc.length % 3)); left--;
      cable(a, c1); cable(a, c2); acc.push(a);
      for (let j = 0; j < 9 && left > 0; j++, left--) {
        const m = add(s, j % 3 ? 'server' : 'camera', 1 + (acc.length % 3));
        cable(m, a, (o.downAt === `${s}/${acc.length}/${j}`) ? 'down' : '');
        if (j % 2 && acc.length > 1) cable(m, acc[acc.length - 2]);
      }
    }
    if (s > 0) edges.push({from: nodes[0].uid, to: r, kind: 'site', via: 'mpls',
                           state: s === 1 ? 'error' : 'ok'});
  }
  return {nodes, edges, sites: siteRows, networks: [...nets.values()], unplaced: []};
}
function use(map) { _infraMap = map; _infraMapStamp++; _infraLinkUse(null); _infraMapUse(null); }
function overlaps(boxes) {
  const b = boxes.slice().sort((p, q) => p.x - q.x);
  let n = 0;
  for (let i = 0; i < b.length; i++)
    for (let j = i + 1; j < b.length && b[j].x < b[i].x + b[i].w; j++)
      if (b[i].y < b[j].y + b[j].h && b[j].y < b[i].y + b[i].h) n++;
  return n;
}
"""


class TestASiteIsWhereAMachineIs:

    def test_grouped_by_inventory_site_then_by_what_it_says_then_none(self, run):
        out = run(r"""
            const sites = new Map([['s1', 'Madrid'], ['s2', 'Bilbao']]);
            const nodes = [
              {uid: 'a', site: 's1', status: 'ok'}, {uid: 'b', site: 's1', status: 'error'},
              {uid: 'c', site: 's2', status: 'ok'},
              {uid: 'd', site: 'gone', location: 'Sevilla › CPD › R-1', status: 'warning'},
              {uid: 'e', location: 'sevilla, planta 2', status: 'ok'},
              {uid: 'f', status: ''}, {uid: 'f2'}, {uid: 'f3'}, {uid: 'f4'},
              {uid: 'g', site: 's2', status: 'ok'},
              {uid: 'h', site: 's2', status: 'ok'}];
            const G = ssNetGroups(nodes, n => ssNetGroupOf(n, sites));
            __out = {keys: G.list.map(g => g.key), names: G.list.map(g => g.name),
                     kinds: G.list.map(g => g.kind), worst: G.list.map(g => g.worst),
                     d: G.of.get('d'), e: G.of.get('e'), f: G.of.get('f')};
        """)
        # Biggest first, then by name; "no site" last whatever its size.
        assert out['keys'] == ['s:s2', 's:s1', 'l:sevilla', '-']
        assert out['names'][:3] == ['Bilbao', 'Madrid', 'Sevilla']
        assert out['kinds'] == ['site', 'site', 'loc', 'none']
        assert out['worst'] == ['ok', 'error', 'warning', '']
        # A site the inventory does not know is not one; the location then decides.
        assert out['d'] == out['e'] == 'l:sevilla' and out['f'] == '-'


class TestFoldingASiteAddsItsLinesUp:

    def test_the_lines_to_a_folded_site_are_one_with_the_number_and_the_worst_state(self, run):
        out = run(r"""
            const groupOf = id => ({a1: 'A', a2: 'A', a3: 'A', b1: 'B', b2: 'B', c1: 'C'})[id] || '';
            const edges = [
              {a: 'a1', b: 'b1', kind: 'lldp', state: ''},
              {a: 'a2', b: 'b1', kind: 'lldp', state: 'down'},
              {a: 'a3', b: 'b2', kind: 'site', state: 'warning'},
              {a: 'a1', b: 'a2', kind: 'lldp', state: ''},
              {a: 'a2', b: 'a3', kind: 'lldp', state: 'down'},
              {a: 'b1', b: 'c1', kind: 'lldp', state: ''},
              {a: 'b1', b: 'b2', kind: 'lldp', state: ''},
              {a: 'a1', b: 'gone', kind: 'lldp', state: ''}];
            const F = ssNetFold(['a1', 'a2', 'a3', 'b1', 'b2', 'c1'], edges, groupOf,
                                new Set(['A']), {keep: true, aggKind: () => 'cable'});
            __out = {items: F.items.map(i => [i.id, i.group, i.folded]),
                     links: F.links.map(l => [l.a, l.b, l.count, l.state, !!l.agg, l.edges]),
                     inside: [...F.inside], insideState: [...F.insideState]};
        """)
        assert out['items'] == [['grp:A', 'A', True], ['b1', 'B', False], ['b2', 'B', False],
                                ['c1', 'C', False]]
        links = {(a, b): rest for a, b, *rest in out['links']}
        # Three cables from the folded site, to two machines: one line each, added up, worst.
        assert links[('grp:A', 'b1')] == [2, 'down', True, [0, 1]]
        assert links[('grp:A', 'b2')] == [1, 'warning', True, [2]]
        # Between two open machines, every cable stays its own line.
        assert links[('b1', 'c1')] == [1, '', False, [5]] and ('b1', 'b2') in links
        # Inside the folded site: counted, with the worst of them — and an end that is not on
        # the picture (filtered out) draws nothing at all.
        assert out['inside'] == [['grp:A', 2]] and out['insideState'] == [['grp:A', 'down']]
        assert len(out['links']) == 4

    def test_a_part_folded_into_a_machine_is_accounted_for(self, run):
        """Servers folded into the switch they hang from: drawn as the switch, listed as what
        it took in, and their cables to it inside it — with the worst of those."""
        out = run(r"""
            const edges = [{a: 's1', b: 'sw', kind: 'lldp', state: ''},
                           {a: 's2', b: 'sw', kind: 'down', state: 'down'},
                           {a: 'sw', b: 'core', kind: 'lldp', state: ''}];
            const F = ssNetFold(['core', 'sw', 's1', 's2'], edges, () => 'G', new Set(),
                                {keep: true, alias: id => (id[0] === 's' && id !== 'sw') ? 'sw' : id});
            __out = {items: F.items.map(i => i.id), absorbed: [...F.absorbed],
                     inside: [...F.inside], st: [...F.insideState], links: F.links.length};
        """)
        assert out['items'] == ['core', 'sw']
        assert out['absorbed'] == [['sw', ['s1', 's2']]]
        assert out['inside'] == [['sw', 2]] and out['st'] == [['sw', 'down']]
        assert out['links'] == 1

    def test_a_large_fleet_starts_folded_and_a_choice_wins(self, run):
        out = run(r"""
            const g = [{key: 'A'}, {key: 'B'}, {key: 'C'}];
            const f = (n, p) => [...ssNetFolded(g, n, p)].sort();
            __out = {small: f(_NG.AUTO, {}), big: f(_NG.AUTO + 1, {}),
                     one: f(5000, {k: {B: 1}}), all: f(5000, {all: 'open', k: {C: 0}}),
                     fold: f(3, {all: 'fold'}), single: [...ssNetFolded([{key: 'A'}], 9999, {})]};
        """)
        assert out['small'] == [] and out['big'] == ['A', 'B', 'C']
        assert out['one'] == ['A', 'C'] and out['all'] == ['C'] and out['fold'] == ['A', 'B', 'C']
        # One group has nothing to fold into: a frame round the whole picture says nothing.
        assert out['single'] == []

    def test_what_is_kept_on_the_account_is_validated_on_the_way_in(self, run):
        out = run(r"""
            ssNetFoldApply({map: {all: 'open', k: {'s:x': 0, 'bad': 7, '~net:a': 1}},
                            links: {all: 'sideways', k: 'nope'}, other: {all: 'open'}});
            const saved = ssNetFoldSaved();
            ssNetFoldApply(null);
            __out = {saved, after: ssNetFoldSaved()};
        """)
        assert out['saved'] == {'map': {'all': 'open', 'k': {'s:x': 0, '~net:a': 1}},
                                'links': {}}
        assert out['after'] == {'map': {}, 'links': {}}


class TestTheLayout:

    def test_nothing_on_top_of_anything_and_the_same_picture_twice(self, run):
        out = run(r"""
            const res = {};
            for (const mode of ['folded', 'open', 'full']) {
              const map = fleet(9, 60, {});
              const lay = () => {
                _ngFold = {map: {}, links: {}};
                if (mode !== 'folded') _ngFold.links = {all: 'open'};
                if (mode === 'full') _ngFold.links.k = {'~leaves': 1};
                use(map);
                const L = _infraLinkLayout(map);
                return {pos: L.pos, frames: L.frames};
              };
              const one = lay(), two = lay();
              const boxes = Object.values(one.pos);
              // The frames of different sites must not overlap either.
              res[mode] = {same: JSON.stringify(one) === JSON.stringify(two),
                           boxes: boxes.length, over: overlaps(boxes),
                           frameOver: overlaps(one.frames),
                           ints: boxes.every(b => Number.isInteger(b.x) && Number.isInteger(b.y)),
                           // Every open machine is inside its own site's frame.
                           inside: boxes.filter(b => !b.folded).every(b => {
                             const f = one.frames.find(x => x.key === b.group);
                             return f && b.x >= f.x && b.y >= f.y && b.x + b.w <= f.x + f.w
                                    && b.y + b.h <= f.y + f.h; })};
            }
            __out = res;
        """)
        for mode in ('folded', 'open', 'full'):
            r = out[mode]
            assert r['same'], mode
            assert r['over'] == 0 and r['frameOver'] == 0, (mode, r)
            assert r['ints'] and r['inside'], (mode, r)
        assert out['folded']['boxes'] == 9
        assert out['full']['boxes'] == 9 * 60

    def test_it_is_two_dimensional_and_not_a_strip(self, run):
        """The reported pictures were one row wide and one column tall."""
        out = run(r"""
            const map = fleet(1, 300, {noSites: true});
            _ngFold = {map: {}, links: {k: {'~leaves': 1}}};
            use(map);
            const L = _infraLinkLayout(map);
            const F = fleet(8, 6, {});
            _ngFold = {map: {}, links: {all: 'fold'}};
            use(F);
            const G = _infraLinkLayout(F);
            const xs = new Set(Object.values(G.pos).map(p => p.x)),
                  ys = new Set(Object.values(G.pos).map(p => p.y));
            __out = {w: L.width, h: L.height, cols: new Set(Object.values(L.pos).map(p => p.x)).size,
                     gx: xs.size, gy: ys.size, grouped: L.grouped};
        """)
        assert not out['grouped']
        assert 0.4 < out['w'] / out['h'] < 4, out
        assert out['cols'] >= 8, out
        # Eight folded sites are spread over both axes, not lined up.
        assert out['gx'] >= 3 and out['gy'] >= 2, out

    def test_every_machine_is_drawn_or_accounted_for(self, run):
        out = run(r"""
            const map = fleet(4, 50, {});
            const res = {};
            for (const [label, pref] of [['default', {}], ['leaves', {all: 'open'}]]) {
              _ngFold = {map: {}, links: pref};
              use(map);
              const L = _infraLinkLayout(map);
              const drawn = new Set(Object.values(L.pos).filter(p => !p.folded).map(p => p.uid));
              for (const ids of L.absorbed.values()) ids.forEach(u => drawn.add(u));
              for (const p of Object.values(L.pos)) if (p.folded)
                (L.groupBy.get(p.group).members || []).forEach(u => drawn.add(u));
              L.loose.forEach(n => drawn.add(n.uid));
              res[label] = {all: map.nodes.every(n => drawn.has(n.uid)), n: drawn.size,
                            absorbed: [...L.absorbed.values()].reduce((s, v) => s + v.length, 0)};
            }
            __out = res;
        """)
        assert out['default']['all'] and out['default']['n'] == 200
        assert out['leaves']['all'] and out['leaves']['absorbed'] > 0


class TestTheFiltersNarrowThePicture:

    def test_what_the_list_shows_is_what_is_drawn(self, run):
        out = run(r"""
            const map = fleet(3, 30, {});
            _ngFold = {map: {all: 'open', k: {'~net': 1}}, links: {all: 'open', k: {'~leaves': 1}}};
            use(map);
            const all = Object.keys(_infraLinkLayout(map).pos).length;
            const keep = map.nodes.filter(n => n.site === 's1').map(n => n.uid);
            _infraLinkUse(keep);
            const L = _infraLinkLayout(map);
            _infraMapUse(keep);
            const M = _infraMapLayout(map);
            const devs = [...M.at.values()].filter(p => p.node).map(p => p.uid);
            __out = {all, links: Object.keys(L.pos).sort(), keep: keep.slice().sort(),
                     grouped: L.grouped, map: devs.sort(),
                     edgesOut: L.edges.filter(e => !keep.includes(e.from) || !keep.includes(e.to)).length};
        """)
        assert out['all'] == 90
        assert out['links'] == out['keep'] and out['map'] == out['keep']
        assert out['edgesOut'] == 0
        # One site left: no frame, nothing to fold.
        assert not out['grouped']


class TestTheStatesAreOnThePicture:

    def test_a_dead_cable_a_degraded_site_link_and_a_folded_site_in_trouble(self, run):
        out = run(r"""
            const map = fleet(3, 30, {downAt: '0/1/1'});
            _ngFold = {map: {}, links: {all: 'open', k: {'~leaves': 1}}};
            use(map);
            const L = _infraLinkLayout(map);
            const html = _infraLinkContent(L);
            const down = L.edges.findIndex(e => e.kind === 'down');
            const site = L.edges.findIndex(e => e.kind === 'site' && e.state === 'error');
            const g = s => (html.split(`data-edge="${s}"`)[1] || '').split('</g>')[0];
            // Folded: the site with the dead cable wears it on its box.
            _ngFold = {map: {}, links: {all: 'fold'}};
            _infraMapStamp++;
            const F = _infraLinkLayout(map);
            const fh = _infraLinkContent(F);
            const s0 = fh.split('data-node="grp:s:s0"')[1].split('</g>')[0];
            const agg = F.links.find(l => (l.a === 'grp:s:s0' || l.b === 'grp:s:s0') && l.agg
                                          && (l.a === 'grp:s:s1' || l.b === 'grp:s:s1'));
            // …and a switch with its servers folded in wears the worst of them and their cables.
            _ngFold = {map: {}, links: {all: 'open', k: {'~leaves': 0}}};
            _infraMapStamp++;
            const P = _infraLinkLayout(map);
            const parent = P.parentOf.get(L.edges[down].from) || P.parentOf.get(L.edges[down].to);
            const pill = _infraLinkLeavesPill(P.pos[parent], P);
            __out = {downState: _infraLinkState(L.edges[down]), downClaim: _infraLinkClaim(L.edges[down]),
                     downHtml: g(down), siteHtml: g(site), siteState: _infraLinkState(L.edges[site]),
                     s0, aggState: agg && agg.state, inside: F.insideState.get('grp:s:s0'),
                     pill, worst: ssNetWorst(['ok', 'warning', 'down', 'error'])};
        """)
        assert out['downState'] == 'down' and out['downClaim'] == 'down'
        assert 'var(--bs-danger)' in out['downHtml'] and 'stroke-dasharray="7 4"' in out['downHtml']
        assert out['siteState'] == 'error' and 'var(--bs-danger)' in out['siteHtml']
        # The folded site with machines in error is edged in red, and its dead cable is inside.
        assert 'var(--bs-danger)' in out['s0'] and out['inside'] == 'down'
        # The site link in error between the two folded sites keeps its state, added up.
        assert out['aggState'] == 'error'
        assert 'var(--bs-danger)' in out['pill'] and '+' in out['pill']
        assert out['worst'] == 'down'


class TestTheAddressMap:

    def test_a_next_hop_nobody_registered_is_one_router_and_not_a_fan(self, run):
        """Every machine pointing at an unregistered `.1` was a way out of its own, each with a
        curve from the cloud — the fan the map was reported for."""
        out = run(r"""
            const map = fleet(2, 120, {});
            _ngFold = {map: {all: 'open', k: {'~net': 1}}, links: {}};
            use(map);
            const L = _infraMapLayout(map);
            const ghosts = [...L.at.values()].filter(p => p.kind === 'ghost');
            const exits = L.links.filter(l => l.kind === 'exit');
            const serves = L.links.filter(l => l.kind === 'serves');
            _ngFold = {map: {all: 'open'}, links: {}};
            _infraMapStamp++;
            const D = _infraMapLayout(map);
            __out = {ghosts: ghosts.length, users: ghosts.reduce((s, g) => s + g.ghost.users.length, 0),
                     exits: exits.length, serves: serves.length,
                     servesCount: serves.reduce((s, l) => s + l.count, 0),
                     gateways: [...L.at.values()].filter(p => p.kind === 'gateway').length,
                     netfold: [...D.at.values()].filter(p => p.kind === 'netfold').length,
                     drawn: D.at.size, over: overlaps([...D.at.values()])};
        """)
        nets = 2 * 4                       # four networks per site (core + three access)
        assert out['ghosts'] == nets and out['users'] == 240
        assert out['exits'] == nets, 'one line from the outside per router, not per machine'
        assert out['servesCount'] == 240 and out['serves'] <= nets * 2
        assert out['gateways'] == 0, 'a machine using a next hop is not a way out'
        # By default a network of more than BAND_MAX machines is folded into its plate.
        assert out['netfold'] >= 1 and out['over'] == 0


class TestAThousandMachinesDoNotFreezeThePage:

    #: Generous on purpose — CI machines are slower than a workstation, and the point is the
    #: order of magnitude: the old layouts were not slow, they were unreadable; a layout that
    #: took seconds per hover would be the next complaint. Measured on a workstation: under
    #: 100 ms to lay out and under 100 ms to draw, for either map, in every fold state.
    BUDGET_MS = 1500

    def test_layout_and_drawing_inside_the_budget(self, run):
        out = run(r"""
            const map = fleet(12, 84, {});
            const res = {nodes: map.nodes.length,
                         cables: map.edges.filter(e => e.kind === 'lldp' || e.kind === 'down').length};
            for (const mode of ['default', 'open', 'full']) {
              _ngFold = {map: {}, links: {}};
              if (mode !== 'default') { _ngFold.map = {all: 'open'}; _ngFold.links = {all: 'open'}; }
              if (mode === 'full') { _ngFold.map.k = {'~net': 1}; _ngFold.links.k = {'~leaves': 1}; }
              use(map);
              let t = Date.now();
              const L = _infraLinkLayout(map);
              res['links_layout_' + mode] = Date.now() - t;
              t = Date.now();
              const h = _infraLinkContent(L);
              res['links_draw_' + mode] = Date.now() - t;
              t = Date.now();
              const M = _infraMapLayout(map);
              res['map_layout_' + mode] = Date.now() - t;
              t = Date.now();
              _infraMapContent(M);
              res['map_draw_' + mode] = Date.now() - t;
              // A hover re-reads the layout: it must be the kept one, not a new one.
              t = Date.now();
              for (let i = 0; i < 50; i++) _infraLinkLayout(map);
              res['links_hover50_' + mode] = Date.now() - t;
              res['drawn_' + mode] = Object.keys(L.pos).length;
              res['html_' + mode] = h.length;
            }
            __out = res;
        """)
        assert out['nodes'] >= 1000 and out['cables'] >= 1400, out
        assert out['drawn_full'] == out['nodes']
        for key, ms in out.items():
            if key.split('_')[0] in ('links', 'map') and not key.startswith('links_hover'):
                assert ms < self.BUDGET_MS, (key, ms, out)
        assert out['links_hover50_full'] < self.BUDGET_MS, out


class TestItIsWiredIntoTheList:

    def test_the_folds_travel_with_the_list_preferences(self, run):
        out = run(r"""
            _ngFold = {map: {all: 'open'}, links: {k: {'s:a': 0}}};
            const reg = _LIST_TABLE_REGISTRY.find(d => d.k === 'infra');
            const saved = reg.extra();
            _ngFold = {map: {}, links: {}};
            reg.applyExtra({view: 'links', net: saved.net});
            __out = {saved, back: ssNetFoldSaved()};
        """)
        assert out['saved']['net'] == {'map': {'all': 'open'}, 'links': {'k': {'s:a': 0}}}
        assert out['back'] == out['saved']['net']
