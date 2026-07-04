#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the host SSH helper (lib/hosts/ssh_client.py).

SSH reachability is a host-level concern reused by modules; these cover
inline-key parsing and that test_connection never raises (reports failures).
"""

from unittest.mock import patch

import pytest

from lib.hosts import ssh_client


@pytest.mark.skipif(not ssh_client.HAS_PARAMIKO, reason='paramiko not installed')
class TestPkey:

    def test_parses_generated_key(self):
        import io
        import paramiko
        key = paramiko.RSAKey.generate(2048)
        buf = io.StringIO()
        key.write_private_key(buf)
        parsed = ssh_client.pkey_from_string(buf.getvalue())
        assert parsed.get_fingerprint() == key.get_fingerprint()

    def test_invalid_key_raises(self):
        with pytest.raises(ValueError):
            ssh_client.pkey_from_string('not a key')


@pytest.mark.skipif(not ssh_client.HAS_PARAMIKO, reason='paramiko not installed')
class TestTestConnection:

    def test_empty_address_reported(self):
        ok, msg = ssh_client.test_connection(address='')
        assert ok is False and 'address' in msg.lower()

    def test_success(self):
        with patch.object(ssh_client, 'connect') as mock_conn:
            mock_conn.return_value.close.return_value = None
            ok, msg = ssh_client.test_connection(
                address='10.0.0.1', user='root', password='x')
        assert ok is True and 'success' in msg.lower()

    def test_failure_is_caught(self):
        with patch.object(ssh_client, 'connect', side_effect=OSError('refused')):
            ok, msg = ssh_client.test_connection(address='10.0.0.1', user='root')
        assert ok is False and 'refused' in msg

    def test_build_connect_kwargs_auth_precedence(self):
        # Inline key text wins over key file, which wins over password.
        with patch.object(ssh_client, 'pkey_from_string', return_value='PKEY'):
            kw = ssh_client.build_connect_kwargs(
                address='h', user='u', password='p',
                key_path='/k', key_string='KEYTEXT')
        assert kw['pkey'] == 'PKEY'
        assert 'key_filename' not in kw and 'password' not in kw

    def test_build_connect_kwargs_password_only(self):
        kw = ssh_client.build_connect_kwargs(address='h', user='u', password='p')
        assert kw['password'] == 'p'
        assert 'pkey' not in kw and 'key_filename' not in kw


def test_no_paramiko_degrades_gracefully():
    with patch.object(ssh_client, 'HAS_PARAMIKO', False):
        ok, msg = ssh_client.test_connection(address='10.0.0.1')
        assert ok is False and 'paramiko' in msg.lower()
        with pytest.raises(ValueError):
            ssh_client.pkey_from_string('whatever')


class _FakeStd:
    def __init__(self, text):
        self._b = text.encode()
    def read(self):
        return self._b


class _FakeClient:
    """Minimal SSH client whose exec_command replays canned command output."""
    def __init__(self, outputs):
        self._outputs = outputs   # {cmd: stdout text}
    def exec_command(self, cmd, timeout=None):   # noqa: ARG002
        return None, _FakeStd(self._outputs.get(cmd, '')), _FakeStd('')


class TestDetectOs:

    def test_uname_linux(self):
        c = _FakeClient({'uname -s': 'Linux\n'})
        assert ssh_client.detect_os(c) == 'linux'

    def test_uname_darwin(self):
        c = _FakeClient({'uname -s': 'Darwin'})
        assert ssh_client.detect_os(c) == 'darwin'

    def test_uname_freebsd(self):
        c = _FakeClient({'uname -s': 'FreeBSD'})
        assert ssh_client.detect_os(c) == 'freebsd'

    def test_windows_via_ver(self):
        # No uname → falls back to `ver` (Windows).
        c = _FakeClient({'ver': 'Microsoft Windows [Version 10.0.19045]'})
        assert ssh_client.detect_os(c) == 'windows'

    def test_unknown_is_other(self):
        assert ssh_client.detect_os(_FakeClient({})) == 'other'

    def test_test_connection_detect_returns_os(self):
        if not ssh_client.HAS_PARAMIKO:
            pytest.skip('paramiko not installed')
        fake = _FakeClient({'uname -s': 'Linux'})
        with patch.object(ssh_client, 'connect', return_value=fake):
            ok, msg, os_found = ssh_client.test_connection(
                address='10.0.0.1', user='root', detect=True)
        assert ok is True and os_found == 'linux'


def test_local_os_is_canonical():
    from lib.util import os_detect
    assert os_detect.local_os() in os_detect.CANONICAL
