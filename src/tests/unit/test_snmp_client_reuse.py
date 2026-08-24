#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - the SNMP engine is built once, not once per question.
#
"""What an ``SnmpEngine`` costs, and why there is only one of them.

Reported from the screen: an SNMP collection takes for ever, and the panel goes slow while it
runs. Neither was the network. Rebuilt per request — which is what the client did — an engine
costs about a SECOND, measured on loopback against a local agent answering instantly:

* pysnmp recompiles thirteen MIB modules from their Python source. `runpy.run_path` compiles
  the file each time, so the `.pyc` beside it is never the thing that gets used;
* the first OID resolved calls `add_mib_compiler`, which builds a full LALR parser for the SMI
  grammar — an ASN.1 compiler, constructed to look up an OID already held in numbers.

Both are costs of BEING an engine, not of asking it anything, and both are paid once per
engine. A device carrying the whole shipped catalogue is 348 reads: 365 seconds became 6.

Nothing about that is visible from the outside — the readings were right, there was no error
and no warning, and the only symptom was a wait — which is why the guards here are about the
COUNT of engines rather than about any answer.

The tests import no Flask, directly or transitively (`lib.core.snmp.client` is the pysnmp
guard, the protocol tables and two primitives), so there is no `_HAS_FLASK` guard; pysnmp
itself is optional and gated per class where the names it defines are needed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.snmp import client as _client        # noqa: E402

_needs_pysnmp = pytest.mark.skipif(not _client._HAS_PYSNMP, reason='pysnmp not installed')

CONN = {'host': '10.0.0.9', 'port': 161, 'version': '2c', 'community': 'public',
        'timeout': 2, 'retries': 1}


@pytest.fixture(autouse=True)
def _clean():
    """Nothing kept between tests. These all count what the module cached."""
    _client._reset()
    yield
    _client._reset()


class _Counted:
    """Stands in for pysnmp, counting what the client asked to be built."""

    def __init__(self):
        self.engines = 0
        self.targets = []
        self.asked = []

    def engine(self):
        self.engines += 1
        return f'engine-{self.engines}'

    def transport(self):
        counted = self

        class _T:
            @staticmethod
            async def create(address, timeout=0, retries=0):
                counted.targets.append((address, timeout, retries))
                return f'target-{len(counted.targets)}'
        return _T

    def get_cmd(self):
        counted = self

        async def _get(engine, auth, transport, _ctx, *var_binds):
            counted.asked.append((engine, transport, len(var_binds)))
            return None, 0, 0, [('1.3.6.1.2.1.1.1.0', '42')]
        return _get


@pytest.fixture
def fake(monkeypatch):
    counted = _Counted()
    monkeypatch.setattr(_client, 'SnmpEngine', counted.engine)
    monkeypatch.setattr(_client, 'UdpTransportTarget', counted.transport())
    monkeypatch.setattr(_client, 'get_cmd', counted.get_cmd())
    return counted


@_needs_pysnmp
class TestTheEngineIsBuiltOnce:
    """The whole fix, and the only thing separating six seconds from six minutes."""

    def test_ten_reads_build_one_engine(self, fake):
        for i in range(10):
            got, err = _client.SnmpClient._snmp_get(oid=f'1.3.6.1.2.1.1.{i + 1}.0', **CONN)
            assert (got, err) == ('42', None)
        assert len(fake.asked) == 10, 'the device was not actually asked ten times'
        assert fake.engines == 1, (
            f'{fake.engines} engines for ten reads — each one recompiles the MIBs')

    def test_and_resolves_the_address_once(self, fake):
        for i in range(10):
            _client.SnmpClient._snmp_get(oid=f'1.3.6.1.2.1.1.{i + 1}.0', **CONN)
        assert len(fake.targets) == 1, 'one DNS lookup per metric'

    def test_a_second_device_shares_the_engine_and_not_the_address(self, fake):
        _client.SnmpClient._snmp_get(oid='1.3.6.1.2.1.1.1.0', **CONN)
        _client.SnmpClient._snmp_get(oid='1.3.6.1.2.1.1.1.0', **{**CONN, 'host': '10.0.0.8'})
        assert fake.engines == 1
        assert [t[0] for t in fake.targets] == [('10.0.0.9', 161), ('10.0.0.8', 161)]
        assert len({a[1] for a in fake.asked}) == 2, 'both devices were asked on one transport'

    def test_a_different_timeout_is_a_different_transport(self, fake):
        """It is baked into the target, so sharing one would silently apply the other
        device's patience to this one."""
        _client.SnmpClient._snmp_get(oid='1.3.6.1.2.1.1.1.0', **CONN)
        _client.SnmpClient._snmp_get(oid='1.3.6.1.2.1.1.1.0', **{**CONN, 'timeout': 9})
        assert [t[1] for t in fake.targets] == [2, 9]

    def test_the_walk_shares_it_with_the_get(self, fake, monkeypatch):
        async def _bulk(engine, auth, transport, _ctx, _nr, _mr, *_vb, **_kw):
            root = '1.3.6.1.2.1.2.2.1.2'
            for i in (1, 2):
                yield None, 0, 0, [(f'{root}.{i}', _Pretty(f'v{i}'))]
        monkeypatch.setattr(_client, 'bulk_walk_cmd', _bulk)
        _client.SnmpClient._snmp_get(oid='1.3.6.1.2.1.1.1.0', **CONN)
        rows, err = _client.SnmpClient._snmp_walk_oid(oid='1.3.6.1.2.1.2.2.1.2', **CONN)
        assert (rows, err) == ({'1': 'v1', '2': 'v2'}, None)
        assert fake.engines == 1 and len(fake.targets) == 1


