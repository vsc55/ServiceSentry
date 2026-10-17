#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo's monitoring side (`lib.core.dcim.demo_monitor`), installed through the demo.

Asked for: devices, clusters and checks behind the demo, with probe data, so the sites and the
alerts are real. What is proved here:

* every item the demo painted is a device of the registry, with its class, documentation
  address, profiles and placeholder credentials, and is bound to it;
* the checks are simulated items the monitor answers; the states the board shows DERIVE from
  their results —the same state the demo painted, now from somewhere— and break when the feed
  stops; the scheduler's own cycle keeps them fresh and never runs a probe for them;
* the alerts go through the cycle's notifier and reach no channel;
* no unrelated module is enabled, a disabled one stays disabled;
* removing takes all of it away and leaves what was not the demo's; installing twice adds
  nothing.

**One install for the whole file.** The demo takes a minute to install and every xdist worker
that ran one of these tests built its own —four, five at once on the same cores, plus the two
tests that needed a fresh one: sixteen minutes—. Now it is installed once per session, under a
lock every worker shares (`_snapshots`), copied for each module and for each test that changes
it; the inventory alone is kept beside it for the one test that needs to install the monitoring
part on its own.
"""

import importlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

from lib.core.dcim import demo, demo_monitor                       # noqa: E402
from lib.core.dcim import service as dcim_svc                      # noqa: E402
from lib.core.notify import registry                               # noqa: E402
from lib.core.notify.monitor_notifier import MonitorNotifier       # noqa: E402
from lib.modules import simulated                                  # noqa: E402

_DOC_NETS = ('192.0.2.', '198.51.100.', '203.0.113.', '2001:db8:')
#: What the installation had before the demo: a module tuned and one switched off, a device
#: and a credential of its own whose names the demo would want.
_BEFORE_MODULES = {'ping': {'threads': 3},
                   'temperature': {'enabled': False}}


def _panel(tmp):
    from tests.conftest import _seed_editable_config
    cfg, var = os.path.join(tmp, 'cfg'), os.path.join(tmp, 'var')
    os.makedirs(cfg)
    os.makedirs(var)
    with open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8') as fh:
        json.dump({'monitoring': {'timer_check': 300, 'autostart': False},
                   'global': {'log_level': 'off'}, 'events': {'autostart': False},
                   'syslog': {'autostart': False},
                   # Every monitor alert kind routed to Telegram: if a demo alert could reach
                   # a channel, this is the configuration that would send it.
                   'notifications': {'telegram_on_down': True, 'telegram_on_warn': True,
                                     'telegram_on_recovery': True}}, fh)
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa._modules_dir = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                                   'watchfuls')
    _seed_editable_config(wa, cfg)
    wa._save_modules(json.loads(json.dumps(_BEFORE_MODULES)))
    wa._devices_store.create({'name': 'CORE-1', 'address': '10.9.9.9'}, actor='someone')
    wa._credentials_store.create({'name': demo_monitor.CRED_SSH, 'ctype': 'ssh',
                                  'description': 'ours', 'data': {'ssh_user': 'ops'}},
                                 actor='someone')
    return wa, var


class _Spy:
    """A Telegram channel that only counts, and the alerts the notifier was handed."""

    def __init__(self):
        self.sent, self.added = [], []

    def channels(self):
        def flush(_r, _cfg, alerts, *_a):
            self.sent.append(list(alerts))
            return True, 'ok'
        return {'telegram': registry.Channel('telegram', lambda *a, **k: (True, ''), flush)}


def _install(tmp, spy, progress=None):
    wa, var = _panel(tmp)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(registry, 'channels', spy.channels)
        mp.setattr(demo_monitor, 'HISTORY_HOURS', 12)
        mp.setattr(demo_monitor, 'INCIDENT', dict(demo_monitor.INCIDENT, from_h=8, to_h=6))
        _add = MonitorNotifier.add

        def add(self, kind, module, item, message, also='', simulated=False):
            spy.added.append({'kind': kind, 'simulated': simulated})
            return _add(self, kind, module, item, message, also=also, simulated=simulated)
        mp.setattr(MonitorNotifier, 'add', add)
        made = demo.build(wa._dcim_store, app=wa, var_dir=var, progress=progress)
    return wa, var, made


def _open(tmp):
    """A panel over a copy of a snapshot (no seeding: it is all there)."""
    cfg, var = os.path.join(tmp, 'cfg'), os.path.join(tmp, 'var')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa._modules_dir = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                                   'watchfuls')
    return wa, var


def _copy(src, dst):
    """A snapshot copied: the files as they are, each SQLite database through the engine's own
    backup (a live one may have pages in its journal still)."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns('*.db', '*.db-wal', '*.db-shm'))
    for root, _dirs, files in os.walk(src):
        for name in files:
            if name.endswith('.db'):
                here = os.path.join(root, name)
                there = os.path.join(dst, os.path.relpath(here, src))
                a, b = sqlite3.connect(here), sqlite3.connect(there)
                try:
                    a.backup(b)
                finally:
                    a.close()
                    b.close()


@pytest.fixture(scope='session')
def _snapshots(tmp_path_factory, worker_id):
    """``(installed dir, inventory dir, meta)``: the demo installed through the panel, and the
    inventory alone, built ONCE for every worker of the session (the first one to ask builds
    them, under a lock; the rest wait and read). *meta* is what the install said: the sites it
    made and the alerts the notifier was handed."""
    from filelock import FileLock
    root = tmp_path_factory.getbasetemp()
    if worker_id != 'master':
        root = root.parent
    base = root / 'demo_monitor_snapshots'
    base.mkdir(exist_ok=True)
    meta_file = base / 'meta.json'
    with FileLock(str(base / 'lock')):
        if not meta_file.exists():
            spy = _Spy()
            wa, _var, made = _install(str(base / 'installed'), spy)
            _settle(wa)
            # The inventory alone: the same build with no part joined to it.
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(demo, 'DEMO_PARTS', [])
                wb, _vb = _panel(str(base / 'inventory'))
                inventory = demo.build(wb._dcim_store, app=wb, var_dir=_vb)
            _settle(wb)
            meta_file.write_text(json.dumps({
                'made': made, 'inventory': inventory, 'added': spy.added, 'sent': spy.sent}),
                encoding='utf-8')
    return str(base / 'installed'), str(base / 'inventory'), json.loads(
        meta_file.read_text(encoding='utf-8'))


