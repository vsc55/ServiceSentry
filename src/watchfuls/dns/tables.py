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

"""Watchful module to check DNS resolution for any record type."""

"""Which record types resolve which way, and the two coercions that read them.

Static knowledge with no owner: discovery, the check loop and the resolvers all read these,
so they belong to none of the three.
"""

_SOCKET_TYPES = frozenset({'A', 'AAAA'})

# Record types probed at the domain apex during discovery (overridable in the
# schema via the "list" collection's __discovery_probe_types__).
_DEFAULT_PROBE_TYPES = ('A', 'AAAA', 'MX', 'TXT', 'NS', 'SOA', 'CNAME', 'CAA', 'SRV')

# Maps a record type to a UI category (icon/colour + default operator) — the
# category definitions themselves live in schema.json (__discovery_categories__).
_TYPE_CATEGORY = {
    'A': 'address', 'AAAA': 'address', 'CNAME': 'alias',
    'MX': 'mail', 'NS': 'ns', 'SOA': 'ns', 'PTR': 'ns', 'SRV': 'srv',
    'TXT': 'text', 'CAA': 'text',
}


def _coerce_int(value, default: int = 0) -> int:
    """Best-effort int conversion; returns *default* on bad/empty input."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy(value) -> bool:
    """Interpret JSON/string booleans (True, "true", "1", "yes", "on")."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on', 'enable')
