#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""General-purpose, stateless helpers.

Small, dependency-light utilities that carry no project state and pull in
neither Flask nor the database: byte formatting (:func:`bytes2human`) and
OS identification (:mod:`lib.util.os_detect`).  Grouped here to keep the top
of :mod:`lib` for the project's core primitives (``ObjectBase``, ``Mem`` …).
"""

from lib.util.tools import bytes2human
from lib.util import os_detect

__all__ = ['bytes2human', 'os_detect']
