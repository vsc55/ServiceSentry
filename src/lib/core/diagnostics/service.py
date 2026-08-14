#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free diagnostics helpers extracted from :mod:`lib.core.diagnostics.routes`.

Everything here takes the web admin (`wa`) and reads what it already holds — the connector, the
paths, the embedded services, the config. It imports no Flask and touches no request: the route
layer is left with three route declarations, a permission and an audit line, which is all a
route layer should be.

The split is by *what the answer depends on*, not by file size. :mod:`collect` is a function of
the process and the disk and needs nothing; this is a function of the running panel; and
:mod:`report` is a function of what those two returned. Only the middle one can be wrong in a
way that depends on how the install is deployed, which is the part worth being able to read on
its own.
"""

from __future__ import annotations

import os

from lib import __version__
from lib.config.spec import cfg_default
from lib.core.diagnostics import collect


def lock_path() -> str:
    """`src/requirements.lock`, from this file's own position in the tree.

    Walked up from `__file__` rather than read off the app or the working directory: the
    process may have been started from anywhere, and a diagnostics page that reports "no
    dependency information" because somebody `cd`'d is worse than none.
    """
    here = os.path.dirname(os.path.abspath(__file__))          # …/src/lib/core/diagnostics
    src = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(src, 'requirements.lock')


def database(wa) -> dict:
    """Which engine, which driver, and where.

    Read from the connector the panel is already using — asking the config would report what it
    was *told*, and the interesting case is exactly when those two differ.
    """
    conn = getattr(wa, '_db_connector', None)
    syslog = getattr(wa, '_syslog_db_connector', None)
    out = {'engine': getattr(conn, 'KIND', collect.UNKNOWN) if conn else collect.UNKNOWN,
           'path': str(getattr(conn, '_path', '') or ''),
           'separate_syslog_db': bool(syslog is not None and syslog is not conn)}
    if syslog is not None and syslog is not conn:
        out['syslog_engine'] = getattr(syslog, 'KIND', collect.UNKNOWN)
    return out


def runtime(wa) -> dict:
    """How this process is deployed — the answer that reframes every other one.

    Whether the scheduler runs HERE decides where to look for a check that did not run, and on
    a multi-container install that is a different container from the one serving this page.
    """
    # `global|log_level`, read the way `_apply_log_level` reads it. There is no attribute
    # mirroring it on the instance — it is applied to the shared debug printer and not held —
    # and asking for one answered an empty string, so the field said "—" on every install. A
    # diagnostics page reporting a blank where a value exists is worse than not showing the
    # row: it reads as "this is not set".
    section = wa._config_section('global') if hasattr(wa, '_config_section') else {}
    level = (section or {}).get('log_level', cfg_default('global|log_level'))
    return {
        'version': __version__,
        # `_startup_id`, which is what this process actually has: a uuid minted at start-up and
        # the thing the browser watches to notice the panel restarted. There is no
        # `_instance_id` on the web admin — asking for one answered '' and the field said "—"
        # everywhere, which reads as "this install has no identity" rather than "this page
        # asked the wrong question".
        'startup_id': str(getattr(wa, '_startup_id', '') or ''),
        'embedded_services': sorted(getattr(wa, '_embedded_services', {}) or {}),
        'log_level': str(level or ''),
        'var_dir': str(getattr(wa, '_var_dir', '') or ''),
        'config_dir': str(getattr(wa, '_config_dir', '') or ''),
    }


def storage_paths(wa) -> dict:
    """The three directories worth reporting on, resolved the way their owners resolve them."""
    var_dir = str(getattr(wa, '_var_dir', '') or '')
    return {
        'var_dir': var_dir,
        'config_dir': str(getattr(wa, '_config_dir', '') or ''),
        # Empty `backup_dir` means `<var_dir>/backups`, and the page has to report where copies
        # ACTUALLY land — not the setting, which is blank on most installs.
        'backup_dir': (str(getattr(wa, '_BACKUP_DIR', '') or '')
                       or os.path.join(var_dir, 'backups')),
    }


def update_url(wa) -> str:
    """Where to ask about new releases. Configurable so a fork — or an install behind an
    internal mirror — points somewhere else without a code change; empty means the built-in
    default in :mod:`lib.core.diagnostics.update`."""
    section = wa._config_section('web_admin') if hasattr(wa, '_config_section') else {}
    return str((section or {}).get('update_check_url') or '')


def payload(wa) -> dict:
    """Everything answerable without leaving the machine.

    Computed on every call and never cached: a diagnostics page served from a cache describes
    the problem you had before.
    """
    return {
        'runtime': runtime(wa),
        'system': collect.system_info(),
        'database': database(wa),
        'storage': collect.storage(storage_paths(wa)),
        'dependencies': collect.dependencies(lock_path()),
        'features': collect.optional_features(),
    }
