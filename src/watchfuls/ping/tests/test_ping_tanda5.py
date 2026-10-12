#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/ping (W12): a process with no ICMP privilege at all.

Neither a raw nor an unprivileged datagram ICMP socket could be opened, and every host came
out DOWN for a reason that was the monitor's, not theirs. The last resort is the system
``ping`` binary (judged by its exit code, RTT read leniently), and when that is missing too
the check says ICMP is not permitted instead of a bare DOWN.
"""

import subprocess
from unittest.mock import patch

import pytest

from conftest import create_mock_monitor

# ── Recorded system ping answers ─────────────────────────────────────────────────

_LINUX_EN = """PING 192.0.2.10 (192.0.2.10) 56(84) bytes of data.
64 bytes from 192.0.2.10: icmp_seq=1 ttl=117 time=14.2 ms

--- 192.0.2.10 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 14.200/14.200/14.200/0.000 ms
"""

_LINUX_ES = """PING 192.0.2.10 (192.0.2.10) 56(84) bytes de datos.
64 bytes desde 192.0.2.10: icmp_seq=1 ttl=117 tiempo=9,87 ms

--- 192.0.2.10 estadísticas ping ---
1 paquetes transmitidos, 1 recibidos, 0% paquetes perdidos, tiempo 0ms
"""

_LINUX_DOWN = """PING 192.0.2.10 (192.0.2.10) 56(84) bytes of data.

--- 192.0.2.10 ping statistics ---
1 packets transmitted, 0 received, 100% packet loss, time 0ms
"""

_WIN_EN = """
Pinging 192.0.2.10 with 32 bytes of data:
Reply from 192.0.2.10: bytes=32 time=23ms TTL=117

Ping statistics for 192.0.2.10:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 23ms, Maximum = 23ms, Average = 23ms
"""

_WIN_ES = """
Haciendo ping a 192.0.2.10 con 32 bytes de datos:
Respuesta desde 192.0.2.10: bytes=32 tiempo=18ms TTL=117

Estadísticas de ping para 192.0.2.10:
    Paquetes: enviados = 1, recibidos = 1, perdidos = 0
    (0% perdidos),
Tiempos aproximados de ida y vuelta en milisegundos:
    Mínimo = 18ms, Máximo = 18ms, Media = 18ms
"""

_WIN_ES_SUBMS = """
Haciendo ping a 127.0.0.1 con 32 bytes de datos:
Respuesta desde 127.0.0.1: bytes=32 tiempo<1m TTL=128
"""

# A router answering for an unreachable host: Windows ping exits 0 here.
_WIN_UNREACHABLE = """
Pinging 192.0.2.10 with 32 bytes of data:
Reply from 192.0.2.1: Destination host unreachable.

Ping statistics for 192.0.2.10:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
"""

_MAC = """PING 192.0.2.10 (192.0.2.10): 56 data bytes
64 bytes from 192.0.2.10: icmp_seq=0 ttl=117 time=31.504 ms
"""


def _watchful(items=None):
    from watchfuls.ping import Watchful
    return Watchful(create_mock_monitor({'watchfuls.ping': {'list': items or {}}}))


class TestParsePingOutput:
    """The verdict is the exit code; the RTT is read from any locale's ``=N ms`` shape."""

    @pytest.mark.parametrize('out,platform,rtt', [
        (_LINUX_EN, 'linux', 14.2),
        (_LINUX_ES, 'linux', 9.87),
        (_MAC, 'darwin', 31.504),
        (_WIN_EN, 'win32', 23.0),
        (_WIN_ES, 'win32', 18.0),
        (_WIN_ES_SUBMS, 'win32', 1.0),
    ])
    def test_reply_rtt_read_in_every_locale(self, out, platform, rtt):
        from watchfuls.ping.client import _parse_ping_output
        assert _parse_ping_output(out, 0, platform) == pytest.approx(rtt)

    def test_a_failed_exit_code_is_down(self):
        from watchfuls.ping.client import _parse_ping_output
        assert _parse_ping_output(_LINUX_DOWN, 1, 'linux') is None

    def test_windows_router_unreachable_with_exit_zero_is_down(self):
        from watchfuls.ping.client import _parse_ping_output
        assert _parse_ping_output(_WIN_UNREACHABLE, 0, 'win32') is None

    def test_up_with_an_unreadable_rtt_is_up_without_latency(self):
        from watchfuls.ping.client import RTT_UNKNOWN, _parse_ping_output
        assert _parse_ping_output('reply received', 0, 'linux') == RTT_UNKNOWN


