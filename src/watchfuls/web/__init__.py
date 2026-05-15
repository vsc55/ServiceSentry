#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Lorenzo Carbonell (aka atareao)
# <lorenzo.carbonell.cerezo at gmail dot com>
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
""" Watchful to check web status. """

import concurrent.futures
import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


@dataclass
class WebResult:
    """ Dataclass to represent the result of a web check. """
    status: int
    reason: str

class Watchful(ModuleBase):
    """ Class to check web status. """

    ITEM_SCHEMA = _SCHEMA

    # Default values are derived from schema.json so there is a single
    # source of truth that the web UI can also consume.
    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    # Module-level fallbacks: used when item value is 0 and module config is also absent.
    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("Web: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_url = []
        for (key, value) in self.get_conf('list', {}).items():
            is_enabled = self._DEFAULTS['enabled']
            match value:
                case bool():
                    # Legacy support: if the value is a boolean, use it directly as enabled/disabled
                    # and treat the key as the URL.
                    is_enabled = value
                    url = key
                    verify_ssl = True
                    scheme = 'https'
                    self._debug(
                        f"[Deprecate] Check: {url} - Enabled: {is_enabled}. Please update format.",
                        DebugLevel.warning
                    )

                case dict():
                    # New format: value is a dict with possible 'enabled', 'url', 'scheme',
                    # and 'verify_ssl' keys.
                    is_enabled = value.get("enabled", is_enabled)
                    url = (value.get('url', '') or '').strip() or key
                    scheme = (value.get('scheme', '') or 'https').strip()
                    verify_ssl = bool(value.get('verify_ssl', True))
                    self._debug(f"Check: {url} - Enabled: {is_enabled}", DebugLevel.info)

                case _:
                    # If the value is neither a bool nor a dict, use the default enabled state
                    # and the key as URL.
                    url = key
                    verify_ssl = True
                    scheme = 'https'
                    self._debug(
                        f"Check: {url} - Unknown configuration format, using default enabled={is_enabled}.",
                        DebugLevel.warning
                    )

            if is_enabled:
                list_url.append((key, url, verify_ssl, scheme))

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.get_conf('threads', self._DEFAULT_THREADS)) as executor:
            future_to_url = {
                executor.submit(self._web_check, name, url, verify_ssl, scheme): name
                for name, url, verify_ssl, scheme in list_url
            }
            for future in concurrent.futures.as_completed(future_to_url):
                name = future_to_url[future]
                try:
                    future.result()

                except Exception as exc: # pylint: disable=broad-except
                    self._debug(f"Check: {name} - Exception: {exc}", DebugLevel.error)
                    message = f'Check: {name} - Error: {exc} 💥'
                    self.dict_return.set(name, False, message)

        super().check()
        return self.dict_return

    def _web_check(self, name, url, verify_ssl=True, scheme='https'):
        code_true = self.get_conf_in_list("code",    name, 0) or self.get_conf('code',    self._MODULE_DEFAULTS['code'])
        timeout   = self.get_conf_in_list("timeout", name, 0) or self.get_conf('timeout', self._MODULE_DEFAULTS['timeout'])

        status_code: int = self._web_return(url, timeout, verify_ssl, scheme)
        status: bool = status_code == code_true

        icon = '🔼' if status else '🔽'
        s_message = f'Web: {name} {icon}'

        other_data = {
            'code': status_code,
        }
        self.dict_return.set(name, status, s_message, False, other_data)

        if self.check_status(status, self.name_module, name):
            self.send_message(s_message, status)

    def _web_return(self, url, timeout=15, verify_ssl=True, scheme='https') -> int:
        """Return the HTTP status code for *url* using native Python.

        Supports both ``http://`` and ``https://`` URLs.  If the URL does not
        include a scheme, the *scheme* parameter is used (default: ``https``).
        When *verify_ssl* is False and the URL is HTTPS, certificate
        verification is disabled.
        Returns the integer status code, or 0 on connection error.
        """
        target = url if '://' in url else f'{scheme}://{url}'
        try:
            req = urllib.request.Request(
                target,
                method='GET',
                headers={'User-Agent': 'ServiceSentry/1.0'},
            )
            kwargs = {}
            if not verify_ssl and target.startswith('https://'):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                kwargs['context'] = ctx
            with urllib.request.urlopen(req, timeout=timeout, **kwargs) as resp:
                return resp.status

        except urllib.error.HTTPError as exc:
            return exc.code

        except (urllib.error.URLError, OSError):
            return 0
