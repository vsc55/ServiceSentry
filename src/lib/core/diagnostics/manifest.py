#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions and audit events the diagnostics domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_diagnostics',   # i18n key for the role-editor group heading
    'order': 160,                        # after backup (150): administration, not operation
    'permissions': (
        # ONE flag, and granted to nobody by default. The page reports no secret, but it does
        # report the shape of the install — paths, versions, which libraries are present — and
        # that is the inventory somebody writes an exploit against. It is also, for the same
        # reason, exactly what an operator needs before opening a support thread.
        {'flag': 'diagnostics_view', 'roles': ()},
    ),
}


AUDIT_EVENTS = [
    # The update check is the only thing here that leaves the machine. Recorded because
    # "who made this box talk to github.com, and when" is a question a segregated network
    # will ask, and the honest answer has to be findable.
    {'key': 'diagnostics_update_checked', 'severity': 'muted'},
]
