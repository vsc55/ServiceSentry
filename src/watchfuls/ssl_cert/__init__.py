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

"""Watchful module to check SSL/TLS certificate expiry."""

import concurrent.futures
import json
import os
import socket
import ssl
import time

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')


class Watchful(ModuleBase):
    """Watchful module to check SSL/TLS certificate expiry."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("SSL Cert: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_items = []
        for (key, value) in self.get_conf('list', {}).items():
            if not isinstance(value, dict):
                continue
            # Host-centric: merge a referenced host's address/port (no-op inline).
            value = self.resolve_host(value)
            enabled = str(value.get('enabled', True)).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            if not enabled:
                continue
            host = (value.get('host', '') or '').strip() or key
            port = int(value.get('port', 0) or 0) or 443
            # SNI / hostname to validate against — defaults to the address.  For
            # a reverse proxy serving several FQDNs on one address, set this to
            # the FQDN whose certificate you want to check.
            server_name = (value.get('server_name', '') or '').strip() or host
            verify = str(value.get('verify', True)).lower() not in ('false', '0', 'no', 'off', 'disable')
            warning_days = int(value.get('warning_days', 0) or 0) or self.get_conf('warning_days', self._MODULE_DEFAULTS['warning_days'])
            timeout = int(value.get('timeout', 0) or 0) or self.get_conf('timeout', self._MODULE_DEFAULTS['timeout'])
            label = (value.get('label', '') or '').strip() or server_name or host or key
            self._debug(f"SSL Cert: {key} - host={host}:{port} sni={server_name} verify={verify} warning_days={warning_days}", DebugLevel.info)
            list_items.append({
                'key': key,
                'label': label,
                'host': host,
                'server_name': server_name,
                'verify': verify,
                'port': port,
                'warning_days': warning_days,
                'timeout': timeout,
            })

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_item = {
                executor.submit(self._ssl_check, item): item
                for item in list_items
            }
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f"SSL Cert: {item['key']} - Exception: {exc}", DebugLevel.error)
                    message = f'SSL Cert: {item.get("label") or item["key"]} - *Error: {exc}* 💥'
                    self.dict_return.set(item['key'], False, message)

        super().check()
        return self.dict_return

    def _ssl_check(self, item):
        key = item['key']
        label = item.get('label') or item['server_name'] or item['host'] or key
        host = item['host']
        server_name = item['server_name']
        verify = item['verify']
        port = item['port']
        warning_days = item['warning_days']
        timeout = item['timeout']

        # Connect to the server's ADDRESS; the SNI/hostname is *server_name*, so
        # a reverse proxy returns (and we validate) the right FQDN certificate.
        ctx = ssl.create_default_context()
        if not verify:
            # Insecure mode: still fetch the cert (e.g. self-signed) to check
            # expiry, but don't fail on chain/hostname/expiry.
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=server_name) as ssock:
                der = ssock.getpeercert(binary_form=True)

        not_after, expires_str = self._cert_expiry(der)
        days_left = (not_after - time.time()) / 86400
        ok = days_left > warning_days

        if ok:
            message = f'SSL Cert: *{label}* - expires in {days_left:.1f} days ✅'
        elif days_left <= 0:
            message = f'SSL Cert: *{label}* - EXPIRED ({abs(days_left):.1f} days ago) ⚠️'
        else:
            message = f'SSL Cert: *{label}* - expires in {days_left:.1f} days (warning threshold: {warning_days}d) ⚠️'

        other_data = {
            'host': host,
            'server_name': server_name,
            'port': port,
            'verify': verify,
            'days_left': round(days_left, 2),
            'expires': expires_str,
        }
        self.dict_return.set(key, ok, message, False, other_data)

        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok)

    @staticmethod
    def _cert_expiry(der: bytes):
        """Return (expiry_epoch_seconds, expiry_iso_str) from a DER certificate.

        Parsed with ``cryptography`` so it works even in insecure mode, where
        ``getpeercert()`` returns no dict (verification disabled)."""
        from cryptography import x509  # noqa: PLC0415
        cert = x509.load_der_x509_certificate(der)
        try:
            dt = cert.not_valid_after_utc            # cryptography >= 42 (tz-aware)
        except AttributeError:                       # older: naive UTC
            import datetime  # noqa: PLC0415
            dt = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp(), dt.strftime('%Y-%m-%d %H:%M:%S UTC')
