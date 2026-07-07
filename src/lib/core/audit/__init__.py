#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit domain — the audit-trail viewer (see :mod:`lib.core`).

* ``store``       — :class:`~lib.core.audit.store.AuditStore`
* ``mixin``       — ``_AuditMixin`` (WebAdmin glue: the ``_audit()`` writer)
* ``routes``      — ``register(app, wa)`` (the /api/v1/audit endpoints)
* ``permissions`` — ``MODULE_PERMISSIONS`` (audit_view / audit_delete)

Note: the audit store is also written by the standalone services (monitoring / events),
which import it from here (``lib.core.audit.store``) — the one cross-layer
importer of a domain store, accepted to keep the whole audit domain co-located.  Kept
light (no import of ``mixin`` here) so permission discovery can import ``permissions``
without the Flask glue.
"""
