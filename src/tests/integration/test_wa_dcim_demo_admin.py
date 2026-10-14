#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demonstration data from Configuration → Maintenance (`/api/v1/dcim/demo`).

Asked for: an option in Maintenance to add or delete the demo data, as `main.py dcim demo` does
from a shell. What is checked: it says whether it is there, installs it, refuses to install it
twice unless asked to rebuild it, removes only the demo, writes both to the audit log, and only
whoever holds `db_maintenance` may do any of it.

With app and session: what is checked is the routes' answer and the store behind them.
"""

from __future__ import annotations

import shutil

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
    from tests.integration.test_wa_dcim import _as                  # noqa: E402
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


class TestTheDemoFromMaintenance:

    def test_install_refuse_twice_rebuild_and_remove_only_the_demo(self, admin, client, monkeypatch):
        _login(client)
        c = client
        apuntado = []
        audit0 = admin._audit
        monkeypatch.setattr(admin, '_audit', lambda ev, **kw: (apuntado.append(ev), audit0(ev, **kw))[1])
        # Something of somebody's own, that removing the demo must not touch.
        mio = c.post('/api/v1/dcim/sites', json={'name': 'Sede propia'}).get_json()['uid']

        assert c.get('/api/v1/dcim/demo').get_json() == {'installed': False, 'sites': []}
        r = c.post('/api/v1/dcim/demo', json={})
        assert r.status_code == 200 and r.get_json()['ok'], r.get_json()
        assert r.get_json()['counts']['racks'] > 0
        estado = c.get('/api/v1/dcim/demo').get_json()
        assert estado['installed'] and len(estado['sites']) >= 1
        assert c.post('/api/v1/dcim/demo', json={}).status_code == 409, 'not twice unless asked'
        assert c.post('/api/v1/dcim/demo', json={'replace': True}).status_code == 200

        r = c.delete('/api/v1/dcim/demo')
        assert r.status_code == 200 and r.get_json()['removed'] >= 1
        assert c.get('/api/v1/dcim/demo').get_json()['installed'] is False
        assert admin._dcim_store.sites.get(mio), 'removing the demo took a site of somebody else'
        assert c.delete('/api/v1/dcim/demo').get_json()['removed'] == 0

        assert apuntado.count('dcim_demo_installed') == 2 and apuntado.count('dcim_demo_removed') == 1

    def test_only_whoever_holds_maintenance(self, admin):
        editor = _as(admin, 'ed-demo', ['dcim_view', 'dcim_edit'])
        for metodo in ('get', 'post', 'delete'):
            r = getattr(editor, metodo)('/api/v1/dcim/demo', json={})
            assert r.status_code in (302, 401, 403), (metodo, r.status_code)
        mant = _as(admin, 'mt-demo', ['db_maintenance'])
        assert mant.get('/api/v1/dcim/demo').status_code == 200


_PROBE = r"""
__out = {};
const preguntas = [], envios = [], avisos = [];
showConfirmModal = (texto, si) => { preguntas.push(texto); return si(); };
showToast = (texto, tipo) => avisos.push(tipo);
_dcimSend = (m, u, b) => { envios.push([m, u, b]); return Promise.resolve({ok: true, data: {removed: 2}}); };
apiGet = () => Promise.resolve({installed: true});
_dcimPlan = {room: {uid: 'r'}};
_dcimDemoRemove();
// What follows the send runs after a promise the harness does not wait for: checked by itself.
_dcimDemoForget();
__out.borrar = {pregunta: preguntas.length, envio: envios[0], planOlvidado: _dcimPlan === null};
"""


@pytest.mark.skipif(shutil.which('node') is None, reason='no node to run the script with')
def test_the_buttons_ask_first_and_call_the_route(client):
    """The Maintenance buttons name these functions: removing asks before anything, then
    deletes through the section's sender and forgets what the inventory had open."""
    _login(client)
    out = node_run(panel_bundle(client), _PROBE)
    b = out['borrar']
    assert b['pregunta'] == 1 and b['envio'][:2] == ['DELETE', '/api/v1/dcim/demo'] and b['planOlvidado']



def test_install_and_remove_sit_side_by_side_in_maintenance(admin, client):
    """Reported: «I don't see the option to delete the demo data». It was there, in «Data
    deletion» among eight wipes, while «Install» had a group of its own: both go together."""
    _login(client)
    cards = client.get('/api/v1/config/layout').get_json()['cards']
    acts = next(c for c in cards if (c.get('section') or c.get('id')) == 'maintenance')['actions']
    grupo = {a['id']: a.get('group_label_key') for a in acts}
    assert grupo['dcim_demo_remove'] == grupo['dcim_demo_install'] == 'cfg_actions_group_demo'
