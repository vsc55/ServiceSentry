#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host registry routes: /api/v1/hosts (GET, POST), /api/v1/hosts/<uid> (PUT, DELETE).

A host carries an address plus per-protocol connection profiles (ssh, snmp, db,
http…) that watchful modules reuse, so a server's connection is defined once.

Access is gated by the dedicated ``servers_view`` / ``servers_edit`` /
``servers_delete`` permissions (the Servers tab).  Secret values inside the
profiles are masked on read and restored from
the stored value when the client omits them on write — the same scheme as
the module configuration.
"""

import copy
import json
import os
import re
import uuid

from flask import jsonify, request, session


def _coll_meta(modules_dir: str, mod: str, coll: str) -> dict:
    """The collection's schema meta (``__discovery_label_template__`` etc.) read
    from the module's schema.json, or ``{}``."""
    from lib.modules.credential_schemas import _watchfuls_dir  # noqa: PLC0415
    bare = str(mod).replace('watchfuls.', '')
    sp = os.path.join(_watchfuls_dir(modules_dir), bare, 'schema.json')
    try:
        with open(sp, encoding='utf-8') as fh:
            c = json.load(fh).get(coll)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def _format_item_label(tpl: str, host_name: str, item: dict, disc_field: str) -> str:
    """Format a check's label from the module's discovery template (e.g.
    ``"{host} - {name}"``): ``{host}`` = the (new) host name, ``{name}`` = the
    item's operative field (``__discovery_field__``, e.g. service/partition),
    ``{other}`` = any item field.  Mirrors the frontend ``_discoveryLabel``."""
    base = {'host': host_name or '', 'name': str(item.get(disc_field) or '') if disc_field else '',
            'display_name': '', 'type': ''}

    def _repl(m):
        k = m.group(1)
        if k in base:
            return base[k]
        v = item.get(k)
        return str(v) if v is not None else ''
    s = re.sub(r'\{(\w+)\}', _repl, tpl)
    s = re.sub(r'\s*-\s*$', '', s)
    s = re.sub(r'^\s*-\s*', '', s)
    return s.strip()

from lib.security import secret_manager
from lib.system import ssh_client
from lib.hosts import probe as host_probe
from lib.hosts.migrate import apply_to_modules, build_migration_plan

SYSTEM_USER = 'system'


def _delete_host_checks(wa, uid: str) -> int:
    """Delete every module check bound to host *uid*.  Single-bind items
    (``host_uid``) are removed; for a multi-host (cluster) check the host is just
    removed from ``host_uids`` (the check is deleted only if it had no other
    member).  Returns how many checks were deleted or unbound."""
    try:
        modules = wa._load_modules()
    except Exception:  # pylint: disable=broad-except
        return 0
    count = 0
    for mod, mcfg in modules.items():
        if str(mod).startswith('__') or not isinstance(mcfg, dict):
            continue
        for coll, items in list(mcfg.items()):
            if str(coll).startswith('__') or not isinstance(items, dict):
                continue
            for key in list(items.keys()):
                item = items[key]
                if not isinstance(item, dict):
                    continue
                hu = item.get('host_uids')
                if isinstance(hu, list) and any(str(x).strip() for x in hu):
                    remaining = [x for x in hu if str(x).strip() != str(uid)]
                    if len(remaining) != len(hu):
                        if remaining:
                            item['host_uids'] = remaining      # still a member of the cluster
                        else:
                            del items[key]                     # last member → drop the check
                        count += 1
                    continue
                if str(item.get('host_uid') or '') == str(uid):
                    del items[key]
                    count += 1
    if count:
        wa._save_modules(modules)
    return count


