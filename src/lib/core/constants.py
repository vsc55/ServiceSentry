#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Foundational, layer-agnostic constants.

These live in ``lib.core`` (the foundational layer) so that core domains,
providers and the web admin can all import them in the correct direction
(everyone → ``lib.core``), instead of ``lib.core`` reaching up into
``lib.web_admin`` for them.
"""

# Reserved internal username for system-generated audit entries.
# This name MUST NOT be assigned to any real user account.
SYSTEM_USER: str = 'system'
