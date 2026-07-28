#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Datastore watchful: which client libraries are actually installed.
#
"""One import attempt per backend, and the verdict about the module as a whole.

Every engine this watchful supports needs its own client library, and none of them is going
to be present everywhere. So each is probed once, here, and the rest of the module asks this
file instead of wrapping its own try/except - five files needed the same answer.

pymysql is the only hard requirement: without it the module cannot function and is disabled.
Any other absence disables one engine and leaves the module usable, which is the difference
between MISSING_DEPS and PARTIAL_DEPS.
"""

# These names ARE this file's product: the import is the probe, and the flag is the answer.
# Declaring them keeps a linter from reading "imported but unused" as a mistake - the module
# objects are re-imported where they are actually spoken to (engines.py, tunnel.py), which is
# free, since the second import hits the interpreter's module cache.
__all__ = ['_PYMYSQL', '_PARAMIKO', '_PSYCOPG2', '_PYMSSQL', '_PYMONGO', '_REDIS',
           '_PYMEMCACHE', '_ALL_BACKENDS', '_MISSING_BACKENDS',
           'pymysql', 'paramiko', 'psycopg2', 'pymssql', 'pymongo', 'redis_lib', '_pmc']

try:
    import pymysql
    import pymysql.cursors
    _PYMYSQL = True
except ImportError:
    _PYMYSQL = False

try:
    import paramiko
    _PARAMIKO = True
except ImportError:
    _PARAMIKO = False

try:
    import psycopg2
    _PSYCOPG2 = True
except ImportError:
    _PSYCOPG2 = False

try:
    import pymssql
    _PYMSSQL = True
except ImportError:
    _PYMSSQL = False

try:
    import pymongo
    _PYMONGO = True
except ImportError:
    _PYMONGO = False

try:
    import redis as redis_lib
    _REDIS = True
except ImportError:
    _REDIS = False

try:
    import pymemcache.client.base as _pmc
    _PYMEMCACHE = True
except ImportError:
    _PYMEMCACHE = False

# ── Dependency availability ───────────────────────────────────────────────────

# pymysql is the only hard requirement for this module (MySQL/MariaDB).
# All other backends are optional: their absence only disables that specific engine.
_ALL_BACKENDS: list[tuple[str, bool]] = [
    ('PyMySQL',         _PYMYSQL),
    ('paramiko',        _PARAMIKO),
    ('psycopg2-binary', _PSYCOPG2),
    ('pymssql',         _PYMSSQL),
    ('pymongo',         _PYMONGO),
    ('redis',           _REDIS),
    ('pymemcache',      _PYMEMCACHE),
]
# Packages that are absent — used to populate MISSING_DEPS / PARTIAL_DEPS.
_MISSING_BACKENDS: list[str] = [pkg for pkg, ok in _ALL_BACKENDS if not ok]
