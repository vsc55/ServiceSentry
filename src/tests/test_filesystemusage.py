#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/filesystemusage.py."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.conftest import create_mock_monitor


def _part(device, mountpoint, fstype='ext4'):
    """Helper: crea un objeto similar a psutil partition."""
    return SimpleNamespace(device=device, mountpoint=mountpoint, fstype=fstype, opts='rw')


def _usage(percent):
    """Helper: crea un objeto similar a psutil disk_usage."""
    return SimpleNamespace(total=100_000_000, used=int(percent * 1_000_000), free=0, percent=percent)


class TestFilesystemUsageInit:

    def test_init(self):
        from watchfuls.filesystemusage import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.filesystemusage': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.filesystemusage'


class TestFilesystemUsageCheck:

    def setup_method(self):
        from watchfuls.filesystemusage import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.filesystemusage.psutil')
    def test_check_normal_usage(self, mock_psutil):
        """Particiones por debajo del umbral = OK."""
        mock_psutil.disk_partitions.return_value = [
            _part('/dev/sda1', '/'),
            _part('/dev/sda2', '/home'),
            _part('/dev/mmcblk0p6', '/boot'),
        ]
        mock_psutil.disk_usage.side_effect = lambda mp: {
            '/': _usage(17.0),
            '/home': _usage(6.0),
            '/boot': _usage(32.0),
        }[mp]

        config = {'watchfuls.filesystemusage': {'alert': 85, 'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list

        for val in items.values():
            assert val['status'] is True
            assert 'Filesystem' in val['message']

    @patch('watchfuls.filesystemusage.psutil')
    def test_check_high_usage(self, mock_psutil):
        """Partición por encima del umbral = warning."""
        mock_psutil.disk_partitions.return_value = [
            _part('/dev/sda1', '/'),
            _part('/dev/sda2', '/home'),
        ]
        mock_psutil.disk_usage.side_effect = lambda mp: {
            '/': _usage(90.0),
            '/home': _usage(6.0),
        }[mp]

        config = {'watchfuls.filesystemusage': {'alert': 85, 'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list

        assert items['/']['status'] is False
        assert 'Warning' in items['/']['message']
        assert items['/home']['status'] is True

    @patch('watchfuls.filesystemusage.psutil')
    def test_check_custom_alert_per_partition(self, mock_psutil):
        """Umbral personalizado por partición."""
        mock_psutil.disk_partitions.return_value = [
            _part('/dev/sda1', '/'),
        ]
        mock_psutil.disk_usage.side_effect = lambda mp: {
            '/': _usage(17.0),
        }[mp]

        config = {'watchfuls.filesystemusage': {'alert': 85, 'list': {'/': 10}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list

        # 17% > 10% → warning
        assert items['/']['status'] is False

    @patch('watchfuls.filesystemusage.psutil')
    def test_check_other_data(self, mock_psutil):
        """other_data contiene used, mount y alert."""
        mock_psutil.disk_partitions.return_value = [
            _part('/dev/sda1', '/'),
        ]
        mock_psutil.disk_usage.side_effect = lambda mp: {
            '/': _usage(17.0),
        }[mp]

        config = {'watchfuls.filesystemusage': {'alert': 85, 'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list

        other = items['/']['other_data']
        assert 'used' in other
        assert 'mount' in other
        assert 'alert' in other
        assert other['mount'] == '/'
        assert other['used'] == 17.0

    @patch('watchfuls.filesystemusage.psutil')
    def test_check_no_partitions(self, mock_psutil):
        """Sin particiones, no hay resultados."""
        mock_psutil.disk_partitions.return_value = []

        config = {'watchfuls.filesystemusage': {'alert': 85, 'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.filesystemusage.psutil')
    def test_check_exact_threshold(self, mock_psutil):
        """Uso exactamente en el umbral, no supera (float comparison)."""
        mock_psutil.disk_partitions.return_value = [
            _part('/dev/sda1', '/'),
        ]
        mock_psutil.disk_usage.side_effect = lambda mp: {
            '/': _usage(85.0),
        }[mp]

        config = {'watchfuls.filesystemusage': {'alert': 85, 'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list

        # 85% no es > 85% → OK
        assert items['/']['status'] is True

    @patch('watchfuls.filesystemusage.psutil')
    def test_ignored_fstypes(self, mock_psutil):
        """Pseudo-filesystems como tmpfs y squashfs se ignoran."""
        mock_psutil.disk_partitions.return_value = [
            _part('/dev/sda1', '/', 'ext4'),
            _part('tmpfs', '/run', 'tmpfs'),
            _part('squashfs', '/snap/core', 'squashfs'),
        ]
        mock_psutil.disk_usage.side_effect = lambda mp: _usage(50.0)

        config = {'watchfuls.filesystemusage': {'alert': 85, 'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list

        assert '/' in items
        assert '/run' not in items
        assert '/snap/core' not in items

    @patch('watchfuls.filesystemusage.psutil')
    def test_permission_error_skipped(self, mock_psutil):
        """Particiones con PermissionError se saltan sin error."""
        mock_psutil.disk_partitions.return_value = [
            _part('/dev/sda1', '/'),
            _part('/dev/sda2', '/restricted'),
        ]
        def fake_usage(mp):
            if mp == '/restricted':
                raise PermissionError("access denied")
            return _usage(50.0)
        mock_psutil.disk_usage.side_effect = fake_usage

        config = {'watchfuls.filesystemusage': {'alert': 85, 'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list

        assert '/' in items
        assert '/restricted' not in items

    @patch('watchfuls.filesystemusage.psutil')
    def test_windows_style_partitions(self, mock_psutil):
        """Particiones estilo Windows (C:\\, D:\\)."""
        mock_psutil.disk_partitions.return_value = [
            _part('C:\\', 'C:\\', 'NTFS'),
            _part('D:\\', 'D:\\', 'NTFS'),
        ]
        mock_psutil.disk_usage.side_effect = lambda mp: {
            'C:\\': _usage(88.0),
            'D:\\': _usage(45.0),
        }[mp]

        config = {'watchfuls.filesystemusage': {'alert': 85, 'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list

        assert items['C:\\']['status'] is False
        assert items['D:\\']['status'] is True
