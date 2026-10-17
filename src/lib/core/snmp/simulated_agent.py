#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A simulated SNMP agent: a device that answers from a description instead of the network.

A device whose ``snmp`` profile carries a ``simulated`` description (the demo's devices do —
`lib.core.dcim.demo_monitor`) is sampled by the **real** SNMP module with its **real** device
profiles: the same probes, walks, rates between samples, identity, headline measures,
neighbours and sightings. Only the two primitives change: when the sampler is about to talk to
such a device it binds its address here (:func:`bind_server`), and `SnmpClient._snmp_get` /
`_snmp_walk_oid` answer from :class:`Agent` instead of opening a socket. Nothing is ever sent
for a bound address — the demo's are documentation addresses that route nowhere anyway.

The description is small and the agent builds the MIB from it, on each request, for the
instant it is asked at:

* system (RFC 1213): descr, objectID, uptime from ``boot``, contact, name, location;
* IF-MIB: ``ifTable`` / ``ifXTable`` per interface, with octet, packet, error and discard
  counters that are the integral of a rate with a daily swing — so they only ever grow, wrap
  at 32 bits like a real ``ifInOctets`` and give a believable chart once two samples exist;
* LLDP-MIB: the local ports and the neighbour of each one (``lldpRemTable``);
* ENTITY-MIB: serial, model, firmware and maker of the chassis;
* HOST-RESOURCES and UCD-SNMP (a net-snmp agent): processor load per core, storage, memory,
  load averages and lm-sensors temperatures and fans;
* UPS-MIB (RFC 1628) for a UPS: battery, input, output and bypass per line, alarms — the load
  being the one the inventory hangs from it;
* ENTITY-SENSOR-MIB (RFC 3433) for a metered PDU: a sensor per outlet, phase and inlet, with
  the current and power of what is plugged into each.

