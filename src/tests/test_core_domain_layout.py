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
"""

import io
import os
import re
import subprocess
import sys

import pytest

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def _domains():
    """Core domain packages — a directory under lib/core with an __init__.py."""
    return sorted(d for d in os.listdir(CORE)
                  if os.path.isfile(os.path.join(CORE, d, '__init__.py')))


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()


class TestTheScanItself:
    """If these fail the guard is broken, not the layout."""

    def test_domains_are_found(self):
        found = _domains()
        assert len(found) >= 10, f'only {found} — the scan is looking in the wrong place'
        for expected in ('users', 'roles', 'groups', 'permissions'):
            assert expected in found


class TestDomainCodeLivesWithItsDomain:

    def test_no_domain_mixin_is_left_in_web_admin(self):
        """The failure this exists for: a domain's mixin left behind in
        lib/web_admin/mixins while its domain package moved."""
        stray = sorted(f[:-3] for f in os.listdir(WA_MIXINS)
                       if f.endswith('.py') and f != '__init__.py'
                       and f[:-3] not in NON_DOMAIN_MIXINS)
        assert not stray, (
            'these look like domain glue and belong in lib/core/<domain>/mixin.py: '
            + ', '.join(stray))

    def test_every_domain_mixin_is_in_its_package(self):
        """Stated the other way round, so the rule holds for domains added later."""
        for name in _domains():
            assert not os.path.isfile(os.path.join(WA_MIXINS, f'{name}.py')), (
                f'{name} has a package under lib/core but its mixin sits in web_admin')

    def test_permissions_is_a_domain_package(self):
        """It was a flat module while every other domain was a package."""
        assert os.path.isfile(os.path.join(CORE, 'permissions', '__init__.py'))
        assert os.path.isfile(os.path.join(CORE, 'permissions', 'mixin.py'))
        assert not os.path.isfile(os.path.join(CORE, 'permissions.py')), \
            'both the package and the old flat module exist — imports would be ambiguous'


class TestTheImportCycleStaysOpen:
    """``lib/core/__init__.py`` asks for light domain __init__ files for a concrete
    reason: discovery imports them very early, from the web admin's own import."""

    @pytest.mark.parametrize('name', _domains())
    def test_a_domain_init_does_not_import_its_mixin(self, name):
        if not os.path.isfile(os.path.join(CORE, name, 'mixin.py')):
            pytest.skip(f'{name} has no mixin')
        src = _read(os.path.join(CORE, name, '__init__.py'))
        assert not re.search(r'^\s*from\s+\.mixin\s+import|^\s*from\s+\.\s+import\s+mixin',
                             src, re.M), f'lib/core/{name}/__init__.py imports its mixin'

    @staticmethod
    def _flask_probe(module):
        """Import *module* in a fresh interpreter. Exit 0 = no Flask, 2 = Flask came with
        it. Deliberately NOT 1 for "Flask": a failed import also exits 1, and a probe that
        cannot tell "clean" from "blew up" would pass for a module that does not import."""
        code = (f'import sys; import {module}; '
                "sys.exit(2 if 'flask' in sys.modules else 0)")
        # The timeout is a hang-guard, not a speed check: importing the app takes ~3s in
        # isolation, and this probe only cares WHETHER flask comes in, never how fast. Under a
        # full `-n auto` run every core is already saturated by xdist workers, and this extra
        # subprocess can be starved long past a tight cap — a 120s limit turned that starvation
        # into a false failure. 600s still catches a genuine hang while tolerating the
        # contention a real hang never would.
        r = subprocess.run([sys.executable, '-c', code], cwd=SRC,
                           capture_output=True, timeout=600)
        assert r.returncode in (0, 2), (
            f'importing {module} failed:\n' + r.stderr.decode('utf-8', 'replace'))
        return r.returncode

    def test_the_probe_detects_flask(self):
        """Positive control. Without it the test below passes for any module at all."""
        assert self._flask_probe('lib.web_admin.app') == 2

    def test_the_catalog_imports_without_flask(self):
        """The catalog is imported before the app exists. If it ever pulls in the web glue
        (which imports flask), discovery and the web admin import each other."""
        assert self._flask_probe('lib.core.permissions') == 0, \
            'importing lib.core.permissions dragged in Flask'

    def test_the_catalog_is_still_imported_the_same_way(self):
        """Turning the module into a package must be invisible to the modules that import
        the catalog itself (the identities moved on purpose — see the class below)."""
        from lib.core.permissions import (          # noqa: PLC0415
            PERMISSIONS, PERMISSION_GROUPS, BUILTIN_ROLE_PERMISSIONS,
            discover_permissions, is_module_perm,
        )
        assert len(PERMISSIONS) == 66 and len(PERMISSION_GROUPS) == 17
        assert BUILTIN_ROLE_PERMISSIONS['admin'] == frozenset(PERMISSIONS)
        assert discover_permissions() and is_module_perm('module.ping.view')


