#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config domain — the editable application configuration (see :mod:`lib.core`).

* ``store``  — :class:`~lib.core.config.store.ConfigStore` (DB-backed editable layer,
               one row per ``section|field``).  NOT the config *subsystem* store
               (:class:`lib.config.config_store.ConfigStore`), a different class.
* ``service`` — Flask-free logic: save planning/validation, INT_RULES/BOOL_RULES, and the
                frontend UI-schema assembly (``build_config_schema``)
* ``routes``  — thin HTTP layer: /api/v1/config (GET/PUT) + /config/layout + /config/schema
* ``permissions`` — ``MODULE_PERMISSIONS`` (config_view / config_edit)

The store is also imported by the standalone services (they read editable config).
"""
