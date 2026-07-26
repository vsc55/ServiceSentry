#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What actually changed, so a save writes that and nothing else.

Roles, users and groups are held in memory, edited in place and then written back.  The
write used to be ``DELETE FROM <table>`` followed by re-inserting every row: correct while
one process owns the database, and destructive the moment two do.  Two admins on two
replicas editing *different* roles do not lose a field each — the one who saves second
deletes the other's role and puts back the table as it looked in ITS memory.  Nothing
fails, nothing is logged, and the change is simply gone.

The fix is to write the difference, and the important half of the difference is what NOT
to touch:

* a row we hold and that changed  → update it;
* a row we hold and never had     → insert it;
* a row we HAD and no longer hold → delete it: somebody deleted it here;
* a row in the table we never knew about → **leave it alone**.  We cannot tell "created by
  someone else while I was editing" from "deleted by me" without a snapshot, and only the
  snapshot says which. That last rule is the whole point of this module.

Hence the snapshot: the state as it was last read from — or written to — the database.
"""

from __future__ import annotations

import copy


def snapshot(entities: dict) -> dict:
    """A deep copy to diff the next save against.

    Deep, not shallow: these dicts hold lists (a role's permissions, a group's roles) that
    are edited in place, and a shallow copy would share them — the snapshot would change
    with the live data and every diff would report "nothing changed".
    """
    return copy.deepcopy(entities or {})


def diff_entities(before: dict, after: dict):
    """``(rows to write, uids to delete)`` between two snapshots of the same collection.

    Deletions are drawn from *before*, never from the table: a row nobody in this process
    ever saw is not this process's business.
    """
    before = before or {}
    after = after or {}
    writes = {uid: row for uid, row in after.items() if before.get(uid) != row}
    deletes = [uid for uid in before if uid not in after]
    return writes, deletes
