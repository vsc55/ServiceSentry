#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How much of a module's audit detail one entry may hold.

A module's ``audit_detail`` hook decides WHAT is worth recording — the SNMP MIB import names
every file it fetched and every one it could not, with the reason. How much of that fits in a
single entry is not the module's call: the detail is stored as JSON in one row and painted
whole when the entry is opened, and what a module lists is bounded by nothing. A large MIB
repository has hundreds of files.

So the ceiling lives in one place, on the route that writes the entry, and honours the setting
that already exists for it (``web_admin|audit_detail_max_items``). Left to each module they
would each pick a different number, and the setting would mean nothing.

Flask-free on purpose: the shaping is plain data in / plain data out, and a guard here would
skip the tests in exactly the install (a slimmed service container) where nothing else covers
this code.
"""

from lib.core.modules.actions import cap_audit_lists


class TestItBoundsWhatAModuleWrote:

    def test_a_short_list_is_left_alone(self):
        d = cap_audit_lists({'name': 'x', 'imported_names': ['a', 'b']}, 100)
        assert d['imported_names'] == ['a', 'b']
        assert 'imported_names_truncated' not in d

    def test_a_long_list_is_cut_and_says_so(self):
        """A list silently cut at N reads as a complete list of N, which is worse than no
        list at all: it answers "which ones?" wrongly instead of not answering."""
        d = cap_audit_lists({'imported_names': [str(i) for i in range(250)]}, 100)
        assert len(d['imported_names']) == 100
        assert d['imported_names_truncated'] == 150

    def test_every_list_is_bounded_not_a_named_few(self):
        """The rule is about lists, not about the keys this or that module happens to use —
        a module added tomorrow gets the ceiling without editing anything here."""
        d = cap_audit_lists({'anything_at_all': [1, 2, 3], 'other': [1, 2, 3]}, 2)
        assert d['anything_at_all'] == [1, 2] and d['anything_at_all_truncated'] == 1
        assert d['other'] == [1, 2] and d['other_truncated'] == 1

    def test_what_is_not_a_list_is_untouched(self):
        """The counts and the summary line are what say the action ran at all."""
        d = cap_audit_lists({'name': 'GitHub import: 81 ok', 'imported': 81, 'ok': True}, 1)
        assert d == {'name': 'GitHub import: 81 ok', 'imported': 81, 'ok': True}

    def test_zero_is_no_ceiling_and_not_no_list(self):
        """It meant the opposite until this panel settled on one reading of 0. This was the
        last ceiling that disagreed: `audit_max_entries`, the syslog retention and the backup
        buckets all take 0 as "no limit", so somebody zeroing every cap to keep everything
        lost exactly the names that make an entry worth opening. Small entries are a small
        NUMBER now."""
        d = cap_audit_lists({'name': 'x', 'failed': 3, 'failed_names': ['a', 'b', 'c']}, 0)
        assert d == {'name': 'x', 'failed': 3, 'failed_names': ['a', 'b', 'c']}

    def test_a_nonsense_ceiling_does_not_lose_the_entry(self):
        """Config arrives as text and can be anything. Dropping the detail because the
        setting is malformed would lose the record over a preference."""
        for bad in (None, 'abc', object()):
            d = cap_audit_lists({'name': 'x', 'names': ['a', 'b']}, bad)
            assert d['names'] == ['a', 'b'], f'the entry lost its lists for max_items={bad!r}'

    def test_the_callers_dict_is_not_modified(self):
        src = {'names': ['a', 'b', 'c']}
        cap_audit_lists(src, 1)
        assert src == {'names': ['a', 'b', 'c']}
