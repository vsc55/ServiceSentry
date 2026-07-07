#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Credentials domain — reusable named SSH identities (see :mod:`lib.core`).

* ``store``       — :class:`~lib.core.credentials.store.CredentialsStore`
                    (+ ``apply_credential`` / ``SSH_CRED_FIELDS`` helpers)
* ``routes``      — ``register(app, wa)`` (the /api/v1/credentials endpoints)
* ``permissions`` — ``MODULE_PERMISSIONS`` (credentials_view / add / edit / delete)

The store is also imported by the standalone monitoring service and the module system
(``lib.modules.module_base``) — they reach in from here, which is fine: this is a
*core* domain (a foundational layer everything else builds on).  Kept light (no import
of ``store`` here) so permission discovery can import ``permissions`` alone.
"""
