#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this package contributes: one permission, and nothing else.

It declares no ``BACKGROUND_JOBS`` of its own — it is the screen that COLLECTS them, and a
list of jobs that listed itself would be the one row always on it.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_jobs',     # i18n key for the role-editor group heading
    'order': 145,                   # between audit (140) and backup (150): all administration
    'permissions': (
        # Look at what the panel is doing in the background. `viewer`, deliberately: it
        # starts nothing, cancels nothing and shows no credential — it answers "why is this
        # slow" and "did my backup finish", which are questions somebody watching a wall
        # screen has as much right to as anybody. Every row is work another permission
        # already allowed somebody to start.
        {'flag': 'jobs_view', 'roles': ('viewer', 'editor')},
    ),
}
