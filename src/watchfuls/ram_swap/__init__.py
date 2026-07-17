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

"""Watchful to check RAM and SWAP usage on the bound host (local or over SSH).

Host-centric: each check binds to a host (``host_uid``).  Memory stats are read
on that host via :meth:`ModuleBase.host_exec` using an OS-appropriate command
(``/proc/meminfo`` on Linux, ``wmic`` on Windows, ``vm_stat``/``sysctl`` on
macOS, ``sysctl``/``swapinfo`` on FreeBSD) and compared with per-check
thresholds.
"""

import json
import os

from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

# Marker joining the per-OS sub-readings (inserted in Python, not by a remote
# ``echo``); the parsers split the combined output on it.
_SEP = '---SS---'

# Per-OS command(s) that yield the memory figures parsed below.  macOS/FreeBSD
# need several readings: each is a separate single-binary command (no shell
# chaining) so the set fits a strict SSH allowlist (see docs/caso-ssh-hardening.md);
# their outputs are joined here with _SEP.
_MEM_CMDS = {
    'linux':   ['cat /proc/meminfo'],
    'windows': ['wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value'],
    'darwin':  ['sysctl -n hw.memsize', 'vm_stat', 'sysctl -n vm.swapusage'],
    'freebsd': ['sysctl -n hw.pagesize vm.stats.vm.v_page_count vm.stats.vm.v_free_count '
                'vm.stats.vm.v_inactive_count vm.stats.vm.v_cache_count',
                'swapinfo -k'],
}


