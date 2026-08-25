#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Infrastructure domain — the fleet as it IS right now, not as it is configured.

System › Infrastructure answers "what have I declared": hosts, clusters, which module
watches what, with which credential. That is a registry, it is edited, and it is where a
change is a change to the installation.

This is the other half, and it had nowhere to live: **what those machines are doing**. A
host's address, its state, the values its checks last returned, and the series behind them.
It writes no record of its own — the registry stays where it is, behind its own permissions —
so it can be handed to whoever watches the screens without handing them the installation.

The one thing it does that is not a read is ASK FOR FRESH NUMBERS: a device's checks, run now,
through the same executor the scheduler cycle uses. That is not an edit of anything, but it is
not free either, so it carries a permission of its own (``infra_collect``) instead of riding on
the one that lets you look.

Self-contained (see :mod:`lib.core`):

* ``service``     — the view-model, Flask-free (the fleet row, a host's live values)
* ``routes``      — ``register(app, wa)`` (the /api/v1/infra endpoints)
* ``manifest``    — ``MODULE_PERMISSIONS`` (``infra_view``, ``infra_collect``) + ``AUDIT_EVENTS``

**No store of its own, and that is the design.** Every fact this section shows already
belongs to somebody: the hosts registry owns the machines, the check state owns what a
check last returned, and the history store owns the series. A fourth copy would be a fourth
thing to keep in step, and the first one to drift would be the one people are watching.
"""
