#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Ping watchful: speaking ICMP.
#
"""Echo request, echo reply, and the socket that carries them.

Written by hand rather than shelling out to the system ``ping``: parsing another program's
localised, per-platform output to learn a round-trip time is a worse contract than building
the packet ourselves. The cost is that a raw socket needs privilege; without it the
unprivileged datagram ICMP socket is tried, and only when neither opens is the system
``ping`` called (as an argument list, never a shell) and judged by its exit code.

A check decides what a lost packet MEANS - how many attempts, which threshold. This decides
how to send one and how to recognise the answer as ours: the reply carries the identifier and
sequence we put in, and a reply that matches neither belongs to somebody else's ping.
"""

import concurrent.futures
import ipaddress
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import time

# A convenience library, not a requirement: the native implementation below is the one that
# always works, and MISSING_DEPS stays empty because its absence costs nothing.
try:
    from pythonping import ping as _pythonping
    _PYTHONPING_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYTHONPING_AVAILABLE = False


# A reply whose round-trip time the system ``ping`` printed in a form we could not read: the
# host answered, the latency is unknown. Negative so it can never pass for a measurement.
RTT_UNKNOWN = -1.0

# The round-trip time in a system ``ping`` line, in any locale: the word before it changes
# (time / tiempo / Zeit / temps…) but the shape does not — ``=`` or ``<``, a number, then
# ``ms`` (Spanish Windows prints a bare ``m``: "tiempo<1m"). ``bytes=32 `` and ``ttl=117 ``
# are not followed by an ``m``, so they never match.
_RTT_RE = re.compile(r'[=<]\s*(\d+(?:[.,]\d+)?)\s*ms?(?![a-z])', re.IGNORECASE)


class IcmpUnavailable(OSError):
    """No way to send ICMP from this process: no raw socket, no unprivileged datagram
    socket, and no system ``ping`` binary to delegate to. A configuration problem of the
    host running the check — not a verdict on the host being checked."""


def _ping_argv(binary: str, dest: str, timeout: int, platform: str | None = None) -> list:
    """The system ``ping`` command for one echo to *dest*, as an argument list.

    Per platform because the flags are not portable: Windows counts with ``-n`` and waits
    with ``-w`` in milliseconds; Linux (iputils, busybox) waits with ``-W`` in seconds;
    macOS and the BSDs use ``-t`` for the overall timeout in seconds.
    """
    platform = platform or sys.platform
    t = max(1, int(timeout))
    if platform.startswith('win'):
        return [binary, '-n', '1', '-w', str(t * 1000), dest]
    if platform.startswith('linux'):
        return [binary, '-c', '1', '-W', str(t), dest]
    return [binary, '-c', '1', '-t', str(t), dest]


def _parse_ping_output(out: str, code: int, platform: str | None = None) -> float | None:
    """Read a system ``ping`` answer: RTT in ms, ``RTT_UNKNOWN`` when up but unreadable,
    ``None`` when down.

    The verdict comes from the exit code, which does not depend on the locale. Windows is
    the exception: its ``ping`` exits 0 when a ROUTER answers "Destination host
    unreachable", so there the reply must also carry ``TTL=`` — the one token every
    Windows locale prints on a genuine echo reply.
    """
    platform = platform or sys.platform
    out = out or ''
    if code != 0:
        return None
    if platform.startswith('win') and 'ttl=' not in out.lower():
        return None
    m = _RTT_RE.search(out)
    if not m:
        return RTT_UNKNOWN
    try:
        return float(m.group(1).replace(',', '.'))
    except ValueError:
        return RTT_UNKNOWN


