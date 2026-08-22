#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SNMP — the protocol, not the check.

SNMP arrived as a watchful because the first thing anybody wanted from it was a check: read
an OID, compare the answer. It stopped being one a long time ago. A MIB library, a symbol
browser, a compiler, a resolver, a catalogue of device profiles and a sampler that turns one
of them into a chart are not "a check with options" — they are how the panel speaks a
protocol, in the same sense that :mod:`lib.core.hosts` is how it reaches a machine.

The consequence is the one that matters: **what a device IS belongs to the device**. A host
carries its SNMP profile the way it carries its SSH connection — an address, a port, an
identity — and every check bound to it inherits that instead of restating it. A module
cannot own that, because it is not about any one module.

What lives here (arriving in steps — this package is being assembled, not designed twice):

* ``profiles`` — what a device profile IS: metrics, their kind, their scale, how a table's
  rows are named. Plus the shipped catalogue in ``profiles/`` and the rules for groups.
* ``metrics``  — counter maths. A counter is a running total and a chart wants a rate, and
  the difference between them is wrap-around, resets and elapsed time.

What stays a watchful (``watchfuls/snmp``): the *check* — one OID, an operator, a value an
admin expects — including a check against a bare address that was never registered as a
host. Asking one question of an IP should not require declaring a device first.

Kept light on purpose, like every other core domain's ``__init__``: no submodule imports
here, and nothing that reaches for Flask. Discovery imports core packages very early.
"""
