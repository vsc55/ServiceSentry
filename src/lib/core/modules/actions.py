#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The configuration a watchful ACTION runs with, resolved the way a scheduled check would.

An action asked for from the UI (`/api/v1/modules/watchfuls/<module>/<action>`) is handed a
config from a form, and a form does not carry what a scheduled run has: the bound device's
address and SSH settings, the secrets the browser was never given, the credential the item
merely references. Each of those is filled in here, mirroring what ``ModuleBase.resolve_device``
does on the scheduler's side — because an action that behaves differently from the check it
belongs to is worse than no action at all.

Resolved TWICE, at two shapes: a flat form posted for the module, and the item nested under
its collection when a discovery is scoped to one — the item is where `device_uid` and `cred_uid`
live, so the second pass is not a nicety.

The one thing here that is not about the config going in is `cap_audit_lists`, which bounds
what the result may record. Same reason, other end: how much of its own output an action may
put in one audit entry is not the module's call.

Flask-free: it takes the panel object and a dict, and answers with a dict.
"""

from __future__ import annotations

import copy
import json
import os

from lib.security import secret_manager

from .items import is_item_collection


# ── watchful-action config resolution ────────────────────────────────────────────
# Flask-free config resolution/merge for /api/v1/modules/watchfuls/<module>/<action>: resolve the
# bound device (address + SSH, server-side), restore masked secrets, and overlay referenced
# credentials — mirroring what ModuleBase.resolve_device does for a scheduled check.
def resolve_device_ctx(wa, config):
    """Build a device-context dict for device-aware discovery, or None.

    Resolved server-side so SSH secrets never come from the client: a ``device_uid`` is looked
    up in the device registry (decrypted); a brand-new (unsaved) device may instead pass a
    ``_device`` draft, whose masked secrets are restored from the stored device when a ``device_uid``
    is also given."""
    from lib.core.devices.resolve import resolve_os  # noqa: PLC0415

    def _apply_ssh_cred(ssh):
        """Overlay a named SSH credential (ssh profile ``cred_uid``) — the device may reference
        the credential manager instead of inline secrets, so device-aware discovery must resolve
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

    def _ctx(address, kind, os_, profiles):
        is_remote = str(kind or 'local').strip().lower() == 'remote'
        # Web discovery can't probe a remote OS here → assume 'linux' for 'auto'.
        os_ = resolve_os(os_, is_remote, remote_auto='linux')
        # EVERY protocol profile travels, not only ssh. A device carries one profile per
        # protocol it speaks, and an action's connection fields may come from any of them —
        # an SNMP action needs the device's community exactly as an SSH one needs its key.
        # While only ssh was carried, a widened profile handed the action the address and
        # nothing else, which fails as "no answer from the device" rather than as "nobody
        # told me the community".
        profiles = {k: dict(v) for k, v in (profiles or {}).items() if isinstance(v, dict)}
        profiles['ssh'] = _apply_ssh_cred(profiles.get('ssh') or {})
        return {'address': address or '', 'kind': kind or 'local', 'os': os_,
                'ssh': profiles['ssh'], 'profiles': profiles}

    store = getattr(wa, '_devices_store', None)
    uid = str(config.get('device_uid') or '').strip()
    if not uid:
        # Multi-device (cluster) check: provision against the primary bound device.
        uids = config.get('device_uids')
        if isinstance(uids, list):
            uid = next((str(u).strip() for u in uids if str(u).strip()), '')
    stored = store.get(uid, decrypt=True) if (store and uid) else None
    draft = config.get('_device') if isinstance(config.get('_device'), dict) else None

    if draft:
        profiles = {k: dict(v) for k, v in (draft.get('profiles') or {}).items()
                    if isinstance(v, dict)}
        # A draft may carry the ssh profile flat (older callers) instead of under `profiles`.
        if not profiles.get('ssh') and isinstance(draft.get('ssh'), dict):
            profiles['ssh'] = dict(draft['ssh'])
        if stored:
            # Restore every secret the client masked out, in every protocol — by the same
            # field-name rule the device store itself uses, so a module's own secret field
            # (an SNMP community, a token) is restored without core naming it.
            secret_manager.restore_sensitive(
                profiles, stored.get('profiles') or {},
                keys=getattr(wa, '_secret_keys', None) or secret_manager.ENCRYPT_KEYS)
        return _ctx(draft.get('address') or (stored or {}).get('address'),
                    draft.get('kind') or (stored or {}).get('kind'),
                    draft.get('os') or (stored or {}).get('os'), profiles)
    if stored:
        return _ctx(stored.get('address'), stored.get('kind'), stored.get('os'),
                    stored.get('profiles') or {})
    return None


