#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core — foundational primitives and the self-contained domain modules.

* :mod:`lib.core.object_base` — :class:`ObjectBase`, the base class carrying the
  shared :class:`~lib.debug.Debug` instance every class uses (re-exported from the
  package root :mod:`lib` as ``ObjectBase``).
* :mod:`lib.core.permissions` — :func:`discover_permissions`, the unified permission
  discovery scanning ``lib.core.*`` and ``lib.services.*``.
* One package per **core domain** (``audit``, ``users``, ``roles``, ``groups``,
  ``sessions``, ``config``, ``credentials``, ``history``, ``modules``, ``hosts``,
  ``clusters``, ``overview``): each bundles everything about that domain — its
  ``store`` (persistence), its ``mixin`` (the WebAdmin glue), its ``routes`` (endpoint
  registration) and its ``permissions`` (the flags/group/role grants it owns) — instead
  of spreading those across ``lib/stores``, ``lib/web_admin/mixins`` and
  ``lib/web_admin/routes``.  The same self-describing model as ``lib.services.*`` (which
  are deployment-boundary subsystems); core is the foundational layer everything else —
  services, modules, the web admin — builds on and imports from.

The UI templates stay in ``lib/web_admin/templates/partials/<domain>`` — they consume a
domain through its routes/API.

IMPORTANT: keep each ``lib.core.<domain>.__init__`` lightweight (avoid importing its
``mixin`` at module top).  Permission discovery imports the ``permissions`` submodule of
every domain very early (at ``lib.web_admin.constants`` import time); a heavy package
``__init__`` that pulls in the Flask glue would risk an import cycle with the web admin.
"""
