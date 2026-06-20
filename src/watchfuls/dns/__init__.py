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

import concurrent.futures
import json
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
import threading
import time

_IS_WINDOWS = platform.system().lower().startswith('win')

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')

# Detect dnspython by looking for its resolver.py in sys.path, explicitly
# skipping our own directory.  A plain `import dns.resolver` would fail here
# because monitor.py registers *this* file as sys.modules['dns'] before running
# __init__.py, so 'dns.resolver' would resolve to watchfuls/dns/resolver.py
# (which doesn't exist) instead of the installed dnspython package.
def _find_dnspython_dir() -> str | None:
    """Return the path to the installed dnspython package dir, or None."""
    _self_dir = os.path.normcase(os.path.abspath(os.path.dirname(__file__)))
    for _p in sys.path:
        _candidate = os.path.join(_p, 'dns')
        if os.path.normcase(os.path.abspath(_candidate)) == _self_dir:
            continue
        if os.path.isfile(os.path.join(_candidate, 'resolver.py')):
            return _candidate
    return None

_DNSPYTHON_DIR = _find_dnspython_dir()
_HAS_DNSPYTHON: bool = _DNSPYTHON_DIR is not None

# Lazily loaded dnspython submodules (populated on first use): a dict with keys
# 'resolver', 'zone', 'query', 'rdatatype', 'exception' — or None if unavailable.
_dnspython = None
# Guards the sys.modules / sys.path juggling below: check() resolves items in
# parallel threads, so the first non-A queries can race into this loader at once.
_dns_load_lock = threading.Lock()

# Submodules to import; resolver covers normal queries, zone/query/rdatatype AXFR.
_DNSPY_SUBMODULES = ('resolver', 'zone', 'query', 'rdatatype', 'exception')


def _load_dnspython():
    """Import dnspython submodules, bypassing the watchful name collision.

    At call time, __init__.py has finished executing so the import lock for
    'dns' is free.  We temporarily evict ourselves from sys.modules and remove
    watchfuls/ from sys.path so that 'import dns.*' finds dnspython.

    Thread-safe: the global sys.modules/sys.path mutation runs under a lock so
    concurrent first-time callers can't corrupt the 'dns' module mapping.
    Returns the cached submodule dict, or None when dnspython is not installed.
    """
    global _dnspython
    if _dnspython is not None:
        return _dnspython
    if not _HAS_DNSPYTHON:
        return None
    with _dns_load_lock:
        if _dnspython is not None:   # another thread loaded it while we waited
            return _dnspython
        _dnspython = _load_dnspython_locked()
        return _dnspython


def _load_dnspython_locked():
    """Body of :func:`_load_dnspython`, executed while holding the load lock."""
    _watchfuls_dir = os.path.dirname(os.path.dirname(__file__))
    _saved_dns = sys.modules.pop('dns', None)
    for _sub in _DNSPY_SUBMODULES:
        sys.modules.pop(f'dns.{_sub}', None)
    _had_path = _watchfuls_dir in sys.path
    if _had_path:
        sys.path.remove(_watchfuls_dir)
    mods = None
    try:
        import importlib as _il  # noqa: PLC0415
        mods = {name: _il.import_module(f'dns.{name}') for name in _DNSPY_SUBMODULES}
    except ImportError:
        mods = None
    finally:
        if _had_path and _watchfuls_dir not in sys.path:
            sys.path.insert(0, _watchfuls_dir)
        # Restore the watchful as sys.modules['dns'] so future calls to
        # importlib.import_module('dns') still return the correct watchful.
        if _saved_dns is not None:
            sys.modules['dns'] = _saved_dns
    return mods


def _load_dns_resolver():
    """Return the dnspython ``resolver`` submodule, or None if unavailable."""
    mods = _load_dnspython()
    return mods['resolver'] if mods else None

_SOCKET_TYPES = frozenset({'A', 'AAAA'})

# Record types probed at the domain apex during discovery (overridable in the
# schema via the "list" collection's __discovery_probe_types__).
_DEFAULT_PROBE_TYPES = ('A', 'AAAA', 'MX', 'TXT', 'NS', 'SOA', 'CNAME', 'CAA', 'SRV')

# Maps a record type to a UI category (icon/colour + default operator) — the
# category definitions themselves live in schema.json (__discovery_categories__).
_TYPE_CATEGORY = {
    'A': 'address', 'AAAA': 'address', 'CNAME': 'alias',
    'MX': 'mail', 'NS': 'ns', 'SOA': 'ns', 'PTR': 'ns', 'SRV': 'srv',
    'TXT': 'text', 'CAA': 'text',
}


