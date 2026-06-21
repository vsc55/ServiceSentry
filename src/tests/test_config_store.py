#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ConfigStore — the DB-backed editable configuration layer."""

from lib.db import get_connector
from lib.stores.config import ConfigStore


def _store():
    db = get_connector(None, default_sqlite_path=':memory:')
    return ConfigStore(db), db


class TestConfigStore:

    def test_is_empty(self):
        s, _ = _store()
        assert s.is_empty() is True
        s.set('global|log_level', 'info')
        assert s.is_empty() is False

    def test_type_preservation_roundtrip(self):
        s, _ = _store()
        values = {
            'global|log_level': 'info',           # str
            'modules|threads': 5,                  # int
            'web_admin|dark_mode': True,           # bool
            'notifications|matrix': {'a': True},   # dict
            'web_admin|page_sizes': [10, 25, 50],  # list
        }
        s.set_many(values)
        assert s.load_all() == values

    def test_get_and_has(self):
        s, _ = _store()
        s.set('modules|timeout', 15)
        assert s.get('modules|timeout') == 15
        assert s.has('modules|timeout') is True
        assert s.get('modules|threads') is None
        assert s.has('modules|threads') is False

    def test_stored_null_vs_absent(self):
        s, _ = _store()
        s.set('x|y', None)               # explicitly stored null
        assert s.get('x|y') is None
        assert s.has('x|y') is True      # present despite null value
        assert s.has('x|z') is False

    def test_set_many_upsert(self):
        s, db = _store()
        s.set('modules|threads', 5)
        uid1 = db.fetchone("SELECT uid FROM config WHERE path='modules|threads'")[0]
        s.set('modules|threads', 9)       # update keeps the same row/uid
        uid2 = db.fetchone("SELECT uid FROM config WHERE path='modules|threads'")[0]
        assert uid1 == uid2
        assert s.get('modules|threads') == 9

    def test_delete(self):
        s, _ = _store()
        s.set_many({'a|b': 1, 'c|d': 2})
        s.delete('a|b')
        assert s.has('a|b') is False
        assert s.get('c|d') == 2

    def test_value_agnostic_stores_ciphertext_asis(self):
        s, db = _store()
        s.set('telegram|token', 'enc:gAAAA…')   # the store does not encrypt/decrypt
        raw = db.fetchone("SELECT value FROM config WHERE path='telegram|token'")[0]
        assert raw == '"enc:gAAAA…"'             # JSON-encoded, stored verbatim
        assert s.get('telegram|token') == 'enc:gAAAA…'

    def test_audit_columns_populated(self):
        s, db = _store()
        s.set('a|b', 1, actor='admin')
        c_at, u_at, u_by = db.fetchone(
            "SELECT created_at, updated_at, updated_by FROM config WHERE path='a|b'")
        assert c_at and u_at and u_by == 'admin'

    def test_version_increments(self):
        s, _ = _store()
        v0 = s.version()
        s.set('a|b', 1)
        assert s.version() == v0 + 1
        s.delete('a|b')
        assert s.version() == v0 + 2
