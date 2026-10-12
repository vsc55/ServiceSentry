#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background-service defects found by the second 2026-10-12 audit (sixth batch).

- The monitor's alerts go out on a daemon thread: ``--monitor -t 0``, a stop and the web
  process's shutdown returned before it had sent them, and they were lost for good.
- An external syslog source whose database was down read as an EMPTY table: the event
  worker moved its cursor to 0 and replayed the whole table when it came back.
- The jail notified a ban under its own lock, which every request and datagram takes.
- An unreadable ``check_state`` read as empty: every DOWN re-alerted.
- The events ``run_now`` ran the tick on the heartbeat's own thread.
- Telegram's 429 was a lost message, and one exception ended a whole batch.
- ``srv1`` collected the parts of ``srv10`` as its recovery; and a module that reports a
  sub-entity only while it fails never announced that it was over.
- A replica that took the events lease used the cooldowns it read at start-up.
- A forged UDP source jailed whatever address it named.
- A rule regex with nested quantifiers froze the process on a syslog line.
- The receive queue had no byte bound, and the message text was not clipped.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest


# ── SVC-1: the alerts queued at exit are sent before the process goes ─────────

class _NotifyHost:
    _CONFIG_FILE = 'x'

    def _read_config_file(self, _f):
        return {'notifications': {'t6svc_on_down': True}}

    def _dbg(self, *_a, **_k):
        pass


@pytest.fixture
def slow_channel(monkeypatch):
    """A channel that takes a while (an HTTP round trip), as the only one registered."""
    from lib.core.notify import registry
    sent = []

    def _flush(_router, _cfg, alerts, _host, _url):
        time.sleep(0.3)
        sent.append(len(alerts))
        return True, 'ok'
    ch = registry.Channel('t6svc', lambda *a, **k: (True, ''), _flush)
    monkeypatch.setattr(registry, 'channels', lambda: {'t6svc': ch})
    return sent


def _queue_one_alert():
    from lib.core.notify.monitor_notifier import MonitorNotifier
    n = MonitorNotifier(_NotifyHost())
    n.add('down', 'm', 'k', 'k is DOWN')
    assert n.flush_later() is True


def _bare_monitor_service(monkeypatch):
    from lib.services.monitoring import service as svc_mod

    class _Svc(svc_mod.MonitorService):
        _monitoring_interval = 300

    svc = _Svc.__new__(_Svc)
    svc._stop = threading.Event()
    svc._dbg = lambda *a, **k: None
    svc._monitoring_thread = None
    monkeypatch.setattr(svc_mod, 'start_control_server', lambda _s: None)
    monkeypatch.setattr(svc_mod.signal, 'signal', lambda *a, **k: None)
    return svc


class TestAlertsDrainedAtExit:

    def test_single_pass_returns_after_its_alerts_went_out(self, monkeypatch, slow_channel):
        svc = _bare_monitor_service(monkeypatch)
        svc._monitoring_run_one_cycle = _queue_one_alert
        assert svc.run(once=True) == 0
        assert slow_channel == [1], 'the -t 0 pass exited with its alert still queued'

    def test_a_stop_waits_for_the_last_cycle_s_alerts(self, monkeypatch, slow_channel):
        svc = _bare_monitor_service(monkeypatch)
        svc._stop.set()
        svc._monitoring_enabled = lambda: False
        svc.start_heartbeat = svc.stop_heartbeat = lambda: None
        svc._watch_loop = lambda: None
        svc._monitoring_stop = _queue_one_alert          # the cycle in flight queues one
        assert svc.run() == 0
        assert slow_channel == [1]

    def test_the_embedded_monitor_drains_on_shutdown(self, slow_channel):
        from lib.services.monitoring.embedded import EmbeddedMonitor
        mon = EmbeddedMonitor.__new__(EmbeddedMonitor)
        mon._monitoring_stop_event = threading.Event()
        mon._monitoring_thread = None
        _queue_one_alert()
        mon.on_shutdown()
        assert mon._monitoring_stop_event.is_set()
        assert slow_channel == [1]

    def test_the_drain_is_bounded(self, monkeypatch):
        from lib.core.notify import monitor_notifier, registry
        gate = threading.Event()

        def _stuck(*_a):
            gate.wait(5)
            return True, ''
        ch = registry.Channel('t6svc', lambda *a, **k: (True, ''), _stuck)
        monkeypatch.setattr(registry, 'channels', lambda: {'t6svc': ch})
        from lib.services.monitoring.embedded import EmbeddedMonitor
        mon = EmbeddedMonitor.__new__(EmbeddedMonitor)
        mon._monitoring_thread = None
        _queue_one_alert()
        try:
            t0 = time.monotonic()
            assert mon._monitoring_drain_alerts(0.3) is False
            assert time.monotonic() - t0 < 2
        finally:
            gate.set()
            monitor_notifier.drain(5)


