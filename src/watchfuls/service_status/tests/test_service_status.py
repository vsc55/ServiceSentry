#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/service_status.py."""

import pytest
import psutil
from unittest.mock import patch, MagicMock
from conftest import create_mock_monitor


# ── Systemd (Linux) output fixtures ───────────────────────────────

SYSTEMCTL_ACTIVE = """\
● nginx.service - A high performance web server
   Loaded: loaded (/lib/systemd/system/nginx.service; enabled)
   Active: active (running) since Mon 2019-05-27 11:28:46 CEST; 1min 48s ago
"""

SYSTEMCTL_INACTIVE = """\
● nginx.service - A high performance web server
   Loaded: loaded (/lib/systemd/system/nginx.service; enabled)
   Active: inactive (dead) since Mon 2019-05-27 11:30:51 CEST; 1s ago
"""

SYSTEMCTL_FAILED = """\
● nginx.service - A high performance web server
   Loaded: loaded (/lib/systemd/system/nginx.service; enabled)
   Active: failed (Result: exit-code) since Mon 2019-05-27 11:30:51 CEST; 1s ago
"""

SYSTEMCTL_ACTIVE_EXITED = """\
● cron.service - Regular background program processing daemon
   Loaded: loaded (/lib/systemd/system/cron.service; enabled)
   Active: active (exited) since Mon 2019-05-27 11:28:46 CEST; 1min 48s ago
"""

# ── systemctl list-units output for discover ──────────────────────

SYSTEMCTL_LIST_OUTPUT = """\
  nginx.service        loaded active running   A high performance web server and reverse proxy
  cron.service         loaded active running   Regular background program processing daemon
  snapd.service        loaded inactive dead    Snap Daemon
  ssh.service          loaded active running   OpenBSD Secure Shell server
"""

# ── OpenRC output fixtures ─────────────────────────────────────────

RC_STATUS_OUTPUT = """\
Runlevel: default
 nginx                    [  started  ]
 sshd                     [  started  ]
 crond                    [  stopped  ]
 NetworkManager           [  crashed  ]
Dynamic Runlevel: hotplugged
Dynamic Runlevel: needed/wanted
Dynamic Runlevel: manual
"""


# ══════════════════════════════════════════════════════════════════
# Init
# ══════════════════════════════════════════════════════════════════

class TestServiceStatusInit:

    def test_init_linux_systemd(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'systemd'):
            mock_monitor = create_mock_monitor({'watchfuls.service_status': {}})
            w = Watchful(mock_monitor)
            assert w.name_module == 'watchfuls.service_status'
            assert w.paths.find('systemctl') == '/bin/systemctl'

    def test_init_linux_openrc(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'openrc'), \
             patch('shutil.which', return_value='/sbin/rc-service'):
            mock_monitor = create_mock_monitor({'watchfuls.service_status': {}})
            w = Watchful(mock_monitor)
            assert w.paths.find('rc-service') == '/sbin/rc-service'

    def test_init_linux_openrc_fallback(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'openrc'), \
             patch('shutil.which', return_value=None):
            mock_monitor = create_mock_monitor({'watchfuls.service_status': {}})
            w = Watchful(mock_monitor)
            assert w.paths.find('rc-service') == 'rc-service'

    def test_init_linux_sysv(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'sysv'), \
             patch('shutil.which', return_value='/usr/sbin/service'):
            mock_monitor = create_mock_monitor({'watchfuls.service_status': {}})
            w = Watchful(mock_monitor)
            assert w.paths.find('service') == '/usr/sbin/service'

    def test_init_windows(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'windows'):
            mock_monitor = create_mock_monitor({'watchfuls.service_status': {}})
            w = Watchful(mock_monitor)
            assert w.paths.find('sc') == 'sc'


# ══════════════════════════════════════════════════════════════════
# _clear_str
# ══════════════════════════════════════════════════════════════════

class TestServiceStatusClearStr:

    def _make(self):
        from watchfuls.service_status import Watchful
        return Watchful(create_mock_monitor({'watchfuls.service_status': {}}))

    def test_clear_str_parentheses(self):
        assert self._make()._clear_str("(running)") == "running"

    def test_clear_str_empty(self):
        assert self._make()._clear_str("") == ""

    def test_clear_str_none(self):
        assert self._make()._clear_str(None) == ""


