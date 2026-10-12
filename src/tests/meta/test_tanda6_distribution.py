#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution defects of the 2026-10-12 audit's sixth batch.

- DIST-1  rpm re-applied root:root 0750 to /etc and /var/lib on every upgrade (they were
          package directories), and the services running as `servicesentry` lost their own
          config. The package no longer owns them; the postinstall creates them and hands
          them back to the drop-in's user.
- DIST-2  every launcher forced `--web-host 0.0.0.0`, so the panel's Host field did nothing.
- DIST-4  Helm generated the secret key under `helm template` (lookup is empty there): a new
          key per render, every stored secret undecryptable. Now it fails unless told.
- DIST-5  the compose worker wrote root:root files the non-root containers could not touch.
- DIST-7  update.sh stopped the services, then failed building the venv, and left them down.
- DIST-8  the package scripts acted on every argument except a short exclusion list.
- DIST-10 the workflow pasted the tag into shell, downloaded nfpm unverified, and ran with the
          default token permissions.
- DIST-11 a Python upgrade broke the venv and the unit only said "No such file".
- DIST-12 install.sh over an install left retired files behind.
- DIST-13 CI never ran the venv as the dedicated user, nor an rpm upgrade.

The shell is run for real where it can be (with fake system tools); YAML is parsed, the chart
is rendered with `helm template`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_ROOT = os.path.dirname(_SRC)
_HELM = os.path.join(_ROOT, 'helm', 'servicesentry')
_SCRIPTS = os.path.join(_ROOT, 'packaging', 'scripts')
_WF = os.path.join(_ROOT, '.github', 'workflows')
_DOCKER = os.path.join(_ROOT, 'docker')
_UNITS = ['ServiSesentry', 'ServiSesentry-web']


def _read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as fh:
        return fh.read()


def _code(text: str) -> str:
    """The text without shell comments (a comment naming a fix is not the fix)."""
    return re.sub(r'(?m)^\s*#.*$', '', text)


def _sh():
    sh = shutil.which('sh')
    if not sh:
        pytest.skip('no POSIX sh')
    return sh


def _fakes(tmp_path, tools, codes=None):
    """Fake system tools that log their arguments; returns (PATH env, log path)."""
    fake = tmp_path / 'bin'
    fake.mkdir(exist_ok=True)
    log = tmp_path / 'calls.log'
    for tool in tools:
        (fake / tool).write_text(
            f'#!/bin/sh\necho "{tool} $*" >> "{log.as_posix()}"\nexit {(codes or {}).get(tool, 0)}\n',
            encoding='utf-8', newline='\n')
        os.chmod(fake / tool, 0o755)
    env = dict(os.environ, PATH=fake.as_posix() + os.pathsep + os.environ.get('PATH', ''))
    return env, log


def _calls(log):
    return log.read_text(encoding='utf-8') if log.exists() else ''


# ── DIST-1: the package does not own /etc and /var/lib ──────────────────────────
class TestPackageDirs:

    def test_nfpm_ships_no_config_or_data_directory(self):
        nfpm = _read(_ROOT, 'packaging', 'nfpm.yaml')
        for d in ('/etc/ServiSesentry', '/var/lib/ServiSesentry'):
            assert not re.search(r'^\s*-\s*dst:\s*%s\s*$' % re.escape(d), nfpm, re.M), \
                f'{d} as a package directory gets its owner reset by rpm on every upgrade'
        assert 'type: dir' not in _code(nfpm)

    def test_postinstall_creates_them_and_restores_the_owner_before_restarting(self):
        code = _code(_read(_SCRIPTS, 'postinstall.sh'))
        assert re.search(r'^mkdir -p "\$\{CONF_DIR\}" "\$\{VAR_DIR\}"$', code, re.M)
        call = code.index('\nrestore_dir_owner\n')
        assert call < code.index('try-restart'), 'the owner must be back before the restart'
        assert 'chown -R' not in code[code.index('restore_dir_owner() {'):call]

    def _run(self, tmp_path, dropin_user):
        text = _read(_SCRIPTS, 'postinstall.sh')
        fn = re.search(r'^restore_dir_owner\(\) \{\n.*?^\}\n', text, re.M | re.S)
        assert fn, 'postinstall.sh must hand the dirs back in restore_dir_owner'
        etc = tmp_path / 'systemd'
        if dropin_user:
            d = etc / 'ServiSesentry.service.d'
            d.mkdir(parents=True)
            (d / '10-servicesentry-user.conf').write_text(
                f'[Service]\nUser={dropin_user}\nGroup={dropin_user}\n', encoding='utf-8')
        env, log = _fakes(tmp_path, ['chown', 'getent'])
        probe = tmp_path / 'probe.sh'
        probe.write_text(
            f'CONF_DIR={(tmp_path / "etc").as_posix()}\nVAR_DIR={(tmp_path / "var").as_posix()}\n'
            f'SYSTEMD_ETC={etc.as_posix()}\n' + fn.group(0) + 'restore_dir_owner\n',
            encoding='utf-8', newline='\n')
        r = subprocess.run([_sh(), probe.as_posix()], capture_output=True, text=True, env=env,
                           timeout=30)
        assert r.returncode == 0, r.stderr
        return [l for l in _calls(log).splitlines() if l.startswith('chown')]

    def test_a_dedicated_user_install_gets_both_dirs_back(self, tmp_path):
        calls = self._run(tmp_path, 'servicesentry')
        assert len(calls) == 1
        assert re.match(r'^chown servicesentry:servicesentry \S+/etc \S+/var$', calls[0]), calls

    def test_a_root_install_is_left_alone(self, tmp_path):
        assert self._run(tmp_path, None) == []