# ── SVC-2: an unavailable external table is not an empty one ──────────────────

class _DownDB:
    def describe_table(self, _t):
        raise ConnectionError('database unreachable')

    def fetchone(self, *_a, **_k):
        raise AssertionError('no query on a table that could not be confirmed')


class _CursorState:
    def __init__(self):
        self.c = {}

    def cursor(self, k):
        return self.c.get(k)

    def set_cursor(self, k, v):
        self.c[k] = v

    def cooldowns(self):
        return {}


class _ExtStore:
    def __init__(self, n):
        self.rows = [{'id': i, 'message': f'm{i}'} for i in range(1, n + 1)]
        self.down = False

    def max_id(self):
        return None if self.down else self.rows[-1]['id']

    def query_since(self, last, limit=500):
        if self.down:
            return []
        return [r for r in self.rows if r['id'] > last][:limit]


def _events_worker(ext):
    from lib.services.events.manager import _EventsMixin

    class W(_EventsMixin):
        _CONFIG_FILE = 'x'

        def __init__(self):
            self._init_events()
            self._event_state = _CursorState()
            self._syslog_sources = SimpleNamespace(watched=lambda: [('ext1', 'rsyslog', ext)])
            self.evaluated = 0

        def _read_config_file(self, _f):
            return {}

        def _dbg(self, *_a, **_k):
            pass

        def _eval_event(self, source, rec, log_source=''):
            self.evaluated += 1
    return W()


class TestUnavailableSourceKeepsTheCursor:

    def test_a_table_that_cannot_be_described_has_no_max_id(self):
        from lib.services.syslog.store.messages import SyslogStore
        store = SyslogStore(_DownDB(), read_only=True)
        assert store.max_id() is None
        assert store.query_since(0) == []

    def test_a_blip_does_not_replay_the_table(self):
        ext = _ExtStore(3000)
        w = _events_worker(ext)
        w._event_worker_tick()
        assert w._event_state.c == {'syslog:ext1': 3000} and w.evaluated == 0
        ext.down = True
        w._event_worker_tick()
        assert w._event_state.c == {'syslog:ext1': 3000}, 'cursor moved on a dead source'
        ext.down = False
        ext.rows.append({'id': 3001, 'message': 'new'})
        w._event_worker_tick()
        assert w.evaluated == 1, f're-evaluated {w.evaluated} rows after the blip'

    def test_a_first_run_on_a_dead_source_seeds_nothing(self):
        ext = _ExtStore(10)
        ext.down = True
        w = _events_worker(ext)
        w._event_worker_tick()
        assert 'syslog:ext1' not in w._event_state.c


# ── SVC-3: the jail notifies with its lock released ───────────────────────────

def _jail_with_probe():
    from lib.services.ipban.jail import IpBanManager
    seen = []

    def notify(action, _ip, _info):
        res = []

        def probe():
            got = m._lock.acquire(blocking=False)
            if got:
                m._lock.release()
            res.append(got)
        t = threading.Thread(target=probe)
        t.start()
        t.join(2)
        seen.append((action, res[0] if res else None))
    m = IpBanManager(notify=notify)
    m.configure(enabled=True, auth_threshold=1, auth_window=60)
    return m, seen


class TestJailNotifiesOutsideItsLock:

    def test_an_offense_ban(self):
        m, seen = _jail_with_probe()
        assert m.register_offense('203.0.113.9', 'login_failed') is True
        assert seen == [('banned', True)], 'notified while holding the jail lock'

    def test_a_manual_ban_and_its_escalation(self):
        m, seen = _jail_with_probe()
        assert m.ban('203.0.113.10', reason='manual') is not None
        assert m.ban('203.0.113.10', reason='manual') is not None
        assert seen == [('banned', True), ('ban_escalated', True)]

    def test_an_unban(self):
        m, seen = _jail_with_probe()
        m.ban('203.0.113.11')
        seen.clear()
        assert m.unban('203.0.113.11') is True
        assert seen == [('unbanned', True)]


# ── SVC-4: an unreadable check_state is not an empty one ──────────────────────

def _state_store():
    from lib.db import get_connector
    from lib.services.monitoring.check_state import CheckStateStore
    return CheckStateStore(get_connector(None, default_sqlite_path=':memory:'))


