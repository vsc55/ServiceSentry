#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows reserved TCP port ranges (``netsh ... excludedportrange``).

On Windows, winnat / Hyper-V / WSL / Docker reserve chunks of the port space;
binding to a port inside one fails with ``WinError 10013`` even though nothing
is listening (and the reservations shift across reboots).  This helper surfaces
those ranges so a bind failure can explain the *real* cause instead of looking
like a generic permission error.

Pure-parsing (:func:`parse_excluded_ranges`) is split from the OS query
(:func:`excluded_port_ranges`) so the parser is testable without running netsh.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Each data row of the netsh table is two integers (start, end), optionally with
# a trailing '*' marker.  Headers/dashes carry no leading integer pair, so this
# stays language-independent (works for the English "Start Port" table too).
_RANGE_RE = re.compile(r'^\s*(\d+)\s+(\d+)')


def parse_excluded_ranges(text: str) -> list[tuple[int, int]]:
    """Parse ``netsh interface ipv4 show excludedportrange`` output into a list
    of inclusive ``(start, end)`` ranges."""
    ranges: list[tuple[int, int]] = []
    for line in (text or '').splitlines():
        m = _RANGE_RE.match(line)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if start <= end:
                ranges.append((start, end))
    return ranges


def excluded_port_ranges(protocol: str = 'tcp') -> list[tuple[int, int]]:
    """Windows' reserved ``(start, end)`` port ranges for *protocol*.

    Returns ``[]`` when not running on Windows or when the query fails — never
    raises, so callers can use it freely on any platform.
    """
    if sys.platform != 'win32':
        return []
    try:
        out = subprocess.run(
            ['netsh', 'interface', 'ipv4', 'show', 'excludedportrange',
             f'protocol={protocol}'],
            capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_excluded_ranges(out.stdout or '')


def port_excluded(port: int, ranges: list[tuple[int, int]] | None = None):
    """Return the reserved ``(start, end)`` range containing *port*, or ``None``.

    Queries Windows when *ranges* is not supplied (so on non-Windows it is
    always ``None``)."""
    if ranges is None:
        ranges = excluded_port_ranges()
    for start, end in ranges:
        if start <= port <= end:
            return (start, end)
    return None
