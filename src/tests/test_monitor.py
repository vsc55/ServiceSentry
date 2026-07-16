#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Monitor._get_enabled_modules and check_module."""

import os
from unittest.mock import patch, MagicMock

import pytest

from lib import Monitor
from lib.modules import ReturnModuleCheck


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
    m = Monitor(str(tmp_path), config_dir, modules_dir, var_dir)
    yield m
    m.close()   # stop the Telegram sender thread so tests don't accumulate threads


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


# ──────────────────── notifier / no background thread ─────────────


class TestNotifier:
    """The monitor no longer owns a threaded Telegram client: it buffers alerts into an
    injected MonitorNotifier and spawns no background sender thread of its own."""

    def test_monitor_has_no_telegram_thread(self, monitor):
        assert not hasattr(monitor, 'tg')     # the queued Telegram client is gone
        assert monitor._notifier is None      # set by the daemon, not on construction

    def test_close_is_a_safe_noop(self, monitor):
        monitor.close()
        monitor.close()                       # idempotent, never raises
        assert monitor._notifier is None

    def test_alert_kind_mapping(self):
        from lib.services.monitoring.monitor import Monitor
        assert Monitor._alert_kind(True) == 'recovery'
        assert Monitor._alert_kind(False) == 'down'
        assert Monitor._alert_kind(False, 'warning') == 'warn'

    def test_process_result_buffers_alert(self, monitor):
        """A changed, sendable item is buffered into the notifier with the mapped kind."""
        added = []
        monitor._notifier = type('N', (), {'add': lambda self, *a: added.append(a)})()
        rmc = ReturnModuleCheck()
        rmc.set('item1', False, 'boom', send_msg=True)
        monitor._process_module_result('ping', rmc)
        assert added == [('down', 'ping', 'item1', 'boom')]

    def test_send_message_carries_module_and_item(self, monitor):
        """The ad-hoc bridge path buffers the watchful's name (Module) + friendly item."""
        added = []
        monitor._notifier = type('N', (), {'add': lambda self, *a: added.append(a)})()
        monitor.send_message('boom', False, module='ntp', item='NS1')
        assert added == [('down', 'ntp', 'NS1', 'boom')]

    def test_module_supplied_name_wins_over_uid_key(self, monitor):
        """A result carrying a friendly name shows that name, not its UID key."""
        added = []
        monitor._notifier = type('N', (), {'add': lambda self, *a: added.append(a)})()
        rmc = ReturnModuleCheck()
        rmc.set('c41dc992-uid', False, 'CPU high', send_msg=True, name='PVE02')
        monitor._process_module_result('cpu', rmc)
        assert added == [('down', 'cpu', 'PVE02', 'CPU high')]

    def test_item_label_resolves_host_uid(self, monitor):
        """The item column shows the bound host's friendly name, not the item/host UID."""
        monitor._host_name_map = {'uid-1': 'NS1'}
        # A check item bound to a host via host_uid in the module config → host name.
        monitor.config_modules = type('C', (), {
            'get_conf': lambda self, path: (
                {'list': {'chk-1': {'host_uid': 'uid-1'}}} if path == ['cpu'] else {})})()
        assert monitor._item_label('cpu', 'chk-1') == 'NS1'
        # The key itself is a host_uid (host-bound base modules) → host name.
        assert monitor._item_label('cpu', 'uid-1') == 'NS1'
        # Unknown → the key itself.
        assert monitor._item_label('cpu', 'nope') == 'nope'


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

    @staticmethod
    def _recorder(monitor):
        """Attach a recording notifier; returns the list of (kind, module, item, msg)."""
        added = []
        monitor._notifier = type('N', (), {'add': lambda self, *a: added.append(a)})()
        return added

    def test_first_record_notifies_and_persists(self, monitor):
        added = self._recorder(monitor)
        # With no prior records, the first change announces the current state.
        monitor._process_module_result('mod', self._result('k', False, 'down'))
        assert added == [('down', 'mod', 'k', 'down')]
        # ... and saving persists it to the check_state table.
        monitor.status.save()
        assert monitor._check_state_store.get_all()[('mod', 'k', '')]['status'] is False

    def test_unchanged_state_is_silent(self, monitor):
        added = self._recorder(monitor)
        monitor._process_module_result('mod', self._result('k', True, 'ok'))   # first OK → no recovery
        monitor._process_module_result('mod', self._result('k', True, 'ok'))   # unchanged → silent
        monitor._process_module_result('mod', self._result('k', False, 'dn'))  # transition → notifies
        assert added == [('down', 'mod', 'k', 'dn')]

    def test_first_seen_ok_is_not_a_recovery(self, monitor):
        """A passing check seen for the first time never 'recovered' — no spurious recovery
        (so a first cycle / manual "Run all" over many OK checks doesn't blast recoveries).
        Its state is still recorded, so a later real transition is detected."""
        added = self._recorder(monitor)
        monitor._process_module_result('mod', self._result('k', True, 'ok'))
        assert added == []                                        # suppressed
        # A real DOWN → UP transition IS a recovery.
        monitor._process_module_result('mod', self._result('k', False, 'dn'))  # → down
        monitor._process_module_result('mod', self._result('k', True, 'ok'))   # down → up = recovery
        assert added == [('down', 'mod', 'k', 'dn'), ('recovery', 'mod', 'k', 'ok')]

    def test_first_seen_down_still_notifies(self, monitor):
        """A first-seen FAILING check still announces its current state (real problem now)."""
        added = self._recorder(monitor)
        monitor._process_module_result('mod', self._result('k', False, 'down'))
        assert added == [('down', 'mod', 'k', 'down')]

    def test_state_survives_restart(self, monitor):
        # Record an OK state and persist it to the DB.
        monitor._process_module_result('mod', self._result('k', True, 'ok'))
        monitor.status.save()
        assert monitor._check_state_store.get_all()[('mod', 'k', '')]['status'] is True

        # A fresh Monitor on the same var dir (same DB) loads the baseline.
        m2 = Monitor(monitor.dir_base, monitor.dir_config, monitor.dir_modules, monitor.dir_var)
        assert m2.status.get_conf(['mod', 'k', 'status'], None) is True
        # The same OK result must NOT re-announce after the restart.
        added = self._recorder(m2)
        m2._process_module_result('mod', self._result('k', True, 'ok'))
        assert added == []

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

    def test_slash_composite_keys_are_distinct_metrics(self, monitor):
        # Regression: one item (with a uid) emitting two '/'-composite result keys
        # (m365 '<item>/site' + '<item>/tenant') must persist as TWO rows keyed by
        # uid + a distinct '/'-metric — NOT collapse to (uid, '') and trip the
        # UNIQUE PK, which aborted the whole persist and left the module empty.
        monitor.config_modules.data = {'m365': {'list': {'item_1': {'uid': 'U-1'}}}}
        monitor._process_module_result('m365', self._result('item_1/site', True, 'ok'))
        monitor._process_module_result('m365', self._result('item_1/tenant', False, 'hi'))
        monitor.status.save()
        states = monitor._check_state_store.get_all()
        assert states[('m365', 'U-1', '/site')]['item_uid'] == 'U-1'
        assert states[('m365', 'U-1', '/tenant')]['item_uid'] == 'U-1'
        # The keys reconstruct verbatim (with '/'), so the UI/label resolver and
        # the monitor's change detection see the same key the module emits.
        assert monitor._check_state_store.as_status_dict()['m365'].keys() == {
            'U-1/site', 'U-1/tenant'}

    def test_stale_bare_key_does_not_abort_persist(self, monitor):
        # A stale bare '<item>' (e.g. from an earlier missing-credentials run)
        # sitting next to a fresh '<item>/site' must not collide: both resolve to
        # the item uid but with different metrics, and the persist must not abort.
        monitor.config_modules.data = {'m365': {'list': {'item_1': {'uid': 'U-1'}}}}
        monitor.status.data = {'m365': {
            'item_1':      {'status': False, 'message': 'missing creds', 'other_data': {}},
            'item_1/site': {'status': True,  'message': 'ok',            'other_data': {}},
        }}
        assert monitor.status.save() is True
        out = monitor._check_state_store.as_status_dict()['m365']
        assert 'U-1' in out and 'U-1/site' in out


