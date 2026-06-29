#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows-specific helpers (sibling of :mod:`lib.system.linux`)."""

from .ports import excluded_port_ranges, parse_excluded_ranges, port_excluded

__all__ = ['excluded_port_ranges', 'parse_excluded_ranges', 'port_excluded']
