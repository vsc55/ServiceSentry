#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI command handlers (user/group admin + service status/reload).

Each handler runs against a :class:`lib.cli.context.CliContext` and reuses the canonical,
Flask-free operations in :mod:`lib.core.users.service` / :mod:`lib.core.groups.service`.
Returns a shell exit code (0 = ok). Validation failures surface as the same i18n messages
the web UI shows.
"""

from __future__ import annotations

import getpass
import sys
import time

from lib.core.groups import service as groups_svc
from lib.core.users import service as users_svc
from lib.core.users.service import AdminOpError
from lib.core.permissions import BUILTIN_ROLE_UIDS
from lib.i18n import translate

# UID → built-in role key (the inverse of BUILTIN_ROLE_UIDS), for display.
_BUILTIN_UID_TO_KEY = {uid: key for key, uid in BUILTIN_ROLE_UIDS.items()}

_LIVE_SECS = 60   # a heartbeat newer than this ⇒ the instance is considered live


def _status_services() -> list:
    """Every embedded service, auto-discovered from its ``EMBEDDED_SERVICE`` descriptor —
    no hardcoded list, a new service shows up automatically."""
    from lib.services import discover_embedded_services  # noqa: PLC0415
    return [m['key'] for m in discover_embedded_services()]


def _reload_targets() -> list:
    """Services that run a command-draining daemon, auto-discovered from their
    ``STANDALONE`` descriptor — exactly the services whose heartbeat loop claims and
    applies the ``reload`` command (inline services like ipban have no daemon, so no
    ``STANDALONE`` entry, and are skipped)."""
    from lib.services import discover_standalone_services  # noqa: PLC0415
    return [d['key'] for d in discover_standalone_services()]


def _t(ctx, key, *args) -> str:
    return translate(ctx.lang, key, *args)


def _err(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def _ok(msg: str) -> int:
    print(msg)
    return 0


def _role_label(ctx, role_uid: str) -> str:
    """Human label for a role UID (built-in key or custom name)."""
    if role_uid in _BUILTIN_UID_TO_KEY:
        return _BUILTIN_UID_TO_KEY[role_uid]
    rd = ctx.roles.get(role_uid) or {}
    return rd.get('name') or role_uid


def _require_user(ctx, username: str):
    if username not in ctx.users:
        raise AdminOpError('user_not_found')
    return ctx.users[username]


# ── user commands ──────────────────────────────────────────────────────────────
def cmd_user_add(ctx, args) -> int:
    password = args.password or getpass.getpass('Password: ')
    try:
        gids = []
        for g in (args.group or []):
            uid = ctx.group_uid(g)
            if not uid:
                return _err(_t(ctx, 'invalid_groups', g))
            gids.append(uid)
        users_svc.create_user(
            ctx.users, username=args.username, password=password,
            policy=ctx.password_policy(), custom_roles=ctx.roles, groups=ctx.groups,
            role=args.role or 'none', display_name=args.display or '', email=args.email or '',
            group_uids=gids, enabled=not args.disabled, actor='cli')
    except AdminOpError as e:
        return _err(_t(ctx, e.key, *e.args))
    ctx.persist_users()
    return _ok(f"user '{args.username}' created (role {args.role or 'none'}"
               f"{', disabled' if args.disabled else ''})")


def cmd_user_enable(ctx, args) -> int:
    return _set_enabled(ctx, args.username, True)


def cmd_user_disable(ctx, args) -> int:
    return _set_enabled(ctx, args.username, False)


def _set_enabled(ctx, username: str, enabled: bool) -> int:
    try:
        _require_user(ctx, username)
        changed = users_svc.set_enabled(ctx.users, username, enabled, actor='cli')
    except AdminOpError as e:
        return _err(_t(ctx, e.key, *e.args))
    if changed:
        ctx.persist_users()
        return _ok(f"user '{username}' {'enabled' if enabled else 'disabled'}")
    return _ok(f"user '{username}' already {'enabled' if enabled else 'disabled'}")


def cmd_user_passwd(ctx, args) -> int:
    password = args.password or getpass.getpass('New password: ')
    try:
        user = _require_user(ctx, args.username)
        users_svc.set_password(user, password, ctx.password_policy(), actor='cli')
    except AdminOpError as e:
        return _err(_t(ctx, e.key, *e.args))
    ctx.persist_users()
    return _ok(f"password updated for '{args.username}'")


def cmd_user_role(ctx, args) -> int:
    try:
        _require_user(ctx, args.username)
        new_uid = users_svc.set_role(ctx.users, args.username, args.role, ctx.roles, actor='cli')
    except AdminOpError as e:
        return _err(_t(ctx, e.key, *e.args))
    ctx.persist_users()
    return _ok(f"user '{args.username}' role set to {_role_label(ctx, new_uid)}")


def cmd_user_group_add(ctx, args) -> int:
    return _user_group(ctx, args, add=True)


def cmd_user_group_del(ctx, args) -> int:
    return _user_group(ctx, args, add=False)


def _user_group(ctx, args, *, add: bool) -> int:
    gid = ctx.group_uid(args.group)
    if not gid:
        return _err(_t(ctx, 'invalid_groups', args.group))
    try:
        user = _require_user(ctx, args.username)
        if add:
            changed = users_svc.add_group(user, gid, ctx.groups, actor='cli')
        else:
            changed = users_svc.remove_group(user, gid, actor='cli')
    except AdminOpError as e:
        return _err(_t(ctx, e.key, *e.args))
    if changed:
        ctx.persist_users()
        verb = 'added to' if add else 'removed from'
        return _ok(f"user '{args.username}' {verb} group '{args.group}'")
    return _ok(f"user '{args.username}' {'already in' if add else 'not in'} group '{args.group}'")


# ── group commands ─────────────────────────────────────────────────────────────
def cmd_group_add(ctx, args) -> int:
    try:
        uid = groups_svc.create_group(
            ctx.groups, name=args.name, description=args.description or '',
            roles=(args.role or []), custom_roles=ctx.roles, actor='cli')
    except AdminOpError as e:
        return _err(_t(ctx, e.key, *e.args))
    ctx.persist_groups()
    return _ok(f"group '{args.name}' created (uid {uid})")


def cmd_group_del(ctx, args) -> int:
    gid = ctx.group_uid(args.name)
    if not gid:
        return _err(_t(ctx, 'group_not_found'))
    try:
        affected = groups_svc.delete_group(ctx.groups, ctx.users, gid)
    except AdminOpError as e:
        return _err(_t(ctx, e.key, *e.args))
    if affected:
        ctx.persist_users()
    ctx.persist_groups()
    return _ok(f"group '{args.name}' deleted"
               + (f" (removed from {len(affected)} user(s))" if affected else ""))


# ── service status / reload ─────────────────────────────────────────────────────
def cmd_status(ctx, args) -> int:
    by_key: dict[str, list] = {}
    for inst in ctx.instances_store.list_instances():
        by_key.setdefault(inst.get('service_key'), []).append(inst)
    now = time.time()
    print(f"{'SERVICE':12} {'STATE':10} {'ENABLED':8} INSTANCES")
    for key in dict.fromkeys(_status_services() + list(by_key)):
        rows = by_key.get(key, [])
        enabled = bool((ctx.cfg.get(key) or {}).get('enabled', True))
        if rows:
            live = any(r.get('running') and (now - (r.get('last_seen') or 0) < _LIVE_SECS) for r in rows)
            state = 'running' if live else 'stopped'
        else:
            state = '-'
        print(f"{key:12} {state:10} {('yes' if enabled else 'no'):8} {len(rows)}")
    return 0


def cmd_reload(ctx, args) -> int:
    sent = []
    for key in _reload_targets():
        if ctx.commands_store.enqueue(key, 'reload', created_by='cli'):
            sent.append(key)
    if not sent:
        return _err('could not queue reload commands')
    print(f"reload queued for: {', '.join(sent)}")
    print("a running daemon applies it on its next heartbeat (~10s) and reconciles services")
    return 0


# ── dispatch ────────────────────────────────────────────────────────────────────
_HANDLERS = {
    ('user', 'add'):        cmd_user_add,
    ('user', 'enable'):     cmd_user_enable,
    ('user', 'disable'):    cmd_user_disable,
    ('user', 'passwd'):     cmd_user_passwd,
    ('user', 'role'):       cmd_user_role,
    ('user', 'group-add'):  cmd_user_group_add,
    ('user', 'group-del'):  cmd_user_group_del,
    ('group', 'add'):       cmd_group_add,
    ('group', 'del'):       cmd_group_del,
    ('status', None):       cmd_status,
    ('reload', None):       cmd_reload,
}


def run(args, config_dir: str, var_dir: str) -> int:
    """Entry point from main.py — build the context and dispatch to the handler."""
    from lib.cli.context import CliContext  # noqa: PLC0415 (defer the store imports)
    handler = _HANDLERS.get((args.cmd, getattr(args, 'sub', None)))
    if handler is None:
        print(f"error: unknown command '{args.cmd} {getattr(args, 'sub', '') or ''}'".strip(),
              file=sys.stderr)
        return 2
    try:
        ctx = CliContext(config_dir, var_dir)
    except Exception as exc:  # pylint: disable=broad-except
        return _err(f"could not open ServiceSentry data ({config_dir}): {exc}")
    return handler(ctx, args)
