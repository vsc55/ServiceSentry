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

"""Watchful module to check DNS resolution for any record type."""

import concurrent.futures
import time

from lib.debug import DebugLevel
from lib.modules import ModuleBase

from . import deps
from .actions import DnsDiscovery
from .defaults import _SCHEMA
from . import client
from . import tables

# What is left here is the module itself: the class, the loop over items and one check.
# Reaching the real dnspython from a package called `dns` moved to deps, the four ways of
# asking a question to client, the record-type knowledge to tables, and discovery to actions.
# See deps.py for the naming trap this package carries.

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')


class Watchful(DnsDiscovery, ModuleBase):
    """Watchful module to check DNS resolution for any record type."""

    ITEM_SCHEMA = _SCHEMA

    # Without dnspython only A/AAAA records can be resolved (via stdlib socket).
    # All other record types (MX, CNAME, TXT, NS, PTR, …) require dnspython.
    MISSING_DEPS: list[str] = [] if deps._HAS_DNSPYTHON else ['dnspython']

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])

    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])

    # Discovery action exposed at /api/v1/modules/watchfuls/dns/discover (read-only).
    WATCHFUL_ACTIONS: frozenset = frozenset({'discover'})
    READ_ONLY_ACTIONS: frozenset = frozenset({'discover'})

    def __init__(self, monitor):
        super().__init__(monitor, __package__)
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
            timeout = (tables._coerce_int(value.get('timeout'))
                       or tables._coerce_int(self.module_default('timeout', self._MODULE_DEFAULTS['timeout']))
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
                    message = self._msg('dns_exc', lbl, exc)
                    self.dict_return.set(item['key'], False, message, name=lbl)

        super().check()
        return self.dict_return

    def _resolve_on_host(self, item, host, record_type, nameserver, timeout):
        """Resolve by running dig/nslookup ON the bound host (host_exec: SSH for a
        remote host, a local subprocess for a local one)."""
        os_ = self.host_os(item)
        cmd = client._remote_dns_cmd(os_, host, record_type, nameserver, timeout)
        out, err, code = self.host_exec(item, cmd, timeout=int(timeout) + 5)
        if os_ == 'windows':
            return client._parse_nslookup(record_type, out)
        parsed = client._parse_dig_short(record_type, out)
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
            elif client._IS_WINDOWS:
                # Inline check on a Windows daemon: use the OS DNS Client, since
                # python.exe's direct dnspython queries are commonly firewalled.
                resolved = client._resolve_win(host, record_type, nameserver, timeout)
            # A/AAAA use stdlib sockets (system resolver); with an explicit
            # nameserver they go through dnspython so the query targets that server.
            elif record_type in tables._SOCKET_TYPES and not nameserver:
                resolved = client._resolve_socket(host, record_type, timeout)
            else:
                resolved = client._resolve_dns(host, record_type, timeout, nameserver)
        except ImportError as exc:
            resolved = []
            error = str(exc)
        except Exception as exc:  # pylint: disable=broad-except
            resolved = []
            error = str(exc)
        response_time = round((time.monotonic() - _t0) * 1000.0, 1)

        ok = bool(resolved)
        if ok and expected:
            if record_type in tables._SOCKET_TYPES:
                # A/AAAA resolve to discrete IPs — require an exact match so
                # e.g. "1.2.3.4" doesn't match "11.2.3.40" by substring.
                ok = any(expected.lower() == r.lower() for r in resolved)
            else:
                ok = any(expected.lower() in r.lower() for r in resolved)

        short = ', '.join(resolved[:3]) + ('…' if len(resolved) > 3 else '')

        if error:
            message = self._msg('dns_error', label, error)
            ok = False
        elif ok:
            message = self._msg('dns_ok', label, short, response_time)
        elif not resolved:
            message = self._msg('dns_no_results', label)
        else:
            message = self._msg('dns_unexpected', label, expected, short)

        other_data = {
            'host': host,
            'record_type': record_type,
            'resolved': resolved,
            'expected': expected,
            'response_time': response_time,
            'name': label,   # display name for the status views (key is a UID)
        }
        # name= keeps the module's own fallback (label, else "<type> <host>"): the key
        # is a UID, so the derived-from-config name would be blank for an unlabelled item.
        self._emit(key, ok, message, other_data, name=label)
