#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Each core domain keeps its own code — including its WebAdmin glue.

``lib/core/__init__.py`` states the rule: a domain package bundles its ``store``, its
``mixin``, its ``routes`` and its ``manifest`` *"instead of spreading those across
lib/stores, lib/web_admin/mixins and lib/web_admin/routes"*.  The reorganisation had
stopped one domain short — permissions still had its 210-line resolution mixin sitting in
``lib/web_admin/mixins/``, which is exactly where the docstring says it should not be. A
docstring cannot notice that; these tests can.

They also pin the two invariants that make the layout work rather than merely look tidy:

* the catalog must stay importable **without Flask**, because permission discovery runs at
  ``lib.web_admin.constants`` import time — pulling the web glue in from the catalog would
  close an import cycle;
* "what counts as a permission" must have exactly one definition. It had two, written out
  identically, so a new kind of per-instance key would have had to be remembered in both —
  and the half that was forgotten would silently DROP those keys rather than fail.


Split by category: this file holds the structural guards (they read the repo's own source, docs
and templates); the rest of the original ``test_core_domain_layout.py`` lives in
``tests/unit/test_core_domain_layout.py``."""

import io
import os

import pytest


SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
CORE = os.path.join(SRC, 'lib', 'core')
WA_MIXINS = os.path.join(SRC, 'lib', 'web_admin', 'mixins')

# The glue that belongs to no domain and therefore legitimately lives in web_admin:
# the panel's own login/session lifecycle, the mixin that discovers and controls the
# embedded services rather than owning one, and the staleness check that re-reads a cache
# when another process has written — it serves users, roles AND groups, so putting it in any
# one of their packages would make the other two import from a domain they have nothing to
# do with. That is exactly the coupling this file exists to prevent.
# Three more joined them when the boot code came out of app.py, and each is here for the
# same reason: it serves EVERY domain, so filing it under one would make the rest import from
# a package they have nothing to do with.
#   stores   — constructs each domain's store at startup. It is about boot order and backends,
#              not about any one of the things it builds.
#   scanners — service health, certificate expiry and secret expiry. Nobody configured these
#              and no domain owns them; they exist because the panel is the only thing in a
#              position to notice.
#   embed    — frame-ancestors and the session cookie's SameSite, which are one decision in
#              two places and belong to the app's security posture, not to a domain.
# `config` deliberately did NOT stay: lib/core/config/routes.py calls _read_config_file,
# _write_config and _apply_config_on_save, so that mixin is the config domain's glue and lives
# in lib/core/config/mixin.py like every other domain's. This guard is what caught it.
# Glue that belongs to no domain. 'context' (what every template renders with) and
# 'server' (binding the interfaces and serving) were carved out of app.py, where they sat
# inside and beside the method that builds the Flask app.
NON_DOMAIN_MIXINS = {'auth', 'services', 'freshness', 'stores', 'scanners', 'embed',
                     'context', 'server', 'hooks', 'guards'}


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()












class TestOneEscalationGuard:
    """"A non-admin may only grant permissions they hold" was written twice too: as a
    closure in the roles routes, and as the last line of ``_role_grantable``. Same rule,
    two spellings — either could have been tightened without the other."""

    def test_the_guard_is_defined_once(self):
        import inspect                                               # noqa: PLC0415
        # importorskip: el mixin arrastra Flask, que puede no estar en una instalación slim.
        mixin = pytest.importorskip('lib.core.permissions.mixin')
        assert hasattr(mixin._PermissionsMixin, '_perms_grantable')
        src = _read(os.path.join(SRC, 'lib', 'core', 'roles', 'routes.py'))
        assert 'def _check_perms_escalation' not in src, \
            'the roles routes define their own copy of the escalation guard again'
        assert 'wa._perms_grantable(' in src
        assert '_perms_grantable' in inspect.getsource(
            mixin._PermissionsMixin._role_grantable), \
            '_role_grantable spells the rule out again instead of calling it'
