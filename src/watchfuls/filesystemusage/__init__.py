#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Lorenzo Carbonell (aka atareao)
# <lorenzo.carbonell.cerezo at gmail dot com>
#
# Copyright © 2019  Javier Pastor (aka vsc55)
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
"""Watchful to check filesystem usage on the bound host (local or over SSH).

Host-centric: each check binds to a host (``host_uid``) and a mount point.  Disk
usage is read on that host via :meth:`ModuleBase.host_exec` (``df`` on Unix,
``wmic logicaldisk`` on Windows) and compared with a per-check threshold.
"""

import json
import os

import psutil

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

_DF_CMDS = {
    'linux':   'df -P -k',
    'darwin':  'df -P -k',
    'freebsd': 'df -P -k',
    'other':   'df -P -k',
    'windows': 'wmic logicaldisk get DeviceID,FreeSpace,Size /format:value',
}

# Pseudo/virtual filesystems hidden in local discovery.
_IGNORED_FSTYPES = frozenset({
    'squashfs', 'tmpfs', 'devtmpfs', 'overlay', 'proc', 'sysfs',
    'devfs', 'cgroup', 'cgroup2', 'autofs', 'binfmt_misc',
})


class Watchful(ModuleBase):
    """Check filesystem usage per host + mount point against a threshold."""

    ITEM_SCHEMA = _SCHEMA
    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'discover'})

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])
    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("FilesystemUsage: module disabled, skipping.", DebugLevel.info)
            return self.dict_return
        items = [(k, v) for k, v in self.get_conf('list', {}).items()
                 if isinstance(v, dict) and v.get('enabled', self._DEFAULTS['enabled'])]
        self.run_parallel(items, self._fs_check, 'Disk')
        super().check()
        return self.dict_return

    def _fs_check(self, key, raw):
        item = self.resolve_host(raw)
        if item.get('_host_maintenance') or not item.get('enabled', True):
            return
        part = (item.get('partition', '') or '').strip() or key
        # Editable display name (e.g. "host - /"); falls back to the partition.
        label = (item.get('label', '') or '').strip() or part
        os_ = self.host_os(item)
        cmd = self.host_cmd_for(item, _DF_CMDS, default_os='linux')
        out, err, code = self.host_exec(
            item, cmd, timeout=self.module_default('timeout', self._MODULE_DEFAULTS['timeout']))
        if code != 0 and not out:
            raise OSError((err or '').strip() or f'df exited {code}')
        used = self._parse(os_, out, part)
        if used is None:
            raise ValueError(f'mount point "{part}" not found')

        # Blank/0/absent inherits the module-level "Threshold (%)" via the canonical
        # item -> module -> global chain (module_default also handles a blank module
        # value safely, unlike a raw get_conf which could yield float('') ).
        alert = float(item.get('alert', 0)
                      or self.module_default('alert', self._MODULE_DEFAULTS['alert']))
        ok = used <= alert
        msg = f'{label} ({part}) used {used}%' if label != part else f'partition {part} used {used}%'
        msg = f'Normal {msg} ✅' if ok else f'Warning {msg} ⚠️'
        # Key the result by the item key (unique per check) — not by the mount
        # point, or two checks on the same partition would collide into one.
        self.dict_return.set(key, ok, msg, other_data={'used': used, 'mount': part, 'alert': alert})

    # ── Parsers (pure) ────────────────────────────────────────────────────────
    @classmethod
    def _parse(cls, os_, out, part):
        return cls._parse_wmic(out, part) if os_ == 'windows' else cls._parse_df(out, part)

    @staticmethod
    def _parse_df(out, part):
        """`df -P -k` → use% for the row matching *part* (mount point or device)."""
        for line in out.splitlines()[1:]:
            f = line.split()
            if len(f) < 6:
                continue
            cap = f[4].rstrip('%')
            mount = ' '.join(f[5:])
            if (mount == part or f[0] == part) and cap.lstrip('-').isdigit():
                return int(cap)
        return None

    @staticmethod
    def _parse_wmic(out, part):
        """`wmic logicaldisk … /format:value` → used% for the matching DeviceID."""
        disks, cur = [], {}
        for line in out.splitlines():
            line = line.strip()
            if not line:
                if cur:
                    disks.append(cur); cur = {}
                continue
            if '=' in line:
                k, _, v = line.partition('=')
                cur[k.strip()] = v.strip()
        if cur:
            disks.append(cur)
        want = part.rstrip('\\').upper()
        for d in disks:
            if d.get('DeviceID', '').rstrip('\\').upper() == want:
                size = int(d.get('Size') or 0)
                free = int(d.get('FreeSpace') or 0)
                return round((size - free) / size * 100) if size > 0 else None
        return None

    # ── Discover (local autocomplete, or over SSH for a remote host) ──────────
    @classmethod
    def discover(cls, config=None) -> list:
        from lib.hosts import runner as host_runner  # noqa: PLC0415
        host = (config or {}).get('__host__') if isinstance(config, dict) else None
        if host_runner.is_remote(host):
            os_ = str(host.get('os') or 'linux')
            cmd = _DF_CMDS.get(os_) or _DF_CMDS['linux']
            out, _err, code = host_runner.run(host, cmd, timeout=15)
            if code != 0 and not out:
                return []
            return cls._discover_parse(os_, out)
        try:
            parts = []
            for p in psutil.disk_partitions():
                if p.fstype in _IGNORED_FSTYPES:
                    continue
                try:
                    pct = f'{psutil.disk_usage(p.mountpoint).percent:.0f}%'
                except (PermissionError, OSError):
                    pct = '?'
                parts.append({'name': p.mountpoint,
                              'display_name': p.device + (f' ({p.fstype})' if p.fstype else ''),
                              'status': pct})
            return sorted(parts, key=lambda x: x['name'].lower())
        except Exception:  # pylint: disable=broad-except
            return []

    @staticmethod
    def _discover_parse(os_, out):
        items = []
        if os_ == 'windows':
            disks, cur = [], {}
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    if cur:
                        disks.append(cur); cur = {}
                    continue
                if '=' in line:
                    k, _, v = line.partition('=')
                    cur[k.strip()] = v.strip()
            if cur:
                disks.append(cur)
            for d in disks:
                dev = d.get('DeviceID', '')
                if not dev:
                    continue
                size = int(d.get('Size') or 0)
                free = int(d.get('FreeSpace') or 0)
                pct = f'{round((size - free) / size * 100)}%' if size > 0 else '?'
                items.append({'name': dev, 'display_name': dev, 'status': pct})
            return sorted(items, key=lambda x: x['name'].lower())
        for line in out.splitlines()[1:]:
            f = line.split()
            if len(f) < 6:
                continue
            mount = ' '.join(f[5:])
            items.append({'name': mount, 'display_name': f[0], 'status': f[4]})
        return sorted(items, key=lambda x: x['name'].lower())