class TestPingArgv:
    """An argument list per platform, the destination last, never a shell string."""

    def test_linux(self):
        from watchfuls.ping.client import _ping_argv
        assert _ping_argv('/bin/ping', '192.0.2.10', 2, 'linux') == \
            ['/bin/ping', '-c', '1', '-W', '2', '192.0.2.10']

    def test_windows_waits_in_milliseconds(self):
        from watchfuls.ping.client import _ping_argv
        assert _ping_argv('ping.exe', '192.0.2.10', 3, 'win32') == \
            ['ping.exe', '-n', '1', '-w', '3000', '192.0.2.10']

    def test_macos_and_bsd(self):
        from watchfuls.ping.client import _ping_argv
        assert _ping_argv('/sbin/ping', '192.0.2.10', 2, 'darwin')[1:5] == ['-c', '1', '-t', '2']
        assert _ping_argv('/sbin/ping', '192.0.2.10', 2, 'freebsd13')[1:5] == ['-c', '1', '-t', '2']


class TestSystemPingFallback:
    """No raw socket, no datagram socket: the system ping is the last resort."""

    def test_no_icmp_socket_falls_back_to_the_system_ping(self):
        w = _watchful()
        res = subprocess.CompletedProcess([], 0, _LINUX_EN, '')
        with patch('watchfuls.ping.client._PYTHONPING_AVAILABLE', False), \
             patch.object(type(w), '_create_icmp_socket', return_value=None), \
             patch('watchfuls.ping.client.shutil.which', return_value='/bin/ping'), \
             patch('watchfuls.ping.client.sys.platform', 'linux'), \
             patch('watchfuls.ping.client.subprocess.run', return_value=res) as run:
            assert w._icmp_ping('127.0.0.1', 2) == pytest.approx(14.2)
        argv = run.call_args.args[0]
        assert isinstance(argv, list) and argv[0] == '/bin/ping' and argv[-1] == '127.0.0.1'
        assert run.call_args.kwargs.get('shell') is False
        assert run.call_args.kwargs.get('stdin') == subprocess.DEVNULL

    def test_a_non_address_never_reaches_the_command_line(self):
        """The fallback is fed the RESOLVED address and checks it: a value starting with
        '-' could otherwise be read by ping as an option."""
        from watchfuls.ping import Watchful
        with patch('watchfuls.ping.client.subprocess.run') as run, \
             patch('watchfuls.ping.client.shutil.which', return_value='/bin/ping'):
            assert Watchful._system_ping('-f', 1) is None
            assert Watchful._system_ping('--help 127.0.0.1', 1) is None
        run.assert_not_called()

    def test_a_timeout_of_the_binary_is_down(self):
        from watchfuls.ping import Watchful
        with patch('watchfuls.ping.client.shutil.which', return_value='/bin/ping'), \
             patch('watchfuls.ping.client.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('ping', 6)):
            assert Watchful._system_ping('192.0.2.10', 1) is None

    def test_no_ping_binary_raises_icmp_unavailable(self):
        from watchfuls.ping import Watchful
        from watchfuls.ping.client import IcmpUnavailable
        with patch('watchfuls.ping.client.shutil.which', return_value=None):
            with pytest.raises(IcmpUnavailable):
                Watchful._system_ping('192.0.2.10', 1)


class TestNoIcmpMessage:
    """With no way to send ICMP at all, the check names the cause instead of a bare DOWN."""

    def test_check_reports_icmp_not_permitted(self):
        w = _watchful({'h1': {'enabled': True, 'host': '127.0.0.1', 'alert': 1}})
        with patch('watchfuls.ping.client._PYTHONPING_AVAILABLE', False), \
             patch.object(type(w), '_create_icmp_socket', return_value=None), \
             patch('watchfuls.ping.client.shutil.which', return_value=None), \
             patch('watchfuls.ping.time.sleep'):
            items = w.check().list
        assert items['h1']['status'] is False
        assert items['h1']['message'] == w._msg('ping_no_icmp', '127.0.0.1')
        assert 'ICMP' in items['h1']['message']

    def test_up_with_unknown_rtt_carries_no_latency(self):
        from watchfuls.ping.client import RTT_UNKNOWN
        w = _watchful({'h1': {'enabled': True, 'host': '127.0.0.1'}})
        with patch.object(type(w), '_icmp_ping', return_value=RTT_UNKNOWN):
            items = w.check().list
        assert items['h1']['status'] is True
        assert 'latency_ms' not in (items['h1'].get('other_data') or {})

    def test_both_languages_carry_the_message(self):
        import json
        import os
        base = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0], 'lang')
        for f in ('en_EN.json', 'es_ES.json'):
            with open(os.path.join(base, f), encoding='utf-8') as fh:
                data = json.load(fh)
            assert 'ping_no_icmp' in data['messages'], f
            assert data['messages_vars']['ping_no_icmp'] == ['host'], f

