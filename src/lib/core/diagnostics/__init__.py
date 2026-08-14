#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostics domain — what this install is, in one screen (see :mod:`lib.core`).

* ``collect``  — pure collectors: system, dependencies, optional features, storage
* ``service``  — what the running panel knows: runtime, database, paths (Flask-free)
* ``report``   — the payload as a document: text, JSON, XML (pure)
* ``update``   — the release check (the only thing here that leaves the machine)
* ``routes``   — ``register(app, wa)`` (the /api/v1/diagnostics endpoints)
* ``manifest`` — ``MODULE_PERMISSIONS`` (diagnostics_view) + ``AUDIT_EVENTS``

Split by **what an answer depends on**, not by file size: `collect` needs nothing but the
process, `service` needs the panel, `report` needs only what those two returned. Only the
middle one can be wrong in a way that depends on how the install is deployed.

There is no store and no mixin: this domain owns no state. It reads the process, the
filesystem and the objects the web admin already holds, and every answer is computed at the
moment it is asked — a diagnostics page served from a cache is a diagnostics page describing
the problem you had before.
"""