def _coerce_int(value, default: int = 0) -> int:
    """Best-effort int conversion; returns *default* on bad/empty input."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy(value) -> bool:
    """Interpret JSON/string booleans (True, "true", "1", "yes", "on")."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on', 'enable')


def _resolve_socket(host: str, record_type: str, timeout: float) -> list:
    """Resolve A or AAAA records using stdlib socket (no extra deps).

    ``socket.getaddrinfo`` has no native timeout, so it runs in a worker thread
    bounded by ``future.result(timeout=…)``.  On timeout we deliberately call
    ``shutdown(wait=False)`` — using the executor as a context manager would join
    the (still-blocked) worker on exit, defeating the timeout entirely.

    Raises ``TimeoutError`` on timeout and lets non-name-resolution ``OSError``s
    propagate so the caller can report them; a name that simply does not resolve
    (``gaierror``) returns an empty list ("no results").
    """
    family = socket.AF_INET if record_type == 'A' else socket.AF_INET6
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = ex.submit(socket.getaddrinfo, host, None, family)
    try:
        results = future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f'resolution timed out after {timeout}s') from None
    except socket.gaierror:
        return []
    finally:
        # Never wait: a hung getaddrinfo would otherwise block past the timeout.
        ex.shutdown(wait=False)
    return list(dict.fromkeys(r[4][0] for r in results))


def _nameserver_ips(nameserver: str) -> list:
    """Resolve a nameserver spec (IP or hostname) to a list of IPs to query."""
    import ipaddress  # noqa: PLC0415
    ns = (nameserver or '').strip()
    if not ns:
        return []
    try:
        ipaddress.ip_address(ns)
        return [ns]                      # already an IP
    except ValueError:
        pass
    try:                                  # resolve the hostname via the system resolver
        infos = socket.getaddrinfo(ns, 53, proto=socket.IPPROTO_UDP)
        return list(dict.fromkeys(i[4][0] for i in infos))
    except OSError:
        return []


def _resolve_dns(host: str, record_type: str, timeout: float, nameserver: str = '') -> list:
    """Resolve any DNS record type using dnspython. Returns list of string representations.

    When *nameserver* is given (IP or hostname), the query is sent to that server
    instead of the daemon's system resolver — so a specific DNS server can be
    verified."""
    _r = _load_dns_resolver()
    if _r is None:
        raise ImportError(
            f"dnspython not installed — cannot query {record_type} records. "
            "Install it with: pip install dnspython"
        )
    resolver = _r.Resolver()
    resolver.lifetime = float(timeout)
    if nameserver:
        ips = _nameserver_ips(nameserver)
        if not ips:
            raise ValueError(f'could not resolve nameserver "{nameserver}"')
        resolver.nameservers = ips
    try:
        answers = resolver.resolve(host, record_type)
    except (_r.NXDOMAIN, _r.NoAnswer):
        return []

    result = []
    for rdata in answers:
        rt = record_type.upper()
        if rt in ('A', 'AAAA'):
            result.append(str(rdata))
        elif rt == 'CNAME':
            result.append(str(rdata.target).rstrip('.'))
        elif rt == 'MX':
            result.append(f'{rdata.preference} {str(rdata.exchange).rstrip(".")}')
        elif rt == 'TXT':
            result.append(b''.join(rdata.strings).decode('utf-8', errors='replace'))
        elif rt in ('NS', 'PTR'):
            result.append(str(rdata.target).rstrip('.'))
        elif rt == 'SOA':
            result.append(f'{str(rdata.mname).rstrip(".")} serial={rdata.serial}')
        else:
            result.append(str(rdata))
    return result


# ── Windows daemon resolution (Resolve-DnsName) ───────────────────────────────
# On Windows, python.exe's direct DNS queries (dnspython) are often blocked by
# the firewall even though the OS DNS Client resolves fine.  Use Resolve-DnsName
# (structured JSON) for daemon-side resolution there.
_DNS_TYPE_NUM = {'A': 1, 'AAAA': 28, 'NS': 2, 'CNAME': 5, 'SOA': 6,
                 'PTR': 12, 'MX': 15, 'TXT': 16, 'SRV': 33}


def _psq(s: str) -> str:
    """Quote a value for a PowerShell single-quoted string."""
    return "'" + str(s).replace("'", "''") + "'"


