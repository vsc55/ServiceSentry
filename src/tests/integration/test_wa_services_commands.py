#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The per-service command menu: what it offers, and that it looks like the rest of the panel.

Two separate things are pinned here, and the second is the one that bites.

**The menu entries carry an icon.** Start and Stop sit a centimetre away with one each, so a
text-only dropdown beside them reads as unfinished. The glyph is chosen per COMMAND rather
than per service, because "Reload" means the same thing wherever it appears and must not be
one icon under Monitor and another under Syslog.

**The frontend list must not claim a command the service cannot run.** Which commands a
service offers lives in a hardcoded map in the renderer, while what it actually accepts lives
in that service's ``_apply_command``. Two declarations of one fact, and they have already
drifted — syslog accepts ``clear_status`` as an alias of ``prune`` and the panel never offers
it. That direction is harmless; the other one is not: an entry the backend rejects is a menu
item that fails every time it is pressed. The check below is that direction only, deliberately.


Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_wa_services_commands.py`` lives in ``tests/unit/test_wa_services_commands.py``."""

import os

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
RENDER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'services',
                      '_render.html')


@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestFail2banActuallyRunsThem:
    """Static agreement is not enough for a service whose hook had to go somewhere new: the
    queue must reach it and the work must happen."""

    ROUTE = '/api/v1/services/ipban/command/'

    def test_prune_sweeps_the_store(self, admin, client, monkeypatch):
        _login(client)
        calls = []
        store = getattr(admin, '_ipban_store', None)
        assert store is not None, 'the jail has no store in this fixture'
        monkeypatch.setattr(store, 'prune', lambda now, **k: calls.append(now))
        r = client.post(self.ROUTE + 'prune', json={})
        assert r.status_code == 200 and r.get_json()['ok']
        assert calls, 'the command was queued but nothing swept'

    def test_reload_pushes_config_into_the_live_jail(self, admin, client, monkeypatch):
        _login(client)
        calls = []
        monkeypatch.setattr(admin, '_configure_ipban', lambda: calls.append(1))
        r = client.post(self.ROUTE + 'reload', json={})
        assert r.status_code == 200 and r.get_json()['ok']
        assert calls, 'reload did not reconfigure the jail'

    def test_an_action_it_does_not_know_is_recorded_as_failed(self, admin, client):
        """ipban has no work cycle, so `run_now` means nothing to it — and its
        `_apply_command` says so.

        Note what the HTTP answer does NOT tell you: `ok: true` here means "queued", not
        "ran". The route validates against one global set of action names, so an action a
        particular service cannot perform is accepted, dispatched, and only refused by the
        service itself — the refusal lands in the command row, out of sight. Pinned as it
        stands rather than as it should be; making the response honest needs each service to
        DECLARE its commands, which is the same change that would stop the panel hardcoding
        the menu."""
        _login(client)
        r = client.post(self.ROUTE + 'run_now', json={})
        assert r.status_code == 200
        cmd_id = r.get_json().get('command_id')
        store = getattr(admin, '_service_commands_store', None)
        assert store is not None and cmd_id
        row = next((c for c in store.list_recent('ipban')
                    if str(c.get('id')) == str(cmd_id)), None)
        assert row is not None, 'the command was not recorded'
        assert row.get('ok') is False, 'a command the service cannot run was marked successful'
        assert 'unknown_action' in str(row.get('result', ''))

    def test_it_needs_the_control_permission(self, client):
        """It reconfigures the jail that keeps attackers out."""
        assert client.post(self.ROUTE + 'prune', json={}).status_code in (401, 403)




