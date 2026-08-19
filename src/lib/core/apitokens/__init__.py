#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API tokens: a way for an account to be scripted without handing over its password.

Everything but SCIM authenticated by session cookie plus CSRF, which means automation had to
store a real password — and once an account carries a second factor, a password stops being
enough to sign in at all. So enabling `mfa_required` quietly broke every script in the
building, and the only workaround was an account deliberately left unprotected.

A token is the answer to both: 192 random bits, no second factor to complete, no cookie, and
revocable on its own without touching the account.

The map::

    service.py   minting, parsing, hashing, expiry, the permission intersection — no Flask
    store.py     the `api_tokens` table; only the hash is ever stored
    mixin.py     the before_request hook that turns a Bearer header into an identity
    routes.py    the account's own tokens: list, create, revoke
    manifest.py  the audit events

Two properties hold the whole thing up, and both live in `service.effective`:

* a token is **intersected** with its owner's current permissions on every request, so it can
  never outgrow the account, and demoting the account demotes the token at the same instant;
* `'*'` means "whatever the owner has", not "everything" — the same statement written so it
  keeps being true after a role changes.
"""
