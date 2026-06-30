---
purpose: AI agent reference for creating ServiceSentry watchful modules
version: "2.1"
last_validated: "2026-06-26"
validated_by: "Code-vs-doc audit (2026-06-26): reconciled host binding (__host_profile__ / __host_multiple__ / __credential__), __history__, field props (multi / nullable / ipkind / term_field / result_multi / placeholder_map_field), discovery UI meta-keys (__check_title_field__, __title_editable__, __discovery_uid_key__/_label_template__/_inputs__/_value_field__/_dedup_with_type__), MISSING_DEPS/PARTIAL_DEPS, host-aware exec helpers. No reverse drift (every documented symbol exists). Prior: agent built http_check from this doc alone, 393/393 tests pass (2026-05-29)."
coverage: "100% — all code features documented"
---

# AI Module Guide — ServiceSentry Watchful Modules

> **How to use this document:**
> Read §1 (Quick Reference) and §2 (Checklist) first.
> They give you the full blueprint. Use §3–§9 for exact syntax when needed.
> §10 (Common Failures) lists every mistake an agent has made with this codebase.

---

## §1 · QUICK REFERENCE

### 1.1 File structure

```
watchfuls/<module_name>/          # module_name: lowercase, underscores only
├── __init__.py                   # REQUIRED — Watchful class implementation
├── watchful.py                   # REQUIRED — always exactly: from . import Watchful
├── schema.json                   # REQUIRED — field definitions for UI
├── info.json                     # REQUIRED — module metadata
└── lang/
    ├── en_EN.json                # REQUIRED — labels for every visible field
    └── es_ES.json                # REQUIRED — same, translated
```

Optional:
```
└── web/
    ├── _ui.html                  # OPTIONAL — JS injected into dashboard <script>
    └── _modals.html              # OPTIONAL — HTML for custom modals
```

Auto-discovery: no registration needed. Monitor scans `watchfuls/` for packages with `__init__.py`.

---

### 1.2 Class blueprint

```python
class Watchful(ModuleBase):

    # ── REQUIRED ────────────────────────────────────────────────────────
    ITEM_SCHEMA = _SCHEMA                   # loaded from schema.json at module level
    _DEFAULTS   = {k: v['default']          # MUST exclude __*__ keys and non-dict values
                   for k, v in _SCHEMA['list'].items()
                   if not k.startswith('__') and isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)  # __package__ = 'watchfuls.mi_modulo'

    def check(self) -> dict_return:
        # ... monitoring logic ...
        super().check()          # MUST call before return (writes debug log)
        return self.dict_return  # MUST return this object

    # ── OPTIONAL ────────────────────────────────────────────────────────
    SUPPORTED_PLATFORMS: tuple          = ('linux', 'darwin')   # omit = all platforms
    WATCHFUL_ACTIONS:    frozenset[str] = frozenset({'discover', 'test_connection'})
    READ_ONLY_ACTIONS:   frozenset[str] = frozenset({'discover'})  # subset of WATCHFUL_ACTIONS
    WATCHFUL_TOOLBAR:    tuple[dict]    = ({'icon':'bi-...','label_key':'...','onclick':'jsFn'},)

    @classmethod
    def audit_detail(cls, action: str, result: dict) -> dict | None: ...
```

---

### 1.3 `info.json` blueprint

```json
{
    "name":         "mi_modulo",    // REQUIRED — same as package folder name
    "version":      "1.0.0",       // REQUIRED
    "description":  "...",         // REQUIRED
    "icon":         "🔍",          // REQUIRED — emoji or icon code
    "dependencies": []             // REQUIRED — list of pip packages, [] if none
}
```

> **INVARIANT:** `dependencies` MUST always be present, even as `[]`. Omitting it fails the integrity test suite.

---

### 1.4 `schema.json` blueprint

```json
{
    "__module__": {
        "api_ver": "v1",                        // OPTIONAL — default "v1"
        "enabled": {"type": "bool", "default": true},
        "threads": {"type": "int",  "default": 5,  "min": 1, "max": 50},
        "timeout": {"type": "int",  "default": 10, "min": 1, "max": 300}
    },
    "list": {
        "__field_order__":    [...],             // OPTIONAL
        "__group_when__":     {...},             // OPTIONAL
        "__actions__":        [...],             // OPTIONAL
        "__test__":           "/api/v1/...",     // OPTIONAL
        "__discovery__":      "action_name",    // OPTIONAL
        "__discovery_method__": "POST",         // OPTIONAL — default GET
        "enabled": {"type": "bool", "default": true},
        "my_field": {"type": "str",  "default": ""}
    }
}
```

---

### 1.5 `lang/*.json` blueprint

```json
{
    "pretty_name": "...",              // REQUIRED
    "labels": {
        // REQUIRED: one entry for EVERY field in EVERY collection including __module__
        // Example: "enabled", "threads", "timeout" at __module__ level also need labels
        "enabled": "Enabled",
        "threads": "Threads",
        "my_field": "My Field"
    },
    "hints":         {...},            // OPTIONAL — {field: "help text"}
    "option_labels": {...},            // REQUIRED if any field uses "options"
    "group_labels":  {...},            // REQUIRED if any field uses "group"
    "action_labels": {...},            // REQUIRED if __actions__ or input_action used
    "collections":   {"list": "..."},  // OPTIONAL — rename the collection header
    "new_item_key_label":  "...",      // OPTIONAL
    "rename_item_prompt":  "...",      // OPTIONAL
    "ui":            {...}             // OPTIONAL — strings for web/_ui.html
}
```

> **INVARIANT:** Every field in every collection (including `__module__`) MUST have an entry in `labels`. Fields with `hidden: true` are exempt.

