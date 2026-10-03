#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the syslog listener (UDP/TCP receive, framing, allowlist)."""

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from lib.services.syslog.server import SyslogServer, _parse_binds


class TestParseBinds:
    def test_blank_defaults_to_all_ipv4_and_ipv6(self):
        both = [(socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')]
        assert _parse_binds('') == both
        assert _parse_binds(None) == both

    def test_detects_family_and_multiple(self):
        out = _parse_binds('0.0.0.0, ::, 192.168.1.5, [fe80::1]')
        assert out == [
            (socket.AF_INET, '0.0.0.0'),
            (socket.AF_INET6, '::'),
            (socket.AF_INET, '192.168.1.5'),
            (socket.AF_INET6, 'fe80::1'),
        ]

    def test_dedup(self):
        assert _parse_binds('127.0.0.1 127.0.0.1') == [(socket.AF_INET, '127.0.0.1')]


def _free_port(proto: str = 'tcp') -> int:
    """A free port for *proto* (``'tcp'`` or ``'udp'``).

    Probe with the SAME socket type the caller will bind: the two port spaces are
    independent, so a number free for TCP can already be taken for UDP. Asking the wrong
    one is what made these tests fail under a full parallel run and pass on their own.
    """
    kind = socket.SOCK_DGRAM if proto == 'udp' else socket.SOCK_STREAM
    s = socket.socket(socket.AF_INET, kind)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Sink:
    def __init__(self):
        self.recs = []
        self._lock = threading.Lock()

    def __call__(self, batch):
        with self._lock:
            self.recs.extend(batch)

    def wait(self, n=1, timeout=4.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if len(self.recs) >= n:
                    return True
            time.sleep(0.05)
        return False


@pytest.fixture
def sink():
    return _Sink()


class TestUdp:
    def test_receive_udp(self, sink):
        port = _free_port('udp')
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', udp_port=port)
        assert srv.start() == []
        try:
            c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            c.sendto(b'<34>Oct 11 22:14:15 myhost su: failed', ('127.0.0.1', port))
            assert sink.wait(1)
            assert sink.recs[0]['app'] == 'su'
            assert sink.recs[0]['source'] == '127.0.0.1'
            assert sink.recs[0]['severity_name'] == 'crit'
        finally:
            srv.stop()

    def test_allowlist_blocks(self, sink):
        port = _free_port('udp')
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', udp_port=port,
                           allowed_sources=['10.0.0.0/8'])
        assert srv.start() == []
        try:
            c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            c.sendto(b'<13>kernel: boom', ('127.0.0.1', port))
            assert not sink.wait(1, timeout=1.5)      # 127.0.0.1 not allowed → dropped
            assert srv._drops.get('127.0.0.1', {}).get('count', 0) >= 1   # and counted
        finally:
            srv.stop()

    def test_drop_logging_counts_and_rate_limits(self):
        logs, drops = [], []
        srv = SyslogServer(sink=lambda *_a: None, bind_host='127.0.0.1',
                           allowed_sources=['10.0.0.0/8'],
                           dbg_warn=lambda m: logs.append(m),
                           on_drop=lambda s, tr, d: drops.append((s, tr, d)))
        srv._note_drop('1.2.3.4', 'UDP')
        srv._note_drop('1.2.3.4', 'UDP')   # within the window → counted, not re-logged/flushed
        assert srv._drops['1.2.3.4']['count'] == 2
        assert len(logs) == 1
        assert 'dropped UDP from 1.2.3.4' in logs[0] and 'not in allowed sources' in logs[0]
        assert drops == [('1.2.3.4', 'UDP', 1)]   # first flush delta = 1


class TestTcp:
    def test_newline_framing(self, sink):
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tcp_port=port)
        assert srv.start() == []
        try:
            c = socket.create_connection(('127.0.0.1', port), timeout=2)
            c.sendall(b'<13>kernel: boom\n<13>sshd: login\n')
            assert sink.wait(2)
            msgs = {r['message'] for r in sink.recs}
            assert msgs == {'boom', 'login'}
            c.close()
        finally:
            srv.stop()

    def test_octet_counted_framing(self, sink):
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tcp_port=port)
        assert srv.start() == []
        try:
            c = socket.create_connection(('127.0.0.1', port), timeout=2)
            frame = b'<13>app: hi'                    # 11 bytes
            c.sendall(b'%d %s' % (len(frame), frame))
            assert sink.wait(1)
            assert sink.recs[0]['message'] == 'hi' and sink.recs[0]['app'] == 'app'
            c.close()
        finally:
            srv.stop()


class TestLifecycle:
    def test_bind_failure_reported(self, sink):
        # Binding to an address not assigned to this host (TEST-NET-1, RFC 5737)
        # fails on every platform → start() reports the problem.
        srv = SyslogServer(sink=sink, bind_host='192.0.2.1', udp_port=51400)
        problems = srv.start()
        assert problems and 'UDP' in problems[0]
        assert srv.running is False
        srv.stop()

    def test_no_ports_no_threads(self, sink):
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1')   # nothing enabled
        assert srv.start() == []
        assert srv.running is False
        srv.stop()