# ══════════════════════════════════════════════════════════════════
# _service_return — Linux / systemd
# ══════════════════════════════════════════════════════════════════

class TestServiceStatusReturnLinux:

    def setup_method(self):
        from watchfuls.service_status import Watchful
        self.Watchful = Watchful

    def _make(self):
        return self.Watchful(create_mock_monitor({'watchfuls.service_status': {}}))

    def test_service_running(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'systemd'), \
             patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE, "")):
            status, error, message = w._service_return("nginx")
            assert status is True
            assert error is False
            assert message == "running"

    def test_service_inactive(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'systemd'), \
             patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_INACTIVE, "")):
            status, error, message = w._service_return("nginx")
            assert status is False
            assert error is False
            assert message == ""

    def test_service_failed(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'systemd'), \
             patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_FAILED, "")):
            status, _, _ = w._service_return("nginx")
            assert status is False

    def test_service_active_exited(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'systemd'), \
             patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE_EXITED, "")):
            status, _, message = w._service_return("cron")
            assert status is False
            assert message == "exited"

    def test_service_no_stdout(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'systemd'), \
             patch.object(w, '_run_cmd', return_value=("", "Unit not found")):
            status, error, _ = w._service_return("fake")
            assert status is False
            assert error is True

    def test_service_return_systemd_direct(self):
        """_service_return_systemd is callable directly."""
        w = self._make()
        with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE, "")):
            status, _, _ = w._service_return_systemd("nginx")
            assert status is True


# ══════════════════════════════════════════════════════════════════
# _service_return — Linux / OpenRC
# ══════════════════════════════════════════════════════════════════

class TestServiceStatusReturnOpenRC:

    def setup_method(self):
        from watchfuls.service_status import Watchful
        self.Watchful = Watchful

    def _make(self):
        with patch.object(self.Watchful, '_PLATFORM', 'linux'), \
             patch.object(self.Watchful, '_INIT_SYSTEM', 'openrc'), \
             patch('shutil.which', return_value='/sbin/rc-service'):
            return self.Watchful(create_mock_monitor({'watchfuls.service_status': {}}))

    def test_service_running(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'openrc'), \
             patch.object(w, '_run_cmd', return_value=(' * status: started\n', '', 0)):
            status, error, message = w._service_return("nginx")
            assert status is True
            assert error is False
            assert message == 'running'

    def test_service_stopped(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'openrc'), \
             patch.object(w, '_run_cmd', return_value=(' * status: stopped\n', '', 1)):
            status, error, message = w._service_return("nginx")
            assert status is False
            assert error is False
            assert message == 'stopped'

    def test_service_not_found(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'openrc'), \
             patch.object(w, '_run_cmd', return_value=('', ' * ERROR: nginx does not exist\n', 1)):
            status, error, message = w._service_return("nginx")
            assert status is False
            assert error is True
            assert 'does not exist' in message.lower()

    def test_service_return_openrc_direct(self):
        """_service_return_openrc is callable directly."""
        w = self._make()
        with patch.object(w, '_run_cmd', return_value=('started\n', '', 0)):
            status, _, _ = w._service_return_openrc("nginx")
            assert status is True


# ══════════════════════════════════════════════════════════════════
# _service_return — Linux / SysV
# ══════════════════════════════════════════════════════════════════

class TestServiceStatusReturnSysV:

    def setup_method(self):
        from watchfuls.service_status import Watchful
        self.Watchful = Watchful

    def _make(self):
        with patch.object(self.Watchful, '_PLATFORM', 'linux'), \
             patch.object(self.Watchful, '_INIT_SYSTEM', 'sysv'), \
             patch('shutil.which', return_value='/usr/sbin/service'):
            return self.Watchful(create_mock_monitor({'watchfuls.service_status': {}}))

    def test_service_running(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'sysv'), \
             patch.object(w, '_run_cmd', return_value=('nginx is running.\n', '', 0)):
            status, error, message = w._service_return("nginx")
            assert status is True
            assert error is False
            assert message == 'running'

    def test_service_stopped(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'sysv'), \
             patch.object(w, '_run_cmd', return_value=('nginx is stopped.\n', '', 1)):
            status, error, message = w._service_return("nginx")
            assert status is False
            assert error is False
            assert 'nginx is stopped' in message

    def test_service_not_found(self):
        """Empty output with non-zero exit → error."""
        w = self._make()
        with patch.object(w, '_PLATFORM', 'linux'), \
             patch.object(w, '_INIT_SYSTEM', 'sysv'), \
             patch.object(w, '_run_cmd', return_value=('', '', 1)):
            status, error, message = w._service_return("ghost")
            assert status is False
            assert error is True
            assert 'not found' in message

    def test_service_return_sysv_direct(self):
        """_service_return_sysv is callable directly."""
        w = self._make()
        with patch.object(w, '_run_cmd', return_value=('running\n', '', 0)):
            status, _, _ = w._service_return_sysv("nginx")
            assert status is True


