#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DB-backend smoke test: boot the WebAdmin against the configured database and
confirm the whole schema reconciles cleanly — twice (idempotency).

Constructing :class:`WebAdmin` runs ``_init_entity_store`` + ``reconcile_module_tables``,
which creates EVERY table (users/roles/config/hosts/history/syslog/events/service_*
and the module tables) via the pluggable connector.  The DB backend comes from the
``SS_DB_*`` env (overlaid by ``bootstrap_database_cfg``), so pointing it at SQLite,
MySQL/MariaDB or PostgreSQL exercises that engine's DDL — catching cross-engine bugs
(e.g. MySQL can't index a plain TEXT column) that the SQLite-only unit tests miss.

Run (from anywhere; adds ``src`` to the path itself):
    SS_DB_DRIVER=mysql SS_DB_HOST=127.0.0.1 ... python src/tools/db_smoke.py
"""

from __future__ import annotations

import os
import sys
import tempfile

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../src
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def main() -> int:
    from lib.web_admin import WebAdmin  # noqa: PLC0415

    driver = os.environ.get('SS_DB_DRIVER', 'sqlite')
    modules_dir = os.path.join(_SRC, 'watchfuls')
    config_dir = tempfile.mkdtemp(prefix='ss-cfg-')
    var_dir = tempfile.mkdtemp(prefix='ss-var-')
    print(f'[db-smoke] engine={driver} config={config_dir}', flush=True)

    # Two passes: the first CREATEs the schema, the second must reconcile an
    # existing schema with no changes (a VARCHAR/TEXT mismatch would loop-rebuild).
    for i in (1, 2):
        wa = WebAdmin(config_dir, 'admin', 'admin', var_dir, modules_dir=modules_dir)
        print(f'[db-smoke] pass {i}: schema reconciled on {driver}', flush=True)
        try:
            wa._db_connector.close()
        except Exception:  # pylint: disable=broad-except
            pass

    print('[db-smoke] OK', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
