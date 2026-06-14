#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/ssl_cert.

The TLS handshake validates chain + hostname (SNI) + expiry via the default
context; expiry days are read from the peer certificate (DER, parsed with
``cryptography``).  Here the socket/context are mocked and ``_cert_expiry`` is
stubbed so no real network or parsing happens.
"""

import ssl
import time
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

from conftest import create_mock_monitor


@contextmanager
def _mock_tls(expiry_ts):
    """Mock the TLS connection; capture the created context for assertions."""
    from watchfuls.ssl_cert import Watchful
    ssock = MagicMock()
    ssock.getpeercert.return_value = b'DER'
    ssock.__enter__ = lambda s: s
    ssock.__exit__ = MagicMock(return_value=False)
    sock = MagicMock()
    sock.__enter__ = lambda s: s
    sock.__exit__ = MagicMock(return_value=False)
    ctx = MagicMock()
    ctx.wrap_socket.return_value = ssock
    with patch('watchfuls.ssl_cert.socket.create_connection', return_value=sock) as conn, \
         patch('watchfuls.ssl_cert.ssl.create_default_context', return_value=ctx), \
         patch.object(Watchful, '_cert_expiry',
                      return_value=(expiry_ts, '2030-01-01 00:00:00 UTC')):
        yield {'ctx': ctx, 'conn': conn, 'wrap': ctx.wrap_socket}


def _w(items, module=None):
    from watchfuls.ssl_cert import Watchful
    cfg = {'warning_days': 30, **(module or {}), 'list': items}
    return Watchful(create_mock_monitor({'watchfuls.ssl_cert': cfg}))


class TestSslCertCheck:

    def test_disabled_module_empty(self):
        assert len(_w({}, {'enabled': False}).check().items()) == 0

    def test_disabled_item_skipped(self):
        w = _w({'a': {'enabled': False, 'host': 'example.com'}})
        assert len(w.check().items()) == 0

    def test_valid_ok(self):
        w = _w({'example.com': {'enabled': True, 'host': 'example.com', 'port': 443}})
        with _mock_tls(time.time() + 60 * 86400):
            items = w.check().list
        assert items['example.com']['status'] is True

    def test_within_warning_window(self):
        w = _w({'example.com': {'enabled': True, 'host': 'example.com'}})
        with _mock_tls(time.time() + 10 * 86400):
            items = w.check().list
        assert items['example.com']['status'] is False
        assert 'warning threshold' in items['example.com']['message']

    def test_expired(self):
        w = _w({'example.com': {'enabled': True, 'host': 'example.com'}})
        with _mock_tls(time.time() - 5 * 86400):
            items = w.check().list
        assert items['example.com']['status'] is False
        assert 'EXPIRED' in items['example.com']['message']

    def test_connection_error_handled(self):
        w = _w({'example.com': {'enabled': True, 'host': 'example.com'}})
        with patch('watchfuls.ssl_cert.socket.create_connection',
                   side_effect=ConnectionRefusedError('refused')):
            items = w.check().list
        assert items['example.com']['status'] is False
        assert 'Error' in items['example.com']['message']

    def test_per_item_warning_days_overrides_module(self):
        w = _w({'example.com': {'enabled': True, 'host': 'example.com', 'warning_days': 10}})
        with _mock_tls(time.time() + 20 * 86400):
            items = w.check().list
        assert items['example.com']['status'] is True   # 20 > per-item 10

    def test_sni_uses_server_name_not_address(self):
        # Connect to the address, but send the FQDN as SNI / validate against it.
        w = _w({'proxy': {'enabled': True, 'host': '10.0.0.9',
                          'server_name': 'app.example.com', 'port': 8443}})
        with _mock_tls(time.time() + 60 * 86400) as m:
            items = w.check().list
        assert m['conn'].call_args.args[0] == ('10.0.0.9', 8443)         # connect to address
        assert m['wrap'].call_args.kwargs['server_hostname'] == 'app.example.com'  # SNI = FQDN
        od = items['proxy']['other_data']
        assert od['server_name'] == 'app.example.com' and od['verify'] is True

    def test_sni_defaults_to_address(self):
        w = _w({'h': {'enabled': True, 'host': 'example.com'}})
        with _mock_tls(time.time() + 60 * 86400) as m:
            w.check()
        assert m['wrap'].call_args.kwargs['server_hostname'] == 'example.com'

    def test_verify_off_uses_insecure_context(self):
        w = _w({'self': {'enabled': True, 'host': 'example.com', 'verify': False}})
        with _mock_tls(time.time() + 60 * 86400) as m:
            items = w.check().list
        assert m['ctx'].check_hostname is False
        assert m['ctx'].verify_mode == ssl.CERT_NONE
        assert items['self']['status'] is True
        assert items['self']['other_data']['verify'] is False

    def test_verify_on_uses_default_context(self):
        w = _w({'h': {'enabled': True, 'host': 'example.com', 'verify': True}})
        with _mock_tls(time.time() + 60 * 86400) as m:
            w.check()
        # Default context left intact (no insecure downgrade).
        assert m['ctx'].verify_mode != ssl.CERT_NONE


class TestCertExpiry:
    """The DER parser returns a real expiry from a generated certificate."""

    def test_parses_generated_cert(self):
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError:
            import pytest
            pytest.skip('cryptography not installed')
        import datetime
        from watchfuls.ssl_cert import Watchful
        key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        not_after = datetime.datetime(2031, 6, 1, tzinfo=datetime.timezone.utc)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'x')])
        cert = (x509.CertificateBuilder()
                .subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(1)
                .not_valid_before(datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc))
                .not_valid_after(not_after)
                .sign(key, hashes.SHA256()))
        from cryptography.hazmat.primitives.serialization import Encoding
        ts, s = Watchful._cert_expiry(cert.public_bytes(Encoding.DER))
        assert abs(ts - not_after.timestamp()) < 2
        assert s.startswith('2031-06-01')