class _Pretty:
    def __init__(self, text):
        self._text = text

    def prettyPrint(self):        # noqa: N802  (pysnmp's own spelling)
        return self._text


@_needs_pysnmp
class TestTheEngineIsNotThrownAway:
    """`close_dispatcher` was in a `finally` on both primitives. On a shared engine that is
    not cleanup — it is closing the socket the NEXT read needs, and the reads after it fail
    with something that reads like the device."""

    def test_no_request_path_closes_the_dispatcher(self):
        src = _read_client()
        for name in ('_snmp_get', '_snmp_walk_oid', '_snmp_walk'):
            body = src.split(f'def {name}(')[1].split('\n    @')[0]
            assert 'close_dispatcher' not in body, (
                f'{name} still closes the engine it now shares')

    def test_only_the_reset_closes_it(self):
        src = _read_client()
        assert src.count('close_dispatcher') == 1
        assert 'close_dispatcher' in src.split('def _reset(')[1].split('\nasync def')[0]

    def test_nothing_builds_an_engine_of_its_own_any_more(self):
        """The cost is the constructor, so one left behind anywhere is the whole bug back for
        whatever path still calls it."""
        src = _read_client()
        assert src.count('SnmpEngine()') == 1, 'an engine is still built outside _engine()'
        assert 'SnmpEngine()' in src.split('async def _engine(')[1].split('\n\n\nasync')[0]


@_needs_pysnmp
class TestTheCredentialIsTheSameObject:
    """pysnmp's local configuration datastore keys on the object. A fresh one per request is
    a fresh row per request: the engine grows for the life of the process, and every read
    pays to configure what the read before it configured."""

    def test_the_same_credential_gives_the_identical_object(self):
        a = _client.SnmpClient._auth_cached('2c', 'public')
        assert _client.SnmpClient._auth_cached('2c', 'public') is a

    def test_a_different_community_does_not(self):
        a = _client.SnmpClient._auth_cached('2c', 'public')
        assert _client.SnmpClient._auth_cached('2c', 'private') is not a

    def test_nor_a_different_version(self):
        a = _client.SnmpClient._auth_cached('2c', 'public')
        assert _client.SnmpClient._auth_cached('1', 'public') is not a

    def test_nor_a_v3_key_or_protocol(self):
        """Every part of it, or a rotated key would go on being the old key."""
        base = ('3', '', 'sam', 'authkey', 'privkey', 'SHA', 'AES-128')
        a = _client.SnmpClient._auth_cached(*base)
        assert _client.SnmpClient._auth_cached(*base) is a
        for i, other in ((2, 'max'), (3, 'other'), (4, 'other'), (5, 'MD5'), (6, 'DES')):
            changed = list(base)
            changed[i] = other
            assert _client.SnmpClient._auth_cached(*changed) is not a, base[i]


class TestTheLoopIsOursAndStaysUp:
    """The engine cannot outlive the loop its socket was opened on, so keeping one means
    keeping the other."""

    def test_the_same_loop_every_time(self):
        assert _client._snmp_loop() is _client._snmp_loop()

    def test_a_loop_whose_thread_has_gone_is_replaced(self):
        """Otherwise every caller waits on it for ever — a hang with nothing to read."""
        first = _client._snmp_loop()
        _client._LOOP_THREAD.join(0)
        _client._LOOP_THREAD = threading.Thread(target=lambda: None)   # already finished
        _client._LOOP_THREAD.start()
        _client._LOOP_THREAD.join()
        assert _client._snmp_loop() is not first
        assert _client.run_coroutine(_answer()) == 42

    def test_it_answers_from_a_thread_with_no_loop(self):
        assert _client.run_coroutine(_answer()) == 42

    def test_it_answers_from_a_thread_that_has_one(self):
        """`asyncio.run` REFUSES here, and this is called from whatever thread the panel is
        serving on. Reported as discovery finding nothing at all: the refusal was caught by a
        `try/except: continue`, so every server was skipped and the empty list read as a
        device with no OIDs."""
        assert _in_a_loop(lambda: _client.run_coroutine(_answer())) == 42

    def test_an_exception_still_reaches_the_caller(self):
        with pytest.raises(ValueError, match='boom'):
            _client.run_coroutine(_boom())

    def test_one_wedged_request_does_not_stop_the_others(self):
        """They share a loop now. If a slow device held it, one unreachable machine would
        stop every other machine's collection."""
        started = threading.Event()

        async def _slow():
            started.set()
            await asyncio.sleep(30)

        fut = asyncio.run_coroutine_threadsafe(_slow(), _client._snmp_loop())
        assert started.wait(5), 'the loop never picked the slow one up'
        try:
            assert _client.run_coroutine(_answer()) == 42
        finally:
            fut.cancel()


async def _answer():
    return 42


async def _boom():
    raise ValueError('boom')


def _in_a_loop(fn):
    """Run *fn* on a thread that already has a running loop of its own."""
    box: dict = {}

    def _thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(asyncio.to_thread(lambda: box.setdefault('v', fn())))
        finally:
            loop.close()

    run = threading.Thread(target=_thread)
    run.start()
    run.join()
    return box.get('v')


def _read_client() -> str:
    from tests.helpers import _read                 # noqa: PLC0415
    root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
    return _read(os.path.join(root, 'lib', 'core', 'snmp', 'client.py'))
