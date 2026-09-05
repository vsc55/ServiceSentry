#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where the equipment physically IS, and whose it is.

The rest of the panel knows what a device is and how to reach it. This package knows the two
things a registry of addresses cannot answer: **where do I walk to** when something breaks, and
**who does this belong to** when the answer has to be billed or hidden.

Those are two questions and they are deliberately not one tree:

* **Containment** is physical and strictly nested — a site holds rooms, a room holds racks, a
  rack holds items. Every one of those is somewhere, and it is somewhere in exactly one place.
* **Ownership** is an attribute, said at whatever level somebody knows it and inherited
  downwards. A holding's IT department shares a datacenter, a room and a rack between the
  group's companies: in one cabinet there are 2U of one, 4U of another and a switch of the
  department's own that serves them all. Hanging the datacenter off a company makes that case
  impossible, and it is the normal case as soon as there is more than one company.

The other decision that shapes everything is that **a rack holds ITEMS, and some items are
hosts** — never the reverse. A patch panel takes 1U and is not a host; a blanking plate takes 1U
and is nothing; a blade chassis takes 7U and contains eight things that are; a switched-off
server still occupies its U whether or not anything monitors it. So `hosts` is not touched: the
registry stays the source of truth for what exists and how to reach it, this package says where
it sits, and either side survives the other being deleted.

See ``docs/explica-dcim.md`` for the model, the phases, and what is deliberately not built.
"""