def _settle(wa):
    try:
        wa._db_connector.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    except Exception:  # pylint: disable=broad-except
        pass


def _from(snapshot):
    tmp = os.path.join(tempfile.mkdtemp(), 'copy')
    _copy(snapshot, tmp)
    return _open(tmp)


@pytest.fixture(scope='module')
def installed(_snapshots):
    snap, _inv, meta = _snapshots
    wa, var = _from(snap)
    spy = _Spy()
    spy.added, spy.sent = list(meta['added']), list(meta['sent'])
    yield wa, var, dict(meta['made']), spy


def _ctx(wa, made, app=True):
    return demo.DemoContext(wa._dcim_store, app=wa if app else None, words=demo.texts(''),
                            created={'sites': {k: made[k] for k in demo.UID_KEYS}})


def _rows(wa, made):
    return demo_monitor._painted(_ctx(wa, made))


def _states(wa):
    from lib.core.devices import service as devices_svc
    return devices_svc._device_statuses(wa)


def _board(wa, made):
    """Every site's and every link's state, as the board computes them."""
    estados = _states(wa)
    s = wa._dcim_store
    por_item, sedes = {}, {}
    for key in demo.UID_KEYS:
        st = []
        for room in s.rooms_of(made[key]):
            for rack in s.racks_of(room['uid']):
                for it in s.items_of(rack['uid']):
                    por_item[it['uid']] = dcim_svc.item_state(it, estados)
                    st.append(por_item[it['uid']])
        sedes[key] = dcim_svc.worst(st)
    links = dcim_svc.links_roll(s.links_of(), s.sites.list(), por_item)['links']
    return sedes, links


def _power(wa, made):
    return demo_monitor._power_rows(_ctx(wa, made), _rows(wa, made))


def _uid_of(wa, r):
    """The device a painted or power row is bound to, as the inventory says now."""
    s = wa._dcim_store
    if r.get('pdu'):
        return s.pdus.get(r['pdu']['uid'])['device_uid']
    if r.get('source'):
        return s.sources.get(r['source']['uid'])['device_uid']
    return s.items.get(r['item']['uid'])['device_uid']


def _device(wa, name):
    return next(d for d in wa._devices_store.list(decrypt=True)
                if d['source'] == 'demo' and d['name'] == name)


def _snmp_of(wa, uid):
    """``{(field, row): value}`` of what the SNMP sweep recorded of one device."""
    out = {}
    for key, rec in (wa._read_check_status().get('snmp') or {}).items():
        if not key.startswith(f'host.{uid}'):
            continue
        data = rec.get('other_data') or {}
        row = str(data.get('_row') or '')
        for field, value in data.items():
            if not str(field).startswith('_'):
                out[(field, row)] = value
        for facts in (data.get('_attrs') or {}).values():
            for field, value in facts.items():
                out[(field, row)] = value
    return out


def _demo_items(wa):
    return list(demo_monitor._demo_items(wa._load_modules()))


class TestDevices:

    def test_every_painted_item_is_a_bound_device(self, installed):
        wa, _var, made, _spy = installed
        rows = _rows(wa, made)
        devs = {d['uid']: d for d in wa._devices_store.list(decrypt=False)}
        assert len(rows) > 300
        for r in rows:
            uid = r['item'].get('device_uid')
            assert uid in devs, r['label']
            d = devs[uid]
            assert d['source'] == 'demo' and d['external_id'] == r['item']['uid']
            assert d['address'].startswith(_DOC_NETS), d['address']
            assert d['device_type'], r['label']

    def test_profiles_and_placeholder_credentials(self, installed):
        wa, _var, made, _spy = installed
        rows = {r['label']: r for r in _rows(wa, made)}
        srv = wa._devices_store.get(rows['srv-s02-01']['item']['device_uid'])
        cred = srv['profiles']['ssh']['cred_uid']
        assert srv['kind'] == 'remote' and cred
        fila = wa._credentials_store.get(cred)
        # The installation's own credential with the same name was not taken over.
        assert fila['name'] != demo_monitor.CRED_SSH and fila['description'] != 'ours'
        assert fila['description'] in demo_monitor._every_text('cred_desc')
        assert fila['data']['ssh_password'].startswith('demo-placeholder')
        crudo = wa._db_connector.fetchone('SELECT data FROM credentials WHERE uid = ?', (cred,))
        assert 'demo-placeholder' not in crudo[0]          # encrypted at rest, like any secret
        sw = wa._devices_store.get(rows['SW-A01']['item']['device_uid'])
        assert sw['kind'] == 'none' and sw['profiles']['snmp']['version'] == '2c'
        types = {t['uid']: t.get('slug') for t in wa._device_types_store.list()}
        assert types[srv['device_type']] == 'hypervisor'
        assert types[sw['device_type']] == 'switch'

    def test_a_name_already_taken_is_not_reused(self, installed):
        wa, _var, made, _spy = installed
        rows = {r['label']: r for r in _rows(wa, made)}
        ours = wa._devices_store.get_by_name('CORE-1')
        assert ours['source'] == '' and ours['address'] == '10.9.9.9'
        dev = wa._devices_store.get(rows['CORE-1']['item']['device_uid'])
        assert dev['name'] == 'CORE-1 [demo]' and dev['source'] == 'demo'


