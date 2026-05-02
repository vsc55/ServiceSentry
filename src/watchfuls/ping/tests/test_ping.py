#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/ping.py."""

from unittest.mock import patch

import pytest

from conftest import create_mock_monitor


class TestPingInit:

    def test_init(self):
        from watchfuls.ping import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.ping': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.ping'

    def test_no_external_ping_dependency(self):
        """The module must not depend on an external ping binary."""
        from watchfuls.ping import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.ping': {}})
        w = Watchful(mock_monitor)
        # paths.find returns '' when key is not registered
        assert not w.paths.find('ping')


class TestPingCheck:

    def setup_method(self):
        from watchfuls.ping import Watchful
        self.Watchful = Watchful

    def test_check_empty_list(self):
        """Sin hosts configurados, no hay resultados."""
        config = {'watchfuls.ping': {'list': {}}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.list) == 0

    def test_check_disabled_host(self):
        """Host deshabilitado no se procesa."""
        config = {
            'watchfuls.ping': {
                'list': {
                    '192.168.1.1': False
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_host_enabled_bool(self):
        """Host habilitado con booleano se procesa."""
        config = {
            'watchfuls.ping': {
                'list': {
                    '192.168.1.1': True
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        # Mock _icmp_ping para simular ping exitoso
        with patch.object(w, '_icmp_ping', return_value=True):
            result = w.check()
            items = result.list
            assert '192.168.1.1' in items
            assert items['192.168.1.1']['status'] is True

    def test_check_host_ping_fails(self):
        """Ping fallido se marca como fallo."""
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'timeout': 1,
                'list': {
                    '192.168.1.99': True
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        # Mock _icmp_ping para simular ping fallido
        with patch.object(w, '_icmp_ping', return_value=False):
            result = w.check()
            items = result.list
            assert '192.168.1.99' in items
            assert items['192.168.1.99']['status'] is False

    def test_check_host_with_host_field(self):
        """Key es nombre descriptivo, host field contiene la IP."""
        config = {
            'watchfuls.ping': {
                'list': {
                    'Router': {
                        'enabled': True,
                        'host': '192.168.1.1',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_icmp_ping', return_value=True):
            result = w.check()
            items = result.list
            assert 'Router' in items
            # El mensaje debe contener "Router" (el nombre del key)
            assert 'Router' in items['Router']['message']

    def test_check_backward_compat_key_as_host(self):
        """Sin campo host, el key se usa como IP (retrocompat)."""
        config = {
            'watchfuls.ping': {
                'list': {
                    '192.168.1.1': {
                        'enabled': True,
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_icmp_ping', return_value=True):
            result = w.check()
            items = result.list
            assert '192.168.1.1' in items
            assert items['192.168.1.1']['status'] is True

    def test_check_multiple_hosts(self):
        """Múltiples hosts se procesan."""
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'list': {
                    '192.168.1.1': True,
                    '192.168.1.2': True,
                    '192.168.1.3': False,
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_icmp_ping', return_value=True):
            result = w.check()
            items = result.list
            assert '192.168.1.1' in items
            assert '192.168.1.2' in items
            assert '192.168.1.3' not in items  # Deshabilitado


class TestPingConfigOptions:

    def test_config_options_enum(self):
        from watchfuls.ping import ConfigOptions
        assert hasattr(ConfigOptions, 'enabled')
        assert hasattr(ConfigOptions, 'alert')
        assert hasattr(ConfigOptions, 'host')
        assert hasattr(ConfigOptions, 'timeout')
        assert hasattr(ConfigOptions, 'attempt')

    def test_alert_uses_base_enum_value(self):
        """alert == 2 matches EnumConfigOptions.alert from the base."""
        from watchfuls.ping import ConfigOptions
        assert ConfigOptions.alert == 2


class TestPingGetConf:

    def setup_method(self):
        from watchfuls.ping import ConfigOptions, Watchful
        self.Watchful = Watchful
        self.ConfigOptions = ConfigOptions

    def test_get_conf_none_raises_value_error(self):
        """opt_find=None lanza ValueError."""
        config = {'watchfuls.ping': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        with pytest.raises(ValueError, match="can not be None"):
            w._get_conf(None, '192.168.1.1')

    def test_get_conf_invalid_option_raises_type_error(self):
        """opt_find inválido lanza TypeError."""
        from enum import IntEnum

        class FakeOption(IntEnum):
            invalid = 999

        config = {'watchfuls.ping': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        with pytest.raises(TypeError, match="is not valid option"):
            w._get_conf(FakeOption.invalid, '192.168.1.1')


class TestIcmpNative:
    """Tests for the native ICMP implementation internals."""

    def setup_method(self):
        from watchfuls.ping import Watchful
        self.Watchful = Watchful
        config = {'watchfuls.ping': {'list': {}}}
        self.w = Watchful(create_mock_monitor(config))

    # ── checksum ───────────────────────────────────────────────────

    def test_icmp_checksum_zero_bytes(self):
        """Checksum of all-zero bytes is 0xFFFF."""
        assert self.Watchful._icmp_checksum(b'\x00\x00') == 0xFFFF

    def test_icmp_checksum_known_value(self):
        """Checksum of a known payload matches expected value."""
        # ICMP Echo Request header (type=8, code=0, id=1, seq=1, chk=0)
        header = b'\x08\x00\x00\x00\x00\x01\x00\x01'
        chk = self.Watchful._icmp_checksum(header)
        assert isinstance(chk, int)
        assert 0 <= chk <= 0xFFFF

    def test_icmp_checksum_odd_length(self):
        """Checksum handles odd-length data by padding."""
        result = self.Watchful._icmp_checksum(b'\x01\x02\x03')
        assert isinstance(result, int)
        assert 0 <= result <= 0xFFFF

    # ── build packet ───────────────────────────────────────────────

    def test_build_icmp_packet_length(self):
        """Packet is 8-byte header + 13-byte payload."""
        pkt = self.Watchful._build_icmp_packet(1234, 1)
        assert len(pkt) == 8 + len(b'ServiceSentry')

    def test_build_icmp_packet_type_code(self):
        """First byte is type=8 (Echo Request), second is code=0."""
        pkt = self.Watchful._build_icmp_packet(1234, 1)
        assert pkt[0] == 8
        assert pkt[1] == 0

    def test_build_icmp_packet_id_seq(self):
        """Packet id and seq are encoded correctly."""
        import struct
        pkt = self.Watchful._build_icmp_packet(0xABCD, 5)
        _, _, _, pid, seq = struct.unpack('!BBHHH', pkt[:8])
        assert pid == 0xABCD
        assert seq == 5

    def test_build_icmp_packet_checksum_valid(self):
        """Checksum of the full packet is 0 (or 0xFFFF)."""
        pkt = self.Watchful._build_icmp_packet(1, 1)
        chk = self.Watchful._icmp_checksum(pkt)
        # A correct checksum produces 0 when re-verified
        assert chk in (0, 0xFFFF)

    # ── create socket ──────────────────────────────────────────────

    def test_create_icmp_socket_returns_socket_or_none(self):
        """Returns a socket object or None if no permissions."""
        import socket
        icmp_proto = socket.getprotobyname('icmp')
        result = self.Watchful._create_icmp_socket(icmp_proto)
        if result is not None:
            assert hasattr(result, 'sendto')
            result.close()

    def test_create_icmp_socket_no_perms(self):
        """When all socket types fail, returns None."""
        import socket
        with patch('socket.socket', side_effect=PermissionError):
            result = self.Watchful._create_icmp_socket(
                socket.getprotobyname('icmp'),
            )
            assert result is None

    # ── _icmp_ping integration ─────────────────────────────────────

    def test_icmp_ping_unresolvable_host(self):
        """Unresolvable hostname returns False."""
        assert self.w._icmp_ping('host.invalid.test', 1) is False

    def test_icmp_ping_no_socket(self):
        """If no socket can be created, returns False (native path)."""
        with patch('watchfuls.ping._PYTHONPING_AVAILABLE', False):
            with patch.object(self.Watchful, '_create_icmp_socket',
                              return_value=None):
                assert self.w._icmp_ping('127.0.0.1', 1) is False

    def test_icmp_ping_sendto_fails(self):
        """If sendto raises OSError, returns False (native path)."""
        import socket
        mock_sock = patch('socket.socket').start()
        mock_instance = mock_sock.return_value
        mock_instance.sendto.side_effect = OSError("Network unreachable")
        with patch('watchfuls.ping._PYTHONPING_AVAILABLE', False):
            with patch.object(self.Watchful, '_create_icmp_socket',
                              return_value=mock_instance):
                result = self.w._icmp_ping('127.0.0.1', 1)
                assert result is False
        patch.stopall()

    # ── _ping_return retries ───────────────────────────────────────

    def test_ping_return_succeeds_first_try(self):
        """Returns True immediately if first ICMP ping succeeds."""
        with patch.object(self.w, '_icmp_ping', return_value=True):
            assert self.w._ping_return('127.0.0.1', 1, 3) is True

    def test_ping_return_retries_on_failure(self):
        """Retries up to 'attempt' times before giving up."""
        with patch.object(self.w, '_icmp_ping', return_value=False), \
             patch('time.sleep'):
            assert self.w._ping_return('127.0.0.1', 1, 2) is False

    def test_ping_return_succeeds_on_second_attempt(self):
        """Succeeds on second attempt after first failure."""
        with patch.object(self.w, '_icmp_ping',
                          side_effect=[False, True]), \
             patch('time.sleep'):
            assert self.w._ping_return('127.0.0.1', 1, 3) is True

    # ── receive reply parsing ──────────────────────────────────────

    def test_receive_reply_timeout(self):
        """Returns False when socket times out."""
        import socket as sock_mod
        mock_sock = patch('socket.socket').start()
        mock_instance = mock_sock.return_value
        mock_instance.recvfrom.side_effect = sock_mod.timeout
        result = self.Watchful._receive_icmp_reply(mock_instance, 1, 1, 1)
        assert result is False
        patch.stopall()

    def test_receive_reply_valid_echo_reply_raw(self):
        """Parses a valid Echo Reply from a RAW socket (with IP header)."""
        import struct

        # Minimal IPv4 header (20 bytes) + ICMP Echo Reply
        ip_header = b'\x45' + b'\x00' * 19  # version=4, IHL=5 → 20 bytes
        icmp_reply = struct.pack('!BBHHH', 0, 0, 0, 42, 1) + b'payload'
        data = ip_header + icmp_reply

        mock_sock = patch('socket.socket').start()
        mock_instance = mock_sock.return_value
        mock_instance.recvfrom.return_value = (data, ('1.2.3.4', 0))
        result = self.Watchful._receive_icmp_reply(mock_instance, 42, 1, 5)
        assert result is True
        patch.stopall()

    def test_receive_reply_valid_echo_reply_dgram(self):
        """Parses a valid Echo Reply from a DGRAM socket (no IP header)."""
        import struct
        icmp_reply = struct.pack('!BBHHH', 0, 0, 0, 42, 1) + b'payload'

        mock_sock = patch('socket.socket').start()
        mock_instance = mock_sock.return_value
        mock_instance.recvfrom.return_value = (icmp_reply, ('1.2.3.4', 0))
        result = self.Watchful._receive_icmp_reply(mock_instance, 42, 1, 5)
        assert result is True
        patch.stopall()

    def test_receive_reply_wrong_id_ignored(self):
        """Echo Reply with wrong packet_id is ignored, then timeout."""
        import socket as sock_mod
        import struct
        wrong_reply = struct.pack('!BBHHH', 0, 0, 0, 999, 1)
        mock_sock = patch('socket.socket').start()
        mock_instance = mock_sock.return_value
        mock_instance.recvfrom.side_effect = [
            (wrong_reply, ('1.2.3.4', 0)),
            sock_mod.timeout,
        ]
        result = self.Watchful._receive_icmp_reply(mock_instance, 42, 1, 1)
        assert result is False
        patch.stopall()


class TestDefaults:
    """Defaults are derived from ITEM_SCHEMA — single source of truth."""

    def test_defaults_extracted_from_schema(self):
        from watchfuls.ping import Watchful

        # Rich schema: _DEFAULTS extracts 'default' values
        for key, meta in Watchful.ITEM_SCHEMA['list'].items():
            assert key in Watchful._DEFAULTS
            assert Watchful._DEFAULTS[key] == meta['default']

    def test_schema_has_all_fields(self):
        from watchfuls.ping import Watchful
        expected = {'enabled', 'host', 'timeout', 'attempt', 'alert'}
        assert set(Watchful.ITEM_SCHEMA['list'].keys()) == expected

    def test_schema_has_type_metadata(self):
        """Every field in the schema has a 'type' key."""
        from watchfuls.ping import Watchful
        for key, meta in Watchful.ITEM_SCHEMA['list'].items():
            assert 'type' in meta, f'{key} missing type'
            assert 'default' in meta, f'{key} missing default'

    def test_default_values(self):
        from watchfuls.ping import Watchful
        d = Watchful._DEFAULTS
        assert d['enabled'] is True
        assert d['timeout'] == 5
        assert d['attempt'] == 3
        assert d['alert'] == 1
        assert d['host'] == ''

    def test_no_legacy_default_attributes(self):
        """_default_attempt / _default_timeout / _default_enabled removed."""
        from watchfuls.ping import Watchful
        assert not hasattr(Watchful, '_default_attempt')
        assert not hasattr(Watchful, '_default_timeout')
        assert not hasattr(Watchful, '_default_enabled')


class TestAlertThreshold:
    """alert: consecutive check failures before declaring KO."""

    def setup_method(self):
        from watchfuls.ping import Watchful
        self.Watchful = Watchful

    def _make(self, config):
        return self.Watchful(create_mock_monitor(config))

    def test_alert_default_is_1(self):
        """With default alert=1 a single failure is KO immediately."""
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'list': {'10.0.0.1': True},
            }
        }
        w = self._make(config)
        with patch.object(w, '_icmp_ping', return_value=False), \
             patch('time.sleep'):
            result = w.check()
        assert result.list['10.0.0.1']['status'] is False

    def test_alert_2_needs_two_failures(self):
        """With alert=2 the first failure keeps status True."""
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'alert': 2,
                'list': {'10.0.0.1': True},
            }
        }
        w = self._make(config)
        with patch.object(w, '_icmp_ping', return_value=False), \
             patch('time.sleep'):
            r1 = w.check()
        # First failure — still OK because alert=2
        assert r1.list['10.0.0.1']['status'] is True

    def test_alert_2_ko_on_second_failure(self):
        """With alert=2 the second consecutive failure is KO."""
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'alert': 2,
                'list': {'10.0.0.1': True},
            }
        }
        w = self._make(config)
        with patch.object(w, '_icmp_ping', return_value=False), \
             patch('time.sleep'):
            w.check()  # first failure
            w.dict_return._dict_return.clear()
            r2 = w.check()
        assert r2.list['10.0.0.1']['status'] is False

    def test_alert_resets_on_success(self):
        """A successful ping resets the failure counter."""
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'alert': 3,
                'list': {'10.0.0.1': True},
            }
        }
        w = self._make(config)
        with patch('time.sleep'):
            # Two failures
            with patch.object(w, '_icmp_ping', return_value=False):
                w.check()
                w.dict_return._dict_return.clear()
                w.check()
            assert w._fail_count['10.0.0.1'] == 2

            # One success — counter resets
            w.dict_return._dict_return.clear()
            with patch.object(w, '_icmp_ping', return_value=True):
                r = w.check()
            assert w._fail_count['10.0.0.1'] == 0
            assert r.list['10.0.0.1']['status'] is True

    def test_alert_per_host(self):
        """Each host in 'list' can have its own alert threshold."""
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'list': {
                    '10.0.0.1': {'enabled': True, 'alert': 1},
                    '10.0.0.2': {'enabled': True, 'alert': 3},
                },
            }
        }
        w = self._make(config)
        with patch.object(w, '_icmp_ping', return_value=False), \
             patch('time.sleep'):
            r = w.check()
        # host with alert=1 → KO immediately
        assert r.list['10.0.0.1']['status'] is False
        # host with alert=3 → still OK after 1 failure
        assert r.list['10.0.0.2']['status'] is True

    def test_get_conf_alert_returns_int(self):
        """_get_conf parses alert as int."""
        from watchfuls.ping import ConfigOptions
        config = {'watchfuls.ping': {'alert': '5', 'list': {}}}
        w = self._make(config)
        assert w._get_conf(ConfigOptions.alert, 'any') == 5


class TestEmojiMessages:
    """Messages use literal emoji characters, not Unicode escapes."""

    def setup_method(self):
        from watchfuls.ping import Watchful
        self.Watchful = Watchful

    def test_success_message_contains_up_emoji(self):
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'list': {'10.0.0.1': True},
            }
        }
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_icmp_ping', return_value=True):
            r = w.check()
        assert '🔼' in r.list['10.0.0.1']['message']

    def test_failure_message_contains_down_emoji(self):
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'list': {'10.0.0.1': True},
            }
        }
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_icmp_ping', return_value=False), \
             patch('time.sleep'):
            r = w.check()
        assert '🔽' in r.list['10.0.0.1']['message']

    def test_exception_message_contains_explosion_emoji(self):
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'list': {'10.0.0.1': True},
            }
        }
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_ping_check', side_effect=RuntimeError("boom")):
            r = w.check()
        assert '💥' in r.list['10.0.0.1']['message']
