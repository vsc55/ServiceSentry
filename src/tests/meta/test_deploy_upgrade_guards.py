#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two deployment defects found by the 2026-10-12 audit.

- Helm: with the default values (control on, no token) the services opened no control
  listener, yet the worker, events and syslog pods were probed on it — restarted every ~80 s
  and never Ready. The chart now generates the token, and probes only when a listener can
  exist.
- Packages: the pre-remove script stopped both services on an upgrade too, and nothing
  started them again. On an upgrade it now leaves them alone and the post-install restarts
  the ones that were running.

The scripts are run for real under `sh` with a fake `systemctl` that records its calls.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_ROOT = os.path.dirname(_SRC)
_HELM = os.path.join(_ROOT, 'helm', 'servicesentry', 'templates')
_SCRIPTS = os.path.join(_ROOT, 'packaging', 'scripts')


def _read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as fh:
        return fh.read()


class TestHelmControl:

    @pytest.mark.parametrize('role', ['worker', 'events', 'syslog'])
    def test_probes_are_gated_on_a_listener(self, role):
        text = _read(_HELM, f'{role}.yaml')
        assert '/control/health' in text
        assert '{{- if .Values.control.enabled }}' not in text, \
            'gate the control port and probes on servicesentry.controlListens'
        assert 'servicesentry.controlListens' in text

    def test_an_empty_token_is_generated_and_kept(self):
        text = _read(_HELM, 'secret.yaml')
        assert 'SS_CONTROL_TOKEN' in text and 'randAlphaNum' in text and 'lookup' in text
        assert 'and .Values.control.enabled .Values.control.token' not in text

    def test_helm_renders_probes_with_a_token(self):
        helm = shutil.which('helm')
        if not helm:
            pytest.skip('helm not installed')
        out = subprocess.run(
            [helm, 'template', 't', os.path.join(_ROOT, 'helm', 'servicesentry'),
             '--set', 'auth.password=x', '--set', 'database.password=y',
             '--set', 'database.host=db',
             # An empty token is generated only when asked to (helm template sees no live
             # Secret: test_tanda6_distribution.TestHelmSecrets).
             '--set', 'generateSecrets=true'], capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr
        assert out.stdout.count('/control/health') >= 2
        assert re.search(r'SS_CONTROL_TOKEN: "\S{20,}"', out.stdout)


def _run(script, args, tmp_path):
    sh = shutil.which('sh')
    if not sh:
        pytest.skip('no POSIX sh')
    fake = tmp_path / 'bin'
    fake.mkdir(exist_ok=True)
    log = tmp_path / 'calls.log'
    (fake / 'systemctl').write_text(f'#!/bin/sh\necho "$@" >> "{log.as_posix()}"\nexit 0\n',
                                    encoding='utf-8', newline='\n')
    os.chmod(fake / 'systemctl', 0o755)
    # The scripts ask for /run/systemd/system; stand it in by rewriting the test.
    body = _read(_SCRIPTS, script).replace('[ -d /run/systemd/system ]', 'true')
    copia = tmp_path / script
    copia.write_text(body, encoding='utf-8', newline='\n')
    env = dict(os.environ, PATH=fake.as_posix() + os.pathsep + os.environ.get('PATH', ''))
    r = subprocess.run([sh, copia.as_posix(), *args], capture_output=True, text=True,
                       env=env, timeout=60)
    return r.returncode, (log.read_text(encoding='utf-8') if log.exists() else '')


class TestPackageUpgrade:

    @pytest.mark.parametrize('args', [['upgrade', '1.0'], ['1']])
    def test_preremove_leaves_the_services_running_on_an_upgrade(self, tmp_path, args):
        code, calls = _run('preremove.sh', args, tmp_path)
        assert code == 0 and 'stop' not in calls and 'disable' not in calls

    @pytest.mark.parametrize('args', [['remove'], ['0']])
    def test_preremove_stops_them_on_a_removal(self, tmp_path, args):
        code, calls = _run('preremove.sh', args, tmp_path)
        assert code == 0 and 'stop ServiSesentry-web' in calls

    def test_postinstall_restarts_running_services_on_an_upgrade(self):
        text = _read(_SCRIPTS, 'postinstall.sh')
        assert 'try-restart' in text
        assert re.search(r'"\$\{1:-\}" = "configure" \] && \[ -n "\$\{2:-\}"', text)
