#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions in the shared module plumbing found by the 2026-10-12 audit.

* ``module_default('timeout')`` with an explicit 0 returned 0, and every subprocess or
  socket built from it gave up at once: the whole module failed each cycle.
* ``device_exec`` ran local commands with the service's stdin inherited, and ``wmic`` reads
  its console input until EOF — the check hung until its timeout killed it.
"""

from unittest.mock import MagicMock, patch

import pytest

from lib.modules.module_base import ModuleBase


class _Fake(ModuleBase):
    def __init__(self, stored, glob=None):
        self._stored = stored
        self._monitor = MagicMock()
        self._monitor.config.get_conf.return_value = glob

    @property
    def is_monitor_exist(self):
        return True

    def get_conf(self, *a, **kw):
        return self._stored

    def _module_schema_defaults(self):
        return {'timeout': 15, 'threads': 4, 'alert': 80}


class TestTimeoutZeroIsNotATimeout:

    @pytest.mark.parametrize('stored', [0, '0', -3])
    def test_a_non_positive_timeout_inherits_the_schema_default(self, stored):
        assert _Fake({'timeout': stored}).module_default('timeout', 15) == 15

    def test_a_non_positive_timeout_inherits_the_global_first(self):
        assert _Fake({'timeout': 0}, glob=30).module_default('timeout', 15) == 30

    def test_a_zero_global_timeout_falls_to_the_schema_default(self):
        assert _Fake({'timeout': None}, glob=0).module_default('timeout', 15) == 15

    def test_threads_zero_inherits_too(self):
        assert _Fake({'threads': 0}).module_default('threads', 4) == 4

    def test_a_real_timeout_is_kept(self):
        assert _Fake({'timeout': 7}).module_default('timeout', 15) == 7

    def test_an_explicit_zero_threshold_still_means_off(self):
        """The general contract is untouched: 0 on a threshold is a real value."""
        assert _Fake({'alert': 0}).module_default('alert', 80) == 0


class TestDeviceExecClosesStdin:

    def test_local_commands_run_with_stdin_closed(self):
        import subprocess
        res = MagicMock(stdout='LoadPercentage=5', stderr='', returncode=0)
        with patch('subprocess.run', return_value=res) as run:
            out = _Fake({}).device_exec({'device_kind': 'local'}, 'wmic cpu get x /value',
                                        timeout=5)
        assert out == ('LoadPercentage=5', '', 0)
        assert run.call_args.kwargs.get('stdin') is subprocess.DEVNULL
