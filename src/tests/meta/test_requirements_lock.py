#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""requirements.lock pins everything requirements.txt asks for, at a version the floor accepts.

`requirements.txt` is the intent; the lock is what Docker, the packages and CI install. PyYAML
was added to the first for the device-type catalogue and the lock was never regenerated, so
every installation built from the lock shipped without it — and the importer, which degrades
quietly when the module is missing, said nothing. A floor raised for a CVE and left
unsatisfied in the lock would be the same mistake with a worse ending.
"""

import os
import re

from tests.helpers import _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]

_REQ = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(>=\s*([0-9][0-9A-Za-z.]*))?')
_PIN = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][0-9A-Za-z.]*)')


def _norm(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def _version(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r'[.]', v))


def _wanted():
    out = {}
    for line in _read(os.path.join(SRC, 'requirements.txt')).splitlines():
        line = line.split('#', 1)[0]
        m = _REQ.match(line)
        if m:
            out[_norm(m.group(1))] = m.group(3) or ''
    return out


def _pinned():
    out = {}
    for line in _read(os.path.join(SRC, 'requirements.lock')).splitlines():
        m = _PIN.match(line)
        if m:
            out[_norm(m.group(1))] = m.group(2)
    return out


class TestTheLockHoldsWhatIsRequired:

    def test_every_requirement_is_pinned(self):
        pinned = _pinned()
        missing = sorted(set(_wanted()) - set(pinned))
        assert not missing, (f'in requirements.txt but not in requirements.lock: {missing} — '
                             'regenerate the lock (see the header of requirements.txt)')

    def test_every_floor_is_met_by_its_pin(self):
        pinned = _pinned()
        low = [f'{n} {pinned[n]} < {floor}' for n, floor in _wanted().items()
               if floor and n in pinned and _version(pinned[n]) < _version(floor)]
        assert not low, f'the lock pins below the floor: {low}'

    def test_the_guard_reads_the_real_files(self):
        """Not vacuous: both files parse into something, and a known pair is seen."""
        wanted, pinned = _wanted(), _pinned()
        assert 'flask' in wanted and 'flask' in pinned
        assert len(pinned) >= len(wanted)
