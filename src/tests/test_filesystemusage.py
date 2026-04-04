#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/filesystemusage.py."""

import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import create_mock_monitor


# Salida típica de df
DF_OUTPUT = """\
Filesystem     1K-blocks    Used Available Use% Mounted on
/dev/sda1       51474016 8203456  40634112  17% /
/dev/sda2      102948032 5120000  92555776   6% /home
/dev/mmcblk0p6    253871   81510    172361  32% /boot
"""

DF_OUTPUT_HIGH_USAGE = """\
Filesystem     1K-blocks    Used Available Use% Mounted on
/dev/sda1       51474016 45000000  6474016  90% /
/dev/sda2      102948032 5120000  92555776   6% /home
"""


class TestFilesystemUsageInit:

    def test_init(self):
        from watchfuls.filesystemusage import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.filesystemusage': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.filesystemusage'
        assert w.paths.find('df') == '/bin/df'


class TestFilesystemUsageCheck:

    def setup_method(self):
        from watchfuls.filesystemusage import Watchful
        self.Watchful = Watchful

    def test_check_normal_usage(self):
        """Particiones por debajo del umbral = OK."""
        config = {
            'watchfuls.filesystemusage': {
                'alert': 85,
                'list': {},
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=DF_OUTPUT):
            result = w.check()
            items = result.list
            # sda1 (17%), sda2 (6%), mmcblk0p6 (32%) — todos < 85%
            for key, val in items.items():
                assert val['status'] is True
                assert 'Filesystem' in val['message']

    def test_check_high_usage(self):
        """Partición por encima del umbral = warning."""
        config = {
            'watchfuls.filesystemusage': {
                'alert': 85,
                'list': {},
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=DF_OUTPUT_HIGH_USAGE):
            result = w.check()
            items = result.list
            # sda1 (90% > 85%) → warning, sda2 (6%) → OK
            assert items['sda1']['status'] is False
            assert 'Warning' in items['sda1']['message']
            assert items['sda2']['status'] is True

    def test_check_custom_alert_per_partition(self):
        """Umbral personalizado por partición."""
        config = {
            'watchfuls.filesystemusage': {
                'alert': 85,
                'list': {
                    '/': 10,  # umbral muy bajo para /
                },
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=DF_OUTPUT):
            result = w.check()
            items = result.list
            # sda1 (17% > 10%) → warning
            assert items['sda1']['status'] is False

    def test_check_other_data(self):
        """other_data contiene used, mount y alert."""
        config = {
            'watchfuls.filesystemusage': {
                'alert': 85,
                'list': {},
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=DF_OUTPUT):
            result = w.check()
            items = result.list
            if 'sda1' in items:
                other = items['sda1']['other_data']
                assert 'used' in other
                assert 'mount' in other
                assert 'alert' in other
                assert other['mount'] == '/'

    def test_check_no_output(self):
        """Sin salida de df, no hay resultados."""
        config = {
            'watchfuls.filesystemusage': {
                'alert': 85,
                'list': {},
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=""):
            result = w.check()
            assert len(result.items()) == 0

    def test_check_exact_threshold(self):
        """Uso exactamente en el umbral, no supera (float comparison)."""
        df_exact = """\
Filesystem     1K-blocks    Used Available Use% Mounted on
/dev/sda1       51474016 8203456  40634112  85% /
"""
        config = {
            'watchfuls.filesystemusage': {
                'alert': 85,
                'list': {},
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=df_exact):
            result = w.check()
            items = result.list
            # 85% no es > 85% → OK
            assert items['sda1']['status'] is True
