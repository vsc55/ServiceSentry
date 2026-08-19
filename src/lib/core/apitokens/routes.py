#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API-token routes: an account's own tokens, and cutting off somebody else's.

Routes registered by this file:

    GET    /api/v1/account/tokens              this account's tokens (never the secret)
    POST   /api/v1/account/tokens              mint one; answers the token ONCE
    GET    /api/v1/account/tokens/<uid>/access what one of mine has been doing
    POST   /api/v1/account/tokens/<uid>/rotate a new secret for the same setup
    PUT    /api/v1/account/tokens/<uid>        change what one of mine may do
    DELETE /api/v1/account/tokens/<uid>        revoke one of mine
    DELETE /api/v1/users/<username>/tokens     revoke ALL of somebody else's (sessions_revoke)

    GET    /api/v1/tokens                      every token in the installation (sessions_view)
    GET    /api/v1/tokens/<uid>/access          what any one has been doing (sessions_view)
    GET    /api/v1/tokens/access                every call of every token (sessions_view)
    GET    /api/v1/users/<username>/permissions what that account may be given (users_edit)
    POST   /api/v1/users/<username>/tokens     mint one FOR that account (users_edit)
    PUT    /api/v1/tokens/<uid>                change what any one may do (users_edit)
    POST   /api/v1/tokens/<uid>/rotate         a new secret for any one (users_edit)
    DELETE /api/v1/tokens/<uid>                revoke any single one (sessions_revoke)

**Three permissions and not one**, because they are three different acts. Reading the list is
the sessions question — what standing access exists — and revoking is the sessions answer, which
is why both ride the flags that already govern it. Minting a credential that acts AS an account
is account administration, so it rides `users_edit`. An installation that grants one and not the
others gets exactly what it asked for.

