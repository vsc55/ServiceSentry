#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this package contributes: its permissions, its tables, its audit lines and its section.

**Why the permissions are the core's and not the inventory's.** They were `dcim_all_view` and
`dcim_org_edit`, which said that seeing every company and deciding whose things are were facts
about a rack. They are not: the same company that pays for the cabinet has users in the
directory and licences in Microsoft 365, and a role that may see subsidiary B should see
subsidiary B's things wherever they are. Two flags named after one section could not say that.

**Deciding whose something is stays its own flag.** `orgs_edit` moves a piece of property between
companies; in a group that means billing, and it means who may see it — which is not the same
authority as tidying a cabinet. No role carries it by default, not even `editor`.
"""

from .store import SCHEMAS as _TABLES

MODULE_PERMISSIONS = {
    'group': 'perm_group_orgs',       # i18n key for the role-editor group heading
    'order': 47,                      # right after the inventory: the other axis of the same fleet
    'permissions': (
        # The registry itself. Both roles: it is a list of the group's companies, and it is
        # already half-visible anywhere a badge names one.
        {'flag': 'orgs_view', 'roles': ('editor', 'viewer')},
        # …and everything of every company, rather than only the companies granted one by one.
        # Both roles by default, so nothing narrows on the day this lands: a role is narrowed by
        # NOT holding this and holding `org.<uid>.view` instead, which is opt-in and visible in
        # the role editor rather than implied by an absence.
        {'flag': 'orgs_all_view', 'roles': ('editor', 'viewer')},
        # Create companies, and say who owns what. No role by default — see the docstring.
        {'flag': 'orgs_edit', 'roles': ()},
    ),
}


AUDIT_EVENTS = [
    # Whose things are. This line is the answer to "since when was that ours", and it is the one
    # somebody goes looking for months later.
    {'key': 'org_owner_set', 'severity': 'info'},
    # And removing a company. Louder than a rename: everything that was on her name stops being
    # on anybody's, which is a change to what a dozen screens show and no screen announces.
    {'key': 'org_deleted', 'severity': 'warning'},
]


# ── Tables this package keeps in the shared database ─────────────────────────────────────
DB_TABLES = list(_TABLES)


# ── The section this package claims ──────────────────────────────────────────────────────
#
# `placement: system` because of what it IS: something an operator ADMINISTERS, filed beside
# Services, Modules and Credentials, not beside the dashboards an operator watches. It is
# written on the first day and almost never again.
#
# `i18n` names the section of the core language files its words come from. A module's page is
# titled by its `pretty_name` because the core owns no string that names a module; a core
# section names itself.
PAGE: dict = {
    'id': 'orgs', 'icon': 'bi-buildings', 'order': 40,
    'placement': 'system', 'perm': 'orgs_view',
    'render': 'renderOrgsPage',
    'i18n': 'orgs_page',
}
