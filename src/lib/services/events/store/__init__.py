#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-notification persistence (one package for the whole subsystem), one store
class per table plus the :class:`EventStateStore` facade over the worker-state pair:

* ``rules``     — :class:`EventRulesStore`      (tabla ``event_rules``)
* ``cooldowns`` — :class:`CooldownsStore`       (tabla ``event_cooldowns``)
* ``cursor``    — :class:`CursorStore`          (tabla ``event_cursor``)
* ``state``     — :class:`EventStateStore`      (fachada: cooldowns + cursor = estado del worker)
* ``log``       — :class:`NotificationLogStore` (tabla del log de envíos)

Importa desde aquí: ``from lib.services.events.store import EventRulesStore, EventStateStore, NotificationLogStore``.
"""

from .cooldowns import CooldownsStore
from .cursor import CursorStore
from .log import NotificationLogStore
from .rules import EventRulesStore
from .state import EventStateStore

__all__ = [
    'EventRulesStore', 'EventStateStore', 'NotificationLogStore',
    'CooldownsStore', 'CursorStore',
]
