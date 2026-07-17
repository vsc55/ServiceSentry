#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recipient token resolution for notification channels.

A recipient list (e.g. ``email|recipients``) is a comma-separated string whose
tokens are one of:

* a plain address                — passed through as-is;
* ``user:<user_uid>``            — resolved to that panel user's email;
* ``group:<group_uid>``          — resolved to the emails of the group's members.

Only *enabled* users with a non-empty email contribute. The result is de-duplicated
(case-insensitive, order-preserving); tokens that resolve to nothing (unknown or
email-less user/group) are reported in ``skipped`` so a caller can warn.

It builds :class:`UsersStore` / :class:`GroupsStore` from the shared DB connector, so
it works in every process that has one (web admin and the monitor alike) — the router
owns it via ``router.store('recipients', lambda ctx: RecipientResolver(ctx.db))``, so
no channel or the router itself has to know about the user/group stores directly.
"""

from __future__ import annotations

USER_PREFIX = 'user:'
GROUP_PREFIX = 'group:'


def parse_tokens(raw) -> list[str]:
    """Split a recipient string (comma/semicolon separated) into trimmed tokens.
    A list is returned as-is (already tokenised)."""
    if isinstance(raw, (list, tuple)):
        return [str(t).strip() for t in raw if str(t).strip()]
    return [t.strip() for t in str(raw or '').replace(';', ',').split(',') if t.strip()]


class RecipientResolver:
    """Expand recipient tokens (plain email | ``user:<uid>`` | ``group:<uid>``)."""

    def __init__(self, db) -> None:
        self._db = db

    def _load(self) -> dict:
        """Snapshot the directory needed to resolve tokens (loaded fresh so directory
        edits take effect immediately). Names are recorded for *all* users/groups (so a
        skipped token still gets a friendly label), but only **enabled** users contribute
        an email/membership and only **enabled** groups may expand::

            {'user_email': {uid: email},   # enabled users with an email only
             'user_name':  {uid: label},   # all users (for labels)
             'group_emails': {uid: [email]}, 'group_name': {uid: name},
             'group_enabled': {uid, …}}
        """
        user_email: dict = {}
        user_name: dict = {}
        group_emails: dict = {}
        group_name: dict = {}
        group_enabled: set = set()
        try:
            from lib.core.users.store import UsersStore    # noqa: PLC0415
            for uname, u in (UsersStore(self._db).load() or {}).items():
                if not isinstance(u, dict):
                    continue
                uid = u.get('uid') or uname
                user_name[uid] = u.get('display_name') or uname
                if u.get('enabled') is False:              # disabled: labelled, but no email
                    continue
                email = (u.get('email') or '').strip()
                if not email:
                    continue
                user_email[uid] = email
                for guid in (u.get('groups') or []):
                    group_emails.setdefault(guid, []).append(email)
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            from lib.core.groups.store import GroupsStore   # noqa: PLC0415
            for uid, g in (GroupsStore(self._db).load() or {}).items():
                group_name[uid] = g.get('name') or uid
                if g.get('enabled') is not False:
                    group_enabled.add(uid)
        except Exception:  # pylint: disable=broad-except
            pass
        return {'user_email': user_email, 'user_name': user_name,
                'group_emails': group_emails, 'group_name': group_name,
                'group_enabled': group_enabled}

    def expand(self, raw) -> dict:
        """Resolve ``raw`` (string or token list) → ``{'emails', 'skipped'}``. ``emails``
        is de-duplicated case-insensitively (order kept); ``skipped`` carries human labels
        for tokens that yield nobody — an unknown (deleted), disabled, or email-less
        user/group — so the caller can warn. A deleted user/group falls back to its uid."""
        tokens = parse_tokens(raw)
        needs_dir = any(t.startswith((USER_PREFIX, GROUP_PREFIX)) for t in tokens)
        d = self._load() if needs_dir else {}
        out: list[str] = []
        seen: set = set()
        skipped: list[str] = []

        def _add(email: str) -> None:
            key = email.lower()
            if key not in seen:
                seen.add(key)
                out.append(email)

        for tok in tokens:
            if tok.startswith(GROUP_PREFIX):
                guid = tok[len(GROUP_PREFIX):]
                # Disabled or deleted group → don't send; empty group → nothing to send.
                members = (d.get('group_emails', {}).get(guid) or []
                           if guid in d.get('group_enabled', set()) else [])
                if not members:
                    skipped.append(d.get('group_name', {}).get(guid, guid))
                    continue
                for e in members:
                    _add(e)
            elif tok.startswith(USER_PREFIX):
                uid = tok[len(USER_PREFIX):]
                email = d.get('user_email', {}).get(uid)   # only enabled users with an email
                if not email:
                    skipped.append(d.get('user_name', {}).get(uid, uid))
                    continue
                _add(email)
            else:
                _add(tok)
        return {'emails': out, 'skipped': skipped}

    def resolve(self, raw) -> list[str]:
        """Convenience: just the resolved email list (see :meth:`expand`)."""
        return self.expand(raw)['emails']