# ── DIST-2: no launcher forces the bind address ─────────────────────────────────
class TestNoForcedBind:

    @pytest.mark.parametrize('path', [
        ('init', 'systemd', 'ServiSesentry-web.service'),
        ('init', 'openrc', 'init.d', 'ServiSesentry-web'),
        ('docker', 'entrypoint.sh'),
    ])
    def test_no_web_host_flag(self, path):
        code = _code(_read(_ROOT, *path))
        assert '--web-host' not in code and '--web-port' not in code, \
            'a flag here overrides the Host/Port fields of Configuration'

    def test_openrc_conf_sets_nothing_by_default(self):
        conf = _code(_read(_ROOT, 'init', 'openrc', 'conf.d', 'ServiSesentry-web'))
        assert not re.search(r'^\s*SS_WEB_(HOST|PORT)=', conf, re.M)
        init = _read(_ROOT, 'init', 'openrc', 'init.d', 'ServiSesentry-web')
        assert 'SS_WEB_HOST:=' not in init and 'SS_WEB_PORT:=' not in init
        assert re.search(r'if \[ -n "\$\{SS_WEB_HOST\}" \]; then export SS_WEB_HOST; fi', init)

    def test_the_compose_files_still_bind_every_interface_in_a_container(self):
        # The image keeps SS_WEB_HOST=0.0.0.0: a container that listened on 127.0.0.1 would be
        # unreachable through its published port.
        assert re.search(r'^ENV SS_WEB_HOST=0\.0\.0\.0', _read(_DOCKER, 'Dockerfile'), re.M)


# ── DIST-4: Helm never generates a key per render ───────────────────────────────
def _helm(*sets):
    helm = shutil.which('helm')
    if not helm:
        pytest.skip('helm not installed')
    args = [helm, 'template', 't', _HELM, '--set', 'auth.password=x',
            '--set', 'database.password=y', '--set', 'database.host=db']
    for s in sets:
        args += ['--set', s]
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


class TestHelmSecrets:

    def test_an_empty_secret_key_fails_under_helm_template(self):
        r = _helm('control.token=' + 'k' * 32)
        assert r.returncode != 0
        assert 'secretKey' in r.stderr and 'generateSecrets' in r.stderr

    def test_an_empty_control_token_fails_too(self):
        r = _helm('secretKey=abc')
        assert r.returncode != 0
        assert 'control.token' in r.stderr

    def test_explicit_values_render(self):
        r = _helm('secretKey=abc', 'control.token=' + 'k' * 32)
        assert r.returncode == 0, r.stderr
        assert 'flask_secret: "abc"' in r.stdout

    def test_control_off_needs_no_token(self):
        assert _helm('secretKey=abc', 'control.enabled=false').returncode == 0

    def test_generation_is_an_explicit_opt_in(self):
        r = _helm('generateSecrets=true')
        assert r.returncode == 0, r.stderr
        assert re.search(r'flask_secret: "[0-9a-f]{64}"', r.stdout)
        assert re.search(r'SS_CONTROL_TOKEN: "\S{20,}"', r.stdout)

    def test_values_and_notes_document_it(self):
        values = _read(_HELM, 'values.yaml')
        assert re.search(r'^generateSecrets: false$', values, re.M)
        assert 'helm template' in values
        assert 'generateSecrets' in _read(_HELM, 'templates', 'NOTES.txt')


