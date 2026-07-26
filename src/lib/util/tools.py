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
""" Tools for the project. """

import secrets as _secrets


def generate_token(nbytes=32):
    """Generate a cryptographically-strong random token as a hex string
    (``nbytes`` of entropy → ``2·nbytes`` hex chars).  Generic: reuse for any
    bearer/secret token (SCIM, API keys, one-off secrets…)."""
    try:
        nbytes = int(nbytes)
    except (TypeError, ValueError):
        nbytes = 32
    nbytes = max(16, min(nbytes, 128))     # clamp to a sane range
    return _secrets.token_hex(nbytes)


# The full binary ladder, so the two directions cover the same range: a schema that
# later offers "PB" as a threshold unit must not silently be read as GB.
_SCALE = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB')
_UNITS = {name: 1024 ** i for i, name in enumerate(_SCALE)}


def fmt_bytes(n) -> str:
    """Human-readable byte size with a unit suffix: ``0 B``, ``1.5 GB``, ``2.0 TB``.

    The spaced, two-letter form is what ends up in alert messages and on the Status bar,
    so it favours readability over compactness.  :func:`bytes2human` is the older,
    compact variant (``1.5G``) — see its note.

    Scales all the way to YB rather than stopping at PB: a formatter that caps does not
    say "too big", it prints ``2097152.0 PB``, which is worse than useless in an alert.

    Never raises: a value that is not a number formats as ``0 B``, because a monitoring
    message must render even when the API answered something unexpected.
    """
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return '0 B'
    last = _SCALE[-1]
    for unit in _SCALE:
        if n < 1024 or unit == last:
            return f'{int(n)} B' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} {last}'


def to_bytes(value, unit: str) -> int:
    """A value + unit (``KB``…``YB``) → bytes; 0 for a blank or invalid value.

    The inverse of :func:`fmt_bytes` for configured thresholds, where the admin types a
    number and picks a unit.  An unknown unit is read as GB rather than rejected: a
    threshold that silently became 0 would disable the alert it was meant to raise.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    return int(v * _UNITS.get(str(unit or 'GB').upper(), _UNITS['GB']))


def bytes2human(n):
    """Compact human-readable byte size (``1.5G``, ``100B``) — no space, one-letter unit.

    NOTE: nothing in the project calls this; :func:`fmt_bytes` is the formatter actually
    in use, and the two differ only in presentation.  Kept because it is exported public
    API, but prefer ``fmt_bytes`` for anything user-facing.
    """
    # http://code.activestate.com/recipes/577972-disk-usage/
    # print("Total:", bytes2human(total))
    # print("Used:", bytes2human(used))
    # print("Free:", bytes2human(free))

    symbols = ('K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
    prefix = {}
    for i, s in enumerate(symbols):
        prefix[s] = 1 << (i+1)*10
    for s in reversed(symbols):
        if n >= prefix[s]:
            value = float(n) / prefix[s]
            return f'{value:.1f}{s}'
    return f"{n}B"
