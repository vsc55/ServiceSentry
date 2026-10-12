#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/temperature found by the 2026-10-12 audit."""

from unittest.mock import patch


_LOCAL = ("/sys/class/thermal/thermal_zone0/type:x86_pkg_temp\n"
          "/sys/class/thermal/thermal_zone0/temp:45000\n")


class TestLocalDiscovery:
    """The runner's local branch runs without a shell, so the `thermal_zone*` globs reached
    grep literally and matched nothing: discovery on the panel's own machine was always
    empty. The zones are now read in Python."""

    def test_local_discovery_does_not_hand_the_glob_to_the_runner(self):
        from watchfuls.temperature import Watchful
        with patch.object(Watchful, '_read_thermal_local', return_value=_LOCAL), \
             patch('lib.core.devices.runner.run') as run:
            found = Watchful.discover({'__device__': {'kind': 'local', 'os': 'linux'}})
        run.assert_not_called()
        assert [s['name'] for s in found] == ['x86_pkg_temp']

    def test_no_device_is_local_too(self):
        from watchfuls.temperature import Watchful
        with patch.object(Watchful, '_read_thermal_local', return_value=_LOCAL), \
             patch('lib.core.devices.runner.run') as run:
            found = Watchful.discover({})
        run.assert_not_called()
        assert found and found[0]['status'] == '45.0°C'

    def test_read_thermal_local_expands_the_zones(self):
        import io
        from watchfuls.temperature import Watchful
        files = {'/sys/class/thermal/thermal_zone0/type': 'acpitz\n',
                 '/sys/class/thermal/thermal_zone0/temp': '41000\n'}

        def fake_glob(pattern):
            leaf = pattern.rsplit('/', 1)[1]
            return [p for p in files if p.endswith('/' + leaf)]

        with patch('watchfuls.temperature.glob.glob', side_effect=fake_glob), \
             patch('watchfuls.temperature.open', create=True,
                   side_effect=lambda p, **_kw: io.StringIO(files[p])):
            out = Watchful._read_thermal_local()
        assert dict(Watchful._parse_thermal(out)) == {'acpitz': 41.0}

    def test_a_device_with_no_connection_still_runs_nothing(self):
        from watchfuls.temperature import Watchful
        with patch.object(Watchful, '_read_thermal_local') as local, \
             patch('lib.core.devices.runner.run', return_value=('', 'no exec', -1)):
            assert Watchful.discover({'__device__': {'kind': 'none'}}) == []
        local.assert_not_called()
