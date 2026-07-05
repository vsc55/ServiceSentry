#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security primitives.

Cross-cutting building blocks that enforce the project's security policy:

* :mod:`lib.security.secret_manager` — value-level Fernet encryption
  (``enc:`` prefix, ``ENCRYPT_KEYS``, mask/restore of sensitive fields);
* :mod:`lib.security.net_guard` — ``validate_external_url()`` SSRF guard for
  user-supplied URLs;
* :mod:`lib.security.csrf` — double-submit CSRF token policy (issue / validate);
* :mod:`lib.security.headers` — HTTP response security headers (CSP, X-Frame-Options…);
* :mod:`lib.security.ratelimit` — ``RateLimiter`` sliding-window brute-force throttle
  (per-IP login / SCIM bearer).

Kept import-light on purpose (no eager ``cryptography`` import): submodules are
imported by whoever needs them.
"""
