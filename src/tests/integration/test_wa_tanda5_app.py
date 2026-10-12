#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deferred findings of the 2026-10-12 audit, fifth batch — the parts that go through the app.

* V11 — an event rule created through the API without a cooldown gets 60 s; an explicit 0 is
  kept, and editing a rule stored without one does not give it one.
* D12 — a power source may hang from another site's source, but only for a caller who may
  WRITE that other site; same-site chains keep today's rule.
"""

from __future__ import annotations

import pytest

import shutil

from tests.conftest import _login, _login_as                        # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _uid(r):
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()['uid']


_RULE = {'name': 'Rule T5', 'source': 'syslog', 'channels': ['telegram']}


class TestEventRuleCooldown:
    """V11."""

    def test_a_rule_created_without_one_gets_sixty_seconds(self, admin, client):
        _login(client)
        r = client.post('/api/v1/event/rules', json=dict(_RULE))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['rule']['cooldown'] == 60

    def test_an_explicit_zero_is_kept(self, admin, client):
        _login(client)
        r = client.post('/api/v1/event/rules', json=dict(_RULE, cooldown=0))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['rule']['cooldown'] == 0

    def test_editing_a_stored_rule_without_one_does_not_change_it(self, admin, client):
        _login(client)
        rid = client.post('/api/v1/event/rules',
                          json=dict(_RULE, cooldown=None)).get_json()['rule']['id']
        r = client.put(f'/api/v1/event/rules/{rid}', json=dict(_RULE, name='Rule T5b'))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['rule']['cooldown'] is None


@pytest.fixture()
def sedes(admin, client):
    """Company A with two sites, company B with one; a user of A."""
    _login(client)
    c = client
    a = _uid(c.post('/api/v1/orgs', json={'name': 'A', 'short': 'A'}))
    b = _uid(c.post('/api/v1/orgs', json={'name': 'B', 'short': 'B'}))
    sa1 = _uid(c.post('/api/v1/dcim/sites', json={'name': 'SA1'}))
    sa2 = _uid(c.post('/api/v1/dcim/sites', json={'name': 'SA2'}))
    sb = _uid(c.post('/api/v1/dcim/sites', json={'name': 'SB'}))
    for s, o in ((sa1, a), (sa2, a), (sb, b)):
        c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': s, 'org_uid': o})
    ua = _login_as(admin, 'ua5', perms=['dcim_view', 'dcim_edit', f'org.{a}.view'])
    return dict(sa1=sa1, sa2=sa2, sb=sb, ua=ua)


class TestCrossSiteChains:
    """D12."""

    def test_a_chain_may_cross_into_a_site_the_caller_writes(self, admin, client, sedes):
        ua = sedes['ua']
        arriba = _uid(ua.post('/api/v1/dcim/sources', json={'site_uid': sedes['sa2'],
                                                            'name': 'Substation'}))
        nueva = _uid(ua.post('/api/v1/dcim/sources', json={'site_uid': sedes['sa1'],
                                                           'name': 'Panel',
                                                           'upstream_uid': arriba}))
        assert admin._dcim_store.sources.get(nueva)['upstream_uid'] == arriba
        otra = _uid(ua.post('/api/v1/dcim/sources', json={'site_uid': sedes['sa1'],
                                                          'name': 'Panel 2'}))
        r = ua.put(f'/api/v1/dcim/sources/{otra}', json={'upstream_uid': arriba})
        assert r.status_code == 200, r.get_json()

    def test_a_chain_may_not_cross_into_a_site_the_caller_cannot_write(self, admin, client,
                                                                        sedes):
        ua = sedes['ua']
        ajena = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': sedes['sb'],
                                                               'name': 'B-UPS'}))
        r = ua.post('/api/v1/dcim/sources', json={'site_uid': sedes['sa1'], 'name': 'P',
                                                  'upstream_uid': ajena})
        assert r.status_code == 403
        mia = _uid(ua.post('/api/v1/dcim/sources', json={'site_uid': sedes['sa1'], 'name': 'P'}))
        r = ua.put(f'/api/v1/dcim/sources/{mia}', json={'upstream_uid': ajena})
        assert r.status_code == 403
        assert admin._dcim_store.sources.get(mia)['upstream_uid'] == ''

    def test_a_same_site_chain_keeps_todays_rule(self, admin, client, sedes):
        ua = sedes['ua']
        arriba = _uid(ua.post('/api/v1/dcim/sources', json={'site_uid': sedes['sa1'],
                                                            'name': 'UPS'}))
        _uid(ua.post('/api/v1/dcim/sources', json={'site_uid': sedes['sa1'], 'name': 'Out',
                                                   'upstream_uid': arriba}))


@pytest.fixture()
def cruce(admin, client):
    """A rack of company A fed through a panel of A from a UPS on company B's site."""
    _login(client)
    c = client
    a = _uid(c.post('/api/v1/orgs', json={'name': 'A', 'short': 'A'}))
    b = _uid(c.post('/api/v1/orgs', json={'name': 'B', 'short': 'B'}))
    sa = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Alpha-site'}))
    sb = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Bravo-site'}))
    for s, o in ((sa, a), (sb, b)):
        c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': s, 'org_uid': o})
    room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': sa, 'name': 'R'}))
    rack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'K',
                                                   'u_height': 42}))
    ups = _uid(c.post('/api/v1/dcim/sources', json={'site_uid': sb, 'name': 'Bravo-UPS',
                                                    'kind': 'ups'}))
    panel = _uid(c.post('/api/v1/dcim/sources', json={'site_uid': sa, 'name': 'Alpha-panel',
                                                      'upstream_uid': ups}))
    pdu = _uid(c.post('/api/v1/dcim/pdus', json={'rack_uid': rack, 'name': 'PDU-A',
                                                 'source_uid': panel}))
    ua = _login_as(admin, 'ua5x', perms=['dcim_view', f'org.{a}.view'])
    return dict(sa=sa, rack=rack, pdu=pdu, ua=ua)


