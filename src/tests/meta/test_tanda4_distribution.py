#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution defects found by the 2026-10-12 audit (E4, E5, E6, E8, E9, E15).

- E4  Helm: the var dir (backups, pictures, MIBs, SNMP profiles) was always an emptyDir.
      `persistence.enabled` now mounts one claim on every pod; off by default, with a
      warning in NOTES, so an upgrade changes nothing.
- E5  Gentoo: the overlay tarball had no profiles/repo_name, no metadata/layout.conf and
      no Manifest, so Portage would not take it. packaging/gentoo/overlay.sh writes all
      three — run here for real under bash against a local archive.
- E6  Gentoo: pkg_postrm tested REPLACING_VERSIONS, which is never set in a postrm, so an
      upgrade deleted the venv; and the conf.d interpreter was sed'd in /etc after install,
      so every upgrade queued a ._cfg file that put the system Python back.
- E8  CI: packages-install had an implicit success(), which a skipped `tests` (the `build`
      tag) fails — the packages were built but never installed.
- E9  Init: output was block-buffered under systemd, and OpenRC sent it to /dev/null.
- E15 CI: a manual dispatch pushed images although docker.yml says it only builds.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess

import pytest

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_ROOT = os.path.dirname(_SRC)
_HELM = os.path.join(_ROOT, 'helm', 'servicesentry')
_GENTOO = os.path.join(_ROOT, 'packaging', 'gentoo')
_WF = os.path.join(_ROOT, '.github', 'workflows')


def _read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as fh:
        return fh.read()


def _job(workflow: str, name: str) -> str:
    """The text of one job of a workflow: from `  name:` to the next top-level job."""
    text = _read(_WF, workflow)
    m = re.search(rf'^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:\n|\Z)', text, re.M | re.S)
    assert m, f'job {name} not found in {workflow}'
    return m.group(1)


