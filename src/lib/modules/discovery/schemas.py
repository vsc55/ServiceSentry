#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Javier Pastor (aka VSC55)
# <jpastor at cerebelum dot net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""Scanning every watchful's ``schema.json`` and building the catalogues from it.

This is not module behaviour. It reads a directory of modules and answers questions ABOUT
them — what fields each declares, which of those are secret, what the web UI should render —
and it needs no monitor, no config and no instance. It sat inside ``module_base`` because the
base class was the first thing that needed it, and it stayed there while the package built
around exactly this idea grew up beside it: this package's own docstring says it is "kept
apart from the module framework itself (module_base / dict_return_check)", and the largest
scanner of the lot was still inside the framework.

Mixed into ``ModuleBase`` rather than exposed as loose functions, because
``ModuleBase.discover_schemas(...)`` is the published entry point and half a dozen callers
across lib/ and the watchfuls reach it that way. That is composition, not a convenience
re-export: the class really does provide these.
"""

import importlib
import json
import os
import sys


# ─────────────────────────────────────────────────────────────────────────────
#  WATCHFULS DIRECTORY — read this before changing it, and before moving this file
# ─────────────────────────────────────────────────────────────────────────────
#  This used to be `os.path.join(os.path.dirname(__file__), '..', '..', 'watchfuls')`, a
#  count of how deep this file sits. That is a hidden dependency on the file's POSITION,
#  and moving the file is exactly what happens when the code is reorganised: when this
#  scanner moved one directory deeper the count kept pointing one level too high, at a
#  directory that does not exist.
#
#  What made it expensive was not the wrong count, it was the SILENCE. `discover_schemas`
#  treats a missing directory as an empty result, not as an error, so nothing failed —
#  the catalogue simply came back empty and surfaced far away as `KeyError: 'ping|list'`,
#  and in the UI it would have been modules rendered with no fields and no explanation.
#
#  So it is searched, not counted: walk up from this file for the first ancestor holding
#  both `lib/` and `watchfuls/`. That survives this file moving anywhere inside `lib/`.
#  The fallback keeps the old behaviour if the search finds nothing, and
#  `TestTheDefaultPathStillFindsTheModules` fails loudly if either stops working.
#
#  Rule of thumb this cost us: if a function DERIVES a path, the test to write is the one
#  that calls it with NO arguments — the version you hand a path to will keep passing.
def _find_watchfuls_dir() -> str:
    """The watchfuls directory, located by structure rather than by counting parents."""
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        parent = os.path.dirname(here)
        if parent == here:                       # reached the filesystem root
            break
        if (os.path.isdir(os.path.join(parent, 'watchfuls'))
                and os.path.isdir(os.path.join(parent, 'lib'))):
            return os.path.join(parent, 'watchfuls')
        here = parent
    # Nothing found: fall back to the historical relative path so behaviour is unchanged
    # in a layout this search does not recognise.
    return os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        os.pardir, os.pardir, os.pardir, 'watchfuls'))


class SchemaDiscovery:
    """The schema catalogues, mixed into ``ModuleBase``."""


    # Fields ModuleBase injects into every watchful's module-level config, declared
    # schema.json-style — one entry per field with its fallback default and (for
    # the ones shown on the config pane) the collapsible section it groups under.
    # ``module_default()``/``is_enabled()`` read ``default``; ``discover_schemas``
    # stamps ``group``. A module's own schema value always wins.
    _MODULE_FIELDS = {
        'enabled': {'default': True},
        'threads': {'default': 5, 'group': 'execution'},
        'timeout': {'group': 'execution'},          # default is module-specific
    }
    # Config-pane section → i18n label key (like a lang file's group_labels). The
    # 'defaults' section is the UI catch-all for a module's own ungrouped fields.
    _MODULE_SECTION_LABELS = {'execution': 'module_execution', 'defaults': 'module_defaults'}

    @classmethod
    def module_field_default(cls, name, fallback=None):
        """Fallback default for a ModuleBase-injected field — the single source is
        :attr:`_MODULE_FIELDS` (no derived copies)."""
        return cls._MODULE_FIELDS.get(name, {}).get('default', fallback)

    # Per-item field schema for the module's collections.
    # Override in subclasses to declare which fields each item supports.
    # Format: { 'collection_key': { field: default_value, … } }
    # Example: { 'list': { 'enabled': True, 'code': 200 } }
    ITEM_SCHEMA: dict[str, dict] = {}

    # Classmethods exposed as web actions via /api/watchfuls/<module>/<action>.
    # Override in subclasses to whitelist callable classmethods.
    WATCHFUL_ACTIONS: frozenset[str] = frozenset()

    # Optional Python packages required by this watchful.
    # Override in subclasses to a non-empty list when an import fails so that
    # discover_schemas() can mark the module as unavailable in the UI and
    # display a "pip install <pkg>" hint instead of the normal controls.
    MISSING_DEPS: list[str] = []

    # Optional packages whose absence degrades (but does not break) this watchful.
    # The module remains functional without them but the UI shows a warning badge
    # so users know that some features or backends may be unavailable.
    PARTIAL_DEPS: list[str] = []

    @staticmethod
    def _schema_defaults(collection: dict) -> dict:
        """Extract default values from an enriched ``ITEM_SCHEMA`` collection.

        Supports both the simple format (``{field: value}``) and the rich
        format (``{field: {default: value, type: ..., ...}}``).
        """
        defaults: dict = {}
        for k, v in collection.items():
            if k.startswith('__'):
                continue
            if isinstance(v, dict) and 'default' in v:
                val = v['default']
                defaults[k] = list(val) if isinstance(val, list) else val
            else:
                defaults[k] = list(v) if isinstance(v, list) else v
        return defaults

    @classmethod
    def discover_secret_fields(cls, watchfuls_dir: str | None = None) -> set[str]:
        """Return the set of field names every module flags as secret/sensitive.

        Lets the core protect module credentials (encrypt at rest, mask in API
        responses, redact in audit) without hardcoding any module-specific
        field names — modules declare ``"secret": true`` / ``"sensitive": true``
        in their schema.json and the core discovers them here.  One level of
        ``sub_collection`` nesting is inspected too.
        """
        secret_fields: set[str] = set()

        def _scan(fields: dict) -> None:
            for fkey, meta in fields.items():
                if not isinstance(meta, dict):
                    continue
                if meta.get('secret') or meta.get('sensitive'):
                    secret_fields.add(fkey)
                if meta.get('type') == 'sub_collection' and isinstance(meta.get('fields'), dict):
                    _scan(meta['fields'])

        try:
            for coll_fields in cls.discover_schemas(watchfuls_dir).values():
                if isinstance(coll_fields, dict):
                    _scan(coll_fields)
        except Exception:  # pylint: disable=broad-except
            pass
        return secret_fields

    @classmethod
    def discover_schemas(cls, watchfuls_dir: str | None = None) -> dict[str, dict]:
        """Scan the *watchfuls* package and return the aggregated schemas.

        Returns a flat dict keyed ``"module_name|collection"`` whose values
        are the per-item field metadata declared by each module's
        ``ITEM_SCHEMA``.  For folder-based modules (new style) the per-field
        ``label_i18n`` and the top-level ``__i18n__`` entry are built by
        merging ``schema.json``, ``info.json`` and ``lang/*.json`` so that
        the Python class stays clean.

        When *watchfuls_dir* is ``None`` it is located by :func:`_find_watchfuls_dir` —
        see the note above that function before changing anything about this path.
        """
        if watchfuls_dir is None:
            watchfuls_dir = _find_watchfuls_dir()

        schemas: dict[str, dict] = {}
        if not os.path.isdir(watchfuls_dir):
            return schemas

        # Ensure the parent of watchfuls is on sys.path so
        # ``import watchfuls.<name>`` works.
        parent = os.path.dirname(watchfuls_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        # Collect package-based module names (folder with __init__.py).
        entries: list[str] = []
        for entry in sorted(os.listdir(watchfuls_dir)):
            if entry.startswith('_'):
                continue
            entry_path = os.path.join(watchfuls_dir, entry)
            if (os.path.isdir(entry_path) and
                    os.path.isfile(os.path.join(entry_path, '__init__.py'))):
                entries.append(entry)

        for mod_name in entries:
            fq = f'watchfuls.{mod_name}'
            mod_dir = os.path.join(watchfuls_dir, mod_name)
            try:
                mod = importlib.import_module(fq)
            except Exception:                           # pragma: no cover
                continue
            watchful_cls = getattr(mod, 'Watchful', None)
            if watchful_cls is None:
                continue

            # Read schema.json from disk on every call so changes take effect
            # without a server restart (bypasses the module-level import cache).
            schema_path = os.path.join(mod_dir, 'schema.json')
            if os.path.isfile(schema_path):
                try:
                    with open(schema_path, encoding='utf-8') as _f:
                        item_schema = json.load(_f)
                except Exception:                       # pragma: no cover
                    item_schema = getattr(watchful_cls, 'ITEM_SCHEMA', None)
            else:
                item_schema = getattr(watchful_cls, 'ITEM_SCHEMA', None)
            if not item_schema or not isinstance(item_schema, dict):
                continue
            info = cls._load_module_info(mod_dir)
            lang_data = cls._load_module_langs(mod_dir)

            supported_platforms = getattr(watchful_cls, 'SUPPORTED_PLATFORMS', None)
            platform_unsupported = (
                isinstance(supported_platforms, (list, tuple)) and
                sys.platform not in supported_platforms
            )
            missing_deps  = list(getattr(watchful_cls, 'MISSING_DEPS',  None) or [])
            partial_deps  = list(getattr(watchful_cls, 'PARTIAL_DEPS',  None) or [])

            for collection, fields in item_schema.items():
                if collection in ('__i18n__', '__icon__', '__host_profile__', '__host_multiple__',
                                   '__host_multiple_bind__', '__overview_widget__',
                                   '__credential__', '__credentials__', '__status_render__',
                                   '__entraid_provision__', '__page__', '__backup_part__'):
                    # __i18n__ handled separately; __host_profile__/__host_multiple__
                    # are host-binding metadata; __credential__ is consumed by the
                    # central credentials catalog (credential_schemas reads it from
                    # schema.json directly); __status_render__ is read by
                    # module_status_render() — none of these are renderable
                    # collections, so keep them out of ITEM_SCHEMAS.
                    continue
                col_fields = dict(fields)
                # Stamp each ModuleBase field's section `group` (e.g. threads/
                # timeout → 'execution') so schemas don't repeat it and the UI
                # stays generic. A field's own explicit `group` always wins.
                if collection == '__module__':
                    for _ifk, _ifspec in cls._MODULE_FIELDS.items():
                        _grp = _ifspec.get('group')
                        _ifm = col_fields.get(_ifk)
                        if _grp and isinstance(_ifm, dict) and not _ifm.get('group'):
                            col_fields[_ifk] = {**_ifm, 'group': _grp}
                # Merge label_i18n from lang files.
                # Sub-collection fields (type='sub_collection') are rendered as
                # nested collections, not as scalar form fields, so they do not
                # receive label_i18n here (their title comes from lang.collections).
                if lang_data:
                    for field_key, field_meta in list(col_fields.items()):
                        if (isinstance(field_meta, dict) and 'type' in field_meta
                                and field_meta.get('type') != 'sub_collection'):
                            label_i18n = {
                                lc: ld['labels'][field_key]
                                for lc, ld in lang_data.items()
                                if field_key in ld.get('labels', {})
                            }
                            if label_i18n:
                                col_fields[field_key] = {**field_meta, 'label_i18n': label_i18n}
                # Mark fields whose supported_platforms excludes the current platform.
                for _fk, _fm in list(col_fields.items()):
                    if _fk.startswith('__'):
                        continue
                    if isinstance(_fm, dict) and 'supported_platforms' in _fm:
                        _fplats = _fm['supported_platforms']
                        if isinstance(_fplats, (list, tuple)) and sys.platform not in _fplats:
                            col_fields[_fk] = {**_fm, '__unsupported__': True}
                if platform_unsupported:
                    col_fields['__unsupported__'] = True
                # Missing optional dependencies — mark module as unavailable and
                # carry the package list so the UI can show an install hint.
                if missing_deps:
                    col_fields['__unsupported__'] = True
                    col_fields['__missing_deps__'] = missing_deps
                # Partial dependencies — module still works but some features/backends
                # are degraded. Only set when not already fully disabled.
                elif partial_deps:
                    col_fields['__partial_deps__'] = partial_deps
                # Per-option dependency check: cross-reference each field's
                # options_deps dict with the set of unavailable packages so the
                # UI can disable specific select options instead of the whole module.
                _unavail = set(missing_deps + partial_deps)
                if _unavail:
                    for _fk, _fm in list(col_fields.items()):
                        if _fk.startswith('__'):
                            continue
                        if not (isinstance(_fm, dict) and 'options_deps' in _fm):
                            continue
                        _disabled = {
                            opt: pkg
                            for opt, pkg in _fm['options_deps'].items()
                            if pkg in _unavail
                        }
                        if _disabled:
                            col_fields[_fk] = {**_fm, 'options_disabled': _disabled}
                schemas[f'{mod_name}|{collection}'] = col_fields

                # Register sub-collection schemas.
                # Any field with type='sub_collection' in a collection is itself a
                # nested item collection.  Its item schema is registered under
                # 'mod|collection|sub_key' so the JS _schemaKeyOf() helper can find
                # it at paths like 'snmp|servers|router_1|checks'.
                for _sc_key, _sc_val in list(col_fields.items()):
                    if _sc_key.startswith('__') or not isinstance(_sc_val, dict):
                        continue
                    if _sc_val.get('type') != 'sub_collection':
                        continue
                    _sub_fields = dict(_sc_val)
                    # Apply label_i18n to the sub-collection's own item fields.
                    if lang_data:
                        for _sf_key, _sf_meta in list(_sub_fields.items()):
                            if (isinstance(_sf_meta, dict) and 'type' in _sf_meta
                                    and _sf_meta.get('type') != 'sub_collection'):
                                _lbl_i18n = {
                                    lc: ld['labels'][_sf_key]
                                    for lc, ld in lang_data.items()
                                    if _sf_key in ld.get('labels', {})
                                }
                                if _lbl_i18n:
                                    _sub_fields[_sf_key] = {**_sf_meta, 'label_i18n': _lbl_i18n}
                    if missing_deps:
                        _sub_fields['__unsupported__'] = True
                        _sub_fields['__missing_deps__'] = missing_deps
                    schemas[f'{mod_name}|{collection}|{_sc_key}'] = _sub_fields

            _module_key = f'{mod_name}|__module__'

            # Propagate declared UI capabilities (legacy — kept for compatibility).
            #   WATCHFUL_UI: frozenset[str] = frozenset({'file_manager', ...})
            _ui_caps = getattr(watchful_cls, 'WATCHFUL_UI', None)
            if _ui_caps and _module_key in schemas:
                schemas[_module_key]['__ui__'] = sorted(_ui_caps)

            # Propagate toolbar button declarations so the dashboard renders them
            # generically without any module-specific logic.  A module opts in by:
            #   WATCHFUL_TOOLBAR: tuple[dict, ...] = (
            #       {'icon': 'bi-...', 'label_key': '...', 'onclick': 'jsFnName'},
            #   )
            _toolbar = getattr(watchful_cls, 'WATCHFUL_TOOLBAR', None)
            if _toolbar and _module_key in schemas:
                schemas[_module_key]['__toolbar__'] = [
                    {k: str(v) for k, v in btn.items()} for btn in _toolbar
                ]

            # Module icon (``__icon__``, a Bootstrap class) — language-agnostic, so
            # exposed as its own entry; consumed by moduleIcon() in the panel AND by
            # the public status page, so both show the module's declared icon.
            _decl_icon = item_schema.get('__icon__')
            if isinstance(_decl_icon, str) and _decl_icon.strip():
                schemas[f'{mod_name}|__icon__'] = _decl_icon.strip()

            # Build __i18n__ entry.
            if info or lang_data:
                icon = info.get('icon', '\U0001f4e6')
                _skip = {'pretty_name', 'labels'}
                i18n = {
                    lc: {
                        'pretty_name': ld.get('pretty_name', mod_name),
                        'icon': icon,
                        **{k: v for k, v in ld.items() if k not in _skip},
                    }
                    for lc, ld in lang_data.items()
                }
                # Supply the labels for ModuleBase's own module-pane sections
                # (Execution / Defaults) via the same group_labels channel the UI
                # already reads; a module's own group_labels for the same key win.
                from lib.i18n import translate as _tr  # local import: avoid cycle
                for lc, entry in i18n.items():
                    _core_gl = {g: _tr(lc, key) for g, key in cls._MODULE_SECTION_LABELS.items()}
                    entry['group_labels'] = {**_core_gl, **(entry.get('group_labels') or {})}
                if i18n:
                    schemas[f'{mod_name}|__i18n__'] = i18n

        return schemas

    @staticmethod
    def _load_module_info(module_dir: str) -> dict:
        """Load ``info.json`` from a folder-based module directory."""
        path = os.path.join(module_dir, 'info.json')
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as fh:
                return json.load(fh)
        return {}

    @staticmethod
    def _load_module_langs(module_dir: str) -> dict[str, dict]:
        """Load all ``lang/*.json`` files from a folder-based module directory."""
        lang_dir = os.path.join(module_dir, 'lang')
        result: dict[str, dict] = {}
        if not os.path.isdir(lang_dir):
            return result
        for fname in sorted(os.listdir(lang_dir)):
            if fname.endswith('.json') and not fname.startswith('_'):
                lang_code = fname[:-5]
                with open(os.path.join(lang_dir, fname), encoding='utf-8') as fh:
                    result[lang_code] = json.load(fh)
        return result