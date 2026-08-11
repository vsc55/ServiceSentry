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


class TestACopyKnowsWhichTaskTookIt:
    """Retention counts per task, so the name has to say which one produced the file.

    Without it a daily task and a monthly one share a counter, and the daily one prunes the
    monthly one's copies — deleting exactly the ones that took a month to become worth having.
    """

    def test_the_name_carries_the_task(self):
        n = sched.auto_name(dt.datetime(2026, 8, 9, 3, 0, 0), 'Diaria config')
        assert n == 'auto-diaria-config-20260809-030000'

    def test_a_task_name_cannot_steer_the_path(self):
        """The slug is what appears in a FILE NAME. A task called `../etc` would otherwise
        decide where its own copies are written."""
        n = sched.auto_name(dt.datetime(2026, 8, 9, 3, 0, 0), '../etc/passwd')
        assert '/' not in n and chr(92) not in n and '..' not in n

    def test_a_task_only_sees_its_own(self):
        assert sched.is_auto('auto-diaria-20260809-030000', 'diaria') is True
        assert sched.is_auto('auto-mensual-20260809-030000', 'diaria') is False
        assert sched.is_auto('copia-a-mano', 'diaria') is False

    def test_copies_from_before_tasks_existed_are_not_orphaned(self):
        """`auto-<date>`, with no task in it. Something has to still recognise them, or the
        upgrade would leave every copy already on disk outside every counter — never pruned,
        and never counted as "the last one" either."""
        old = 'auto-20260101-000000'
        assert sched.is_auto(old) is True            # any task at all
        assert sched.is_auto(old, '') is True        # the unnamed task owns them
        assert sched.is_auto(old, 'diaria') is False  # a named one does not claim them

    def test_the_clock_is_per_task(self):
        rows = [_b('auto-diaria-20260809-030000', 500),
                _b('auto-mensual-20260809-030000', 900)]
        assert sched.last_auto_ts(rows, 'diaria') == 500
        assert sched.last_auto_ts(rows, 'mensual') == 900
        assert sched.last_auto_ts(rows) == 900       # any of them

    def test_retention_never_crosses_tasks(self):
        """The bug this whole redesign exists to avoid."""
        rows = [_b('auto-diaria-1', 1), _b('auto-diaria-2', 2), _b('auto-diaria-3', 3),
                _b('auto-mensual-1', 4)]
        assert sched.prune(rows, 1, 'diaria') == ['auto-diaria-1', 'auto-diaria-2']
        assert sched.prune(rows, 1, 'mensual') == []


class TestSayingWhenByTheCalendar:
    """"Every N hours" survives the panel being down but drifts and cannot say "Mondays at
    03:00". A wall-clock rule says exactly that and, asked naively, misses its window whenever
    the process was not up for it.

    So it is asked the other way round: what was the most recent moment this task was DUE, and
    has a copy been taken since? True from the moment the window passes until one is taken —
    which keeps the catch-up the interval gave for free.
    """

    LUN_9 = dt.datetime(2026, 8, 10, 9, 0)      # a Monday, 09:00

    def test_daily_uses_todays_window_once_it_has_passed(self):
        assert sched.last_due_at(self.LUN_9, [], '03:00') == dt.datetime(2026, 8, 10, 3, 0)

    def test_before_the_hour_it_is_yesterdays(self):
        early = dt.datetime(2026, 8, 10, 1, 0)
        assert sched.last_due_at(early, [], '03:00') == dt.datetime(2026, 8, 9, 3, 0)

    def test_a_day_not_chosen_falls_back_to_the_last_one_that_was(self):
        """Tuesday 01:00 with Mon+Wed selected: the last window was Monday's."""
        mar = dt.datetime(2026, 8, 11, 1, 0)
        assert sched.last_due_at(mar, [0, 2], '03:00') == dt.datetime(2026, 8, 10, 3, 0)

    def test_a_window_missed_while_the_panel_was_down_is_still_due(self):
        """The property the interval model had and a naive clock check does not."""
        sunday = dt.datetime(2026, 8, 9, 3, 0).timestamp()
        assert sched.is_due_calendar(self.LUN_9, [], '03:00', sunday) is True

    def test_not_due_again_once_it_has_run(self):
        today = dt.datetime(2026, 8, 10, 3, 5).timestamp()
        assert sched.is_due_calendar(self.LUN_9, [], '03:00', today) is False

    def test_with_no_copy_yet_it_is_due(self):
        """Waiting for next Monday to find out the path was wrong is a week of believing in a
        backup that does not exist."""
        assert sched.is_due_calendar(self.LUN_9, [0], '03:00', None) is True

    def test_no_day_ticked_means_every_day(self):
        """Never "no days": a task somebody created that silently never runs is the failure
        this whole feature exists against."""
        assert sched.normalise_days([]) == []
        assert sched.last_due_at(self.LUN_9, [], '03:00') is not None

    def test_all_seven_collapse_to_every_day(self):
        assert sched.normalise_days([0, 1, 2, 3, 4, 5, 6]) == []

    def test_nonsense_days_are_dropped(self):
        """A day nothing can match is a task that looks scheduled and never runs."""
        assert sched.normalise_days(['lunes', 9, -1, None]) == []
        assert sched.normalise_days([2, 2, 0]) == [0, 2]

    def test_a_bad_time_falls_back_instead_of_raising(self):
        """An operator types this, and a typo must not stop the scheduler thread."""
        for bad in ('', '25:00', 'tres', None, '3'):
            assert sched.parse_at(bad) == (3, 0), bad
        assert sched.parse_at('07:45') == (7, 45)

    def test_one_entry_point_answers_for_both_kinds(self):
        """A scheduler that branched on mode at each call is a scheduler with two places to get
        the catch-up wrong."""
        now = self.LUN_9.timestamp()
        interval = {'mode': 'interval', 'every_hours': 24}
        calendar = {'mode': 'calendar', 'days': [0], 'at': '03:00'}
        assert sched.task_is_due(interval, now, None) is True
        assert sched.task_is_due(calendar, now, None) is True
        assert sched.task_is_due(calendar, now, dt.datetime(2026, 8, 10, 3, 5).timestamp()) is False
        # A task with no mode at all is an interval one — that is what every task was before
        # the calendar existed, and they must keep running.
        assert sched.task_is_due({'every_hours': 24}, now, None) is True
