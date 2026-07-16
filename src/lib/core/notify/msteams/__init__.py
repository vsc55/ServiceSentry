#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Teams notification channel.

Teams is one logical notification channel with two destination kinds:

* **channels** — Incoming Webhook URLs (one per Teams channel), stored as records
  in their own table (:mod:`lib.core.notify.msteams.store`); an alert is POSTed as
  an Adaptive Card to each enabled URL.
* **users** — direct-to-user delivery configured in the ``msteams`` config section,
  with a selectable mechanism: ``activity_feed`` (Microsoft Graph
  ``sendActivityNotification`` — outbound only) or ``bot`` (Bot Framework proactive
  1:1 chat — requires a public messaging endpoint and a registered Azure Bot).

:mod:`lib.core.notify.msteams.notify` fans an alert out to both kinds.
"""
