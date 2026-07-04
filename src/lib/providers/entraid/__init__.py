#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID provider.

Two sides:

* :mod:`~lib.providers.entraid.declarations` — the ``__entraid_provision__``
  declaration model (discovery + normalisation); no network.
* :mod:`~lib.providers.entraid.graph` — the Microsoft Graph HTTP client (tokens,
  group reads, app provisioning, mail send).

The declaration helpers are re-exported here for convenience; import the Graph
client explicitly (``from lib.providers.entraid import graph``).
"""

from lib.providers.entraid.declarations import (  # noqa: F401
    GRAPH_APP_ID,
    entraid_provision_extras,
    module_entraid_provision,
    normalize_entraid_provision,
)
