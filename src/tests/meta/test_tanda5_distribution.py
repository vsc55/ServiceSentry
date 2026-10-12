#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution items deferred from the 2026-10-12 audit (E7, E9 and two follow-ups).

- E7  install.sh left an install that would not start: it ran /usr/bin/python3 with the
      distro packages of dependencies.txt (no flask among them) and never copied
      requirements.lock; update.sh did `rm -rf /opt/ServiSesentry`, venv included. Both now
      build/keep the venv from the lock (packaging/scripts/make-venv.sh), with the same
      Python >= 3.11.3 floor as the packages, and point units / conf.d at it.
- E9  every service ran as root. A FRESH install (deb `configure` with no old version, rpm
      $1 = 1, Gentoo REPLACING_VERSIONS empty, install.sh with no previous dirs) runs them
      as `servicesentry` with CAP_NET_RAW + CAP_NET_BIND_SERVICE; an existing install keeps
      root until `servicesentry-user enable`. Plus logrotate for the OpenRC SS_LOG files.
- CI  a manual dispatch on a `v*` tag ref still reached the `release` job.
- Helm with persistence, worker/syslog (root) left files the uid-1000 pods could not write.
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
_GENTOO = os.path.join(_ROOT, 'packaging', 'gentoo')
_SCRIPTS = os.path.join(_ROOT, 'packaging', 'scripts')
_WF = os.path.join(_ROOT, '.github', 'workflows')
_UNITS = ['ServiSesentry', 'ServiSesentry-web']
_FLOOR = 'sys.version_info >= (3, 11, 3)'


def _read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as fh:
        return fh.read()


def _code(text: str) -> str:
    """The text without shell comments (a comment naming a fix is not the fix)."""
    return re.sub(r'(?m)^\s*#.*$', '', text)


def _bash():
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('no bash')
    return bash