# ══════════════════════════════════════════════════════════════════
# _service_return — Windows (psutil)
# ══════════════════════════════════════════════════════════════════

class TestServiceStatusReturnWindows:

    def setup_method(self):
        from watchfuls.service_status import Watchful
        self.Watchful = Watchful

    def _make(self):
        with patch.object(self.Watchful, '_PLATFORM', 'windows'):
            return self.Watchful(create_mock_monitor({'watchfuls.service_status': {}}))

    def _mock_svc(self, status):
        svc = MagicMock()
        svc.status.return_value = status
        return svc

    def test_service_running(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'windows'), \
             patch('psutil.win_service_get', return_value=self._mock_svc('running'), create=True):
            status, error, message = w._service_return("nginx")
            assert status is True
            assert error is False
            assert message == "running"

    def test_service_stopped(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'windows'), \
             patch('psutil.win_service_get', return_value=self._mock_svc('stopped'), create=True):
            status, error, message = w._service_return("nginx")
            assert status is False
            assert error is False
            assert message == "stopped"

    def test_service_paused(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'windows'), \
             patch('psutil.win_service_get', return_value=self._mock_svc('paused'), create=True):
            status, error, message = w._service_return("nginx")
            assert status is False
            assert error is False
            assert message == "paused"

    def test_service_not_found(self):
        w = self._make()
        with patch.object(w, '_PLATFORM', 'windows'), \
             patch('psutil.win_service_get', side_effect=Exception("service not found"), create=True):
            status, error, _ = w._service_return("fake")
            assert status is False
            assert error is True

    def test_service_return_windows_direct(self):
        """_service_return_windows is callable directly."""
        w = self._make()
        with patch('psutil.win_service_get', return_value=self._mock_svc('running'), create=True):
            status, _, _ = w._service_return_windows("nginx")
            assert status is True


# ══════════════════════════════════════════════════════════════════
# check() — full workflow
# ══════════════════════════════════════════════════════════════════

