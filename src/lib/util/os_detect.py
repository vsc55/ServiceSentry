#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Operating-system identification helpers (core, host-domain).

A host declares its OS so modules that run OS-specific commands (e.g. RAID)
know which syntax to use.  The value may be ``auto``:

  * a **local** host resolves ``auto`` to the platform this process runs on;
  * a **remote** host resolves ``auto`` over SSH (see :mod:`lib.hosts.ssh_client`).

Canonical OS tokens are kept small and stable so module code can switch on them.
"""

from __future__ import annotations

import sys

# Canonical OS tokens (plus the special 'auto' / 'other').
OS_AUTO = 'auto'
OS_OTHER = 'other'
CANONICAL = ('linux', 'windows', 'darwin', 'freebsd', OS_OTHER)
# Selectable values offered in the UI (auto first).
OPTIONS = (OS_AUTO, 'linux', 'windows', 'darwin', 'freebsd', OS_OTHER)


def canonical_os(value: str) -> str:
    """Map an arbitrary platform/uname string to a canonical token."""
    v = str(value or '').strip().lower()
    if not v:
        return OS_OTHER
    if v in CANONICAL or v == OS_AUTO:
        return v
    if v.startswith('linux'):
        return 'linux'
    if v.startswith(('win', 'cygwin', 'msys')) or 'windows' in v:
        return 'windows'
    if v.startswith(('darwin', 'mac')) or 'os x' in v or 'macos' in v:
        return 'darwin'
    if 'bsd' in v:                       # freebsd / openbsd / netbsd
        return 'freebsd'
    return OS_OTHER


def local_os() -> str:
    """The canonical OS of the machine this process runs on."""
    return canonical_os(sys.platform)
