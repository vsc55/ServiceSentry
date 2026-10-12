#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for lib/modules/device_binding.py from the second 2026-10-12 audit (WF-8).

The LOCAL branch of ``device_exec`` decoded the command's output with ``text=True`` and no
error policy: one byte the locale codec cannot read (a service description in another code
page, a file name) raised inside ``subprocess.run`` and the whole reading came back as an
error with no output. The process spawned here is this interpreter printing fixed bytes.
"""

import sys

from conftest import create_mock_monitor


def _watchful():
    from watchfuls.process import Watchful
    return Watchful(create_mock_monitor({'watchfuls.process': {}}))


def test_local_output_with_undecodable_bytes_is_still_read():
    # 0x81 and 0x90 are undefined in cp1252; 0xff is never valid UTF-8.
    script = 'import sys; sys.stdout.buffer.write(bytes([111, 107, 32, 129, 255, 144, 10]))'
    cmd = f'"{sys.executable}" -c "{script}"'
    out, err, code = _watchful().device_exec({'enabled': True}, cmd, timeout=30)
    assert code == 0, err
    assert out.startswith('ok ')


def test_remote_auto_os_reads_as_linux():
    """WF-3, at the source: ``device_os`` answers Linux for a remote device left on auto."""
    w = _watchful()
    assert w.device_os({'device_os': 'auto'}) == 'linux'
    assert w.device_os({'device_os': ' FreeBSD '}) == 'freebsd'
