#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSentry
#
# Copyright © 2019  Javier Pastor (aka VSC55)
# <jpastor at cerebelum dot net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Watchful module to check DNS resolution for any record type."""

"""Discovery: ask a domain what it has, so nobody types record types from memory.

Probes the apex for a handful of types, and where the zone allows it, asks for the whole
thing at once (AXFR) - which turns "add a check per record" from an afternoon into a
selection. Runs locally, or over SSH on the bound host when the item has one, because a
record can resolve differently depending on where you stand.
"""

import concurrent.futures
import re
import shlex
import socket

from . import deps
from .defaults import _SCHEMA
from . import client
from . import tables


class DnsDiscovery:
    """The ``discover`` action and everything it needs. Mixed into ``Watchful``."""

    # ── Discovery ───────────────────────────────────────────────────────────
    @classmethod
    def discover(cls, config=None) -> list:
        """Discover DNS records for a domain.

        Input arrives in ``config['_discovery_input']`` (the route strips
        ``__dunder__`` keys, so a single-underscore key is used):
            {domain, axfr (bool), axfr_server}

        Default mode probes a configurable set of record types at the domain
        apex and returns those that exist.  With ``axfr`` enabled it attempts a
        full zone transfer (only works when the authoritative server allows it).
        Returns ``[{name, record_type, value, category, status}]``.
        """
        config = config or {}
        inp = config.get('_discovery_input') or {}
        domain = str(inp.get('domain') or '').strip().rstrip('.')
        if not domain:
            return []
        timeout = tables._coerce_int(config.get('timeout'), 5) or 5
        # Host-aware: the Servers modal injects the bound host; when it is remote,
        # probe from THERE (over SSH) so a host that reaches the DNS discovers.
        from lib.core.hosts import runner as host_runner  # noqa: PLC0415
        host = config.get('__host__') if isinstance(config, dict) else None
        if tables._truthy(inp.get('axfr')):
            try:
                return cls._discover_axfr(domain, str(inp.get('axfr_server') or '').strip(), timeout)
            except Exception:  # pylint: disable=broad-except
                # AXFR is best-effort (usually refused on public zones) — never
                # 500; an empty result reads as "no records transferable".
                return []
        if host_runner.is_remote(host):
            return cls._discover_probe_remote(host, domain, timeout)
        return cls._discover_probe(domain, timeout)

    @classmethod
    def _probe_types(cls) -> list:
        types = _SCHEMA.get('list', {}).get('__discovery_probe_types__')
        if isinstance(types, list) and types:
            return [str(t).strip().upper() for t in types if str(t).strip()]
        return list(tables._DEFAULT_PROBE_TYPES)

    @classmethod
    def _discover_probe(cls, domain: str, timeout: int) -> list:
        """Probe each candidate record type at the apex (in parallel)."""
        types = cls._probe_types()

        def _probe(rt: str):
            try:
                if client._IS_WINDOWS:
                    # Daemon on Windows: use the OS DNS Client (Resolve-DnsName);
                    # python.exe's direct dnspython queries are often firewalled.
                    resolved = client._resolve_win(domain, rt, '', timeout)
                elif rt in tables._SOCKET_TYPES and not deps._HAS_DNSPYTHON:
                    resolved = client._resolve_socket(domain, rt, timeout)
                else:
                    resolved = client._resolve_dns(domain, rt, timeout)
            except Exception:  # pylint: disable=broad-except
                return None
            if not resolved:
                return None
            return cls._probe_record(domain, rt, resolved)

        out = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(types))) as ex:
            for res in ex.map(_probe, types):
                if res:
                    out.append(res)
        return out

    @staticmethod
    def _probe_record(domain: str, rt: str, resolved: list) -> dict:
        value = ', '.join(resolved[:3]) + ('…' if len(resolved) > 3 else '')
        return {
            'name': domain, 'record_type': rt, 'value': value,
            'fill_value': resolved[0],   # pre-fills the "expected" field
            'category': tables._TYPE_CATEGORY.get(rt, 'other'), 'status': 'found',
        }

    @classmethod
    def _discover_probe_remote(cls, host: dict, domain: str, timeout: int) -> list:
        """Probe record types by running dig/nslookup ON the bound host (SSH), so
        a host that can reach the (internal) DNS does the discovery."""
        from lib.core.hosts import runner as host_runner  # noqa: PLC0415
        os_ = str((host or {}).get('os') or 'linux').strip().lower()
        types = cls._probe_types()
        if os_ == 'windows':
            out = []
            for rt in types:
                res, _e, _c = host_runner.run(
                    host, client._remote_dns_cmd('windows', domain, rt, '', timeout), timeout=timeout + 3)
                resolved = client._parse_nslookup(rt, res)
                if resolved:
                    out.append(cls._probe_record(domain, rt, resolved))
            return out
        # One SSH call running a dig per type, separated by markers — avoids a
        # connection per record type.
        t = max(1, int(timeout))
        script = '; '.join(
            f'echo "##{rt}##"; dig +short +time={t} +tries=1 {shlex.quote(rt)} {shlex.quote(domain)}'
            for rt in types)
        res, _e, _c = host_runner.run(host, script, timeout=t * len(types) + 5)
        return cls._parse_combined_dig(domain, res)

    @classmethod
    def _parse_combined_dig(cls, domain: str, out: str) -> list:
        """Parse the marker-separated combined dig output into found records."""
        records, cur_rt, buf = [], None, []

        def _flush():
            if cur_rt and buf:
                resolved = client._parse_dig_short(cur_rt, '\n'.join(buf))
                if resolved:
                    records.append(cls._probe_record(domain, cur_rt, resolved))

        for line in (out or '').splitlines():
            m = re.match(r'^##(\w+)##$', line.strip())
            if m:
                _flush()
                cur_rt, buf = m.group(1), []
            else:
                buf.append(line)
        _flush()
        return records

    @classmethod
    def _discover_axfr(cls, domain: str, server: str, timeout: int) -> list:
        """Attempt a full zone transfer (AXFR) and list every record."""
        mods = deps._load_dnspython()
        if not mods:
            raise ImportError('dnspython is required for AXFR (pip install dnspython)')
        ns_ip = cls._axfr_server_ip(domain, server, timeout, mods)
        zone = mods['zone'].from_xfr(
            mods['query'].xfr(ns_ip, domain, lifetime=float(timeout)))
        to_text = mods['rdatatype'].to_text
        out = []
        for name, node in zone.nodes.items():
            rel = str(name)
            fqdn = domain if rel in ('@', '') else f'{rel}.{domain}'
            for rdataset in node.rdatasets:
                rtype = to_text(rdataset.rdtype)
                values = [rd.to_text() for rd in rdataset]
                value = ', '.join(values[:3]) + ('…' if len(values) > 3 else '')
                out.append({
                    'name': fqdn, 'record_type': rtype, 'value': value,
                    'fill_value': values[0] if values else '',
                    'category': tables._TYPE_CATEGORY.get(rtype, 'other'), 'status': 'found',
                })
        return out

    @staticmethod
    def _axfr_server_ip(domain: str, server: str, timeout: int, mods) -> str:
        """Resolve the nameserver IP to transfer from (explicit, or the zone's NS)."""
        target = server
        if not target:
            resolver = mods['resolver'].Resolver()
            resolver.lifetime = float(timeout)
            target = str(resolver.resolve(domain, 'NS')[0].target).rstrip('.')
        try:
            return socket.getaddrinfo(target, None)[0][4][0]
        except OSError:
            return target  # already an IP, or let xfr() surface the error
