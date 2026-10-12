#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User accounts mixin for WebAdmin."""

import uuid

from werkzeug.security import generate_password_hash

from lib.core.constants import BUILTIN_ROLE_UIDS
from lib.core.entity_sync import diff_entities, snapshot


#: The password the bootstrap administrator gets when nobody chose one (no ``SS_PASSWORD``,
#: no ``web_admin.password`` in config.json) — ``main.py`` and ``WebAdmin.__init__`` fall
#: back to it. An account created with it is marked ``must_change_password``: everybody
#: knows it, so the first sign-in has to replace it before it opens anything else.
DEFAULT_BOOTSTRAP_PASSWORD = 'admin'


class _UsersMixin:
    """Persistence and lookup for user accounts (DB table ``users``)."""

    #: The rows as last read from — or written to — the database (see _persist_users).
    _users_snapshot: dict = None

    def _load_or_create_users(self, default_user: str, default_pass: str):
        """Load users from the DB or create the default admin on first run."""
        data = self._users_store.load()
        if data:
            self._users = data
            self._users_snapshot = snapshot(data)
        # Ensure every user has a stable uid
        dirty = False
        for udata in self._users.values():
            if not udata.get('uid'):
                udata['uid'] = str(uuid.uuid4())
                dirty = True
        if dirty:
            self._persist_users()
        # First run: no users in DB yet
        if not self._users:
            self._users = {
                default_user: {
                    'uid': str(uuid.uuid4()),
                    'password_hash': generate_password_hash(default_pass),
                    'role': BUILTIN_ROLE_UIDS['admin'],
                    'display_name': 'Administrator',
                    **({'must_change_password': True}
                       if default_pass == DEFAULT_BOOTSTRAP_PASSWORD else {}),
                },
            }
            self._persist_users()

    def _load_users(self) -> None:
        """Re-read the users table into memory.

        Separate from :meth:`_load_or_create_users`, which is the first-run path: that one
        may CREATE the default administrator, and a reload must never do that — a
        momentarily unreadable table would mint a second admin account.

        An empty answer is refused rather than applied. "No users" is not a state this
        product can be in: it means the table is mid-migration or the process was pointed
        at the wrong database, and applying it would lock everyone out of a running
        instance.
        """
        data = self._users_store.load()
        if data:
            self._users = data

    def _reload_users_if_stale(self) -> bool:
        """Re-read the users table when another writer has touched it (see
        :class:`lib.web_admin.mixins.freshness._FreshnessMixin`).  The CLI writes this one
        — ``ssentry user role bob viewer`` was invisible to a running web process until it
        was restarted."""
        return self._reload_if_stale('users', getattr(self, '_users_store', None),
                                     self._load_users)

    def _persist_users(self) -> bool:
        """Write the users this process changed — not the whole table.

        Replacing every row would delete an account the CLI created while the panel held
        an older copy, silently. :mod:`lib.core.entity_sync` has the rule.
        """
        writes, deletes = diff_entities(self._users_snapshot, self._users)
        if not writes and not deletes:
            return True
        ok = self._users_store.apply(writes, deletes)
        if ok:
            self._users_snapshot = snapshot(self._users)
            self._mark_fresh('users', self._users_store)
        return ok

    # ── forced password change ────────────────────────────────────────────────
    #: What a signed-in account that owes a new password may still reach: the screen that
    #: takes it, the API behind the account page's own form, and the way out. Everything
    #: else answers 403 (API) or is sent to that screen (pages).
    _PW_CHANGE_ENDPOINTS = frozenset({'login_password_change', 'api_change_own_password',
                                      'logout', 'login', 'static'})
    _PW_CHANGE_PREFIXES = ('/static/', '/brand/', '/favicon')

    def _must_change_password(self, username: str) -> bool:
        """Does this account owe a new password before it may do anything else?"""
        user = (getattr(self, '_users', None) or {}).get(username or '') or {}
        return bool(user.get('must_change_password'))

    def _hook_must_change_password(self):
        """The gate for an account still holding the built-in default password.

        A before_request hook and not a check in the landing page: every door into the panel
        — the password form, an SSO callback, a second factor, a URL typed by hand, an API
        call from the console — ends up here, so none of them can be the one that forgot.
        """
        from flask import g, jsonify, redirect, request, session, url_for  # noqa: PLC0415
        if not session.get('logged_in'):
            return None
        if not self._must_change_password(session.get('username', '')):
            return None
        if (request.endpoint in self._PW_CHANGE_ENDPOINTS
                or request.path.startswith(self._PW_CHANGE_PREFIXES)):
            return None
        # Not an offence: the SPA asks for a dozen things on its way to being told, and the
        # one administrator of a new install must not be jailed for having signed in.
        g._ipban_counted = True
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': self._t('password_change_required'),
                            'code': 'password_change_required',
                            'next': url_for('login_password_change')}), 403
        return redirect(url_for('login_password_change'))

    def _live_api_token_count(self, username: str) -> int:
        """How many API tokens of this account still work (not revoked, not expired).

        What a password change reports back: a token is a credential the new password does
        not replace, so the person changing it is told they exist and offered to cut them —
        not have them cut silently, which would break whatever integration holds them.
        """
        store = getattr(self, '_api_token_store', None)
        uid = ((getattr(self, '_users', None) or {}).get(username or '') or {}).get('uid', '')
        if store is None or not uid:
            return 0
        from lib.core.apitokens import service as tok_svc   # noqa: PLC0415
        try:
            return sum(1 for r in store.list_for(uid)
                       if not r.get('revoked') and not tok_svc.is_expired(r.get('expires_at')))
        except Exception:  # pylint: disable=broad-except
            return 0

    def _change_own_password(self, username: str, current_pw: str, new_pw: str):
        """Set an account's own password after checking the current one.

        The one implementation behind the account page's form and the forced-change screen.
        Returns ``None`` on success, or ``(status, i18n_key, *args)`` describing the refusal.
        On success the ``must_change_password`` mark is cleared — the new password is the
        proof it was replaced — and the caller revokes the other sessions and audits.
        """
        from werkzeug.security import check_password_hash  # noqa: PLC0415
        if not new_pw:
            return (400, 'new_password_required')
        user = (getattr(self, '_users', None) or {}).get(username or '')
        if not user:
            return (404, 'user_not_found')
        if user.get('auth_source', 'local') != 'local':
            return (403, 'sso_user_no_password')
        if not check_password_hash(user.get('password_hash', ''), current_pw or ''):
            return (403, 'wrong_current_password')
        # The same password again is not a change: on the forced screen it would clear the
        # mark while leaving the default everybody knows, and anywhere else it rotates nothing.
        if check_password_hash(user.get('password_hash', ''), new_pw):
            return (400, 'password_same_as_old')
        pw_err = self._validate_password(new_pw)
        if pw_err:
            return (400, *pw_err)
        user['password_hash'] = generate_password_hash(new_pw)
        user.pop('must_change_password', None)
        self._persist_users()
        return None
