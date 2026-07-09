#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free module-config operations — validation, per-item write authorization, UID
normalization, view helpers and host provisioning, extracted from
:mod:`lib.core.modules.routes`.

Everything here is Flask-free (no request/session/jsonify); the route owns request parsing,
secret restore, module-config persistence and audit.  Most functions are pure over plain
dicts and raise :class:`~lib.core.users.service.AdminOpError` on a violation.  The one
exception is :func:`sync_provisioned_hosts`, which *does* write — it provisions linked hosts
in another domain's store; that store is injected explicitly (not reached through ``wa``), so
the side-effect is visible in the signature rather than hidden Flask coupling.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
import uuid

from lib.core.users.service import AdminOpError

# Canonical UUID form, used to tell an opaque item key from a human-given one.
_UUID_RE = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# Collections that hold check items, keyed by the item UID. Nested collections
# (e.g. snmp's per-server ``checks``) are re-keyed recursively.
_ITEM_COLLECTIONS = ('list', 'servers')
_NESTED_ITEM_COLLECTIONS = ('checks',)


# ── view / validation ────────────────────────────────────────────────────────────
def visible_modules(all_data: dict, perms) -> dict:
    """The subset of *all_data* the user may view via per-module ``module.{name}.view``
    permissions (used when the user lacks the global ``modules_view``)."""
    return {n: c for n, c in all_data.items() if f'module.{n}.view' in perms}


def has_any_module_write(perms) -> bool:
    """True if *perms* carry any write capability that could authorize a module save —
    module-level, per-module, or a server/cluster permission that can authorize a
    host-bound check change.  Used to reject a no-write user before parsing the body."""
    return (
        'modules_edit' in perms or 'modules_add' in perms or 'modules_delete' in perms or
        'servers_add' in perms or 'servers_edit' in perms or
        'clusters_add' in perms or 'clusters_edit' in perms or 'clusters_delete' in perms or
        any(p.startswith('module.') and (p.endswith('.edit') or p.endswith('.add') or p.endswith('.delete'))
            for p in perms) or
        any(p.startswith('server.') and (p.endswith('.add') or p.endswith('.edit'))
            for p in perms) or
        any(p.startswith('cluster.') and (p.endswith('.add') or p.endswith('.edit') or p.endswith('.delete'))
            for p in perms)
    )


def validate_modules_shape(data: dict) -> None:
    """Every top-level value must be a module-config dict.  Raises on a malformed body."""
    if not all(isinstance(v, dict) for v in data.values()):
        raise AdminOpError('invalid_modules_data')


# ── per-item write authorization ─────────────────────────────────────────────────
def _is_item_collection(v) -> bool:
    """A module section holding items (``list``/``servers``/…) is dict-valued;
    module-level fields (enabled, threads, timeout, …) are scalars (bool/int),
    never dicts.  Items inside may be dicts or a bool shorthand
    (``"1.2.3.4": false`` = disabled), so the value *type* of items is not used
    to classify the section — only the section being a dict matters."""
    return isinstance(v, dict)


def _item_host_uid(o, n) -> str:
    """Host UID of an item from its new or old value (items can be non-dict
    bool shorthands, which carry no host binding)."""
    for it in (n, o):
        if isinstance(it, dict):
            hu = str(it.get('host_uid') or '').strip()
            if hu:
                return hu
    return ''


def _is_cluster_item(o, n) -> bool:
    """A cluster item is a multi-host-bound check — it carries ``host_uids`` (a
    list), unlike an ordinary single-bound (``host_uid``) or unbound check."""
    for it in (n, o):
        if isinstance(it, dict) and isinstance(it.get('host_uids'), list):
            return True
    return False


def _cluster_authorized(perms, action: str, uid: str = '') -> bool:
    """True if *perms* authorize *action* (add/edit/delete) on a cluster — via the
    global ``clusters_*`` flag or a per-cluster ``cluster.{uid}.{action}`` override."""
    if {'add': 'clusters_add', 'edit': 'clusters_edit',
            'delete': 'clusters_delete'}.get(action) in perms:
        return True
    return bool(uid) and f'cluster.{uid}.{action}' in perms


def _server_authorized(perms, action: str, host_uid: str) -> bool:
    """True if *perms* authorize *action* on server *host_uid* — via the global
    ``servers_*`` flag or a per-server ``server.{uid}.{action}`` override."""
    _g = {'view': 'servers_view', 'add': 'servers_add',
          'edit': 'servers_edit', 'delete': 'servers_delete'}
    if _g.get(action) in perms:
        return True
    return bool(host_uid) and f'server.{host_uid}.{action}' in perms


