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
asked from a bound device rather than from here.

A check decides WHAT to look up and what the answer means. This decides how to ask.
"""

import concurrent.futures
import ipaddress
import json
import platform
import re
import shlex
import socket
import subprocess

from . import deps
from . import tables

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
    # The type goes in UNQUOTED (it is an enum argument), so it is whitelisted first: a
    # stored `A;<command>` used to run in this PowerShell, on the panel.
    rt = tables.safe_record_type(record_type)
    ns = f' -Server {_psq(nameserver)}' if nameserver else ''
    ps = (f"Resolve-DnsName -Name {_psq(host)} -Type {rt}{ns} -DnsOnly -ErrorAction Stop "
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


# ── Remote resolution (run on a bound device via SSH) ───────────────────────────
def _remote_dns_cmd(os_: str, host: str, record_type: str, nameserver: str, timeout: int) -> str:
    """Build the DNS query command to run ON the bound device.

    Unix uses ``dig`` (clean, parseable); Windows uses ``nslookup``.  The
    nameserver, when given, directs the query at that server."""
    record_type = tables.safe_record_type(record_type)
    if os_ == 'windows':
        # The remote shell is cmd.exe OR PowerShell (Windows OpenSSH's DefaultShell), and no
        # quoting is safe in both: cmd.exe double quotes leave PowerShell's "$(...)"
        # live, and PowerShell single quotes are literal characters to cmd.exe. So the VALUES
        # are restricted instead - a hostname or an IP has no character either shell
        # interprets inside double quotes - and refused otherwise, before anything runs.
        host_ = _safe_dns_name(host)
        ns = f' "{_safe_dns_name(nameserver)}"' if nameserver else ''
        return f'nslookup -type={record_type} "{host_}"{ns}'
    t = max(1, int(timeout))
    ns = (' @' + shlex.quote(nameserver)) if nameserver else ''
    return f'dig +short +time={t} +tries=1 {shlex.quote(record_type)} {shlex.quote(host)}{ns}'


_DNS_NAME_RE = re.compile(r'^[A-Za-z0-9_.:\-]{1,253}$')


def _safe_dns_name(value) -> str:
    """*value* when it is a hostname or an IP literal, else ``ValueError``.

    Letters, digits, ``_ . - :`` (``_`` for SRV-style labels, ``:`` for IPv6) and nothing
    else: no quote, ``$``, backtick, ``%`` or separator either Windows shell would act on."""
    v = str(value or '').strip()
    if not _DNS_NAME_RE.match(v) or v.startswith('-'):
        raise ValueError(f'invalid host name {v[:40]!r}')
    return v


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


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _parse_nslookup(record_type: str, out: str) -> list:
    """Best-effort parse of Windows ``nslookup`` output.

    The first block (up to the first blank line) names the server that answered — its
    ``Address:`` is the server itself, not an answer — so it is skipped by POSITION. It used
    to be skipped until an English ``Name:`` or ``Non-authoritative answer:`` showed up, and
    those headers are localised (``Nombre:``, ``Respuesta no autoritativa:``): on a Spanish
    Windows nothing was ever read. The record lines themselves are not localised.

    Two shapes need more than one line: several addresses continue on indented lines under
    ``Addresses:``, and a TXT record prints ``text =`` with its strings on the lines after it
    (a long record split into several quoted strings is joined, as dnspython does)."""
    rt = record_type.upper()
    results = []
    lines = (out or '').splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines) and lines[i].strip():
        i += 1
    in_addr = False
    txt_buf = None          # list of strings of the TXT record being read, or None

    def _flush_txt():
        nonlocal txt_buf
        if txt_buf:
            results.append(''.join(txt_buf))
        txt_buf = None

    for line in lines[i:]:
        s = line.strip()
        low = s.lower()
        if not s:
            in_addr = False
            continue
        if rt in ('A', 'AAAA'):
            # By SHAPE, not by the label: the label is localised (Address, Dirección,
            # Adresse, Indirizzo...) and a list of words only ever covers the languages
            # somebody thought of. Past the server block, "<word>: <ip>" is an answer and an
            # indented bare IP continues a multi-address list.
            head, sep, val = s.partition(':')
            if in_addr and line[:1].isspace() and _is_ip(s):
                results.append(s)
            elif sep and not _is_ip(s) and _is_ip(val.strip()):
                results.append(val.strip())
                in_addr = True
            elif sep and not _is_ip(s) and not val.strip():
                in_addr = True          # "Addresses:" with every address on the next lines
            else:
                in_addr = False
        elif rt == 'MX' and 'mail exchanger' in low:
            # "MX preference = 10, mail exchanger = mx.example" → "10 mx.example", the form
            # dig and dnspython give. Splitting on the FIRST "=" kept the whole tail.
            pref = low.split('preference', 1)[1].split('=', 1)[1].split(',', 1)[0].strip() \
                if 'preference' in low else ''
            exch = s[low.index('mail exchanger'):].split('=', 1)[1].strip().rstrip('.')
            results.append(f'{pref} {exch}'.strip())
        elif rt in ('CNAME', 'NS', 'PTR') and '=' in s and ('canonical' in low or 'nameserver' in low or 'name =' in low):
            results.append(s.split('=', 1)[1].strip().rstrip('.'))
        elif rt == 'TXT':
            if 'text =' in low:
                _flush_txt()
                txt_buf = []
                val = s.split('=', 1)[1].strip()
                if val:
                    txt_buf.append(val.strip('"'))
            elif txt_buf is not None and s.startswith('"'):
                txt_buf.append(s.strip('"'))
            else:
                _flush_txt()
    if rt == 'TXT':
        _flush_txt()
    return results
