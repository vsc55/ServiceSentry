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

"""Watchful module to check that processes are running, on the bound host.

Host-centric: each check binds to a host (``host_uid``).  The process list is
read on that host via :meth:`ModuleBase.host_exec` — locally for a *local* host
or over SSH for a *remote* one — using an OS-appropriate command (``ps`` on
Unix, ``tasklist`` on Windows) and the matches are counted against ``min_count``.
"""

import csv
import io
import json
import os

import psutil

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

# Command that lists process (command) names, one per line, per OS.
_LIST_CMDS = {
    'linux':   'ps -A -o comm=',
    'darwin':  'ps -A -o comm=',
    'freebsd': 'ps -A -o comm=',
    'other':   'ps -A -o comm=',
    'windows': 'tasklist /FO CSV /NH',
}


class Watchful(ModuleBase):
    """Check that named processes are running (>= min_count) on each host."""

    WATCHFUL_ACTIONS: frozenset = frozenset({'discover'})

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])

    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("Process: module disabled, skipping.", DebugLevel.info)
            return self.dict_return

        items = [(k, v) for k, v in self.get_conf('list', {}).items()
                 if isinstance(v, dict) and v.get('enabled', self._DEFAULTS['enabled'])]
        self.run_parallel(items, self._process_check, 'Process')

        super().check()
        return self.dict_return

    def _process_check(self, key, raw):
        item = self.resolve_host(raw)
        # Bound host in maintenance → skip (resolve_host disables it).
        if item.get('_host_maintenance') or not item.get('enabled', True):
            return
        name = (item.get('process', '') or '').strip() or key
        module_min = int(self.get_conf('min_count', self._MODULE_DEFAULTS.get('min_count', 1)) or 1)
        min_count = int(item.get('min_count', 0) or 0) or module_min
        os_ = self.host_os(item)
        timeout = self.module_default('timeout', self._MODULE_DEFAULTS['timeout'])

        cmd = self.host_cmd_for(item, _LIST_CMDS, default_os='linux')
        out, err, code = self.host_exec(item, cmd, timeout=timeout)
        if code != 0 and not out:
            raise OSError((err or '').strip() or f'process listing exited {code}')

        count = self._count_matches(out, os_, name)
        ok = count >= min_count
        message = (self._msg('proc_ok', key, count) if ok
                   else self._msg('proc_low', key, count, min_count))

        other_data = {'process': name, 'count': count, 'min_count': min_count}
        self.dict_return.set(key, ok, message, False, other_data)
        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok, item=name)

    @staticmethod
    def _count_matches(out: str, os_: str, name: str) -> int:
        """Count processes matching *name* (case-insensitive) in *out*."""
        name_l = name.lower()
        count = 0
        if os_ == 'windows':
            for row in csv.reader(io.StringIO(out)):
                if not row:
                    continue
                img = row[0].strip().lower()
                if img == name_l or img == f'{name_l}.exe':
                    count += 1
            return count
        # Unix: one command name per line (comm is the basename; Linux truncates
        # to 15 chars, so match the truncation too).
        for line in out.splitlines():
            comm = line.strip()
            if not comm:
                continue
            base = comm.rsplit('/', 1)[-1].lower()
            if base == name_l or base == name_l[:15] or comm.lower() == name_l:
                count += 1
        return count

    @classmethod
    def discover(cls, config=None) -> list:
        """List running processes (with instance counts) for the autocomplete.

        When called with a host context (``config['__host__']``, injected by the
        route for the Servers modal) and that host is remote, the list is read
        over SSH on the host; otherwise it is read from THIS machine (psutil).
        """
        from lib.core.hosts import runner as host_runner  # noqa: PLC0415
        host = (config or {}).get('__host__') if isinstance(config, dict) else None
        if host_runner.is_remote(host):
            os_ = str(host.get('os') or 'linux')
            cmd = _LIST_CMDS.get(os_) or _LIST_CMDS['linux']
            out, _err, code = host_runner.run(host, cmd, timeout=15)
            if code != 0 and not out:
                return []
            return cls._discover_from_listing(out, os_)
        try:
            counts: dict[str, int] = {}
            for p in psutil.process_iter(['name']):
                pname = (p.info.get('name') or '').strip()
                if pname:
                    counts[pname] = counts.get(pname, 0) + 1
            return sorted(
                [{'name': n, 'display_name': n, 'status': f'×{c}'} for n, c in counts.items()],
                key=lambda x: x['name'].lower(),
            )
        except Exception:  # pylint: disable=broad-except
            return []

    @staticmethod
    def _discover_from_listing(out: str, os_: str) -> list:
        """Aggregate a ps/tasklist listing into [{name, display_name, status}]."""
        counts: dict[str, int] = {}
        if os_ == 'windows':
            for row in csv.reader(io.StringIO(out)):
                if row and row[0].strip():
                    img = row[0].strip()
                    counts[img] = counts.get(img, 0) + 1
        else:
            for line in out.splitlines():
                comm = line.strip().rsplit('/', 1)[-1]
                if comm:
                    counts[comm] = counts.get(comm, 0) + 1
        return sorted(
            [{'name': n, 'display_name': n, 'status': f'×{c}'} for n, c in counts.items()],
            key=lambda x: x['name'].lower(),
        )
