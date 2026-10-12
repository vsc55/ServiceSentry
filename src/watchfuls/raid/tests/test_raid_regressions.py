#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for the RAID mdstat parser found by the 2026-10-12 audit."""

from lib.system.linux.raid_mdstat import RaidMdstat

_RAID0 = """Personalities : [raid0]
md0 : active raid0 sdb1[1] sda1[0]
      1953260544 blocks super 1.2 512k chunks

unused devices: <none>
"""

_LINEAR = """Personalities : [linear]
md1 : active linear sdc1[1] sdd1[0]
      976630464 blocks super 1.2 0k rounding

unused devices: <none>
"""


class TestNonRedundantArrays:
    """RAID0 and linear arrays print no [n/m] counter (they have no redundancy to count), so
    they were left without a state and reported "unknown" forever."""

    def test_an_active_raid0_is_ok(self):
        md = RaidMdstat.parse_lines(_RAID0)
        assert md['md0']['update'] == RaidMdstat.UpdateStatus.ok

    def test_an_active_linear_is_ok(self):
        md = RaidMdstat.parse_lines(_LINEAR)
        assert md['md1']['update'] == RaidMdstat.UpdateStatus.ok

    def test_a_raid1_without_counter_stays_unknown(self):
        """Only the arrays that CANNOT carry a counter are settled by "active"."""
        text = _RAID0.replace('raid0', 'raid1')
        assert 'update' not in RaidMdstat.parse_lines(text)['md0']
