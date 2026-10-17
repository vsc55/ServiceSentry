#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The monitoring side of the demo: devices, clusters, checks and their results.

The inventory alone painted its equipment with a state of its own (``dc_item.demo_state``): a
colour with no check behind it. This part puts the checks behind it, so the site map, the site
cards, the WAN links and the trouble board show what the MONITOR says — exactly as on a real
installation:

* every item the demo painted (the active rack equipment of every site, and the access points,
  cameras and printers of the offices) becomes a **device** of the registry (Infrastructure),
  with its class (Catalogue › Device types), its address, its protocol profiles (SSH for the
  servers, SNMP for the network gear, ICMP for all) and, where a real one would have it, a
  **credential** of the credentials store — placeholders that say so, never a secret — and the
  item is **bound** to it (``dc_item.device_uid``);
* each device gets the **checks** a real one would (ping for all; CPU, memory and disk for the
  servers that matter; the web interface of the firewalls, arrays and cameras; the VPN
  certificate; SNMP hardware health where the demo had a reason to give; RAID), and three
  **clusters** join them: the firewall HA pair, the core VRRP pair and the hypervisor cluster;
* every check is a **simulated item** (:mod:`lib.modules.simulated`): its watchful never sees
  it —nothing is ever probed, no packet leaves for the documentation addresses it carries—
  and the monitor answers it from its scenario on every cycle, so it is never stale, in the
  embedded scheduler and in a dedicated worker alike (the scenario lives in the configuration
  both read). Its results land in the SAME ``check_state`` and ``history`` tables a real check
  writes, through the monitor's own processing, so the state derives as for any device
  (`lib.core.devices.service._device_statuses` → `lib.core.dcim.service.item_state`);
* the scenario says what the demo said: each item's state and reason (``demo_state`` /
  ``demo_reason``) is now the result of one of its checks, so the colours are the same and
  each comes from somewhere. Two days of past readings are written too —latency, CPU, memory—
  with one incident and its recovery (the Texas router, yesterday) and the current
  outages starting when they did;
* every device that would speak **SNMP** carries its device profiles and the description of its
  agent (`lib.core.snmp.simulated_agent`): the SNMP module's own sampler reads it —identity,
  interfaces in use with traffic, LLDP neighbours from the cabling, CPU, memory and sensors— so
  Infrastructure's details, the network map and the cable drift check see the inventory's
  topology and incidents; offline devices answer nothing. Their **logs** are syslog lines of
  their incidents, marked so no event rule matches them;
* the alerts the first results raise go through the cycle's notifier like any other and stop
  before every channel (`lib.core.notify.monitor_notifier.deliverable`): a demonstration never
  pages anybody.

Everything it writes is found again by a mark, not by a name somebody may share: the devices
by ``source = 'demo'`` (and the item they stand for in ``external_id``), the checks by their
scenario's ``source``, the credentials by name AND description, the module entries it created
by ``__demo__``. `remove` takes all of it away; `install` twice writes nothing new.

Registered as a part of the demo (`lib.core.dcim.demo.register_part`) at import.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import os
import time
import uuid

from lib.i18n import TRANSLATIONS
from lib.modules import simulated

#: The mark on everything this part writes.
SOURCE = 'demo'
#: The steps of an install, in order (their texts: ``step_<key>`` in the demo's words).
STEPS = ('monitor_devices', 'monitor_history', 'monitor_checks', 'monitor_results')
#: The credentials, language-free as a product name is: found by name AND description.
CRED_SSH = 'Demo · SSH'
CRED_PVE = 'Demo · Proxmox API'
CREDS = (CRED_SSH, CRED_PVE)
#: The field a module entry this part created carries, so only that one is ever taken away.
MODULE_MARK = '__demo__'
#: How many hours of past readings an install writes, one an hour.
HISTORY_HOURS = 48
#: The namespace of the checks' uids: the same item and module always give the same check, so
#: installing again rewrites it instead of adding a second one.
_NS = uuid.UUID('6f1d6b2e-0d4c-4d1e-9a51-7b5a2f0de0a1')

#: The section of the core lang files that holds this part's words.
WORDS = 'dcim_demo_monitor_words'
#: The language a partial translation falls back to, as the demo's own words do.
_BASE_LANG = 'es_ES'
_WATCHFULS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), 'watchfuls')

#: The addresses: documentation ranges only (RFC 5737 / RFC 3849), never one that routes.
POOLS = {'net': '192.0.2.0/24', 'srv': '198.51.100.0/24', 'hpc': '203.0.113.0/24',
         'v6': '2001:db8:d::/64'}
#: The room items that are infrastructure and watched as such. The PCs, phones and screens
#: of the desks are not: a real installation does not page anybody about a PC switched off.
ROOM_ROLES = ('ap', 'camera', 'printer')
#: Which device class each role is (`devices/stores/types.py` SEED slugs).
_TYPE_OF = {'server': 'server', 'switch': 'switch', 'router': 'router', 'firewall': 'firewall',
            'storage': 'nas', 'camera': 'camera', 'printer': 'printer', 'ups': 'ups'}
#: Round-trip times per site, in ms: a LAN, the recovery centre, and the far ones.
_LATENCY = {'site': (0.4, 0.2), 'site_dr': (6.5, 1.5), 'site_tx': (112.0, 8.0),
            'site_pr': (186.0, 22.0), 'site_za': (164.0, 10.0), 'site_tw': (246.0, 14.0)}
#: The reasons a check of their own answers; every other reason is SNMP hardware health.
_BY_PING = ('why_ping', 'why_site_offline')
_BY_RAID = ('why_raid_failed',)
_BY_WEB = ('why_cam_signal',)
#: How long ago each current outage started, in hours (default 3): what the history shows.
_SINCE = {'why_ping': 0.25, 'why_site_offline': 2.0, 'why_ipsec_down': 5.0,
          'why_ha_sync': 0.1, 'why_uplink_down': 1.0}
#: The past incident: the Texas router stopped answering yesterday, for two hours (inside the
#: day a chart opens on).
INCIDENT = {'label': 'RTR-TX', 'from_h': 21, 'to_h': 19}


def texts(lang: str = '') -> dict:
    """This part's words in *lang*, completed from Spanish where it says nothing."""
    def _words(name):
        return dict((TRANSLATIONS.get(str(name or '')) or {}).get(WORDS) or {})
    out = _words(_BASE_LANG)
    if lang and lang != _BASE_LANG:
        out.update(_words(lang))
    return out


def _every_text(key: str) -> set:
    return {str(texts(lang).get(key) or '') for lang in TRANSLATIONS} - {''}


# ── Where it writes ──────────────────────────────────────────────────────────────────────────

class _Surface:
    """The stores this part writes, from the panel when it installs and from the database
    when the command line does (no panel: built on the inventory's own connector)."""

    def __init__(self, ctx):
        app = getattr(ctx, 'app', None)
        self.app, self.db, self.dcim = app, ctx.db, ctx.store
        fernet = getattr(ctx, 'fernet', None)
        from lib.core.credentials.store import CredentialsStore       # noqa: PLC0415
        from lib.core.devices.stores.devices import DevicesStore      # noqa: PLC0415
        from lib.core.devices.stores.types import DeviceTypesStore    # noqa: PLC0415
        from lib.core.history.store import HistoryStore               # noqa: PLC0415
        from lib.services.monitoring.check_state.store import CheckStateStore  # noqa: PLC0415

        def _of(attr, make):
            got = getattr(app, attr, None) if app is not None else None
            return got if got is not None else make()
        self.devices = _of('_devices_store', lambda: DevicesStore(self.db, fernet=fernet))
        self.creds = _of('_credentials_store', lambda: CredentialsStore(self.db, fernet=fernet))
        self.types = _of('_device_types_store', lambda: DeviceTypesStore(self.db))
        self.state = _of('_check_state_store', lambda: CheckStateStore(self.db))
        self.history = _of('_history', lambda: HistoryStore(self.db))
        self.orgs = getattr(app, '_orgs_store', None) if app is not None else None
        self._facade = None

    def mutate_modules(self, fn):
        """Load → *fn* → save, as every other writer of the module configuration does."""
        if self.app is not None:
            from lib.core.modules.facade import mutate_modules     # noqa: PLC0415
            return mutate_modules(self.app, fn)
        if self._facade is None:
            from lib.core.modules.facade import DbBackedModules    # noqa: PLC0415
            from lib.core.modules.store import ModulesStore        # noqa: PLC0415
            self._facade = DbBackedModules(ModulesStore(self.db))
        self._facade.read()
        data = copy.deepcopy(self._facade.data)
        out = fn(data)
        if out:
            self._facade.save(data, expected_version=self._facade.loaded_version)
        return out

    def modules(self) -> dict:
        box = {}

        def _peek(m):
            box['m'] = copy.deepcopy(m)
            return None
        self.mutate_modules(_peek)
        return box.get('m') or {}


