#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MFA domain — the second factor, from the arithmetic up (see :mod:`lib.core`).

The layer that never heard of Flask, and is tested against somebody else's numbers:

* ``totp``    — RFC 6238 / RFC 4226. Verified against the RFC's own published vectors
* ``qr``      — ISO/IEC 18004, written here: Reed-Solomon over GF(256), interleaving, BCH
                format/version bits, the eight masks and their penalty rules, and an SVG.
                One algorithm end to end, which is why it is one file
* ``cbor``    — RFC 8949, DECODE only: what an authenticator sends. Refuses indefinite
                lengths and duplicate keys, and reports how far it read
* ``cose``    — RFC 8152 public keys, ES256 / RS256 / EdDSA. The algorithm is the one
                recorded at REGISTRATION, never the one the key claims later
* ``webauthn``— the two ceremonies, one check at a time: challenge in constant time,
                origin by exact equality, RP-ID hash, user presence, signature counter

The layer that knows about this installation:

* ``store``   — :class:`~lib.core.mfa.store.MfaStore`: ``mfa_factors`` + ``mfa_recovery``.
                The seed is encrypted at rest and the store REFUSES to write one it cannot
                protect, which is what makes a policy safe to ignore on a keyless install
* ``service`` — enrolment, confirmation, verification and the recovery codes. Pure functions
                over a store: no Flask, no session
* ``policy``  — ``_MfaPolicyMixin``: who must carry one, which SSO providers are trusted, and
                where a security key would be registered. **Decides**; touches no request
* ``mixin``   — ``_MfaMixin``: the half-finished sign-in, which is a note in the cookie and
                deliberately NOT a session. **Remembers**; needs Flask
* ``routes``  — ``register(app, wa)``: the account's own endpoints plus the admin reset
* ``manifest``— ``MODULE_PERMISSIONS`` (``mfa_reset_others``) and the six audit events

The two mixins are composed side by side onto ``WebAdmin``; the split is about what a reader
and a test have to carry, not about severing them.

Keep this ``__init__`` lightweight — do NOT import the submodules here. Permission discovery
imports ``manifest`` very early, and an ``__init__`` that pulled in the Flask glue would make
that import a cycle.

The whole subsystem, with its diagrams and the decisions behind it: ``docs/explica-mfa.md``.
"""
