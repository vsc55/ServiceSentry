#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for lib/core/devices/probe — the DEVICE half of the Servers "test" feature.

Resolving an unsaved device is what is specific to devices here; running the check is not, and
lives in lib/modules/check_runner (see tests/test_module_check_runner.py).  The runs below
stay in this file because what they exercise is the device resolution: a check reaching a
remote machine through the draft the admin has typed but not yet saved.
"""

from contextlib import contextmanager
from unittest.mock import patch

from lib.core.devices import ssh_client
from lib.core.devices import probe as device_probe
from lib.modules.check_runner import run_module_check


@contextmanager
def _mock_ssh(out):
    """Mock the remote SSH path used by device_exec (connect_host + run_command)."""
    with patch.object(ssh_client, 'HAS_PARAMIKO', True), \
         patch.object(ssh_client, 'connect_host', return_value=object()), \
         patch.object(ssh_client, 'run_command', return_value=(out, '', 0)):
        yield


class _FakeStore:
    def __init__(self, devices):
        self._h = devices
    def get(self, uid, **_kw):
        return self._h.get(uid)


_DEVICE = {'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': 'linux',
         'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'root'}}}

_PS_OUT = "nginx\nnginx\nsshd\n"


class TestTheDraftDeviceIsWhatGetsChecked:
    """The modal tests what the admin typed, so the check must reach the draft's address."""

    def test_runs_process_check_remote(self):
        cfg = {'watchfuls.process': {'list': {
            'web': {'process': 'nginx', 'min_count': 2, 'enabled': True, 'device_uid': 'h1'}}}}
        store = device_probe.ProbeDevicesStore(_DEVICE, _FakeStore({'h1': _DEVICE}))
        with _mock_ssh(_PS_OUT):
            results = run_module_check('process', cfg, devices_store=store)
        assert len(results) == 1
        assert results[0]['key'] == 'web' and results[0]['status'] is True
        assert results[0]['other_data']['count'] == 2

    def test_runs_process_check_failure(self):
        cfg = {'watchfuls.process': {'list': {
            'web': {'process': 'nginx', 'min_count': 5, 'enabled': True, 'device_uid': 'h1'}}}}
        store = device_probe.ProbeDevicesStore(_DEVICE, _FakeStore({'h1': _DEVICE}))
        with _mock_ssh(_PS_OUT):
            results = run_module_check('process', cfg, devices_store=store)
        assert results[0]['status'] is False


class TestProbeDevicesStore:

    def test_returns_draft_for_its_uid(self):
        real = _FakeStore({'real': {'uid': 'real', 'address': 'x'}})
        draft = {'uid': '__probe__', 'address': '10.0.0.9'}
        store = device_probe.ProbeDevicesStore(draft, real)
        assert store.get('__probe__')['address'] == '10.0.0.9'
        assert store.get('real')['address'] == 'x'
        assert store.get('nope') is None