# ── E7: install.sh / update.sh build and keep a venv from the lock ───────────────
class TestScriptInstallVenv:

    def test_make_venv_has_the_packages_floor_and_the_lock(self):
        mk = _read(_SCRIPTS, 'make-venv.sh')
        assert _FLOOR in mk and _FLOOR in _read(_SCRIPTS, 'postinstall.sh'), \
            'install.sh and the packages must refuse the same interpreters'
        assert re.search(r'pip install --no-cache-dir -r "\$\{LOCK\}"', mk)
        assert 'LOCK="${APP_DIR}/requirements.lock"' in mk

    @pytest.mark.parametrize('script', ['install.sh', 'update.sh'])
    def test_scripts_build_the_venv_and_copy_the_lock(self, script):
        code = _code(_read(_ROOT, script))
        assert 'sh packaging/scripts/make-venv.sh' in code
        # The app is copied as a tree (requirements.lock included), not `src/*.py` + dirs.
        assert re.search(r"^tar -C src ", code, re.M)
        assert 'cp src/*.py' not in code
        assert "--exclude='requirements.lock'" not in code

    @pytest.mark.parametrize('script', ['install.sh', 'update.sh'])
    def test_units_get_the_venv_interpreter(self, script):
        code = _code(_read(_ROOT, script))
        # The same sed packaging/build.sh applies to the packaged units.
        sed = "s|^ExecStart=/usr/bin/python3 |ExecStart=/opt/ServiSesentry/venv/bin/python |"
        assert sed in _read(_ROOT, 'packaging', 'build.sh')
        assert sed in code
        assert not re.search(r'^\s*cp init/systemd/', code, re.M), \
            'a unit copied verbatim runs the system python, which has no flask'
        assert 'SS_PYTHON="/opt/ServiSesentry/venv/bin/python"' in code

    def test_update_keeps_the_venv(self, tmp_path):
        code = _code(_read(_ROOT, 'update.sh'))
        assert not re.search(r'^\s*rm -rf /opt/ServiSesentry\s*$', code, re.M), \
            'deleting the app dir takes the venv the services run with'
        m = re.search(r'^(find /opt/ServiSesentry .*)$', code, re.M)
        assert m, 'update.sh must clear the app dir except venv/'
        app = tmp_path / 'app'
        (app / 'venv' / 'bin').mkdir(parents=True)
        (app / 'venv' / 'bin' / 'python').write_text('x')
        (app / 'lib').mkdir()
        (app / 'main.py').write_text('x')
        line = m.group(1).replace('/opt/ServiSesentry', app.as_posix())
        r = subprocess.run([_bash(), '-c', line], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert sorted(p.name for p in app.iterdir()) == ['venv']
        assert (app / 'venv' / 'bin' / 'python').is_file()

    def test_dependencies_txt_is_only_what_the_venv_needs(self):
        deps = _read(_ROOT, 'dependencies.txt').split()
        assert deps == ['python3', 'python3-venv'], \
            'the libraries come from requirements.lock; distro python3-* are not what runs'
        assert 'dependencies.txt' in _read(_ROOT, 'check_dependencies.sh')


# ── E9: the dedicated user, on fresh installs only ───────────────────────────────
def _fake_bin(tmp_path):
    fake = tmp_path / 'bin'
    fake.mkdir(exist_ok=True)
    log = tmp_path / 'calls.log'
    for tool in ('getent', 'groupadd', 'useradd', 'chown', 'chmod', 'systemctl'):
        exit_code = 2 if tool == 'getent' else 0          # getent: "no such account"
        (fake / tool).write_text(
            f'#!/bin/sh\necho "{tool} $*" >> "{log.as_posix()}"\nexit {exit_code}\n',
            encoding='utf-8', newline='\n')
        os.chmod(fake / tool, 0o755)
    return fake, log


class TestDedicatedUser:

    def _tool(self, tmp_path, *args):
        sh = shutil.which('sh')
        if not sh:
            pytest.skip('no POSIX sh')
        fake, log = _fake_bin(tmp_path)
        etc = tmp_path / 'systemd'
        env = dict(os.environ,
                   PATH=fake.as_posix() + os.pathsep + os.environ.get('PATH', ''),
                   SS_SYSTEMD_ETC=etc.as_posix(),
                   SS_CONFIG_DIR=(tmp_path / 'etc').as_posix(),
                   SS_VAR_DIR=(tmp_path / 'var').as_posix(),
                   SS_LOG_DIR=(tmp_path / 'log').as_posix())
        r = subprocess.run([sh, os.path.join(_SCRIPTS, 'servicesentry-user.sh').replace(os.sep, '/'),
                            *args], capture_output=True, text=True, env=env, timeout=60)
        assert r.returncode == 0, r.stderr
        return etc, (log.read_text(encoding='utf-8') if log.exists() else '')

    def test_enable_writes_the_dropins_and_hands_over_the_dirs(self, tmp_path):
        etc, calls = self._tool(tmp_path, 'enable', '--no-restart')
        for unit in _UNITS:
            dropin = (etc / f'{unit}.service.d' / '10-servicesentry-user.conf').read_text()
            assert re.search(r'^User=servicesentry$', dropin, re.M)
            assert re.search(r'^AmbientCapabilities=CAP_NET_RAW CAP_NET_BIND_SERVICE$',
                             dropin, re.M)
        assert 'useradd --system' in calls and 'groupadd --system servicesentry' in calls
        assert re.search(r'^chown -R servicesentry:servicesentry .*/etc .*/var$', calls, re.M)

    def test_disable_goes_back_to_root(self, tmp_path):
        etc, _ = self._tool(tmp_path, 'enable', '--no-restart')
        _, calls = self._tool(tmp_path, 'disable', '--no-restart')
        assert not (etc / 'ServiSesentry.service.d' / '10-servicesentry-user.conf').exists()
        assert 'chown -R root:root' in calls

    def test_the_units_name_no_user(self):
        # They are shared by fresh installs and upgrades: a User= here would switch an
        # existing root install under its root-owned database. The drop-in carries it.
        for unit in _UNITS:
            assert not re.search(r'^User=', _read(_ROOT, 'init', 'systemd', f'{unit}.service'),
                                 re.M)

    @pytest.mark.parametrize('args,fresh', [
        (['configure', ''], True), (['configure', '1.2.2'], False),   # deb
        (['1'], True), (['2'], False),                                # rpm
        (['abort-upgrade', '1.2.2'], False),
    ])
    def test_postinstall_tells_fresh_from_upgrade(self, tmp_path, args, fresh):
        sh = shutil.which('sh')
        if not sh:
            pytest.skip('no POSIX sh')
        text = _read(_SCRIPTS, 'postinstall.sh')
        fn = re.search(r'^is_fresh_install\(\) \{\n.*?^\}\n', text, re.M | re.S)
        assert fn, 'postinstall.sh must decide fresh vs upgrade in is_fresh_install'
        assert re.search(r'^if is_fresh_install "\$@"; then\n\s+sh /usr/sbin/servicesentry-user '
                         r'enable --no-restart', text, re.M)
        probe = tmp_path / 'probe.sh'
        probe.write_text(fn.group(0) + 'is_fresh_install "$@"\n', encoding='utf-8',
                         newline='\n')
        r = subprocess.run([sh, probe.as_posix(), *args], capture_output=True, timeout=30)
        assert (r.returncode == 0) is fresh

    def test_install_sh_switches_only_a_fresh_install(self):
        code = _code(_read(_ROOT, 'install.sh'))
        fresh = code.index('FRESH=1')
        assert fresh < code.index('mkdir -p "${CONF_DIR}"'), \
            'fresh must be decided before install.sh creates the directories'
        assert re.search(r'if \[ "\$\{FRESH\}" = 1 \] && \[ "\$\{SS_RUN_AS_ROOT:-0\}" != 1 \]; '
                         r'then\n\s+sh /usr/sbin/servicesentry-user enable', code)
        assert not re.search(r'^\s*(sh\s+)?\S*servicesentry-user\s+enable',
                             _code(_read(_ROOT, 'update.sh')), re.M), \
            'update.sh must never switch the user'

    def test_ebuild_switches_only_a_fresh_install(self):
        text = _read(_GENTOO, 'servicesentry.ebuild.in')
        post = re.search(r'^pkg_postinst\(\) \{\n(.*?)^\}', text, re.M | re.S).group(1)
        assert re.search(r'if \[\[ -z \$\{REPLACING_VERSIONS\} \]\]; then\n\s+sh '
                         r'/usr/sbin/servicesentry-user enable', post)
        assert 'acct-user/servicesentry' in text and 'acct-group/servicesentry' in text
        install = re.search(r'^src_install\(\) \{\n(.*?)^\}', text, re.M | re.S).group(1)
        assert not re.search(r'^\s*keepdir /var/lib/ServiSesentry', install, re.M), \
            'a directory in the image would carry root:root into every merge'
        assert 'newsbin packaging/scripts/servicesentry-user.sh servicesentry-user' in install

    def test_overlay_ships_the_account_packages(self, tmp_path):
        if not shutil.which('b2sum') or not shutil.which('sha512sum'):
            pytest.skip('needs b2sum and sha512sum')
        archive = tmp_path / 'src.tar.gz'
        archive.write_bytes(b'x' * 100)
        out = tmp_path / 'overlay'
        r = subprocess.run([_bash(), os.path.join(_GENTOO, 'overlay.sh').replace(os.sep, '/'),
                            '1.2.3', out.as_posix(), archive.as_posix()],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        user = (out / 'acct-user' / 'servicesentry' / 'servicesentry-0.ebuild').read_text()
        group = (out / 'acct-group' / 'servicesentry' / 'servicesentry-0.ebuild').read_text()
        assert 'inherit acct-user' in user and re.search(r'^ACCT_USER_ID=-1$', user, re.M)
        assert 'inherit acct-group' in group and re.search(r'^ACCT_GROUP_ID=-1$', group, re.M)
        # The eclass would chown a home dir on every merge — and the data dir's owner is
        # what the OpenRC scripts run the daemon as.
        assert not re.search(r'^ACCT_USER_HOME=', user, re.M)

    @pytest.mark.parametrize('svc', _UNITS)
    def test_openrc_runs_as_the_data_owner_with_the_capabilities(self, svc):
        text = _read(_ROOT, 'init', 'openrc', 'init.d', svc)
        assert ': "${SS_USER:=$(stat -c %U /var/lib/ServiSesentry 2>/dev/null)}"' in text
        assert re.search(r'^\s+command_user="\$\{SS_USER\}"$', text, re.M)
        assert 'capabilities="^cap_net_raw,^cap_net_bind_service"' in text
        assert 'checkpath -f -m 0640 -o "${command_user}" "${SS_LOG}"' in text

    def test_packages_ship_the_tool_and_the_logrotate_rule(self):
        nfpm = _read(_ROOT, 'packaging', 'nfpm.yaml')
        assert re.search(r'src: \./scripts/servicesentry-user\.sh\n\s+dst: /usr/sbin/servicesentry-user\n'
                         r'\s+file_info:\n\s+mode: 0755', nfpm)
        assert re.search(r'src: \.\./init/logrotate/servicesentry\n\s+dst: /etc/logrotate\.d/servicesentry\n'
                         r'\s+type: config\|noreplace', nfpm)
        ebuild = _read(_GENTOO, 'servicesentry.ebuild.in')
        assert 'newins init/logrotate/servicesentry servicesentry' in ebuild
        for script in ('install.sh', 'update.sh'):
            assert 'init/logrotate/servicesentry /etc/logrotate.d/servicesentry' in \
                _code(_read(_ROOT, script))

    def test_logrotate_covers_both_openrc_logs(self):
        rule = _read(_ROOT, 'init', 'logrotate', 'servicesentry')
        assert '/var/log/ServiSesentry.log /var/log/ServiSesentry-web.log {' in rule
        for opt in ('copytruncate', 'missingok', 'notifempty', 'compress'):
            assert re.search(rf'^\s+{opt}$', rule, re.M), opt


# ── CI: only a push publishes a Release ──────────────────────────────────────────
class TestReleaseGate:

    def test_release_needs_a_push(self):
        text = _read(_WF, 'docker.yml')
        m = re.search(r'^  release:\n(.*?)(?=^  [\w-]+:\n|\Z)', text, re.M | re.S)
        assert m
        cond = re.search(r'^    if: (.*)$', m.group(1), re.M).group(1)
        assert "github.event_name == 'push'" in cond, \
            'a workflow_dispatch on a v* tag ref has the same github.ref'
        assert "startsWith(github.ref, 'refs/tags/v')" in cond
        assert 'workflow_dispatch:' in text and 'tags: ["v*", "test", "build"]' in text


# ── Helm: one owner for the shared var claim ─────────────────────────────────────
class TestHelmVarOwnership:

    def _render(self, *extra):
        helm = shutil.which('helm')
        if not helm:
            pytest.skip('helm not installed')
        out = subprocess.run(
            [helm, 'template', 't', _HELM, '--set', 'auth.password=x',
             '--set', 'database.password=y', '--set', 'database.host=db', *extra],
            capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr
        docs = out.stdout.split('\n---\n')
        return {re.search(r'^  name: (\S+)$', d, re.M).group(1): d
                for d in docs if 'kind: Deployment' in d}

    def test_root_roles_share_the_group_with_persistence(self):
        deps = self._render('--set', 'persistence.enabled=true')
        for role in ('worker', 'syslog'):
            d = deps[f't-servicesentry-{role}']
            assert '- name: var-owner' in d and 'chown -R 1000:1000 /var/lib/ServiSesentry' in d
            assert re.search(r'^\s+runAsGroup: 1000$', d, re.M)
            assert re.search(r'^\s+fsGroup: 1000$', d, re.M)
            assert 'umask 0002 && exec /entrypoint.sh' in d
        assert 'add: ["NET_RAW"]' in deps['t-servicesentry-worker']
        assert 'var-owner' not in deps['t-servicesentry-web']

    def test_nothing_changes_without_persistence(self):
        deps = self._render()
        for role in ('worker', 'syslog'):
            d = deps[f't-servicesentry-{role}']
            assert 'var-owner' not in d and 'umask' not in d and 'runAsGroup' not in d
        assert 'add: ["NET_RAW"]' in deps['t-servicesentry-worker']

    def test_values_document_the_switch(self):
        values = _read(_HELM, 'values.yaml')
        block = re.search(r'^persistence:\n((?:  .*\n|\n)+?)(?=^\S)', values, re.M).group(1)
        assert re.search(r'^  fixOwnership: true$', block, re.M)


# ── Docs ─────────────────────────────────────────────────────────────────────────
class TestDocs:

    def test_kubernetes_doc_covers_persistence(self):
        doc = _read(_ROOT, 'docs', 'caso-kubernetes.md')
        for key in ('persistence.enabled', 'persistence.existingClaim',
                    'persistence.storageClass', 'persistence.accessModes',
                    'persistence.size', 'persistence.fixOwnership',
                    'helm.sh/resource-policy: keep', 'all_squash,anonuid=1000,anongid=1000'):
            assert key in doc, key

    def test_deployment_doc_covers_the_new_pieces(self):
        doc = _read(_ROOT, 'docs', 'caso-despliegue.md')
        for key in ('SS_LOG', 'logrotate', 'packaging/gentoo/overlay.sh',
                    'servicesentry-user enable', 'make-venv.sh', 'SS_RUN_AS_ROOT',
                    'REPLACING_VERSIONS', '## Usuario dedicado'):
            assert key in doc, key
        assert 'aparato' not in doc