**None of these can be called with a token.** A narrow token that could mint a wide one is not
a narrow token, and a token that can revoke its owner's other tokens is a foothold that cleans
up after itself. Managing credentials is the one thing that stays behind a real sign-in — the
same reason changing a password and enrolling a second factor do.
"""

from datetime import datetime, timedelta, timezone

from flask import g, jsonify, request, session

from lib.core.apitokens import service as tok_svc
from lib.core.constants import SYSTEM_USER, is_reserved_username
from lib.core.permissions import is_valid_perm
from lib.core.users import service as users_svc

# A ceiling on how far ahead an expiry may be set, and a cap on how many live tokens one
# account may hold. Neither is a security boundary — the owner could mint more tomorrow — they
# are there so a list stays a list and "never expires" stays a deliberate choice rather than
# the shape of every token because the field was left alone.
MAX_EXPIRY_DAYS = 730
MAX_TOKENS_PER_USER = 20
# How many rows the cross-token feed answers with. The per-token rings already bound the total;
# this bounds what one request carries, because "every call of every token" is a table nobody
# reads past the first screen of and every row past that still crosses the wire.
ACCESS_FEED_MAX = 500


def register(app, wa):
    session_required = wa._session_required
    revoke_others = wa._perm_required('sessions_revoke')

    def _me() -> tuple:
        username = session.get('username', '')
        return username, wa._mfa_uid(username)

    view_others = wa._perm_required('sessions_view')
    edit_users = wa._perm_required('users_edit')

    def _target(username: str):
        """The account an administrator is acting on, real or built-in.

        Returns `(uid, record, error)`. The built-ins are not rows in the users store — a row
        is a login surface — so they are resolved from their synthesized record, which is what
        makes `system` an owner a token can name.
        """
        name = str(username or '')
        if is_reserved_username(name):
            rec = users_svc.builtin_users().get(name.strip().lower())
            if rec is None:
                return '', None, (jsonify({'error': wa._t('user_not_found')}), 404)
            # `anonymous` is the identity of a caller who never identified themselves. A token
            # is an identification, so a token owned by it is a contradiction — and it would
            # put a credential behind the one name the log uses for "we do not know who".
            if name.strip().lower() != SYSTEM_USER:
                return '', None, (jsonify({'error': wa._t('api_token_owner_not_allowed')}), 400)
            # The panel's own identity is not something a delegated user-manager hands out.
            if not wa._is_admin_requester():
                return '', None, (jsonify({'error': wa._t('insufficient_permissions')}), 403)
            return rec.get('uid', ''), rec, None
        user = wa._users.get(name)
        if user is None:
            return '', None, (jsonify({'error': wa._t('user_not_found')}), 404)
        # The same hierarchy guard the rest of the panel applies: an account that is an
        # administrator — by role OR through a group — is not one a non-admin acts on.
        if not wa._is_admin_requester() and users_svc.user_is_admin(user, wa._groups):
            return '', None, (jsonify({'error': wa._t('insufficient_permissions')}), 403)
        return user.get('uid', ''), user, None

    def _owner_permissions(username: str, rec: dict) -> tuple:
        """What a token for this account could ever do — and whether anything bounds it.

        Resolved by the SERVER, through the same function every guard uses, because "what is
        this account's effective permission set" is a question about roles, group membership
        and disabled groups. A second answer computed in the browser would be a second
        implementation of the permission system, and the one that drifted would be the one
        drawing the checkboxes.

        A built-in identity holds none and is unbounded (see service.effective): there is
        nothing to intersect with, so nothing bounds it except the caller.
        """
        if is_reserved_username(username):
            return frozenset(), True
        return wa._get_effective_permissions(
            username, (rec or {}).get('role', '')), False

    def _star_allowed(unbounded: bool):
        """May this caller mint an `'*'` token for the account in hand?

        `'*'` resolves against the OWNER on every request, so for somebody else's token it
        means "everything that account has, and everything it is ever given". That is the
        useful reading — it is how a token for an account keeps matching the account — and it
        is also the one thing here that grows without anybody deciding: whoever minted it saw
        the secret once, so a permission granted to that account next year widens a credential
        they may still be holding.

        Which makes it an ADMINISTRATOR's call and nobody else's. An administrator already
        holds every permission, so a token that tracks an account can never carry them past
        their own ceiling; for a delegated user-manager it could, and that is an escalation
        that arrives by itself.

        For a built-in identity it stays refused, and not as policy: there is no owner set to
        resolve it against, so `service.effective` returns the empty set for it. It would be a
        token that can do nothing while claiming to do everything.
        """
        if unbounded:
            return jsonify({'error': wa._t('api_token_star_not_for_system')}), 400
        if not wa._is_admin_requester():
            return jsonify({'error': wa._t('api_token_star_admin_only')}), 403
        return None

    def _wanted_permissions(data: dict, *, owner=None):
        """The permission set a request asks for, or an error response.

        Shared by minting and editing on purpose: the two are the same decision made at
        different times, and a scope you may not create is not one you may edit your way into.
        Validated against the CALLER's own set — the intersection at request time would drop
        the excess anyway, so refusing here is what keeps the list saying what it means
        instead of showing a permission that silently does nothing.
        """
        wanted = data.get('permissions')
        if wanted == tok_svc.ALL or wanted == [tok_svc.ALL]:
            return tok_svc.ALL, None
        asked = [str(p) for p in (wanted or []) if str(p)]
        if not asked:
            return None, (jsonify({'error': wa._t('api_token_perms_required')}), 400)
        unknown = [p for p in asked if not is_valid_perm(p)]
        if unknown:
            return None, (jsonify({'error': wa._t('api_token_bad_perm'),
                                   'detail': unknown}), 400)
        over = [p for p in asked if p not in wa._get_session_permissions()]
        if over:
            return None, (jsonify({'error': wa._t('api_token_perm_not_yours'),
                                   'detail': over}), 403)
        # …and, for somebody else's token, what the OWNER has. Not a security rule — the
        # intersection at request time drops the excess anyway — but the same one the account's
        # own screen applies: a permission that silently does nothing makes the list say
        # something it does not mean.
        if owner is not None:
            missing = [p for p in asked if p not in owner]
            if missing:
                return None, (jsonify({'error': wa._t('api_token_perm_not_owners'),
                                       'detail': missing}), 400)
        return asked, None

    @app.route('/api/v1/account/tokens', methods=['GET'])
    @session_required
    def api_account_tokens():
        """This account's tokens. No hash, no token — those exist once, at creation."""
        _username, uid = _me()
        rows = wa._api_token_store.list_for(uid) if uid else []
        return jsonify({'tokens': [tok_svc.public(r) for r in rows],
                        'max': MAX_TOKENS_PER_USER})

    @app.route('/api/v1/account/tokens', methods=['POST'])
    @session_required
    def api_account_token_create():
        """Mint a token. The only moment it exists in full is this response.

        Permissions are validated against the CALLER's own set, so a token cannot be minted
        with something its owner does not have — the intersection at request time would drop
        it anyway, and refusing here means the list says what it means instead of showing a
        permission that silently does nothing.
        """
        username, uid = _me()
        if not uid:
            return jsonify({'error': wa._t('user_not_found')}), 404
        data = request.get_json(silent=True) or {}
        name = tok_svc.validate_name(data.get('name'))
        if not name:
            return jsonify({'error': wa._t('api_token_name_required')}), 400
        if wa._api_token_store.count_for(uid) >= MAX_TOKENS_PER_USER:
            return jsonify({'error': wa._t('api_token_too_many')}), 400
        # The name is the only thing in the list that says what a token is for, so two of them
        # wearing the same one makes revoking the right one a coin flip.
        if wa._api_token_store.name_taken(uid, name):
            return jsonify({'error': wa._t('api_token_name_taken')}), 409

        perms, err = _wanted_permissions(data)
        if err:
            return err

        days = data.get('expires_days')
        expires_at = ''
        if days not in (None, '', 0, '0'):
            try:
                days = int(days)
            except (TypeError, ValueError):
                return jsonify({'error': wa._t('api_token_bad_expiry')}), 400
            if days < 1 or days > MAX_EXPIRY_DAYS:
                return jsonify({'error': wa._t('api_token_bad_expiry')}), 400
            expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

        raw, token_id, token_hash = tok_svc.mint()
        tok_uid = wa._api_token_store.create(
            user_uid=uid, name=name, token_id=token_id, token_hash=token_hash,
            permissions=tok_svc.encode_permissions(perms), expires_at=expires_at,
            created=datetime.now(timezone.utc).isoformat(), created_by=username)
        # The detail names the token and what it may do — never the token itself. An audit
        # log that carries a live credential is a second place to steal it from.
        wa._audit('api_token_created', detail={
            'name': name, 'token_id': token_id,
            'permissions': tok_svc.ALL if perms == tok_svc.ALL else sorted(perms),
            'expires_at': expires_at or 'never'})
        row = wa._api_token_store.by_token_id(token_id) or {}
        return jsonify({'ok': True, 'token': raw, 'record': tok_svc.public(row)})

    @app.route('/api/v1/account/tokens/<uid>/access', methods=['GET'])
    @session_required
    def api_account_token_access(uid: str):
        """What one of my tokens has been doing: its recent calls, newest first.

        `last_used` says whether a token is alive; it cannot say what it is for or whether what
        it is doing is what you set it up to do. The audit log answers neither question either
        — it records the ACCOUNT, so a token's writes read as the person's own, and reads are
        not audited for anybody.

        The refused calls are in here on purpose. "This token asked for something it may not
        have" is the line worth finding, and a history of successes only is a history of the
        half that went as expected.
        """
        _username, my_uid = _me()
        row = next((r for r in wa._api_token_store.list_for(my_uid or '')
                    if r.get('uid') == uid), None)
        if not row:
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        return jsonify({'access': wa._api_token_store.access_for(uid),
                        'max': int(getattr(wa, '_API_TOKEN_LOG_MAX', 200) or 0)})

    @app.route('/api/v1/account/tokens/<uid>/rotate', methods=['POST'])
    @session_required
    def api_account_token_rotate(uid: str):
        """A new secret for the same name, permissions and lifetime — **without** the old one
        stopping first.

        Rotating by revoke-then-create is what this replaces, and it has two costs that are
        not obvious until you do it at 3am: the permission set has to be reassembled from
        memory, and everything using the token is broken from the moment you revoke until the
        moment the new one is deployed. Here the old one keeps working, so the changeover has
        a window instead of an outage — and it is revoked when you say so.

        Which means both exist for a while, and names have to stay unique: the OLD one is
        renamed with a "(previous)" suffix and the new one inherits the name. That way
        whatever reads the list still finds the name it knows attached to the token that is
        current, and the one to retire is the one that says it.

        The lifetime carried over is the original SPAN, not the original date: a token that
        was minted for 90 days rotates into another 90 days. Copying the date would hand back
        something that expires tomorrow and call it a rotation.
        """
        _username, my_uid = _me()
        if not my_uid:
            return jsonify({'error': wa._t('user_not_found')}), 404
        old = next((r for r in wa._api_token_store.list_for(my_uid)
                    if r.get('uid') == uid), None)
        if not old or old.get('revoked'):
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        span_days = 0
        if old.get('expires_at') and old.get('created'):
            try:
                span = (datetime.fromisoformat(old['expires_at'])
                        - datetime.fromisoformat(old['created']))
                span_days = max(1, min(MAX_EXPIRY_DAYS, span.days))
            except ValueError:
                span_days = 0
        expires_at = ((datetime.now(timezone.utc) + timedelta(days=span_days)).isoformat()
                      if span_days else '')
        name = tok_svc.validate_name(old.get('name'))
        # Rename first: for the instant between the two writes, two live tokens sharing a name
        # is the state this is here to avoid.
        prev_name = tok_svc.validate_name(f"{name} {wa._t('api_token_prev_suffix')}")
        wa._api_token_store.rename(uid, prev_name, user_uid=my_uid)
        raw, token_id, token_hash = tok_svc.mint()
        wa._api_token_store.create(
            user_uid=my_uid, name=name, token_id=token_id, token_hash=token_hash,
            permissions=old.get('permissions', '[]'), expires_at=expires_at,
            created=datetime.now(timezone.utc).isoformat(), created_by=_username)
        wa._audit('api_token_rotated', detail={
            'name': name, 'token_id': token_id,
            'replaces': old.get('token_id', ''),
            'permissions': tok_svc.decode_permissions(old.get('permissions', '[]')),
            'expires_at': expires_at or 'never'})
        row = wa._api_token_store.by_token_id(token_id) or {}
        return jsonify({'ok': True, 'token': raw, 'record': tok_svc.public(row),
                        'previous': {'uid': uid, 'name': prev_name}})

    @app.route('/api/v1/account/tokens/<uid>', methods=['PUT'])
    @session_required
    def api_account_token_update(uid: str):
        """Change what an existing token may do, without minting a new one.

        The scope and the secret are two different things, and only one of them is wrong when
        a token turns out to need one permission more. Without this, changing a scope meant
        rotate — or revoke and create — which redeploys a secret everywhere it is configured
        to fix a decision that has nothing to do with the secret. That is the kind of cost
        that gets paid once and then avoided by minting the wide token instead.

        It takes effect on the NEXT request the existing token makes: the permissions are read
        from the row and intersected with the owner's on every call, so there is no cached
        grant to invalidate.

        A revoked token is not edited — it is not a token any more, and a scope on it would be
        a promise nothing keeps.
        """
        _username, my_uid = _me()
        if not my_uid:
            return jsonify({'error': wa._t('user_not_found')}), 404
        row = next((r for r in wa._api_token_store.list_for(my_uid)
                    if r.get('uid') == uid), None)
        if not row or row.get('revoked'):
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        perms, err = _wanted_permissions(request.get_json(silent=True) or {})
        if err:
            return err
        before = tok_svc.decode_permissions(row.get('permissions', '[]'))
        if not wa._api_token_store.set_permissions(
                uid, tok_svc.encode_permissions(perms), user_uid=my_uid):
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        # Both sides of the change: an entry that says what a token may do now, without saying
        # what it could do before, cannot answer the only question asked of it.
        wa._audit('api_token_edited', detail={
            'name': row.get('name', ''), 'token_id': row.get('token_id', ''),
            'permissions_before': before if before == tok_svc.ALL else sorted(before),
            'permissions': tok_svc.ALL if perms == tok_svc.ALL else sorted(perms)})
        fresh = next((r for r in wa._api_token_store.list_for(my_uid)
                      if r.get('uid') == uid), row)
        return jsonify({'ok': True, 'record': tok_svc.public(fresh)})

    @app.route('/api/v1/account/tokens/<uid>', methods=['DELETE'])
    @session_required
    def api_account_token_revoke(uid: str):
        """Revoke one of my own tokens."""
        _username, my_uid = _me()
        if not my_uid:
            return jsonify({'error': wa._t('user_not_found')}), 404
        row = next((r for r in wa._api_token_store.list_for(my_uid)
                    if r.get('uid') == uid), None)
        # Pinned to the owner in the UPDATE as well: this lookup is the friendly answer, that
        # one is what makes guessing a uid useless.
        if not wa._api_token_store.revoke(uid, user_uid=my_uid):
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        wa._audit('api_token_revoked', detail={'name': (row or {}).get('name', ''),
                                               'token_id': (row or {}).get('token_id', '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/users/<username>/tokens', methods=['DELETE'])
    @session_required
    @revoke_others
    def api_user_tokens_revoke(username: str):
        """Cut off every token of another account — offboarding, or a leak.

        All of them and not one: this is used when an account's access has to stop, and
        picking tokens off a list one at a time is how one gets left behind.
        """
        user = wa._users.get(username)
        if user is None:
            return jsonify({'error': wa._t('user_not_found')}), 404
        # The same hierarchy guard the rest of the panel applies: an account that is an
        # administrator — by role OR through a group — is not something a non-admin acts on.
        if (not wa._is_admin_requester()
                and users_svc.user_is_admin(user, wa._groups)):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        n = wa._api_token_store.revoke_all_for(user.get('uid', ''))
        if n:
            wa._audit('api_tokens_revoked_by_admin',
                      detail={'username': username, 'count': n})
        return jsonify({'ok': True, 'revoked': n})


    @app.route('/api/v1/tokens', methods=['GET'])
    @session_required
    @view_others
    def api_tokens_all():
        """Every token in the installation, with the account each belongs to.

        The account list answers "who exists" and the sessions screen answers "who is signed
        in"; neither answers "what can run against this panel without anybody signing in",
        which is the question a token makes possible and the one nothing could answer before
        this. Asking it account by account is how the answer ends up depending on which
        accounts somebody remembered to open.
        """
        by_uid = {u.get('uid', ''): name for name, u in wa._users.items()}
        for name, rec in users_svc.builtin_users().items():
            by_uid[rec.get('uid', '')] = name
        out = []
        for row in wa._api_token_store.list_all():
            rec = tok_svc.public(row)
            # A token whose account is gone is not hidden: it cannot authenticate (the hook
            # refuses an owner it cannot resolve), but a row nobody can name is exactly the
            # kind of leftover an audit is looking for, and hiding it answers the question
            # wrongly.
            rec['username'] = by_uid.get(row.get('user_uid', ''), '')
            rec['user_uid'] = row.get('user_uid', '')
            out.append(rec)
        return jsonify({'tokens': out, 'max': MAX_TOKENS_PER_USER})

    @app.route('/api/v1/users/<username>/tokens', methods=['POST'])
    @session_required
    @edit_users
    def api_user_token_create(username: str):
        """Mint a token that acts AS another account — including the built-in `system`.

        Two things make this not an escalation. The permissions must be ones the CALLER holds:
        without that rule, anybody who may edit users could mint a token for an administrator
        and then hold it. And the account hierarchy applies, so a non-admin cannot act on an
        administrator's account at all — the same guard the rest of user management uses.

        `'*'` means "whatever the owner has", which for somebody else's token is the useful
        reading: it keeps matching the account as the account changes. It is an ADMINISTRATOR's
        call for that reason — see `_star_allowed` — and it stays refused for `system`, which
        has no owner set to resolve it against.

        A `system` token is the one whose scope is fixed at creation: that identity holds no
        permissions to be intersected with, so nothing narrows the token afterwards except
        revoking it. It exists because automation that belongs to a person dies with that
        person's account, which is the failure this is here to prevent — and it is the reason
        only an administrator may mint one.
        """
        actor, _uid = _me()
        uid, _rec, err = _target(username)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        name = tok_svc.validate_name(data.get('name'))
        if not name:
            return jsonify({'error': wa._t('api_token_name_required')}), 400
        if wa._api_token_store.count_for(uid) >= MAX_TOKENS_PER_USER:
            return jsonify({'error': wa._t('api_token_too_many')}), 400
        if wa._api_token_store.name_taken(uid, name):
            return jsonify({'error': wa._t('api_token_name_taken')}), 409
        owner_perms, unbounded = _owner_permissions(username, _rec)
        if data.get('permissions') in (tok_svc.ALL, [tok_svc.ALL]):
            serr = _star_allowed(unbounded)
            if serr:
                return serr
        perms, perr = _wanted_permissions(data, owner=None if unbounded else owner_perms)
        if perr:
            return perr

        days = data.get('expires_days')
        expires_at = ''
        if days not in (None, '', 0, '0'):
            try:
                days = int(days)
            except (TypeError, ValueError):
                return jsonify({'error': wa._t('api_token_bad_expiry')}), 400
            if days < 1 or days > MAX_EXPIRY_DAYS:
                return jsonify({'error': wa._t('api_token_bad_expiry')}), 400
            expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

        raw, token_id, token_hash = tok_svc.mint()
        wa._api_token_store.create(
            user_uid=uid, name=name, token_id=token_id, token_hash=token_hash,
            permissions=tok_svc.encode_permissions(perms), expires_at=expires_at,
            created=datetime.now(timezone.utc).isoformat(), created_by=actor)
        # Its own event, and a loud one: this is somebody handing out a credential that is not
        # theirs, which is a different act from minting one for yourself and has to be findable
        # as such.
        wa._audit('api_token_created_for', detail={
            'username': username, 'name': name, 'token_id': token_id,
            'permissions': sorted(perms), 'expires_at': expires_at or 'never'})
        row = wa._api_token_store.by_token_id(token_id) or {}
        rec = tok_svc.public(row)
        rec['username'] = username
        return jsonify({'ok': True, 'token': raw, 'record': rec})

    @app.route('/api/v1/tokens/access', methods=['GET'])
    @session_required
    @view_others
    def api_tokens_access_all():
        """Every call of every token, newest first — the installation's API traffic.

        The per-token history answers "is this credential doing what I set it up to do". This
        answers the one nobody could ask at all: what has been reaching this panel without
        anybody signing in, in order, across every token there is. A burst of 403s from a
        credential nobody was thinking about is a thing you see here and nowhere else.

        Each row carries the account it belongs to, resolved here rather than in the browser:
        the owner of a token is a lookup the server already does for the listing beside it, and
        two answers to "whose is this" is one more than the screen can survive.
        """
        by_uid = {u.get('uid', ''): name for name, u in wa._users.items()}
        for name, rec in users_svc.builtin_users().items():
            by_uid[rec.get('uid', '')] = name
        tokens = {r.get('uid', ''): r for r in wa._api_token_store.list_all()}
        out = []
        for row in wa._api_token_store.access_all(ACCESS_FEED_MAX):
            tk = tokens.get(row.get('token_uid', '')) or {}
            row['name'] = tk.get('name', '')
            row['username'] = by_uid.get(tk.get('user_uid', ''), '')
            out.append(row)
        return jsonify({'access': out, 'max': ACCESS_FEED_MAX})

    @app.route('/api/v1/tokens/<uid>/access', methods=['GET'])
    @session_required
    @view_others
    def api_token_access_any(uid: str):
        """The same history, for any token — including one whose account is gone.

        Especially that one: a credential nobody owns any more is the thing an access review
        wants to read the calls of, and the account it belonged to is not around to be asked.
        """
        row = next((r for r in wa._api_token_store.list_all() if r.get('uid') == uid), None)
        if not row:
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        owner, _rec = wa._token_owner(row.get('user_uid', ''))
        if owner:
            _u, _r, err = _target(owner)
            if err:
                return err
        return jsonify({'access': wa._api_token_store.access_for(uid),
                        'max': int(getattr(wa, '_API_TOKEN_LOG_MAX', 200) or 0)})

    @app.route('/api/v1/users/<username>/permissions', methods=['GET'])
    @session_required
    @edit_users
    def api_user_permissions(username: str):
        """What this account may be given — the checkboxes the token dialog should draw.

        The dialog used to offer the CALLER's permissions and nothing else, so an administrator
        minting a token for a viewer was shown all seventy-five and could tick sixty the viewer
        does not have. Nothing broke — the intersection drops them at request time — which is
        exactly the problem: the list said the token could do things it could never do, and the
        first evidence otherwise was a 403 in whatever was scripted.

        `unbounded` is the built-in identity, whose set is empty because nothing narrows it:
        there the ceiling is the caller's own, and the dialog says so.
        """
        _uid, rec, err = _target(username)
        if err:
            return err
        perms, unbounded = _owner_permissions(username, rec)
        return jsonify({'permissions': sorted(perms), 'unbounded': unbounded})

    @app.route('/api/v1/tokens/<uid>', methods=['PUT'])
    @session_required
    @edit_users
    def api_token_update_any(uid: str):
        """Change what somebody else's token may do, without minting a new one.

        The same act as editing your own, with the two rules that govern every administrative
        act on a token: the account hierarchy, and no granting what the caller does not hold.
        """
        row = next((r for r in wa._api_token_store.list_all() if r.get('uid') == uid), None)
        if not row or row.get('revoked'):
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        owner, rec = wa._token_owner(row.get('user_uid', ''))
        if not owner:
            # A token whose account is gone can be revoked but not re-scoped: there is nobody
            # to bound it by, and an orphan with a fresh permission set is a credential being
            # kept alive rather than cleaned up.
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        _u, _r, err = _target(owner)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        owner_perms, unbounded = _owner_permissions(owner, rec)
        if data.get('permissions') in (tok_svc.ALL, [tok_svc.ALL]):
            serr = _star_allowed(unbounded)
            if serr:
                return serr
        perms, perr = _wanted_permissions(data, owner=None if unbounded else owner_perms)
        if perr:
            return perr
        before = tok_svc.decode_permissions(row.get('permissions', '[]'))
        if not wa._api_token_store.set_permissions(uid, tok_svc.encode_permissions(perms)):
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        wa._audit('api_token_edited_by_admin', detail={
            'username': owner, 'name': row.get('name', ''),
            'token_id': row.get('token_id', ''),
            'permissions_before': before if before == tok_svc.ALL else sorted(before),
            'permissions': sorted(perms)})
        fresh = next((r for r in wa._api_token_store.list_all() if r.get('uid') == uid), row)
        out = tok_svc.public(fresh)
        out['username'] = owner
        return jsonify({'ok': True, 'record': out})

    @app.route('/api/v1/tokens/<uid>/rotate', methods=['POST'])
    @session_required
    @edit_users
    def api_token_rotate_any(uid: str):
        """A new secret for somebody else's token, with the old one still working.

        No scope changes here, so there is nothing to grant and the caller's own permissions do
        not come into it — only the hierarchy, which decides whose credentials you may touch at
        all. The lifetime carried over is the original SPAN, exactly as on your own.
        """
        old = next((r for r in wa._api_token_store.list_all() if r.get('uid') == uid), None)
        if not old or old.get('revoked'):
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        owner, _rec = wa._token_owner(old.get('user_uid', ''))
        if not owner:
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        _u, _r, err = _target(owner)
        if err:
            return err
        span_days = 0
        if old.get('expires_at') and old.get('created'):
            try:
                span = (datetime.fromisoformat(old['expires_at'])
                        - datetime.fromisoformat(old['created']))
                span_days = max(1, min(MAX_EXPIRY_DAYS, span.days))
            except ValueError:
                span_days = 0
        expires_at = ((datetime.now(timezone.utc) + timedelta(days=span_days)).isoformat()
                      if span_days else '')
        name = tok_svc.validate_name(old.get('name'))
        prev_name = tok_svc.validate_name(f"{name} {wa._t('api_token_prev_suffix')}")
        wa._api_token_store.rename(uid, prev_name)
        raw, token_id, token_hash = tok_svc.mint()
        actor, _my = _me()
        wa._api_token_store.create(
            user_uid=old.get('user_uid', ''), name=name, token_id=token_id,
            token_hash=token_hash, permissions=old.get('permissions', '[]'),
            expires_at=expires_at, created=datetime.now(timezone.utc).isoformat(),
            created_by=actor)
        wa._audit('api_token_rotated_by_admin', detail={
            'username': owner, 'name': name, 'token_id': token_id,
            'replaces': old.get('token_id', ''),
            'expires_at': expires_at or 'never'})
        row = wa._api_token_store.by_token_id(token_id) or {}
        out = tok_svc.public(row)
        out['username'] = owner
        return jsonify({'ok': True, 'token': raw, 'record': out,
                        'previous': {'uid': uid, 'name': prev_name}})

    @app.route('/api/v1/tokens/<uid>', methods=['DELETE'])
    @session_required
    @revoke_others
    def api_token_revoke_any(uid: str):
        """Revoke one token belonging to anybody — a leak, or a leftover.

        Revoking ALL of an account's is the offboarding tool and stays where it is; this is
        for the row you are looking at, which is what an administrator reading a list of
        standing access actually wants to act on.
        """
        row = next((r for r in wa._api_token_store.list_all() if r.get('uid') == uid), None)
        if not row:
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        owner, _rec = wa._token_owner(row.get('user_uid', ''))
        # An account this caller may not act on is not one whose credentials they may cut —
        # except when it no longer exists, where the leftover is the whole point.
        if owner:
            _uid, _r, err = _target(owner)
            if err:
                return err
        if not wa._api_token_store.revoke(uid):
            return jsonify({'error': wa._t('api_token_not_found')}), 404
        wa._audit('api_token_revoked_by_admin', detail={
            'username': owner or '', 'name': row.get('name', ''),
            'token_id': row.get('token_id', '')})
        return jsonify({'ok': True})