def _parse_resolve_dnsname(record_type: str, records: list) -> list:
    """Map Resolve-DnsName JSON records to the same strings as _resolve_dns,
    keeping only the queried type (the cmdlet also returns additional records)."""
    rt = record_type.upper()
    want = _DNS_TYPE_NUM.get(rt)
    out = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if want is not None and rec.get('Type') != want:
            continue
        if rt in ('A', 'AAAA'):
            v = rec.get('IPAddress')
            if v:
                out.append(str(v))
        elif rt == 'MX':
            ex = rec.get('NameExchange')
            if ex:
                out.append(f"{rec.get('Preference')} {ex}")
        elif rt in ('NS', 'CNAME', 'PTR'):
            v = rec.get('NameHost')
            if v:
                out.append(str(v))
        elif rt == 'TXT':
            s = rec.get('Strings')
            out.append(''.join(s) if isinstance(s, list) else str(s or ''))
        elif rt == 'SOA':
            ps = rec.get('PrimaryServer')
            if ps:
                out.append(f"{ps} serial={rec.get('SerialNumber')}")
        else:
            for k in ('IPAddress', 'NameHost', 'NameExchange'):
                if rec.get(k):
                    out.append(str(rec[k]))
                    break
    return out


def _resolve_win(host: str, record_type: str, nameserver: str, timeout: float) -> list:
    """Resolve via the Windows DNS Client (Resolve-DnsName) — works where direct
    dnspython queries from python.exe are firewall-blocked."""
    ns = f' -Server {_psq(nameserver)}' if nameserver else ''
    ps = (f"Resolve-DnsName -Name {_psq(host)} -Type {record_type.upper()}{ns} -DnsOnly -ErrorAction Stop "
          "| Select-Object Name,Type,NameExchange,Preference,NameHost,IPAddress,Strings,PrimaryServer,SerialNumber "
          "| ConvertTo-Json -Compress -Depth 4")
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
            capture_output=True, text=True, timeout=float(timeout) + 5)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f'Resolve-DnsName timed out after {timeout}s') from None
    out = (r.stdout or '').strip()
    if not out:
        return []   # NXDOMAIN / NoAnswer (cmdlet errors → empty stdout)
    try:
        data = json.loads(out)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return _parse_resolve_dnsname(record_type, data)


# ── Remote resolution (run on a bound host via SSH) ───────────────────────────
def _remote_dns_cmd(os_: str, host: str, record_type: str, nameserver: str, timeout: int) -> str:
    """Build the DNS query command to run ON the bound host.

    Unix uses ``dig`` (clean, parseable); Windows uses ``nslookup``.  The
    nameserver, when given, directs the query at that server."""
    if os_ == 'windows':
        ns = f' {nameserver}' if nameserver else ''
        return f'nslookup -type={record_type} {host}{ns}'
    t = max(1, int(timeout))
    ns = (' @' + shlex.quote(nameserver)) if nameserver else ''
    return f'dig +short +time={t} +tries=1 {shlex.quote(record_type)} {shlex.quote(host)}{ns}'


def _parse_dig_short(record_type: str, out: str) -> list:
    """Parse ``dig +short`` output into the same string form as _resolve_dns."""
    rt = record_type.upper()
    results = []
    for line in (out or '').splitlines():
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        if rt == 'TXT':
            line = line.strip('"')
        elif rt == 'SOA':
            toks = line.split()
            line = f'{toks[0].rstrip(".")} serial={toks[2]}' if len(toks) >= 3 else line.rstrip('.')
        else:
            line = line.rstrip('.')
        results.append(line)
    return results


def _parse_nslookup(record_type: str, out: str) -> list:
    """Best-effort parse of Windows ``nslookup`` output (the first Address is the
    queried server itself, so it is skipped)."""
    rt = record_type.upper()
    results = []
    lines = (out or '').splitlines()
    # Drop the server header block (up to the first blank line after "Server:").
    started = False
    for line in lines:
        s = line.strip()
        if s.lower().startswith('name:') or 'non-authoritative' in s.lower():
            started = True
        if not started:
            continue
        low = s.lower()
        if rt in ('A', 'AAAA') and (low.startswith('address:') or low.startswith('addresses:')):
            results.append(s.split(':', 1)[1].strip())
        elif rt == 'MX' and 'mail exchanger' in low:
            results.append(s.split('=', 1)[1].strip().rstrip('.'))
        elif rt in ('CNAME', 'NS', 'PTR') and '=' in s and ('canonical' in low or 'nameserver' in low or 'name =' in low):
            results.append(s.split('=', 1)[1].strip().rstrip('.'))
        elif rt == 'TXT' and 'text =' in low:
            results.append(s.split('=', 1)[1].strip().strip('"'))
    return results


