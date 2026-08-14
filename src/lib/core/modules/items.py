#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""An item's identity: its uid, its name, its schema, and keeping them in step.

A module's configuration is mostly a list of ITEMS — a check, a server, a nested check under a
server — and almost everything the panel does with one starts by asking which item it is. That
question has several shapes: the uid a save must not duplicate, the name a person typed, the
schema the item is drawn from, and whether the thing in front of you is a collection of items
at all.

They live together because they are the same question. Splitting "generate a uid" from "is this
a collection of items" would put two halves of one rule in two files, and the rule is what the
clone, the duplicate and the rekey all lean on.

Flask-free and pure over plain dicts, like the rest of the domain.
"""

from __future__ import annotations

import re
import uuid


# Canonical UUID form, used to tell an opaque item key from a human-given one.
_UUID_RE = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# Collections that hold check items, keyed by the item UID. Nested collections
# (e.g. snmp's per-server ``checks``) are re-keyed recursively.
_ITEM_COLLECTIONS = ('list', 'servers')
_NESTED_ITEM_COLLECTIONS = ('checks',)


def is_item_collection(v) -> bool:
    """A module section holding items (``list``/``servers``/…) is dict-valued;
    module-level fields (enabled, threads, timeout, …) are scalars (bool/int),
    never dicts.  Items inside may be dicts or a bool shorthand
    (``"1.2.3.4": false`` = disabled), so the value *type* of items is not used
    to classify the section — only the section being a dict matters."""
    return isinstance(v, dict)


def item_host_uid(o, n) -> str:
    """Host UID of an item from its new or old value (items can be non-dict
    bool shorthands, which carry no host binding)."""
    for it in (n, o):
        if isinstance(it, dict):
            hu = str(it.get('host_uid') or '').strip()
            if hu:
                return hu
    return ''


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
        # A uid that is already taken USED TO cost the other item its existence: this builds
        # a dict keyed by uid, so the second write silently replaced the first and a save
        # came back with one check fewer — no error, nothing in the audit, just a check that
        # stopped existing. Two items can collide from an imported config, a hand-edited
        # file, or an item whose key is another item's uid. Whatever put them there, saving
        # is not allowed to resolve it by dropping one.
        while uid in out:
            uid = str(uuid.uuid4())
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


def duplicate_item_uids(data: dict) -> list:
    """Every uid that more than one item claims, as ``["<module>/<uid>", …]``.

    Reading this BEFORE the re-key is what makes a collision visible: afterwards there is
    nothing to see, because the second item has quietly been given a new uid. A duplicate
    should never exist — knowing one arrived, and from which module, is the difference
    between finding its cause and guessing at it.
    """
    out = []
    for module, module_cfg in (data or {}).items():
        if not isinstance(module_cfg, dict):
            continue
        for coll_name in _ITEM_COLLECTIONS:
            coll = module_cfg.get(coll_name)
            if not isinstance(coll, dict):
                continue
            seen: set = set()
            for item in coll.values():
                uid = str((item or {}).get('uid') or '').strip() if isinstance(item, dict) else ''
                if uid and uid in seen:
                    out.append(f'{module}/{uid}')
                elif uid:
                    seen.add(uid)
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


# ── where an item came from ──────────────────────────────────────────────────────
# The UI stamps this on a copy so the save can tell a clone from a hand-made item. By the
# time the payload arrives the two are indistinguishable — same fields, a uid the server just
# generated — and "where did this come from" is exactly what somebody asks of the audit when
# two rows look alike. Taken (not read) at save time: it answers a question about the write,
# it is not part of the configuration, and storing it would make it a fact about the item
# for ever rather than about the moment it was created.
_CLONE_MARK = '__cloned_from__'


def take_clone_marks(data: dict) -> dict:
    """``{(module, coll, key): source_key}`` for every marked item, removing the mark."""
    marks: dict = {}
    for module, module_cfg in (data or {}).items():
        if not isinstance(module_cfg, dict):
            continue
        for coll_name in _ITEM_COLLECTIONS:
            coll = module_cfg.get(coll_name)
            if not isinstance(coll, dict):
                continue
            for key, item in coll.items():
                if not isinstance(item, dict) or _CLONE_MARK not in item:
                    continue
                src = str(item.pop(_CLONE_MARK) or '').strip()
                if src:
                    marks[(module, coll_name, key)] = src
    return marks


def item_schemas(modules_dir: str | None) -> dict:
    """The per-collection item schemas, keyed ``"module|collection"`` — or ``{}``.

    Wrapped so the audit never depends on discovery succeeding: naming an item is a nicety,
    and a module folder that fails to scan must not be the reason a save 500s. Same shape of
    guard as :func:`strip_credential_fields`.
    """
    try:
        from lib.modules.module_base import ModuleBase  # noqa: PLC0415
        return ModuleBase.discover_schemas(modules_dir) or {}
    except Exception:  # pylint: disable=broad-except
        return {}


def _item_title_field(schemas: dict, module: str, coll: str) -> str:
    """The field holding an item's name, as the module's schema declares it.

    Modules do declare it (``label`` for most, ``ups_name``, ``process``), and using the
    declaration rather than guessing is what keeps this correct for the next module that
    picks a different field. ``label`` is the fallback the rest of the UI already assumes.
    """
    sch = (schemas or {}).get(f'{module}|{coll}') or {}
    return sch.get('__check_title_field__') or 'label'


def _item_name(item, key: str, title_field: str) -> str:
    """What to CALL an item in an audit entry: its name and its uid, never one alone.

    The name is what the reader recognises; the uid is what survives a rename. An entry that
    carried only the name would stop matching the item the first time it was renamed, and one
    that carried only the uid would need a lookup to mean anything.
    """
    name = str((item or {}).get(title_field) or '').strip() if isinstance(item, dict) else ''
    return f'{name} ({key})' if name and name != key else key


def item_origin_rows(old_data: dict, data: dict, marks: dict, schemas=None) -> list:
    """Audit rows naming every item that APPEARED in this save, and where it came from.

    ``_diff_dicts`` already reports the new item's fields, but it reports them the same way
    whether the item was typed from scratch or copied — the one distinction somebody chasing
    a duplicate actually needs. These rows state it outright.
    """
    rows = []
    for module, module_cfg in (data or {}).items():
        if not isinstance(module_cfg, dict):
            continue
        for coll_name in _ITEM_COLLECTIONS:
            coll = module_cfg.get(coll_name)
            if not isinstance(coll, dict):
                continue
            old_coll = ((old_data or {}).get(module) or {}).get(coll_name)
            old_coll = old_coll if isinstance(old_coll, dict) else {}
            tf = _item_title_field(schemas, module, coll_name)
            for key, item in coll.items():
                if key in old_coll:
                    continue
                src = marks.get((module, coll_name, key))
                where = f'{module}.{coll_name}'
                if src:
                    rows.append({
                        'field': f'{where} · cloned item',
                        'old': _item_name(old_coll.get(src), src, tf),
                        'new': _item_name(item, key, tf),
                    })
                else:
                    rows.append({
                        'field': f'{where} · new item',
                        'old': '',
                        'new': _item_name(item, key, tf),
                    })
    return rows