# ── DIST-5: the compose worker writes group-writable files ───────────────────────
_COMPOSE_WITH_WORKER = ['docker-compose.microservices.yml',
                        'docker-compose.microservices-traefik.yml',
                        'docker-compose.microservices-test.yml',
                        'docker-compose.ha-test.yml']


class TestComposeWorker:

    @pytest.mark.parametrize('name', _COMPOSE_WITH_WORKER)
    def test_worker_shares_the_group_with_umask_0002(self, name):
        yaml = pytest.importorskip('yaml')
        with open(os.path.join(_DOCKER, name), encoding='utf-8') as fh:
            worker = yaml.safe_load(fh)['services']['worker']
        assert str(worker.get('user')) == '0:1000', \
            'root (for NET_RAW) but in the ssentry group the other containers run as'
        cmd = ' '.join(worker.get('entrypoint') or [])
        assert 'umask 0002' in cmd and 'exec /entrypoint.sh' in cmd
        assert 'chown -R 1000:1000 /var/lib/ServiSesentry' in cmd


# ── DIST-7 / DIST-12: update.sh and install.sh ──────────────────────────────────
class TestScriptOrder:

    def test_update_builds_the_venv_before_stopping(self):
        code = _code(_read(_ROOT, 'update.sh'))
        venv = code.index('sh packaging/scripts/make-venv.sh')
        assert venv < code.index('systemctl stop ServiSesentry.service')
        assert venv < code.index('rc-service ServiSesentry     stop')
        assert 'trap restart_on_failure EXIT' in code

    def test_update_restarts_what_was_running_when_it_fails(self, tmp_path):
        bash = shutil.which('bash')
        if not bash:
            pytest.skip('no bash')
        text = _read(_ROOT, 'update.sh')
        fn = re.search(r'^restart_on_failure\(\) \{\n.*?^\}\n', text, re.M | re.S)
        assert fn
        env, log = _fakes(tmp_path, ['systemctl'])
        probe = tmp_path / 'probe.sh'
        probe.write_text('INIT_SYSTEM=systemd\nSTOPPED=" ServiSesentry ServiSesentry-web"\n'
                         + fn.group(0) + 'trap restart_on_failure EXIT\nfalse\n',
                         encoding='utf-8', newline='\n')
        r = subprocess.run([bash, '-e', probe.as_posix()], capture_output=True, text=True,
                           env=env, timeout=30)
        assert r.returncode != 0
        calls = _calls(log)
        assert 'start ServiSesentry.service' in calls and 'start ServiSesentry-web.service' in calls

    def test_a_finished_update_disarms_the_trap(self):
        code = _code(_read(_ROOT, 'update.sh'))
        assert code.rindex('STOPPED=""') > code.rindex('esac'), \
            'after the services were started again, a late failure must not start them twice'

    def test_install_over_an_install_clears_all_but_the_venv(self):
        code = _code(_read(_ROOT, 'install.sh'))
        find = code.index('find "${APP_DIR}" -mindepth 1 -maxdepth 1 ! -name venv -exec rm -rf {} +')
        assert find < code.index('tar -C src')