class TestChecksAndClusters:

    def test_each_device_has_simulated_checks(self, installed):
        wa, _var, made, _spy = installed
        items = _demo_items(wa)
        bound = {i.get('device_uid') for _m, _c, _k, i in items}
        for r in _rows(wa, made):
            assert r['item']['device_uid'] in bound, r['label']
        ping = [i for m, _c, _k, i in items if m == 'ping']
        # …one each, the UPSs and PDUs too.
        assert len(ping) == len(_rows(wa, made)) + len(_power(wa, made))
        assert all(simulated.is_simulated(i) for _m, _c, _k, i in items)

    def test_no_unrelated_module_and_disabled_stays_disabled(self, installed):
        wa, _var, _made, _spy = installed
        mods = wa._load_modules()
        assert mods['temperature'] == {'enabled': False}
        assert mods['ping']['threads'] == 3 and 'enabled' not in mods['ping']
        assert demo_monitor.MODULE_MARK not in mods['ping']
        nuevos = set(mods) - set(_BEFORE_MODULES)
        assert nuevos <= {'cpu', 'ram_swap', 'filesystemusage', 'web', 'ssl_cert', 'snmp',
                          'raid', 'keepalived', 'proxmox'}, nuevos
        for m in nuevos:
            assert mods[m].get(demo_monitor.MODULE_MARK) is True and 'enabled' not in mods[m]

    def test_three_clusters_with_their_members(self, installed):
        wa, _var, made, _spy = installed
        rows = {r['label']: r['item']['device_uid'] for r in _rows(wa, made)}
        mods = wa._load_modules()
        ka = [i for i in mods['keepalived']['list'].values() if 'device_uids' in i]
        miembros = sorted(sorted(i['device_uids']) for i in ka)
        assert miembros == sorted([sorted([rows['FW-1'], rows['FW-2']]),
                                   sorted([rows['CORE-1'], rows['CORE-2']])])
        pve = [i for i in mods['proxmox']['list'].values() if 'device_uids' in i]
        assert len(pve) == 1 and len(pve[0]['device_uids']) == 12
        dev = wa._devices_store.get(rows['FW-1'])
        assert dev['profiles']['keepalived']['priority'] == 150


def _every_one_due(mp):
    """A sweep of the whole fleet, as a cycle long after the last one: every simulated device
    is due (they are sampled on a cadence of their own, `simulated_agent.is_due`)."""
    from lib.core.snmp import simulated_agent
    mp.setattr(simulated_agent, 'is_due', lambda *_a, **_k: True)


def _api(wa):
    c = wa.app.test_client()
    c.post('/login', data={'username': 'admin', 'password': 'secret'})
    return c


