#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID provider.

Layout:

* :mod:`~lib.providers.entraid.declarations` — the ``__entraid_provision__``
  declaration model (discovery + normalisation); no network.
* The Microsoft Graph HTTP surface, split by concern:
  :mod:`~lib.providers.entraid.client` (endpoints/ids, no HTTP),
  :mod:`~lib.providers.entraid.auth` (app-only + device-code tokens),
  :mod:`~lib.providers.entraid.directory` (group reads),
  :mod:`~lib.providers.entraid.mail` (``sendMail``),
  :mod:`~lib.providers.entraid.teams` (activity feed + Bot Framework),
  :mod:`~lib.providers.entraid.provisioning` (app-registration).

The declaration helpers are re-exported here for convenience; import the specific
Graph submodule explicitly (e.g. ``from lib.providers.entraid import auth``).
"""

from lib.providers.entraid.declarations import (  # noqa: F401
    GRAPH_APP_ID,
    entraid_provision_extras,
    module_entraid_provision,
    normalize_entraid_provision,
)
