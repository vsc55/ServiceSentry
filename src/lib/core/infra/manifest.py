#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the infrastructure domain owns, and what it writes to the audit log.

Discovered by :func:`lib.core.permissions.discover_permissions` and merged by
:mod:`lib.web_admin.constants`, like every other domain's.

**Reading is not ``devices_view``.** Reading the live state of the fleet and editing the
registry that defines it are different acts, wanted by different people: the person watching a
screen at 3am needs the first and must not be handed the second, which carries the addresses,
the bound credentials and the buttons that change them. That split is the whole reason this
section exists apart from System › Infrastructure.

**And asking for fresh numbers is neither of them.** The section shows what the last cycle
recorded, so the newest thing on it can be an hour old — the interval is a setting, and an
SNMP profile that takes minutes is slower still. "Collect now" is the answer to that, and it
is a third act: it costs the device a poll, it can run for minutes, and it makes the checks
announce whatever they find. A viewer reading a wall screen must not be able to start it by
leaning on a button, so it has a flag of its own rather than riding on ``infra_view``.

There is still no ``infra_edit``: nothing here writes a record of its own. Collecting writes
through the modules, which is the same path the scheduler uses and the same permission model —
what there is to CHANGE lives in the registry, behind the permissions the registry already has.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_infra',      # i18n key for the role-editor group heading
    'order': 45,                      # between the services (10–40) and the core domains
    'permissions': (
        # The fleet, live. Granted to editor and viewer by default: it is a read of things
        # both roles can already reach one screen over, arranged by machine instead of by
        # check.
        {'flag': 'infra_view', 'roles': ('editor', 'viewer')},
        # Run this device's checks now. `editor` and not `viewer`, exactly like `checks_run`
        # (lib/services/monitoring/manifest.py) — the same act from the other screen, so the
        # two roles that may operate monitoring are the same two in both places.
        {'flag': 'infra_collect', 'roles': ('editor',)},
        # Say that one row of one machine is worth an alert. `editor`, like collecting: it
        # decides what wakes somebody up, which is operating the monitoring and not looking
        # at it. NOT `devices_edit`: it stores no address, no credential and no name — the
        # registry stays behind its own permission.
        {'flag': 'infra_watch', 'roles': ('editor',)},
    ),
}


# What this package writes to the audit log, and how loud each one is. Declared
# rather than guessed from the event name: the badge is the only thing a glance
# down two hundred rows gives you, and deriving it from a noun made the colour
# depend on what somebody called the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'infra_collect', 'severity': 'muted'},
    # Louder than a collection: this one changes what the panel will and will not report,
    # and "why did nobody get told" is a question answered by this line.
    {'key': 'infra_watch', 'severity': 'info'},
    # Quieter than either: where somebody dragged the boxes on a map. It is on the audit log
    # at all because it reaches the account record, and a write to that store is worth a line
    # even when what it holds is a picture.
    {'key': 'infra_link_layout', 'severity': 'muted'},
]


# ── Tables this package keeps in the shared database ─────────────────────────────────────
#
# What devices SAW, which is not what checks found: a switch's forwarding table and a
# machine's ARP cache. Hundreds of volatile rows per device that nobody wants alerts about
# and that are only worth anything joined across the fleet — see `evidence.py` for why they
# are not results.
#
# Declared for the sake of STARTUP: the store reconciles its own table when it is built, but
# it is built on demand (a cycle that samples a switch, a request that draws the map), and
# the two ways of arriving there are not equally forgiving.
from .evidence import SCHEMA as _EVIDENCE   # noqa: E402

DB_TABLES = [_EVIDENCE]

# What this package runs in the background, for the screen that lists all of it
# (lib/core/jobs). Declared rather than reached into: a core that imported four job
# registries by name would have to be edited to learn about a fifth.
from .jobs import live as BACKGROUND_JOBS      # noqa: E402,F401  (a descriptor)
