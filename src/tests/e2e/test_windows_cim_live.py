#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Windows commands of cpu, filesystemusage and ram_swap, run for real on Windows.

`wmic` is gone from Windows 11 24H2 and Windows Server 2025, and the three modules read Windows
through PowerShell `Get-CimInstance` instead. Their parsers were only ever fed recorded output;
this runs the exact command each module sends, through the same local `device_exec` the check
uses (shell, stdin closed, replacement decoding), and parses what a real Windows answers.

Opt-in: Windows AND ``SS_TEST_WINDOWS_CIM=1`` — the Windows job in .github/workflows/tests.yml
sets it. A CIM disk query can take long on a workstation with mapped network drives, so it is
not part of an ordinary local run.
"""

from __future__ import annotations

import os
import shutil

import pytest

pytestmark = pytest.mark.skipif(
    os.name != 'nt' or os.environ.get('SS_TEST_WINDOWS_CIM') != '1',
    reason='Windows CIM live test: Windows with SS_TEST_WINDOWS_CIM=1 only')

_TIMEOUT = 120


def _exec(cmd: str) -> tuple:
    """`DeviceBinding.device_exec` on a local item, as a check runs it."""
    from lib.modules.device_binding import DeviceBinding

    class _Local(DeviceBinding):
        def _notify_lang(self):
            return 'en_EN'
    return _Local.device_exec(_Local.__new__(_Local), {'device_kind': 'local'}, cmd,
                              timeout=_TIMEOUT)


def _ok(out, err, code):
    assert code == 0, f'exit {code}: {err!r}'
    assert out.strip(), f'no output (stderr {err!r})'


def test_powershell_is_there():
    assert shutil.which('powershell'), 'Windows PowerShell is missing on this runner'


def test_cpu_load_is_read():
    from watchfuls.cpu import Watchful, _cpu_cmd
    out, err, code = _exec(_cpu_cmd('windows'))
    _ok(out, err, code)
    load = Watchful._parse_windows(out)
    assert load is not None and 0 <= load <= 100, f'unreadable CPU output: {out!r}'


def test_system_drive_usage_is_read():
    from watchfuls.filesystemusage import _DF_CMDS, Watchful
    out, err, code = _exec(_DF_CMDS['windows'])
    _ok(out, err, code)
    drive = os.environ.get('SystemDrive', 'C:')
    used = Watchful._parse_wmic(out, drive)
    assert used is not None and 0 <= used <= 100, f'{drive} not found in: {out!r}'


def test_memory_usage_is_read():
    from watchfuls.ram_swap import _MEM_CMDS, Watchful
    out, err, code = _exec(_MEM_CMDS['windows'][0])
    _ok(out, err, code)
    ram, swap = Watchful._parse_windows(out)
    assert ram is not None and 0 < ram <= 100, f'unreadable memory output: {out!r}'
    assert swap is None


def test_where_wmic_is_gone_the_cim_path_does_not_need_it():
    """Report, not a requirement: Server 2025 may or may not ship the wmic feature. The three
    tests above already prove the CIM path works; here we just make sure nothing above
    silently fell back to wmic on a runner that has it."""
    from watchfuls.filesystemusage import _DF_CMDS
    assert 'wmic' not in _DF_CMDS['windows'].lower()