def _clone_host_checks(wa, src_uid: str, new_uid: str, label: str = '',
                       only_keys: set | None = None) -> int:
    """Duplicate every module check item bound to *src_uid* onto *new_uid*.

    When *only_keys* is given, only items whose key is in it are cloned/joined
    (the user picked them); ``None`` clones all bound checks.

    For each item whose ``host_uid`` is the source host, a deep copy is inserted
    under a fresh item UID pointing at the clone, so the new server inherits the
    same monitoring.  The clone's ``label`` is set to *label* (the new host's
    name) so checks read sensibly instead of falling back to the opaque item UID.

    For a multi-host (cluster) check the source is one MEMBER of, the clone's uid
    is ADDED to that same check's ``host_uids`` (the clone joins the cluster) —
    the check is not duplicated.

    Items are loaded decrypted and saved re-encrypted, so inline secrets survive.
    Returns the number of checks the clone was wired into.
    """
    try:
        modules = wa._load_modules()
    except Exception:  # pylint: disable=broad-except
        return 0
    count = 0
    for mod, mcfg in modules.items():
        if str(mod).startswith('__') or not isinstance(mcfg, dict):
            continue
        for coll, items in list(mcfg.items()):
            if str(coll).startswith('__') or not isinstance(items, dict):
                continue
            # The collection's label template (e.g. service_status "{host} - {name}")
            # lets the clone keep its per-item part (service/partition) with the NEW
            # host name; without one we just use the host name.
            _meta = _coll_meta(wa._modules_dir, mod, coll)
            _tpl = _meta.get('__discovery_label_template__')
            _disc = _meta.get('__discovery_field__')
            for ikey, item in list(items.items()):
                if not isinstance(item, dict):
                    continue
                if only_keys is not None and str(ikey) not in only_keys:
                    continue                       # the user did not pick this check
                # Multi-host (cluster) binding: the host is one member of a shared
                # check.  Don't duplicate the check — add the clone as a NEW member
                # of the SAME check so it joins the cluster (even if a stale
                # host_uid also matches).
                hu = item.get('host_uids')
                if isinstance(hu, list) and any(str(x).strip() for x in hu):
                    members = [str(x).strip() for x in hu]
                    if str(src_uid) in members and str(new_uid) not in members:
                        hu.append(new_uid)
                        count += 1
                    continue
                if str(item.get('host_uid') or '') != str(src_uid):
                    continue
                clone = copy.deepcopy(item)
                clone['host_uid'] = new_uid
                clone.pop('uid', None)
                # Re-format the label with the new host name (+ the item's own
                # operative field via the template), else just the host name.
                clone['label'] = (_format_item_label(_tpl, label, clone, _disc)
                                  if _tpl else label)
                items[str(uuid.uuid4())] = clone
                count += 1
    if count:
        wa._save_modules(modules)
    return count

_MOD_RE = re.compile(r'^[a-z][a-z0-9_]*$')

# Host fields that an 'add'-only user may NOT change (only the ``modules`` hint
# list may grow).  Secrets in ``profiles`` must already be restored before this
# comparison so an unchanged profile is not seen as edited.
_HOST_EDIT_FIELDS = ('name', 'address', 'kind', 'os', 'maintenance',
                     'tags', 'description', 'profiles')


def _only_modules_growth(old: dict, data: dict) -> bool:
    """True if *data* changes nothing on the host except adding entries to the
    ``modules`` list (no field edits, no module removals)."""
    for f in _HOST_EDIT_FIELDS:
        if data.get(f) != old.get(f):
            return False
    old_mods = set(old.get('modules') or [])
    new_mods = set(data.get('modules') or [])
    return old_mods <= new_mods


def _bare(module_key: str) -> str:
    return module_key.split('.')[-1]


def _probe_host_record(wa, body):
    """Build a decrypted host record for testing from the request.

    A stored host (by ``host_uid``) merged with the posted ``_host`` draft;
    masked secrets in the draft are restored from storage.  Maintenance is
    forced off so an explicit test always runs.
    """
    store = getattr(wa, '_hosts_store', None)
    uid = str(body.get('host_uid') or '').strip()
    stored = store.get(uid, decrypt=True) if (store and uid) else None
    draft = body.get('_host') if isinstance(body.get('_host'), dict) else None
    record = dict(stored) if stored else {}
    if draft:
        record['address'] = draft.get('address', record.get('address', ''))
        record['kind'] = draft.get('kind', record.get('kind', 'local'))
        record['os'] = draft.get('os', record.get('os', 'auto'))
        profiles = {p: dict(f or {}) for p, f in (draft.get('profiles') or {}).items()}
        if stored:
            secret_manager.restore_sensitive(profiles, stored.get('profiles') or {},
                                             keys=wa._secret_keys)
        if profiles:
            record['profiles'] = profiles
    record.setdefault('profiles', {})
    record['uid'] = uid or '__probe__'
    record['maintenance'] = False
    # Resolve a referenced credential into the ssh profile so the probe/test
    # uses the credential's identity (not the stored inline secret) — the same
    # overlay resolve_host applies at runtime.
    ssh = record['profiles'].get('ssh') or {}
    cred_uid = str(ssh.get('cred_uid') or '').strip()
    if cred_uid:
        from lib.stores.credentials import apply_credential, SSH_CRED_FIELDS  # noqa: PLC0415
        cstore = getattr(wa, '_credentials_store', None)
        cred = cstore.get(cred_uid) if cstore is not None else None
        base = {k: v for k, v in ssh.items() if k not in SSH_CRED_FIELDS}
        record['profiles']['ssh'] = apply_credential(base, cred)
    return record


def _restore_check_secrets(wa, bare_module, coll, key, fields):
    """Restore masked (null/'') secret fields in a check's *fields* from the
    stored module-config item, so a test run AFTER a reload (when the UI only
    holds masked secrets) uses the real, stored values instead of empties."""
    if not isinstance(fields, dict):
        return
    modules = wa._load_modules()
    for mk in (bare_module, f'watchfuls.{bare_module}'):
        mod = modules.get(mk)
        items = mod.get(coll) if isinstance(mod, dict) else None
        stored = items.get(key) if isinstance(items, dict) else None
        if isinstance(stored, dict):
            secret_manager.restore_sensitive(fields, stored, keys=wa._secret_keys)
            return


