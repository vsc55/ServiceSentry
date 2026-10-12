#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The sixth batch of the 2026-10-12 audit's identity defects in the panel, pinned in `node`.

Editing a token's permissions read `res.data.ok` on what `apiPut` returned — the BODY, not
`{status, data}` — so every save said "Save error", successful or not. And a password change
or reset, which leaves the account's API tokens working on purpose, now says how many there
are and offers to revoke them in the panel's own modal.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')

_PROBE = r"""
__out = {};
const avisos = [];
showToast = (m, k) => { avisos.push([String(m), k || '']); };
setTimeout = () => 0;
ssBtnBusy = () => () => {};
_accTokenReadPerms = () => ['dashboard_view'];
let cerrados = 0;
hideInfoModal = () => { cerrados++; };
renderAllTokens = () => {};
_accTokensLoad = () => {};

__wait = (async () => {
    // UI-2: a save the server accepted is taken as one, on both screens.
    apiPut = async () => ({ok: true, record: {}});
    await _atkSave('u1');
    await _accTokenSave('u2');
    __out.guardado = [cerrados, avisos.map(a => a[1])];

    // …and one it refused shows ITS error, not the generic one.
    avisos.length = 0; cerrados = 0;
    apiPut = async () => ({error: 'nope'});
    await _atkSave('u1');
    await _accTokenSave('u2');
    __out.rechazado = [cerrados, avisos.map(a => a[0])];

    // IDN-5: the offer after a password change — the in-app modal, then the revoke-all route.
    let pend = null, pregunta = '';
    showConfirmModal = (m, fn) => { pregunta = String(m); pend = fn(); };
    const borradas = [];
    apiDelete = async (u) => { borradas.push(u); return {status: 200, data: {ok: true, revoked: 3}}; };
    avisos.length = 0;
    _offerRevokeTokens(3, '/api/v1/account/tokens');
    await pend;
    __out.oferta = [/3/.test(pregunta), borradas.slice(), avisos.length];
    pend = null; borradas.length = 0;
    _offerRevokeTokens(0, '/api/v1/account/tokens');
    __out.nada = [pend, borradas.length];
    __out.cableado = [/_offerRevokeTokens\(/.test(String(saveAccountPreferences)),
                      /_offerRevokeTokens\(/.test(String(resetUserPassword))];
})();
"""


def _make_wa():
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    return wa


@pytest.fixture(scope='module')
def out():
    if shutil.which('node') is None:
        pytest.skip('no node: nothing to run the script with')
    c = _make_wa().app.test_client()
    _login(c)
    return node_run(panel_bundle(c), _PROBE)


class TestTokenPermissionEdit:

    def test_an_accepted_save_closes_the_modal_and_says_so(self, out):
        assert out['guardado'] == [2, ['success', 'success']]

    def test_a_refused_save_shows_the_servers_error(self, out):
        assert out['rechazado'] == [0, ['nope', 'nope']]


class TestPasswordChangeOffersToRevokeTokens:

    def test_the_offer_asks_in_app_and_calls_revoke_all(self, out):
        assert out['oferta'] == [True, ['/api/v1/account/tokens'], 1]

    def test_no_tokens_no_offer(self, out):
        assert out['nada'] == [None, 0]

    def test_both_password_screens_make_the_offer(self, out):
        assert out['cableado'] == [True, True]