class TestOneDefinitionOfAValidPermission:

    def test_the_rule_is_written_once(self):
        """It was written twice, verbatim: once where a role is saved and once where a
        role's permissions are resolved."""
        offenders = []
        for root, _dirs, files in os.walk(os.path.join(SRC, 'lib')):
            for f in files:
                if not f.endswith('.py'):
                    continue
                path = os.path.join(root, f)
                rel = os.path.relpath(path, SRC).replace(os.sep, '/')
                if rel == 'lib/core/permissions/__init__.py':
                    continue        # the one definition
                for i, line in enumerate(_read(path).splitlines(), 1):
                    if 'is_module_perm(' in line and 'is_server_perm(' in line:
                        offenders.append(f'{rel}:{i}')
        assert not offenders, (
            'the validity rule is spelled out again here — call filter_valid_permissions '
            'instead: ' + ', '.join(offenders))

    def test_both_directions_use_it(self):
        """Saving a role and resolving a role must agree on what a permission is."""
        from lib.core.permissions import filter_valid_permissions   # noqa: PLC0415
        from lib.core.roles import service as roles_svc             # noqa: PLC0415
        assert roles_svc.filter_valid_permissions is filter_valid_permissions
        assert 'filter_valid_permissions' in _read(
            os.path.join(CORE, 'permissions', 'mixin.py'))

    @pytest.mark.parametrize('perm,valid', [
        ('users_view', True), ('module.ping.view', True), ('server.abc-1.edit', True),
        ('cluster.x.delete', True), ('users_fly', False), ('module.ping.fly', False),
        ('', False),
    ])
    def test_what_the_rule_says(self, perm, valid):
        from lib.core.permissions import is_valid_perm               # noqa: PLC0415
        assert is_valid_perm(perm) is valid