class TestSnmp:
    """Asked for from the screen: «it has no SNMP data — they all should, the real-time network
    map is validated with it». Every demo device that speaks SNMP is sampled by the SNMP
    module's own sampler and profiles, answered by its simulated agent."""

    def _speaking(self, wa, made):
        return [r for r in _rows(wa, made) if r['role'] in demo_monitor._SNMP_PROFILES]

    def test_identity_of_every_device(self, installed):
        """Every demo device that speaks SNMP —in trouble or not— says what it is."""
        from lib.core.devices.resolve import reported_facts
        wa, _var, made, _spy = installed
        estado = wa._read_check_status()
        site_names = {s['name'] for s in demo.find(wa._dcim_store)}
        todos = self._speaking(wa, made)
        assert len(todos) == len(_rows(wa, made))           # every painted device speaks
        for r in todos:
            dev = wa._devices_store.get(r['item']['device_uid'], decrypt=False)
            f = {k: v[0]['value'] for k, v in reported_facts(estado, dev['uid']).items()}
            assert f.get('name') == dev['name'], r['label']
            for role in ('description', 'serial', 'firmware', 'location', 'model_reported'):
                assert f.get(role), (r['label'], role)
            assert f['location'].split(' › ')[0] in site_names

    def test_every_device_has_measures_and_raw_data(self, installed):
        """Asked for from the screen, of srv-a01-03 in error: «they should all have data». Each
        device's sheet has a header measure with a value and raw results; one in error has its
        fault IN its SNMP data (srv-a01-03: the NIC down), not an absence of it."""
        from lib.core.snmp import profiles as snmp_profiles
        wa, _var, made, _spy = installed
        c = _api(wa)
        # Every device, out of the state the sheet is built from: a numeric reading of a
        # measure its own profiles declare as a headline. (Through the sheet itself for one
        # device of each kind and site below: the sheet is two seconds a device, and 451 of
        # them were most of this file's sixteen minutes.)
        cat = snmp_profiles.catalog()
        estado = wa._read_check_status().get('snmp') or {}
        filas = _rows(wa, made) + _power(wa, made)
        uno = {}
        for r in filas:
            uid = _uid_of(wa, r)
            dev = wa._devices_store.get(uid, decrypt=False)
            cabeza = {m['key'] for p in snmp_profiles.expand(
                cat, dev['profiles']['snmp']['device_profiles']) for m in cat[p]['metrics']
                      if m.get('headline')}
            mios = [v for k, v in estado.items() if k.startswith(f'host.{uid}')]
            assert mios, r['label']
            assert any(isinstance((v.get('other_data') or {}).get(f), (int, float))
                       for v in mios for f in cabeza), r['label']
            uno.setdefault((r['site_key'], r['role']), uid)
        for uid in uno.values():
            j = c.get(f"/api/v1/infra/devices/{uid}").get_json()
            snmp = [x for x in j['results'] if x['module'] == 'snmp'
                    and str(x['key']).startswith('host.')]
            assert snmp, uid
            cabecera = [m for m in j['metrics'] if m.get('headline') and m['module'] == 'snmp'
                        and isinstance(m.get('value'), (int, float))]
            assert cabecera, uid
        srv = {x['label']: x for x in _rows(wa, made)}['srv-a01-03']
        j = c.get(f"/api/v1/infra/devices/{srv['item']['device_uid']}").get_json()
        oper = [m['value'] for m in j['metrics'] if m['field'] == 'if_oper' and m.get('row')]
        assert oper and set(oper) == {2}, oper             # every data link of it, down

    def test_offline_site_keeps_what_it_was_and_answers_nothing_fresh(self, installed):
        """South Africa answered until it went offline: after a sweep it answers nothing, and
        its sheet still says what each device is."""
        from lib.core.devices.resolve import reported_facts
        wa, _var, made, _spy = installed
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(registry, 'channels', lambda: {})
            _every_one_due(mp)
            wa._run_checks(['snmp'], timeout=300)
        estado = wa._read_check_status()
        snmp = estado.get('snmp') or {}
        # Everyone else answered this sweep, the ones in trouble too (srv-a01-03 included).
        for r in self._speaking(wa, made):
            if r['site_key'] == 'site_za':
                continue
            fila = snmp.get(f"host.{r['item']['device_uid']}/metrics") or {}
            assert fila and 'error' not in (fila.get('other_data') or {}), r['label']
        za = [r for r in self._speaking(wa, made) if r['site_key'] == 'site_za']
        assert {r['label'] for r in za} >= {'RTR-ZA', 'FW-ZA', 'SW-ZA', 'srv-za-01'}
        for r in za:
            uid = r['item']['device_uid']
            mios = {k: v for k, v in snmp.items() if k.startswith(f'host.{uid}')}
            assert set(mios) == {f'host.{uid}/metrics'}, r['label']
            assert 'error' in mios[f'host.{uid}/metrics']['other_data']
            assert reported_facts(estado, uid).get('name'), r['label']
            assert [s for s in wa._history.get_index()
                    if str(s.get('key') or '').startswith(f'host.{uid}/')], r['label']

    def test_header_measures_are_declared_and_valued(self, installed):
        wa, _var, made, _spy = installed
        rows = {r['label']: r for r in _rows(wa, made)}
        c = _api(wa)
        for label, want in (('srv-s02-01', {'uptime', 'cpu_idle', 'load_1'}),
                            ('SW-A01', {'uptime'}), ('FW-S01', {'uptime'})):
            j = c.get(f"/api/v1/infra/devices/{rows[label]['item']['device_uid']}").get_json()
            cabecera = {m['field'] for m in j['metrics'] if m.get('headline')
                        and isinstance(m.get('value'), (int, float))}
            assert want <= cabecera, (label, cabecera)

    def test_logs_tab_and_lldp_and_map(self, installed):
        """The Logs tab reads the incident; the map's LLDP links are the cabling's, port by
        port; the uplink CORE-2 lost is not on it; a second sweep gives traffic rates."""
        from lib.core.dcim import service as dcim_svc
        from lib.core.dcim.store import PASS_THROUGH
        wa, _var, made, _spy = installed
        rows = {r['label']: r for r in _rows(wa, made)}
        c = _api(wa)
        fwdr = wa._devices_store.get(rows['FW-DR']['item']['device_uid'], decrypt=False)
        logs = c.get(f"/api/v1/syslog?device={fwdr['address']}").get_json()
        texto = json.dumps(logs, ensure_ascii=False)
        assert 'IKEv2' in texto and 'ipsec0' in texto

        habla = {r['item']['uid']: r for r in self._speaking(wa, made)
                 if r['site_key'] != 'site_za'}
        esperado = set()
        for uid, r in habla.items():
            for path in dcim_svc.trace(wa._dcim_store, uid):
                fin = path[-1]
                if (len(path) < 2 or (path[1].get('cable') or {}).get('kind') == 'power'
                        or fin.get('role') in PASS_THROUGH or fin.get('item') not in habla):
                    continue
                a, b = r['item']['device_uid'], habla[fin['item']]['item']['device_uid']
                esperado.add(frozenset(((a, path[0]['port']), (b, fin['port']))))
        # The ends each device says are down (its agent's own interfaces): the core uplink
        # and the links of srv-a01-03.
        caido = set()
        for uid, r in habla.items():
            spec = (wa._devices_store.get(r['item']['device_uid'])['profiles']['snmp']
                    ['simulated'])
            caido |= {(r['item']['device_uid'], f['name']) for f in spec['ifs']
                      if int(f.get('oper') or 1) == 2}
        perdido = {e for e in esperado if set(e) & caido}
        core2 = rows['CORE-2']['item']['device_uid']
        srv = rows['srv-a01-03']['item']['device_uid']
        assert any(core2 in {d for d, _p in e} for e in perdido)
        assert any(srv in {d for d, _p in e} for e in perdido)
        esperado -= perdido
        mapa = c.get('/api/v1/infra/map').get_json()
        visto = set()
        for e in mapa['edges']:
            if e.get('kind') != 'lldp':
                continue
            pa, pb = e['ports'].get(e['from']) or [], e['ports'].get(e['to']) or []
            for x in pa:
                for y in pb:
                    visto.add(frozenset(((e['from'], x), (e['to'], y))))
        assert len(esperado) > 100
        assert esperado <= visto, list(esperado - visto)[:5]
        assert not (visto & perdido)
        nodos = {n['uid']: n for n in mapa['nodes']}
        assert nodos[rows['RTR-ZA']['item']['device_uid']]['status'] == 'error'

        # As a dedicated worker would, which never ran the install: no agent bound in this
        # process. The sampler itself binds each device's agent before it talks to it.
        from lib.core.snmp import simulated_agent
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(simulated_agent, '_BOUND', {})
            mp.setattr(simulated_agent, '_AGENTS', {})
            mp.setattr(registry, 'channels', lambda: {})
            _every_one_due(mp)
            wa._run_checks(['snmp'], timeout=300)
        estado = wa._read_check_status().get('snmp') or {}
        sw = rows['SW-A01']['item']['device_uid']
        rates = [v['other_data'].get('if_hc_in') for k, v in estado.items()
                 if k.startswith(f'host.{sw}/') and 'if_hc_in' in (v.get('other_data') or {})]
        assert rates and any(x and x > 0 for x in rates)