---

### 1.6 Return-value contracts for classmethod actions

| Action type | HTTP | Return type | Shape |
|-------------|------|-------------|-------|
| `test_connection` | POST | `dict` | `{"ok": bool, "message": str}` |
| `list_*` (field_picker) | POST | `dict` | `{"ok": bool, "items": list[str]}` |
| `discover` | GET or POST | `list[dict]` | `[{"name":..., "display_name":..., ...}]` |
| `compile_start` (async job) | POST | `dict` | `{"ok": bool, "job_id": str, "total": int}` |
| `compile_status` (poll) | POST | `dict` | `{"done": bool, "completed": int, "total": int}` |
| `get_details` | POST | `dict` | `{"ok": bool, ...custom fields...}` |

> **INVARIANT:** `discover()` MUST return a **list** (not a dict). All other actions return a dict.

---

## §2 · CHECKLIST

### Minimum viable module

- [ ] `watchfuls/<name>/__init__.py` — `Watchful(ModuleBase)` class
- [ ] `watchfuls/<name>/watchful.py` — `from . import Watchful` (exactly this, nothing else)
- [ ] `watchfuls/<name>/schema.json` — `__module__` + at least one named collection
- [ ] `watchfuls/<name>/info.json` — `name`, `version`, `description`, `icon`, `dependencies: []`
- [ ] `watchfuls/<name>/lang/en_EN.json` — `pretty_name` + `labels` for ALL visible fields
- [ ] `watchfuls/<name>/lang/es_ES.json` — same, translated
- [ ] `ITEM_SCHEMA = _SCHEMA` assigned in class
- [ ] `_DEFAULTS` built from schema, excluding `__*__` keys and non-dict entries
- [ ] `super().__init__(monitor, __package__)` in `__init__`
- [ ] `super().check()` called **before** `return self.dict_return` in `check()`
- [ ] `dict_return.set(key, ok, msg)` called for every monitored item
- [ ] `check_status(ok, self.name_module, key)` + `send_message(msg, ok)` for notifications

### Schema features (add as needed)

- [ ] `__field_order__` — control rendering order
- [ ] `group` on fields + `group_labels` in lang — visual grouping
- [ ] `show_when: {field: [values]}` — conditional visibility
- [ ] `__group_when__` — conditional group headers
- [ ] `options` + `option_labels` in lang — dropdown fields
- [ ] `options_int` — dropdown for integer fields
- [ ] `options_deps` — disable options when pip package missing
- [ ] `sensitive: true` — password masking (auto-encrypted if name is `password`/`token`/`secret`/`ssh_password`)
- [ ] `hidden: true` — stored but never rendered (exempt from labels requirement)
- [ ] `readonly: true` — displayed but not manually editable
- [ ] `placeholder` / `placeholder_module` / `placeholder_map` / `zero_as_blank`
- [ ] `numericString: true` — digits-only string input
- [ ] `__pick_from_collection__` — picker from sibling collection
- [ ] `input_action` — icon button on a field (list_*, field_picker)
- [ ] `__actions__` + `action_labels` in lang — form action buttons
- [ ] `__test__` — quick-test button in collection header
- [ ] `__discovery__` + `WATCHFUL_ACTIONS` + `lang labels` — discover modal
- [ ] `__discovery_method__: "POST"` — if discover needs module config
- [ ] `__discovery_subtitle__` / `__discovery_type_field__` / `__discovery_category_field__` / `__discovery_categories__` — rich discovery modal
- [ ] `__discovery_default_operators__` — auto-set operator on add
- [ ] `__discovery_type_store_field__` + `hidden: true` field — persist detected type
- [ ] `__discovery_field__` / `__key_mirrors_field__` — inline search + key sync
- [ ] `__new_item_fields__` — required fields on item creation
- [ ] Sub-collection: `"type": "sub_collection"` field with its own schema

### Python class features (add as needed)

- [ ] `SUPPORTED_PLATFORMS` — restrict to platforms
- [ ] `WATCHFUL_ACTIONS` — expose classmethods as web endpoints
- [ ] `READ_ONLY_ACTIONS` — suppress audit for read-only actions
- [ ] `WATCHFUL_TOOLBAR` — toolbar buttons in module card
- [ ] `MISSING_DEPS` — list of required pip packages; if absent, module shows `__unsupported__` + "pip install …"
- [ ] `PARTIAL_DEPS` — list of optional pip packages; if absent, module shows a warning badge but stays usable
- [ ] `audit_detail(cls, action, result)` — custom audit log entries
- [ ] `host_os()` / `host_cmd_for()` / `host_exec()` — host-aware (local/SSH) execution helpers (see §7)
- [ ] `web/_ui.html` + `web/_modals.html` — custom JS/HTML
- [ ] `fail_streak(key, failed)` — consecutive failure tracking (persisted in check_state DB; survives cycles/processes)

---

## §3 · COMMON FAILURES

Errors that have occurred when creating modules with this guide. Check against these before running tests.

### F-01 · Missing `dependencies` in `info.json`
```
AssertionError: http_check/info.json missing keys: {'dependencies'}
```
**Cause:** `"dependencies"` must always be present, even as `[]`.
**Fix:** Add `"dependencies": []` to `info.json`.

---

### F-02 · Missing labels for `__module__` fields
```
AssertionError: mi_modulo|__module__['threads'] missing 'label_i18n'
```
**Cause:** `labels` in `lang/*.json` must cover ALL fields in ALL collections, **including `__module__`**. If `__module__` defines `enabled`, `threads`, `timeout`, all three need entries in `labels`.
**Fix:** Add `"threads": "Threads"`, `"timeout": "Timeout (s)"` etc. to `labels` in both lang files.

