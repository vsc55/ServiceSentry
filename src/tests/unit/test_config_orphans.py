#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - readings stored under a key nothing owns any more.
#
"""The sweep that finds them, and the care it has to take.

Reported from the screen: a NAS whose module item had been removed showed zero on every tab
while eighteen thousand of its samples were still in the table. A reading is filed under the
key of whatever produced it, and removing that leaves the rows behind under a key nothing can
resolve — not deleted, not reachable, and counted by nothing.

Every test here is about the same risk from one side or the other: this decides what gets
DELETED, so a key it mistakes for an orphan is a week of somebody's history gone. The controls
that matter are the negative ones — what it must leave alone.

No Flask, no database: the question is arithmetic on two lists, which is exactly why it was
written to take them as arguments.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.config import orphans                    # noqa: E402

ITEMS = {'snmp': {'item-a', 'item-b'}, 'ping': {'192.168.1.1'}, 'cpu': {'cpu-1'}}
HOSTS = {'host-1', 'host-2'}
MODS = {'snmp', 'ping', 'cpu'}


def _rows(*pairs):
    return [{'module': m, 'key': k, 'count': n} for m, k, n in pairs]


def _keys(found):
    return {(r['module'], r['key']) for r in found}


class TestWhatItLeavesAlone:
    """The half that matters: this deletes, so a false positive is data loss."""

    def test_a_series_of_a_live_item(self):
        rows = _rows(('snmp', 'item-a', 5), ('cpu', 'cpu-1', 2))
        assert orphans.scan(rows, ITEMS, HOSTS, modules=MODS) == []

    def test_the_rows_of_a_table_that_item_samples(self):
        """One SNMP item files a result per interface: `<item>/<row>`. Reading the key whole
        and finding no item by that name would condemn every row of every device."""
        rows = _rows(('snmp', 'item-a/eth0', 9), ('snmp', 'item-a/eth1', 9))
        assert orphans.scan(rows, ITEMS, HOSTS, modules=MODS) == []

    def test_a_derived_key(self):
        """`<item>_<suffix>` — ram_swap's `<uid>_ram`."""
        rows = _rows(('cpu', 'cpu-1_load', 3))
        assert orphans.scan(rows, ITEMS, HOSTS, modules=MODS) == []

    def test_a_device_read_from_its_own_record(self):
        """A switch with no module item at all files under `host.<uid>`; that is not an
        orphan, it is the normal shape for equipment read over SNMP alone."""
        rows = _rows(('snmp', 'host.host-1/gi1', 4), ('snmp', 'host.host-2', 1))
        assert orphans.scan(rows, ITEMS, HOSTS, modules=MODS) == []

    def test_an_item_keyed_by_its_own_name(self):
        """A classic inline check is keyed by what it watches, not by a uid. Treating "looks
        like a uid" as the test would have swept every one of them."""
        rows = _rows(('ping', '192.168.1.1', 7))
        assert orphans.scan(rows, ITEMS, HOSTS, modules=MODS) == []

    def test_a_module_the_configuration_no_longer_mentions(self):
        """Absent means "not added" — which is also what a module whose folder was moved
        looks like. Deleting its history because it is not installed today would be the sweep
        doing the very thing it exists to prevent."""
        rows = _rows(('gone', 'whatever', 40))
        assert orphans.scan(rows, ITEMS, HOSTS, modules=MODS) == []
        # …unless the caller says to sweep regardless.
        assert len(orphans.scan(rows, ITEMS, HOSTS, modules=None)) == 1

    def test_a_row_with_nothing_to_go_on(self):
        rows = [{'module': '', 'key': 'x'}, {'module': 'snmp', 'key': ''}, {}, None]
        assert orphans.scan(rows, ITEMS, HOSTS, modules=MODS) == []


