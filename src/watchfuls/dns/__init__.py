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
import socket
import sys
import threading
import time

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


def _resolve_dns(host: str, record_type: str, timeout: float) -> list:
    """Resolve any DNS record type using dnspython. Returns list of string representations."""
    _r = _load_dns_resolver()
    if _r is None:
        raise ImportError(
            f"dnspython not installed — cannot query {record_type} records. "
            "Install it with: pip install dnspython"
        )
    resolver = _r.Resolver()
    resolver.lifetime = float(timeout)
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


class Watchful(ModuleBase):
    """Watchful module to check DNS resolution for any record type."""

    ITEM_SCHEMA = _SCHEMA

    # Without dnspython only A/AAAA records can be resolved (via stdlib socket).
    # All other record types (MX, CNAME, TXT, NS, PTR, …) require dnspython.
    MISSING_DEPS: list[str] = [] if _HAS_DNSPYTHON else ['dnspython']

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

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
        if _truthy(inp.get('axfr')):
            try:
                return cls._discover_axfr(domain, str(inp.get('axfr_server') or '').strip(), timeout)
            except Exception:  # pylint: disable=broad-except
                # AXFR is best-effort (usually refused on public zones) — never
                # 500; an empty result reads as "no records transferable".
                return []
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
                if rt in _SOCKET_TYPES and not _HAS_DNSPYTHON:
                    resolved = _resolve_socket(domain, rt, timeout)
                else:
                    resolved = _resolve_dns(domain, rt, timeout)
            except Exception:  # pylint: disable=broad-except
                return None
            if not resolved:
                return None
            value = ', '.join(resolved[:3]) + ('…' if len(resolved) > 3 else '')
            return {
                'name': domain, 'record_type': rt, 'value': value,
                'fill_value': resolved[0],   # pre-fills the "expected" field
                'category': _TYPE_CATEGORY.get(rt, 'other'), 'status': 'found',
            }

        out = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(types))) as ex:
            for res in ex.map(_probe, types):
                if res:
                    out.append(res)
        return out

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
        for (key, value) in self.get_conf('list', {}).items():
            if not isinstance(value, dict):
                continue
            enabled = str(value.get('enabled', True)).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            if not enabled:
                continue
            host = (value.get('host', '') or '').strip() or key
            record_type = (value.get('record_type', '') or '').strip().upper() or 'A'
            expected = (value.get('expected', '') or '').strip()
            # Robust parse: a hand-edited / migrated non-numeric value must not
            # raise here (the loop runs in the main thread — it would abort the
            # whole module check instead of failing just this item).
            timeout = (_coerce_int(value.get('timeout'))
                       or _coerce_int(self.get_conf('timeout', self._MODULE_DEFAULTS['timeout']))
                       or self._MODULE_DEFAULTS['timeout'])
            self._debug(f"DNS: {key} - host={host} type={record_type} expected={expected!r}", DebugLevel.info)
            list_items.append({
                'key': key,
                'host': host,
                'record_type': record_type,
                'expected': expected,
                'timeout': timeout,
            })

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
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
                    message = f'DNS: {item["key"]} - *Error: {exc}* 💥'
                    self.dict_return.set(item['key'], False, message)

        super().check()
        return self.dict_return

    def _dns_check(self, item):
        key = item['key']
        host = item['host']
        record_type = item['record_type']
        expected = item['expected']
        timeout = item['timeout']

        error = None
        _t0 = time.monotonic()
        try:
            if record_type in _SOCKET_TYPES:
                resolved = _resolve_socket(host, record_type, timeout)
            else:
                resolved = _resolve_dns(host, record_type, timeout)
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
            message = f'DNS: *{key}* - {record_type} {host}: {error} ⚠️'
            ok = False
        elif ok:
            message = f'DNS: *{key}* - {record_type} {host} → {short} ({response_time} ms) ✅'
        elif not resolved:
            message = f'DNS: *{key}* - {record_type} {host}: no results ⚠️'
        else:
            message = f'DNS: *{key}* - {record_type} {host}: expected "{expected}" not in [{short}] ⚠️'

        other_data = {
            'host': host,
            'record_type': record_type,
            'resolved': resolved,
            'expected': expected,
            'response_time': response_time,
        }
        self.dict_return.set(key, ok, message, False, other_data)

        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok)
