#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-notification persistence (one package for the whole subsystem):

* ``rules``  — :class:`EventRulesStore`        (tabla ``event_rules``)
* ``state``  — :class:`EventStateStore`        (tablas ``event_cooldowns`` + ``event_cursor``: estado del worker)
* ``log``    — :class:`NotificationLogStore`   (tabla del log de envíos)

Importa desde aquí: ``from lib.stores.event import EventRulesStore, EventStateStore, NotificationLogStore``.
"""

from .log import NotificationLogStore
from .rules import EventRulesStore
from .state import EventStateStore

__all__ = ['EventRulesStore', 'EventStateStore', 'NotificationLogStore']
