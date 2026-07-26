#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Azure Resource Manager — endpoints, API versions and the monitor-side client.

ARM is **not** Microsoft Graph.  Same tenant, same sign-in, different audience
(``management.azure.com``) and a different consent model: reading a subscription needs an
Azure **RBAC role assignment** (Reader is enough), which an Entra *app role* does not
grant.  Getting this wrong is the classic Azure integration failure — every Graph
permission granted, every ARM call still 403.

The token itself is issued by Entra, which is why :class:`ArmApi` extends
:class:`~lib.providers.entraid.graph_api.EntraApi` rather than duplicating the transport:
Azure depends on Entra, never the other way round.
"""

from __future__ import annotations

import json

from lib.providers.entraid.graph_api import EntraApi

ARM_BASE = 'https://management.azure.com'
ARM_SCOPE = 'https://management.azure.com/.default'

# API versions, in one place rather than repeated at each call site — changing one used to
# mean hunting literals through a thousand-line module.  All verified against the REST
# reference before use, and all stable (never a preview: a preview version can be
# withdrawn, which would break monitoring with no code change on our side).
API_COMPUTE = '2024-07-01'
API_METRICS = '2023-10-01'
API_HEALTH = '2022-10-01'
API_NETWORK = '2023-09-01'
API_RESOURCES = '2021-04-01'
API_LOCATIONS = '2022-12-01'
API_BUDGETS = '2024-08-01'
API_SUBSCRIPTIONS = '2020-01-01'
API_ROLE_ASSIGNMENTS = '2022-04-01'

# The public Azure status RSS.  Unauthenticated: Azure publishes no official JSON status
# API, so consumers parse the feed.
STATUS_FEED = 'https://azurestatuscdn.azureedge.net/en-us/status/feed/'


class ArmApi(EntraApi):
    """Azure Resource Manager reads, on top of the shared Entra transport."""

    @classmethod
    def _arm_json(cls, token: str, path: str, timeout: int) -> dict:
        """An authenticated ARM GET → the decoded body."""
        return json.loads(cls._api_text(ARM_BASE, token, path, timeout) or '{}') or {}

    @classmethod
    def _arm_paged(cls, token: str, path: str, timeout: int, **kw) -> list:
        """Every page of an ARM collection.

        ARM names its continuation ``nextLink`` where Graph says ``@odata.nextLink`` — the
        only difference, so the shared pager takes the key as a parameter.
        """
        return cls._paged(token, path, timeout, next_key='nextLink', base=ARM_BASE, **kw)