class TestLoad:
    """Under fan-in load a real collector sees many devices connecting at once and
    streaming bursts.  TCP is a reliable stream, so *nothing* may be lost: every
    framed message must reach the sink exactly once.  (UDP is best-effort by design
    — see ``test_udp_burst_is_best_effort`` — so it gets a tolerant assertion.)"""

    def test_many_concurrent_connections_no_loss_tcp(self, sink):
        # 1000 devices connected at the same time, each streaming a few messages = 5000.
        # Phase 1 opens ALL sockets first (bounded to the listen backlog so we don't
        # self-inflict SYN drops), holding them open — so the server really holds 1000
        # live connections, one reader thread each, at once.  Phase 2 then streams on
        # all of them.  Nothing may be lost on TCP: the sink must receive every framed
        # message exactly once.
        conns, per_conn = 1000, 5
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tcp_port=port)
        assert srv.start() == []
        expected = {f'{k}-{i}' for k in range(conns) for i in range(per_conn)}
        socks: dict = {}
        errors: list = []
        lock = threading.Lock()

        def connect(k: int) -> None:
            for _ in range(20):                          # retry: listen backlog is finite
                try:
                    s = socket.create_connection(('127.0.0.1', port), timeout=10)
                    with lock:
                        socks[k] = s
                    return
                except OSError:
                    time.sleep(0.05)
            errors.append(f'conn {k}: could not connect')

        def stream(k: int, s: socket.socket) -> None:
            try:
                s.sendall(b''.join(b'<13>host%d: %d-%d\n' % (k, k, i) for i in range(per_conn)))
                s.close()
            except Exception as e:                       # pylint: disable=broad-except
                errors.append(f'conn {k}: {e!r}')

        try:
            # Phase 1: establish all 1000 connections, holding them open (workers capped
            # at the server's listen backlog so pending SYNs never overflow it).
            with ThreadPoolExecutor(max_workers=64) as pool:
                list(pool.map(connect, range(conns)))
            assert not errors, f'connect errors: {errors[:5]}'
            assert len(socks) == conns, f'only {len(socks)}/{conns} connections established'
            # Phase 2: 1000 connections are now live at once — stream on all of them.
            with ThreadPoolExecutor(max_workers=64) as pool:
                list(pool.map(lambda kv: stream(*kv), list(socks.items())))
            assert not errors, f'stream errors: {errors[:5]}'
            assert sink.wait(len(expected), timeout=60), \
                f'only {len(sink.recs)}/{len(expected)} messages received'
            got = [r['message'] for r in sink.recs]
            assert len(got) == len(expected)             # no loss AND no duplication
            assert set(got) == expected                  # exactly the messages sent
        finally:
            for s in socks.values():
                try:
                    s.close()
                except OSError:
                    pass
            srv.stop()

    def test_high_volume_single_connection_octet_counted_no_loss(self, sink):
        # One connection, 3000 octet-counted (RFC 6587) frames back-to-back —
        # exercises the framing path under volume; still zero loss on TCP.
        total = 3000
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tcp_port=port)
        assert srv.start() == []
        try:
            c = socket.create_connection(('127.0.0.1', port), timeout=10)
            chunks = []
            for i in range(total):
                frame = b'<13>vol: %d' % i
                chunks.append(b'%d %s' % (len(frame), frame))   # "<len> <frame>"
            c.sendall(b''.join(chunks))
            c.close()
            assert sink.wait(total, timeout=30), \
                f'only {len(sink.recs)}/{total} frames received'
            got = [r['message'] for r in sink.recs]
            assert len(got) == total
            assert set(got) == {str(i) for i in range(total)}
        finally:
            srv.stop()

    def test_udp_burst_is_best_effort(self, sink):
        # UDP has no delivery guarantee: a burst may lose datagrams at the OS
        # buffer, so we only assert the receiver survives the burst and still
        # delivers the bulk on loopback — NOT exact delivery (that would be flaky).
        burst = 500
        port = _free_port('udp')
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', udp_port=port)
        assert srv.start() == []
        try:
            c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for i in range(burst):
                c.sendto(b'<13>burst: %d' % i, ('127.0.0.1', port))
            c.close()
            assert sink.wait(burst // 2, timeout=15), \
                f'received only {len(sink.recs)}/{burst} (UDP is lossy, but expected the bulk)'
            assert srv.running is True                   # burst didn't take the listener down
        finally:
            srv.stop()


# ── connection bounds (handshake deadline, idle timeout, cap, prompt stop) ────────
@pytest.fixture(scope='module')
def tls_pair(tmp_path_factory):
    """A throwaway self-signed cert + key for the TLS listener."""
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'syslog-test')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(datetime.datetime(2020, 1, 1))
            .not_valid_after(datetime.datetime(2040, 1, 1))
            .sign(key, hashes.SHA256()))
    d = tmp_path_factory.mktemp('syslog-tls')
    cert_p, key_p = d / 'cert.pem', d / 'key.pem'
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_p.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    return str(cert_p), str(key_p)


