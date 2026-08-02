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
# later offers "PiB" as a threshold unit must not silently be read as GiB.
#
# IEC labels, because the scale IS binary. It used to print "GB" while dividing by 1024 —
# the Windows convention, and an ambiguity that showed up the moment somebody asked whether
# this counted the same thing as the rest of the panel: a "1.0 GB" here is 1073741824 bytes,
# while the label on a disk means 1000000000. The suffix now says which one it is.
_SCALE = ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB')
_UNITS = {name: 1024 ** i for i, name in enumerate(_SCALE)}
# Every threshold an admin has already saved says "GB". Those values were ALWAYS binary —
# only the label was wrong — so the old spellings map onto the same numbers rather than
# being rejected: a stored "100 GB" must go on meaning exactly what it meant yesterday.
# Accepted for reading, never produced: `fmt_bytes` emits only the IEC names above.
_LEGACY_UNITS = {'KB': 'KiB', 'MB': 'MiB', 'GB': 'GiB', 'TB': 'TiB',
                 'PB': 'PiB', 'EB': 'EiB', 'ZB': 'ZiB', 'YB': 'YiB'}


def normalize_unit(unit) -> str:
    """A unit name as this project spells it now: ``GB`` → ``GiB``, ``GiB`` → ``GiB``.

    Public because the spelling outlives the value: config saved before the rename still
    says ``GB``, and anything that shows the admin their own stored unit — a dropdown, a
    threshold summary — has to display the current name for the same quantity.
    """
    u = str(unit or '').strip()
    if u in _UNITS:
        return u
    return _LEGACY_UNITS.get(u.upper(), u)


def fmt_bytes(n) -> str:
    """Human-readable byte size with a unit suffix: ``0 B``, ``1.5 GiB``, ``2.0 TiB``.

    The spaced form is what ends up in alert messages and on the Status bar, so it favours
    readability over compactness.  :func:`bytes2human` is the older, compact variant
    (``1.5G``) — see its note.

    The suffix is IEC (``GiB``) because the scale is binary. Printing "GB" while dividing by
    1024 is the Windows convention and it is genuinely ambiguous: the same three characters
    mean 1000000000 on the box a disk came in. The whole panel is one base and now says so.

    Scales all the way to YiB rather than stopping at PiB: a formatter that caps does not
    say "too big", it prints ``2097152.0 PiB``, which is worse than useless in an alert.

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
    """A value + unit (``KiB``…``YiB``, or the old ``KB``…``YB``) → bytes; 0 if invalid.

    The inverse of :func:`fmt_bytes` for configured thresholds, where the admin types a
    number and picks a unit.  The two MUST share this ladder: if one scaled by 1024 and the
    other by 1000, a threshold saved as "100 GiB" would read back as "107.4 GiB" — a value
    the admin typed themselves, drifting every time they looked at it.

    An unknown unit is read as GiB rather than rejected: a threshold that silently became 0
    would disable the alert it was meant to raise.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    return int(v * _UNITS.get(normalize_unit(unit) or 'GiB', _UNITS['GiB']))


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