class Headless:
    """What this part needs of a panel, built from what a command line already has open
    (`main.py dcim demo`, `lib.cli.commands`): the shared database and its key, the
    configuration and data directories. The same stores the panel would hand over —devices,
    credentials (encrypted with the installation's key), device types, check state, history,
    syslog, the module configuration— and the directories a monitor is built from, so the
    first results and the first SNMP sweep are the monitor's own, as from the panel. No Flask,
    no scheduler and no channel: the alerts of the first results are not raised at all (from
    the panel they are raised and kept from every channel), and the scheduler, when the panel
    runs, carries on from the state written here.

    Passed to `demo.build` / `demo.remove` as their ``app``."""

    headless = True

    def __init__(self, db, *, fernet=None, config_dir: str = '', var_dir: str = '',
                 modules_dir: str = '', cfg: dict | None = None):
        from lib.core.credentials.store import CredentialsStore       # noqa: PLC0415
        from lib.core.devices.stores.devices import DevicesStore      # noqa: PLC0415
        from lib.core.devices.stores.types import DeviceTypesStore    # noqa: PLC0415
        from lib.core.history.store import HistoryStore               # noqa: PLC0415
        from lib.core.modules.facade import DbBackedModules           # noqa: PLC0415
        from lib.core.modules.store import ModulesStore               # noqa: PLC0415
        from lib.security import secret_manager                       # noqa: PLC0415
        from lib.services.monitoring.check_state.store import CheckStateStore  # noqa: PLC0415
        self._db_connector = db
        self._fernet = fernet
        self._config_dir = str(config_dir or '')
        self._var_dir = str(var_dir or config_dir or '')
        self._modules_dir = str(modules_dir or _WATCHFULS)
        self._cfg = dict(cfg or {})
        self._devices_store = DevicesStore(db, fernet=fernet)
        self._credentials_store = CredentialsStore(db, fernet=fernet)
        self._device_types_store = DeviceTypesStore(db)
        self._check_state_store = CheckStateStore(db)
        self._history = HistoryStore(db)
        self._orgs_store = None
        try:
            from lib.core.orgs.store import OrgsStore                  # noqa: PLC0415
            self._orgs_store = OrgsStore(db)
        except Exception:                                   # pylint: disable=broad-except
            pass
        self._modules_facade = DbBackedModules(ModulesStore(db), fernet=fernet,
                                               secret_keys=secret_manager.ENCRYPT_KEYS)
        self._modules_facade.read()
        self._syslog_store = self._syslog()

    @classmethod
    def from_cli(cls, ctx) -> 'Headless':
        """From a `lib.cli.context.CliContext`."""
        return cls(ctx.db, fernet=getattr(ctx, 'fernet', None), config_dir=ctx.config_dir,
                   var_dir=ctx.var_dir, cfg=getattr(ctx, 'cfg', None))

    def _syslog(self):
        """The syslog store the panel would open: its own database when ``syslog_db`` says
        so, the shared one otherwise. ``None`` when it cannot be opened (the logs are a
        nicety of the demo, not a step of it)."""
        try:
            from lib.config.manager import overlay_section_env     # noqa: PLC0415
            from lib.db import build_syslog_connector               # noqa: PLC0415
            from lib.services.syslog.store import SyslogStore, is_read_only  # noqa: PLC0415
            sdb = overlay_section_env('syslog_db', dict(self._cfg.get('syslog_db') or {}))
            conn = build_syslog_connector(
                sdb, main_connector=self._db_connector,
                default_sqlite_path=os.path.join(self._var_dir, 'syslog.db'))
            return SyslogStore(conn, time_zone=lambda: (self._cfg.get('syslog') or {}).get(
                'time_zone'), read_only=is_read_only(sdb))
        except Exception:                                   # pylint: disable=broad-except
            return None

    def _load_modules(self) -> dict:
        return copy.deepcopy(self._modules_facade.reload_if_changed())

    def _save_modules(self, data: dict) -> bool:
        self._modules_facade.save(copy.deepcopy(data))
        return True


def status(ctx) -> dict:
    """What of this part is installed: ``{devices, checks, credentials}`` (zeros when none).
    Reads only; a database with no device registry has none of it."""
    if getattr(ctx, 'app', None) is None and not ctx.db.table_exists('devices'):
        return {'devices': 0, 'checks': 0, 'credentials': 0}
    surf = _Surface(ctx)
    descs = _every_text('cred_desc')
    creds = sum(1 for nombre in CREDS for candidato in _cred_names(nombre)
                if str((surf.creds.get_by_name(candidato, decrypt=False) or {})
                       .get('description') or '') in descs)
    return {'devices': len(_demo_devices(surf)),
            'checks': sum(1 for _ in _demo_items(surf.modules())), 'credentials': creds}


# ── What the demo painted ────────────────────────────────────────────────────────────────────

def _painted(ctx) -> list[dict]:
    """The items of the demo sites that carry a demo state, with where they are: the rack
    equipment that answers and the infrastructure of the offices. ``[{item, site_key, room,
    rack, role, label, state, why}]``, in a stable order."""
    from lib.core.dcim import demo                               # noqa: PLC0415
    from lib.core.dcim.service import DEMO_STATES                # noqa: PLC0415
    s = ctx.store
    words = ctx.words or demo.texts(ctx.lang)
    why_of = {str(v): k for k, v in words.items() if str(k).startswith('why_')}
    sites = {k: v for k, v in ((ctx.created or {}).get('sites') or {}).items()
             if k in demo.UID_KEYS and v}
    out = []
    for site_key, site in sites.items():
        for room in s.rooms_of(site):
            filas = []
            for rack in s.racks_of(room['uid']):
                for it in s.items_of(rack['uid']):
                    if str(it.get('role') or '') not in demo._MUTE:      # noqa: SLF001
                        filas.append((it, rack))
            for it in s.items_in_room(room['uid']):
                if str(it.get('role') or '') in ROOM_ROLES:
                    filas.append((it, None))
            for it, rack in filas:
                estado = str(it.get('demo_state') or '')
                if estado not in DEMO_STATES and not it.get('device_uid'):
                    continue
                out.append({'item': it, 'site_key': site_key, 'room': room, 'rack': rack,
                            'role': str(it.get('role') or ''),
                            'label': str(it.get('label') or '').strip() or it['uid'][:8],
                            'state': estado if estado in DEMO_STATES else 'ok',
                            'why': why_of.get(str(it.get('demo_reason') or ''), ''),
                            'reason': str(it.get('demo_reason') or '')})
    return out


def _names(rows: list) -> None:
    """A unique device name for each row: its label, or its label and rack when two share it
    (the arrays and the console servers of a room have the same model name)."""
    cuenta: dict = {}
    for r in rows:
        cuenta[r['label']] = cuenta.get(r['label'], 0) + 1
    vistos: set = set()
    for r in rows:
        nombre = r['label']
        if cuenta[nombre] > 1:
            nombre = f"{nombre} · {(r['rack'] or {}).get('name') or r['room']['name']}"
        base, n = nombre, 2
        while nombre in vistos:
            nombre, n = f'{base} ({n})', n + 1
        vistos.add(nombre)
        r['name'] = nombre


class _Addresses:
    """Documentation addresses, handed out in order from each pool; IPv6 when one runs out."""

    def __init__(self):
        self._next = {k: ipaddress.ip_network(v).hosts() for k, v in POOLS.items()}
        for _ in range(9):                       # .1-.9 are the gateways and the VIPs
            next(self._next['net'])

    def take(self, pool: str) -> str:
        try:
            return str(next(self._next[pool]))
        except StopIteration:
            return str(next(self._next['v6']))


def _pool(r) -> str:
    if r['role'] != 'server':
        return 'net'
    return 'hpc' if r['label'].startswith('gpu-') else 'srv'


# ── The checks ───────────────────────────────────────────────────────────────────────────────

def _messages(lang: str) -> dict:
    """``{module: {key: template}}`` from each watchful's own lang file, so a demo result reads
    exactly as the module's own would."""
    out = {}
    for mod in ('ping', 'cpu', 'ram_swap', 'filesystemusage', 'web', 'ssl_cert', 'snmp',
                'raid', 'keepalived', 'proxmox'):
        msgs = {}
        for name in ('es_ES', 'en_EN', lang):
            try:
                with open(os.path.join(_WATCHFULS, mod, 'lang', f'{name}.json'),
                          encoding='utf-8') as fh:
                    msgs.update(json.load(fh).get('messages') or {})
            except (OSError, ValueError, TypeError):
                pass
        out[mod] = msgs
    return out


def _fmt(tpl: str, *args) -> str:
    try:
        return str(tpl).format(*args)
    except (IndexError, KeyError, ValueError):
        return ' '.join(str(a) for a in args)


def _check_uid(item_uid: str, module: str, extra: str = '') -> str:
    return str(uuid.uuid5(_NS, f'{item_uid}|{module}|{extra}'))


def _res(status: str, message: str, suffix: str = '', metrics=None, data=None,
         since_h: float = 0.0) -> dict:
    out = {'suffix': suffix, 'status': status, 'message': message}
    if metrics:
        out['metrics'] = metrics
    if data:
        out['data'] = data
    if since_h:
        out['since_h'] = since_h
    return out


