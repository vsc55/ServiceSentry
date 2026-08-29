#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Physical-inventory API routes: ``/api/v1/dcim/*``

    GET    /api/v1/dcim/export                take models and templates to another install
    POST   /api/v1/dcim/import                …and bring them in here
    GET    /api/v1/dcim/orgs                  every company
    POST   /api/v1/dcim/orgs                  create one
    PUT    /api/v1/dcim/orgs/<uid>            rename one
    DELETE /api/v1/dcim/orgs/<uid>            remove one
    POST   /api/v1/dcim/owner                 say whose something is (or stop saying)
    GET    /api/v1/dcim/sites                 the sites, their rooms and each room's racks
    POST   /api/v1/dcim/sites                 …and the same four verbs for
    PUT    /api/v1/dcim/sites/<uid>              rooms and racks
    DELETE /api/v1/dcim/sites/<uid>
    POST   /api/v1/dcim/rooms/<uid>/plan     upload a room's floor plan
    DELETE /api/v1/dcim/rooms/<uid>/plan     …and take it away
    GET    /api/v1/dcim/media/<path:name>    serve one stored picture
    GET    /api/v1/dcim/media-dir            which folder the pictures actually go to
    GET    /api/v1/dcim/rooms/<uid>/features what is in the room besides the racks
    POST   /api/v1/dcim/rows                 declare a row of racks
    PUT    /api/v1/dcim/rows/<uid>           …name it, or say which aisles it faces
    DELETE /api/v1/dcim/rows/<uid>           …undeclare it
    POST   /api/v1/dcim/features             put one there
    PUT    /api/v1/dcim/features/<uid>       move it, turn it, name it
    DELETE /api/v1/dcim/features/<uid>       take it away
    POST   /api/v1/dcim/rooms/<uid>/import  bring a plan back from a file
    GET    /api/v1/dcim/racks/<uid>/power   how the rack is fed, and what would go dark
    GET    /api/v1/dcim/sources               what is upstream: mains, panels, UPS
    POST   /api/v1/dcim/sources              …declare one
    PUT    /api/v1/dcim/sources/<uid>        …change it, or throw its bypass
    POST   /api/v1/dcim/sources/<uid>/clone  …copy it with everything hanging off it
    DELETE /api/v1/dcim/sources/<uid>        …undeclare it
    POST   /api/v1/dcim/pdus                 add a power strip
    PUT    /api/v1/dcim/pdus/<uid>           …change it
    DELETE /api/v1/dcim/pdus/<uid>           …take it out, with its cables
    POST   /api/v1/dcim/feeds                plug something in
    PUT    /api/v1/dcim/feeds/<uid>          …change that cable
    DELETE /api/v1/dcim/feeds/<uid>          …unplug it
    GET    /api/v1/dcim/racks/<uid>/cables  what is declared, against what the devices see
    POST   /api/v1/dcim/cables               declare a cable
    PUT    /api/v1/dcim/cables/<uid>         …change it
    DELETE /api/v1/dcim/cables/<uid>         …pull it
    POST   /api/v1/dcim/links                declare a link between two sites
    PUT    /api/v1/dcim/links/<uid>          …change it
    DELETE /api/v1/dcim/links/<uid>          …drop it
    GET    /api/v1/dcim/fits                 where does this fit, and why not where it doesn't
    GET    /api/v1/dcim/board                what is wrong and how to get to it
    GET    /api/v1/dcim/items/<uid>/parts    what is inside one device
    POST   /api/v1/dcim/parts               …put a component in it
    PUT    /api/v1/dcim/parts/<uid>         …change it
    DELETE /api/v1/dcim/parts/<uid>         …take it out
    GET    /api/v1/dcim/hosts                 the machines an item may be linked to
    GET    /api/v1/dcim/racks                 the racks of one room (?room=<uid>)
    GET    /api/v1/dcim/racks/<uid>           one rack: its items and what is free
    POST   /api/v1/dcim/items                 put something in a rack
    PUT    /api/v1/dcim/items/<uid>           move or relabel it
    DELETE /api/v1/dcim/items/<uid>           take it out
    GET    /api/v1/dcim/profiles              what gets asked of a component of each class
    PUT    /api/v1/dcim/profiles              …replace it, without shipping a release
    GET    /api/v1/dcim/profiles/history      …who changed it, and when
    GET    /api/v1/dcim/profiles/compare      …what changed between two versions
    DELETE /api/v1/dcim/profiles              …and go back to the one that ships
    GET    /api/v1/dcim/connectors            how each thing plugs in — the connector catalogue
    PUT    /api/v1/dcim/connectors            …replace it, without shipping a release
    GET    /api/v1/dcim/connectors/history    …who changed it, and when
    DELETE /api/v1/dcim/connectors            …and go back to the one that ships
    GET    /api/v1/dcim/brands                the brands — the root of the catalogue
    POST   /api/v1/dcim/brands                write one
    PUT    /api/v1/dcim/brands/<uid>          change it
    DELETE /api/v1/dcim/brands/<uid>          drop it, while nothing is theirs
    GET    /api/v1/dcim/platforms            what a machine ships with: Debian, RouterOS, ESXi
    POST   /api/v1/dcim/platforms            …add one
    PUT    /api/v1/dcim/platforms/<uid>      …rename or correct it
    DELETE /api/v1/dcim/platforms/<uid>      …retire it, if nothing points at it
    POST   /api/v1/dcim/platforms/drop       …retire several at once, keeping the ones in use
    GET    /api/v1/dcim/builds/<uid>/files    the papers of a purchase standard
    POST   /api/v1/dcim/builds/<uid>/files    …attach one
    GET    /api/v1/dcim/builds                the purchase standards: what we actually buy
    GET    /api/v1/dcim/builds/<uid>          one, with what it carries
    POST   /api/v1/dcim/builds                write one, or clone one
    PUT    /api/v1/dcim/builds/<uid>          change it
    DELETE /api/v1/dcim/builds/<uid>          retire it — the machines born of it stay
    POST   /api/v1/dcim/builds/<uid>/image/<face>  its own picture of a face
    DELETE /api/v1/dcim/builds/<uid>/image/<face>  take it off
    GET    /api/v1/dcim/builds/<uid>/history  what it said before, and who changed it
    POST   /api/v1/dcim/builds/<uid>/restore  go back to a version — as one more change
    POST   /api/v1/dcim/builds/<uid>/parts    fit a component to the template
    PUT    /api/v1/dcim/build-parts/<uid>     change one
    DELETE /api/v1/dcim/build-parts/<uid>     take it off
    GET    /api/v1/dcim/catalog/<uid>/history  what this model used to say, and who changed it
    POST   /api/v1/dcim/catalog/<uid>/restore  put a past version back
    GET    /api/v1/dcim/catalog               the model catalogue
    GET    /api/v1/dcim/catalog/suggest       what a device's own words point at
    GET    /api/v1/dcim/catalog/browse        what a GitHub library holds, first
    POST   /api/v1/dcim/catalog/upload        import a zip that came IN the request
    GET    /api/v1/dcim/schemas               what fields a model can have
    POST   /api/v1/dcim/schemas/fetch         bring the library's three
    POST   /api/v1/dcim/schemas               write one, or clone one
    DELETE /api/v1/dcim/schemas/<uid>         drop one
    POST   /api/v1/dcim/catalog               a model written by hand
    PUT    /api/v1/dcim/catalog/<uid>         correct one — the class it was guessed to be
    GET    /api/v1/dcim/catalog/<uid>/files    the manuals and datasheets of a model
    POST   /api/v1/dcim/catalog/<uid>/files    …attach one
    GET    /api/v1/dcim/files/<uid>            …download it
    DELETE /api/v1/dcim/files/<uid>            …take it off
    POST   /api/v1/dcim/catalog/<uid>/image/<face>   put a picture on one
    DELETE /api/v1/dcim/catalog/<uid>/image/<face>   take it off
    DELETE /api/v1/dcim/catalog/<uid>         drop ONE model, with its pictures
    POST   /api/v1/dcim/catalog/drop          drop the ticked ones, or a whole source
    POST   /api/v1/dcim/catalog/basics        the generics that ship with the panel
    POST   /api/v1/dcim/catalog/import        import one, in the background
    GET    /api/v1/dcim/catalog/import/<job_id>  …and watch it

