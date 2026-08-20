#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The configuration a watchful ACTION runs with, resolved the way a scheduled check would.

An action asked for from the UI (`/api/v1/modules/watchfuls/<module>/<action>`) is handed a
config from a form, and a form does not carry what a scheduled run has: the bound host's
address and SSH settings, the secrets the browser was never given, the credential the item
merely references. Each of those is filled in here, mirroring what ``ModuleBase.resolve_host``
does on the scheduler's side — because an action that behaves differently from the check it
belongs to is worse than no action at all.

Resolved TWICE, at two shapes: a flat form posted for the module, and the item nested under
its collection when a discovery is scoped to one — the item is where `host_uid` and `cred_uid`
live, so the second pass is not a nicety.

The one thing here that is not about the config going in is `cap_audit_lists`, which bounds
what the result may record. Same reason, other end: how much of its own output an action may
put in one audit entry is not the module's call.

Flask-free: it takes the panel object and a dict, and answers with a dict.
"""

from __future__ import annotations

import json
import os

from .items import is_item_collection


# ── watchful-action config resolution ────────────────────────────────────────────
# Flask-free config resolution/merge for /api/v1/modules/watchfuls/<module>/<action>: resolve the
# bound host (address + SSH, server-side), restore masked secrets, and overlay referenced
# credentials — mirroring what ModuleBase.resolve_host does for a scheduled check.
def resolve_host_ctx(wa, config):
    """Build a host-context dict for host-aware discovery, or None.

    Resolved server-side so SSH secrets never come from the client: a ``host_uid`` is looked
    up in the host registry (decrypted); a brand-new (unsaved) host may instead pass a
    ``_host`` draft, whose masked secrets are restored from the stored host when a ``host_uid``
    is also given."""
    from lib.core.hosts.resolve import resolve_os  # noqa: PLC0415

    def _apply_ssh_cred(ssh):
        """Overlay a named SSH credential (ssh profile ``cred_uid``) — the host may reference
        the credential manager instead of inline secrets, so host-aware discovery must resolve
        it (like ModuleBase does for checks)."""
        ssh = dict(ssh or {})
        cred_uid = str(ssh.get('cred_uid') or '').strip()
        cstore = getattr(wa, '_credentials_store', None)
        if not cred_uid or cstore is None:
            return ssh
        try:
            cred = cstore.get(cred_uid)
        except Exception:  # pylint: disable=broad-except
            return ssh
        if not cred:
            return ssh
        from lib.core.credentials.store import apply_credential  # noqa: PLC0415
        return apply_credential(ssh, cred)

    def _ctx(address, kind, os_, ssh):
        is_remote = str(kind or 'local').strip().lower() == 'remote'
        # Web discovery can't probe a remote OS here → assume 'linux' for 'auto'.
        os_ = resolve_os(os_, is_remote, remote_auto='linux')
        return {'address': address or '', 'kind': kind or 'local', 'os': os_,
                'ssh': _apply_ssh_cred(ssh)}

    store = getattr(wa, '_hosts_store', None)
    uid = str(config.get('host_uid') or '').strip()
    if not uid:
        # Multi-host (cluster) check: provision against the primary bound host.
        uids = config.get('host_uids')
        if isinstance(uids, list):
            uid = next((str(u).strip() for u in uids if str(u).strip()), '')
    stored = store.get(uid, decrypt=True) if (store and uid) else None
    draft = config.get('_host') if isinstance(config.get('_host'), dict) else None

    if draft:
        ssh = dict((draft.get('profiles') or {}).get('ssh') or draft.get('ssh') or {})
        if stored:  # restore secrets the client masked out
            stored_ssh = (stored.get('profiles') or {}).get('ssh') or {}
            for k in ('ssh_password', 'ssh_key_string'):
                if ssh.get(k) in (None, '') and stored_ssh.get(k):
                    ssh[k] = stored_ssh[k]
        return _ctx(draft.get('address') or (stored or {}).get('address'),
                    draft.get('kind') or (stored or {}).get('kind'),
                    draft.get('os') or (stored or {}).get('os'), ssh)
    if stored:
        return _ctx(stored.get('address'), stored.get('kind'), stored.get('os'),
                    (stored.get('profiles') or {}).get('ssh') or {})
    return None


def fill_from_stored_item(wa, module, config):
    """Fill an action's *config* from the STORED item named by ``_item_key``, for keys the
    client did not send.

    An action invoked from a form posts the whole (possibly unsaved) item, and those values
    must win — they are what the user is testing.  But an action invoked from somewhere with
    no form (a module's own section asking for a live refresh) knows only the item key, and
    without this it would run against an empty item: no ``cred_uid``, so no credentials, so
    a puzzling authentication failure on a check that works everywhere else.
    """
    key = str(config.get('_item_key') or '').strip()
    if not key:
        return
    try:
        modules = wa._load_modules()
    except Exception:  # pylint: disable=broad-except
        return
    for mk in (module, f'watchfuls.{module}'):
        mod = modules.get(mk)
        if not isinstance(mod, dict):
            continue
        for coll, items in mod.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            stored = items.get(key)
            if isinstance(stored, dict):
                for k, v in stored.items():
                    config.setdefault(k, v)     # client values always win
                return


def restore_action_secrets(wa, module, config):
    """Restore masked (null/'') secret fields in an action's *config* from what is stored.

    Two levels, because a module has secrets at both. An ITEM's (matched by the injected
    ``_item_key``) so a web action run after a reload — datastore test_connection,
    list_databases — authenticates with the stored password instead of the masked placeholder.
    And the MODULE's own, which reach an action the same way and were left masked: the browser
    holds ``null`` for every secret it was sent, so an action that needs one received nothing
    and behaved as if it had never been configured. A GitHub token that silently does not
    apply looks exactly like a rate limit nobody can explain.
    """
    try:
        from lib.security import secret_manager  # noqa: PLC0415
        modules = wa._load_modules()
    except Exception:  # pylint: disable=broad-except
        return
    key = str(config.get('_item_key') or '').strip()
    for mk in (module, f'watchfuls.{module}'):
        mod = modules.get(mk)
        if not isinstance(mod, dict):
            continue
        # The module's own fields: everything that is not a collection of items.
        _own = {k: v for k, v in mod.items()
                if not k.startswith('__') and not isinstance(v, dict)}
        if _own:
            secret_manager.restore_sensitive(
                config, _own, keys=getattr(wa, '_secret_keys', frozenset()))
        if not key:
            continue
        for coll, items in mod.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            stored = items.get(key)
            if isinstance(stored, dict):
                secret_manager.restore_sensitive(
                    config, stored, keys=getattr(wa, '_secret_keys', frozenset()))
                return


def apply_cred_to_config(wa, config):
    """Overlay every referenced credential's fields onto an action's *config*, so a web action
    (test_connection, provision_token…) authenticates with the stored credential — not an inline
    secret.  Applies the primary ``cred_uid`` plus any secondary ``*_cred_uid`` (e.g. a
    credential-editor action's ``ssh_cred_uid``).  Mirrors ModuleBase.resolve_host; runs last so
    the credential wins."""
    cstore = getattr(wa, '_credentials_store', None)
    if cstore is None:
        return
    # Primary cred_uid first, then secondaries (ssh_cred_uid, …).
    uids = sorted((k for k in config if k == 'cred_uid' or k.endswith('_cred_uid')),
                  key=lambda k: k != 'cred_uid')
    for key in uids:
        uid = str(config.get(key) or '').strip()
        if not uid:
            continue
        try:
            cred = cstore.get(uid)
        except Exception:  # pylint: disable=broad-except
            continue
        if not cred or cred.get('enabled') is False:
            continue
        for k, v in (cred.get('data') or {}).items():
            if v not in (None, ''):
                config[k] = v


def merge_host_conn(wa, module, config, host_ctx):
    """Populate *config*'s connection fields from the bound host (its address and SSH profile),
    mirroring ModuleBase.resolve_host — so a web action runs on a host-bound check whose own
    connection fields are empty.  An explicit value on the check always wins; only blank/0/
    missing fields are filled.

    Reads ``__host_profile__`` straight from the module schema (not module_host_specs, which
    drops address-only profiles like datastore's 'db') so the address_field is filled even when
    its ``fields`` list is empty."""
    from lib.core.hosts.resolve import host_profile_specs  # noqa: PLC0415
    try:
        base = wa._modules_dir or os.path.normpath(
            os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, 'watchfuls'))
        with open(os.path.join(base, module, 'schema.json'), encoding='utf-8') as fh:
            hp = json.load(fh).get('__host_profile__')
    except Exception:  # pylint: disable=broad-except
        return
    specs = host_profile_specs(hp)
    address = host_ctx.get('address') or ''
    ssh = host_ctx.get('ssh') or {}
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        address_field = spec.get('address_field')
        # The address_field is filled from the host address even when not listed in `fields`
        # (e.g. datastore 'host', web 'url' stay visible/editable) — only when the check left it
        # blank, so a per-check override wins.
        if address_field and address and config.get(address_field) in (None, '', 0):
            config[address_field] = address
        for f in (spec.get('fields') or []):
            if config.get(f) not in (None, '', 0):
                continue              # the check's own value wins
            if f in ssh:
                config[f] = ssh[f]    # ssh_* ← host SSH profile


def apply_item_identities(wa, module, config):
    """Resolve the bound host and the referenced credential for the ITEMS inside *config*.

    The top-level pass beside this one answers for an action posted as one flat form. A
    discovery scoped to a parent item is not that shape: the UI posts
    ``{module scalars…, "<collection>": {"<key>": {…the item…}}}``, and the item is where
    ``host_uid`` and ``cred_uid`` live. Resolving only the top level left the action looking at
    an item with an empty address and no identity at all.

    That is what "you launch OID discovery and get nothing back" was: the SNMP server took its
    address from a bound host and its community from a credential, so the action saw
    ``host: ''`` and skipped the server before sending a single packet — while the checks on
    that same server ran fine, because the check path resolves per item (ModuleBase.resolve_host)
    and this one did not.

    Generic on purpose: every module whose discovery scopes to a parent item has the same
    shape, and the alternative is each of them reaching into the credential store on its own.

    Same precedence as the top-level pass, deliberately: the bound host only FILLS what the
    item left blank (a per-check override is why that field stays editable), while the
    credential is applied last and WINS. The two passes must not differ — an action that
    authenticated one way when posted as a form and another when posted as an item is the
    harder of the two bugs to see.
    """
    for coll_key, coll in list((config or {}).items()):
        if coll_key.startswith('__') or not is_item_collection(coll):
            continue
        for item in coll.values():
            if not isinstance(item, dict):
                continue
            host_ctx = resolve_host_ctx(wa, item)
            if host_ctx is not None:
                merge_host_conn(wa, module, item, host_ctx)
            # Last, so the credential wins over anything the host profile filled in.
            apply_cred_to_config(wa, item)


def cap_audit_lists(detail: dict, max_items: int) -> dict:
    """Bound every list a module put in its audit entry, in one place.

    A module's ``audit_detail`` hook decides WHAT is worth recording; how much of it one
    entry may hold is not its call.  The detail is stored as JSON in a single row and
    painted whole when the entry is opened, and what a module lists is unbounded by
    anything — the SNMP MIB import names every file it fetched, and a large repository has
    hundreds.  Without a ceiling here every module would have to remember one, and they
    would each pick a different number.

    Honours ``web_admin|audit_detail_max_items``, the same setting the database-maintenance
    entry uses, and says what it dropped: a list silently cut at N reads as a complete list
    of N, which is worse than no list at all.  ``max_items=0`` means **no ceiling** — every
    item is kept — which is what 0 means in every other ceiling in this panel.

    Returns a new dict; the caller's is untouched.
    """
    try:
        cap = max(0, int(max_items))
    except (TypeError, ValueError):
        return dict(detail)
    out = {}
    for key, val in (detail or {}).items():
        if not isinstance(val, list):
            out[key] = val
            continue
        if not cap:                     # 0 = no ceiling, not "no list"
            out[key] = list(val)
            continue
        out[key] = val[:cap]
        if len(val) > cap:
            out[f'{key}_truncated'] = len(val) - cap
    return out
