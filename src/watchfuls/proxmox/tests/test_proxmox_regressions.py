#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/proxmox found by the 2026-10-12 audit."""

from unittest.mock import patch

import pytest

from conftest import create_mock_monitor


@pytest.fixture(autouse=True)
def _no_ssrf_guard():
    with patch('lib.security.net_guard.validate_external_url', return_value=None):
        yield


def _run_ceph(error_msg, code=500):
    from watchfuls.proxmox import Watchful
    from watchfuls.proxmox.client import PveError
    item = {'enabled': True, 'label': 'PVE', 'host': '10.0.0.1', 'port': 8006,
            'verify_ssl': False, 'auth_method': 'token', 'token_id': 'mon@pve!ss',
            'token_secret': 'uuid-secret', 'check_cluster': False, 'check_nodes': False,
            'check_ceph': True, 'check_network': False, 'check_updates': False}
    w = Watchful(create_mock_monitor(
        {'watchfuls.proxmox': {'threads': 1, 'alert': 1, 'list': {'pve': item}}}))

    def fake_get(_conn, path):
        if path == '/cluster/ceph/status':
            raise PveError(code, error_msg)
        return {'version': '8.0'}

    with patch.object(w, '_pve_get', side_effect=fake_get):
        return w.check().list['pve/ceph']


class TestBrokenCephIsNotAbsentCeph:
    """A broken Ceph speaks through rados too. Matching the bare word "rados" (or "unable
    to", "command") filed a cluster whose monitors are unreachable as "Ceph not installed"
    and reported it OK."""

    @pytest.mark.parametrize('msg', [
        'rados_connect failed - Connection timed out',
        'got timeout',
        'rados_connect failed - Permission denied',
        'unable to get monitor info from DNS SRV',
    ])
    def test_a_broken_ceph_is_a_failure(self, msg):
        row = _run_ceph(msg)
        assert row['status'] is False, msg

    @pytest.mark.parametrize('msg', [
        'rados_connect failed - No such file or directory',
        'binary not installed: /usr/bin/ceph-mon',
        'Ceph is not initialized',
    ])
    def test_an_absent_ceph_is_still_not_configured(self, msg):
        row = _run_ceph(msg)
        assert row['status'] is True, msg
