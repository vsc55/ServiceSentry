#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-rules manager mixin — re-exported from the Flask-independent
:mod:`lib.event_manager` so both the WebAdmin and the standalone syslog service
(which must import without Flask) can mix it in.
"""

from lib.event_manager import _EventsMixin

__all__ = ['_EventsMixin']
