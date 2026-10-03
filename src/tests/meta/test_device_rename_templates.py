#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Both ends of each conversation between the screen and the server use the same name.

Commit 8e0bc89 renamed `host` to `device` in the JavaScript, and in ten places the other end
had not moved: a query parameter, a field the server returns, the placeholder in every
discovery label, a CSS class half renamed. None of them raised — a filter that is dropped shows
everything, a field that is missing shows a dash — so nothing failed until somebody looked.

The rule: the panel's own entity is `device` on both ends. `host` stays only where it is the
network word — Flask's `request.host`, the address a check connects to, the sender of a syslog
message, the machine that holds a lease.
"""

import os

import pytest

from tests.helpers import _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
P = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials')


def _src(*parts):
    return _read(os.path.join(*parts))


@pytest.mark.parametrize('path, must, must_not', [
    # The syslog route filters a device's messages by `?device=`.
    ((P, 'infra', '_tabs.html'), "/api/v1/syslog?limit=1&device=", "/api/v1/syslog?limit=1&host="),
    ((P, 'servers', '_monitoring.html'), "new URLSearchParams({ device: st.addr",
     "new URLSearchParams({ host: st.addr"),
    ((SRC, 'lib', 'services', 'syslog', 'routes.py'), "request.args.get('device'",
     "request.args.get('host'"),
    # One class on both ends, or picking a credential profile hides nothing.
    ((P, 'servers', '_checks.html'), 'class="credprof-device"', "credprof-host"),
    # Every module's `__discovery_label_template__` says `{device}`.
    ((P, 'modules', '_discovery.html'), "const base = { device: device || ''",
     "const base = { host: "),
    # Proxmox's item field is `host` — the address its API is reached at.
    ((P, 'module_action', '_modal.html'), "if (device) init.host = device;",
     "init.device = device"),
    # An event rule's legacy filter is `host`: the sender of the syslog message.
    ((P, 'events', '_render.html'), "if (r.host) bits.push('host=' + r.host);", "r.device"),
    ((P, 'events', '_modal.html'), "severity_max: '', host: ''", "severity_max: '', device: ''"),
    # What the server returns is `host`: a lease holder's machine, the HTTP Host, an address.
    ((P, 'jobs', '_timers.html'), "r.host || r.holder", "r.device"),
    ((P, 'diagnostics', '_render.html'), "n.host || '—'", "n.device"),
    ((SRC, 'lib', 'providers', 'freshservice', 'web', '_ui.html'), "d.host || ''", "d.device"),
    ((SRC, 'lib', 'core', 'snmp', 'web', 'profiles_ui.html'), "d.sysname || d.host",
     "d.sysname || d.device"),
])
def test_the_screen_uses_the_name_the_other_side_uses(path, must, must_not):
    text = _src(*path)
    assert must in text, f'{os.path.join(*path[1:])}: expected {must!r}'
    assert must_not not in text, f'{os.path.join(*path[1:])}: still has {must_not!r}'


def test_every_discovery_label_says_device():
    """The placeholder is `{device}`, in the modules and in both renderers; `{host}` would print
    itself into the label of every discovered row."""
    import glob
    import json
    for path in glob.glob(os.path.join(SRC, 'watchfuls', '*', 'schema.json')):
        text = _read(path)
        assert '{host}' not in text, path
        json.loads(text)
    svc = _read(os.path.join(SRC, 'lib', 'core', 'devices', 'service.py'))
    assert "base = {'device': device_name or ''," in svc and "'host': device_name" not in svc
