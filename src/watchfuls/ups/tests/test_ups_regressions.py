#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/ups found by the 2026-10-12 audit."""

from unittest.mock import MagicMock, patch

import pytest

from conftest import create_mock_monitor

import watchfuls.ups as ups_module


def _query_capturing(user, password):
    """Run _nut_query against a fake upsd and return what was written to it."""
    written = []
    f = MagicMock()
    f.write.side_effect = written.append
    f.readline.side_effect = ['OK\n', 'OK\n']
    f.__iter__ = lambda s: iter(['END LIST VAR ups\n'])
    sock = MagicMock()
    sock.makefile.return_value = f
    with patch('watchfuls.ups.socket.create_connection', return_value=sock):
        ups_module._nut_query('192.0.2.5', 3493, 'ups', user, password, 5)
    return ''.join(written)


class TestNutArguments:
    """upsd tokenises on spaces with double quotes and backslash escapes: a password with a
    space went out as two arguments, and one with a line break ended the command and began
    another of the sender's choosing."""

    def test_a_password_with_spaces_is_quoted(self):
        sent = _query_capturing('monuser', 'two words')
        assert 'PASSWORD "two words"\n' in sent

    def test_quotes_and_backslashes_are_escaped(self):
        sent = _query_capturing('monuser', r'a"b\c')
        assert r'PASSWORD "a\"b\\c"' + '\n' in sent

    def test_a_plain_value_is_sent_as_is(self):
        sent = _query_capturing('monuser', 'secret')
        assert 'USERNAME monuser\n' in sent and 'PASSWORD secret\n' in sent

    @pytest.mark.parametrize('password', ['x\nINSTCMD ups load.off', 'x\rY'])
    def test_a_line_break_is_refused_before_connecting(self, password):
        with patch('watchfuls.ups.socket.create_connection') as conn:
            with pytest.raises(ValueError):
                ups_module._nut_query('192.0.2.5', 3493, 'ups', 'monuser', password, 5)
        conn.assert_not_called()


class TestOneBadNumberDoesNotSinkTheModule:
    """The per-item port/timeout were parsed outside the per-item executor: one malformed
    value raised out of check() and no UPS of the module was checked."""

    def test_the_bad_item_fails_alone(self):
        w = ups_module.Watchful(create_mock_monitor({'watchfuls.ups': {'list': {
            'bad':  {'enabled': True, 'host': '192.0.2.5', 'port': 'abc'},
            'good': {'enabled': True, 'host': '192.0.2.6'},
        }}}))
        variables = {'ups.status': 'OL', 'battery.charge': '100',
                     'battery.runtime': '3600', 'ups.load': '20'}
        with patch('watchfuls.ups._nut_query', return_value=variables):
            items = w.check().list
        assert items['bad']['status'] is False
        assert any(k.startswith('good') and v['status'] is True for k, v in items.items())
