#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the infrastructure domain owns.

Discovered by :func:`lib.core.permissions.discover_permissions` and merged by
:mod:`lib.web_admin.constants`, like every other domain's.

**One flag, and it is not ``servers_view``.** Reading the live state of the fleet and
editing the registry that defines it are different acts, wanted by different people: the
person watching a screen at 3am needs the first and must not be handed the second, which
carries the addresses, the bound credentials and the buttons that change them. That split is
the whole reason this section exists apart from System › Infrastructure.

There is no ``infra_edit``: this domain writes nothing. What there is to change lives in the
registry, behind the permissions the registry already has.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_infra',      # i18n key for the role-editor group heading
    'order': 45,                      # between the services (10–40) and the core domains
    'permissions': (
        # The fleet, live. Granted to editor and viewer by default: it is a read of things
        # both roles can already reach one screen over, arranged by machine instead of by
        # check.
        {'flag': 'infra_view', 'roles': ('editor', 'viewer')},
    ),
}