def _plan(r: dict, m: dict, w: dict) -> dict:
    """``{module: (collection, item fields, [results])}``: the checks of one device, with what
    each answers. The device's state is the worst of them, and it is the demo's."""
    label, role, estado, why = r['label'], r['role'], r['state'], r['why']
    caido = why == 'why_site_offline'
    since = _SINCE.get(why, 3.0)
    lat = _LATENCY.get(r['site_key'], (0.4, 0.2))
    if role in ('ap', 'camera', 'printer', 'kvm', 'console'):
        lat = (lat[0] + 0.6, lat[1] + 0.3)
    p = {}
    ping_bad = why in _BY_PING
    p['ping'] = ('list', {}, [_res('error' if ping_bad else 'ok',
                                   _fmt(m['ping'].get('ping_down' if ping_bad else 'ping_up'), label),
                                   metrics=None if ping_bad else {'latency_ms': [lat[0], lat[1], 2]},
                                   data={'reason': r['reason']} if ping_bad else None,
                                   since_h=since if ping_bad else 0)])
    servidor_completo = role == 'server' and (r['label'].startswith('srv-s')
                                              or r['site_key'] != 'site')
    def _sin_red(prefix):
        return _res('error', f"{prefix}: {label} - *Error: {w['unreachable']}* 💥", since_h=since)
    if servidor_completo:
        semilla = sum(ord(c) for c in label)
        cpu, ram, disco = 18 + semilla % 37, 42 + semilla % 23, 31 + semilla % 41
        p['cpu'] = ('list', {}, [
            _sin_red('CPU') if caido else
            _res('ok', _fmt(m['cpu'].get('cpu_ok'), label, cpu),
                 metrics={'used': [cpu, 9, 1]}, data={'alert': 85.0})])
        p['ram_swap'] = ('list', {}, [_sin_red('Memory')] if caido else [
            _res('ok', _fmt(m['ram_swap'].get('mem_ok'), 'RAM', label, ram), suffix='_ram',
                 metrics={'used': [ram, 6, 1]}, data={'alert': 60.0, 'name': f'{label} - RAM'}),
            _res('ok', _fmt(m['ram_swap'].get('mem_ok'), 'SWAP', label, 2), suffix='_swap',
                 metrics={'used': [2, 1.5, 1]}, data={'alert': 60.0, 'name': f'{label} - SWAP'})])
        p['filesystemusage'] = ('list', {'partition': '/'}, [
            _sin_red('Disk') if caido else
            _res('ok', _fmt(m['filesystemusage'].get('fs_ok_label'), label, '/', disco),
                 metrics={'used': [disco, 1, 0]}, data={'mount': '/', 'alert': 85.0})])
    if role in ('firewall', 'storage', 'camera'):
        mal = why in _BY_WEB
        p['web'] = ('list', {}, [
            _sin_red('Web') if caido else
            _res('error' if mal else 'ok',
                 _fmt(m['web'].get('web_down' if mal else 'web_up'), label)
                 + (f" [{w['camera_detail']}]" if mal else ''),
                 data={'code': 0 if mal else 200,
                       'detail': w['camera_detail'] if mal else 'HTTP 200'},
                 since_h=since if mal else 0)])
    if role == 'firewall' and r['site_key'] == 'site':
        p['ssl_cert'] = ('list', {}, [_res('ok', _fmt(m['ssl_cert'].get('ssl_ok'), label, 214),
                                           data={'days_left': 214, 'port': 443})])
    if why in _BY_RAID:
        p['raid'] = ('list', {}, [_res(estado, _fmt(m['raid'].get('raid_degraded'), label, 'md0')
                                       + ' ' + r['reason'], suffix='_md0', since_h=since)])
    elif estado != 'ok' and why not in _BY_PING + _BY_WEB:
        # The rest of the reasons are what a device's own agent says over SNMP: a supply, a
        # GPU, a port, a tunnel. The check that would have seen it, with the demo's words.
        clave = 'snmp_state_warn' if estado == 'warning' else 'snmp_state_bad'
        p['snmp'] = ('servers', {'checks': {}}, [
            _res(estado, _fmt(m['snmp'].get(clave), label, w['health'], r['reason']),
                 since_h=since)])
    elif role in ('router', 'firewall') or label.startswith('CORE-'):
        p['snmp'] = ('servers', {'checks': {}}, [
            _sin_red('SNMP') if caido else
            _res('ok', _fmt(m['snmp'].get('snmp_up'), label, w['health_ok']))])
    return p


def _scenario(results: list) -> dict:
    return {'source': SOURCE, 'results': results}


def _check_item(r: dict, module: str, fields: dict, results: list) -> tuple:
    uid = _check_uid(_ext(r), module)
    item = {'uid': uid, 'enabled': True, 'label': r['name'], 'device_uid': r['device'],
            **fields, simulated.SIM_KEY: _scenario(results)}
    return uid, item


# ── Install ──────────────────────────────────────────────────────────────────────────────────

def _credentials(surf: _Surface, w: dict, actor: str) -> dict:
    """The two placeholder credentials, created once: ``{name: uid}``."""
    quiere = {CRED_SSH: ('ssh', {'ssh_user': 'demo', 'ssh_auth_method': 'password',
                                 'ssh_password': 'demo-placeholder-not-a-secret'}),
              CRED_PVE: ('proxmox_auth', {'auth_method': 'token',
                                          'token_id': 'demo@pve!servicesentry',
                                          'token_secret': 'demo-placeholder-not-a-secret'})}
    out = {}
    marcas = _every_text('cred_desc')
    for nombre, (tipo, datos) in quiere.items():
        for candidato in _cred_names(nombre):
            fila = surf.creds.get_by_name(candidato, decrypt=False)
            if fila is None:
                uid = surf.creds.create({'name': candidato, 'ctype': tipo,
                                         'description': w['cred_desc'], 'data': datos},
                                        actor=actor)
                if uid:
                    out[nombre] = uid
                break
            if str(fila.get('description') or '') in marcas:
                out[nombre] = fila['uid']               # ours, from an earlier install
                break
            # The installation's own, by the same name: never used, never touched.
    return out


def _cred_names(nombre: str) -> tuple:
    """The names a demo credential may have: its own, or tagged when that one is taken."""
    return (nombre, f'{nombre} [demo]')


def _types(surf: _Surface) -> dict:
    out = {}
    for slug in set(_TYPE_OF.values()) | {'hypervisor', 'other'}:
        try:
            fila = surf.types.by_slug(slug)
        except Exception:                                   # pylint: disable=broad-except
            fila = None
        out[slug] = (fila or {}).get('uid', '')
    return out


def _demo_devices(surf: _Surface) -> dict:
    """``{dc_item uid: device}`` of the devices this part made."""
    return {str(d.get('external_id') or ''): d for d in surf.devices.list(decrypt=False)
            if str(d.get('source') or '') == SOURCE}


def _device_record(r, w, creds, types, addr) -> dict:
    role = r['role']
    hyper = r['label'].startswith('srv-s')
    tipo = types.get('hypervisor' if hyper else _TYPE_OF.get(role, 'other')) or ''
    perfiles = {'icmp': {}}
    if role == 'server':
        perfiles['ssh'] = {'ssh_port': 22, 'cred_uid': creds.get(CRED_SSH, ''),
                           'ssh_verify_host': False}
        if hyper:
            perfiles['proxmox'] = {'port': 8006, 'node': r['label'],
                                   'cred_uid': creds.get(CRED_PVE, '')}
    if role in _SNMP_PROFILES:
        perfiles['snmp'] = {'port': 161, 'version': '2c', 'community': 'demo-placeholder'}
    if role == 'firewall' and r['site_key'] == 'site':
        perfiles['keepalived'] = {'priority': 150 if r['label'].endswith('1') else 100}
    if r['label'].startswith('CORE-'):
        perfiles['keepalived'] = {'priority': 200 if r['label'].endswith('1') else 150}
    return {'name': r['name'], 'address': addr,
            'kind': 'remote' if role == 'server' else 'none',
            'os': 'linux' if role == 'server' else 'other',
            'device_type': tipo, 'tags': ['demo'],
            'description': w['device_desc'] % (r['room']['name'],),
            'profiles': perfiles, 'source': SOURCE, 'external_id': _ext(r)}


def _ext(r: dict) -> str:
    """What a device stands for (``external_id``): its DCIM item, or —a UPS with no item, only
    a source of the power chain— that source."""
    return str(r.get('ext') or (r.get('item') or {}).get('uid') or '')


# ── The power: UPSs and metered PDUs ─────────────────────────────────────────────────────────

#: The mains of each site: volts and hertz (Spain and South Africa 230 V 50 Hz; the data
#: centres of Texas and Puerto Rico 208 V 60 Hz; Taiwan 220 V 60 Hz).
_MAINS = {'site': (230, 50), 'site_dr': (230, 50), 'site_za': (230, 50),
          'site_tx': (208, 60), 'site_pr': (208, 60), 'site_tw': (220, 60)}
#: What the equipment draws of what the inventory says it does (`dc_feed.watts_said`): a
#: declared figure is a nameplate or a plan, and a server runs at a fraction of it.
DRAW = 0.6
#: The UPS of the demo that tells something (the bypass of «SAI B» the inventory already
#: declares is the other): the Texas one, on the mains with tired batteries.
TIRED_UPS = {'site_key': 'site_tx', 'runtime_min': 4, 'alarms': (1, 3), 'since_h': 70.0}


def _power_rows(ctx, painted: list) -> list[dict]:
    """The UPSs and the metered PDUs of the demo sites, as devices to be: ``[{role ('ups' or
    'pdu'), item (or None), source / pdu (the row of the power chain), site_key, room, rack,
    label, state, why, reason, ext}]``. A site the demo has offline (`why_site_offline`) has
    them offline too. In a stable order."""
    from lib.core.dcim import demo                               # noqa: PLC0415
    s = ctx.store
    sites = {k: v for k, v in ((ctx.created or {}).get('sites') or {}).items()
             if k in demo.UID_KEYS and v}
    caidas = {r['site_key']: r['reason'] for r in painted if r['why'] == 'why_site_offline'}
    out = []
    for site_key in [k for k in demo.UID_KEYS if k in sites]:
        site = sites[site_key]
        salas = list(s.rooms_of(site))
        racks, primera = {}, {}
        for room in salas:
            for rack in s.racks_of(room['uid']):
                racks[rack['uid']] = (rack, room)

        def fila(role, label, ext, room, rack, **extra):
            caida = site_key in caidas
            out.append(dict({'role': role, 'label': label, 'ext': ext, 'site_key': site_key,
                             'room': room, 'rack': rack, 'state': 'error' if caida else 'ok',
                             'why': 'why_site_offline' if caida else '',
                             'reason': caidas.get(site_key, '')}, **extra))
        for rack_uid, (rack, room) in racks.items():
            for pdu in s.pdus_of(rack_uid):
                item = s.items.get(pdu['item_uid']) if pdu.get('item_uid') else None
                primera.setdefault(str(pdu.get('source_uid') or ''), (room, rack))
                label = str((item or {}).get('label') or '').strip() or str(pdu.get('name'))
                fila('pdu', label, item['uid'] if item else f"dc_pdu:{pdu['uid']}", room, rack,
                     item=item, pdu=pdu)
        for src in s.sources_of(site):
            if str(src.get('kind') or '') != 'ups':
                continue
            item = s.items.get(src['item_uid']) if src.get('item_uid') else None
            feat = s.features.get(src['feature_uid']) if src.get('feature_uid') else None
            # Where it is: its item's rack or room, the room its drawing is in, or —a UPS the
            # inventory only knows as a source— the room of the first PDU it feeds.
            por_sala = {x['uid']: x for x in salas}
            rack, room = racks.get(str((item or {}).get('rack_uid') or ''), (None, None))
            room = (room or por_sala.get(str((item or {}).get('room_uid') or ''))
                    or por_sala.get(str((feat or {}).get('room_uid') or '')))
            if room is None:
                room, rack = primera.get(src['uid'], (salas[0] if salas else None, None))
            if room is None:
                continue
            fila('ups', str(src.get('name') or ''),
                 item['uid'] if item else f"dc_source:{src['uid']}", room, rack,
                 item=item, source=src, feature=feat)
    return out


