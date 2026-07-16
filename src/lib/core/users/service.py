#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free user-management operations — the single source of truth for user
validation + mutation, shared by the web routes (:mod:`lib.core.users.routes`) and the
CLI (:mod:`lib.cli`).

Each function validates and mutates the plain ``users`` dict (``{username: {...}}``) and
raises :class:`AdminOpError` (carrying an i18n key + args) on any rule violation.  Callers
own **persistence** (``UsersStore``/``_persist_users``), **audit**, and any
**requester-context** guards (self-edit, role hierarchy) — those need the request/session
and stay in the routes; the CLI runs as an operator and doesn't apply them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

from lib.core.constants import SYSTEM_USER
from lib.core.permissions import BUILTIN_ROLE_UIDS
from lib.util.entity_audit import touch_entity, track_change

MAX_USERNAME_LEN = 64
MAX_DISPLAY_NAME_LEN = 128
_SYMBOLS = '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'


class AdminOpError(Exception):
    """A validation/operation failure carrying an i18n key + args (like ``WebAdmin._t``)."""

    def __init__(self, key: str, *args):
        super().__init__(key)
        self.key = key
        self.args = args


@dataclass
class PasswordPolicy:
    """Password rules — mirrors the ``web_admin|pw_*`` config (see WebAdmin)."""
    min_len: int = 8
    max_len: int = 128
    require_upper: bool = False
    require_digit: bool = False
    require_symbol: bool = False


def validate_password(pw: str, policy: PasswordPolicy) -> tuple | None:
    """Return an i18n error tuple ``(key, *args)`` if *pw* violates *policy*, else ``None``.
    The one implementation of the password policy, shared by the UI and the CLI."""
    if len(pw) < policy.min_len:
        return ('password_too_short', str(policy.min_len))
    if len(pw) > policy.max_len:
        return ('password_too_long', str(policy.max_len))
    if policy.require_upper and not (any(c.isupper() for c in pw) and any(c.islower() for c in pw)):
        return ('password_need_upper',)
    if policy.require_digit and not any(c.isdigit() for c in pw):
        return ('password_need_digit',)
    if policy.require_symbol and not any(c in _SYMBOLS for c in pw):
        return ('password_need_symbol',)
    return None


# ── role helpers (uid ⇆ name), Flask-free ──────────────────────────────────────
def resolve_role_uid(role: str, custom_roles: dict) -> str | None:
    """Resolve a role given as a built-in key ('admin'…), a role UID, or a custom-role
    name/UID → its UID, or ``None`` if unknown."""
    if not role:
        return None
    if role in BUILTIN_ROLE_UIDS:                 # built-in internal key
        return BUILTIN_ROLE_UIDS[role]
    if role in set(BUILTIN_ROLE_UIDS.values()) | set(custom_roles):   # already a valid uid
        return role
    for uid, rd in custom_roles.items():          # custom role by display name / key
        if rd.get('name') == role or rd.get('key') == role:
            return uid
    return None


def role_is_admin(role_uid: str) -> bool:
    """True if a stored role UID is the built-in admin role."""
    return role_uid == BUILTIN_ROLE_UIDS['admin']


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── operations ─────────────────────────────────────────────────────────────────
def create_user(users: dict, *, username: str, password: str, policy: PasswordPolicy,
                custom_roles: dict, groups: dict, role: str = 'none', display_name: str = '',
                email: str = '', lang: str = '', landing_page: str = '', group_uids=(),
                enabled: bool = True, actor: str = SYSTEM_USER, valid_langs=(),
                valid_landing=()) -> str:
    """Validate and add a new user to *users*. Returns the username. Mutates *users* in
    place (no persistence). Raises :class:`AdminOpError` on any violation."""
    username = (username or '').strip()
    display_name = (display_name or '').strip() or username
    email = (email or '').strip()
    if not username:
        raise AdminOpError('username_required')
    if username.lower() == SYSTEM_USER:
        raise AdminOpError('username_reserved', SYSTEM_USER)
    if len(username) > MAX_USERNAME_LEN:
        raise AdminOpError('name_too_long', MAX_USERNAME_LEN)
    if not password:
        raise AdminOpError('password_required')
    pw_err = validate_password(password, policy)
    if pw_err:
        raise AdminOpError(*pw_err)
    if len(display_name) > MAX_DISPLAY_NAME_LEN:
        raise AdminOpError('display_name_too_long', MAX_DISPLAY_NAME_LEN)
    role_uid = resolve_role_uid(role, custom_roles)
    if not role_uid:
        raise AdminOpError('invalid_role')
    if lang and valid_langs and lang not in valid_langs:
        raise AdminOpError('invalid_lang', lang)
    landing_page = str(landing_page or '').strip()
    if landing_page and valid_landing and landing_page not in valid_landing:
        raise AdminOpError('invalid_landing_page')
    group_uids = list(group_uids or [])
    unknown = [g for g in group_uids if g not in groups]
    if unknown:
        raise AdminOpError('invalid_groups', ', '.join(unknown))
    if username in users:
        raise AdminOpError('user_already_exists', username)

    ts = _now()
    rec = {
        'uid': str(uuid.uuid4()), 'password_hash': generate_password_hash(password),
        'role': role_uid, 'display_name': display_name,
        'created_at': ts, 'updated_at': ts, 'updated_by': actor,
    }
    if email:
        rec['email'] = email
    if lang:
        rec['lang'] = lang
    if landing_page:
        rec['landing_page'] = landing_page
    if group_uids:
        rec['groups'] = group_uids
    if not enabled:
        rec['enabled'] = False
    users[username] = rec
    return username