# ── who may have stored secrets filled in ────────────────────────────────────────
# Read-only actions are open to anyone with ``modules_view``, and every helper below fills
# the config with something the caller never sent: the stored item's fields and secrets, the
# bound device's address and SSH, a credential's identity. Each of those is safe only while
# the request cannot also choose WHERE the action connects — and the client's own values win
# everywhere below, by design, because they are what an editor is testing. So before any of
# it runs, the config is confined to what this caller may change.
_DEVICE_KEYS = ('device_uid', 'device_uids', '_device')


def _is_cred_key(key) -> bool:
    return key == 'cred_uid' or str(key).endswith('_cred_uid')


def _device_binding(item) -> str:
    """The device an item's device context resolves to (``device_uid``, else the first
    ``device_uids`` member) — the same choice :func:`resolve_device_ctx` makes."""
    if not isinstance(item, dict):
        return ''
    uid = str(item.get('device_uid') or '').strip()
    if uid:
        return uid
    uids = item.get('device_uids')
    if isinstance(uids, list):
        return next((str(u).strip() for u in uids if str(u).strip()), '')
    return ''


def _stored_item(modules, module, key, coll=None):
    """The stored item *key* of *module* (in *coll*, or the first collection holding it)."""
    for mk in (module, f'watchfuls.{module}'):
        mod = modules.get(mk)
        if not isinstance(mod, dict):
            continue
        for c, items in mod.items():
            if c.startswith('__') or not isinstance(items, dict):
                continue
            if coll is not None and c != coll:
                continue
            stored = items.get(key)
            if isinstance(stored, dict):
                return stored
    return None


def confine_action_config(wa, module, config) -> dict:
    """Reduce an action's *config* to what the caller may point at stored secrets.

    Mutates *config* in place and answers ``{'item_secrets': bool, 'module_secrets': bool}``
    — whether the stored item's and the module's own secrets may then be filled in.

    - A stored item (``_item_key``) the caller may not EDIT (module edit, edit on the device it
      is bound to, or edit on its cluster) runs exactly as saved: the config is rebuilt from
      the stored item plus the client's ``_control`` keys. A viewer refreshing a module page
      sends the stored item anyway, so nothing they can see changes — but a ``host`` of their
      own no longer travels with the item's token.
    - A device the request names (``device_uid``/``device_uids``/``_device``) supplies its
      address and secrets only to a caller who may edit that device. Otherwise, when it is the
      device the stored item is bound to, the item runs as saved; when it is not, the device
      keys are dropped.
    - A caller with no write right in the request at all (no module edit, no editable item, no
      editable device) gets no stored secret: credentials and device drafts are dropped.
    """
    try:
        modules = wa._load_modules() or {}
    except Exception:  # pylint: disable=broad-except
        modules = {}
    try:
        perms = wa._get_session_permissions()
    except Exception:  # pylint: disable=broad-except
        perms = frozenset()
    can_module = wa._has_module_permission(module, 'edit')

    def can_device(uid):
        return bool(uid) and wa._has_server_permission(uid, 'edit')

    def item_editable(item, ikey):
        if can_module or can_device(str(item.get('device_uid') or '').strip()):
            return True
        if isinstance(item.get('device_uids'), list):
            cl = str(item.get('uid') or '').strip() or ikey
            return 'clusters_edit' in perms or f'cluster.{cl}.edit' in perms
        return False

    def as_stored(item):
        ctrl = {k: v for k, v in config.items()
                if str(k).startswith('_') and k != '_device'}
        config.clear()
        config.update(copy.deepcopy(item))
        config.update(ctrl)
        return {'item_secrets': True, 'module_secrets': True}

    def strip(item, creds):
        for k in _DEVICE_KEYS:
            item.pop(k, None)
        if creds:
            for k in [k for k in item if _is_cred_key(k)]:
                item.pop(k, None)

    key = str(config.get('_item_key') or '').strip()
    stored = _stored_item(modules, module, key) if key else None
    if stored is not None and not item_editable(stored, key):
        return as_stored(stored)
    du = _device_binding(config)
    if du and not can_device(du):
        if stored is not None and du == _device_binding(stored):
            return as_stored(stored)
        strip(config, creds=False)
        du = ''
    writer = can_module or stored is not None or bool(du)
    if not writer:
        strip(config, creds=True)
    # The items nested under a collection carry their own binding and credential, which
    # apply_item_identities resolves — the same rules, one item at a time.
    for coll_key, coll in list(config.items()):
        if str(coll_key).startswith('_') or not is_item_collection(coll):
            continue
        for ik, item in list(coll.items()):
            if not isinstance(item, dict):
                continue
            ndu = _device_binding(item)
            if ndu and not can_device(ndu):
                nst = _stored_item(modules, module, ik, coll_key)
                if nst is not None and _device_binding(nst) == ndu:
                    coll[ik] = copy.deepcopy(nst)
                    continue
                strip(item, creds=False)
            if not writer:
                strip(item, creds=True)
    return {'item_secrets': stored is not None, 'module_secrets': can_module}


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


