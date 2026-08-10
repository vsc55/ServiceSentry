#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""When an automatic copy is due, and which old ones go.

An INTERVAL, not a time of day, and the difference is the whole design: a panel that was down
at 03:00 must still take its daily copy when it comes back at 09:00. "How long since the last
one" stays true until a copy is taken; "is it 03:00 now" is false 1439 minutes out of 1440 and
misses the window entirely if the process was not up for it. A missed window is the case a
backup exists for.

Flask-free and clock-free: every function here takes the time as an argument, so the tests state
a situation instead of waiting for one.
"""

import datetime as dt

from lib.core.backup import schedule as sched

HOUR = 3600.0


def _b(name, mtime):
    return {'name': name, 'mtime': mtime}


class TestWhenOneIsDue:

    def test_zero_hours_is_off(self):
        """0 is how the config says "no automatic copies" — and it has to be, because a field
        an operator types into will sooner or later hold a 0."""
        assert sched.is_due(0, 1_000_000, None) is False

    def test_an_unreadable_interval_is_off_not_every_tick(self):
        """A typo must not turn the scheduler into a loop that copies on every tick."""
        for bad in ('', 'diario', None, 'abc'):
            assert sched.is_due(bad, 1_000_000, None) is False, bad

    def test_with_no_copy_yet_one_is_due_immediately(self):
        """An install that has never taken one is the install that most needs it, and waiting
        a full interval to start would hide a misconfigured path for a day."""
        assert sched.is_due(24, 1_000_000, None) is True

    def test_not_due_before_the_interval_has_passed(self):
        now = 1_000_000
        assert sched.is_due(24, now, now - 23 * HOUR) is False

    def test_due_once_it_has(self):
        now = 1_000_000
        assert sched.is_due(24, now, now - 24 * HOUR) is True

    def test_a_window_missed_while_the_panel_was_down_is_still_due(self):
        """The whole reason this is an interval. Three days off, and the copy happens on the
        way back up rather than being skipped because 03:00 passed unattended."""
        now = 1_000_000
        assert sched.is_due(24, now, now - 3 * 24 * HOUR) is True


class TestWhichCopyCounts:

    def test_only_automatic_copies_set_the_clock(self):
        """Taking one by hand before an upgrade must not push the scheduled one back a whole
        interval: they answer different questions, and only one of them is a promise."""
        assert sched.last_auto_ts([_b('antes-de-actualizar', 999)]) is None
        assert sched.last_auto_ts([_b('auto-20260808-0300', 500),
                                   _b('antes-de-actualizar', 999)]) == 500

    def test_the_newest_automatic_one_wins(self):
        assert sched.last_auto_ts([_b('auto-a', 100), _b('auto-b', 300)]) == 300

    def test_an_empty_folder_has_no_clock(self):
        assert sched.last_auto_ts([]) is None


class TestRetention:

    def test_it_keeps_the_newest_n(self):
        rows = [_b(f'auto-{i}', i) for i in range(10)]
        assert sorted(sched.prune(rows, 3)) == sorted(f'auto-{i}' for i in range(7))

    def test_zero_keeps_everything(self):
        """An operator who prunes elsewhere must be able to say so, and reading zero as
        "delete them all" is the reading that loses data."""
        assert sched.prune([_b('auto-a', 1), _b('auto-b', 2)], 0) == []

    def test_a_nonsense_value_deletes_nothing(self):
        for bad in ('', None, 'siete'):
            assert sched.prune([_b('auto-a', 1)], bad) == [], bad

    def test_a_hand_made_copy_is_never_pruned(self):
        """It was taken before an upgrade, by somebody who meant it. A counter does not get to
        throw that away."""
        rows = [_b('auto-1', 1), _b('auto-2', 2), _b('antes-de-actualizar', 3)]
        assert sched.prune(rows, 1) == ['auto-1']

    def test_fewer_copies_than_the_limit_prunes_nothing(self):
        assert sched.prune([_b('auto-a', 1)], 7) == []


class TestTheName:

    def test_it_says_what_made_it(self):
        """Recognised by name and not recorded in a table: the files are the truth — somebody
        can copy one in, or delete one with the panel stopped — and a name that says what made
        it survives being moved to another machine."""
        name = sched.auto_name(dt.datetime(2026, 8, 8, 3, 0, 30))
        assert name.startswith(sched.AUTO_PREFIX)
        assert sched.is_auto(name) and not sched.is_auto('copia-manual')

    def test_two_copies_in_the_same_minute_do_not_collide(self):
        """`create_backup` refuses to overwrite, so a name without seconds would make the
        second copy of a minute fail rather than land."""
        a = sched.auto_name(dt.datetime(2026, 8, 8, 3, 0, 10))
        b = sched.auto_name(dt.datetime(2026, 8, 8, 3, 0, 40))
        assert a != b
