#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for lib/mem.py — MemInfo dataclass and Mem class."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lib.mem import Mem, MemInfo

# --- MemInfo dataclass tests ---

class TestMemInfo:

    def test_defaults(self):
        m = MemInfo()
        assert m.total == 0
        assert m.free == 0

    def test_custom_values(self):
        m = MemInfo(total=8000, free=3000)
        assert m.total == 8000
        assert m.free == 3000

    def test_used(self):
        m = MemInfo(total=8000, free=3000)
        assert m.used == 5000

    def test_used_when_free_equals_total(self):
        m = MemInfo(total=8000, free=8000)
        assert m.used == 0

    def test_used_percent(self):
        m = MemInfo(total=1000, free=400)
        assert m.used_percent == pytest.approx(60.0)

    def test_used_percent_zero_total(self):
        """total=0 should return 0.0, not raise ZeroDivisionError."""
        m = MemInfo(total=0, free=0)
        assert m.used_percent == 0.0

    def test_used_percent_negative_total(self):
        """Negative total should return 0.0."""
        m = MemInfo(total=-100, free=50)
        assert m.used_percent == 0.0

    def test_used_percent_100(self):
        m = MemInfo(total=1000, free=0)
        assert m.used_percent == pytest.approx(100.0)

    def test_used_percent_precision(self):
        m = MemInfo(total=3, free=1)
        assert m.used_percent == pytest.approx(66.6666, rel=1e-3)


# --- Mem.ram property tests ---

class TestMemRam:

    @patch('lib.mem.psutil')
    def test_ram_values(self, mock_psutil):
        """total and available converted from bytes to kB."""
        mock_psutil.virtual_memory.return_value = SimpleNamespace(
            total=16_777_216_000, available=8_388_608_000,
        )
        ram = Mem().ram
        assert isinstance(ram, MemInfo)
        assert ram.total == 16_777_216_000 // 1024
        assert ram.free == 8_388_608_000 // 1024

    @patch('lib.mem.psutil')
    def test_ram_used(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = SimpleNamespace(
            total=16_000_000_000, available=6_000_000_000,
        )
        ram = Mem().ram
        assert ram.used == (16_000_000_000 - 6_000_000_000) // 1024

    @patch('lib.mem.psutil')
    def test_ram_used_percent(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = SimpleNamespace(
            total=10_000_000_000, available=4_000_000_000,
        )
        ram = Mem().ram
        expected = ((10_000_000_000 - 4_000_000_000) / 10_000_000_000) * 100.0
        assert ram.used_percent == pytest.approx(expected)

    @patch('lib.mem.psutil')
    def test_ram_all_free(self, mock_psutil):
        """Edge case: all memory available."""
        mock_psutil.virtual_memory.return_value = SimpleNamespace(
            total=8_000_000_000, available=8_000_000_000,
        )
        ram = Mem().ram
        assert ram.used == 0
        assert ram.used_percent == 0.0


# --- Mem.swap property tests ---

class TestMemSwap:

    @patch('lib.mem.psutil')
    def test_swap_values(self, mock_psutil):
        """total and free converted from bytes to kB."""
        mock_psutil.swap_memory.return_value = SimpleNamespace(
            total=4_294_967_296, used=104_857_600,
        )
        swap = Mem().swap
        assert isinstance(swap, MemInfo)
        assert swap.total == 4_294_967_296 // 1024
        assert swap.free == (4_294_967_296 - 104_857_600) // 1024

    @patch('lib.mem.psutil')
    def test_swap_used(self, mock_psutil):
        mock_psutil.swap_memory.return_value = SimpleNamespace(
            total=4_000_000_000, used=500_000_000,
        )
        swap = Mem().swap
        expected_total = 4_000_000_000 // 1024
        expected_free = (4_000_000_000 - 500_000_000) // 1024
        assert swap.used == expected_total - expected_free

    @patch('lib.mem.psutil')
    def test_swap_zero(self, mock_psutil):
        """System with no swap configured."""
        mock_psutil.swap_memory.return_value = SimpleNamespace(
            total=0, used=0,
        )
        swap = Mem().swap
        assert swap.total == 0
        assert swap.free == 0
        assert swap.used_percent == 0.0

    @patch('lib.mem.psutil')
    def test_swap_fully_used(self, mock_psutil):
        """Edge case: all swap used."""
        mock_psutil.swap_memory.return_value = SimpleNamespace(
            total=2_000_000_000, used=2_000_000_000,
        )
        swap = Mem().swap
        assert swap.free == 0
        assert swap.used_percent == pytest.approx(100.0)