---

### F-03 · `_DEFAULTS` includes meta-keys
```python
# WRONG — includes __field_order__, __actions__, etc.
_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()}

# CORRECT
_DEFAULTS = {
    k: v['default']
    for k, v in _SCHEMA['list'].items()
    if not k.startswith('__') and isinstance(v, dict) and 'default' in v
}
```

---

### F-04 · Forgetting `super().check()` before return
```python
# WRONG — debug log never written; monitor behaves unexpectedly
def check(self):
    ...
    return self.dict_return

# CORRECT
def check(self):
    ...
    super().check()          # MUST be called
    return self.dict_return
```

---

### F-05 · `check()` not returning `self.dict_return`
```python
# WRONG — Monitor receives None; crashes or produces no status
def check(self):
    super().check()
    # missing return

# CORRECT
def check(self):
    super().check()
    return self.dict_return  # MUST return this object
```

---

### F-06 · Wrong classmethod signature for POST vs GET
```python
# POST action — receives config dict from request body
@classmethod
def test_connection(cls, config: dict) -> dict: ...

# GET action — no arguments
@classmethod
def discover(cls) -> list: ...
```
The route handler calls `method(config)` for POST and `method()` for GET. Mixing them causes a `TypeError` that returns a 500, not a 404.

---

### F-07 · `discover()` returning a dict instead of a list
```python
# WRONG — frontend expects Array.isArray(res.data) == true
return {"items": [...]}

# CORRECT
return [{"name": "...", "display_name": "..."}, ...]
```

---

### F-08 · `WATCHFUL_TOOLBAR` onclick not a global JS function
```python
WATCHFUL_TOOLBAR = ({'onclick': 'openMyModal'},)
```
`openMyModal` must be a **global** function defined in `web/_ui.html` (injected into the dashboard `<script>` block). If not present, the button click silently fails. The server validates it matches `^[a-zA-Z_$][a-zA-Z0-9_$]*$`.

---

### F-09 · `get_conf_in_list` with wrong collection name
```python
# If schema uses "servers" not "list", this always returns the default:
value = self.get_conf_in_list('host', item_key, '')

# Correct for non-default collection names:
value = self.get_conf_in_list('host', item_key, '', key_name_list='servers')
```

---

### F-10 · File operations without path confinement
```python
# DANGEROUS — path traversal possible
path = os.path.join(var_dir, 'files', user_name)

# CORRECT — two-layer validation always required
if not _safe_filename(name):
    return {'ok': False, 'message': 'Invalid filename'}
path = _confined_path(base_dir, name)
if not path:
    return {'ok': False, 'message': 'Invalid filename'}
```

---

### F-11 · `__var_dir__` treated as user-controlled
`__var_dir__` is **injected by the route handler** after stripping all client-supplied `__dunder__` keys. Its value is always server-side. Never trust it if it comes from the client directly.

---

### F-12 · Sub-collection schema key naming
```python
# Wrong — 'type: sub_collection' causes schemaDefaults() to include
# 'type': 'sub_collection' in the item defaults, showing a "Type" field in the UI.
# This is the expected behavior; it was a pre-existing bug that was fixed in the
# schemaDefaults() JS function. No action needed in the module.
```

---

### F-13 · `show_when` conditioned on a bool field does not update in fullscreen modal

**Symptom:** Fields with `show_when: {"my_bool": [true]}` appear/hide correctly in the
regular card view but do NOT respond when the toggle is flipped inside the fullscreen
expand modal.

**Cause:** The fullscreen modal renders the same item a second time, giving two DOM elements
with the same `data-sw-item-path`. `_refreshConditionalFields` used `querySelector` which
only found the first element (the hidden card behind the modal).

**Fix (already applied in the framework):**
- `_refreshConditionalFields` now uses `querySelectorAll` and updates ALL matching
  containers simultaneously.
- Bool toggle fields now call `_refreshConditionalFields(itemPath)` in their `onchange`
  handler (previously only `<select>` fields did this).

**No action needed in modules.** `show_when` conditioned on bool fields works correctly
in both the regular card and the fullscreen modal.

---

### F-14 · `test_connection` / `__test__` button reports "URL is required" when URL is the item key

**Context:** The `web` module (and any module) where the `url` field has
`"placeholder": "__key__"` — meaning the item's dictionary key IS the URL, and the
`url` field is stored as `""`.

**Cause:** When `testItemConnection` and `itemAction` POST the item's data, they send
`{url: "", ...}` — the item KEY ("www.example.com") is NOT a field in the item object,
it's the dict key. The classmethod receives `url = ""` and reports "URL is required".

**Fix (already applied in the framework):**
Both `testItemConnection` and `itemAction` now inject `_item_key` into every POST payload:
```javascript
const _itemKey = parts[parts.length - 1];  // last segment of pathStr
if (_itemKey) itemData['_item_key'] = _itemKey;
```

**Usage in classmethods:**
```python
@classmethod
def test_connection(cls, config: dict) -> dict:
    # Fall back to item key when url field is empty (placeholder: "__key__" pattern)
    url = (config.get('url') or '').strip() or (config.get('_item_key') or '').strip()
    if not url:
        return {'ok': False, 'message': 'URL is required'}
```

`_item_key` is NOT stripped by the route handler (only `__dunder__` keys are stripped).

---