class TestWhatItFinds:

    def test_a_deleted_items_series(self):
        rows = _rows(('snmp', 'item-gone/eth0', 12))
        found = orphans.scan(rows, ITEMS, HOSTS, modules=MODS)
        assert _keys(found) == {('snmp', 'item-gone/eth0')}
        assert found[0]['reason'] == 'item'

    def test_a_deleted_hosts_series(self):
        rows = _rows(('snmp', 'host.host-gone/gi1', 3))
        found = orphans.scan(rows, ITEMS, HOSTS, modules=MODS)
        assert _keys(found) == {('snmp', 'host.host-gone/gi1')}
        assert found[0]['reason'] == 'host'

    def test_the_module_is_read_as_the_results_record_it(self):
        """A result says `snmp`; the configuration may hold it as `watchfuls.snmp`."""
        rows = _rows(('watchfuls.snmp', 'item-a', 1))
        assert orphans.scan(rows, ITEMS, HOSTS, modules=MODS) == []

    def test_a_name_that_merely_contains_a_live_key_is_not_owned_by_it(self):
        """Substring matching would have spared an orphan for looking like a survivor."""
        rows = _rows(('snmp', 'item-abc', 1))
        assert _keys(orphans.scan(rows, ITEMS, HOSTS, modules=MODS)) == {('snmp', 'item-abc')}

    def test_only_the_first_separator_counts(self):
        """A row name may contain `/` or `_`. Cutting at the LAST one would credit a reading
        to an owner that never existed — and, worse, to one that happens to exist."""
        assert orphans.owner_of('item-a/eth0/sub') == ('item', 'item-a/eth0/sub')
        assert orphans.owner_of('host.host-1/a/b') == ('host', 'host-1')
        rows = _rows(('snmp', 'item-a/eth0/sub', 1))
        assert orphans.scan(rows, ITEMS, HOSTS, modules=MODS) == []


class TestWhatItReports:

    def test_the_totals_are_series_and_rows(self):
        rows = _rows(('snmp', 'a/1', 10), ('snmp', 'a/2', 5), ('m365', 'b', 2))
        found = orphans.scan(rows, {}, set(), modules={'snmp', 'm365'})
        s = orphans.summary(found)
        assert s['series'] == 3 and s['count'] == 17

    def test_and_broken_down_by_module(self):
        rows = _rows(('snmp', 'a', 10), ('snmp', 'b', 5), ('m365', 'c', 2))
        s = orphans.summary(orphans.scan(rows, {}, set(), modules={'snmp', 'm365'}))
        assert s['modules'] == [{'module': 'm365', 'series': 1, 'count': 2},
                                {'module': 'snmp', 'series': 2, 'count': 15}]

    def test_nothing_found_is_a_zero_and_not_an_absence(self):
        s = orphans.summary([])
        assert s == {'series': 0, 'count': 0, 'modules': []}


class TestTheSweepIsOfferedAndNotTaken:
    """"The item is gone" and "the data is worthless" are different statements, and the second
    is the operator's. So nothing here deletes, and the route that does finds them again
    itself rather than trusting the list a browser was shown."""

    def _routes(self):
        from tests.helpers import _read                 # noqa: PLC0415
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        return _read(os.path.join(root, 'lib', 'core', 'config', 'routes.py'))

    def test_the_finder_deletes_nothing(self):
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        with open(os.path.join(root, 'lib', 'core', 'config', 'orphans.py'),
                  encoding='utf-8') as fh:
            src = fh.read()
        for word in ('DELETE', 'delete_series', 'execute('):
            assert word not in src, f'the finder writes ({word})'

    def test_the_purge_scans_again_rather_than_trusting_the_screen(self):
        """The list was true when it was drawn. A cycle since may have recorded a reading
        under a key it now owns, and deleting what a screen remembers is how a sweep removes
        something that stopped being an orphan while somebody read the dialog."""
        src = self._routes()
        body = src.split('def api_db_orphans_purge(')[1].split(chr(10) + '    @app.route')[0]
        assert 'orphans.scan(' in body, 'it deletes a list it was handed'
        assert 'request.get_json' not in body and 'request.args' not in body

    def test_it_is_behind_the_maintenance_permission(self):
        src = self._routes()
        block = src.split("@app.route('/api/v1/config/db/orphans'")[1]
        assert "_perm_required('db_maintenance')" in block

    def test_and_it_is_audited(self):
        src = self._routes()
        assert "wa._audit('db_orphans_purged'" in src
        from lib.core.config.manifest import AUDIT_EVENTS      # noqa: PLC0415
        ev = next(e for e in AUDIT_EVENTS if e['key'] == 'db_orphans_purged')
        assert ev['severity'] != 'muted', (
            'the one action here that removes readings is logged as quietly as the two that '
            'do not')
