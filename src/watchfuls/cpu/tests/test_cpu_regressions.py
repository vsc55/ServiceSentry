#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/cpu found by the 2026-10-12 audit."""


class TestGuestNotCountedTwice:
    """/proc/stat's guest and guest_nice are already inside user and nice. Summing all ten
    columns counted guest time twice and inflated the busy % on any hypervisor."""

    def test_guest_time_does_not_inflate_usage(self):
        from watchfuls.cpu import Watchful
        # +1000 jiffies, idle +250 → 75 % busy; 500 of the user time was guest time.
        out = ("cpu  1000 0 0 8000 1000 0 0 0 0 0\n"
               "cpu  1750 0 0 8250 1000 0 0 0 500 0\n")
        assert round(Watchful._parse_proc_stat(out), 1) == 75.0

    def test_steal_still_counts(self):
        from watchfuls.cpu import Watchful
        # steal is the 8th column and IS part of the total: +1000 with +250 idle → 75 %.
        out = ("cpu  1000 0 0 8000 1000 0 0 0 0 0\n"
               "cpu  1500 0 0 8250 1000 0 0 250 0 0\n")
        assert round(Watchful._parse_proc_stat(out), 1) == 75.0
