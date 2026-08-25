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

from lib.core.snmp import profiles as _profiles
from lib.core.snmp.actions import SnmpActions
from .checks import SnmpChecks
from lib.core.snmp.client import SnmpClient, _HAS_PYSNMP
from .defaults import _SCHEMA, _CHECK_DEFAULTS, _SERVER_DEFAULTS
from lib.core.snmp.mibs.admin import MibAdmin, startup_compile_mibs as _startup_compile_mibs, _HAS_PYSMI
from .sampler import SnmpSampler
from .widget import SnmpWidget

# What is left here is the module itself: the class, what it declares and what it offers the
# panel. Everything that answered a different question has its own file — speaking SNMP to a
# device (client), running the checks (checks), administering the MIB catalogue (mib_admin),
# the operations the panel invokes (actions) and turning a profile into a series (sampler).
# They are mixed back in below, so the class is unchanged from the outside.


class Watchful(MibAdmin, SnmpChecks, SnmpClient, SnmpActions, SnmpSampler,
               SnmpWidget, ModuleBase):
    """Multi-server SNMP OID monitoring."""

    ITEM_SCHEMA = _SCHEMA

    MISSING_DEPS: list[str]  = [] if _HAS_PYSNMP else ['pysnmp']
    PARTIAL_DEPS: list[str]  = [] if _HAS_PYSMI  else ['pysmi']

    # One action, and it is the only one that was ever about a check: `discover` finds the
    # OIDs to build a check's field from. Everything else this module used to answer for —
    # the MIB library, the profile catalogue, asking a device what it serves — is the core's
    # and answers at /api/v1/snmp/<action>. They were listed here because that was the only
    # place a panel operation could be listed, not because a check owned them.
    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'discover'})

    # Actions that produce no side effects — audit logging is suppressed for them.
    READ_ONLY_ACTIONS: frozenset[str] = frozenset({'discover'})


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
        # Told where the library is and how to log, rather than reaching into this object for
        # both: it was the one thing in the core's MIB administration that needed an instance.
        _startup_compile_mibs(str(getattr(monitor, 'dir_var', '') or '').strip(), self._debug)

def discover_history_sources(lang: str = 'en_EN', var_dir: str = '') -> dict:
    """``{profile id: {label, short, rank}}`` — what to call the things that answered.

    Separate from the fields on purpose. A screen groups a device's facts by whatever produced
    them, and a profile of pure identity facts (the VLAN table, the neighbour table) records no
    measurement at all — so reading the names off the field map left exactly those cards headed
    with a raw id.
    """
    cdir = _profiles.custom_dir(var_dir)
    catalog = _profiles.catalog(custom=_profiles.load_dir(cdir) if cdir else None)
    return {pid: _profiles.history_source(prof, lang) for pid, prof in catalog.items()}


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