def _apply_check_cred(wa, fields):
    """Overlay a check's referenced credential (``cred_uid``) onto its *fields*
    so a host-bound check test authenticates with the credential — not the
    restored stored inline secret.  Returns *fields* (possibly a new dict)."""
    uid = str((fields or {}).get('cred_uid') or '').strip()
    if not uid:
        return fields
    cstore = getattr(wa, '_credentials_store', None)
    cred = cstore.get(uid) if cstore is not None else None
    from lib.stores.credentials import apply_credential  # noqa: PLC0415
    return apply_credential(fields, cred)


def _checks_for_host(wa, uid):
    """Grouped ``{(bare_module, collection): {key: item}}`` for every check in
    the module configuration bound to *uid* (used when the client doesn't send the list)."""
    modules = wa._load_modules()
    grouped = {}
    for mod_key, mod_cfg in modules.items():
        if not isinstance(mod_cfg, dict):
            continue
        bare = _bare(mod_key)
        if not _MOD_RE.match(bare):
            continue
        for coll, items in mod_cfg.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            for key, item in items.items():
                if isinstance(item, dict) and item.get('host_uid') == uid:
                    grouped.setdefault((bare, coll), {})[key] = item
    return grouped


def _host_statuses(wa):
    """Return ``{host_uid: 'ok'|'error'|'warning'}`` derived from the daemon's
    status file and the host_uid binding of each check in the module configuration.

    The check status is binary (True = OK) but a non-OK result carries a severity
    ('warning' for an aviso, else 'error'), so a host is:
      * ``error``   — at least one enabled check reports a hard (error) failure;
      * ``warning`` — no hard errors, but at least one check is a warning-severity
                      failure, OR it has enabled checks none of which has a status
                      yet (the daemon hasn't evaluated them — newly added / pending);
      * ``ok``      — it has enabled checks and every evaluated one is OK.
    Hosts with no enabled checks are absent (the column shows a neutral dash).
    Maintenance is NOT folded in here — the UI shows it as an override.
    """
    status_raw = wa._read_check_status()

    def _check_info(mod_key, check_key):
        """The recorded (status, severity) for a check, trying full and bare keys."""
        for mk in (mod_key, _bare(mod_key)):
            mod = status_raw.get(mk)
            if isinstance(mod, dict) and check_key in mod:
                info = mod.get(check_key)
                if isinstance(info, dict):
                    return info.get('status'), (info.get('severity') or '')
                return None, ''
        return '__absent__', ''

    modules = wa._load_modules()
    agg = {}   # uid -> {'has_error', 'has_warn', 'known', 'total'}
    for mod_key, mod_cfg in modules.items():
        if not isinstance(mod_cfg, dict):
            continue
        for coll, items in mod_cfg.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            for check_key, item in items.items():
                if not isinstance(item, dict):
                    continue
                uid = item.get('host_uid')
                if not uid or item.get('enabled') is False:
                    continue
                a = agg.setdefault(uid, {'has_error': False, 'has_warn': False,
                                         'known': 0, 'total': 0})
                a['total'] += 1
                st, sev = _check_info(mod_key, check_key)
                if st == '__absent__':
                    continue
                a['known'] += 1
                if st is not True:
                    if sev == 'warning':
                        a['has_warn'] = True
                    else:
                        a['has_error'] = True

    out = {}
    for uid, a in agg.items():
        if a['total'] == 0:
            continue
        if a['has_error']:
            out[uid] = 'error'
        elif a['has_warn'] or a['known'] == 0:
            out[uid] = 'warning'
        else:
            out[uid] = 'ok'
    return out


def _host_bound_modules(wa):
    """Return ``{host_uid: {bare_module: any_check_enabled}}`` — which modules
    have checks bound to each host and whether any of them is enabled."""
    modules = wa._load_modules()
    out = {}
    for mod_key, mod_cfg in modules.items():
        if not isinstance(mod_cfg, dict):
            continue
        bare = _bare(mod_key)
        for coll, items in mod_cfg.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            for item in items.values():
                if not isinstance(item, dict):
                    continue
                uid = item.get('host_uid')
                if not uid:
                    continue
                mods = out.setdefault(uid, {})
                mods[bare] = mods.get(bare, False) or (item.get('enabled') is not False)
    return out


def _create_unique_host(store, name, candidate, actor):
    """Create a host, suffixing the name on collision.  Returns the uid or None."""
    base = (name or candidate.get('address') or 'host').strip() or 'host'
    profiles = candidate.get('profiles', {})
    body = {'name': base, 'address': candidate.get('address', ''),
            # A migrated connection that carries an SSH tunnel is a remote host.
            'kind': 'remote' if profiles.get('ssh') else 'local',
            'profiles': profiles}
    for attempt in (base, f"{base} ({candidate.get('address', '')})",
                    *[f"{base}-{i}" for i in range(2, 12)]):
        body['name'] = attempt.strip()
        uid = store.create(body, actor=actor)
        if uid:
            return uid
    return None
