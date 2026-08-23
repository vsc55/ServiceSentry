#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How the fleet is wired together, out of what it already answered.

**Nothing here asks a device anything.** Every edge is read out of facts already recorded by
the ordinary cycle: the addresses a machine says it has, the prefix each one sits on, and the
next hop it uses for what it cannot deliver itself. That is the whole point — a map that cost
a new conversation with forty machines would be a map somebody turns off.

WHAT IT CAN AND CANNOT SAY, in order of how much it knows:

* **an address is on a network.** Arithmetic, and certain: 192.168.250.21/24 is on
  192.168.250.0/24, on every machine ever made. Two devices with an address on the same
  network can reach each other without a router, and that is a real thing to draw.
* **a machine's way out.** The next hop of its default route, which the device states. If
  that address belongs to a machine in the registry it is an edge between two known things;
  if it does not, it is a router nobody has added, drawn as what it is.
* **which port is plugged into which port.** It cannot. That is LLDP, and until a device
  serves it this map is about REACHABILITY and says so — an inferred edge and a cable are
  not the same claim, and drawing them the same way would be the map lying quietly.

So every edge carries how it was arrived at (``kind``), and the screen is expected to show
that rather than flatten it: "these two are on one network" is not "these two are connected".
"""

from __future__ import annotations

#: Addresses that say nothing about where a machine is. Loopback is on every machine and
#: would put the whole fleet on one network; the unspecified address is not an address.
_IGNORED_NETS = ('127.', '0.0.0.0')


def _parse_address(text: str) -> tuple:
    """``('192.168.1.10/24')`` → ``('192.168.1.10', 24)``, or ``('', 0)``.

    The prefix is what the profile paired onto the address (``"as": "prefix"``). Without one
    the address is still an address — it just cannot be placed on a network, and saying
    nothing is better than assuming /24 because most of them are.
    """
    raw = str(text or '').strip()
    if not raw:
        return '', 0
    addr, _, bits = raw.partition('/')
    addr = addr.strip()
    try:
        prefix = int(bits) if bits.strip() else 0
    except ValueError:
        prefix = 0
    if not (0 <= prefix <= 32):
        prefix = 0
    return addr, prefix


def _octets(addr: str) -> list | None:
    parts = str(addr or '').split('.')
    if len(parts) != 4:
        return None                      # IPv6 is not placed on a network here, yet
    try:
        out = [int(p) for p in parts]
    except ValueError:
        return None
    return out if all(0 <= o <= 255 for o in out) else None


def network_of(addr: str, prefix: int) -> str:
    """The network an address sits on, as ``a.b.c.d/n`` — or ``''`` when it cannot be said."""
    octets = _octets(addr)
    if octets is None or not 1 <= int(prefix or 0) <= 32:
        return ''
    value = (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
    mask = ((1 << int(prefix)) - 1) << (32 - int(prefix))
    net = value & mask
    return '.'.join(str((net >> shift) & 0xFF) for shift in (24, 16, 8, 0)) + f'/{prefix}'


def _ignored(addr: str) -> bool:
    return any(str(addr or '').startswith(p) for p in _IGNORED_NETS)


def _facts_of(attrs: list) -> dict:
    """``{role: value}`` for the facts that are about the MACHINE.

    Row-bound facts belong to something else — a disk's serial, an interface's MAC — and a
    machine is not on a network because one of its disks said something.
    """
    out: dict = {}
    for a in attrs or ():
        if a.get('row'):
            continue
        key = str(a.get('key') or '')
        if key and key not in out:
            out[key] = str(a.get('value') or '').strip()
    return out


def build(hosts: list, attrs_by_host: dict) -> dict:
    """The map: ``{'networks': [...], 'nodes': [...], 'edges': [...], 'unplaced': [...]}``.

    *hosts* is the fleet as the list screen has it (uid, name, …). *attrs_by_host* is
    ``{uid: [attribute, …]}`` — whatever ``infra.service.attributes`` produced for each.
    """
    nodes: list = []
    networks: dict = {}
    edges: list = []
    by_address: dict = {}                # every address the fleet claims → the uid holding it
    unplaced: list = []

    for host in hosts or ():
        uid = str(host.get('uid') or '')
        if not uid:
            continue
        facts = _facts_of(attrs_by_host.get(uid) or [])
        addrs, nets = [], []
        for chunk in str(facts.get('ip') or '').split(','):
            addr, prefix = _parse_address(chunk)
            if not addr or _ignored(addr):
                continue
            addrs.append(f'{addr}/{prefix}' if prefix else addr)
            by_address.setdefault(addr, uid)
            net = network_of(addr, prefix)
            if net:
                nets.append(net)
                networks.setdefault(net, {'net': net, 'members': []})
        # The registry's own address, for a machine whose checks have never answered. It is
        # the address somebody typed, which is a fact about the record and not about the
        # device — so it places the node and is never treated as one the device claimed.
        if not addrs and str(host.get('address') or '').strip():
            addrs.append(str(host['address']).strip())
            by_address.setdefault(str(host['address']).strip(), uid)
        node = {'uid': uid, 'name': str(host.get('name') or ''),
                'kind': str(host.get('device_type') or host.get('kind') or ''),
                'status': str(host.get('status') or ''),
                'addresses': addrs, 'networks': sorted(set(nets)),
                'gateway': str(facts.get('gateway') or '').split(',')[0].strip()}
        nodes.append(node)
        for net in set(nets):
            networks[net]['members'].append(uid)
        if not nets:
            unplaced.append(uid)

    # …and the way out of each network. Drawn from what the machine SAYS its next hop is, so
    # a device with two default routes contributes the first and a device with none
    # contributes nothing rather than a guess.
    for node in nodes:
        gw = node['gateway']
        if not gw or _ignored(gw):
            continue
        target = by_address.get(gw)
        edges.append({'from': node['uid'], 'to': target or '', 'address': gw,
                      # `gateway` when the far end is a machine the panel knows, `exit` when
                      # it is a router nobody added. Different claims, different drawings.
                      'kind': 'gateway' if target else 'exit'})

    return {
        'networks': sorted(networks.values(), key=lambda n: _sort_key(n['net'])),
        'nodes': sorted(nodes, key=lambda n: (n['name'] or n['uid']).lower()),
        'edges': edges,
        'unplaced': unplaced,
    }


def _sort_key(net: str) -> tuple:
    """Networks in address order, so the list reads the way a routing table does."""
    addr, _, bits = str(net).partition('/')
    octets = _octets(addr) or [0, 0, 0, 0]
    try:
        prefix = int(bits)
    except ValueError:
        prefix = 0
    return tuple(octets) + (prefix,)
