#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests: validate all real watchful modules are structurally sound.

These tests verify that every module under watchfuls/ can be:
  - discovered by Monitor._get_enabled_modules
  - imported without errors
  - has a valid Watchful class with ITEM_SCHEMA
  - has a valid info.json (name, version, description, icon, dependencies)
  - has valid lang/*.json files (pretty_name, labels keys)
  - contributes __i18n__ entries via discover_schemas
  - contributes schema entries via discover_schemas, with the correct field types
"""

import importlib
import json
import os
import sys

import pytest

# ──────────────────────────── Paths ───────────────────────────────

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WATCHFULS_DIR = os.path.join(_SRC_DIR, "watchfuls")

# Ensure watchfuls parent is importable
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# ──────────────────────── Helpers ─────────────────────────────────

def _real_module_names():
    """Return sorted list of real package-based module names in watchfuls/."""
    names = []
    for entry in sorted(os.listdir(_WATCHFULS_DIR)):
        if entry.startswith("_"):
            continue
        entry_path = os.path.join(_WATCHFULS_DIR, entry)
        if os.path.isdir(entry_path) and os.path.isfile(
            os.path.join(entry_path, "__init__.py")
        ):
            names.append(entry)
    return names


_MODULE_NAMES = _real_module_names()

# ──────────────────── Module discovery ────────────────────────────


class TestRealModuleDiscovery:
    """Monitor._get_enabled_modules finds all real watchful modules."""

    @pytest.fixture(autouse=True)
    def _monitor(self, tmp_path):
        from lib import Monitor

        config_dir = str(tmp_path / "config")
        var_dir = str(tmp_path / "var")
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(var_dir, exist_ok=True)
        self.monitor = Monitor(
            str(tmp_path), config_dir, _WATCHFULS_DIR, var_dir
        )

    def test_discovers_all_expected_modules(self):
        found = self.monitor._get_enabled_modules()
        for mod in _MODULE_NAMES:
            assert mod in found, f"Module '{mod}' not discovered by _get_enabled_modules"

    def test_no_extra_unexpected_entries(self):
        """Only known package modules are returned — no __pycache__ or .py files."""
        found = self.monitor._get_enabled_modules()
        for name in found:
            assert not name.startswith("__"), f"Dunder entry leaked: {name}"
            assert not name.endswith(".py"), f"Flat .py file leaked: {name}"


# ──────────────────── Module importability ────────────────────────


class TestRealModuleImport:
    """Every real watchful module imports cleanly and exposes Watchful."""

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_module_imports(self, mod_name):
        fq = f"watchfuls.{mod_name}"
        try:
            mod = importlib.import_module(fq)
        except Exception as exc:
            pytest.fail(f"watchfuls.{mod_name} failed to import: {exc}")
        assert hasattr(mod, "Watchful"), (
            f"watchfuls.{mod_name} has no Watchful class"
        )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_watchful_has_item_schema(self, mod_name):
        mod = importlib.import_module(f"watchfuls.{mod_name}")
        schema = getattr(mod.Watchful, "ITEM_SCHEMA", None)
        assert schema is not None, f"{mod_name}.Watchful has no ITEM_SCHEMA"
        assert isinstance(schema, dict), f"{mod_name}.ITEM_SCHEMA is not a dict"
        assert len(schema) > 0, f"{mod_name}.ITEM_SCHEMA is empty"

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_item_schema_collections_are_dicts(self, mod_name):
        """Each collection inside ITEM_SCHEMA must be a dict of field definitions."""
        mod = importlib.import_module(f"watchfuls.{mod_name}")
        schema = mod.Watchful.ITEM_SCHEMA
        for collection, fields in schema.items():
            if collection.startswith("__"):
                # dunder metadata (i18n, host profile/multiple, credential…),
                # not a renderable collection of field defs.
                continue
            assert isinstance(fields, dict), (
                f"{mod_name}.ITEM_SCHEMA['{collection}'] is not a dict"
            )
            for field_key, field_meta in fields.items():
                if field_key.startswith('__'):
                    continue  # dunder metadata keys (e.g. __discovery__) are not field defs
                if not isinstance(field_meta, dict):
                    continue  # scalar metadata (e.g. api_ver) are not field defs
                assert isinstance(field_meta, dict), (
                    f"{mod_name}.ITEM_SCHEMA['{collection}']['{field_key}'] "
                    f"is not a dict (got {type(field_meta).__name__})"
                )
                assert "type" in field_meta, (
                    f"{mod_name}.ITEM_SCHEMA['{collection}']['{field_key}'] "
                    f"is missing 'type' key"
                )


# ──────────────────── info.json integrity ─────────────────────────


class TestRealModuleInfoJson:
    """Every real watchful module has a valid info.json."""

    _REQUIRED_KEYS = {"name", "version", "description", "icon", "dependencies"}

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_info_json_exists(self, mod_name):
        path = os.path.join(_WATCHFULS_DIR, mod_name, "info.json")
        assert os.path.isfile(path), f"{mod_name}/info.json not found"

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_info_json_is_valid_json(self, mod_name):
        path = os.path.join(_WATCHFULS_DIR, mod_name, "info.json")
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            pytest.fail(f"{mod_name}/info.json is not valid JSON: {exc}")
        assert isinstance(data, dict), f"{mod_name}/info.json root must be a dict"

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_info_json_has_required_keys(self, mod_name):
        path = os.path.join(_WATCHFULS_DIR, mod_name, "info.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        missing = self._REQUIRED_KEYS - data.keys()
        assert not missing, (
            f"{mod_name}/info.json missing keys: {missing}"
        )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_info_json_name_is_nonempty_string(self, mod_name):
        path = os.path.join(_WATCHFULS_DIR, mod_name, "info.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert isinstance(data.get("name"), str) and data["name"].strip(), (
            f"{mod_name}/info.json 'name' must be a non-empty string"
        )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_info_json_icon_is_nonempty_string(self, mod_name):
        path = os.path.join(_WATCHFULS_DIR, mod_name, "info.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert isinstance(data.get("icon"), str) and data["icon"].strip(), (
            f"{mod_name}/info.json 'icon' must be a non-empty string"
        )


# ──────────────────── lang/*.json integrity ───────────────────────


class TestRealModuleLangFiles:
    """Every real watchful module has valid lang/*.json files."""

    _EXPECTED_LOCALES = {"en_EN.json", "es_ES.json"}
    _REQUIRED_LANG_KEYS = {"pretty_name", "labels"}

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_lang_dir_exists(self, mod_name):
        lang_dir = os.path.join(_WATCHFULS_DIR, mod_name, "lang")
        assert os.path.isdir(lang_dir), f"{mod_name}/lang/ directory not found"

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_expected_locales_present(self, mod_name):
        lang_dir = os.path.join(_WATCHFULS_DIR, mod_name, "lang")
        found = {f for f in os.listdir(lang_dir) if f.endswith(".json")}
        missing = self._EXPECTED_LOCALES - found
        assert not missing, (
            f"{mod_name}/lang/ missing locale files: {missing}"
        )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_lang_files_are_valid_json(self, mod_name):
        lang_dir = os.path.join(_WATCHFULS_DIR, mod_name, "lang")
        for fname in os.listdir(lang_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(lang_dir, fname)
            try:
                with open(path, encoding="utf-8") as fh:
                    json.load(fh)
            except json.JSONDecodeError as exc:
                pytest.fail(f"{mod_name}/lang/{fname} is not valid JSON: {exc}")

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_lang_files_have_required_keys(self, mod_name):
        lang_dir = os.path.join(_WATCHFULS_DIR, mod_name, "lang")
        for fname in os.listdir(lang_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(lang_dir, fname)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            missing = self._REQUIRED_LANG_KEYS - data.keys()
            assert not missing, (
                f"{mod_name}/lang/{fname} missing keys: {missing}"
            )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_lang_pretty_name_is_nonempty_string(self, mod_name):
        lang_dir = os.path.join(_WATCHFULS_DIR, mod_name, "lang")
        for fname in os.listdir(lang_dir):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(lang_dir, fname), encoding="utf-8") as fh:
                data = json.load(fh)
            assert isinstance(data.get("pretty_name"), str) and data["pretty_name"].strip(), (
                f"{mod_name}/lang/{fname} 'pretty_name' must be a non-empty string"
            )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_lang_labels_is_dict(self, mod_name):
        lang_dir = os.path.join(_WATCHFULS_DIR, mod_name, "lang")
        for fname in os.listdir(lang_dir):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(lang_dir, fname), encoding="utf-8") as fh:
                data = json.load(fh)
            assert isinstance(data.get("labels"), dict), (
                f"{mod_name}/lang/{fname} 'labels' must be a dict"
            )


# ──────────────────── discover_schemas integration ────────────────


class TestDiscoverSchemasRealModules:
    """discover_schemas loads schemas AND i18n from all real modules."""

    @pytest.fixture(autouse=True)
    def _schemas(self):
        from lib.modules import ModuleBase
        self.schemas = ModuleBase.discover_schemas(_WATCHFULS_DIR)

    def test_returns_non_empty(self):
        assert len(self.schemas) > 0

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_module_has_at_least_one_schema_collection(self, mod_name):
        keys = [k for k in self.schemas if k.startswith(f"{mod_name}|") and "__i18n__" not in k]
        assert keys, f"discover_schemas returned no schema collections for '{mod_name}'"

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_module_has_i18n_entry(self, mod_name):
        key = f"{mod_name}|__i18n__"
        assert key in self.schemas, (
            f"discover_schemas missing __i18n__ entry for '{mod_name}'"
        )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_i18n_entry_has_expected_locales(self, mod_name):
        i18n = self.schemas[f"{mod_name}|__i18n__"]
        for locale in ("en_EN", "es_ES"):
            assert locale in i18n, (
                f"{mod_name}|__i18n__ missing locale '{locale}'"
            )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_i18n_pretty_name_populated(self, mod_name):
        i18n = self.schemas[f"{mod_name}|__i18n__"]
        for locale, entry in i18n.items():
            assert entry.get("pretty_name"), (
                f"{mod_name}|__i18n__[{locale}] has empty 'pretty_name'"
            )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_i18n_icon_populated(self, mod_name):
        i18n = self.schemas[f"{mod_name}|__i18n__"]
        for locale, entry in i18n.items():
            assert entry.get("icon"), (
                f"{mod_name}|__i18n__[{locale}] has empty 'icon'"
            )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_schema_fields_have_label_i18n_when_lang_exists(self, mod_name):
        """Schema fields must carry label_i18n entries loaded from lang/ files."""
        schema_keys = [
            k for k in self.schemas
            if k.startswith(f"{mod_name}|") and not k.split('|', 1)[1].startswith('__')
        ]
        for sk in schema_keys:
            for field_key, field_meta in self.schemas[sk].items():
                if field_key.startswith('__') or not isinstance(field_meta, dict):
                    continue
                # Sub-collection fields are rendered as nested collections, not as
                # scalar form fields — their title comes from lang.collections, so
                # they intentionally have no label_i18n on the parent schema entry.
                if field_meta.get('type') == 'sub_collection':
                    continue
                # Hidden fields are never rendered, so they need no display label.
                if field_meta.get('hidden'):
                    continue
                assert "label_i18n" in field_meta, (
                    f"{sk}['{field_key}'] missing 'label_i18n' "
                    f"(lang/ files exist but labels not merged)"
                )


# ──────────────────── WATCHFUL_ACTIONS integrity ──────────────────


# Modules known to expose web actions — maps module name to expected actions.
_EXPECTED_ACTIONS: dict[str, frozenset] = {
    'datastore':       frozenset({'test_connection', 'list_databases'}),
    'filesystemusage': frozenset({'discover'}),
    'service_status':  frozenset({'discover'}),
    'temperature':     frozenset({'discover'}),
}


class TestWatchfulActions:
    """WATCHFUL_ACTIONS is correctly declared on every module."""

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_watchful_actions_is_frozenset(self, mod_name):
        """WATCHFUL_ACTIONS must be a frozenset (or absent on base-only modules)."""
        mod = importlib.import_module(f"watchfuls.{mod_name}")
        actions = getattr(mod.Watchful, 'WATCHFUL_ACTIONS', None)
        if actions is not None:
            assert isinstance(actions, frozenset), (
                f"{mod_name}.Watchful.WATCHFUL_ACTIONS must be a frozenset, "
                f"got {type(actions).__name__}"
            )

    @pytest.mark.parametrize("mod_name,expected", list(_EXPECTED_ACTIONS.items()))
    def test_expected_actions_declared(self, mod_name, expected):
        """Modules that expose web actions must declare the correct WATCHFUL_ACTIONS."""
        mod = importlib.import_module(f"watchfuls.{mod_name}")
        actions = getattr(mod.Watchful, 'WATCHFUL_ACTIONS', frozenset())
        assert actions == expected, (
            f"{mod_name}.Watchful.WATCHFUL_ACTIONS = {actions!r}, "
            f"expected {expected!r}"
        )

    @pytest.mark.parametrize("mod_name,expected", list(_EXPECTED_ACTIONS.items()))
    def test_action_methods_exist(self, mod_name, expected):
        """Every action in WATCHFUL_ACTIONS must be a callable classmethod."""
        mod = importlib.import_module(f"watchfuls.{mod_name}")
        for action in expected:
            method = getattr(mod.Watchful, action, None)
            assert callable(method), (
                f"{mod_name}.Watchful.{action} is in WATCHFUL_ACTIONS "
                f"but is not callable"
            )


# ──────────────── runtime / system-wiring contract ─────────────────

def _load_schema(mod_name: str) -> dict:
    """The module's schema.json as a dict (empty when missing/invalid)."""
    sp = os.path.join(_WATCHFULS_DIR, mod_name, "schema.json")
    if not os.path.isfile(sp):
        return {}
    try:
        with open(sp, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


class TestRealModuleRuntimeContract:
    """Beyond static metadata: every real module must WIRE INTO the running
    system.  Generic (discovery-driven) so a NEW module is covered automatically —
    no per-module test to write.  This is the layer the recent regressions slipped
    past (a module that doesn't run, or isn't exposed in a catalog)."""

    @pytest.fixture(autouse=True)
    def _monitor(self, tmp_path):
        from lib import Monitor
        config_dir = str(tmp_path / "config")
        var_dir = str(tmp_path / "var")
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(var_dir, exist_ok=True)
        if _SRC_DIR not in sys.path:
            sys.path.insert(0, _SRC_DIR)
        self.monitor = Monitor(str(tmp_path), config_dir, _WATCHFULS_DIR, var_dir)

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_instantiates_and_check_runs_on_empty_config(self, mod_name):
        """The system can build each module against a Monitor and run check() on
        an EMPTY config without raising — returning the ReturnModuleCheck contract.
        Catches modules that crash on load / init / empty-config (i.e. that the
        monitor cannot actually execute)."""
        from contextlib import nullcontext
        from unittest.mock import patch
        from lib.modules import ReturnModuleCheck
        cls = importlib.import_module(f"watchfuls.{mod_name}").Watchful
        # Neutralise heavy startup hooks generically (e.g. snmp MIB compilation).
        ctx = (patch.object(cls, "_startup_compile_mibs", return_value=None)
               if hasattr(cls, "_startup_compile_mibs") else nullcontext())
        with ctx:
            result = cls(self.monitor).check()
        assert isinstance(result, ReturnModuleCheck), (
            f"{mod_name}.check() did not return a ReturnModuleCheck"
        )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_declared_credential_type_is_in_catalog(self, mod_name):
        """A module that declares a __credential__ type must be exposed by the
        central credential catalog (so the manager can create/edit it)."""
        from lib.credential_schemas import credential_schemas
        decl = _load_schema(mod_name).get("__credential__") or \
            _load_schema(mod_name).get("__credentials__")
        if not decl:
            pytest.skip("module declares no credential type")
        cat = credential_schemas(_WATCHFULS_DIR)
        for spec in ([decl] if isinstance(decl, dict) else decl):
            ctype = isinstance(spec, dict) and str(spec.get("type") or "").strip()
            if ctype and ctype != "ssh":
                assert ctype in cat, (
                    f"{mod_name} credential type '{ctype}' missing from catalog"
                )

    @pytest.mark.parametrize("mod_name", _MODULE_NAMES)
    def test_host_capable_module_is_exposed_in_catalogs(self, mod_name):
        """A module that declares a __host_profile__ must be exposed by the host
        catalogs the UI/monitor rely on: the multi-bind flag (which enumerates
        every host-capable module) and at least one host-bindable collection.
        (module_host_fields legitimately omits modules that hide no fields, e.g.
        web's visible 'url', so it is NOT the right catalog to assert here.)"""
        from lib.hosts.profiles import module_host_collections, module_host_multi_bind
        if not _load_schema(mod_name).get("__host_profile__"):
            pytest.skip("module is not host-capable")
        mb = module_host_multi_bind()
        assert mod_name in mb and isinstance(mb[mod_name], bool), (
            f"{mod_name} missing a multi-bind flag in module_host_multi_bind()"
        )
        assert module_host_collections().get(mod_name), (
            f"{mod_name} host-capable but has no host-bindable collection"
        )
