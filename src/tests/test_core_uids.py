#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``00000000-0000-4000-*`` belongs to the built-in identities and to nothing else.

That reservation is what makes "is this UID one of ours?" answerable from the value itself —
no lookup, and no false positive possible. A generated UID landing in there is not a
realistic event (twelve leading zeros), but "almost always true" is not a property identity
can be built on: the exception would be exactly the row nobody would think to check.

The rule only holds while every identity is minted through :func:`lib.core.uids.new_uid`,
and accounts are created in seven different places — hence the last test here.
"""

import io
import itertools
import os
from unittest.mock import patch

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Everywhere an identity UID is born: the three services, plus the four paths that provision
# on the fly at first sign-in / on the IdP's say-so.
MINTING_SITES = (
    'lib/core/users/service.py',
    'lib/core/groups/service.py',
    'lib/core/roles/service.py',
    'lib/providers/ldap/auth.py',
    'lib/providers/oidc/auth.py',
    'lib/providers/saml/auth.py',
    'lib/providers/scim/service.py',
)


class TestTheBuiltInNamespaceIsReserved:

    def test_every_built_in_is_inside_it(self):
        from lib.core.constants import BUILTIN_UID_PREFIX, BUILTIN_UIDS
        for kind, uids in BUILTIN_UIDS.items():
            for name, uid in uids.items():
                assert uid.startswith(BUILTIN_UID_PREFIX), f'{kind}/{name}'

    def test_the_prefix_is_written_once_and_composed_in(self):
        """Declared prefix-first so a built-in CANNOT be written outside the range — the
        other order (derive the prefix back out of the values) leaves that possible and
        merely detectable. One edit moves every built-in together."""
        import io as _io
        src = _io.open(os.path.join(SRC, 'lib', 'core', 'constants.py'), encoding='utf-8').read()
        from lib.core.constants import BUILTIN_UID_PREFIX, BUILTIN_UIDS
        assert src.count(repr(BUILTIN_UID_PREFIX)) == 1, 'the prefix is spelled out twice'
        for uids in BUILTIN_UIDS.values():
            for uid in uids.values():
                assert repr(uid) not in src, 'a built-in UID is pasted whole, not composed'

    def test_generated_uids_stay_out(self):
        from lib.core.constants import BUILTIN_UID_PREFIX
        from lib.core.uids import new_uid
        for _ in range(2000):
            assert not new_uid().startswith(BUILTIN_UID_PREFIX)

    def test_a_collision_is_re_drawn_not_mangled(self):
        """The colliding value is replaced, not edited: patching one nibble would hand out a
        UID derived from a discarded draw, and "it is random anyway" is how two of them end
        up equal.

        The collision is BUILT from the reserved prefix rather than pasted — a literal
        built-in UUID in a test is what ``test_core_domain_layout`` refuses, and rightly:
        a pasted copy passes its own test while the product uses another value.
        """
        from lib.core import uids as _uids
        from lib.core.constants import BUILTIN_UID_PREFIX
        collision = BUILTIN_UID_PREFIX + '8002-000000000009'
        clean = '11111111-2222-4333-8444-555555555555'
        draws = itertools.chain([collision], itertools.repeat(clean))
        with patch.object(_uids.uuid, 'uuid4', side_effect=lambda: next(draws)):
            assert _uids.new_uid() == clean

    def test_every_identity_is_minted_through_it(self):
        """A bare ``uuid4()`` in any of the seven puts the guarantee back to "almost
        always" — and the one that reintroduces it will be a provisioning path, because
        those are the ones nobody remembers are account-creation code."""
        offenders = [rel for rel in MINTING_SITES
                     if 'uuid.uuid4()' in io.open(os.path.join(SRC, *rel.split('/')),
                                                  encoding='utf-8').read()]
        assert not offenders, f'minting identity UIDs outside lib.core.uids: {offenders}'