# ── E4: Helm var dir ─────────────────────────────────────────────────────────────
class TestHelmPersistence:

    def test_values_default_off(self):
        text = _read(_HELM, 'values.yaml')
        m = re.search(r'^persistence:\n((?:  .*\n)+)', text, re.M)
        assert m, 'values.yaml needs a persistence block'
        block = m.group(1)
        assert re.search(r'^  enabled: false\b', block, re.M), \
            'persistence must default to off: an upgrade must not start asking for a PVC'
        assert 'existingClaim' in block and 'ReadWriteMany' in block

    def test_var_volume_switches_to_the_claim(self):
        text = _read(_HELM, 'templates', '_helpers.tpl')
        vol = text[text.index('define "servicesentry.volumes"'):]
        vol = vol[:vol.index('{{- end -}}\n\n')]
        assert 'persistentVolumeClaim' in vol and '.Values.persistence.enabled' in vol
        assert 'emptyDir' in vol, 'the default must stay an emptyDir'

    def test_pvc_template_is_kept_on_uninstall(self):
        text = _read(_HELM, 'templates', 'pvc.yaml')
        assert 'kind: PersistentVolumeClaim' in text
        assert 'not .Values.persistence.existingClaim' in text
        assert 'helm.sh/resource-policy: keep' in text

    def test_notes_warn_when_off(self):
        text = _read(_HELM, 'templates', 'NOTES.txt')
        assert 'if not .Values.persistence.enabled' in text and 'emptyDir' in text

    def test_helm_renders_the_claim(self):
        helm = shutil.which('helm')
        if not helm:
            pytest.skip('helm not installed')
        out = subprocess.run(
            [helm, 'template', 't', _HELM, '--set', 'auth.password=x',
             '--set', 'database.password=y', '--set', 'database.host=db',
             # The key and the token are not what is under test (see test_tanda6_distribution).
             '--set', 'generateSecrets=true',
             '--set', 'persistence.enabled=true'], capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr
        assert 'kind: PersistentVolumeClaim' in out.stdout
        assert out.stdout.count('claimName: t-servicesentry-var') >= 3


# ── E5: Gentoo overlay ───────────────────────────────────────────────────────────
class TestGentooOverlay:

    def _build(self, tmp_path, version='1.2.3'):
        bash = shutil.which('bash')
        if not bash or not shutil.which('b2sum') or not shutil.which('sha512sum'):
            pytest.skip('needs bash, b2sum and sha512sum')
        archive = tmp_path / 'src.tar.gz'
        archive.write_bytes(b'not really a tarball, only hashed\n' * 50)
        out = tmp_path / 'overlay'
        r = subprocess.run([bash, os.path.join(_GENTOO, 'overlay.sh').replace(os.sep, '/'),
                            version, out.as_posix(), archive.as_posix()],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return out, archive.read_bytes()

    def test_overlay_is_a_repository(self, tmp_path):
        out, _ = self._build(tmp_path)
        assert (out / 'profiles' / 'repo_name').read_text().strip() == 'servicesentry'
        layout = (out / 'metadata' / 'layout.conf').read_text()
        assert re.search(r'^masters = gentoo$', layout, re.M)
        assert re.search(r'^thin-manifests = true$', layout, re.M)
        pkg = out / 'app-admin' / 'servicesentry'
        assert (pkg / 'servicesentry-1.2.3.ebuild').is_file()
        assert (pkg / 'metadata.xml').is_file()

    def test_manifest_hashes_the_distfile(self, tmp_path):
        out, data = self._build(tmp_path)
        line = (out / 'app-admin' / 'servicesentry' / 'Manifest').read_text().strip()
        assert line == (f'DIST servicesentry-1.2.3.tar.gz {len(data)} '
                        f'BLAKE2B {hashlib.blake2b(data).hexdigest()} '
                        f'SHA512 {hashlib.sha512(data).hexdigest()}')

    def test_distfile_name_matches_the_ebuild(self):
        # The Manifest names ${P}.tar.gz; the ebuild must fetch it under that name.
        assert '-> ${P}.tar.gz' in _read(_GENTOO, 'servicesentry.ebuild.in')

    def test_build_sh_uses_it(self):
        assert re.search(r'^bash "\$\{ROOT\}/packaging/gentoo/overlay\.sh"',
                         _read(_ROOT, 'packaging', 'build.sh'), re.M)


# ── E6: Gentoo upgrade ───────────────────────────────────────────────────────────
class TestGentooUpgrade:

    def _fn(self, name):
        text = _read(_GENTOO, 'servicesentry.ebuild.in')
        m = re.search(rf'^{name}\(\) \{{\n(.*?)^\}}', text, re.M | re.S)
        assert m, name
        return m.group(1)

    def test_postrm_keeps_the_venv_on_an_upgrade(self):
        body = self._fn('pkg_postrm')
        assert 'REPLACED_BY_VERSION' in body
        assert 'REPLACING_VERSIONS' not in re.sub(r'#.*', '', body), \
            'REPLACING_VERSIONS is never set in pkg_postrm'

    def test_confd_is_installed_with_the_venv_interpreter(self):
        install = self._fn('src_install')
        assert 'newconfd' in install and '/opt/ServiSesentry/venv/bin/python' in install
        assert not re.search(r'^\s*doconfd ', install, re.M)
        postinst = re.sub(r'#.*', '', self._fn('pkg_postinst'))
        assert '/etc/conf.d' not in postinst, \
            'editing conf.d after install makes every upgrade queue a ._cfg file'


# ── E8 / E15: workflows ──────────────────────────────────────────────────────────
class TestWorkflows:

    def test_packages_install_survives_a_skipped_suite(self):
        job = _job('docker.yml', 'packages-install')
        cond = re.search(r'^    if: (>-\n(?:      .*\n)+|.*\n)', job, re.M).group(1)
        assert '!cancelled()' in cond or 'always()' in cond, \
            'an implicit success() fails when the `tests` ancestor is skipped (tag build)'
        assert "needs.packages.result == 'success'" in cond

    def test_only_a_push_publishes_an_image(self):
        text = _read(_WF, 'build-image.yml')
        assert "push: ${{ github.event_name == 'push' }}" in text
        assert "github.event_name != 'pull_request'" not in re.sub(r'#.*', '', text)


# ── E9: service output ───────────────────────────────────────────────────────────
class TestServiceOutput:

    @pytest.mark.parametrize('unit', ['ServiSesentry', 'ServiSesentry-web'])
    def test_systemd_unbuffered(self, unit):
        text = _read(_ROOT, 'init', 'systemd', f'{unit}.service')
        assert re.search(r'^Environment=PYTHONUNBUFFERED=1$', text, re.M)

    @pytest.mark.parametrize('svc', ['ServiSesentry', 'ServiSesentry-web'])
    def test_openrc_keeps_the_output(self, svc):
        text = _read(_ROOT, 'init', 'openrc', 'init.d', svc)
        assert re.search(r'^\s*output_log=', text, re.M)
        assert re.search(r'^\s*error_log=', text, re.M)
        assert 'export PYTHONUNBUFFERED=1' in text
