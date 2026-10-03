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
        rows = [_b('auto-diaria-20260801-030000', 1), _b('auto-diaria-20260802-030000', 2),
                _b('auto-diaria-20260803-030000', 3), _b('auto-mensual-20260801-030000', 4)]
        assert sched.prune(rows, 1, 'diaria') == ['auto-diaria-20260801-030000',
                                                  'auto-diaria-20260802-030000']
        assert sched.prune(rows, 1, 'mensual') == []

    def test_a_task_does_not_claim_one_whose_name_extends_its_own(self):
        """Task "db" and task "db-full": a prefix test on `auto-db-` also matched
        `auto-db-full-<stamp>`, so "db" keeping one copy deleted every copy "db-full" had."""
        t0 = 1_780_000_000
        rows = [_b(sched.auto_name(dt.datetime.fromtimestamp(t0 + i * HOUR), 'db-full'),
                   t0 + i * HOUR) for i in range(5)]
        rows.append(_b(sched.auto_name(dt.datetime.fromtimestamp(t0 + 9 * HOUR), 'db'),
                       t0 + 9 * HOUR))
        assert sched.prune(rows, {'keep_last': 1}, 'db') == []
        assert sched.prune(rows, {'keep_last': 1}, 'db-full') == [b['name'] for b in rows[:4]]

    def test_the_clock_of_a_task_ignores_the_copies_of_a_longer_name(self):
        """`last_auto_ts` reported db-full's copies as db's latest, so "db" never ran."""
        rows = [_b('auto-db-full-20260809-030000', 900)]
        assert sched.last_auto_ts(rows, 'db') is None
        assert sched.last_auto_ts(rows, 'db-full') == 900

    def test_only_the_exact_stamp_belongs_to_a_task(self):
        assert sched.is_auto('auto-db-20260809-030000', 'db') is True
        assert sched.is_auto('auto-db-full-20260809-030000', 'db') is False
        assert sched.is_auto('auto-db-20260809-030000-extra', 'db') is False
        assert sched.is_auto('auto-db-2026', 'db') is False

    def test_the_unscoped_copies_do_not_claim_a_task_named_with_digits(self):
        """`auto-<stamp>` was recognised by "a digit after the prefix", which also matched the
        copies of a task called `2024`."""
        assert sched.is_auto('auto-2024-20260809-030000', '') is False
        assert sched.is_auto('auto-2024-20260809-030000', '2024') is True
        assert sched.is_auto('auto-20260809-030000', '') is True


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


