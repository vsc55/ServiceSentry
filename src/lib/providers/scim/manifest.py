#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this package contributes, discovered by :mod:`lib.discovery`.

SCIM provisioning: the identity provider creating, updating and deleting users and
groups over the standard protocol, plus a rejected bearer token.
"""

# What this package writes to the audit log, and how loud each one is. Declared here rather
# than guessed from the event name: the badge is the only thing a glance down two hundred
# rows gives you, and deriving it from a noun made the colour depend on what somebody called
# the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'scim_auth_failed', 'severity': 'danger'},
    {'key': 'scim_user_created', 'severity': 'success'},
    {'key': 'scim_user_updated', 'severity': 'info'},
    {'key': 'scim_user_deleted', 'severity': 'danger'},
    {'key': 'scim_group_created', 'severity': 'success'},
    {'key': 'scim_group_updated', 'severity': 'info'},
    {'key': 'scim_group_deleted', 'severity': 'danger'},
]
