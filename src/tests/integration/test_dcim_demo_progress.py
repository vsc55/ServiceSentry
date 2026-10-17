#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Installing, updating and removing the demo is a job that says what it is doing.

Asked for: «installing the demo only shows a toast when it starts and another when it ends; a
dialog should say what it is doing at each moment». The demo reports each step as it goes
(`demo.Progress`), the panel runs it as a background job (`jobs.start_demo`, the catalogue
import's mechanism) and Maintenance follows it in a dialog. And the demo can be joined by other
parts (`demo.register_part`) without editing it, inside the same step reporting and failure
handling.

What is checked: the job starts and its steps come in order, ending done at 100 % with its
result; a second start while one runs is refused with the running one's id; a part that fails
reports its step and the demo is removed; a registered part is installed with its context and
its progress, and removed; and, in `node`, the dialog's body, the status line with the update
button, and a second click reopening the dialog instead of starting another.
"""

from __future__ import annotations

import shutil

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle, wait_job          # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


@pytest.fixture()
def parts():
    """The registry as it was, back after the test: a dummy part must not leak."""
    from lib.core.dcim import demo                                  # noqa: PLC0415
    antes = list(demo.DEMO_PARTS)
    yield demo
    demo.DEMO_PARTS[:] = antes


class TestTheJob:

    def test_the_steps_come_in_order_and_it_ends_done(self, admin, client):
        from lib.core.dcim import demo                              # noqa: PLC0415
        _login(client)
        r = client.post('/api/v1/dcim/demo', json={})
        assert r.status_code == 202
        job_id = r.get_json()['job']
        # While it runs the status says so, and a second start is refused with ITS id.
        segundo = client.post('/api/v1/dcim/demo', json={'replace': True})
        assert segundo.status_code == 409 and segundo.get_json()['job'] == job_id
        assert client.delete('/api/v1/dcim/demo').get_json()['job'] == job_id
        assert client.get('/api/v1/dcim/demo').get_json()['job']['id'] == job_id
        fin = wait_job(client, job_id)
        assert fin['done'] and not fin['error'] and fin['percent'] == 100
        claves = [x['key'] for x in fin['log']]
        esperado = list(demo.BUILD_STEPS) + [k for p in demo.DEMO_PARTS for k in p.steps] + ['done']
        assert claves == esperado
        assert all(x['elapsed'] is not None for x in fin['log'])
        modelos = next(x for x in fin['log'] if x['key'] == 'models')
        assert modelos['done'] == modelos['total'] == len(__import__(
            'lib.core.dcim.demo_faces', fromlist=['x']).every())
        assert fin['result']['counts']['racks'] == 45
        assert fin['result']['version'] == demo.DEMO_VERSION
        # Removing: its own steps, and the result says how many sites went.
        fin = wait_job(client, client.delete('/api/v1/dcim/demo').get_json()['job'])
        assert [x['key'] for x in fin['log']] == list(demo.REMOVE_STEPS) + ['done']
        assert fin['result']['removed'] == 6 and fin['action'] == 'remove'

    def test_the_job_runner_itself_runs_one_at_a_time(self):
        """Not only the route: two callers racing past it still get one job."""
        import threading                                            # noqa: PLC0415
        from lib.core.dcim import jobs                              # noqa: PLC0415
        suelta, corridas = threading.Event(), []

        def run(report):
            corridas.append(1)
            report({'step_key': 'a', 'step': 'A', 'step_no': 1, 'steps_total': 1,
                    'percent': 50})
            suelta.wait(10)
            return {'ok': 1}

        uno, err = jobs.start_demo('install', run)
        dos, err2 = jobs.start_demo('install', run)
        assert not err and err2 == 'dcim_demo_busy' and dos == uno
        suelta.set()
        import time                                                 # noqa: PLC0415
        for _ in range(200):
            if jobs.job_status(uno)['done']:
                break
            time.sleep(0.02)
        fin = jobs.job_status(uno)
        assert corridas == [1] and fin['result'] == {'ok': 1} and fin['percent'] == 100
        assert fin['log'] == [{'key': 'a', 'text': 'A', 'done': None, 'total': None,
                               'elapsed': fin['log'][0]['elapsed']}]

    def test_the_jobs_screen_lists_it_with_its_steps(self, admin, client):
        from lib.core.dcim import jobs                              # noqa: PLC0415
        _login(client)
        job_id = client.post('/api/v1/dcim/demo', json={}).get_json()['job']
        wait_job(client, job_id)
        fila = next(j for j in jobs.live(admin) if j['id'] == job_id)
        assert fila['kind'] == 'dcim_demo' and fila['state'] == 'done' and fila['done'] == 100
        assert fila['steps'] and all(s['state'] == 'ok' for s in fila['steps'])
        wait_job(client, client.delete('/api/v1/dcim/demo').get_json()['job'])

    def test_a_failing_step_is_reported_and_what_was_made_is_removed(self, admin, client,
                                                                     parts):
        demo = parts

        def revienta(ctx, progress):
            progress('boom', 1, 3)
            raise RuntimeError('the probe feed is down')

        demo.register_part('roto', revienta, lambda ctx, progress: None, steps=('boom',))
        _login(client)
        fin = wait_job(client, client.post('/api/v1/dcim/demo', json={}).get_json()['job'])
        assert fin['done'] and fin['error'] == 'the probe feed is down'
        assert fin['error_step'] == 'boom' and fin['error_step_text'] == 'boom'
        assert fin['log'][-1]['key'] == 'boom' and fin['log'][-1]['done'] == 1
        store = admin._dcim_store
        assert not demo.find(store) and not store.racks.list() and not store.parts.list()
        from lib.core.dcim.catalog import CatalogStore              # noqa: PLC0415
        assert not CatalogStore(store._db).list('source = ?', (demo.SOURCE,))
        assert not demo.state(store)['installed']


class TestOtherPartsJoinIt:

    def test_a_part_is_installed_with_its_context_and_removed(self, admin, parts):
        demo = parts
        visto = {}

        def instala(ctx, progress):
            visto['ctx'] = ctx
            progress('dummy', 0, 2)
            progress('dummy', 2, 2)

        def quita(ctx, progress):
            visto['quitado'] = dict(ctx.created)
            progress('dummy')

        demo.register_part('prueba', instala, quita, steps=('dummy',))
        demo.register_part('prueba', instala, quita, steps=('dummy',))   # replaced, not twice
        assert [p.name for p in demo.DEMO_PARTS].count('prueba') == 1
        pasos = []
        store = admin._dcim_store
        demo.build(store, var_dir=admin._var_dir, lang='en_EN', actor='t', app=admin,
                   progress=lambda ev: pasos.append((ev['step_key'], ev['done'])))
        ctx = visto['ctx']
        assert ctx.store is store and ctx.app is admin and ctx.actor == 't'
        assert ctx.lang == 'en_EN' and ctx.words['step_done'] == 'Done'
        assert set(ctx.created['sites']) == set(demo.UID_KEYS)
        assert ctx.created['items']['CORE-1'] and ctx.created['racks']['A01']
        assert ctx.created['models']['server'] and ctx.created['orgs']['operator']
        assert ('dummy', 2) in pasos and pasos[-1][0] == 'done'
        assert pasos.index(('dummy', 0)) > max(i for i, p in enumerate(pasos)
                                              if p[0] == 'states')
        demo.remove(store, var_dir=admin._var_dir, app=admin)
        assert set(visto['quitado']['sites'].values()) and not demo.find(store)


_PROBE = r"""
__out = {};
const modales = [], envios = [], preguntas = [];
const tallas = [];
showHtmlModal = (titulo, html, v, a, talla) => { modales.push(html); tallas.push(talla); };
showConfirmModal = (texto, si) => { preguntas.push(texto); return si(); };
showToast = () => {};
_dcimSend = (m, u, b) => { envios.push([m, u]); return Promise.resolve({ok: true, data: {job: 'j1'}}); };
let estado = {installed: true, installed_version: 1, version: 2, outdated: true,
              installed_at: '2026-10-01T08:00:00Z', job: null};
apiGet = (u) => Promise.resolve(u.indexOf('/jobs/') >= 0
    ? {job: {id: 'j1', action: 'install', done: false, percent: 40, step: 'Cableando', step_no: 9,
             steps_total: 13, count: 3, total: 10,
             log: [{key: 'models', text: 'Modelos', done: 58, total: 58, elapsed: 1.5},
                   {key: 'cabling', text: 'Cableando', done: 3, total: 10, elapsed: null}]}}
    : estado);
setTimeout = () => 0;
const caja = {innerHTML: ''};
__wait = (async () => {
    await _dcimDemoStatus(caja);
    __out.estado = caja.innerHTML;
    const c0 = __out.corriendo = _dcimDemoJobHtml({action: 'install', done: false, percent: 40,
        step: 'Cableando', step_no: 9, steps_total: 13, count: 3, total: 10,
        log: [{key: 'models', text: 'Modelos', done: 58, total: 58, elapsed: 1.5},
              {key: 'cabling', text: 'Cableando', done: 3, total: 10, elapsed: null}]});
    __out.fallo = _dcimDemoJobHtml({action: 'update', done: true, percent: 61, error: 'disco lleno',
        error_step: 'cabling', error_step_text: 'Cableando',
        log: [{key: 'cabling', text: 'Cableando', done: 3, total: 10, elapsed: 2}]});
    // With a job running, «Install» reopens its dialog: no question, nothing sent.
    estado = {installed: false, version: 2, job: {id: 'j9', done: false, step: 'x', percent: 5}};
    await _dcimDemoInstall();
    __out.reabre = {modales: modales.length, preguntas: preguntas.length, envios: envios.length,
                    seguido: _dcDemoJob && _dcDemoJob.id};
    // A fixed-size dialog (no maximise, no resize) whose log has a fixed height of its own.
    __out.talla = {size: tallas[0], logBox: /<ul id="dcDemoLog" class="[^"]*ss-log-box/.test(c0)};
    // The log follows the newest step, unless the reader scrolled up to read one.
    const log = {scrollHeight: 900, clientHeight: 256, scrollTop: 644};
    const docReal = document.getElementById;
    document.getElementById = (id) => (id === 'dcDemoLog' ? log : null);
    const alFinal = _dcimDemoAtEnd();
    log.scrollHeight = 1100; _dcimDemoFollow(alFinal);
    const siguio = log.scrollTop === 1100;
    log.scrollTop = 100;
    const leyendo = _dcimDemoAtEnd();
    log.scrollHeight = 1300; _dcimDemoFollow(leyendo);
    __out.sigue = {atEnd: alFinal, followed: siguio, reading: leyendo, kept: log.scrollTop === 100};
    document.getElementById = docReal;
})();
"""


@pytest.mark.skipif(shutil.which('node') is None, reason='no node to run the script with')
def test_the_dialog_and_the_status_line_in_node(client):
    _login(client)
    out = node_run(panel_bundle(client), _PROBE)
    e = out['estado']
    assert '1' in e and '2026-10-01' in e and '_dcimDemoUpdate()' in e and 'btn-warning' in e
    c = out['corriendo']
    assert 'width:40%' in c and '9' in c and '13' in c and 'Cableando' in c and '(3/10)' in c
    assert '(58/58)' in c and '1.5 s' in c and 'bi-hourglass-split' in c
    f = out['fallo']
    assert 'bg-danger' in f and 'Cableando' in f and 'disco lleno' in f and 'bi-x-circle' in f
    assert out['reabre'] == {'modales': 1, 'preguntas': 0, 'envios': 0, 'seguido': 'j9'}
    # Fixed size, not maximisable; and the log scrolls with the steps unless one is being read.
    assert out['talla'] == {'size': 'fit', 'logBox': True}
    assert out['sigue'] == {'atEnd': True, 'followed': True, 'reading': False, 'kept': True}