class TestServiceStatusCheck:

    def setup_method(self):
        from watchfuls.service_status import Watchful
        self.Watchful = Watchful

    def test_check_empty_list(self):
        config = {'watchfuls.service_status': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        assert len(w.check().items()) == 0

    def test_check_disabled_service(self):
        config = {'watchfuls.service_status': {'list': {
            'nginx': {'enabled': False, 'remediation': False}
        }}}
        w = self.Watchful(create_mock_monitor(config))
        assert len(w.check().items()) == 0

    def test_check_service_running(self):
        config = {'watchfuls.service_status': {'list': {
            'nginx': {'enabled': True, 'remediation': False}
        }}}
        with patch.object(self.Watchful, '_PLATFORM', 'linux'), \
             patch.object(self.Watchful, '_INIT_SYSTEM', 'systemd'):
            w = self.Watchful(create_mock_monitor(config))
            with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE, "")):
                items = w.check().list
                assert 'nginx' in items
                assert items['nginx']['status'] is True
                assert 'Running' in items['nginx']['message']

    def test_check_service_stopped(self):
        config = {'watchfuls.service_status': {'list': {
            'nginx': {'enabled': True, 'remediation': False}
        }}}
        with patch.object(self.Watchful, '_PLATFORM', 'linux'), \
             patch.object(self.Watchful, '_INIT_SYSTEM', 'systemd'):
            w = self.Watchful(create_mock_monitor(config))
            with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_INACTIVE, "")):
                items = w.check().list
                assert 'nginx' in items
                assert items['nginx']['status'] is False
                assert 'Stop' in items['nginx']['message']

    def test_check_expected_stopped_service_is_stopped(self):
        """expected=stopped + service stopped → OK (status True)."""
        config = {'watchfuls.service_status': {'list': {
            'nginx': {'enabled': True, 'remediation': False, 'expected': 'stopped'}
        }}}
        with patch.object(self.Watchful, '_PLATFORM', 'linux'), \
             patch.object(self.Watchful, '_INIT_SYSTEM', 'systemd'):
            w = self.Watchful(create_mock_monitor(config))
            with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_INACTIVE, "")):
                items = w.check().list
                assert items['nginx']['status'] is True
                assert 'Stopped' in items['nginx']['message']

    def test_check_expected_stopped_service_is_running(self):
        """expected=stopped + service running → error (status False)."""
        config = {'watchfuls.service_status': {'list': {
            'nginx': {'enabled': True, 'remediation': False, 'expected': 'stopped'}
        }}}
        with patch.object(self.Watchful, '_PLATFORM', 'linux'), \
             patch.object(self.Watchful, '_INIT_SYSTEM', 'systemd'):
            w = self.Watchful(create_mock_monitor(config))
            with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE, "")):
                items = w.check().list
                assert items['nginx']['status'] is False
                assert 'Running' in items['nginx']['message']

    def test_check_multiple_services(self):
        config = {'watchfuls.service_status': {'list': {
            'nginx':   {'enabled': True,  'remediation': False},
            'apache2': {'enabled': True,  'remediation': False},
            'mysql':   {'enabled': False, 'remediation': False},
        }}}
        with patch.object(self.Watchful, '_PLATFORM', 'linux'), \
             patch.object(self.Watchful, '_INIT_SYSTEM', 'systemd'):
            w = self.Watchful(create_mock_monitor(config))
            with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE, "")):
                items = w.check().list
                assert 'nginx'   in items
                assert 'apache2' in items
                assert 'mysql' not in items


# ══════════════════════════════════════════════════════════════════
# discover()
# ══════════════════════════════════════════════════════════════════

