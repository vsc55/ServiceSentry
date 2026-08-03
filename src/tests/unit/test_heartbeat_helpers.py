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
