#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The part every store does the same way is written once.

Each domain owns its own store — columns, joins, JSON payloads, how a row becomes a dict —
and none of that is shared.  What was shared and copied anyway was the small stuff around
the edges: nine identical ``close()``, seven identical ``count()``, three identical
audit-column backfills, seven copies of "what time is it, in the format this project
stores", and one byte-identical pair of encrypt/decrypt helpers.

The line count is not the point.  Each of those is a **decision** — "closing is a no-op
because the connector owns the connection lifecycle" — and a decision written nine times is
a decision nobody can change.

Two of these tests exist because of real failures rather than tidiness:

* the freshness probe was given the *raw* table name for a table whose name is a reserved
  word, which on MySQL 8 does not raise: it makes the probe answer "no idea", and a probe
  that cannot answer never reloads anything;
* two timestamp formats coexisted (``…Z`` in the stores, ``…+00:00`` from ``touch_entity``)
  and for the same second the second sorts *below* the first, so ordering by the stored
  string stopped being ordering by time exactly when two writers met.
"""

import io
import os
import re

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from lib.db.store_base import BaseStore, EncryptedPayloadMixin
from lib.util.entity_audit import touch_entity, utc_now_iso

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
CORE_STORES = [
    'audit', 'credentials', 'groups', 'history', 'hosts', 'roles', 'sessions', 'users',
]


def _store_src(domain):
    return io.open(os.path.join(SRC, 'lib', 'core', domain, 'store.py'),
                   encoding='utf-8-sig').read()






@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestTheProbeUsesTheRightIdentifier:

    def test_a_reserved_table_name_is_quoted(self, admin):
        """`groups` is reserved on MySQL 8. Unquoted, the probe does not raise — it returns
        None, the caller reads "no answer" and never reloads. This is the assertion that
        would have caught it: the probe must go through the same identifier the rest of the
        store's SQL uses."""
        store = admin._groups_store
        assert store._sql_table == store._db.quote_ident('groups')
        assert store.stamp() is not None

    def test_the_logical_name_stays_unquoted(self, admin):
        """The counter row is keyed by the plain name — quoting it there would create a
        second, never-bumped row under a different key."""
        assert admin._groups_store._TABLE == 'groups'
