#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ConfigControl facade over the check_state table (drop-in for status.json)."""

from __future__ import annotations

from lib.config import ConfigControl

from .store import CheckStateStore  # noqa: F401  (used in the type annotation)


class DbBackedStatus(ConfigControl):
    """A :class:`ConfigControl` whose ``read``/``save`` sync with the
    ``check_state`` table instead of a file — a drop-in for the monitor's
    in-memory ``self.status`` so all ``get_conf``/``set_conf`` callers are
    unchanged while ``status.json`` disappears."""

    def __init__(self, store: 'CheckStateStore', uid_resolver=None):
        super().__init__(None, {})
        self._store = store
        self._uid_resolver = uid_resolver

    def read(self, *_a, **_kw):
        self.data = self._store.as_status_dict() if self._store else {}
        return self.data

    def save(self, data=None):
        if data is not None:
            self.data = data
        if self._store is not None:
            return self._store.persist_status(
                self.data, item_uid_resolver=self._uid_resolver)
        return True
