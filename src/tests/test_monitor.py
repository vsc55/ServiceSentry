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


class TestMonitorAudit:
    """Monitor system events must land in the SAME audit table the web admin
    uses (shared DB), not in a separate audit.json file."""

    def test_audit_system_writes_to_db(self, monitor):
        assert monitor._audit_store is not None
        monitor._audit_system('module_check_timeout', {'module': 'x', 'timeout': 120})
        rows = monitor._db.fetchall(
            "SELECT event, user, ip FROM audit WHERE event = 'module_check_timeout'")
        assert rows and rows[-1] == ('module_check_timeout', 'system', 'internal')
        # No audit.json was created (DB path succeeded).
        assert not os.path.isfile(os.path.join(monitor.dir_config, 'audit.json'))

    def test_audit_system_falls_back_to_file(self, monitor):
        # Simulate a DB failure → the event must still be recorded somewhere.
        monitor._audit_store = None
        monitor._audit_system('module_check_error', {'module': 'y'})
        assert os.path.isfile(os.path.join(monitor.dir_config, 'audit.json'))


class TestCheckStatePersistence:
    """The persistent check_state table is the authoritative baseline for
    change detection, so restarts don't re-fire notifications, and the very
    first sight of a check is recorded silently."""

    @staticmethod
    def _result(key, status, msg='m'):
        from lib.modules import ReturnModuleCheck
        r = ReturnModuleCheck()
        r.set(key, status, msg)
        return r

    def test_first_record_notifies_and_persists(self, monitor, monkeypatch):
        sent = []
        monkeypatch.setattr(monitor, 'send_message', lambda m, s=None: sent.append((m, s)))
        # With no prior records, the first change announces the current state.
        monitor._process_module_result('mod', self._result('k', False, 'down'))
        assert sent == [('down', False)]
        # ... and saving persists it to the check_state table.
        monitor.status.save()
        assert monitor._check_state_store.get_all()[('mod', 'k', '')]['status'] is False

    def test_unchanged_state_is_silent(self, monitor, monkeypatch):
        sent = []
        monkeypatch.setattr(monitor, 'send_message', lambda m, s=None: sent.append((m, s)))
        monitor._process_module_result('mod', self._result('k', True, 'ok'))   # first → notifies
        monitor._process_module_result('mod', self._result('k', True, 'ok'))   # unchanged → silent
        monitor._process_module_result('mod', self._result('k', False, 'dn'))  # transition → notifies
        assert sent == [('ok', True), ('dn', False)]

    def test_state_survives_restart(self, monitor, monkeypatch):
        # Record an OK state and persist it to the DB.
        monitor._process_module_result('mod', self._result('k', True, 'ok'))
        monitor.status.save()
        assert monitor._check_state_store.get_all()[('mod', 'k', '')]['status'] is True

        # A fresh Monitor on the same var dir (same DB) loads the baseline.
        m2 = Monitor(monitor.dir_base, monitor.dir_config, monitor.dir_modules, monitor.dir_var)
        assert m2.status.get_conf(['mod', 'k', 'status'], None) is True
        # The same OK result must NOT re-announce after the restart.
        sent = []
        monkeypatch.setattr(m2, 'send_message', lambda msg, s=None: sent.append(msg))
        m2._process_module_result('mod', self._result('k', True, 'ok'))
        assert sent == []

    def test_clear_status_also_clears_state(self, monitor):
        monitor._process_module_result('mod', self._result('k', True, 'ok'))
        monitor.status.save()
        assert monitor._check_state_store.get_all()
        monitor.clear_status()
        assert monitor._check_state_store.get_all() == {}

    def test_maintenance_purges_live_state(self, monitor):
        # An item bound to host H1, with a recorded live status.
        monitor.config_modules.data = {'mod': {'list': {'item1': {'host_uid': 'H1'}}}}
        monitor._process_module_result('mod', self._result('item1', True, 'ok'))
        monitor.status.save()
        assert ('mod', 'item1', '') in monitor._check_state_store.get_all()

        # H1 enters maintenance → its live state must be purged (history kept).
        class _FakeHosts:
            def list(self, decrypt=False):   # noqa: D401, ARG002
                return [{'uid': 'H1', 'maintenance': True}]
        monitor._hosts_store = _FakeHosts()
        monitor.purge_maintenance_states()

        assert ('mod', 'item1', '') not in monitor._check_state_store.get_all()
        assert not isinstance(monitor.status.get_conf(['mod', 'item1', 'status'], None), bool)

    def test_derived_key_split_into_metric(self, monitor):
        # ram_swap-style: one item (keyed by its uid), two derived result keys.
        # Each is stored as key=<uid> + metric=ram/swap, not "<uid>_ram".
        monitor.config_modules.data = {'ram_swap': {'list': {'U-1': {'uid': 'U-1'}}}}
        monitor._process_module_result('ram_swap', self._result('U-1_ram', True, 'ok'))
        monitor._process_module_result('ram_swap', self._result('U-1_swap', False, 'hi'))
        monitor.status.save()
        states = monitor._check_state_store.get_all()
        assert states[('ram_swap', 'U-1', 'ram')]['item_uid'] == 'U-1'
        assert states[('ram_swap', 'U-1', 'swap')]['item_uid'] == 'U-1'
        # The monitor still sees the full result keys (reconstructed).
        assert isinstance(monitor.status.get_conf(['ram_swap', 'U-1_ram', 'status'], None), bool)

    def test_item_key_with_underscore_is_not_split(self, monitor):
        # An item key containing '_' must NOT be split into a bogus metric.
        monitor.config_modules.data = {'mod': {'list': {'item_1': {'uid': 'item_1'}}}}
        monitor._process_module_result('mod', self._result('item_1', True, 'ok'))
        monitor.status.save()
        row = monitor._check_state_store.get_all()[('mod', 'item_1', '')]
        assert row['item_uid'] == 'item_1' and row['metric'] == ''


class TestFailStreak:
    """ModuleBase.fail_streak persists in the monitor status store and flags
    the monitor so status.json is saved even without a status flip."""

    def test_streak_persists_and_marks_dirty(self, monitor):
        _make_package_module(monitor.dir_modules, "streaky")
        import sys
        if monitor.dir_modules not in sys.path:
            sys.path.insert(0, monitor.dir_modules)
        try:
            import importlib
            mod = importlib.import_module("streaky")
            monitor._status_counts_dirty = False
            w1 = mod.Watchful(monitor)
            assert w1.fail_streak('k', True) == 1
            assert monitor._status_counts_dirty is True
            # Fresh instance, same monitor (next cycle) → streak continues.
            w2 = mod.Watchful(monitor)
            assert w2.fail_streak('k', True) == 2
            assert w2.fail_streak('k', False) == 0   # recovery resets
        finally:
            sys.path = [p for p in sys.path if p != monitor.dir_modules]
            sys.modules.pop("streaky", None)