class TestStatesComeFromTheChecks:

    def test_each_item_reads_the_state_the_demo_painted(self, installed):
        wa, _var, made, _spy = installed
        estados = _states(wa)
        for r in _rows(wa, made):
            it = wa._dcim_store.items.get(r['item']['uid'])
            assert dcim_svc.item_state(it, estados) == r['state'], r['label']
        assert estados[_rows(wa, made)[0]['item']['device_uid']] in ('ok', 'warning', 'error')

    def test_sites_and_links(self, installed):
        wa, _var, made, _spy = installed
        sedes, links = _board(wa, made)
        assert sedes['site_za'] == 'error' and sedes['site_tw'] == 'ok'
        assert sedes['site_pr'] == 'warning'
        dr = [l for l in links if {l['a_site'], l['b_site']} == {made['site'], made['site_dr']}]
        assert sorted(l['state'] for l in dr) == ['error', 'ok']

    def test_break_the_feed_and_the_site_is_no_longer_down(self, installed):
        """The states are the results': with no feed the cycle prunes them and South Africa
        stops reading «down»; the next cycle with the feed puts it back."""
        wa, _var, made, _spy = installed
        from lib.core.snmp import devices as snmp_devices
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(simulated, 'results', lambda *_a, **_k: [])
            # …and the SNMP sweep, the other half of the feed: nothing samples the agents.
            mp.setattr(snmp_devices, 'devices_to_sample', lambda *_a, **_k: [])
            mp.setattr(registry, 'channels', lambda: {})
            wa._run_checks(['ping', 'cpu', 'ram_swap', 'filesystemusage', 'web', 'snmp'])
        sedes, _links = _board(wa, made)
        assert sedes['site_za'] != 'error'
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(registry, 'channels', lambda: {})
            wa._run_checks(['ping', 'cpu', 'ram_swap', 'filesystemusage', 'web', 'snmp'])
        sedes, _links = _board(wa, made)
        assert sedes['site_za'] == 'error'

    def test_a_cycle_answers_them_and_probes_nothing(self, installed):
        wa, _var, made, _spy = installed
        wdir = wa._modules_dir
        if wdir not in sys.path:
            sys.path.insert(0, wdir)
        ping = importlib.import_module('ping')
        sondas = []
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ping.Watchful, '_ping_return',
                       lambda self, host, *a: sondas.append(host) or (False, None))
            mp.setattr(registry, 'channels', lambda: {})
            results, errors = wa._run_checks(['ping'])
        assert not errors
        demo_hosts = {d['address'] for d in wa._devices_store.list(decrypt=False)
                      if d['source'] == 'demo'}
        assert not demo_hosts & set(sondas), 'a demo device was probed'
        ping_keys = {k for m, _c, k, _i in _demo_items(wa) if m == 'ping'}
        assert ping_keys <= set(results['ping'])

    def test_history_has_the_incident_and_the_outages(self, installed):
        wa, _var, made, _spy = installed
        hist = wa._history
        import time
        q = lambda key: hist.query('ping', key, time.time() - 3 * 86400, time.time() + 60,
                                   max_points=0)
        rows = {r['label']: r for r in _rows(wa, made)}
        keys = {i['device_uid']: k for m, _c, k, i in _demo_items(wa) if m == 'ping'}
        za = q(keys[rows['RTR-ZA']['item']['device_uid']])
        assert za and za[0]['status'] in (True, 1) and za[-1]['status'] in (False, 0)
        assert time.time() - za[0]['ts'] > 6 * 3600       # days of it, not one moment
        tx = q(keys[rows['RTR-TX']['item']['device_uid']])
        caidas = [p for p in tx if p['status'] in (False, 0)]
        assert caidas and tx[-1]['status'] in (True, 1)   # the incident, and its recovery
        tw = q(keys[rows['RTR-TW']['item']['device_uid']])
        assert tw and all(p['status'] in (True, 1) for p in tw)
        assert any('latency_ms' in (p.get('data') or {}) for p in tw)
        cpu = {i['device_uid']: k for m, _c, k, i in _demo_items(wa) if m == 'cpu'}
        uno = hist.query('cpu', cpu[rows['srv-s02-01']['item']['device_uid']],
                         time.time() - 3 * 86400, time.time() + 60, max_points=0)
        assert uno and time.time() - uno[0]['ts'] > 6 * 3600
        assert all('used' in (p.get('data') or {}) for p in uno)

    @pytest.fixture(autouse=True)
    def _with_snapshots(self, _snapshots):
        self._snaps = _snapshots

    def test_the_past_is_written_before_the_scheduler_can_answer(self):
        """Found on the verification server: the scheduler answered the new checks while the
        install was still writing their past, and a series it had started was skipped — CPU,
        memory and disk had twenty minutes of history instead of two days."""
        visto = []
        _real = demo_monitor._backfill

        def backfill(surf, rows, nuevos, progress):
            visto.append(len(list(demo_monitor._demo_items(surf.modules()))))
            return _real(surf, rows, nuevos, progress)
        pasos = []
        _snap, inventory, meta = self._snaps
        wa, _var = _from(inventory)
        words = demo.texts('')
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(demo_monitor, '_backfill', backfill)
            mp.setattr(demo_monitor, 'HISTORY_HOURS', 2)
            mp.setattr(registry, 'channels', lambda: {})
            ctx = demo.DemoContext(wa._dcim_store, app=wa, words=words, created={
                'sites': {k: meta['inventory'][k] for k in demo.UID_KEYS}})
            demo_monitor.install(ctx, demo.Progress(pasos.append, words, demo_monitor.STEPS))
        assert visto == [0]
        # …and each of this part's steps ENDS at its total: the dialog showed «350/356» for
        # good, because the last tick of a throttled loop was the last multiple of 25.
        for paso in demo_monitor.STEPS:
            mios = [e for e in pasos if e['step_key'] == paso and e.get('total')]
            assert mios, paso
            assert mios[-1]['done'] == mios[-1]['total'], (paso, mios[-1])


class TestNoExternalDelivery:

    def test_the_alerts_were_raised_and_none_was_sent(self, installed):
        wa, _var, _made, spy = installed
        simulados = [a for a in spy.added if a['simulated']]
        assert len(simulados) >= 20                    # the outages did raise their alerts
        assert spy.sent == []

    def test_a_real_alert_still_goes_out(self, installed):
        """The control: the same configuration and channel deliver an ordinary alert, so the
        silence above is the guard's and not a channel that was never wired."""
        wa, _var, _made, _spy = installed
        spy = _Spy()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(registry, 'channels', spy.channels)
            n = MonitorNotifier(wa)
            n.add('down', 'ping', 'real-host', 'Ping: real-host 🔽')
            n.add('down', 'ping', 'demo-host', 'Ping: demo-host 🔽', simulated=True)
            n.flush()
        assert len(spy.sent) == 1 and [a['item'] for a in spy.sent[0]] == ['real-host']