def authorize_module_write(name: str, old_mod, new_mod, perms) -> bool:
    """Authorize a change to module *name* for a user lacking global module-write.

    Host-bound item changes (items carrying ``host_uid``) may be authorized by
    per-server / global server permissions: adding an item needs server ``add``,
    modifying or removing one needs server ``edit``.  Module-level scalar changes
    and non-host-bound items still require the module permissions.
    """
    if old_mod == new_mod:
        return True
    if f'module.{name}.edit' in perms:
        return True
    is_new = old_mod is None
    is_removed = new_mod is None
    if is_new and 'modules_add' in perms:
        return True
    if is_removed and 'modules_delete' in perms:
        return True

    old_mod = old_mod if isinstance(old_mod, dict) else {}
    new_mod = new_mod if isinstance(new_mod, dict) else {}

    # Module-level (non-collection) scalar changes require module edit — except on
    # a brand-new module being scaffolded purely to hold host-bound items.
    if not is_new:
        old_s = {k: v for k, v in old_mod.items() if not _is_item_collection(v)}
        new_s = {k: v for k, v in new_mod.items() if not _is_item_collection(v)}
        for k in set(old_s) | set(new_s):
            if old_s.get(k) != new_s.get(k):
                return False

    # Authorize each added/removed/modified item by its host binding.
    coll_names = {k for k, v in old_mod.items() if _is_item_collection(v)} \
               | {k for k, v in new_mod.items() if _is_item_collection(v)}
    saw_change = False
    for coll in coll_names:
        old_items = old_mod.get(coll) if _is_item_collection(old_mod.get(coll)) else {}
        new_items = new_mod.get(coll) if _is_item_collection(new_mod.get(coll)) else {}
        for ik in set(old_items) | set(new_items):
            o, n = old_items.get(ik), new_items.get(ik)
            if o == n:
                continue
            saw_change = True
            if _is_cluster_item(o, n):
                # Multi-bind cluster check → its own clusters_* permissions (or a
                # per-cluster cluster.{uid}.{action} override), with a distinct
                # delete (removal) action.
                c_action = 'add' if o is None else ('delete' if n is None else 'edit')
                cl_uid = ((n or {}).get('uid') if isinstance(n, dict) else None) \
                    or ((o or {}).get('uid') if isinstance(o, dict) else None) or ik
                if not _cluster_authorized(perms, c_action, cl_uid):
                    return False
                continue
            hu = _item_host_uid(o, n)
            action = 'add' if o is None else 'edit'        # add new / modify|remove
            if not _server_authorized(perms, action, hu):
                return False
    # A change with no authorizable host-bound item diff (whole-module add/remove
    # with no host-bound items, or only scalar churn) is not server-authorizable.
    return saw_change


def authorize_modules_save(old_data: dict, data: dict, perms) -> None:
    """Authorize every changed module individually (for a user without global
    ``modules_edit``). Raises :class:`AdminOpError` (``access_denied``) on the first
    unauthorized change."""
    for name in set(old_data) | set(data):
        if not authorize_module_write(name, old_data.get(name), data.get(name), perms):
            raise AdminOpError('access_denied')


# ── UID normalization ────────────────────────────────────────────────────────────
def ensure_item_uids(data: dict) -> None:
    """Add a stable UUID to every module item that lacks one.

    Items live inside dict-valued sections of each module config (typically
    called ``list`` or ``servers``).  A UUID is generated only when absent so
    existing UIDs are never overwritten.
    """
    for module_cfg in data.values():
        if not isinstance(module_cfg, dict):
            continue
        for section_val in module_cfg.values():
            if not isinstance(section_val, dict):
                continue
            for item in section_val.values():
                if isinstance(item, dict) and 'uid' not in item:
                    item['uid'] = str(uuid.uuid4())


def _rekey_collection(coll: dict) -> dict:
    """Return *coll* re-keyed so each item's dict key equals its ``uid``
    (generated when absent); recurses into nested item collections."""
    out: dict = {}
    for old_key, item in coll.items():
        if not isinstance(item, dict):
            out[old_key] = item
            continue
        uid = str(item.get('uid') or '').strip() or str(uuid.uuid4())
        item['uid'] = uid
        # Preserve a human-readable old key as the editable label, so re-keying
        # to an opaque UID never loses the name (e.g. ups items keyed by name).
        if (not str(item.get('label') or '').strip()
                and old_key != uid and not _UUID_RE.match(str(old_key))):
            item['label'] = old_key
        for sub in _NESTED_ITEM_COLLECTIONS:
            sub_val = item.get(sub)
            if isinstance(sub_val, dict) and sub_val:
                item[sub] = _rekey_collection(sub_val)
        out[uid] = item
    return out