# ── DIST-8: package scripts act only on a real removal ──────────────────────────
class TestRemovalOnly:

    def _run(self, tmp_path, script, args):
        body = _read(_SCRIPTS, script).replace('[ -d /run/systemd/system ]', 'true')
        venv = tmp_path / 'opt' / 'venv'
        venv.mkdir(parents=True)
        body = body.replace('/opt/ServiSesentry/venv', venv.as_posix())
        copia = tmp_path / script
        copia.write_text(body, encoding='utf-8', newline='\n')
        env, log = _fakes(tmp_path, ['systemctl'])
        r = subprocess.run([_sh(), copia.as_posix(), *args], capture_output=True, text=True,
                           env=env, timeout=60)
        assert r.returncode == 0, r.stderr
        return _calls(log), venv.exists()

    @pytest.mark.parametrize('args', [['failed-upgrade', '1.0'], ['deconfigure'],
                                      ['upgrade', '1.0'], ['1'], ['2']])
    def test_preremove_leaves_them_running(self, tmp_path, args):
        calls, _ = self._run(tmp_path, 'preremove.sh', args)
        assert 'stop' not in calls

    @pytest.mark.parametrize('args', [['abort-upgrade', '1.0'], ['failed-upgrade', '1.0'],
                                      ['abort-install'], ['disappear'], ['upgrade', '1.0'],
                                      ['1']])
    def test_postremove_keeps_the_venv(self, tmp_path, args):
        _, kept = self._run(tmp_path, 'postremove.sh', args)
        assert kept

    @pytest.mark.parametrize('args', [['remove'], ['purge'], ['0']])
    def test_postremove_removes_it_on_a_removal(self, tmp_path, args):
        _, kept = self._run(tmp_path, 'postremove.sh', args)
        assert not kept


# ── DIST-10: the workflow ───────────────────────────────────────────────────────
def _workflow(name):
    yaml = pytest.importorskip('yaml')
    with open(os.path.join(_WF, name), encoding='utf-8') as fh:
        return yaml.safe_load(fh)


class TestWorkflowHardening:

    def test_read_only_by_default(self):
        wf = _workflow('docker.yml')
        assert wf.get('permissions') == {'contents': 'read'}

    def test_no_expression_inside_a_script(self):
        """`${{ }}` is pasted into the script before the shell parses it: a value somebody
        controls (a tag name) becomes code. Values go in through `env:`."""
        bad = [f'{job_id}: {step.get("name")}'
               for job_id, job in _workflow('docker.yml')['jobs'].items()
               for step in job.get('steps') or [] if '${{' in (step.get('run') or '')]
        assert bad == [], bad

    def test_the_version_is_validated_and_passed_through_env(self):
        text = _read(_WF, 'docker.yml')
        assert "grep -Eq '^[0-9A-Za-z.+-]+$'" in text
        assert 'run: bash packaging/build.sh "${SS_PKG_VERSION}"' in text
        assert 'steps.ver.outputs.value }}"' not in text

    def test_nfpm_is_checked_against_its_hash(self):
        text = _read(_WF, 'docker.yml')
        assert re.search(r'NFPM_SHA256: [0-9a-f]{64}\n', text)
        assert 'sha256sum -c -' in text

    def test_build_sh_refuses_a_version_with_odd_characters(self):
        assert '[0-9A-Za-z.+-]' in _read(_ROOT, 'packaging', 'build.sh')


# ── DIST-11: a broken venv says what to do ──────────────────────────────────────
class TestBrokenVenv:

    @pytest.mark.parametrize('unit', _UNITS)
    def test_units_check_the_venv_first(self, unit):
        text = _read(_ROOT, 'init', 'systemd', f'{unit}.service')
        pre = re.search(r"^ExecStartPre=/bin/sh -c '(.*)'$", text, re.M)
        assert pre, 'the unit must check the venv interpreter before starting'
        assert 'make-venv.sh' in pre.group(1)
        assert '$' not in pre.group(1), 'systemd expands $VAR itself: write $$ or none'

    def _pre(self, tmp_path, python_body):
        text = _read(_ROOT, 'init', 'systemd', 'ServiSesentry.service')
        cmd = re.search(r"^ExecStartPre=/bin/sh -c '(.*)'$", text, re.M).group(1)
        app = tmp_path / 'opt'
        if python_body is not None:
            (app / 'venv' / 'bin').mkdir(parents=True)
            py = app / 'venv' / 'bin' / 'python'
            py.write_text(f'#!/bin/sh\n{python_body}\n', encoding='utf-8', newline='\n')
            os.chmod(py, 0o755)
        cmd = cmd.replace('/opt/ServiSesentry', app.as_posix())
        return subprocess.run([_sh(), '-c', cmd], capture_output=True, text=True, timeout=30)

    def test_a_broken_venv_stops_the_start_with_the_fix(self, tmp_path):
        r = self._pre(tmp_path, 'exit 127')
        assert r.returncode != 0 and 'make-venv.sh' in r.stderr

    def test_a_working_venv_passes(self, tmp_path):
        assert self._pre(tmp_path, 'exit 0').returncode == 0

    def test_no_venv_skips_the_check(self, tmp_path):
        assert self._pre(tmp_path, None).returncode == 0

    def test_the_packaged_unit_keeps_the_check(self, tmp_path):
        # build.sh / install.sh rewrite ExecStart only; the check must survive that sed.
        text = _read(_ROOT, 'init', 'systemd', 'ServiSesentry-web.service')
        sed = re.compile(r'^ExecStart=/usr/bin/python3 ', re.M)
        out = sed.sub('ExecStart=/opt/ServiSesentry/venv/bin/python ', text)
        assert 'ExecStartPre=/bin/sh -c' in out
        assert re.search(r'^ExecStart=/opt/ServiSesentry/venv/bin/python ', out, re.M)

    @pytest.mark.parametrize('svc', _UNITS)
    def test_openrc_checks_the_interpreter(self, svc):
        text = _read(_ROOT, 'init', 'openrc', 'init.d', svc)
        pre = re.search(r'^start_pre\(\) \{\n(.*?)^\}', text, re.M | re.S).group(1)
        assert '"${SS_PYTHON}" -c' in pre and 'make-venv.sh' in pre and 'return 1' in pre

    def test_make_venv_travels_with_the_app(self):
        assert re.search(r'src: \./scripts/make-venv\.sh\n\s+dst: /opt/ServiSesentry/make-venv\.sh',
                         _read(_ROOT, 'packaging', 'nfpm.yaml'))
        for script in ('install.sh', 'update.sh'):
            assert 'install -m 0755 packaging/scripts/make-venv.sh' in _code(_read(_ROOT, script))
        assert 'doexe packaging/scripts/make-venv.sh' in _read(_ROOT, 'packaging', 'gentoo',
                                                               'servicesentry.ebuild.in')


