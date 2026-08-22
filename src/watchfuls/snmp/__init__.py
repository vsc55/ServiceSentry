#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — SNMP monitoring watchful.
#
# Defines a set of *servers* (connection profiles) and a set of *checks*
# (OID queries), where each check references a server by its key.
# Multiple servers and multiple checks per server are supported.
#
# Optional dependency: pysnmp >= 6  (pip install pysnmp)
"""SNMP watchful — multi-server OID monitoring."""

import concurrent.futures
import re

from lib.debug import DebugLevel
from lib.modules import ModuleBase

from . import profile_store as _profile_store
from lib.core.snmp import profiles as _profiles
from .actions import SnmpActions
from .checks import SnmpChecks
from .client import SnmpClient, _HAS_PYSNMP
from .defaults import _SCHEMA, _CHECK_DEFAULTS, _SERVER_DEFAULTS
from .mib_admin import MibAdmin, _HAS_PYSMI
from . import mib_versions as _mib_versions
from .sampler import SnmpSampler

# What is left here is the module itself: the class, what it declares and what it offers the
# panel. Everything that answered a different question has its own file — speaking SNMP to a
# device (client), running the checks (checks), administering the MIB catalogue (mib_admin),
# the operations the panel invokes (actions) and turning a profile into a series (sampler).
# They are mixed back in below, so the class is unchanged from the outside.


class Watchful(MibAdmin, SnmpChecks, SnmpClient, SnmpActions, SnmpSampler,
               ModuleBase):
    """Multi-server SNMP OID monitoring."""

    ITEM_SCHEMA = _SCHEMA

    MISSING_DEPS: list[str]  = [] if _HAS_PYSNMP else ['pysnmp']
    PARTIAL_DEPS: list[str]  = [] if _HAS_PYSMI  else ['pysmi']

    WATCHFUL_ACTIONS: frozenset[str] = frozenset({
        'discover',
        'list_profiles',
        'detect_profiles',
        'test_profiles',
        'test_profiles_start',
        'test_profiles_status',
        'save_profile_group',
        'delete_profile_group',
        'save_profile',
        'delete_profile',
        'list_mibs',
        'list_mib_sources',
        'compile_mibs',
        'compile_mibs_start',
        'compile_mibs_status',
        'compile_mibs_cancel',
        'delete_mib',
        'upload_mib',
        'import_mib_from_url',
        'import_mib_from_github',
        'import_mib_from_github_start',
        'import_mib_from_github_status',
        'import_mib_archive',
        'import_mib_archive_start',
        'import_mib_archive_status',
        'get_mib_details',
        'get_raw_mib_details',
        'get_all_symbols',
        'build_oid_index',
        'save_mib_source',
        'diff_mib_versions',
        'restore_mib_version',
        'list_mib_versions',
        'get_mib_version',
        'lint_mib_source',
        'delete_mib_version',
        'orphan_versions',
        'diff_mib_files',
        'mib_dupe_details',
        'restore_orphan',
        'forget_mib_versions',
        'library_leftovers',
        'clean_library',
    })

    # Actions that produce no side effects — audit logging is suppressed for them.
    READ_ONLY_ACTIONS: frozenset[str] = frozenset({
        'discover',
        'list_profiles',
        'detect_profiles',
        'test_profiles',
        'test_profiles_start',
        'test_profiles_status',
        'list_mibs',
        'list_mib_sources',
        'get_mib_details',
        'get_raw_mib_details',
        'get_all_symbols',
        'list_mib_versions',
        'get_mib_version',
        'diff_mib_versions',
        'lint_mib_source',
        'orphan_versions',
        'diff_mib_files',
        'mib_dupe_details',
        'library_leftovers',
    })


    # No toolbar. All three of these used to be buttons on the module's card in Modules,
    # each throwing a dialog over whatever was on screen — the library, the symbol browser
    # and the profile catalogue. They are the SNMP section now, and its views: a card in a
    # list of modules is where you configure a module, not where you administer what it
    # holds. The profile picker is still a dialog, because it is opened from inside another
    # one (a server's `device_profiles` field) and answers to it.
    WATCHFUL_TOOLBAR: tuple[dict, ...] = ()

    # Legacy compat alias so ModuleBase helpers that expect _DEFAULTS still work
    _DEFAULTS        = _CHECK_DEFAULTS
    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])


    def __init__(self, monitor):
        super().__init__(monitor, __package__)
        self._startup_compile_mibs()

def discover_history_fields(lang: str = 'en_EN', var_dir: str = '') -> dict:
    """Every value a device profile can record, named — see lib.modules.history_fields.

    What this module charts is not knowable at build time: it is decided by the profiles
    installed, which are files, and one of them was written for the box in somebody's rack
    after this release shipped. The static __history__ in schema.json says a check has no
    numeric field, which is true of a check; a sampled metric arrives with a name only if the
    profile that declared it is asked.

    The UNION of the catalogue, not the profiles actually assigned: a field's label answers
    "what is this series", which does not depend on which device happens to serve it, and
    working out the assignments would mean reading the module configuration from a function
    whose whole point is that it does not need it.
    """
    cdir = _profiles.custom_dir(var_dir)
    catalog = _profiles.catalog(custom=_profiles.load_dir(cdir) if cdir else None)
    out: dict = {}
    for prof in catalog.values():
        # First profile to name a field wins: two profiles measuring "cpu_user" are measuring
        # the same thing, and the alternative is a label that changes with dict order.
        for field, meta in _profiles.history_fields(prof, lang).items():
            out.setdefault(field, meta)
    return out


def discover_db_tables():
    """The tables this module keeps in the shared database.

    Edited MIB sources and their history, and the profile groupings written in the panel. On
    the general connector rather than files beside the MIBs because a deployment with a web
    container and a worker container shares the database and not the disk — and a MIB
    corrected in the panel has to be the MIB the worker compiles, exactly as a grouping made
    in the panel has to be the one the worker samples.
    """
    return [_mib_versions.SCHEMA, _profile_store.SCHEMA]
