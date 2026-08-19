#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the API-tokens domain declares (see :mod:`lib.core.permissions`).

**No permission of its own for managing your own tokens.** Minting one is the account acting
for itself, like changing its password or enrolling a second factor: a flag there would be a
way to stop somebody automating their own access while leaving them able to do the same thing
by hand, slower.

What a token can DO is not governed here either. It is the intersection of what its owner may
do and what the token was given, computed on every request — so the permission system already
in place is the one that applies, and there is nothing extra to keep in step.

Revoking somebody ELSE's tokens rides on ``sessions_revoke``. A token is standing access to
this panel, which is exactly what that permission is about; inventing a second flag for the
same act would let an installation grant one and not the other and be surprised by which
kind of access it just failed to cut off.
"""

AUDIT_EVENTS = [
    {'key': 'api_token_created', 'severity': 'warning'},
    {'key': 'api_token_revoked', 'severity': 'info'},
    {'key': 'api_token_rotated', 'severity': 'warning'},
    # Editing a scope is a grant, so it is logged like one — with what it was before,
    # since 'what changed' is the only question asked of an entry like this.
    {'key': 'api_token_edited', 'severity': 'warning'},
    # Somebody else's, by an administrator — the loud ones, like every act on another
    # account. Minting one is its own event: handing out a credential that is not yours
    # is a different act from minting your own, and has to be findable as such.
    {'key': 'api_token_created_for', 'severity': 'danger'},
    {'key': 'api_token_revoked_by_admin', 'severity': 'warning'},
    {'key': 'api_token_edited_by_admin', 'severity': 'danger'},
    {'key': 'api_token_rotated_by_admin', 'severity': 'warning'},
    {'key': 'api_tokens_revoked_by_admin', 'severity': 'danger'},
]