class TestRetentionKeepsHistoryNotJustCopies:
    """A counter answers "how many do I keep?". The question worth answering is "how far back
    can I go, and at what resolution?" — and seven copies can be one week at daily resolution
    or two years at monthly. Only the second survives finding out in March that something broke
    in January."""

    @staticmethod
    def _daily(n, task='diaria', status='ok', size=1):
        """*n* copies, one a day, newest first."""
        import datetime as dt
        base = dt.datetime(2026, 8, 11, 3, 0)
        return [{'name': sched.auto_name(base - dt.timedelta(days=i), task),
                 'mtime': (base - dt.timedelta(days=i)).timestamp(),
                 'size': size, 'status': status} for i in range(n)]

    def test_buckets_buy_years_of_history_for_the_price_of_days(self):
        rows = self._daily(400)
        policy = {'keep_last': 3, 'keep_daily': 7, 'keep_weekly': 4,
                  'keep_monthly': 6, 'keep_yearly': 2}
        kept = sched.survivors(rows, policy, 'diaria')
        assert 12 <= len(kept) <= 20, len(kept)
        # The claim, stated as the comparison it actually is: the SAME number of copies buys
        # months of history instead of a fortnight of it. (Each bucket keeps the NEWEST copy of
        # its period, so "2 yearly" reaches back to last 31 December — not to the oldest file.)
        span = (kept[0]['mtime'] - kept[-1]['mtime']) / 86400
        flat = sched.survivors(rows, {'keep_last': len(kept)}, 'diaria')
        flat_span = (flat[0]['mtime'] - flat[-1]['mtime']) / 86400
        assert span > 200 and span > flat_span * 10, (span, flat_span)

    def test_a_copy_survives_if_any_rule_claims_it(self):
        """The union, not the intersection — which is what makes the numbers add up to 17
        instead of 180."""
        rows = self._daily(40)
        only_weekly = sched.survivors(rows, {'keep_weekly': 3}, 'diaria')
        both = sched.survivors(rows, {'keep_weekly': 3, 'keep_last': 5}, 'diaria')
        assert {b['name'] for b in only_weekly} <= {b['name'] for b in both}

    def test_nothing_configured_keeps_everything(self):
        """An operator who prunes elsewhere must be able to say so, and reading "no rules" as
        "delete them all" is the reading that loses data."""
        rows = self._daily(20)
        assert sched.prune(rows, {}, 'diaria') == []
        assert sched.prune(rows, {'keep_last': 0, 'keep_daily': 0}, 'diaria') == []

    def test_the_old_single_counter_still_means_what_it_meant(self):
        """A task that was working must not need rewriting to go on working."""
        rows = self._daily(20)
        assert len(sched.survivors(rows, 7, 'diaria')) == 7
        assert len(sched.survivors(rows, {'keep': 7}, 'diaria')) == 7

    def test_deletions_are_the_complement_and_come_oldest_first(self):
        rows = self._daily(30)
        policy = {'keep_last': 2, 'keep_daily': 5}
        gone = sched.prune(rows, policy, 'diaria')
        kept = sched.survivors(rows, policy, 'diaria')
        assert len(gone) + len(kept) == len(rows)
        assert not ({b['name'] for b in kept} & set(gone))
        assert gone[0].endswith('20260713-030000'), gone[0]      # the oldest of the 30

    def test_a_hand_made_copy_is_never_touched(self):
        rows = self._daily(10) + [{'name': 'copia-a-mano', 'mtime': 0, 'size': 1}]
        assert 'copia-a-mano' not in sched.prune(rows, {'keep_last': 1}, 'diaria')


class TestTheFloorsNoBucketCanExpress:

    @staticmethod
    def _rows(statuses):
        import datetime as dt
        base = dt.datetime(2026, 8, 11, 3, 0)
        return [{'name': sched.auto_name(base - dt.timedelta(days=i), 'x'),
                 'mtime': (base - dt.timedelta(days=i)).timestamp(),
                 'size': 10, 'status': st} for i, st in enumerate(statuses)]

    def test_the_newest_copy_is_never_deleted(self):
        """A policy that leaves a task with nothing has misconfigured the one thing it exists
        to provide, and that is found out at restore time."""
        rows = self._rows(['ok'] * 5)
        gone = sched.prune(rows, {'keep_last': 0, 'keep_daily': 0, 'max_size': 1}, 'x')
        assert rows[0]['name'] not in gone

    def test_the_newest_GOOD_copy_survives_a_run_of_partial_ones(self):
        """Otherwise seven copies remain of which none is usable. The verdict already travels
        inside the archive, so this costs a lookup and no guesswork."""
        rows = self._rows(['partial', 'partial', 'partial', 'ok', 'ok'])
        gone = sched.prune(rows, {'keep_last': 2}, 'x')
        assert rows[3]['name'] not in gone, 'the last good copy was pruned'
        assert rows[4]['name'] in gone, 'the OLDER good one is not protected too'

    def test_with_no_good_copy_at_all_it_protects_nothing_extra(self):
        rows = self._rows(['partial'] * 4)
        assert len(sched.prune(rows, {'keep_last': 1}, 'x')) == 3