class TestCrossSiteChainView:
    """D12 — the power path marks the hop into another site, and hides what the reader may
    not see of it."""

    def _rack_now(self, cli, cruce):
        r = cli.get(f'/api/v1/dcim/racks/{cruce["rack"]}/power')
        assert r.status_code == 200, r.get_json()
        fila = [p for p in r.get_json()['pdus'] if p['uid'] == cruce['pdu']][0]
        return r, fila['path']['now']

    def test_whoever_sees_both_sites_gets_the_hop_by_name(self, admin, client, cruce):
        _, now = self._rack_now(client, cruce)
        assert [n['name'] for n in now] == ['Alpha-panel', 'Bravo-UPS']
        assert now[1]['cross_site'] is True and now[1]['site_name'] == 'Bravo-site'

    def test_whoever_sees_one_site_gets_an_anonymous_hop(self, admin, client, cruce):
        r, now = self._rack_now(cruce['ua'], cruce)
        assert now[0]['name'] == 'Alpha-panel'
        assert now[1].get('hidden') is True and now[1]['name'] == ''
        assert 'Bravo' not in r.get_data(as_text=True)
        r = cruce['ua'].get(f'/api/v1/dcim/sources?site={cruce["sa"]}')
        assert r.status_code == 200
        assert r.get_json()['paths'][cruce['pdu']]['now'][1].get('hidden') is True
        assert 'Bravo' not in r.get_data(as_text=True)


_CHAIN_PROBE = r"""
__out = {};
const p = {pdus: [{uid: 'p', name: 'PDU', feed: 'a', color: '#000', source_uid: 's',
                   path: {known: true, clean: [], now: [
                       {uid: 's', name: 'Panel', kind: 'panel'},
                       {uid: 'u', name: 'Far UPS', kind: 'ups', cross_site: true,
                        site_name: 'Far site'}]}},
                  {uid: 'q', name: 'PDU2', feed: 'b', color: '#000', source_uid: 's',
                   path: {known: true, clean: [], now: [
                       {uid: 's', name: 'Panel', kind: 'panel'},
                       {uid: '', name: '', kind: '', cross_site: true, hidden: true}]}}],
           sources: []};
__out.html = _dcPowerChain(p);
__out.hidden = t('dcim_chain_hidden_site');
__out.other = t('dcim_chain_other_site');
"""


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_the_rack_view_draws_the_hop_and_the_anonymous_one(client):
    """D12 — the hop is drawn with the other site's name, the hidden one with the fixed text."""
    _login(client)
    out = node_run(panel_bundle(client), _CHAIN_PROBE)
    html = out['html']
    assert 'Far site' in html and 'Far UPS' in html
    assert out['hidden'] and out['hidden'] != out['other']
    assert out['hidden'] in html, 'the anonymous hop is not drawn as such'
    assert html.count('bi-building') == 2