def _break_reads(store, monkeypatch):
    def _boom(*_a, **_k):
        raise ConnectionError('database gone')
    monkeypatch.setattr(store._db, 'fetchall', _boom)


class TestUnreadableCheckState:

    def test_get_all_raises_instead_of_returning_nothing(self, monkeypatch):
        store = _state_store()
        store.persist_status({'ping': {'srv': {'status': False, 'fail_count': 3}}})
        _break_reads(store, monkeypatch)
        with pytest.raises(ConnectionError):
            store.get_all()

    def test_the_monitor_keeps_the_state_it_held(self, monkeypatch):
        from lib.services.monitoring.check_state import DbBackedStatus
        store = _state_store()
        store.persist_status({'ping': {'srv': {'status': False, 'fail_count': 3}}})
        status = DbBackedStatus(store)
        status.read()
        before = status.data
        assert before['ping']['srv']['status'] is False
        _break_reads(store, monkeypatch)
        with pytest.raises(ConnectionError):
            status.read()
        assert status.data == before, 'the held state was replaced by an empty one'

    def test_a_save_on_an_unreadable_table_fails_and_keeps_the_rows(self, monkeypatch):
        store = _state_store()
        store.persist_status({'ping': {'srv': {'status': False, 'fail_count': 3}}})
        uid = store.get_all()[('ping', 'srv', '')]['uid']
        real = store._db.fetchall
        _break_reads(store, monkeypatch)
        assert store.persist_module('ping', {'srv': {'status': False}}) is False
        monkeypatch.setattr(store._db, 'fetchall', real)
        assert store.get_all()[('ping', 'srv', '')]['uid'] == uid


# ── SVC-5: the events run-now has a thread of its own ─────────────────────────

class TestEventsRunNowOffTheHeartbeat:

    def _worker(self):
        from lib.services.events.manager import _EventsMixin
        gate, ran = threading.Event(), []

        class W(_EventsMixin):
            def __init__(self):
                self._init_events()

            def _dbg(self, *_a, **_k):
                pass

            def _event_worker_tick_impl(self):
                ran.append(threading.current_thread().name)
                gate.wait(5)
                return 0
        return W(), gate, ran

    def test_it_returns_at_once_and_ticks_elsewhere(self):
        w, gate, ran = self._worker()
        try:
            t0 = time.monotonic()
            assert w._apply_command('run_now', {}) == (True, 'started')
            assert time.monotonic() - t0 < 1, 'run_now blocked the heartbeat thread'
            for _ in range(100):
                if ran:
                    break
                time.sleep(0.01)
            assert ran and ran[0] != threading.current_thread().name
            assert w._apply_command('run_now', {}) == (False, 'busy')
            assert w._event_worker_tick() == 0, 'the worker loop ticked beside it'
        finally:
            gate.set()
        for _ in range(100):
            if w._event_tick_lock.acquire(blocking=False):
                w._event_tick_lock.release()
                break
            time.sleep(0.01)
        else:
            pytest.fail('the run-now thread never released the tick lock')


# ── SVC-6: Telegram's 429 and a failure in the middle of a batch ──────────────

class _Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body or {}

    def json(self):
        return self._body


class TestTelegramRetryAndBatch:

    def test_a_429_is_waited_out_and_resent(self, monkeypatch):
        import lib.providers.telegram as tg
        answers = [_Resp(429, {'parameters': {'retry_after': 2}}), _Resp(200)]
        waits = []
        monkeypatch.setattr(tg.requests, 'post', lambda *a, **k: answers.pop(0))
        monkeypatch.setattr(tg.time, 'sleep', waits.append)
        assert tg.send_telegram('t', 'c', 'hi') == (True, 200, 'sent')
        assert waits == [2]

    def test_the_wait_is_capped_and_the_retries_end(self, monkeypatch):
        import lib.providers.telegram as tg
        waits, calls = [], []

        def post(*_a, **_k):
            calls.append(1)
            return _Resp(429, {'parameters': {'retry_after': 99999}})
        monkeypatch.setattr(tg.requests, 'post', post)
        monkeypatch.setattr(tg.time, 'sleep', waits.append)
        ok, code, _info = tg.send_telegram('t', 'c', 'hi')
        assert (ok, code) == (False, 429)
        assert waits and max(waits) <= tg._RETRY_AFTER_MAX
        assert len(calls) == tg._RETRY_429 + 1

    def test_one_failure_does_not_end_the_batch(self, monkeypatch):
        import requests
        import lib.providers.telegram as provider
        from lib.core.notify.telegram import channel
        sent = []

        def send(_t, _c, text, **_k):
            sent.append(text)
            if len(sent) == 1:
                raise requests.ConnectionError('timed out')
            return True, 200, 'sent'
        monkeypatch.setattr(provider, 'send_telegram', send)
        alerts = [{'kind': 'down', 'module': 'm', 'item': f'i{n}', 'message': f'down {n}'}
                  for n in range(3)]
        cfg = {'telegram': {'token': 't', 'chat_id': 'c', 'group_messages': False}}
        ok, info = channel.flush(None, cfg, alerts, 'host', '')
        assert len(sent) == 4, 'the messages after the failure were never tried'
        assert ok is False and 'timed out' in info