class TestFailStreak:
    """ModuleBase.fail_streak persists in the monitor status store and flags
    the monitor so the check state is persisted even without a status flip."""

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


class TestRefreshRuntimeConfig:
    """The monitor no longer owns a Telegram client — credentials are read from the
    effective (DB+file) config at flush time by the injected MonitorNotifier, so
    refresh_runtime_config just re-applies the DB layer (no sender to churn)."""

    def test_refresh_is_safe_without_a_notifier(self, monitor):
        assert not hasattr(monitor, 'tg')
        monitor.refresh_runtime_config()      # must not raise (no _init_telegram anymore)
        assert monitor._notifier is None


class TestDaemonModuleConfigRefresh:
    """Regression: the persistent daemon monitor holds its own ModulesStore whose
    version() counter never reflects the web admin's writes (a separate store
    instance). refresh_runtime_config() must re-read module config from the DB so
    checks added in the UI (e.g. a new Proxmox cluster) actually run — otherwise
    they never reach status / history / Telegram."""

    def test_refresh_picks_up_web_added_check(self, monitor):
        from lib.core.modules import ModulesStore, DbBackedModules
        # Simulate the web admin adding a Proxmox check via its OWN store instance.
        web_cm = DbBackedModules(ModulesStore(monitor._db), fernet=monitor._fernet)
        web_cm.read()
        data = web_cm.data
        data.setdefault('watchfuls.proxmox', {}).setdefault('list', {})['pve'] = {
            'enabled': True, 'label': 'Lab'}
        web_cm.save(data)

        # The persistent monitor is stale until it re-reads.
        before = monitor.config_modules.get_conf(
            ['watchfuls.proxmox', 'list', 'pve', 'label'], '')
        assert before == ''
        monitor.refresh_runtime_config()
        after = monitor.config_modules.get_conf(
            ['watchfuls.proxmox', 'list', 'pve', 'label'], '')
        assert after == 'Lab'