class TestInstallTwiceAndRemove:

    def test_install_again_writes_nothing(self, installed):
        wa, _var, made, _spy = installed
        antes = (len(wa._devices_store.list(decrypt=False)), len(_demo_items(wa)),
                 len(wa._credentials_store.list(decrypt=False)))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(registry, 'channels', lambda: {})
            out = demo_monitor.install(_ctx(wa, made))
        assert out['devices'] == 0 and out['checks'] == 0 and out['samples'] == 0
        assert antes == (len(wa._devices_store.list(decrypt=False)), len(_demo_items(wa)),
                         len(wa._credentials_store.list(decrypt=False)))

    def test_without_the_panel_it_installs_nothing(self, installed):
        wa, _var, made, _spy = installed
        assert demo_monitor.install(_ctx(wa, made, app=False)) == {'skipped': 'no panel'}

    def test_remove_takes_all_of_it_and_nothing_else(self, _snapshots):
        snap, _inv, meta = _snapshots
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(registry, 'channels', lambda: {})
            wa, var = _from(snap)
            made = dict(meta['made'])
            demo_keys = {(m, k) for m, _c, k, _i in _demo_items(wa)}
            assert demo_keys
            suyos = {d['uid'] for d in wa._devices_store.list(decrypt=False)
                     if d['source'] == 'demo'}
            assert any(k.startswith('host.') for k in
                       (wa._check_state_store.as_status_dict().get('snmp') or {}))
            logdb = wa._syslog_store._db
            n_logs = logdb.fetchone('SELECT COUNT(*) FROM SystemEvents WHERE MsgID = ?',
                                    (simulated.SYSLOG_MSGID,))[0]
            assert n_logs > 10
            assert demo.remove(wa._dcim_store, app=wa, var_dir=var) == 6
        mods = wa._load_modules()
        assert mods == _BEFORE_MODULES
        assert [d['name'] for d in wa._devices_store.list(decrypt=False)] == ['CORE-1']
        assert [c['description'] for c in wa._credentials_store.list(decrypt=False)] == ['ours']
        estado = wa._check_state_store.as_status_dict()
        assert not any(k.split('/')[0].split('_')[0] in {x for _m, x in demo_keys}
                       for m in estado.values() for k in m)
        assert not [s for s in wa._history.get_index()
                    if (s.get('module'), str(s.get('key') or '').split('/')[0]) in demo_keys
                    or (s.get('module'), str(s.get('key') or '').rsplit('_', 1)[0]) in demo_keys]
        from lib.core.devices.resolve import device_uid_from_key
        assert not [k for m in wa._check_state_store.as_status_dict().values() for k in m
                    if device_uid_from_key(k) in suyos]
        assert not [s for s in wa._history.get_index()
                    if device_uid_from_key(str(s.get('key') or '')) in suyos]
        assert logdb.fetchone('SELECT COUNT(*) FROM SystemEvents WHERE MsgID = ?',
                              (simulated.SYSLOG_MSGID,))[0] == 0
        # Twice converges: nothing left to remove, nothing fails.
        assert demo_monitor.remove(_ctx(wa, made))['devices'] == 0

    def test_remove_without_the_panel_creates_no_table(self, tmp_path):
        from lib.core.dcim.store import DcimStore
        from lib.db import get_connector
        store = DcimStore(get_connector(None, default_sqlite_path=str(tmp_path / 'x.db')))
        antes = set(store._db.list_tables())
        out = demo_monitor.remove(demo.DemoContext(store))
        assert out['devices'] == 0 and set(store._db.list_tables()) == antes


