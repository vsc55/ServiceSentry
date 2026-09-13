#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hosts domain — everything about hosts in one place (the "Servers" tab; see
:mod:`lib.core`).

Admin/registry layer:
* ``stores``  — the domain's TABLES, one per file: ``stores/hosts.py`` (the host registry and its
  encrypted profiles) and ``stores/types.py`` (``host_type``, the device classes). Read and
  written here; import either from ``lib.core.hosts.stores``.
* ``classes`` — what the panel ASKS about those classes (catalog / ensure / known / uid_for /
  in_use / usage). A layer above the store, because whoever draws a class or brings one in from
  a provider has nothing to say to the table — it asks the panel a question.
* ``routes`` — module ``routes.py`` (``register``): /api/v1/hosts endpoints
* ``permissions`` — ``MODULE_PERMISSIONS`` (group ``perm_group_devices``: devices_view / add / edit / delete)
* ``overview_widget`` — the servers/coverage/servers_list Overview widgets

Execution/connection primitives (also used by the monitoring engine ``lib.modules`` and
``lib.system`` — core is the foundational layer they build on):
* ``profiles``   — connection-profile catalog per protocol (module_host_fields/specs)
* ``resolve``    — shared host-resolution primitives (host_profile_specs, resolve_os)
* ``ssh_client`` — SSH transport (paramiko connect / run_command / test_connection)
* ``runner``     — local/SSH command execution (run, is_remote)
* ``probe``      — run a single module check once (the Servers "test" feature)
* ``migrate``    — detect duplicate inline connections and plan their migration

Folder named ``hosts`` (matches the store/table); the permission group is ``servers``
(the user-facing tab).  Keep this ``__init__`` lightweight — do NOT import the submodules
here (permission discovery imports ``permissions`` very early; a heavy ``__init__`` that
pulls in the Flask/SSH glue would risk an import cycle).
"""