# ── SVC-7 + WF-2: what a pruned failing key's recovery is ─────────────────────

class _RD:
    def __init__(self, data):
        self._d = data

    def keys(self):
        return self._d.keys()

    def get_status(self, k):
        return self._d[k][0]

    def get_message(self, k):
        return self._d[k][1]


def _recovery(key, data):
    from lib.services.monitoring.monitor import Monitor
    sent = []
    fake = SimpleNamespace(_notifier=SimpleNamespace(add=lambda *a: sent.append(a)),
                           _item_label=lambda _m, k: k)
    Monitor._recovered_by_parts(fake, 'mod', key, {'status': False}, _RD(data))
    return sent


class TestRecoveryOfAPrunedKey:

    def test_another_item_s_parts_are_not_this_one_s(self):
        assert _recovery('srv1', {'srv10_ram': (True, 'ok'), 'srv10_swap': (True, 'ok')}) == []

    def test_its_own_parts_still_are(self):
        sent = _recovery('srv1', {'srv1_ram': (True, 'RAM ok'), 'srv1/vip': (True, 'VIP ok')})
        assert len(sent) == 1 and sent[0][0] == 'recovery'

    def test_an_ancestor_reporting_ok_is_the_recovery(self):
        sent = _recovery('tenant/health/exchange', {'tenant': (True, 'All services healthy')})
        assert len(sent) == 1
        kind, module, label, text = sent[0]
        assert (kind, module, label) == ('recovery', 'mod', 'tenant/health/exchange')
        assert 'healthy' in text

    def test_a_failing_ancestor_is_not(self):
        assert _recovery('tenant/resources/vm1', {'tenant': (False, 'tenant unreachable')}) == []

    def test_a_sibling_prefix_is_not_an_ancestor(self):
        assert _recovery('tenant10/health/x', {'tenant1': (True, 'ok')}) == []


# ── SVC-8: a new leader reads the cooldowns the old one wrote ─────────────────

class TestCooldownsReloadedOnLeadership:

    def test_a_replica_taking_the_lease_honours_the_persisted_cooldown(self):
        from lib.services.events.manager import _EventsMixin
        now = time.time()
        rule = {'id': 'r1', 'name': 'r1', 'enabled': True, 'source': 'syslog',
                'cooldown': 600, 'match_groups': []}

        class State(_CursorState):
            def __init__(self):
                super().__init__()
                self.persisted = {}

            def cooldowns(self):
                return dict(self.persisted)

            def set_cooldown(self, uid, ts):
                self.persisted[uid] = ts

        class Rows:
            def __init__(self):
                self.rows = [{'id': 1, 'message': 'x', 'severity': 3}]

            def max_id(self):
                return self.rows[-1]['id']

            def query_since(self, last, limit=500):
                return [r for r in self.rows if r['id'] > last][:limit]

        class W(_EventsMixin):
            _CONFIG_FILE = 'x'

            def __init__(self):
                self._init_events()
                self._event_state = State()
                self._syslog_store = Rows()
                self._event_rules_cache = [rule]
                self.leader = False
                self.fired = []

            def _work_allowed(self):
                return self.leader

            def _read_config_file(self, _f):
                return {}

            def _dbg(self, *_a, **_k):
                pass

            def _dispatch_event(self, source, r, ctx):
                self.fired.append(ctx['id'])

        w = W()                                  # started as a standby: cache empty
        w._event_worker_tick()
        w._event_state.persisted['r1'] = now     # the old leader fired a moment ago
        w._event_state.set_cursor('syslog', 1)
        w._syslog_store.rows.append({'id': 2, 'message': 'x', 'severity': 3})
        w.leader = True                          # the lease changes hands
        w._event_worker_tick()
        assert w.fired == [], 'the new leader re-fired a rule still in cooldown'


