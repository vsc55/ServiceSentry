#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The 2D plan editor: what any plan where things are placed does the same way.

``web/_plan2d.html`` holds it, as a Jinja partial the pages include by path
(``core/plan2d/web/_plan2d.html``): choosing one or several things (Shift/Ctrl + click, a box,
the pointer mode), moving them together while their edges snap to what is beside them,
groups, a second press for what is underneath and «send to back», the keys, and saving several
things as one undo step.

It names no kind of thing. Each screen registers an adapter (``p2dMake(name, ad)``) that says
what is on it, where each thing is and how it moves, how it is saved and what turning or
removing it means. The inventory's room plan and floor plan are its two screens today
(``partials/dcim/_plan2d_room.html`` and ``_plan2d_floor.html``).

**What can be put on a plan is its catalogue** (``kinds.py``): the base objects any plan of a
building may hold, each screen's own (``register_screen``), and the ones somebody creates from
a screen (``plan2d_kind``, ``store.py``), served by ``routes.py`` (``/api/v1/plan2d/<screen>/kinds``).

It has no permission of its own: each screen names with which of its permissions its catalogue
is read and managed. Where a placed thing is stored is the screen's too — the engine and the
catalogue only say what it is, where it is and how it looks.
"""
