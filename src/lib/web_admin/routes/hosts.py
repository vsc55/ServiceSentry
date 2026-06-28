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
    from lib.credential_schemas import _watchfuls_dir  # noqa: PLC0415
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

from lib import secret_manager, ssh_client
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


def register(app, wa):
    login_required = wa._login_required

    def _store():
        return getattr(wa, '_hosts_store', None)

    def _can_edit_body_host():
        """Edit gate for the test endpoints — allow the global ``servers_edit``
        or a per-server ``server.{uid}.edit`` when the body targets an existing
        host (a new draft has no uid, so it needs the global permission)."""
        uid = str((request.get_json(silent=True) or {}).get('uid') or '').strip()
        return wa._has_server_permission(uid, 'edit')

    @app.route('/api/v1/hosts', methods=['GET'])
    @login_required
    def api_get_hosts():
        """List hosts the current user may view (secrets masked).

        Users with the global ``servers_view`` see every host; otherwise only
        hosts for which they hold a ``server.{uid}.view`` per-server permission.
        """
        perms = wa._get_session_permissions()
        has_global_view = 'servers_view' in perms
        has_any_view = has_global_view or any(
            p.startswith('server.') and p.endswith('.view') for p in perms)
        if not has_any_view:
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'hosts': []})
        hosts = secret_manager.mask_sensitive(store.list(decrypt=True), wa._secret_keys)
        if not has_global_view:
            hosts = [h for h in hosts if f"server.{h.get('uid')}.view" in perms]
        statuses = _host_statuses(wa)
        bound = _host_bound_modules(wa)
        for h in hosts:
            uid = h.get('uid')
            h['status'] = statuses.get(uid, '')
            mods = bound.get(uid, {})
            # Total = modules the host carries (its saved list ∪ any with a bound
            # check); active = those with at least one enabled check.
            total = set(h.get('modules') or []) | set(mods)
            h['modules_total'] = len(total)
            h['modules_active'] = sum(1 for m in total if mods.get(m))
        return jsonify({'hosts': hosts})

    @app.route('/api/v1/hosts/<uid>/status', methods=['GET'])
    @login_required
    def api_host_status(uid):
        """Latest recorded results (from the daemon's status.json) for every
        check bound to this host — shown in the server modal's "Latest data" tab.

        Each entry: ``{module, key, name, ok, message, data, ts}``.  Derived keys
        (e.g. ram_swap ``<uid>_ram``) are matched to their base bound item.
        """
        if not wa._has_server_permission(uid, 'view'):
            return jsonify({'error': wa._t('access_denied')}), 403
        # Bound items per bare module: {bare: {item_key: label}}.
        bound: dict = {}
        for (bare, _coll), items in _checks_for_host(wa, uid).items():
            for k, item in items.items():
                bound.setdefault(bare, {})[k] = str((item or {}).get('label') or '').strip()
        # Current live state (from the check_state DB table).
        status_raw = wa._read_check_status()
        # Index the history once, grouped by bare module, for the fallback when a
        # check has no live status (e.g. the host is in maintenance, so its live
        # records were purged).
        hist_by_mod: dict = {}
        hist_store = getattr(wa, '_history', None)
        if hist_store is not None:
            try:
                for s in hist_store.get_index():
                    hist_by_mod.setdefault(s.get('module'), []).append(s)
            except Exception:  # pylint: disable=broad-except
                pass

        def _matches(skey, keys):
            """Map a (possibly derived) result key to its bound base item key."""
            base = skey if skey in keys else skey.rsplit('_', 1)[0]
            return base if base in keys else None

        results = []
        for bare, keys in bound.items():
            covered = set()
            # 1) Live values from status.json.
            mod_status = status_raw.get(bare)
            if not isinstance(mod_status, dict):
                mod_status = status_raw.get(f'watchfuls.{bare}')
            if isinstance(mod_status, dict):
                for skey, info in mod_status.items():
                    if not isinstance(info, dict):
                        continue
                    base = _matches(skey, keys)
                    if base is None:
                        continue
                    data = info.get('other_data') if isinstance(info.get('other_data'), dict) else {}
                    name = str(data.get('name') or '').strip() or keys.get(base) or skey
                    ok = info.get('status') is True
                    sev = (info.get('severity') or '').lower()
                    results.append({
                        'module': bare, 'key': skey, 'name': name,
                        'ok': ok,
                        'level': 'ok' if ok else ('warning' if sev == 'warning' else 'error'),
                        'message': info.get('message', ''),
                        'data': data, 'ts': info.get('ts', ''),
                        'source': 'live',
                    })
                    covered.add(skey)
            # 2) History fallback for series with no live value.
            for s in hist_by_mod.get(bare, []):
                skey = s.get('key')
                if skey in covered:
                    continue
                base = _matches(skey, keys)
                if base is None:
                    continue
                data = s.get('last_data') if isinstance(s.get('last_data'), dict) else {}
                name = str(data.get('name') or '').strip() or keys.get(base) or skey
                _ok = s.get('last_status') is True
                results.append({
                    'module': bare, 'key': skey, 'name': name,
                    'ok': _ok,
                    'level': 'ok' if _ok else 'error',   # history keeps no severity
                    'message': data.get('message', '') if isinstance(data, dict) else '',
                    'data': data, 'ts': s.get('last_ts', ''),
                    'source': 'history',
                })
                covered.add(skey)
        results.sort(key=lambda r: (r['module'], r['name']))
        return jsonify({'results': results})

    @app.route('/api/v1/hosts', methods=['POST'])
    @login_required
    def api_create_host():
        """Create a host."""
        if 'servers_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        data, err = wa._require_json()
        if err:
            return err
        if not str(data.get('name') or '').strip():
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        uid = store.create(data, actor=session.get('username', SYSTEM_USER))
        if not uid:
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        wa._audit('host_created', detail={
            'uid': uid, 'name': data.get('name'),
            'address': data.get('address', ''),
            'kind': data.get('kind', 'local'),
            'os': data.get('os', 'auto'),
            'maintenance': bool(data.get('maintenance')),
            'profiles': sorted((data.get('profiles') or {}).keys()),
        })
        return jsonify({'ok': True, 'uid': uid})

    @app.route('/api/v1/hosts/<uid>/clone', methods=['POST'])
    @login_required
    def api_clone_host(uid):
        """Clone a host: duplicate the stored host (all profiles + secrets) under a
        NEW uid, overriding name/address from the request.  The source is read
        DECRYPTED and re-created, so inline profile secrets (ssh_password,
        ssh_key_string…) are preserved (and re-encrypted) instead of being lost as
        they would in a client-side copy of the masked data."""
        if 'servers_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        src = store.get(uid, decrypt=True)
        if src is None:
            return jsonify({'error': wa._t('host_not_found')}), 404
        body, err = wa._require_json()
        if err:
            return err
        data = copy.deepcopy(src)              # deep copy: we mutate nested profiles
        data.pop('uid', None)
        data['name'] = str((body or {}).get('name') or '').strip() \
            or f"{src.get('name', '')} (copia)"
        if 'address' in (body or {}):
            data['address'] = str(body.get('address') or '').strip()
        # A clone is a DIFFERENT machine → let the OS auto-detect rather than
        # inheriting the source's (possibly wrong) value.
        data['os'] = 'auto'
        # The cluster-node identity (which Proxmox node this host IS) is unique to
        # the machine — a clone is a different node, so blank it.
        for _prof in (data.get('profiles') or {}).values():
            if isinstance(_prof, dict):
                _prof.pop('node', None)
        if not data['name']:
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        new_uid = store.create(data, actor=session.get('username', SYSTEM_USER))
        if not new_uid:
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        # Duplicate the source host's module checks onto the clone.  When the
        # client sends a ``checks`` list, only those item keys are cloned (the
        # user picked them in the modal); absent → clone all.
        _sel = (body or {}).get('checks')
        only_keys = set(str(k) for k in _sel) if isinstance(_sel, list) else None
        checks_cloned = _clone_host_checks(wa, uid, new_uid, label=data['name'],
                                           only_keys=only_keys)
        wa._audit('host_cloned', detail={
            'uid': new_uid, 'source_uid': uid, 'name': data['name'],
            'address': data.get('address', ''), 'checks_cloned': checks_cloned,
        })
        return jsonify({'ok': True, 'uid': new_uid, 'checks_cloned': checks_cloned})

    @app.route('/api/v1/hosts/<uid>', methods=['PUT'])
    @login_required
    def api_update_host(uid):
        """Update a host.  Masked (null/'') secrets are restored from the
        stored value so the client never has to resend them."""
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        old = store.get(uid, decrypt=True)
        if old is None:
            return jsonify({'error': wa._t('host_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        # Restore secrets the client masked out (profiles only carry secrets).
        # Done before authorization so an unchanged profile isn't seen as edited.
        if isinstance(data.get('profiles'), dict):
            secret_manager.restore_sensitive(
                data['profiles'], old.get('profiles') or {}, keys=wa._secret_keys)
        # Full edit, or — for an 'add'-only user — a change limited to registering
        # additional monitored modules (the host's ``modules`` hint list), which
        # is how adding a check to a server touches the host record.
        if not wa._has_server_permission(uid, 'edit'):
            if not (wa._has_server_permission(uid, 'add')
                    and _only_modules_growth(old, data)):
                return jsonify({'error': wa._t('access_denied')}), 403
        if not store.update(uid, data, actor=session.get('username', SYSTEM_USER)):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        # Field-level diff (secrets masked) — same convention as config/modules.
        _diffable = ('name', 'address', 'kind', 'os', 'maintenance', 'tags',
                     'description', 'profiles', 'modules')
        changes = wa._diff_dicts(
            {k: old.get(k) for k in _diffable},
            {k: data.get(k) for k in _diffable},
            sensitive=wa._secret_keys,
        )
        wa._audit('host_updated', detail={
            'uid': uid, 'name': data.get('name'), 'changes': changes,
        })
        return jsonify({'ok': True})

    @app.route('/api/v1/hosts/test_ssh', methods=['POST'])
    @login_required
    def api_test_host_ssh():
        """Probe the SSH connection for a (remote) host without saving it.

        Body: ``{address, profiles:{ssh:{...}}, uid?}``.  When a secret field is
        masked (null/'') and ``uid`` is given, it is restored from the stored
        host so the user need not re-enter the password/key to test.
        """
        if not _can_edit_body_host():
            return jsonify({'error': wa._t('access_denied')}), 403
        if not ssh_client.HAS_PARAMIKO:
            return jsonify({'ok': False,
                            'message': 'paramiko is not installed (pip install paramiko)'})
        data, err = wa._require_json()
        if err:
            return err
        ssh = dict((data.get('profiles') or {}).get('ssh') or {})
        uid = str(data.get('uid') or '').strip()
        cred_uid = str(ssh.get('cred_uid') or '').strip()
        if cred_uid:
            # A reusable credential supplies the identity: drop any inline
            # user/auth/secret (so a stale value can't win) and overlay the
            # credential — exactly what resolve_host does at runtime.  The
            # stored host's inline secret must NOT be restored here, or a wrong
            # credential would be tested with the host's old correct password.
            from lib.stores.credentials import apply_credential, SSH_CRED_FIELDS  # noqa: PLC0415
            cstore = getattr(wa, '_credentials_store', None)
            cred = cstore.get(cred_uid) if cstore is not None else None
            ssh = apply_credential({k: v for k, v in ssh.items() if k not in SSH_CRED_FIELDS}, cred)
        else:
            # Inline edit flow: restore masked secrets from the stored host so
            # the user need not re-type the password/key just to test.
            store = _store()
            if store is not None and uid:
                stored = store.get(uid, decrypt=True) or {}
                stored_ssh = (stored.get('profiles') or {}).get('ssh') or {}
                for k in ('ssh_password', 'ssh_key_string'):
                    if ssh.get(k) in (None, '') and stored_ssh.get(k):
                        ssh[k] = stored_ssh[k]
        ok, msg, os_found = ssh_client.test_connection(
            address=data.get('address', ''),
            port=ssh.get('ssh_port') or 22,
            user=ssh.get('ssh_user', ''),
            password=ssh.get('ssh_password', ''),
            key_path=ssh.get('ssh_key', ''),
            key_string=ssh.get('ssh_key_string', ''),
            verify_host=bool(ssh.get('ssh_verify_host', False)),
            detect=True,
        )
        wa._audit('host_ssh_tested', detail={
            'uid': uid, 'address': data.get('address', ''), 'ok': ok, 'os': os_found,
        })
        return jsonify({'ok': ok, 'message': msg, 'os': os_found})

    def _item_name(items, key):
        """Friendly label for a result key: the item's ``label``, falling back to
        the base item for derived keys (e.g. ram_swap ``<uid>_ram``)."""
        for cand in (key, key.rsplit('_', 1)[0]):
            it = items.get(cand)
            if isinstance(it, dict) and str(it.get('label') or '').strip():
                return str(it['label']).strip()
        return ''

    def _run_checks(record, grouped):
        """Run each grouped check once on the host; return a flat result list."""
        store = host_probe.ProbeHostsStore(record, _store())
        db = getattr(wa, '_db_connector', None)
        out = []
        for (bare, coll), items in grouped.items():
            cfg = {f'watchfuls.{bare}': {coll: items}}
            try:
                results = host_probe.run_module_check(
                    bare, cfg, hosts_store=store, db=db, modules_dir=wa._modules_dir)
            except Exception as exc:  # pylint: disable=broad-except
                out.append({'module': bare, 'key': '', 'name': '', 'ok': False,
                            'message': str(exc)})
                continue
            for r in results:
                out.append({'module': bare, 'key': r['key'],
                            'name': _item_name(items, r['key']),
                            'ok': r['status'], 'message': r['message']})
        return out

    def _ssh_test(record):
        ssh = (record.get('profiles') or {}).get('ssh') or {}
        if not ssh_client.HAS_PARAMIKO:
            return {'ok': False, 'message': 'paramiko is not installed'}
        ok, msg, _os = ssh_client.test_connection(
            address=record.get('address', ''), port=ssh.get('ssh_port') or 22,
            user=ssh.get('ssh_user', ''), password=ssh.get('ssh_password', ''),
            key_path=ssh.get('ssh_key', ''), key_string=ssh.get('ssh_key_string', ''),
            verify_host=bool(ssh.get('ssh_verify_host', False)), detect=True)
        return {'ok': ok, 'message': msg}

    @app.route('/api/v1/hosts/test_check', methods=['POST'])
    @login_required
    def api_test_host_check():
        """Run ONE check once on the host and return its result(s)."""
        if not _can_edit_body_host():
            return jsonify({'error': wa._t('access_denied')}), 403
        body, err = wa._require_json()
        if err:
            return err
        module = _bare(str(body.get('module') or ''))
        if not _MOD_RE.match(module):
            return jsonify({'ok': False, 'message': 'invalid module'}), 400
        coll = str(body.get('collection') or 'list')
        key = str(body.get('key') or 'check')
        record = _probe_host_record(wa, body)
        fields = dict(body.get('fields') or {})
        # The modal sends cred_uid at the body level (the check's binding lives
        # outside its fields); fold it in so the credential is actually applied.
        if body.get('cred_uid') and not fields.get('cred_uid'):
            fields['cred_uid'] = body.get('cred_uid')
        _restore_check_secrets(wa, module, coll, key, fields)
        fields = _apply_check_cred(wa, fields)
        item = {**fields, 'host_uid': record['uid'], 'enabled': True}
        results = _run_checks(record, {(module, coll): {key: item}})
        ok = bool(results) and all(r['ok'] for r in results)
        wa._audit('host_test_check', detail={
            'uid': record['uid'], 'name': record.get('name', ''),
            'module': module, 'key': key, 'ok': ok,
            'results': [{'key': r['key'], 'ok': r['ok'], 'message': r['message']}
                        for r in results],
        })
        return jsonify({'ok': ok, 'results': results})

    @app.route('/api/v1/hosts/test', methods=['POST'])
    @login_required
    def api_test_host():
        """Full host test: SSH connection (if remote) + every bound check once."""
        if not _can_edit_body_host():
            return jsonify({'error': wa._t('access_denied')}), 403
        body, err = wa._require_json()
        if err:
            return err
        record = _probe_host_record(wa, body)
        out = {'ssh': None, 'results': []}
        # A module-scoped test (no_ssh) skips the SSH connection check.
        if str(record.get('kind') or '').lower() == 'remote' and not body.get('no_ssh'):
            out['ssh'] = _ssh_test(record)

        # Checks: explicit list from the modal, else everything bound in the module configuration.
        grouped = {}
        checks = body.get('checks')
        if isinstance(checks, list):
            for c in checks:
                bare = _bare(str(c.get('module') or ''))
                if not _MOD_RE.match(bare):
                    continue
                coll = str(c.get('collection') or 'list')
                key = str(c.get('key') or '') or f'check{len(grouped)}'
                fields = dict(c.get('fields') or {})
                if c.get('cred_uid') and not fields.get('cred_uid'):
                    fields['cred_uid'] = c.get('cred_uid')
                _restore_check_secrets(wa, bare, coll, key, fields)
                fields = _apply_check_cred(wa, fields)
                grouped.setdefault((bare, coll), {})[key] = {
                    **fields, 'host_uid': record['uid'], 'enabled': True}
        else:
            grouped = _checks_for_host(wa, record['uid'])
            for _items in grouped.values():
                for _k in list(_items):
                    _items[_k] = _apply_check_cred(wa, _items[_k])

        out['results'] = _run_checks(record, grouped)
        out['ok'] = ((out['ssh'] is None or out['ssh']['ok'])
                     and all(r['ok'] for r in out['results']))
        passed = sum(1 for r in out['results'] if r['ok'])
        failed = [r for r in out['results'] if not r['ok']]
        wa._audit('host_tested', detail={
            'uid': record['uid'], 'name': record.get('name', ''),
            'ok': out['ok'],
            'ssh': (out['ssh'] or {}).get('ok'),
            'total': len(out['results']), 'passed': passed, 'failed': len(failed),
            # Per-check outcome so the audit shows exactly which check failed.
            'results': [{'module': r['module'], 'key': r['key'], 'ok': r['ok'],
                         'message': r['message']} for r in out['results']],
        })
        return jsonify(out)

    @app.route('/api/v1/hosts/<uid>', methods=['DELETE'])
    @login_required
    def api_delete_host(uid):
        """Delete a host."""
        if not wa._has_server_permission(uid, 'delete'):
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('host_not_found')}), 404
        old = store.get(uid, decrypt=False)
        if old is None or not store.delete(uid):
            return jsonify({'error': wa._t('host_not_found')}), 404
        # Optionally also delete the module checks bound to this host (the client
        # asks the user). Otherwise they are left (and read as inline).
        checks_deleted = 0
        if str(request.args.get('with_checks') or '').lower() in ('1', 'true', 'yes'):
            checks_deleted = _delete_host_checks(wa, uid)
        wa._audit('host_deleted', detail={
            'uid': uid, 'name': old.get('name', ''), 'address': old.get('address', ''),
            'checks_deleted': checks_deleted,
        })
        return jsonify({'ok': True, 'checks_deleted': checks_deleted})

    # ── Assisted migration: detect inline connections repeated across modules
    #    and propose collapsing them into shared hosts. ───────────────────────

    @app.route('/api/v1/hosts/migrate/preview', methods=['GET'])
    @login_required
    def api_migrate_preview():
        """Return the migration proposal (candidate hosts; secrets masked)."""
        if 'servers_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        modules = wa._load_modules()
        plan = build_migration_plan(modules, wa._modules_dir)
        return jsonify(secret_manager.mask_sensitive(plan, wa._secret_keys))

    @app.route('/api/v1/hosts/migrate/apply', methods=['POST'])
    @login_required
    def api_migrate_apply():
        """Create hosts for the accepted candidates and rewrite the checks.

        Body: ``{"accept": [{"id": <candidate id>, "name": <optional>}]}``.
        The plan is rebuilt server-side from the (decrypted) module configuration, so the
        client never supplies credentials — only which candidates to accept.
        """
        if 'servers_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        body, err = wa._require_json()
        if err:
            return err
        accept = body.get('accept') or []
        modules = wa._load_modules()
        plan = build_migration_plan(modules, wa._modules_dir)
        by_id = {c['id']: c for c in plan['candidates']}
        actor = session.get('username', SYSTEM_USER)

        applied, created = [], []
        for acc in accept:
            cand = by_id.get(acc.get('id'))
            if not cand:
                continue
            uid = _create_unique_host(store, acc.get('name'), cand, actor)
            if not uid:
                continue
            applied.append({'uid': uid, 'members': cand['members']})
            created.append({
                'uid': uid,
                'name': (acc.get('name') or cand.get('suggested_name') or '').strip(),
                'address': cand.get('address', ''),
                'members': len(cand['members']),
                'checks': [f"{m['module'].split('.')[-1]}/{m['key']}" for m in cand['members']],
            })

        if applied:
            apply_to_modules(modules, applied, wa._modules_dir)
            if not wa._save_modules(modules):
                return jsonify({'error': wa._t('save_file_error')}), 500
            wa._audit('hosts_migrated', detail={
                'hosts': len(created),
                'checks': sum(c['members'] for c in created),
                'created': [{k: c[k] for k in ('uid', 'name', 'address', 'checks')}
                            for c in created],
            })
        return jsonify({'ok': True, 'created': len(created),
                        'checks': sum(c['members'] for c in created)})
