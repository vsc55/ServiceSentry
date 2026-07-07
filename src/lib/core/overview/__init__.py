#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview domain — the dashboard (see :mod:`lib.core`).

* ``routes``      — ``register(app, wa)``: the dashboard *layout* endpoints
                    (/api/v1/overview/default-layout, /reset-factory)
* ``permissions`` — ``MODULE_PERMISSIONS`` (overview_view / edit / set_default / reset_factory)

No dedicated store: the org default layout lives in ``config.overview.default_layout``
and the per-user layout on the user record.  The overview *data* snapshot
(/api/v1/modules/overview) stays in the modules domain, and the widget catalog in the
module-discovery layer.
"""
