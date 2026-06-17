#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistence stores: thin DB-backed repositories, one per domain entity.

Each submodule owns one table (schema declared via lib.db.schema) and exposes a
Store class:
    audit        — AuditStore (the audit trail)
    check_state  — CheckStateStore / DbBackedStatus (per-check live state)
    groups       — GroupsStore
    history      — HistoryStore (time-series of check results)
    hosts        — HostsStore (host registry + per-protocol encrypted profiles)
    roles        — RolesStore
    sessions     — SessionsStore
    users        — UsersStore
"""