class TestTheSizeBudget:

    @staticmethod
    def _rows(n, size):
        import datetime as dt
        base = dt.datetime(2026, 8, 11, 3, 0)
        return [{'name': sched.auto_name(base - dt.timedelta(days=i), 'x'),
                 'mtime': (base - dt.timedelta(days=i)).timestamp(),
                 'size': size, 'status': 'ok'} for i in range(n)]

    def test_it_drops_the_oldest_until_they_fit(self):
        rows = self._rows(10, 10)                      # 100 units in total
        gone = sched.prune(rows, {'keep_last': 10, 'max_size': 35}, 'x')
        assert len(rows) - len(gone) == 3

    def test_it_can_only_take_away_what_the_rules_kept(self):
        """The buckets say what is worth keeping; the budget says what there is room for."""
        rows = self._rows(10, 1)
        gone = sched.prune(rows, {'keep_last': 4, 'max_size': 1000}, 'x')
        assert len(rows) - len(gone) == 4, 'a roomy budget added copies the rules dropped'

    def test_zero_means_no_budget(self):
        rows = self._rows(5, 10 ** 9)
        assert sched.prune(rows, {'keep_last': 5, 'max_size': 0}, 'x') == []

    def test_running_out_of_room_still_leaves_one(self):
        """The floors are applied after the budget: no room is not a reason to be left with
        nothing."""
        rows = self._rows(4, 10 ** 9)
        gone = sched.prune(rows, {'keep_last': 4, 'max_size': 1}, 'x')
        assert len(gone) == 3 and rows[0]['name'] not in gone


class TestALockedCopyIsNotACandidate:
    """The buckets answer "how much history" and the floors answer "never leave the task with
    nothing". Neither can say *this particular archive*."""

    @staticmethod
    def _rows(n, locked=(), size=10):
        base = dt.datetime(2026, 8, 11, 3, 0)
        return [{'name': sched.auto_name(base - dt.timedelta(days=i), 'x'),
                 'mtime': (base - dt.timedelta(days=i)).timestamp(),
                 'size': size, 'status': 'ok', 'locked': i in locked} for i in range(n)]

    def test_it_is_never_pruned(self):
        rows = self._rows(6, locked=(5,))
        gone = sched.prune(rows, {'keep_last': 1}, 'x')
        assert rows[5]['name'] not in gone
        assert len(gone) == 4, gone

    def test_it_still_claims_its_bucket(self):
        """Filtered at the END and not hidden from the rules: protecting the newest copy of a
        day must not silently buy the task a second one for that day."""
        rows = self._rows(6, locked=(0,))
        assert len(sched.survivors(rows, {'keep_last': 3}, 'x')) == 3

    def test_the_budget_spends_its_size_but_cannot_drop_it(self):
        """The room it takes is gone whether or not the ceiling acknowledges it — and a ceiling
        that could delete it would override the one instruction the lock exists to give."""
        rows = self._rows(4, locked=(3,), size=10)         # the OLDEST is locked
        gone = sched.prune(rows, {'keep_last': 4, 'max_size': 25}, 'x')
        assert rows[3]['name'] not in gone
        kept = len(rows) - len(gone)
        assert kept == 2, [r['name'] for r in rows if r['name'] not in gone]


