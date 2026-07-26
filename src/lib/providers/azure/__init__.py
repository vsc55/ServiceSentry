#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Azure provider — Azure Resource Manager.

Separate from :mod:`lib.providers.entraid` because ARM is a different API surface with a
different consent model, even though the same tenant and the same sign-in reach both: an
ARM call is authorised by an Azure **RBAC role assignment**, not by an Entra app role.
Keeping them apart is what stops "we granted every Graph permission and it still 403s"
from being a mystery.

Layout, split by which process talks to Azure:

* :mod:`~lib.providers.azure.arm` — endpoints, API versions and :class:`ArmApi`, the
  **monitor**-side client (urllib, via the shared Entra transport).
* :mod:`~lib.providers.azure.rbac` — subscription listing, role assignment and the
  access probe behind the credential's permission check, for the **web**-side
  provisioning wizard (``requests``).  Everything Azure-specific about that check lives
  there: the generic Entra route only folds in the row this package hands it.

Azure depends on Entra (the token is issued there), never the other way round.
"""

from lib.providers.azure.arm import (  # noqa: F401  (re-exported)
    ARM_BASE, ARM_SCOPE, ArmApi)
