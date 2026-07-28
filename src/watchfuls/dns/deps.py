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

"""Reaching the real dnspython from a package that is itself called ``dns``.

The monitor registers this watchful as ``sys.modules['dns']`` before running its
``__init__``, so a plain ``import dns.resolver`` finds US, not dnspython. Detection walks
sys.path for a *different* directory holding ``resolver.py``, and loading temporarily evicts
this package from sys.modules and drops watchfuls/ from sys.path.

It is lazy on purpose: only non-A lookups need dnspython, so a deployment that never asks for
an MX record never pays the import - and the lock exists because check() resolves items in
parallel threads, and the first few non-A queries race into the loader together.
""" + """
# NAMING TRAP — do not add resolver.py, zone.py, query.py, rdatatype.py or exception.py to
# this package. The monitor registers it as sys.modules['dns'], so those names are exactly
# dnspython's submodules and the loader below juggles sys.modules/sys.path to reach the real
# ones. A file here with one of those names is a collision waiting for whoever adds it.
"""

import os
import sys
import threading


# Detect dnspython by looking for its resolver.py in sys.path, explicitly
# skipping our own directory.  A plain `import dns.resolver` would fail here
# because monitor.py registers *this* file as sys.modules['dns'] before running
# __init__.py, so 'dns.resolver' would resolve to watchfuls/dns/resolver.py
# (which doesn't exist) instead of the installed dnspython package.
def _find_dnspython_dir() -> str | None:
    """Return the path to the installed dnspython package dir, or None."""
    _self_dir = os.path.normcase(os.path.abspath(os.path.dirname(__file__)))
    for _p in sys.path:
        _candidate = os.path.join(_p, 'dns')
        if os.path.normcase(os.path.abspath(_candidate)) == _self_dir:
            continue
        if os.path.isfile(os.path.join(_candidate, 'resolver.py')):
            return _candidate
    return None

_DNSPYTHON_DIR = _find_dnspython_dir()
_HAS_DNSPYTHON: bool = _DNSPYTHON_DIR is not None

# Lazily loaded dnspython submodules (populated on first use): a dict with keys
# 'resolver', 'zone', 'query', 'rdatatype', 'exception' — or None if unavailable.
_dnspython = None
# Guards the sys.modules / sys.path juggling below: check() resolves items in
# parallel threads, so the first non-A queries can race into this loader at once.
_dns_load_lock = threading.Lock()

# Submodules to import; resolver covers normal queries, zone/query/rdatatype AXFR.
_DNSPY_SUBMODULES = ('resolver', 'zone', 'query', 'rdatatype', 'exception')


def _load_dnspython():
    """Import dnspython submodules, bypassing the watchful name collision.

    At call time, __init__.py has finished executing so the import lock for
    'dns' is free.  We temporarily evict ourselves from sys.modules and remove
    watchfuls/ from sys.path so that 'import dns.*' finds dnspython.

    Thread-safe: the global sys.modules/sys.path mutation runs under a lock so
    concurrent first-time callers can't corrupt the 'dns' module mapping.
    Returns the cached submodule dict, or None when dnspython is not installed.
    """
    global _dnspython
    if _dnspython is not None:
        return _dnspython
    if not _HAS_DNSPYTHON:
        return None
    with _dns_load_lock:
        if _dnspython is not None:   # another thread loaded it while we waited
            return _dnspython
        _dnspython = _load_dnspython_locked()
        return _dnspython


def _load_dnspython_locked():
    """Body of :func:`_load_dnspython`, executed while holding the load lock."""
    _watchfuls_dir = os.path.dirname(os.path.dirname(__file__))
    _saved_dns = sys.modules.pop('dns', None)
    for _sub in _DNSPY_SUBMODULES:
        sys.modules.pop(f'dns.{_sub}', None)
    _had_path = _watchfuls_dir in sys.path
    if _had_path:
        sys.path.remove(_watchfuls_dir)
    mods = None
    try:
        import importlib as _il  # noqa: PLC0415
        mods = {name: _il.import_module(f'dns.{name}') for name in _DNSPY_SUBMODULES}
    except ImportError:
        mods = None
    finally:
        if _had_path and _watchfuls_dir not in sys.path:
            sys.path.insert(0, _watchfuls_dir)
        # Restore the watchful as sys.modules['dns'] so future calls to
        # importlib.import_module('dns') still return the correct watchful.
        if _saved_dns is not None:
            sys.modules['dns'] = _saved_dns
    return mods


def _load_dns_resolver():
    """Return the dnspython ``resolver`` submodule, or None if unavailable."""
    mods = _load_dnspython()
    return mods['resolver'] if mods else None
