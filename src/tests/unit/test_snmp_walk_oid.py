#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Walking ONE column, which is what a profile metric asks for.

The discovery walk sweeps two fixed subtrees, truncates values to 120 characters and swallows
errors, because what it produces is a list somebody picks from. A sampled metric is a different
question with the same name, and every one of those three choices is wrong for it: it walks the
column the profile named, needs the value whole (a truncated counter is a wrong number, not a
shortened one), and needs to know when the device did not answer — an empty table and an
unreachable device are not the same thing, and they look identical without it.

What is being pinned here is mostly the ARITHMETIC OF THE KEY. Rows are filed under the OID
suffix after the walked root, and getting that wrong does not raise: it produces a table whose
rows are keyed by something that is not the index, which the sampler then pairs against names
walked from another column — and the traffic of port 3 quietly becomes the traffic of port 4.
"""

import pytest

from lib.core.snmp import client as snmp_client
from lib.core.snmp.client import SnmpClient

pytestmark = pytest.mark.skipif(not snmp_client._HAS_PYSNMP, reason='pysnmp is not installed')


# ── A device on the other end of the socket ──────────────────────────────────

class _Val:
    def __init__(self, text):
        self._t = text

    def prettyPrint(self):        # noqa: N802 — pysnmp's own spelling
        return self._t


class _Err:
    def __init__(self, text):
        self._t = text

    def prettyPrint(self):        # noqa: N802 — pysnmp's own spelling
        return self._t

    def __str__(self):
        return self._t


class _Cmd:
    """The async iterator pysnmp's walk commands return."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _rows(pairs):
    """One PDU carrying every (oid, value) pair — no error."""
    return [(None, 0, 0, [(oid, _Val(val)) for oid, val in pairs])]


@pytest.fixture
def device(monkeypatch):
    """Stand in for everything pysnmp does with a socket, and hand back scripted PDUs."""
    class _Any:
        def __init__(self, *a, **kw):
            pass

        def close_dispatcher(self):
            pass

    class _Transport:
        @staticmethod
        async def create(*_a, **_kw):
            return _Any()

    box = {}

    def _cmd(*_a, **_kw):
        return _Cmd(box['chunks'])

    monkeypatch.setattr(snmp_client, 'UdpTransportTarget', _Transport)
    monkeypatch.setattr(snmp_client, 'SnmpEngine', _Any)
    monkeypatch.setattr(snmp_client, 'ContextData', _Any)
    monkeypatch.setattr(snmp_client, 'ObjectType', lambda *a, **k: object())
    monkeypatch.setattr(snmp_client, 'ObjectIdentity', lambda *a, **k: object())
    monkeypatch.setattr(snmp_client, 'bulk_walk_cmd', _cmd)
    monkeypatch.setattr(snmp_client, 'walk_cmd', _cmd)

    def _answer(chunks):
        box['chunks'] = chunks

    return _answer


def _walk(oid='1.3.6.1.2.1.2.2.1.10', **kw):
    return SnmpClient._snmp_walk_oid(
        host='10.0.0.1', port=161, version='2c', community='public',
        timeout=1, retries=0, oid=oid, **kw)


class TestTheKeyIsTheIndex:

    def test_a_row_is_keyed_by_what_is_left_after_the_root(self, device):
        device(_rows([('1.3.6.1.2.1.2.2.1.10.1', '100'),
                      ('1.3.6.1.2.1.2.2.1.10.2', '200')]))
        rows, err = _walk()
        assert err is None
        assert rows == {'1': '100', '2': '200'}

    def test_a_multi_part_index_stays_whole(self, device):
        """Plenty of tables are indexed by more than one number (a disk inside a controller,
        an address inside an interface). Keeping only the first part merges rows that are not
        the same row."""
        device(_rows([('1.3.6.1.2.1.2.2.1.10.4.1.2', '7')]))
        rows, _err = _walk()
        assert rows == {'4.1.2': '7'}

    def test_a_scalar_walked_as_a_table_is_one_row(self, device):
        """A profile may walk something that turns out to be a single value; that is a table
        of one, not a value with no index."""
        device(_rows([('1.3.6.1.2.1.2.2.1.10', '5')]))
        rows, _err = _walk()
        assert rows == {'0': '5'}

    def test_the_walk_stops_when_it_leaves_the_subtree(self, device):
        """Everything past the column belongs to a different metric. Keeping it would file
        another table's values under indices of this one."""
        device(_rows([('1.3.6.1.2.1.2.2.1.10.1', '100'),
                      ('1.3.6.1.2.1.2.2.1.11.1', '999')]))
        rows, err = _walk()
        assert rows == {'1': '100'} and err is None


class TestTheValueArrivesWhole:

    def test_a_long_value_is_not_truncated(self, device):
        """Discovery shortens values because it shows them in a list. A counter shortened is
        a different number, and nothing downstream could tell."""
        big = '1' * 400
        device(_rows([('1.3.6.1.2.1.2.2.1.10.1', big)]))
        rows, _err = _walk()
        assert rows['1'] == big


class TestSayingWhatWentWrong:

    def test_a_device_that_does_not_answer_reports_it(self, device):
        """An empty table and an unreachable device look identical to the caller otherwise —
        and one of them means "assign a different profile" while the other means "check the
        cable"."""
        device([('No SNMP response received before timeout', 0, 0, [])])
        rows, err = _walk()
        assert rows == {} and 'timeout' in err

    def test_an_error_status_names_the_index_it_happened_at(self, device):
        device([(None, _Err('noSuchName'), 1, [])])
        rows, err = _walk()
        assert rows == {} and 'noSuchName' in err

    def test_rows_read_before_an_error_are_kept(self, device):
        """Half a table is worth charting; throwing it away turns a partial answer into an
        outage."""
        device(_rows([('1.3.6.1.2.1.2.2.1.10.1', '100')])
               + [(None, _Err('genErr'), 1, [])])
        rows, err = _walk()
        assert rows == {'1': '100'} and err

    def test_asking_for_nothing_is_refused_rather_than_walking_everything(self, device):
        """An empty root would walk the device's whole tree — thousands of PDUs on a cycle
        that has to finish before the next one starts."""
        device(_rows([]))
        rows, err = _walk(oid='')
        assert rows == {} and err


class TestABoundedTable:

    def test_a_table_stops_at_the_ceiling(self, device):
        """A chassis switch answers thousands of rows on one column, and the walk that
        fetches them has to finish before the next cycle starts."""
        device(_rows([(f'1.3.6.1.2.1.2.2.1.10.{i}', str(i)) for i in range(1, 40)]))
        rows, err = _walk(max_rows=10)
        assert len(rows) == 10 and err is None

    def test_the_default_ceiling_is_generous_for_real_hardware(self):
        """A 48-port switch, a NAS with 24 disks and a router with a few hundred sub-interfaces
        all have to fit, or the cap is a silent data loss rather than a guard."""
        assert SnmpClient.WALK_MAX_ROWS >= 512
