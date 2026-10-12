#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background-service and helper defects found by the 2026-10-12 audit (fourth batch).

- A module that overran its deadline processed its result under its own run's lock while
  the next cycle wrote the same live status under another one.
- The dedicated monitor started its scheduler before the heartbeat had claimed the lease,
  so its first cycle was skipped and the first check came one interval late.
- Renewing the leader lease ignored the UPDATE's rowcount: two leaders for one beat.
- The control listener had no socket timeout: an idle client held a thread for ever.
- A syslog batch on a dead database was retried row by row — 500 timeouts per batch.
- The service command queue was never pruned, and a command claimed by a dead instance
  stayed "running" for good.
- The webhook SSRF guard was bypassed by following a redirect.
- One Telegram line over 4096 characters was a 400 and the alert was lost.
- A tile template could inject directives into the Content-Security-Policy header.
- A byte the locale could not decode left a command's output empty.
- Google Maps with no way out cost a 10 s wait on every page that drew the map.
- `to_bytes('inf')` raised and took down the check reading the threshold.
"""

from __future__ import annotations

import html
import math
import re
import shlex
import socket
import sys
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


# ── V9: one save lock per monitor ─────────────────────────────────────────────

class _Result:
    def __init__(self, key):
        self.list = [key]

    def get_status(self, _k):
        return True

    def get_message(self, _k):
        return ''

    def get_other_data(self, _k):
        return {}


class _Status:
    def __init__(self):
        self.data = {}

    def read(self):
        return True

    def save_module(self, _name):
        return True


class _Monitor:
    """Just what run_checks touches; records how many results are processed at once."""

    def __init__(self, check_delay: dict, process_delay: float):
        self.status = _Status()
        self.config_modules = SimpleNamespace(get_conf=lambda _m: {})
        self.debug = SimpleNamespace(print=lambda *a, **k: None)
        self._db = None
        self._check_delay = check_delay
        self._process_delay = process_delay
        self._busy = 0
        self.max_busy = 0
        self._count_lock = threading.Lock()

    def _get_enabled_modules(self):
        return list(self._check_delay)

    def _import_watchful(self, _m):
        return None

    def check_module(self, name, only_device=''):
        time.sleep(self._check_delay[name])
        return True, name, _Result(name)

    def _process_module_result(self, _name, _data, prune=True):
        with self._count_lock:
            self._busy += 1
            self.max_busy = max(self.max_busy, self._busy)
        time.sleep(self._process_delay)
        with self._count_lock:
            self._busy -= 1


class TestStragglerSharesTheSaveLock:

    def test_a_straggler_and_the_next_cycle_never_write_the_status_at_once(self):
        from lib.services.monitoring import executor
        mon = _Monitor({'slow': 0.3, 'fast': 0.0}, process_delay=0.5)
        # Cycle 1: `slow` overruns the deadline and lands on its own thread at ~0.3 s.
        executor.run_checks(mon, ['slow'], timeout=0.05)
        # Cycle 2 starts at once; `fast` is processing from ~0.05 s to ~0.55 s.
        executor.run_checks(mon, ['fast'], timeout=5)
        end = time.monotonic() + 10
        while mon._inflight_modules and time.monotonic() < end:
            time.sleep(0.02)
        assert not mon._inflight_modules, 'the straggler never landed'
        assert mon.max_busy == 1, 'a straggler and the next cycle wrote the status together'

    def test_the_lock_belongs_to_the_monitor(self):
        from lib.services.monitoring.executor import _save_lock_of
        a, b = SimpleNamespace(), SimpleNamespace()
        assert _save_lock_of(a) is _save_lock_of(a)
        assert _save_lock_of(a) is not _save_lock_of(b)


# ── V10: the lease before the first cycle ─────────────────────────────────────

class TestMonitorServiceStartOrder:

    def test_the_heartbeat_claims_the_lease_before_the_scheduler_starts(self, monkeypatch):
        from lib.services.monitoring import service as svc_mod
        calls = []

        class _Svc(svc_mod.MonitorService):
            _monitoring_interval = 300                # a property on the real one

        svc = _Svc.__new__(_Svc)
        svc._stop = threading.Event()
        svc._stop.set()                               # run() returns as soon as it is up
        svc._dbg = lambda *a, **k: None
        svc._monitoring_enabled = lambda: True
        svc._monitoring_start = lambda run_now=False: calls.append('scheduler')
        svc.start_heartbeat = lambda: calls.append('heartbeat')
        svc._monitoring_stop = lambda: None
        svc.stop_heartbeat = lambda: None
        svc._watch_loop = lambda: None
        monkeypatch.setattr(svc_mod, 'start_control_server', lambda _s: None)
        monkeypatch.setattr(svc_mod.signal, 'signal', lambda *a, **k: None)
        assert svc.run() == 0
        assert calls == ['heartbeat', 'scheduler']


# ── V12: renewing the lease honours the rowcount ──────────────────────────────

class _LeaseDB:
    """The holder reads as us, but the UPDATE finds nobody: another replica claimed it."""

    def __init__(self, me):
        self._me = me

    @contextmanager
    def transaction(self):
        yield

    def fetchone(self, _sql, _params=()):
        return (self._me, time.time() - 1)           # ours, but expired

    def execute(self, _sql, _params=()):
        return 0


class TestLeaderRenewRowcount:

    def test_a_renewal_that_updated_nothing_is_not_leadership(self):
        from lib.services.manager.leader import ServiceLeaderStore
        store = ServiceLeaderStore.__new__(ServiceLeaderStore)
        store._db = _LeaseDB('me')
        assert store.try_acquire('monitoring', 'me') is False


# ── V13: the control listener times idle connections out ──────────────────────

class TestControlServerTimeout:

    def test_the_handler_has_a_finite_socket_timeout(self):
        from lib.services.control_server import _Handler
        assert _Handler.timeout is not None and 0 < _Handler.timeout <= 60

    def test_an_idle_client_is_dropped(self, monkeypatch):
        from lib.services import control_server as cs
        monkeypatch.setattr(cs._Handler, 'timeout', 0.3)
        srv = cs.ControlServer(SimpleNamespace(_HB_KEY='x'), 'tok', 0, '127.0.0.1')
        srv.start()
        try:
            port = srv._httpd.server_address[1]
            with socket.create_connection(('127.0.0.1', port), timeout=5) as c:
                assert c.recv(1024) == b'', 'the server closed the idle connection'
        finally:
            srv.stop()

    def test_a_non_ascii_token_is_refused_not_raised(self):
        from lib.services.control_server import _Handler
        fake = SimpleNamespace(headers={'Authorization': 'Bearer tök'}, _token='tok')
        assert _Handler._authed(fake) is False
        fake.headers = {'Authorization': 'Bearer tok'}
        assert _Handler._authed(fake) is True


# ── V15: a dead database does not cost one timeout per row ────────────────────

class _DeadDB:
    def __init__(self):
        self.attempts = 0

    @contextmanager
    def transaction(self):
        self.attempts += 1
        raise ConnectionError('database is down')
        yield                                         # pragma: no cover


class TestSyslogBatchOnADeadDatabase:

    def test_the_row_by_row_retry_gives_up(self):
        from lib.services.syslog.store.messages import SyslogStore
        store = SyslogStore.__new__(SyslogStore)
        store.read_only = False
        store._db = _DeadDB()
        store._row_values = lambda rec: ()
        with pytest.raises(ConnectionError):
            store.add_many([{'message': str(i)} for i in range(500)])
        assert store._db.attempts <= 5, f'{store._db.attempts} attempts for one batch'


# ── V16: the command queue is pruned and dead claims are closed ───────────────

class TestCommandQueueHousekeeping:

    def _store(self, tmp_path):
        from lib.db.sqlite import SQLiteConnector
        from lib.services.manager.commands import ServiceCommandsStore
        return ServiceCommandsStore(SQLiteConnector(str(tmp_path / 'c.db')))

    def test_stale_claims_are_closed_and_old_rows_dropped(self, tmp_path):
        st = self._store(tmp_path)
        db = st._db
        now = time.time()
        rows = [
            # (action, created_at, claimed_at, done_at)
            ('stale_claim', now - 7200, now - 7200, None),
            ('fresh_claim', now - 60, now - 60, None),
            ('never_claimed_old', now - 3 * 86400, None, None),
            ('pending_new', now - 60, None, None),
            ('done_old', now - 3 * 86400, now - 3 * 86400, now - 3 * 86400),
            ('done_new', now - 60, now - 60, now - 60),
        ]
        for action, created, claimed, done in rows:
            db.execute('INSERT INTO service_commands (service_key, action, args, created_by, '
                       'created_at, claimed_at, done_at) VALUES (?,?,?,?,?,?,?)',
                       ('monitoring', action, '{}', '', created, claimed, done))
        db.commit()
        st.prune()
        got = {r['action']: r for r in st.list_recent(limit=50)}
        assert 'done_old' not in got
        assert got['stale_claim']['ok'] is False and got['stale_claim']['done_at']
        assert 'abandoned' in got['stale_claim']['result']
        assert got['never_claimed_old']['ok'] is False
        assert 'expired' in got['never_claimed_old']['result']
        for alive in ('fresh_claim', 'pending_new'):
            assert got[alive]['done_at'] is None, alive
        assert got['done_new']['done_at']
        # The expired one is not handed out any more.
        assert st.claim_next('monitoring', 'me')['action'] == 'pending_new'

    def test_the_heartbeat_prune_prunes_the_command_queue(self):
        from lib.services.heartbeat import _HeartbeatMixin
        called = []

        class _Svc(_HeartbeatMixin):
            _service_instances_store = None
            _service_commands_store = SimpleNamespace(prune=lambda *a, **k: called.append(1))

        _Svc()._heartbeat_prune()
        assert called == [1]


# ── V17: the webhook does not follow redirects ────────────────────────────────

class TestWebhookRedirects:

    def _capture(self, monkeypatch):
        from lib.core.notify.webhook import notify as wh
        seen = []

        def fake(url, **kw):
            seen.append((url, kw))
            return SimpleNamespace(status_code=302)
        monkeypatch.setattr(wh._req, 'post', fake)
        monkeypatch.setattr(wh._req, 'put', fake)
        monkeypatch.setattr(wh._req, 'get', fake)
        return wh, seen

    @pytest.mark.parametrize('method', ['POST', 'PUT', 'GET'])
    def test_no_method_follows_a_redirect(self, monkeypatch, method):
        wh, seen = self._capture(monkeypatch)
        ok, _msg = wh._dispatch({'enabled': True, 'url': 'http://192.0.2.10/hook',
                                 'method': method, 'timeout': 5}, kind='down', message='x')
        assert ok is False, 'a 3xx is not a delivery'
        assert seen and seen[0][1].get('allow_redirects') is False

    def test_a_get_whose_host_comes_from_a_placeholder_is_checked_rendered(self, monkeypatch):
        wh, seen = self._capture(monkeypatch)
        ok, _msg = wh._dispatch({'enabled': True, 'url': 'http://{item}/latest/meta-data',
                                 'method': 'GET', 'timeout': 5},
                                kind='down', item='169.254.169.254', message='x')
        assert ok is False
        assert seen == [], 'the metadata address was requested'


class TestTeamsWebhookGuard:
    """The Teams channel posts to a URL the operator types: same guard as the webhook."""

    def _capture(self, monkeypatch):
        from lib.core.notify.msteams import notify as tn
        seen = []

        def fake(url, **kw):
            seen.append((url, kw))
            return SimpleNamespace(status_code=302)
        monkeypatch.setattr(tn._req, 'post', fake)
        return tn, seen

    def test_the_metadata_address_is_never_requested(self, monkeypatch):
        tn, seen = self._capture(monkeypatch)
        ok, _msg = tn._post_card('http://169.254.169.254/latest/meta-data', {})
        assert ok is False
        assert seen == [], 'the metadata address was requested'

    def test_a_redirect_is_not_followed(self, monkeypatch):
        tn, seen = self._capture(monkeypatch)
        ok, _msg = tn._post_card('http://192.0.2.10/webhook', {})
        assert ok is False, 'a 3xx is not a delivery'
        assert seen and seen[0][1].get('allow_redirects') is False


# ── V18: Telegram text stays under the cap ────────────────────────────────────

def _parsed_len(text: str) -> int:
    """What Telegram counts: the text after the HTML is parsed."""
    return len(html.unescape(re.sub(r'<[^>]+>', '', text)))


class TestTelegramLongLines:

    @pytest.mark.parametrize('grouped', [False, True])
    def test_a_huge_alert_is_clipped_not_rejected(self, monkeypatch, grouped):
        import lib.providers.telegram as provider
        from lib.core.notify.telegram import channel
        sent = []
        monkeypatch.setattr(provider, 'send_telegram',
                            lambda _t, _c, text, **_k: (sent.append(text), (True, 200, 'sent'))[1])
        alerts = [{'kind': 'down', 'module': 'm', 'item': 'i', 'message': '<&>' * 4000}]
        cfg = {'telegram': {'token': 't', 'chat_id': 'c', 'group_messages': grouped}}
        channel.flush(None, cfg, alerts, 'host', '')
        assert sent and all(_parsed_len(t) < 4096 for t in sent), [_parsed_len(t) for t in sent]

    def test_a_single_event_message_is_clipped(self):
        from lib.core.notify.telegram.notify import _format
        text = _format('down', 'm', 'i', 'DOWN', 'x' * 20000, '2026-10-12 10:00')
        assert _parsed_len(text) < 4096


# ── E10: a tile template cannot write the CSP ─────────────────────────────────

class TestTileOriginIsAnOrigin:

    @pytest.mark.parametrize('tiles', [
        'https://tiles.example.org; script-src *;/{z}/{x}/{y}.png',
        'https://tiles.example.org,*/{z}',
        'https://tiles example.org/{z}',
        'https://tiles.example.org:99999/{z}',
    ])
    def test_injection_is_refused(self, tiles):
        from lib.maps.catalog import origin_of
        assert origin_of(tiles) == ''

    def test_real_origins_still_come_out(self):
        from lib.maps.catalog import origin_of
        assert origin_of('https://u:p@Tiles.Example.org:8443/{z}') == 'https://tiles.example.org:8443'
        assert origin_of('http://192.0.2.5/{z}/{x}/{y}.png') == 'http://192.0.2.5'
        assert origin_of('https://[2001:db8::1]:8080/{z}') == 'https://[2001:db8::1]:8080'


# ── E11: undecodable bytes do not empty the output ────────────────────────────

class TestExecDecoding:

    def test_local_output_survives_a_bad_byte(self):
        from lib.system.exe import Exec
        script = "import sys; sys.stdout.buffer.write(b'ok \\x81\\xff end')"
        r = Exec(f'{shlex.quote(sys.executable)} -c {shlex.quote(script)}').start()
        assert r.exception is None, r.exception
        assert r.out and r.out.startswith('ok ') and r.out.endswith(' end')

    def test_remote_output_survives_a_bad_byte(self, monkeypatch):
        from lib.system import exe

        class _Stream:
            def __init__(self, data):
                self._data = data
                self.channel = SimpleNamespace(recv_exit_status=lambda: 0)

            def read(self):
                return self._data

        class _Client:
            def load_system_host_keys(self):
                pass

            def set_missing_host_key_policy(self, _p):
                pass

            def connect(self, **_kw):
                pass

            def exec_command(self, _cmd, timeout=None):
                return None, _Stream(b'ok \x81\xff end'), _Stream(b'')

            def close(self):
                pass

        monkeypatch.setattr(exe.paramiko, 'SSHClient', _Client)
        ex = exe.Exec('uptime')
        ex.location = exe.EnumLocationExec.remote
        r = ex.start()
        assert r.exception is None, r.exception
        assert r.out.startswith('ok ') and r.out.endswith(' end') and r.code == 0


# ── E12: a failed Google session is remembered for a while ────────────────────

class TestGoogleSessionFailureIsCached:

    def test_no_second_network_wait_after_a_failure(self, monkeypatch):
        from lib.maps import google
        google.forget()
        calls = []

        def down(*_a, **_k):
            calls.append(1)
            raise OSError('no route to host')
        monkeypatch.setattr(google, '_open', down)
        try:
            for _ in range(3):
                with pytest.raises(google.MapKeyError):
                    google.session_for('k')
            assert len(calls) == 1
            google.forget()                          # the test button: try again now
            with pytest.raises(google.MapKeyError):
                google.session_for('k')
            assert len(calls) == 2
        finally:
            google.forget()


# ── E14: to_bytes of a non-finite number ──────────────────────────────────────

class TestToBytesNonFinite:

    @pytest.mark.parametrize('value', ['inf', '-inf', 'nan', math.inf, math.nan])
    def test_reads_as_unset(self, value):
        from lib.util import to_bytes
        assert to_bytes(value, 'GiB') == 0
