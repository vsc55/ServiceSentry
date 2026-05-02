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
            if collection == "__i18n__":
                continue
            assert isinstance(fields, dict), (
                f"{mod_name}.ITEM_SCHEMA['{collection}'] is not a dict"
            )
            for field_key, field_meta in fields.items():
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
            if k.startswith(f"{mod_name}|") and "__i18n__" not in k
        ]
        for sk in schema_keys:
            for field_key, field_meta in self.schemas[sk].items():
                if not isinstance(field_meta, dict):
                    continue
                assert "label_i18n" in field_meta, (
                    f"{sk}['{field_key}'] missing 'label_i18n' "
                    f"(lang/ files exist but labels not merged)"
                )