def set_password(user: dict, password: str, policy: PasswordPolicy, *, actor: str = SYSTEM_USER) -> None:
    """Set (hash) a user's password after policy validation. Raises on violation."""
    if user.get('auth_source', 'local') != 'local':
        raise AdminOpError('sso_user_no_password')
    pw_err = validate_password(password, policy)
    if pw_err:
        raise AdminOpError(*pw_err)
    user['password_hash'] = generate_password_hash(password)
    user['updated_by'] = actor
    user['updated_at'] = _now()


def set_role(users: dict, username: str, role: str, custom_roles: dict, *,
             actor: str = SYSTEM_USER) -> str:
    """Set a user's role (guards against demoting the last admin). Returns the new UID."""
    user = users[username]
    new_uid = resolve_role_uid(role, custom_roles)
    if not new_uid:
        raise AdminOpError('invalid_role')
    if role_is_admin(user.get('role', '')) and not role_is_admin(new_uid):
        if sum(1 for u in users.values() if role_is_admin(u.get('role', ''))) <= 1:
            raise AdminOpError('must_have_admin')
    user['role'] = new_uid
    user['updated_by'] = actor
    user['updated_at'] = _now()
    return new_uid


def set_enabled(users: dict, username: str, enabled: bool, *, actor: str = SYSTEM_USER) -> bool:
    """Enable/disable a user (guards against disabling the last active admin).
    Returns True if the state actually changed."""
    user = users[username]
    if user.get('enabled', True) == enabled:
        return False
    if not enabled and role_is_admin(user.get('role', '')):
        active_admins = sum(1 for u in users.values()
                            if role_is_admin(u.get('role', '')) and u.get('enabled', True))
        if active_admins <= 1:
            raise AdminOpError('cannot_disable_last_admin')
    user['enabled'] = enabled
    user['updated_by'] = actor
    user['updated_at'] = _now()
    return True


def set_groups(user: dict, group_uids: list, groups: dict, *, actor: str = SYSTEM_USER) -> None:
    """Replace a user's group membership (validated against *groups*)."""
    unknown = [g for g in group_uids if g not in groups]
    if unknown:
        raise AdminOpError('invalid_groups', ', '.join(unknown))
    user['groups'] = list(group_uids)
    user['updated_by'] = actor
    user['updated_at'] = _now()


def add_group(user: dict, group_uid: str, groups: dict, *, actor: str = SYSTEM_USER) -> bool:
    """Add a group to a user's membership. Returns True if it was added."""
    if group_uid not in groups:
        raise AdminOpError('invalid_groups', group_uid)
    cur = list(user.get('groups', []))
    if group_uid in cur:
        return False
    cur.append(group_uid)
    user['groups'] = cur
    user['updated_by'] = actor
    user['updated_at'] = _now()
    return True


def remove_group(user: dict, group_uid: str, *, actor: str = SYSTEM_USER) -> bool:
    """Remove a group from a user's membership. Returns True if it was removed."""
    cur = list(user.get('groups', []))
    if group_uid not in cur:
        return False
    user['groups'] = [g for g in cur if g != group_uid]
    user['updated_by'] = actor
    user['updated_at'] = _now()
    return True


