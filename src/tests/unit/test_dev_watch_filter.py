#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dev_watch's change filter (2026-10-12 audit, E16).

`data` was skipped wherever it appeared in a path, meant for the runtime data dir — and it
also swallowed lib/core/dcim/data, the DCIM catalogues, which are source: editing one did
not restart the dev server. It is now skipped only at the top of src/.

dev_watch loads .env.dev into os.environ when imported; the test loads it with a stub
`dotenv` so the test process's environment is left alone.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest

pytest.importorskip('watchfiles')
from watchfiles import Change  # noqa: E402

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


@pytest.fixture(scope='module')
def flt():
    stub = types.ModuleType('dotenv')
    stub.load_dotenv = lambda *a, **k: None
    saved = sys.modules.get('dotenv')
    sys.modules['dotenv'] = stub
    try:
        spec = importlib.util.spec_from_file_location(
            '_dev_watch_under_test', os.path.join(_SRC, 'dev_watch.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            sys.modules.pop('dotenv', None)
        else:
            sys.modules['dotenv'] = saved
    return mod._SourceFilter()


def _p(*parts):
    return os.path.join(_SRC, *parts)


@pytest.mark.parametrize('path', [
    ('lib', 'core', 'dcim', 'data', 'basics.json'),
    ('lib', 'core', 'dcim', 'store.py'),
    ('watchfuls', 'ping', 'schema.json'),
    ('main.py',),
])
def test_source_restarts(flt, path):
    assert flt(Change.modified, _p(*path))


@pytest.mark.parametrize('path', [
    ('data', 'config.json'),
    ('lib', '__pycache__', 'x.py'),
    ('watchfuls', 'ping', 'tests', 'test_ping.py'),
    ('.venv', 'Lib', 'site.py'),
    ('lib', 'web_admin', 'static', 'web_admin.css'),
])
def test_runtime_and_noise_do_not(flt, path):
    assert not flt(Change.modified, _p(*path))
