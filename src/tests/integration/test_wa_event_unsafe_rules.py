#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A rule stored before unsafe regexes were refused is never evaluated — and it says so.

Saving now refuses a pattern with nested repetitions (`(a+)+`), and the worker never runs one
it finds stored. A rule like that looked active in the list and never fired: the list now marks
it, the rules API names the patterns, and the worker logs it when it loads the rules.
"""

from __future__ import annotations

import shutil
import uuid

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')

_BAD = '^(a+)+$'


def _stored(admin, name, pattern):
    """Straight into the store, as a rule saved before the check existed."""
    rid = str(uuid.uuid4())
    admin._event_rules_store.upsert({
        'id': rid, 'name': name, 'enabled': True, 'source': 'syslog', 'channels': ['telegram'],
        'events': [], 'match_groups': [[{'type': 'regex', 'field': 'message', 'text': pattern}]]})
    return rid


def test_the_api_names_the_unsafe_patterns(admin, client):
    _login(client)
    _stored(admin, 'old-bad', _BAD)
    _stored(admin, 'old-good', r'^disk \d+ failed$')
    rules = {r['name']: r for r in client.get('/api/v1/event/rules').get_json()['rules']}
    assert rules['old-bad']['unsafe_regex'] == [_BAD]
    assert rules['old-good']['unsafe_regex'] == []


def test_loading_the_rules_logs_the_mute_one(admin):
    _stored(admin, 'old-bad', _BAD)
    ev = admin._embedded_services['events']
    dichos = []
    ev._dbg = lambda msg, *a, **k: dichos.append(str(msg))
    ev._events_reload()
    assert any('old-bad' in m and 'NOT evaluated' in m for m in dichos), dichos


_PROBE = r"""
__out = {};
__out.bad = _evrCell({name: 'old-bad', unsafe_regex: ['^(a+)+$']}, 'name');
__out.good = _evrCell({name: 'old-good', unsafe_regex: []}, 'name');
__out.badge = t('event_rule_unsafe_badge');
"""


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_the_list_marks_the_rule(client):
    _login(client)
    out = node_run(panel_bundle(client), _PROBE)
    assert out['badge'] in out['bad'] and '^(a+)+$' in out['bad']
    assert out['badge'] not in out['good']
