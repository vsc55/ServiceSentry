#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""External provider integrations (identity/cloud APIs, e.g. Microsoft Entra ID).

Kept in a low layer so both ``lib.modules`` and ``lib.web_admin`` can use them
without a circular import; provider modules depend only on the standard library
(plus ``requests`` for the ones that talk to a remote API).
"""
