#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/service_status.py."""

import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import create_mock_monitor


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


class TestServiceStatusInit:

    def test_init(self):
        from watchfuls.service_status import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.service_status': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.service_status'
        assert w.paths.find('systemctl') == '/bin/systemctl'


class TestServiceStatusClearStr:

    def test_clear_str_parentheses(self):
        from watchfuls.service_status import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.service_status': {}})
        w = Watchful(mock_monitor)
        # __clear_str es estático privado, lo accedemos así
        result = w._clear_str("(running)")
        assert result == "running"

    def test_clear_str_empty(self):
        from watchfuls.service_status import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.service_status': {}})
        w = Watchful(mock_monitor)
        result = w._clear_str("")
        assert result == ""

    def test_clear_str_none(self):
        from watchfuls.service_status import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.service_status': {}})
        w = Watchful(mock_monitor)
        result = w._clear_str(None)
        assert result == ""


class TestServiceStatusReturn:

    def setup_method(self):
        from watchfuls.service_status import Watchful
        self.Watchful = Watchful

    def test_service_running(self):
        """Servicio activo y running → True."""
        config = {'watchfuls.service_status': {}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE, "")):
            status, error, message = w._service_return("nginx")
            assert status is True
            assert error is False
            assert message == "running"

    def test_service_inactive(self):
        """Servicio inactivo (dead) → False."""
        config = {'watchfuls.service_status': {}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_INACTIVE, "")):
            status, error, message = w._service_return("nginx")
            assert status is False
            assert error is False
            assert message == ""

    def test_service_failed(self):
        """Servicio failed → False con mensaje."""
        config = {'watchfuls.service_status': {}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_FAILED, "")):
            status, error, message = w._service_return("nginx")
            assert status is False

    def test_service_active_exited(self):
        """Servicio active (exited) → False."""
        config = {'watchfuls.service_status': {}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE_EXITED, "")):
            status, error, message = w._service_return("cron")
            assert status is False
            assert message == "exited"

    def test_service_no_stdout(self):
        """Sin stdout retorna error."""
        config = {'watchfuls.service_status': {}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=("", "Unit not found")):
            status, error, message = w._service_return("fake")
            assert status is False
            assert error is True


class TestServiceStatusCheck:

    def setup_method(self):
        from watchfuls.service_status import Watchful
        self.Watchful = Watchful

    def test_check_empty_list(self):
        """Sin servicios configurados, no hay resultados."""
        config = {'watchfuls.service_status': {'list': {}}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_service(self):
        """Servicio deshabilitado no se procesa."""
        config = {
            'watchfuls.service_status': {
                'list': {
                    'nginx': {'enabled': False, 'remediation': False}
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_service_running(self):
        """Servicio running se marca OK."""
        config = {
            'watchfuls.service_status': {
                'list': {
                    'nginx': {'enabled': True, 'remediation': False}
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE, "")):
            result = w.check()
            items = result.list
            assert 'nginx' in items
            assert items['nginx']['status'] is True
            assert 'Running' in items['nginx']['message']

    def test_check_service_stopped(self):
        """Servicio stopped se marca como fallo."""
        config = {
            'watchfuls.service_status': {
                'list': {
                    'nginx': {'enabled': True, 'remediation': False}
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_INACTIVE, "")):
            result = w.check()
            items = result.list
            assert 'nginx' in items
            assert items['nginx']['status'] is False
            assert 'Stop' in items['nginx']['message']

    def test_check_multiple_services(self):
        """Múltiples servicios se procesan."""
        config = {
            'watchfuls.service_status': {
                'list': {
                    'nginx': {'enabled': True, 'remediation': False},
                    'apache2': {'enabled': True, 'remediation': False},
                    'mysql': {'enabled': False, 'remediation': False},
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=(SYSTEMCTL_ACTIVE, "")):
            result = w.check()
            items = result.list
            assert 'nginx' in items
            assert 'apache2' in items
            assert 'mysql' not in items
