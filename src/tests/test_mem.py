#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for lib/linux/mem.py — MemInfo dataclass and Mem class."""

from unittest.mock import mock_open, patch

import pytest

from lib.linux.mem import Mem, MemInfo

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


# --- Mem._read_meminfo tests ---

MEMINFO_MODERN = """\
MemTotal:       16384000 kB
MemFree:         2000000 kB
MemAvailable:    8000000 kB
Buffers:          500000 kB
Cached:          3000000 kB
SwapTotal:       4096000 kB
SwapFree:        4000000 kB
"""

MEMINFO_LEGACY = """\
MemTotal:       16384000 kB
MemFree:         2000000 kB
Buffers:          500000 kB
Cached:          3000000 kB
SwapTotal:       4096000 kB
SwapFree:        4000000 kB
"""

MEMINFO_MINIMAL = """\
MemTotal:       1000 kB
MemFree:         500 kB
"""


class TestMemReadMeminfo:

    @patch('builtins.open', mock_open(read_data=MEMINFO_MODERN))
    def test_parses_all_keys(self):
        data = Mem._read_meminfo()
        assert data['MemTotal'] == 16384000
        assert data['MemFree'] == 2000000
        assert data['MemAvailable'] == 8000000
        assert data['Buffers'] == 500000
        assert data['Cached'] == 3000000
        assert data['SwapTotal'] == 4096000
        assert data['SwapFree'] == 4000000

    @patch('builtins.open', mock_open(read_data=MEMINFO_MINIMAL))
    def test_parses_minimal(self):
        data = Mem._read_meminfo()
        assert data['MemTotal'] == 1000
        assert data['MemFree'] == 500
        assert 'SwapTotal' not in data

    @patch('builtins.open', mock_open(read_data=""))
    def test_empty_file(self):
        data = Mem._read_meminfo()
        assert data == {}


# --- Mem.ram property tests ---

class TestMemRam:

    @patch('builtins.open', mock_open(read_data=MEMINFO_MODERN))
    def test_ram_uses_memavailable(self):
        """Modern kernels: free = MemAvailable."""
        m = Mem()
        ram = m.ram
        assert isinstance(ram, MemInfo)
        assert ram.total == 16384000
        assert ram.free == 8000000

    @patch('builtins.open', mock_open(read_data=MEMINFO_LEGACY))
    def test_ram_fallback_no_memavailable(self):
        """Legacy kernels: free = MemFree + Buffers + Cached."""
        m = Mem()
        ram = m.ram
        assert ram.total == 16384000
        assert ram.free == 2000000 + 500000 + 3000000  # 5500000

    @patch('builtins.open', mock_open(read_data=MEMINFO_MODERN))
    def test_ram_used(self):
        m = Mem()
        ram = m.ram
        assert ram.used == 16384000 - 8000000

    @patch('builtins.open', mock_open(read_data=MEMINFO_MODERN))
    def test_ram_used_percent(self):
        m = Mem()
        ram = m.ram
        expected = ((16384000 - 8000000) / 16384000) * 100.0
        assert ram.used_percent == pytest.approx(expected)


# --- Mem.swap property tests ---

class TestMemSwap:

    @patch('builtins.open', mock_open(read_data=MEMINFO_MODERN))
    def test_swap_values(self):
        m = Mem()
        swap = m.swap
        assert isinstance(swap, MemInfo)
        assert swap.total == 4096000
        assert swap.free == 4000000

    @patch('builtins.open', mock_open(read_data=MEMINFO_MODERN))
    def test_swap_used(self):
        m = Mem()
        swap = m.swap
        assert swap.used == 4096000 - 4000000

    @patch('builtins.open', mock_open(read_data=MEMINFO_MINIMAL))
    def test_swap_missing_keys(self):
        """If SwapTotal/SwapFree not in meminfo, defaults to 0."""
        m = Mem()
        swap = m.swap
        assert swap.total == 0
        assert swap.free == 0
        assert swap.used_percent == 0.0
