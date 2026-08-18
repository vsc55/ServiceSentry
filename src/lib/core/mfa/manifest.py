#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions and audit events the MFA domain owns (see :mod:`lib.core.permissions`).

One permission, and it is not "may I use MFA". Managing your OWN second factor needs no flag
at all — like changing your own password, it is something every account does on its own page,
and a permission there would be a way to lock somebody out of protecting themselves.

What needs a flag is taking somebody ELSE'S off, because that is the operation that lowers an
account's protection and it has to be granted deliberately.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_mfa',        # i18n key for the role-editor group heading
    'order': 105,                     # beside sessions (100): both are about how people get in
    'permissions': (
        # Removing another account's second factor. Granted to nobody by default: it is the
        # supported way back in for somebody who lost their phone, and it is also the way an
        # attacker with `users_edit` would strip the protection off an account before going
        # after its password. Deliberate, or not at all.
        {'flag': 'mfa_reset_others', 'roles': ()},
    ),
}


# Every one of these is somebody's account changing shape, so none of them is muted. The two
# that matter most are the last two: a recovery code being used is either the owner in trouble
# or somebody who should not be there, and a reset by an administrator is the one path that
# removes a factor without the owner proving anything.
AUDIT_EVENTS = [
    {'key': 'mfa_enrolled', 'severity': 'warning'},
    {'key': 'mfa_disabled', 'severity': 'danger'},
    {'key': 'mfa_recovery_regenerated', 'severity': 'warning'},
    {'key': 'mfa_failed', 'severity': 'warning'},
    {'key': 'mfa_recovery_used', 'severity': 'danger'},
    {'key': 'mfa_reset_by_admin', 'severity': 'danger'},
]
