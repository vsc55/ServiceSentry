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


Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_builtin_identities.py`` lives in ``tests/unit/test_builtin_identities.py``."""

import pytest

try:
    from lib.web_admin import WebAdmin           # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")




class TestTheBuiltInIdentitiesAreFirstClass:
    """`system` and `anonymous` are built-in USERS — a name, a stable UID and a row in the
    users list, the same way `Administrators` is a built-in group.

    Before this they were bare strings: the audit column that answers "who did this" named
    something the rest of the system knew nothing about, so there was nothing to look up.
    They are synthesized, never stored: a database row is a login surface (a password to
    set, a session to open, one CLI edit away from being a real account), and these two must
    never be reachable that way.
    """

    def test_they_have_stable_uids(self):
        """The UIDs are identity — fixed literals in ``lib.core.constants``, never minted at
        import time, and distinct from every other built-in so a UID alone says which kind of
        thing it names.

        The values are NOT repeated here: a pasted copy passes its own test happily while the
        product uses another value (``test_core_domain_layout`` enforces the one home).
        """
        from lib.core.constants import (ANONYMOUS_USER, BUILTIN_GROUP_UIDS,
                                        BUILTIN_ROLE_UIDS, BUILTIN_USER_UIDS,
                                        BUILTIN_USER_UID_SET, SYSTEM_USER)
        assert set(BUILTIN_USER_UIDS) == {SYSTEM_USER, ANONYMOUS_USER}
        assert BUILTIN_USER_UID_SET == frozenset(BUILTIN_USER_UIDS.values())
        assert len(BUILTIN_USER_UID_SET) == len(BUILTIN_USER_UIDS)   # no two share one
        others = set(BUILTIN_ROLE_UIDS.values()) | set(BUILTIN_GROUP_UIDS.values())
        assert not (BUILTIN_USER_UID_SET & others)
        # Fixed, not minted: a generated UID would be a different account on every restart.
        import inspect                                                # noqa: PLC0415
        import lib.core.constants as _c                               # noqa: PLC0415
        assert 'uuid' not in inspect.getsource(_c)

    def test_the_reserved_names_derive_from_the_uid_map(self):
        """One declaration: a third built-in identity is one line, not two that can drift."""
        from lib.core.constants import BUILTIN_USER_UIDS, RESERVED_USERNAMES
        assert RESERVED_USERNAMES == frozenset(BUILTIN_USER_UIDS)

    def test_the_listing_shows_them(self, client):
        """A reader who finds `system` in the audit log can look it up in Users."""
        _login(client)
        users = client.get('/api/v1/users').get_json()
        assert users['system']['builtin'] is True
        assert users['anonymous']['builtin'] is True
        assert users['admin']['builtin'] is False
        assert users['system']['uid'] and users['system']['uid'] != users['anonymous']['uid']

    def test_they_hold_no_role_and_no_password(self, admin, client):
        """`system` acts with the panel's authority because it never passes a permission
        check — not because it holds one. And no row means no hash to authenticate against."""
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _login(client)
        rec = client.get('/api/v1/users').get_json()['system']
        assert rec['role'] == BUILTIN_ROLE_UIDS['none']
        assert rec['auth_source'] == 'internal'
        assert 'password_hash' not in rec
        assert 'system' not in admin._users and 'anonymous' not in admin._users

    def test_they_cannot_be_edited_or_deleted(self, client):
        """Internal means internal — the same refusal the built-in roles and groups give."""
        _login(client)
        for name in ('system', 'anonymous'):
            r = client.put(f'/api/v1/users/{name}', json={'display_name': 'Hijacked'})
            assert r.status_code == 403, name
            assert 'error' in r.get_json()
            assert client.delete(f'/api/v1/users/{name}').status_code == 403, name

    def test_a_legacy_account_holding_the_name_is_not_hidden(self, admin, client):
        """An installation that provisioned `system` BEFORE the name was reserved still has
        that account. Shadowing it behind a row marked "built-in, not editable" would leave
        the admin unable to see — or delete — the very account that made the log ambiguous.
        """
        admin._users['system'] = {
            'uid': 'legacy-uid', 'password_hash': generate_password_hash('x'),
            'role': 'viewer', 'display_name': 'Squatter',
        }
        _login(client)
        rec = client.get('/api/v1/users').get_json()['system']
        assert rec['uid'] == 'legacy-uid' and rec['builtin'] is False
        assert client.delete('/api/v1/users/system').status_code == 200
        assert 'system' not in admin._users
        # …and once it is gone, the built-in identity is back in its place.
        assert client.get('/api/v1/users').get_json()['system']['builtin'] is True

    def test_the_language_is_inherited_not_pinned(self):
        """`lang: ''` is the INHERIT sentinel, the same one a real user who never chose a
        language carries: the panel and the notifier then fall back to the configured system
        language at *send* time. Stamping the current one here would freeze it the day the
        admin changes it — and would read as a preference these two never expressed."""
        from lib.core.users.service import builtin_user_record
        assert builtin_user_record('system')['lang'] == ''

    def test_they_can_never_log_in_even_with_a_row(self, admin, client):
        """The SSO doors refuse them on every sign-in, but a `system` account provisioned
        before the name was reserved still HAS a row and a password hash. `system` in the log
        has to mean the panel acted on its own; the moment a person can sign in under that
        name it means nothing at all."""
        admin._users['system'] = {
            'uid': 'legacy-uid',
            'password_hash': generate_password_hash('secret', method='pbkdf2:sha256'),
            'role': 'viewer',
        }
        r = client.post('/login', data={'username': 'system', 'password': 'secret'},
                        follow_redirects=True)
        assert r.status_code == 200
        assert not client.get('/api/v1/me').get_json().get('logged_in', False)
        entry = next(e for e in reversed(admin._audit_log) if e['event'] == 'login_failed')
        assert entry['detail']['reason'] == 'username_reserved'

    def test_the_display_names_are_translated(self, admin):
        """The listing shows a name a reader recognises, not the internal key."""
        from lib.core.users.service import builtin_users
        recs = builtin_users(describe=lambda n: admin._t('builtin_user_' + n))
        assert recs['system']['display_name'] == 'System'
        assert recs['anonymous']['display_name'] == 'Anonymous'
        assert all('builtin_user_' not in r['display_name'] for r in recs.values())