class TestServiceStatusDiscover:

    def test_discover_linux_systemd(self):
        from watchfuls.service_status import Watchful
        mock_result = MagicMock(stdout=SYSTEMCTL_LIST_OUTPUT)
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'systemd'), \
             patch('subprocess.run', return_value=mock_result):
            services = Watchful.discover()

        names = [s['name'] for s in services]
        assert 'nginx' in names
        assert 'cron' in names
        assert 'snapd' in names
        assert 'ssh' in names
        nginx = next(s for s in services if s['name'] == 'nginx')
        assert nginx['status'] == 'running'
        snapd = next(s for s in services if s['name'] == 'snapd')
        assert snapd['status'] == 'dead'

    def test_discover_linux_systemd_strips_service_suffix(self):
        from watchfuls.service_status import Watchful
        mock_result = MagicMock(stdout=SYSTEMCTL_LIST_OUTPUT)
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'systemd'), \
             patch('subprocess.run', return_value=mock_result):
            services = Watchful.discover()
        for s in services:
            assert not s['name'].endswith('.service')

    def test_discover_linux_systemd_empty(self):
        from watchfuls.service_status import Watchful
        mock_result = MagicMock(stdout='')
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'systemd'), \
             patch('subprocess.run', return_value=mock_result):
            services = Watchful.discover()
        assert services == []

    def test_discover_linux_systemd_exception(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'systemd'), \
             patch('subprocess.run', side_effect=FileNotFoundError('systemctl not found')):
            services = Watchful.discover()
        assert services == []

    def test_discover_linux_openrc(self):
        from watchfuls.service_status import Watchful
        mock_result = MagicMock(stdout=RC_STATUS_OUTPUT)
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'openrc'), \
             patch('subprocess.run', return_value=mock_result):
            services = Watchful.discover()

        names = [s['name'] for s in services]
        assert 'nginx' in names
        assert 'sshd' in names
        assert 'crond' in names
        assert 'NetworkManager' in names

    def test_discover_linux_openrc_status_mapping(self):
        from watchfuls.service_status import Watchful
        mock_result = MagicMock(stdout=RC_STATUS_OUTPUT)
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'openrc'), \
             patch('subprocess.run', return_value=mock_result):
            services = Watchful.discover()

        nginx = next(s for s in services if s['name'] == 'nginx')
        assert nginx['status'] == 'running'
        crond = next(s for s in services if s['name'] == 'crond')
        assert crond['status'] == 'stopped'
        nm = next(s for s in services if s['name'] == 'NetworkManager')
        assert nm['status'] == 'crashed'

    def test_discover_linux_openrc_no_duplicates(self):
        from watchfuls.service_status import Watchful
        dup_output = RC_STATUS_OUTPUT + " nginx                    [  started  ]\n"
        mock_result = MagicMock(stdout=dup_output)
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'openrc'), \
             patch('subprocess.run', return_value=mock_result):
            services = Watchful.discover()
        assert sum(1 for s in services if s['name'] == 'nginx') == 1

    def test_discover_linux_openrc_exception(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'openrc'), \
             patch('subprocess.run', side_effect=FileNotFoundError('rc-status not found')):
            services = Watchful.discover()
        assert services == []

    def test_discover_linux_sysv(self):
        from watchfuls.service_status import Watchful
        init_entries = ['nginx', 'ssh', 'cron', 'README', 'functions']
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'sysv'), \
             patch('os.path.isdir', return_value=True), \
             patch('os.listdir', return_value=init_entries), \
             patch('os.access', return_value=True), \
             patch('os.path.isdir', side_effect=lambda p: p == '/etc/init.d'):
            services = Watchful.discover()

        names = [s['name'] for s in services]
        assert 'nginx' in names
        assert 'ssh' in names
        assert 'cron' in names
        assert 'README' not in names
        assert 'functions' not in names

    def test_discover_linux_sysv_no_init_dir(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'sysv'), \
             patch('os.path.isdir', return_value=False):
            services = Watchful.discover()
        assert services == []

    def test_discover_linux_sysv_exception(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'linux'), \
             patch.object(Watchful, '_INIT_SYSTEM', 'sysv'), \
             patch('os.path.isdir', return_value=True), \
             patch('os.listdir', side_effect=PermissionError('denied')):
            services = Watchful.discover()
        assert services == []

    def _mock_win_services(self, entries):
        """entries: list of (name, display_name, status) tuples."""
        mocks = []
        for name, display, status in entries:
            svc = MagicMock()
            svc.name.return_value = name
            svc.display_name.return_value = display
            svc.status.return_value = status
            mocks.append(svc)
        return mocks

    def test_discover_windows(self):
        from watchfuls.service_status import Watchful
        svcs = self._mock_win_services([
            ('nginx',    'nginx web server', 'running'),
            ('Spooler',  'Print Spooler',    'running'),
            ('wuauserv', 'Windows Update',   'stopped'),
        ])
        with patch.object(Watchful, '_PLATFORM', 'windows'), \
             patch('psutil.win_service_iter', return_value=svcs, create=True):
            services = Watchful.discover()

        names = [s['name'] for s in services]
        assert 'nginx' in names
        assert 'Spooler' in names
        assert 'wuauserv' in names
        nginx = next(s for s in services if s['name'] == 'nginx')
        assert nginx['status'] == 'running'
        wu = next(s for s in services if s['name'] == 'wuauserv')
        assert wu['status'] == 'stopped'

    def test_discover_windows_display_name(self):
        from watchfuls.service_status import Watchful
        svcs = self._mock_win_services([('nginx', 'nginx web server', 'running')])
        with patch.object(Watchful, '_PLATFORM', 'windows'), \
             patch('psutil.win_service_iter', return_value=svcs, create=True):
            services = Watchful.discover()
        nginx = next(s for s in services if s['name'] == 'nginx')
        assert nginx['display_name'] == 'nginx web server'

    def test_discover_windows_empty(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'windows'), \
             patch('psutil.win_service_iter', return_value=[], create=True):
            services = Watchful.discover()
        assert services == []

    def test_discover_windows_exception(self):
        from watchfuls.service_status import Watchful
        with patch.object(Watchful, '_PLATFORM', 'windows'), \
             patch('psutil.win_service_iter', side_effect=Exception('access denied'), create=True):
            services = Watchful.discover()
        assert services == []
