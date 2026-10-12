#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/process from the second 2026-10-12 audit (WF-10).

The message named the item KEY (an opaque uid) and the alert said only "nginx": with the
same process watched on several servers nobody could tell which one fell. Both now carry
the process and the device. ``device_exec`` is patched: nothing runs.
"""

from unittest.mock import patch

from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, devices):
        self._h = devices

    def get(self, uid, **_kw):
        return self._h.get(uid)


_UID = '3f1c2b9e-0000-4000-8000-00000000abcd'


def _watchful(item):
    from watchfuls.process import Watchful
    mm = create_mock_monitor({'watchfuls.process': {'list': {_UID: item}}})
    mm._devices_store = _FakeStore({'h1': {
        'uid': 'h1', 'name': 'web-01', 'address': '10.0.0.9', 'kind': 'remote',
        'os': 'linux', 'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'root'}}}})
    return Watchful(mm)


def _run(item, out):
    w = _watchful(item)
    with patch.object(w, 'device_exec', return_value=(out, '', 0)), \
            patch.object(w, 'send_message') as send:
        w._monitor.check_status.return_value = True
        res = w.check().list[_UID]
    return res, send


class TestMessageNamesProcessAndDevice:

    def test_failure_message_and_alert_name(self):
        res, send = _run({'enabled': True, 'process': 'nginx', 'device_uid': 'h1',
                          'min_count': 2}, 'nginx\nsshd\n')
        assert res['status'] is False
        assert _UID not in res['message']
        assert 'web-01 - nginx' in res['message']
        assert res['name'] == 'web-01 - nginx'
        assert send.call_args.kwargs['item'] == 'web-01 - nginx'
        assert res['other_data']['device'] == 'web-01'

    def test_ok_message_never_shows_the_uid(self):
        res, _send = _run({'enabled': True, 'process': 'nginx', 'device_uid': 'h1'},
                          'nginx\n')
        assert res['status'] is True
        assert _UID not in res['message'] and 'nginx' in res['message']

    def test_inline_check_names_the_process_alone(self):
        from watchfuls.process import Watchful
        mm = create_mock_monitor({'watchfuls.process': {'list': {
            _UID: {'enabled': True, 'process': 'cron'}}}})
        w = Watchful(mm)
        with patch.object(w, 'device_exec', return_value=('cron\n', '', 0)):
            res = w.check().list[_UID]
        assert res['name'] == 'cron' and _UID not in res['message']