def restore_action_secrets(wa, module, config, *, module_level=True, item_level=True):
    """Restore masked (null/'') secret fields in an action's *config* from what is stored.

    Two levels, because a module has secrets at both. An ITEM's (matched by the injected
    ``_item_key``) so a web action run after a reload — datastore test_connection,
    list_databases — authenticates with the stored password instead of the masked placeholder.
    And the MODULE's own, which reach an action the same way and were left masked: the browser
    holds ``null`` for every secret it was sent, so an action that needs one received nothing
    and behaved as if it had never been configured. A GitHub token that silently does not
    apply looks exactly like a rate limit nobody can explain.

    *module_level* / *item_level* switch either level off — :func:`confine_action_config`
    decides which a caller is owed.
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
        if _own and module_level:
            secret_manager.restore_sensitive(
                config, _own, keys=getattr(wa, '_secret_keys', frozenset()))
        if not key or not item_level:
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
    credential-editor action's ``ssh_cred_uid``).  Mirrors ModuleBase.resolve_device; runs last so
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


def merge_device_conn(wa, module, config, device_ctx):
    """Populate *config*'s connection fields from the bound device (its address and the profile
    of EACH protocol the module declares), mirroring ModuleBase.resolve_device — so a web action
    runs on a device-bound check whose own connection fields are empty.  An explicit value on the
    check always wins; only blank/0/missing fields are filled.

    Each spec draws from its own protocol (``profiles[spec['key']]``), which is what
    ``resolve_device`` does for a scheduled check.  Filling every spec from the SSH profile was
    survivable only while ssh was the one profile with fields to give: the moment another
    protocol carries credentials — an SNMP community, a device's port — the action got the
    address and nothing else, and failed as if the device had not answered.

    Reads ``__device_profile__`` straight from the module schema (not module_device_specs, which
    drops address-only profiles like datastore's 'db') so the address_field is filled even when
    its ``fields`` list is empty."""
    from lib.core.devices.resolve import device_profile_specs  # noqa: PLC0415
    try:
        base = wa._modules_dir or os.path.normpath(
            os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, 'watchfuls'))
        with open(os.path.join(base, module, 'schema.json'), encoding='utf-8') as fh:
            hp = json.load(fh).get('__device_profile__')
    except Exception:  # pylint: disable=broad-except
        return
    specs = device_profile_specs(hp)
    address = device_ctx.get('address') or ''
    profiles = device_ctx.get('profiles')
    if not isinstance(profiles, dict):      # a caller that built the ctx by hand
        profiles = {'ssh': device_ctx.get('ssh') or {}}
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        address_field = spec.get('address_field')
        # The address_field is filled from the device address even when not listed in `fields`
        # (e.g. datastore 'host', web 'url' stay visible/editable) — only when the check left it
        # blank, so a per-check override wins.
        if address_field and address and config.get(address_field) in (None, '', 0):
            config[address_field] = address
        prof = profiles.get(spec.get('key'))
        prof = prof if isinstance(prof, dict) else {}
        # The device's identity for this protocol, when the action names none — the credential
        # itself is overlaid afterwards by apply_cred_to_config, so it still wins over the
        # inline values filled here, exactly as it does on the scheduler's side.
        if not str(config.get('cred_uid') or '').strip() and prof.get('cred_uid'):
            config['cred_uid'] = prof['cred_uid']
        for f in (spec.get('fields') or []):
            if config.get(f) not in (None, '', 0):
                continue              # the check's own value wins
            if f in prof and prof[f] not in (None, ''):
                config[f] = prof[f]   # ← this protocol's profile on the device


def apply_item_identities(wa, module, config):
    """Resolve the bound device and the referenced credential for the ITEMS inside *config*.

    The top-level pass beside this one answers for an action posted as one flat form. A
    discovery scoped to a parent item is not that shape: the UI posts
    ``{module scalars…, "<collection>": {"<key>": {…the item…}}}``, and the item is where
    ``device_uid`` and ``cred_uid`` live. Resolving only the top level left the action looking at
    an item with an empty address and no identity at all.

    That is what "you launch OID discovery and get nothing back" was: the SNMP server took its
    address from a bound device and its community from a credential, so the action saw
    ``device: ''`` and skipped the server before sending a single packet — while the checks on
    that same server ran fine, because the check path resolves per item (ModuleBase.resolve_device)
    and this one did not.

    Generic on purpose: every module whose discovery scopes to a parent item has the same
    shape, and the alternative is each of them reaching into the credential store on its own.

    Same precedence as the top-level pass, deliberately: the bound device only FILLS what the
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
            device_ctx = resolve_device_ctx(wa, item)
            if device_ctx is not None:
                merge_device_conn(wa, module, item, device_ctx)
            # Last, so the credential wins over anything the device profile filled in.
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
