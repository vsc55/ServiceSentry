#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host domain: connection profiles, remote command running, single-check
probing and the assisted inline-connection migration planner.

Submodules:
    profiles — connection-profile catalog per protocol (module_host_fields/specs)
    runner   — local/SSH command execution helpers (run, is_remote)
    probe    — run a single module check once (used by the host wizard)
    migrate  — detect duplicate inline connections and plan their migration

The host registry itself (HostsStore) lives with the other stores in
lib.stores.hosts.
"""
