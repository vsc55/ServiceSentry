#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Datastore watchful: the static lookups.
#
"""The port to use when none was given, the name to print, and the config vocabulary.

Their own file because the check loop, the actions and the config resolution all read them,
and none of the three owns them.
"""

from enum import IntEnum

# Default TCP port per engine (used when port == 0)
_DEFAULT_PORTS = {
    'mysql': 3306, 'mariadb': 3306,
    'postgres': 5432,
    'mssql': 1433,
    'mongodb': 27017,
    'redis': 6379, 'valkey': 6379,
    'elasticsearch': 9200, 'opensearch': 9200,
    'influxdb': 8086,
    'memcached': 11211,
}

_PRETTY = {
    'mysql': 'MySQL / MariaDB', 'mariadb': 'MySQL / MariaDB',
    'postgres': 'PostgreSQL', 'mssql': 'MSSQL',
    'mongodb': 'MongoDB',
    'redis': 'Redis / Valkey', 'valkey': 'Redis / Valkey',
    'elasticsearch': 'Elasticsearch / OpenSearch', 'opensearch': 'Elasticsearch / OpenSearch',
    'influxdb': 'InfluxDB',
    'memcached': 'Memcached',
}


# ── ConfigOptions ─────────────────────────────────────────────────────────────

class ConfigOptions(IntEnum):
    enabled      = 1
    db_type      = 2
    conn_type    = 3
    host         = 100
    port         = 101
    user         = 102
    password     = 103
    db           = 104
    socket       = 105
    scheme       = 106
    auth_db      = 107
    db_index     = 108
    tls          = 109
    timeout      = 111
    token        = 110
    ssh_host        = 200
    ssh_port        = 201
    ssh_user        = 202
    ssh_password    = 203
    ssh_key         = 204
    ssh_verify_host = 205
    ssh_key_string  = 206
