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

"""Watchful to check CPU usage on the bound host (local or over SSH).

Host-centric: each check binds to a host (``host_uid``).  CPU usage is sampled
on that host via :meth:`ModuleBase.host_exec` using an OS-appropriate command
(two ``/proc/stat`` reads on Linux, ``kern.cp_time`` on FreeBSD, ``top -l2`` on
macOS, ``wmic`` on Windows) and compared with a per-check threshold.
"""

import concurrent.futures
import json
import os

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


def _cpu_cmds(interval: float) -> dict:
    """Per-OS command that yields the samples parsed below ({sleep} = interval)."""
    s = max(0.1, float(interval))
    return {
        'linux':   f"cat /proc/stat | grep '^cpu '; sleep {s}; cat /proc/stat | grep '^cpu '",
        'freebsd': f"sysctl -n kern.cp_time; sleep {s}; sysctl -n kern.cp_time",
        'darwin':  "top -l 2 -n 0",
        'windows': "wmic cpu get loadpercentage /value",
    }


class Watchful(ModuleBase):
    """Check CPU usage per host against a percentage threshold."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            return self.dict_return
        items = [(k, v) for k, v in self.get_conf('list', {}).items()
                 if isinstance(v, dict) and v.get('enabled', self._DEFAULTS['enabled'])]
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._MODULE_DEFAULTS['threads'])) as executor:
            futures = {executor.submit(self._cpu_check, k, v): k for k, v in items}
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f"cpu: {self.item_label(key)} - Exception: {exc}", DebugLevel.error)
                    _raw = self.get_conf('list', {}).get(key, {})
                    _lbl = (_raw.get('label') or key) if isinstance(_raw, dict) else key
                    self.dict_return.set(key, False, f'CPU: {_lbl} - *Error: {exc}* 💥')
        super().check()
        return self.dict_return

    def _cpu_check(self, key, raw):
        item = self.resolve_host(raw)
        if item.get('_host_maintenance') or not item.get('enabled', True):
            return
        label = (item.get('label') or '').strip() or key
        os_ = self.host_os(item)
        interval = self.get_conf('interval', self._MODULE_DEFAULTS['interval'])
        cmds = _cpu_cmds(interval)
        cmd = cmds.get(os_) or cmds['linux']
        timeout = self.get_conf('timeout', self._MODULE_DEFAULTS['timeout']) + interval
        out, err, code = self.host_exec(item, cmd, timeout=int(timeout) + 2)
        if code != 0 and not out:
            raise OSError((err or '').strip() or f'cpu query exited {code}')
        usage = self._parse(os_, out)
        if usage is None:
            raise ValueError('could not parse CPU output')

        alert = float(item.get('alert', self._DEFAULTS['alert']) or self._DEFAULTS['alert'])
        used = round(float(usage), 1)
        ok = used < alert
        msg = f'CPU ({label}) used {used:.1f}%'
        msg = f'Normal {msg} ✅' if ok else f'Excessive {msg} ⚠️'
        self.dict_return.set(key, ok, msg, other_data={'used': used, 'alert': alert})

    # ── Per-OS parsers (pure; return usage % or None) ─────────────────────────
    @classmethod
    def _parse(cls, os_, out):
        if os_ == 'windows':
            return cls._parse_windows(out)
        if os_ == 'darwin':
            return cls._parse_darwin(out)
        if os_ == 'freebsd':
            return cls._parse_cp_time(out)
        return cls._parse_proc_stat(out)

    @staticmethod
    def _parse_proc_stat(out):
        """Two `cpu ...` lines from /proc/stat → busy% over the interval."""
        samples = []
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0] == 'cpu':
                nums = [int(x) for x in parts[1:] if x.lstrip('-').isdigit()]
                if len(nums) >= 5:
                    total = sum(nums)
                    idle = nums[3] + nums[4]   # idle + iowait
                    samples.append((total, idle))
        if len(samples) < 2:
            return None
        dt = samples[1][0] - samples[0][0]
        di = samples[1][1] - samples[0][1]
        return 100.0 * (1 - di / dt) if dt > 0 else None

    @staticmethod
    def _parse_cp_time(out):
        """Two FreeBSD `kern.cp_time` lines (user nice sys intr idle) → busy%."""
        samples = []
        for line in out.splitlines():
            nums = [int(x) for x in line.split() if x.lstrip('-').isdigit()]
            if len(nums) >= 5:
                samples.append((sum(nums), nums[-1]))   # idle is the last counter
        if len(samples) < 2:
            return None
        dt = samples[1][0] - samples[0][0]
        di = samples[1][1] - samples[0][1]
        return 100.0 * (1 - di / dt) if dt > 0 else None

    @staticmethod
    def _parse_darwin(out):
        """macOS `top -l2` → last "CPU usage: … N% idle" line → 100 - idle."""
        idle = None
        for line in out.splitlines():
            low = line.lower()
            if 'cpu usage' not in low or 'idle' not in low:
                continue
            toks = low.replace(',', ' ').split()
            for i, tok in enumerate(toks):       # the % right before "idle"
                if tok == 'idle' and i > 0 and toks[i - 1].endswith('%'):
                    try:
                        idle = float(toks[i - 1].rstrip('%'))
                    except ValueError:
                        pass
        return (100.0 - idle) if idle is not None else None

    @staticmethod
    def _parse_windows(out):
        """`wmic cpu get loadpercentage /value` → average of LoadPercentage."""
        vals = []
        for line in out.splitlines():
            if '=' in line:
                k, _, v = line.partition('=')
                if k.strip().lower() == 'loadpercentage' and v.strip().isdigit():
                    vals.append(int(v.strip()))
        return sum(vals) / len(vals) if vals else None
