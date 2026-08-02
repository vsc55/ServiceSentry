#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this package contributes, discovered by :mod:`lib.discovery`.

Purging the scoped grants of a module or cluster that no longer exists — a name can come
back, and a stale ``module.<name>.edit`` would silently apply to whatever is called that
next, so the removal is worth noticing.
"""

# What this package writes to the audit log, and how loud each one is. Declared here rather
# than guessed from the event name: the badge is the only thing a glance down two hundred
# rows gives you, and deriving it from a noun made the colour depend on what somebody called
# the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'role_permissions_pruned', 'severity': 'warning'},
]