# ── NET-3: a forged UDP source is counted, not jailed ─────────────────────────

class _OneDatagram:
    def __init__(self, src):
        self._left = [(b'<13>forged', (src, 514))]

    def recvfrom(self, _n):
        if self._left:
            return self._left.pop()
        raise OSError('closed')


def _server(**kw):
    from lib.services.syslog.server import SyslogServer
    return SyslogServer(sink=lambda *_a: None, allowed_sources=['10.0.0.0/8'], **kw)


class TestSpoofedUdpDoesNotJail:

    def test_a_rejected_datagram_is_counted_but_not_reported(self):
        offenses, drops = [], []
        srv = _server(on_offense=lambda ip, cat: offenses.append(ip),
                      on_drop=lambda ip, tr, n: drops.append((ip, tr, n)))
        srv._udp_loop(_OneDatagram('192.0.2.1'))
        assert offenses == [], 'a forged UDP source address was reported to the jail'
        assert drops == [('192.0.2.1', 'UDP', 1)]

    def test_a_rejected_tcp_connection_still_is(self):
        offenses = []
        srv = _server(on_offense=lambda ip, cat: offenses.append((ip, cat)))
        srv._reject('192.0.2.1', 'TCP')
        assert offenses == [('192.0.2.1', 'syslog_drop')]


# ── NET-4: a rule regex cannot hang the process ───────────────────────────────

class TestRuleRegexIsBounded:

    @pytest.mark.parametrize('pattern', ['^(a+)+$', r'(\w+\s?)*$', '(x{1,3})+y', '(a|b+)+x'])
    def test_nested_quantifiers_are_refused_on_save(self, pattern):
        from lib.core.users.service import AdminOpError
        from lib.services.events.rules_logic import clean_rule, validate_rule
        rule = clean_rule({'name': 'r', 'source': 'syslog', 'channels': ['email'],
                           'match_groups': [[{'type': 'regex', 'text': pattern}]]})
        with pytest.raises(AdminOpError) as exc:
            validate_rule(rule)
        assert exc.value.key == 'event_unsafe_regex'

    @pytest.mark.parametrize('pattern', [r'\d{1,3}(\.\d{1,3}){3}', 'error|fail',
                                         '^sshd.*Failed password', '(?:a|b)+c', '(?>a+)+'])
    def test_ordinary_patterns_still_save(self, pattern):
        from lib.services.events.rules_logic import clean_rule, validate_rule
        validate_rule(clean_rule({'name': 'r', 'source': 'syslog', 'channels': ['email'],
                                  'match_groups': [[{'type': 'regex', 'text': pattern}]]}))

    def test_a_stored_unsafe_pattern_is_never_run(self, monkeypatch):
        from lib.services.events import manager
        calls = []
        monkeypatch.setattr(manager.re, 'search', lambda *a, **k: calls.append(a))
        assert manager._EventsMixin._text_matches('regex', '^(a+)+$', 'a' * 40 + '!') is False
        assert calls == []

    def test_the_text_a_regex_sees_is_bounded(self, monkeypatch):
        from lib.services.events import manager
        seen = []
        monkeypatch.setattr(manager.re, 'search', lambda p, t, *a: seen.append(len(t)))
        manager._EventsMixin._text_matches('regex', 'needle', 'x' * 100_000)
        assert seen == [manager.REGEX_MAX_TEXT]


# ── NET-7: the receive queue has a byte budget, and the message is clipped ────

class TestSyslogMemoryBounds:

    def test_the_message_is_clipped_like_raw(self):
        from lib.services.syslog.parser import parse_message
        rec = parse_message(b'<13>Oct 12 10:00:00 host app: ' + b'x' * 60_000, source='10.0.0.1')
        assert len(rec['message']) <= 8192 and len(rec['raw']) <= 8192

    def test_the_queue_stops_at_its_byte_budget(self):
        srv = _server()
        srv._q_bytes_max = 100
        srv._enqueue(b'x' * 60, '10.0.0.1')
        srv._enqueue(b'x' * 60, '10.0.0.1')
        assert srv._q.qsize() == 1 and srv._q_bytes == 60

    def test_the_writer_gives_the_budget_back(self):
        got = []
        srv = _server()
        srv._sink = got.extend
        srv._enqueue(b'<13>hello', '10.0.0.1')
        assert srv._q_bytes == len(b'<13>hello')
        srv._stop.set()
        srv._writer_loop()
        assert len(got) == 1 and srv._q_bytes == 0
