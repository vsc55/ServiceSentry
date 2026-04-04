#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para lib/linux/raid_mdstat.py — RaidMdstat."""

import pytest
from unittest.mock import patch, MagicMock
from lib.linux.raid_mdstat import RaidMdstat


# Contenido típico de /proc/mdstat con un RAID saludable
MDSTAT_OK = """\
Personalities : [raid1]
md0 : active raid1 sda1[0] sdb1[1]
      1953513472 blocks [2/2] [UU]

unused devices: <none>
"""

# RAID degradado
MDSTAT_DEGRADED = """\
Personalities : [raid1]
md0 : active raid1 sda1[0]
      1953513472 blocks [2/1] [U_]

unused devices: <none>
"""

# RAID en recovery
MDSTAT_RECOVERY = """\
Personalities : [raid1]
md0 : active raid1 sda1[0] sdb1[2]
      1953513472 blocks [2/1] [U_]
      [>....................]  recovery = 5.2% (101580544/1953513472) finish=200.5min speed=150000K/sec

unused devices: <none>
"""

# Sin RAIDs
MDSTAT_EMPTY = """\
Personalities :
unused devices: <none>
"""

# Múltiples RAIDs
MDSTAT_MULTI = """\
Personalities : [raid1]
md0 : active raid1 sda1[0] sdb1[1]
      1000 blocks [2/2] [UU]

md1 : active raid1 sda2[0] sdb2[1]
      2000 blocks [2/2] [UU]

unused devices: <none>
"""


class TestRaidMdstatInit:

    def test_default_init(self):
        r = RaidMdstat()
        assert r.is_remote is False
        assert r.paths.find('mdstat') == '/proc/mdstat'

    def test_custom_path(self):
        r = RaidMdstat(mdstat='/custom/mdstat')
        assert r.paths.find('mdstat') == '/custom/mdstat'

    def test_remote_init(self):
        r = RaidMdstat(host='server1', port=22, user='root', password='pass')
        assert r.is_remote is True

    def test_not_remote_without_host(self):
        r = RaidMdstat(host=None)
        assert r.is_remote is False


class TestRaidMdstatValidateRemote:

    def test_valid_remote(self):
        r = RaidMdstat(host='server1', port=22, user='root', password='pass')
        assert r.validate_remote is True

    def test_invalid_port_zero(self):
        r = RaidMdstat(host='server1', port=0, user='root')
        assert r.validate_remote is False

    def test_invalid_no_user(self):
        r = RaidMdstat(host='server1', port=22, user='')
        assert r.validate_remote is False

    def test_invalid_empty_host(self):
        r = RaidMdstat(host='  ', port=22, user='root')
        assert r.validate_remote is False


class TestRaidMdstatIsExistLocal:

    @patch('lib.linux.raid_mdstat.os.path.isfile', return_value=True)
    def test_exist_local(self, mock_isfile):
        r = RaidMdstat(mdstat='/proc/mdstat')
        assert r.is_exist is True
        mock_isfile.assert_called_once_with('/proc/mdstat')

    @patch('lib.linux.raid_mdstat.os.path.isfile', return_value=False)
    def test_not_exist_local(self, mock_isfile):
        r = RaidMdstat(mdstat='/proc/mdstat')
        assert r.is_exist is False


class TestRaidMdstatIsExistRemote:

    @patch.object(RaidMdstat, '_exec_remote')
    def test_exist_remote(self, mock_exec):
        mock_exec.return_value = ("exists\n", "", None)
        r = RaidMdstat(host='server1', port=22, user='root', password='pass')
        assert r.is_exist is True

    @patch.object(RaidMdstat, '_exec_remote')
    def test_not_exist_remote(self, mock_exec):
        mock_exec.return_value = ("", "", None)
        r = RaidMdstat(host='server1', port=22, user='root', password='pass')
        assert r.is_exist is False

    @patch.object(RaidMdstat, '_exec_remote')
    def test_remote_stderr_returns_false(self, mock_exec):
        mock_exec.return_value = ("", "error occurred", None)
        r = RaidMdstat(host='server1', port=22, user='root', password='pass')
        assert r.is_exist is False

    def test_remote_invalid_config_returns_false(self):
        r = RaidMdstat(host='server1', port=0, user='')
        assert r.is_exist is False