def update_user(users: dict, username: str, data: dict, *, policy: PasswordPolicy,
                custom_roles: dict, groups: dict, valid_langs=(), valid_landing=(),
                max_display_name_len: int = MAX_DISPLAY_NAME_LEN, role_display=None,
                actor: str = SYSTEM_USER) -> dict:
    """Apply an admin edit to an existing user from a request *data* dict — the data-side
    of ``PUT /api/v1/users/<username>``. Validates + mutates + audits each field and returns
    ``{'changes': [...], 'password_reset': bool, 'disabled': bool}`` so the caller can audit
    and run the session side-effects (revoke on password reset / disable).

    The **requester-context** guards (role hierarchy, only-admin-grants-admin,
    reset-another's-password, can't-disable-self) need the session and stay with the caller,
    which must run them before calling this. *role_display* is an optional ``uid -> name``
    callable used only for the role-change audit label (injected to stay Flask-free)."""
    user = users[username]
    is_sso = user.get('auth_source', 'local') != 'local'
    changes: list[dict] = []
    password_reset = False
    disabled = False

    if 'role' in data:
        new_role_uid = resolve_role_uid(data['role'], custom_roles)
        if not new_role_uid:
            raise AdminOpError('invalid_role')
        # Prevent demoting the last admin.
        if role_is_admin(user.get('role', '')) and not role_is_admin(new_role_uid):
            if sum(1 for u in users.values() if role_is_admin(u.get('role', ''))) <= 1:
                raise AdminOpError('must_have_admin')
        old_role_uid = user.get('role', '')
        if old_role_uid != new_role_uid:   # compare uid-to-uid, not name-to-uid
            changes.append({
                'field': 'role',
                'old': role_display(old_role_uid) if role_display else old_role_uid,
                'new': role_display(new_role_uid) if role_display else new_role_uid,
            })
        user['role'] = new_role_uid

    if 'display_name' in data and not is_sso:
        new_dn = data['display_name'].strip() or username
        if len(new_dn) > max_display_name_len:
            raise AdminOpError('display_name_too_long', max_display_name_len)
        track_change(changes, user, 'display_name', new_dn, old_default=username)

    if 'password' in data and data['password']:
        if is_sso:
            raise AdminOpError('sso_user_no_password')
        pw_err = validate_password(data['password'], policy)
        if pw_err:
            raise AdminOpError(*pw_err)
        user['password_hash'] = generate_password_hash(data['password'])
        password_reset = True

    if 'email' in data and not is_sso:
        track_change(changes, user, 'email', data['email'].strip())

    if 'lang' in data:
        lang = data['lang']
        if lang != '' and valid_langs and lang not in valid_langs:
            raise AdminOpError('invalid_lang', lang)
        track_change(changes, user, 'lang', lang)

    if 'landing_page' in data:
        lp = str(data['landing_page'] or '').strip()   # '' = inherit (group/global)
        if lp and valid_landing and lp not in valid_landing:
            raise AdminOpError('invalid_landing_page')
        track_change(changes, user, 'landing_page', lp)

    if 'dark_mode' in data:
        dm = data['dark_mode']
        if dm is not None and not isinstance(dm, bool):
            raise AdminOpError('invalid_dark_mode')
        old_dm = user.get('dark_mode')
        if old_dm != dm:
            changes.append({'field': 'dark_mode', 'old': old_dm, 'new': dm})
        if dm is None:
            user.pop('dark_mode', None)
        else:
            user['dark_mode'] = dm

    if 'groups' in data:
        if not isinstance(data['groups'], list):
            raise AdminOpError('invalid_groups', '')
        unknown = [g for g in data['groups'] if g not in groups]
        if unknown:
            raise AdminOpError('invalid_groups', ', '.join(unknown))
        old_groups_names = sorted(g for g in user.get('groups', []) if g in groups)
        new_groups_names = sorted(data['groups'])
        if old_groups_names != new_groups_names:
            changes.append({'field': 'groups', 'old': old_groups_names, 'new': new_groups_names})
        user['groups'] = list(data['groups'])

    if 'enabled' in data:
        new_enabled = bool(data['enabled'])
        old_enabled = user.get('enabled', True)
        if old_enabled != new_enabled:
            # Guard against disabling the last active admin (can't-disable-self is a
            # requester-context guard and stays with the caller).
            if not new_enabled and role_is_admin(user.get('role', '')):
                active = sum(1 for d in users.values()
                             if role_is_admin(d.get('role', '')) and d.get('enabled', True))
                if active <= 1:
                    raise AdminOpError('cannot_disable_last_admin')
            changes.append({'field': 'enabled', 'old': old_enabled, 'new': new_enabled})
            user['enabled'] = new_enabled
            if not new_enabled:
                disabled = True

    # Admin housekeeping: clear a user's stored UI customisations so they fall back to the
    # defaults — table column layouts, the overview dashboard layout, and/or modal layouts.
    clear_keys = data.get('clear_table_keys')
    if isinstance(clear_keys, list) and isinstance(user.get('table_config'), dict):
        removed = [k for k in clear_keys if user['table_config'].pop(str(k), None) is not None]
        if removed:
            changes.append({'field': 'table_config', 'old': sorted(removed), 'new': 'cleared'})
    if data.get('clear_dashboard_layout') and user.pop('dashboard_layout', None):
        changes.append({'field': 'dashboard_layout', 'old': 'custom', 'new': 'cleared'})
    clear_mkeys = data.get('clear_modal_keys')
    if isinstance(clear_mkeys, list) and isinstance(user.get('modal_config'), dict):
        removed_m = [k for k in clear_mkeys if user['modal_config'].pop(str(k), None) is not None]
        if removed_m:
            changes.append({'field': 'modal_config', 'old': sorted(removed_m), 'new': 'cleared'})

    touch_entity(user, actor)
    return {'changes': changes, 'password_reset': password_reset, 'disabled': disabled}
