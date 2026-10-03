#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the heartbeat helpers: db_summary + app_version."""

from lib.services.heartbeat import app_version, db_summary


class TestDbSummary:

    def test_sqlite_uses_basename(self):
        assert db_summary({'driver': 'sqlite', 'path': '/var/lib/x/data.db'}) == {
            'driver': 'sqlite', 'host': None, 'name': 'data.db'}

    def test_sqlite_default_name(self):
        assert db_summary(None)['name'] == 'data.db'
        assert db_summary({}, 'syslog.db')['name'] == 'syslog.db'

    def test_mysql_keeps_host_and_name(self):
        assert db_summary({'driver': 'mysql', 'host': 'db', 'name': 'ss'}) == {
            'driver': 'mysql', 'host': 'db', 'name': 'ss'}

    def test_engine_and_type_aliases(self):
        assert db_summary({'engine': 'postgresql', 'host': 'h', 'name': 'n'})['driver'] == 'postgresql'
        assert db_summary({'type': 'mariadb', 'host': 'h', 'name': 'n'})['driver'] == 'mariadb'


class TestAppVersion:

    def test_uses_lib_version(self):
        from lib import __version__
        assert app_version() == __version__

    def test_not_overridable_by_env(self, monkeypatch):
        # The version reflects the running code — an env value must NOT override it.
        monkeypatch.setenv('SS_VERSION', '9.9.9-test')
        from lib import __version__
        assert app_version() == __version__


class _Cmds:
    def __init__(self):
        self.claimed = 0

    def claim_next(self, _key, _who):
        self.claimed += 1
        return None

    def complete(self, *_a):
        pass


class _Lease:
    def release(self, *_a):
        pass


class TestAStandbyLeavesTheQueueToTheLeader:
    """A hot-standby replica of a single-owner service claimed queued commands too, so a
    `run_now` could run a whole cycle on a standby's stale in-memory monitor."""

    def _svc(self, *, gated, leader):
        from lib.services.heartbeat import _HeartbeatMixin

        class _Svc(_HeartbeatMixin):
            _HB_KEY = 'monitoring'
            _LEADER_GATED = gated

            def _apply_command(self, action, args=None):
                return True, 'ran'

        s = _Svc()
        s._service_commands_store = _Cmds()
        s._service_leader_store = _Lease()
        s._is_leader = leader
        return s

    def test_a_standby_does_not_claim(self):
        s = self._svc(gated=True, leader=False)
        s._drain_commands()
        assert s._service_commands_store.claimed == 0

    def test_the_leader_does(self):
        s = self._svc(gated=True, leader=True)
        s._drain_commands()
        assert s._service_commands_store.claimed == 1

    def test_an_active_active_service_always_does(self):
        s = self._svc(gated=False, leader=False)
        s._drain_commands()
        assert s._service_commands_store.claimed == 1

    def test_run_now_is_refused_off_the_leader(self):
        import threading
        from lib.services.monitoring.manager import _MonitoringMixin

        class _M(_MonitoringMixin):
            def __init__(self):
                self._check_lock = threading.Lock()
                self.ran = False

            def _work_allowed(self):
                return False

            def _monitoring_run_one_cycle(self):
                self.ran = True
                return {}, []

        m = _M()
        assert m._apply_command('run_now') == (False, 'not_leader')
        assert m.ran is False
