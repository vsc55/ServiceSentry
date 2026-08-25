#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MIBs — turning an OID into something a person can read.

An SNMP agent answers `1.3.6.1.4.1.2021.11.9.0` with a `7`. Nothing in that exchange says the
number is a percentage, that it is about a CPU, or what the OID is called: all of it lives in
a MIB, which is a text file somebody else wrote, usually years ago, often not quite to
standard. This package is what the panel does about that.

* ``lint``     — reading a MIB source without compiling it: what it declares, what it imports,
  what is wrong with it and on which line. Deliberately its own layer, because the compiler's
  answer to a bad file is a message that points somewhere else.
* ``resolver`` — compiling and resolving: name to OID and back, with the library on disk as
  the source of truth.
* ``catalog``  — the symbol index, persisted, so the browser and the OID picker do not
  re-parse a thousand modules to answer one question.

Core rather than the SNMP watchful because a MIB is not a check's private business: it is how
the installation understands its devices at all, and the same library answers the browser, the
profile catalogue, discovery and whatever asks next.
"""