class TestPower:
    """Asked for: «the UPSs and PDUs of the demo have no SNMP data». Every UPS and metered PDU
    is a device answered by its agent through the STANDARD MIBs —UPS-MIB (RFC 1628) and
    ENTITY-SENSOR-MIB (RFC 3433)— with the load the inventory hangs from it."""

    def test_every_ups_and_pdu_is_a_bound_device(self, installed):
        wa, _var, made, _spy = installed
        rows = _power(wa, made)
        s = wa._dcim_store
        devs = {d['uid']: d for d in wa._devices_store.list(decrypt=False)}
        types = {t['uid']: t.get('slug') for t in wa._device_types_store.list()}
        assert len([r for r in rows if r['role'] == 'ups']) == len(
            [x for x in s.sources.list() if x['kind'] == 'ups'])
        assert len([r for r in rows if r['role'] == 'pdu']) == len(s.pdus.list())
        for r in rows:
            fila = (s.pdus if r['role'] == 'pdu' else s.sources).get(
                (r.get('pdu') or r.get('source'))['uid'])
            d = devs[fila['device_uid']]
            assert d['source'] == 'demo' and d['address'].startswith(_DOC_NETS), r['label']
            if r.get('item'):
                assert s.items.get(r['item']['uid'])['device_uid'] == d['uid']
            prof = d['profiles']['snmp']['device_profiles']
            assert ('ups_mib' if r['role'] == 'ups' else 'entity_sensor') in prof
            assert types[d['device_type']] == ('ups' if r['role'] == 'ups' else 'other')
        # The drawing of «SAI A» in its room is bound too.
        sai = next(x for x in s.sources.list() if x['name'] == 'SAI A')
        assert s.features.get(sai['feature_uid'])['device_uid'] == sai['device_uid']

    def test_the_ups_carries_what_its_pdus_draw(self, installed):
        """«SAI A»: its output is what the PDUs of every rack it feeds draw, its load that
        against its rating, its runtime the inventory's own at half load scaled by it."""
        from lib.core.dcim import service as dcim_svc
        wa, _var, made, _spy = installed
        s = wa._dcim_store
        sai = next(x for x in s.sources.list() if x['name'] == 'SAI A')
        fuentes = s.sources_of()
        detras = [p for p in s.pdus.list() if sai['uid'] in {
            f['uid'] for f in dcim_svc.chain_up(fuentes, p['source_uid'], honour_bypass=False)}]
        dibujo = sum(demo_monitor._draw(f) for f in s.feeds_of([p['uid'] for p in detras]))
        got = _snmp_of(wa, sai['device_uid'])
        salida = sum(v for (f, _r), v in got.items() if f == 'ups_out_power')
        assert len(detras) > 20 and dibujo > 10000
        assert 0.85 * dibujo <= salida <= 1.15 * dibujo, (salida, dibujo)
        carga = [v for (f, _r), v in got.items() if f == 'ups_out_load']
        assert len(carga) == 3                                   # three lines
        assert abs(sum(carga) / 3 - salida / sai['capacity_w'] * 100) <= 2
        assert got[('ups_output_source', '')] == 3 and got[('ups_battery_status', '')] == 2
        assert got[('ups_charge', '')] == 100 and got[('ups_runtime', '')] > 0
        assert got[('vendor_reported', '')] == 'Demo' and got[('model', '')]

    def test_the_pdu_says_what_is_plugged_into_each_outlet(self, installed):
        wa, _var, made, _spy = installed
        s = wa._dcim_store
        racks = {r['uid'] for room in s.rooms_of(made['site']) for r in s.racks_of(room['uid'])}
        pdu = next(p for p in s.pdus.list()
                   if p['rack_uid'] in racks and len(s.feeds_of([p['uid']])) >= 5)
        feeds = s.feeds_of([pdu['uid']])
        got = _snmp_of(wa, pdu['device_uid'])
        for f in feeds:
            w = got[('ent_sensor_power', f"Outlet {f['outlet']} power")]
            assert 0.85 * demo_monitor._draw(f) <= w <= 1.15 * demo_monitor._draw(f) + 1
            amps = got[('ent_sensor_current', f"Outlet {f['outlet']} current")]
            assert isinstance(amps, float) and 0 < amps < 32       # two decimals, in amps
        total = sum(demo_monitor._draw(f) for f in feeds)
        assert 0.85 * total <= got[('ent_sensor_power', 'Inlet power')] <= 1.15 * total + 1
        volts = got[('ent_sensor_volt_ac', [k for k in ('Inlet voltage', 'Phase L1 voltage')
                                             if ('ent_sensor_volt_ac', k) in got][0])]
        assert 225 <= volts <= 235                                 # one decimal, a 230 V site
        # No outlet that nothing is plugged into: a row of every sample for nothing.
        tomas = {r for (_f, r) in got if r.startswith('Outlet ')}
        assert len(tomas) == 2 * len({f['outlet'] for f in feeds})

    def test_the_ups_that_tell_something(self, installed):
        """«SAI B», which the inventory declares on bypass, says so; the Texas one has tired
        batteries; South Africa's answers nothing. Each device's state is what it said."""
        from lib.core.devices import service as devices_svc
        wa, _var, made, _spy = installed
        s = wa._dcim_store
        estados = devices_svc._device_statuses(wa)
        por_nombre = {x['name']: x for x in s.sources.list() if x['kind'] == 'ups'}
        b = _snmp_of(wa, por_nombre['SAI B']['device_uid'])
        assert int(por_nombre['SAI B']['bypass']) == 1
        assert b[('ups_output_source', '')] == 4 and b[('ups_alarms_present', '')] == 1
        assert estados[por_nombre['SAI B']['device_uid']] == 'warning'
        tx = next(x for x in por_nombre.values() if x['site_uid'] == made['site_tx'])
        t = _snmp_of(wa, tx['device_uid'])
        assert t[('ups_battery_status', '')] == 3 and t[('ups_runtime', '')] == 4
        assert t[('ups_alarms_present', '')] == 2
        assert estados[tx['device_uid']] == 'warning'
        alarmas = {v for (f, _r), v in t.items() if f == 'ups_alarm'}
        assert alarmas == {'1', '3'}                     # battery bad, low battery
        za = next(x for x in por_nombre.values() if x['site_uid'] == made['site_za'])
        assert estados[za['device_uid']] == 'error'
        sanos = [x for x in por_nombre.values()
                 if x['site_uid'] not in (made['site_tx'], made['site_za'])
                 and not int(x['bypass'] or 0)]
        assert sanos and all(estados[x['device_uid']] == 'ok' for x in sanos)

    def test_their_alerts_are_marked_and_reach_no_channel(self, _snapshots):
        """Two sweeps: South Africa's devices answer nothing twice and are reported down by
        the SNMP module ITSELF (not by a scenario) — and the alert is marked as a simulation's
        and kept from every channel, like the scenarios'. Before, it went out."""
        snap, _inv, meta = _snapshots
        wa, _var = _from(snap)
        made = dict(meta['made'])
        spy, vistos = _Spy(), []
        _add = MonitorNotifier.add
        za = {d['uid'] for d in wa._devices_store.list(decrypt=False)
              if d['source'] == 'demo' and d['external_id'] in {
                  demo_monitor._ext(r) for r in _rows(wa, made) + _power(wa, made)
                  if r['site_key'] == 'site_za'}}
        nombres = {d['name'] for d in wa._devices_store.list(decrypt=False) if d['uid'] in za}

        def add(self, kind, module, item, message, also='', simulated=False):
            vistos.append((kind, module, item, simulated))
            return _add(self, kind, module, item, message, also=also, simulated=simulated)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(registry, 'channels', spy.channels)
            mp.setattr(MonitorNotifier, 'add', add)
            _every_one_due(mp)
            for _ in range(2):
                wa._run_checks(['snmp'], timeout=600)
        caidas = [v for v in vistos if v[1] == 'snmp' and v[2] in nombres and v[0] == 'down']
        assert caidas, vistos[:5]
        assert all(v[3] is True for v in vistos if v[1] == 'snmp'), [
            v for v in vistos if not v[3]][:5]
        assert spy.sent == []

    def test_removing_the_part_unbinds_the_power_chain(self, _snapshots):
        snap, _inv, meta = _snapshots
        wa, _var = _from(snap)
        s = wa._dcim_store
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(registry, 'channels', lambda: {})
            out = demo_monitor.remove(_ctx(wa, dict(meta['made'])))
        assert out['devices'] > 400
        for table in (s.pdus, s.sources, s.features, s.items):
            assert not [x for x in table.list() if x.get('device_uid')], table


