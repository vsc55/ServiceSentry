#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo says which version of its content it is, and the panel which one is installed.

Asked for: knowing whether the installed demo is the latest. `demo.DEMO_VERSION` numbers the
content; an install records it with its date and author (`dc_demo`), removing clears it, and the
status —route and command line— says what is installed, what this code would install and
whether there is a newer one, so Maintenance can offer to update it.

The guard: a fingerprint of the demo's content —its models' data, pictures, texts, templates,
platforms, and how many of each thing a build writes— is pinned next to the version. Changing
the content without bumping the version fails here with «bump DEMO_VERSION».
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from types import SimpleNamespace

import pytest

from tests.conftest import _login                                   # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')

#: DEMO_VERSION → the fingerprint of the content it names. When the content changes, bump
#: `demo.DEMO_VERSION` and add its line here (the failure prints the new fingerprint).
_PINNED = {
    2: '2d0f51d4f7165a8e',
    3: '0bc5a1562e7390d6',
    4: '4051313525013eb2',
    # The same content as 4: what changed is what its monitoring installs (the UPSs and PDUs
    # as devices), which the fingerprint does not read and an installed demo should get.
    5: '4051313525013eb2',
}


def _store(tmp):
    from lib.core.dcim.store import DcimStore                       # noqa: PLC0415
    from lib.db import get_connector                                # noqa: PLC0415
    return DcimStore(get_connector(None, default_sqlite_path=os.path.join(tmp, 'data.db')))


def fingerprint() -> str:
    """The demo's content, hashed: the data of its models of every tree, the pictures on disk,
    the texts in each language, its templates and platforms, and the counts of what a build
    writes (sites, rooms, racks, items, cables, parts…), which is where a change to the layout
    code shows."""
    from lib.core.dcim import demo, demo_faces                      # noqa: PLC0415
    h = hashlib.sha256()
    for parte in (demo_faces.MODELS, demo_faces.RACKS, demo_faces.MODULES,
                  demo_faces.COMPONENTS, demo_faces.SPECS, demo.BUILDS, demo.PLATFORMS,
                  sorted(demo._RACK_MODELS.items()), demo.REAL_PLATFORMS):  # noqa: SLF001
        h.update(json.dumps(parte, sort_keys=True, default=list).encode('utf-8'))
    for nombre in sorted(os.listdir(demo_faces.FACES_DIR)):
        with open(os.path.join(demo_faces.FACES_DIR, nombre), 'rb') as fh:
            h.update(nombre.encode('utf-8') + fh.read())
    for lang in ('es_ES', 'en_EN'):
        h.update(json.dumps(demo.texts(lang), sort_keys=True).encode('utf-8'))
    tmp = tempfile.mkdtemp(prefix='ss-demo-fp-')
    made = demo.build(_store(tmp), var_dir=tmp, lang='es_ES')
    h.update(json.dumps({k: v for k, v in made.items() if k not in demo.UID_KEYS},
                        sort_keys=True).encode('utf-8'))
    return h.hexdigest()[:16]


class TestTheVersionMovesWithTheContent:

    def test_the_content_is_the_one_its_version_names(self):
        from lib.core.dcim import demo                              # noqa: PLC0415
        fp = fingerprint()
        assert demo.DEMO_VERSION in _PINNED and _PINNED[demo.DEMO_VERSION] == fp, (
            'The demo content changed (fingerprint %s). Bump DEMO_VERSION in '
            'lib/core/dcim/demo.py and pin {%d: %r} in this test.'
            % (fp, demo.DEMO_VERSION + (demo.DEMO_VERSION in _PINNED
                                        and _PINNED[demo.DEMO_VERSION] != fp), fp))

    def test_versions_only_go_up(self):
        from lib.core.dcim import demo                              # noqa: PLC0415
        assert demo.DEMO_VERSION == max(_PINNED) and demo.DEMO_VERSION >= 2


