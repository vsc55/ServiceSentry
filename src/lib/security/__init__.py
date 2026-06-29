#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security primitives.

Cross-cutting building blocks that enforce the project's security policy:

* :mod:`lib.security.secret_manager` — value-level Fernet encryption
  (``enc:`` prefix, ``ENCRYPT_KEYS``, mask/restore of sensitive fields);
* :mod:`lib.security.net_guard` — ``validate_external_url()`` SSRF guard for
  user-supplied URLs.

Kept import-light on purpose (no eager ``cryptography`` import): submodules are
imported by whoever needs them.
"""
