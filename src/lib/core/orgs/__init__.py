#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Companies, and what belongs to each — a fact about the installation, not about one screen.

The registry is three columns and the interesting half is the other one: **ownership is said at
whatever level somebody knows it and inherited downwards, innermost wins**, over scopes that
belong to whoever declares them. A rack is one scope; a host is another; a mailbox in Microsoft
365 and a subscription in Azure are two more, and none of them is this package's business beyond
knowing that they exist.

It was born inside the physical inventory because that is where the question was first asked —
whose is this cabinet, and who may see what is in it. That was an accident of chronology: the
same company that pays for the rack has users in the directory, licences in Microsoft 365 and a
bill from a cloud provider, and a registry that lives inside one section is a registry the other
sections cannot use without naming it.

What lives here:

* :mod:`.store` — the two tables (``org`` and ``org_owner``) and what is written to them;
* :mod:`.owners` — the rules, which know nothing about databases: resolve, may-see, all-of-them;
* :mod:`.scopes` — the registry of what CAN be owned, declared by whoever owns it;
* :mod:`.routes` — the API, and :mod:`.manifest` the permissions, the tables and the section.
"""
