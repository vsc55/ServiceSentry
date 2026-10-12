#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime halves of the 2026-10-12 audit's sixth batch: where the panel listens, how long a
connection may idle, and who the CLI runs as.

- **DIST-2.** Every launcher passed `--web-host 0.0.0.0`, so the Host field of Configuration →
  External access did nothing. The order is now CLI > env (`SS_WEB_HOST`/`SS_WEB_PORT`, then
  `SS_PORT`) > saved config > default, and the two env vars are registered in the config spec
  so the field shows locked when they are set.
- **DIST-3.** Werkzeug's threaded server had no socket timeout: an idle connection held a
  thread and a descriptor forever.
- **DIST-9.** The CLI run as root over a dedicated user's data created root-owned files the
  services could not write. It now becomes the data directory's owner, or refuses.

No app, no DB, no sockets: the server test only looks at what `make_server` is handed.
"""

from __future__ import annotations

import types

import pytest

import main
from lib.config.manager import overlay_section_env
from lib.config.spec import CFG_BY_PATH, env_field_specs


# ── DIST-2: where the panel listens ─────────────────────────────────────────────
def _args(**kw):
    return types.SimpleNamespace(web_host=kw.get('host'), web_port=kw.get('port'))


class TestWebBind:

    def test_the_saved_setting_decides_when_nothing_else_is_given(self):
        assert main.resolve_web_bind(_args(), {'host': '127.0.0.1', 'port': 9001}) == \
            ('127.0.0.1', 9001)

    def test_defaults_without_a_setting(self):
        assert main.resolve_web_bind(_args(), {}) == ('0.0.0.0', 8080)

    def test_env_overrides_beat_the_saved_setting(self):
        ov = {'web_admin|host': '10.0.0.5', 'web_admin|port': 9100}
        assert main.resolve_web_bind(_args(), {'host': '127.0.0.1', 'port': 9001}, ov) == \
            ('10.0.0.5', 9100)

    def test_the_command_line_beats_everything(self):
        ov = {'web_admin|host': '10.0.0.5', 'web_admin|port': 9100}
        assert main.resolve_web_bind(_args(host='::1', port=7000),
                                     {'host': '127.0.0.1', 'port': 9001}, ov) == ('::1', 7000)

    def test_start_web_binds_through_it(self):
        import inspect                                               # noqa: PLC0415
        src = inspect.getsource(main.start_web)
        assert 'resolve_web_bind(' in src
        assert "_wa_cfg.get('host') or" not in src

    def test_host_and_port_vars_are_registered(self):
        e = env_field_specs()
        assert e['SS_WEB_HOST'] == ('web_admin|host', str)
        assert e['SS_WEB_PORT'] == ('web_admin|port', int)
        assert e['SS_PORT'] == ('web_admin|port', int)
        names = list(e)
        assert names.index('SS_WEB_PORT') > names.index('SS_PORT'), \
            'consumers apply these in order, last wins: SS_WEB_PORT must come after SS_PORT'
        assert CFG_BY_PATH['web_admin|port'].env_alias == ('SS_WEB_PORT',)

    def test_ss_web_port_wins_over_ss_port(self, monkeypatch):
        monkeypatch.setenv('SS_PORT', '9001')
        monkeypatch.setenv('SS_WEB_PORT', '9002')
        monkeypatch.setenv('SS_WEB_HOST', '127.0.0.1')
        out = overlay_section_env('web_admin', {'port': 8080, 'host': '0.0.0.0'})
        assert out['port'] == 9002 and out['host'] == '127.0.0.1'


# ── DIST-3: idle connections are dropped ─────────────────────────────────────────
class TestRequestTimeout:

    def test_the_server_is_built_with_a_timed_handler(self, monkeypatch):
        pytest.importorskip('flask')        # the mixin's package imports the Flask app
        import werkzeug.serving                                      # noqa: PLC0415
        from lib.web_admin.mixins.server import _ServerMixin        # noqa: PLC0415
        seen = {}

        def fake_make_server(host, port, app, **kw):
            seen.update(kw)
            return object()

        monkeypatch.setattr(werkzeug.serving, 'make_server', fake_make_server)
        servers, failed = _ServerMixin._bind_web_servers(['127.0.0.1'], 1, lambda *a: None)
        assert failed == [] and len(servers) == 1
        handler = seen.get('request_handler')
        assert handler is not None, 'make_server got no request handler: no timeout'
        assert issubclass(handler, werkzeug.serving.WSGIRequestHandler)
        assert handler.timeout == _ServerMixin.WEB_REQUEST_TIMEOUT
        assert 5 <= _ServerMixin.WEB_REQUEST_TIMEOUT <= 120


# ── DIST-9: the CLI becomes the owner of the data ───────────────────────────────
class _FakeOs:
    """Just enough of `os` for the switch: records the calls, in order."""

    name = 'posix'

    def __init__(self, euid=0, uid=999, gid=998, fail=None):
        self._euid, self._st = euid, types.SimpleNamespace(st_uid=uid, st_gid=gid)
        self.calls, self._fail = [], fail

    def geteuid(self):
        return self._euid

    def stat(self, path):
        if path == '/missing':
            raise FileNotFoundError(path)
        return self._st

    def _rec(self, name, *a):
        if self._fail == name:
            raise PermissionError(name)
        self.calls.append((name,) + a)

    def setgroups(self, groups):
        self._rec('setgroups', list(groups))

    def setgid(self, gid):
        self._rec('setgid', gid)

    def setuid(self, uid):
        self._rec('setuid', uid)


class TestCliOwner:

    def test_root_becomes_the_owner_gid_first(self):
        fos = _FakeOs()
        got = main._cli_become_data_owner('/var/lib/x', _os=fos)
        assert got
        assert [c[0] for c in fos.calls] == ['setgroups', 'setgid', 'setuid']
        assert fos.calls[1] == ('setgid', 998) and fos.calls[2] == ('setuid', 999)

    def test_not_root_changes_nothing(self):
        fos = _FakeOs(euid=1000)
        assert main._cli_become_data_owner('/var/lib/x', _os=fos) is None
        assert fos.calls == []

    def test_roots_own_data_changes_nothing(self):
        fos = _FakeOs(uid=0, gid=0)
        assert main._cli_become_data_owner('/var/lib/x', _os=fos) is None
        assert fos.calls == []

    def test_no_data_dir_yet_changes_nothing(self):
        fos = _FakeOs()
        assert main._cli_become_data_owner('/missing', _os=fos) is None

    def test_a_failed_switch_refuses_instead_of_writing(self, capsys):
        fos = _FakeOs(fail='setuid')
        with pytest.raises(SystemExit) as exc:
            main._cli_become_data_owner('/var/lib/x', _os=fos)
        assert exc.value.code == 1
        assert 'runuser' in capsys.readouterr().err

    def test_the_cli_entry_point_calls_it_before_the_commands(self):
        import inspect                                               # noqa: PLC0415
        src = inspect.getsource(main)
        tail = src[src.index('if __name__ == "__main__":'):]
        assert tail.index('_cli_become_data_owner(') < tail.index('_cli.run(')