def _draw(feed: dict) -> float:
    """What one cord draws, in watts: `DRAW` of what the inventory says, ±12 % per item."""
    said = float(feed.get('watts_said') or 0)
    return said * DRAW * (1 + ((_h(feed.get('uid'), 'draw') % 25) - 12) / 100.0)


def _power_specs(ctx, rows: list) -> dict:
    """``{device uid: (device profiles, agent description)}`` for the UPSs and PDUs.

    A PDU answers ENTITY-SENSOR-MIB: a sensor for the current and the power of each outlet
    something is plugged into (from its feeds), its inlet —or its three phases, on a strip of
    more than one phase's worth— and, on the A strip, the rack's temperature and humidity.
    A UPS answers UPS-MIB, its load being what the PDUs behind it draw (through the power
    chain, `dcim.service.chain_up`, bypasses included: a UPS on bypass still carries it).
    «SAI B», which the inventory declares on bypass, says so; the Texas one has tired
    batteries (`TIRED_UPS`); South Africa answers nothing."""
    from lib.core.dcim import service as dcim_svc           # noqa: PLC0415
    from lib.core.dcim.catalog import CatalogStore          # noqa: PLC0415
    s = ctx.store
    cat = CatalogStore(ctx.db)
    ahora = time.time()
    fuentes = s.sources_of()
    # What each PDU draws, and from which UPSs.
    por_pdu, de_ups = {}, {}
    for r in rows:
        if r['role'] != 'pdu':
            continue
        feeds = s.feeds_of([r['pdu']['uid']])
        por_pdu[r['pdu']['uid']] = feeds
        total = sum(_draw(f) for f in feeds)
        for src in dcim_svc.chain_up(fuentes, r['pdu'].get('source_uid'), honour_bypass=False):
            if str(src.get('kind') or '') == 'ups':
                de_ups[src['uid']] = de_ups.get(src['uid'], 0.0) + total
    out = {}
    for r in rows:
        if not r.get('device'):
            continue
        volts, hz = _MAINS.get(r['site_key'], (230, 50))
        uid = r['ext']
        modelo = (cat.get(str((r.get('item') or {}).get('type_uid') or '')) or {}).get('model')
        rack = r.get('rack') or {}
        lugar = ' › '.join(x for x in (r['room'].get('name'), str(rack.get('name') or '')) if x)
        spec = {'source': SOURCE, 'name': r['name'],
                'objectid': f"1.3.6.1.4.1.32473.1.{_OBJECT_ID[r['role']]}",
                'contact': 'NOC Demo <noc@demo.example>', 'location': lugar,
                'boot': float(int(ahora // 86400) * 86400 - 86400 * (20 + _h(uid, 'boot') % 300)),
                'ip': str(r.get('address') or ''), 'mask': '255.255.255.0',
                'gateway': '.'.join(str(r.get('address') or '').split('.')[:3] + ['1'])
                if str(r.get('address') or '').count('.') == 3 else '',
                'ifs': [{'name': 'eth0', 'speed': 100_000_000, 'mac': _mac(uid, 'eth0'),
                         'admin': 1, 'oper': 1, 'rate_in': 900.0, 'rate_out': 1400.0,
                         'alias': 'NMC'}],
                'silent': r['why'] == 'why_site_offline'}
        if r['role'] == 'pdu':
            pdu = r['pdu']
            firmware = 'DM-PDU 2.6.3'
            modelo = modelo or f"Metered PDU {int(pdu.get('outlets') or 0)} × C13"
            spec['sensors'] = _pdu_sensors(pdu, por_pdu.get(pdu['uid']) or [], volts, hz)
        else:
            src = r['source']
            cap = float(src.get('capacity_w') or 1000)
            firmware = 'DM-UPS 3.1.4'
            modelo = modelo or f"Online UPS {cap / 1000:g} kW"
            ups = {'manufacturer': 'Demo', 'model': modelo, 'firmware': firmware,
                   'agent': 'DM-NMC 2.4.1', 'name': r['name'],
                   'attached': ', '.join(sorted(x['name'] for x in rows
                                                if x['role'] == 'pdu' and x.get('pdu')
                                                and src['uid'] in {
                                                    f['uid'] for f in dcim_svc.chain_up(
                                                        fuentes, x['pdu'].get('source_uid'),
                                                        honour_bypass=False)}))[:240],
                   'rated_w': cap, 'rated_va': cap / 0.9, 'lines': 3 if cap >= 10000 else 1,
                   'volts': volts, 'hz': hz, 'load_w': round(de_ups.get(src['uid'], 0.0)),
                   'autonomy_min': float(src.get('autonomy_min') or 15),
                   'battery_v': 480 if cap >= 40000 else 240 if cap >= 10000
                   else 96 if cap >= 3000 else 48,
                   'temp': 24 + _h(uid, 'temp') % 4, 'input_bads': _h(uid, 'bads') % 4,
                   'source': 'normal', 'battery': 'normal', 'alarms': []}
            if int(src.get('bypass') or 0):
                ups.update({'source': 'bypass', 'alarms': [9],
                            'since': _since_of(src.get('bypass_at'), ahora - 86400)})
            if r['site_key'] == TIRED_UPS['site_key']:
                ups.update({'battery': 'low', 'runtime_min': TIRED_UPS['runtime_min'],
                            'alarms': list(TIRED_UPS['alarms']),
                            'since': ahora - TIRED_UPS['since_h'] * 3600})
                r['scenario'] = 'tired'
            elif ups['source'] == 'bypass':
                r['scenario'] = 'bypass'
            spec['ups'] = ups
        spec['descr'] = f"Demo {modelo}, {firmware}"
        spec['entity'] = {'descr': modelo, 'name': 'Chassis',
                          'serial': str((r.get('item') or {}).get('serial') or '')
                          or 'DM%010d' % (_h(uid) % 10**10),
                          'model': modelo, 'vendor': 'Demo', 'firmware': firmware}
        out[r['device']] = (list(_SNMP_PROFILES[r['role']]), spec)
    return out


def _since_of(stamp, default: float) -> float:
    """An inventory date (``2026-10-01T08:00:00``) as a moment, or *default*."""
    try:
        from datetime import datetime, timezone              # noqa: PLC0415
        return datetime.fromisoformat(str(stamp)).replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return default


def _pdu_sensors(pdu: dict, feeds: list, volts: float, hz: float) -> list:
    """The ENTITY-SENSOR-MIB sensors of one metered PDU, from what is plugged into it."""
    por_toma: dict = {}
    for f in feeds:
        n = int(f.get('outlet') or 0)
        if n:
            por_toma[n] = por_toma.get(n, 0.0) + _draw(f)
    total = sum(por_toma.values())
    pf = 0.97
    out = []
    if float(pdu.get('capacity_w') or 0) > 7400:
        # A three-phase strip: its outlets alternate L1, L2, L3, as they are wired.
        for k in range(3):
            fase = sum(w for n, w in por_toma.items() if (n - 1) % 3 == k)
            out += [{'name': f'Phase L{k + 1} voltage', 'type': 3, 'precision': 1,
                     'value': volts},
                    {'name': f'Phase L{k + 1} current', 'type': 5, 'precision': 2,
                     'value': fase / volts / pf}]
    else:
        out += [{'name': 'Inlet voltage', 'type': 3, 'precision': 1, 'value': volts},
                {'name': 'Inlet current', 'type': 5, 'precision': 2,
                 'value': total / volts / pf}]
    out += [{'name': 'Inlet frequency', 'type': 7, 'precision': 1, 'value': hz},
            {'name': 'Inlet power', 'type': 6, 'precision': 0, 'value': total}]
    for n in sorted(por_toma):
        out += [{'name': f'Outlet {n} current', 'type': 5, 'precision': 2,
                 'value': por_toma[n] / volts / pf},
                {'name': f'Outlet {n} power', 'type': 6, 'precision': 0, 'value': por_toma[n]}]
    if str(pdu.get('feed') or '') == 'a':
        semilla = _h(pdu.get('uid'), 'env')
        out += [{'name': 'Rack temperature', 'type': 8, 'precision': 1,
                 'value': 23.5 + (semilla % 30) / 10.0},
                {'name': 'Rack humidity', 'type': 9, 'precision': 0,
                 'value': 42 + semilla % 9}]
    return out


def _bind_power(ctx, r: dict, uid: str, actor: str) -> None:
    """The power row and its item, bound to the device that answers for them."""
    s = ctx.store
    for table, row in ((s.items, r.get('item')), (s.pdus, r.get('pdu')),
                       (s.sources, r.get('source')), (s.features, r.get('feature'))):
        if row and str(row.get('device_uid') or '') != uid:
            table.update(row['uid'], {'device_uid': uid}, actor=actor)


# ── What each device says over SNMP ──────────────────────────────────────────────────────────

#: Who speaks SNMP, with which of the panel's device profiles: the same an installation would
#: assign to a real one of the kind.
_SNMP_PROFILES = {'server': ['grp_linux', 'entity_physical'],
                  'switch': ['grp_network', 'entity_physical'],
                  'router': ['grp_network', 'entity_physical'],
                  'firewall': ['grp_network', 'entity_physical'],
                  'storage': ['grp_network', 'entity_physical'],
                  'kvm': ['sys_generic', 'if_generic', 'entity_physical'],
                  'console': ['sys_generic', 'if_generic', 'entity_physical'],
                  'ap': ['sys_generic', 'if_generic', 'lldp', 'entity_physical'],
                  'camera': ['sys_generic', 'if_generic', 'entity_physical'],
                  'printer': ['sys_generic', 'if_generic', 'entity_physical'],
                  # The power: through the standard MIBs, no maker's (see `_power_specs`).
                  'ups': ['sys_generic', 'if_generic', 'entity_physical', 'ups_mib'],
                  'pdu': ['sys_generic', 'if_generic', 'entity_physical', 'entity_sensor']}
#: The firmware each kind of the demo's equipment runs (the demo's own platforms).
_FIRMWARE = {'switch': 'DM-NOS 7.4', 'router': 'DM-RTOS 17.9', 'firewall': 'DM-SecOS 7.2',
             'storage': 'DM-SAN OS 6.1', 'console': 'DM-Console OS 5.2',
             'kvm': 'DM-Console OS 5.2', 'ap': 'DM-NOS 7.4', 'camera': 'DM-RTOS 17.9',
             'printer': 'DM-RTOS 17.9'}
#: sysObjectID of the fictitious makers: under 32473, the enterprise number IANA reserves for
#: documentation (RFC 5612). A Linux server answers net-snmp's own (8072), as a real one does.
_OBJECT_ID = {'switch': 1, 'router': 2, 'firewall': 3, 'storage': 4, 'console': 5, 'kvm': 6,
              'ap': 7, 'camera': 8, 'printer': 9, 'ups': 10, 'pdu': 11}
_LINUX_OID = '1.3.6.1.4.1.8072.3.2.10'
#: The uplink the demo says CORE-2 lost (`why_uplink_down`).
UPLINK_PORT = 'Te1/1/2'
_SPEED = (('400g', 400), ('100g', 100), ('40g', 40), ('25g', 25), ('10g', 10), ('2.5g', 2.5),
          ('1000base', 1), ('100base', 0.1))


def _h(*parts) -> int:
    return int(uuid.uuid5(_NS, '|'.join(str(p) for p in parts)).hex[:12], 16)


def _mac(*parts) -> str:
    """A locally administered MAC (02:…), stable for the same thing."""
    n = _h('mac', *parts)
    octs = [0x02] + [(n >> (8 * i)) & 0xFF for i in range(5)]
    return ':'.join('%02x' % o for o in octs)


def _speed(kind) -> int:
    kind = str(kind or '').lower()
    for tag, gbit in _SPEED:
        if tag in kind:
            return int(gbit * 1_000_000_000)
    return 1_000_000_000


def _descr(r: dict, m: dict) -> str:
    if r['role'] == 'server':
        return (f"Linux {r['name']} 6.1.0-25-amd64 #1 SMP PREEMPT_DYNAMIC Debian "
                f"6.1.106-3 (2024-08-26) x86_64")
    return f"Demo {m.get('model') or r['role']}, {_FIRMWARE.get(r['role'], 'DM-NOS 7.4')}"


def _snmp_specs(ctx, rows: list) -> dict:
    """``{device uid: (device profiles, agent description)}`` for every device that speaks
    SNMP: its identity from the inventory (name, model, serial, firmware, where it is), its
    interfaces from its model's ports with their state and traffic from the cabling, its LLDP
    neighbours from where each cable really ends (through the patch panels, `dcim.trace`), and
    the incidents the demo tells: the uplink of CORE-2 down, CRC errors on SW-P2-2, the IPsec
    tunnel of the recovery centre down, South Africa and srv-a01-03 answering nothing."""
    from lib.core.dcim import service as dcim_svc           # noqa: PLC0415
    from lib.core.dcim.catalog import CatalogStore          # noqa: PLC0415
    from lib.core.dcim.store import PASS_THROUGH            # noqa: PLC0415
    s = ctx.store
    cat = CatalogStore(ctx.db)
    by_item = {r['item']['uid']: r for r in rows if r['role'] in _SNMP_PROFILES}
    sitios = {v: (s.sites.get(v) or {})
              for v in ((ctx.created or {}).get('sites') or {}).values() if v}
    modelos: dict = {}
    ahora = time.time()

    def model(it):
        tu = str(it.get('type_uid') or '')
        if tu not in modelos:
            modelos[tu] = (cat.get(tu) or {}) if tu else {}
        return modelos[tu]

    # Where each data cable of each device really ends.
    vecinos: dict = {}
    for uid in by_item:
        for path in dcim_svc.trace(s, uid):
            if len(path) < 2 or (path[1].get('cable') or {}).get('kind') == 'power':
                continue
            fin = path[-1]
            if fin.get('hidden') or fin.get('role') in PASS_THROUGH or not fin.get('item'):
                continue
            vecinos.setdefault(uid, {})[path[0]['port']] = (fin['item'], fin.get('port') or '')

    # A link that is down is down at both of its ends: the uplink CORE-2 lost (`_WHY`), and
    # the network of a server that stopped answering ping —its BMC still answers, and says the
    # NIC lost its link—.
    caidos = set()
    for uid, r in by_item.items():
        if r['why'] == 'why_ping':
            for puerto, far in vecinos.get(uid, {}).items():
                caidos.update({(uid, puerto), far})
        if r['why'] == 'why_uplink_down':
            # The port the demo names, when its cabling has it; else the cable to the other
            # core, which is the uplink the reason talks about.
            mios = vecinos.get(uid, {})
            puerto = UPLINK_PORT if UPLINK_PORT in mios else next(
                (p for p, (far, _fp) in sorted(mios.items())
                 if str((by_item.get(far) or {}).get('label') or '').startswith('CORE-')), '')
            if puerto:
                caidos.add((uid, puerto))
                caidos.add(mios[puerto])
                r['uplink_down'] = puerto

    out = {}
    for uid, r in by_item.items():
        it, role, why = r['item'], r['role'], r['why']
        m = model(it)
        rack = r['rack'] or {}
        sitio = sitios.get(r['room'].get('site_uid')) or {}
        lugar = ' › '.join(x for x in (str(sitio.get('name') or ''), r['room']['name'],
                                        str(rack.get('name') or '')) if x)
        if it.get('u_start'):
            lugar += f" U{it['u_start']}"
        puertos = [p for p in ((m.get('port_list') or {}).get('interfaces') or [])
                   if isinstance(p, dict) and p.get('name')]
        if not puertos:
            puertos = [{'name': 'eth0', 'type': '1000base-t'}]
        mios = vecinos.get(uid, {})
        # The interfaces that are in use: the cabled ones. A real agent
        # reports every port of the chassis; the demo's leave the empty ones out, because each
        # one is a row of every sample of every cycle for three hundred devices, and an empty
        # port's row says nothing a chart would show.
        en_uso = [p for p in puertos if str(p['name']) in mios]
        puertos = en_uso or puertos[:1]
        ifs, lldp = [], []
        for n, p in enumerate(puertos, start=1):
            name = str(p['name'])
            far = mios.get(name)
            f = {'name': name, 'speed': _speed(p.get('type')), 'mac': _mac(uid, name),
                 'admin': 1, 'oper': 1 if far else 2}
            if far:
                lejos = by_item.get(far[0])
                troncal = lejos is not None and lejos['role'] in (
                    'switch', 'router', 'firewall', 'storage')
                base = (2.5e7 if troncal else 1.5e6) * (1 + (_h(uid, name) % 70) / 100)
                f.update({'rate_in': base, 'rate_out': base * 0.6,
                          'alias': (lejos['name'] if lejos else str(far[0]))[:64]})
                if lejos is not None:
                    lldp.append({'local': n, 'sysname': lejos['name'], 'port': far[1],
                                 'port_desc': far[1], 'chassis': _mac(far[0], 'chassis'),
                                 'sysdesc': _descr(lejos, model(lejos['item']))})
            if (uid, name) in caidos:
                f.update({'oper': 2, 'rate_in': 0, 'rate_out': 0})
                lldp = [x for x in lldp if x['local'] != n]
            if why == 'why_port_errors' and name == 'Gi1/0/17':
                f['err_ratio'] = 0.032
            ifs.append(f)
        if role == 'firewall':
            # The tunnel to the recovery centre, down at both of its ends.
            caido = why == 'why_ipsec_down' or (r['site_key'] == 'site'
                                                and r['label'] == 'FW-2')
            ifs.append({'name': 'ipsec0', 'type': 131, 'speed': 300_000_000, 'mac': '',
                        'admin': 1, 'oper': 2 if caido else 1,
                        'rate_in': 0 if caido else 4e6, 'rate_out': 0 if caido else 3e6,
                        'alias': 'IPsec Demo - DR'})
        addr = str(r.get('address') or '')
        spec = {'source': SOURCE, 'name': r['name'], 'descr': _descr(r, m),
                'objectid': _LINUX_OID if role == 'server'
                else f"1.3.6.1.4.1.32473.1.{_OBJECT_ID.get(role, 99)}",
                'contact': 'NOC Demo <noc@demo.example>', 'location': lugar,
                'boot': float(int(ahora // 86400) * 86400 - 86400 * (3 + _h(uid, 'boot') % 160)),
                'ip': addr, 'mask': '255.255.255.0',
                'gateway': '.'.join(addr.split('.')[:3] + ['1']) if addr.count('.') == 3 else '',
                'forwarding': role in ('router', 'firewall'),
                'chassis': _mac(uid, 'chassis'), 'ifs': ifs, 'lldp': lldp,
                'entity': {'descr': m.get('model') or role, 'name': 'Chassis',
                           'serial': str(it.get('serial') or '') or 'DM%010d' % (_h(uid) % 10**10),
                           'model': m.get('model') or '', 'vendor': 'Demo',
                           'firmware': 'Debian 12' if role == 'server'
                           else _FIRMWARE.get(role, 'DM-NOS 7.4')},
                # Only a site with no link at all says nothing: everything else in trouble still
                # answers, and says what is wrong with it.
                'silent': why == 'why_site_offline'}
        if role == 'server':
            gpu = r['label'].startswith('gpu-')
            semilla = sum(ord(c) for c in r['label'])
            temps = [{'name': 'Package id 0', 'c': 46 + semilla % 9},
                     {'name': 'Package id 1', 'c': 44 + semilla % 8}]
            if gpu:
                temps += [{'name': f'GPU {g}',
                           'c': 88 if (why == 'why_gpu_temp' and g == 5) else 61 + (semilla + g) % 9}
                          for g in range(8)]
            spec['host'] = {'cores': 64 if gpu else 32, 'cpu': 18 + semilla % 37,
                            'mem_kb': (1024 if gpu else 512) * 1024 * 1024,
                            'mem_used': (42 + semilla % 23) / 100.0,
                            'storage': [{'descr': '/', 'kb': 480 * 1024 * 1024,
                                         'used': (31 + semilla % 41) / 100.0}],
                            'temps': temps,
                            'fans': [{'name': f'Fan {k}', 'rpm': 7200 + 40 * k}
                                     for k in range(1, 7)]}
        out[r['device']] = (list(_SNMP_PROFILES[role]), spec)
    return out


def _syslog(surf):
    store = getattr(surf.app, '_syslog_store', None) if surf.app is not None else None
    if store is None or getattr(store, 'read_only', False):
        return None
    return store


def _log_lines(rows: list) -> list:
    """What the devices of the demo have logged: the incidents it tells, as the device that
    saw each one would have written it, and a little of the ordinary noise of a fleet. Each
    line from the device's address, so its Logs tab finds it; each with the simulated MSGID."""
    ahora = time.time()
    out = []

    def line(r, hace_h, sev, app, msg):
        out.append({'ts': ahora - hace_h * 3600, 'facility': 23, 'severity': sev,
                    'hostname': r['name'], 'source': str(r.get('address') or ''),
                    'app': app, 'procid': '', 'msgid': simulated.SYSLOG_MSGID,
                    'message': msg, 'raw': msg})
    for r in rows:
        why, since = r['why'], _SINCE.get(r['why'], 3.0)
        if why == 'why_uplink_down':
            puerto = r.get('uplink_down') or UPLINK_PORT
            line(r, since, 3, 'IFMGR', f'%LINK-3-UPDOWN: Interface {puerto}, changed state to down')
            line(r, since - 0.01, 4, 'LLDP', f'LLDP neighbour CORE-1 on {puerto} aged out')
        elif why == 'why_port_errors':
            line(r, 1.5, 4, 'IFMGR', '%ETH-4-CRC: Gi1/0/17 input CRC errors above 3% (FCS)')
        elif why == 'why_ipsec_down':
            line(r, since, 3, 'ike', 'IKEv2 SA to Demo deleted: DPD timeout (3 retries)')
            line(r, since - 0.02, 3, 'ike', 'IPsec tunnel ipsec0 down; retrying in 60 s')
        elif why == 'why_ha_sync':
            line(r, since, 4, 'ha', 'HA: session sync to peer stalled for 360 s')
        elif why in ('why_psu_one', 'why_psu_both'):
            line(r, since, 2 if why == 'why_psu_both' else 4, 'envmon',
                 'PSU2 input lost' if why == 'why_psu_one' else 'PSU1 and PSU2 input lost')
        elif why == 'why_gpu_temp':
            line(r, since, 4, 'kernel', 'nvidia: GPU 5 temperature 88 C above slowdown 85 C')
        elif why == 'why_gpu_xid':
            line(r, since, 3, 'kernel', 'NVRM: Xid (PCI:0000:3b:00): 79, GPU has fallen off the bus')
        elif why == 'why_ecc':
            line(r, since, 4, 'kernel', 'EDAC MC1: 112 CE memory read error on DIMM_B2')
        elif why == 'why_disk_smart':
            line(r, since, 4, 'smartd', 'Device: /dev/sdb [SAT], 24 Currently unreadable (pending) sectors')
        elif why == 'why_raid_failed':
            line(r, since, 2, 'mdadm', 'Fail event detected on md device /dev/md0, component device /dev/sdc1')
        elif why == 'why_nvr_disk':
            line(r, since, 4, 'nvrd', 'Recording volume: disk 3 reports reallocated sectors')
        elif why == 'why_ping':
            line(r, since, 3, 'kernel', 'ixgbe 0000:3b:00.0 eth0: NIC Link is Down')
            line(r, since - 0.001, 2, 'kernel', 'bond0: now running without any active interface!')
        elif why == 'why_sdwan_latency':
            line(r, since, 4, 'sdwan', 'Path internet-1 latency 380 ms above SLA 150 ms')
        if r['label'] == INCIDENT['label']:
            line(r, INCIDENT['from_h'], 3, 'IFMGR', '%LINK-3-UPDOWN: Interface Gi0/0, changed state to down')
            line(r, INCIDENT['to_h'], 5, 'IFMGR', '%LINK-3-UPDOWN: Interface Gi0/0, changed state to up')
        if r['role'] in ('switch', 'router', 'firewall') and r['site_key'] != 'site_za':
            line(r, 6.0, 6, 'sshd', 'Accepted publickey for netops from 192.0.2.250 port 51234 ssh2')
            line(r, 0.5, 6, 'ntpd', 'synchronized to 192.0.2.123, stratum 2')
        if r['role'] == 'server' and r['label'].startswith('srv-s'):
            line(r, 2.0, 6, 'CRON', '(root) CMD (/usr/lib/sysstat/debian-sa1 1 1)')
        if r.get('scenario') == 'bypass':
            line(r, 26.0, 4, 'ups', 'Transfer to bypass: maintenance bypass switch closed')
        elif r.get('scenario') == 'tired':
            line(r, TIRED_UPS['since_h'], 4, 'ups',
                 f"Battery self-test: runtime {TIRED_UPS['runtime_min']} min below the "
                 f"configured minimum; replace the battery")
            line(r, TIRED_UPS['since_h'] - 0.01, 4, 'ups', 'Alarm: battery low (on mains)')
    return out


def _write_logs(surf, rows: list) -> int:
    store = _syslog(surf)
    if store is None:
        return 0
    try:
        hay = store._db.fetchone('SELECT COUNT(*) FROM SystemEvents WHERE MsgID = ?',  # noqa: SLF001
                                 (simulated.SYSLOG_MSGID,))
        if hay and int(hay[0] or 0):
            return 0                                    # written by an earlier install
        lineas = sorted(_log_lines(rows), key=lambda x: x['ts'])
        return store.add_many(lineas) if lineas else 0
    except Exception:                                   # pylint: disable=broad-except
        return 0


def _remove_logs(surf) -> int:
    store = _syslog(surf)
    if store is None:
        return 0
    try:
        n = store._db.execute('DELETE FROM SystemEvents WHERE MsgID = ?',   # noqa: SLF001
                              (simulated.SYSLOG_MSGID,))
        store._db.commit()                                                  # noqa: SLF001
        return int(n or 0)
    except Exception:                                   # pylint: disable=broad-except
        return 0


def install(ctx, progress=None) -> dict:
    """Register, bind, configure and answer the demo's equipment (see the module doc).
    Idempotent: what exists already is reused, never duplicated. Returns what it wrote."""
    progress = progress or (lambda *_a, **_k: None)
    if getattr(ctx, 'app', None) is None:
        # Without the panel there is no monitor to answer the checks, no notifier to keep the
        # alerts in, and no key to encrypt the placeholders with: the inventory keeps the
        # states it painted itself (`dc_item.demo_state`). See `docs/ref-cli.md`.
        return {'skipped': 'no panel'}
    surf = _Surface(ctx)
    w = dict(texts(ctx.lang))
    actor = str(getattr(ctx, 'actor', '') or SOURCE)
    rows = _painted(ctx)
    for r in rows:
        r['ext'] = r['item']['uid']
    # …and the power that feeds them: every UPS and metered PDU, a device of its own.
    power = _power_rows(ctx, rows)
    rows += power
    _names(rows)

    # 1. The devices, their class, profiles and credentials, and the binding.
    progress('monitor_devices', 0, len(rows))
    creds = _credentials(surf, w, actor)
    types = _types(surf)
    ya = _demo_devices(surf)
    addr = _Addresses()
    hechos = 0
    saltados: list = []
    for n, r in enumerate(rows):
        direccion = addr.take(_pool(r))
        dev = ya.get(r['ext'])
        if dev is None:
            uid = surf.devices.create(_device_record(r, w, creds, types, direccion), actor=actor)
            if not uid:
                # A real device already has this name: the demo's carries its tag.
                rec = _device_record(r, w, creds, types, direccion)
                rec['name'] = f"{r['name']} [demo]"
                uid = surf.devices.create(rec, actor=actor)
                if uid:
                    r['name'] = rec['name']
            if not uid:
                # Not created: counted and said (in the result, and the step does not reach its
                # total), never reported as done.
                saltados.append(r['name'])
                continue
            hechos += 1
        else:
            uid = dev['uid']
            # The name it has in the registry is the one it says (sysName) and is checked by.
            r['name'] = str(dev.get('name') or r['name'])
        r['device'] = uid
        r['address'] = (dev or {}).get('address') or direccion
        if r['role'] in ('ups', 'pdu'):
            _bind_power(ctx, r, uid, actor)
        elif str(r['item'].get('device_uid') or '') != uid:
            ctx.store.items.update(r['item']['uid'], {'device_uid': uid}, actor=actor)
        if (n + 1) % 25 == 0:
            progress('monitor_devices', n + 1 - len(saltados), len(rows))
    # The end of the step, always: a tick every 25 left it showing the last multiple (350/356).
    progress('monitor_devices', len(rows) - len(saltados), len(rows))
    if saltados:
        try:
            from lib.core.object_base import ObjectBase      # noqa: PLC0415
            ObjectBase.debug.print(f'> Demo >> {len(saltados)} device(s) not created: '
                                   f'{", ".join(saltados[:10])}')
        except Exception:                                   # pylint: disable=broad-except
            pass
    rows = [r for r in rows if r.get('device')]
    power = [r for r in power if r.get('device')]
    painted = [r for r in rows if r['role'] not in ('ups', 'pdu')]
    # What each one says over SNMP, now that every device —every neighbour— has its name.
    specs = dict(_snmp_specs(ctx, painted))
    specs.update(_power_specs(ctx, power))
    for dev_uid, (perfiles, spec) in specs.items():
        dev = surf.devices.get(dev_uid, decrypt=True)
        if dev is None:
            continue
        snmp = dict((dev.get('profiles') or {}).get('snmp') or {})
        quiere = dict(snmp, device_profiles=perfiles, simulated=spec)
        if snmp != quiere:
            dev['profiles'] = dict(dev.get('profiles') or {}, snmp=quiere)
            surf.devices.update(dev_uid, dev, actor=actor)

    # 2. The checks and the clusters, as they will be written.
    m = _messages(ctx.lang)
    nuevos: dict = {}                      # {module: {collection: {uid: item}}}
    por_disp: dict = {}
    for r in rows:
        for mod, (coll, fields, results) in _plan(r, m, w).items():
            uid, item = _check_item(r, mod, fields, results)
            nuevos.setdefault(mod, {}).setdefault(coll, {})[uid] = item
            por_disp.setdefault(r['device'], set()).add(mod)
    for uid, item in _clusters(rows, m, w).items():
        nuevos.setdefault(item.pop('__module__'), {}).setdefault('list', {})[uid] = item

    # 3. The days before: what a chart of these devices shows when it is opened. BEFORE the
    # checks reach the configuration: once they are there the scheduler answers them, and a
    # series it has started is one the past can no longer be written under (it would become
    # the series' «last»).
    escritas = _backfill(surf, rows, nuevos, progress)

    # 4. The checks, in ONE write of the module configuration.
    progress('monitor_checks', 0, len(rows))

    def _write(modules) -> int:
        cambios = 0
        for mod, colls in nuevos.items():
            entry = modules.get(mod)
            if not isinstance(entry, dict):
                # Not added here yet: added for the demo, and said so, so removing the demo
                # takes the entry away and the module is «not added» again. Never `enabled`
                # written: an entry the installation disabled stays disabled.
                entry = modules[mod] = {MODULE_MARK: True}
            for coll, items in colls.items():
                coleccion = entry.setdefault(coll, {})
                for uid, item in items.items():
                    if _unstamped(coleccion.get(uid)) != item:
                        coleccion[uid] = copy.deepcopy(item)
                        cambios += 1
        return cambios
    cambios = surf.mutate_modules(_write) or 0
    # The modules each device is watched by, as its record says (the Infrastructure column).
    for r in rows:
        mods = sorted(por_disp.get(r['device'], ()))
        dev = surf.devices.get(r['device'], decrypt=True)
        if dev is not None and sorted(dev.get('modules') or []) != mods:
            dev['modules'] = mods
            surf.devices.update(r['device'], dev, actor=actor)
    progress('monitor_checks', len(rows), len(rows))

    # 5. The results of now, through the monitor's own processing, and what was logged.
    progress('monitor_results', 0, 1)
    _first_results(ctx, surf, surf.modules())
    lineas = _write_logs(surf, rows)
    progress('monitor_results', 1, 1)
    return {'devices': hechos, 'checks': cambios, 'samples': escritas, 'logs': lineas,
            'credentials': len(creds), 'not_created': saltados}


#: What the module store stamps on an item it saved: not the item's content.
_STAMPS = ('created_at', 'updated_at', 'updated_by', 'created_by')


def _unstamped(item):
    """*item* as this part wrote it: without the stamps the store adds. Read back after a
    restart, every item carries them, and comparing with them rewrote every check of the demo
    on a second install."""
    if not isinstance(item, dict):
        return item
    return {k: v for k, v in item.items() if k not in _STAMPS}


def _clusters(rows: list, m: dict, w: dict) -> dict:
    """The three clusters: ``{uid: item}`` with the module they belong to in ``__module__``."""
    by_label = {r['label']: r for r in rows if r['site_key'] == 'site'}
    out = {}

    def _ka(key, labels, vip):
        miembros = [by_label[x] for x in labels if x in by_label]
        if len(miembros) < 2:
            return
        nombre = w[key]
        res = [_res('ok', _fmt(m['keepalived'].get('ka_vip_active'), nombre, vip,
                               miembros[0]['name']), suffix='/vip')]
        for i, mb in enumerate(miembros):
            res.append(_res('ok', _fmt(m['keepalived'].get('ka_node_ok'), nombre, mb['name'],
                                       w['state_master'] if i == 0 else w['state_backup'],
                                       w['running'], ''), suffix=f"/node/{mb['label']}"))
        uid = _check_uid(miembros[0]['item']['uid'], 'keepalived', key)
        out[uid] = {'__module__': 'keepalived', 'uid': uid, 'enabled': True, 'label': nombre,
                    'description': w['cluster_desc'], 'vip': vip,
                    'device_uids': [mb['device'] for mb in miembros],
                    'check_service': True, 'check_vip': True, 'check_priority': False,
                    simulated.SIM_KEY: _scenario(res)}
    _ka('cluster_fw', ('FW-1', 'FW-2'), '192.0.2.1')
    _ka('cluster_core', ('CORE-1', 'CORE-2'), '192.0.2.2')

    nodos = [r for r in rows if r['site_key'] == 'site' and r['label'].startswith('srv-s')]
    if len(nodos) >= 2:
        nombre = w['cluster_pve']
        res = [_res('ok', _fmt(m['proxmox'].get('px_cluster'), nombre, '🟢', nombre,
                               m['proxmox'].get('px_quorum_ok', 'OK'), len(nodos), len(nodos)))]
        res += [_res('ok', _fmt(m['proxmox'].get('px_node_online'), nombre, n['name'], ''),
                     suffix=f"/node/{n['label']}") for n in nodos]
        uid = _check_uid(nodos[0]['item']['uid'], 'proxmox', 'cluster')
        out[uid] = {'__module__': 'proxmox', 'uid': uid, 'enabled': True, 'label': nombre,
                    'description': w['cluster_desc'], 'port': 8006,
                    'device_uids': [n['device'] for n in nodos],
                    simulated.SIM_KEY: _scenario(res)}
    return out


def _demo_items(modules: dict):
    """Every check of the demo in *modules*: ``(module, collection, key, item)``."""
    for mod, entry in (modules or {}).items():
        if not isinstance(entry, dict):
            continue
        for coll, items in entry.items():
            if str(coll).startswith('__') or not isinstance(items, dict):
                continue
            for key, item in items.items():
                if simulated.is_simulated(item) and \
                        str(item[simulated.SIM_KEY].get('source') or '') == SOURCE:
                    yield mod, coll, key, item


def _backfill(surf: _Surface, rows: list, modules: dict, progress) -> int:
    """Two days of readings, one an hour, for the devices somebody opens a chart of: all but
    the hundreds of compute nodes of the main site, which start their history with the demo.
    Written only for a series that has none yet, so installing again adds nothing."""
    hist = surf.history
    if hist is None:
        return 0
    lejos = {r['device'] for r in rows
             if not (r['site_key'] == 'site' and r['role'] == 'server'
                     and not r['label'].startswith('srv-s'))}
    incidente = {r['device'] for r in rows if r['label'] == INCIDENT['label']}
    trabajo = [(mod, key, item) for mod, _c, key, item in _demo_items(modules)
               if str(item.get('device_uid') or '') in lejos or item.get('device_uids')]
    ahora = time.time()
    escritas = 0
    for n, (mod, key, item) in enumerate(trabajo):
        for res in item[simulated.SIM_KEY]['results']:
            rkey = f"{key}{res.get('suffix') or ''}"
            if hist._find_series(mod, rkey) is not None:        # noqa: SLF001
                continue
            malo = str(res.get('status') or 'ok') != 'ok'
            desde = float(res.get('since_h') or 0)
            for h in range(HISTORY_HOURS, 0, -1):
                ts = ahora - h * 3600
                ok = not (malo and h <= desde)
                if item.get('device_uid') in incidente and mod == 'ping' \
                        and INCIDENT['to_h'] < h <= INCIDENT['from_h']:
                    ok = False
                datos = {} if not ok and mod == 'ping' else {
                    k: v for k, v in ((k, simulated.metric(rkey, k, spec, ts))
                                      for k, spec in (res.get('metrics') or {}).items())
                    if v is not None}
                datos[simulated.MARK] = SOURCE
                hist.record(mod, rkey, ok, datos, item_uid=key, ts=ts)
                escritas += 1
        if (n + 1) % 20 == 0:
            progress('monitor_history', n + 1, len(trabajo))
    progress('monitor_history', len(trabajo), len(trabajo))
    return escritas


def _first_results(ctx, surf: _Surface, modules: dict) -> None:
    """The results of now. From the panel, through a monitor —the same processing a cycle
    applies: state rows, a history sample, and the alerts of what is down, which the notifier
    keeps from every channel—. From the command line, straight to the state table (no monitor
    to run, no alert to raise); the first cycle of the scheduler carries on from there."""
    from lib.modules import ReturnModuleCheck                     # noqa: PLC0415
    mods = sorted({mod for mod, _c, _k, _i in _demo_items(modules)})
    monitor = _monitor(ctx.app) if ctx.app is not None else None
    if monitor is None:
        for mod in mods:
            for r in simulated.results(modules.get(mod) or {}):
                surf.state.set(mod, r['key'], r['status'], message=r['message'],
                               other_data=r['other_data'], severity=r['severity'],
                               item_uid=r['item_uid'])
        return
    try:
        monitor.status.read()
    except Exception:                                    # pylint: disable=broad-except
        pass
    sampled = _first_samples(monitor, surf)
    for mod in sorted(set(mods) | ({'snmp'} if sampled.list else set())):
        rd = ReturnModuleCheck()
        simulated.merge_into(rd, monitor.config_modules.get_conf([mod]) or {})
        if mod == 'snmp':
            for key in sampled.list:
                rd.set(key, sampled.get_status(key), sampled.get_message(key), True,
                       sampled.get_other_data(key), sampled.get_severity(key) or None,
                       name=sampled.get_name(key))
        monitor._process_module_result(mod, rd, prune=False)     # noqa: SLF001
        save = getattr(monitor.status, 'save_module', None)
        if callable(save):
            save(mod)
        else:
            monitor.status.save()
        if surf.history is not None:
            for key in rd.list:
                surf.history.record(mod, key, rd.get_status(key), rd.get_other_data(key))
    notifier = getattr(monitor, '_notifier', None)
    if notifier is not None:
        notifier.flush(public_url='')


def _first_samples(monitor, surf: _Surface):
    """The first SNMP sweep of the demo's devices, by the SNMP module's own sampler —which
    answers them from their agent's description (`lib.core.snmp.simulated_agent`)—, so their
    identity, interfaces and neighbours are on screen before the scheduler's first cycle. The
    counters' rates come from the second sweep on, as on a real device."""
    from lib.core.snmp import simulated_agent                    # noqa: PLC0415
    from lib.core.snmp.devices import device_key                 # noqa: PLC0415
    from lib.modules import ReturnModuleCheck                    # noqa: PLC0415
    vacio = ReturnModuleCheck()
    demo = [d for d in surf.devices.list(decrypt=True)
            if str(d.get('source') or '') == SOURCE and simulated_agent.spec_of_device(d)]
    for d in demo:
        # This process answers them too: a test of a profile from the panel finds the agent.
        simulated_agent.bind(str(d.get('address') or ''), simulated_agent.spec_of_device(d))
    if not demo:
        return vacio
    try:
        watchful = monitor._import_watchful('snmp').Watchful(monitor)  # noqa: SLF001
    except Exception:                                    # pylint: disable=broad-except
        return vacio
    for d in demo:
        spec = simulated_agent.spec_of_device(d)
        addr = str(d.get('address') or '')
        if spec.get('silent'):
            # The offline site answered until it went offline: its first sweep is the one it
            # gave before, so its identity and its last readings are there, as they would be.
            simulated_agent.awake(addr, True)
        try:
            watchful._sample_item(device_key(d['uid']),                # noqa: SLF001
                                  {'device_uid': d['uid'], 'enabled': True,
                                   'label': d.get('name') or d['uid']})
        except Exception:                                # pylint: disable=broad-except
            pass
        finally:
            simulated_agent.awake(addr, False)
    return watchful.dict_return


def _monitor(app):
    """A monitor of the panel's, as the «run now» button builds one, with the cycle's notifier."""
    try:
        from lib import Monitor                                   # noqa: PLC0415
        from lib.core.notify.monitor_notifier import MonitorNotifier   # noqa: PLC0415
        mdir = getattr(app, '_modules_dir', '') or _WATCHFULS
        monitor = Monitor(os.path.dirname(mdir), app._config_dir, mdir, app._var_dir)  # noqa: SLF001
        # A command line has no channel to route through, and needs none: a demonstration's
        # alerts reach no channel anyway (`deliverable`), so its monitor has no notifier.
        monitor._notifier = (None if getattr(app, 'headless', False)     # noqa: SLF001
                             else MonitorNotifier(app))
        if getattr(monitor, '_check_state_store', None) is None:
            return None
        return monitor
    except Exception:                                           # pylint: disable=broad-except
        return None


# ── Remove ───────────────────────────────────────────────────────────────────────────────────

def remove(ctx, progress=None) -> dict:
    """Take away everything `install` wrote: the checks and clusters (and a module entry it
    created, once empty), their state and history, the devices with their binding and
    ownership, and the placeholder credentials. Idempotent; never touches what it did not
    write. *progress* is not called: the demo reports its own removal steps."""
    del progress
    if getattr(ctx, 'app', None) is None and not ctx.db.table_exists('devices'):
        # A database with no device registry (the inventory alone) has nothing of this
        # part, and building the stores to find that out would create their tables.
        return {'checks': 0, 'devices': 0, 'series': 0, 'credentials': 0}
    surf = _Surface(ctx)
    quitar: list = []

    def _strip(modules) -> int:
        for mod, coll, key, item in list(_demo_items(modules)):
            quitar.append((mod, key, item))
            del modules[mod][coll][key]
            if not modules[mod][coll]:
                # Emptied here: as it reads back from the database, with no collection.
                del modules[mod][coll]
        for mod in list(modules):
            entry = modules[mod]
            if isinstance(entry, dict) and entry.get(MODULE_MARK):
                vacio = all(not v for k, v in entry.items()
                            if not str(k).startswith('__') and isinstance(v, dict))
                if vacio and set(k for k in entry if not isinstance(entry[k], dict)) \
                        <= {MODULE_MARK}:
                    del modules[mod]
                    quitar.append((mod, None, None))
        return len(quitar)
    surf.mutate_modules(_strip)

    series = 0
    for mod, key, item in quitar:
        if key is None:
            continue
        try:
            surf.state.delete(mod, key)
        except Exception:                                   # pylint: disable=broad-except
            pass
        if surf.history is not None:
            claves = {f"{key}{r.get('suffix') or ''}"
                      for r in (item or {}).get(simulated.SIM_KEY, {}).get('results', [])}
            for rkey in claves - {key}:
                series += 1 if surf.history.delete_series(mod, rkey) else 0
            series += surf.history.delete_item(mod, key)[0]

    logs = _remove_logs(surf)
    disp = _demo_devices(surf)
    # What the SNMP sweep recorded of them: its state rows, its series and what it sighted.
    from lib.core.devices.resolve import device_result_key, device_uid_from_key  # noqa: PLC0415
    suyos = {dev['uid'] for dev in disp.values()}
    try:
        for mod, rows_ in (surf.state.as_status_dict() or {}).items():
            for key in list(rows_):
                if device_uid_from_key(key) in suyos:
                    surf.state.delete(mod, key)
                    surf.state.delete(mod, key.split('/')[0])
    except Exception:                                   # pylint: disable=broad-except
        pass
    for uid in suyos:
        if surf.history is not None:
            series += surf.history.delete_item('snmp', device_result_key(uid))[0]
        try:
            if ctx.db.table_exists('net_evidence'):
                ctx.db.execute('DELETE FROM net_evidence WHERE uid = ?', (uid,))
                ctx.db.commit()
        except Exception:                               # pylint: disable=broad-except
            pass
    # The power chain's rows bound to them (a PDU, a UPS that is only a source, the drawing of
    # one in its room), whatever item they stand for.
    for table in (ctx.store.pdus, ctx.store.sources, ctx.store.features):
        for row in table.list():
            if str(row.get('device_uid') or '') in suyos:
                table.update(row['uid'], {'device_uid': ''}, actor='')
    for item_uid, dev in disp.items():
        it = ctx.store.items.get(item_uid) if item_uid else None
        if it and str(it.get('device_uid') or '') == dev['uid']:
            ctx.store.items.update(item_uid, {'device_uid': ''}, actor='')
        if surf.orgs is not None:
            try:
                surf.orgs.forget_scope('device', dev['uid'])
            except Exception:                               # pylint: disable=broad-except
                pass
        surf.devices.delete(dev['uid'])

    descs = _every_text('cred_desc')
    creds = 0
    for nombre in CREDS:
        for candidato in _cred_names(nombre):
            fila = surf.creds.get_by_name(candidato, decrypt=False)
            if fila and str(fila.get('description') or '') in descs:
                surf.creds.delete(fila['uid'])
                creds += 1
    return {'checks': sum(1 for q in quitar if q[1] is not None), 'devices': len(disp),
            'series': series, 'credentials': creds, 'logs': logs}


def _register() -> None:
    from lib.core.dcim import demo                               # noqa: PLC0415
    register = getattr(demo, 'register_part', None)
    if callable(register):
        register('monitor', install, remove, STEPS)


_register()
