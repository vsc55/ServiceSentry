#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Service and data defects found by the 2026-10-12 audit — each pinned where it is decided.

- SQLite: a transaction that read before writing got «database is locked» at once when
  another connection committed in between (deferred BEGIN in WAL).
- Backups: a DATETIME or DECIMAL from MySQL/PostgreSQL could not be written to JSON, so every
  copy holding syslog came out `partial`.
- DCIM search: `ESCAPE '\\'` is a syntax error on MySQL/MariaDB; the escape is `!` now.
- Alerts were sent inline at the end of the cycle, inside its lock — one slow channel held
  every check. They go out on the notifier's own thread.
- The Telegram bot token is in the URL, and the driver's error quoted it into the logs.
- A flood of rejected syslog datagrams wrote two offence rows per packet under the jail's lock.
- A failure recorded under an item's bare key was pruned silently when the item came back
  under sub-keys: the DOWN was sent and its recovery never was.
- `--verbose` alone no longer enables the debugger (see test_secret_and_debug_guards).
"""

from __future__ import annotations

import datetime
import decimal
import os
import threading
import time
from unittest import mock

import pytest

from lib.core.backup.archive import clean_cell
from lib.core.dcim.store import LIKE_ESC, like_clause, like_esc
from lib.db.sqlite import SQLiteConnector


class TestSqliteImmediate:

    def test_a_transaction_that_reads_first_waits_instead_of_failing(self, tmp_path):
        db = SQLiteConnector(str(tmp_path / 't.db'))
        db.execute_ddl('CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)')
        db.execute("INSERT INTO t VALUES ('a', '1')")
        db.commit()
        leyo, out = threading.Event(), {}

        def primero():
            try:
                with db.transaction():
                    db.fetchall('SELECT v FROM t')
                    leyo.set()
                    time.sleep(0.4)                   # another connection writes meanwhile
                    db.execute("UPDATE t SET v = '2' WHERE k = 'a'")
                out['a'] = 'ok'
            except Exception as exc:                  # pylint: disable=broad-except
                out['a'] = repr(exc)

        def segundo():
            leyo.wait(5)
            try:
                db.execute("UPDATE t SET v = '3' WHERE k = 'a'")
                db.commit()
                out['b'] = 'ok'
            except Exception as exc:                  # pylint: disable=broad-except
                out['b'] = repr(exc)
        hilos = [threading.Thread(target=primero), threading.Thread(target=segundo)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(30)
        assert out == {'a': 'ok', 'b': 'ok'}
        assert db.fetchone("SELECT v FROM t WHERE k = 'a'")[0] == '3', 'the second waited its turn'


class TestBackupCells:

    def test_server_driver_types_become_json(self):
        assert clean_cell(datetime.datetime(2026, 1, 2, 3, 4, 5), False) == '2026-01-02 03:04:05'
        assert clean_cell(datetime.date(2026, 1, 2), True) == '2026-01-02'
        assert clean_cell(decimal.Decimal('2.5'), True) == 2.5
        assert clean_cell(decimal.Decimal('3'), True) == 3


class TestLikeEscape:

    def test_the_escape_is_not_a_backslash(self):
        sql, _ = like_clause(['name'], 'x')
        assert '\\' not in sql and f"ESCAPE '{LIKE_ESC}'" in sql

    def test_wildcards_typed_are_literal(self, tmp_path):
        db = SQLiteConnector(str(tmp_path / 'l.db'))
        q = f"SELECT CASE WHEN LOWER(?) LIKE ? ESCAPE '{LIKE_ESC}' THEN 1 ELSE 0 END"
        res = [db.fetchone(q, (t, '%' + like_esc(p) + '%'))[0]
               for t, p in (('a_b', 'a_b'), ('axb', 'a_b'), ('50%', '50%'), ('500', '50%'),
                            ('x!y', 'x!y'))]
        assert res == [1, 0, 1, 0, 1]


class TestAlertsOffTheCycle:

    def test_flush_later_returns_at_once_and_sends_in_order(self):
        from lib.core.notify import monitor_notifier as mn         # noqa: PLC0415
        enviados = []

        class _Ch:
            @staticmethod
            def flush(_wa, _cfg, alerts, _host, _url):
                time.sleep(0.3)                                    # a slow receiver
                enviados.append([a['item'] for a in alerts])
                return True, 'ok'

        wa = mock.Mock(spec=['_read_config_file', '_CONFIG_FILE', '_dbg'])
        wa._read_config_file.return_value = {'notifications': {'slow_on_down': True}}
        n = mn.MonitorNotifier(wa)
        with mock.patch.object(mn.registry, 'channels', return_value={'slow': _Ch()}):
            n.add('down', 'm', 'uno', 'x')
            t0 = time.monotonic()
            assert n.flush_later() is True
            n.add('down', 'm', 'dos', 'y')
            n.flush_later()
            assert time.monotonic() - t0 < 0.2, 'the cycle does not wait for the channel'
            assert mn.drain(10)
        assert enviados == [['uno'], ['dos']]


class TestTelegramToken:

    def test_a_connection_error_does_not_carry_the_token(self):
        import requests                                            # noqa: PLC0415
        from lib.providers import telegram                         # noqa: PLC0415
        err = requests.ConnectionError('Max retries exceeded with url: /bot123:SECRET/sendMessage')
        with mock.patch.object(telegram.requests, 'post', side_effect=err):
            with pytest.raises(requests.ConnectionError) as got:
                telegram.send_telegram('123:SECRET', '1', 'hola')
        assert '123:SECRET' not in str(got.value) and '***' in str(got.value)


class TestSyslogOffences:

    def test_offences_are_reported_once_per_window_per_source(self):
        from lib.services.syslog.server import SyslogServer        # noqa: PLC0415
        avisos = []
        srv = SyslogServer(sink=lambda *_a: None, bind_host='127.0.0.1',
                           allowed_sources=['10.0.0.0/8'], dbg_warn=lambda _m: None,
                           on_offense=lambda ip, why: avisos.append(ip))
        for _ in range(50):
            srv._reject('1.2.3.4', 'UDP')
        srv._reject('5.6.7.8', 'UDP')
        assert avisos == ['1.2.3.4', '5.6.7.8']

    def test_the_drop_tally_makes_room_for_new_sources(self):
        from lib.services.syslog import server as sv               # noqa: PLC0415
        srv = sv.SyslogServer(sink=lambda *_a: None, bind_host='127.0.0.1',
                              allowed_sources=['10.0.0.0/8'], dbg_warn=lambda _m: None)
        viejo = time.time() - 7200
        srv._drops = {f'9.9.{i // 256}.{i % 256}': {'count': 1, 'last_log': viejo, 'flushed': 1}
                      for i in range(sv._DROPS_MAX)}
        srv._note_drop('1.2.3.4', 'UDP')
        assert '1.2.3.4' in srv._drops


class TestRecoveryUnderSubKeys:

    def test_a_bare_key_error_is_followed_by_its_recovery(self, tmp_path):
        from lib import Monitor                                    # noqa: PLC0415
        from lib.modules import ReturnModuleCheck                  # noqa: PLC0415
        for d in ('config', 'var', 'watchfuls'):
            os.makedirs(tmp_path / d, exist_ok=True)
        m = Monitor(str(tmp_path), str(tmp_path / 'config'), str(tmp_path / 'watchfuls'),
                    str(tmp_path / 'var'))
        try:
            m._notifier = mock.Mock()
            caido = ReturnModuleCheck()
            caido.set('srv1', False, 'Memory srv1: SSH refused')
            m._process_module_result('ram_swap', caido)
            m._notifier.reset_mock()
            vuelve = ReturnModuleCheck()
            vuelve.set('srv1_ram', True, 'RAM 40%')
            vuelve.set('srv1_swap', True, 'Swap 1%')
            m._process_module_result('ram_swap', vuelve)
            kinds = [c.args[0] for c in m._notifier.add.call_args_list]
            assert kinds == ['recovery'], kinds
        finally:
            m.close()


class TestUnsavedStateIsKept:

    def test_a_state_that_failed_to_save_does_not_realert(self, tmp_path):
        from lib import Monitor                                    # noqa: PLC0415
        from lib.modules import ReturnModuleCheck                  # noqa: PLC0415
        from lib.services.monitoring.executor import run_checks    # noqa: PLC0415
        for d in ('config', 'var', 'watchfuls'):
            os.makedirs(tmp_path / d, exist_ok=True)
        m = Monitor(str(tmp_path), str(tmp_path / 'config'), str(tmp_path / 'watchfuls'),
                    str(tmp_path / 'var'))

        class _Status:
            """A store whose writes fail: reading gives back what was there before."""
            data: dict = {}

            def read(self):
                self.data = {}
                return self.data

            def save_module(self, _name):
                return False

            def get_conf(self, path, default=None):
                cur = self.data
                for p in path:
                    if not isinstance(cur, dict) or p not in cur:
                        return default
                    cur = cur[p]
                return cur

            def set_conf(self, path, value):
                cur = self.data
                for p in path[:-1]:
                    cur = cur.setdefault(p, {})
                cur[path[-1]] = value

        def _check(_mod, only_device=''):
            r = ReturnModuleCheck()
            r.set('item1', False, 'down')
            return True, 'fakemod', r
        try:
            m.status = _Status()
            m._notifier = mock.Mock()
            with mock.patch.object(m, 'check_module', side_effect=_check):
                run_checks(m, ['fakemod'], timeout=10)
                run_checks(m, ['fakemod'], timeout=10)
            kinds = [c.args[0] for c in m._notifier.add.call_args_list]
            assert kinds == ['down'], kinds
        finally:
            m.close()
