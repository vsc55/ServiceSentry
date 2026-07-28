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

"""Asking a DNS question - four ways, because one is never enough.

Straight through the socket for A/AAAA/PTR, dnspython for everything else, PowerShell's
Resolve-DnsName on Windows (where python.exe's own queries are often blocked by the firewall
while the OS DNS client resolves fine), and dig/nslookup over SSH when the question has to be
asked from a bound host rather than from here.

A check decides WHAT to look up and what the answer means. This decides how to ask.
"""

import concurrent.futures
import json
import platform
import shlex
import socket
import subprocess

from . import deps

_IS_WINDOWS = platform.system().lower().startswith('win')


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
    _r = deps._load_dns_resolver()
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
        # cmd.exe (host_exec shell=True): double-quote to neutralise & | < > ^; strip
        # embedded quotes so a config value can't break out and inject a command. (Does not
        # stop %VAR% expansion — no RCE, value is admin/config-controlled.)
        def _wq(s):
            return '"' + str(s).replace('"', '') + '"'
        ns = f' {_wq(nameserver)}' if nameserver else ''
        return f'nslookup -type={_wq(record_type)} {_wq(host)}{ns}'
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
