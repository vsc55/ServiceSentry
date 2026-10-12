#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/datastore found by the 2026-10-12 audit."""

from unittest.mock import patch

from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, devices):
        self._h = devices

    def get(self, uid, **_kw):
        return self._h.get(uid)


def _watchful(maintenance):
    from watchfuls.datastore import Watchful
    mm = create_mock_monitor({'watchfuls.datastore': {'list': {
        'db1': {'enabled': True, 'db_type': 'mysql', 'device_uid': 'h1'}}}})
    mm._devices_store = _FakeStore({'h1': {
        'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': 'linux',
        'maintenance': maintenance, 'profiles': {}}})
    return Watchful(mm)


class TestDeviceMaintenance:
    """Every other module skips a check whose bound device is in maintenance; the datastore
    filtered on the RAW item, which never carries the mark, and kept alerting."""

    def test_a_device_in_maintenance_is_not_checked(self):
        w = _watchful(maintenance=True)
        with patch.object(w, '_ds_check') as ds:
            result = w.check()
        ds.assert_not_called()
        assert len(result.items()) == 0

    def test_a_device_out_of_maintenance_still_is(self):
        w = _watchful(maintenance=False)
        with patch.object(w, '_ds_check') as ds:
            w.check()
        ds.assert_called_once_with('db1')