class TestDaemonCycleIntegration:
    """End-to-end wiring of one daemon cycle on the PERSISTENT monitor:

    a check added in the web (via separate DB store instances) must, after the
    per-cycle ``refresh_runtime_config()``, actually run and land in ALL three
    surfaces — current status, history, and an attempted Telegram send with the
    DB-stored credentials.  This covers the seams three real regressions slipped
    through: stale module config, Telegram initialised before the DB layer, and
    the config→run→notify path as a whole.
    """

    def _make_listing_module(self, modules_dir, name):
        """A module that emits one *notifying* OK result per configured list item
        (so whether the monitor SEES the config actually matters)."""
        mod_dir = os.path.join(modules_dir, name)
        os.makedirs(mod_dir, exist_ok=True)
        with open(os.path.join(mod_dir, '__init__.py'), 'w', encoding='utf-8') as fh:
            fh.write(
                "from lib.modules import ModuleBase, ReturnModuleCheck\n\n"
                "class Watchful(ModuleBase):\n"
                "    ITEM_SCHEMA = {'list': {'enabled': {'type': 'bool', 'default': True},\n"
                "                            'label': {'type': 'str', 'default': ''}}}\n"
                "    def __init__(self, monitor):\n"
                "        super().__init__(monitor, __package__)\n"
                "    def check(self):\n"
                "        r = ReturnModuleCheck()\n"
                "        for k, v in (self.get_conf('list', {}) or {}).items():\n"
                "            if isinstance(v, dict) and v.get('enabled', True):\n"
                "                r.set(k + '/state', True, f'{k} ok', True)\n"
                "        return r\n"
            )

    def test_added_check_reaches_status_history_telegram(self, monitor):
        import sys
        import time
        name = 'clustermod'
        self._make_listing_module(monitor.dir_modules, name)
        if monitor.dir_modules not in sys.path:
            sys.path.insert(0, monitor.dir_modules)

        # The web admin writes BOTH the Telegram creds and the new check to the DB
        # through its own store instances — invisible to the persistent monitor.
        from lib.core.config.store import ConfigStore
        from lib.config import config_path
        from lib.config.manager import ConfigManager
        from lib.core.modules import ModulesStore, DbBackedModules
        ConfigManager(ConfigStore(monitor._db), config_path(monitor.dir_config),
                      fernet=monitor._fernet).write(
            {'telegram': {'token': 'TKN-9', 'chat_id': 'CHT-9'}})
        web_cm = DbBackedModules(ModulesStore(monitor._db), fernet=monitor._fernet)
        web_cm.read()
        web_cm.data.setdefault(name, {}).setdefault('list', {})['pve'] = {
            'enabled': True, 'label': 'Lab'}
        web_cm.save(web_cm.data)

        try:
            # BEFORE the refresh the persistent monitor is blind to the new check.
            assert 'pve/state' not in monitor.check_module(name)[2].list

            # The per-cycle refresh the daemon now performs.
            monitor.refresh_runtime_config()

            # Wire a notifier reading the effective (DB-folded) config, with the routing
            # matrix sending recoveries to Telegram — mirrors the daemon (whose manager
            # is the dispatcher `wa`). This proves the DB creds reach the send.
            from lib.core.notify.monitor_notifier import MonitorNotifier

            class _WA:
                _CONFIG_FILE = 'config.json'
                def _read_config_file(self, _f):
                    return {'telegram': {
                                'token': monitor.config.get_conf(['telegram', 'token'], ''),
                                'chat_id': monitor.config.get_conf(['telegram', 'chat_id'], ''),
                                'group_messages': False},
                            'notifications': {'telegram_on_recovery': True}}
                def _dbg(self, *a, **k): pass
                def _load_webhooks(self, *, decrypt=True): return []
                def _config_section(self, _n): return {}
            monitor._notifier = MonitorNotifier(_WA())

            import lib.providers.telegram as telegram_mod
            with patch.object(telegram_mod, 'requests') as req:
                req.RequestException = Exception
                req.post.return_value = MagicMock(status_code=200)

                # Run the cycle exactly like the daemon: check → process → history → flush.
                ok, mname, data = monitor.check_module(name)
                assert ok and data is not None and 'pve/state' in data.list
                # Seed a prior DOWN so the OK result is a genuine recovery (down → up) that
                # sends — a first-seen OK check is (correctly) not a recovery and stays quiet.
                monitor.status.set_conf([name, 'pve/state', 'status'], False)
                monitor._process_module_result(mname, data)
                for key in data.list:
                    monitor._history.record(mname, key, data.get_status(key),
                                            data.get_other_data(key))
                monitor._notifier.flush()            # flush the cycle's grouped alerts

            # 1) STATUS — the live result is recorded.
            assert monitor.status.get_conf([name, 'pve/state', 'status']) is True

            # 2) HISTORY — a sample landed and is queryable.
            pts = monitor._history.query(name, 'pve/state', 0, time.time() + 1)
            assert len(pts) == 1

            # 3) TELEGRAM — a send was attempted with the DB credentials (proving
            #    token/chat_id were NOT null — the original bug).
            assert req.post.called
            assert 'TKN-9' in req.post.call_args.args[0]
            assert req.post.call_args.kwargs['data']['chat_id'] == 'CHT-9'
        finally:
            sys.path = [p for p in sys.path if p != monitor.dir_modules]
            sys.modules.pop(name, None)