class Watchful(ModuleBase):
    """Watchful module to check DNS resolution for any record type."""

    ITEM_SCHEMA = _SCHEMA

    # Without dnspython only A/AAAA records can be resolved (via stdlib socket).
    # All other record types (MX, CNAME, TXT, NS, PTR, …) require dnspython.
    MISSING_DEPS: list[str] = [] if _HAS_DNSPYTHON else ['dnspython']

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])

    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])

    # Discovery action exposed at /api/v1/watchfuls/dns/discover (read-only).
    WATCHFUL_ACTIONS: frozenset = frozenset({'discover'})
    READ_ONLY_ACTIONS: frozenset = frozenset({'discover'})

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

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
        timeout = _coerce_int(config.get('timeout'), 5) or 5
        # Host-aware: the Servers modal injects the bound host; when it is remote,
        # probe from THERE (over SSH) so a host that reaches the DNS discovers.
        from lib.hosts import runner as host_runner  # noqa: PLC0415
        host = config.get('__host__') if isinstance(config, dict) else None
        if _truthy(inp.get('axfr')):
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
        return list(_DEFAULT_PROBE_TYPES)

    @classmethod
    def _discover_probe(cls, domain: str, timeout: int) -> list:
        """Probe each candidate record type at the apex (in parallel)."""
        types = cls._probe_types()

        def _probe(rt: str):
            try:
                if _IS_WINDOWS:
                    # Daemon on Windows: use the OS DNS Client (Resolve-DnsName);
                    # python.exe's direct dnspython queries are often firewalled.
                    resolved = _resolve_win(domain, rt, '', timeout)
                elif rt in _SOCKET_TYPES and not _HAS_DNSPYTHON:
                    resolved = _resolve_socket(domain, rt, timeout)
                else:
                    resolved = _resolve_dns(domain, rt, timeout)
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
            'category': _TYPE_CATEGORY.get(rt, 'other'), 'status': 'found',
        }

    @classmethod
    def _discover_probe_remote(cls, host: dict, domain: str, timeout: int) -> list:
        """Probe record types by running dig/nslookup ON the bound host (SSH), so
        a host that can reach the (internal) DNS does the discovery."""
        from lib.hosts import runner as host_runner  # noqa: PLC0415
        os_ = str((host or {}).get('os') or 'linux').strip().lower()
        types = cls._probe_types()
        if os_ == 'windows':
            out = []
            for rt in types:
                res, _e, _c = host_runner.run(
                    host, _remote_dns_cmd('windows', domain, rt, '', timeout), timeout=timeout + 3)
                resolved = _parse_nslookup(rt, res)
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
                resolved = _parse_dig_short(cur_rt, '\n'.join(buf))
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
        mods = _load_dnspython()
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
                    'category': _TYPE_CATEGORY.get(rtype, 'other'), 'status': 'found',
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

    def check(self):
        if not self.is_enabled:
            self._debug("DNS: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_items = []
        for (key, raw) in self.get_conf('list', {}).items():
            if not isinstance(raw, dict):
                continue
            # Host-centric: when bound to a host, inject its SSH connection / OS /
            # kind so the query can run ON that host (no-op for inline checks).
            value = self.resolve_host(raw)
            if value.get('_host_maintenance'):
                continue
            enabled = str(value.get('enabled', True)).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            if not enabled:
                continue
            host = (value.get('host', '') or '').strip() or key
            record_type = (value.get('record_type', '') or '').strip().upper() or 'A'
            # Per-item nameserver, or the module-wide default, or the system
            # resolver (blank) — same "item overrides global" pattern as timeout.
            nameserver = ((value.get('nameserver', '') or '').strip()
                          or str(self.get_conf('nameserver',
                                  self._MODULE_DEFAULTS.get('nameserver', '')) or '').strip())
            label = (value.get('label', '') or '').strip()
            expected = (value.get('expected', '') or '').strip()
            # Robust parse: a hand-edited / migrated non-numeric value must not
            # raise here (the loop runs in the main thread — it would abort the
            # whole module check instead of failing just this item).
            timeout = (_coerce_int(value.get('timeout'))
                       or _coerce_int(self.module_default('timeout', self._MODULE_DEFAULTS['timeout']))
                       or self._MODULE_DEFAULTS['timeout'])
            self._debug(f"DNS: {self.item_label(key)} - host={host} type={record_type} expected={expected!r}", DebugLevel.info)
            # Carry the resolved value (ssh_*, host_os, host_kind) plus the
            # cleaned check fields so _dns_check can run locally or over SSH.
            item = dict(value)
            item.update({
                'key': key,
                'host': host,
                'record_type': record_type,
                'nameserver': nameserver,
                'label': label,
                'expected': expected,
                'timeout': timeout,
            })
            list_items.append(item)

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, self.module_default('threads', self._default_threads))) as executor:
            future_to_item = {
                executor.submit(self._dns_check, item): item
                for item in list_items
            }
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f"DNS: {item['key']} - Exception: {exc}", DebugLevel.error)
                    lbl = item.get('label') or f'{item["record_type"]} {item["host"]}'
                    message = f'DNS: {lbl} - *Error: {exc}* 💥'
                    self.dict_return.set(item['key'], False, message)

        super().check()
        return self.dict_return

    def _resolve_on_host(self, item, host, record_type, nameserver, timeout):
        """Resolve by running dig/nslookup ON the bound host (host_exec: SSH for a
        remote host, a local subprocess for a local one)."""
        os_ = self.host_os(item)
        cmd = _remote_dns_cmd(os_, host, record_type, nameserver, timeout)
        out, err, code = self.host_exec(item, cmd, timeout=int(timeout) + 5)
        if os_ == 'windows':
            return _parse_nslookup(record_type, out)
        parsed = _parse_dig_short(record_type, out)
        # dig: empty output with a non-zero exit means the query failed (e.g. the
        # server timed out / is unreachable from the host) — surface it.
        if not parsed and code != 0:
            raise OSError((err or out or f'dig exited {code}').strip())
        return parsed

    def _dns_check(self, item):
        key = item['key']
        host = item['host']
        record_type = item['record_type']
        nameserver = item.get('nameserver', '')
        # Editable display name (e.g. "MX cerebelum.lan"); the key is an opaque UID.
        label = (item.get('label', '') or '').strip() or f'{record_type} {host}'
        expected = item['expected']
        timeout = item['timeout']

        error = None
        _t0 = time.monotonic()
        try:
            if item.get('host_kind'):
                # Bound to a host: run the query THERE via dig/nslookup — over SSH
                # for a remote host, or as a local subprocess for a local host.
                # host_exec picks the transport; only INLINE checks (no host) use
                # the daemon's in-process resolver below.
                resolved = self._resolve_on_host(item, host, record_type, nameserver, timeout)
            elif _IS_WINDOWS:
                # Inline check on a Windows daemon: use the OS DNS Client, since
                # python.exe's direct dnspython queries are commonly firewalled.
                resolved = _resolve_win(host, record_type, nameserver, timeout)
            # A/AAAA use stdlib sockets (system resolver); with an explicit
            # nameserver they go through dnspython so the query targets that server.
            elif record_type in _SOCKET_TYPES and not nameserver:
                resolved = _resolve_socket(host, record_type, timeout)
            else:
                resolved = _resolve_dns(host, record_type, timeout, nameserver)
        except ImportError as exc:
            resolved = []
            error = str(exc)
        except Exception as exc:  # pylint: disable=broad-except
            resolved = []
            error = str(exc)
        response_time = round((time.monotonic() - _t0) * 1000.0, 1)

        ok = bool(resolved)
        if ok and expected:
            if record_type in _SOCKET_TYPES:
                # A/AAAA resolve to discrete IPs — require an exact match so
                # e.g. "1.2.3.4" doesn't match "11.2.3.40" by substring.
                ok = any(expected.lower() == r.lower() for r in resolved)
            else:
                ok = any(expected.lower() in r.lower() for r in resolved)

        short = ', '.join(resolved[:3]) + ('…' if len(resolved) > 3 else '')

        if error:
            message = f'DNS: *{label}*: {error} ⚠️'
            ok = False
        elif ok:
            message = f'DNS: *{label}* → {short} ({response_time} ms) ✅'
        elif not resolved:
            message = f'DNS: *{label}*: no results ⚠️'
        else:
            message = f'DNS: *{label}*: expected "{expected}" not in [{short}] ⚠️'

        other_data = {
            'host': host,
            'record_type': record_type,
            'resolved': resolved,
            'expected': expected,
            'response_time': response_time,
            'name': label,   # display name for the status views (key is a UID)
        }
        self.dict_return.set(key, ok, message, False, other_data)

        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok)