class TestCadence:
    """Asked for: «with the demo the panel samples 356 devices by SNMP every cycle and feels
    slow». A simulated device is sampled once per `simulated_interval` (five minutes), each at
    its own moment within it; in the cycles between it keeps what it said."""

    def _sweep(self, wa):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(registry, 'channels', lambda: {})
            _every_one_due(mp)
            wa._run_checks(['snmp'], timeout=600)

    def _cycle(self, wa, shift=0.0):
        """A cycle *shift* seconds after the last sweep (every sample moment moved back)."""
        if shift:
            st = wa._check_state_store
            mods = st.as_status_dict().get('snmp') or {}
            for rec in mods.values():
                ms = rec.get('module_state')
                if isinstance(ms, dict) and 'sim_at' in ms:
                    ms['sim_at'] = float(ms['sim_at']) - shift
            st.persist_module('snmp', mods)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(registry, 'channels', lambda: {})
            res, err = wa._run_checks(['snmp'], timeout=600)
        assert not err
        return res.get('snmp') or {}

    def test_right_after_a_sweep_nothing_is_sampled_and_nothing_is_lost(self, installed):
        wa, _var, _made, _spy = installed
        self._sweep(wa)
        antes = {k for k in (wa._read_check_status().get('snmp') or {})}
        series = {s['key']: s.get('count') for s in wa._history.get_index()
                  if s['module'] == 'snmp'}
        got = self._cycle(wa)
        demo_uids = {d['uid'] for d in wa._devices_store.list(decrypt=False)
                     if d['source'] == 'demo'}
        # Only the few whose moment came in the seconds the sweep and this cycle took.
        sampled = {k.split('/')[0][5:] for k in got if k.startswith('host.')} & demo_uids
        assert len(sampled) <= 0.15 * len(demo_uids), len(sampled)
        assert antes <= set(wa._read_check_status().get('snmp') or {})   # all kept
        despues = {s['key']: s.get('count') for s in wa._history.get_index()
                   if s['module'] == 'snmp'}
        # (A scenario item of the module is answered every cycle: it is not a sample.)
        quietos = {k: n for k, n in series.items()
                   if k.startswith('host.') and k.split('/')[0][5:] not in sampled}
        assert quietos and all(despues.get(k) == n for k, n in quietos.items())

    def test_a_minute_later_a_slice_of_them(self, installed):
        wa, _var, _made, _spy = installed
        self._sweep(wa)
        got = self._cycle(wa, shift=60)
        demo_uids = {d['uid'] for d in wa._devices_store.list(decrypt=False)
                     if d['source'] == 'demo' and (d.get('profiles') or {}).get('snmp')}
        sampled = {k.split('/')[0][5:] for k in got if k.startswith('host.')} & demo_uids
        # A fifth of the fleet in a minute of a five-minute cadence, give or take.
        assert 0.10 * len(demo_uids) <= len(sampled) <= 0.32 * len(demo_uids), len(sampled)
        # …and five minutes later every one of them has been.
        got = self._cycle(wa, shift=301)
        sampled = {k.split('/')[0][5:] for k in got if k.startswith('host.')} & demo_uids
        assert sampled == demo_uids


class TestCommandLine:
    """Asked for: «`main.py dcim demo` installs the demo without its monitoring». The command
    line installs, reports and removes it whole, with no panel running: the part is built from
    the database and the configuration the command already opens (`demo_monitor.Headless`)."""

    def test_install_status_and_remove_without_a_panel(self, tmp_path, capsys):
        from types import SimpleNamespace
        from lib.cli import commands
        from lib.cli.context import CliContext
        d = str(tmp_path)

        def run(**kw):
            args = SimpleNamespace(cmd='dcim', sub='demo', replace=False, remove=False,
                                   no_images=True, status=False, quiet=False)
            for k, v in kw.items():
                setattr(args, k, v)
            return commands.run(args, d, d)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(demo_monitor, 'HISTORY_HOURS', 2)
            assert run() == 0
        out = capsys.readouterr().out
        ctx = CliContext(d, d)
        words = demo.texts(ctx.lang)
        for paso in demo_monitor.STEPS:                      # the same progress lines
            assert words['step_' + paso] in out, paso
        ctx = CliContext(d, d)
        host = demo_monitor.Headless.from_cli(ctx)
        devs = [x for x in host._devices_store.list(decrypt=False) if x['source'] == 'demo']
        assert len(devs) > 400
        estado = host._check_state_store.as_status_dict()
        assert len(estado.get('ping') or {}) >= len(devs)
        # The first SNMP sweep is the monitor's, with no panel: identity and readings.
        assert sum(1 for k in (estado.get('snmp') or {}) if k.endswith('/metrics')) > 300
        assert any(s['module'] == 'ping' for s in host._history.get_index())
        # The placeholder credentials, encrypted with the installation's key.
        cred = host._credentials_store.get_by_name(demo_monitor.CRED_SSH, decrypt=True)
        assert cred['data']['ssh_password'].startswith('demo-placeholder')
        # …and the log lines, in the syslog store the panel would open.
        logs = 'SELECT COUNT(*) FROM SystemEvents WHERE MsgID = ?'
        assert host._syslog_store._db.fetchone(logs, (simulated.SYSLOG_MSGID,))[0] > 10
        assert run(status=True) == 0
        assert f"monitoring: {len(devs)} devices" in capsys.readouterr().out
        assert run(remove=True) == 0
        assert 'demo removed (6 sites)' in capsys.readouterr().out
        ctx = CliContext(d, d)
        host = demo_monitor.Headless.from_cli(ctx)
        assert not [x for x in host._devices_store.list(decrypt=False) if x['source'] == 'demo']
        assert not list(demo_monitor._demo_items(host._load_modules()))
        assert not host._credentials_store.list(decrypt=False)
        assert host._syslog_store._db.fetchone(logs, (simulated.SYSLOG_MSGID,))[0] == 0
        assert run(status=True) == 0
        assert 'no demo installed' in capsys.readouterr().out
