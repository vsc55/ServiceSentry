#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The 3D viewer: everything the panel draws in three dimensions, in one place.

``web/`` holds it, as Jinja partials the pages include by path (``core/view3d/web/…``):

* the engine — ``_viewer3d.html`` (WebGL, the camera, picking), ``_viewer3d_tools.html``
  (search, measuring, the card, the toolbar) and ``_viewer3d_real.html`` (the realistic
  painter and the walk, loaded by ``/3d`` only);
* the inventory's scenes — ``_room3d.html`` (a room), ``_site3d.html`` (a floor and the
  building), ``_look3d.html`` (colours, circuits, search, live state, the camera in the
  address), ``_select3d.html`` (highlighting what is clicked) and ``_rack3d.html`` (a rack,
  the one 3D view left inside the panel);
* the page ``/3d`` — ``explore3d.html`` and its ``_page.html``; its route is ``routes.py``.

The data comes from the inventory's API (``/api/v1/dcim/*``) under its permissions: this
package owns no table and no permission of its own.
"""