class TestAPolicyWithANameOnIt:
    """A task states its own retention or FOLLOWS a shared profile. Resolved in one place, so
    the scheduler and the screen can never disagree about which numbers are live."""

    PROFILES = [{'id': 'p1', 'name': 'GFS', 'keep_last': 2, 'keep_daily': 0, 'keep_weekly': 0,
                 'keep_monthly': 0, 'keep_yearly': 0, 'max_size': 0}]

    @staticmethod
    def _rows(n):
        base = dt.datetime(2026, 8, 11, 3, 0)
        return [{'name': sched.auto_name(base - dt.timedelta(days=i), 'x'),
                 'mtime': (base - dt.timedelta(days=i)).timestamp(),
                 'size': 10, 'status': 'ok'} for i in range(n)]

    def test_a_task_with_no_profile_is_left_exactly_as_written(self):
        task = {'name': 'x', 'keep_last': 9}
        assert sched.with_profile(task, self.PROFILES) == task

    def test_the_profile_replaces_the_policy_it_does_not_merge_with_it(self):
        """A profile that says nothing about monthlies means none — otherwise a task keeps
        history the policy it follows never mentions, and nothing on screen says why."""
        task = {'name': 'x', 'profile': 'p1', 'keep_last': 5, 'keep_monthly': 12}
        got = sched.with_profile(task, self.PROFILES)
        assert got['keep_last'] == 2 and got['keep_monthly'] == 0

    def test_the_legacy_counter_does_not_leak_past_a_profile(self):
        """`keep` is read when no bucket is set; a task following a profile HAS stated its
        buckets, so an old counter left on the row must not come back to life."""
        task = {'name': 'x', 'profile': 'p1', 'keep': 30}
        assert sched.retention_policy(sched.with_profile(task, self.PROFILES)) \
            == {'keep_last': 2}

    def test_a_profile_that_is_gone_leaves_the_tasks_own_numbers_standing(self):
        """Not "no rules", which reads as keep-everything and fills a disk. The task's own
        policy was never overwritten, so it is still the last thing that task actually said."""
        task = {'name': 'x', 'profile': 'deleted', 'keep_last': 4}
        assert sched.retention_policy(sched.with_profile(task, [])) == {'keep_last': 4}

    def test_pruning_obeys_the_profile_and_not_the_boxes_underneath(self):
        rows = self._rows(6)
        task = {'name': 'x', 'profile': 'p1', 'keep_last': 6}
        assert sched.prune(rows, task, 'x') == [], 'unresolved, the task keeps its own six'
        gone = sched.prune(rows, sched.with_profile(task, self.PROFILES), 'x')
        assert len(gone) == 4, gone


class TestCuandoLeTocaLaProximaVez:
    """`next_due_at` — la cifra que la pantalla de Temporizadores tiene que enseñar.

    Nació de un fallo reportado desde la pantalla: «Copias programadas» salía en ámbar con
    «Atrasado 41 min» mientras la pantalla de al lado enseñaba tres copias recién hechas. La
    lista calculaba «última vuelta + cada cuánto», y para este temporizador esas dos cifras
    miden cosas distintas: el hilo despierta cada diez minutos, pero toma el arriendo **sólo
    cuando hay trabajo**, así que su marca es la última copia. Sumarle el tic da un instante sin
    significado, y con una programación horaria o diaria queda siempre en el pasado.
    """

    def test_una_horaria_que_copio_hace_un_rato_no_esta_atrasada(self):
        """El caso exacto de la captura: copia horaria, la última hace 51 minutos."""
        ahora = 1_700_000_000.0
        t = {'name': 'cada-hora', 'mode': 'interval', 'every_hours': 1}
        falta = sched.next_due_at(t, ahora, ahora - 51 * 60) - ahora
        assert 8 * 60 < falta <= 9 * 60, falta
        assert sched.task_is_due(t, ahora, ahora - 51 * 60) is False

    def test_a_la_que_ya_le_tocaba_le_toca_ahora(self):
        """«Ahora» y no un pasado inventado: le toca, y eso es lo que hay que decir."""
        ahora = 1_700_000_000.0
        t = {'mode': 'interval', 'every_hours': 1}
        assert sched.next_due_at(t, ahora, ahora - 7200) == ahora

    def test_una_diaria_copiada_hoy_apunta_a_manana(self):
        hoy = dt.datetime(2026, 9, 13, 12, 0, 0)
        tarea = {'mode': 'calendar', 'days': [], 'at': '00:13'}
        ya = hoy.replace(hour=0, minute=13, second=0, microsecond=0).timestamp()
        prox = dt.datetime.fromtimestamp(sched.next_due_at(tarea, hoy.timestamp(), ya))
        assert (prox.day, prox.hour, prox.minute) == (14, 0, 13)

    def test_una_semanal_salta_al_proximo_dia_marcado(self):
        """Lunes y jueves: un lunes por la tarde, la siguiente es el jueves."""
        lunes = dt.datetime(2026, 9, 14, 18, 0, 0)      # 14/09/2026 es lunes
        assert lunes.weekday() == 0
        tarea = {'mode': 'calendar', 'days': [0, 3], 'at': '03:00'}
        ya = lunes.replace(hour=3, minute=0, second=0, microsecond=0).timestamp()
        prox = dt.datetime.fromtimestamp(sched.next_due_at(tarea, lunes.timestamp(), ya))
        assert prox.weekday() == 3 and prox.day == 17

    def test_una_apagada_no_tiene_proxima(self):
        """Cero horas es APAGADA, no «cada cero»: devolver un instante la pintaría corriendo."""
        ahora = 1_700_000_000.0
        assert sched.next_due_at({'every_hours': 0}, ahora, ahora - 60) == 0.0
        assert sched.next_due_at({'every_hours': 'dos'}, ahora, ahora - 60) == 0.0

    def test_y_una_que_no_ha_copiado_nunca_le_toca_ya(self):
        """La instalación que nunca ha copiado es la que más lo necesita — la misma regla que
        sigue `is_due`, y aquí tiene que dar la misma respuesta o las dos discreparían."""
        ahora = 1_700_000_000.0
        t = {'mode': 'interval', 'every_hours': 24}
        assert sched.task_is_due(t, ahora, None) is True
        assert sched.next_due_at(t, ahora, None) == ahora