class Watchful(ModuleBase):
    """Check RAM/SWAP usage per host against percentage thresholds."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])

    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            return self.dict_return
        items = [(k, v) for k, v in self.get_conf('list', {}).items()
                 if isinstance(v, dict) and v.get('enabled', self._DEFAULTS['enabled'])]
        self.run_parallel(items, self._mem_check, 'Memory')
        super().check()
        return self.dict_return

    @staticmethod
    def _alert(value, default) -> int:
        try:
            v = int(value)
        except (TypeError, ValueError):
            return int(default)
        return v if 0 <= v <= 100 else int(default)

    def _mem_check(self, key, raw):
        item = self.resolve_host(raw)
        if item.get('_host_maintenance') or not item.get('enabled', True):
            return
        label = (item.get('label') or '').strip() or key
        os_ = self.host_os(item)
        if os_ not in _MEM_CMDS:
            self.dict_return.set(f'{key}_ram', False,
                                 self._msg('mem_unsupported_os', label, os_),
                                 severity='warning', name=label)
            return
        timeout = self.module_default('timeout', self._MODULE_DEFAULTS['timeout'])
        outs = []
        for cmd in _MEM_CMDS[os_]:
            out, err, code = self.host_exec(item, cmd, timeout=timeout)
            if code != 0 and not out:
                raise OSError((err or '').strip() or f'memory query exited {code}')
            outs.append(out)
        out = f'\n{_SEP}\n'.join(outs)
        ram_pct, swap_pct = self._parse(os_, out)
        if ram_pct is None:
            raise ValueError('could not parse memory output')

        # Blank/0/absent per-item threshold inherits the module-level value
        # (Configuration > Modules), then the module schema default.
        self._emit(f'{key}_ram', 'RAM', label, ram_pct,
                   self._alert(item.get('alert_ram') or None,
                               self.module_default('alert_ram', self._MODULE_DEFAULTS['alert_ram'])))
        if swap_pct is not None:
            self._emit(f'{key}_swap', 'SWAP', label, swap_pct,
                       self._alert(item.get('alert_swap') or None,
                                   self.module_default('alert_swap', self._MODULE_DEFAULTS['alert_swap'])))

    def _emit(self, result_key, caption, label, used_pct, alert):
        used = round(float(used_pct), 1)
        warning = used >= float(alert)
        msg = self._msg('mem_high' if warning else 'mem_ok', caption, label, f'{used:.1f}')
        # 'name' is the display name for status views, since the result key is a
        # derived UID ("<item>_ram"/"_swap") — e.g. "NS1 - RAM".
        # A usage-threshold breach is a warning (host reachable), not a down.
        self.dict_return.set(result_key, not warning, msg,
                             other_data={'used': used, 'alert': float(alert),
                                         'name': f'{label} - {caption}'},
                             severity='warning', name=f'{label} - {caption}')

    # ── Per-OS parsers (pure; return (ram_pct, swap_pct|None)) ────────────────
    @classmethod
    def _parse(cls, os_, out):
        return {
            'linux':   cls._parse_linux,
            'windows': cls._parse_windows,
            'darwin':  cls._parse_darwin,
            'freebsd': cls._parse_freebsd,
        }[os_](out)

    @staticmethod
    def _kv_meminfo(out):
        vals = {}
        for line in out.splitlines():
            if ':' not in line:
                continue
            k, _, rest = line.partition(':')
            parts = rest.split()
            if parts and parts[0].lstrip('-').isdigit():
                vals[k.strip()] = int(parts[0])    # value in kB
        return vals

    @classmethod
    def _parse_linux(cls, out):
        v = cls._kv_meminfo(out)
        total = v.get('MemTotal', 0)
        avail = v.get('MemAvailable', v.get('MemFree', 0))
        ram = (total - avail) / total * 100 if total else None
        sw_total = v.get('SwapTotal', 0)
        sw_free = v.get('SwapFree', 0)
        swap = (sw_total - sw_free) / sw_total * 100 if sw_total else 0.0
        return ram, swap

    @staticmethod
    def _parse_windows(out):
        kv = {}
        for line in out.splitlines():
            if '=' in line:
                k, _, val = line.partition('=')
                val = val.strip()
                if val.isdigit():
                    kv[k.strip()] = int(val)        # value in kB
        total = kv.get('TotalVisibleMemorySize', 0)
        free = kv.get('FreePhysicalMemory', 0)
        ram = (total - free) / total * 100 if total else None
        return ram, None                            # swap (pagefile) not queried

    @staticmethod
    def _parse_darwin(out):
        memsize_s, vm_s, swap_s = (out.split('---SS---') + ['', '', ''])[:3]
        try:
            memsize = int(memsize_s.strip().splitlines()[0])
        except (IndexError, ValueError):
            return None, None
        page = 4096
        pages = {}
        for line in vm_s.splitlines():
            low = line.lower()
            if 'page size of' in low:
                for tok in low.split():
                    if tok.isdigit():
                        page = int(tok); break
            elif ':' in line:
                k, _, rest = line.partition(':')
                num = rest.strip().rstrip('.').strip()
                if num.isdigit():
                    pages[k.strip().lower()] = int(num)
        used_pages = (pages.get('pages active', 0) + pages.get('pages wired down', 0)
                      + pages.get('pages occupied by compressor', 0))
        ram = used_pages * page / memsize * 100 if memsize else None
        swap = None
        # "total = 2048.00M  used = 512.00M  free = 1536.00M"
        nums = []
        for tok in swap_s.replace('=', ' ').split():
            t = tok.rstrip('M').rstrip('m')
            try:
                nums.append(float(t))
            except ValueError:
                pass
        if len(nums) >= 2 and nums[0] > 0:
            swap = nums[1] / nums[0] * 100
        return ram, swap

    @staticmethod
    def _parse_freebsd(out):
        sysctl_s, swap_s = (out.split('---SS---') + ['', ''])[:2]
        nums = [int(x) for x in sysctl_s.split() if x.lstrip('-').isdigit()]
        ram = None
        if len(nums) >= 3:
            _pagesize, page_count, free_count = nums[0], nums[1], nums[2]
            inactive = nums[3] if len(nums) > 3 else 0
            cache = nums[4] if len(nums) > 4 else 0
            avail = free_count + inactive + cache
            ram = (page_count - avail) / page_count * 100 if page_count else None
        # swapinfo -k: last data line ".... <used%>" with a trailing "NN%".
        swap = None
        for line in swap_s.splitlines():
            line = line.strip()
            if line.endswith('%'):
                tok = line.split()[-1].rstrip('%')
                try:
                    swap = float(tok); break
                except ValueError:
                    pass
        return ram, swap