def rekey_items_by_uid(data: dict) -> None:
    """Re-key every check item (and nested check) by its ``uid`` in place.

    Makes the item's dict key equal its UID so each watchful's result key (the
    dict key it iterates) is the stable UID — the canonical relation used by
    status.json / check_state / history.
    """
    for module_cfg in data.values():
        if not isinstance(module_cfg, dict):
            continue
        for coll_name in _ITEM_COLLECTIONS:
            coll = module_cfg.get(coll_name)
            if isinstance(coll, dict) and coll:
                module_cfg[coll_name] = _rekey_collection(coll)


# ── credential / provisioning helpers ────────────────────────────────────────────
def strip_credential_fields(data: dict, modules_dir: str) -> None:
    """For items that reference a credential (``cred_uid``), drop the module's inline
    credential fields (e.g. web's auth_user/auth_password) so a stale user/secret can't
    linger — the credential supplies them at runtime.  Driven by discovery (per-module
    credential schemas), so it stays module-agnostic."""
    try:
        from lib.modules.discovery.credential_schemas import credential_schemas  # noqa: PLC0415
        cat = credential_schemas(modules_dir)
    except Exception:  # pylint: disable=broad-except
        return
    by_module: dict = {}
    for spec in cat.values():
        mod = spec.get('module')
        if mod and mod != '__core__':
            by_module.setdefault(mod, set()).update(
                f['name'] for f in (spec.get('fields') or []))
    if not by_module:
        return
    for mod_key, mod_cfg in data.items():
        if not isinstance(mod_cfg, dict):
            continue
        fields = by_module.get(mod_key.split('.')[-1])
        if not fields:
            continue
        for coll, items in mod_cfg.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            for item in items.values():
                if isinstance(item, dict) and str(item.get('cred_uid') or '').strip():
                    for f in fields:
                        item.pop(f, None)


def provision_host_decl(modules_dir: str, module_name: str) -> dict | None:
    """A module's ``__provision_host__`` declaration, if any (from schema.json).

    Generic, module-agnostic: a module may declare — in a collection's schema —
    that each item provisions a linked host from one of its address fields::

        "__provision_host__": {"address_field": "endpoint", "link_field": "endpoint_host_uid",
                               "name_template": "Endpoint: {label}", "collection": "list"}

    The core reads this by discovery; nothing here is specific to any module."""
    if not modules_dir or not module_name:
        return None
    try:
        path = os.path.join(modules_dir, module_name, 'schema.json')
        with open(path, encoding='utf-8') as fh:
            schema = json.load(fh)
    except (OSError, ValueError):
        return None
    for coll in schema.values():
        if isinstance(coll, dict) and isinstance(coll.get('__provision_host__'), dict):
            decl = dict(coll['__provision_host__'])
            decl.setdefault('collection', 'list')
            return decl
    return None


