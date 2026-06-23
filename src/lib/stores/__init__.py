#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistence stores: thin DB-backed repositories, one per domain entity.

Each submodule owns one or more tables (schema declared via lib.db.schema) and
exposes a Store class:
    audit        — AuditStore (the audit trail)
    check_state  — CheckStateStore / DbBackedStatus (per-check live state)
    config       — ConfigStore (editable configuration; one row per section|field)
    credentials  — CredentialsStore (reusable named SSH identities)
    groups       — GroupsStore (tables: groups, groups_roles)
    history      — HistoryStore (time-series of check results)
    hosts        — HostsStore (host registry + per-protocol encrypted profiles)
    modules      — ModulesStore / DbBackedModules (watchful module/item config;
                   tables: module_config, module_config_items)
    roles        — RolesStore
    sessions     — SessionsStore
    syslog       — SyslogStore (received syslog messages; time+row retention)
    users        — UsersStore (tables: users, users_groups)
    webhooks     — WebhooksStore (outgoing notification webhooks)
"""