class TestRaidMdstatReadStatusLocal:

    @patch('lib.linux.raid_mdstat.os.path.isfile', return_value=True)
    @patch('builtins.open')
    def test_read_ok(self, mock_open, mock_isfile):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = MDSTAT_OK
        r = RaidMdstat(mdstat='/proc/mdstat')
        result = r.read_status()
        assert 'md0' in result
        assert result['md0']['update'] == RaidMdstat.UpdateStatus.ok

    @patch('lib.linux.raid_mdstat.os.path.isfile', return_value=True)
    @patch('builtins.open')
    def test_read_degraded(self, mock_open, mock_isfile):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = MDSTAT_DEGRADED
        r = RaidMdstat(mdstat='/proc/mdstat')
        result = r.read_status()
        assert 'md0' in result
        assert result['md0']['update'] == RaidMdstat.UpdateStatus.error

    @patch('lib.linux.raid_mdstat.os.path.isfile', return_value=True)
    @patch('builtins.open')
    def test_read_recovery(self, mock_open, mock_isfile):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = MDSTAT_RECOVERY
        r = RaidMdstat(mdstat='/proc/mdstat')
        result = r.read_status()
        assert 'md0' in result
        assert result['md0']['update'] == RaidMdstat.UpdateStatus.recovery
        assert result['md0']['recovery']['percent'] == 5.2

    @patch('lib.linux.raid_mdstat.os.path.isfile', return_value=False)
    def test_read_not_exist(self, mock_isfile):
        r = RaidMdstat(mdstat='/proc/mdstat')
        result = r.read_status()
        assert result == {}

    @patch('lib.linux.raid_mdstat.os.path.isfile', return_value=True)
    @patch('builtins.open')
    def test_read_empty(self, mock_open, mock_isfile):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = MDSTAT_EMPTY
        r = RaidMdstat(mdstat='/proc/mdstat')
        result = r.read_status()
        assert result == {}

    @patch('lib.linux.raid_mdstat.os.path.isfile', return_value=True)
    @patch('builtins.open')
    def test_read_multiple_raids(self, mock_open, mock_isfile):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = MDSTAT_MULTI
        r = RaidMdstat(mdstat='/proc/mdstat')
        result = r.read_status()
        assert 'md0' in result
        assert 'md1' in result
        assert result['md0']['update'] == RaidMdstat.UpdateStatus.ok
        assert result['md1']['update'] == RaidMdstat.UpdateStatus.ok


class TestRaidMdstatReadStatusRemote:

    @patch.object(RaidMdstat, '_exec_remote')
    def test_read_remote_ok(self, mock_exec):
        # Primer llamada: is_exist -> "exists"
        # Segunda llamada: cat -> contenido mdstat
        mock_exec.side_effect = [
            ("exists\n", "", None),
            (MDSTAT_OK, "", None),
        ]
        r = RaidMdstat(host='server1', port=22, user='root', password='pass')
        result = r.read_status()
        assert 'md0' in result
        assert result['md0']['update'] == RaidMdstat.UpdateStatus.ok

    @patch.object(RaidMdstat, '_exec_remote')
    def test_read_remote_stderr_raises(self, mock_exec):
        mock_exec.side_effect = [
            ("exists\n", "", None),
            ("", "permission denied", None),
        ]
        r = RaidMdstat(host='server1', port=22, user='root', password='pass')
        with pytest.raises(Exception, match="ERROR"):
            r.read_status()


class TestUpdateStatusEnum:

    def test_values(self):
        assert RaidMdstat.UpdateStatus.unknown.value == 0
        assert RaidMdstat.UpdateStatus.ok.value == 1
        assert RaidMdstat.UpdateStatus.error.value == 2
        assert RaidMdstat.UpdateStatus.recovery.value == 3