class TestTheInstalledVersion:

    def test_status_before_after_and_removed(self, tmp_path):
        from lib.core.dcim import demo                              # noqa: PLC0415
        store = _store(str(tmp_path))
        antes = demo.state(store)
        assert antes == {'installed': False, 'sites': [], 'version': demo.DEMO_VERSION,
                         'installed_version': None, 'installed_at': None,
                         'installed_by': None, 'outdated': False}
        demo.build(store, actor='ana', var_dir=str(tmp_path), lang='en_EN')
        e = demo.state(store)
        assert e['installed'] and e['installed_version'] == demo.DEMO_VERSION
        assert e['installed_by'] == 'ana' and e['installed_at'][:2] == '20'
        assert not e['outdated']
        demo.remove(store, var_dir=str(tmp_path))
        assert demo.state(store) == antes
        assert not store._db.fetchall('SELECT uid FROM dc_demo')        # noqa: SLF001

    def test_an_older_one_is_offered_and_the_update_records_the_new(self, tmp_path):
        from lib.core.dcim import demo                              # noqa: PLC0415
        store = _store(str(tmp_path))
        demo.build(store, var_dir=str(tmp_path))
        store._db.execute('UPDATE dc_demo SET version = ?', (demo.DEMO_VERSION - 1,))  # noqa
        store._db.commit()                                          # noqa: SLF001
        e = demo.state(store)
        assert e['outdated'] and e['installed_version'] == demo.DEMO_VERSION - 1
        demo.build(store, var_dir=str(tmp_path), replace=True, actor='upd')
        e = demo.state(store)
        assert not e['outdated'] and e['installed_version'] == demo.DEMO_VERSION
        assert e['installed_by'] == 'upd'
        assert len(store._db.fetchall('SELECT uid FROM dc_demo')) == 1  # noqa: SLF001

    def test_a_demo_from_before_versions_is_older_than_any(self, tmp_path):
        from lib.core.dcim import demo                              # noqa: PLC0415
        store = _store(str(tmp_path))
        demo.build(store, var_dir=str(tmp_path))
        store._db.execute('DELETE FROM dc_demo')                    # noqa: SLF001
        store._db.commit()                                          # noqa: SLF001
        e = demo.state(store)
        assert e['installed'] and e['installed_version'] == 0 and e['outdated']

    def test_the_command_line_says_it(self, tmp_path, capsys):
        from lib.cli import commands                                # noqa: PLC0415
        d = str(tmp_path)

        def run(**kw):
            args = SimpleNamespace(cmd='dcim', sub='demo', replace=False, remove=False,
                                   status=False, no_images=True, quiet=False)
            for k, v in kw.items():
                setattr(args, k, v)
            return commands.run(args, d, d)

        from lib.core.dcim import demo                              # noqa: PLC0415
        assert run(status=True) == 0
        assert 'no demo installed (this code installs version %d)' % demo.DEMO_VERSION \
            in capsys.readouterr().out
        assert run() == 0
        salida = capsys.readouterr().out
        assert '[1/' in salida and any(demo.texts(l)['step_models'] in salida
                                       for l in ('es_ES', 'en_EN'))
        assert run(status=True) == 0
        assert 'demo installed: version %d' % demo.DEMO_VERSION in capsys.readouterr().out


class TestTheRouteSaysIt:

    def test_the_status_route_and_the_update_offered(self, admin, client):
        from lib.core.dcim import demo                              # noqa: PLC0415
        from tests.helpers import wait_job                          # noqa: PLC0415
        _login(client)
        e = client.get('/api/v1/dcim/demo').get_json()
        assert e['version'] == demo.DEMO_VERSION and not e['installed'] and e['job'] is None
        job = client.post('/api/v1/dcim/demo', json={}).get_json()['job']
        assert wait_job(client, job)['error'] == ''
        e = client.get('/api/v1/dcim/demo').get_json()
        assert e['installed_version'] == demo.DEMO_VERSION and not e['outdated']
        store = admin._dcim_store
        store._db.execute('UPDATE dc_demo SET version = 1')         # noqa: SLF001
        store._db.commit()                                          # noqa: SLF001
        assert client.get('/api/v1/dcim/demo').get_json()['outdated']
        job = client.post('/api/v1/dcim/demo', json={'replace': True}).get_json()['job']
        fin = wait_job(client, job)
        assert fin['action'] == 'update' and fin['error'] == ''
        e = client.get('/api/v1/dcim/demo').get_json()
        assert e['installed_version'] == demo.DEMO_VERSION and not e['outdated']
        assert wait_job(client, client.delete('/api/v1/dcim/demo').get_json()['job'])['done']
        assert client.get('/api/v1/dcim/demo').get_json()['installed_version'] is None
