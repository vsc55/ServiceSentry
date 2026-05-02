#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Monitor._get_enabled_modules and check_module."""

import os

import pytest

from lib import Monitor


# ──────────────────────────── Fixtures ────────────────────────────


@pytest.fixture()
def monitor(tmp_path):
    """Monitor with empty config and var dirs pointing at tmp_path."""
    config_dir = str(tmp_path / "config")
    var_dir = str(tmp_path / "var")
    os.makedirs(config_dir, exist_ok=True)
    os.makedirs(var_dir, exist_ok=True)
    modules_dir = str(tmp_path / "watchfuls")
    os.makedirs(modules_dir, exist_ok=True)
    return Monitor(str(tmp_path), config_dir, modules_dir, var_dir)


def _make_package_module(modules_dir, name, enabled_cfg=None):
    """Create a minimal package-based watchful module under *modules_dir*."""
    mod_dir = os.path.join(modules_dir, name)
    os.makedirs(mod_dir, exist_ok=True)
    init_path = os.path.join(mod_dir, "__init__.py")
    with open(init_path, "w", encoding="utf-8") as fh:
        fh.write(
            "from lib.modules import ModuleBase, ReturnModuleCheck\n\n"
            "class Watchful(ModuleBase):\n"
            "    ITEM_SCHEMA = {'list': {'enabled': {'type': 'bool', 'default': True}}}\n"
            "    def check(self):\n"
            "        r = ReturnModuleCheck()\n"
            "        r.set('item1', True, 'ok')\n"
            "        return r\n"
        )
    return mod_dir


# ──────────────────── _get_enabled_modules ────────────────────────


class TestGetEnabledModules:
    """Unit tests for Monitor._get_enabled_modules."""

    def test_empty_dir_returns_empty(self, monitor):
        assert monitor._get_enabled_modules() == []

    def test_none_modules_dir_returns_empty(self, monitor):
        monitor._modules_dir = None
        assert monitor._get_enabled_modules() == []

    def test_discovers_package_module(self, monitor):
        _make_package_module(monitor.dir_modules, "alpha")
        result = monitor._get_enabled_modules()
        assert "alpha" in result

    def test_discovers_multiple_package_modules(self, monitor):
        for name in ("alpha", "beta", "gamma"):
            _make_package_module(monitor.dir_modules, name)
        result = monitor._get_enabled_modules()
        assert set(result) == {"alpha", "beta", "gamma"}

    def test_ignores_dir_without_init(self, monitor):
        """A subdirectory with no __init__.py is not a module."""
        bare_dir = os.path.join(monitor.dir_modules, "notamodule")
        os.makedirs(bare_dir, exist_ok=True)
        assert monitor._get_enabled_modules() == []

    def test_ignores_dunder_dirs(self, monitor):
        """Directories starting with __ are skipped."""
        dunder = os.path.join(monitor.dir_modules, "__pycache__")
        os.makedirs(dunder, exist_ok=True)
        open(os.path.join(dunder, "__init__.py"), "w").close()
        assert monitor._get_enabled_modules() == []

    def test_respects_enabled_false_in_config(self, monitor):
        """Modules explicitly disabled in config are excluded."""
        _make_package_module(monitor.dir_modules, "disabled_mod")
        monitor.config_modules.data = {"disabled_mod": {"enabled": False}}
        result = monitor._get_enabled_modules()
        assert "disabled_mod" not in result

    def test_respects_enabled_true_in_config(self, monitor):
        """Modules explicitly enabled in config are included."""
        _make_package_module(monitor.dir_modules, "enabled_mod")
        monitor.config_modules.data = {"enabled_mod": {"enabled": True}}
        result = monitor._get_enabled_modules()
        assert "enabled_mod" in result

    def test_flat_py_files_are_not_discovered(self, monitor):
        """Legacy flat .py files are no longer supported and must be ignored."""
        flat = os.path.join(monitor.dir_modules, "legacy_module.py")
        with open(flat, "w", encoding="utf-8") as fh:
            fh.write("class Watchful: pass\n")
        assert monitor._get_enabled_modules() == []


# ──────────────────────────── check_module ─────────────────────────


class TestCheckModule:
    """Unit tests for Monitor.check_module."""

    def test_check_module_returns_result(self, monitor):
        """check_module on a package module present in sys.path returns success."""
        import sys

        # Ensure dir_modules is on sys.path so importlib finds 'mymod'
        if monitor.dir_modules not in sys.path:
            sys.path.insert(0, monitor.dir_modules)

        _make_package_module(monitor.dir_modules, "mymod")
        try:
            success, name, data = monitor.check_module("mymod")
            assert success is True
            assert name == "mymod"
            from lib.modules import ReturnModuleCheck
            assert isinstance(data, ReturnModuleCheck)
            assert "item1" in data.list
        finally:
            sys.path = [p for p in sys.path if p != monitor.dir_modules]
            # Remove cached import so it doesn't pollute other tests
            import sys as _sys
            _sys.modules.pop("mymod", None)

    def test_check_module_bad_name_returns_false(self, monitor):
        """check_module with a non-existent module returns (False, name, None)."""
        success, name, data = monitor.check_module("nonexistent_xyz_module")
        assert success is False
        assert name == "nonexistent_xyz_module"
        assert data is None