class IcmpClient:
    """The native ICMP implementation, mixed into ``Watchful``."""

    # ── System ping (last resort) ─────────────────────────────────

    @staticmethod
    def _system_ping(dest: str, timeout: int) -> float | None:
        """One echo through the system ``ping`` binary, for a process with no ICMP socket.

        The setuid / capability-bearing ``ping`` can send what this process may not. *dest*
        must already be a resolved IP address: that is checked here, so nothing that starts
        with ``-`` can ever reach the command line as an option, and there is no shell.
        Raises :class:`IcmpUnavailable` when there is no ``ping`` binary either.
        """
        try:
            ipaddress.ip_address(dest)
        except ValueError:
            return None
        binary = shutil.which('ping')
        if not binary:
            raise IcmpUnavailable('no ICMP socket and no system ping binary')
        argv = _ping_argv(binary, dest, timeout)
        try:
            res = subprocess.run(argv, shell=False, capture_output=True,  # noqa: S603
                                 stdin=subprocess.DEVNULL, text=True, errors='replace',
                                 timeout=max(1, int(timeout)) + 5, check=False)
        except subprocess.TimeoutExpired:
            return None
        except OSError as exc:
            raise IcmpUnavailable(str(exc)) from exc
        return _parse_ping_output(res.stdout, res.returncode)

    # ── Native ICMP implementation ────────────────────────────────

    @staticmethod
    def _icmp_checksum(data: bytes) -> int:
        """Calculate the Internet checksum (RFC 1071)."""
        if len(data) % 2:
            data += b'\x00'
        s = 0
        for i in range(0, len(data), 2):
            w = (data[i] << 8) + data[i + 1]
            s += w
        s = (s >> 16) + (s & 0xFFFF)
        s += s >> 16
        return ~s & 0xFFFF

    def _icmp_ping(self, host: str, timeout: int) -> float | None:
        """Send a single ICMP Echo Request and wait for a reply.

        Uses ``pythonping`` when available (cross-platform, no root needed
        on Windows).  Falls back to a native ICMP socket implementation
        when ``pythonping`` is not installed: tries ``SOCK_RAW`` first
        (requires elevated privileges) and then ``SOCK_DGRAM`` (allowed
        on many Linux distributions for unprivileged users).

        Returns RTT in milliseconds on success, or ``None`` on failure.
        """
        if _PYTHONPING_AVAILABLE:
            try:
                result = _pythonping(host, timeout=timeout, count=1, verbose=False)
                if result.success():
                    return result.rtt_avg_ms
                return None
            except PermissionError:
                # pythonping only speaks SOCK_RAW: without root/CAP_NET_RAW it refuses every
                # host, and every host came out DOWN. The native path below can still use an
                # unprivileged SOCK_DGRAM ICMP socket where the kernel allows it.
                pass
            except Exception:  # pylint: disable=broad-except
                return None
        # Native ICMP (pythonping absent, or refused for lack of privilege)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
                _fut = _ex.submit(socket.gethostbyname, host)
                dest = _fut.result(timeout=timeout)
        except (socket.gaierror, concurrent.futures.TimeoutError):
            return None

        icmp_proto = socket.getprotobyname('icmp')
        sock = self._create_icmp_socket(icmp_proto)
        if sock is None:
            # Neither a raw nor an unprivileged datagram ICMP socket: without this every host
            # came out DOWN, all of them for the same reason that had nothing to do with them.
            # The system ping usually carries the privilege this process lacks.
            return self._system_ping(dest, timeout)

        try:
            sock.settimeout(timeout)
            packet_id = secrets.randbits(16)
            seq = 1
            packet = self._build_icmp_packet(packet_id, seq)
            t0 = time.monotonic()
            sock.sendto(packet, (dest, 0))
            if self._receive_icmp_reply(sock, packet_id, seq, timeout):
                return (time.monotonic() - t0) * 1000
            return None
        except (OSError, socket.error):
            return None
        finally:
            sock.close()

    @staticmethod
    def _create_icmp_socket(icmp_proto: int):
        """Create an ICMP socket, trying RAW first, then DGRAM."""
        for sock_type in (socket.SOCK_RAW, socket.SOCK_DGRAM):
            try:
                return socket.socket(
                    socket.AF_INET, sock_type, icmp_proto,
                )
            except PermissionError:
                continue
            except OSError:
                continue
        return None

    @staticmethod
    def _build_icmp_packet(packet_id: int, seq: int) -> bytes:
        """Build an ICMP Echo Request packet."""
        # Type 8, Code 0 = Echo Request
        icmp_type = 8
        icmp_code = 0
        checksum = 0
        payload = b'ServiceSentry'  # arbitrary payload

        # Header with dummy checksum
        header = struct.pack('!BBHHH', icmp_type, icmp_code, checksum, packet_id, seq)
        # Calculate real checksum
        checksum = IcmpClient._icmp_checksum(header + payload)
        header = struct.pack('!BBHHH', icmp_type, icmp_code, checksum, packet_id, seq)
        return header + payload

    @staticmethod
    def _receive_icmp_reply(sock, packet_id: int, seq: int, timeout: int) -> bool:
        """Wait for the matching ICMP Echo Reply."""
        dgram = getattr(sock, 'type', None) == socket.SOCK_DGRAM
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(1024)
            except (socket.timeout, OSError):
                return False

            # Determine where the ICMP header starts.
            # RAW sockets include the IP header (usually 20 bytes),
            # DGRAM sockets strip it.
            if len(data) >= 28 and (data[0] >> 4) == 4:
                # IPv4 header present — extract IHL
                ip_hdr_len = (data[0] & 0x0F) * 4
                icmp_data = data[ip_hdr_len:]
            else:
                icmp_data = data

            if len(icmp_data) < 8:
                continue

            icmp_type, icmp_code, _, recv_id, recv_seq = struct.unpack(
                '!BBHHH', icmp_data[:8],
            )
            # Type 0 = Echo Reply
            if icmp_type == 0 and icmp_code == 0:
                # On an unprivileged SOCK_DGRAM ICMP socket (Linux ping_group_range) the
                # kernel REWRITES the identifier to the socket's own port and hands this
                # socket only the replies to it — so the id we chose never comes back and
                # demanding it made every reply "somebody else's". The kernel did the
                # matching; the sequence is still ours to check.
                if recv_seq == seq and (dgram or recv_id == packet_id):
                    return True