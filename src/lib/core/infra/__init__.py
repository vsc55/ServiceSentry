#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Infrastructure domain — the fleet as it IS right now, not as it is configured.

System › Infrastructure answers "what have I declared": hosts, clusters, which module
watches what, with which credential. That is a registry, it is edited, and it is where a
change is a change to the installation.

This is the other half, and it had nowhere to live: **what those machines are doing**. A
host's address, its state, the values its checks last returned, and the series behind them.
Read-only by construction — there is no write route here — so it can be handed to whoever
watches the screens without handing them the registry as well.

Self-contained (see :mod:`lib.core`):

* ``service``     — the view-model, Flask-free (the fleet row, a host's live values)
* ``routes``      — ``register(app, wa)`` (the /api/v1/infra endpoints)
* ``manifest``    — ``MODULE_PERMISSIONS`` (``infra_view``)

**No store of its own, and that is the design.** Every fact this section shows already
belongs to somebody: the hosts registry owns the machines, the check state owns what a
check last returned, and the history store owns the series. A fourth copy would be a fourth
thing to keep in step, and the first one to drift would be the one people are watching.
"""