``silent: true`` is a device that does not answer at all — a timeout, as an unreachable one.
Enterprise OIDs of the fictitious makers use 32473, the private enterprise number IANA
reserves for documentation (RFC 5612); a Linux server says 8072, net-snmp's, which is what the
agent on a real one says.
"""

from __future__ import annotations

import math
import random
import threading
import time

#: The address → description of every simulated device this process has been told about.
_BOUND: dict = {}
_LOCK = threading.Lock()

_W32 = 2 ** 32
_W64 = 2 ** 64
_DAY = 86400.0


def bind(host: str, spec: dict | None) -> None:
    """Answer *host* from *spec* from now on (``None`` forgets it)."""
    host = str(host or '').strip()
    if not host:
        return
    with _LOCK:
        if isinstance(spec, dict):
            _BOUND[host] = spec
        else:
            _BOUND.pop(host, None)
        _AGENTS.pop(host, None)


#: Addresses answered even if their description says ``silent``: the sweep a device gave before
#: it went offline (`awake`).
_AWAKE: set = set()


def awake(host: str, on: bool = True) -> None:
    """Let a silent device answer (or stop letting it): for the sweep it gave before it went
    offline, so what it was is on record."""
    host = str(host or '').strip()
    with _LOCK:
        (_AWAKE.add if on else _AWAKE.discard)(host)
        _AGENTS.pop(host, None)


#: One agent per address for a few seconds: a device's sampling is some sixty requests in a
#: row, and building its MIB sixty times would be the whole cost of the cycle. Within the
#: window every request reads the same instant, as one sweep of a real agent nearly does.
_AGENTS: dict = {}
_REUSE_S = 10.0


def lookup(host: str):
    """The :class:`Agent` for *host*, or ``None`` for a real device."""
    host = str(host or '').strip()
    spec = _BOUND.get(host)
    if spec is None:
        return None
    now = time.time()
    with _LOCK:
        got = _AGENTS.get(host)
        if got is not None and got.base is spec and now - got.now < _REUSE_S:
            return got
        answer = dict(spec, silent=False) if host in _AWAKE and spec.get('silent') else spec
        got = _AGENTS[host] = Agent(answer, now, base=spec)
        return got


def spec_of_device(device: dict | None) -> dict | None:
    """The simulated description a registry device carries, if any."""
    prof = ((device or {}).get('profiles') or {}).get('snmp') or {}
    spec = prof.get('simulated') if isinstance(prof, dict) else None
    return spec if isinstance(spec, dict) else None


def bind_server(module, server: dict) -> dict | None:
    """Bind the device a resolved SNMP *server* stands for, when it is a simulated one, and
    hand back its description (``None`` for a real device).

    Called by the sampler before it talks to the server: the description lives on the
    registry device, which every process that samples can read."""
    uid = str((server or {}).get('device_uid') or '').strip()
    store = getattr(getattr(module, '_monitor', None), '_devices_store', None)
    if not uid or store is None:
        return None
    try:
        spec = spec_of_device(store.get(uid))
    except Exception:  # pylint: disable=broad-except
        return None
    if spec is None:
        return None
    bind(str(server.get('host') or ''), spec)
    for addr in str(server.get('host') or '').split():
        bind(addr, spec)
    return spec


# ── How often a simulated device is sampled ──────────────────────────────────────────────────
#
# A simulated agent answers from memory, and still each sample is the whole of the real
# sampler's work for it: every profile, every row, a state row and a history sample per row.
# The demo's 356 devices were all of that every cycle —a minute of the scheduler on SQLite, with
# the panel's pages waiting behind it— for numbers that are a function of the clock. So they
# are sampled on a cadence of their own (the SNMP module's `simulated_interval`, five minutes),
# each at its own moment within it: what a cycle samples is the slice whose moment came, so a
# cycle every minute takes a fifth of them and the history of each is one reading every five
# minutes —a line, because the counters are integrals of the clock and a rate over five
# minutes is the same rate—. In the cycles between, what it said last stands
# (`ReturnModuleCheck.keep`).

#: The cadence when the module says nothing, in seconds.
DEFAULT_INTERVAL = 300
#: Where in a device's sample state the moment of its last sample is kept.
SAMPLED_AT = 'sim_at'


def phase(uid: str, interval: float) -> float:
    """Where in each *interval* this device's moment falls: stable for the device, spread
    evenly over a fleet."""
    if interval <= 0:
        return 0.0
    import zlib                                         # noqa: PLC0415
    return float(zlib.crc32(str(uid or '').encode('utf-8')) % max(1, int(interval)))


def is_due(uid: str, last, now: float, interval: float) -> bool:
    """Whether a simulated device sampled at *last* (``None``: never) is due at *now*.

    Due once per *interval*, at its own `phase`: when a moment of it has passed since the last
    sample. ``interval <= 0`` is every cycle. A clock that went back, or a sample older than
    the interval (the scheduler was stopped), is due too."""
    if interval <= 0 or last is None:
        return True
    try:
        last = float(last)
    except (TypeError, ValueError):
        return True
    if now < last or now - last >= interval:
        return True
    p = phase(uid, interval)
    return math.floor((now - p) / interval) > math.floor((last - p) / interval)


def _oid_key(oid: str) -> tuple:
    return tuple(int(x) for x in str(oid).strip('.').split('.') if x.isdigit())


class Agent:
    """Answers GET and WALK from a description, for the instant it is asked at."""

    def __init__(self, spec: dict, now: float | None = None, base: dict | None = None):
        self.spec = spec or {}
        self.base = base if base is not None else spec
        self.now = time.time() if now is None else float(now)
        self._tree = None
        self._building: dict = {}
        self._lock = threading.Lock()

    # ── the two primitives, with the client's return shapes ──────────────────────────────
    def get(self, oid: str):
        from lib.core.snmp.client import NoAnswer          # noqa: PLC0415
        if self.spec.get('silent'):
            return None, NoAnswer('No SNMP response received before timeout')
        val = self.tree().get(_oid_key(oid))
        if val is None:
            return None, f'No Such Object currently exists at this OID at {oid}'
        return str(val), None

    def walk(self, oid: str, max_rows: int = 0):
        from lib.core.snmp.client import NoAnswer, Truncated  # noqa: PLC0415
        if self.spec.get('silent'):
            return {}, NoAnswer('No SNMP response received before timeout')
        root = _oid_key(oid)
        n = len(root)
        rows: dict = {}
        limit = int(max_rows or 512)
        tree = self.tree()
        for key in sorted(k for k in tree if k[:n] == root):
            rows['0' if len(key) == n else '.'.join(str(x) for x in key[n:])] = str(tree[key])
            if len(rows) > limit:
                rows.pop(next(reversed(rows)))
                return rows, Truncated(f'more than {limit} rows; only the first {limit} were read')
        return rows, None

    # ── the MIB ──────────────────────────────────────────────────────────────────────────
    def tree(self) -> dict:
        with self._lock:
            if self._tree is None:
                self._building = {}
                self._system()
                self._interfaces()
                self._lldp()
                self._entity()
                self._host()
                self._ups()
                self._sensors()
                self._tree = self._building
        return self._tree

    def _put(self, oid: str, value) -> None:
        self._building[_oid_key(oid)] = value

    def _rnd(self, *salt) -> random.Random:
        window = int(self.now // 300)
        return random.Random('|'.join(str(s) for s in (self.spec.get('name'), window) + salt))

    def _system(self) -> None:
        s = self.spec
        up = max(0.0, self.now - float(s.get('boot') or self.now - 86400 * 30))
        self._put('1.3.6.1.2.1.1.1.0', s.get('descr') or '')
        self._put('1.3.6.1.2.1.1.2.0', s.get('objectid') or '1.3.6.1.4.1.32473.1')
        self._put('1.3.6.1.2.1.1.3.0', int(up * 100))
        self._put('1.3.6.1.2.1.1.4.0', s.get('contact') or '')
        self._put('1.3.6.1.2.1.1.5.0', s.get('name') or '')
        self._put('1.3.6.1.2.1.1.6.0', s.get('location') or '')
        self._put('1.3.6.1.2.1.1.7.0', 78)
        ip, mask = str(s.get('ip') or ''), str(s.get('mask') or '255.255.255.0')
        if ip and ':' not in ip:
            self._put(f'1.3.6.1.2.1.4.20.1.1.{ip}', ip)
            self._put(f'1.3.6.1.2.1.4.20.1.2.{ip}', 1)
            self._put(f'1.3.6.1.2.1.4.20.1.3.{ip}', mask)
            gw = str(s.get('gateway') or '')
            if gw:
                self._put('1.3.6.1.2.1.4.21.1.1.0.0.0.0', '0.0.0.0')
                self._put('1.3.6.1.2.1.4.21.1.7.0.0.0.0', gw)
        self._put('1.3.6.1.2.1.4.1.0', 1 if s.get('forwarding') else 2)

    def _counter(self, base: float, phase: float, up: float) -> float:
        """∫ base·(1 + 0.35·sin(2πt/day + phase)) dt over the uptime: grows, never shrinks."""
        if base <= 0:
            return 0.0
        a = 0.35 * _DAY / (2 * math.pi)
        t0 = self.now - up
        w = 2 * math.pi / _DAY
        return base * (up + a * (math.cos(w * t0 + phase) - math.cos(w * self.now + phase)))

    def _interfaces(self) -> None:
        ifs = self.spec.get('ifs') or []
        if not ifs:
            return
        up = max(1.0, self.now - float(self.spec.get('boot') or self.now - 86400 * 30))
        self._put('1.3.6.1.2.1.2.1.0', len(ifs))
        self._put('1.3.6.1.2.1.31.1.5.0', 0)
        for n, f in enumerate(ifs, start=1):
            name = str(f.get('name') or f'port{n}')
            speed = int(f.get('speed') or 1_000_000_000)
            oper_up = int(f.get('oper') or 1) == 1
            phase = (sum(ord(c) for c in name) % 628) / 100.0
            rin = float(f.get('rate_in') or 0) if oper_up else 0.0
            rout = float(f.get('rate_out') or 0) if oper_up else 0.0
            octin, octout = self._counter(rin, phase, up), self._counter(rout, phase + 1, up)
            pin, pout = octin / 800.0, octout / 800.0
            err = float(f.get('err_ratio') or 0)
            ifd = f'1.3.6.1.2.1.2.2.1.{{}}.{n}'
            for col, val in ((1, n), (2, name), (3, int(f.get('type') or 6)), (4, 1500),
                             (5, min(speed, _W32 - 1)), (6, f.get('mac') or ''),
                             (7, int(f.get('admin') or 1)), (8, 1 if oper_up else 2),
                             (10, int(octin) % _W32), (11, int(pin) % _W32),
                             (13, int(pin * 0.00002) % _W32), (14, int(pin * err) % _W32),
                             (16, int(octout) % _W32), (17, int(pout) % _W32),
                             (19, int(pout * 0.00001) % _W32), (20, 0)):
                self._put(ifd.format(col), val)
            ifx = f'1.3.6.1.2.1.31.1.1.1.{{}}.{n}'
            for col, val in ((1, name), (6, int(octin) % _W64), (10, int(octout) % _W64),
                             (15, speed // 1_000_000), (18, f.get('alias') or '')):
                self._put(ifx.format(col), val)

    def _lldp(self) -> None:
        peers = self.spec.get('lldp') or []
        ifs = self.spec.get('ifs') or []
        if not ifs or self.spec.get('lldp') is None:
            return
        self._put('1.0.8802.1.1.2.1.3.1.0', 4)
        self._put('1.0.8802.1.1.2.1.3.2.0', self.spec.get('chassis') or '')
        self._put('1.0.8802.1.1.2.1.3.3.0', self.spec.get('name') or '')
        for n, f in enumerate(ifs, start=1):
            self._put(f'1.0.8802.1.1.2.1.3.7.1.3.{n}', str(f.get('name') or ''))
            self._put(f'1.0.8802.1.1.2.1.3.7.1.4.{n}', str(f.get('name') or ''))
        for p in peers:
            n = int(p.get('local') or 0)
            if not n:
                continue
            idx = f'0.{n}.1'
            for col, key in ((5, 'chassis'), (7, 'port'), (8, 'port_desc'), (9, 'sysname'),
                             (10, 'sysdesc')):
                self._put(f'1.0.8802.1.1.2.1.4.1.1.{col}.{idx}', str(p.get(key) or ''))

    def _entity(self) -> None:
        e = self.spec.get('entity') or {}
        if not e:
            return
        self._put('1.3.6.1.2.1.47.1.4.1.0', 0)
        base = '1.3.6.1.2.1.47.1.1.1.1.{}.1'
        for col, key in ((2, 'descr'), (7, 'name'), (9, 'firmware'), (11, 'serial'),
                         (12, 'vendor'), (13, 'model')):
            self._put(base.format(col), str(e.get(key) or ''))

    def _swing(self, phase: float = 0.0, depth: float = 0.08) -> float:
        """The daily rhythm of a load: ±*depth* around 1."""
        return 1.0 + depth * math.sin(2 * math.pi * self.now / _DAY + phase)

    def _uptime_ticks(self) -> int:
        return int(max(0.0, self.now - float(self.spec.get('boot') or self.now - 86400 * 30))
                   * 100)

    def _ups(self) -> None:
        """UPS-MIB (RFC 1628), from ``ups``: identity, battery, input, output, bypass and the
        alarm table. The load is the one the inventory says hangs from this UPS, with the day's
        swing; the runtime follows it; on battery the input is gone and the clock runs."""
        u = self.spec.get('ups') or {}
        if not u:
            return
        rnd = self._rnd('ups')
        b = '1.3.6.1.2.1.33.1'
        lines = max(1, int(u.get('lines') or 1))
        rated = max(1.0, float(u.get('rated_w') or 1000))
        load = max(0.0, float(u.get('load_w') or 0)) * self._swing(1.3) * rnd.uniform(0.98, 1.02)
        frac = min(1.5, load / rated)
        volts, hz = float(u.get('volts') or 230), float(u.get('hz') or 50)
        source = str(u.get('source') or 'normal')
        battery = str(u.get('battery') or 'normal')
        for col, key in ((1, 'manufacturer'), (2, 'model'), (3, 'firmware'), (4, 'agent'),
                         (5, 'name'), (6, 'attached')):
            self._put(f'{b}.1.{col}.0', str(u.get(key) or ''))
        # The battery. Its runtime is the one the inventory declares at half load
        # (`autonomy_min`), longer with less on it and shorter with more; one whose cells are
        # tired says so with a runtime of its own and `batteryLow` while still on the mains.
        autonomy = float(u.get('autonomy_min') or 15)
        runtime = (float(u['runtime_min']) if u.get('runtime_min') is not None
                   else min(autonomy * 4, autonomy * (0.5 / max(0.08, frac)) ** 1.1))
        on_battery = source == 'battery'
        since = max(0.0, self.now - float(u.get('since') or self.now))
        if on_battery:
            runtime = max(1.0, runtime - since / 60.0)
        charge = 100 if not on_battery else max(5, int(100 - since / 60.0 * 100
                                                       / max(1.0, runtime)))
        self._put(f'{b}.2.1.0', {'normal': 2, 'low': 3, 'depleted': 4}.get(battery, 1))
        self._put(f'{b}.2.2.0', int(since) if on_battery else 0)
        self._put(f'{b}.2.3.0', max(0, int(round(runtime))))
        self._put(f'{b}.2.4.0', charge)
        dc = float(u.get('battery_v') or 48)
        self._put(f'{b}.2.5.0', int(dc * (1.0 if on_battery else 1.125) * 10
                                     + rnd.uniform(-2, 2)))
        self._put(f'{b}.2.6.0', int(load / max(1.0, dc) * 10) if on_battery else 0)
        self._put(f'{b}.2.7.0', int(round(float(u.get('temp') or 25) + rnd.uniform(-0.6, 0.6))))
        # The input, line by line: what the UPS draws (its own losses included), nothing when
        # it is running on its battery.
        self._put(f'{b}.3.1.0', int(u.get('input_bads') or 0))
        self._put(f'{b}.3.2.0', lines)
        eff = 0.94 if source == 'normal' else 1.0
        for n in range(1, lines + 1):
            v = 0 if on_battery else int(round(volts * rnd.uniform(0.985, 1.012)))
            w = 0 if on_battery else int(load / lines / eff)
            self._put(f'{b}.3.3.1.1.{n}', n)
            self._put(f'{b}.3.3.1.2.{n}', 0 if on_battery else int(hz * 10 + rnd.randint(-1, 1)))
            self._put(f'{b}.3.3.1.3.{n}', v)
            self._put(f'{b}.3.3.1.4.{n}', int(w / max(1, v) / 0.95 * 10) if v else 0)
            self._put(f'{b}.3.3.1.5.{n}', w)
        # The output, line by line: the load, and its share of the rating.
        self._put(f'{b}.4.1.0', {'normal': 3, 'bypass': 4, 'battery': 5, 'none': 2,
                                 'booster': 6, 'reducer': 7}.get(source, 1))
        self._put(f'{b}.4.2.0', int(hz * 10))
        self._put(f'{b}.4.3.0', lines)
        for n in range(1, lines + 1):
            w = load / lines
            v = int(round(volts * rnd.uniform(0.997, 1.003)))
            self._put(f'{b}.4.4.1.1.{n}', n)
            self._put(f'{b}.4.4.1.2.{n}', v)
            self._put(f'{b}.4.4.1.3.{n}', int(w / max(1, v) / 0.95 * 10))
            self._put(f'{b}.4.4.1.4.{n}', int(w))
            self._put(f'{b}.4.4.1.5.{n}', int(round(w / (rated / lines) * 100)))
        # The bypass, which is the mains itself.
        self._put(f'{b}.5.1.0', 0 if on_battery else int(hz * 10))
        self._put(f'{b}.5.2.0', lines)
        for n in range(1, lines + 1):
            self._put(f'{b}.5.3.1.1.{n}', n)
            self._put(f'{b}.5.3.1.2.{n}', 0 if on_battery else int(round(volts)))
        # The alarms it has raised: well-known ones (upsWellKnownAlarms), each since when.
        alarms = [int(a) for a in (u.get('alarms') or ())]
        self._put(f'{b}.6.1.0', len(alarms))
        at = max(0, self._uptime_ticks() - int(since * 100))
        for n, alarm in enumerate(alarms, start=1):
            self._put(f'{b}.6.2.1.1.{n}', n)
            self._put(f'{b}.6.2.1.2.{n}', f'{b}.6.3.{alarm}')
            self._put(f'{b}.6.2.1.3.{n}', at)
        # What it was configured for.
        self._put(f'{b}.9.1.0', int(volts))
        self._put(f'{b}.9.2.0', int(hz * 10))
        self._put(f'{b}.9.3.0', int(volts))
        self._put(f'{b}.9.4.0', int(hz * 10))
        self._put(f'{b}.9.5.0', int(u.get('rated_va') or rated / 0.9))
        self._put(f'{b}.9.6.0', int(rated))

    #: ENTITY-SENSOR-MIB's unit of each `EntitySensorDataType`, as `entPhySensorUnitsDisplay`.
    _SENSOR_UNITS = {3: 'V', 4: 'V', 5: 'A', 6: 'W', 7: 'Hz', 8: 'C', 9: '%RH', 10: 'RPM'}

    def _sensors(self) -> None:
        """ENTITY-SENSOR-MIB (RFC 3433), from ``sensors``: each one a physical entity of its
        own (ENTITY-MIB, class sensor, inside the chassis) with its type, the decimals it
        carries and its reading — currents and powers with the day's swing of what is
        plugged in, voltages and frequencies steady."""
        sensors = self.spec.get('sensors') or []
        if not sensors:
            return
        rnd = self._rnd('sensors')
        ticks = self._uptime_ticks()
        self._put('1.3.6.1.2.1.47.1.4.1.0', 0)
        swing = self._swing(1.3)
        for n, sensor in enumerate(sensors, start=1):
            idx = 100 + n
            name = str(sensor.get('name') or f'Sensor {n}')
            kind = int(sensor.get('type') or 2)
            prec = int(sensor.get('precision') or 0)
            base = float(sensor.get('value') or 0)
            if kind in (5, 6):
                value = base * swing * rnd.uniform(0.97, 1.03)
            elif kind in (3, 4):
                value = base * rnd.uniform(0.996, 1.004)
            elif kind == 7:
                value = base + rnd.uniform(-0.03, 0.03)
            else:
                value = base + rnd.uniform(-0.5, 0.5)
            ent = '1.3.6.1.2.1.47.1.1.1.1.{}.' + str(idx)
            self._put(ent.format(2), name)
            self._put(ent.format(4), 1)
            self._put(ent.format(5), 8)
            self._put(ent.format(7), name)
            sen = '1.3.6.1.2.1.99.1.1.1.{}.' + str(idx)
            self._put(sen.format(1), kind)
            self._put(sen.format(2), 9)
            self._put(sen.format(3), prec)
            self._put(sen.format(4), int(round(value * 10 ** prec)))
            self._put(sen.format(5), int(sensor.get('status') or 1))
            self._put(sen.format(6), self._SENSOR_UNITS.get(kind, ''))
            self._put(sen.format(7), ticks)
            self._put(sen.format(8), 1000)

    def _host(self) -> None:
        h = self.spec.get('host') or {}
        if not h:
            return
        rnd = self._rnd('host')
        cores = max(1, int(h.get('cores') or 8))
        cpu = max(0.0, min(100.0, float(h.get('cpu') or 20) + rnd.uniform(-8, 8)))
        self._put('1.3.6.1.2.1.25.1.5.0', int(h.get('users') or 1))
        self._put('1.3.6.1.2.1.25.1.6.0', int(h.get('procs') or 240) + rnd.randint(-10, 10))
        for c in range(cores):
            idx = 196608 + c
            self._put(f'1.3.6.1.2.1.25.3.2.1.3.{idx}', f'CPU {c}')
            self._put(f'1.3.6.1.2.1.25.3.3.1.2.{idx}',
                      int(max(0, min(100, cpu + rnd.uniform(-6, 6)))))
        kb = int(h.get('mem_kb') or 64 * 1024 * 1024)
        used = max(0.05, min(0.98, float(h.get('mem_used') or 0.5) + rnd.uniform(-0.03, 0.03)))
        for i, (descr, size, frac) in enumerate(
                [('Physical memory', kb, used), ('Swap space', kb // 8, 0.02)]
                + [(d.get('descr'), int(d.get('kb') or 0), float(d.get('used') or 0))
                   for d in (h.get('storage') or [])], start=1):
            kind = ('1.3.6.1.2.1.25.2.1.2' if i == 1 else '1.3.6.1.2.1.25.2.1.3' if i == 2
                    else '1.3.6.1.2.1.25.2.1.4')
            self._put(f'1.3.6.1.2.1.25.2.3.1.2.{i}', kind)
            self._put(f'1.3.6.1.2.1.25.2.3.1.3.{i}', descr)
            self._put(f'1.3.6.1.2.1.25.2.3.1.4.{i}', 1024)
            self._put(f'1.3.6.1.2.1.25.2.3.1.5.{i}', size)
            self._put(f'1.3.6.1.2.1.25.2.3.1.6.{i}', int(size * frac))
        user, system = cpu * 0.7, cpu * 0.3
        self._put('1.3.6.1.4.1.2021.11.9.0', int(user))
        self._put('1.3.6.1.4.1.2021.11.10.0', int(system))
        self._put('1.3.6.1.4.1.2021.11.11.0', int(100 - cpu))
        self._put('1.3.6.1.4.1.2021.11.67.0', cores)
        for i, f in ((1, 1.0), (2, 0.9), (3, 0.8)):
            self._put(f'1.3.6.1.4.1.2021.10.1.5.{i}', int(cores * cpu / 100 * f * 100))
        self._put('1.3.6.1.4.1.2021.4.3.0', kb // 8)
        self._put('1.3.6.1.4.1.2021.4.4.0', int(kb // 8 * 0.98))
        self._put('1.3.6.1.4.1.2021.4.5.0', kb)
        self._put('1.3.6.1.4.1.2021.4.6.0', int(kb * (1 - used)))
        self._put('1.3.6.1.4.1.2021.4.14.0', kb // 50)
        self._put('1.3.6.1.4.1.2021.4.15.0', kb // 6)
        self._put('1.3.6.1.4.1.2021.4.27.0', int(kb * (1 - used)))
        for i, t in enumerate(h.get('temps') or [], start=1):
            self._put(f'1.3.6.1.4.1.2021.13.16.2.1.2.{i}', t.get('name') or f'temp{i}')
            self._put(f'1.3.6.1.4.1.2021.13.16.2.1.3.{i}',
                      int((float(t.get('c') or 40) + rnd.uniform(-1.5, 1.5)) * 1000))
        for i, fan in enumerate(h.get('fans') or [], start=1):
            self._put(f'1.3.6.1.4.1.2021.13.16.3.1.2.{i}', fan.get('name') or f'fan{i}')
            self._put(f'1.3.6.1.4.1.2021.13.16.3.1.3.{i}',
                      int(float(fan.get('rpm') or 6000) + rnd.uniform(-150, 150)))
