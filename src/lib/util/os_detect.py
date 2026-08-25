#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Operating-system identification helpers (core, host-domain).

A host declares its OS so modules that run OS-specific commands (e.g. RAID)
know which syntax to use.  The value may be ``auto``:

  * a **local** host resolves ``auto`` to the platform this process runs on;
  * a **remote** host resolves ``auto`` over SSH (see :mod:`lib.core.hosts.ssh_client`).

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
    """Map an arbitrary platform/uname string to a canonical token.

    Two kinds of string reach this, and the difference is why the prefixes are not enough on
    their own. `uname -s` and `sys.platform` answer ONE word — that is the fast path below.
    A device describing itself answers a sentence: `sysDescr` on a Synology is "Linux nas-01
    5.10.55 …" and a `lsb_release` extend answers "Debian GNU/Linux 12", where the word that
    matters is in the middle. Read only as a prefix, the second one was OTHER — which reads as
    "a platform this panel has no word for" and is not what the machine said.

    Prefixes first, so a one-word answer never depends on what else its name contains.
    """
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
    # …and then anywhere in the sentence. BSD is already above and Windows is caught by its
    # own containment test, so what is left is the two that only had a prefix rule.
    if 'linux' in v:
        return 'linux'
    if 'darwin' in v:
        return 'darwin'
    return OS_OTHER


def local_os() -> str:
    """The canonical OS of the machine this process runs on."""
    return canonical_os(sys.platform)
