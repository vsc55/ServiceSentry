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
* **which port is plugged into which port.** Only where LLDP is served. That is the one
  thing in SNMP that answers the topology question exactly, and it is the strongest edge on
  the picture: a device saying "I can see that one down this cable, on its port 3" is not an
  inference at all. Everything else here says who can REACH whom, which is a different claim,
  and a machine only answers LLDP where somebody runs an agent for it.

So every edge carries how it was arrived at (``kind``), and the screen is expected to show
that rather than flatten it: "these two are on one network" is not "these two are connected".
"""

from __future__ import annotations

import re

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


def _rows_of(attrs: list) -> list:
    """The ROW-bound facts, grouped by the row they belong to: ``[{row, key: value, …}]``.

    The other half of what a device answered. A neighbour is a row — LLDP reports one per
    neighbour per port — so what identifies it and which port it answered on arrive as facts
    of that row, exactly like a disk's model and serial do.
    """
    rows: dict = {}
    for a in attrs or ():
        row = str(a.get('row') or '')
        if not row:
            continue
        key = str(a.get('key') or '')
        if key:
            rows.setdefault(row, {'row': row}).setdefault(key, str(a.get('value') or '').strip())
    return list(rows.values())


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


def mac_key(text) -> str:
    """A MAC in one form, whatever form it arrived in.

    SNMP answers these as raw octets, as ``0x068c62818594``, as ``06:8c:62:81:85:94`` and as
    ``6:8c:62:81:85:94`` — the same address four ways, from four agents, on one network. The
    join that finds a machine on a switch port compares them to each other, so a comparison
    that is not normalised is a map with no links on it and nothing saying why.
    """
    text = str(text or '').strip().lower()
    if text.startswith('0x'):
        text = text[2:]              # the octet-string form, which is most agents
    # Grouped forms are padded per group, not just stripped: an agent that writes
    # "bc:24:11:e:90:5f" has dropped a leading zero, and squashing that gives eleven
    # characters and a MAC that matches nothing. Cisco's "bc24.110e.905f" pads to itself.
    if any(sep in text for sep in ':-.'):
        parts = [p for p in re.split(r'[:\-.]', text) if p != '']
        if parts and all(all(c in '0123456789abcdef' for c in p) for p in parts):
            joined = ''.join(p.zfill(2) if len(p) < 2 else p for p in parts)
            if len(joined) == 12:
                return joined
    hexes = [c for c in text if c in '0123456789abcdef']
    return ''.join(hexes) if len(hexes) == 12 else ''


def _port_named(port, owner_uid: str, by_mac: dict) -> str:
    """One port of *owner_uid*, as a name — resolving the MAC form when that is what arrived.

    A switch with no port description answers its portId, which on most of them is that port's
    hardware address. Reported from a real rack, where one end of every link in a trunk read
    `00:00:5E:00:53:01` where a port name goes. It is an interface of a machine this panel
    already reads, and `by_mac` says which — but only when the MAC belongs to the machine the
    port is supposed to be ON, or the map would put a neighbour's interface on this device.
    """
    text = str(port or '').strip()
    if not text:
        return ''
    owner = by_mac.get(mac_key(text))
    if owner and owner[0] == owner_uid and owner[1]:
        return owner[1]
    return text


def _split_private(networks: dict) -> None:
    """Mark the networks whose members are not on ONE network at all.

    Reported from the map: two NAS both showed as living in 172.17.0.0/16, drawn as
    neighbours, and they cannot reach each other. It is `docker0` — every machine running
    containers has one, every one of them is 172.17.0.1, and they are as many separate
    networks as there are machines.

    Detected from something universally true rather than from knowing what Docker is: **two
    machines cannot hold the same address on one network.** If they both claim 172.17.0.1,
    either it is not the same network or one of them is unreachable — and in both cases
    drawing them as neighbours is a lie. The map says so instead of joining them.

    Nothing is dropped. The network keeps its members and gains a flag, because "there are
    six machines each with their own 172.17.0.0/16" is a fact about the fleet worth reading.
    """
    for net in networks.values():
        claims = net.pop('claims', {}) or {}
        seen: dict = {}
        for uid, addr in claims.items():
            seen.setdefault(addr, []).append(uid)
        net['private'] = any(len(v) > 1 for v in seen.values())


def build(hosts: list, attrs_by_host: dict, evidence: dict | None = None) -> dict:
    """The map: ``{'networks': [...], 'nodes': [...], 'edges': [...], 'unplaced': [...]}``.

    *hosts* is the fleet as the list screen has it (uid, name, …). *attrs_by_host* is
    ``{uid: [attribute, …]}`` — whatever ``infra.service.attributes`` produced for each.
    *evidence* is ``{kind: {uid: {key: value}}}`` from ``infra.evidence`` — what devices SAW,
    which is what places a machine on a switch port when it speaks no LLDP.

    An ``lldp`` edge carries ``bundle``: how many cables run between that pair. Four cables
    between a router and a switch is a trunk, and the map has to draw four lines — the count
    is what a reader wants and it is what the two devices actually said.

    …and ``lag`` — ``{uid: {port: the aggregate it belongs to}}`` — for the ends that said so.
    Which of a device's ports are one aggregate is not in any neighbour table: from outside,
    four cables and a four-port LAG answer identically. It is a configuration fact, and the
    device states it in IEEE8023-LAG-MIB (the `lag` profile). Present only for the ends that
    serve it, because the alternative is the map calling four cables a bundle for having
    counted four of them.
    """
    nodes: list = []
    networks: dict = {}
    edges: list = []
    by_address: dict = {}                # every address the fleet claims → the uid holding it
    by_name: dict = {}                   # …and every name it goes by, for the LLDP join
    by_mac: dict = {}                    # …and every MAC → (uid, the interface it is on)
    aggs: dict = {}                      # …and, per uid, which aggregate each port is in
    seen: dict = {}                      # uid → the neighbours it reported
    unplaced: list = []

    for host in hosts or ():
        uid = str(host.get('uid') or '')
        if not uid:
            continue
        attrs = attrs_by_host.get(uid) or []
        facts = _facts_of(attrs)
        rows = _rows_of(attrs)
        seen[uid] = [r for r in rows if r.get('neighbour')]
        # Every MAC this machine owns, AND which of its interfaces has it. Row-bound on
        # purpose: a MAC belongs to an interface, and a machine has as many as it has
        # interfaces.
        #
        # The interface NAME is what turns half a cable into a whole one. A switch with no port
        # description reports its portId, which on most of them is that port's hardware
        # address — so the neighbour says "I see 00:00:5E:00:53:01" and the map had a MAC where
        # a port name goes. That MAC is an interface of a machine this panel already reads, and
        # this is the index that says which.
        for row in rows:
            key = mac_key(row.get('mac'))
            if key:
                by_mac.setdefault(key, (uid, str(row.get('row') or '')))
            # …and which aggregate this port is a member of, where the device said. Row-bound
            # for the same reason: it is a fact about a PORT. The name is the aggregate's own
            # interface name, resolved on the way in — the MIB answers an interface index, and
            # "member of 141" is the same fact nobody can read.
            agg = str(row.get('aggregate') or '').strip()
            if agg and row.get('row'):
                aggs.setdefault(uid, {})[str(row['row'])] = agg
        # What this machine answers to. LLDP names a neighbour by its OWN hostname, which is
        # what `sysName` says and is usually — but not always — what the registry calls it.
        # Both are indexed, because a machine registered as "nas" and calling itself
        # "erebor.cerebelum.lan" is one machine and the map must not draw it as two.
        for name in (facts.get('name'), host.get('name')):
            for form in _name_forms(name):
                by_name.setdefault(form, uid)
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
                networks.setdefault(net, {'net': net, 'members': [], 'claims': {}})
                # WHICH address put this machine here. Kept because it is the only thing that
                # can tell one machine's private range from another's — see `_split_private`.
                networks[net]['claims'].setdefault(uid, addr)
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

    # The exact edges first, because they are the ones that are not an inference: a device
    # reporting an LLDP neighbour is saying it can see that machine down one of its own
    # cables. Only where the far end is a machine the panel knows — a neighbour nobody has
    # registered is real, and the map is the wrong place to acquire inventory.
    #
    # ONE line per pair of machines, and ALL the ports each side named.
    #
    # The line is per pair because a cable is a pair of PORTS and a report only ever names the
    # far one: LLDP says "I see that one, and this is the port IT answered on", never "…and I
    # answered on mine". So two reports of one cable name two different ports, and there is no
    # key that both tells four cables apart AND recognises the two halves of one. Keyed by the
    # far port, an ordinary point-to-point link with an agent at each end becomes two lines —
    # which is a worse lie than the one below.
    #
    # What IS knowable is every port each side put on the wire. A four-cable trunk shows up as
    # four rows in each device's own neighbour table — the router saw the switch on ether11-14,
    # the switch saw the router on GE25-28 — and every one of those is kept.
    #
    # A report ALSO says which of the reporter's own ports it came in on, and that is the half
    # that used to go missing: it is not in any column, it is the second component of the row's
    # index (`lldpRemLocalPortNum`), and the profile now reads it from there and names it
    # through the local-port table. Reported from the rack: a router that knows perfectly well
    # its neighbour is on ether8 drew a cable whose own end read "port not identified", because
    # nothing had asked the only place the answer was kept.
    #
    # A device's own name for its own port WINS over what its neighbour called it. Not
    # tidiness: they are usually the same string and occasionally are not, and merging the two
    # would list one port twice and count one cable as two.
    links: dict = {}
    for uid, neighbours in seen.items():
        for rem in neighbours:
            target = None
            for form in _name_forms(rem.get('neighbour')):
                target = by_name.get(form)
                if target:
                    break
            if not target or target == uid:
                continue                 # unknown, or a machine seeing itself down a loop
            port = _port_named(rem.get('port_desc') or rem.get('port'), target, by_mac)
            mine = _port_named(rem.get('local_port'), uid, by_mac)
            # Sorted, so the same cable keys the same whichever end reported it first, and
            # `from`/`to` are the two ENDS and not a direction: being plugged together is
            # symmetric and the drawing has no arrowhead on it.
            pair = tuple(sorted((uid, target)))
            link = links.setdefault(pair, {'from': pair[0], 'to': pair[1], 'kind': 'lldp',
                                           'ports': {}, 'by': [], 'confirmed': False,
                                           # Kept apart until every report is in: which of
                                           # the two a side ends up showing is decided once,
                                           # and not by whichever device answered first.
                                           '_own': {}, '_said': {}})
            if port:
                link['_said'].setdefault(target, [])
                if port not in link['_said'][target]:
                    link['_said'][target].append(port)
            if mine:
                link['_own'].setdefault(uid, [])
                if mine not in link['_own'][uid]:
                    link['_own'][uid].append(mine)
            if uid not in link['by']:
                link['by'].append(uid)
            link['confirmed'] = len(link['by']) > 1
    for link in links.values():
        own, said = link.pop('_own'), link.pop('_said')
        for side in set(own) | set(said):
            got = own.get(side) or said.get(side) or []
            if got:
                link['ports'][side] = got
        for uid in link['ports']:
            # Numeric-aware: a trunk is ether11, ether12, ether13, ether14 and a list that
            # reads ether11, ether12, ether13, ether14 is the only one anybody can check
            # against the front of the switch.
            link['ports'][uid].sort(key=lambda p: [int(t) if t.isdigit() else t.lower()
                                                   for t in re.split(r'(\d+)', p)])
        # How many cables this pair has, as far as either end could tell. Four rows on one
        # side is four cables — that is what a neighbour table counts — and the larger of the
        # two sides is the honest answer when they disagree, because a side that reported
        # fewer is a side that saw fewer, not a rack with fewer wires in it.
        #
        # `bundle` says how many, NOT that they are an aggregate. Whether cables are a LAG is
        # a configuration fact that lives in IEEE8023-LAG-MIB — read by the `lag` profile and
        # carried below — and calling four cables a bundle for having counted four of them
        # would be the picture claiming more than the data does.
        link['bundle'] = max([len(v) for v in link['ports'].values()] or [1], default=1)
        # …and, for each end that serves IEEE8023-LAG-MIB, which aggregate each of those
        # ports belongs to. This is the half `bundle` cannot state: the count says four
        # cables, and only the device itself can say the four are one link. Ports with no
        # answer are simply absent — a port missing from here is a port whose device did not
        # say, which is not the same as one that said no.
        for uid, ports in link['ports'].items():
            mine = {p: aggs.get(uid, {}).get(p) for p in ports}
            mine = {p: a for p, a in mine.items() if a}
            if mine:
                link.setdefault('lag', {})[uid] = mine
    edges.extend(links[k] for k in sorted(links))
    # …and the machines a switch has placed on a port, for everything that speaks no LLDP.
    # Never over the top of a cable already established: a pair with both is one link, and the
    # LLDP one is the stronger statement of the two.
    edges.extend(_port_edges(evidence or {}, by_mac, {n['uid'] for n in nodes}, set(links)))
    # …then the way out of each network. Drawn from what the machine SAYS its next hop is, so
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

    _split_private(networks)
    return {
        'networks': sorted(networks.values(), key=lambda n: _sort_key(n['net'])),
        'nodes': sorted(nodes, key=lambda n: (n['name'] or n['uid']).lower()),
        'edges': edges,
        'unplaced': unplaced,
    }


#: A port carrying more than one KNOWN machine is not an access port — it is an uplink, and
#: what is behind it is behind something else. Counted rather than guessed at by a threshold:
#: "a port with more than eight MACs" would throw away the hypervisor whose guests each have
#: one, which is exactly the machine somebody wants to find.
def _port_edges(evidence: dict, by_mac: dict, known: set, already: set) -> list:
    """Machines placed on a switch port, from what the switch has learned.

    The chain is three tables deep and each one only knows its own link of it: a MAC is on a
    bridge port, a bridge port is an interface, an interface has a name. The switch answers
    all three and joins none of them, so this does.

    What makes it honest is the count. A MAC on a port says the machine is *reachable* through
    it, not that it is plugged into it — everything behind another switch is reachable through
    the port that switch is on. So a port is only claimed as somewhere a machine IS when
    exactly one machine the panel knows is on it; a port with several is an uplink, and its
    edges are dropped and counted rather than drawn as a fan of cables that do not exist.
    """
    fdb = evidence.get('fdb') or {}
    ports = evidence.get('bridgeport') or {}
    names = evidence.get('ifname') or {}
    out: list = []
    for sw_uid, learned in fdb.items():
        if sw_uid not in known:
            continue
        # …grouped by the port, because the decision is about the port and not about the MAC.
        on_port: dict = {}
        for mac, port in (learned or {}).items():
            owner = by_mac.get(mac_key(mac))
            uid = owner[0] if owner else None
            if uid and uid != sw_uid:
                on_port.setdefault(str(port), set()).add(uid)
        for port, uids in sorted(on_port.items()):
            if len(uids) != 1:
                continue                 # an uplink: what is behind it is behind something
            uid = next(iter(uids))
            ifindex = (ports.get(sw_uid) or {}).get(port, '')
            name = (names.get(sw_uid) or {}).get(str(ifindex), '') or port
            pair = tuple(sorted((sw_uid, uid)))
            if pair in already:
                continue                 # LLDP already said it, and said it better
            out.append({'from': pair[0], 'to': pair[1], 'kind': 'port',
                        'ports': {sw_uid: str(name)}, 'by': [sw_uid], 'confirmed': False})
    return out


def _name_forms(name) -> tuple:
    """The ways one machine's name can be written, for matching one against another.

    LLDP reports a hostname and the registry holds whatever somebody typed. Case is not a
    difference — SNMP agents disagree about it freely — and neither is the domain: "erebor"
    and "erebor.cerebelum.lan" are the same machine, and refusing to join them would draw the
    map with every link missing on precisely the fleets that have a search domain.
    """
    text = str(name or '').strip().lower()
    if not text:
        return ()
    short = text.split('.')[0]
    return (text,) if short == text else (text, short)


def _sort_key(net: str) -> tuple:
    """Networks in address order, so the list reads the way a routing table does."""
    addr, _, bits = str(net).partition('/')
    octets = _octets(addr) or [0, 0, 0, 0]
    try:
        prefix = int(bits)
    except ValueError:
        prefix = 0
    return tuple(octets) + (prefix,)