class TestBuiltInIdentitiesHaveOneHome:
    """The stable UUIDs of the built-in roles and groups sat in the permissions catalog —
    the one module that never read them. They are identity, named by users, groups, roles,
    permission resolution, SCIM and the CLI, so they live in ``lib.core.constants``, whose
    whole purpose is constants everyone can import downwards."""

    UUID_RE = re.compile(r'\b0{8}-0{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}\b')

    def test_the_uuids_are_written_in_exactly_one_place(self):
        """A pasted copy passes its own test happily while the product uses another
        value — which is how two of these ended up in the test suite."""
        offenders = []
        for base in ('lib', 'tests'):
            for root, dirs, files in os.walk(os.path.join(SRC, base)):
                dirs[:] = [d for d in dirs if d != '__pycache__']
                for f in files:
                    if not f.endswith('.py'):
                        continue
                    rel = os.path.relpath(os.path.join(root, f), SRC).replace(os.sep, '/')
                    if rel == 'lib/core/constants.py':
                        continue        # the definition
                    for i, line in enumerate(_read(os.path.join(root, f)).splitlines(), 1):
                        if self.UUID_RE.search(line):
                            offenders.append(f'{rel}:{i}')
        assert not offenders, (
            'built-in UUIDs written out again instead of imported from lib.core.constants: '
            + ', '.join(offenders))

    def test_the_catalog_does_not_hold_them(self):
        import lib.core.permissions as catalog                       # noqa: PLC0415
        for name in ('BUILTIN_ROLE_UIDS', 'BUILTIN_GROUP_UIDS', 'ROLES'):
            assert not hasattr(catalog, name), (
                f'{name} is back in the permissions catalog — it is identity, not catalog, '
                'and re-exporting it would create the second name this move removed')

    def test_the_role_names_are_enumerated_once(self):
        """``ROLES`` and the keys of ``BUILTIN_ROLE_UIDS`` were two literals of the same
        four names; ROLES is derived from the map now, so adding a built-in role cannot
        update one and miss the other."""
        from lib.core.constants import BUILTIN_ROLE_UIDS, ROLES      # noqa: PLC0415
        assert ROLES == tuple(BUILTIN_ROLE_UIDS)

    def test_the_grants_cover_exactly_those_roles(self):
        """The third enumeration — what each built-in role grants — cannot be derived, so
        it is checked: a role with a UID but no grants resolves to no permissions at all,
        silently."""
        from lib.core.constants import ROLES                         # noqa: PLC0415
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS    # noqa: PLC0415
        assert tuple(BUILTIN_ROLE_PERMISSIONS) == ROLES

    def test_the_group_uid_set_is_derived(self):
        from lib.core.constants import (                             # noqa: PLC0415
            BUILTIN_GROUP_UIDS, BUILTIN_GROUP_UID_SET)
        assert BUILTIN_GROUP_UID_SET == frozenset(BUILTIN_GROUP_UIDS.values())

    def test_all_three_kinds_come_from_one_map(self):
        """Roles, groups and users were three separate literals of the same idea. They are
        views over ``BUILTIN_UIDS`` now, so "which UIDs are built in" has one answer."""
        from lib.core.constants import (                             # noqa: PLC0415
            BUILTIN_GROUP_UIDS, BUILTIN_ROLE_UIDS, BUILTIN_UIDS, BUILTIN_USER_UIDS)
        assert set(BUILTIN_UIDS) == {'role', 'group', 'user'}
        assert BUILTIN_ROLE_UIDS == BUILTIN_UIDS['role']
        assert BUILTIN_GROUP_UIDS == BUILTIN_UIDS['group']
        assert BUILTIN_USER_UIDS == BUILTIN_UIDS['user']

    def test_no_two_built_ins_share_a_uid(self):
        """A collision would make one entity resolve as another kind — silently."""
        from lib.core.constants import BUILTIN_UIDS, BUILTIN_UID_KIND  # noqa: PLC0415
        total = sum(len(uids) for uids in BUILTIN_UIDS.values())
        assert len(BUILTIN_UID_KIND) == total

    def test_the_variant_block_says_which_kind(self):
        """The UUID's variant block carries the kind — ``…-8001-…`` users, ``…-8002-…``
        groups, ``…-8003-…`` roles — so a UID names its kind without a lookup and a new kind
        takes the next value. It stays ``8xxx`` because that first nibble is what makes a
        UUID RFC-4122 variant 1; ``0001`` there would not be a valid UUID of this family.

        The values themselves are NOT repeated here (see the one-home test above): the
        convention is checked against what the module declares.
        """
        from lib.core.constants import BUILTIN_UIDS, builtin_kind    # noqa: PLC0415
        block = {'user': '8001', 'group': '8002', 'role': '8003'}
        for kind, uids in BUILTIN_UIDS.items():
            for name, uid in uids.items():
                assert uid.split('-')[3] == block[kind], f'{kind}/{name}'
                assert builtin_kind(uid) == kind
        assert builtin_kind('nope') is None and builtin_kind(None) is None


class TestOneEscalationGuard:
    """"A non-admin may only grant permissions they hold" was written twice too: as a
    closure in the roles routes, and as the last line of ``_role_grantable``. Same rule,
    two spellings — either could have been tightened without the other."""

    def test_the_guard_is_defined_once(self):
        import inspect                                               # noqa: PLC0415
        from lib.core.permissions import mixin                       # noqa: PLC0415
        assert hasattr(mixin._PermissionsMixin, '_perms_grantable')
        src = _read(os.path.join(SRC, 'lib', 'core', 'roles', 'routes.py'))
        assert 'def _check_perms_escalation' not in src, \
            'the roles routes define their own copy of the escalation guard again'
        assert 'wa._perms_grantable(' in src
        assert '_perms_grantable' in inspect.getsource(
            mixin._PermissionsMixin._role_grantable), \
            '_role_grantable spells the rule out again instead of calling it'
