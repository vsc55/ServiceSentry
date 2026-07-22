#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event subsystem (Flask-free, decoupled rule evaluation):

* ``manager`` — :class:`_EventsMixin`: rule matching, cooldown and the cursor-based
  worker; shared by the WebAdmin and the standalone services.
* ``service`` — :class:`EventService`: runs the worker as its own process/container.

Import the concrete symbols from their modules (``lib.services.events.manager`` /
``lib.services.events.service``) so importing one piece does not pull in the other.
"""
