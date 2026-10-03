#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free device domain logic — everything the device routes need that isn't HTTP.

Two kinds of function live here:

* pure read/transform helpers (``enrich_devices``, ``build_device_status``,
  ``build_clone_record``) — dicts in, dicts out; and
* the check-fan-out / status / probe-prep bookkeeping a device change implies (clone/delete a
  device's bound checks, per-device status summaries, device-record probing, secret restore and
  credential overlay).  These take the ``wa`` app object to reach the module config
  (``wa._load_modules`` / ``wa._save_modules``) and its stores, but carry **no Flask coupling**
  (no request/session/jsonify).

Device validation/normalization itself lives in :class:`~lib.core.devices.stores.devices.DevicesStore`.
"""

from __future__ import annotations

import copy
import json
import os
import re
import uuid

from lib.core.devices.resolve import device_uid_from_key
from lib.core.modules.facade import mutate_modules
from lib.security import secret_manager


def enrich_devices(devices: list, statuses: dict, bound: dict, reported: dict | None = None) -> list:
    """Annotate each device (in place) with ``status`` and module totals.  *statuses* is
    ``{uid: status}``; *bound* is ``{uid: {module: has_active_check}}``.  ``modules_total`` =
    the device's saved modules ∪ any with a bound check; ``modules_active`` = those with at
    least one enabled check.  Returns *devices*.

    *reported* is ``{uid: {os, vendor, model, brand}}`` — what each machine has SAID about
    itself (see ``infra.service.fleet_identity``). Three of those four land as they are: who
    made a box and which model it is are not settings, so there is nothing for them to argue
    with.

    ``os`` is the exception, and lands as ``os_auto`` ONLY where the device's own field is
    ``auto``. It is not the setting, it is the answer the setting stands for — a screen showing
    "auto" and nothing else is a screen keeping something it already knows to itself, and a
    screen showing the device's word over a setting somebody chose is worse than either.
    """
    for h in devices:
        uid = h.get('uid')
        said = (reported or {}).get(uid) or {}
        h['status'] = statuses.get(uid, '')
        h['os_auto'] = (str(said.get('os') or '')
                        if str(h.get('os') or 'auto').strip().lower() == 'auto' else '')
        h['vendor'] = str(said.get('vendor') or '')
        h['model'] = str(said.get('model') or '')
        h['brand'] = dict(said.get('brand') or {})
        mods = bound.get(uid, {})
        total = set(h.get('modules') or []) | set(mods)
        h['modules_total'] = len(total)
        h['modules_active'] = sum(1 for m in total if mods.get(m))
    return devices


def _row_of(skey: str, data: dict) -> str:
    """Which ROW of the item this result is about, or '' when the item is the whole answer.

    One item can produce many results — an SNMP device profile samples a table and files one
    per disk, per volume, per interface — and every one of them inherits the ITEM's label,
    because that is the only name the configuration holds. On a page that is already about
    that device the result is the device's name printed three hundred times, which says
    nothing at all: what somebody needs to read is "Drive 1", "/volume1", "eth0".

    Two sources, in order of how much they know:

    * ``_row`` in the recorded data — the name the module gave the row, as a person writes it
      ("Drive 1 (DX517-1)"). Underscore-prefixed like ``_attrs``: the recorders already treat
      that prefix as "about the result" rather than "a measurement of it";
    * the ``<item>/<detail>`` key, whose detail segment is the same thing with the spaces
      taken out — the fallback for a module that files composite keys without naming them.

    ``metrics`` is the sampler's word for "the item itself, not one of its rows", so it names
    no row and answers ''.
    """
    row = str((data or {}).get('_row') or '').strip()
    if row:
        return row
    detail = skey.split('/', 1)[1] if '/' in skey else ''
    return '' if detail in ('', 'metrics') else detail


def build_device_status(bound: dict, status_raw: dict, hist_by_mod: dict) -> list:
    """Build the device modal's "Latest data" rows: for every bound item (``bound`` =
    ``{bare_module: {item_key: label}}``) merge the live value from ``status_raw`` with a
    history fallback (``hist_by_mod`` = ``{bare_module: [series...]}``).  Derived result keys
    (e.g. ram_swap ``<uid>_ram``) are mapped back to their base bound item.  Sorted by
    ``(module, name)``."""
    def _matches(skey, keys):
        """Map a (possibly derived) result key to its bound base item key.

        Three shapes, tried in order of how specific they are:

        * the key IS the item (an inline check);
        * <item>/<detail> — the composite convention the rest of the product already
          speaks (history's check_label resolves it the same way): one item producing
          several rows, which is what an SNMP device profile does when it samples a table
          and files a row per interface, per volume, per disk;
        * <item>_<suffix> — the older derived-key shape (ram_swap's <uid>_ram).

        The middle one was missing, and its absence had no symptom worth noticing: the rows
        were recorded, charted and named correctly, and simply never reached the screen that
        was built to show them.
        """
        if skey in keys:
            return skey
        for base in (skey.split('/', 1)[0], skey.rsplit('_', 1)[0]):
            if base in keys:
                return base
        return None

    results = []
    for bare, keys in bound.items():
        covered = set()
        # Y qué ITEMS están dando parte ahora mismo, que no es lo mismo que qué claves. Un
        # `ram_swap` no escribe nada bajo su propia clave: escribe `<item>_ram` y `<item>_swap`.
        # Así que la clave desnuda `<item>` no tiene valor vivo nunca, y si alguna vez quedó una
        # serie suya en el historial —dos muestras fallidas de hace ocho horas, sin datos, de
        # cuando el chequeo aún no leía nada— el respaldo la daba por el estado de AHORA y la
        # máquina salía en rojo con sus dos medidas en verde al lado. Medido en la pantalla de
        # PVE01, que la flota daba por buena.
        #
        # El respaldo existe para el caso de verdad: una máquina en mantenimiento a la que le
        # podaron el estado vivo. Si el item habla, no hay nada que respaldar.
        vivos = set()
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
                vivos.add(base)
                data = info.get('other_data') if isinstance(info.get('other_data'), dict) else {}
                name = str(data.get('name') or '').strip() or keys.get(base) or skey
                row = _row_of(skey, data)
                ok = info.get('status') is True
                sev = (info.get('severity') or '').lower()
                results.append({
                    'module': bare, 'key': skey, 'name': name, 'row': row,
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
            if base is None or base in vivos:
                continue
            data = s.get('last_data') if isinstance(s.get('last_data'), dict) else {}
            name = str(data.get('name') or '').strip() or keys.get(base) or skey
            _ok = s.get('last_status') is True
            results.append({
                'module': bare, 'key': skey, 'name': name,
                'row': _row_of(skey, data),
                'ok': _ok,
                'level': 'ok' if _ok else 'error',   # history keeps no severity
                'message': data.get('message', '') if isinstance(data, dict) else '',
                'data': data, 'ts': s.get('last_ts', ''),
                'source': 'history',
            })
            covered.add(skey)
    # By row within a module, so a table of one device's disks reads Drive 1, Drive 2…
    # and not in whatever order the agent answered them.
    results.sort(key=lambda r: (r['module'], r.get('row') or '', r['name']))
    return results


def build_clone_record(src: dict, body: dict, member_fields) -> dict:
    """Build the record for cloning device *src*: deep-copy, drop the uid, override
    name/address from *body* (name falls back to ``"<name> (copia)"``), force ``os='auto'``
    (a clone is a different machine), and strip every per-node cluster-identity field
    (the legacy ``node`` plus each module's declared ``__member_field__`` in *member_fields*)
    from every profile.  Pure — the caller persists via the store."""
    body = body or {}
    data = copy.deepcopy(src)              # deep copy: we mutate nested profiles
    data.pop('uid', None)
    data['name'] = str(body.get('name') or '').strip() or f"{src.get('name', '')} (copia)"
    if 'address' in body:
        data['address'] = str(body.get('address') or '').strip()
    # A clone is a DIFFERENT machine → let the OS auto-detect rather than inheriting the
    # source's (possibly wrong) value.
    data['os'] = 'auto'
    # What ties the record to ONE machine does not travel either. `source`/`external_id` say
    # which asset of an importer this device IS: copied, the clone was "maintained by" that
    # importer (a rename answered 409) and two devices claimed one external key, so the next
    # import updated whichever it found first. `watch` marks rows (ports, disks) of the
    # source machine; the clone's rows are other cables. Audit stamps are the store's to set.
    for k in ('source', 'external_id', 'watch', 'created_at', 'updated_at', 'updated_by'):
        data.pop(k, None)
    # The per-node cluster identity (which node this device IS) is unique to the machine;
    # a clone is a different node, so blank it.
    strip = {'node'} | set(member_fields)
    for prof in (data.get('profiles') or {}).values():
        if isinstance(prof, dict):
            for k in strip:
                prof.pop(k, None)
    return data


# ── check fan-out / status / probe-prep ──────────────────────────────────────────
_MOD_RE = re.compile(r'^[a-z][a-z0-9_]*$')

# Device fields that an 'add'-only user may NOT change (only the ``modules`` hint list may
# grow).  Secrets in ``profiles`` must already be restored before this comparison so an
# unchanged profile is not seen as edited.
_DEVICE_EDIT_FIELDS = ('name', 'address', 'kind', 'os', 'maintenance', 'virtual',
                     'device_type', 'tags', 'description', 'profiles')

# Fields the store KEEPS when the body leaves them out (``DevicesStore.update`` reads an
# absent ``source``/``external_id`` as "unchanged"), so absence is not a change. They were
# missing from the list above, which let an 'add'-only user re-class a device, tie it to an
# importer or cut it loose from one through the "add a check" path.
_DEVICE_KEPT_IF_ABSENT = ('source', 'external_id')


def _same_field(old: dict, data: dict, f: str) -> bool:
    """Whether *data* leaves device field *f* as *old* has it.

    ``device_type`` compares as text: the form sends ``''`` for an unclassified device whose
    record may carry ``''`` or nothing, and that is not an edit."""
    if f in _DEVICE_KEPT_IF_ABSENT:
        return data.get(f) is None or str(data.get(f) or '') == str(old.get(f) or '')
    if f == 'device_type':
        return str(data.get(f) or '') == str(old.get(f) or '')
    return data.get(f) == old.get(f)


def _bare(module_key: str) -> str:
    return module_key.split('.')[-1]


def _coll_meta(modules_dir: str, mod: str, coll: str) -> dict:
    """The collection's schema meta (``__discovery_label_template__`` etc.) read from the
    module's schema.json, or ``{}``."""
    from lib.modules.discovery.credential_schemas import _watchfuls_dir  # noqa: PLC0415
    bare = str(mod).replace('watchfuls.', '')
    sp = os.path.join(_watchfuls_dir(modules_dir), bare, 'schema.json')
    try:
        with open(sp, encoding='utf-8') as fh:
            c = json.load(fh).get(coll)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def _format_item_label(tpl: str, device_name: str, item: dict, disc_field: str) -> str:
    """Format a check's label from the module's discovery template (e.g. ``"{device} - {name}"``):
    ``{device}`` = the (new) device name, ``{name}`` = the item's operative field
    (``__discovery_field__``, e.g. service/partition), ``{other}`` = any item field.
    Mirrors the frontend ``_discoveryLabel``."""
    base = {'device': device_name or '',
            'name': str(item.get(disc_field) or '') if disc_field else '',
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


def _delete_device_checks(wa, uid: str) -> int:
    """Delete every module check bound to device *uid*.  Single-bind items (``device_uid``) are
    removed; for a multi-device (cluster) check the device is just removed from ``device_uids`` (the
    check is deleted only if it had no other member).  Returns how many checks were deleted or
    unbound."""
    # Load, edit and save as ONE step (see modules.facade.mutate_modules): done as three,
    # a module save landing in between was overwritten by this stale copy.
    def _apply(modules) -> int:
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
                    hu = item.get('device_uids')
                    if isinstance(hu, list) and any(str(x).strip() for x in hu):
                        remaining = [x for x in hu if str(x).strip() != str(uid)]
                        if len(remaining) != len(hu):
                            if remaining:
                                item['device_uids'] = remaining      # still a member of the cluster
                            else:
                                del items[key]                     # last member → drop the check
                            count += 1
                        continue
                    if str(item.get('device_uid') or '') == str(uid):
                        del items[key]
                        count += 1
        return count

    try:
        return mutate_modules(wa, _apply) or 0
    except Exception:  # pylint: disable=broad-except
        return 0


def _clone_device_checks(wa, src_uid: str, new_uid: str, label: str = '',
                       only_keys: set | None = None) -> int:
    """Duplicate every module check item bound to *src_uid* onto *new_uid*.

    When *only_keys* is given, only items whose key is in it are cloned/joined (the user
    picked them); ``None`` clones all bound checks.

    For each item whose ``device_uid`` is the source device, a deep copy is inserted under a fresh
    item UID pointing at the clone, so the new server inherits the same monitoring.  The
    clone's ``label`` is set to *label* (the new device's name) so checks read sensibly instead
    of falling back to the opaque item UID.

    For a multi-device (cluster) check the source is one MEMBER of, the clone's uid is ADDED to
    that same check's ``device_uids`` (the clone joins the cluster) — the check is not duplicated.

    Items are loaded decrypted and saved re-encrypted, so inline secrets survive.  Returns the
    number of checks the clone was wired into."""
    # Load, edit and save as ONE step (see modules.facade.mutate_modules): done as three,
    # a module save landing in between was overwritten by this stale copy.
    def _apply(modules) -> int:
        count = 0
        for mod, mcfg in modules.items():
            if str(mod).startswith('__') or not isinstance(mcfg, dict):
                continue
            for coll, items in list(mcfg.items()):
                if str(coll).startswith('__') or not isinstance(items, dict):
                    continue
                # The collection's label template (e.g. service_status "{device} - {name}") lets the
                # clone keep its per-item part (service/partition) with the NEW device name; without
                # one we just use the device name.
                _meta = _coll_meta(wa._modules_dir, mod, coll)
                _tpl = _meta.get('__discovery_label_template__')
                _disc = _meta.get('__discovery_field__')
                for ikey, item in list(items.items()):
                    if not isinstance(item, dict):
                        continue
                    if only_keys is not None and str(ikey) not in only_keys:
                        continue                       # the user did not pick this check
                    # Multi-device (cluster) binding: the device is one member of a shared check.
                    # Don't duplicate the check — add the clone as a NEW member of the SAME check
                    # so it joins the cluster (even if a stale device_uid also matches).
                    hu = item.get('device_uids')
                    if isinstance(hu, list) and any(str(x).strip() for x in hu):
                        members = [str(x).strip() for x in hu]
                        if str(src_uid) in members and str(new_uid) not in members:
                            hu.append(new_uid)
                            count += 1
                        continue
                    if str(item.get('device_uid') or '') != str(src_uid):
                        continue
                    clone = copy.deepcopy(item)
                    clone['device_uid'] = new_uid
                    clone.pop('uid', None)
                    # Re-format the label with the new device name (+ the item's own operative field
                    # via the template), else just the device name.
                    clone['label'] = (_format_item_label(_tpl, label, clone, _disc)
                                      if _tpl else label)
                    items[str(uuid.uuid4())] = clone
                    count += 1
        return count

    try:
        return mutate_modules(wa, _apply) or 0
    except Exception:  # pylint: disable=broad-except
        return 0


def forget_device_references(wa, uid: str, actor: str = '') -> None:
    """Clear what other domains say about device *uid*, which has just been deleted.

    Ownership (``org_owner`` rows of scope ``device``) is dropped; the DCIM rows that name it
    as their managed side (``dc_item``, ``dc_pdu``, ``dc_source`` → ``device_uid``) keep
    existing — a rack still holds the box, a PDU is still on the wall — but no longer point
    at a device nobody can resolve. Through the stores' own APIs; each part is best-effort,
    because the device is already gone and a failure here must not turn that into a 500."""
    uid = str(uid or '').strip()
    if not uid:
        return
    orgs = getattr(wa, '_orgs_store', None)
    if orgs is not None:
        try:
            orgs.forget_scope('device', uid)
        except Exception:  # pylint: disable=broad-except
            pass
    dcim = getattr(wa, '_dcim_store', None)
    if dcim is None:
        return
    for table in ('items', 'pdus', 'sources'):
        rows = getattr(dcim, table, None)
        if rows is None:
            continue
        try:
            for row in rows.list('device_uid = ?', (uid,)):
                rows.update(row['uid'], {'device_uid': ''}, actor=actor)
        except Exception:  # pylint: disable=broad-except
            pass


def _only_modules_growth(old: dict, data: dict) -> bool:
    """True if *data* changes nothing on the device except adding entries to the ``modules``
    list (no field edits, no module removals)."""
    for f in _DEVICE_EDIT_FIELDS + _DEVICE_KEPT_IF_ABSENT:
        if not _same_field(old, data, f):
            return False
    old_mods = set(old.get('modules') or [])
    new_mods = set(data.get('modules') or [])
    return old_mods <= new_mods


def _probe_device_record(wa, body):
    """Build a decrypted device record for testing from the request.

    A stored device (by ``device_uid``) merged with the posted ``_device`` draft; masked secrets in
    the draft are restored from storage.  Maintenance is forced off so an explicit test always
    runs."""
    store = getattr(wa, '_devices_store', None)
    uid = str(body.get('device_uid') or '').strip()
    stored = store.get(uid, decrypt=True) if (store and uid) else None
    draft = body.get('_device') if isinstance(body.get('_device'), dict) else None
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
    # Resolve a referenced credential into the ssh profile so the probe/test uses the
    # credential's identity (not the stored inline secret) — the same overlay resolve_device
    # applies at runtime.
    ssh = record['profiles'].get('ssh') or {}
    cred_uid = str(ssh.get('cred_uid') or '').strip()
    if cred_uid:
        from lib.core.credentials.store import apply_credential, SSH_CRED_FIELDS  # noqa: PLC0415
        cstore = getattr(wa, '_credentials_store', None)
        cred = cstore.get(cred_uid) if cstore is not None else None
        base = {k: v for k, v in ssh.items() if k not in SSH_CRED_FIELDS}
        record['profiles']['ssh'] = apply_credential(base, cred)
    return record


def _restore_check_secrets(wa, bare_module, coll, key, fields, may_restore=None):
    """Restore masked (null/'') secret fields in a check's *fields* from the stored
    module-config item, so a test run AFTER a reload (when the UI only holds masked secrets)
    uses the real, stored values instead of empties.

    *may_restore(stored_item)* says whether the caller may have THAT check's secrets: the key
    is the client's to choose and the device the test runs against is too, so without it a
    device editor could name any other check and have its password sent to their device."""
    if not isinstance(fields, dict):
        return
    modules = wa._load_modules()
    for mk in (bare_module, f'watchfuls.{bare_module}'):
        mod = modules.get(mk)
        items = mod.get(coll) if isinstance(mod, dict) else None
        stored = items.get(key) if isinstance(items, dict) else None
        if isinstance(stored, dict):
            if may_restore is not None and not may_restore(stored):
                return
            secret_manager.restore_sensitive(fields, stored, keys=wa._secret_keys)
            return


def _apply_check_cred(wa, fields):
    """Overlay a check's referenced credential (``cred_uid``) onto its *fields* so a
    device-bound check test authenticates with the credential — not the restored stored inline
    secret.  Returns *fields* (possibly a new dict)."""
    uid = str((fields or {}).get('cred_uid') or '').strip()
    if not uid:
        return fields
    cstore = getattr(wa, '_credentials_store', None)
    cred = cstore.get(uid) if cstore is not None else None
    from lib.core.credentials.store import apply_credential  # noqa: PLC0415
    return apply_credential(fields, cred)


def _checks_for_device(wa, uid):
    """Grouped ``{(bare_module, collection): {key: item}}`` for every check in the module
    configuration bound to *uid* (used when the client doesn't send the list)."""
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
                if isinstance(item, dict) and item.get('device_uid') == uid:
                    grouped.setdefault((bare, coll), {})[key] = item
    return grouped


def device_recorded_keys(series: list, uid: str) -> dict:
    """``{bare_module: {result_key: ''}}`` for what a module RECORDED about the device itself.

    The same question :func:`device_sampled_keys` asks of the live state, asked of the history —
    and it has to be asked, because the live state is not always there. A machine in
    maintenance has its checks skipped, so the next cycle prunes every key the module stopped
    returning, which for a device sampled through the registry is all of them. Reported from
    the screen: a switch put into maintenance opened onto four empty tabs with a year of
    history sitting behind it.

    The history is kept on purpose for exactly this (see ``purge_maintenance_states``); it was
    simply unreachable from a page that worked out what a device is made of from the live
    state alone.
    """
    uid = str(uid or '').strip()
    out: dict = {}
    if not uid:
        return out
    for row in series or ():
        if not isinstance(row, dict):
            continue
        key = str(row.get('key') or '')
        if device_uid_from_key(key) != uid:
            continue
        # The base key, not the row: `build_device_status` maps `<base>/<row>` back to it, which
        # is what makes one entry stand for a device's whole table.
        out.setdefault(_bare(str(row.get('module') or '')), {})[key.split('/', 1)[0]] = ''
    return out


def device_sampled_keys(status_raw: dict, uid: str) -> dict:
    """``{bare_module: {result_key: ''}}`` for what a module recorded about the DEVICE itself.

    Some devices are read because the REGISTRY says they are devices, not because somebody
    configured a check: an SNMP profile with device profiles assigned is enough, and what comes
    back is filed under the device (``device.<uid>/…``) rather than under an item.

    Two screens already knew that and one did not. The status column reads these keys, so a
    switch sampled this way turned red; the device page built its rows from the configured
    checks alone, so the same switch showed "no check points at this device" and four empty
    tabs. One machine, two answers, and the one with the numbers in it was the one nobody
    could see — reported exactly that way.

    Read from what was RECORDED rather than from what could be: this needs no list of which
    modules sample devices, and cannot disagree with the column that already does it.
    """
    uid = str(uid or '').strip()
    out: dict = {}
    if not uid or not isinstance(status_raw, dict):
        return out
    for mod_key, mod_status in status_raw.items():
        if not isinstance(mod_status, dict):
            continue
        bare = _bare(str(mod_key))
        for res_key in mod_status:
            if device_uid_from_key(res_key) != uid:
                continue
            # The base key, not the row: `build_device_status` maps `<base>/<row>` back to it,
            # which is what makes one entry stand for a device's whole table.
            out.setdefault(bare, {})[str(res_key).split('/', 1)[0]] = ''
    return out


def _device_statuses(wa):
    """Return ``{device_uid: 'ok'|'error'|'warning'}`` derived from the daemon's status file and
    the device_uid binding of each check in the module configuration.

    The check status is binary (True = OK) but a non-OK result carries a severity ('warning'
    for an aviso, else 'error'), so a device is:
      * ``error``   — at least one enabled check reports a hard (error) failure;
      * ``warning`` — no hard errors, but at least one check is a warning-severity failure, OR
                      it has enabled checks none of which has a status yet (the daemon hasn't
                      evaluated them — newly added / pending);
      * ``ok``      — it has enabled checks and every evaluated one is OK.
    Devices with no enabled checks are absent (the column shows a neutral dash).  Maintenance is
    NOT folded in here — the UI shows it as an override."""
    status_raw = wa._read_check_status()

    # Every result, indexed by the CHECK it belongs to rather than by the key it was filed
    # under. A watchful that samples rows files `<key>/<row>` or `<key>_<metric>` and nothing
    # at all under the bare key, so a look-up by key alone finds nothing — and "nothing" is
    # the newly-added case, which paints as a warning.
    #
    # Reported from the screen: two NAS sitting in warning with everything they answer green.
    # Each has one enabled SNMP item with no OID checks and twelve device profiles, so all 295
    # of its readings are sub-metrics and not one of them is under the item's own key. The
    # machine said "I have a check nobody has evaluated yet" about a check evaluated 295 times
    # a cycle. The switches and routers were fine because they have no configured item at all
    # and are rescued further down, by the `device.<uid>` branch.
    #
    # By `item_uid`, which is the same uid the configuration keys the check by, so no result
    # key has to be taken apart to find out whose it is.
    _by_item: dict = {}
    for _mk, _mod_status in status_raw.items():
        if not isinstance(_mod_status, dict):
            continue
        bucket = _by_item.setdefault(_bare(_mk), {})
        for _info in _mod_status.values():
            if isinstance(_info, dict) and _info.get('item_uid'):
                bucket.setdefault(_info['item_uid'], []).append(_info)

    def _check_info(mod_key, check_key):
        """The recorded (status, severity) for a check, trying full and bare keys."""
        for mk in (mod_key, _bare(mod_key)):
            mod = status_raw.get(mk)
            if isinstance(mod, dict) and check_key in mod:
                info = mod.get(check_key)
                if isinstance(info, dict):
                    return info.get('status'), (info.get('severity') or '')
                return None, ''
        # Nothing under its own key: the rows it produced, if it produced any. Worst first —
        # one row in trouble is the check in trouble, and a machine with one failed disk and
        # forty good ones is not a machine that is fine.
        rows = _by_item.get(_bare(mod_key), {}).get(check_key) or []
        if rows:
            if any(r.get('status') is not True and (r.get('severity') or '') != 'warning'
                   for r in rows):
                return False, ''
            if any(r.get('status') is not True for r in rows):
                return False, 'warning'
            return True, ''
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
                uid = item.get('device_uid')
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

    # …and the results that belong to a device with no check behind them: a device the panel
    # reads because the DEVICE says it is one (an SNMP profile with device profiles assigned).
    # Without this a device can be sampled, found down, and still show a neutral dash — the
    # column would be answering "how many checks did you configure" while looking like it
    # answers "is this machine all right".
    for mod_status in status_raw.values():
        if not isinstance(mod_status, dict):
            continue
        for res_key, info in mod_status.items():
            uid = device_uid_from_key(res_key)
            if not uid:
                continue
            a = agg.setdefault(uid, {'has_error': False, 'has_warn': False,
                                     'known': 0, 'total': 0})
            a['total'] += 1
            a['known'] += 1
            st = info.get('status') if isinstance(info, dict) else None
            sev = (info.get('severity') or '') if isinstance(info, dict) else ''
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


def _device_bound_modules(wa):
    """Return ``{device_uid: {bare_module: any_check_enabled}}`` — which modules have checks
    bound to each device and whether any of them is enabled."""
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
                uid = item.get('device_uid')
                if not uid:
                    continue
                mods = out.setdefault(uid, {})
                mods[bare] = mods.get(bare, False) or (item.get('enabled') is not False)
    return out


def _create_unique_device(store, name, candidate, actor):
    """Create a device, suffixing the name on collision.  Returns the uid or None."""
    base = (name or candidate.get('address') or 'device').strip() or 'device'
    profiles = candidate.get('profiles', {})
    body = {'name': base, 'address': candidate.get('address', ''),
            # A migrated connection that carries an SSH tunnel is a remote device.
            'kind': 'remote' if profiles.get('ssh') else 'local',
            'profiles': profiles}
    for attempt in (base, f"{base} ({candidate.get('address', '')})",
                    *[f"{base}-{i}" for i in range(2, 12)]):
        body['name'] = attempt.strip()
        uid = store.create(body, actor=actor)
        if uid:
            return uid
    return None
