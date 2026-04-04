#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para lib/tools.py — bytes2human."""

from lib.tools import bytes2human


class TestBytes2Human:

    def test_bytes(self):
        assert bytes2human(0) == "0B"

    def test_bytes_small(self):
        assert bytes2human(100) == "100B"

    def test_kilobytes(self):
        assert bytes2human(1024) == "1.0K"

    def test_kilobytes_fraction(self):
        assert bytes2human(1536) == "1.5K"

    def test_megabytes(self):
        assert bytes2human(1048576) == "1.0M"

    def test_gigabytes(self):
        assert bytes2human(1073741824) == "1.0G"

    def test_terabytes(self):
        assert bytes2human(1099511627776) == "1.0T"

    def test_large_gigabytes(self):
        # 10 GB
        result = bytes2human(10 * 1073741824)
        assert result == "10.0G"

    def test_just_under_1k(self):
        assert bytes2human(1023) == "1023B"

    def test_exactly_2k(self):
        assert bytes2human(2048) == "2.0K"

    def test_mixed_megabytes(self):
        # 1.5 MB
        assert bytes2human(1572864) == "1.5M"
