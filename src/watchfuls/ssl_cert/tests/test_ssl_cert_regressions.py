#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/ssl_cert found by the 2026-10-12 audit."""

from unittest.mock import patch

from conftest import create_mock_monitor


class TestOneBadNumberDoesNotSinkTheModule:
    """The per-item port/warning_days/timeout were parsed outside the per-item executor: one
    malformed value raised out of check() and no certificate of the module was checked."""

    def test_the_bad_item_fails_alone(self):
        from watchfuls.ssl_cert import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.ssl_cert': {'list': {
            'bad':  {'enabled': True, 'host': 'a.example.test', 'warning_days': 'soon'},
            'good': {'enabled': True, 'host': 'b.example.test'},
        }}}))
        seen = []

        def fake_check(item):
            seen.append(item['key'])
            w.dict_return.set(item['key'], True, 'ok')

        with patch.object(w, '_ssl_check', side_effect=fake_check):
            items = w.check().list
        assert seen == ['good']
        assert items['bad']['status'] is False
        assert items['good']['status'] is True
