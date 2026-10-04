#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docs/ref-permisos.md is the one place the permission catalogue is written down for people.

It said 76 flags for months while the code had 93, missed `jobs_view` entirely, listed the
built-in roles without a third of what they hold, and said `admin` did not hold
`mfa_reset_others`. Nothing compared the two. This does.
"""

import os
import re

from tests.helpers import _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
DOC = os.path.join(os.path.dirname(SRC), 'docs', 'ref-permisos.md')


def _flags():
    from lib.core.permissions import PERMISSIONS                      # noqa: PLC0415
    return [p['flag'] if isinstance(p, dict) else p for p in PERMISSIONS]


class TestTheReferenceMatchesTheCode:

    def test_every_flag_is_documented(self):
        doc = _read(DOC)
        faltan = [f for f in _flags() if '`%s`' % f not in doc]
        assert not faltan, f'docs/ref-permisos.md does not name: {faltan}'

    def test_it_says_how_many_there_are(self):
        doc = _read(DOC)
        n = len(_flags())
        # Las filas de editor y viewer dicen cuántos tiene cada uno, que es otra cuenta.
        texto = '\n'.join(l for l in doc.splitlines()
                          if not l.startswith(('| `editor`', '| `viewer`')))
        cuentas = {int(x) for x in re.findall(r'\b(\d+) flags', texto)}
        assert cuentas == {n}, f'the doc counts {sorted(cuentas)} flags; the code has {n}'

    def test_the_built_in_roles_are_listed_whole(self):
        """The lists are what someone reads before giving a role to a person."""
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS          # noqa: PLC0415
        doc = _read(DOC)
        for role in ('editor', 'viewer'):
            fila = [l for l in doc.splitlines() if l.startswith('| `%s` |' % role)]
            assert fila, f'no row for {role}'
            faltan = [f for f in BUILTIN_ROLE_PERMISSIONS[role] if '`%s`' % f not in fila[0]]
            assert not faltan, f'{role} row misses {faltan}'


class TestEveryScopedGrantCanBeGiven:
    """`org.<uid>.view` existed in the server's rule and the manifest said it was granted in the
    role editor — and nothing there drew it. Every per-object key the validator accepts has rows
    on the Permissions screen to give it."""

    def test_the_screen_has_rows_for_each_prefix(self):
        res = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                 'permissions', '_resources.html'))
        for prefix in ('module', 'server', 'cluster', 'org', 'syslogsrc'):
            assert "prefix: '%s'" % prefix in res, prefix
        org = res.split("prefix: 'org'", 1)[1].split('},\n    },', 1)[0]
        assert "actions: ['view']" in org, 'a company is only ever narrowed for reading'
        assert "globalFor: { view: 'orgs_all_view' }" in org
        src = res.split("prefix: 'syslogsrc'", 1)[1].split('},\n    },', 1)[0]
        assert "actions: ['view']" in src, 'an external syslog source is only ever read'
        assert "globalFor: { view: 'syslog_sources_all_view' }" in src