**Every read narrows.** Not "the listing narrows": every one of them, because the section is
about a place and a place can hold several companies' equipment. What the caller may see is
resolved once per request (:func:`lib.core.dcim.owners.visible_orgs`) and applied to whatever is
being returned — an item that is not theirs comes back as position and size and nothing else.

**Every write checks the same thing before it writes**, and a write is checked against the
owner of the thing being *changed*, not of the thing being changed *to*: moving somebody else's
server one U is still touching somebody else's server.

**Where each route lives.** This was one 3571-line module — a third of the domain — and the split
is **by subject, not by layer**: a room's routes, the power chain's, the catalogue's and the
templates' are four different jobs, and whoever comes to touch one has no reason to walk through
the other three. Each area lists its own endpoints in its own header.

    places.py    companies, sites, rooms, racks and what stands on the floor
    power.py     mains, panels, UPSs, strips, feeds and cables
    racks.py     a cabinet inside: what takes each U, what is fitted to it, where it fits
    docs.py      the two catalogue documents: component profiles and connectors
    library.py   brands and platforms
    builds.py    the templates: what a machine is bought as
    catalog.py   the model catalogue, its import and the portable file

    _context.py  what every area shares: the permission decorators and the helpers used by
                 two or more. What only one area uses stays with it — that is half the room
                 the split buys
    _common.py   the two pure functions that need neither `app` nor `wa`
"""

from __future__ import annotations

from lib.core.dcim.routes import (builds, catalog, docs, library, places, power,
                                  racks)
from lib.core.dcim.routes._context import build as _context


def register(app, wa):
    """Registrar la sección entera. **Un solo punto de entrada**: quien la usa hace
    `from lib.core.dcim.routes import register` y no tiene por qué saber que dentro hay
    siete áreas."""
    C = _context(app, wa)
    for area in (places, power, racks, docs, library, builds, catalog):
        area.register(app, wa, C)
