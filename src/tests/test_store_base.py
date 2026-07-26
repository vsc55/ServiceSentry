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

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_STORES = [
    'audit', 'credentials', 'groups', 'history', 'hosts', 'roles', 'sessions', 'users',
]


def _store_src(domain):
    return io.open(os.path.join(SRC, 'lib', 'core', domain, 'store.py'),
                   encoding='utf-8-sig').read()


class TestOneTimestampFormat:

    def test_it_is_utc_second_resolution_and_sortable(self):
        now = utc_now_iso()
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', now), now

    def test_touch_entity_uses_it(self):
        """It used to produce a different spelling of the same instant."""
        entity = {}
        touch_entity(entity, 'tester')
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', entity['updated_at'])
        assert entity['updated_by'] == 'tester'

    def test_lexicographic_order_is_chronological(self):
        """The property everything that compares these strings depends on. With the two
        old formats, '…10:00:00Z' sorted ABOVE '…10:00:00.5+00:00' — a later instant
        comparing as earlier."""
        earlier, later = '2026-07-26T10:00:00Z', '2026-07-26T10:00:01Z'
        assert earlier < later

    @pytest.mark.parametrize('domain', CORE_STORES)
    def test_no_store_spells_it_out_again(self, domain):
        assert "strftime('%Y-%m-%dT%H:%M:%SZ'" not in _store_src(domain), (
            f'{domain} defines its own timestamp format again')


class TestTheSharedBase:

    @pytest.mark.parametrize('domain', CORE_STORES)
    def test_the_store_uses_it(self, domain):
        assert 'BaseStore' in _store_src(domain)

    @pytest.mark.parametrize('domain', CORE_STORES)
    def test_it_does_not_reimplement_what_it_inherits(self, domain):
        src = _store_src(domain)
        assert 'No-op: the connector owns' not in src, f'{domain} has its own close()'
        assert not re.search(r'def count\(self\).*?\n.*?SELECT COUNT\(\*\)', src, re.S) \
            or '_TABLE' not in src, f'{domain} has both _TABLE and its own count()'

    def test_encryption_is_defined_once(self):
        """Credentials and host profiles used byte-identical helpers."""
        for domain in ('credentials', 'hosts'):
            src = _store_src(domain)
            assert 'EncryptedPayloadMixin' in src
            assert 'def _encrypt' not in src, f'{domain} kept its own copy'

    def test_close_is_a_no_op_callers_can_rely_on(self):
        BaseStore(db=None).close()      # must not raise, must not need a connector

    def test_the_mixin_passes_the_payload_through_without_a_key(self):
        """No Fernet configured (encryption off) must mean "leave it alone", never "drop
        it" — these payloads are host profiles and credentials."""
        class _S(EncryptedPayloadMixin):
            pass
        payload = {'ssh_password': 'plaintext'}
        assert _S()._encrypt(payload) == payload
        assert _S()._decrypt(payload) == payload


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
