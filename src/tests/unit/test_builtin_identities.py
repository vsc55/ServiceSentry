#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`system` and `anonymous`: the two identities the panel writes under itself.

They are protected the way the built-in roles and groups are — declared once in
``lib.core.constants`` and refused by a shared check — and they are USERS in every sense that
matters to a reader of the audit log: a name, a stable UID, a row in the users list. In no
sense that matters to a login: no password, no session, no permissions.

Filed apart from ``test_wa_audit.py`` because the subject is the identities themselves, not
the audit log — even though the log is what they exist for. What made them necessary is
recorded there; what they ARE is here.


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_builtin_identities.py`` lives in
``tests/integration/test_builtin_identities.py``."""



class TestTheReservedNamesCannotBecomeAccounts:
    """`system` and `anonymous` are the two identities the audit log reserves, and they are
    protected the way the built-in roles and groups are: declared once in
    ``lib.core.constants`` and refused by a shared check, not re-implemented per caller.

    That mattered because accounts arrive by FIVE doors, and only the first one checked:

    * the users API (``create_user``);
    * LDAP, OIDC and SAML2, which provision on the fly at first sign-in;
    * SCIM, where the IdP creates the account outright.

    So a directory with a user called `system` created a local `system`, whose every action
    would then read as the panel's own — the log stays complete and stops being trustworthy,
    which is the failure mode an audit log cannot have.
    """

    DOORS = (
        ('lib/core/users/service.py', 'the users API'),
        ('lib/providers/ldap/auth.py', 'LDAP auto-provisioning'),
        ('lib/providers/oidc/auth.py', 'OIDC auto-provisioning'),
        ('lib/providers/saml/auth.py', 'SAML2 auto-provisioning'),
        ('lib/providers/scim/service.py', 'SCIM provisioning'),
    )

    def test_every_door_checks(self):
        import io as _io
        import os as _os
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        for rel, what in self.DOORS:
            body = _io.open(_os.path.join(root, *rel.split('/')), encoding='utf-8').read()
            assert 'is_reserved_username' in body, f'{what} can still create one'

    def test_the_check_is_one_function_not_five(self):
        """Five copies of "is it system or anonymous" would drift the day a third name is
        added — and the drift would show up as an audit log that is wrong in one place."""
        from lib.core.constants import RESERVED_USERNAMES, is_reserved_username
        assert RESERVED_USERNAMES == {'system', 'anonymous'}
        assert is_reserved_username('SYSTEM') and is_reserved_username('  Anonymous ')
        assert not is_reserved_username('admin') and not is_reserved_username('')
        assert not is_reserved_username(None)

    def test_sso_rejects_the_sign_in_rather_than_renaming(self):
        """There is no safe account to let them into: silently provisioning them under
        another name would hand an IdP user an account nobody asked for."""
        import io as _io
        import os as _os
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        for rel in ('lib/providers/oidc/auth.py', 'lib/providers/saml/auth.py',
                    'lib/providers/ldap/auth.py'):
            body = _io.open(_os.path.join(root, *rel.split('/')), encoding='utf-8').read()
            # The USE, not the import at the top of the file.
            i = body.index('if is_reserved_username(')
            assert 'return None' in body[i:i + 400], f'{rel} does not reject the sign-in'

    def test_scim_calls_it_invalid_not_taken(self):
        """409 would say the name exists and could be freed. It is not available at all."""
        import io as _io
        import os as _os
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        body = _io.open(_os.path.join(root, 'lib', 'providers', 'scim', 'service.py'),
                        encoding='utf-8').read()
        i = body.index('if is_reserved_username(')
        assert 'invalidValue' in body[i:i + 300] and '400' in body[i:i + 300]


