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
import urllib.error
import urllib.request
from dataclasses import dataclass

from lib.debug import DebugLevel
from lib.modules import ModuleBase


@dataclass
class WebResult:
    """ Dataclass to represent the result of a web check. """
    status: int
    reason: str

class Watchful(ModuleBase):
    """ Class to check web status. """

    ITEM_SCHEMA = {
        'list': {
            'enabled': {
                'default': True,
                'type': 'bool'
            },
            'url': {
                'default': '', 
                'type': 'str'
            },
            'code': {
                'default': 200,
                'type': 'int',
                'min': 1,
                'max': 9999
            },
            'timeout': {
                'default': 15,
                'type': 'int',
                'min': 1,
                'max': 300
            },
        },
    }

    # Default values are derived from ITEM_SCHEMA so there is a single
    # source of truth that the web UI can also consume.
    _DEFAULTS = {k: v['default'] for k, v in ITEM_SCHEMA['list'].items()}

    def __init__(self, monitor):
        super().__init__(monitor, __name__)

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
                    self._debug(
                        f"[Deprecate] Check: {url} - Enabled: {is_enabled}. Please update format.",
                        DebugLevel.warning
                    )

                case dict():
                    # New format: value is a dict with possible 'enabled' and 'url' keys.
                    # If 'enabled' is not specified, default to the module's default enabled state.
                    # If 'url' is not specified, default to the key.
                    is_enabled = value.get("enabled", is_enabled)
                    url = (value.get('url', '') or '').strip() or key
                    self._debug(f"Check: {url} - Enabled: {is_enabled}", DebugLevel.info)

                case _:
                    # If the value is neither a bool nor a dict, treat it as disabled and use
                    # the key as URL.
                    is_enabled = False
                    url = key
                    self._debug(
                        f"Check: {url} - Invalid configuration format. Treating as disabled.",
                        DebugLevel.warning
                    )

            if is_enabled:
                list_url.append((key, url))

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.get_conf('threads', self._DEFAULT_THREADS)) as executor:
            future_to_url = {
                executor.submit(self._web_check, name, url): (name, url)
                for name, url in list_url
            }
            for future in concurrent.futures.as_completed(future_to_url):
                name, url = future_to_url[future]
                try:
                    future.result()

                except Exception as exc: # pylint: disable=broad-except
                    self._debug(f"Check: {name} - Exception: {exc}", DebugLevel.error)
                    message = f'Check: {name} - Error: {exc} 💥'
                    self.dict_return.set(name, False, message)

        super().check()
        return self.dict_return

    def _web_check(self, name, url):
        code_true = self.get_conf_in_list("code", name, self._DEFAULTS['code'])
        timeout = self.get_conf_in_list("timeout", name, self._DEFAULTS['timeout'])

        result: WebResult = self._web_return(url, timeout)
        status: bool = result.status == code_true

        icon = '🔼' if status else '🔽'
        s_message = f'Web: {name} {icon}'
        if not status:
            s_message += f'\n 👉👉 Reason: {result.reason}\n'

        other_data = {
            'code': result.status,
            'reason': result.reason,
        }
        self.dict_return.set(name, status, s_message, False, other_data)

        if self.check_status(status, self.name_module, name):
            self.send_message(s_message, status)

    def _web_return(self, url, timeout) -> WebResult:
        """Return the HTTP status code for *url* using native Python.

        Supports both ``http://`` and ``https://`` URLs.  If the URL
        does not include a scheme, ``https://`` is assumed.
        """
        target = url if '://' in url else f'https://{url}'
        try:
            req = urllib.request.Request(
                target,
                method='GET',
                headers={'User-Agent': 'ServiceSentry/1.0'},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return WebResult(resp.status, resp.reason)

        except urllib.error.HTTPError as exc:
            return WebResult(exc.code, exc.reason)

        except (urllib.error.URLError, OSError) as exc:
            return WebResult(0, getattr(exc, 'reason', str(exc)))