# ── DIST-13: CI runs the venv as the dedicated user, and an rpm upgrade ─────────
class TestCiInstall:

    def test_install_tests_run_the_venv_as_servicesentry(self):
        text = _code(_read(_WF, 'install-tests.yml'))
        assert 'python3 /opt/ServiSesentry/main.py' not in text, \
            'the system python as root proves neither the venv nor the permissions'
        assert text.count('runuser -u servicesentry -- /opt/ServiSesentry/venv/bin/python') >= 3
        assert 'python3-flask' not in text

    def test_rpm_job_installs_two_versions_and_checks_the_owner(self):
        wf = _workflow('docker.yml')
        steps = wf['jobs']['packages-install']['steps']
        up = [s for s in steps if 'upgrade' in (s.get('name') or '').lower()]
        assert up and up[0].get('if') == "matrix.kind == 'rpm'"
        assert 'dnf install -y ./next/*.rpm' in up[0]['run']
        assert 'servicesentry:servicesentry' in up[0]['run']
        built = [s for s in wf['jobs']['packages']['steps']
                 if 'packages-next' in str(s.get('with', {}).get('name', ''))]
        assert built, 'the newer rpm is uploaded under its own artifact name'
        release = wf['jobs']['release']['steps']
        assert not any('packages-next' in str(s) for s in release), \
            'the rehearsal rpm must never reach a Release'


# ── DIST-6: the image does not claim credentials are mandatory ───────────────────
class TestFirstRunDocs:

    def test_dockerfile_says_what_an_unset_password_does(self):
        text = _read(_DOCKER, 'Dockerfile')
        assert 'no defaults: must be set explicitly' not in text
        assert 'admin/admin' in text and 'new' in text and 'first login' in text

    def test_cli_doc_explains_runuser(self):
        assert 'runuser -u servicesentry' in _read(_ROOT, 'docs', 'ref-cli.md')


class TestWindowsCimRunsOnWindows:
    """cpu, filesystemusage and ram_swap read Windows through `Get-CimInstance`; only a real
    Windows proves the commands and parsers agree. The CI job that does it must stay."""

    def test_the_tests_workflow_has_a_windows_job_running_the_cim_test(self):
        import yaml
        wf = yaml.safe_load(_read(_ROOT, '.github', 'workflows', 'tests.yml'))
        jobs = [j for j in wf['jobs'].values() if 'windows' in str(j.get('runs-on', ''))]
        assert jobs, 'no Windows job in tests.yml'
        texto = repr(jobs)
        assert 'test_windows_cim_live.py' in texto and "'SS_TEST_WINDOWS_CIM': '1'" in texto
