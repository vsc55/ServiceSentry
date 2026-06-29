#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Syslog persistence (distinta de ``lib.syslog``, el receptor):

* ``messages`` — :class:`SyslogStore`       (mensajes recibidos; retención por antigüedad/filas)
* ``drops``    — :class:`SyslogDropsStore`  (orígenes descartados por la allowlist)

Importa desde aquí: ``from lib.stores.syslog import SyslogStore, SyslogDropsStore``.
"""

from .drops import SyslogDropsStore
from .messages import SyslogStore

__all__ = ['SyslogStore', 'SyslogDropsStore']