# ──────────────────── _get_item_uid (result key → item) ───────────────


class TestGetItemUid:
    """Result keys map back to their configured item UID, across the two derived
    conventions: '/'-composite (cluster sub-results) and '_'-suffix."""

    def test_exact_key(self, monitor):
        cfg = {'list': {'u-123': {'uid': 'u-123'}}}
        with patch.object(monitor.config_modules, 'get_conf', return_value=cfg):
            assert monitor._get_item_uid('watchfuls.x', 'u-123') == 'u-123'

    def test_slash_composite_key(self, monitor):
        # Cluster sub-results: '<uid>/vip', '<uid>/node/pve04' → the item uid.
        cfg = {'list': {'u-123': {'uid': 'u-123'}}}
        with patch.object(monitor.config_modules, 'get_conf', return_value=cfg):
            assert monitor._get_item_uid('watchfuls.x', 'u-123/vip') == 'u-123'
            assert monitor._get_item_uid('watchfuls.x', 'u-123/node/pve04') == 'u-123'

    def test_underscore_derived_key(self, monitor):
        cfg = {'list': {'u-9': {'uid': 'u-9'}}}
        with patch.object(monitor.config_modules, 'get_conf', return_value=cfg):
            assert monitor._get_item_uid('watchfuls.x', 'u-9_ram') == 'u-9'

    def test_unknown_key_returns_none(self, monitor):
        cfg = {'list': {'u-1': {'uid': 'u-1'}}}
        with patch.object(monitor.config_modules, 'get_conf', return_value=cfg):
            assert monitor._get_item_uid('watchfuls.x', 'nope/vip') is None
