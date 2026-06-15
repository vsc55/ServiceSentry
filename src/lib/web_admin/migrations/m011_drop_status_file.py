#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration 011: remove the obsolete ``status.json`` file.

The per-check working state now lives entirely in the ``check_state`` DB table
(see :mod:`lib.check_state_store`).  After the m010 re-key the file's keys are
stale, so it is simply deleted; the monitor repopulates ``check_state`` on its
next cycle.
"""

import os

ID = '011_drop_status_file'


def run(wa):
    var_dir = getattr(wa, '_var_dir', None)
    if not var_dir:
        return
    path = os.path.join(var_dir, getattr(wa, '_STATUS_FILE', 'status.json'))
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
