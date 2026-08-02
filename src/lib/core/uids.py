#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minting entity UIDs that stay out of the built-in namespace.

What that namespace IS lives with the identities themselves
(:data:`lib.core.constants.BUILTIN_UID_PREFIX`, which every built-in UID is composed from, so
the prefix exists in exactly one place and changing it moves all of them together).  What
lives here is the other half of the promise: nothing new is ever minted inside it.

The odds of a random identifier landing on twelve leading zeros are not a practical worry —
this loop will not run twice in the product's lifetime.  It is here so the boundary is a
guarantee instead of a probability, which is the only kind of statement worth making about
identity: the whole point of a reserved range is that a value inside it can be trusted to be
ours without a lookup, and "almost always" makes the exception exactly the row nobody would
think to check.

Everything minted before this is an ordinary random identifier and keeps working: the
reservation is a promise about NEW values, not a rule anything validates against.
"""

from __future__ import annotations

import uuid

from lib.core.constants import BUILTIN_UID_PREFIX


def new_uid() -> str:
    """A fresh UUID4, re-drawn on the (vanishing) chance it lands in the built-in range.

    Re-drawn rather than patched: editing one digit of a colliding value would hand out an
    identifier derived from a discarded draw, and "it is random anyway" is how two of them
    end up equal.
    """
    while True:
        raw = str(uuid.uuid4())
        if not raw.startswith(BUILTIN_UID_PREFIX):
            return raw