def _closed_by_peer(sock: socket.socket, within: float) -> bool:
    """True when the server closes *sock* within *within* seconds (EOF or reset)."""
    sock.settimeout(within)
    try:
        return sock.recv(1) == b''
    except (ConnectionResetError, ConnectionAbortedError):
        return True
    except (socket.timeout, TimeoutError):
        return False


def _wait_until(pred, timeout=3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


class TestConnectionBounds:
    """An accepted TCP/TLS connection must never pin a thread for good: silent
    peers are closed, a TLS handshake has a deadline, the number of live
    connections is capped and stop() closes them instead of waiting on each."""

    def test_idle_plain_tcp_connection_is_closed(self, sink):
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tcp_port=port, idle_timeout=0.5)
        assert srv.start() == []
        c = socket.create_connection(('127.0.0.1', port), timeout=2)
        try:
            assert _closed_by_peer(c, within=4.0)
        finally:
            c.close()
            srv.stop()

    def test_active_tcp_connection_survives_idle_timeout(self, sink):
        # The idle clock restarts on every chunk: a sender that keeps talking stays.
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tcp_port=port, idle_timeout=0.8)
        assert srv.start() == []
        c = socket.create_connection(('127.0.0.1', port), timeout=2)
        try:
            for i in range(4):                       # 4 x 0.4 s > idle_timeout
                c.sendall(b'<13>app: tick%d\n' % i)
                time.sleep(0.4)
            assert sink.wait(4, timeout=3)
            assert {r['message'] for r in sink.recs} == {f'tick{i}' for i in range(4)}
        finally:
            c.close()
            srv.stop()

    def test_tls_handshake_has_a_deadline(self, sink, tls_pair):
        # A peer that connects to the TLS port and never says a word is dropped
        # once the handshake deadline passes (it used to block wrap_socket forever).
        cert, key = tls_pair
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tls_port=port,
                           tls_cert=cert, tls_key=key, handshake_timeout=0.5)
        assert srv.start() == []
        c = socket.create_connection(('127.0.0.1', port), timeout=2)
        try:
            assert _closed_by_peer(c, within=4.0)
        finally:
            c.close()
            srv.stop()

    def test_tls_message_still_received(self, sink, tls_pair):
        import ssl
        cert, key = tls_pair
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tls_port=port,
                           tls_cert=cert, tls_key=key)
        assert srv.start() == []
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
                with ctx.wrap_socket(raw) as c:
                    c.sendall(b'<13>secure: over tls\n')
                    assert sink.wait(1, timeout=3)
            assert sink.recs[0]['message'] == 'over tls'
        finally:
            srv.stop()

    def test_connection_cap_refuses_extra_and_frees_on_close(self, sink):
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tcp_port=port, max_connections=2)
        assert srv.start() == []
        c1 = socket.create_connection(('127.0.0.1', port), timeout=2)
        c2 = socket.create_connection(('127.0.0.1', port), timeout=2)
        extra = []
        try:
            assert _wait_until(lambda: len(srv._conns) == 2)
            c3 = socket.create_connection(('127.0.0.1', port), timeout=2)
            extra.append(c3)
            assert _closed_by_peer(c3, within=3.0)          # over the cap → closed
            c2.sendall(b'<13>app: kept\n')                  # the admitted ones still work
            assert sink.wait(1, timeout=3)
            c1.close()                                      # a slot frees on disconnect
            assert _wait_until(lambda: len(srv._conns) == 1)
            c4 = socket.create_connection(('127.0.0.1', port), timeout=2)
            extra.append(c4)
            c4.sendall(b'<13>app: after\n')
            assert sink.wait(2, timeout=3)
            assert {r['message'] for r in sink.recs} == {'kept', 'after'}
        finally:
            for s in (c1, c2, *extra):
                s.close()
            srv.stop()

    def test_stop_closes_live_connections_promptly(self, sink, tls_pair):
        # Three silent TLS peers used to block in the handshake: stop() waited 2 s on
        # each (6 s, under the caller's listener lock) and the threads survived it.
        cert, key = tls_pair
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tls_port=port,
                           tls_cert=cert, tls_key=key)
        assert srv.start() == []
        clients = [socket.create_connection(('127.0.0.1', port), timeout=2) for _ in range(3)]
        try:
            assert _wait_until(lambda: len(srv._conns) == 3)
            conn_threads = [t for t in list(srv._threads) if t.name == 'syslog-conn']
            assert len(conn_threads) == 3
            t0 = time.monotonic()
            srv.stop()
            assert time.monotonic() - t0 < 1.5
            assert not any(t.is_alive() for t in conn_threads)
            assert not srv._conns
        finally:
            for c in clients:
                c.close()
            srv.stop()
