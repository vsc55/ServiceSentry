#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the SNMP package contributes to the rest of the panel (see :mod:`lib.discovery`).

Kept to descriptors: data, and the odd callable. Whatever needs real code lives in its own
module and is imported here, so this file stays a readable list of what the package offers.
"""

from __future__ import annotations

# ── The connection a Host carries for this protocol ──────────────────────────────────────
#
# Declared by the core, the way SSH is, and for the same reason SSH is: **an SNMP profile is
# a property of the device**. Its address, its port, the identity it answers to and what it
# declares itself to be do not stop being true when no check exists, and re-entering them on
# every check that points at one box is how a device ends up authenticating two ways.
#
# It was the SNMP *watchful* that declared this until now, which had a consequence beyond
# tidiness: the host form could only offer a protocol whose module happened to be installed,
# and core code that needed to know what an SNMP connection looks like had to go and read a
# module's schema.json to find out.
#
# The module still declares its own ``__host_profile__`` — that is how a CHECK inherits these
# fields when it is bound to a host — and it still declares the same fields inline, because a
# check against a bare IP has to remain possible. Those two copies and this one are pinned
# against each other by tests/meta/test_snmp_host_profile_agrees.py.
HOST_PROFILE: dict = {
    'key':           'snmp',
    'module':        'snmp',      # whose credential type the form offers (snmp_auth)
    'address_field': 'host',      # filled from the host's address; never drawn
    # Field labels come from the lang files under this section, exactly as the built-in SSH
    # profile's do: a core-owned form takes its words from core i18n.
    'i18n':          'snmp_profile',
    'fields': [
        {'name': 'host', 'type': 'str', 'placeholder': '192.168.1.1', 'default': ''},
        {'name': 'port', 'type': 'int', 'min': 1, 'max': 65535, 'default': 161},
        {'name': 'version', 'type': 'str', 'default': '2c', 'options': ['1', '2c', '3']},
        {'name': 'community', 'type': 'str', 'default': 'public', 'secret': True,
         'show_when': {'version': ['1', '2c']}},
        {'name': 'snmpv3_username', 'type': 'str', 'default': '',
         'show_when': {'version': ['3']}},
        {'name': 'snmpv3_auth_key', 'type': 'str', 'default': '', 'secret': True,
         'show_when': {'version': ['3']}},
        {'name': 'snmpv3_priv_key', 'type': 'str', 'default': '', 'secret': True,
         'show_when': {'version': ['3']}},
        {'name': 'snmpv3_auth_protocol', 'type': 'str', 'default': 'MD5',
         'options': ['MD5', 'SHA', 'SHA-224', 'SHA-256', 'SHA-384', 'SHA-512', 'none'],
         'show_when': {'version': ['3']}},
        {'name': 'snmpv3_priv_protocol', 'type': 'str', 'default': 'DES',
         'options': ['DES', '3DES', 'AES-128', 'AES-192', 'AES-256', 'none'],
         'show_when': {'version': ['3']}},
        # What the device declares itself to be. A list, with a picker beside it — typed by
        # hand these are ids, and a misspelt one is a device that measures nothing.
        {'name': 'device_profiles', 'type': 'str', 'default': '', 'multi': True},
    ],
}


# ── The operations the panel may invoke ──────────────────────────────────────────────────
#
# Reachable at ``/api/v1/snmp/<action>`` (lib/core/snmp/routes.py). They used to be watchful
# actions, dispatched at ``/api/v1/modules/watchfuls/snmp/<action>`` — a path that described
# where the code lived rather than what the endpoint is about. Compiling a MIB or writing a
# device profile is not something a *check* does.
#
# ``discover`` is deliberately absent: it finds OIDs for the field of a check, so it is a
# check's action and stays with the watchful. The split is by what an operation is ABOUT.
ACTIONS: frozenset[str] = frozenset({
    # the MIB library
    'list_mibs', 'list_mib_sources', 'get_mib_details', 'get_raw_mib_details',
    'get_all_symbols', 'build_oid_index', 'upload_mib', 'delete_mib',
    'compile_mibs', 'compile_mibs_start', 'compile_mibs_status', 'compile_mibs_cancel',
    'import_mib_from_url', 'import_mib_from_github', 'import_mib_from_github_start',
    'import_mib_from_github_status', 'import_mib_archive', 'import_mib_archive_start',
    'import_mib_archive_status', 'save_mib_source', 'lint_mib_source',
    # its edit history
    'list_mib_versions', 'get_mib_version', 'diff_mib_versions', 'restore_mib_version',
    'delete_mib_version', 'forget_mib_versions', 'orphan_versions', 'restore_orphan',
    # what a library is holding that nobody wants
    'diff_mib_files', 'mib_dupe_details', 'library_leftovers', 'clean_library',
    # the device-profile catalogue
    'list_profiles', 'save_profile', 'save_profile_group',
    'delete_profile', 'delete_profile_group',
    # …and asking a device about it
    'detect_profiles', 'test_profiles', 'test_profiles_start', 'test_profiles_status',
})

#: Operations that change nothing. They need only ``snmp_view``, and are not audited — an
#: audit log that records every read is one nobody reads.
READ_ONLY: frozenset[str] = frozenset({
    'list_mibs', 'list_mib_sources', 'get_mib_details', 'get_raw_mib_details',
    'get_all_symbols', 'lint_mib_source',
    'list_mib_versions', 'get_mib_version', 'diff_mib_versions', 'orphan_versions',
    'diff_mib_files', 'mib_dupe_details', 'library_leftovers',
    'list_profiles',
    'detect_profiles', 'test_profiles', 'test_profiles_start', 'test_profiles_status',
})


# ── Permissions this package owns (see lib.core.permissions) ─────────────────────────────
#
# Its own, rather than borrowing the modules flags it used to hang off. That was never a
# decision: a watchful owns no permission flags, so everything SNMP offered was gated by
# "can this person see modules" — which meant the MIB library could not be granted to
# somebody without granting them every module in the panel, and could not be withheld from
# somebody who needed the rest.
MODULE_PERMISSIONS = {
    'group': 'perm_group_snmp',
    'order': 165,                 # beside Servers (160): what the devices there are made of
    'permissions': (
        # Reading the library and the catalogue, and asking a device what it serves — the
        # last one talks to the network but changes nothing, here or on the device.
        {'flag': 'snmp_view',   'roles': ('editor', 'viewer')},
        # Compiling, importing, deleting, editing a MIB source, and writing device profiles.
        {'flag': 'snmp_manage', 'roles': ('editor',)},
    ),
}


# ── What this package writes to the audit log ────────────────────────────────────────────
#
# Declared rather than derived from the name: the badge is the only thing a glance down two
# hundred rows gives you, and deriving it from a noun makes the colour depend on what
# somebody called the event.
#
# Muted, like the module action it replaces. It is one row per operation, and the operations
# people run in bulk — compiling a library, importing an archive — would otherwise paint a
# page of warnings for work that went fine.
AUDIT_EVENTS = [
    {'key': 'snmp_action', 'severity': 'muted'},
]


# ── The section this package claims ──────────────────────────────────────────────────────
#
# A page of its own, declared here rather than in a module's schema.json. The MIB library,
# the symbol browser and the profile catalogue are the core's: a screen that disappeared when
# somebody removed the SNMP watchful would be a library you can still fill and no longer look
# at, and a catalogue the sampler still reads with nowhere to edit it.
#
# `placement: system` because of what it IS: something an operator ADMINISTERS, filed beside
# Services, Modules and Credentials, not beside the dashboards an operator watches.
#
# `i18n` names the section of the core lang files its words come from — the title and one per
# view. A module's page is titled by its `pretty_name` because the core owns no string that
# names a module; a core section names itself.
PAGE: dict = {
    'id': 'snmp', 'icon': 'bi-hdd-stack', 'order': 25,
    'placement': 'system', 'perm': 'snmp_view',
    'render': 'renderSnmpMibsPage',
    'i18n': 'snmp_page',
    'views': [
        {'slug': 'library',  'icon': 'bi-hdd-stack',      'label': 'view_mibs'},
        {'slug': 'import',   'icon': 'bi-cloud-download', 'label': 'view_import'},
        {'slug': 'compile',  'icon': 'bi-gear',           'label': 'view_compile'},
        {'slug': 'browser',  'icon': 'bi-diagram-3',      'label': 'view_browser'},
        {'slug': 'profiles', 'icon': 'bi-grid-3x3-gap',   'label': 'view_profiles'},
    ],
}


# ── What a backup must hold of this package ──────────────────────────────────────────────
#
# The raw MIB files. Not derived data — they are what somebody imported, corrected and, in
# more than one case, spent an afternoon on; the compiled tree and the symbol index are both
# rebuilt from them.
#
# Declared here rather than in a module's schema.json because of how the old arrangement
# failed: a backup part lives exactly as long as the file declaring it, so removing the SNMP
# watchful took the library out of every backup **and said nothing**. The archive is simply
# smaller, and you find out when you need it.
#
# `default: False` deliberately: a library of vendor archives is large and re-importable, so
# it is offered rather than assumed. What matters is that it can be chosen at all.
BACKUP_PART: dict = {
    'id': 'mibs', 'dir': 'snmp_mibs/raw',
    'i18n': 'snmp_ui', 'label_key': 'backup_part_mibs',
    'default': False,
}
