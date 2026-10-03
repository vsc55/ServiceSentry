#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is this external identity the one the account is bound to?

Every SSO ``sync_user`` finds the account by a NAME — ``preferred_username``, a SAML
attribute, a directory login — and a name is the one thing an identity provider is free to
change and hand to somebody else. OpenID Connect says it in so many words: only ``sub`` is
stable, ``preferred_username`` is a label. Finding the account by name and then overwriting
its ``auth_source_id`` (and its role) with whatever subject arrived meant that a second person
who came to carry that name — in the same IdP after a rename, or in ANOTHER provider that
happens to use the same string — was signed into the first person's account and handed its
history, its tokens and its second factor's protection.

So the binding is checked before it is written. The rules:

* an account never bound to anything (``auth_source_id`` empty — created by an administrator
  for an SSO user, or before this existed) is linked by its first sign-in, as before;
* a **SCIM**-provisioned account is linked by its first sign-in too: SCIM provisions, it does
  not authenticate, and its ``auth_source_id`` is the IdP's ``externalId`` rather than a
  sign-in subject (who provisioned it is pinned separately — see ``remember_provisioning``);
* an account bound to ANOTHER provider is refused: moving an account between identity
  providers is an administrator's decision, not something a sign-in does by itself;
* an account bound to THIS provider must present the same subject. *subject* ``None`` means
  "this provider cannot give a stable one" (a SAML transient NameID) — then only the
  provider is checked.

Nothing here touches Flask; the providers call it from ``sync_user`` and refuse the sign-in
(``None``) when it answers a reason.
"""

from __future__ import annotations

#: auth_source values that are an account kind rather than an external identity.
_NOT_BOUND = ('', 'local', 'scim')


def binding_conflict(user: dict, source: str, subject, *, fold_case: bool = False) -> str:
    """``''`` when *user* may be (re)linked to *source*/*subject*, else the reason why not:
    ``'bound_to_other_provider'`` or ``'subject_mismatch'``.

    *fold_case* compares subjects case-insensitively — for a directory DN, which LDAP itself
    compares that way.
    """
    u = user or {}
    current_src = str(u.get('auth_source') or 'local')
    current_id = str(u.get('auth_source_id') or '').strip()
    if current_src in _NOT_BOUND or not current_id:
        return ''
    if current_src != str(source or ''):
        return 'bound_to_other_provider'
    if subject is None:
        return ''
    new_id = str(subject or '').strip()
    if fold_case:
        same = new_id.lower() == current_id.lower()
    else:
        same = new_id == current_id
    return '' if same else 'subject_mismatch'


def note_refusal(reason: str) -> None:
    """Leave why a ``sync_user`` said no where the callback that audits it can read it.

    ``sync_user`` answers ``None`` for every refusal, and the callback wrote one reason for
    all of them — "auto-create is off" for an account that EXISTS and was refused for being
    bound to somebody else, which is the one line an investigation would need to be right.
    Per request (``flask.g``), so two sign-ins in flight never read each other's reason;
    a no-op without a request.
    """
    try:
        from flask import g, has_request_context   # noqa: PLC0415
    except ImportError:                            # a Flask-less service process
        return
    if has_request_context():
        g.sso_refusal = str(reason or '')


def refusal(default: str) -> str:
    """The reason :func:`note_refusal` left for this request, else *default*."""
    try:
        from flask import g, has_request_context   # noqa: PLC0415
    except ImportError:
        return default
    if has_request_context():
        return str(getattr(g, 'sso_refusal', '') or default)
    return default