## §4 · `__init__.py` — complete template

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Watchful module: mi_modulo."""

import concurrent.futures
import json
import os

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA: dict = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)


class Watchful(ModuleBase):

    # ── REQUIRED ────────────────────────────────────────────────────────
    ITEM_SCHEMA = _SCHEMA
    _DEFAULTS = {
        k: v['default']
        for k, v in _SCHEMA['list'].items()
        if not k.startswith('__') and isinstance(v, dict) and 'default' in v
    }

    # ── OPTIONAL class attributes ────────────────────────────────────────
    SUPPORTED_PLATFORMS: tuple = ('linux', 'darwin')   # omit = all platforms

    WATCHFUL_ACTIONS: frozenset[str] = frozenset({
        'discover',
        'test_connection',
        'list_items',
    })
    READ_ONLY_ACTIONS: frozenset[str] = frozenset({
        'discover', 'list_items',
    })

    WATCHFUL_TOOLBAR: tuple[dict, ...] = (
        {'icon': 'bi-database-gear', 'label_key': 'file_manager',
         'onclick': 'openFileManagerModal'},
    )

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    # ── Monitoring loop (REQUIRED) ────────────────────────────────────────
    def check(self):
        items = self._get_items()
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, self.module_default('threads', self._default_threads))
        ) as executor:
            futures = {
                executor.submit(self._item_check, name, target): (name, target)
                for name, target in items
            }
            for future in concurrent.futures.as_completed(futures):
                name, target = futures[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self.dict_return.set(name, False, f'Mi Modulo: *{name}* Error: {exc}')
        super().check()          # MUST call before return
        return self.dict_return  # MUST return

    # ── Private helpers ───────────────────────────────────────────────────
    def _get_items(self) -> list[tuple[str, str]]:
        result = []
        for key, value in self.get_conf('list', {}).items():
            if isinstance(value, bool):
                is_enabled, target = value, key
            elif isinstance(value, dict):
                is_enabled = bool(value.get('enabled', self._DEFAULTS.get('enabled', True)))
                target = (value.get('target', '') or '').strip() or key
            else:
                is_enabled, target = True, key
            if is_enabled:
                result.append((key, target))
        return result

    def _item_check(self, name: str, target: str) -> None:
        timeout = self.get_conf_in_list('timeout', name, self._DEFAULTS.get('timeout', 10))
        ok, detail = self._do_check(target, timeout)

        # Optional: consecutive failure threshold. Counter is persisted in the
        # check_state DB via fail_streak — NOT an instance dict, which would reset
        # every cycle (the monitor builds a fresh Watchful each cycle, and the
        # systemd one-shot mode runs each cycle in a fresh process).
        alert = int(self.get_conf_in_list('alert', name, 1) or 1)
        streak = self.fail_streak(name, not ok)
        effective_ok = ok or (streak < alert)

        msg = f'Mi Modulo: *{name}* {"OK" if ok else f"FAIL — {detail}"}'
        other_data = {'target': target, 'detail': detail}
        self.dict_return.set(name, effective_ok, msg, False, other_data)

        if self.check_status(effective_ok, self.name_module, name):
            self.send_message(msg, effective_ok)

    def _do_check(self, target: str, timeout: int) -> tuple[bool, str]:
        raise NotImplementedError

    # ── Optional: web classmethods ────────────────────────────────────────
    @classmethod
    def discover(cls) -> list[dict]:
        """GET — no config needed. Returns list (not dict)."""
        return [{'name': 'item1', 'display_name': 'Item 1', 'status': 'active'}]

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """POST — receives item fields + __var_dir__ from server."""
        try:
            return {'ok': True, 'message': 'OK'}
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}

    @classmethod
    def list_items(cls, config: dict) -> dict:
        """POST — for input_action with result: 'field_picker'."""
        return {'ok': True, 'items': ['a', 'b', 'c']}

    @classmethod
    def audit_detail(cls, action: str, result: dict) -> dict | None:
        """Return None to suppress audit entry (e.g. for polling actions).
        Return dict with extra fields to merge into the audit entry.
        Only called for actions NOT in READ_ONLY_ACTIONS."""
        if action == 'poll_status' and result.get('done') is False:
            return None  # suppress intermediate polls
        return {'ok': result.get('ok', True), 'name': action}
```

---

## §5 · `schema.json` — field property reference

### Field properties (all fields accept these)

| Property | Type | Required | Description |
|----------|------|:--------:|-------------|
| `type` | `"bool"\|"str"\|"int"\|"float"` | **YES** | Data type |
| `default` | any | **YES** | Default value when key absent in the module configuration (DB-backed; read via `config_modules`) |
| `min` | number | no | Minimum value for int/float |
| `max` | number | no | Maximum value for int/float |
| `sensitive` | bool | no | Render as password input. Auto-encrypted in disk if field name is `password`, `ssh_password`, `token`, or `secret` |
| `hidden` | bool | no | Store in the module configuration but never render. Exempt from label requirement |
| `readonly` | bool | no | Render as non-editable. Action buttons (discover, input_action) still work |
| `options` | string[] | no | Allowed values for `str` → renders `<select>` |
| `options_int` | int[] | no | Allowed values for `int` → renders `<select>`. Value `0` displays as `t('all')` |
| `options_deps` | `{value: "package"}` | no | Disable option if pip package missing |
| `group` | string | no | Visual group name. Needs matching entry in `group_labels` |
| `show_when` | `{field: [values]}` | no | Conditions (AND) controlling visibility. Value excluded from payload when hidden |
| `placeholder` | string | no | Static hint text. `"__key__"` uses the item key |
| `placeholder_module` | string | no | Name of a `__module__`-level field whose value becomes the placeholder |
| `placeholder_map` | `{value: hint}` | no | Map from preceding field's value to placeholder |
| `placeholder_map_field` | string | no | Name of the field whose value keys `placeholder_map` (defaults to the preceding field) |
| `zero_as_blank` | bool | no | Display value `0` as blank (shows placeholder). Semantic: "0 = use module default" |
| `inherit_blank` | bool | no | int/float `__module__` field: blank → stored `null`, inherits the global `modules\|<field>`, shown as placeholder |
| `nullable` | bool | no | int/float: blank → stored `null` ("use default"); placeholder shows the default. Generic (also used by panel config) |
| `multi` | bool | no | `str` field rendered as a removable-chips list (comma/space/newline separated; stored comma-joined) |
| `ipkind` | string | no | Validate field as an IP address (client + server). `"ip"` (IPv4/IPv6, no mask) or `"cidr"` (IP or CIDR). Combine with `multi` for a validated list |
| `term_field` | string | no | Sibling field whose value selects this field's label/hint/action from the lang `field_terms` map |
| `numericString` | bool | no | Restrict keyboard to digits only (for `str` fields containing numbers) |
| `__pick_from_collection__` | string | no | Name of sibling collection for picker button |
| `input_action` | object | no | Icon button on field. See §5.1 |
| `supported_platforms` | string[] | no | `["linux","win32","darwin"]` — field disabled on other platforms |
| `label_i18n` | dict | — | Auto-injected from lang/*.json. Never write manually |

> `placeholder` also accepts the special value `"__address__"` (resolves to the item's `host`/`url`/`address`, or the bound host's address).

### §5.1 `input_action` properties

| Property | Required | Description |
|----------|:--------:|-------------|
| `id` | **YES** | Key in `action_labels` for button tooltip |
| `url` | **YES** | Endpoint for POST request |
| `extra` | **YES** | Extra fields merged into payload (`{}` if none) |
| `icon` | **YES** | Bootstrap Icons class |
| `result` | **YES** | `"toast"` \| `"list"` \| `"field_picker"` |
| `result_field` | if field_picker | Field name to receive selected value |
| `result_multi` | no | `true` = picker result is a removable-chips multi-value instead of a single value |

### §5.2 Collection meta-keys (`__*__`)

| Key | Required | Description |
|-----|:--------:|-------------|
| `__field_order__` | no | Array of field names fixing render order |
| `__group_when__` | no | `{group_name: show_when_condition}` — conditional group headers |
| `__actions__` | no | Array of action button definitions. See §5.3 |
| `__test__` | no | URL for quick-test button in collection header |
| `__discovery__` | no | Action name for discover modal button |
| `__discovery_method__` | no | `"POST"` or `"GET"` (default). POST sends module config as body |
| `__discovery_field__` | no | Field name to get an inline search button |
| `__discovery_subtitle__` | no | Template string for modal subtitle. `{field_name}` placeholders |
| `__discovery_type_field__` | no | Field in discover result for type badge (default: `"status"`) |
| `__discovery_category_field__` | no | Field in discover result for category lookup |
| `__discovery_categories__` | no | `{category: {icon, color}}` — category badge styles |
| `__discovery_default_operators__` | no | `{category: operator}` — auto-set operator on add |
| `__discovery_type_store_field__` | no | Hidden field name to store detected type on add |
| `__discovery_label_template__` | no | Template `{field}` to build each discovered row's label (e.g. `"{host} - {db_type}"`) |
| `__discovery_uid_key__` | no | `true` = discovered item keys are opaque UUIDs (key not user-editable) |
| `__discovery_value_field__` | no | Field of the discover result used to fill the item (instead of the key) |
| `__discovery_inputs__` | no | Array of extra input controls shown in the discover modal (filters) |
| `__discovery_dedup_with_type__` | no | `true` = dedupe discovered items using the type field as part of the key |
| `__key_mirrors_field__` | no | Auto-sync item key with this field value on discover-add |
| `__check_title_field__` | no | Field holding the item's visible label (e.g. `"label"`, `"process"`) |
| `__title_editable__` | no | `true` = the item label (`__check_title_field__`) is renameable in the UI |
| `__new_item_fields__` | no | Fields shown in "new item" dialog before full form |
| `type: "sub_collection"` | — | Nested collection. See §5.4 |

> **Module-private meta-keys:** a module may stash its own `__custom__` config in
> `schema.json` and read it from `_SCHEMA` in its classmethods (e.g. `dns` defines
> `__discovery_probe_types__` and reads it in `discover()`). Core ignores unknown
> `__*__` keys (stripped from `ITEM_SCHEMAS`), so they're safe for module-specific use.

### §5.3 `__actions__` entry properties

| Property | Required | Description |
|----------|:--------:|-------------|
| `id` | **YES** | Key in `action_labels` |
| `url` | **YES** | POST endpoint |
| `extra` | **YES** | Extra payload fields (`{}` if none) |
| `icon` | **YES** | Bootstrap Icons class |
| `variant` | **YES** | Bootstrap button variant: `"secondary"`, `"warning"`, `"danger"`, etc. **Never** `"outline-*"` |
| `full_width` | no | `true` = button fills 100% width |
| `result` | no | `"toast"` (default) \| `"list"` \| `"field_picker"` |
| `result_field` | if field_picker | Target field for selected value |
| `show_when` | no | Same syntax as field `show_when` |
| `group` | no | Place button inside this group instead of at form bottom |

### §5.4 Sub-collections

Declare a nested collection by adding a `"type": "sub_collection"` field. The nested schema supports all the same meta-keys and field properties.

```json
"servers": {
    "__new_item_fields__": ["host"],
    "enabled": {"type": "bool", "default": true},
    "host":    {"type": "str",  "default": ""},
    "checks": {
        "type":                           "sub_collection",
        "__discovery__":                  "discover",
        "__discovery_method__":           "POST",
        "__discovery_field__":            "oid",
        "__key_mirrors_field__":          "oid",
        "__discovery_type_store_field__": "item_type",
        "enabled":    {"type": "bool", "default": true},
        "oid":        {"type": "str",  "default": "", "readonly": true},
        "item_type":  {"type": "str",  "default": "", "hidden": true},
        "operator":   {"type": "str",  "default": "any",
                       "options": ["any","eq","ne","gt","lt","gte","lte","contains"]},
        "value":      {"type": "str",  "default": ""}
    }
}
```

When discover runs on `checks` (POST), body includes module scalars + parent server item:
```json
{"enabled": true, "threads": 5, "servers": {"server_key": {...full server data...}}, "__var_dir__": "..."}
```

### §5.5 Module-level meta-keys (`__module__`)

For host-aware / history / credential-backed modules, declare these in `__module__`:

| Key | Description |
|-----|-------------|
| `api_ver` | API version for action URLs (`/api/<ver>/watchfuls/...`). Default `"v1"` |
| `__host_profile__` | Connection fields a check inherits when bound to a host: `{"key": <proto>, "address_field": <field>, "fields": [...]}` (dict or list). Resolved by `ModuleBase.resolve_host()` |
| `__host_multiple__` | `true` = a check can bind to several hosts (multi-select) |
| `__credential__` | Reusable-credential fields: `{"type": "web_auth", "fields": [...]}` (referenceable from the credential store) |
| `__history__` | Numeric field(s) recorded as a time series for the history graphs: `{"field": "temp", "unit": "°C", "label": "..."}`, or `{"fields": {name: {...}}}`, or `{"field": null}` for status-only |

```json
"__module__": {
    "api_ver": "v1",
    "__host_profile__": {"key": "snmp", "address_field": "host", "fields": ["host"]},
    "__host_multiple__": true,
    "__history__": {"field": "percent", "unit": "%", "label": "Usage"},
    "enabled": {"type": "bool", "default": true}
}
```

> Runtime-injected keys (set by `discover_schemas()`, do NOT write in `schema.json`):
> `__unsupported__`, `__missing_deps__`, `__partial_deps__`, `options_disabled`,
> `__toolbar__`, `__ui__`, `__i18n__`, `label_i18n`.

---

## §6 · `lang/*.json` — complete reference

```
INVARIANT: EVERY field in EVERY collection — including __module__ — MUST have
           a corresponding entry in "labels", except fields with hidden: true.
           Violation causes test suite failure: "missing 'label_i18n'".
```

```json
{
    "pretty_name":       "...",         // REQUIRED
    "module_description": "...",        // OPTIONAL — long description in module card

    "labels": {                         // REQUIRED — covers ALL fields in ALL collections
        "enabled": "Enabled",           // __module__.enabled
        "threads": "Threads",           // __module__.threads  ← often forgotten
        "timeout": "Timeout (s)",       // __module__.timeout  ← often forgotten
        "my_field": "My Field"          // list.my_field
    },

    "hints": {                          // OPTIONAL — help text per field
        "my_field": "Description shown under the field."
    },

    "option_labels": {                  // REQUIRED if any field uses "options"
        "my_field": {"value1": "Label 1", "value2": "Label 2"}
    },

    "group_labels": {                   // REQUIRED if any field uses "group"
        "my_group": "My Group"
    },

    "action_labels": {                  // REQUIRED if __actions__ or input_action used
        "test_connection": "Test",
        "list_items":      "Browse"
    },

    "collections": {                    // OPTIONAL
        "list": "Servers"
    },

    "new_item_key_label":  "Name:",     // OPTIONAL
    "rename_item_prompt":  "New name:", // OPTIONAL

    "ui": {                             // OPTIONAL — strings for web/_ui.html JS
        "file_manager": "File Manager"
    }
}
```

---

## §7 · `ModuleBase` API reference

### Configuration reads

```python
# Module-level field
value = self.get_conf('timeout', default=10)
value = self.get_conf('threads', 5, select_module='watchfuls.other')

# Module-level setting resolved via the item → module → global chain.
# Returns the module's saved value; if blank, inherits the global modules|<field>
# (config.json); if absent, the schema default. Always returns int.
# Use this (NOT get_conf) for 'threads' and 'timeout'.
workers = self.module_default('threads', self._default_threads)
timeout = self.module_default('timeout', 10)

# Item field from collection "list" (default)
value = self.get_conf_in_list('timeout', item_key, default=10)

# Item field from named collection
value = self.get_conf_in_list('alert', item_key, 80, key_name_list='config')

# Type parsers (return default if value invalid)
v = self._parse_conf_int(raw, default=0, min_val=1)
v = self._parse_conf_float(raw, default=0.0, min_val=0.0)
v = self._parse_conf_str(raw, default='localhost')
```

### `dict_return` API

```python
# Write result
self.dict_return.set(key, status, message, send_msg=False, other_data=None)
# key:        str  — item identifier (used in the check_state table and as notification key)
# status:     bool — True=OK, False=Error
# message:    str  — Telegram message (supports *bold*, _italic_, `code`, [url](link))
# send_msg:   bool — False: manual send_message() call; True: auto-send immediately
# other_data: dict — stored in check_state under "extra"; visible on /status page

# Update a field of an existing result
self.dict_return.update(key, 'message', 'New text')  # option: "status"|"message"|"send"|"other_data"

# Read results
self.dict_return.get(key)            # → dict  full result
self.dict_return.get_status(key)     # → bool
self.dict_return.get_message(key)    # → str
self.dict_return.get_other_data(key) # → dict
self.dict_return.is_exist(key)       # → bool
self.dict_return.remove(key)         # → bool
self.dict_return.count               # property: int
for key, data in self.dict_return.items(): ...
for key in self.dict_return.keys():  ...
```

### Notifications

```python
# Notify only when state CHANGED from last cycle.
# FIRST cycle always returns True (prev state = None), so always notifies at startup.
if self.check_status(ok, self.name_module, key):
    self.send_message(msg, ok)

# Like check_status but also notifies when error type changes (both False, different msg).
# Use when: ok=False AND error message is in other_data={'message': error_detail}
if self.check_status_custom(ok, key, error_detail):
    self.send_message(msg, ok)

# Consecutive-failure counter, persisted in the check_state DB (survives cycles
# and processes — do NOT use an instance dict, it resets every cycle).
# Returns the updated streak for `key`; reset to 0 when failed=False.
streak = self.fail_streak(key, not ok)
effective_ok = ok or (streak < alert_threshold)
```

### Commands

```python
# Local command — stdout only
output = self._run_cmd('systemctl status nginx')

# Local — stdout + stderr
out, err = self._run_cmd('cmd', return_str_err=True)

# Local — stdout + exit code
out, code = self._run_cmd('cmd', return_exit_code=True)

# Full control (local or SSH)
from lib import Exec, ExecResult
result = Exec.execute(
    command='df -h',
    host='192.168.1.10',  # omit for local
    port=22, user='root',
    password='pass',      # or key_file='/path/to/id_rsa'
    timeout=30.0,
)
# result.out (str|None), result.err (str|None), result.code (int|None), result.exception (Exception|None)
if result.exception:
    return False, str(result.exception)

# Reusable SSH runner (multiple commands same host)
runner = Exec()
runner.set_remote(host='h', port=22, user='root', key_file='/path/key', timeout=15.0)
runner.command = 'uptime'; r1 = runner.start()
runner.command = 'df -h';  r2 = runner.start()

# Host-aware helpers (PREFERRED for host-bound checks) — pick the per-OS command
# and run it locally or over SSH using the item's bound host, transparently:
os_name = self.host_os(item)                       # 'linux' | 'darwin' | 'win32'
cmd     = self.host_cmd_for(item, {'linux': 'cat /proc/stat',
                                   'darwin': 'top -l 2 -n 0'})
out, err, code = self.host_exec(item, cmd, timeout=15)
```

### Useful properties

```python
self.name_module        # str: 'watchfuls.mi_modulo'
self.is_enabled         # bool: whether module is enabled
self._default_threads   # int: default thread count
```

### Debug levels

```python
from lib.debug import DebugLevel
self._debug("message", DebugLevel.debug)     # level 1 — verbose trace
self._debug("message", DebugLevel.info)      # level 2 — general info
self._debug("message", DebugLevel.warning)   # level 3 — non-critical warning
self._debug("message", DebugLevel.error)     # level 4 — recoverable error
self._debug("message", DebugLevel.emergency) # level 5 — critical failure
```

---

## §8 · Secure file operations

Apply BOTH layers when handling user-supplied filenames. A single layer is insufficient.

```python
import os, pathlib, re

_SAFE_FILENAME_RE = re.compile(r'^[A-Za-z0-9_.-]+$')

def _safe_filename(name: str, kind: str = 'raw') -> str | None:
    """Allowlist validation. Returns name or None if invalid."""
    if not name or '/' in name or os.sep in name or name.startswith('.'):
        return None
    if not _SAFE_FILENAME_RE.match(name):
        return None
    ext = os.path.splitext(name)[1].lower()
    if kind == 'compiled' and ext != '.py':
        return None
    if kind == 'raw' and ext not in ('', '.txt', '.conf'):
        return None
    return name

def _confined_path(base_dir: str, *parts: str) -> str | None:
    """Resolves path and confirms it stays inside base_dir (blocks symlink escapes)."""
    base   = pathlib.Path(base_dir).resolve()
    target = pathlib.Path(os.path.join(base_dir, *parts)).resolve()
    if not str(target).startswith(str(base) + os.sep) and target != base:
        return None
    return str(target)

# Usage:
@classmethod
def delete_file(cls, config: dict) -> dict:
    var_dir = str(config.get('__var_dir__') or '').strip()
    name    = str(config.get('name') or '').strip()
    if not var_dir or not _safe_filename(name):
        return {'ok': False, 'message': 'Invalid parameters'}
    base = os.path.join(var_dir, 'my_module', 'files')
    path = _confined_path(base, name)
    if not path or not os.path.isfile(path):
        return {'ok': False, 'message': 'File not found'}
    os.remove(path)
    return {'ok': True}
```

---

## §9 · Test template

```python
#!/usr/bin/env python3
"""Tests for watchfuls.mi_modulo."""

from unittest.mock import patch
import pytest
from conftest import create_mock_monitor

# create_mock_monitor(config) notes:
# - config key is FULL name: 'watchfuls.mi_modulo' (not 'mi_modulo')
# - check_status returns False by default (no notifications fired)
# - send_message is a silent mock

def _monitor(list_cfg: dict | None = None):
    return create_mock_monitor({'watchfuls.mi_modulo': {'list': list_cfg or {}}})


class TestInit:
    def test_name_module(self):
        from watchfuls.mi_modulo import Watchful
        w = Watchful(_monitor())
        assert w.name_module == 'watchfuls.mi_modulo'

    def test_defaults_match_schema(self):
        from watchfuls.mi_modulo import Watchful
        for key, meta in Watchful.ITEM_SCHEMA['list'].items():
            if key.startswith('__') or not isinstance(meta, dict) or meta.get('hidden'):
                continue
            assert key in Watchful._DEFAULTS, f'Missing default for {key!r}'


class TestCheck:
    def test_empty_list(self):
        from watchfuls.mi_modulo import Watchful
        result = Watchful(_monitor()).check()
        assert list(result.keys()) == []

    def test_disabled_skipped(self):
        from watchfuls.mi_modulo import Watchful
        w = Watchful(_monitor({'x': {'enabled': False}}))
        assert list(w.check().keys()) == []

    def test_item_ok(self):
        from watchfuls.mi_modulo import Watchful
        w = Watchful(_monitor({'item': {'enabled': True}}))
        with patch.object(w, '_do_check', return_value=(True, 'OK')):
            assert w.check().get_status('item') is True

    def test_item_fail(self):
        from watchfuls.mi_modulo import Watchful
        w = Watchful(_monitor({'item': {'enabled': True}}))
        with patch.object(w, '_do_check', return_value=(False, 'timeout')):
            assert w.check().get_status('item') is False

    def test_bool_true_compat(self):
        """Backward compat: value=True uses key as target."""
        from watchfuls.mi_modulo import Watchful
        w = Watchful(_monitor({'target_key': True}))
        with patch.object(w, '_do_check', return_value=(True, 'OK')):
            assert 'target_key' in list(w.check().keys())

    def test_bool_false_disabled(self):
        from watchfuls.mi_modulo import Watchful
        w = Watchful(_monitor({'target_key': False}))
        assert list(w.check().keys()) == []


class TestClassmethods:
    def test_test_connection_ok(self):
        from watchfuls.mi_modulo import Watchful
        # replace with module-specific mock
        r = Watchful.test_connection({'url': 'http://example.com'})
        assert 'ok' in r
        assert 'message' in r

    def test_test_connection_missing_param(self):
        from watchfuls.mi_modulo import Watchful
        r = Watchful.test_connection({})
        assert r['ok'] is False


class TestSchema:
    def test_all_visible_fields_have_type_and_default(self):
        from watchfuls.mi_modulo import Watchful
        for col in ('list',):
            for key, meta in Watchful.ITEM_SCHEMA[col].items():
                if key.startswith('__') or not isinstance(meta, dict):
                    continue
                if meta.get('hidden') or meta.get('type') == 'sub_collection':
                    continue
                assert 'type' in meta,    f'{col}[{key!r}] missing "type"'
                assert 'default' in meta, f'{col}[{key!r}] missing "default"'
```

---

## §10 · Linux utilities (optional)

### Thermal sensors

```python
from lib.system.linux import ThermalInfoCollection  # requires SUPPORTED_PLATFORMS = ('linux',)

col = ThermalInfoCollection(autodetect=True)
for node in col.nodes:
    print(node.dev)   # 'thermal_zone0'
    print(node.type)  # 'x86_pkg_temp'
    print(node.temp)  # float °C
```

### RAID arrays (`/proc/mdstat`)

```python
from lib.system.linux import RaidMdstat  # requires SUPPORTED_PLATFORMS = ('linux',)

md = RaidMdstat()                          # local
md = RaidMdstat(host='h', port=22, user='root', key_file='/path/key')  # remote

if md.is_exist:
    status = md.read_status()
    # {'md0': {'status':'active','type':'raid1','disk':[...],'update': RaidMdstat.UpdateStatus.ok}}
    ok = (status['md0']['update'] == RaidMdstat.UpdateStatus.ok)

# UpdateStatus values: ok | error | recovery | unknown
```

---

## §11 · `WATCHFUL_TOOLBAR` reference

```python
WATCHFUL_TOOLBAR: tuple[dict, ...] = (
    {
        'icon':      'bi-database-gear',      # Bootstrap Icons class
        'label_key': 'file_manager',          # key in lang/*.json → ui.<label_key>
        'onclick':   'openFileManagerModal',  # MUST be a global JS function(modName)
    },
)
```

**Constraints:**
- `onclick` value MUST match `^[a-zA-Z_$][a-zA-Z0-9_$]*$` (validated server-side)
- The JS function MUST be defined globally in `web/_ui.html`
- Function signature: `function myFn(modName) { ... }`
- `label_key` must have a matching entry in `lang/*.json → ui`

> **Legacy `WATCHFUL_UI`:** an optional `frozenset[str]` class var, propagated by
> `discover_schemas()` as `__ui__`. Superseded by `WATCHFUL_TOOLBAR` (no current
> module uses it); prefer the toolbar.

---

## §12 · `web/_ui.html` and `web/_modals.html`

### `_ui.html`

Jinja2 template fragment. Injected verbatim into the dashboard `<script>` block.
Can use `{{ }}` and `{% %}` Jinja2 syntax.
Define all functions referenced by `WATCHFUL_TOOLBAR.onclick` here.

```html
{# web/_ui.html #}
function openFileManagerModal(modName) {
    // modName: string — the module name e.g. 'snmp'
    bootstrap.Modal.getOrCreateInstance(
        document.getElementById('fileManagerModal')
    ).show();
}
```

### `_modals.html`

Jinja2 template fragment. Injected into the page `<body>`.
Available Jinja2 variable: `i18n.close` (translated "Close" string).

```html
{# web/_modals.html #}
<div class="modal fade" id="fileManagerModal" tabindex="-1">
    <div class="modal-dialog modal-xl">
        <div class="modal-content">
            <div class="modal-header py-2">
                <h6 class="modal-title">File Manager</h6>
                <button type="button" class="btn-close" data-bs-dismiss="modal"
                    title="{{ i18n.close }}"></button>
            </div>
            <div class="modal-body p-3"></div>
            <div class="modal-footer py-1">
                <button class="btn btn-sm btn-secondary" data-bs-dismiss="modal">
                    {{ i18n.close }}
                </button>
            </div>
        </div>
    </div>
</div>
```