class TestCadaCuantoLeToca:
    """`due_span` — el periodo de la tarea, que es el que la barra de avance necesita.

    La otra mitad del fallo de la pantalla: la fila enseñaba «cada 10 min» —el tic del hilo—
    junto a un «siguiente» sacado de la programación, y la barra, dibujada sobre esos diez
    minutos mientras faltaba una hora, se llenaba y se quedaba llena.
    """

    def test_por_intervalo_es_el_intervalo(self):
        assert sched.due_span({'mode': 'interval', 'every_hours': 1}, 1_700_000_000.0) == 3600
        assert sched.due_span({'every_hours': 6}, 1_700_000_000.0) == 21600

    def test_una_diaria_por_calendario_es_un_dia(self):
        mie = dt.datetime(2026, 9, 16, 12, 0, 0)
        assert sched.due_span({'mode': 'calendar', 'days': [], 'at': '03:00'},
                              mie.timestamp()) == 86400

    def test_pero_una_semanal_no_lo_es_y_no_es_un_promedio(self):
        """Lunes y jueves: desde el lunes hay tres días hasta el jueves, y desde el jueves
        cuatro hasta el lunes. La verdad de ese calendario son las dos, según dónde se mire —
        y un promedio de tres y medio sería una cifra que no ocurre nunca."""
        martes = dt.datetime(2026, 9, 15, 12, 0, 0)     # entre el lunes y el jueves
        assert martes.weekday() == 1
        assert sched.due_span({'mode': 'calendar', 'days': [0, 3], 'at': '03:00'},
                              martes.timestamp()) == 3 * 86400
        viernes = dt.datetime(2026, 9, 18, 12, 0, 0)    # entre el jueves y el lunes
        assert sched.due_span({'mode': 'calendar', 'days': [0, 3], 'at': '03:00'},
                              viernes.timestamp()) == 4 * 86400

    def test_y_una_apagada_no_tiene_periodo(self):
        """Cero y no un valor por defecto: la fila cae entonces al tic, que es lo único cierto
        de un temporizador cuyo trabajo está apagado."""
        assert sched.due_span({'every_hours': 0}, 1_700_000_000.0) == 0.0
        assert sched.due_span({'every_hours': 'dos'}, 1_700_000_000.0) == 0.0
