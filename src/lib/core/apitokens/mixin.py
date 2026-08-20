#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authenticating a request by ``Authorization: Bearer`` — the Flask-bound half.

This runs as a **before_request hook, ahead of the CSRF one**, and that order is the design
rather than a detail. CSRF has to know how a request authenticated in order to judge it: a
bearer request is not a browser being tricked into posting, it is a client that had to be told
a secret, and no cross-site page can attach an ``Authorization`` header without the target's
consent. Deciding that after the CSRF hook would mean the hook rejecting every write an API
client makes.

The cookie session wins when there is one. A browser that is signed in stays a browser, with
CSRF and everything else that follows from it; the token path exists for callers that have no
session at all.

**No session row is created.** A token is not a session: it does not appear in the sessions
table, it is not revoked by "revoke all sessions", and it has its own list and its own expiry.
Writing one would put a row nobody can explain in the screen people use to see who is signed
in, and would make "sign everybody out" mean something different depending on what you meant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import g, request, session

from lib.core.apitokens import service as tok_svc
from lib.core.constants import BUILTIN_USER_UID_SET
from lib.core.users import service as users_svc

# How stale `last_used` is allowed to get. The column answers "is this token still in use",
# which does not need to be true to the second — and a write on every request would put the
# API's hottest table on the write path of every call.
_TOUCH_SECONDS = 60


class _ApiTokenMixin:
    """Bearer-token authentication for the API surface."""

    def _api_token_presented(self) -> str:
        """The raw token from the ``Authorization`` header, or `''`."""
        auth = request.headers.get('Authorization', '')
        if not auth.lower().startswith('bearer '):
            return ''
        return auth[7:].strip()

    def _hook_api_token(self):
        """Resolve a bearer token into an identity for this request. Never a refusal.

        A bad token is left unauthenticated rather than rejected here, so the answer comes
        from the same guard that answers everything else — an API caller gets 401 JSON and a
        browser gets the login page, decided in one place instead of two.
        """
        g.api_token = None
        store = getattr(self, '_api_token_store', None)
        if store is None or session.get('logged_in'):
            return None                     # a signed-in browser stays a browser
        raw = self._api_token_presented()
        if not raw:
            return None
        token_id, secret = tok_svc.parse(raw)
        if not token_id:
            return None
        try:
            row = store.by_token_id(token_id)
        except Exception:                   # pylint: disable=broad-except
            return None                     # a store that cannot answer authenticates nobody
        if not row or row.get('revoked') or not tok_svc.matches(secret, row.get('token_hash', '')):
            return None
        if tok_svc.is_expired(row.get('expires_at', '')):
            return None
        username, user = self._token_owner(row.get('user_uid', ''))
        if not username or user is None:
            return None
        # The account's own state still governs. A token is a way for an account to act, not
        # an identity of its own: disabling the account, or marking it no-login, has to stop
        # its tokens too or offboarding would leave a door open that nobody thinks to close.
        if not user.get('enabled', True) or not user.get('login_enabled', True):
            return None
        g.api_token = row
        # Populated for THIS request only — the whole panel reads the caller out of `session`,
        # and 68 call sites reading it through a second accessor is 68 chances to read the
        # wrong one. The response hook below stops it becoming a cookie.
        session['logged_in'] = True
        session['username'] = username
        self._api_token_touch(row)
        return None

    def _token_owner(self, user_uid: str) -> tuple:
        """The account a token belongs to — including the built-in identities.

        `_uid_to_username` walks the users store, and the built-ins are not rows in it on
        purpose: a row is a login surface. They still own tokens (that is what a `system`
        token IS — automation acting as the panel rather than as a person), so they are
        resolved from their synthesized record instead of being invisible here, which would
        make such a token authenticate as nobody.
        """
        uid = str(user_uid or '')
        if uid in BUILTIN_USER_UID_SET:
            for name, rec in users_svc.builtin_users().items():
                if rec.get('uid') == uid:
                    return name, rec
            return None, None
        return self._uid_to_username(uid)

    def _api_token_touch(self, row: dict) -> None:
        """Record use, at most once a minute."""
        now = datetime.now(timezone.utc)
        last = str(row.get('last_used') or '')
        if last:
            try:
                prev = datetime.fromisoformat(last)
                if prev.tzinfo is None:
                    prev = prev.replace(tzinfo=timezone.utc)
                if (now - prev).total_seconds() < _TOUCH_SECONDS:
                    return
            except ValueError:
                pass
        try:
            self._api_token_store.touch(row.get('uid', ''), now.isoformat())
        except Exception:                   # pylint: disable=broad-except
            pass                            # bookkeeping must never fail a request

    def _hook_api_token_access(self, response):
        """Record what a token just did — after the fact, so the STATUS is part of it.

        A refused call is the interesting one. "This token asked for something it may not have"
        is the line an access review is looking for, and a log written before the answer cannot
        contain it.

        The route PATTERN is stored, not the URL: `/api/v1/users/<username>` rather than the
        forty paths it resolves to. A ring filled with one name per row answers "which
        endpoints does this token use" with a wall of near-identical strings, and the raw path
        is also where an id or an email would end up in a table shown to whoever may read the
        token list. Unmatched requests (a 404) have no rule, so the path is taken as-is and
        truncated — a 404 is exactly when the URL is the point.
        """
        row = getattr(g, 'api_token', None)
        store = getattr(self, '_api_token_store', None)
        if not row or store is None or not getattr(self, '_API_TOKEN_LOG_ENABLED', True):
            return response
        try:
            rule = getattr(request.url_rule, 'rule', '') or request.path
            store.log_access(
                row.get('uid', ''),
                ts=datetime.now(timezone.utc).isoformat(),
                ip=request.remote_addr or '',
                method=request.method, path=rule,
                status=int(getattr(response, 'status_code', 0) or 0),
                keep=int(getattr(self, '_API_TOKEN_LOG_MAX', 200) or 0))
        except Exception:                       # pylint: disable=broad-except
            pass                                # bookkeeping must never fail a response
        return response

    def _hook_api_token_no_cookie(self, response):
        """Stop a token request from being handed a session cookie.

        The identity above is written into `session` so the rest of the panel can read it the
        way it always does, and Flask would take that as a session to persist. It is not one:
        the client did not ask for a session, ignoring the cookie is the best case, and storing
        it turns a stateless call into a second credential sitting on somebody's disk.

        Runs as an ``after_request``, which Flask calls **before** ``save_session`` — the one
        window where clearing the flag still prevents the write.
        """
        if getattr(g, 'api_token', None):
            # ONLY the flag. `session.permanent = False` looks like it belongs here and is
            # the bug it was written to prevent: it writes `_permanent` INTO the session,
            # which marks it modified again — so the cookie went out anyway, carrying an
            # identity the client never asked for. And the next request arrived holding it,
            # took the browser path, found no row in the session registry, and was refused.
            session.modified = False
        return response

    # ── permissions ──────────────────────────────────────────────────────────

    def _api_token_permissions(self, owner_permissions) -> frozenset:
        """The token's permissions for this request, intersected with the owner's."""
        row = getattr(g, 'api_token', None) or {}
        # A built-in owner has no permissions to intersect with — see service.effective.
        return tok_svc.effective(row.get('permissions', '[]'), owner_permissions,
                                 unbounded=row.get('user_uid', '') in BUILTIN_USER_UID_SET)