def sync_provisioned_hosts(hosts_store, modules_dir: str, data: dict, actor: str) -> list:
    """Auto-provision/link a host for every module item that declares one (mutates *data*
    in place).  **Writes** to *hosts_store* (the one persisting function here — the store is
    injected explicitly, not reached through ``wa``).

    Fully generic: driven by each module's ``__provision_host__`` schema declaration
    (see :func:`provision_host_decl`) — the core knows nothing about any specific module.  A
    module declares that its items provision a host from one of their address fields (a
    stable/floating endpoint address); this ensures a linked host (``address == that field``)
    and stamps its uid on the item's ``link_field``, syncing the address when it changes.
    Modelling the endpoint as a host lets any address module (ping/web/ssl_cert…) monitor it
    via the normal host binding.

    Idempotent: an item already linked (``link_field`` set) is reused by uid; an unlinked
    item first tries to ADOPT an existing host with the same deterministic name before
    creating one — so re-saving (before the new link round-trips to the client) never spawns
    duplicate hosts.

    Returns the list of links established this call
    (``[{module, collection, item, field, uid}]``) so the caller can round-trip them to the
    client (which holds no ``link_field`` for a just-created host).  Best-effort: failures are
    swallowed so they never block saving the config."""
    if hosts_store is None or not modules_dir:
        return []
    from lib.core.hosts.service import _create_unique_host  # noqa: PLC0415
    assignments: list = []
    for mod_key, mod_cfg in data.items():
        if not isinstance(mod_cfg, dict):
            continue
        decl = provision_host_decl(modules_dir, str(mod_key).split('.')[-1])
        if not decl:
            continue
        addr_f, link_f = decl.get('address_field'), decl.get('link_field')
        coll = decl.get('collection') or 'list'
        items = mod_cfg.get(coll)
        if not (addr_f and link_f and isinstance(items, dict)):
            continue
        name_tpl = decl.get('name_template') or (str(addr_f) + ': {label}')
        for key, item in items.items():
            if not isinstance(item, dict):
                continue
            addr = str(item.get(addr_f) or '').strip()
            if not addr:
                continue
            uid = str(item.get(link_f) or '').strip()
            try:
                host = hosts_store.get(uid) if uid else None
                if host:
                    if str(host.get('address') or '').strip() != addr:
                        hosts_store.update(uid, {**host, 'address': addr}, actor=actor)
                    continue
                hostname = name_tpl.format(label=item.get('label') or key, key=key)
                # Adopt an existing host with this deterministic name instead of
                # creating a duplicate (idempotent across re-saves / stale clients).
                existing = None
                try:
                    existing = hosts_store.get_by_name(hostname)
                except Exception:  # pylint: disable=broad-except
                    existing = None
                if existing and existing.get('uid'):
                    new_uid = existing['uid']
                    if str(existing.get('address') or '').strip() != addr:
                        hosts_store.update(new_uid, {**existing, 'address': addr}, actor=actor)
                else:
                    new_uid = _create_unique_host(
                        hosts_store, hostname, {'address': addr, 'profiles': {}}, actor)
                if new_uid:
                    item[link_f] = new_uid
                    assignments.append({'module': mod_key, 'collection': coll,
                                        'item': key, 'field': link_f, 'uid': new_uid})
            except Exception:  # pylint: disable=broad-except
                continue
    return assignments


# ── watchful-action config resolution ────────────────────────────────────────────
# Flask-free config resolution/merge for /api/v1/modules/watchfuls/<module>/<action>: resolve the
# bound host (address + SSH, server-side), restore masked secrets, and overlay referenced
# credentials — mirroring what ModuleBase.resolve_host does for a scheduled check.
def _resolve_host_ctx(wa, config):
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


def _restore_action_secrets(wa, module, config):
    """Restore masked (null/'') secret fields in an action's *config* from the stored
    module-config item (matched by the injected ``_item_key``), so a web action (e.g. datastore
    test_connection / list_databases) run AFTER a reload uses the real stored secret instead of
    the masked placeholder."""
    key = str(config.get('_item_key') or '').strip()
    if not key:
        return
    try:
        from lib.security import secret_manager  # noqa: PLC0415
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
                secret_manager.restore_sensitive(
                    config, stored, keys=getattr(wa, '_secret_keys', frozenset()))
                return


def _apply_cred_to_config(wa, config):
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


def _merge_host_conn(wa, module, config, host_ctx):
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


def build_module_widgets(modules_dir: str, status_raw: dict, modules_raw: dict, lang: str) -> dict:
    """Generic Overview-widget data: for every module declaring ``__overview_widget__``,
    call its ``Watchful.overview_widget(items, status, lang)`` hook and collect the result.
    The core stays module-agnostic — all domain logic/strings come from the module."""
    out: dict = {}
    try:
        from lib.modules.discovery.overview_widgets import overview_widgets_catalog  # noqa: PLC0415
        catalog = overview_widgets_catalog(modules_dir)
    except Exception:  # pylint: disable=broad-except
        return out
    if not catalog:
        return out
    parent = os.path.dirname(modules_dir or '')
    if parent and parent not in sys.path:
        sys.path.insert(0, parent)
    for mod_name in catalog:
        try:
            status = next((status_raw[k] for k in (f'watchfuls.{mod_name}', mod_name)
                           if isinstance(status_raw.get(k), dict)), {})
            cfg = next((modules_raw[k] for k in (f'watchfuls.{mod_name}', mod_name)
                        if isinstance(modules_raw.get(k), dict)), {})
            items = cfg.get('list') if isinstance(cfg.get('list'), dict) else {}
            cls = getattr(importlib.import_module(f'watchfuls.{mod_name}'), 'Watchful', None)
            fn = getattr(cls, 'overview_widget', None)
            if callable(fn):
                out[mod_name] = fn(items, status, lang) or {}
        except Exception:  # pylint: disable=broad-except
            continue
    return out
