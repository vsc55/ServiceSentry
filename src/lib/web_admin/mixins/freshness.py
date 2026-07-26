#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keeping the in-memory copies honest when this is not the only writer.

Roles, users and groups are read from the database once, at startup, and every request
answers from those dicts.  That is a single-writer assumption, and there are two ways it is
already false: the **CLI** writes users and groups against the same database, and a second
**web replica** writes all three.  The process that did not make the change keeps serving
what it loaded — including permissions that were revoked — until somebody restarts it.

Reloading on every request would fix it by re-reading and re-parsing every row to discover
that nothing changed, which is the normal case.  Instead each table is asked something
cheap (:mod:`lib.db.freshness`) and re-read only when the answer moves.

This lives in ``lib/web_admin/mixins`` rather than with a domain because it belongs to no
domain: it is the same three lines for roles, users and groups, and writing them three
times is how they drift apart.  Each domain mixin keeps its own thin
``_reload_<domain>_if_stale`` — knowing how to reload ITS data is the domain's business;
knowing when is not.
"""

from __future__ import annotations

import time


class _FreshnessMixin:
    """Re-read a cached table when another writer has touched it."""

    #: ``{key: (stamp, monotonic time of the last probe)}``
    _freshness: dict

    def _freshness_state(self) -> dict:
        if getattr(self, '_freshness', None) is None:
            self._freshness = {}
        return self._freshness

    def _reload_if_stale(self, key: str, store, loader) -> bool:
        """Reload through *loader* when *store*'s table changed.  True if it reloaded.

        MUST be called before a request handler starts, never inside one: a loader
        replaces its dict wholesale, so reloading halfway through an edit would throw away
        the change being made.

        Whether a given answer is worth applying is the loader's business, not this
        method's — ``_load_users`` refuses an empty table, because a database that answers
        "no rows" (mid-migration, or pointed at the wrong file) would otherwise leave a
        running instance with nobody able to log in.
        """
        if store is None or loader is None:
            return False
        state = self._freshness_state()
        stamp_before, checked_at = state.get(key, (None, 0.0))
        ttl = getattr(self, '_CACHE_RELOAD_SECS', 5)
        now = time.monotonic()
        if ttl and (now - checked_at) < ttl:
            return False
        stamp = store.stamp()
        state[key] = (stamp_before, now)
        # None is "no answer", not "nothing there": on an unreadable database keep what is
        # already loaded rather than reload from — or wipe against — it.
        if stamp is None or stamp == stamp_before:
            return False
        state[key] = (stamp, now)
        if stamp_before is None:
            return False        # first probe: startup already loaded it, just record
        loader()
        return True

    def _mark_fresh(self, key: str, store) -> None:
        """Record the stamp our OWN write just produced, so the next request does not
        re-read the rows we wrote — over a caller that may still be editing them."""
        if store is None:
            return
        self._freshness_state()[key] = (store.stamp(), time.monotonic())
