#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discovery of feature declarations from watchful module schemas.

Catalogs built by scanning each module's ``schema.json``: credential types
(``__credential__``) and Overview widgets (``__overview_widget__``).  Kept apart
from the module framework itself (module_base / dict_return_check).
"""
