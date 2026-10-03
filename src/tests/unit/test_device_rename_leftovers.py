#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the rename of the host domain to the device domain reached and should not have.

Commit 8e0bc89 renamed `host` to `device` wherever the word meant the panel's registry
entry. Some of the places it reached meant something else — a third party's attribute, a
network address, a name already written inside somebody's database — and each of those broke
with the suite green. These pin down the ones that are code (the screen's are in
`tests/meta/test_device_rename_templates.py`).
"""

class TestFlaskRequestStillHasAHost:
    """`request.host` is Flask's, and it carries what the browser asked for. Renamed to
    `request.device` it raised on every request: SAML could not build its request, and with
    `force_fqdn` on, the panel answered 500 to every page — the settings page included."""

    def test_saml_reads_the_request_host(self):
        from lib.providers.saml.auth import _prepare_flask_request

        class _Req:
            url = 'https://panel.example.org/sso/acs'
            scheme = 'https'
            host = 'panel.example.org'
            path = '/sso/acs'
            args = {}
            form = {}

        assert _prepare_flask_request(_Req())['http_host'] == 'panel.example.org'

    def test_no_python_reads_request_device(self):
        import os
        import re
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        bad = []
        for base, dirs, files in os.walk(os.path.join(src, 'lib')):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in files:
                if f.endswith('.py'):
                    p = os.path.join(base, f)
                    with open(p, encoding='utf-8') as fh:
                        if re.search(r'\b(request|req)\.device\b', fh.read()):
                            bad.append(os.path.relpath(p, src))
        assert not bad, bad


class TestTheSshHostIsAHost:

    def test_raid_mdstat_takes_host(self):
        from lib.system.linux.raid_mdstat import RaidMdstat
        assert RaidMdstat(host='srv1', user='root').is_remote
